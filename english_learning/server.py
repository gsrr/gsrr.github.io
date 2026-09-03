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
                  economy as game_economy, recruitment as game_recruit, technology as game_tech,
                  frontier as game_frontier, regions as game_regions)
from learning import api as learning_api                                                   # 學習領域(與遊戲領域分離)

# ---- Phase 10A.3: ONE conquest map ------------------------------------------------------------
# The game has a single playable surface. This is GAME configuration: it is not derived from a
# course, a CEFR level, a lesson, a campaign or player progress, and no request can widen it.
# Non-World maps (taiwan / taipei / china) stay in world-data as dormant data — catalogued and
# renderable, but not part of the active conquest surface.
GAME_WORLD_MAP_ID = "world"


def allowed_game_maps():
    """The map ids conquest operations may touch. One entry today; still a set so that opening a
    second surface later is a data/config change rather than a rewrite of every call site."""
    return {GAME_WORLD_MAP_ID}


# ===== Phase 14A.6: the ONE canonical answer to "what does each participant hold here?" =====
# Ranking's "Territories Held" used to be `+= 1` for every store entry with an owner, which counted
# things that are not territories of the game being played:
#
#   * off-map catalogue territories -- the catalogue holds 318 ids but allowed_game_maps() is
#     {"world"}, so a `china:pAH` left in an older store counted;
#   * legacy keys canonize_keys() cannot resolve (a course filename such as "A1/002.json") -- it
#     deliberately PRESERVES those rather than dropping data, so they counted too.
#
# Measured before the fix: a store holding world:ad + china:pAH + "A1/002.json" reported 3.
# The count and the holdings list are now derived from this ONE helper, so they cannot drift, and
# the filter is the existing playable-map authority -- no second catalogue.
def room_holdings(tstore):
    """{owner: [{"id", "name", "pop"}, ...]} for the CURRENT ROOM's playable World territories only,
    ordered by player-facing name. Owners with no playable ground do not appear.

    This is the ONE answer to "what does each participant hold in this room", and every World
    ownership-derived metric is taken from it: Territories Held, the holdings list, the Empire
    Population territory contribution, and /api/territory's per-owner counts. Deriving them from one
    set is what stops them disagreeing about which records qualify.

    `pop` is aggregation input, not part of the client contract -- public_holdings() projects it out.
    """
    playable = set(playable_territory_ids())
    out = {}
    for tid, h in (tstore or {}).items():
        if not isinstance(h, dict):
            continue
        owner = h.get("owner")
        if not owner or tid not in playable:
            continue
        meta = (terr_catalog.territories.get(tid) if terr_catalog else None) or {}
        out.setdefault(owner, []).append({"id": tid, "name": meta.get("displayName") or tid,
                                          "pop": clampi(h.get("pop", 0))})
    for lst in out.values():
        lst.sort(key=lambda t: (t["name"].lower(), t["id"]))
    return out


def public_holdings(held):
    """The client contract: identity and a player-facing name, and nothing else."""
    return [{"id": t["id"], "name": t["name"]} for t in (held or [])]


def holdings_population(held):
    """The territory half of Empire Population, over the SAME records that count as held."""
    return sum(clampi(t.get("pop", 0)) for t in (held or []))


def playable_territory_ids():
    """Every canonical id on the active game map. Phase 10B needs the FULL set, not the store's keys:
    a territory nobody has touched has no store entry, and that absence is precisely what makes it
    neutral, so 'is any territory still claimable?' cannot be answered from the store alone."""
    if not terr_catalog:
        return []
    allowed = allowed_game_maps()
    if not terr_catalog.loaded:
        terr_catalog.load()
    return [tid for tid, t in terr_catalog.territories.items() if t.get("mapId") in allowed]


def territory_on_active_map(territory_id):
    return bool(terr_catalog) and terr_catalog.map_of(territory_id) in allowed_game_maps()


# Phase 10A retired LEVEL_PRIMARY_MAP / allowed_maps_for_level(). They mapped a CEFR level id
# ("Pre-A1"/"A1"/"A2"/"B1") to one canonical mapId and gated territory claims to it. A learning level
# now has ZERO authority over game-map eligibility. The room's `map` field survives as compatibility
# and display metadata (room listings, the lobby subtitle) and controls nothing.
# terr_catalog.child_maps() stays -- it is the catalog's own parent/child accessor, for map hierarchy.


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


# ---- Phase 8A.1 — explicit vs implicit room -----------------------------------
# `?room=LOBBY` and a MISSING room parameter both resolve to LOBBY, so the fallback
# is invisible to a handler that only reads current_room(). A mutation must be able
# to tell them apart: an explicit LOBBY is a legitimate target, an implicit one is a
# client that lost its room. The distinction is a property of the REQUEST, so it is
# recorded once, here, at the only point a client-supplied room enters the process,
# and is deliberately NOT touched by the internal set_room() calls that background
# loops and room-lifecycle handlers use to walk from room to room.
def set_request_room(raw):
    _req.room_explicit = bool((raw or "").strip())
    set_room(raw)


def room_was_explicit():
    return bool(getattr(_req, "room_explicit", False))


def request_room_param(path):
    return (parse_qs(urlparse(path).query).get("room", [""]) or [""])[0]


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
# Phase 12B.1: inference stays SERIALISED. faster-whisper holds one CTranslate2 model instance here
# and the server is a ThreadingHTTPServer, so several children pressing Record land in different
# threads on the same model. There is no evidence in this repository that concurrent transcribe() on
# a shared instance is safe, so the lock is kept deliberately -- see docs/stt-availability.md. The
# cost is throughput: read-alongs are graded one at a time.
_infer_lock = threading.Lock()

# ---- STT readiness (Phase 12B.1) -------------------------------------------------------------
# TRI-STATE, and the third state matters:
#   None  -- never probed. The lazy path decides, exactly as before. This is what `import server`
#            leaves behind, so unit tests that replace transcribe() are completely unaffected and
#            no test ever loads a multi-hundred-MB model.
#   True  -- a startup probe loaded the model successfully.
#   False -- a startup probe RAN and FAILED. Only then does /api/stt refuse up front, which is the
#            whole point: a broken deployment is discovered at boot, not by the first child to press
#            Record.
_stt_ready = None
_stt_ready_detail = ""

# How many requests may be waiting for the inference lock before the server says "busy". Without a
# bound, a class pressing Record at once parks one thread per child on _infer_lock, each holding its
# audio in memory for as long as the queue takes to drain. This does not make inference faster; it
# stops the queue growing without limit.
STT_MAX_WAITING = int(os.environ.get("STT_MAX_WAITING", "4"))
_stt_waiting = 0
_stt_waiting_lock = threading.Lock()


def stt_warmup():
    """Load the model NOW and record whether it worked. Called from __main__ only, never on import."""
    global _stt_ready, _stt_ready_detail
    try:
        get_model()
        _stt_ready, _stt_ready_detail = True, ""
    except Exception as exc:                     # missing package, missing model, bad WHISPER_MODEL
        _stt_ready, _stt_ready_detail = False, type(exc).__name__
    return _stt_ready


