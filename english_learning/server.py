#!/usr/bin/env python3
"""極小後端服務（Python 標準函式庫）。
   GET  /api/count  -> {"count": N}                      訪客計數
   POST /api/visit  -> 累加並回傳 {"count": N}
   POST /api/stt?text=<目標句>  (body = 音檔位元組)       發音用：Whisper 轉文字
        -> {"transcript": "..."}（前端再跟目標句比對算分）
   計數存於 /data/visits.json（docker volume）。
   STT 用 faster-whisper（開源、免費、CPU 可跑）；缺套件/ffmpeg 時回傳錯誤、不影響計數。
"""
import json, os, threading, tempfile, subprocess, hashlib, secrets, time
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA = "/data/visits.json"
lock = threading.Lock()

# ---- Whisper（延遲載入、單一模型、推論序列化） ----
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base.en")
_model = None
_model_lock = threading.Lock()
_infer_lock = threading.Lock()


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        return _model


def transcribe(audio_bytes):
    model = get_model()
    inp = wav = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(audio_bytes)
            inp = f.name
        wav = inp + ".wav"
        subprocess.run(["ffmpeg", "-y", "-i", inp, "-ar", "16000", "-ac", "1", wav],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with _infer_lock:
            segments, _info = model.transcribe(wav, language="en", beam_size=1)
            return " ".join(s.text for s in segments).strip()
    finally:
        for p in (inp, wav):
            if p:
                try:
                    os.remove(p)
                except Exception:
                    pass


def read_count():
    try:
        with open(DATA) as f:
            return int(json.load(f).get("count", 0))
    except Exception:
        return 0


def write_count(n):
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    tmp = DATA + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"count": n}, f)
    os.replace(tmp, DATA)


# ---- 帳號 + 雲端進度（拆檔） ----
# accounts.json 只放帳密與班級碼：{"users":{user:{salt,hash,code}}, "codes":{code:user}}
# 進度各自一檔： /data/progress/<hash>.json = {"students":{…班級名冊…}, "sdata":{…個人快照…}}
# token 放記憶體、有過期時間（伺服器重啟需重新登入）。密碼 PBKDF2 雜湊。pilot 等級驗證。
ACCT = "/data/accounts.json"
PROG_DIR = "/data/progress"
acct_lock = threading.Lock()
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")          # 後台總管密碼；沒設則停用後台帳號
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")   # 內建後台帳號名稱（在登入頁用此帳號+ADMIN_KEY登入）
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # 班級碼去掉易混字 0/O/1/I/L

# --- 記憶體 token（含過期）---
TOKEN_TTL = 30 * 24 * 3600        # 30 天
_tokens = {}                      # token -> {"user":.., "exp":..}
_tok_lock = threading.Lock()


def _prune_tokens():
    now = time.time()
    for t in [t for t, r in _tokens.items() if r["exp"] < now]:
        _tokens.pop(t, None)


def issue_token(user, admin=False):
    tok = secrets.token_hex(24)
    with _tok_lock:
        _prune_tokens()
        _tokens[tok] = {"user": user, "exp": time.time() + TOKEN_TTL, "admin": admin}
    return tok


def token_user(tok):
    if not tok:
        return None
    with _tok_lock:
        rec = _tokens.get(tok)
        if not rec:
            return None
        if rec["exp"] < time.time():
            _tokens.pop(tok, None)
            return None
        return rec["user"]


# --- accounts.json（帳密 + 碼）---
def load_accounts():
    try:
        with open(ACCT) as f:
            db = json.load(f)
    except Exception:
        db = {}
    db.setdefault("users", {})
    db.setdefault("codes", {})
    return db


def save_accounts(db):
    os.makedirs(os.path.dirname(ACCT), exist_ok=True)
    tmp = ACCT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(db, f)
    os.replace(tmp, ACCT)


# --- 進度檔（每位使用者一檔，檔名用使用者名雜湊避免特殊字元）---
def _prog_path(user):
    h = hashlib.sha1(user.encode("utf-8")).hexdigest()[:20]
    return os.path.join(PROG_DIR, h + ".json")


def load_progress(user):
    try:
        with open(_prog_path(user)) as f:
            p = json.load(f)
    except Exception:
        p = {}
    p.setdefault("students", {})
    p.setdefault("sdata", {})
    return p


def save_progress(user, p):
    os.makedirs(PROG_DIR, exist_ok=True)
    path = _prog_path(user)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(p, f)
    os.replace(tmp, path)


