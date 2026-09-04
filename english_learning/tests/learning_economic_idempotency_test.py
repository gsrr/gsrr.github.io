#!/usr/bin/env python3
"""Phase 7C.1 — economic rewards must FAIL CLOSED on corrupt idempotency state.

    python3 tests/learning_economic_idempotency_test.py

A missing record legitimately means "never paid". A MALFORMED record means "we cannot tell", and for
anything that mints economic value the two must never collapse into the same answer. Cosmetic
rewards keep the Phase 5F fail-open behaviour, which is documented and safe because a duplicate
badge is inert.
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from learning import (api as L, completion as C, qualifications as Q,  # noqa: E402
                      registry as R, reward_ledger as LG, rewards as W)

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


PASS_GOLD = 10000
MASTERY_GOLD = 20000        # sentinel, like PASS_GOLD above
svc = L.LearningService(content_root=ROOT, reward_amounts={"PASS_GOLD": PASS_GOLD})
ZOO = "english.prea1.taipei.zoo"
QUIZ3 = ZOO + ".quiz3"
KEY = svc.completion_key(QUIZ3)
zoo_key = json.load(open(os.path.join(ROOT, "Pre-A1", "taipei", "zoo.json"),
                         encoding="utf-8"))["quiz3"]
ANSWERS = [{"q": i["q"], "answer": i["answer"]} for i in zoo_key]


def pay(state, now=100):
    """Settle a genuine passing attempt; returns (state, gold_paid)."""
    res, err = svc.grade_attempt(QUIZ3, ANSWERS)
    assert not err and res["passed"], err
    state, out = svc.record_attempt(state, QUIZ3, res, now)
    return state, out["rewardAmount"]


# ============================== the honest path is unchanged ==============================
st, first = pay({})
assert first == PASS_GOLD, first
st, second = pay(st, 200)
assert second == 0, "a second pass must never re-pay"
assert st["activityCompletions"][KEY]["rewarded"] is True
ok("baseline: the gold-bearing activity pays exactly once, and a normal retry pays nothing")

# ============================== VALID_ABSENT still pays ==============================
# Deleting the record is not corruption: it is a learner who has genuinely never passed.
fresh = copy.deepcopy(st)
del fresh["activityCompletions"][KEY]
fresh, again = pay(fresh, 300)
assert again == PASS_GOLD, "a genuinely absent record must remain payable"
ok("VALID_ABSENT: a missing completion record still pays — corruption handling must not "
   "punish a learner who really has not passed yet")

# ============================== CORRUPT must NOT pay ==============================
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
for label, junk in CORRUPTIONS.items():
    s = copy.deepcopy(st)
    if label == "whole table is a string":
        s["activityCompletions"] = junk
    else:
        s["activityCompletions"][KEY] = junk
    try:
        s, amount = pay(s, 400)
    except Exception as e:                     # a crash is its own defect: denial of service
        crashed.append("%s -> %s: %s" % (label, type(e).__name__, e))
        continue
    if amount != 0:
        bad.append("%s -> paid %d" % (label, amount))
assert not bad, "corrupt idempotency state MINTED gold: %s" % bad
assert not crashed, "corrupt idempotency state CRASHED settlement: %s" % crashed
ok("CORRUPT: every malformed completion shape refuses payment — uncertain payment history "
   "yields zero new economic value (%d shapes)" % len(CORRUPTIONS))

# ============================== corruption must not destroy evidence ==============================
s = copy.deepcopy(st)
s["activityCompletions"][KEY] = "junk"
before = copy.deepcopy(s["activityCompletions"])
s, amount = pay(s, 500)
assert amount == 0
assert s["activityCompletions"][KEY] == "junk", "the corrupt record was rewritten or erased"
ok("corruption is preserved, not repaired: the malformed record survives settlement so it stays "
   "diagnosable, and no reward ownership is fabricated")

# ============================== the learner is not bricked ==============================
s = copy.deepcopy(st)
s["activityCompletions"][KEY] = "junk"
res, err = svc.grade_attempt(QUIZ3, ANSWERS)
s, out = svc.record_attempt(s, QUIZ3, res, 600)
assert out["passed"] is True, "grading must still work"
assert out["rewardAmount"] == 0 and out["rewarded"] is False
sv = svc.state_view(s)
assert isinstance(sv, dict) and "qualifications" in sv, "state must remain readable"
pv = svc.progress_view(s)
assert isinstance(pv.get("lessons"), dict), "progress must remain readable"
ok("a corrupt economic record refuses the payout only: grading, qualifications, progress and "
   "state all keep working, so unrelated gameplay is never bricked")

# ============================== a corrupt COSMETIC record must not block gold ==============================
s = copy.deepcopy(st)
del s["activityCompletions"][KEY]          # genuinely unpaid
s[LG.LEDGER_KEY] = "totally-corrupt-cosmetic-ledger"
s, amount = pay(s, 700)
assert amount == PASS_GOLD, "a corrupt COSMETIC ledger must not block an unrelated legitimate payout"
ok("scope: cosmetic-ledger corruption does not leak into the activity payout decision, which is "
   "guarded by its own record")

# ============================== hypothetical mastery gold, never activated in production ==========
assert R.REGISTRY.lesson_reward_policy_of(ZOO) == "lesson_mastery_badge", \
    "production must still carry the COSMETIC lesson policy — 7C.1 activates no gold"
cand = copy.deepcopy(R.DATA)
cand["lessons"][ZOO]["completionPolicy"]["rewardPolicy"] = "lesson_mastery_gold"
assert R.validate(cand) == [], R.validate(cand)
msvc = L.LearningService(R.Registry(cand), content_root=ROOT,
                         reward_amounts={"PASS_GOLD": PASS_GOLD, "LESSON_MASTERY_GOLD": MASTERY_GOLD})
SUFFIX = ["read_along", "quiz3", "quiz4", "matching", "wh", "cloze", "roleplay"]


def master(state, now=1000):
    """Seed authoritative evidence for all seven Rule A levels, then settle the lesson."""
    for suf in SUFFIX:
        aid = ZOO + "." + suf
        if msvc.is_roleplay(aid):
            state.setdefault("roleplayProgress", {})[aid] = {"passes": 10, "turns": 10, "pct": 100}
        elif msvc.is_matching(aid):
            state.setdefault("matchingProgress", {})[aid] = {"correct": 10, "total": 10, "pct": 100}
        elif msvc.is_read_along(aid):
            state.setdefault("sttProgress", {})[aid] = {"pct": 100}
        else:
            Q.record_activity_score(state, aid, 10, 10, 100, now)
            Q.record_completion(state, msvc.completion_key(aid), passed_at=now, pct=100,
                                rewarded=True)
    out = {}
    msvc._settle_lesson(state, ZOO, now, out)
    return state, out.get("lessonRewardAmount", 0)

ms, paid = master({})
assert paid == MASTERY_GOLD, paid            # the INJECTED amount, whatever it is
ms2, again = master(copy.deepcopy(ms), 2000)
assert again == 0, "mastery gold must not re-pay on a replay"
ok("hypothetical mastery gold (test-only policy, never activated) pays exactly once and refuses "
   "a replayed settlement")

for label, mutate in (
        ("corrupt rewardLedger", lambda s: s.__setitem__(LG.LEDGER_KEY, "junk")),
        ("corrupt lessonCompletionHistory", lambda s: s.__setitem__(C.HISTORY_KEY, "junk")),
        ("corrupt this lesson's history entry",
         lambda s: s[C.HISTORY_KEY].__setitem__(ZOO, "junk")),
        ("corrupt legacy lessonCompletions", lambda s: s.__setitem__("lessonCompletions", "junk")),
):
    s = copy.deepcopy(ms)
    mutate(s)
    s, amount = master(s, 3000)
    assert amount == 0, "%s -> minted %d mastery gold" % (label, amount)
ok("corrupting the reward ledger, the completion history, a single history entry or the legacy "
   "completion table each refuse mastery gold rather than minting it again")

# a mastery-gold learner whose history is intact but ledger wiped is still not re-paid
s = copy.deepcopy(ms)
s.pop(LG.LEDGER_KEY, None)
s, amount = master(s, 4000)
assert amount == 0, "the completion record alone must still block a re-pay"
ok("defence in depth: with the ledger entirely removed, the intact completion history still "
   "blocks a second mastery payout")

# ============================== cosmetics keep the documented 5F behaviour ==============================
cs, cout = {}, {}
cs = svc._settle_lesson(cs, ZOO, 10, cout) or cs
badge = copy.deepcopy(ms)
badge[LG.LEDGER_KEY] = "junk"
assert LG.entries(badge) == [] and LG.owned_items(badge) == [], \
    "cosmetic reads still normalise to empty (Phase 5F)"
ok("cosmetic behaviour is unchanged: a corrupt ledger still reads as empty for display, exactly "
   "as Phase 5F documented")

# ============================== concurrency: one event -> at most one payout ==================
# server.py serialises load -> settle -> save under acct_lock at all four settlement endpoints, so
# two racing attempts cannot both observe "unpaid". Settlement is a pure state transition, so this
# models that contract: many callers sharing ONE state object under the lock yield exactly one payout.
import threading  # noqa: E402

shared, lock, amounts = {}, threading.Lock(), []


def racer():
    res, _ = svc.grade_attempt(QUIZ3, ANSWERS)
    with lock:                                   # mirrors server.py's `with acct_lock:`
        _, out = svc.record_attempt(shared, QUIZ3, res, 900)
        amounts.append(out["rewardAmount"])


ts = [threading.Thread(target=racer) for _ in range(8)]
for th in ts:
    th.start()
for th in ts:
    th.join()
assert sum(1 for a in amounts if a > 0) == 1, amounts
assert sum(amounts) == PASS_GOLD, amounts
ok("concurrency: 8 racing settlements of the same activity produce exactly ONE payout (%d gold "
   "total) under the same lock server.py holds" % sum(amounts))

# The domain alone cannot serialise separate snapshots — that mutual exclusion lives in server.py.
# Pinned here so nobody later removes acct_lock believing the domain is self-protecting.
snap = {}
res_u, _ = svc.grade_attempt(QUIZ3, ANSWERS)
_, o1 = svc.record_attempt(copy.deepcopy(snap), QUIZ3, res_u, 950)
_, o2 = svc.record_attempt(copy.deepcopy(snap), QUIZ3, res_u, 950)
assert o1["rewardAmount"] == PASS_GOLD and o2["rewardAmount"] == PASS_GOLD
ok("scope note: two settlements against SEPARATE state snapshots both pay — the exclusion that "
   "prevents that is server.py's acct_lock, and this test pins the requirement")

print("\nAll %d economic-idempotency tests passed." % passed)