def stt_status():
    """Readiness for operators. Deliberately free of paths, model names and stack traces."""
    return {"probed": _stt_ready is not None, "available": _stt_ready is not False,
            "reason": _stt_ready_detail if _stt_ready is False else ""}


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
    # Phase 7F.2: `passcnt` is no longer normalised, served or read. Legacy values already sitting in
    # saved economy files are ignored in place — no migration, no rewrite, no deletion.
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
PASS_GOLD = game_config.PASS_GOLD                   # Phase 7C.2: 關卡活動(quiz3) 的小額確認獎勵
# 遊戲設定只認中性的經濟金額(MASTERY_GOLD)；「整課精通」這個學習概念只存在於這一行的對應關係，
# 由 server.py 把它餵給 Learning Domain 的 amountKey。game/ 永遠不認識課程詞彙。
LESSON_MASTERY_GOLD = game_config.MASTERY_GOLD      # 整課精通(Rule A)的主要獎勵
DEFEND_GOLD = game_config.DEFEND_GOLD               # 防守成功 +50 金幣
# Phase 3A：後端權威地重新批改課程活動時，讀取「與前端相同」的課程 JSON(答案鍵)。容器內內容在
# /var/www/html(Dockerfile 設 CONTENT_ROOT)；本機/測試預設為 server.py 所在的專案根目錄。
CONTENT_ROOT = os.environ.get("CONTENT_ROOT") or os.path.dirname(os.path.abspath(__file__))
# Learning Domain 單一入口。獎勵「金額」在這裡由遊戲設定注入(內容包只能指名 policy，不能指定金額 §15)。
LEARNING = learning_api.LearningService(content_root=CONTENT_ROOT,
                                        reward_amounts={"PASS_GOLD": PASS_GOLD,
                                                        "LESSON_MASTERY_GOLD": LESSON_MASTERY_GOLD})
ATTACK_FAIL_GOLD = game_config.ATTACK_FAIL_GOLD     # 攻打失敗 −50 金幣
REENTRY_GOLD_COST = game_config.REENTRY_GOLD_COST   # Phase 10B: 零領地重返的一次性金幣代價
REENTRY_CANDIDATES = game_config.REENTRY_CANDIDATES # 伺服器提供幾個落腳點
# Phase 8B.2: these were duplicated LITERALS here and in game/config.py. Two copies of a price is
# one copy too many — the 8B.2 rebalance changed config.py and this file silently kept the old
# numbers, which game_domain_test.py caught. They are aliases now, exactly like PASS_GOLD above, so
# game/config.py is the single source of every balance constant.
# Phase 8F.3: DEFEND_GOLD / ATTACK_FAIL_GOLD were the last two literals this comment already claimed
# were aliases. They are aliases now too, so the claim is finally true for every balance constant.
# 蓋建築的金幣花費：兵工廠(科技) + 三種生產建築
BUILD_COST = game_config.BUILD_COST
TECH_TRACKS = ("atk", "def")                       # 鍛造(+攻) / 鎧甲(+防)
TECH_COST = game_config.TECH_COST                  # 第 1/2/3 級花費
TECH_MAX = game_config.TECH_MAX
# 招募：每名兵的金幣成本、該兵種需要哪棟建築、每次招募的數量(加進該領地守軍)
UNIT_COST = game_config.UNIT_COST
UNIT_BUILDING = game_config.UNIT_BUILDING
RECRUIT_BATCH = game_config.RECRUIT_BATCH
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


# 「這個擁有者是不是 AI？」的唯一權威判斷。/api/room/start 把房內 AI 命名為 "AI 1".."AI 7"，所以只比對
# AI_OWNER 會漏掉每一個真實房間的 AI(Phase 8F.3 修正的缺陷)。名單 = 房間名冊 ∪ {預設名, 舊中文名}，
# 與前端 isAiOwner() 完全一致；舊資料/ai_move() 預設參數仍可能留下 AI_OWNER，因此兩者都要認。
def is_ai_owner(name, names=None):
    if not name:
        return False
    if name == AI_OWNER or name == AI_OWNER_LEGACY:
        return True
    return name in (room_ai_names() if names is None else names)


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
                # 與真人同一條 Game-Domain 規則：擁有權/相鄰/駐軍/戰鬥完全相同。Phase 10A.3R 之後
                # 連「學習資格」這個差別也沒有了(真人同樣不受資格限制)；require_qualifications=False
                # 保留為明確的無效參數，讓這條 AI 路徑不必因為簽名而改動。
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
        if logged[0] == "attack_fail" and logged[2] and not is_ai_owner(logged[2], ai_names):
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
    ai_names = room_ai_names()                     # 先讀名冊(load_room 不取鎖)，避免在鎖內做檔案 I/O
    with terr_lock:
        store = load_territory_store()
        with econ_lock:
            estore = load_econ_store()
            t_dirty = e_dirty = False
            # 1) 各領地徵兵 → 加進該區守軍，花擁有者金幣池(只花金幣，不扣人口)。人口不再自動成長。
            for f, h in store.items():
                if not (isinstance(h, dict) and h.get("owner") and not is_ai_owner(h["owner"], ai_names)):
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


# ===== Phase 12B.1.2 — authoritative class membership =====
# Before this phase there was no server-provable relationship between a student ACCOUNT and a class.
# A teacher's roster was a dict keyed by DISPLAY NAME inside the teacher's own progress file, and
# /api/class/sync authenticated the class CODE only -- so an unauthenticated client that knew a code
# could write any name into any teacher's roster (demonstrated: 'NotMyStudent' and 'STUDENT1' were
# injected into a teacher's dashboard with no token at all). Names are not identities, and a code is
# not authority.
#
# The canonical relation now lives on the STUDENT'S OWN ACCOUNT:
#
#     db["users"][student]["joinedClass"]   = <class code>
#     db["users"][student]["joinedClassAt"] = <epoch seconds>
#
# and ownership is derived through the existing code index:
#
#     class code --> db["codes"][code] --> owning teacher account
#
# Nothing is trusted from the client except the code the student typed, which is validated against
# that index. A display name is presentation only and never decides which account joined.


def class_owner_of(db, code):
    """The account that owns a class code, or None. The single derivation of class ownership."""
    c = (code or "").strip().upper()
    if not c:
        return None
    owner = (db.get("codes") or {}).get(c)
    if not owner or owner not in (db.get("users") or {}):
        return None                      # a dangling code index entry is not authority
    return owner


def class_membership_of(db, student_account):
    """(code, owning teacher) for an account's authoritative membership, or (None, None)."""
    u = (db.get("users") or {}).get(student_account)
    if not u:
        return None, None
    code = u.get("joinedClass")
    if not code:
        return None, None
    return code, class_owner_of(db, code)


def may_manage(teacher_account, student_account, db=None):
    """THE canonical answer to "may this teacher act on this student?".

    Derived only from authoritative account state -- never from a roster, a display name, or any
    client-supplied field. Phase 12B.2 must reuse this rather than compare code strings itself.
    """
    if not teacher_account or not student_account:
        return False
    # Teachers and students share one account namespace and EVERY account owns a class code, so an
    # account could join its own class. Self-management would let a learner authorise themselves,
    # which is exactly what an accessibility accommodation must never allow.
    if teacher_account == student_account:
        return False
    if db is None:
        db = load_accounts()
    if teacher_account not in (db.get("users") or {}):
        return False
    _code, owner = class_membership_of(db, student_account)
    return owner is not None and owner == teacher_account


def class_members_of(teacher_account, db=None):
    """Every account whose authoritative membership points at this teacher's class."""
    if db is None:
        db = load_accounts()
    out = []
    for acct in (db.get("users") or {}):
        if may_manage(teacher_account, acct, db):
            out.append(acct)
    return sorted(out)


# ===== Phase 12B.2 — Read Along input mode =====
# All 57 lessons require Read Along for mastery, and Read Along is scored from speech. A learner with
# no microphone, a denied permission, an unsupported device or a speech-recognition accessibility
# need therefore cannot reach authoritative mastery at all.
#
# The accommodation changes the INPUT MODALITY only:
#
#     speech : audio -> transcribe() -> stt_scoring.score_sentence -> record_read_along()
#     typed  : typed text            -> stt_scoring.score_sentence -> record_read_along()
#
# Both satisfy the SAME required Read Along activity, through the same scorer, the same 80% mark and
# the same completion/reward settlement. Nothing about the curriculum changes: no requiredActivityIds
# edit, no new activity id, no threshold change, no reward change.
#
# What is stored is the permitted input mode and who set it -- never a diagnosis, a disability, a
# medical reason or a justification. The server has no use for any of that.
READ_ALONG_MODES = ("speech", "typed")


