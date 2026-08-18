#!/usr/bin/env python3
"""Phase 3D — authoritative whole-lesson completion machinery (capability only).

    python3 tests/learning_lesson_completion_test.py

Everything here runs against SYNTHETIC registry data. Phase 3D deliberately configures no production
lesson with an active completionPolicy, because Level 2 (STT) and Level 5 (matching) have no
server-authoritative evidence — so the machinery is proven on a test pack instead, and a dedicated
section asserts that production stays at zero.

Covers §30 policy evaluation, §31 authority, §32 first completion, §33 lesson qualification,
§34 lesson reward, §35 the untouched activity reward, §36 legacy progress.
"""
import copy
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))   # Phase 9B.1: shared registry-derived expectations
import curriculum_expectations as CX  # noqa: E402
from learning import (api as L, completion as C, qualifications as Q,   # noqa: E402
                      registry as R, rewards as W)

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ============ a synthetic, non-English content pack with a real completion policy ============
tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, "packs", "bio"), exist_ok=True)
json.dump({"a": [{"q": "A cell has a membrane.", "answer": "Yes"},
                 {"q": "A cell is a mineral.", "answer": "No"}],
           "b": [{"q": "Mitochondria make ATP.", "answer": "Yes"},
                 {"q": "DNA is a protein.", "answer": "No"}],
           "c": [{"q": "Osmosis moves water.", "answer": "Yes"},
                 {"q": "Osmosis moves stone.", "answer": "No"}]},
          open(os.path.join(tmp, "packs", "bio", "cells.json"), "w", encoding="utf-8"))


def act(key, grants=(), reward="none"):
    return {"lessonId": "bio.cells.intro", "contentKey": key, "graderType": "yes_no",
            "title": "Cells " + key, "grants": list(grants), "rewardPolicy": reward}


BASE = {
    "schemaVersion": 1,
    "contentPacks": {"bio": {"title": "Biology"}},
    "courses": {"bio.cells": {"contentPackId": "bio", "title": "Cells"}},
    "units": {},
    "lessons": {"bio.cells.intro": {
        "courseId": "bio.cells", "contentPath": "packs/bio/cells", "title": "Cell basics",
        "completionPolicy": {"type": "all_required_activities", "version": 1,
                             "requiredActivityIds": ["bio.cells.intro.a", "bio.cells.intro.b"],
                             "grants": ["bio.cells.intro.complete"],
                             "rewardPolicy": "none"}}},
    "activities": {"bio.cells.intro.a": act("a"), "bio.cells.intro.b": act("b"),
                   "bio.cells.intro.c": act("c")},          # c is OPTIONAL - not in the policy
    "qualifications": {"bio.cells.intro.complete": {"scope": "lesson", "title": "Cell basics — complete"}},
}
assert R.validate(BASE) == [], R.validate(BASE)

RIGHT = {
    "bio.cells.intro.a": [{"q": "A cell has a membrane.", "answer": "Yes"},
                          {"q": "A cell is a mineral.", "answer": "No"}],
    "bio.cells.intro.b": [{"q": "Mitochondria make ATP.", "answer": "Yes"},
                          {"q": "DNA is a protein.", "answer": "No"}],
    "bio.cells.intro.c": [{"q": "Osmosis moves water.", "answer": "Yes"},
                          {"q": "Osmosis moves stone.", "answer": "No"}],
}
WRONG = {k: [{"q": i["q"], "answer": ("No" if i["answer"] == "Yes" else "Yes")} for i in v]
         for k, v in RIGHT.items()}


def service(data=None, amounts=None):
    return L.LearningService(R.Registry(data or BASE), content_root=tmp,
                             reward_amounts=amounts if amounts is not None else {"PASS_GOLD": 10000})


def do(svc, state, aid, answers, now=1000):
    res, err = svc.grade_attempt(aid, answers)
    assert err is None, (aid, err)
    return svc.record_attempt(state, aid, res, now)


