#!/usr/bin/env python3
"""極小後端服務（Python 標準函式庫）。
   GET  /api/count  -> {"count": N}                      訪客計數
   POST /api/visit  -> 累加並回傳 {"count": N}
   POST /api/stt?text=<目標句>  (body = 音檔位元組)       發音用：Whisper 轉文字
        -> {"transcript": "..."}（前端再跟目標句比對算分）
   計數存於 /data/visits.json（docker volume）。
   STT 用 faster-whisper（開源、免費、CPU 可跑）；缺套件/ffmpeg 時回傳錯誤、不影響計數。
"""
import json, os, threading, tempfile, subprocess, hashlib, secrets, time, random
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
try:                                   # 正規領地目錄(唯讀權威)：身分/人口解析
    from territory_catalog import catalog as terr_catalog
except Exception:
    terr_catalog = None
from game import (army as game_army, conquest as game_conquest, config as game_config,   # 核心遊戲領域
                  economy as game_economy, recruitment as game_recruit, technology as game_tech)
from learning import api as learning_api                                                   # 學習領域(與遊戲領域分離)

# 房間地圖(等級 id) -> 主 canonical mapId。子地圖(下鑽)改由 world-data/maps.json 的 childMaps 提供。
LEVEL_PRIMARY_MAP = {"Pre-A1": "taiwan", "A1": "china", "A2": "world", "B1": "world"}


def allowed_maps_for_level(level):
    """房間某等級允許認領的 mapId 清單 = 主地圖 + 其子地圖(childMaps)。未知等級 -> None(不限制)。"""
    prim = LEVEL_PRIMARY_MAP.get(level or "")
    if not prim:
        return None
    maps = [prim]
    if terr_catalog:
        try:
            maps += terr_catalog.child_maps(prim)
        except Exception:
            pass
    return maps


def canonize_keys(d):
    """把 territory / 學習到的 catalog 這種 {key: value} 的 key 就地正規化成 canonical 領地 id。
    舊版 legacy key('maps/world.svg#us') 可讀；解析不到的 key 保留(不丟棄)；碰撞則保留第一個。"""
    if not terr_catalog or not isinstance(d, dict):
        return d
    out, seen = {}, {}
    for k, v in d.items():
        ck = None
        try:
            ck = terr_catalog.resolve_any(k)
        except Exception:
            ck = None
        ck = ck or k                    # 解析不到 → 保留原 key（不丟棄）
        if ck in out:                   # 碰撞：兩個 legacy key 對到同一 canonical → 保留第一個
            seen[ck] = seen.get(ck, 1) + 1
            continue
        out[ck] = v
    return out

DATA = "/data/visits.json"
lock = threading.Lock()

# --- Per-room world isolation -------------------------------------------------
# Every "world" file (territory / economy / events / room config) lives under
# /data/rooms/<CODE>/ where <CODE> is a teacher's class code. A request carries
# its room in the ?room=<code> query param; background loops set it per room.
# The current room is held in a thread-local so the storage helpers below stay
# signature-compatible with all their existing call sites.
ROOMS_DIR = "/data/rooms"
DEFAULT_ROOM = "LOBBY"
_req = threading.local()


def set_room(code):
    _req.room = (code or "").upper() or DEFAULT_ROOM


def current_room():
    return getattr(_req, "room", DEFAULT_ROOM) or DEFAULT_ROOM


def room_code_safe(code):
    safe = "".join(c for c in (code or "").upper() if c.isalnum())
    return safe or DEFAULT_ROOM


def room_path(name, code=None):
    return os.path.join(ROOMS_DIR, room_code_safe(code or current_room()), name)


def list_rooms():
    try:
        out = []
        for d in os.listdir(ROOMS_DIR):
            if os.path.isfile(os.path.join(ROOMS_DIR, d, "room.json")):
                out.append(d)
        return out
    except Exception:
        return []

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


def transcribe(audio_bytes, hint=""):
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
            # 把目標句當提示 → 咬字不標準時也較容易轉出目標詞（軟性引導，非強制）
            segments, _info = model.transcribe(wav, language="en", beam_size=1,
                                               initial_prompt=(hint[:300] if hint else None))
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


# --- 玩家目前所在的房間(單一)：存在帳號上，一次只在一個房間裡活動 ---
def get_user_room(user):
    if not user:
        return ""
    return ((load_accounts()["users"].get(user) or {}).get("room") or "").upper()


def set_user_room(user, code):
    if not user:
        return
    with acct_lock:
        db = load_accounts()
        u = db["users"].get(user)
        if u is not None:
            u["room"] = (code or "").upper()
            save_accounts(db)


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
        with open(room_path("territory.json")) as f:
            t = json.load(f)
            if not isinstance(t, dict):
                return {}
            for h in t.values():                       # 把舊的中文 AI 名字就地換成英文
                if isinstance(h, dict) and h.get("owner") == AI_OWNER_LEGACY:
                    h["owner"] = AI_OWNER
            return canonize_keys(t)                     # legacy key -> canonical(下次存檔即遷移)
    except Exception:
        return {}


