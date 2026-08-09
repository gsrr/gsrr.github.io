#!/usr/bin/env python3
"""Phase 7C.2 — the learning economy pays for MASTERY, not for the gate activity.

    python3 tests/learning_economy_rebalance_test.py

Model B, landed atomically: the gate activity pays 160, whole-lesson mastery pays 640, so a newly
mastered lesson is worth 800 and the six activities that used to pay nothing now carry 80% of the
value. Existing learners are never back-paid: mastery already recorded under the active policy
version is historical, and history is not a payable event.
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from game import config as GC  # noqa: E402
from learning import (api as L, completion as C, qualifications as Q,  # noqa: E402
                      registry as R, reward_ledger as LG, rewards as W)

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# game/config.py stays content-independent, so the constant is neutrally named MASTERY_GOLD; the
# learning-side amountKey it feeds is LESSON_MASTERY_GOLD. server.py owns that mapping.
AMOUNTS = {"PASS_GOLD": GC.PASS_GOLD, "LESSON_MASTERY_GOLD": GC.MASTERY_GOLD}
svc = L.LearningService(content_root=ROOT, reward_amounts=AMOUNTS)
reg = R.REGISTRY
TAIPEI4 = sorted("english.prea1.taipei." + s for s in ("zoo", "mrt", "market", "park"))
ZOO = "english.prea1.taipei.zoo"
QUIZ3 = ZOO + ".quiz3"
SUFFIX = ["read_along", "quiz3", "quiz4", "matching", "wh", "cloze", "roleplay"]
zoo_key = json.load(open(os.path.join(ROOT, "Pre-A1", "taipei", "zoo.json"),
                         encoding="utf-8"))["quiz3"]
ANSWERS = [{"q": i["q"], "answer": i["answer"]} for i in zoo_key]

# ============================== the approved production shape ==============================
assert GC.PASS_GOLD == 160, GC.PASS_GOLD
assert GC.MASTERY_GOLD == 640, GC.MASTERY_GOLD
assert GC.PASS_GOLD + GC.MASTERY_GOLD == 800
assert not hasattr(GC, "LESSON_MASTERY_GOLD"), (
    "game/ must not carry learning vocabulary — see the §20 content-independence regression")
GATES = sorted("english.prea1.taipei.%s.quiz3" % s
               for s in ("zoo", "mrt", "market", "park"))
gold_bearing = sorted(a for a in reg.activities if svc.reward_for(a)["amount"] > 0)
assert gold_bearing == GATES, gold_bearing          # Phase 7C.2a: all four gates
assert {reg.reward_policy_of(a) for a in GATES} == {"standard_activity_pass"}
for aid in GATES:
    assert svc.reward_for(aid)["amount"] == 160, aid
for lid in TAIPEI4:
    ps = reg.lesson_reward_policies_of(lid)
    assert ps == ["lesson_mastery_badge", "lesson_mastery_gold"], (lid, ps)
    econ = [p for p in ps if W.is_economic(p)]
    assert len(econ) == 1 and W.resolve(econ[0], AMOUNTS)["amount"] == 640, (lid, econ)
assert R.validate(R.DATA) == [], R.validate(R.DATA)
ok("production shape: four gold-bearing gate activities at 160 sharing one policy, four "
   "lessons paying 640 at mastery alongside the cosmetic badge - 800 per lesson, 3200 per "
   "campaign")

# the completion contract itself is untouched
for lid in TAIPEI4:
    cp = reg.completion_policy_of(lid)
    assert cp["type"] == "average_required_activities" and cp["version"] == 2
    assert cp["passMark"] == 80 and len(cp["requiredActivityIds"]) == 7
ok("completion semantics unchanged: average_required_activities v2, passMark 80, 7 activities")

# campaign stays cosmetic; nothing else economic exists
used = ({reg.lesson_reward_policy_of(l) for l in reg.lessons}
        | set(sum([reg.lesson_reward_policies_of(l) for l in reg.lessons], []))
        | {reg.course_reward_policy_of(c) for c in reg.courses}
        | {reg.reward_policy_of(a) for a in reg.activities})
assert sorted(p for p in used if W.is_economic(p)) == ["lesson_mastery_gold",
                                                       "standard_activity_pass"], sorted(used)
assert not [p for p in used if W.type_of(p) in ("gameplay", "profile")]
assert "campaign_complete_gold" not in used and "campaign_profile_frame" not in used
for cid in reg.courses:
    assert not W.is_economic(reg.course_reward_policy_of(cid)), cid
ok("campaign completion remains cosmetic-only; no gameplay or profile reward is active")


def master(state, lid=ZOO, now=1000):
    """Seed authoritative evidence for all seven Rule A levels, then settle."""
    for suf in SUFFIX:
        aid = lid + "." + suf
        if svc.is_roleplay(aid):
            state.setdefault("roleplayProgress", {})[aid] = {"passes": 10, "turns": 10, "pct": 100}
        elif svc.is_matching(aid):
            state.setdefault("matchingProgress", {})[aid] = {"correct": 10, "total": 10, "pct": 100}
        elif svc.is_read_along(aid):
            state.setdefault("sttProgress", {})[aid] = {"pct": 100}
        else:
            Q.record_activity_score(state, aid, 10, 10, 100, now)
            Q.record_completion(state, svc.completion_key(aid), passed_at=now, pct=100,
                                rewarded=True)
    out = {}
    svc._settle_lesson(state, lid, now, out)
    return state, out


def quiz3(state, now=100):
    res, err = svc.grade_attempt(QUIZ3, ANSWERS)
    assert not err and res["passed"], err
    state, out = svc.record_attempt(state, QUIZ3, res, now)
    return state, out


# ============================== A. fresh learner ==============================
st, o = quiz3({})
assert o["rewardAmount"] == 160, o["rewardAmount"]
assert o["granted"] == ["english.prea1.taipei.zoo"], o["granted"]
assert o["grantedNow"] == ["english.prea1.taipei.zoo"]
assert o.get("lessonRewardAmount", 0) == 0, "mastery must not pay at quiz3"
assert LG.owned_items(st) == [], "no badge yet"
st, mo = master(st, now=2000)
assert mo["lessonRewardAmount"] == 640, mo
assert mo["lessonCompletedNow"] is True
assert LG.owned_items(st) == ["badge.lesson.mastered"], LG.owned_items(st)
assert LG.total_granted(st, "gold") == 160 + 640 == 800
ok("A/fresh learner: quiz3 pays 160 and grants the qualification; mastery pays 640 and the badge; "
   "800 total, both recorded in the ledger")

# ============================== exactly-once ==============================
base = copy.deepcopy(st)
_, again = master(copy.deepcopy(base), now=3000)
assert again.get("lessonRewardAmount", 0) == 0, "replayed mastery must pay nothing"
s2, o2 = quiz3(copy.deepcopy(base), now=3100)
assert o2["rewardAmount"] == 0, "replayed quiz3 must pay nothing"
# a worse retry: mastery stands, no clawback, no re-pay
dip = copy.deepcopy(base)
# one zeroed level leaves the seven-level mean at ~86, still passing; two puts it unambiguously under
dip["sttProgress"][ZOO + ".read_along"] = {"pct": 0}
dip["matchingProgress"][ZOO + ".matching"] = {"correct": 0, "total": 10, "pct": 0}
ev = svc.evaluate_lesson(ZOO, dip)
assert ev["completed"] is False, "the live average should now be below the pass mark"
status = svc.lesson_status(ZOO, dip)
assert status["activePolicyCompleted"] is True, "mastery is an achievement and is never revoked"
_, dout = master(dip, now=3200)                      # recovery
assert dout.get("lessonRewardAmount", 0) == 0, "recovering must not pay a second time"
assert LG.total_granted(dip, "gold") == 800, LG.total_granted(dip, "gold")
ok("exactly-once: replayed mastery, replayed quiz3, a Needs-Review dip and a recovery all pay 0; "
   "mastery gold is never clawed back")

# ============================== B/C/D. migration ==============================
# B — an old learner paid the historical 10000, never mastered.
old_b = {"activityCompletions": {svc.completion_key(QUIZ3):
                                 {"passedAt": 1, "pct": 100, "rewarded": True}},
         "qualifications": {"english.prea1.taipei.zoo": {"earnedAt": 1}}}
snap_b = copy.deepcopy(old_b)
_, ob = quiz3(copy.deepcopy(old_b), now=4000)
assert ob["rewardAmount"] == 0, "the historical gate payout is never re-paid at the new rate"
b_state, bm = master(copy.deepcopy(old_b), now=4100)
assert bm["lessonRewardAmount"] == 640, "a first-ever mastery still pays, at the new rate"
assert snap_b["activityCompletions"] == old_b["activityCompletions"], "history was mutated"
ok("B/old learner with the historical 10000 but no mastery: no clawback, no re-pay of the gate, "
   "and their FIRST mastery pays 640 like anyone else")

# C — an old learner who already mastered under the ACTIVE v2 policy.
old_c = {}
old_c, _ = master(old_c, now=10)                      # mastered while the policy was cosmetic-only
old_c.pop(LG.LEDGER_KEY, None)                        # they never had a gold ledger entry
gold_before = LG.total_granted(old_c, "gold")
hist_before = copy.deepcopy(old_c[C.HISTORY_KEY])
for now in (5000, 5100, 5200):                        # several later touches
    old_c, oc = master(old_c, now=now)
    assert oc.get("lessonRewardAmount", 0) == 0, "retroactive mastery gold was minted at %d" % now
    assert oc["lessonCompletedNow"] is False
_, ocq = quiz3(old_c, now=5300)
assert ocq.get("lessonRewardAmount", 0) == 0, "a later attempt must not backfill mastery gold"
assert LG.total_granted(old_c, "gold") == gold_before
assert old_c[C.HISTORY_KEY] == hist_before, "completion history was rewritten"
ok("C/old learner already mastered under active v2: NO retroactive 640 on any later attempt, "
   "no clawback, and the completion history is left byte-identical")

# D — a learner carrying retired v1 history as well as v2.
old_d = {}
old_d, _ = master(old_d, now=20)
old_d[C.HISTORY_KEY][ZOO].insert(0, {"policyVersion": 1, "completedAt": 5})
hist_d = copy.deepcopy(old_d[C.HISTORY_KEY])
old_d, od = master(old_d, now=6000)
assert od.get("lessonRewardAmount", 0) == 0, "v1+v2 history must not produce a fresh payout"
assert old_d[C.HISTORY_KEY] == hist_d, "policy history was rewritten"
ok("D/learner with retired v1 and active v2 history: no retroactive gold, no duplicate reward and "
   "no rewrite of the version history")

# the mechanism, stated explicitly
probe = {}
probe, _ = master(probe, now=30)
_, again2 = master(probe, now=40)
assert again2["lessonCompletedNow"] is False
ok("the distinction is the ACTIVE-VERSION completion record: _settle_lesson only reaches the grant "
   "path when record_lesson_completion reports `newly`, so historical mastery is structurally "
   "unpayable rather than filtered after the fact")

# ============================== corruption still fails closed ==============================
for label, mutate in (
        ("corrupt lessonCompletionHistory", lambda s: s.__setitem__(C.HISTORY_KEY, "junk")),
        ("corrupt this lesson's entry",
         lambda s: s.setdefault(C.HISTORY_KEY, {}).__setitem__(ZOO, "junk")),
        ("corrupt legacy lessonCompletions", lambda s: s.__setitem__("lessonCompletions", "junk")),
):
    s = {}
    mutate(s)
    s, co = master(s, now=7000)
    assert co.get("lessonRewardAmount", 0) == 0, "%s minted mastery gold" % label
    assert co.get("lessonRewardBlocked") == "corrupt_payment_history", (label, co)
for junk in ("junk", 12345, ["x"], {"k": "v"}, {"k": {"passedAt": 1}}):
    s = copy.deepcopy(base)
    s["activityCompletions"][svc.completion_key(QUIZ3)] = junk
    _, jo = quiz3(s, now=7100)
    assert jo["rewardAmount"] == 0, "corrupt gate history minted %d" % jo["rewardAmount"]
ok("Phase 7C.1 hardening still holds at the new rates: corrupt mastery history refuses 640 with a "
   "diagnostic, and corrupt gate history refuses 160")

# ============================== the client cannot influence either amount =================
forged = {"activityId": QUIZ3, "rewardAmount": 999999, "rewardType": "gold",
          "lessonRewardAmount": 999999, "rewarded": False,
          "rewardPolicy": "campaign_complete_gold", "pct": 100, "passed": True}
res, _ = svc.grade_attempt(QUIZ3, ANSWERS)
assert isinstance(res, dict) and res["passed"] is True
s, fo = svc.record_attempt({}, QUIZ3, dict(res, **forged), 8000)
assert fo["rewardAmount"] == 160, fo["rewardAmount"]
s, fm = master(s, now=8100)
assert fm["lessonRewardAmount"] == 640, fm["lessonRewardAmount"]
ok("forged reward fields in the graded result are ignored: the server resolves 160 and 640 from "
   "game config through the policy allowlist, never from the payload")

# ============================== concurrency ==============================
import threading  # noqa: E402

shared, lock, paid = {}, threading.Lock(), []


def racer():
    res_c, _ = svc.grade_attempt(QUIZ3, ANSWERS)
    with lock:                                    # mirrors server.py's acct_lock
        _, out_c = svc.record_attempt(shared, QUIZ3, res_c, 9000)
        paid.append(out_c["rewardAmount"])


ts = [threading.Thread(target=racer) for _ in range(8)]
for th in ts:
    th.start()
for th in ts:
    th.join()
assert sum(paid) == 160, paid

mshared, mpaid = {}, []


def mracer():
    with lock:
        _, mo_c = master(mshared, now=9100)
        mpaid.append(mo_c.get("lessonRewardAmount", 0))


ts = [threading.Thread(target=mracer) for _ in range(8)]
for th in ts:
    th.start()
for th in ts:
    th.join()
assert sum(mpaid) == 640, mpaid
ok("concurrency: 8 racing gate settlements total 160 and 8 racing mastery settlements total 640 "
   "under the lock server.py holds")

print("\nAll %d economy-rebalance tests passed." % passed)