# ============================== §30 pure evaluation ==============================
LESSON = BASE["lessons"]["bio.cells.intro"]
e = C.evaluate("bio.cells.intro", LESSON, set())
assert e["available"] is True and e["completed"] is False
assert e["requiredActivityIds"] == ["bio.cells.intro.a", "bio.cells.intro.b"]
assert e["missingActivityIds"] == e["requiredActivityIds"] and e["completedActivityIds"] == []
assert e["policyType"] == "all_required_activities" and e["policyVersion"] == 1
# partial
e = C.evaluate("bio.cells.intro", LESSON, {"bio.cells.intro.a"})
assert e["completed"] is False and e["missingActivityIds"] == ["bio.cells.intro.b"]
assert e["completedActivityIds"] == ["bio.cells.intro.a"]
# all required
e = C.evaluate("bio.cells.intro", LESSON, {"bio.cells.intro.a", "bio.cells.intro.b"})
assert e["completed"] is True and e["missingActivityIds"] == []
# an extra OPTIONAL activity neither helps nor hurts
assert C.evaluate("bio.cells.intro", LESSON, {"bio.cells.intro.c"})["completed"] is False
assert C.evaluate("bio.cells.intro", LESSON,
                  {"bio.cells.intro.a", "bio.cells.intro.b", "bio.cells.intro.c"})["completed"] is True
# repeated evaluation is stable
for _ in range(3):
    assert C.evaluate("bio.cells.intro", LESSON,
                      {"bio.cells.intro.a", "bio.cells.intro.b"})["completed"] is True
# unknown lesson / no policy / malformed policy -> never completable, never "vacuously complete"
assert C.evaluate("nope", None, {"anything"})["available"] is False
assert C.evaluate("nope", None, {"anything"})["completed"] is False
assert C.evaluate("x", {"title": "no policy"}, {"a"})["available"] is False
for bad in ({"completionPolicy": {"type": "unknown_type", "version": 1, "requiredActivityIds": ["a"]}},
            {"completionPolicy": {"type": "all_required_activities", "version": 1,
                                  "requiredActivityIds": []}},
            {"completionPolicy": {}}, {"completionPolicy": None}, {"completionPolicy": "nope"}):
    r = C.evaluate("x", bad, {"a", "b", "c"})
    assert r["completed"] is False, bad
assert C.policy_version({"version": 0}) == 1 and C.policy_version({"version": True}) == 1
assert C.policy_version({"version": 7}) == 7
ok("§30 evaluation: none/partial/all/extra-optional/repeat, unknown lesson, malformed policy never completes")

# ============================== §32 first completion is idempotent ==============================
svc = service()
st = {}
assert svc.evaluate_lesson("bio.cells.intro", st)["completed"] is False
st, out = do(svc, st, "bio.cells.intro.a", RIGHT["bio.cells.intro.a"], now=1000)
assert out["passed"] and out["lessonCompleted"] is False and out["lessonCompletedNow"] is False
assert C.get_lesson_completion(st, "bio.cells.intro") is None, "one of two required -> not complete"
st, out = do(svc, st, "bio.cells.intro.b", RIGHT["bio.cells.intro.b"], now=2000)
assert out["lessonCompleted"] is True and out["lessonCompletedNow"] is True
rec = C.get_lesson_completion(st, "bio.cells.intro")
assert rec == {"completedAt": 2000, "policyVersion": 1}, rec
# retrying an activity leaves the lesson record untouched
st, out = do(svc, st, "bio.cells.intro.a", RIGHT["bio.cells.intro.a"], now=9000)
assert out["lessonCompleted"] is True and out["lessonCompletedNow"] is False
assert C.get_lesson_completion(st, "bio.cells.intro") == {"completedAt": 2000, "policyVersion": 1}
# a FAILING retry cannot un-complete the lesson or re-date it
st, out = do(svc, st, "bio.cells.intro.a", WRONG["bio.cells.intro.a"], now=9500)
assert out["passed"] is False
assert C.get_lesson_completion(st, "bio.cells.intro") == {"completedAt": 2000, "policyVersion": 1}
assert C.completed_lesson_ids(st) == {"bio.cells.intro"}
ok("§32 first completion: recorded once at the completing attempt, never re-dated by retries or failures")