def read_along_mode_of(account, db=None):
    """The permitted Read Along input mode for an account. Absent field == "speech", so every
    existing account keeps today's behaviour with no migration."""
    if db is None:
        db = load_accounts()
    u = (db.get("users") or {}).get(account) or {}
    return "typed" if u.get("readAlongMode") == "typed" else "speech"


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


# Phase 4D §21: the unambiguous lesson-status fields. All derived server-side from the trusted
# registry + authoritative score stores; a client cannot submit or influence any of them.
_LESSON_STATUS_FIELDS = ("currentPolicySatisfied", "historicallyCompleted", "activePolicyVersion",
                         "activePolicyCompleted", "activePolicyCompletedAt", "firstCompletedAt",
                         "firstCompletedPolicyVersion", "missingActivityIds", "roundedPct")


def _lesson_status_fields(out):
    return {k: out[k] for k in _LESSON_STATUS_FIELDS if k in out}


# Phase 5F：第一個正式獎勵是「純外觀(cosmetic)」。只回傳前端顯示得到的東西——這次是否真的發放、
# 發了哪一個 itemId——不外洩 ledger 內部(grantKey/grantedAt/金額)。itemId 只有在「這一次」真的
# 授予時才存在(見 learning/api.py grant_reward)，所以前端不需要自己判斷重複。
# Phase 7C.2a：金額也一起回傳。這不是「洩漏」——這是學習者剛剛賺到的錢，介面要能誠實說出數字，
# 而不是含糊的「+gold」。金額仍然完全由後端決定(遊戲設定 → 政策白名單)，client 無法影響。
# ledger 內部(grantKey/grantedAt)依舊不外流。
_REWARD_FIELDS = ("lessonRewardType", "lessonRewardItemId", "rewardAmount", "lessonRewardAmount",
                  "courseId", "courseCompleted",
                  "courseCompletedNow", "courseRewardType", "courseRewardItemId")