def save_territory_store(t):
    p = room_path("territory.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(t, f)
    os.replace(tmp, p)


# --- 玩家經濟（每位玩家：人口 population + 兵力 troops + 上次成長時間）---
ECON_FILE = "/data/economy.json"
econ_lock = threading.Lock()
GROW_SECONDS = 3600   # 金幣結算間隔：每小時
ECON_MAX_CATCHUP = 72 # 一次最多補算 72 小時，避免長時間停機後金幣暴衝
ECON_START_POP = 100
ECON_START_TROOPS = 100
TROOP_ALL = ("cav", "archer", "inf", "spear")   # 兵力池分兵種保存的順序


def _norm_troops(v):
    # 兵力池改成「分兵種」保存：{cav,archer,inf,spear}。舊資料是單一數字 → 平均拆成四種(餘數給步兵)。
    if isinstance(v, dict):
        return {k: clampi(v.get(k, 0)) for k in TROOP_ALL}
    n = clampi(v)
    per = n // 4
    d = {k: per for k in TROOP_ALL}
    d["inf"] += n - per * 4
    return d


def troops_total(t):
    return sum(clampi(v) for v in (t or {}).values()) if isinstance(t, dict) else clampi(t)


def load_econ_store():
    try:
        with open(room_path("economy.json")) as f:
            e = json.load(f)
            return e if isinstance(e, dict) else {}
    except Exception:
        return {}


def save_econ_store(e):
    p = room_path("economy.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(e, f)
    os.replace(tmp, p)


# --- 全站事件牆（所有人共見）：[{ts, user, text}]，只留最近 EVENTS_MAX 筆 ---
EVENTS_FILE = "/data/events.json"
ev_lock = threading.Lock()
EVENTS_MAX = 120


def load_events():
    try:
        with open(room_path("events.json")) as f:
            e = json.load(f)
            if not isinstance(e, list):
                return []
            for ev in e:                               # 舊事件裡的中文 AI 名字改成英文
                if isinstance(ev, dict):
                    if ev.get("user") == AI_OWNER_LEGACY:
                        ev["user"] = AI_OWNER
                    if isinstance(ev.get("text"), str) and AI_OWNER_LEGACY in ev["text"]:
                        ev["text"] = ev["text"].replace(AI_OWNER_LEGACY, AI_OWNER)
            return e
    except Exception:
        return []


def save_events(e):
    p = room_path("events.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(e, f)
    os.replace(tmp, p)


def clean_txt(s, n=40):
    # 移除角括號避免前端 innerHTML 被注入，並限制長度
    return str(s or "").replace("<", "").replace(">", "").strip()[:n]


def clampi(v, lo=0, hi=100000000):
    try:
        v = int(round(float(v)))
    except Exception:
        v = 0
    return max(lo, min(hi, v))


# 取得（或初始化）玩家經濟，並依「過了幾小時」補算「金幣」產出。
# 金幣是玩家統一資源：由(家鄉人口 + 該玩家所有領地人口)每小時各生 GOLD_RATE 匯入同一個金幣池。
# 兵力(troops)不再隨時間自動成長——只透過部署/戰鬥增減。
def econ_get(store, user, now, region_pop=0):
    e = store.get(user)
    if not isinstance(e, dict):
        rm = load_room()                       # 新玩家開局資源 = 房間設定的起始資源
        e = {"population": clampi(rm.get("startPop", ECON_START_POP)),
             "troops": _norm_troops(clampi(rm.get("startTroops", ECON_START_TROOPS))),
             "gold": clampi(rm.get("startGold", 0)), "lastGold": now}
        store[user] = e
    pop = clampi(e.get("population", ECON_START_POP))
    gold = clampi(e.get("gold", 0))
    if "lastGold" in e:
        try:
            last = float(e["lastGold"])
        except Exception:
            last = now
    else:
        last = now                                  # 舊帳號首次改用金幣制 → 從現在起算，不回溯灌金幣
    # 被動金幣結算委派給 Game Domain(game.economy)——單一權威公式，行為不變。
    gold, last = game_economy.calculate_passive_gold(gold, pop, clampi(region_pop), last, now)
    e["population"], e["gold"], e["lastGold"] = pop, gold, last
    e["troops"] = _norm_troops(e.get("troops", 0))   # 兵力池分兵種保存(舊的單一數字會自動轉)
    if not isinstance(e.get("passcnt"), dict):       # 每課通過次數(佔領解鎖用)——改由後端統一保存
        e["passcnt"] = {}
    if not isinstance(e.get("buildings"), dict):     # 家鄉基地的建築(蓋在自己的預設領地)
        e["buildings"] = {}
    if not isinstance(e.get("tech"), dict):          # 家鄉科技 → 加成你派出去的攻擊軍
        e["tech"] = {}
    e.pop("lastGrow", None)                          # 移除舊的兵力成長時間戳
    return e


# 幫某玩家的金幣池加/扣值(delta 可負，最低 0)，回傳新金幣。給戰鬥獎懲用。
def econ_add_gold(user, delta):
    if not user or delta == 0:
        return None
    with terr_lock:
        rp = user_region_pop(load_territory_store(), user)
    with econ_lock:
        store = load_econ_store()
        e = econ_get(store, user, time.time(), rp)
        e["gold"] = clampi(e.get("gold", 0) + delta)
        save_econ_store(store)
        return e["gold"]


# 某玩家名下所有領地的人口總和（給金幣收入計算用）
def user_region_pop(tstore, user):
    return sum(clampi(h.get("pop", 0)) for h in tstore.values()
              if isinstance(h, dict) and h.get("owner") == user)


# ---- 領地建設：兵工廠(armory) + 科技樹(鍛造+攻 / 鎧甲+防)，用「金幣」研發 ----
# 金幣：每塊領地依人口每小時產金，累積在該區(h["gold"])。研發即時完成、只惠及該區守軍。
GOLD_RATE = 0.10                                   # 每小時金幣 = round(pop * GOLD_RATE)
PASS_GOLD = 10000                                   # 通過一課 +10000 金幣（重賞上課）
DEFEND_GOLD = 50                                    # 防守成功 +50 金幣
# Phase 3A：後端權威地重新批改課程活動時，讀取「與前端相同」的課程 JSON(答案鍵)。容器內內容在
# /var/www/html(Dockerfile 設 CONTENT_ROOT)；本機/測試預設為 server.py 所在的專案根目錄。
CONTENT_ROOT = os.environ.get("CONTENT_ROOT") or os.path.dirname(os.path.abspath(__file__))
# Learning Domain 單一入口。獎勵「金額」在這裡由遊戲設定注入(內容包只能指名 policy，不能指定金額 §15)。
LEARNING = learning_api.LearningService(content_root=CONTENT_ROOT,
                                        reward_amounts={"PASS_GOLD": PASS_GOLD})
ATTACK_FAIL_GOLD = 50                               # 攻打失敗 −50 金幣
# 蓋建築的金幣花費：兵工廠(科技) + 三種生產建築
BUILD_COST = {"armory": 50, "barracks": 60, "archery": 80, "stable": 120}
TECH_TRACKS = ("atk", "def")                       # 鍛造(+攻) / 鎧甲(+防)
TECH_COST = {"atk": [80, 160, 280], "def": [80, 160, 280]}   # 第 1/2/3 級花費
TECH_MAX = 3
# 招募：每名兵的金幣成本、該兵種需要哪棟建築、每次招募的數量(加進該領地守軍)
UNIT_COST = {"inf": 2, "spear": 3, "archer": 4, "cav": 5}
UNIT_BUILDING = {"inf": "barracks", "spear": "barracks", "archer": "archery", "cav": "stable"}
RECRUIT_BATCH = 10
# 家鄉基地(預設領地)的特殊 key：蓋建築/研發存在玩家經濟裡；招募加進「自由兵力池」；科技加成你的攻擊軍。
HOME_KEY = "@home"


# 該領地每小時「上繳」給擁有者的金幣(= 人口 × GOLD_RATE)。領地本身不再存金幣、也不再自動長兵。
def region_gold_income(h):
    return int(round(clampi(h.get("pop", 0)) * GOLD_RATE))


# ================= 電腦 AI 帝國：伺服器背景自動擴張 / 攻擊 =================
# 一個常駐執行緒，每隔 20–30 分鐘出手一次：攻打某位玩家的領地，或佔領一塊(曾被佔過而現為無主的)領地。
# 戰鬥用「兵力 × 兵種克制」估算勝負(守方有先攻/主場加成)，兵力規模隨玩家平均駐軍成長。
AI_OWNER = "AI Empire"
AI_OWNER_LEGACY = "電腦 AI 帝國"   # 舊名：讀檔時把既有資料一併改成英文，UI 不會殘留中文
AI_AVATAR = "🤖"
AI_TICK_MIN = 20 * 60
AI_TICK_MAX = 30 * 60
TROOP_KINDS = ("cav", "archer", "inf", "spear")
TERR_CATALOG = "/data/territory_catalog.json"   # 從真人佔領學到的 {regionKey: pop}
# AI 有自己的「家鄉基地」(存在 economy.json 的 AI_OWNER 帳下，off-map、玩家打不到)：
# 人口→每小時金幣、金幣→自動招募補兵。難度越高，預設人口與金幣越多(→ 收入更高、軍隊更快更大)。
AI_DIFFICULTY = os.environ.get("AI_DIFFICULTY", "normal").lower()
AI_DIFF = {
    "easy":   {"pop": 120,  "gold": 300},
    "normal": {"pop": 400,  "gold": 1500},
    "hard":   {"pop": 1000, "gold": 8000},
}

# ================= 房間(一局)：老師開房設定 → 學生加入競爭 =================
# 一台部署共用「一個房間」(單一世界)。老師設定：地圖、幾個 AI(各難度)、學生起始資源、上限人數。
# 按「開始」→ 重置世界(領地/經濟/事件)、依設定生成 AI、之後學生加入就照設定發起始資源。
room_lock = threading.Lock()
ROOM_DEFAULTS = {
    "map": "Pre-A1",                       # 競爭用的地圖(等級 id)＝匹配的課程
    "ais": [{"name": "AI 1", "difficulty": "normal"}],
    "capacity": 8,                         # 房間總人數(含 AI)；真人上限 = capacity - len(ais)
    "startPop": 150, "startGold": 500, "startTroops": 100,
    "maxStudents": 40, "members": [], "host": "", "started": False, "startedAt": 0,
}
ROOM_CODE_LEN = 5
ROOM_MAX_PLAYERS = 8                        # 私人房間總人數(含 AI)上限
# 全域世界：常駐、世界地圖、不分等級、人人可進、玩家不能重置/停止
GLOBAL_ROOM = "GLOBAL"
GLOBAL_MAP = os.environ.get("GLOBAL_MAP", "A2")          # 世界地圖(A2)
GLOBAL_AIS = clampi(os.environ.get("GLOBAL_AIS") or 3, 0, 16)
GLOBAL_AI_DIFF = os.environ.get("GLOBAL_AI_DIFF", "normal")
# 起始資源用三檔預設(pop, gold, troops)取代逐項數字
RES_PRESETS = {
    "low":    (100, 300, 60),
    "medium": (150, 500, 100),
    "high":   (250, 1000, 180),
}
RES_DEFAULT = "medium"


def res_from_values(pop, gold, troops):
    for name, (p, g, t) in RES_PRESETS.items():
        if (clampi(pop), clampi(gold), clampi(troops)) == (p, g, t):
            return name
    return RES_DEFAULT


def load_room(code=None):
    try:
        with open(room_path("room.json", code)) as f:
            r = json.load(f)
        if not isinstance(r, dict):
            r = {}
    except Exception:
        r = {}
    out = dict(ROOM_DEFAULTS)
    out.update(r)
    if not isinstance(out.get("ais"), list) or not out["ais"]:
        out["ais"] = [dict(a) for a in ROOM_DEFAULTS["ais"]]
    if not isinstance(out.get("members"), list):
        out["members"] = []
    return out


def save_room(r, code=None):
    p = room_path("room.json", code)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(r, f)
    os.replace(tmp, p)


def gen_room_code():
    existing = set(list_rooms())
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(ROOM_CODE_LEN))
        if code not in existing and code != GLOBAL_ROOM:
            return code


def is_global(code):
    return (code or "").upper() == GLOBAL_ROOM


def ensure_global_room():
    # 常駐世界：不存在就建立(世界地圖、幾個預設 AI、無人數上限、沒有 host、永遠 started)
    keep = current_room()
    try:
        set_room(GLOBAL_ROOM)
        r = load_room()
        if r.get("started") and r.get("map") and os.path.isfile(room_path("room.json")):
            return
        diff = GLOBAL_AI_DIFF if GLOBAL_AI_DIFF in AI_DIFF else "normal"
        r = dict(ROOM_DEFAULTS)
        r.update({
            "map": GLOBAL_MAP,
            "ais": [{"name": "AI " + str(i + 1), "difficulty": diff} for i in range(GLOBAL_AIS)],
            "capacity": 100000, "maxStudents": 100000,
            "startPop": RES_PRESETS[RES_DEFAULT][0], "startGold": RES_PRESETS[RES_DEFAULT][1],
            "startTroops": RES_PRESETS[RES_DEFAULT][2], "resources": RES_DEFAULT,
            "members": [], "host": "", "started": True, "startedAt": int(time.time()),
        })
        save_room(r)
    finally:
        set_room(keep)


def find_user_room(user):
    # 回傳這位使用者建立(host)的房間代碼(一人一間)；找不到回 None。不更動 caller 的目前房間。
    keep = current_room()
    try:
        for code in list_rooms():
            set_room(code)
            if load_room().get("host") == user:
                return code
        return None
    finally:
        set_room(keep)


def room_ai_names(r=None):
    r = r or load_room()
    return set(a.get("name") for a in (r.get("ais") or []) if a.get("name"))


# 學生加入名額控管：回傳是否可進場(已是成員/主持人=可；額滿=不可，否則登記為成員)
def room_admit(user):
    with room_lock:
        r = load_room()
        if not r.get("started"):
            return True                        # 沒有進行中的房間 → 一律放行
        if user == r.get("host") or user in room_ai_names(r):
            return True
        members = r.get("members") or []
        if user in members:
            return True
        if len(members) >= clampi(r.get("maxStudents", 40), 1, 500):
            return False
        members.append(user)
        r["members"] = members
        save_room(r)
        return True


def load_catalog():
    try:
        with open(TERR_CATALOG) as f:
            c = json.load(f)
            return canonize_keys(c) if isinstance(c, dict) else {}   # 學到的人口快取也用 canonical key
    except Exception:
        return {}


def save_catalog(c):
    os.makedirs(os.path.dirname(TERR_CATALOG), exist_ok=True)
    tmp = TERR_CATALOG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(c, f)
    os.replace(tmp, TERR_CATALOG)


# NOTE (Phase 2A): the legacy aggregate "_force_power / _mix / _alive" AI battle formula was
# RETIRED, and the old server-local counter tables "_atk_bonus / _def_bonus" were REMOVED — they
# were no longer authoritative or referenced. The single source of truth for unit counters is now
# game.config.atk_bonus / game.config.def_bonus, consumed by the one canonical engine
# (game.battle via game.conquest.resolve_attack) for BOTH player and AI battles.


def _region_display(key):       # 從 store key 生一個看得懂的名字給事件牆用
    if terr_catalog:            # canonical id -> 目錄裡的顯示名
        try:
            t = terr_catalog.territories.get(key) if terr_catalog.loaded else None
            if t is None and not terr_catalog.loaded:
                terr_catalog.load(); t = terr_catalog.territories.get(key)
            if t and t.get("displayName"):
                return clean_txt(t["displayName"], 40)
        except Exception:
            pass
    k = key.split("#")[-1] if "#" in key else (key.split(":")[-1] if ":" in key else key)
    k = k.split("/")[-1]
    k = k.rsplit(".", 1)[0]
    return clean_txt(k.replace("_", " ").replace("-", " ").strip() or "a region", 40)


def _ai_log_event(ai_name, kind, region, victim=None, key=None, atk=0, dfn=0):
    forces = " · 🗡️%d vs 🛡️%d" % (clampi(atk), clampi(dfn)) if (atk or dfn) else ""
    if kind == "occupy":
        text = "🤖 %s occupied %s" % (ai_name, region)
        etype = "occupy"
    elif kind == "attack_win":
        text = "🤖 %s stormed %s%s%s" % (ai_name, region, (" (was %s's)" % victim if victim else ""), forces)
        etype = "attack"
    elif kind == "attack_fail":
        text = "🛡️ %s repelled the 🤖 %s attack on %s%s" % (victim or "Defenders", ai_name, region, forces)
        etype = "defend"
    else:
        return
    # 除了給人看的 text，另存結構化欄位讓前端能把事件定位到地圖某一塊並依時間回放
    ev = {"ts": int(time.time()), "user": ai_name, "text": clean_txt(text, 120),
          "type": etype, "key": key or "", "region": region,
          "owner": ai_name, "victim": victim or ""}
    with ev_lock:
        evs = load_events()
        evs.append(ev)
        if len(evs) > EVENTS_MAX:
            evs = evs[-EVENTS_MAX:]
        save_events(evs)


# AI 家鄉基地經濟：依難度種下人口/金幣，之後跟玩家一樣每小時產金(人口 + AI 領地人口)。
def ai_econ(estore, now, tstore, name, difficulty):
    if not isinstance(estore.get(name), dict):
        diff = AI_DIFF.get(difficulty, AI_DIFF["normal"])
        estore[name] = {"population": diff["pop"], "gold": diff["gold"],
                        "lastGold": now, "troops": _norm_troops(0)}
    return econ_get(estore, name, now, user_region_pop(tstore, name))


# AI 補兵：把金幣全部拿去買一批平均分配的部隊，加進 AI 兵力池。
def _ai_recruit(ae):
    gold = clampi(ae.get("gold", 0))
    if gold <= 0:
        return
    per = gold // len(TROOP_ALL)
    spent = 0
    for u in TROOP_ALL:
        n = per // UNIT_COST[u]
        if n > 0:
            ae["troops"][u] = clampi(ae["troops"].get(u, 0)) + n
            spent += n * UNIT_COST[u]
    ae["gold"] = clampi(gold - spent)


def ai_move(ai_name=AI_OWNER, difficulty=AI_DIFFICULTY, ai_names=None):
    ai_names = ai_names or {ai_name}
    logged = None
    with terr_lock:
        store = load_territory_store()
        with econ_lock:
            estore = load_econ_store()
            ae = ai_econ(estore, time.time(), store, ai_name, difficulty)   # 家鄉基地：累積金幣(off-map，玩家打不到)
            _ai_recruit(ae)                            # 金幣 → 招募補兵到 AI 兵力池
            pool = ae["troops"]
            army = [{"type": t, "hp": clampi(pool.get(t, 0))} for t in TROOP_ALL if clampi(pool.get(t, 0)) > 0]
            pool_total = sum(t["hp"] for t in army)

            owned = set(store.keys())
            ai_owned = {f: h for f, h in store.items()
                        if isinstance(h, dict) and h.get("owner") in ai_names}
            player_regions = [f for f, h in store.items()      # 只打「非 AI」的領地
                              if isinstance(h, dict) and h.get("owner") and h.get("owner") not in ai_names]
            cat = load_catalog()
            unowned_known = [k for k in cat.keys() if k not in owned]

            # Phase 2B：AI 攻擊也必須「從相鄰的自有領地(有駐軍)出兵」。來源挑選 = 駐軍最多者(平手取
            #   canonical id 最小)——最簡單的確定性規則，不做路徑搜尋/策略圖搜尋。占領(neutral)流程不變。
            def _best_source(tgt):
                cands = [s for s, sh in ai_owned.items()
                         if terr_catalog and terr_catalog.are_adjacent(s, tgt)
                         and game_army.garrison_total(sh.get("troops")) > 0]
                cands.sort(key=lambda s: (-game_army.garrison_total(ai_owned[s].get("troops")), s))
                return cands[0] if cands else None
            attack_targets = [t for t in player_regions if _best_source(t)]

            can_occupy = bool(unowned_known) and pool_total >= 8   # 占領仍用兵力池的軍隊
            can_attack_now = bool(attack_targets)                  # 攻擊改用來源領地駐軍
            if not (can_occupy or can_attack_now):    # 沒有可行動作 → 這回合只補兵、存錢
                save_econ_store(estore)
                return None
            act = ("attack" if random.random() < 0.6 else "occupy") if (can_occupy and can_attack_now) \
                else ("attack" if can_attack_now else "occupy")

            if act == "occupy":
                key = random.choice(unowned_known)
                store[key] = {"owner": ai_name, "avatar": AI_AVATAR, "troops": army,
                              "pop": clampi(cat.get(key, 100))}
                ae["troops"] = _norm_troops(0)         # 兵力池派出去當駐軍 → 清空(靠金幣再補)
                logged = ("occupy", _region_display(key), None, key)
            else:
                target = random.choice(attack_targets)   # 保留「隨機挑目標」的既有風格(僅限有相鄰來源者)
                source = _best_source(target)
                sh, th = store[source], store[target]
                victim = th.get("owner")
                region = _region_display(target)
                squad = game_army.alive_garrison(sh.get("troops"))   # AI 投入整支來源駐軍
                def_troops = th.get("troops") or []
                atk_force = sum(u["hp"] for u in squad)
                def_force = sum(clampi(t.get("hp", 0)) for t in def_troops if isinstance(t, dict))
                # 與真人同一條 Game-Domain 規則：擁有權/相鄰/駐軍/戰鬥完全相同。唯一差別 =
                # require_qualifications=False：人類的「學習資格」不適用於 AI(明確政策，非散落的 if-ai)。
                elig = game_conquest.can_attack(ai_name, source, target, squad, terr_catalog, store,
                                                require_qualifications=False)
                if not elig.allowed:                   # 已預篩，理論上不會發生 → 保守跳過，狀態零變動
                    save_econ_store(estore)
                    return None
                res = game_conquest.resolve_attack(squad, def_troops, sh.get("tech") or {},
                                                   th.get("tech") or {}, random)
                ns, nt = game_conquest.apply_territorial_attack(sh, th, squad, res, ai_name, AI_AVATAR)
                if res["attackerWon"] and not clampi(nt.get("pop", 0)):
                    nt["pop"] = clampi(th.get("pop", cat.get(target, 100)))
                store[source] = ns                     # 來源駐軍已扣除出征兵(輸則生還者退回)
                store[target] = nt                     # 贏 → 易主+生還者進駐；輸 → 守方保留+守軍改為生還者
                logged = (("attack_win" if res["attackerWon"] else "attack_fail"),
                          region, victim, target, atk_force, def_force)
            save_econ_store(estore)
        save_territory_store(store)

    if logged:
        _ai_log_event(ai_name, *logged)
        if logged[0] == "attack_fail" and logged[2] and logged[2] not in ai_names:
            econ_add_gold(logged[2], DEFEND_GOLD)      # 玩家成功擋下 AI → 防守成功 +50
    return logged


def ai_loop():
    time.sleep(60)                                 # 開機後稍等，避免和啟動流程搶鎖
    while True:
        try:
            for code in list_rooms():              # 每個房間各自跑自己的 AI
                set_room(code)
                try:
                    room = load_room()
                    ais = room.get("ais") or []
                    names = room_ai_names(room)
                    if room.get("started") and ais:
                        for a in ais:              # 房間裡每個 AI 各出手一次
                            try:
                                ai_move(a.get("name") or AI_OWNER, a.get("difficulty", "normal"), names)
                            except Exception:
                                pass
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(random.randint(AI_TICK_MIN, AI_TICK_MAX))


# ================= 徵兵制：領地每小時自動花預算金幣買兵(平均分配到各生產兵種) =================
CONSCRIPT_MAX_CATCHUP = 24                          # 一次最多補算 24 小時，避免長時間停機後暴衝


def _producible_units(buildings):                  # 依已蓋的生產建築 → 可生產的兵種
    b = buildings or {}
    u = []
    if b.get("barracks"): u += ["inf", "spear"]
    if b.get("archery"):  u += ["archer"]
    if b.get("stable"):   u += ["cav"]
    return u


def _conscript_buy(units, spend):                  # 把 spend 金幣平均分配到各兵種，回傳 {兵種:數量}, 實際花費
    if not units or spend <= 0:
        return {}, 0
    per = spend // len(units)
    bought, cost = {}, 0
    for u in units:
        n = per // UNIT_COST[u]
        if n > 0:
            bought[u] = n
            cost += n * UNIT_COST[u]
    return bought, cost


def _as_float(v, default):
    try:
        return float(v)
    except Exception:
        return default


def conscript_tick():
    now = time.time()
    with terr_lock:
        store = load_territory_store()
        with econ_lock:
            estore = load_econ_store()
            t_dirty = e_dirty = False
            # 1) 各領地徵兵 → 加進該區守軍，花擁有者金幣池(只花金幣，不扣人口)。人口不再自動成長。
            for f, h in store.items():
                if not (isinstance(h, dict) and h.get("owner") and h.get("owner") != AI_OWNER):
                    continue
                if not h.get("conscript"):
                    continue
                budget = clampi(h.get("conscriptBudget", 0))
                units = _producible_units(h.get("buildings"))
                if budget <= 0 or not units:
                    continue
                e = econ_get(estore, h["owner"], now, user_region_pop(store, h["owner"]))
                last = _as_float(h.get("lastConscript"), now)
                hours = min(int((now - last) // GROW_SECONDS), CONSCRIPT_MAX_CATCHUP)
                if hours <= 0:
                    continue
                troops = h.get("troops") or []
                for _ in range(hours):
                    if clampi(e.get("gold", 0)) < budget:   # 金幣不夠整筆預算 → 這小時不做事
                        break
                    bought, cost = _conscript_buy(units, budget)
                    if cost <= 0:
                        break
                    for u, n in bought.items():
                        slot = next((t for t in troops if isinstance(t, dict) and t.get("type") == u), None)
                        if slot:
                            slot["hp"] = clampi(slot.get("hp", 0)) + n
                        else:
                            troops.append({"type": u, "hp": n})
                    e["gold"] = clampi(e.get("gold", 0)) - cost   # 徵兵只花金幣，不扣人口
                    e_dirty = True
                h["troops"] = troops
                h["lastConscript"] = last + hours * GROW_SECONDS
                t_dirty = True
            # 2) 家鄉基地徵兵 → 加進自由兵力池(economy troops)
            for user in list(estore.keys()):
                e = estore.get(user)
                if not (isinstance(e, dict) and e.get("conscript")):
                    continue
                budget = clampi(e.get("conscriptBudget", 0))
                units = _producible_units(e.get("buildings"))
                if budget <= 0 or not units:
                    continue
                e = econ_get(estore, user, now, user_region_pop(store, user))
                last = _as_float(e.get("lastConscript"), now)
                hours = min(int((now - last) // GROW_SECONDS), CONSCRIPT_MAX_CATCHUP)
                if hours <= 0:
                    continue
                for _ in range(hours):
                    if clampi(e.get("gold", 0)) < budget:   # 金幣不夠整筆預算 → 這小時不做事
                        break
                    bought, cost = _conscript_buy(units, budget)
                    if cost <= 0:
                        break
                    for u, n in bought.items():                    # 分兵種加進兵力池
                        e["troops"][u] = clampi(e["troops"].get(u, 0)) + n
                    e["gold"] = clampi(e.get("gold", 0)) - cost   # 徵兵只花金幣，不扣人口
                    e_dirty = True
                e["lastConscript"] = last + hours * GROW_SECONDS
                e_dirty = True
            if e_dirty:
                save_econ_store(estore)
        if t_dirty:
            save_territory_store(store)


def conscript_loop():
    time.sleep(120)
    while True:
        try:
            for code in list_rooms():              # 每個房間各自結算徵兵
                set_room(code)
                try:
                    conscript_tick()
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(300)                            # 每 5 分鐘檢查一次，依「過了幾小時」補算


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
        set_room((parse_qs(urlparse(self.path).query).get("room", [""]) or [""])[0])
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
        elif path == "/api/events":
            self._handle_events()
        elif path == "/api/room":
            self._handle_room()
        elif path == "/api/rooms":
            self._handle_rooms_list()
        elif path == "/api/learning/registry":
            self._handle_learning_registry()
        elif path == "/api/learning/state":
            self._handle_learning_state()
        elif path == "/api/learning/progress":
            self._handle_learning_progress()
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        set_room((parse_qs(urlparse(self.path).query).get("room", [""]) or [""])[0])
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
        elif path == "/api/territory/release":
            self._handle_territory_release()
        elif path == "/api/territory/build":
            self._handle_territory_build()
        elif path == "/api/territory/research":
            self._handle_territory_research()
        elif path == "/api/territory/recruit":
            self._handle_territory_recruit()
        elif path == "/api/territory/engage":
            self._handle_territory_engage()
        elif path == "/api/territory/attack":
            self._handle_territory_attack()
        elif path == "/api/territory/attack-result":
            self._handle_territory_attack_result()
        elif path == "/api/territory/conscript":
            self._handle_territory_conscript()
        elif path == "/api/economy/set":
            self._handle_economy_set()
        elif path == "/api/economy/pass":
            self._handle_economy_pass()
        elif path == "/api/learning/attempt":
            self._handle_learning_attempt()
        elif path == "/api/learning/matching/start":
            self._handle_matching_start()
        elif path == "/api/learning/matching/attempt":
            self._handle_matching_attempt()
        elif path == "/api/learning/roleplay/start":
            self._handle_roleplay_start()
        elif path == "/api/learning/roleplay/respond":
            self._handle_roleplay_respond()
        elif path == "/api/room/start":
            self._handle_room_start()
        elif path == "/api/room/stop":
            self._handle_room_stop()
        elif path == "/api/room/create":
            self._handle_room_create()
        elif path == "/api/room/enter" or path == "/api/room/join":
            self._handle_room_enter()
        elif path == "/api/room/leave":
            self._handle_room_leave()
        elif path == "/api/event":
            self._handle_event_add()
        else:
            self._send({"error": "not found"}, 404)

    # Phase 3E1：Read-Along 轉為後端權威。帶 activityId + sentenceIndex(且已登入) → 伺服器自己
    #   從課程內容取出目標句、自己批改、自己保存(每句取最佳)。client 送的 ?text= 在這個模式下一律忽略。
    #   沒帶 activityId → 舊模式(roleplay 用)，只回 transcript，不產生任何權威狀態。
    #   轉檔/辨識失敗 → 回錯誤且「不」寫入任何分數/完成/資格/獎勵(不可把當機變成滿分)。
    def _handle_stt(self):
        qs = parse_qs(urlparse(self.path).query)
        client_text = (qs.get("text", [""]) or [""])[0]
        aid = (qs.get("activityId", [""]) or [""])[0].strip()
        sidx_raw = (qs.get("sentenceIndex", [""]) or [""])[0].strip()
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._send({"error": "no audio"}, 400)
            return
        audio = self.rfile.read(length)
        user = token_user(self._token())
        authoritative = bool(aid) and user is not None
        target = client_text                          # legacy mode only: a soft whisper hint
        if authoritative:
            if not LEARNING.is_read_along(aid):
                self._send({"error": "not a read-along activity", "reason": "not_scorable"}, 400)
                return
            target, total = LEARNING.read_along_target(aid, sidx_raw)
            if target is None:
                self._send({"error": "unknown sentence for this activity",
                            "reason": "bad_sentence"}, 400)
                return
        elif aid and user is None:
            self._send({"error": "Not logged in"}, 401)
            return
        try:
            text = transcribe(audio, target)
        except Exception:
            # §14: an outage must never become authoritative success. No score, no completion, no
            # qualification, no reward. Internal detail is not leaked to the client.
            self._send({"error": "speech recognition unavailable", "reason": "stt_unavailable"}, 503)
            return
        if not authoritative:
            self._send({"transcript": text, "target": target, "authoritative": False})
            return
        with acct_lock:
            p = load_progress(user)
            learning = p.setdefault("learning", {})
            _, out = LEARNING.record_read_along(learning, aid, sidx_raw, text, int(time.time()))
            if out is None:
                self._send({"error": "unknown sentence for this activity",
                            "reason": "bad_sentence"}, 400)
                return
            save_progress(user, p)
        delta = clampi(out.get("rewardAmount", 0)) + clampi(out.get("lessonRewardAmount", 0))
        newgold = econ_add_gold(user, delta) if delta else None
        self._send({"transcript": text, "target": out["target"], "authoritative": True,
                    "activityId": out["activityId"], "sentenceIndex": out["sentenceIndex"],
                    "score": out["score"], "improved": out["improved"],
                    "totalSentences": out["totalSentences"],
                    "activityPct": out["activityPct"], "activityPassed": out["activityPassed"],
                    "qualifications": out["granted"], "rewarded": out["rewarded"], "gold": newgold})

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
        me = token_user(self._token())              # 戰霧：只有自己的領地才看得到守軍/科技
        ai_names = room_ai_names()
        with terr_lock:
            store = load_territory_store()
        holders, counts = {}, {}
        for f, h in store.items():
            if not isinstance(h, dict):
                continue
            owner = h.get("owner")
            if owner:
                counts[owner] = counts.get(owner, 0) + 1
            if owner and owner == me:               # 自己的領地：完整資訊
                holders[f] = {"owner": owner, "avatar": h.get("avatar", "👦"),
                              "troops": h.get("troops") or [], "pop": h.get("pop"),
                              "income": region_gold_income(h),
                              "buildings": h.get("buildings") or {}, "tech": h.get("tech") or {}, "mine": True,
                              "conscript": bool(h.get("conscript")), "conscriptBudget": clampi(h.get("conscriptBudget", 0))}
            else:                                   # 別人/AI 的領地：不透露兵力、兵種、科技
                holders[f] = {"owner": owner, "avatar": h.get("avatar", "👦"),
                              "pop": h.get("pop"), "hidden": True, "ai": owner in ai_names}
        self._send({"holders": holders, "counts": counts})

    # 攻方在前端用兵種打贏（或佔領空據點）後呼叫，存下新的守備軍（pilot：信任前端結果）
    # 後端權威：把 client 傳來的任何識別碼解析成 canonical 領地 id(解析不到回 None)。
    def _canon(self, raw):
        raw = (raw or "").strip()
        if not raw:
            return None
        if terr_catalog:
            try:
                return terr_catalog.resolve_any(raw)
            except Exception:
                return None
        return raw          # 目錄不可用時退回原字串(相容)

    def _handle_territory_claim(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        troops_in = d.get("troops")
        if not isinstance(troops_in, list):
            self._send({"error": "missing troops"}, 400)
            return
        # ---- 後端權威：解析 + 驗證領地身分（絕不直接信任 client 的 SVG path）----
        f = self._canon(d.get("file"))
        if not f:
            self._send({"error": "Unknown territory", "reason": "unresolved"}, 400)
            return
        if not terr_catalog or not terr_catalog.is_canonical(f):
            self._send({"error": "Territory not in catalog", "reason": "not_in_catalog"}, 400)
            return
        allowed = allowed_maps_for_level(load_room().get("map") or "")
        if allowed is not None and terr_catalog.map_of(f) not in allowed:
            self._send({"error": "Territory is not on this room's map", "reason": "wrong_map"}, 400)
            return
        cpop = terr_catalog.game_population(f)
        if cpop is None:
            self._send({"error": "No population for territory", "reason": "no_population"}, 400)
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
        region_pop = clampi(cpop)          # 人口以目錄為權威(不信任 client 的 pop)
        # 佔領只發生在「無主」據點：有主據點要先打贏(/api/territory/attack 後端權威地清成無主)才能佔領。
        # 後端強制此規則 → client 不能用 /claim 直接奪取敵方領地(繞過戰鬥)。只能佔無主或重部署自己的。
        with terr_lock:
            store = load_territory_store()
            prev = store.get(f) if isinstance(store.get(f), dict) else {}
            if prev.get("owner") and prev.get("owner") != user:   # 有主且非本人 → 必須先攻打
                self._send({"error": "Territory is held — attack it first", "reason": "held"}, 403)
                return
            keep = {}
            if prev.get("owner") == user:                # 重新部署自己的守軍 → 保留建築/科技/人口/徵兵設定
                keep = {"buildings": prev.get("buildings") or {}, "tech": prev.get("tech") or {}}
                for k in ("pop", "lastPop", "conscript", "conscriptBudget", "lastConscript"):
                    if k in prev:
                        keep[k] = prev[k]
            store[f] = {"owner": user, "avatar": str(d.get("avatar", "👦"))[:8],
                        "troops": troops, "pop": region_pop, **keep}
            save_territory_store(store)                  # 一律以 canonical key 存檔
            cat = load_catalog()                         # 讓電腦 AI 學到「這塊地存在 + 人口」
            if cat.get(f) != region_pop:
                cat[f] = region_pop
                save_catalog(cat)
        self._send({"ok": True, "territory": f})

    # 攻方打贏「有主」據點後呼叫：把該據點清成「無主」，前主人扣掉該區人口。
    # 攻方不會馬上取得所有權——之後要走「過關→佔領」流程才真正佔領。
    # LEGACY (Phase 2A): winning an attack now neutralizes the region AUTHORITATIVELY inside
    # /api/territory/attack. /release is retired from the combat path and is restricted to the
    # region's OWNER (self-abandon) — a client can NEVER neutralize an ENEMY territory via /release.
    def _handle_territory_release(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        f = self._canon(d.get("file")) or (d.get("file") or "").strip()   # canonical 領地 id(相容 legacy)
        if not f:
            self._send({"error": "missing file"}, 400)
            return
        with terr_lock:
            store = load_territory_store()
            h = store.get(f)
            if not isinstance(h, dict) or not h.get("owner"):
                self._send({"ok": True, "released": False})       # 已無主 → 冪等，無事可做
                return
            if h.get("owner") != user:                            # 只能放棄自己的領地，不能清空敵方
                self._send({"error": "not your region", "reason": "not_owner"}, 403)
                return
            del store[f]           # 放棄自家守備 → 恢復無主（該區的駐軍/成長隨之消失）
            save_territory_store(store)
        # 領地的兵力現在長在「該區駐軍」而不是玩家人口池，失去領地即失去其駐軍。
        self._send({"ok": True, "released": True})

    # 蓋建築（目前：兵工廠 armory）：需為該領地擁有者，扣該區金幣。
    def _handle_territory_build(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        f = self._canon(d.get("file")) or (d.get("file") or "").strip()   # canonical 領地 id(相容 legacy)
        building = str(d.get("building", ""))
        if building not in BUILD_COST:
            self._send({"error": "unknown building"}, 400)
            return
        cost = BUILD_COST[building]
        if f == HOME_KEY:                          # 家鄉基地：建築存在玩家經濟裡
            with terr_lock:
                region_pop = user_region_pop(load_territory_store(), user)
            with econ_lock:
                estore = load_econ_store()
                e = econ_get(estore, user, time.time(), region_pop)
                builds = e["buildings"]
                if builds.get(building):
                    self._send({"error": "already built"}, 400)
                    return
                if clampi(e.get("gold", 0)) < cost:
                    self._send({"error": "not enough gold", "gold": clampi(e.get("gold", 0)), "cost": cost}, 400)
                    return
                e["gold"] = clampi(e.get("gold", 0)) - cost
                builds[building] = True
                save_econ_store(estore)
                newgold = e["gold"]
            self._send({"ok": True, "gold": newgold, "buildings": builds})
            return
        with terr_lock:                            # terr 外層、econ 內層(全站一致的鎖順序)
            store = load_territory_store()
            h = store.get(f)
            if not isinstance(h, dict) or h.get("owner") != user:
                self._send({"error": "not your region"}, 403)
                return
            builds = h.get("buildings") or {}
            if builds.get(building):
                self._send({"error": "already built"}, 400)
                return
            region_pop = user_region_pop(store, user)
            with econ_lock:                        # 從玩家的統一金幣池扣款
                estore = load_econ_store()
                e = econ_get(estore, user, time.time(), region_pop)
                if clampi(e.get("gold", 0)) < cost:
                    self._send({"error": "not enough gold", "gold": clampi(e.get("gold", 0)), "cost": cost}, 400)
                    return
                e["gold"] = clampi(e.get("gold", 0)) - cost
                save_econ_store(estore)
                newgold = e["gold"]
            builds[building] = True
            h["buildings"] = builds
            save_territory_store(store)
        self._send({"ok": True, "gold": newgold, "buildings": builds})

    # 在兵工廠研發科技（track = atk 鍛造 / def 鎧甲），即時完成、只惠及該區守軍。
    def _handle_territory_research(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        f = self._canon(d.get("file")) or (d.get("file") or "").strip()   # canonical 領地 id(相容 legacy)
        track = str(d.get("track", ""))
        if track not in TECH_TRACKS:
            self._send({"error": "unknown track"}, 400)
            return
        def _tech_reject(reason, gold, cost):   # 把 game.technology 的原因翻回既有的 HTTP 回應(行為不變)
            if reason == "need_armory":
                self._send({"error": "need armory"}, 400)
            elif reason == "maxed":
                self._send({"error": "maxed"}, 400)
            else:
                self._send({"error": "not enough gold", "gold": clampi(gold), "cost": cost}, 400)
        if f == HOME_KEY:                          # 家鄉科技：研發存在玩家經濟裡(加成攻擊軍)
            with terr_lock:
                region_pop = user_region_pop(load_territory_store(), user)
            with econ_lock:
                estore = load_econ_store()
                e = econ_get(estore, user, time.time(), region_pop)
                tech = e["tech"]
                ok, cost, nxt, reason = game_tech.can_research(track, tech.get(track, 0), e.get("gold", 0),
                                                               has_armory=bool(e["buildings"].get("armory")))
                if not ok:
                    _tech_reject(reason, e.get("gold", 0), cost)
                    return
                e["gold"] = clampi(e.get("gold", 0)) - cost
                tech[track] = nxt
                save_econ_store(estore)
                newgold = e["gold"]
            self._send({"ok": True, "gold": newgold, "tech": tech})
            return
        with terr_lock:
            store = load_territory_store()
            h = store.get(f)
            if not isinstance(h, dict) or h.get("owner") != user:
                self._send({"error": "not your region"}, 403)
                return
            tech = h.get("tech") or {}
            region_pop = user_region_pop(store, user)
            with econ_lock:                        # 從玩家的統一金幣池扣款
                estore = load_econ_store()
                e = econ_get(estore, user, time.time(), region_pop)
                ok, cost, nxt, reason = game_tech.can_research(track, tech.get(track, 0), e.get("gold", 0),
                                                               has_armory=bool((h.get("buildings") or {}).get("armory")))
                if not ok:
                    _tech_reject(reason, e.get("gold", 0), cost)
                    return
                e["gold"] = clampi(e.get("gold", 0)) - cost
                save_econ_store(estore)
                newgold = e["gold"]
            tech[track] = nxt
            h["tech"] = tech
            save_territory_store(store)
        self._send({"ok": True, "gold": newgold, "tech": tech})

    # 招募：在該領地用玩家的統一金幣池生產部隊，加進該區守軍(需先蓋對應建築)。
    def _handle_territory_recruit(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        f = self._canon(d.get("file")) or (d.get("file") or "").strip()   # canonical 領地 id(相容 legacy)
        unit = str(d.get("unit", ""))
        if unit not in game_config.UNIT_COST:
            self._send({"error": "unknown unit"}, 400)
            return
        qty = clampi(d.get("qty", RECRUIT_BATCH), 1, 100000)
        need = game_recruit.building_for(unit)

        def _recruit_reject(reason, gold, cost):   # game.recruitment 原因 → 既有 HTTP 回應(行為不變)
            if reason and reason.startswith("need_"):
                self._send({"error": "need " + need}, 400)
            elif reason == "not_your_region":
                self._send({"error": "not your region"}, 403)
            else:
                self._send({"error": "not enough gold", "gold": clampi(gold), "cost": cost}, 400)
        if f == HOME_KEY:                          # 家鄉招募 → 加進「自由兵力池」(economy troops)
            with terr_lock:
                region_pop = user_region_pop(load_territory_store(), user)
            with econ_lock:
                estore = load_econ_store()
                e = econ_get(estore, user, time.time(), region_pop)
                ok, cost, reason = game_recruit.can_recruit(unit, qty, e.get("gold", 0), bool(e["buildings"].get(need)))
                if not ok:
                    _recruit_reject(reason, e.get("gold", 0), cost)
                    return
                e["gold"] = clampi(e.get("gold", 0)) - cost   # 招募只花金幣，不再扣人口
                e["troops"][unit] = clampi(e["troops"].get(unit, 0)) + qty   # 加進該兵種
                save_econ_store(estore)
                newgold, newtroops, newpop = e["gold"], e["troops"], e["population"]
            self._send({"ok": True, "gold": newgold, "troops": newtroops, "population": newpop})
            return
        with terr_lock:
            store = load_territory_store()
            h = store.get(f)
            owns = isinstance(h, dict) and h.get("owner") == user
            has_bld = bool((h or {}).get("buildings", {}).get(need)) if isinstance(h, dict) else False
            region_pop = user_region_pop(store, user) if isinstance(h, dict) else 0
            with econ_lock:                        # 從玩家的統一金幣池扣款
                estore = load_econ_store()
                e = econ_get(estore, user, time.time(), region_pop)
                ok, cost, reason = game_recruit.can_recruit(unit, qty, e.get("gold", 0), has_bld, owns_territory=owns)
                if not ok:
                    _recruit_reject(reason, e.get("gold", 0), cost)
                    return
                e["gold"] = clampi(e.get("gold", 0)) - cost   # 招募只花金幣，不再扣人口
                save_econ_store(estore)
                newgold = e["gold"]
            troops = h.get("troops") or []          # 併進同兵種，否則新增一格
            slot = next((t for t in troops if isinstance(t, dict) and t.get("type") == unit), None)
            if slot:
                slot["hp"] = clampi(slot.get("hp", 0)) + qty
            else:
                troops.append({"type": unit, "hp": qty})
            h["troops"] = troops
            save_territory_store(store)
        self._send({"ok": True, "gold": newgold, "troops": h["troops"], "population": h["pop"]})

    # 設定徵兵制：開/關 + 每小時預算(金幣)。之後由 conscript_loop 每小時自動買兵。
    def _handle_territory_conscript(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        f = self._canon(d.get("file")) or (d.get("file") or "").strip()   # canonical 領地 id(相容 legacy)
        on = bool(d.get("on"))
        budget = clampi(d.get("budget", 0), 0, 1000000)
        now = time.time()
        if f == HOME_KEY:                          # 家鄉基地
            with econ_lock:
                estore = load_econ_store()
                e = econ_get(estore, user, now, 0)
                e["conscript"], e["conscriptBudget"], e["lastConscript"] = on, budget, now
                save_econ_store(estore)
            self._send({"ok": True, "conscript": on, "conscriptBudget": budget})
            return
        with terr_lock:
            store = load_territory_store()
            h = store.get(f)
            if not isinstance(h, dict) or h.get("owner") != user:
                self._send({"error": "not your region"}, 403)
                return
            h["conscript"], h["conscriptBudget"], h["lastConscript"] = on, budget, now
            save_territory_store(store)
        self._send({"ok": True, "conscript": on, "conscriptBudget": budget})

    # LEGACY / READ-ONLY (Phase 2A): the server-authoritative /api/territory/attack returns the
    # defender order+tech itself, so the combat path no longer needs this pre-battle reveal. Kept as a
    # READ-ONLY endpoint (it mutates nothing) — it cannot create an authority bypass. No reachable
    # flow calls it after the openOutpost migration.
    def _handle_territory_engage(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        raw = self._body_json().get("file")
        f = self._canon(raw) or (raw or "").strip()
        with terr_lock:
            store = load_territory_store()
            h = store.get(f)
        if not isinstance(h, dict) or not h.get("owner"):
            self._send({"troops": [], "tech": {}})
            return
        self._send({"owner": h.get("owner"), "troops": h.get("troops") or [], "tech": h.get("tech") or {}})

    # LEGACY / RETIRED (Phase 2A): battle gold (attacker −ATTACK_FAIL_GOLD / defender +DEFEND_GOLD) is
    # now applied AUTHORITATIVELY inside /api/territory/attack. This endpoint no longer mutates any
    # gold/reward and cannot forge a battle outcome. Kept as a non-authoritative no-op purely so a
    # stray old client does not error (it used to read `gold`, which is now simply omitted).
    def _handle_territory_attack_result(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        self._send({"ok": True, "legacy": True})   # 不再更動任何金幣/所有權/兵力

    # Phase 2B — territorial conquest：攻擊必須「從自己的相鄰領地(source)出兵」打「敵方相鄰領地(target)」。
    #   出征兵取自 SOURCE 駐軍(不再是全域兵力池)；資格由 game.conquest.can_attack 權威判定(World-Domain 相鄰)。
    #   贏 → target 直接易主、生還者成為 target 新駐軍；輸 → 生還者退回 source 駐軍、守方保留。金幣規則不變。
    # HTTP 情境對照：source_not_owned → 403；其餘資格失敗 → 400，皆附穩定 reason。
    _ATTACK_STATUS = {"source_not_owned": 403, "qualification_required": 403}   # 其餘 reason 一律 400

    def _handle_territory_attack(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        source = self._canon(d.get("sourceTerritoryId") or d.get("source"))
        target = self._canon(d.get("targetTerritoryId") or d.get("target") or d.get("file"))
        # 來源不可由後端臆測：舊 client 只送 target 沒送 source → 明確拒絕(不繞過相鄰規則)。
        if not source:
            self._send({"error": "sourceTerritoryId is required (attack from an owned adjacent territory)",
                        "reason": "source_not_found"}, 400)
            return
        if not target:
            self._send({"error": "Unknown target territory", "reason": "target_not_found"}, 400)
            return
        squad = []
        for t in (d.get("squad") or d.get("troops") or [])[:4]:
            if isinstance(t, dict) and str(t.get("type")) in self.TROOP_TYPES:
                hp = int(t.get("hp", 0) or 0)
                if hp > 0:
                    squad.append({"type": t["type"], "hp": max(0, min(100000, hp))})
        avatar = str(d.get("avatar", "\U0001F466"))[:8]
        defender = None
        result = None
        pq = self._player_qualifications(user)           # 玩家(權威)學習資格；AI 走另一條(bypass)
        with terr_lock:
            store = load_territory_store()
            elig = game_conquest.can_attack(user, source, target, squad, terr_catalog, store,
                                            player_qualifications=pq, require_qualifications=True)
            if not elig.allowed:                         # 資格不符 → 一切狀態零變動(原子拒絕)
                resp = {"error": "Attack not allowed", "reason": elig.reason}
                if elig.reason == "qualification_required":   # 附上缺哪些資格(給前端顯示/導向學習)
                    resp["missingQualificationIds"] = elig.missing_qualifications
                self._send(resp, self._ATTACK_STATUS.get(elig.reason, 400))
                return
            src, tgt = store[source], store[target]
            defender = tgt.get("owner")
            def_tech = tgt.get("tech") or {}
            # 攻方科技 = SOURCE 領地科技(駐軍所在地)；守方科技 = TARGET 領地科技。戰鬥公式不變。
            result = game_conquest.resolve_attack(squad, tgt.get("troops") or [], src.get("tech") or {},
                                                  def_tech, random.Random())
            new_source, new_target = game_conquest.apply_territorial_attack(src, tgt, squad, result, user, avatar)
            if result["attackerWon"] and not clampi(new_target.get("pop", 0)):   # 佔領時補人口(以目錄為權威)
                cpop = terr_catalog.game_population(target) if terr_catalog else None
                new_target["pop"] = clampi(cpop if cpop is not None else tgt.get("pop", 0))
            store[source] = new_source
            store[target] = new_target
            save_territory_store(store)
        # 金幣獎懲(規則不變)：輸 → 攻方 −50、守方(真人非 AI) +50；贏 → 不變。在 terr_lock 外呼叫避免巢狀死鎖。
        newgold = None
        if not result["attackerWon"]:
            newgold = econ_add_gold(user, -ATTACK_FAIL_GOLD)
            if defender and defender != user and defender != AI_OWNER:
                econ_add_gold(defender, DEFEND_GOLD)
        self._send({"ok": True,
                    "sourceTerritoryId": source, "targetTerritoryId": target,
                    "attackerWon": result["attackerWon"], "owner": new_target.get("owner"),
                    "sourceGarrison": new_source.get("troops") or [],
                    "targetGarrison": new_target.get("troops") or [],
                    "gold": newgold,
                    "attackerSurvivors": result["attackerSurvivors"],
                    "defenderSurvivors": result["defenderSurvivors"],
                    "defenderOrder": result["defenderOrder"], "defenderTech": def_tech, "defender": defender})

    # 全站事件牆：GET 取最近事件（所有人共見）
    def _handle_events(self):
        with ev_lock:
            evs = load_events()
        evs = list(reversed(evs))[:60]   # 新的在前
        self._send({"events": evs})

    # 全站事件牆：POST 記一筆（需登入）。文字由伺服器依 type 組成，避免前端注入任意內容。
    def _handle_event_add(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        typ = str(d.get("type", ""))
        u = clean_txt(user, 24)
        region = clean_txt(d.get("region"))
        target = clean_txt(d.get("target"))
        level = clean_txt(d.get("level"))
        key = clean_txt(d.get("key"), 120)
        atk = clampi(d.get("atk", 0))                 # 攻城軍力
        dfn = clampi(d.get("def", 0))                 # 守城軍力
        forces = " · 🗡️%d vs 🛡️%d" % (atk, dfn) if (atk or dfn) else ""
        if typ == "occupy" and region:
            text = "🚩 %s occupied %s" % (u, region)
        elif typ == "attack" and region:
            if d.get("win"):
                text = "⚔️ %s stormed %s%s%s" % (u, region, (" (was %s's)" % target if target else ""), forces)
            else:
                text = "🛡️ %s's attack on %s was repelled%s" % (u, region, forces)
        elif typ == "boss" and level:
            text = "🐲 %s defeated the %s boss" % (u, level)
        else:
            self._send({"error": "bad event"}, 400)
            return
        # 結構化欄位供地圖回放定位（boss 事件不綁地圖，key 留空）
        ev = {"ts": int(time.time()), "user": u, "text": text,
              "type": typ, "key": key, "region": region,
              "owner": u, "victim": target}
        with ev_lock:
            evs = load_events()
            evs.append(ev)
            if len(evs) > EVENTS_MAX:
                evs = evs[-EVENTS_MAX:]
            save_events(evs)
        self._send({"ok": True})

    # 玩家經濟：GET 取得（含每日產兵）
    def _handle_economy(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        if not room_admit(user):                   # 房間人數已滿 → 不能加入
            self._send({"error": "room full", "roomFull": True}, 403)
            return
        with terr_lock:
            region_pop = user_region_pop(load_territory_store(), user)
        with econ_lock:
            store = load_econ_store()
            e = econ_get(store, user, time.time(), region_pop)
            save_econ_store(store)
            pop, troops, gold, passcnt = e["population"], e["troops"], e["gold"], e["passcnt"]
            buildings, tech = e["buildings"], e["tech"]
            conscript, cbudget = bool(e.get("conscript")), clampi(e.get("conscriptBudget", 0))
        income = int(round((pop + region_pop) * GOLD_RATE))   # 金幣/小時 = (家鄉+領地人口) × 比例
        self._send({"population": pop, "troops": troops, "troopsTotal": troops_total(troops),
                    "gold": gold, "goldIncome": income,
                    "passcnt": passcnt, "buildings": buildings, "tech": tech,
                    "conscript": conscript, "conscriptBudget": cbudget})

    # Phase 3A — RETIRED as a gold source. This endpoint used to mint PASS_GOLD from a bare, unverified
    # client `{file}` (unlimited-gold exploit). Gold + qualifications now come ONLY from the
    # server-verified /api/learning/attempt. This endpoint no longer touches gold; it only records the
    # neutral-claim occupy passcount (the bootstrap gate, which §Phase 3A does NOT tie to learning).
    def _handle_economy_pass(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        f = (self._body_json().get("file") or "").strip()
        if not f:
            self._send({"error": "missing file"}, 400)
            return
        with terr_lock:
            region_pop = user_region_pop(load_territory_store(), user)
        with econ_lock:
            store = load_econ_store()
            e = econ_get(store, user, time.time(), region_pop)
            pc = e["passcnt"]
            pc[f] = clampi(pc.get(f, 0)) + 1               # 佔領解鎖用的通過次數(不再發金幣)
            save_econ_store(store)
            cnt = pc[f]
        self._send({"ok": True, "file": f, "count": cnt, "legacy": True})   # no gold: server-verified only

    def _player_qualifications(self, user):
        """The player's authoritative set of held qualification IDs (per-account, room-independent)."""
        with acct_lock:
            p = load_progress(user)
        return LEARNING.player_qualification_ids(p.get("learning") or {})

    # 學習登錄簿(公開)：資格 id→標題/學習去處、活動 id→課程對照。不含答案鍵、不含獎勵金額。
    def _handle_learning_registry(self):
        self._send({"registry": LEARNING.public_registry_view()})

    # 玩家自己的(權威)學習狀態：已獲資格 + 活動完成紀錄。前端用來標示領地鎖定/解鎖(僅顯示，非授權)。
    def _handle_learning_state(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        with acct_lock:
            p = load_progress(user)
        self._send(LEARNING.state_view(p.get("learning") or {}))

    # 唯一權威的「學習完成」路徑。前端只送「身分 + 作答」，其餘一律由 Learning Domain 決定：
    #   activityId(或 3A 舊式 lessonId+activity) → 登錄簿解析 → 權威內容 → grader → 完成 → 資格 → 獎勵政策。
    # 伺服器忽略 client 送的 passed / score / correct / qualification / gold / reward。
    def _handle_learning_attempt(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        # 3B 正規身分；同時相容 3A 前端送的 lessonId+activity(進入 Learning Domain 後立即正規化為 activityId)
        aid = LEARNING.resolve_activity((d.get("activityId") or "").strip(),
                                        (d.get("lessonId") or "").strip(),
                                        (d.get("activity") or "").strip())
        if not aid:
            self._send({"error": "unknown or ungradable activity",
                        "reason": learning_api.REASON_NOT_GRADABLE}, 400)
            return
        result, reason = LEARNING.grade_attempt(aid, d.get("answers"))   # 後端權威批改
        if reason:
            self._send({"error": "cannot grade this attempt", "reason": reason}, 400)
            return
        with acct_lock:
            p = load_progress(user)
            learning = p.setdefault("learning", {})
            _, out = LEARNING.record_attempt(learning, aid, result, int(time.time()))
            save_progress(user, p)
        # 獎勵金額來自遊戲設定(LEARNING 建構時注入)，內容包無法指定金額。在 acct_lock 外呼叫避免巢狀鎖。
        # Phase 3D：活動獎勵與「整課完成」獎勵是分開的政策，一次結算。目前沒有任何正式課程啟用
        # completionPolicy，所以 lessonRewardAmount 恆為 0。
        delta = clampi(out["rewardAmount"]) + clampi(out["lessonRewardAmount"])
        newgold = econ_add_gold(user, delta) if delta else None
        granted = out["granted"] if out["passed"] else []
        self._send({"ok": True, "activityId": aid,
                    "passed": out["passed"], "pct": result["pct"],
                    "correct": result["correct"], "total": result["total"],
                    "qualifications": granted,
                    "qualification": (granted[0] if granted else None),   # 3A 相容欄位(單一資格)
                    "grantedNow": bool(out["grantedNow"]), "grantedNowIds": out["grantedNow"],
                    "alreadyCompleted": out["alreadyCompleted"],
                    "rewarded": out["rewarded"], "gold": newgold,
                    # 整課完成(衍生，非 client 宣告)。沒有政策的課程一律 false。
                    "lessonId": out["lessonId"], "lessonCompleted": out["lessonCompleted"],
                    "lessonCompletedNow": out["lessonCompletedNow"],
                    "lessonQualifications": out["lessonQualifications"],
                    "lessonRewarded": out["lessonRewarded"]})

    # Phase 3E2：配對(Level 5)改為「伺服器擁有回合」。抽樣、正確配對、first-try 狀態全在後端；
    #   client 只拿到可顯示的單字與圖片(不含對應關係)，並把每次點擊送回來由後端判定。
    def _handle_matching_start(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        aid = (self._body_json().get("activityId") or "").strip()
        if not LEARNING.is_matching(aid):
            self._send({"error": "not a matching activity", "reason": "not_scorable"}, 400)
            return
        with acct_lock:
            p = load_progress(user)
            learning = p.setdefault("learning", {})
            _, view = LEARNING.start_matching_round(learning, aid, int(time.time()), random.Random())
            if view is None:
                self._send({"error": "matching content unavailable",
                            "reason": "content_unavailable"}, 400)
                return
            save_progress(user, p)
        self._send(view)          # roundId + 單字(依序) + 圖片(打散)；不含任何配對答案

    def _handle_matching_attempt(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        rid = (d.get("roundId") or "").strip()
        with acct_lock:
            p = load_progress(user)
            learning = p.setdefault("learning", {})
            # 回合存在「該帳號自己的」學習狀態裡 → 別人的 roundId 對這個帳號根本不存在(結構性擁有權)。
            _, out = LEARNING.matching_click(learning, rid, d.get("itemId"), d.get("choiceId"),
                                             int(time.time()))
            if out is None:
                self._send({"error": "unknown, expired or finished round",
                            "reason": "bad_round"}, 400)
                return
            save_progress(user, p)
        delta = clampi(out.get("rewardAmount", 0)) + clampi(out.get("lessonRewardAmount", 0))
        newgold = econ_add_gold(user, delta) if delta else None
        resp = {"ok": True, "roundId": rid, "status": out["status"], "expected": out["expected"],
                "total": out["total"], "completed": out["completed"], "scored": out["scored"]}
        if out["status"] == "complete":
            resp.update(result=out["result"], qualifications=out.get("granted") or [],
                        rewarded=bool(out.get("rewarded")), gold=newgold)
        self._send(resp)

    # Phase 4C：Level 10 角色扮演改為「伺服器擁有整場對話」。劇本圖、目前節點、分支 RNG、
    #   分類器門檻、turns/passes 全在後端；client 只送出學習者說的話，拿回可顯示的下一句。
    #   client 送來的 currentNode/nextNode/turns/passes/score/completed 一律不予採信。
    def _handle_roleplay_start(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        aid = (self._body_json().get("activityId") or "").strip()
        if not LEARNING.is_roleplay(aid):
            self._send({"error": "not a roleplay activity", "reason": "not_scorable"}, 400)
            return
        with acct_lock:
            p = load_progress(user)
            learning = p.setdefault("learning", {})
            _, view = LEARNING.start_roleplay_session(learning, aid, int(time.time()),
                                                      random.Random())
            if view is None:
                self._send({"error": "roleplay content unavailable",
                            "reason": "content_unavailable"}, 400)
                return
            save_progress(user, p)
        self._send(view)          # sessionId + 目前 NPC 台詞；不含路由/關鍵字/權重/下一節點

    def _handle_roleplay_respond(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        sid = (d.get("sessionId") or "").strip()
        text = d.get("response")
        if not isinstance(text, str):
            self._send({"error": "response must be a string", "reason": "bad_response"}, 400)
            return
        seq = d.get("seq")
        # seq 是「client 以為自己在回答第幾回合」。只用來擋重送/雙擊/雙分頁，不能改分數。
        if seq is not None and (isinstance(seq, bool) or not isinstance(seq, int)):
            self._send({"error": "seq must be an integer", "reason": "bad_seq"}, 400)
            return
        with acct_lock:
            p = load_progress(user)
            learning = p.setdefault("learning", {})
            # session 存在「該帳號自己的」學習狀態裡 → 別人的 sessionId 對這個帳號根本不存在。
            _, view, reason = LEARNING.roleplay_respond(learning, sid, text, seq,
                                                        int(time.time()), random.Random())
            if view is None:
                self._send({"error": "cannot apply this turn", "reason": reason or "bad_session"},
                           400)
                return
            save_progress(user, p)
        # Role-play 目前沒有任何獎勵/資格政策，這裡仍走與其他活動相同的結算路徑以免日後漏接。
        delta = clampi(view.get("rewardAmount", 0)) + clampi(view.get("lessonRewardAmount", 0))
        newgold = econ_add_gold(user, delta) if delta else None
        resp = {"ok": True, "sessionId": sid, "activityId": view.get("activityId"),
                "result": view.get("result"), "hint": view.get("hint"),
                "prompt": view["prompt"], "turn": view["turn"], "passes": view["passes"],
                "completed": view["completed"]}
        if view["completed"]:
            resp.update(score=view.get("score"), pct=view.get("pct"),
                        qualifications=view.get("granted") or [],
                        rewarded=bool(view.get("rewarded")), gold=newgold,
                        lessonCompleted=bool(view.get("lessonCompleted")),
                        lessonCompletedNow=bool(view.get("lessonCompletedNow")))
        self._send(resp)

    # 唯讀的整課進度：哪些課有權威完成政策、已完成了哪些、還缺哪些活動。不含答案鍵/批改設定/獎勵細節。
    def _handle_learning_progress(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        with acct_lock:
            p = load_progress(user)
        self._send(LEARNING.progress_view(p.get("learning") or {}))

    # 玩家經濟：POST 設定（pilot：信任前端戰果，僅夾範圍）
    def _handle_economy_set(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        with terr_lock:
            region_pop = user_region_pop(load_territory_store(), user)
        with econ_lock:
            store = load_econ_store()
            e = econ_get(store, user, time.time(), region_pop)
            # 人口改為伺服器管理 → 前端不再直接設定 population（招募已不扣人口）
            if "troops" in d:
                e["troops"] = _norm_troops(d.get("troops"))   # 前端回傳分兵種的兵力池
            save_econ_store(store)
            pop, troops, gold = e["population"], e["troops"], e["gold"]
        self._send({"ok": True, "population": pop, "troops": troops, "troopsTotal": troops_total(troops), "gold": gold})

    def _room_view(self, code, r, user):
        # 給前端(大廳/面板)的房間摘要
        ais = r.get("ais") or []
        return {
            "code": code, "map": r.get("map"), "started": bool(r.get("started")),
            "host": r.get("host", ""), "isHost": (r.get("host", "") == user),
            "joined": (user in (r.get("members") or [])),
            "players": len(r.get("members") or []),
            "ais": len(ais), "difficulty": (ais[0].get("difficulty") if ais else "normal"),
            "capacity": clampi(r.get("capacity", ROOM_MAX_PLAYERS), 1, ROOM_MAX_PLAYERS),
            "maxStudents": clampi(r.get("maxStudents", 40), 1, 500),
            "startPop": clampi(r.get("startPop", ECON_START_POP)),
            "startGold": clampi(r.get("startGold", 0)),
            "startTroops": clampi(r.get("startTroops", ECON_START_TROOPS)),
            "resources": r.get("resources") or res_from_values(r.get("startPop", 0), r.get("startGold", 0), r.get("startTroops", 0)),
        }

    # 單一房間狀態：任何人可讀(要知道地圖/是否開始/人數)。room 由 ?room= 決定。
    def _handle_room(self):
        user = token_user(self._token())
        r = load_room()
        v = self._room_view(current_room(), r, user)
        v["aiNames"] = sorted(room_ai_names(r))
        v["aiList"] = [{"name": a.get("name"), "difficulty": a.get("difficulty")} for a in (r.get("ais") or [])]
        self._send(v)

    # 大廳資料：全域世界摘要 + 自己建立的私人房 + 目前所在房間。私人房不公開列出(靠代碼加入)。需登入。
    def _handle_rooms_list(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        keep = current_room()
        set_room(GLOBAL_ROOM)
        gview = self._room_view(GLOBAL_ROOM, load_room(), user)
        mine = None
        mycode = find_user_room(user)
        if mycode:
            set_room(mycode)
            mine = self._room_view(mycode, load_room(), user)
        set_room(keep)
        self._send({"global": gview, "mine": mine, "current": get_user_room(user)})

    # 建立房間：隨機 hash 代碼、host=自己。一人一間 → 已有就回傳原本那間。需登入。
    def _handle_room_create(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        existing = find_user_room(user)
        if existing:
            set_room(existing)
            self._send({"ok": True, "code": existing, "room": self._room_view(existing, load_room(), user), "existing": True})
            return
        with room_lock:
            code = gen_room_code()
            set_room(code)
            r = dict(ROOM_DEFAULTS)
            r.update({"ais": [dict(a) for a in ROOM_DEFAULTS["ais"]], "members": [],
                      "host": user, "started": False, "startedAt": 0})
            save_room(r)
        self._send({"ok": True, "code": code, "room": self._room_view(code, r, user), "existing": False})

    # 進入某房間：全域世界 GLOBAL 或私人房代碼。設為「目前所在房間」(一次只在一個)，首次進場發起始資源；
    # 之前待過的房間會被凍結保留(不清空)，回去可續玩。需登入。
    def _handle_room_enter(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        code = ((parse_qs(urlparse(self.path).query).get("room", [""]) or [""])[0]
                or (parse_qs(urlparse(self.path).query).get("code", [""]) or [""])[0]
                or d.get("code") or d.get("room") or "").strip().upper()
        if is_global(code):
            code = GLOBAL_ROOM
            ensure_global_room()
        elif not code or code not in set(list_rooms()):
            self._send({"error": "Room not found"}, 404)
            return
        set_room(code)
        r = load_room()
        if not is_global(code) and not r.get("started"):
            self._send({"error": "That room hasn't started yet"}, 409)
            return
        if not room_admit(user):
            self._send({"error": "Room is full", "roomFull": True}, 403)
            return
        # 首次進場即依房間設定發放起始資源(econ_get 會種新玩家；老玩家沿用凍結的資料)
        with econ_lock:
            store = load_econ_store()
            econ_get(store, user, time.time())
            save_econ_store(store)
        set_user_room(user, code)                  # 記錄「目前所在房間」(單一)
        self._send({"ok": True, "code": code, "map": r.get("map"),
                    "host": r.get("host", ""), "global": is_global(code)})

    # 離開競賽房間 → 回大廳/練習模式(不在任何房間)。凍結保留原房資料。需登入。
    def _handle_room_leave(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        set_user_room(user, "")
        self._send({"ok": True})

    # 開始一局：把設定存到自己建立的房間 + 重置該房世界(領地/經濟/事件)。沒房就先建一間。需登入。
    def _handle_room_start(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        code = find_user_room(user)
        with room_lock:
            if not code:
                code = gen_room_code()
            set_room(code)
            d = self._body_json()
            capacity = clampi(d.get("capacity", ROOM_MAX_PLAYERS), 1, ROOM_MAX_PLAYERS)  # 總人數(含 AI)最高 8
            # AI：接受 ais 清單，或 aiCount + difficulty。至少保留 1 個真人席 → AI ≤ capacity-1
            diff = str(d.get("difficulty", "normal")).lower()
            if diff not in AI_DIFF:
                diff = "normal"
            if isinstance(d.get("ais"), list):
                diffs = []
                for a in d["ais"]:
                    ad = str((a or {}).get("difficulty", diff)).lower()
                    diffs.append(ad if ad in AI_DIFF else diff)
            else:
                diffs = [diff] * clampi(d.get("aiCount", 1), 0, ROOM_MAX_PLAYERS)
            diffs = diffs[:max(0, capacity - 1)]
            ais = [{"name": "AI " + str(i + 1), "difficulty": diffs[i]} for i in range(len(diffs))]
            max_students = max(1, capacity - len(ais))     # 真人上限 = 總人數 − AI 數
            # 起始資源：low / medium / high 三檔
            res = str(d.get("resources", "")).lower()
            if res not in RES_PRESETS:
                res = RES_DEFAULT
            pop, gold, troops = RES_PRESETS[res]
            r = {
                "map": clean_txt(d.get("map") or "Pre-A1", 16),
                "ais": ais, "capacity": capacity,
                "resources": res, "startPop": pop, "startGold": gold, "startTroops": troops,
                "maxStudents": max_students,
                "members": [], "host": user, "started": True, "startedAt": int(time.time()),
            }
            save_room(r)
        # 重置世界：清空領地、經濟(玩家下次進來會依新設定重發)、事件牆(catalog 保留)
        with terr_lock:
            save_territory_store({})
        with econ_lock:
            save_econ_store({})
        with ev_lock:
            save_events([])
        self._send({"ok": True, "code": code, "room": self._room_view(code, r, user)})

    # 結束一局(停止 AI 行動)。需登入。作用在自己建立的房間。
    def _handle_room_stop(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        code = find_user_room(user)
        if not code:
            self._send({"error": "You have no room"}, 404)
            return
        set_room(code)
        with room_lock:
            r = load_room()
            r["started"] = False
            save_room(r)
        self._send({"ok": True, "code": code})

    def log_message(self, *args):
        pass  # 安靜


if __name__ == "__main__":
    migrate_accounts()      # 舊版單檔結構 -> 拆檔（只跑一次有效果）
    try:                    # 領地目錄(靜態、唯讀)：開機載入 + 驗證，只記錄不致命
        from territory_catalog import catalog as _terr_catalog
        _terr_catalog.load()
        _errs = _terr_catalog.validate()
        print("[territory-catalog]", _terr_catalog.count_per_map(),
              "total", len(_terr_catalog.territories), "errors", len(_errs))
        for _e in _errs[:10]:
            print("  -", _e)
    except Exception as _ex:
        print("[territory-catalog] load skipped:", _ex)
    ensure_global_room()    # 常駐世界(全域房間)：不存在就建立
    threading.Thread(target=ai_loop, daemon=True).start()   # 電腦 AI 帝國：背景自動擴張/攻擊
    threading.Thread(target=conscript_loop, daemon=True).start()   # 徵兵制：每小時自動買兵
    ThreadingHTTPServer(("127.0.0.1", 5000), Handler).serve_forever()
