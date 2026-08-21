#!/usr/bin/env python3
"""Phase 12B.2 — typed Read Along is an INPUT accommodation, not easier mastery.

    python3 tests/read_along_accommodation_test.py

All 57 lessons require Read Along, and Read Along is scored from speech, so a learner with no
microphone, a denied permission, an unsupported device or a speech-recognition accessibility need
could not reach authoritative mastery at all.

The fix changes the input modality and nothing else. `record_read_along()` already takes a TRANSCRIPT
and does everything authoritative itself — resolves the target sentence from lesson content, scores it
with the canonical `stt_scoring.score_sentence`, keeps best-per-sentence retry, and on crossing the
80% mark routes through `record_attempt` for grants and the reward policy. Typed mode therefore
converges on exactly that path; the only difference is where the text came from.

What this suite exists to prove: that the educator boundary is `may_manage()` and nothing else, that a
learner can never enable it for themselves, that the typed endpoint refuses a speech-only account
even when called directly, that the completion identity and reward semantics are byte-identical to
speech, and that typing is not a shortcut.
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
from learning import stt_scoring  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


import tempfile  # noqa: E402

d = tempfile.mkdtemp()
server.ROOMS_DIR = os.path.join(d, "rooms")
server.ACCT = os.path.join(d, "accounts.json")
server.PROG_DIR = os.path.join(d, "progress")
server.DATA = os.path.join(d, "visits.json")
server.TERR_CATALOG = os.path.join(d, "learned.json")
server.LEARNING.content_root = ROOT

srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % PORT
LID = "english.a1.core.001"
AID = LID + ".read_along"


def call(method, path, body=None, tok=None, raw=None):
    url = B + path
    if tok is not None:
        url += ("&" if "?" in url else "?") + "token=" + tok
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    try:
        r = U.urlopen(U.Request(url, data=data, method=method))
        return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def mk(user):
    c, j = call("POST", "/api/register", {"user": user, "pass": "pw123456"})
    assert c == 200, (user, c, j)
    return j["token"], j["code"]


def accounts():
    with open(server.ACCT) as f:
        return json.load(f)


TA, CODE_A = mk("T_OWN")
TB, CODE_B = mk("T_OTHER")
S1, _ = mk("LEARNER_1")
S2, _ = mk("LEARNER_2")
call("POST", "/api/class/sync?code=" + CODE_A, {"displayName": "One"}, tok=S1)
call("POST", "/api/class/sync?code=" + CODE_A, {"displayName": "Two"}, tok=S2)

# a room, so the room-scoped guard is satisfied for scoring calls
call("POST", "/api/room/create", {}, tok=S1)
ROOM = call("POST", "/api/room/start",
            {"map": "A1", "aiCount": 0, "resources": "medium", "capacity": 4}, tok=S1)[1]["code"]
R = "?room=" + ROOM


def setmode(target, mode, tok):
    return call("POST", "/api/accommodation/read-along", {"account": target, "mode": mode}, tok=tok)


def typed(text, tok, aid=AID, idx=0, room=True, extra=None):
    body = {"activityId": aid, "sentenceIndex": idx, "text": text}
    if extra:
        body.update(extra)
    return call("POST", "/api/learning/read-along/typed" + (R if room else ""), body, tok=tok)


def row(tok):
    p = call("GET", "/api/learning/progress" + R, tok=tok)[1]
    return (p.get("lessons") or {}).get(LID) or {}


def gold(tok):
    return call("GET", "/api/economy" + R, tok=tok)[1].get("gold", 0)


def target_of(idx):
    t, _ = server.LEARNING.read_along_target(AID, str(idx))
    return t


# ====================== 1. default is speech, with no migration ======================
db = accounts()
assert "readAlongMode" not in db["users"]["LEARNER_1"], db["users"]["LEARNER_1"]
assert server.read_along_mode_of("LEARNER_1", db) == "speech"
assert server.read_along_mode_of("NO_SUCH_ACCOUNT", db) == "speech"
st = call("GET", "/api/learning/state" + R, tok=S1)[1]
assert st.get("readAlongMode") == "speech", st
ok("1. every account defaults to speech with the field absent -- existing behaviour unchanged and "
   "no migration needed")

# ====================== 2. a learner cannot enable it for themselves ======================
before = json.dumps(accounts(), sort_keys=True)
for label, tok, tgt in [("self", S1, "LEARNER_1"), ("co-member", S2, "LEARNER_1"),
                        ("unrelated teacher", TB, "LEARNER_1")]:
    code, out = setmode(tgt, "typed", tok)
    assert code == 403 and out.get("reason") == "not_authorized", (label, code, out)
assert json.dumps(accounts(), sort_keys=True) == before, "a refused call mutated accounts"
assert server.read_along_mode_of("LEARNER_1") == "speech"
ok("2. a learner cannot enable typed mode for themselves, a co-member cannot, and an unrelated "
   "teacher cannot -- all 403 with zero mutation")

# ====================== 3. tokens and unknown targets fail closed ======================
for tok in (None, "", "bogus", "deadbeef" * 6):
    code, out = setmode("LEARNER_1", "typed", tok)
    assert code == 401, (tok, code, out)
code, out = setmode("GHOST_ACCOUNT", "typed", TA)
assert code == 403 and out.get("reason") == "not_authorized", (code, out)
code, out = setmode("LEARNER_1", "nonsense", TA)
assert code == 400 and out.get("reason") == "bad_mode", (code, out)
assert server.read_along_mode_of("LEARNER_1") == "speech"
ok("3. missing/invalid tokens 401, unknown target 403 (indistinguishable from unauthorized), "
   "unknown mode 400 -- all fail closed")

# ====================== 4. a legacy roster name cannot receive the setting ======================
with server.acct_lock:
    p = server.load_progress("T_OWN")
    p.setdefault("students", {})["LegacyKid"] = {"scores": {}}
    server.save_progress("T_OWN", p)
code, out = setmode("LegacyKid", "typed", TA)
assert code == 403, (code, out)
assert "LegacyKid" not in accounts()["users"], "a legacy name must never become an account"
ok("4. a legacy display-name roster row cannot be granted the setting -- may_manage() refuses it")

# ====================== 5. the owning teacher can enable and disable ======================
code, out = setmode("LEARNER_1", "typed", TA)
assert code == 200 and out.get("readAlongMode") == "typed", (code, out)
db = accounts()
assert db["users"]["LEARNER_1"]["readAlongMode"] == "typed"
assert db["users"]["LEARNER_1"]["readAlongModeBy"] == "T_OWN"
assert isinstance(db["users"]["LEARNER_1"].get("readAlongModeAt"), float)
# no diagnosis, reason or note is stored anywhere
blob = json.dumps(db["users"]["LEARNER_1"])
for banned in ("reason", "diagnos", "disab", "medical", "note", "condition", "justif"):
    assert banned not in blob.lower(), ("sensitive field stored: " + banned, blob)
assert call("GET", "/api/learning/state" + R, tok=S1)[1].get("readAlongMode") == "typed"
ok("5. the owning teacher can enable typed mode; provenance is actor+timestamp only, with no "
   "diagnosis, reason or note stored anywhere")

# ====================== 6. anti-bypass: a speech-only learner is refused ======================
b6 = (len(row(S2).get("completedActivityIds") or []), gold(S2))
code, out = typed(target_of(0), S2)
assert code == 403 and out.get("reason") == "typed_not_enabled", (code, out)
a6 = (len(row(S2).get("completedActivityIds") or []), gold(S2))
assert a6 == b6, ("a refused typed call changed state", b6, a6)
ok("6. a speech-only learner calling the typed endpoint DIRECTLY is refused 403 with no progress "
   "and no Gold -- hiding the text box is not the protection")

# ====================== 7. request validation ======================
code, out = typed(target_of(0), None)
assert code == 401, ("no token", code, out)
for label, kw in [("bad activity", {"aid": LID + ".quiz3"}),
                  ("unknown activity", {"aid": "nope.nope.read_along"}),
                  ("bad sentence index", {"idx": 999}), ("no room", {"room": False})]:
    code, out = typed(target_of(0), S1, **kw)
    assert code >= 400, (label, code, out)
code, out = call("POST", "/api/learning/read-along/typed" + R,
                 {"activityId": AID, "sentenceIndex": 0}, tok=S1)      # text missing
assert code == 400 and out.get("reason") == "no_text", (code, out)
ok("7. the typed endpoint validates token, activity identity, read-along type, sentence index, "
   "room and text presence -- every failure refuses")

# ====================== 8. the server scores; client claims are ignored ======================
code, out = typed("this is nothing like the sentence", S1,
                  extra={"score": 100, "passed": True, "rewarded": True, "activityPct": 100,
                         "target": "an easier sentence"})
assert code == 200, (code, out)
assert out["score"] == 0, ("the server must score what was typed", out)
assert out["target"] == target_of(0), ("the server must resolve its OWN target", out)
assert out["rewarded"] is False and out["rewardAmount"] == 0, out
assert out["activityPassed"] is False, out
ok("8. forged score/passed/rewarded/target fields are ignored: the server resolves the sentence "
   "itself and scores the typed text (0%%)")

# ====================== 9. score parity with the speech path ======================
tgt = target_of(1)
cases = [("exact sentence", tgt),
         ("capitalisation differs", tgt.upper()),
         ("punctuation differs", tgt.replace(".", "").replace(",", "").replace("?", "")),
         ("harmless whitespace", "   " + tgt.replace(" ", "   ") + "  "),
         ("one word missing", " ".join(tgt.split()[:-1])),
         ("one wrong word", " ".join(tgt.split()[:-1] + ["banana"])),
         ("clearly poor answer", "banana helicopter zebra")]
for label, text in cases:
    expected = stt_scoring.score_sentence(tgt, text)["pct"]
    code, out = typed(text, S1, idx=1)
    assert code == 200, (label, code, out)
    assert out["score"] == expected, (label, out["score"], expected)
print("     parity: " + " | ".join("%s=%d%%" % (l, stt_scoring.score_sentence(tgt, t)["pct"])
                                   for l, t in cases))
ok("9. typed scoring is the SAME canonical scorer as speech for all seven shapes -- exact, case, "
   "punctuation, whitespace, missing word, wrong word and a poor answer")

assert stt_scoring.PASS_MARK == 80, stt_scoring.PASS_MARK
ok("10. the pass threshold is the single shared PASS_MARK (80) -- typed mode has no easier bar")

# ====================== 11. reaching the activity: same completion identity ======================
_, total = server.LEARNING.read_along_target(AID, "0")
for i in range(total):
    code, out = typed(target_of(i), S1, idx=i)
    assert code == 200, (i, code, out)
r = row(S1)
assert AID in (r.get("completedActivityIds") or []), \
    ("typed completion must write the EXISTING read-along activity id", r)
for banned in ("read_along_typed", "typed_reading", "accommodation_complete", "skip_read_along"):
    assert not any(banned in a for a in (r.get("completedActivityIds") or [])), banned
    assert not any(banned in a for a in (r.get("requiredActivityIds") or [])), banned
assert len(r.get("requiredActivityIds") or []) == 5, r
ok("11. typed completion writes the EXISTING read-along activity id, introduces no shadow activity, "
   "and leaves the required set at 5")

# ====================== 12. reward parity + idempotency ======================
g_before = gold(S1)
code, out = typed(target_of(0), S1, idx=0)          # replay a sentence already at 100%
assert out["rewarded"] is False and out["rewardAmount"] == 0, out
assert gold(S1) == g_before, "a replay paid again"
# read-along itself mints no gate reward: the quiz3 gate is what pays PASS_GOLD
assert out.get("rewardAmount", 0) == 0
# finish the lesson: the LAST required activity pays MASTERY_GOLD once, via the same settlement
A1J = json.load(open(os.path.join(ROOT, "A1", "001.json"), encoding="utf-8"))
def attempt(key, ans):
    return call("POST", "/api/learning/attempt" + R,
                {"activityId": LID + "." + key, "answers": ans}, tok=S1)[1]
g0 = gold(S1)
o = attempt("quiz3", [{"q": i["q"], "answer": i["answer"]} for i in A1J["quiz3"]])
assert o["rewardAmount"] == PASS_GOLD, (o["rewardAmount"], PASS_GOLD)
attempt("reorder", [{"q": " ".join(x), "answer": list(range(len(x)))} for x in A1J["reorder"]])
attempt("dictation", [{"q": x, "answer": x} for x in A1J["dictation"]])
pic = {v["word"]: v["pic"] for v in server.LEARNING.matching_vocab(LID + ".matching")}
_, view = call("POST", "/api/learning/matching/start" + R, {"activityId": LID + ".matching"}, tok=S1)
last = None
for it in view["items"]:
    cid = next(c["choiceId"] for c in view["choices"] if c["pic"] == pic[it["word"]])
    last = call("POST", "/api/learning/matching/attempt" + R,
                {"roundId": view["roundId"], "itemId": it["itemId"], "choiceId": cid}, tok=S1)[1]
r = row(S1)
assert r.get("activePolicyCompleted") is True, ("the lesson must reach mastery", r)
assert gold(S1) >= g0 + PASS_GOLD + MASTERY_GOLD, (gold(S1), g0)
ok("12. read-along pays no gate reward in either mode; the quiz3 gate still pays PASS_GOLD (%d) and "
   "mastery pays MASTERY_GOLD (%d) once, through the same settlement" % (PASS_GOLD, MASTERY_GOLD))

# ====================== 13. cross-mode replay pays nothing ======================
g = gold(S1)
_real = server.transcribe
server.transcribe = lambda audio, tgt: tgt
code, out = call("POST", "/api/stt?room=%s&activityId=%s&sentenceIndex=0" % (ROOM, AID),
                 raw=b"\x00audio", tok=S1)
server.transcribe = _real
assert code == 200, (code, out)
assert out.get("rewarded") is False and out.get("lessonRewardAmount", 0) == 0, out
assert gold(S1) == g, ("a speech submission after typed mastery paid again", gold(S1), g)
code, out = typed(target_of(0), S1, idx=0)
assert out["rewarded"] is False and out.get("lessonRewardAmount", 0) == 0, out
assert gold(S1) == g, "a typed submission after mastery paid again"
assert row(S1).get("activePolicyCompleted") is True, "mastery is monotonic"
ok("13. speech-after-typed and typed-after-typed both pay ZERO and never re-grant mastery -- the "
   "existing idempotency remains authoritative across modes")

# ====================== 14. disabling preserves everything ======================
before_r = row(S1)
before_g = gold(S1)
code, out = setmode("LEARNER_1", "speech", TA)
assert code == 200 and out.get("readAlongMode") == "speech", (code, out)
assert "readAlongMode" not in accounts()["users"]["LEARNER_1"], "disable should clear the field"
after_r = row(S1)
assert after_r.get("activePolicyCompleted") is True, "mastery was revoked by a mode change"
assert sorted(after_r.get("completedActivityIds") or []) == \
       sorted(before_r.get("completedActivityIds") or []), "completion changed on a mode switch"
assert gold(S1) == before_g, "Gold moved on a mode switch"
code, out = typed(target_of(0), S1)
assert code == 403 and out.get("reason") == "typed_not_enabled", (code, out)
ok("14. disabling typed mode preserves completion, mastery and Gold exactly, and future typed "
   "submissions are refused")

# ====================== 15. a class move transfers control ======================
code, out = setmode("LEARNER_1", "typed", TA)
assert code == 200, out
call("POST", "/api/class/sync?code=" + CODE_B, {"displayName": "moved"}, tok=S1)
code, out = setmode("LEARNER_1", "speech", TA)
assert code == 403 and out.get("reason") == "not_authorized", \
    ("the OLD teacher must lose control immediately", code, out)
assert server.read_along_mode_of("LEARNER_1") == "typed", "the refused call changed the setting"
code, out = setmode("LEARNER_1", "speech", TB)
assert code == 200, ("the NEW owning teacher must gain control", code, out)
assert server.read_along_mode_of("LEARNER_1") == "speech"
# a stale roster copy left with the old teacher grants nothing
with server.acct_lock:
    pa = server.load_progress("T_OWN")
    pa.setdefault("members", {})["LEARNER_1"] = {"displayName": "stale"}
    server.save_progress("T_OWN", pa)
code, out = setmode("LEARNER_1", "typed", TA)
assert code == 403, ("a stale roster copy must not restore authority", code, out)
ok("15. a class move removes the old teacher's control at once and grants it to the new owner; a "
   "stale roster copy cannot restore it")

# ====================== 16. privacy ======================
dA = call("GET", "/api/dashboard", tok=TA)[1]
dB = call("GET", "/api/dashboard", tok=TB)[1]
assert "LEARNER_1" in (dB.get("members") or {}), dB
assert (dB["members"]["LEARNER_1"].get("readAlongMode")) in ("speech", "typed")
assert "LEARNER_1" not in (dA.get("members") or {}), "the old teacher still lists the learner"
st2 = call("GET", "/api/learning/state" + R, tok=S2)[1]
assert st2.get("readAlongMode") == "speech"
assert "LEARNER_1" not in json.dumps(st2), "another learner's identity leaked into learning state"
lb = json.dumps(call("GET", "/api/leaderboard")[1])
assert "readAlongMode" not in lb, "the setting leaked into the leaderboard"
for secret in ("salt", "hash", "token", "readAlongModeBy"):
    assert secret not in json.dumps(dB), ("the dashboard leaked " + secret)
ok("16. only the authorized manager sees a member's mode; a learner sees only their own; the "
   "setting never appears in the leaderboard, and no salt/hash/token/actor leaks to a teacher")

# ====================== 17. the curriculum contract is untouched ======================
from learning import registry as Rg  # noqa: E402
reg = Rg.REGISTRY
stt_acts = [a for a in reg.activities if reg.scorer_type_of(a) == "read_along_stt"]
assert (len(reg.lessons), len(reg.activities), len(stt_acts)) == (57, 457, 57)
req = 0
for lid in reg.lessons:
    pol = reg.completion_policy_of(lid) or {}
    r_ = pol.get("requiredActivityIds") or []
    if any(a in r_ for a in stt_acts if reg.activities[a]["lessonId"] == lid):
        req += 1
    assert len(r_) == (7 if lid.startswith("english.prea1") else 5), (lid, len(r_))
assert req == 57, req
assert (PASS_GOLD, MASTERY_GOLD) == (160, 640)
assert len(reg.qualifications) == 4
ok("17. unchanged: 57 lessons / 457 activities / 57 read-along required in 57, Pre-A1+Taipei 7 and "
   "A1/A2/B1 5, PASS_GOLD 160, MASTERY_GOLD 640, 4 qualifications -- Read Along is still REQUIRED")

print("\nAll %d read-along accommodation tests passed." % passed)
