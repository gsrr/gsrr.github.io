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
            if not isinstance(t, dict):
                return {}
            for h in t.values():                       # 把舊的中文 AI 名字就地換成英文
                if isinstance(h, dict) and h.get("owner") == AI_OWNER_LEGACY:
                    h["owner"] = AI_OWNER
            return t
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
GROW_SECONDS = 3600   # 成長結算間隔：每小時
POP_GROWTH = 0.10     # 人口每小時 +10%（家鄉與各領地各自成長；徵兵時要扣人口）
ECON_MAX_CATCHUP = 72 # 一次最多補算 72 小時，避免長時間停機後人口/金幣暴衝
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


# --- 全站事件牆（所有人共見）：[{ts, user, text}]，只留最近 EVENTS_MAX 筆 ---
EVENTS_FILE = "/data/events.json"
ev_lock = threading.Lock()
EVENTS_MAX = 120


def load_events():
    try:
        with open(EVENTS_FILE) as f:
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
    os.makedirs(os.path.dirname(EVENTS_FILE), exist_ok=True)
    tmp = EVENTS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(e, f)
    os.replace(tmp, EVENTS_FILE)


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
        e = {"population": ECON_START_POP, "troops": ECON_START_TROOPS, "gold": 0, "lastGold": now}
        store[user] = e
    pop = clampi(e.get("population", ECON_START_POP))
    troops = clampi(e.get("troops", 0))
    gold = clampi(e.get("gold", 0))
    if "lastGold" in e:
        try:
            last = float(e["lastGold"])
        except Exception:
            last = now
    else:
        last = now                                  # 舊帳號首次改用金幣制 → 從現在起算，不回溯灌金幣
    hours = int((now - last) // GROW_SECONDS)
    if hours > 0:
        rp = clampi(region_pop)
        for _ in range(min(hours, ECON_MAX_CATCHUP)):   # 每小時：先依當前人口產金，人口再 +POP_GROWTH
            gold = clampi(gold + int(round((pop + rp) * GOLD_RATE)))
            pop = clampi(round(pop * (1 + POP_GROWTH)))
        last = last + hours * GROW_SECONDS               # 時鐘照實推進（即使成長被 catch-up 上限截斷）
    e["population"], e["troops"], e["gold"], e["lastGold"] = pop, troops, gold, last
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
PASS_GOLD = 100                                     # 通過一課 +100 金幣
DEFEND_GOLD = 50                                    # 防守成功 +50 金幣
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


def load_catalog():
    try:
        with open(TERR_CATALOG) as f:
            c = json.load(f)
            return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def save_catalog(c):
    os.makedirs(os.path.dirname(TERR_CATALOG), exist_ok=True)
    tmp = TERR_CATALOG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(c, f)
    os.replace(tmp, TERR_CATALOG)


def _atk_bonus(at, df):        # 攻方 at 打守方 df 的攻擊倍率（對齊前端 atkBonus）
    if at == "spear" and df == "cav":
        return 1.2
    if at == "cav" and df == "archer":
        return 1.1
    if at == "archer" and df in ("spear", "inf"):
        return 1.2
    return 1.0


def _def_bonus(df, at):        # 守方 df 面對攻方 at 的防守倍率（對齊前端 defBonus）
    if df == "cav" and at == "archer":
        return 1.1
    return 1.0


def _alive(troops):            # -> [(type, hp)]，只留活著且合法兵種
    out = []
    for t in (troops or []):
        if not isinstance(t, dict):
            continue
        ty = str(t.get("type", ""))
        hp = int(t.get("hp", 0) or 0)
        if ty in TROOP_KINDS and hp > 0:
            out.append((ty, hp))
    return out


def _mix(force):               # 兵種占比（依 hp 加權）
    tot = sum(hp for _, hp in force) or 1
    m = {}
    for ty, hp in force:
        m[ty] = m.get(ty, 0) + hp / tot
    return m


def _force_power(force, enemy):
    # 兵力 × 對「敵方兵種組成」的加權克制倍率
    em = _mix(enemy)
    p = 0.0
    for ty, hp in force:
        if em:
            mult = sum(frac * _atk_bonus(ty, ety) / _def_bonus(ety, ty) for ety, frac in em.items())
        else:
            mult = 1.0
        p += hp * (mult or 1.0)
    return p


def _ai_make_army(total):      # 把 total 兵力隨機拆成 2–4 種兵
    total = max(4, int(total))
    kinds = random.sample(list(TROOP_KINDS), random.randint(2, 4))
    weights = [random.random() + 0.25 for _ in kinds]
    s = sum(weights) or 1
    army, used = [], 0
    for i, k in enumerate(kinds):
        remaining_slots = len(kinds) - 1 - i
        if remaining_slots == 0:
            hp = total - used
        else:
            hp = int(round(total * weights[i] / s))
            hp = max(1, min(hp, total - used - remaining_slots))
        used += hp
        army.append({"type": k, "hp": max(1, hp)})
    return army


def _ai_reference(store):       # AI 兵力規模：參考當前玩家領地的平均駐軍（隨玩家成長）
    vals = []
    for f, h in store.items():
        if isinstance(h, dict) and h.get("owner") and h.get("owner") != AI_OWNER:
            vals.append(sum(hp for _, hp in _alive(h.get("troops"))))
    base = (sum(vals) / len(vals)) if vals else 80
    return max(40, min(4000, base))


def _region_display(key):       # 從 store key 生一個看得懂的名字給事件牆用
    k = key.split("#")[-1] if "#" in key else key
    k = k.split("/")[-1]
    k = k.rsplit(".", 1)[0]
    return clean_txt(k.replace("_", " ").replace("-", " ").strip() or "a region", 40)


def _ai_log_event(kind, region, victim=None, key=None):
    if kind == "occupy":
        text = "🤖 %s occupied %s" % (AI_OWNER, region)
        etype = "occupy"
    elif kind == "attack_win":
        text = "🤖 %s stormed %s%s" % (AI_OWNER, region, (" (was %s's)" % victim if victim else ""))
        etype = "attack"
    elif kind == "attack_fail":
        text = "🛡️ %s repelled the 🤖 %s attack on %s" % (victim or "Defenders", AI_OWNER, region)
        etype = "defend"
    else:
        return
    # 除了給人看的 text，另存結構化欄位讓前端能把事件定位到地圖某一塊並依時間回放
    ev = {"ts": int(time.time()), "user": AI_OWNER, "text": clean_txt(text, 120),
          "type": etype, "key": key or "", "region": region,
          "owner": AI_OWNER, "victim": victim or ""}
    with ev_lock:
        evs = load_events()
        evs.append(ev)
        if len(evs) > EVENTS_MAX:
            evs = evs[-EVENTS_MAX:]
        save_events(evs)


def ai_move():
    logged = None
    with terr_lock:
        store = load_territory_store()
        ref = _ai_reference(store)
        owned = set(store.keys())
        player_regions = [f for f, h in store.items()
                          if isinstance(h, dict) and h.get("owner") and h.get("owner") != AI_OWNER]
        cat = load_catalog()
        unowned_known = [k for k in cat.keys() if k not in owned]

        choices = []
        if player_regions:
            choices.append("attack")
        if unowned_known:
            choices.append("occupy")
        if not choices:
            return None                            # 還沒有任何可打/可佔的目標（catalog 為空且無玩家）

        if "attack" in choices and "occupy" in choices:
            act = "attack" if random.random() < 0.6 else "occupy"
        else:
            act = choices[0]

        if act == "occupy":
            key = random.choice(unowned_known)
            pop = clampi(cat.get(key, 100))
            army = _ai_make_army(max(8, int(ref * random.uniform(0.6, 1.0))))
            store[key] = {"owner": AI_OWNER, "avatar": AI_AVATAR, "troops": army, "pop": pop}
            save_territory_store(store)
            logged = ("occupy", _region_display(key), None, key)
        else:
            key = random.choice(player_regions)
            h = store[key]
            victim = h.get("owner")
            defender = _alive(h.get("troops"))
            army = _ai_make_army(max(8, int(ref * random.uniform(0.9, 1.5))))
            atk_tuples = [(t["type"], t["hp"]) for t in army]
            tech = h.get("tech") or {}                                   # 守軍的兵工廠科技
            forge = 1 + 0.10 * clampi(tech.get("atk", 0))               # 鍛造 → 守方反擊更痛
            armor = 1 + 0.08 * clampi(tech.get("def", 0))               # 鎧甲 → AI 打進去的傷害變小
            ap = _force_power(atk_tuples, defender) / armor * random.uniform(0.85, 1.15)
            dp = _force_power(defender, atk_tuples) * forge * 1.10 * random.uniform(0.85, 1.15)   # 守方先攻/主場
            region = _region_display(key)
            if ap > dp:                            # AI 打贏 → 直接接管（存活兵力隨戰損縮減）
                surv_frac = max(0.2, min(0.9, 1 - dp / (ap + 1)))
                surv = [{"type": t["type"], "hp": max(1, int(t["hp"] * surv_frac))} for t in army]
                store[key] = {"owner": AI_OWNER, "avatar": AI_AVATAR, "troops": surv,
                              "pop": clampi(h.get("pop", cat.get(key, 100)))}
                save_territory_store(store)
                logged = ("attack_win", region, victim, key)
            else:                                  # AI 落敗 → 守軍受創但守住
                dmg = min(0.6, ap / (dp + 1) * 0.5)
                for t in (h.get("troops") or []):
                    if isinstance(t, dict):
                        t["hp"] = max(0, int(int(t.get("hp", 0) or 0) * (1 - dmg)))
                save_territory_store(store)
                logged = ("attack_fail", region, victim, key)

    if logged:
        _ai_log_event(*logged)
        if logged[0] == "attack_fail" and logged[2] and logged[2] != AI_OWNER:
            econ_add_gold(logged[2], DEFEND_GOLD)      # 玩家成功擋下 AI → 防守成功 +50
    return logged


def ai_loop():
    time.sleep(60)                                 # 開機後稍等，避免和啟動流程搶鎖
    while True:
        try:
            ai_move()
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


def grow_region_pop(h, now):
    # 領地人口每小時 +POP_GROWTH（背景成長，和金幣一樣用時間戳補算）。回傳是否有變動。
    last = _as_float(h.get("lastPop"), now)
    hours = int((now - last) // GROW_SECONDS)
    if hours <= 0:
        if "lastPop" not in h:                # 首見這塊領地 → 從現在起算，不回溯灌人口
            h["lastPop"] = now
            return True
        return False
    pop = clampi(h.get("pop", 0))
    for _ in range(min(hours, ECON_MAX_CATCHUP)):
        pop = clampi(round(pop * (1 + POP_GROWTH)))
    h["pop"], h["lastPop"] = pop, last + hours * GROW_SECONDS
    return True


def conscript_tick():
    now = time.time()
    with terr_lock:
        store = load_territory_store()
        with econ_lock:
            estore = load_econ_store()
            t_dirty = e_dirty = False
            # 1) 各領地：人口每小時 +10%（背景成長）＋ 徵兵 → 加進該區守軍(扣該區人口)、花擁有者金幣池
            for f, h in store.items():
                if not (isinstance(h, dict) and h.get("owner") and h.get("owner") != AI_OWNER):
                    continue
                if grow_region_pop(h, now):             # 每塊領地人口每小時 +POP_GROWTH
                    t_dirty = True
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
                    n_troops = sum(bought.values())
                    if n_troops > clampi(h.get("pop", 0)):  # 人口不夠徵這麼多兵 → 這小時不做事
                        break
                    for u, n in bought.items():
                        slot = next((t for t in troops if isinstance(t, dict) and t.get("type") == u), None)
                        if slot:
                            slot["hp"] = clampi(slot.get("hp", 0)) + n
                        else:
                            troops.append({"type": u, "hp": n})
                    h["pop"] = clampi(h.get("pop", 0)) - n_troops   # 徵兵扣該領地人口
                    e["gold"] = clampi(e.get("gold", 0)) - cost
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
                    n_troops = sum(bought.values())
                    if n_troops > clampi(e.get("population", 0)):  # 家鄉人口不夠 → 這小時不做事
                        break
                    e["troops"] = clampi(e.get("troops", 0)) + n_troops
                    e["population"] = clampi(e.get("population", 0)) - n_troops   # 徵兵扣家鄉人口
                    e["gold"] = clampi(e.get("gold", 0)) - cost
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
            conscript_tick()
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
        elif path == "/api/territory/attack-result":
            self._handle_territory_attack_result()
        elif path == "/api/territory/conscript":
            self._handle_territory_conscript()
        elif path == "/api/economy/set":
            self._handle_economy_set()
        elif path == "/api/economy/pass":
            self._handle_economy_pass()
        elif path == "/api/event":
            self._handle_event_add()
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
            text = transcribe(audio, target)
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
        me = token_user(self._token())              # 戰霧：只有自己的領地才看得到守軍/科技
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
                              "pop": h.get("pop"), "hidden": True}
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
        # 佔領只發生在「無主」據點：有主據點要先打贏 → /territory/release 清成無主，才能佔領。
        # 因此這裡不會有前主人可扣（扣人口在 release 時就處理過了）。
        with terr_lock:
            store = load_territory_store()
            prev = store.get(f) if isinstance(store.get(f), dict) else {}
            keep = {}
            if prev.get("owner") == user:                # 重新部署自己的守軍 → 保留建築/科技/人口/徵兵設定(人口伺服器管理，不被前端覆蓋)
                keep = {"buildings": prev.get("buildings") or {}, "tech": prev.get("tech") or {}}
                for k in ("pop", "lastPop", "conscript", "conscriptBudget", "lastConscript"):
                    if k in prev:
                        keep[k] = prev[k]
            store[f] = {"owner": user, "avatar": str(d.get("avatar", "👦"))[:8],
                        "troops": troops, "pop": region_pop, **keep}
            save_territory_store(store)
            if region_pop > 0:                       # 讓電腦 AI 學到「這塊地存在 + 人口」，日後可佔領
                cat = load_catalog()
                if cat.get(f) != region_pop:
                    cat[f] = region_pop
                    save_catalog(cat)
        self._send({"ok": True})

    # 攻方打贏「有主」據點後呼叫：把該據點清成「無主」，前主人扣掉該區人口。
    # 攻方不會馬上取得所有權——之後要走「過關→佔領」流程才真正佔領。
    def _handle_territory_release(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        f = (d.get("file") or "").strip()
        if not f:
            self._send({"error": "missing file"}, 400)
            return
        with terr_lock:
            store = load_territory_store()
            if f in store:
                del store[f]           # 清空守備 → 恢復無主（該區的駐軍/成長隨之消失）
                save_territory_store(store)
        # 領地的兵力現在長在「該區駐軍」而不是玩家人口池，失去領地即失去其駐軍，
        # 不再另外扣前主人的家鄉人口。
        self._send({"ok": True})

    # 蓋建築（目前：兵工廠 armory）：需為該領地擁有者，扣該區金幣。
    def _handle_territory_build(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        f = (d.get("file") or "").strip()
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
        f = (d.get("file") or "").strip()
        track = str(d.get("track", ""))
        if track not in TECH_TRACKS:
            self._send({"error": "unknown track"}, 400)
            return
        if f == HOME_KEY:                          # 家鄉科技：研發存在玩家經濟裡(加成攻擊軍)
            with terr_lock:
                region_pop = user_region_pop(load_territory_store(), user)
            with econ_lock:
                estore = load_econ_store()
                e = econ_get(estore, user, time.time(), region_pop)
                if not e["buildings"].get("armory"):
                    self._send({"error": "need armory"}, 400)
                    return
                tech = e["tech"]
                lvl = clampi(tech.get(track, 0))
                if lvl >= TECH_MAX:
                    self._send({"error": "maxed"}, 400)
                    return
                cost = TECH_COST[track][lvl]
                if clampi(e.get("gold", 0)) < cost:
                    self._send({"error": "not enough gold", "gold": clampi(e.get("gold", 0)), "cost": cost}, 400)
                    return
                e["gold"] = clampi(e.get("gold", 0)) - cost
                tech[track] = lvl + 1
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
            if not (h.get("buildings") or {}).get("armory"):
                self._send({"error": "need armory"}, 400)
                return
            tech = h.get("tech") or {}
            lvl = clampi(tech.get(track, 0))
            if lvl >= TECH_MAX:
                self._send({"error": "maxed"}, 400)
                return
            cost = TECH_COST[track][lvl]            # 下一級花費
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
            tech[track] = lvl + 1
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
        f = (d.get("file") or "").strip()
        unit = str(d.get("unit", ""))
        if unit not in UNIT_COST:
            self._send({"error": "unknown unit"}, 400)
            return
        qty = clampi(d.get("qty", RECRUIT_BATCH), 1, 100000)
        cost = qty * UNIT_COST[unit]
        need = UNIT_BUILDING[unit]
        if f == HOME_KEY:                          # 家鄉招募 → 加進「自由兵力池」(economy troops)
            with terr_lock:
                region_pop = user_region_pop(load_territory_store(), user)
            with econ_lock:
                estore = load_econ_store()
                e = econ_get(estore, user, time.time(), region_pop)
                if not e["buildings"].get(need):
                    self._send({"error": "need " + need}, 400)
                    return
                if clampi(e.get("gold", 0)) < cost:
                    self._send({"error": "not enough gold", "gold": clampi(e.get("gold", 0)), "cost": cost}, 400)
                    return
                if clampi(e.get("population", 0)) < qty:   # 徵兵要有足夠人口（1 兵 = 1 人口）
                    self._send({"error": "not enough population", "population": clampi(e.get("population", 0)), "need": qty}, 400)
                    return
                e["gold"] = clampi(e.get("gold", 0)) - cost
                e["population"] = clampi(e.get("population", 0)) - qty   # 徵兵扣家鄉人口
                e["troops"] = clampi(e.get("troops", 0)) + qty
                save_econ_store(estore)
                newgold, newtroops, newpop = e["gold"], e["troops"], e["population"]
            self._send({"ok": True, "gold": newgold, "troops": newtroops, "population": newpop})
            return
        with terr_lock:
            store = load_territory_store()
            h = store.get(f)
            if not isinstance(h, dict) or h.get("owner") != user:
                self._send({"error": "not your region"}, 403)
                return
            if not (h.get("buildings") or {}).get(need):
                self._send({"error": "need " + need}, 400)
                return
            if clampi(h.get("pop", 0)) < qty:       # 徵兵要有足夠人口（1 兵 = 1 人口）
                self._send({"error": "not enough population", "population": clampi(h.get("pop", 0)), "need": qty}, 400)
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
            h["pop"] = clampi(h.get("pop", 0)) - qty   # 徵兵扣該領地人口
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
        f = (d.get("file") or "").strip()
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

    # 開戰時才揭露某領地的守軍/科技(戰霧：平時看不到，出兵攻打當下才給前端跑對戰用)
    def _handle_territory_engage(self):
        user = token_user(self._token())
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        f = (self._body_json().get("file") or "").strip()
        with terr_lock:
            store = load_territory_store()
            h = store.get(f)
        if not isinstance(h, dict) or not h.get("owner"):
            self._send({"troops": [], "tech": {}})
            return
        self._send({"owner": h.get("owner"), "troops": h.get("troops") or [], "tech": h.get("tech") or {}})

    # 攻打結果的金幣獎懲(前端跑完對戰後回報)：攻打失敗→攻方 −50、守方 +50；成功不變
    def _handle_territory_attack_result(self):
        user = token_user(self._token())          # 攻方
        if not user:
            self._send({"error": "Not logged in"}, 401)
            return
        d = self._body_json()
        f = (d.get("file") or "").strip()
        win = bool(d.get("win"))
        with terr_lock:
            store = load_territory_store()
            h = store.get(f)
            defender = h.get("owner") if isinstance(h, dict) else None
        newgold = None
        if not win:                               # 攻打失敗
            newgold = econ_add_gold(user, -ATTACK_FAIL_GOLD)
            if defender and defender != user and defender != AI_OWNER:
                econ_add_gold(defender, DEFEND_GOLD)   # 守方防守成功
        self._send({"ok": True, "gold": newgold})

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
        if typ == "occupy" and region:
            text = "🚩 %s occupied %s" % (u, region)
        elif typ == "attack" and region:
            text = "⚔️ %s stormed %s%s" % (u, region, (" (was %s's)" % target if target else ""))
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
        self._send({"population": pop, "troops": troops, "gold": gold, "goldIncome": income,
                    "passcnt": passcnt, "buildings": buildings, "tech": tech,
                    "conscript": conscript, "conscriptBudget": cbudget})

    # 記錄「通過一課」→ 該課通過次數 +1（佔領解鎖用，後端統一保存、跨裝置一致）
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
            pc[f] = clampi(pc.get(f, 0)) + 1
            e["gold"] = clampi(e.get("gold", 0) + PASS_GOLD)   # 通過一課 +100 金幣
            save_econ_store(store)
            cnt, gold = pc[f], e["gold"]
        self._send({"ok": True, "file": f, "count": cnt, "gold": gold})

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
            # 人口改為伺服器管理（每小時 +10% 成長、徵兵扣人口）→ 前端不再直接設定 population
            if "troops" in d:
                e["troops"] = clampi(d.get("troops"))
            save_econ_store(store)
            pop, troops, gold = e["population"], e["troops"], e["gold"]
        self._send({"ok": True, "population": pop, "troops": troops, "gold": gold})

    def log_message(self, *args):
        pass  # 安靜


if __name__ == "__main__":
    migrate_accounts()      # 舊版單檔結構 -> 拆檔（只跑一次有效果）
    threading.Thread(target=ai_loop, daemon=True).start()   # 電腦 AI 帝國：背景自動擴張/攻擊
    threading.Thread(target=conscript_loop, daemon=True).start()   # 徵兵制：每小時自動買兵
    ThreadingHTTPServer(("127.0.0.1", 5000), Handler).serve_forever()