# ============================== §33 lesson qualification ==============================
assert st["qualifications"]["bio.cells.intro.complete"]["earnedAt"] == 2000
assert set(st["qualifications"]) == {"bio.cells.intro.complete"}, "activities here grant nothing"
# without a grants list, completion grants nothing at all - no inference from the hierarchy
NO_GRANT = copy.deepcopy(BASE)
NO_GRANT["lessons"]["bio.cells.intro"]["completionPolicy"].pop("grants")
NO_GRANT["qualifications"] = {}
assert R.validate(NO_GRANT) == [], R.validate(NO_GRANT)
svc2, st2 = service(NO_GRANT), {}
st2, _ = do(svc2, st2, "bio.cells.intro.a", RIGHT["bio.cells.intro.a"])
st2, out2 = do(svc2, st2, "bio.cells.intro.b", RIGHT["bio.cells.intro.b"])
assert out2["lessonCompletedNow"] is True and out2["lessonQualifications"] == []
assert (st2.get("qualifications") or {}) == {}, "no qualification invented for a completed lesson"
ok("§33 lesson qualification: granted once when configured, never inferred when not")

# ============================== §34 lesson reward ==============================
assert out["lessonRewardAmount"] == 0 and out["lessonRewarded"] is False, "policy 'none' pays nothing"
PAID = copy.deepcopy(BASE)
# Phase 5E: a lesson must name a LESSON-scope policy. The activity-scope pass policy is rejected by
# validation rather than silently paying an activity reward for finishing a lesson.
WRONG_SCOPE = copy.deepcopy(BASE)
WRONG_SCOPE["lessons"]["bio.cells.intro"]["completionPolicy"]["rewardPolicy"] = "standard_activity_pass"
assert any("only valid at scope(s) ['activity']" in e for e in R.validate(WRONG_SCOPE)),     R.validate(WRONG_SCOPE)
PAID["lessons"]["bio.cells.intro"]["completionPolicy"]["rewardPolicy"] = "lesson_mastery_gold"
assert R.validate(PAID) == [], R.validate(PAID)
# the amount comes from the policy's OWN config key, not from PASS_GOLD
PAID_AMOUNTS = {"PASS_GOLD": 10000, "LESSON_MASTERY_GOLD": 777}
svc3, st3 = service(PAID, amounts=PAID_AMOUNTS), {}
st3, _ = do(svc3, st3, "bio.cells.intro.a", RIGHT["bio.cells.intro.a"])
st3, o3 = do(svc3, st3, "bio.cells.intro.b", RIGHT["bio.cells.intro.b"])
assert o3["lessonCompletedNow"] is True and o3["lessonRewarded"] is True and o3["lessonRewardAmount"] == 777
# repeats pay nothing more
for _ in range(3):
    st3, o = do(svc3, st3, "bio.cells.intro.a", RIGHT["bio.cells.intro.a"], now=12345)
    assert o["lessonRewarded"] is False and o["lessonRewardAmount"] == 0, o
# a forged/unknown lesson reward policy pays nothing, and the amount never comes from content
BOGUS = copy.deepcopy(BASE)
BOGUS["lessons"]["bio.cells.intro"]["completionPolicy"]["rewardPolicy"] = "jackpot"
assert any("invalid rewardPolicy" in e for e in R.validate(BOGUS)), R.validate(BOGUS)
svc4, st4 = service(BOGUS), {}                                   # even if it slipped past validation
st4, _ = do(svc4, st4, "bio.cells.intro.a", RIGHT["bio.cells.intro.a"])
st4, o4 = do(svc4, st4, "bio.cells.intro.b", RIGHT["bio.cells.intro.b"])
assert o4["lessonCompletedNow"] is True and o4["lessonRewardAmount"] == 0, o4
# and with no injected game-config amount, even a valid policy pays 0
svc5, st5 = service(PAID, amounts={"PASS_GOLD": 10000}), {}
st5, _ = do(svc5, st5, "bio.cells.intro.a", RIGHT["bio.cells.intro.a"])
st5, o5 = do(svc5, st5, "bio.cells.intro.b", RIGHT["bio.cells.intro.b"])
assert o5["lessonRewardAmount"] == 0, o5
ok("§34 lesson reward: policy-driven, first completion only, forged/unknown/uninjected policy pays 0")

# ============================== §31 authority ==============================
# the evaluator's ONLY input is server-verified activity state; client-shaped junk in the learning
# state cannot manufacture a completion
FORGED = {"completed": True, "score": 100, "average": 100, "passed": True,
          "requiredActivities": [], "policyVersion": 999, "green": True,
          "lessonCompletions": {}, "activityCompletions": {}}
