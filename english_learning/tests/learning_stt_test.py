#!/usr/bin/env python3
"""Phase 3E1 — server-authoritative Read-Along (Level 2) scoring, persistence and outage behaviour.

    python3 tests/learning_stt_test.py

Golden cases live in tests/fixtures/learning_stt_golden.json and are shared with
tests/learning_stt_parity.test.js, which derives the SAME expectations from the live frontend rule in
index.html. If the port ever drifts, one of the two files fails.

Covers §23 parity, §24 normalization, §25 retry, §26 authority, §27 outage, §28 persistence,
§29 multiple real lessons, §30 Phase 3D dormancy.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from learning import (api as L, content as C, registry as R,  # noqa: E402
                      stt_scoring as S)

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


GOLDEN = json.load(open(os.path.join(ROOT, "tests", "fixtures", "learning_stt_golden.json"),
                        encoding="utf-8"))["cases"]

# ============================== §23 golden parity cases ==============================
for case in GOLDEN:
    got = S.score_sentence(case["target"], case["transcript"])
    for k in ("pct", "matchedTokens", "totalTokens"):
        assert got[k] == case["expect"][k], "%s: %s expected %r got %r" % (case["name"], k,
                                                                          case["expect"][k], got[k])
ok("§23 golden: %d cases match the ported scoring rule" % len(GOLDEN))

# ============================== §24 normalization ==============================
assert S.pron_words("I'm") == ["i", "am"], S.pron_words("I'm")
assert S.pron_words("I’m") == ["i", "am"], "curly apostrophe folded"
assert S.pron_words("Iʼm") == ["i", "am"], "modifier apostrophe folded"
assert S.pron_words("Hi, Anna. Look!") == ["hi", "anna", "look"], "punctuation dropped"
assert S.pron_words("  a   b  ") == ["a", "b"], "whitespace collapsed"
assert S.pron_words("") == [] and S.pron_words(None) == []
assert S.pron_words("123 456") == [], "digits are not words"
assert S.pron_words("don't won't cannot") == ["do", "not", "will", "not", "can", "not"]
assert S.pron_words("MiXeD CaSe") == ["mixed", "case"]
assert len(S.CONTRACTIONS) == 48, len(S.CONTRACTIONS)
# case / punctuation / extra words / missing words / empty transcript
T = "The panda is black and white."
assert S.score_sentence(T, "the panda is black and white")["pct"] == 100
assert S.score_sentence(T, "THE PANDA IS BLACK AND WHITE!!!")["pct"] == 100
assert S.score_sentence(T, "um the panda is black and white you know")["pct"] == 100, "extra words ok"
assert S.score_sentence(T, "the panda is black")["pct"] == 67, "missing words lower the score"
assert S.score_sentence(T, "")["pct"] == 0 and S.score_sentence(T, None)["pct"] == 0
assert S.score_sentence("", "anything")["pct"] == 0, "no target tokens -> 0"
assert S.score_sentence(None, "anything")["pct"] == 0
# word ORDER is irrelevant (existing behaviour), and each transcript word is consumed once
assert S.score_sentence(T, "white and black is panda the")["pct"] == 100, "order-independent"
assert S.score_sentence("the cat and the dog", "the cat and dog")["pct"] == 80, "multiset consumption"
assert S.score_sentence("the cat and the dog", "the the cat and dog")["pct"] == 100
# a target token with no letters is skipped entirely
assert S.score_sentence("hello -- world", "hello world") == {"pct": 100, "matchedTokens": 2,
                                                             "totalTokens": 2}
# contraction equivalence works in both directions
assert S.score_sentence("I'm happy", "i am happy")["pct"] == 100
assert S.score_sentence("I am happy", "i'm happy")["pct"] == 100
assert S.score_sentence("It's a lion", "it is a lion")["pct"] == 100
# all-or-nothing per target token: half a contraction does not score it
assert S.score_sentence("I'm happy", "i happy")["pct"] == 50
ok("§24 normalization: case/punct/whitespace/apostrophes/contractions/extra/missing/empty all exact")

# ============================== §25 retry — best per sentence ==============================
prog, improved = S.apply_sentence_score({}, 0, 40, 4, 100)
assert improved and prog["sentences"]["0"]["score"] == 40 and prog["pct"] == 10
prog, improved = S.apply_sentence_score(prog, 0, 90, 4, 200)          # better retry
assert improved and prog["sentences"]["0"] == {"score": 90, "updatedAt": 200} and prog["pct"] == 23
prog, improved = S.apply_sentence_score(prog, 0, 10, 4, 300)          # WORSE retry
assert improved is False, "a worse retry must not overwrite"
assert prog["sentences"]["0"] == {"score": 90, "updatedAt": 200}, "best-per-sentence preserved"
assert prog["pct"] == 23, "aggregate unchanged by a worse retry"
prog, _ = S.apply_sentence_score(prog, 0, 90, 4, 400)                 # equal retry is not an improvement
assert prog["sentences"]["0"]["updatedAt"] == 200
# aggregate = mean over ALL sentences, unscored counting as 0
for i, sc in ((1, 100), (2, 100), (3, 100)):
    prog, _ = S.apply_sentence_score(prog, i, sc, 4, 500)
assert prog["pct"] == 98, prog["pct"]          # (90+100+100+100)/4 = 97.5 -> 98 (half-up)
assert S.activity_pct({"sentences": {"0": {"score": 100}}}, 4) == 25
assert S.activity_pct({}, 0) == 0 and S.activity_pct(None, 4) == 0
# malformed stored state is normalized safely rather than crashing (§28)
junk = {"sentences": {"x": {"score": 100}, "1": {"score": "90"}, "2": None, "3": {"score": 999},
                      "4": {"score": True}, "5": {"score": 50}}}
assert S.best_scores(junk) == {5: 50}, S.best_scores(junk)
assert S.activity_pct(junk, 6) == 8
ok("§25 retry: best-per-sentence kept, worse/equal retries ignored, junk state normalized safely")

# ============================== service-level: content authority ==============================
svc = L.LearningService(content_root=ROOT, reward_amounts={"PASS_GOLD": 10000})
ZOO = "english.prea1.taipei.zoo.read_along"
A1 = "english.a1.core.001.read_along"
assert svc.is_read_along(ZOO) and svc.is_read_along(A1)
assert not svc.is_read_along("english.prea1.taipei.zoo.quiz3")
zoo_sentences = svc.read_along_sentences(ZOO)
a1_sentences = svc.read_along_sentences(A1)
assert len(zoo_sentences) == 10 and len(a1_sentences) == 10, (len(zoo_sentences), len(a1_sentences))
assert zoo_sentences[0] == "Hi, Anna. Look! We are at the zoo."
assert a1_sentences[0] == "Hi, Anna. What did you do yesterday?"
assert zoo_sentences != a1_sentences, "two different real lessons"
# the dialogue file matches what the frontend parser would produce
raw = open(os.path.join(ROOT, "Pre-A1", "taipei", "zoo"), encoding="utf-8").read()
expect = [l.split(":", 1)[1].strip() for l in raw.split("\n") if l.strip() and ":" in l]
assert zoo_sentences == expect, "server dialogue parse == parseDialogue()"
# index validation
for bad in (-1, 10, 999, "x", None, 1.5, True, False, "1.5", "-1", " ", "1e1", [0], {"i": 0}):
    t, n = svc.read_along_target(ZOO, bad)
    assert t is None and n in (0, 10), "index %r must be refused, got %r" % (bad, t)
# the query string always arrives as text, so digit strings are the normal path
assert svc.read_along_target(ZOO, "0")[0] == zoo_sentences[0]
assert svc.read_along_target(ZOO, 3)[0] == zoo_sentences[3]
assert svc.read_along_target("english.prea1.taipei.zoo.quiz3", 0) == (None, 0), "not a read-along"
assert svc.read_along_target("nope", 0) == (None, 0)
ok("§17/§18/§29 content authority: two real lessons resolve server-side, bad indexes/types refused")

# ============================== §26 authority + §28 persistence ==============================
st = {}
st, out = svc.record_read_along(st, ZOO, 0, "hi anna look we are at the zoo", 1000)
assert out["score"] == 100 and out["target"] == zoo_sentences[0]
assert out["activityPct"] == 10 and out["activityPassed"] is False
assert st["sttProgress"][ZOO]["sentences"]["0"] == {"score": 100, "updatedAt": 1000}
assert st["sttProgress"][ZOO]["totalSentences"] == 10
# no completion / qualification / reward below the threshold
assert (st.get("activityCompletions") or {}) == {} and (st.get("qualifications") or {}) == {}
assert out["rewarded"] is False and out["rewardAmount"] == 0
# a transcript that is nothing like the target scores low and does not overwrite the best
st, out2 = svc.record_read_along(st, ZOO, 0, "completely unrelated words", 2000)
assert out2["score"] < 100 and out2["improved"] is False
assert st["sttProgress"][ZOO]["sentences"]["0"]["score"] == 100
# survives a JSON round trip (this is exactly how it is persisted)
st = json.loads(json.dumps(st))
assert S.activity_pct(st["sttProgress"][ZOO], 10) == 10
# an unknown activity / bad index writes NOTHING
before = json.dumps(st, sort_keys=True)
for aid, i in ((ZOO, 99), ("nope", 0), ("english.prea1.taipei.zoo.quiz3", 0), (ZOO, "x")):
    st2, o = svc.record_read_along(st, aid, i, "hi", 3000)
    assert o is None, (aid, i)
assert json.dumps(st, sort_keys=True) == before, "a refused attempt mutates nothing"
ok("§26/§28 authority+persistence: server target/score only, sub-threshold grants nothing, refusals inert")

# crossing 80% flows through the normal activity machinery (still zero reward, zero qualification)
st3 = {}
for i, s in enumerate(zoo_sentences):
    st3, o = svc.record_read_along(st3, ZOO, i, s, 4000 + i)
    assert o["score"] == 100, (i, o)
assert o["activityPct"] == 100 and o["activityPassed"] is True
assert st3["activityCompletions"][ZOO]["pct"] == 100 and st3["activityCompletions"][ZOO]["passedAt"]
assert o["granted"] == [] and o["rewarded"] is False and o["rewardAmount"] == 0, o
assert (st3.get("qualifications") or {}) == {}, "§20: Read-Along grants no qualification"
assert o["lessonCompleted"] is False and o["lessonCompletedNow"] is False, "§13: lesson stays dormant"
first_passed = st3["activityCompletions"][ZOO]["passedAt"]
st3, o = svc.record_read_along(st3, ZOO, 0, zoo_sentences[0], 9999)     # repeat
assert st3["activityCompletions"][ZOO]["passedAt"] == first_passed, "first passedAt frozen"
assert o["rewarded"] is False and o["rewardAmount"] == 0, "no repeat payout"
ok("§12/§20/§21: crossing 80%% records an activity completion with 0 gold, 0 qualification, lesson dormant")

# the second real lesson behaves identically (not Zoo-specific)
st4 = {}
for i, s in enumerate(a1_sentences):
    st4, o = svc.record_read_along(st4, A1, i, s, 5000 + i)
assert o["activityPct"] == 100 and o["activityPassed"] is True
assert st4["activityCompletions"][A1]["pct"] == 100
assert ZOO not in st4["sttProgress"], "activities keep separate evidence"
ok("§29 second real lesson (A1/001) scores and persists identically — no Zoo special-casing")

# ============================== §30 Phase 3D dormancy ==============================
active = sorted(lid for lid in svc.registry.lessons if svc.registry.completion_available(lid))
assert active == ["english.prea1.taipei.market", "english.prea1.taipei.mrt", "english.prea1.taipei.park", "english.prea1.taipei.zoo"], active   # Phase 4D: the four Taipei v2 policies
everything = {"activityCompletions": {aid: {"passedAt": 1, "pct": 100, "rewarded": False}
                                      for aid in svc.registry.activities}}
for lid in svc.registry.lessons:
    assert svc.evaluate_lesson(lid, everything)["completed"] is False, lid
assert svc.progress_view(everything)["completedLessonIds"] == []
assert R.validate(R.DATA) == []
ok("§30 dormancy: production completionPolicy count is still 0 even with every activity passed")

# ============================== registry validation of the new scorer (§32) ==============================
import copy  # noqa: E402

BASE = copy.deepcopy(R.DATA)


def rejects(mutate, needle):
    d = copy.deepcopy(BASE)
    mutate(d)
    errs = R.validate(d)
    assert any(needle in e for e in errs), (needle, errs)


A = lambda d: d["activities"][ZOO]  # noqa: E731
rejects(lambda d: A(d).update(scorerType="whisper_magic"), "unknown scorerType")
rejects(lambda d: A(d).update(graderType="yes_no"), "declares both graderType and scorerType")
rejects(lambda d: A(d).update(contentKey="quiz3"), "must not declare a contentKey")
rejects(lambda d: A(d).update(graderConfig={"promptField": "q"}), "must not declare graderConfig")
rejects(lambda d: A(d).pop("scorerType"), "unknown graderType")
rejects(lambda d: A(d).update(rewardGold=999), "may not set")
rejects(lambda d: A(d).update(rewardPolicy="jackpot"), "invalid rewardPolicy")
assert R.validate(BASE) == []
ok("§32 validator: scorerType is validated, mutually exclusive with graderType, no reward coupling")

print("\nAll %d STT tests passed." % passed)
