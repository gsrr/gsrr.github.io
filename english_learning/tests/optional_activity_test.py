#!/usr/bin/env python3
"""Phase 9E.2 — CATALOGUED is not REQUIRED. A1's four practice activities are authoritative but optional.

    python3 tests/optional_activity_test.py

Phase 9E.1 found every A1 lesson offering four activities — quiz4, wh, cloze, roleplay — that the
registry did not declare. They had real content and real learners could work through them, but
`maybeSubmitLearningAttempt()` dropped every submission (no activityId -> return), so they counted for
nothing and the lesson still read "0 / 5".

9E.2 catalogued them rather than deleting them. That makes the distinction load-bearing for the first
time in this product:

    CATALOGUED  — the registry declares the activity exists (9 for A1)
    REQUIRED    — completionPolicy.requiredActivityIds decides mastery (still 5 for A1)

This suite pins that split, and pins that catalogueing did NOT make mastery harder, richer or
qualification-bearing. Populations are derived, so migrating A2/B1 needs no edit here.
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import curriculum_expectations as CX  # noqa: E402
from game import config as GC  # noqa: E402
from learning import api as L, qualifications as Q, registry as R, reward_ledger as LG  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


AMOUNTS = {"PASS_GOLD": GC.PASS_GOLD, "LESSON_MASTERY_GOLD": GC.MASTERY_GOLD}
svc = L.LearningService(content_root=ROOT, reward_amounts=AMOUNTS)
reg = R.REGISTRY
A1 = sorted(l for l in reg.lessons if reg.lesson(l).get("courseId") == "english.a1.core")
A1_REQUIRED = ["read_along", "quiz3", "matching", "reorder", "dictation"]
A1_OPTIONAL = ["quiz4", "wh", "cloze", "roleplay"]


def types_of(lid):
    return sorted(a.rsplit(".", 1)[-1] for a in reg.activities
                  if reg.activities[a]["lessonId"] == lid)


def required_of(lid):
    return [a.rsplit(".", 1)[-1] for a in reg.completion_policy_of(lid)["requiredActivityIds"]]


# ============================== 1. catalogued != required, for all 12 ==============================
assert len(A1) == 12, A1
for lid in A1:
    cat, req = types_of(lid), required_of(lid)
    assert cat == sorted(A1_REQUIRED + A1_OPTIONAL), (lid, cat)
    assert req == A1_REQUIRED, (lid, req)
    assert sorted(set(cat) - set(req)) == sorted(A1_OPTIONAL), (lid, sorted(set(cat) - set(req)))
ok("1. every A1 lesson declares 9 activities but requires 5; the optional four are exactly "
   "quiz4/wh/cloze/roleplay")

# ============================== 2. the optional four are economically inert ==============================
for lid in A1:
    for suf in A1_OPTIONAL:
        aid = lid + "." + suf
        assert reg.reward_policy_of(aid) == "none", aid
        assert svc.reward_for(aid)["amount"] == 0, aid
        assert reg.qualification_ids_for(aid) == [], aid
    gates = [a for a in reg.activities
             if reg.activities[a]["lessonId"] == lid and svc.reward_for(a)["amount"] > 0]
    assert gates == [lid + ".quiz3"], (lid, gates)
ok("2. all 48 optional A1 activities pay 0 and grant nothing; each lesson still has exactly ONE "
   "paying gate (quiz3 at PASS_GOLD)")

# ============================== 3. an optional activity IS authoritatively gradable ==============================
LID = "english.a1.core.002"
src = json.load(open(os.path.join(ROOT, "A1", "002.json"), encoding="utf-8"))
ANS = {
    "quiz4": [{"q": i["q"], "answer": i["answer"]} for i in src["quiz4"]],
    "wh": [{"q": i["q"], "answer": i["a"]} for i in src["wh"]],
    "cloze": [{"q": i["text"], "answer": i["answer"]} for i in src["cloze"]],
}
state = {}
for suf, ans in ANS.items():
    aid = LID + "." + suf
    res, err = svc.grade_attempt(aid, ans)
    assert not err and res["passed"] is True and res["pct"] == 100, (aid, err, res)
    state, out = svc.record_attempt(state, aid, res, 100)
    assert out["rewardAmount"] == 0, (aid, out)
    assert out["granted"] == [], (aid, out)
    assert svc.read_completion(state, aid), ("an optional pass must still be recorded", aid)
graph, version = svc.roleplay_graph(LID + ".roleplay")
assert graph and isinstance(version, str) and len(version) == 16, (LID, version)
assert LG.total_granted(state, "gold") == 0, LG.total_granted(state, "gold")
assert (state.get("qualifications") or {}) == {}
ok("3. optional activities grade authoritatively (100%, evidence persisted) while minting 0 gold and "
   "0 qualifications; the optional role-play graph loads and validates")

# ============================== 4. optional passes do NOT advance mastery ==============================
ev = svc.evaluate_lesson(LID, state)
assert ev["available"] is True and ev["completed"] is False, ev
assert len(ev["requiredActivityIds"]) == 5, ev["requiredActivityIds"]
assert ev["completedActivityIds"] == [], ev["completedActivityIds"]
assert len(ev["missingActivityIds"]) == 5, ev["missingActivityIds"]
pv = svc.progress_view(state)["lessons"][LID]
assert len(pv["requiredActivityIds"]) == 5 and pv["completedActivityIds"] == [], pv
out = {}
svc._settle_lesson(copy.deepcopy(state), LID, 2000, out)
assert out.get("lessonCompletedNow") is not True, out
assert out.get("lessonRewardAmount", 0) == 0, out
ok("4. passing THREE optional activities leaves mastery at 0 / 5 and pays nothing — the denominator "
   "is the policy, never the catalog")

# ============================== 5. the five required still pay exactly 800, once ==============================
st = {}
gate = LID + ".quiz3"
res, err = svc.grade_attempt(gate, [{"q": i["q"], "answer": i["answer"]} for i in src["quiz3"]])
st, g = svc.record_attempt(st, gate, res, 100)
for suf in A1_REQUIRED:
    aid = LID + "." + suf
    if svc.is_matching(aid):
        st.setdefault("matchingProgress", {})[aid] = {"correct": 10, "total": 10, "pct": 100}
    elif svc.is_read_along(aid):
        st.setdefault("sttProgress", {})[aid] = {"pct": 100}
    else:
        Q.record_activity_score(st, aid, 10, 10, 100, 100)
        Q.record_completion(st, svc.completion_key(aid), passed_at=100, pct=100, rewarded=True)
m = {}
svc._settle_lesson(st, LID, 2000, m)
assert g["rewardAmount"] == GC.PASS_GOLD, g
assert m["lessonRewardAmount"] == GC.MASTERY_GOLD, m
assert m["lessonCompletedNow"] is True, m
assert LG.total_granted(st, "gold") == 800, LG.total_granted(st, "gold")
assert (st.get("qualifications") or {}) == {}, "an A1 lesson grants no qualification"
base = copy.deepcopy(st)
_, again = svc.record_attempt(copy.deepcopy(base), gate, res, 3000)
r2 = {}
svc._settle_lesson(copy.deepcopy(base), LID, 3000, r2)
assert again["rewardAmount"] == 0 and r2.get("lessonRewardAmount", 0) == 0
assert LG.total_granted(base, "gold") == 800
ok("5. the five REQUIRED activities still complete the lesson for exactly 800 (160+640), replay pays "
   "0, and no qualification is granted")

# ============================== 6. mastery is reachable WITHOUT the optional four ==============================
# The important safety property: catalogueing optional activities must not make mastery unreachable
# or dependent on them.
assert not set(A1_OPTIONAL) & set(required_of(LID)), required_of(LID)
lean = {}
gr, _ = svc.grade_attempt(gate, [{"q": i["q"], "answer": i["answer"]} for i in src["quiz3"]])
lean, _ = svc.record_attempt(lean, gate, gr, 100)
for suf in A1_REQUIRED:
    aid = LID + "." + suf
    if svc.is_matching(aid):
        lean.setdefault("matchingProgress", {})[aid] = {"correct": 10, "total": 10, "pct": 100}
    elif svc.is_read_along(aid):
        lean.setdefault("sttProgress", {})[aid] = {"pct": 100}
    else:
        Q.record_activity_score(lean, aid, 10, 10, 100, 100)
        Q.record_completion(lean, svc.completion_key(aid), passed_at=100, pct=100, rewarded=True)
assert svc.evaluate_lesson(LID, lean)["completed"] is True, "mastery must not need the optional four"
ok("6. a learner who never touches quiz4/wh/cloze/roleplay still masters the lesson — catalogueing "
   "did not make mastery harder")

# ============================== 7. other families untouched ==============================
for lid in CX.TAIPEI4:
    assert types_of(lid) == required_of(lid + "") or sorted(required_of(lid)) == types_of(lid), lid
    assert len(types_of(lid)) == 7 and len(required_of(lid)) == 7, (lid, types_of(lid))
PRE = sorted(l for l in reg.lessons if reg.lesson(l).get("courseId") == "english.prea1.core")
assert len(PRE) == 24, len(PRE)
for lid in PRE:
    assert len(types_of(lid)) == 7 and len(required_of(lid)) == 7, (lid, types_of(lid))
    assert "reorder" not in types_of(lid) and "dictation" not in types_of(lid), lid
ok("7. Taipei (4) and Pre-A1 (24) keep catalogued == required == 7, and Pre-A1 still declares no "
   "reorder/dictation")

# ============================== 8. global invariants ==============================
CX.assert_completion_model(reg)
gates, completable = CX.assert_reward_model(reg, svc, GC.PASS_GOLD)
assert len(reg.lessons) == 40, len(reg.lessons)
assert len(completable) == 40 and len(gates) == 40, (len(completable), len(gates))
assert sorted(reg.qualifications) == CX.CONQUEST_QUALIFICATIONS, sorted(reg.qualifications)
assert len(CX.qualification_bearing(reg)) == 4
assert len(reg.activities) == 304, len(reg.activities)
ok("8. 40 lessons / 40 gates / 40 policies / 4 qualifications hold at 304 catalogued activities")

print("\nAll %d optional-activity tests passed." % passed)
