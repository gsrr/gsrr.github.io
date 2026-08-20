#!/usr/bin/env python3
"""Phase 11E — the lesson shell shows Gold, so pin what the SERVER actually pays.

    python3 tests/lesson_reward_shell_test.py

Phase 11E gives the lesson page a reward moment: "+160 Gold" on a gate pass, "+640" on mastery,
"+0" on a replay, on optional practice and on a failure. That panel is only honest if those are the
amounts the server really settles, so this drives the real HTTP endpoints against a real room and
asserts the settlement report -- never a rendered string.

Everything here is end-to-end over HTTP with ONE exception: `transcribe()` is replaced by a perfect
reader. Every lesson's required set contains a read-along, and /api/stt answers 503 when speech
recognition is unavailable, so mastery is otherwise unreachable in a test environment. Only the
acoustic model is stubbed -- scoring, completion, qualification and reward settlement all run for
real, through the same handler the browser calls.
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
json.dump({"users": {"ALICE": {"code": "REWARD"}}, "codes": {"REWARD": "ALICE"}},
          open(server.ACCT, "w"))
server._tokens["tA"] = {"user": "ALICE", "exp": time.time() + 9999, "admin": False}

# the ONLY stub: a perfect reader, so the read-along can be scored without Whisper.
server.transcribe = lambda audio, target: target

srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % PORT


def call(method, path, body=None, tok="tA", raw=None):
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
R = "?room=" + CODE


def gold():
    """The balance the client itself would show. Read through /api/economy so the record is
    materialised: reading the raw store before the first settlement returns 0 rather than the
    room's starting gold, which made a +160 payout look like a +660 jump."""
    return call("GET", "/api/economy" + R)[1].get("gold", 0)


def row(lesson_id):
    prog = call("GET", "/api/learning/progress" + R)[1]
    return (prog.get("lessons") or {}).get(lesson_id) or {}


def attempt(aid, answers):
    return call("POST", "/api/learning/attempt" + R,
                {"activityId": aid, "answers": answers})[1]


def read_along(aid):
    """Read every sentence perfectly, through the real /api/stt handler."""
    _, total = server.LEARNING.read_along_target(aid, "0")
    out = None
    for i in range(total):
        # /api/stt is in ROOM_MUTATIONS (it can settle gold), so it fails closed without a room
        code, out = call("POST", "/api/stt?room=%s&activityId=%s&sentenceIndex=%d"
                         % (CODE, aid, i), raw=b"\x00fake-audio")
        assert code == 200, (code, out)
    return out


def matching(aid):
    """Solve a matching round correctly: pair each word with its own picture."""
    pic = {v["word"]: v["pic"] for v in server.LEARNING.matching_vocab(aid)}
    _, view = call("POST", "/api/learning/matching/start" + R, {"activityId": aid})
    rid = view["roundId"]
    out = None
    items, choices = view["items"], view["choices"]
    for n, it in enumerate(items):
        want = pic[it["word"]]
        cid = next(c["choiceId"] for c in choices if c["pic"] == want)
        _, out = call("POST", "/api/learning/matching/attempt" + R,
                      {"roundId": rid, "itemId": it["itemId"], "choiceId": cid})
        assert out.get("ok"), (n, out)
    return out


A1J = json.load(open(os.path.join(ROOT, "A1", "001.json"), encoding="utf-8"))
LID = "english.a1.core.001"
GATE = LID + ".quiz3"
OPTIONAL = LID + ".quiz4"          # catalogued but NOT required for A1
RIGHT_GATE = [{"q": i["q"], "answer": i["answer"]} for i in A1J["quiz3"]]
WRONG_GATE = [{"q": i["q"], "answer": ("No" if i["answer"] == "Yes" else "Yes")} for i in A1J["quiz3"]]
RIGHT_OPT = [{"q": i["q"], "answer": i["answer"]} for i in A1J["quiz4"]]

REQ = row(LID).get("requiredActivityIds") or []
assert REQ, "the A1/001 lesson must publish a required set"

# ====================== 8. the denominators the shell displays ======================
prog = call("GET", "/api/learning/progress" + R)[1]
reg = call("GET", "/api/learning/registry")[1]["registry"]
by_lesson = {}
for aid, spec in reg["activities"].items():
    by_lesson.setdefault(spec["lessonId"], []).append(aid)
for lid, r in (prog.get("lessons") or {}).items():
    need = len(r.get("requiredActivityIds") or [])
    have = len(by_lesson.get(lid) or [])
    if lid.startswith("english.prea1"):
        assert (have, need) == (7, 7), (lid, have, need)
    else:
        assert (have, need) == (9, 5), (lid, have, need)
assert len(REQ) == 5, len(REQ)
ok("8. required denominators are unchanged: Pre-A1/Taipei 7 of 7, A1/A2/B1 5 of 9 catalogued")