svcf = service()
assert svcf.evaluate_lesson("bio.cells.intro", FORGED)["completed"] is False
# a client-planted activityCompletion with no passedAt is not a pass
FORGED2 = {"activityCompletions": {"bio.cells.intro.a": {"pct": 100, "rewarded": True},
                                   "bio.cells.intro.b": {"pct": 100}}}
assert svcf.evaluate_lesson("bio.cells.intro", FORGED2)["completed"] is False
# A planted record of a DIFFERENT policy version does not block a completion of the ACTIVE version —
# that is the whole point of the Phase 4D versioned history: "completed under v999" and "completed
# under v1" are different facts. The planted record survives untouched and keeps first-ever status,
# while the active version is recorded (and paid) exactly once.
PLANTED = {"lessonCompletions": {"bio.cells.intro": {"completedAt": 1, "policyVersion": 999}}}
stp, outp = do(service(PAID), dict(PLANTED), "bio.cells.intro.a", RIGHT["bio.cells.intro.a"])
stp, outp = do(service(PAID), stp, "bio.cells.intro.b", RIGHT["bio.cells.intro.b"])
assert outp["lessonCompletedNow"] is True, outp          # v1 (the ACTIVE version) is newly recorded
assert outp["activePolicyVersion"] == 1 and outp["activePolicyCompleted"] is True, outp
assert outp["firstCompletedPolicyVersion"] == 999, "the planted record keeps first-ever status"
assert stp["lessonCompletions"]["bio.cells.intro"]["completedAt"] == 1, "existing record wins"
assert stp["lessonCompletions"]["bio.cells.intro"]["policyVersion"] == 999, "never re-versioned"
assert [e["policyVersion"] for e in C.merged_history(stp, "bio.cells.intro")] == [1, 999]
# …and a repeat settlement of that same active version neither re-dates nor re-pays
stp2, outp2 = do(service(PAID), stp, "bio.cells.intro.b", RIGHT["bio.cells.intro.b"])
assert outp2["lessonCompletedNow"] is False and outp2["lessonRewarded"] is False, outp2
# there is no client route to assert completion: the service exposes no such mutator
assert not hasattr(L.LearningService, "complete_lesson")
assert not hasattr(L.LearningService, "set_lesson_completed")
ok("§31 authority: forged state/planted records cannot create or re-pay a completion; no mutator exists")

# ============================== §36 legacy progress is untouched ==============================
LEGACY = {"activityCompletions": {"packs/bio/cells#a": {"passedAt": 7, "pct": 100, "rewarded": True}},
          "qualifications": {"legacy.q": {"earnedAt": 5}}}
LEG = copy.deepcopy(BASE)
LEG["activities"]["bio.cells.intro.a"]["legacyKeys"] = ["packs/bio/cells#a"]
svcl = service(LEG)
before = json.dumps(LEGACY, sort_keys=True)
stl, _ = do(svcl, copy.deepcopy(LEGACY), "bio.cells.intro.b", RIGHT["bio.cells.intro.b"], now=3000)
assert stl["activityCompletions"]["packs/bio/cells#a"] == {"passedAt": 7, "pct": 100, "rewarded": True}
assert stl["qualifications"]["legacy.q"] == {"earnedAt": 5}
# the legacy record counts as an authoritative pass, so the lesson completes off it
assert C.get_lesson_completion(stl, "bio.cells.intro") == {"completedAt": 3000, "policyVersion": 1}
assert json.loads(before) == LEGACY, "the input state object was not mutated in place"
ok("§36 legacy progress: Phase 3A/B/C records read as evidence, preserved byte-for-byte, additive only")

# ============================== validator (§42) ==============================
def rejects(mutate, needle):
    d = copy.deepcopy(BASE)
    mutate(d)
    errs = R.validate(d)
    assert any(needle in e for e in errs), (needle, errs)


P = lambda d: d["lessons"]["bio.cells.intro"]["completionPolicy"]  # noqa: E731
rejects(lambda d: P(d).update(type="mean_of_everything"), "unknown type")
rejects(lambda d: P(d).update(type=None), "unknown type")
rejects(lambda d: P(d).update(version=0), "version must be a positive integer")
rejects(lambda d: P(d).update(version="1"), "version must be a positive integer")
rejects(lambda d: P(d).update(version=True), "version must be a positive integer")
rejects(lambda d: P(d).update(requiredActivityIds=[]), "at least one requiredActivityId")
rejects(lambda d: P(d).update(requiredActivityIds=["bio.cells.intro.a", "bio.cells.intro.a"]),
        "duplicate requiredActivityId")
