#!/usr/bin/env python3
"""Phase 3C — the generic attempt endpoint across every migrated grader type.

    python3 tests/learning_attempt_test.py

Covers §30 one endpoint dispatches all graders, §31 reward isolation, §32 qualification isolation,
§33 failure handling per grader, §34 retries, §26 per-grader security.
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request as U

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402

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
json.dump({"users": {"ALICE": {"code": "GRADER"}}, "codes": {"GRADER": "ALICE"}}, open(server.ACCT, "w"))
server._tokens["tALICE"] = {"user": "ALICE", "exp": time.time() + 9999, "admin": False}
from http.server import ThreadingHTTPServer  # noqa: E402

srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % PORT


def call(method, path, body=None, tok="tALICE"):
    url = B + path + ("&" if "?" in path else "?") + "token=" + tok
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = U.urlopen(U.Request(url, data=data, method=method))
        return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


call("POST", "/api/room/create", {})
CODE = call("POST", "/api/room/start", {"map": "Pre-A1", "aiCount": 0, "resources": "medium",
                                        "capacity": 4})[1]["code"]


def attempt(activity_id, answers, extra=None):
    body = {"activityId": activity_id, "answers": answers}
    if extra:
        body.update(extra)
    return call("POST", "/api/learning/attempt?room=" + CODE, body)


def gold():
    server.set_room(CODE)
    e = server.load_econ_store().get("ALICE") or {}
    return e.get("gold", 0)


def state():
    return call("GET", "/api/learning/state?room=" + CODE)[1]


ZOO = json.load(open(os.path.join(ROOT, "Pre-A1", "taipei", "zoo.json"), encoding="utf-8"))
A1 = json.load(open(os.path.join(ROOT, "A1", "001.json"), encoding="utf-8"))
QID = "english.prea1.taipei.zoo"

# authoritative correct evidence for each migrated activity
RIGHT = {
    "english.prea1.taipei.zoo.quiz3": [{"q": i["q"], "answer": i["answer"]} for i in ZOO["quiz3"]],
    "english.prea1.taipei.zoo.quiz4": [{"q": i["q"], "answer": i["answer"]} for i in ZOO["quiz4"]],
    "english.prea1.taipei.zoo.wh": [{"q": i["q"], "answer": i["a"]} for i in ZOO["wh"]],
    "english.prea1.taipei.zoo.cloze": [{"q": i["text"], "answer": i["answer"]} for i in ZOO["cloze"]],
    "english.a1.core.001.reorder": [{"q": " ".join(s), "answer": list(range(len(s)))} for s in A1["reorder"]],
    "english.a1.core.001.dictation": [{"q": s, "answer": s.upper()} for s in A1["dictation"]],
}
WRONG = {
    "english.prea1.taipei.zoo.quiz3": [{"q": i["q"], "answer": ("No" if i["answer"] == "Yes" else "Yes")}
                                       for i in ZOO["quiz3"]],
    "english.prea1.taipei.zoo.quiz4": [{"q": i["q"], "answer": ("No" if i["answer"] == "Yes" else "Yes")}
                                       for i in ZOO["quiz4"]],
    "english.prea1.taipei.zoo.wh": [{"q": i["q"], "answer": (i.get("wrong") or ["x"])[0]} for i in ZOO["wh"]],
    "english.prea1.taipei.zoo.cloze": [{"q": i["text"], "answer": (i.get("wrong") or ["x"])[0]}
                                       for i in ZOO["cloze"]],
    "english.a1.core.001.reorder": [{"q": " ".join(s), "answer": list(reversed(range(len(s))))}
                                    for s in A1["reorder"] if len(s) > 1],
    "english.a1.core.001.dictation": [{"q": s, "answer": "definitely not the sentence"} for s in A1["dictation"]],
}
NO_REWARD = [a for a in RIGHT if a != "english.prea1.taipei.zoo.quiz3"]

# ============================== §30 one endpoint, every grader ==============================
reg = call("GET", "/api/learning/registry")[1]["registry"]
# Phase 3E1 added two Read-Along (STT) activities. They are server-SCORED but not gradable through
# the attempt endpoint, so they are advertised separately and excluded from the deterministic set.
READ_ALONG = {a for a, v in reg["activities"].items() if v.get("scored") == "stt"}
assert READ_ALONG == {"english.prea1.taipei.zoo.read_along", "english.a1.core.001.read_along"}, READ_ALONG
assert set(reg["activities"]) - READ_ALONG == set(RIGHT), sorted(reg["activities"])
assert all(reg["activities"][a]["serverGraded"] is True for a in reg["activities"])
assert all(reg["activities"][a]["scored"] == "deterministic" for a in RIGHT)
blob = json.dumps(reg)
for leak in ("graderType", "graderConfig", "rewardPolicy", "legacyKeys", "PASS_GOLD", "10000",
             "promptField", "answerField"):
    assert leak not in blob, "public registry leaks %s" % leak
ok("§18 registry: 6 activities advertised as serverGraded; no grader/reward internals leaked")

# The economy row is created lazily on first use, so materialise it before measuring the baseline —
# otherwise the room's starting gold would look like a reward. All gold assertions below are deltas.
call("GET", "/api/economy?room=" + CODE)
G0 = gold()
results = {}
for aid in RIGHT:
    code, body = attempt(aid, RIGHT[aid])
    assert code == 200 and body["passed"] is True and body["pct"] == 100, (aid, code, body)
    assert body["activityId"] == aid
    results[aid] = body
assert len({tuple(sorted(b.keys())) for b in results.values()}) == 1, "one uniform response shape"
ok("§30 dispatch: yes_no / multiple_choice(wh) / multiple_choice(cloze) / reorder / dictation all "
   "pass 100%% through ONE /api/learning/attempt")

# ============================== §31 reward isolation ==============================
g_now = gold()
assert results["english.prea1.taipei.zoo.quiz3"]["rewarded"] is True
assert results["english.prea1.taipei.zoo.quiz3"]["gold"] == G0 + server.PASS_GOLD
for aid in NO_REWARD:
    assert results[aid]["rewarded"] is False and results[aid]["gold"] is None, aid
assert g_now - G0 == server.PASS_GOLD, "exactly ONE payout across all six passing activities: %s" % g_now
# repeats pay nothing, for every type
for aid in RIGHT:
    attempt(aid, RIGHT[aid])
assert gold() - G0 == server.PASS_GOLD, "repeats mint nothing: %s" % gold()
ok("§31 reward isolation: 5 migrated activities pay 0, only the Zoo slice pays PASS_GOLD once")

# ============================== §32 qualification isolation ==============================
st = state()
assert set(st["qualifications"]) == {QID}, st["qualifications"]
assert set(st["activityCompletions"]) == set(RIGHT), sorted(st["activityCompletions"])
ok("§32 qualification isolation: 6 completions recorded, but only the granting activity certifies one")

# a synthetic in-memory activity granting TWO qualifications (production data stays clean)
regobj = server.LEARNING.registry
regobj.qualifications["test.q1"] = {"scope": "activity", "title": "T1"}
regobj.qualifications["test.q2"] = {"scope": "activity", "title": "T2"}
regobj.activities["english.prea1.taipei.zoo.multi"] = {
    "lessonId": "english.prea1.taipei.zoo", "contentKey": "quiz4", "graderType": "yes_no",
    "title": "multi", "grants": ["test.q1", "test.q2"], "rewardPolicy": "none"}
# run it as a DIFFERENT learner so ALICE's state stays clean for the security assertions below
server._tokens["tCAROL"] = {"user": "CAROL", "exp": time.time() + 9999, "admin": False}
code, body = call("POST", "/api/learning/attempt?room=" + CODE,
                  {"activityId": "english.prea1.taipei.zoo.multi",
                   "answers": RIGHT["english.prea1.taipei.zoo.quiz4"]}, tok="tCAROL")
assert code == 200 and body["passed"] is True and body["qualifications"] == ["test.q1", "test.q2"], body
assert body["rewarded"] is False and gold() - G0 == server.PASS_GOLD, "ALICE's gold untouched"
carol = call("GET", "/api/learning/state?room=" + CODE, tok="tCAROL")[1]
assert set(carol["qualifications"]) == {"test.q1", "test.q2"}, carol
server.set_room(CODE)
assert (server.load_econ_store().get("CAROL") or {}).get("gold", 0) == 0, "a none-policy pass pays nothing"
regobj.activities.pop("english.prea1.taipei.zoo.multi")
regobj.qualifications.pop("test.q1"); regobj.qualifications.pop("test.q2")
ok("§32 multi-grant: one server-graded activity certifies Q1+Q2 with still zero gold")

# ============================== §33 failures, per grader ==============================
for aid in RIGHT:
    before_g, before_st = gold(), state()
    code, body = attempt(aid, WRONG[aid])
    assert code == 200 and body["passed"] is False, (aid, body)
    assert body["qualifications"] == [] and body["rewarded"] is False and body["gold"] is None, (aid, body)
    assert gold() == before_g, aid
    # a failing retry must not disturb the completion already recorded by the earlier pass
    assert state()["activityCompletions"][aid]["passedAt"] == \
        before_st["activityCompletions"][aid]["passedAt"], aid
ok("§33 failures: every grader rejects wrong evidence — no reward, no qualification, no re-dating")

# malformed / partial evidence, per grader
BAD = [None, "yes", 5, {"a": 1}]
for aid in RIGHT:
    for bad in BAD:
        code, body = call("POST", "/api/learning/attempt?room=" + CODE,
                          {"activityId": aid, "answers": bad})
        assert code == 400 and body["reason"] == "bad_answers", (aid, bad, code, body)
    code, body = attempt(aid, [])                    # empty list IS a valid (empty) submission
    assert code == 200 and body["passed"] is False and body["rewarded"] is False, (aid, body)
    code, body = attempt(aid, [{"junk": 1}, {"q": None, "answer": None}])
    assert code == 200 and body["passed"] is False, (aid, body)
# partial payload: half the items answered correctly is still below PASS_MARK for these sizes
half = {a: RIGHT[a][:1] for a in RIGHT}
for aid in RIGHT:
    code, body = attempt(aid, half[aid])
    assert code == 200 and body["passed"] is False, (aid, body)
assert gold() - G0 == server.PASS_GOLD
ok("§33 malformed/partial: non-list evidence -> 400 bad_answers; junk/empty/partial -> safe non-pass")

# ============================== §26 security, per grader ==============================
for aid in RIGHT:
    # forged authority fields are ignored — wrong answers stay wrong
    code, body = attempt(aid, WRONG[aid], {
        "passed": True, "pct": 100, "correct": 99, "total": 99, "score": 100,
        "graderType": "yes_no", "graderConfig": {"answerField": "q"},
        "qualification": QID, "qualifications": [QID], "grants": [QID],
        "rewardPolicy": "standard_activity_pass", "rewardGold": 999999, "gold": 999999,
        "rewarded": True, "contentPath": "../../etc/passwd", "lessonId": "../../etc/passwd"})
    assert code == 200 and body["passed"] is False and body["pct"] == 0, (aid, body)
    assert body["qualifications"] == [] and body["rewarded"] is False and body["gold"] is None, (aid, body)
assert gold() - G0 == server.PASS_GOLD, "forged fields never minted gold"
assert set(state()["qualifications"]) == {QID}
# a forged graderConfig cannot re-point a grader at an easier field
code, body = attempt("english.prea1.taipei.zoo.wh",
                     [{"q": i["q"], "answer": i["q"]} for i in ZOO["wh"]],
                     {"graderConfig": {"answerField": "q"}})
assert body["passed"] is False and body["pct"] == 0, body
# unknown / traversal activity ids, and lesson ids used as activity ids
for bad_id in ("nope", "english.prea1.taipei.zoo", "english.a1.core.001", "../../etc/passwd",
               "english.prea1.taipei.zoo.quiz3.extra", "", "english.prea1.taipei.zoo.vocab",
               "english.prea1.taipei.zoo.matching"):
    code, body = call("POST", "/api/learning/attempt?room=" + CODE,
                      {"activityId": bad_id, "answers": []})
    assert code == 400 and body["reason"] == "not_gradable", (bad_id, code, body)
    assert "/" not in json.dumps(body) or "etc/passwd" not in json.dumps(body), bad_id
    for tell in (ROOT, "Traceback", ".json", "\\"):
        assert tell not in json.dumps(body), "error leaks filesystem detail for %r: %s" % (bad_id, body)
assert call("POST", "/api/learning/attempt",
            {"activityId": "english.prea1.taipei.zoo.wh", "answers": []}, tok="bogus")[0] == 401
ok("§26 security: forged score/passed/qualification/gold/graderConfig ignored; unknown & traversal ids "
   "rejected with no filesystem detail")

# /api/economy/pass still cannot mint gold (§39)
g = gold()
for f in ("Pre-A1/taipei/zoo", "A1/001", "anything/at/all"):
    code, body = call("POST", "/api/economy/pass?room=" + CODE, {"file": f})
    assert code == 200 and "gold" not in body and body.get("legacy") is True, body
assert gold() == g
ok("§39 /api/economy/pass still mints no gold for any lesson id")

# ============================== §34 retries ==============================
# fail -> retry -> pass on a fresh activity (use the multi-grader set on a fresh user)
server._tokens["tBOB"] = {"user": "BOB", "exp": time.time() + 9999, "admin": False}
for aid in ("english.prea1.taipei.zoo.wh", "english.a1.core.001.reorder",
            "english.a1.core.001.dictation", "english.prea1.taipei.zoo.quiz3"):
    c1, b1 = call("POST", "/api/learning/attempt?room=" + CODE,
                  {"activityId": aid, "answers": WRONG[aid]}, tok="tBOB")
    assert b1["passed"] is False and b1["alreadyCompleted"] is False, (aid, b1)
    c2, b2 = call("POST", "/api/learning/attempt?room=" + CODE,
                  {"activityId": aid, "answers": RIGHT[aid]}, tok="tBOB")
    assert b2["passed"] is True and b2["alreadyCompleted"] is False, (aid, b2)
stb = call("GET", "/api/learning/state?room=" + CODE, tok="tBOB")[1]
first = {a: stb["activityCompletions"][a]["passedAt"] for a in stb["activityCompletions"]}
first_earned = stb["qualifications"][QID]["earnedAt"]
bob_gold_after_first = None
server.set_room(CODE)
bob_gold_after_first = server.load_econ_store()["BOB"]["gold"]
# pass again with a WORSE (but still passing) score where possible, then a failing one
worse = [{"q": i["q"], "answer": i["a"]} for i in ZOO["wh"]]
worse[-1] = {"q": ZOO["wh"][-1]["q"], "answer": (ZOO["wh"][-1].get("wrong") or ["x"])[0]}
c, b = call("POST", "/api/learning/attempt?room=" + CODE,
            {"activityId": "english.prea1.taipei.zoo.wh", "answers": worse}, tok="tBOB")
assert b["alreadyCompleted"] is True and b["rewarded"] is False, b
for aid in ("english.prea1.taipei.zoo.wh", "english.prea1.taipei.zoo.quiz3"):
    call("POST", "/api/learning/attempt?room=" + CODE,
         {"activityId": aid, "answers": WRONG[aid]}, tok="tBOB")
stb2 = call("GET", "/api/learning/state?room=" + CODE, tok="tBOB")[1]
for a, t in first.items():
    assert stb2["activityCompletions"][a]["passedAt"] == t, "first passedAt preserved for " + a
assert stb2["qualifications"][QID]["earnedAt"] == first_earned, "earnedAt preserved"
server.set_room(CODE)
assert server.load_econ_store()["BOB"]["gold"] == bob_gold_after_first, "no second payout on retry"
# documented pct semantics: the record carries the LATEST PASSING pct (a later failure does not lower it)
wh_rec = stb2["activityCompletions"]["english.prea1.taipei.zoo.wh"]
assert wh_rec["pct"] == 80, "latest PASSING pct is stored (80 from the 'worse' pass): %s" % wh_rec
assert wh_rec["rewarded"] is False, "this activity's policy is none, so rewarded stays false"
ok("§34 retries: fail->retry->pass works; first passedAt/earnedAt frozen; no second payout; "
   "record keeps the latest PASSING pct")

# ============ Phase 3D: lesson completion is dormant in production and unforgeable over HTTP ============
code, prog = call("GET", "/api/learning/progress?room=" + CODE)
assert code == 200 and set(prog) == {"lessons", "completedLessonIds"}, prog
assert prog["completedLessonIds"] == [], prog
assert all(l["authoritativeCompletionAvailable"] is False and l["completed"] is False
           for l in prog["lessons"].values()), prog["lessons"]
blob = json.dumps(prog)
for leak in ("answer", "graderType", "graderConfig", "rewardPolicy", "PASS_GOLD", "10000", "contentPath"):
    assert leak not in blob, "progress endpoint leaks " + leak
assert call("GET", "/api/learning/progress", tok="bogus")[0] == 401
# ALICE has passed every registered activity by now, and still completes no lesson
st = state()
assert set(st["activityCompletions"]) >= set(RIGHT) and st["lessonCompletions"] == {}, st
# every attempt response carries the lesson fields, on pass AND on fail, with no completion
for aid in ("english.prea1.taipei.zoo.quiz3", "english.prea1.taipei.zoo.wh"):
    for answers in (RIGHT[aid], WRONG[aid]):
        c, b = attempt(aid, answers)
        assert c == 200, (aid, c, b)
        assert b["lessonCompleted"] is False and b["lessonCompletedNow"] is False, (aid, b)
        assert b["lessonQualifications"] == [] and b["lessonRewarded"] is False, (aid, b)
        assert b["lessonId"] == "english.prea1.taipei.zoo", b
# there is NO client-authoritative completion endpoint (§15)
for path in ("/api/learning/completeLesson", "/api/learning/complete", "/api/learning/lesson"):
    c, _ = call("POST", path + "?room=" + CODE, {"lessonId": "english.prea1.taipei.zoo", "passed": True})
    assert c == 404, (path, c)
# forged lesson fields on a real attempt change nothing
g_pre = gold()
c, b = attempt("english.prea1.taipei.zoo.quiz3", RIGHT["english.prea1.taipei.zoo.quiz3"], {
    "lessonCompleted": True, "lessonCompletedNow": True, "completed": True, "average": 100,
    "policyVersion": 999, "requiredActivityIds": [], "lessonQualifications": ["x"],
    "lessonRewarded": True, "lessonRewardAmount": 999999,
    "completionPolicy": {"type": "all_required_activities", "version": 1,
                         "requiredActivityIds": ["english.prea1.taipei.zoo.quiz3"]}})
assert b["lessonCompleted"] is False and b["lessonRewarded"] is False, b
assert gold() == g_pre and state()["lessonCompletions"] == {}, "forged completion minted nothing"
ok("§15/§26/§27 lesson completion: dormant in production, read-only endpoint, no client mutator, "
   "forged completion/policy/reward fields ignored")

# ============ Phase 3E1: Read-Along STT authority over HTTP (§22, §26, §27) ============
ZOO_RA = "english.prea1.taipei.zoo.read_along"
ZOO_SENTENCES = server.LEARNING.read_along_sentences(ZOO_RA)
_real_transcribe = server.transcribe


def stt(query, body=b"AUDIO", tok="tALICE"):
    url = B + "/api/stt?" + query + ("&" if query else "") + "token=" + tok
    try:
        r = U.urlopen(U.Request(url, data=body, method="POST"))
        return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# the server transcribes; the test controls what the "microphone" produced
def fake_transcribe(text):
    def _t(audio, hint=""):
        fake_transcribe.last_hint = hint
        return text
    return _t


g_stt = gold()
server.transcribe = fake_transcribe(ZOO_SENTENCES[0].lower())
code, b = stt("activityId=%s&sentenceIndex=0" % ZOO_RA)
assert code == 200 and b["authoritative"] is True, (code, b)
assert b["score"] == 100 and b["target"] == ZOO_SENTENCES[0] and b["totalSentences"] == 10
assert b["activityPct"] == 10 and b["activityPassed"] is False and b["rewarded"] is False
assert b["gold"] is None and gold() == g_stt
st = state()
assert st["sttProgress"][ZOO_RA]["sentences"]["0"]["score"] == 100
assert ZOO_RA not in st["activityCompletions"], "10%% is far below the 80%% threshold"
ok("§16 STT authoritative mode: server resolves the target, scores it, persists it, pays nothing")

# the client cannot substitute an easier target: ?text= is ignored in authoritative mode
server.transcribe = fake_transcribe("easy")
code, b = stt("activityId=%s&sentenceIndex=1&text=easy" % ZOO_RA)
assert code == 200 and b["target"] == ZOO_SENTENCES[1], b["target"]
assert b["score"] < 100, "a one-word transcript cannot score the real sentence"
assert fake_transcribe.last_hint == ZOO_SENTENCES[1], "the whisper hint is the SERVER's sentence"
# forged score/pass/reward fields in the query are ignored
server.transcribe = fake_transcribe("nothing like it")
code, b = stt("activityId=%s&sentenceIndex=2&score=100&pct=100&passed=true&activityPct=100"
              "&rewardGold=999999&qualification=english.prea1.taipei.zoo" % ZOO_RA)
assert code == 200 and b["score"] < 100 and b["activityPassed"] is False, b
assert b["rewarded"] is False and gold() == g_stt
assert set(state()["qualifications"]) == {QID}, "no new qualification from Read-Along"
ok("§22/§26 authority: forged target/score/pass/reward/qualification in the request are all ignored")

# malformed identity fails safely and writes nothing
before = json.dumps(state(), sort_keys=True)
for q in ("activityId=%s&sentenceIndex=99" % ZOO_RA, "activityId=%s&sentenceIndex=-1" % ZOO_RA,
          "activityId=%s&sentenceIndex=x" % ZOO_RA, "activityId=%s&sentenceIndex=1.5" % ZOO_RA,
          "activityId=%s" % ZOO_RA, "activityId=nope&sentenceIndex=0",
          "activityId=english.prea1.taipei.zoo.quiz3&sentenceIndex=0",
          "activityId=../../etc/passwd&sentenceIndex=0"):
    c, bb = stt(q)
    assert c == 400 and bb.get("reason") in ("bad_sentence", "not_scorable"), (q, c, bb)
    for tell in (ROOT, "Traceback", ".json", "\\"):
        assert tell not in json.dumps(bb), (q, bb)
assert json.dumps(state(), sort_keys=True) == before, "refused requests mutate nothing"
assert stt("activityId=%s&sentenceIndex=0" % ZOO_RA, tok="bogus")[0] == 401
assert stt("activityId=%s&sentenceIndex=0" % ZOO_RA, body=b"")[0] == 400, "no audio"
ok("§22 malformed identity: out-of-range/float/missing/unknown/non-read-along/traversal all 400, inert")

# §27 OUTAGE: a failing STT backend must never become authoritative success
def boom(audio, hint=""):
    raise RuntimeError("whisper model unavailable: /opt/models/base.en missing")


server.transcribe = boom
before = json.dumps(state(), sort_keys=True)
g_before = gold()
code, b = stt("activityId=%s&sentenceIndex=3" % ZOO_RA)
assert code == 503 and b.get("reason") == "stt_unavailable", (code, b)
assert "whisper" not in json.dumps(b).lower() and "/opt" not in json.dumps(b), "no internal detail leaked"
assert json.dumps(state(), sort_keys=True) == before, "an outage writes NO state"
assert gold() == g_before, "an outage mints no gold"
st = state()
assert "3" not in (st["sttProgress"].get(ZOO_RA) or {}).get("sentences", {}), "no score recorded"
assert ZOO_RA not in st["activityCompletions"], "no completion forged"
assert set(st["qualifications"]) == {QID}, "no qualification forged"
ok("§27 OUTAGE: failing STT -> 503, zero score/completion/qualification/reward, no full-marks fallback")

# legacy mode (roleplay: no activityId) still works and stays non-authoritative
server.transcribe = fake_transcribe("free conversation text")
before = json.dumps(state(), sort_keys=True)
code, b = stt("")
assert code == 200 and b["transcript"] == "free conversation text" and b["authoritative"] is False, b
assert "score" not in b and "activityPct" not in b, b
assert json.dumps(state(), sort_keys=True) == before, "legacy mode creates no learning state"
ok("§16 legacy mode: roleplay's target-less /api/stt still works and creates no authoritative state")

# crossing the threshold flows through the normal machinery: completion, still zero gold
server.set_room(CODE)
g_before = gold()
for i, s in enumerate(ZOO_SENTENCES):
    server.transcribe = fake_transcribe(s.lower())
    c, b = stt("activityId=%s&sentenceIndex=%d" % (ZOO_RA, i))
    assert c == 200 and b["score"] == 100, (i, b)
assert b["activityPct"] == 100 and b["activityPassed"] is True and b["rewarded"] is False, b
st = state()
assert st["activityCompletions"][ZOO_RA]["pct"] == 100
assert gold() == g_before, "Read-Along pays no gold (rewardPolicy none)"
assert set(st["qualifications"]) == {QID}, "and grants no qualification"
assert st["lessonCompletions"] == {}, "§13 lesson completion stays dormant"
first = st["activityCompletions"][ZOO_RA]["passedAt"]
server.transcribe = fake_transcribe("bad")
stt("activityId=%s&sentenceIndex=0" % ZOO_RA)
st2 = state()
assert st2["activityCompletions"][ZOO_RA]["passedAt"] == first, "first passedAt frozen"
assert st2["sttProgress"][ZOO_RA]["sentences"]["0"]["score"] == 100, "best-per-sentence survives a bad retry"
assert gold() == g_before
ok("§12/§25 threshold: 100%% records a completion with 0 gold/0 qualification; bad retry keeps the best")

server.transcribe = _real_transcribe

srv.shutdown()
print("\nAll %d attempt-endpoint tests passed." % passed)
