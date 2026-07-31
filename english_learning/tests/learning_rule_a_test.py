#!/usr/bin/env python3
"""Phase 3F — authoritative Rule A: activityScores evidence + average_required_activities + Zoo.

    python3 tests/learning_rule_a_test.py

Covers the golden Rule A parity cases (including the previously impossible case E), the new
activityScores store, latest-wins retry semantics, and real-Zoo activation.
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from learning import api as L, completion as C, registry as R  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


svc = L.LearningService(content_root=ROOT, reward_amounts={"PASS_GOLD": 10000})
ZOO_LESSON = "english.prea1.taipei.zoo"
REQ = ["english.prea1.taipei.zoo.read_along", "english.prea1.taipei.zoo.quiz3",
       "english.prea1.taipei.zoo.quiz4", "english.prea1.taipei.zoo.matching",
       "english.prea1.taipei.zoo.wh", "english.prea1.taipei.zoo.cloze"]

# ============================== golden Rule A parity (synthetic) ==============================
POLICY = {"completionPolicy": {"type": "average_required_activities", "version": 1,
                               "passMark": 80, "requiredActivityIds": list("abcdef")}}


def ev(scores):
    return C.evaluate("x", POLICY, set(), scores)


def s(correct, total):
    return {"correct": correct, "total": total, "pct": int(correct * 100.0 / total + 0.5)}


full = {k: s(5, 5) for k in "abcdef"}
# A. every level 80 -> mean 80 -> complete
r = ev({k: s(4, 5) for k in "abcdef"})
assert r["completed"] is True and r["roundedPct"] == 80, r
# B. one missing -> incomplete, and named
miss = dict(full)
miss.pop("c")
r = ev(miss)
assert r["completed"] is False and r["missingActivityIds"] == ["c"] and r["meanPct"] is None, r
# C. mean 79.x -> rounds below 80 -> incomplete
r = ev({"a": s(4, 5), "b": s(4, 5), "c": s(4, 5), "d": s(4, 5), "e": s(4, 5), "f": s(38, 50)})
assert abs(r["meanPct"] - 79.33333) < 1e-4 and r["roundedPct"] == 79 and r["completed"] is False, r
# D. mean exactly 79.5 -> half-up to 80 -> complete
r = ev({"a": s(4, 5), "b": s(4, 5), "c": s(4, 5), "d": s(4, 5), "e": s(4, 5), "f": s(77, 100)})
assert abs(r["meanPct"] - 79.5) < 1e-9 and r["roundedPct"] == 80 and r["completed"] is True, r
# E. MANDATORY: an individual level below 80, mean >= 80 -> COMPLETE.
#    This is the case that proves the policy is NOT "every activity must pass".
caseE = {"a": s(5, 5), "b": s(5, 5), "c": s(5, 5), "d": s(5, 5), "e": s(3, 5), "f": s(5, 5)}
r = ev(caseE)
assert abs(r["meanPct"] - 93.33333) < 1e-4 and r["roundedPct"] == 93 and r["completed"] is True, r
assert r["activityScores"]["e"]["pct"] == 60, "the sub-80 level is present and counted"
# F. all high but one missing -> incomplete
r = ev({k: s(5, 5) for k in "abcde"})
assert r["completed"] is False and r["missingActivityIds"] == ["f"], r
# the mean is UNWEIGHTED: a 1-item level counts as much as a 100-item level
r = ev({"a": s(1, 1), "b": s(1, 1), "c": s(1, 1), "d": s(1, 1), "e": s(1, 1), "f": s(0, 100)})
assert abs(r["meanPct"] - (500 / 6.0)) < 1e-9 and r["roundedPct"] == 83, r
ok("golden Rule A: all-80 / missing / 79.x / exact-79.5 / sub-80-but-mean-passes (case E) / unweighted")

# per-level terms are UNROUNDED (2/3 = 66.666..., not 67), with ONE final half-up round
r = ev({k: s(2, 3) for k in "abcdef"})
assert abs(r["meanPct"] - 66.6666667) < 1e-6 and r["roundedPct"] == 67, r
# operation ORDER matters at the ULP level: JS evaluates correct/total*100, so we must too
# (2/3*100 = 66.66666666666666, whereas 200/3 = 66.66666666666667 — a different float)
assert C.rule_a_mean({"a": {"correct": 2, "total": 3}}, ["a"]) == 2 / 3.0 * 100
assert C._round_half_up(79.5) == 80 and C._round_half_up(80.5) == 81
assert round(79.5) == 80 and round(80.5) == 80, "python round() is banker's; ours must not be"
# a malformed / unavailable policy never completes
assert C.evaluate("x", {}, set(), full)["completed"] is False
assert C.evaluate("x", {"completionPolicy": {"type": "average_required_activities", "version": 1,
                                             "requiredActivityIds": []}}, set(), full)["completed"] is False
ok("precision: per-level terms unrounded, one final JS-style half-up round; malformed policy inert")

# ============================== activityScores store ==============================
ZOO = json.load(open(os.path.join(ROOT, "Pre-A1", "taipei", "zoo.json"), encoding="utf-8"))
WH = "english.prea1.taipei.zoo.wh"


def wh_answers(n_right):
    return ([{"q": i["q"], "answer": i["a"]} for i in ZOO["wh"][:n_right]] +
            [{"q": i["q"], "answer": (i.get("wrong") or ["x"])[0]} for i in ZOO["wh"][n_right:]])


# a FAILED deterministic attempt now persists a score, but still no completion
st = {}
res, _ = svc.grade_attempt(WH, wh_answers(3))
st, out = svc.record_attempt(st, WH, res, 100)
assert out["passed"] is False
assert st["activityScores"][WH] == {"correct": 3, "total": 5, "pct": 60, "updatedAt": 100}
assert (st.get("activityCompletions") or {}) == {}, "a failed attempt is NOT a completion"
assert svc.authoritative_activity_score(st, WH) == {"correct": 3, "total": 5, "pct": 60}
# a PASS persists both
res, _ = svc.grade_attempt(WH, wh_answers(5))
st, out = svc.record_attempt(st, WH, res, 200)
assert st["activityScores"][WH]["pct"] == 100 and st["activityCompletions"][WH]["pct"] == 100
first_passed = st["activityCompletions"][WH]["passedAt"]
# a LOWER retry after a pass: score drops (latest-wins), completion survives, no second reward
res, _ = svc.grade_attempt(WH, wh_answers(3))
st, out = svc.record_attempt(st, WH, res, 300)
assert st["activityScores"][WH] == {"correct": 3, "total": 5, "pct": 60, "updatedAt": 300}
assert st["activityCompletions"][WH]["passedAt"] == first_passed, "completion is not revoked"
assert out["rewarded"] is False and out["rewardAmount"] == 0
assert svc.authoritative_activity_score(st, WH)["pct"] == 60, "Rule A sees the LATEST score"
st = json.loads(json.dumps(st))
assert svc.authoritative_activity_score(st, WH)["correct"] == 3, "survives the JSON round trip"
ok("activityScores: fail persists a score but no completion; pass persists both; a lower retry is "
   "latest-wins and never revokes the completion or re-pays")

# the resolver normalizes all three evidence shapes into exact correct/total
st2 = {"sttProgress": {REQ[0]: {"pct": 87}},
       "matchingProgress": {REQ[3]: {"correct": 4, "total": 5, "pct": 80}}}
assert svc.authoritative_activity_score(st2, REQ[0]) == {"correct": 87, "total": 100, "pct": 87}, \
    "legacy recordScore(2, avg, 100)"
assert svc.authoritative_activity_score(st2, REQ[3]) == {"correct": 4, "total": 5, "pct": 80}, \
    "legacy recordScore(5, firstTry, n)"
assert svc.authoritative_activity_score({}, WH) is None
for junk in ({"activityScores": "x"}, {"activityScores": {WH: "x"}}, {"activityScores": {WH: {}}},
             {"activityScores": {WH: {"correct": 1, "total": 0}}}):
    assert svc.authoritative_activity_score(junk, WH) is None, junk
ok("resolver: deterministic/STT/matching all yield exact correct+total; malformed evidence -> None")

# ============================== real Zoo activation ==============================
assert svc.registry.completion_available(ZOO_LESSON)
pol = svc.registry.completion_policy_of(ZOO_LESSON)
assert pol["type"] == "average_required_activities" and pol["version"] == 1 and pol["passMark"] == 80
assert pol["requiredActivityIds"] == REQ, pol["requiredActivityIds"]
assert [l for l in svc.registry.lessons if svc.registry.completion_available(l)] == [ZOO_LESSON]
assert svc.registry.lesson_reward_policy_of(ZOO_LESSON) == "none"
assert svc.registry.lesson_qualification_ids_for(ZOO_LESSON) == []
# the six required activities are exactly the legacy Rule A scored levels of this article
assert len(REQ) == 6 and all(svc.registry.lesson_of_activity(a) == ZOO_LESSON for a in REQ)
ok("Zoo activation: exactly 1 production policy, the 6 legacy scored levels, no reward, no grants")


def zoo_state(scores):
    """Authoritative Zoo evidence from {activityId: (correct, total)}, using the REAL stores."""
    out = {"activityScores": {}, "sttProgress": {}, "matchingProgress": {}}
    for aid, (c, t) in scores.items():
        pct = int(c * 100.0 / t + 0.5)
        if aid.endswith(".read_along"):
            out["sttProgress"][aid] = {"pct": pct, "totalSentences": 10}
        elif aid.endswith(".matching"):
            out["matchingProgress"][aid] = {"correct": c, "total": t, "pct": pct}
        else:
            out["activityScores"][aid] = {"correct": c, "total": t, "pct": pct, "updatedAt": 1}
    return out


allfull = zoo_state({REQ[0]: (100, 100), REQ[1]: (5, 5), REQ[2]: (5, 5), REQ[3]: (5, 5),
                     REQ[4]: (5, 5), REQ[5]: (5, 5)})
r = svc.evaluate_lesson(ZOO_LESSON, allfull)
assert r["available"] and r["completed"] and r["roundedPct"] == 100, r
# case E on the REAL Zoo ids: WH at 60, the rest 100 -> 93 -> complete
caseE_zoo = zoo_state({REQ[0]: (100, 100), REQ[1]: (5, 5), REQ[2]: (5, 5), REQ[3]: (5, 5),
                       REQ[4]: (3, 5), REQ[5]: (5, 5)})
r = svc.evaluate_lesson(ZOO_LESSON, caseE_zoo)
assert r["completed"] is True and r["roundedPct"] == 93, r
# all six present but the mean is below 80 -> not complete
low = zoo_state({REQ[0]: (60, 100), REQ[1]: (4, 5), REQ[2]: (3, 5), REQ[3]: (3, 5),
                 REQ[4]: (4, 5), REQ[5]: (4, 5)})
r = svc.evaluate_lesson(ZOO_LESSON, low)
assert r["completed"] is False and r["roundedPct"] < 80, r
# one missing -> not complete no matter how good the others are
r = svc.evaluate_lesson(ZOO_LESSON, zoo_state({a: (5, 5) for a in REQ[1:]}))
assert r["completed"] is False and r["missingActivityIds"] == [REQ[0]], r
# raising the weak levels through the authoritative stores flips it to complete
fixed = json.loads(json.dumps(low))
for a in (REQ[1], REQ[2], REQ[4], REQ[5]):
    fixed["activityScores"][a] = {"correct": 5, "total": 5, "pct": 100, "updatedAt": 2}
fixed["sttProgress"][REQ[0]] = {"pct": 100, "totalSentences": 10}
assert svc.evaluate_lesson(ZOO_LESSON, fixed)["completed"] is True
ok("real Zoo: all-six completes, case E completes, mean<80 fails, missing fails, improving flips it")

# a client-style localStorage score can never complete the lesson (§26)
fake = {"scores": {"2": {"correct": 100, "total": 100}, "3": {"correct": 5, "total": 5}},
        "statusFromScores": {"passed": True}, "completed": True, "avg": 100}
assert svc.evaluate_lesson(ZOO_LESSON, fake)["completed"] is False
assert svc.evaluate_lesson(ZOO_LESSON, fake)["missingActivityIds"] == REQ
ok("§26 client-shaped score fields in the state cannot complete the lesson")

# ============================== persistence, idempotency, neutrality ==============================
st = json.loads(json.dumps(caseE_zoo))
st, out = svc.record_attempt(st, REQ[1], {"passed": True, "pct": 100, "correct": 5, "total": 5}, 5000)
assert out["lessonCompleted"] is True and out["lessonCompletedNow"] is True
assert C.get_lesson_completion(st, ZOO_LESSON) == {"completedAt": 5000, "policyVersion": 1}
assert out["lessonRewardAmount"] == 0 and out["lessonRewarded"] is False, "no lesson gold"
assert out["lessonQualifications"] == [], "no lesson qualification"
st, out = svc.record_attempt(st, REQ[1], {"passed": True, "pct": 100, "correct": 5, "total": 5}, 9000)
assert out["lessonCompletedNow"] is False
assert C.get_lesson_completion(st, ZOO_LESSON)["completedAt"] == 5000, "never re-dated"
# a lower retry after completion drops the current mean but does NOT revoke history (monotonic)
st, out = svc.record_attempt(st, REQ[1], {"passed": False, "pct": 0, "correct": 0, "total": 5}, 9500)
assert svc.evaluate_lesson(ZOO_LESSON, st)["completed"] is False, "current Rule A state is below 80"
assert C.get_lesson_completion(st, ZOO_LESSON)["completedAt"] == 5000, "history is monotonic"
assert st["activityScores"][REQ[1]]["pct"] == 0, "latest-wins score really did drop"
ok("persistence: recorded once and never re-dated; a later worse score lowers the current mean but "
   "does not revoke the historical completion")

# ============================== progress view ==============================
pv = svc.progress_view(allfull)
z = pv["lessons"][ZOO_LESSON]
assert z["authoritativeCompletionAvailable"] is True and z["requiredActivityIds"] == REQ
assert z["completed"] is False, "no lessonCompletions record in this state"
pv2 = svc.progress_view(st)
assert pv2["lessons"][ZOO_LESSON]["completed"] is True
assert pv2["lessons"][ZOO_LESSON]["completedAt"] == 5000
assert pv2["lessons"][ZOO_LESSON]["policyVersion"] == 1
assert pv2["completedLessonIds"] == [ZOO_LESSON]
blob = json.dumps(pv2)
for leak in ("answer", "graderType", "graderConfig", "rewardPolicy", "roundId", "10000"):
    assert leak not in blob, "progress view leaks " + leak
ok("progress view: Zoo availability / completed / completedAt / policyVersion, no internals")

# ============================== validator ==============================
BASE = copy.deepcopy(R.DATA)
assert R.validate(BASE) == [], R.validate(BASE)


def rejects(mutate, needle):
    d = copy.deepcopy(BASE)
    mutate(d)
    errs = R.validate(d)
    assert any(needle in e for e in errs), (needle, errs)


def P(d):
    return d["lessons"][ZOO_LESSON]["completionPolicy"]


rejects(lambda d: P(d).update(passMark=50), "passMark must be 80")
rejects(lambda d: P(d).update(passMark=0), "passMark must be 80")
rejects(lambda d: P(d).update(type="mean_of_stuff"), "unknown type")
rejects(lambda d: P(d).update(requiredActivityIds=REQ + [REQ[0]]), "duplicate requiredActivityId")
rejects(lambda d: P(d).update(requiredActivityIds=["english.a1.core.001.reorder"]), "belongs to lesson")
rejects(lambda d: P(d).update(requiredActivityIds=["nope.nope"]), "unknown activity")
rejects(lambda d: P(d).update(rewardGold=1), "may not set")
rejects(lambda d: P(d).update(rewardPolicy="jackpot"), "invalid rewardPolicy")
rejects(lambda d: P(d).update(bogusKey=1), "unknown keys")
ok("validator: passMark pinned to 80; unknown type / duplicate / foreign activity / reward rejected")

print("\nAll %d Rule A tests passed." % passed)