rejects(lambda d: P(d).update(requiredActivityIds=["nope.nope"]), "requires unknown activity")
rejects(lambda d: P(d).update(requiredActivityIds=["Bad ID"]), "malformed")
rejects(lambda d: P(d).update(bogus=1), "unknown keys")
rejects(lambda d: P(d).update(rewardGold=999999), "may not set")
rejects(lambda d: P(d).update(rewardPolicy="jackpot"), "invalid rewardPolicy")
rejects(lambda d: P(d).update(grants=["nope"]), "grants unknown qualification")
rejects(lambda d: P(d).update(grants="x"), "grants must be a list")
rejects(lambda d: d["lessons"]["bio.cells.intro"].update(completionPolicy="nope"), "must be an object")
# a lesson may not require an activity that belongs to a DIFFERENT lesson
CROSS = copy.deepcopy(BASE)
CROSS["lessons"]["bio.cells.two"] = {"courseId": "bio.cells", "contentPath": "packs/bio/cells",
                                     "title": "Two"}
CROSS["activities"]["bio.cells.two.a"] = dict(act("a"), lessonId="bio.cells.two")
CROSS["lessons"]["bio.cells.intro"]["completionPolicy"]["requiredActivityIds"] = ["bio.cells.two.a"]
assert any("belongs to lesson" in e for e in R.validate(CROSS)), R.validate(CROSS)
# scope discipline: an ACTIVITY may not grant a lesson-scope qualification, and vice versa
SCOPE = copy.deepcopy(BASE)
SCOPE["activities"]["bio.cells.intro.a"]["grants"] = ["bio.cells.intro.complete"]
assert any("only 'activity' scope is earnable" in e for e in R.validate(SCOPE)), R.validate(SCOPE)
SCOPE2 = copy.deepcopy(BASE)
SCOPE2["qualifications"]["bio.cells.intro.complete"]["scope"] = "activity"
assert any("expected 'lesson'" in e for e in R.validate(SCOPE2)), R.validate(SCOPE2)
# an orphan lesson-scope qualification is rejected
ORPH = copy.deepcopy(BASE)
ORPH["qualifications"]["bio.orphan"] = {"scope": "lesson", "title": "orphan"}
assert any("no lesson completionPolicy grants it" in e for e in R.validate(ORPH)), R.validate(ORPH)
# unit/course scope remains un-earnable
for sc in ("unit", "course"):
    U = copy.deepcopy(BASE)
    U["qualifications"]["bio.x"] = {"scope": sc, "title": "x"}
    assert any("not authoritative yet" in e for e in R.validate(U)), (sc, R.validate(U))
ok("§42 validator: type/version/required/grants/reward/scope/cross-lesson/orphan all enforced")

# ============================== progress view ==============================
pv = service().progress_view(st)
L1 = pv["lessons"]["bio.cells.intro"]
assert L1["authoritativeCompletionAvailable"] is True and L1["completed"] is True
assert L1["completedAt"] == 2000 and L1["policyVersion"] == 1
assert L1["missingActivityIds"] == [] and sorted(L1["completedActivityIds"]) == \
    ["bio.cells.intro.a", "bio.cells.intro.b"]
assert pv["completedLessonIds"] == ["bio.cells.intro"]
blob = json.dumps(pv)
for leak in ("answer", "graderType", "graderConfig", "rewardPolicy", "PASS_GOLD", "10000", "contentPath"):
    assert leak not in blob, "progress view leaks " + leak
empty = service().progress_view({})
assert empty["completedLessonIds"] == [] and empty["lessons"]["bio.cells.intro"]["completed"] is False
ok("progress view: status + missing activities only; no answer keys, grader config or reward detail")

shutil.rmtree(tmp, ignore_errors=True)


