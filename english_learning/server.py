#!/usr/bin/env python3
"""極小後端服務（Python 標準函式庫）。
   GET  /api/count  -> {"count": N}                      訪客計數
   POST /api/visit  -> 累加並回傳 {"count": N}
   POST /api/stt?text=<目標句>  (body = 音檔位元組)       發音用：Whisper 轉文字
        -> {"transcript": "..."}（前端再跟目標句比對算分）
   計數存於 /data/visits.json（docker volume）。
   STT 用 faster-whisper（開源、免費、CPU 可跑）；缺套件/ffmpeg 時回傳錯誤、不影響計數。
"""
import json, os, threading, tempfile, subprocess, hashlib, secrets
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


# ---- 帳號（老師/家長）+ 雲端進度 ----
# 存於 /data/accounts.json：{"users":{user:{salt,hash,data}}, "tokens":{token:user}}
# 密碼用 PBKDF2 雜湊（不存明碼）。這是 pilot 等級的簡易驗證，不是高安全方案。
ACCT = "/data/accounts.json"
acct_lock = threading.Lock()


def load_accounts():
    try:
        with open(ACCT) as f:
            return json.load(f)
    except Exception:
        return {"users": {}, "tokens": {}, "codes": {}}


def save_accounts(db):
    os.makedirs(os.path.dirname(ACCT), exist_ok=True)
    tmp = ACCT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(db, f)
    os.replace(tmp, ACCT)


def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 100000).hex()


# 班級加入碼：去掉易混字（0/O/1/I/L），學生輸入用
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def gen_code(db):
    codes = db.setdefault("codes", {})
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
        if code not in codes:
            return code


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
        with acct_lock:
            db = load_accounts()
            db.setdefault("codes", {})
            u = db["users"].get(user)
            if register:
                if u:
                    self._send({"error": "User already exists"}, 409)
                    return
                salt = secrets.token_hex(16)
                u = {"salt": salt, "hash": hash_pw(pw, salt), "code": None,
                     "data": {"students": {}}, "sdata": {}}
                db["users"][user] = u
            else:
                if not u or hash_pw(pw, u["salt"]) != u["hash"]:
                    self._send({"error": "Wrong username or password"}, 401)
                    return
            if not u.get("code"):                  # 確保每個帳號有一組班級碼（老師入口用）
                u["code"] = gen_code(db)
                db["codes"][u["code"]] = user
            u.setdefault("sdata", {})              # 學生入口的個人進度快照
            token = secrets.token_hex(24)
            db["tokens"][token] = user
            save_accounts(db)
        # data 回傳學生端快照，讓登入後可還原個人進度
        self._send({"token": token, "user": user, "code": u["code"], "data": u.get("sdata", {})})

    # 老師自己的裝置（用 token）上傳
    def _handle_sync(self):
        d = self._body_json()
        incoming = d.get("students") or {}
        with acct_lock:
            db = load_accounts()
            user = db["tokens"].get(self._token())
            if not user:
                self._send({"error": "Not logged in"}, 401)
                return
            students = db["users"][user]["data"].setdefault("students", {})
            for name, blob in incoming.items():
                students[name] = blob
            save_accounts(db)
        self._send({"ok": True})

    # 學生裝置：只用班級碼上傳（不需老師密碼）
    def _handle_class_sync(self):
        d = self._body_json()
        code = ((parse_qs(urlparse(self.path).query).get("code", [""]) or [""])[0] or d.get("code") or "").strip().upper()
        incoming = d.get("students") or {}
        with acct_lock:
            db = load_accounts()
            user = db.setdefault("codes", {}).get(code)
            if not user:
                self._send({"error": "Invalid class code"}, 404)
                return
            students = db["users"][user]["data"].setdefault("students", {})
            for name, blob in incoming.items():
                students[name] = blob          # 以學生名為鍵，後寫覆蓋
            save_accounts(db)
        self._send({"ok": True})

    def _handle_dashboard(self):
        with acct_lock:
            db = load_accounts()
            user = db["tokens"].get(self._token())
            if not user:
                self._send({"error": "Not logged in"}, 401)
                return
            u = db["users"][user]
            data = dict(u["data"])
            data["code"] = u.get("code")
        self._send(data)

    # ---- 學生入口：跨裝置雲端存檔，存在統一帳號的 sdata ----
    def _handle_student_save(self):
        d = self._body_json()
        blob = d.get("data")
        with acct_lock:
            db = load_accounts()
            user = db["tokens"].get(self._token())
            if not user or user not in db["users"]:
                self._send({"error": "Not logged in"}, 401)
                return
            db["users"][user]["sdata"] = blob if isinstance(blob, dict) else {}
            save_accounts(db)
        self._send({"ok": True})

    def _handle_student_load(self):
        with acct_lock:
            db = load_accounts()
            user = db["tokens"].get(self._token())
            if not user or user not in db["users"]:
                self._send({"error": "Not logged in"}, 401)
                return
            data = db["users"][user].get("sdata", {})
        self._send({"data": data})

    def log_message(self, *args):
        pass  # 安靜


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 5000), Handler).serve_forever()