# --- 占地盤（全站共用一檔）：{file: {owner, avatar, card:{emoji,name,atk,def,luck}}} ---
TERR_FILE = "/data/territory.json"
terr_lock = threading.Lock()


def load_territory_store():
    try:
        with open(TERR_FILE) as f:
            t = json.load(f)
            return t if isinstance(t, dict) else {}
    except Exception:
        return {}


def save_territory_store(t):
    os.makedirs(os.path.dirname(TERR_FILE), exist_ok=True)
    tmp = TERR_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(t, f)
    os.replace(tmp, TERR_FILE)


# --- 玩家經濟（每位玩家：人口 population + 兵力 troops + 上次成長時間）---
ECON_FILE = "/data/economy.json"
econ_lock = threading.Lock()
DAY_SECONDS = 86400
ECON_START_POP = 100
ECON_START_TROOPS = 100


def load_econ_store():
    try:
        with open(ECON_FILE) as f:
            e = json.load(f)
            return e if isinstance(e, dict) else {}
    except Exception:
        return {}


def save_econ_store(e):
    os.makedirs(os.path.dirname(ECON_FILE), exist_ok=True)
    tmp = ECON_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(e, f)
    os.replace(tmp, ECON_FILE)


def clampi(v, lo=0, hi=100000000):
    try:
        v = int(round(float(v)))
    except Exception:
        v = 0
    return max(lo, min(hi, v))


# 取得（或初始化）玩家經濟，並依「過了幾天」補算兵力產出（人口每天生 10% 給兵力）
def econ_get(store, user, now):
    e = store.get(user)
    if not isinstance(e, dict):
        e = {"population": ECON_START_POP, "troops": ECON_START_TROOPS, "lastGrow": now}
        store[user] = e
    pop = clampi(e.get("population", ECON_START_POP))
    troops = clampi(e.get("troops", 0))
    last = e.get("lastGrow", now)
    try:
        last = float(last)
    except Exception:
        last = now
    days = int((now - last) // DAY_SECONDS)
    if days > 0:
        troops = clampi(troops + days * int(round(pop * 0.10)))
        last = last + days * DAY_SECONDS
    e["population"], e["troops"], e["lastGrow"] = pop, troops, last
    return e


def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100000).hex()


def gen_code(db):
    codes = db.setdefault("codes", {})
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
        if code not in codes:
            return code


