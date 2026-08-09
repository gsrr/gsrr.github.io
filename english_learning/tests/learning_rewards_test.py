#!/usr/bin/env python3
"""Phase 5E — the generic reward framework: types, scopes, ledger, campaign scope, inertness.

    python3 tests/learning_rewards_test.py

The framework must be able to express gold, cosmetic, profile and gameplay rewards at activity,
lesson and campaign scope — while production stays exactly as it was: one gold-bearing activity,
no lesson reward, no campaign reward, no economy change.
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from learning import (api as L, completion as C, registry as R,  # noqa: E402
                      reward_ledger as LG, rewards as W)

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


svc = L.LearningService(content_root=ROOT, reward_amounts={"PASS_GOLD": 10000})
reg = R.REGISTRY
TAIPEI = "english.prea1.taipei"
ZOO = "english.prea1.taipei.zoo"

# ============================== production is UNCHANGED ==============================
# Phase 7C.2a: every Taipei gate activity pays, through the ONE shared policy.
GATES = sorted("english.prea1.taipei.%s.quiz3" % s
               for s in ("zoo", "mrt", "market", "park"))
gold_bearing = sorted(a for a in reg.activities if svc.reward_for(a)["amount"] > 0)
assert gold_bearing == GATES, gold_bearing
assert {reg.reward_policy_of(a) for a in GATES} == {"standard_activity_pass"}, \
    "the gates must share one policy - no per-lesson reward ids"
assert svc.reward_for(ZOO + ".quiz3") == {"type": "gold", "amount": 10000, "itemId": None,
                                          "once": True}
# Phase 5F activated the first production rewards. They are COSMETIC: the four Taipei lessons grant
# a badge, the Taipei campaign grants a trophy, and nothing else grants anything.
badged = sorted(l for l in reg.lessons if reg.lesson_reward_policy_of(l) == "lesson_mastery_badge")
assert badged == sorted("english.prea1.taipei." + s for s in ("zoo", "mrt", "market", "park")), badged
assert [c for c in reg.courses if reg.course_reward_policy_of(c) == "campaign_trophy"] == \
    ["english.prea1.taipei"]
# Phase 7C.2: a lesson carries a LIST of policies, so checking only reward_policy_of() (the
# first) would silently ignore the economic one. Check every declared policy.
for lid in reg.lessons:
    pids = reg.lesson_reward_policies_of(lid)
    assert set(pids) <= {"none", "lesson_mastery_badge", "lesson_mastery_gold"}, (lid, pids)
    econ = [p for p in pids if W.is_economic(p)]
    assert len(econ) <= 1, (lid, econ)                # never two gold policies on one lesson
for cid in reg.courses:
    pid = reg.course_reward_policy_of(cid)
    assert pid in ("none", "campaign_trophy"), (cid, pid)
    assert not W.is_economic(pid), (cid, pid)         # nor may a campaign
# no gameplay or profile reward is active anywhere
for pid in ({reg.lesson_reward_policy_of(l) for l in reg.lessons}
            | {reg.course_reward_policy_of(c) for c in reg.courses}
            | {reg.reward_policy_of(a) for a in reg.activities}):
    assert W.type_of(pid) in ("none", "gold", "cosmetic"), pid
used = ({reg.reward_policy_of(a) for a in reg.activities}
        | {reg.lesson_reward_policy_of(l) for l in reg.lessons}
        | {reg.course_reward_policy_of(c) for c in reg.courses})
assert used <= set(W.ACTIVE_POLICY_IDS), "production references a framework-only policy: %s" % (
    used - set(W.ACTIVE_POLICY_IDS))
assert R.validate(R.DATA) == [], R.validate(R.DATA)
ok("production economy: 4 gold-bearing gate activities sharing one policy, 4 lessons carrying "
   "a cosmetic badge + at most one economic mastery reward, 1 COSMETIC campaign reward, no "
   "gameplay/profile reward, nothing framework-only referenced")

# ============================== the policy table ==============================
assert set(W.TYPES) == {"none", "gold", "cosmetic", "profile", "gameplay"}, sorted(W.TYPES)
assert W.SCOPES == ("activity", "lesson", "course")
byt = {}
for pid in W.policy_ids():
    byt.setdefault(W.type_of(pid), []).append(pid)
for want in ("gold", "cosmetic", "profile", "gameplay"):
    assert byt.get(want), "no reference policy for reward type %s" % want
assert W.is_economic("standard_activity_pass") is True
for pid in W.policy_ids():
    if W.type_of(pid) != "gold":
        assert W.is_economic(pid) is False, pid       # only gold ever moves the economy
# the module still contains no amounts
src = open(os.path.join(ROOT, "learning", "rewards.py"), encoding="utf-8").read()
import re  # noqa: E402
for tok in re.findall(r"\b\d{3,}\b", src):
    raise AssertionError("rewards.py must contain no amounts, found %s" % tok)
ok("policy table covers all four reward types across three scopes, only gold is economic, and "
   "rewards.py still contains no amounts")

# ============================== scope safety ==============================
assert W.allows_scope("standard_activity_pass", "activity") is True
assert W.allows_scope("standard_activity_pass", "lesson") is False
assert W.allows_scope("campaign_trophy", "course") is True
assert W.allows_scope("campaign_trophy", "activity") is False
assert W.allows_scope("no_such_policy", "activity") is False, "unknown policy must fail closed"
assert W.default_for_scope("activity") == "standard_activity_pass"
assert W.default_for_scope("lesson") == "none" and W.default_for_scope("course") == "none"


def rejects(mutate, needle):
    d = copy.deepcopy(R.DATA)
    mutate(d)
    errs = R.validate(d)
    assert any(needle in e for e in errs), (needle, errs[:3])


rejects(lambda d: d["courses"][TAIPEI].update(rewardPolicy="standard_activity_pass"),
        "only valid at scope(s) ['activity']")
rejects(lambda d: d["activities"][ZOO + ".quiz4"].update(rewardPolicy="campaign_trophy"),
        "only valid at scope(s) ['course']")
rejects(lambda d: d["lessons"][ZOO]["completionPolicy"].update(rewardPolicy="campaign_trophy"),
        "only valid at scope(s) ['course']")
rejects(lambda d: d["courses"][TAIPEI].update(rewardPolicy="nope"), "invalid rewardPolicy")
rejects(lambda d: d["courses"][TAIPEI].update(rewardGold=999), "may not set")
rejects(lambda d: d["activities"][ZOO + ".quiz4"].update(itemId="x"), "may not set 'itemId'")
# a lesson-scope policy IS accepted on a lesson, and a course-scope one on a course
good = copy.deepcopy(R.DATA)
good["lessons"][ZOO]["completionPolicy"]["rewardPolicy"] = "lesson_mastery_badge"
good["courses"][TAIPEI]["rewardPolicy"] = "campaign_trophy"
assert R.validate(good) == [], R.validate(good)
ok("scope safety: a policy can only be attached where its scopes allow; content may name a policy "
   "but never an amount or an item; unknown policies fail closed")

# ============================== the ledger ==============================
st = {}
st, newly = LG.record_grant(st, "lesson", ZOO, "lesson_mastery_badge",
                            W.resolve("lesson_mastery_badge", {}), 1000)
assert newly is True
assert LG.has_grant(st, "lesson", ZOO, "lesson_mastery_badge")
assert st[LG.LEDGER_KEY]["lesson:%s:lesson_mastery_badge" % ZOO] == {
    "policyId": "lesson_mastery_badge", "rewardType": "cosmetic", "scope": "lesson",
    "sourceId": ZOO, "amount": 0, "itemId": "badge.lesson.mastered", "grantedAt": 1000}
before = copy.deepcopy(st)
st, newly = LG.record_grant(st, "lesson", ZOO, "lesson_mastery_badge",
                            W.resolve("lesson_mastery_badge", {}), 9999)
assert newly is False and st == before, "a once reward is never re-granted or re-dated"
# an inert policy records nothing at all
st2, newly2 = LG.record_grant({}, "lesson", ZOO, "none", W.resolve("none", {}), 1)
assert newly2 is False and st2 == {}
st2, newly2 = LG.record_grant({}, "lesson", ZOO, "lesson_mastery_gold",
                              W.resolve("lesson_mastery_gold", {}), 1)
assert newly2 is False, "an unsized gold policy grants nothing rather than free money"
# different scopes/sources are independent
st, _ = LG.record_grant(st, "course", TAIPEI, "campaign_trophy", W.resolve("campaign_trophy", {}), 2000)
st, _ = LG.record_grant(st, "activity", ZOO + ".quiz3", "standard_activity_pass",
                        W.resolve("standard_activity_pass", {"PASS_GOLD": 10000}), 3000)
assert len(LG.entries(st)) == 3
assert LG.owned_items(st) == ["badge.lesson.mastered", "trophy.campaign.complete"]
assert LG.total_granted(st, "gold") == 10000
assert [e["grantKey"] for e in LG.entries(st)] == [
    "lesson:%s:lesson_mastery_badge" % ZOO, "course:%s:campaign_trophy" % TAIPEI,
    "activity:%s.quiz3:standard_activity_pass" % ZOO], "ordered by grantedAt"
# corrupt ledgers read as empty, never raise and never fabricate ownership
for junk in ("x", 5, None, [], {"k": "x"}, {"k": 5}, {"k": {}}, {"k": {"policyId": 7}}):
    assert LG.entries({LG.LEDGER_KEY: junk}) == [], junk
    assert LG.owned_items({LG.LEDGER_KEY: junk}) == [], junk
    assert LG.get_grant({LG.LEDGER_KEY: junk}, "lesson", ZOO, "p") is None, junk
ok("ledger: append-only and idempotent per (scope, sourceId, policy); inert policies write nothing; "
   "scopes are independent; a corrupt ledger reads empty instead of raising or fabricating items")

# ============================== campaign (course) scope ==============================
ev = svc.evaluate_course(TAIPEI, {})
assert ev["available"] is True and ev["completed"] is False
assert ev["lessonIds"] == sorted("english.prea1.taipei.%s" % s
                                 for s in ("market", "mrt", "park", "zoo"))
assert ev["missingLessonIds"] == ev["lessonIds"]
done = {"lessonCompletionHistory": {l: [{"policyVersion": 2, "completedAt": 5}]
                                    for l in ev["lessonIds"]}}
ev2 = svc.evaluate_course(TAIPEI, done)
assert ev2["completed"] is True and ev2["missingLessonIds"] == []
# one lesson short -> not complete
short = {"lessonCompletionHistory": {l: [{"policyVersion": 2, "completedAt": 5}]
                                     for l in ev["lessonIds"][:-1]}}
assert svc.evaluate_course(TAIPEI, short)["completed"] is False
# a completion recorded under a DIFFERENT version does not count for the active policy
wrongv = {"lessonCompletionHistory": {l: [{"policyVersion": 1, "completedAt": 5}]
                                      for l in ev["lessonIds"]}}
assert svc.evaluate_course(TAIPEI, wrongv)["completed"] is False, "v1 history is not v2 completion"
assert svc.evaluate_course("no.such.course", {})["available"] is False
assert svc.evaluate_course(None, {})["completed"] is False
ok("campaign scope: course completion is derived from ACTIVE-version lesson completion; a partial "
   "campaign, an unknown course and a wrong-version history all evaluate to not complete")

# progress_view exposes campaigns read-only, with no internals
pv = svc.progress_view(done)
assert TAIPEI in pv["campaigns"] and pv["campaigns"][TAIPEI]["completed"] is True
assert pv["campaigns"][TAIPEI]["title"] == "Taipei"
assert set(pv["campaigns"][TAIPEI]) == {"title", "completed", "lessonIds", "completedLessonIds",
                                        "missingLessonIds"}
blob = json.dumps(pv)
for leak in ("rewardPolicy", "amountKey", "PASS_GOLD", "10000", "graderType", "scenarioPath"):
    assert leak not in blob, "progress view leaks %s" % leak
ok("progress API exposes campaign status read-only, with no reward or grader internals")

# ============================== end-to-end through a CANDIDATE registry ==============================
# Everything above proves production is inert. This proves the framework actually works when a
# future product decision does switch something on — using the real service, not a mock.
cand = copy.deepcopy(R.DATA)
for _lid, _l in cand["lessons"].items():                # every Taipei lesson earns the badge
    if _l.get("completionPolicy"):
        _l["completionPolicy"]["rewardPolicy"] = "lesson_mastery_badge"
cand["courses"][TAIPEI]["rewardPolicy"] = "campaign_complete_gold"
assert R.validate(cand) == [], R.validate(cand)
csvc = L.LearningService(reg=R.Registry(cand), content_root=ROOT,
                         reward_amounts={"PASS_GOLD": 10000, "CAMPAIGN_COMPLETE_GOLD": 250})
SUF = ["read_along", "quiz3", "quiz4", "matching", "wh", "cloze", "roleplay"]


def full(lid):
    st = {"activityScores": {}, "sttProgress": {}, "matchingProgress": {}, "roleplayProgress": {}}
    for s in SUF:
        aid = "%s.%s" % (lid, s)
        if s == "read_along":
            st["sttProgress"][aid] = {"pct": 90}
        elif s == "matching":
            st["matchingProgress"][aid] = {"correct": 9, "total": 10, "pct": 90}
        elif s == "roleplay":
            st["roleplayProgress"][aid] = {"passes": 9, "turns": 10, "pct": 90}
        else:
            st["activityScores"][aid] = {"correct": 9, "total": 10, "pct": 90}
    return st


# complete Zoo -> the lesson badge is granted, and NO gold moves for it
st = full(ZOO)
out = {}
csvc._settle_lesson(st, ZOO, 1000, out)
assert out["lessonCompletedNow"] is True
assert out["lessonRewardType"] == "cosmetic" and out["lessonRewardItemId"] == "badge.lesson.mastered"
assert out["lessonRewardAmount"] == 0 and out["lessonRewarded"] is False, "cosmetic pays no gold"
assert LG.owned_items(st) == ["badge.lesson.mastered"]
assert out["courseCompleted"] is False and out["courseRewardAmount"] == 0
# re-settling grants nothing a second time
out2 = {}
csvc._settle_lesson(st, ZOO, 2000, out2)
assert out2["lessonRewardAmount"] == 0 and "lessonRewardType" not in out2
assert len(LG.entries(st)) == 1 and LG.entries(st)[0]["grantedAt"] == 1000
ok("candidate lesson reward: a cosmetic lesson policy grants an item exactly once, pays no gold, "
   "and a second settlement adds nothing")

# complete the other three -> the campaign completes and its GOLD reward resolves once
for slug in ("mrt", "market", "park"):
    lid = "english.prea1.taipei." + slug
    for store, rows in full(lid).items():
        st.setdefault(store, {}).update(rows)
    out = {}
    csvc._settle_lesson(st, lid, 3000, out)
assert out["courseCompleted"] is True and out["courseCompletedNow"] is True
assert out["courseRewardType"] == "gold" and out["courseRewardAmount"] == 250
assert out["courseRewarded"] is True
assert LG.total_granted(st, "gold") == 250, "only the campaign gold is in the ledger"
assert sorted(e["scope"] for e in LG.entries(st)) == ["course", "lesson", "lesson", "lesson", "lesson"]
assert LG.owned_items(st) == ["badge.lesson.mastered"], "four grants, one distinct item"
# and it never fires twice
out3 = {}
csvc._settle_course(st, TAIPEI, 4000, out3)
assert out3["courseCompleted"] is True and out3["courseCompletedNow"] is False
assert out3["courseRewardAmount"] == 0
assert LG.total_granted(st, "gold") == 250
ok("candidate campaign reward: finishing the last lesson completes the campaign, grants its gold "
   "exactly once, and re-settling pays nothing")

# an unsized gold policy stays inert even when referenced and satisfied
cand2 = copy.deepcopy(cand)
cand2["courses"][TAIPEI]["rewardPolicy"] = "campaign_complete_gold"
nsvc = L.LearningService(reg=R.Registry(cand2), content_root=ROOT,
                         reward_amounts={"PASS_GOLD": 10000})     # no CAMPAIGN_COMPLETE_GOLD
st2 = copy.deepcopy(st)
st2.pop(LG.LEDGER_KEY, None)
out4 = {}
nsvc._settle_course(st2, TAIPEI, 5000, out4)
assert out4["courseCompleted"] is True and out4["courseCompletedNow"] is False
assert out4["courseRewardAmount"] == 0 and LG.entries(st2) == []
ok("an economic policy whose amount the game config does not supply stays completely inert — "
   "fail closed, never free money")

# ============================== gameplay type is declared, never applied ==============================
cand3 = copy.deepcopy(R.DATA)
cand3["lessons"][ZOO]["completionPolicy"]["rewardPolicy"] = "lesson_mastery_boost"
assert R.validate(cand3) == [], R.validate(cand3)
gsvc = L.LearningService(reg=R.Registry(cand3), content_root=ROOT,
                         reward_amounts={"PASS_GOLD": 10000})
st3 = full(ZOO)
out5 = {}
gsvc._settle_lesson(st3, ZOO, 6000, out5)
assert out5["lessonRewardType"] == "gameplay"
assert out5["lessonRewardItemId"] == "boost.lesson.mastered"
assert out5["lessonRewardAmount"] == 0, "a gameplay reward moves NO economy"
assert LG.owned_items(st3) == ["boost.lesson.mastered"]
assert LG.total_granted(st3, "gold") == 0
ok("a gameplay reward is recorded in the ledger and applies NO effect: it moves no gold, and no "
   "code path consumes it yet — wiring one is a separate product decision")

print()
print("All %d reward-framework tests passed." % passed)