# ====================== 6. a FAILED attempt pays nothing ======================
g0 = gold()
out = attempt(GATE, WRONG_GATE)
assert out["ok"] is True and out["passed"] is False, out
assert out["rewarded"] is False and out["rewardAmount"] == 0, out
assert out["lessonRewarded"] is False and out["lessonRewardAmount"] == 0, out
assert gold() == g0, (gold(), g0)
# NOTE: a failing attempt still lands in completedActivityIds -- "completed" means the activity has
# EVIDENCE, not that it passed, and Rule A then judges the mean. What must not happen is a payout or
# a mastery grant, so those are what is asserted.
r = row(LID)
assert r.get("activePolicyCompleted") is not True, r
assert r.get("currentPolicySatisfied") is not True, r
ok("6. a failed gate attempt pays +0 and grants no mastery, leaving the balance untouched")

# ====================== 1. the gate's FIRST pass pays PASS_GOLD ======================
g0 = gold()
out = attempt(GATE, RIGHT_GATE)
assert out["ok"] is True and out["passed"] is True, out
assert out["rewarded"] is True, out
assert out["rewardAmount"] == PASS_GOLD, (out["rewardAmount"], PASS_GOLD)
assert gold() == g0 + PASS_GOLD, (gold(), g0, PASS_GOLD)
assert out["lessonRewardAmount"] == 0, ("mastery cannot land on the first activity", out)
ok("1. the gate's first pass pays exactly PASS_GOLD (%d) and the balance moves by that much"
   % PASS_GOLD)

# ====================== 2. a REPLAY pays nothing ======================
g0 = gold()
out = attempt(GATE, RIGHT_GATE)
assert out["ok"] is True and out["passed"] is True, out
assert out["rewarded"] is False and out["rewardAmount"] == 0, out
assert gold() == g0, (gold(), g0)
ok("2. replaying the same gate passes again but pays +0 -- the reward is once per lesson")

# ====================== 5. an OPTIONAL activity pays nothing ======================
assert OPTIONAL not in REQ, (OPTIONAL, REQ)
g0 = gold()
out = attempt(OPTIONAL, RIGHT_OPT)
assert out["ok"] is True and out["passed"] is True, out
assert out["rewarded"] is False and out["rewardAmount"] == 0, out
assert out["lessonRewardAmount"] == 0, out
assert gold() == g0, (gold(), g0)
after = row(LID)
assert len(after.get("requiredActivityIds") or []) == 5, after
assert OPTIONAL not in (after.get("requiredActivityIds") or []), after
ok("5. optional practice passes, pays +0, and does not change what mastery requires")

# ====================== 3. mastery pays MASTERY_GOLD, exactly once ======================
# finish every remaining required activity; the last one completes the lesson.
RIGHT_OTHER = {
    LID + ".reorder": [{"q": " ".join(s), "answer": list(range(len(s)))} for s in A1J["reorder"]],
    LID + ".dictation": [{"q": s, "answer": s} for s in A1J["dictation"]],
}
g_before_mastery = gold()
final = None
for aid in REQ:
    r = row(LID)
    if aid in (r.get("completedActivityIds") or []):
        continue
    if aid.endswith(".read_along"):
        final = read_along(aid)
    elif aid.endswith(".matching"):
        final = matching(aid)
    else:
        final = attempt(aid, RIGHT_OTHER[aid])
        assert final.get("passed") is True, (aid, final)

r = row(LID)
assert r.get("activePolicyCompleted") is True, ("the lesson must actually be mastered", r)
assert sorted(r.get("completedActivityIds") or []) == sorted(REQ), r
assert final is not None and final.get("lessonRewarded") is True, final
assert final.get("lessonRewardAmount") == MASTERY_GOLD, (final.get("lessonRewardAmount"), MASTERY_GOLD)
assert final.get("lessonCompletedNow") is True, final
assert gold() >= g_before_mastery + MASTERY_GOLD, (gold(), g_before_mastery)
ok("3. completing every required activity pays the mastery reward exactly once (%d)" % MASTERY_GOLD)

# ====================== 4. mastery does not pay twice ======================
g0 = gold()
out = attempt(GATE, RIGHT_GATE)
assert out["lessonRewarded"] is False and out["lessonRewardAmount"] == 0, out
assert out["rewarded"] is False and out["rewardAmount"] == 0, out
out2 = attempt(LID + ".dictation", RIGHT_OTHER[LID + ".dictation"])
assert out2["lessonRewardAmount"] == 0, out2
assert gold() == g0, (gold(), g0)
assert row(LID).get("activePolicyCompleted") is True, "mastery is monotonic"
ok("4. replaying activities after mastery pays +0 and never re-grants mastery")

# ====================== 7. qualification behaviour unchanged ======================
# the A1 pilot gate pays but grants NO credential; only the four Taipei gates grant.
granting = sorted(a for a, spec in reg["activities"].items() if spec.get("grants"))
assert GATE not in granting, (GATE, granting)
assert len(granting) == 4 and all(".taipei." in a for a in granting), granting
st = call("GET", "/api/learning/state" + R)[1]
assert (st.get("qualifications") or []) == [], ("mastering A1/001 must grant nothing", st)
ok("7. qualification behaviour is unchanged: the A1 gate pays but grants no credential, and only "
   "the four Taipei gates grant (%d)" % len(granting))

print("\nAll %d lesson-reward tests passed. PASS_GOLD=%d MASTERY_GOLD=%d"
      % (passed, PASS_GOLD, MASTERY_GOLD))