# 舊版 accounts.json（data/sdata/tokens 內嵌）一次性搬到拆檔結構
def migrate_accounts():
    try:
        with open(ACCT) as f:
            db = json.load(f)
    except Exception:
        return
    changed = False
    for user, u in db.get("users", {}).items():
        if "data" in u or "sdata" in u:
            p = load_progress(user)
            if isinstance(u.get("data"), dict):
                p["students"] = u["data"].get("students", {}) or p.get("students", {})
            if "sdata" in u:
                p["sdata"] = u.get("sdata") or {}
            save_progress(user, p)
            u.pop("data", None)
            u.pop("sdata", None)
            changed = True
    if "tokens" in db:        # 舊的檔案內 token 丟掉（改記憶體）
        db.pop("tokens", None)
        changed = True
    if changed:
        save_accounts(db)


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/count":
            self._send({"count": read_count()})
        elif path == "/api/dashboard":
            self._handle_dashboard()
        elif path == "/api/student/load":
            self._handle_student_load()
        elif path == "/api/admin/overview":
            self._handle_admin_overview()
        elif path == "/api/leaderboard":
            self._handle_leaderboard()
        elif path == "/api/territory":
            self._handle_territory()
        elif path == "/api/economy":
            self._handle_economy()
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/visit":
            with lock:
                n = read_count() + 1
                write_count(n)
            self._send({"count": n})
        elif path == "/api/stt":
            self._handle_stt()
        elif path == "/api/register":
            self._handle_auth(register=True)
        elif path == "/api/login":
            self._handle_auth(register=False)
        elif path == "/api/sync":
            self._handle_sync()
        elif path == "/api/class/sync":
            self._handle_class_sync()
        elif path == "/api/student/register":
            self._handle_auth(register=True)        # 單一帳號：學生/老師共用
        elif path == "/api/student/login":
            self._handle_auth(register=False)
        elif path == "/api/student/save":
            self._handle_student_save()
        elif path == "/api/territory/claim":
            self._handle_territory_claim()
        elif path == "/api/economy/set":
            self._handle_economy_set()
        else:
            self._send({"error": "not found"}, 404)

    def _handle_stt(self):
        qs = parse_qs(urlparse(self.path).query)
        target = (qs.get("text", [""]) or [""])[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._send({"error": "no audio"}, 400)
            return
        audio = self.rfile.read(length)
        try:
            text = transcribe(audio)
            self._send({"transcript": text, "target": target})
        except Exception as e:
            self._send({"error": str(e)}, 500)

    # ---- 帳號 / 雲端進度 ----
    def _body_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _token(self):
        return (parse_qs(urlparse(self.path).query).get("token", [""]) or [""])[0]

    def _handle_auth(self, register):
        d = self._body_json()
        user = (d.get("user") or "").strip()
        pw = d.get("pass") or ""
        if not user or not pw:
            self._send({"error": "Missing username or password"}, 400)
            return
        # 內建後台帳號：用 ADMIN_USER + ADMIN_KEY 登入，回傳 admin token
        if user == ADMIN_USER:
            if (not register) and ADMIN_KEY and pw == ADMIN_KEY:
                self._send({"token": issue_token(ADMIN_USER, admin=True), "user": ADMIN_USER, "admin": True})
            else:
                self._send({"error": "Wrong username or password"}, 401)
            return
        with acct_lock:
            db = load_accounts()
            u = db["users"].get(user)
            if register:
                if u:
                    self._send({"error": "User already exists"}, 409)
                    return
                salt = secrets.token_hex(16)
                u = {"salt": salt, "hash": hash_pw(pw, salt), "code": gen_code(db), "created": time.time()}
                db["users"][user] = u
                db["codes"][u["code"]] = user
            else:
                if not u or hash_pw(pw, u["salt"]) != u["hash"]:
                    self._send({"error": "Wrong username or password"}, 401)
                    return
                if not u.get("code"):              # 老帳號補一組班級碼
                    u["code"] = gen_code(db)
                    db["codes"][u["code"]] = user
            save_accounts(db)
            sdata = load_progress(user).get("sdata", {})
        token = issue_token(user)
        # data 回傳學生端快照，讓登入後可還原個人進度
        self._send({"token": token, "user": user, "code": u["code"], "data": sdata})

    # 老師自己的裝置（用 token）上傳
    def _handle_sync(self):
        d = self._body_json()
        incoming = d.get("students") or {}
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        with acct_lock:
            p = load_progress(user)
            for name, blob in incoming.items():
                p["students"][name] = blob
            save_progress(user, p)
        self._send({"ok": True})

    # 學生裝置：只用班級碼上傳（不需老師密碼）
    def _handle_class_sync(self):
        d = self._body_json()
        code = ((parse_qs(urlparse(self.path).query).get("code", [""]) or [""])[0] or d.get("code") or "").strip().upper()
        incoming = d.get("students") or {}
        with acct_lock:
            db = load_accounts()
            user = db["codes"].get(code)
            if not user:
                self._send({"error": "Invalid class code"}, 404)
                return
            p = load_progress(user)
            for name, blob in incoming.items():
                p["students"][name] = blob          # 以學生名為鍵，後寫覆蓋
            save_progress(user, p)
        self._send({"ok": True})

    def _handle_dashboard(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        with acct_lock:
            db = load_accounts()
            code = (db["users"].get(user) or {}).get("code")
            p = load_progress(user)
        self._send({"code": code, "students": p.get("students", {})})

    # ---- 學生入口：跨裝置雲端存檔，存在個人進度檔的 sdata ----
    def _handle_student_save(self):
        d = self._body_json()
        blob = d.get("data")
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        with acct_lock:
            p = load_progress(user)
            p["sdata"] = blob if isinstance(blob, dict) else {}
            save_progress(user, p)
        self._send({"ok": True})

    def _handle_student_load(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        with acct_lock:
            p = load_progress(user)
        self._send({"data": p.get("sdata", {})})

    # ---- 後台總管：看所有帳號 / 所有學生（需 ADMIN_KEY）----
    def _handle_admin_overview(self):
        tok = self._token()
        with _tok_lock:
            rec = _tokens.get(tok)
            is_admin = bool(rec and rec.get("admin") and rec["exp"] >= time.time())
        if not is_admin:
            self._send({"error": "Forbidden"}, 403)
            return
        with acct_lock:
            db = load_accounts()
            accounts = []
            for user, u in db.get("users", {}).items():
                p = load_progress(user)
                students = dict(p.get("students", {}))           # 班級名冊
                sd = (p.get("sdata") or {}).get("students") or {}  # 本人個人進度
                for n, b in sd.items():
                    students.setdefault(n, b)
                accounts.append({"user": user, "code": u.get("code"),
                                 "created": u.get("created"), "students": students})
        self._send({"accounts": accounts})

    # ---- 公開排行榜：依每個帳號 sdata.stats（前端算好的通過課數/英雄等級）----
    def _handle_leaderboard(self):
        with terr_lock:
            tstore = load_territory_store()
        regions = {}
        for f, h in tstore.items():
            if isinstance(h, dict) and h.get("owner"):
                regions[h["owner"]] = regions.get(h["owner"], 0) + 1
        with econ_lock:
            estore = load_econ_store()
        with acct_lock:
            db = load_accounts()
            out = []
            for user in db.get("users", {}):
                if user == "testaccount":
                    continue
                stats = (load_progress(user).get("sdata") or {}).get("stats") or {}
                e = estore.get(user) if isinstance(estore, dict) else None
                pop = clampi((e or {}).get("population", ECON_START_POP)) if isinstance(e, dict) else ECON_START_POP
                out.append({"name": user, "avatar": stats.get("avatar", "👦"),
                            "population": pop, "regions": regions.get(user, 0),
                            "passed": int(stats.get("passed", 0) or 0), "level": int(stats.get("level", 1) or 1)})
        out.sort(key=lambda x: (-x["population"], -x["regions"], x["name"].lower()))
        self._send({"leaders": out[:50]})

    # ---- 占地盤：每個據點由「4 兵種 + 兵力」守備（攻方 4v4 打贏才換人）----
    TROOP_TYPES = ("cav", "archer", "inf", "spear")

    def _handle_territory(self):
        with terr_lock:
            store = load_territory_store()
        holders, counts = {}, {}
        for f, h in store.items():
            if not isinstance(h, dict):
                continue
            owner = h.get("owner")
            holders[f] = {"owner": owner, "avatar": h.get("avatar", "👦"),
                          "troops": h.get("troops") or [], "pop": h.get("pop")}
            if owner:
                counts[owner] = counts.get(owner, 0) + 1
        self._send({"holders": holders, "counts": counts})

    # 攻方在前端用兵種打贏（或佔領空據點）後呼叫，存下新的守備軍（pilot：信任前端結果）
    def _handle_territory_claim(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        f = (d.get("file") or "").strip()
        troops_in = d.get("troops")
        if not f or not isinstance(troops_in, list):
            self._send({"error": "missing file/troops"}, 400)
            return
        troops = []
        for t in troops_in[:4]:
            if not isinstance(t, dict):
                continue
            ty = str(t.get("type", ""))
            if ty not in self.TROOP_TYPES:
                continue
            hp = int(t.get("hp", 0) or 0)
            troops.append({"type": ty, "hp": max(0, min(100000, hp))})
        region_pop = int(d.get("pop", 0) or 0)
        prev_owner = None
        with terr_lock:
            store = load_territory_store()
            prev = store.get(f)
            if isinstance(prev, dict):
                prev_owner = prev.get("owner")
            store[f] = {"owner": user, "avatar": str(d.get("avatar", "👦"))[:8],
                        "troops": troops, "pop": region_pop}
            save_territory_store(store)
        # 從別人手中奪下 → 前主人的人口扣掉該區人口（離線也算）
        if prev_owner and prev_owner != user and region_pop > 0:
            with econ_lock:
                es = load_econ_store()
                pe = es.get(prev_owner)
                if isinstance(pe, dict):
                    pe["population"] = clampi(clampi(pe.get("population", 0)) - region_pop)
                    save_econ_store(es)
        self._send({"ok": True})

    # 玩家經濟：GET 取得（含每日產兵）
    def _handle_economy(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        with econ_lock:
            store = load_econ_store()
            e = econ_get(store, user, time.time())
            save_econ_store(store)
            pop, troops = e["population"], e["troops"]
        self._send({"population": pop, "troops": troops, "income": int(round(pop * 0.10))})

    # 玩家經濟：POST 設定（pilot：信任前端戰果，僅夾範圍）
    def _handle_economy_set(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        with econ_lock:
            store = load_econ_store()
            e = econ_get(store, user, time.time())
            if "population" in d:
                e["population"] = clampi(d.get("population"))
            if "troops" in d:
                e["troops"] = clampi(d.get("troops"))
            save_econ_store(store)
            pop, troops = e["population"], e["troops"]
        self._send({"ok": True, "population": pop, "troops": troops})

    def log_message(self, *args):
        pass  # 安靜


if __name__ == "__main__":
    migrate_accounts()      # 舊版單檔結構 -> 拆檔（只跑一次有效果）
    ThreadingHTTPServer(("127.0.0.1", 5000), Handler).serve_forever()