def _reward_fields(out):
    return {k: out[k] for k in _REWARD_FIELDS if k in out}


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- Phase 8A.1 — room-scoped MUTATIONS must name their room --------------
    # Every path below writes room-scoped world state: territory, room economy, or
    # room events. The four learning endpoints are MIXED — they settle ACCOUNT-scoped
    # learning progress and also credit the CURRENT ROOM's economy — which is exactly
    # why they belong here: a once-only reward settled without a room paid its gold
    # into LOBBY while the learner was elsewhere, and the reward cannot be earned twice.
    #
    # Deliberately NOT protected:
    #   * reads (/api/economy, /api/territory, /api/room, /api/events, /api/leaderboard)
    #     keep the legacy fallback — this phase is about mutation targeting. GET
    #     /api/economy does write, but only lazy accrual/seeding of whatever room it
    #     reads, never a client-directed change.
    #   * room lifecycle (/api/room/{create,enter,join,start,stop}, /api/rooms) — these
    #     CHOOSE a room and take it from the body, so requiring an active room first
    #     would make it impossible to ever enter one.
    #   * account-scoped writes (/api/sync, /api/student/save, register/login…) — no
    #     room state is involved.
    ROOM_MUTATIONS = frozenset({
        "/api/economy/set", "/api/event",
        "/api/territory/claim", "/api/territory/attack", "/api/territory/build",
        "/api/territory/recruit", "/api/territory/research", "/api/territory/release",
        "/api/territory/conscript",
        # Phase 11A.1: re-entry spends gold and troops and takes ground, so it belongs here with
        # every other territory mutation. It was omitted when Phase 10B added it, which let a
        # room-less POST fall through to the implicit default room instead of failing closed --
        # the exact stale-tab case Phase 8A.1 introduced this table to stop.
        "/api/territory/reentry",
        "/api/learning/attempt", "/api/learning/matching/attempt",
        # Phase 12B.2: typed Read Along settles gold exactly like the speech path, so it belongs in
        # the same room-scoped guard.
        "/api/learning/read-along/typed",
        "/api/learning/roleplay/respond", "/api/stt",
    })

    # Fails closed on a missing room. Called from the dispatcher BEFORE any handler
    # runs, so a rejection happens before grading, before record_attempt() finalises a
    # reward ledger, and before any territory/economy write — nothing is consumed and
    # the request is safe to retry verbatim once the room is supplied. 400 (not 401/403)
    # because this is a malformed request, not an authorisation failure.
    def _require_room(self):
        if room_was_explicit():
            return True
        # An unauthenticated request cannot mutate anything — its handler rejects it with 401 —
        # so authorisation keeps precedence and a bad token still reads as a bad token rather
        # than as a missing room. Deferring here costs no safety and keeps both errors truthful.
        if not token_user(self._token()):
            return True
        self._send({"error": "Room required", "reason": "room_required"}, 400)
        return False

    def do_GET(self):
        path = self.path.split("?")[0]
        set_request_room(request_room_param(self.path))
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
        elif path == "/api/territory/reentry":
            self._handle_reentry_state()
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
        set_request_room(request_room_param(self.path))
        if path in self.ROOM_MUTATIONS and not self._require_room():
            return                      # Phase 8A.1: fail closed before ANY state change
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
        elif path == "/api/territory/attack":
            self._handle_territory_attack()
        elif path == "/api/territory/reentry":
            self._handle_reentry()
        elif path == "/api/territory/conscript":
            self._handle_territory_conscript()
        elif path == "/api/economy/set":
            self._handle_economy_set()
        elif path == "/api/learning/attempt":
            self._handle_learning_attempt()
        elif path == "/api/learning/read-along/typed":
            self._handle_read_along_typed()
        elif path == "/api/accommodation/read-along":
            self._handle_accommodation_read_along()
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
        # Phase 12B.1: if the startup probe already established that the model cannot load, say so
        # immediately instead of making every learner wait for the same failure. _stt_ready is None
        # when nothing probed (tests, and any embedding that skips warm-up), and that path is
        # unchanged: the transcribe() call below decides.
        if _stt_ready is False:
            self._send({"error": "speech recognition unavailable", "reason": "stt_unavailable"}, 503)
            return
        # Bounded admission. Inference is serialised, so an unbounded number of waiters is a memory
        # and thread leak, not a queue. Refusing is honest and leaves the learner able to retry.
        global _stt_waiting
        with _stt_waiting_lock:
            if _stt_waiting >= STT_MAX_WAITING:
                self._send({"error": "speech scoring is busy", "reason": "stt_busy"}, 503)
                return
            _stt_waiting += 1
        try:
            text = transcribe(audio, target)
        except Exception:
            # §14: an outage must never become authoritative success. No score, no completion, no
            # qualification, no reward. Internal detail is not leaked to the client.
            self._send({"error": "speech recognition unavailable", "reason": "stt_unavailable"}, 503)
            return
        finally:
            with _stt_waiting_lock:
                _stt_waiting -= 1
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
        delta = (clampi(out.get("rewardAmount", 0)) + clampi(out.get("lessonRewardAmount", 0))
                 + clampi(out.get("courseRewardAmount", 0)))
        newgold = econ_add_gold(user, delta) if delta else None
        self._send({"transcript": text, "target": out["target"], "authoritative": True,
                    "activityId": out["activityId"], "sentenceIndex": out["sentenceIndex"],
                    "score": out["score"], "improved": out["improved"],
                    "totalSentences": out["totalSentences"],
                    "activityPct": out["activityPct"], "activityPassed": out["activityPassed"],
                    "qualifications": out["granted"], "rewarded": out["rewarded"], "gold": newgold,
                    "lessonCompletedNow": bool(out.get("lessonCompletedNow")),
                    **_reward_fields(out)})

    # Phase 12B.2: typed Read Along. This is NOT a second mastery engine -- record_read_along()
    # already takes a TRANSCRIPT and does everything authoritative itself: it resolves the target
    # sentence from lesson content, scores it with stt_scoring.score_sentence, keeps best-per-sentence
    # retry semantics, and on crossing PASS_MARK routes through record_attempt for grants and the
    # reward policy. So the only difference from speech is where the text came from.
    #
    # It is a separate route from /api/stt on purpose: typed mode must never touch the audio path, so
    # it cannot request a microphone, cannot invoke transcribe(), and cannot depend on faster_whisper
    # or ffmpeg being installed.
    def _handle_read_along_typed(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in", "reason": "auth_required"}, 401)
            return
        if read_along_mode_of(user) != "typed":
            # hiding the text box is not security: the endpoint itself refuses
            self._send({"error": "Typed Read Along is not enabled for this account",
                        "reason": "typed_not_enabled"}, 403)
            return
        d = self._body_json()
        aid = (d.get("activityId") or "").strip()
        if not LEARNING.is_read_along(aid):
            self._send({"error": "not a read-along activity", "reason": "not_scorable"}, 400)
            return
        sidx_raw = str(d.get("sentenceIndex", "")).strip()
        target, _total = LEARNING.read_along_target(aid, sidx_raw)
        if target is None:
            self._send({"error": "unknown sentence for this activity",
                        "reason": "bad_sentence"}, 400)
            return
        text = d.get("text")
        if not isinstance(text, str):
            self._send({"error": "no text", "reason": "no_text"}, 400)
            return
        with acct_lock:
            p = load_progress(user)
            learning = p.setdefault("learning", {})
            # The client's text is EVIDENCE, never a verdict: any score/passed/reward field in the
            # body is simply not read. The server scores what was typed against its own sentence.
            _, out = LEARNING.record_read_along(learning, aid, sidx_raw, text[:2000], int(time.time()))
            if out is None:
                self._send({"error": "unknown sentence for this activity",
                            "reason": "bad_sentence"}, 400)
                return
            save_progress(user, p)
        delta = (clampi(out.get("rewardAmount", 0)) + clampi(out.get("lessonRewardAmount", 0))
                 + clampi(out.get("courseRewardAmount", 0)))
        newgold = econ_add_gold(user, delta) if delta else None
        self._send({"transcript": text[:2000], "target": out["target"], "authoritative": True,
                    "inputMode": "typed",
                    "activityId": out["activityId"], "sentenceIndex": out["sentenceIndex"],
                    "score": out["score"], "improved": out["improved"],
                    "totalSentences": out["totalSentences"],
                    "activityPct": out["activityPct"], "activityPassed": out["activityPassed"],
                    "qualifications": out["granted"], "rewarded": out["rewarded"], "gold": newgold,
                    "lessonCompletedNow": bool(out.get("lessonCompletedNow")),
                    **_reward_fields(out)})

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

    # Phase 12B.1.2: joining a class is an act by an AUTHENTICATED STUDENT ACCOUNT.
    #
    # Before: this endpoint took a class code and a dict of names, with no token at all. Anyone who
    # learned a code could write arbitrary roster entries into a teacher's dashboard. The code was
    # treated as authority and the names were treated as identities; neither is true.
    #
    # After: the token identifies the joining account, the code is validated against the code index,
    # membership is persisted on the JOINING ACCOUNT, and the roster entry is keyed by that account.
    # The client's `students` dict is ignored entirely for authority -- it named other people.
    def _handle_class_sync(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in", "reason": "auth_required"}, 401)
            return
        d = self._body_json()
        code = ((parse_qs(urlparse(self.path).query).get("code", [""]) or [""])[0]
                or d.get("code") or "").strip().upper()
        with acct_lock:
            db = load_accounts()
            owner = class_owner_of(db, code)
            if not owner:
                self._send({"error": "Invalid class code", "reason": "bad_class_code"}, 404)
                return
            if owner == user:
                # every account owns a code, so this is reachable; joining your own class would make
                # you your own manager, which may_manage() refuses anyway. Refuse it at the source.
                self._send({"error": "That is your own class code", "reason": "self_class"}, 400)
                return
            prev_code, prev_owner = class_membership_of(db, user)
            db["users"][user]["joinedClass"] = code
            db["users"][user]["joinedClassAt"] = time.time()
            save_accounts(db)
        # A move is authoritative the moment the account record changes; the roster copies follow so
        # the previous teacher stops listing a learner they no longer manage.
        if prev_owner and prev_code != code:
            with acct_lock:
                pp = load_progress(prev_owner)
                if (pp.get("members") or {}).pop(user, None) is not None:
                    save_progress(prev_owner, pp)
        label = str(d.get("displayName") or user)[:40]
        snap = d.get("progress")
        with acct_lock:
            p = load_progress(owner)
            members = p.setdefault("members", {})
            rec = members.get(user) or {}
            rec["displayName"] = label
            rec["joinedAt"] = rec.get("joinedAt") or time.time()
            if isinstance(snap, dict):
                rec["progress"] = snap          # the caller's OWN snapshot, never another account's
            members[user] = rec
            save_progress(owner, p)
        self._send({"ok": True, "joinedClass": code, "account": user})

    # Phase 12B.2: an educator sets a learner's Read Along input mode. Authorization is the
    # canonical may_manage() relation and nothing else -- not an account type (none exists), not the
    # role screen, not a display name, not roster contents, not possession of a class code. A learner
    # can never reach this for themselves, because may_manage() refuses manager == target.
    def _handle_accommodation_read_along(self):
        manager = token_user(self._token())
        if not manager:
            self._send({"error": "Not logged in", "reason": "auth_required"}, 401)
            return
        d = self._body_json()
        target = (d.get("account") or "").strip()
        mode = (d.get("mode") or "").strip()
        if mode not in READ_ALONG_MODES:
            self._send({"error": "Unknown mode", "reason": "bad_mode"}, 400)
            return
        with acct_lock:
            db = load_accounts()
            if target not in (db.get("users") or {}):
                self._send({"error": "Not allowed", "reason": "not_authorized"}, 403)
                return
            if not may_manage(manager, target, db):
                # deliberately the same answer as an unknown target: a refusal must not confirm
                # whether an account exists or which class it is in
                self._send({"error": "Not allowed", "reason": "not_authorized"}, 403)
                return
            u = db["users"][target]
            if mode == "typed":
                u["readAlongMode"] = "typed"
            else:
                u.pop("readAlongMode", None)          # back to the absent-field default
            u["readAlongModeBy"] = manager            # provenance for audit, not a reason
            u["readAlongModeAt"] = time.time()
            save_accounts(db)
        self._send({"ok": True, "account": target, "readAlongMode": mode})

    def _handle_dashboard(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        with acct_lock:
            db = load_accounts()
            code = (db["users"].get(user) or {}).get("code")
            p = load_progress(user)
            # Phase 12B.1.2: `members` is the AUTHORITATIVE roster -- every key is an account whose
            # own record points at this teacher's class, re-derived through may_manage() rather than
            # trusted from the stored copy. `students` is the pre-phase name-keyed data: it is kept
            # so no teacher loses history, but it is reported separately and marked non-authoritative
            # because those keys were never bound to an account and cannot be retro-fitted to one.
            authoritative = {}
            stored = p.get("members") or {}
            for acct in class_members_of(user, db):
                rec = dict(stored.get(acct) or {})
                authoritative[acct] = {"account": acct,
                                       "displayName": rec.get("displayName") or acct,
                                       "joinedAt": rec.get("joinedAt"),
                                       # Phase 12B.2: the mode for members this teacher is actually
                                       # authorized to manage (class_members_of re-derives that
                                       # through may_manage), so the control can show real state.
                                       "readAlongMode": read_along_mode_of(acct, db),
                                       "progress": rec.get("progress") or {}}
        self._send({"code": code, "members": authoritative,
                    "students": p.get("students", {}), "legacyStudents": True})

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

    # ---- 公開排行榜 ----
    # Phase 7F.3: the learning number here is the SERVER's own count of mastered lessons, not the
    # client-computed `sdata.stats.passed`. That field was a local Rule B average over localStorage
    # and was therefore forgeable by anyone; it reached this public endpoint verbatim. Ranking never
    # used it (the sort is population -> regions -> name) and the UI never showed it, so replacing
    # the source changes no ordering and no visible row — it only stops a forgeable number being
    # published as though it were progress. `avatar` still comes from sdata: it is cosmetic.
    # No new completion model: this reuses LEARNING.progress_view()'s activePolicyCompleted.
    @staticmethod
    def _mastered_lesson_count(progress):
        """Lessons this account has authoritatively mastered. Never raises, never trusts client data.

        Phase 7F.3: the ONE authoritative learning number the public leaderboard publishes. Counts
        rows whose ACTIVE policy version is completed — the same activePolicyCompleted the lesson UI
        shows — so there is exactly one meaning of "mastered" in the product.
        """
        try:
            view = LEARNING.progress_view((progress or {}).get("learning") or {})
        except Exception:
            return 0
        n = 0
        for row in (view.get("lessons") or {}).values():
            if row.get("authoritativeCompletionAvailable") and row.get("activePolicyCompleted"):
                n += 1
        return n

    # ===== Phase 14A.5: RANKING POPULATION IS THE WHOLE EMPIRE =====
    # This used to publish `estore[user]["population"]` alone -- the HOME BASE figure -- so a player
    # who had conquered half a continent ranked on their starting town. Meanwhile the client invented
    # AI rows whose population was the SUM of their territories, so one column meant two different
    # things depending on the row.
    #
    # The domain already had the answer: game.economy.calculate_passive_gold() earns on
    # (population + region_pop), i.e. the home base PLUS every owned territory. That is the empire,
    # and it is what a rank called Population must mean. Home base is a separate economy record, not
    # an entry in the territory store, so summing both counts it exactly once.
    #
    # AI players are built the same way (ai_econ gives them a base population and the same
    # region_pop gold), so their rows are produced HERE by the same formula instead of being
    # synthesised on the client. Everything is read from the CURRENT ROOM's stores; the sort keys
    # are unchanged.
    # Phase 14A.6: the territory half comes from the SAME playable holdings the count and the list
    # come from -- not from user_region_pop(), which sums every owned store entry. That helper feeds
    # passive Gold from 16 other call sites and is deliberately left exactly as it is; see the
    # report. Off-map catalogue entries and unresolvable legacy keys therefore no longer inflate the
    # rank, and Home Base -- a separate economy record, never a store entry -- is added exactly once.
    def _empire_population(self, name, held, estore, is_account):
        e = estore.get(name) if isinstance(estore, dict) else None
        if isinstance(e, dict):
            base = clampi(e.get("population", ECON_START_POP))
        else:
            # an account that has never played still shows its starting town; a non-account owner
            # (an AI that has not been given an economy yet) is credited with no base it does not have
            base = ECON_START_POP if is_account else 0
        return base + holdings_population(held)

    def _handle_leaderboard(self):
        with terr_lock:
            tstore = load_territory_store()
        # ONE ownership answer for this room: the rows, the counts and the lists all come from it,
        # so there is no second count to drift away from the list.
        holdings = room_holdings(tstore)
        owners = list(holdings.keys())
        with econ_lock:
            estore = load_econ_store()
        with acct_lock:
            db = load_accounts()
            out = []
            named = set()
            for user in db.get("users", {}):
                if user == "testaccount":
                    continue
                prog = load_progress(user)
                stats = (prog.get("sdata") or {}).get("stats") or {}
                named.add(user)
                held = holdings.get(user) or []
                out.append({"name": user, "avatar": stats.get("avatar", "👦"),
                            "population": self._empire_population(user, held, estore, True),
                            # `regions` keeps its name for API compatibility; in leaderboard
                            # semantics it means TERRITORIES HELD, and it is len(territories) so the
                            # number and the list can never disagree.
                            "regions": len(held), "territories": public_holdings(held),
                            "passed": self._mastered_lesson_count(prog), "level": 1})
            # every other owner holding ground in THIS room -- the AI empires, and any legacy owner
            # that is not an account. Same formula, so the Population column means one thing.
            for owner in owners:
                if owner in named:
                    continue
                h = next((v for v in tstore.values()
                          if isinstance(v, dict) and v.get("owner") == owner and v.get("avatar")), None)
                held = holdings.get(owner) or []
                out.append({"name": owner, "avatar": (h or {}).get("avatar") or "🤖",
                            "population": self._empire_population(owner, held, estore, False),
                            "regions": len(held), "territories": public_holdings(held),
                            "passed": 0, "level": 1})
        out.sort(key=lambda x: (-x["population"], -x["regions"], x["name"].lower()))
        self._send({"leaders": out[:50]})

    # ---- 占地盤：每個據點由「4 兵種 + 兵力」守備（攻方 4v4 打贏才換人）----
    TROOP_TYPES = ("cav", "archer", "inf", "spear")

    def _handle_territory(self):
        me = token_user(self._token())              # 戰霧：只有自己的領地才看得到守軍/科技
        ai_names = room_ai_names()
        with terr_lock:
            store = load_territory_store()
        # ===== Phase 13B: strategic classification, derived here and nowhere else =====
        # frontier / interior / isolated is computed by game.frontier from the two authoritative facts
        # this handler already holds -- ownership (this room's store) and adjacency (the catalog) -- and
        # is published READ-ONLY. It is stored nowhere: a saved classification would be wrong the
        # moment a neighbour changed hands, and combat changes neighbours.
        #
        # FOG OF WAR: it is attached ONLY to the requesting player's own territories, and the summary
        # counts describe only their own empire. "Is that enemy territory interior?" is a question
        # about someone else's holdings, and this endpoint does not answer it.
        #
        # NO GAMEPLAY EFFECT in 13B: nothing below reads this, and neither does can_attack, claim,
        # recruit, research, build, income, rewards, re-entry or the AI.
        def _owner_of(tid):
            rec = store.get(tid)
            return rec.get("owner") if isinstance(rec, dict) else None

        def _neighbours_of(tid):
            return terr_catalog.neighbors(tid) if terr_catalog else ()

        mine_ids = [f for f, h in store.items()
                    if isinstance(h, dict) and h.get("owner") and h.get("owner") == me]
        strategic = game_frontier.classify_all(me, mine_ids, _owner_of, _neighbours_of) if me else {}
        # ===== Phase 13C: region aggregation, over the SAME classifier =====
        # An AGGREGATION VIEW and nothing more: regions are not an ownership, combat, income, supply,
        # technology, building or army unit, and nothing below or elsewhere consults this.
        #
        # Membership is stable geography from the catalog (metadata.continent); the counts are derived
        # per request from ownership, exactly like the 13B classification they are built on. Neither is
        # stored. It is computed over the whole PLAYABLE map, not just the player's holdings, so a
        # region can honestly report "7 of 18 owned".
        #
        # `others` is a count only -- no identity, no strength, no garrison -- and it is derivable from
        # ownership the board already shows, so it leaks nothing new.
        def _meta_of(tid):
            return (terr_catalog.territories.get(tid) if terr_catalog else None) or {}

        # summarize() already treats a falsy player as "no holdings anywhere", so there is no
        # signed-out special case to branch on here.
        playable = playable_territory_ids()
        region_rows = game_regions.summarize(playable, me, _owner_of, _neighbours_of, _meta_of)
        # Phase 14A.6: `counts` is WORLD HOLDINGS BY OWNER, and it is taken from the same
        # room_holdings() authority the Ranking uses -- it used to be one increment per owned store
        # entry, so an off-map catalogue id or an unresolvable legacy key inflated the World banner
        # exactly as it inflated the rank. `holders` is deliberately NOT filtered: it is the map's
        # own painting/ownership payload and every other field here is unchanged.
        counts = {owner: len(held) for owner, held in room_holdings(store).items()}
        holders = {}
        for f, h in store.items():
            if not isinstance(h, dict):
                continue
            owner = h.get("owner")
            if owner and owner == me:               # 自己的領地：完整資訊
                holders[f] = {"owner": owner, "avatar": h.get("avatar", "👦"),
                              "troops": h.get("troops") or [], "pop": h.get("pop"),
                              "income": region_gold_income(h),
                              "buildings": h.get("buildings") or {}, "tech": h.get("tech") or {}, "mine": True,
                              "strategic": strategic.get(f),
                              "conscript": bool(h.get("conscript")), "conscriptBudget": clampi(h.get("conscriptBudget", 0))}
            else:                                   # 別人/AI 的領地：不透露兵力、兵種、科技
                holders[f] = {"owner": owner, "avatar": h.get("avatar", "👦"),
                              "pop": h.get("pop"), "hidden": True, "ai": owner in ai_names}
        self._send({"holders": holders, "counts": counts,
                    "strategicSummary": game_frontier.summarize(strategic),
                    "regions": region_rows,
                    # the closed-component caveat 13B surfaced, as a COUNT and nothing else: 13B proved
                    # `interior` means "every land neighbour is mine", never "connected to a useful
                    # front" and never "safe supply". Modelling connectivity is a later phase.
                    "regionNote": game_regions.structural_note(region_rows)})

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
        if not territory_on_active_map(f):
            # Phase 10A.3: only the active game map is playable. This replaces nothing that a course
            # controls -- the room's level is not consulted here and cannot widen or narrow the set.
            self._send({"error": "Territory is not on the active game map",
                        "reason": "inactive_map"}, 400)
            return
        # Phase 10A: a territory's GAME validity is established by the canonical catalog check
        # directly above, and by nothing else. This used to ALSO require the territory's map to match
        # the room's CEFR level (Pre-A1 -> taiwan, A1 -> china, A2/B1 -> world), answering
        # 400 "wrong_map" otherwise -- which made a LEARNING level the authority over which game map
        # a player could own territory on. Learning decides curriculum; the game decides the world.
        # Everything below still gates on GAME facts only: existence, active map, population,
        # ownership, troops and stamina -- Phase 10A.3R removed the learning-qualification gate from
        # this list as well. Room isolation is unaffected -- ownership lives in
        # /data/rooms/<CODE>/territory.json, so it never depended on this check.
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
        # Phase 7D-0：學習資格門檻在這裡才變成「伺服器權威」。在此之前，無主據點的資格檢查只存在於
        # 前端(passCount(file) > base)，所以任何 client 都能直接 POST /claim 拿下有門檻的地區。
        # 資格集合取自帳號的權威學習狀態；client 送來的任何東西(passcnt、pendingOccupy、完成回應、
        # 課程身分)一律不採信。在 terr_lock 之外先取得，維持全站鎖順序(acct → terr → econ)。
        # Phase 10A.3R: no learning qualification is read here any more — claiming is GAME state only.
        # 佔領只發生在「無主」據點：有主據點要先打贏(/api/territory/attack 後端權威地清成無主)才能佔領。
        # 後端強制此規則 → client 不能用 /claim 直接奪取敵方領地(繞過戰鬥)。只能佔無主或重部署自己的。
        with terr_lock:
            store = load_territory_store()
            prev = store.get(f) if isinstance(store.get(f), dict) else {}
            if prev.get("owner") and prev.get("owner") != user:   # 有主且非本人 → 必須先攻打
                self._send({"error": "Territory is held — attack it first", "reason": "held"}, 403)
                return
            # Phase 10A.3R retired the learning-qualification gate that stood here. Acquiring a
            # territory is a GAME decision: ownership, troops and the normal economy. Learning still
            # awards progress, mastery and Gold — it just no longer unlocks ground.
            if prev.get("owner") != user:
                # ---- Phase 8B.3: ACQUIRING a territory costs at least one real troop ----
                # A neutral claim used to accept an empty (or all-zero) garrison, so ownership — and
                # with it the territory's passive income — was free: all seven ungated Taipei
                # districts could be taken for 0 troops and 0 gold, worth ~110 gold/hour. The
                # minimum is deliberately ONE, not a round number: it makes acquisition a real
                # commitment out of the authoritative pool without becoming an economic barrier.
                # Placed BEFORE any mutation so a refusal costs nothing. `troops` is already sanitised above (bad types dropped, hp clamped >= 0),
                # so this counts what would actually be deployed, not what was asked for.
                # Deliberately NOT applied to redeploying a territory you already hold: leaving your
                # own ground undefended stays legal (see docs/current-game-rules.md).
                if sum(u["hp"] for u in troops) < 1:
                    self._send({"error": "Claim not allowed", "reason": "troops_required",
                                "minTroops": 1}, 400)
                    return
            keep = {}
            if prev.get("owner") == user:                # 重新部署自己的守軍 → 保留建築/科技/人口/徵兵設定
                keep = {"buildings": prev.get("buildings") or {}, "tech": prev.get("tech") or {}}
                for k in ("pop", "lastPop", "conscript", "conscriptBudget", "lastConscript"):
                    if k in prev:
                        keep[k] = prev[k]
            # ---- Phase 8B.1: the garrison is DEBITED from the authoritative troop pool ----
            # A claim used to accept whatever garrison the request declared and never touch the pool,
            # so it minted troops out of nothing. Troops may now only MOVE: a deployment costs the
            # pool exactly what it puts on the map. Redeploying a territory you already hold returns
            # its current garrison to the pool first, so the pool+garrisons total is conserved and
            # the existing "the rest stays in your pool" behaviour is preserved — the client used to
            # do this arithmetic itself, which is precisely why it was not binding.
            # Lock order is the established acct -> terr -> econ (identical to recruitment).
            with econ_lock:
                estore = load_econ_store()
                e = econ_get(estore, user, time.time(), user_region_pop(store, user))
                avail = {k: clampi(e["troops"].get(k, 0)) for k in TROOP_ALL}
                for u in (prev.get("troops") or []):      # redeploy: the old garrison comes home
                    if isinstance(u, dict) and u.get("type") in avail:
                        avail[u["type"]] += clampi(u.get("hp", 0))
                need = {}
                for u in troops:
                    need[u["type"]] = need.get(u["type"], 0) + clampi(u["hp"])
                short = {k: v - avail.get(k, 0) for k, v in need.items() if v > avail.get(k, 0)}
                if short:                                 # 兵力不足 → 一切狀態零變動(原子拒絕)
                    self._send({"error": "Not enough troops", "reason": "insufficient_troops",
                                "available": avail, "requested": need, "short": short}, 400)
                    return
                for k, v in need.items():
                    avail[k] -= v
                e["troops"] = avail
                save_econ_store(estore)
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

    # Phase 8F.1 REMOVED /api/territory/engage. It was a READ-ONLY pre-battle reveal from the old
    # client-authoritative chain: the server-authoritative /api/territory/attack returns the defender
    # order and tech itself, so no reachable flow had called it since the openOutpost migration. It
    # mutated nothing, but it was not harmless either -- it returned `troops` and `tech` for ANY
    # territory, which is exactly what _handle_territory withholds from other players (hidden: True).
    # Retiring it removes a dead route AND closes that fog-of-war bypass.

    # Phase 8E REMOVED /api/territory/attack-result. Phase 2A had already made it authoritative-free —
    # battle gold (attacker −ATTACK_FAIL_GOLD / defender +DEFEND_GOLD) moved inside
    # /api/territory/attack — and it survived only as a `{"ok": true, "legacy": true}` no-op so a stray
    # old client would not error. By Phase 8E nothing called it: its client helper (terrAttackResult)
    # had no callers either, and the canonical attack response already carries everything the UI
    # renders. A routed endpoint that settles nothing is a standing invitation to re-add a second
    # settlement path, so it is gone; POST now falls through to the 404 every unknown path gets.
    # There is NO post-battle settlement callback — /api/territory/attack settles completely.

    # Phase 2B — territorial conquest：攻擊必須「從自己的相鄰領地(source)出兵」打「敵方相鄰領地(target)」。
    #   出征兵取自 SOURCE 駐軍(不再是全域兵力池)；資格由 game.conquest.can_attack 權威判定(World-Domain 相鄰)。
    #   贏 → target 直接易主、生還者成為 target 新駐軍；輸 → 生還者退回 source 駐軍、守方保留。金幣規則不變。
    # HTTP 情境對照：source_not_owned → 403；其餘資格失敗 → 400，皆附穩定 reason。
    _ATTACK_STATUS = {"source_not_owned": 403}   # 其餘 reason 一律 400

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
            self._send({"error": "sourceTerritoryId is required (attack from a territory you own)",
                        "reason": "source_not_found"}, 400)
            return
        if not target:
            self._send({"error": "Unknown target territory", "reason": "target_not_found"}, 400)
            return
        # Phase 10A.3: both ends of an attack must sit on the active game map.
        if not territory_on_active_map(source) or not territory_on_active_map(target):
            self._send({"error": "Territory is not on the active game map",
                        "reason": "inactive_map"}, 400)
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
        # Phase 10A.3R: attack reads no learning state at all.
        with terr_lock:
            store = load_territory_store()
            elig = game_conquest.can_attack(user, source, target, squad, terr_catalog, store,
                                            player_qualifications=None, require_qualifications=False)
            if not elig.allowed:                         # 資格不符 → 一切狀態零變動(原子拒絕)
                resp = {"error": "Attack not allowed", "reason": elig.reason}
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
            if defender and defender != user and not is_ai_owner(defender):
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

    # ======================= Phase 10B: zero-territory re-entry =======================
    # A player who holds nothing on a fully-claimed map has NO legal conquest action: /claim answers
    # `held` on every territory and /attack needs an owned source. Re-entry is the one bounded
    # exception, and it is decided here, on the server, from GAME state only.
    #
    # What re-entry does NOT do: it does not weaken adjacency for anybody who owns ground (the
    # ordinary /attack path is untouched), it does not read any learning state, it does not mint
    # troops, and it does not make every territory attackable — only the server's own bounded
    # candidate set is accepted.
    def _reentry_state(self, user, store):
        """The authoritative offer. Recomputed on every request, GET and POST alike, so the POST can
        validate a target without trusting the client and without storing session state."""
        return game_conquest.reentry_state(
            user, playable_territory_ids(), store,
            seed=current_room(),                     # per-room, so two rooms are independent
            limit=REENTRY_CANDIDATES,
            degree_of=(terr_catalog.degree if terr_catalog else None))

    def _reentry_public(self, state, store, user, econ):
        """The client's view. Deliberately omits garrison composition: the map already hides an
        enemy's troops (fog of war), and an eligibility endpoint must not become a scouting tool."""
        out = []
        for tid in state.candidates:
            h = store.get(tid) or {}
            t = (terr_catalog.territories.get(tid) if terr_catalog else None) or {}
            out.append({"territoryId": tid,
                        "displayName": t.get("displayName") or tid,
                        "population": clampi(h.get("pop", 0)) or clampi(t.get("gamePopulation", 0)),
                        "owner": h.get("owner"),
                        "avatar": h.get("avatar"),
                        # presentation-only: an isolated foothold cannot attack out, and the client
                        # says so plainly rather than letting the player find out afterwards.
                        "isolated": bool(terr_catalog and terr_catalog.degree(tid) == 0)})
        return {"available": state.available, "reason": state.reason, "candidates": out,
                "cost": {"gold": REENTRY_GOLD_COST, "minTroops": 1},
                "gold": clampi((econ or {}).get("gold", 0)),
                "troops": {k: clampi(((econ or {}).get("troops") or {}).get(k, 0)) for k in TROOP_ALL}}

    def _handle_reentry_state(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        with terr_lock:
            store = load_territory_store()
            state = self._reentry_state(user, store)
        with econ_lock:
            estore = load_econ_store()
            e = econ_get(estore, user, time.time(), user_region_pop(store, user))
            save_econ_store(estore)
        self._send(self._reentry_public(state, store, user, e))

    def _handle_reentry(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        target = self._canon(d.get("targetTerritoryId") or d.get("target") or d.get("file"))
        squad = []
        for t in (d.get("squad") or d.get("troops") or [])[:4]:
            if isinstance(t, dict) and str(t.get("type")) in self.TROOP_TYPES:
                hp = int(t.get("hp", 0) or 0)
                if hp > 0:
                    squad.append({"type": t["type"], "hp": max(0, min(100000, hp))})
        avatar = str(d.get("avatar", "👦"))[:8]
        if not squad:
            self._send({"error": "Deploy at least one troop to establish a foothold",
                        "reason": "troops_required"}, 400)
            return
        defender = None
        result = None
        new_target = None
        returned = None
        # ONE critical section covers eligibility, the candidate check, the gold+troop debit and the
        # ownership write, so a duplicate POST or two tabs cannot double-spend or double-land. Lock
        # order is the established terr -> econ (identical to /claim).
        with terr_lock:
            store = load_territory_store()
            state = self._reentry_state(user, store)
            if not state.available:
                # `owns_territory` and `neutral_available` are not errors, they are "use the ordinary
                # rules"; 409 says the request contradicts current state rather than being malformed.
                self._send({"error": "Re-entry is not available", "reason": state.reason}, 409)
                return
            if not target:
                self._send({"error": "targetTerritoryId is required", "reason": "target_not_found"}, 400)
                return
            if target not in state.candidates:
                # covers a forged id, an unresolvable id, a dormant-map id, and a real World territory
                # that simply was not offered. The candidate set is the whole authority.
                self._send({"error": "That territory is not one of your re-entry footholds",
                            "reason": "target_not_candidate", "candidates": state.candidates}, 403)
                return
            tgt = store.get(target)
            if not isinstance(tgt, dict) or not tgt.get("owner"):
                self._send({"error": "Foothold target is no longer held", "reason": "not_held"}, 409)
                return
            with econ_lock:
                estore = load_econ_store()
                e = econ_get(estore, user, time.time(), user_region_pop(store, user))
                if clampi(e.get("gold", 0)) < REENTRY_GOLD_COST:
                    self._send({"error": "Not enough gold to re-enter", "reason": "insufficient_gold",
                                "gold": clampi(e.get("gold", 0)), "cost": REENTRY_GOLD_COST}, 400)
                    return
                avail = {k: clampi(e["troops"].get(k, 0)) for k in TROOP_ALL}
                need = {}
                for u in squad:
                    need[u["type"]] = need.get(u["type"], 0) + clampi(u["hp"])
                short = {k: v - avail.get(k, 0) for k, v in need.items() if v > avail.get(k, 0)}
                if short:                              # 兵力不足 → 一切狀態零變動(原子拒絕)
                    self._send({"error": "Not enough troops", "reason": "insufficient_troops",
                                "available": avail, "requested": need, "short": short}, 400)
                    return
                for k, v in need.items():
                    avail[k] -= v
                e["troops"] = avail                    # troops MOVE out of the pool, never minted
                e["gold"] = clampi(e.get("gold", 0)) - REENTRY_GOLD_COST
                home_tech = e.get("tech") or {}        # 家鄉科技加成你派出去的軍隊(與招募路徑同義)
                save_econ_store(estore)
            defender = tgt.get("owner")
            def_tech = tgt.get("tech") or {}
            # THE CANONICAL BATTLE ENGINE. Identical call as /attack: same resolve_attack, same
            # apply_territorial_attack, same casualties and same defender handling. The ONLY thing
            # that differs is where the attacking force came from, because there is no owned source
            # to march it out of -- so a synthetic source carries the squad and the home tech.
            synth_source = {"owner": user, "troops": [dict(u) for u in squad], "tech": home_tech}
            result = game_conquest.resolve_attack(squad, tgt.get("troops") or [], home_tech,
                                                  def_tech, random.Random())
            new_source, new_target = game_conquest.apply_territorial_attack(
                synth_source, tgt, squad, result, user, avatar)
            if result["attackerWon"]:
                if not clampi(new_target.get("pop", 0)):
                    cpop = terr_catalog.game_population(target) if terr_catalog else None
                    new_target["pop"] = clampi(cpop if cpop is not None else tgt.get("pop", 0))
                store[target] = new_target
                save_territory_store(store)
            else:
                # LOSS: canonically the survivors return to the SOURCE garrison. There is no source,
                # so they go back where they came from -- the pool. Only casualties are lost, exactly
                # as in an ordinary failed attack; nothing is duplicated and nothing vanishes.
                with econ_lock:
                    estore = load_econ_store()
                    e2 = econ_get(estore, user, time.time(), user_region_pop(store, user))
                    for s in (new_source.get("troops") or []):
                        if isinstance(s, dict) and s.get("type") in e2["troops"]:
                            e2["troops"][s["type"]] = clampi(e2["troops"].get(s["type"], 0)) + clampi(s.get("hp", 0))
                    returned = dict(e2["troops"])
                    save_econ_store(estore)
                store[target] = new_target             # defender keeps it, garrison = its survivors
                save_territory_store(store)
        # 金幣獎懲與 /attack 完全相同(規則不變)：輸 → 攻方 −50、真人守方 +50。在 terr_lock 外呼叫。
        newgold = None
        if not result["attackerWon"]:
            newgold = econ_add_gold(user, -ATTACK_FAIL_GOLD)
            if defender and defender != user and not is_ai_owner(defender):
                econ_add_gold(defender, DEFEND_GOLD)
        else:
            with econ_lock:
                estore = load_econ_store()
                newgold = clampi(econ_get(estore, user, time.time(), 0).get("gold", 0))
                save_econ_store(estore)
        self._send({"ok": True, "reentry": True, "targetTerritoryId": target,
                    "attackerWon": result["attackerWon"], "owner": new_target.get("owner"),
                    "targetGarrison": new_target.get("troops") or [],
                    "attackerSurvivors": result["attackerSurvivors"],
                    "defenderSurvivors": result["defenderSurvivors"],
                    "defenderOrder": result["defenderOrder"], "defenderTech": def_tech,
                    "defender": defender, "goldSpent": REENTRY_GOLD_COST, "gold": newgold,
                    "troops": returned})

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
            pop, troops, gold = e["population"], e["troops"], e["gold"]
            buildings, tech = e["buildings"], e["tech"]
            conscript, cbudget = bool(e.get("conscript")), clampi(e.get("conscriptBudget", 0))
        income = int(round((pop + region_pop) * GOLD_RATE))   # 金幣/小時 = (家鄉+領地人口) × 比例
        # Phase 7E.2：把「學習獎勵金額」唯讀地告訴前端，讓 Learning Home 能顯示真實數字。
        # 這不是新的獎勵、也不是新的權威來源——金額仍然只存在於 game/config.py，由這裡讀出來。
        # 前端永遠不自己算金額(否則就變成第二份經濟真相)，只是把伺服器說的數字顯示出來。
        self._send({"population": pop, "troops": troops, "troopsTotal": troops_total(troops),
                    "gold": gold, "goldIncome": income,
                    "passGold": PASS_GOLD, "masteryGold": LESSON_MASTERY_GOLD,
                    "buildings": buildings, "tech": tech,
                    "conscript": conscript, "conscriptBudget": cbudget})

    # Phase 7F.2: /api/economy/pass is GONE. It only ever incremented a per-lesson counter that
    # made an ungated territory look like it required a lesson; no server authority read it, and
    # it accepted any unvalidated `file` string. Retiring the Random-Challenge prerequisite
    # removed its last consumer, so the write endpoint goes with it rather than lingering as a
    # route that mutates state for nothing.

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
        view = LEARNING.state_view(p.get("learning") or {})
        # Phase 12B.2: the learner needs to know which input mode is permitted for them. Only their
        # OWN mode is exposed here, and there is no reason field to leak because none is stored.
        if isinstance(view, dict):
            view["readAlongMode"] = read_along_mode_of(user)
        self._send(view)

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
        # Phase 3D：活動獎勵與「整課完成」獎勵是分開的政策，一次結算。
        # Phase 7C.2：lessonRewardAmount 不再恆為 0——四堂 Taipei 課程已啟用 lesson_mastery_gold，
        # 所以同一次提交可能同時帶著「關卡活動」與「整課精通」兩筆金額，兩筆都由後端政策決定。
        delta = (clampi(out["rewardAmount"]) + clampi(out["lessonRewardAmount"])
                 + clampi(out.get("courseRewardAmount", 0)))
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
                    # lessonCompleted 為相容欄位，語意等同 currentPolicySatisfied(見 Phase 4D §19)。
                    "lessonId": out["lessonId"], "lessonCompleted": out["lessonCompleted"],
                    "lessonCompletedNow": out["lessonCompletedNow"],
                    "lessonQualifications": out["lessonQualifications"],
                    "lessonRewarded": out["lessonRewarded"],
                    **_reward_fields(out), **_lesson_status_fields(out)})

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
        delta = (clampi(out.get("rewardAmount", 0)) + clampi(out.get("lessonRewardAmount", 0))
                 + clampi(out.get("courseRewardAmount", 0)))
        newgold = econ_add_gold(user, delta) if delta else None
        resp = {"ok": True, "roundId": rid, "status": out["status"], "expected": out["expected"],
                "total": out["total"], "completed": out["completed"], "scored": out["scored"]}
        if out["status"] == "complete":
            resp.update(result=out["result"], qualifications=out.get("granted") or [],
                        rewarded=bool(out.get("rewarded")), gold=newgold,
                        lessonCompletedNow=bool(out.get("lessonCompletedNow")),
                        **_reward_fields(out))
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
        delta = (clampi(view.get("rewardAmount", 0)) + clampi(view.get("lessonRewardAmount", 0))
                 + clampi(view.get("courseRewardAmount", 0)))
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
                        lessonCompletedNow=bool(view.get("lessonCompletedNow")),
                        **_reward_fields(view), **_lesson_status_fields(view))
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
            # Phase 8B.1: `troops` is IGNORED. It used to write the authoritative pool straight from
            # the request body, so a client could mint 4,000,000 troops for 0 gold and UNIT_COST
            # constrained nobody. The pool is now written only by the two server-side operations that
            # own it: recruitment (which debits gold at UNIT_COST) and claim (which moves troops
            # between the pool and a garrison). Ignoring rather than rejecting kept every existing
            # caller working at the time.
            # Phase 8D: the product client no longer sends `troops` at all — saveEconomy() was its
            # only caller and has been deleted, since the field it pushed was discarded here and its
            # last user (the boss challenge) was charging a cost the game never collected. The ignore
            # stays: it is what makes a stale tab or a non-standard client harmless.
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
    # Phase 12B.1 startup policy: PROBE, REPORT, KEEP SERVING. The Academy, the World, every quiz
    # and every other activity work without speech recognition, so refusing to boot would take the
    # whole product down over one activity's dependency. A failed probe is loud in the log and makes
    # /api/stt answer a truthful 503 from the first request onward.
    print("[stt] warming up model %s ..." % WHISPER_MODEL, flush=True)
    if stt_warmup():
        print("[stt] ready", flush=True)
    else:
        print("[stt] UNAVAILABLE (%s) -- read-along scoring will answer 503 stt_unavailable; "
              "the rest of the app is unaffected" % _stt_ready_detail, flush=True)
    ensure_global_room()    # 常駐世界(全域房間)：不存在就建立
    threading.Thread(target=ai_loop, daemon=True).start()   # 電腦 AI 帝國：背景自動擴張/攻擊
    threading.Thread(target=conscript_loop, daemon=True).start()   # 徵兵制：每小時自動買兵
    ThreadingHTTPServer(("127.0.0.1", 5000), Handler).serve_forever()
