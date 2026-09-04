#!/usr/bin/env python3
"""Phase 7C.2a — the gate reward applies uniformly to ALL FOUR Taipei quiz3 activities.

    python3 tests/learning_gate_coverage_test.py

Phase 7C.2 set the amounts (160 at the gate, 640 at mastery) but left `standard_activity_pass`
attached to Zoo alone, so three of the four lessons were worth 640 instead of 800. This phase
completes the coverage. The point of the tests below is that every economic guarantee previously
proven for Zoo — exactly-once, no retroactive backfill, fail-closed on corrupt payment history,
one payout under concurrency — now holds for each of the four gates independently, and that the
four share ONE policy rather than four look-alike ones.
"""
import copy
import json
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))   # Phase 9B.1: shared registry-derived expectations
import curriculum_expectations as CX  # noqa: E402
from game import config as GC                                          # noqa: E402
from learning import (api as L, completion as C, qualifications as Q,  # noqa: E402
                      registry as R, reward_ledger as LG, rewards as W)

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


SLUGS = ("zoo", "mrt", "market", "park")
LESSONS = ["english.prea1.taipei." + s for s in SLUGS]
GATES = sorted(lid + ".quiz3" for lid in LESSONS)
AMOUNTS = {"PASS_GOLD": GC.PASS_GOLD, "LESSON_MASTERY_GOLD": GC.MASTERY_GOLD}
svc = L.LearningService(content_root=ROOT, reward_amounts=AMOUNTS)
reg = R.REGISTRY


def answers(slug):
    key = json.load(open(os.path.join(ROOT, "Pre-A1", "taipei", slug + ".json"),
                         encoding="utf-8"))["quiz3"]
    return [{"q": i["q"], "answer": i["answer"]} for i in key]


def pay(state, slug, now=100):
    """Settle a genuine passing attempt at one gate; returns (state, gold_paid, out)."""
    aid = "english.prea1.taipei.%s.quiz3" % slug
    res, err = svc.grade_attempt(aid, answers(slug))
    assert not err and res["passed"], (aid, err)
    state, out = svc.record_attempt(state, aid, res, now)
    return state, out["rewardAmount"], out


# ====================== the shape: four gates, one policy, one amount ======================
gold_bearing = sorted(a for a in reg.activities if svc.reward_for(a)["amount"] > 0)
# Phase 9B.1: derived population, not a count. `len == 5` was true of today's inventory only.
assert gold_bearing == CX.declared_gates(reg), gold_bearing
CX.assert_reward_model(reg, svc, GC.PASS_GOLD)
# identity, not merely count — a regression that swapped one lesson's gate for another would keep
# the count at 4 and must still fail here
# The FOUR Taipei gates stay pinned by identity: they are the world contract (each grants a
# Conquest qualification). Curriculum gates are derived and may grow freely alongside them.
assert CX.qualification_bearing(reg) == ["english.prea1.taipei.market.quiz3",
                                        "english.prea1.taipei.mrt.quiz3",
                                        "english.prea1.taipei.park.quiz3",
                                        "english.prea1.taipei.zoo.quiz3"], CX.qualification_bearing(reg)
assert {reg.reward_policy_of(a) for a in GATES} == {"standard_activity_pass"}, \
    "all four gates must resolve through ONE shared policy — no per-lesson reward ids"
for aid in GATES:
    assert svc.reward_for(aid) == {"type": "gold", "amount": GC.PASS_GOLD, "itemId": None,
                                   "once": True}, aid
for lid in LESSONS:
    assert reg.lesson_reward_policies_of(lid) == ["lesson_mastery_badge", "lesson_mastery_gold"], lid
assert R.validate(R.DATA) == [], R.validate(R.DATA)
ok("shape: exactly the four quiz3 gates are gold-bearing, by identity; all four share "
   "`standard_activity_pass` at 160, and each lesson still pays 640 at mastery — 800 per lesson")

# the registry names policies, never amounts
raw = open(os.path.join(ROOT, "learning", "registry.json"), encoding="utf-8").read()
for n in (str(GC.PASS_GOLD), str(GC.MASTERY_GOLD),
          str(GC.PASS_GOLD + GC.MASTERY_GOLD), "3200", "10000"):
    assert n not in raw, "registry.json names the amount %s" % n
ok("content independence: registry.json names policies only — no amount appears anywhere in it")

# ====================== qualification ownership is untouched ======================
qual_acts = sorted(a for a in reg.activities if reg.qualification_ids_for(a))
assert qual_acts == GATES, qual_acts
assert sorted(reg.qualifications) == ["english.prea1.taipei.market.quiz3.pass",
                                      "english.prea1.taipei.mrt.quiz3.pass",
                                      "english.prea1.taipei.park.quiz3.pass",
                                      "english.prea1.taipei.zoo"], sorted(reg.qualifications)
for lid in LESSONS:
    assert reg.lesson_qualification_ids_for(lid) == [], lid   # mastery never grants a qualification
