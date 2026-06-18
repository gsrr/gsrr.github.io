#!/usr/bin/env python3
"""一次性遷移：把舊格式的 accounts.json 併成新的「單一帳號」格式。

舊格式：
  - 學生帳號：key 為 "@<user>"，個人進度快照存在 record["data"]
  - 老師帳號：key 為 "<user>"，班級資料存在 record["data"]["students"] + record["code"]
新格式（server.py 目前用）：
  - 單一 key "<user>"：{salt, hash, code, data:{students:{}}, sdata:{個人進度快照}}
    學生入口讀寫 sdata；老師入口讀寫 data.students + code。

用法：
  python migrate_accounts.py [accounts.json 路徑]   # 預設 /data/accounts.json
  python migrate_accounts.py --dry-run              # 只看會怎麼改，不寫入
  python migrate_accounts.py --no-backup            # 不另存 .bak 備份

可重複執行（idempotent）：已是新格式時不會再動。
"""
import argparse
import json
import os
import shutil
import sys
import time


def migrate(db):
    """就地把 db 從舊格式轉成新格式，回傳 (changed: bool, notes: list[str])。"""
    users = db.setdefault("users", {})
    tokens = db.setdefault("tokens", {})
    db.setdefault("codes", {})
    changed = False
    notes = []

    # 1) 舊的學生帳號 "@user" -> 併入統一帳號 "user"
    for key in [k for k in list(users.keys()) if k.startswith("@")]:
        bare = key[1:]
        srec = users.pop(key)
        changed = True
        progress = srec.get("data", {}) or {}
        if bare in users:
            # 同名已有帳號（多半是老師）：把學生進度補進 sdata，保留原帳密/班級碼
            tgt = users[bare]
            if tgt.get("sdata"):
                notes.append('! "%s"：同名帳號已有 sdata，舊學生進度未覆蓋（保留現有）' % bare)
            else:
                tgt["sdata"] = progress
                notes.append('~ "%s"：學生進度併入既有帳號的 sdata（沿用既有帳密/班級碼）' % bare)
        else:
            # 沒有同名：用學生的帳密建立統一帳號，進度放 sdata（班級碼留待首次登入產生）
            users[bare] = {
                "salt": srec.get("salt"),
                "hash": srec.get("hash"),
                "code": None,
                "data": {"students": {}},
                "sdata": progress,
            }
            notes.append('+ "%s"：由舊學生帳號建立統一帳號' % bare)
        # 指向 "@user" 的登入 token 改指向 bare，讓既有登入狀態不中斷
        for tk, val in list(tokens.items()):
            if val == key:
                tokens[tk] = bare

    # 2) 既有帳號補齊新欄位、清掉過時欄位
    for name, u in users.items():
        if not isinstance(u, dict):
            continue
        if "sdata" not in u:
            u["sdata"] = {}
            changed = True
        if "data" not in u or not isinstance(u.get("data"), dict):
            u["data"] = {"students": {}}
            changed = True
        else:
            u["data"].setdefault("students", {})
        if "code" not in u:
            u["code"] = None
            changed = True
        if u.pop("kind", None) is not None:   # 舊學生帳號的 kind:"student"
            changed = True

    return changed, notes


def main():
    ap = argparse.ArgumentParser(description="Migrate accounts.json to the unified single-account format.")
    ap.add_argument("path", nargs="?", default="/data/accounts.json", help="accounts.json 路徑（預設 /data/accounts.json）")
    ap.add_argument("--dry-run", action="store_true", help="只顯示會怎麼改，不寫入")
    ap.add_argument("--no-backup", action="store_true", help="寫入前不另存 .bak 備份")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print("找不到檔案：%s" % args.path, file=sys.stderr)
        return 1
    with open(args.path, encoding="utf-8") as f:
        db = json.load(f)

    old_at = sum(1 for k in db.get("users", {}) if k.startswith("@"))
    changed, notes = migrate(db)

    print("檔案：%s" % args.path)
    print("舊學生帳號（@ 前綴）：%d 個" % old_at)
    for n in notes:
        print("  " + n)
    print("帳號總數（遷移後）：%d" % len(db.get("users", {})))

    if not changed:
        print("已是新格式，無需變更。")
        return 0
    if args.dry_run:
        print("[dry-run] 未寫入。拿掉 --dry-run 才會實際寫檔。")
        return 0

    if not args.no_backup:
        bak = "%s.bak-%s" % (args.path, time.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(args.path, bak)   # 複製原始檔（尚未覆寫）作為備份
        print("已備份原檔 -> %s" % bak)

    tmp = args.path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False)
    os.replace(tmp, args.path)
    print("已寫入新格式：%s" % args.path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
