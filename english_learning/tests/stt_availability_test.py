#!/usr/bin/env python3
"""Phase 12B.1 — read-along stays available, or fails honestly. Never silently.

    python3 tests/stt_availability_test.py

Phase 12A found four real availability defects behind the authoritative read-along: the model loaded
lazily so a broken deployment was discovered by the first child to press Record; inference is
serialised, so waiters could pile up without bound; there was no truthful "unavailable" signal before
the first failure; and no boundary of any kind.

This pins the SERVER half. It must hold two lines at once:

  * an infrastructure failure never becomes academic evidence — no attempt, no pass, no mastery, no
    Gold, and a retry always possible;
  * the readiness machinery must not change anything for a caller that has not probed. Unit tests
    replace transcribe() and must never load a multi-hundred-MB model, so `import server` leaves
    readiness UNPROBED and the lazy path behaves exactly as it did before this phase.
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request as U
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402
from game.config import PASS_GOLD, MASTERY_GOLD  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ---------------- isolated server ----------------
import tempfile  # noqa: E402

d = tempfile.mkdtemp()
server.ROOMS_DIR = os.path.join(d, "rooms")
server.ACCT = os.path.join(d, "accounts.json")
server.PROG_DIR = os.path.join(d, "progress")
server.DATA = os.path.join(d, "visits.json")
server.TERR_CATALOG = os.path.join(d, "learned.json")
server.LEARNING.content_root = ROOT
json.dump({"users": {"AL": {"code": "STTAV"}}, "codes": {"STTAV": "AL"}}, open(server.ACCT, "w"))
server._tokens["tA"] = {"user": "AL", "exp": time.time() + 9999, "admin": False}

srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % PORT

_real_transcribe = server.transcribe


def call(method, path, body=None, raw=None, tok="tA"):
    url = B + path + ("&" if "?" in path else "?") + "token=" + tok
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    try:
        r = U.urlopen(U.Request(url, data=data, method=method))
        return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


call("POST", "/api/room/create", {})
CODE = call("POST", "/api/room/start", {"map": "A1", "aiCount": 0, "resources": "medium",
                                        "capacity": 4})[1]["code"]
LID = "english.a1.core.001"
AID = LID + ".read_along"


def row():
    p = call("GET", "/api/learning/progress?room=" + CODE)[1]
    return (p.get("lessons") or {}).get(LID) or {}


def gold():
    return call("GET", "/api/economy?room=" + CODE)[1].get("gold", 0)


def snap():
    r = row()
    return (len(r.get("completedActivityIds") or []), r.get("activePolicyCompleted"), gold())


def stt(idx=0, aid=AID, raw=b"\x00audio", room=True, tok="tA"):
    q = "/api/stt?"
    if room:
        q += "room=%s&" % CODE
    if aid:
        q += "activityId=%s&" % aid
    q += "sentenceIndex=%d" % idx
    return call("POST", q, raw=raw, tok=tok)


# ====================== 1. import must not probe or load a model ======================
assert server._stt_ready is None, ("importing server must leave readiness UNPROBED, or every unit "
                                   "test would depend on faster_whisper", server._stt_ready)
st = server.stt_status()
assert st == {"probed": False, "available": True, "reason": ""}, st
assert server._model is None, "no model may be constructed by import"
assert callable(server.stt_warmup), "the warm-up must be an explicit, callable step"
src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
main_at = src.index('if __name__ == "__main__":')
assert src.index("stt_warmup()", main_at) > main_at, "the probe must be called from __main__ only"
# every mention before __main__ must be the definition itself, never a call
for _ln in src[:main_at].splitlines():
    if "stt_warmup" in _ln:
        assert _ln.strip().startswith("def stt_warmup"), ("module-level probe call: %r" % _ln)
ok("1. importing server probes nothing and builds no model; the warm-up is a __main__ step only")

# ====================== 2. UNPROBED readiness leaves the old path intact ======================
server.transcribe = lambda audio, target: target          # a perfect reader
before = snap()
code, out = stt(0)
after = snap()
assert code == 200 and out.get("score") == 100, (code, out)
assert after != before, "a genuine attempt must still be recorded when readiness is unprobed"
ok("2. with readiness UNPROBED the lazy path is unchanged: a real attempt still scores and records")

# ====================== 3. a FAILED probe refuses up front, and changes nothing ======================
def boom():
    raise RuntimeError("no model here")


_real_get_model = server.get_model
server.get_model = boom
try:
    assert server.stt_warmup() is False, "a failing model load must mark readiness False"
    assert server._stt_ready is False
    st = server.stt_status()
    assert st["probed"] is True and st["available"] is False and st["reason"] == "RuntimeError", st
    assert "no model here" not in json.dumps(st), "the reason must not leak the exception message"

    before = snap()
    # transcribe still works -- proving the refusal comes from READINESS, not from transcription
    server.transcribe = lambda audio, target: target
    code, out = stt(1)
    after = snap()
    assert code == 503 and out.get("reason") == "stt_unavailable", (code, out)
    assert before == after, ("a readiness refusal must not touch progress or Gold", before, after)
    ok("3. after a failed probe /api/stt answers 503 stt_unavailable at once, with no state change")

    # and the whole rest of the product keeps working while STT is down
    aq = call("POST", "/api/learning/attempt?room=" + CODE,
              {"activityId": LID + ".quiz3", "answers": []})
    assert aq[0] == 200, ("other activities must be unaffected by an STT outage", aq)
    assert call("GET", "/api/learning/progress?room=" + CODE)[0] == 200
    assert call("GET", "/api/economy?room=" + CODE)[0] == 200
    ok("4. with STT unavailable the rest of the Academy and the economy still serve normally")
finally:
    server.get_model = _real_get_model
    server._stt_ready = None
    server._stt_ready_detail = ""

# ====================== 5. bounded admission: the queue cannot grow without limit ======================
gate = threading.Event()
entered = threading.Semaphore(0)


def blocking_transcribe(audio, target):
    entered.release()
    gate.wait(20)
    return target


server.transcribe = blocking_transcribe
results, threads = [], []


def fire(i):
    results.append(stt(i % 10))


try:
    n = server.STT_MAX_WAITING + 2
    for i in range(n):
        t = threading.Thread(target=fire, args=(i,))
        t.start()
        threads.append(t)
        entered.acquire(timeout=3) if i < server.STT_MAX_WAITING else time.sleep(0.25)
    time.sleep(0.6)
    gate.set()
    for t in threads:
        t.join(25)
finally:
    gate.set()
    server.transcribe = lambda audio, target: target

codes = sorted(c for c, _ in results)
busy = [o for c, o in results if c == 503 and o.get("reason") == "stt_busy"]
assert busy, ("with more than STT_MAX_WAITING=%d concurrent requests some must be refused busy, "
              "got %s" % (server.STT_MAX_WAITING, codes))
assert 200 in codes, ("admitted requests must still succeed", codes)
assert server._stt_waiting == 0, ("the admission counter must return to zero", server._stt_waiting)
ok("5. beyond STT_MAX_WAITING concurrent requests the server refuses 503 stt_busy and the "
   "counter drains back to zero (codes %s)" % codes)

# ====================== 6. every infrastructure failure is academically inert ======================
CASES = []
before = snap()

server.transcribe = lambda audio, target: (_ for _ in ()).throw(RuntimeError("engine exploded"))
code, out = stt(2)
CASES.append(("transcribe raises", code, out.get("reason"), snap()))

code, out = stt(2, raw=b"")
CASES.append(("empty audio", code, out.get("error"), snap()))

code, out = stt(2, aid=LID + ".quiz3")
CASES.append(("wrong activity type", code, out.get("reason"), snap()))

code, out = stt(999)
CASES.append(("bad sentence index", code, out.get("reason"), snap()))

code, out = stt(2, tok="bogus")
CASES.append(("bad token", code, out.get("error"), snap()))

code, out = stt(2, room=False)
CASES.append(("no room", code, out.get("reason"), snap()))

for label, code, reason, after in CASES:
    assert code >= 400, (label, code)
    assert after == before, ("%s must change nothing: %s -> %s" % (label, before, after))
print("     " + " | ".join("%s=%s" % (c[0], c[1]) for c in CASES))
ok("6. every infrastructure failure refuses with a status and leaves progress and Gold untouched")

# ====================== 7. a scored-but-failing attempt is still ACADEMIC, not infrastructure ======================
server.transcribe = lambda audio, target: "banana helicopter"
b7 = snap()
code, out = stt(3)
a7 = snap()
assert code == 200, (code, out)
assert out.get("score") == 0 and out.get("activityPassed") is False, out
assert out.get("rewarded") is False and out.get("rewardAmount") == 0, out
assert a7[0] >= b7[0], "a genuine poor attempt still records evidence"
assert a7[1] is not True and a7[2] == b7[2], ("a failing attempt grants no mastery and no Gold", a7)
ok("7. a genuine poor reading scores 0, records evidence, and pays nothing -- academic failure and "
   "infrastructure failure stay distinct")

# ====================== 8. retry after any failure still works, best score kept ======================
# use a sentence no earlier case has touched, and drive it low BEFORE driving it high, so "improved"
# is actually being exercised rather than depending on what a previous block happened to leave behind
server.transcribe = lambda audio, target: "nothing like the sentence"
code, out = stt(7)
assert code == 200 and out.get("score") == 0, (code, out)
server.transcribe = lambda audio, target: target
code, out = stt(7)
assert code == 200 and out.get("score") == 100, (code, out)
assert out.get("improved") is True, ("the better score must replace the earlier one", out)
ok("8. retry after failure works and the better score replaces the earlier one")

# ====================== 9. forgery protections unchanged (Phase 12A proofs) ======================
code, out = call("POST", "/api/stt?room=%s&activityId=%s&sentenceIndex=4&text=%s"
                 % (CODE, AID, "an+easier+sentence"), raw=b"\x00a")
assert code == 200 and out.get("target") and "easier" not in out["target"], \
    ("the server must resolve the target itself", out.get("target"))
code, out = call("POST", "/api/stt?room=%s&activityId=%s&sentenceIndex=5" % (CODE, AID),
                 raw=json.dumps({"score": 100, "passed": True, "rewarded": True,
                                 "transcript": "perfect"}).encode())
assert out.get("rewarded") is not True or out.get("rewardAmount") == 0, out
assert out.get("activityPassed") is not True, ("a client-claimed pass must be ignored", out)
lo = call("POST", "/api/stt?room=%s&text=hello" % CODE, raw=b"\x00a")
assert lo[0] == 200 and lo[1].get("authoritative") is False, lo
ok("9. authority is unchanged: the server resolves the target, ignores client score/passed/reward, "
   "and the legacy mode stays non-authoritative")

# ====================== 10. the curriculum contract is untouched ======================
from learning import registry as R  # noqa: E402
reg = R.REGISTRY
stt_acts = [a for a in reg.activities if reg.scorer_type_of(a) == "read_along_stt"]
assert len(reg.lessons) == 57 and len(reg.activities) == 457, (len(reg.lessons), len(reg.activities))
assert len(stt_acts) == 57, len(stt_acts)
req_count = 0
for lid in reg.lessons:
    pol = reg.completion_policy_of(lid) or {}
    req = pol.get("requiredActivityIds") or []
    mine = [a for a in stt_acts if reg.activities[a]["lessonId"] == lid]
    if any(a in req for a in mine):
        req_count += 1
    want = 7 if lid.startswith("english.prea1") else 5
    assert len(req) == want, (lid, len(req), want)
assert req_count == 57, req_count
assert (PASS_GOLD, MASTERY_GOLD) == (160, 640), (PASS_GOLD, MASTERY_GOLD)
assert len(reg.qualifications) == 4
ok("10. unchanged by this phase: 57 lessons, 457 activities, read-along required in all 57, "
   "Pre-A1/Taipei 7 and A1/A2/B1 5 required, PASS_GOLD 160, MASTERY_GOLD 640, 4 qualifications")

server.transcribe = _real_transcribe
print("\nAll %d STT-availability tests passed." % passed)