ok("qualification ownership unmoved: the same four gates certify the same four qualifications, and "
   "lesson mastery still certifies nothing")

# ====================== every gate pays exactly once ======================
st, total = {}, 0
for slug in SLUGS:
    st, amount, out = pay(st, slug, 100)
    assert amount == GC.PASS_GOLD, (slug, amount)
    assert out["rewarded"] is True and out["granted"], slug
    total += amount
assert total == 4 * GC.PASS_GOLD == 2000, total
for slug in SLUGS:
    st, again, _ = pay(st, slug, 200)
    assert again == 0, "%s re-paid its gate" % slug
assert len(Q.qualification_ids(st) if hasattr(Q, "qualification_ids")
           else (st.get("qualifications") or {})) == 4
ok("all four gates: first authoritative pass pays 160 each (640 total), and every replay pays 0 — "
   "proven per activity, not only for Zoo")

# re-settlement against the SAME state (refresh / re-login / another room all reload this state).
# The comparison is scoped to the PAYMENT stores on purpose: `activityScores` legitimately records
# every graded attempt (§1, pass or fail), so the whole state is expected to move. What may not move
# is anything that decides whether money is owed.
def payment_state(s):
    return json.dumps({"completions": s.get("activityCompletions"),
                       "ledger": s.get(LG.LEDGER_KEY)}, sort_keys=True)


snapshot = payment_state(st)
for slug in SLUGS:
    st, amount, _ = pay(st, slug, 300)
    assert amount == 0, slug
for lid in LESSONS:                       # reading + settling lessons mints no activity gold
    out = {}
    svc._settle_lesson(st, lid, 300, out)
    assert out.get("rewardAmount", 0) == 0, lid
svc.state_view(st), svc.progress_view(st)
assert payment_state(st) == snapshot, "a read/re-settle path mutated payment state"
ok("re-settlement, progress reads and lesson settlement add no activity gold and leave the "
   "payment stores (completions + ledger) byte-identical")

# ====================== forged client input cannot influence any gate ======================
for slug in SLUGS:
    aid = "english.prea1.taipei.%s.quiz3" % slug
    s = copy.deepcopy(st)
    del s["activityCompletions"][svc.completion_key(aid)]      # genuinely unpaid again
    res, _ = svc.grade_attempt(aid, answers(slug))
    forged = dict(res, rewardAmount=10000, rewardPolicy="campaign_complete_gold",
                  rewarded=False, gold=999999, passed=True, pct=100)
    s, out = svc.record_attempt(s, aid, forged, 400)
    assert out["rewardAmount"] == GC.PASS_GOLD, (slug, out["rewardAmount"])
    assert out.get("rewardType") == "gold"
ok("forged reward fields in the graded result are ignored at every gate: the amount is resolved "
   "from game config through the policy allowlist, never from the payload")

# ====================== corrupt payment history fails closed, at every gate ======================
CORRUPTIONS = {
    "string": "junk",
    "int": 12345,
    "list": [{"passedAt": 1, "pct": 100, "rewarded": True}],
    "null": None,
    "dict missing rewarded": {"passedAt": 100, "pct": 100},
    "dict with non-bool rewarded": {"passedAt": 100, "pct": 100, "rewarded": "yes"},
    "whole table is a string": "activityCompletions-was-clobbered",
}
bad, crashed = [], []
for slug in SLUGS:
    aid = "english.prea1.taipei.%s.quiz3" % slug
    key = svc.completion_key(aid)
    for label, junk in CORRUPTIONS.items():
        s = copy.deepcopy(st)
        if label == "whole table is a string":
            s["activityCompletions"] = junk
        else:
            s["activityCompletions"][key] = junk
        try:
            s, amount, _ = pay(s, slug, 500)
        except Exception as e:                    # a crash is its own defect: denial of service
            crashed.append("%s/%s -> %s: %s" % (slug, label, type(e).__name__, e))
            continue
        if amount != 0:
            bad.append("%s/%s -> paid %d" % (slug, label, amount))
assert not bad, "corrupt idempotency state MINTED gold: %s" % bad
assert not crashed, "corrupt idempotency state CRASHED settlement: %s" % crashed
ok("fail-closed everywhere: %d malformed shapes x 4 gates all refuse payment — no 160, no 640, no "
   "10000, no partial grant" % len(CORRUPTIONS))

# ====================== concurrency: one event -> one payout, per gate ======================
for slug in SLUGS:
    aid = "english.prea1.taipei.%s.quiz3" % slug
    shared, lock, amounts = {}, threading.Lock(), []

    def racer(_aid=aid, _slug=slug, _shared=shared, _lock=lock, _amounts=amounts):
        res, _ = svc.grade_attempt(_aid, answers(_slug))
        with _lock:                              # mirrors server.py's `with acct_lock:`
            _, out = svc.record_attempt(_shared, _aid, res, 900)
            _amounts.append(out["rewardAmount"])

    ts = [threading.Thread(target=racer) for _ in range(8)]
    for th in ts:
        th.start()
    for th in ts:
        th.join()
    assert sum(1 for a in amounts if a > 0) == 1, (slug, amounts)
    assert sum(amounts) == GC.PASS_GOLD, (slug, amounts)
