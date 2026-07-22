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
GROW_SECONDS = 3600   # 兵力成長結算間隔：每小時
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
        income = int(round((pop + clampi(region_pop)) * GOLD_RATE))
        gold = clampi(gold + hours * income)
        last = last + hours * GROW_SECONDS
    e["population"], e["troops"], e["gold"], e["lastGold"] = pop, troops, gold, last
    e.pop("lastGrow", None)                          # 移除舊的兵力成長時間戳
    return e


# 某玩家名下所有領地的人口總和（給金幣收入計算用）
def user_region_pop(tstore, user):
    return sum(clampi(h.get("pop", 0)) for h in tstore.values()
              if isinstance(h, dict) and h.get("owner") == user)


# ---- 領地建設：兵工廠(armory) + 科技樹(鍛造+攻 / 鎧甲+防)，用「金幣」研發 ----
# 金幣：每塊領地依人口每小時產金，累積在該區(h["gold"])。研發即時完成、只惠及該區守軍。
GOLD_RATE = 0.10                                   # 每小時金幣 = round(pop * GOLD_RATE)
BUILD_COST = {"armory": 50}                        # 蓋建築的金幣花費
TECH_TRACKS = ("atk", "def")                       # 鍛造(+攻) / 鎧甲(+防)
TECH_COST = {"atk": [80, 160, 280], "def": [80, 160, 280]}   # 第 1/2/3 級花費
TECH_MAX = 3


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
    return logged


def ai_loop():
    time.sleep(60)                                 # 開機後稍等，避免和啟動流程搶鎖
    while True:
        try:
            ai_move()
        except Exception:
            pass
        time.sleep(random.randint(AI_TICK_MIN, AI_TICK_MAX))


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
        elif path == "/api/economy/set":
            self._handle_economy_set()
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
        with terr_lock:
            store = load_territory_store()
        holders, counts = {}, {}
        for f, h in store.items():
            if not isinstance(h, dict):
                continue
            owner = h.get("owner")
            holders[f] = {"owner": owner, "avatar": h.get("avatar", "👦"),
                          "troops": h.get("troops") or [], "pop": h.get("pop"),
                          "income": region_gold_income(h),   # 該區每小時上繳給擁有者的金幣
                          "buildings": h.get("buildings") or {}, "tech": h.get("tech") or {}}
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
        # 佔領只發生在「無主」據點：有主據點要先打贏 → /territory/release 清成無主，才能佔領。
        # 因此這裡不會有前主人可扣（扣人口在 release 時就處理過了）。
        with terr_lock:
            store = load_territory_store()
            prev = store.get(f) if isinstance(store.get(f), dict) else {}
            keep = {}
            if prev.get("owner") == user:                # 重新部署自己的守軍 → 保留該區建築/科技
                keep = {"buildings": prev.get("buildings") or {}, "tech": prev.get("tech") or {}}
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
            pop, troops, gold = e["population"], e["troops"], e["gold"]
        income = int(round((pop + region_pop) * GOLD_RATE))   # 金幣/小時 = (家鄉+領地人口) × 比例
        self._send({"population": pop, "troops": troops, "gold": gold, "goldIncome": income})

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
            if "population" in d:
                e["population"] = clampi(d.get("population"))
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
    ThreadingHTTPServer(("127.0.0.1", 5000), Handler).serve_forever()