# ============ PRODUCTION: four active v2 policies, and PASS RECORDS ALONE complete nothing ============
prod = L.LearningService(content_root=ROOT, reward_amounts={"PASS_GOLD": 10000})
# Phase 3F activated a 6-activity Zoo v1; Phase 4B retired it (legacy Rule A also scores level 10);
# Phase 4C made level 10 authoritative; Phase 4D activated a 7-activity v2 on all four Taipei lessons.
TAIPEI4 = ["english.prea1.taipei.zoo", "english.prea1.taipei.mrt",
           "english.prea1.taipei.market", "english.prea1.taipei.park"]
active = sorted(lid for lid in prod.registry.lessons if prod.registry.completion_available(lid))
CX.assert_completion_model(prod.registry)
assert set(TAIPEI4) <= set(active), active
assert prod.registry.retired_policy_versions("english.prea1.taipei.zoo") == [1]
assert R.validate(R.DATA) == [], R.validate(R.DATA)
for lid in prod.registry.lessons:
    ev = prod.evaluate_lesson(lid, {})
    assert ev["completed"] is False, lid
    assert ev["available"] is bool(prod.registry.completion_policy_of(lid)), lid   # derived
    # even a player who passed literally every registered activity completes no lesson: Rule A
    # averages SCORES, and a pass record carries no numerator/denominator
    everything = {"activityCompletions": {aid: {"passedAt": 1, "pct": 100, "rewarded": False}
                                          for aid in prod.registry.activities}}
    ev2 = prod.evaluate_lesson(lid, everything)
    assert ev2["completed"] is False, "%s needs real score evidence, not just pass records" % lid
    if lid in TAIPEI4:
        assert len(ev2["missingActivityIds"]) == 7, (lid, ev2["missingActivityIds"])
# no lesson-scope qualification exists in production, so none can be earned
assert all((q or {}).get("scope") == "activity" for q in prod.registry.qualifications.values())
# Phase 5F: the four Taipei lessons carry a cosmetic badge. None of them may be economic.
assert all(prod.registry.lesson_reward_policy_of(l) == "lesson_mastery_badge" for l in TAIPEI4)
assert not any(W.is_economic(prod.registry.lesson_reward_policy_of(l)) for l in TAIPEI4)
assert all(prod.registry.lesson_qualification_ids_for(l) == [] for l in TAIPEI4)
pv = prod.progress_view({"activityCompletions": {aid: {"passedAt": 1, "pct": 100}
                                                 for aid in prod.registry.activities}})
assert pv["completedLessonIds"] == []
assert all(l["completed"] is False for l in pv["lessons"].values())
assert all(l["currentPolicySatisfied"] is False for l in pv["lessons"].values())
ok("production: exactly the 4 Taipei lessons carry an active v2 policy, all reward-free and "
   "grant-free; pass records alone complete nothing because Rule A averages scores")

# the Zoo activity reward is untouched by any of this (§35)
zoo = "english.prea1.taipei.zoo.quiz3"
assert prod.reward_for(zoo) == {"type": "gold", "amount": 10000, "itemId": None, "once": True}
# Zoo's lesson now carries the cosmetic badge, which pays nothing — the activity payout below is
# unaffected by it, which is the point of this section.
assert prod.registry.lesson_reward_policy_of("english.prea1.taipei.zoo") == "lesson_mastery_badge"
assert W.resolve("lesson_mastery_badge", {"PASS_GOLD": 10000})["amount"] == 0
assert W.resolve("none", {"PASS_GOLD": 10000})["amount"] == 0
zoo_key = json.load(open(os.path.join(ROOT, "Pre-A1", "taipei", "zoo.json"), encoding="utf-8"))["quiz3"]
res, err = prod.grade_attempt(zoo, [{"q": i["q"], "answer": i["answer"]} for i in zoo_key])
stz, o = prod.record_attempt({}, zoo, res, 100)
assert o["rewarded"] is True and o["rewardAmount"] == 10000, o
assert o["lessonRewardAmount"] == 0 and o["lessonCompleted"] is False and o["lessonCompletedNow"] is False
stz, o2 = prod.record_attempt(stz, zoo, res, 200)
assert o2["rewarded"] is False and o2["rewardAmount"] == 0 and o2["lessonRewardAmount"] == 0
assert "lessonCompletions" not in stz, "no empty lessonCompletions block is created"
ok("§35 Zoo activity reward unchanged: +PASS_GOLD once, +0 on repeat, and no lesson reward appears")

print("\nAll %d lesson-completion tests passed." % passed)