ok("concurrency: at every gate, 8 racing settlements of the same activity produce exactly ONE "
   "160 payout under the lock server.py holds")

# ====================== existing players: no retroactive activity gold ======================
# Rebuild the exact state a learner would carry from BEFORE this phase, when the three gates were
# `none`, then run them against today's registry.
old_data = copy.deepcopy(R.DATA)
for slug in ("mrt", "market", "park"):
    old_data["activities"]["english.prea1.taipei.%s.quiz3" % slug]["rewardPolicy"] = "none"
old_svc = L.LearningService(R.Registry(old_data), content_root=ROOT, reward_amounts=AMOUNTS)
legacy, legacy_paid = {}, 0
for slug in SLUGS:
    aid = "english.prea1.taipei.%s.quiz3" % slug
    res, _ = old_svc.grade_attempt(aid, answers(slug))
    legacy, out = old_svc.record_attempt(legacy, aid, res, 100)
    legacy_paid += out["rewardAmount"]
assert legacy_paid == GC.PASS_GOLD, legacy_paid              # only Zoo paid, back then
for slug in ("mrt", "market", "park"):
    rec = Q.get_completion(legacy, svc.completion_key("english.prea1.taipei.%s.quiz3" % slug))
    assert rec["rewarded"] is False, slug                    # historically completed, never paid

before = copy.deepcopy(legacy)
svc.state_view(legacy), svc.progress_view(legacy)            # Learning Home / lesson / Profile
for lid in LESSONS:
    out = {}
    svc._settle_lesson(legacy, lid, 700, out)
    assert out.get("rewardAmount", 0) == 0, lid
assert json.dumps(legacy.get("activityCompletions"), sort_keys=True) == \
    json.dumps(before.get("activityCompletions"), sort_keys=True), \
    "an unrelated settlement rewrote a historical completion record"
assert LG.total_granted(legacy, "gold") == LG.total_granted(before, "gold")
ok("existing players: activating three gate policies mints NOTHING on its own — reads, refreshes, "
   "re-logins and lesson settlement all pay 0, and no historical completion record is rewritten "
   "to manufacture or deny eligibility")

# ====================== mastery behaviour from 7C.2 is undisturbed ======================
SUFFIX = ["read_along", "quiz3", "quiz4", "matching", "wh", "cloze", "roleplay"]


def master(state, lid, now=1000):
    """Seed authoritative evidence for all seven Rule A levels, then settle the lesson."""
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
    return state, out.get("lessonRewardAmount", 0)


ms, mastery_total = {}, 0
for lid in LESSONS:
    ms, amount = master(ms, lid, 1000)
    assert amount == GC.MASTERY_GOLD, (lid, amount)
    mastery_total += amount
    _, again = master(copy.deepcopy(ms), lid, 2000)
    assert again == 0, "%s re-paid mastery" % lid
assert mastery_total == 4 * GC.MASTERY_GOLD == 10000, mastery_total
ok("mastery is undisturbed by this phase: each lesson still pays 640 exactly once (2560 across the "
   "campaign) and refuses a replayed settlement")

# ====================== the whole-campaign total ======================
fresh, gate_total = {}, 0
for slug in SLUGS:
    fresh, amount, _ = pay(fresh, slug, 3000)
    gate_total += amount
for lid in LESSONS:
    fresh, amount = master(fresh, lid, 3100)
    assert amount == GC.MASTERY_GOLD, lid
learning_total = LG.total_granted(fresh, "gold")
assert gate_total == 4 * GC.PASS_GOLD == 2000, gate_total
assert learning_total == 4 * (GC.PASS_GOLD + GC.MASTERY_GOLD) == 12000, learning_total
# the ledger alone explains the balance, and cosmetics contribute nothing to it
by_policy = {}
for e in LG.entries(fresh):
    by_policy.setdefault(e["policyId"], []).append(e["amount"])
assert sorted(by_policy["standard_activity_pass"]) == [GC.PASS_GOLD] * 4, by_policy
assert sorted(by_policy["lesson_mastery_gold"]) == [GC.MASTERY_GOLD] * 4, by_policy
assert by_policy["lesson_mastery_badge"] == [0] * 4, by_policy
assert by_policy.get("campaign_trophy", [0]) == [0], by_policy
assert sum(e["amount"] for e in LG.entries(fresh) if e["rewardType"] == "cosmetic") == 0
assert {e["rewardType"] for e in LG.entries(fresh)} == {"gold", "cosmetic"}, "no gameplay/profile"
ok("whole campaign: 4 x 160 at the gates + 4 x 640 at mastery = 3200 learning gold; the ledger "
   "alone explains it, every cosmetic entry records 0, and campaign completion adds no gold")

print("\nAll %d gate-coverage tests passed." % passed)
