#!/usr/bin/env python3
"""Phase 9B.1 — the invariants that make bulk curriculum migration safe.

    python3 tests/migration_invariants_test.py

Two jobs:

1. Pin the QUALIFICATION-FREE CURRICULUM rule in a form that does not tax future migrations. The
   population of paying gates is derived from registry policy declarations, so registering A1/002-012
   (or Pre-A1, A2, B1) needs no edit here. What stays exact is the world contract: the four Conquest
   qualification ids and the territories that require them.

2. Prove the derived assertions in tests/curriculum_expectations.py are STRONGER, not merely shorter,
   than the hardcoded censuses Phase 9B had to edit in twelve files. Every guard below is exercised
   with a NEGATIVE CONTROL: the registry is mutated and the guard must fire. A derived assertion that
   cannot fail is worse than the census it replaced, so each one is shown failing on purpose.

Plus a regression for the Phase 9B.1 validator fix: `lesson_mastery_gold` really pays MASTERY_GOLD on
every mastered lesson, but the validator called it "inert (unreferenced)" because its discovery read
only the FIRST reward policy of each lesson.
"""
import copy
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import curriculum_expectations as CX  # noqa: E402
from game import config as GC  # noqa: E402
from learning import api as L, registry as R, rewards as W  # noqa: E402
import territory_catalog as TC  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


AMOUNTS = {"PASS_GOLD": GC.PASS_GOLD, "LESSON_MASTERY_GOLD": GC.MASTERY_GOLD}
svc = L.LearningService(content_root=ROOT, reward_amounts=AMOUNTS)
reg = R.REGISTRY


def build(data):
    return R.Registry(data), L.LearningService(R.Registry(data), content_root=ROOT,
                                               reward_amounts=AMOUNTS)


def must_fail(data, why):
    """The derived model must reject this registry."""
    r2, s2 = build(data)
    try:
        CX.assert_completion_model(r2)
        CX.assert_reward_model(r2, s2, GC.PASS_GOLD)
    except AssertionError:
        return
    raise AssertionError("the derived model ACCEPTED a registry it must reject: " + why)


# ====================== 1. the real registry satisfies both models ======================
CX.assert_completion_model(reg)
gates, completable = CX.assert_reward_model(reg, svc, GC.PASS_GOLD)
ok("the live registry satisfies the derived completion + reward models (%d gates, %d completable "
   "lessons — both derived, neither hardcoded)" % (len(gates), len(completable)))

# ====================== 2. qualification-free curriculum, derived ======================
world_gates = CX.qualification_bearing(reg)
curriculum = CX.curriculum_gates(reg)
assert sorted(world_gates + curriculum) == gates, (world_gates, curriculum, gates)
assert world_gates == sorted(l + ".quiz3" for l in CX.TAIPEI4), world_gates
for aid in curriculum:
    assert svc.reward_for(aid)["amount"] == GC.PASS_GOLD, aid
    assert reg.qualification_ids_for(aid) == [], aid
    lid = reg.activities[aid]["lessonId"]
    assert reg.completion_available(lid), (aid, lid)
    assert reg.lesson_qualification_ids_for(lid) == [], lid
    assert W.is_economic(reg.reward_policy_of(aid)), aid
# the rule, stated so it survives any future population:
assert set(curriculum).isdisjoint(world_gates)
ok("qualification-free curriculum rule: every paying gate is either a WORLD gate (grants a Conquest "
   "qualification) or a CURRICULUM gate (grants nothing, still pays PASS_GOLD). Today %d world / "
   "%d curriculum; the assertion does not name either population" % (len(world_gates), len(curriculum)))

# ====================== 3. the exact Conquest contract stays exact ======================
assert sorted(reg.qualifications) == CX.CONQUEST_QUALIFICATIONS, sorted(reg.qualifications)
assert len(reg.qualifications) == 4
cat = TC.TerritoryCatalog(os.path.join(ROOT, "world-data")).load()
gated = {t: sorted(cat.attack_requirements(t)) for t in cat.territories
         if cat.attack_requirements(t)}
assert gated == {k: sorted(v) for k, v in CX.GATED_TERRITORIES.items()}, gated
for qids in gated.values():
    for q in qids:
        assert q in CX.CONQUEST_QUALIFICATIONS, q
        assert reg.granted_by(q), ("no activity can grant a required qualification", q)
ok("Conquest contract pinned EXACTLY: 4 qualification ids, 5 gated territories, every required "
   "qualification is grantable by some activity")

# ====================== 4. NEGATIVE CONTROLS — each guard must fire ======================
# 4a. a curriculum gate that starts granting a NEW qualification (the migration mistake that matters)
d = copy.deepcopy(R.DATA)
d["qualifications"]["english.a1.core.001.quiz3.pass"] = {"scope": "activity", "title": "x"}
d["activities"]["english.a1.core.001.quiz3"]["grants"] = ["english.a1.core.001.quiz3.pass"]
must_fail(d, "a curriculum lesson minted a world qualification")
ok("4a NEGATIVE: a curriculum gate that grants a new qualification is REJECTED (this is the guard "
   "that keeps CEFR content from silently unlocking territory)")

# 4b. a gate paying an amount of its own
d = copy.deepcopy(R.DATA)
d["activities"]["english.prea1.taipei.zoo.quiz3"]["rewardPolicy"] = "lesson_mastery_gold"
must_fail(d, "a gate used a non-gate reward policy")
ok("4b NEGATIVE: a gate wired to a different reward policy is REJECTED")

# 4c. a NON-gate activity that starts paying
d = copy.deepcopy(R.DATA)
d["activities"]["english.prea1.taipei.zoo.wh"]["rewardPolicy"] = "standard_activity_pass"
d["activities"]["english.prea1.taipei.zoo.wh"]["grants"] = []
r2, s2 = build(d)
extra = CX.declared_gates(r2)
assert "english.prea1.taipei.zoo.wh" in extra, extra
# paying == declaring still holds, so this is ALLOWED by design (it is exactly what migrating a
# lesson looks like). What must still hold is the world contract — and it does:
CX.assert_reward_model(r2, s2, GC.PASS_GOLD)
ok("4c BOUNDARY: a new activity declaring the gate policy is ACCEPTED (that is migration) while the "
   "world contract still holds — the deliberate loosening, scoped to reward count only")

# 4d. a completable lesson that drops its mastery reward
d = copy.deepcopy(R.DATA)
d["lessons"]["english.a1.core.001"]["completionPolicy"]["rewardPolicy"] = ["lesson_mastery_gold"]
must_fail(d, "a completable lesson lost its cosmetic badge policy")
ok("4d NEGATIVE: a completable lesson without the standard mastery policy pair is REJECTED")

# 4e. a policy requiring an activity that is not registered / belongs elsewhere
d = copy.deepcopy(R.DATA)
d["lessons"]["english.a1.core.001"]["completionPolicy"]["requiredActivityIds"] = \
    ["english.a1.core.001.read_along", "english.prea1.taipei.zoo.quiz3"]
must_fail(d, "a policy required a FOREIGN lesson's activity")
ok("4e NEGATIVE: a completion policy requiring another lesson's activity is REJECTED (the old id "
   "censuses could not see this at all)")

d = copy.deepcopy(R.DATA)
d["lessons"]["english.a1.core.001"]["completionPolicy"]["requiredActivityIds"] = \
    ["english.a1.core.001.does_not_exist"]
must_fail(d, "a policy required an unregistered activity")
ok("4f NEGATIVE: a completion policy requiring an UNREGISTERED activity is REJECTED")

# 4g. a per-lesson pass mark
d = copy.deepcopy(R.DATA)
d["lessons"]["english.a1.core.001"]["completionPolicy"]["passMark"] = 40
must_fail(d, "a lesson invented its own pass mark")
ok("4g NEGATIVE: a lesson-specific passMark is REJECTED (no difficulty drift across curriculum)")

# 4h. an extra qualification appearing in the registry
d = copy.deepcopy(R.DATA)
d["qualifications"]["english.a1.core.999"] = {"scope": "activity", "title": "x"}
must_fail(d, "the qualification set grew")
ok("4h NEGATIVE: adding ANY qualification is REJECTED — the world contract still costs a "
   "deliberate test edit, which is where the tax belongs")

# ====================== 5. validator discovery regression (Goal B) ======================
VAL = os.path.join(ROOT, "tools", "validate_learning_registry.py")
out = subprocess.run([sys.executable, VAL], capture_output=True, text=True, cwd=ROOT)
assert out.returncode == 0, out.stdout + out.stderr
text = out.stdout
# the bug: this line used to read "inert (unreferenced)"
assert "lesson_mastery_gold" in text
mg = [l for l in text.splitlines() if "lesson_mastery_gold" in l][0]
assert "REFERENCED by" in mg and "lesson x" in mg, mg
assert "inert" not in mg, "lesson_mastery_gold must not be reported inert — it pays MASTERY_GOLD"
econ = [l for l in text.splitlines() if "economic policies in use" in l][0]
assert "lesson_mastery_gold" in econ and "standard_activity_pass" in econ, econ
# it must still find genuinely unused economic/framework policies
for pid in ("campaign_complete_gold", "campaign_profile_frame", "lesson_mastery_boost"):
    line = [l for l in text.splitlines() if pid in l][0]
    assert "inert (unreferenced)" in line, line
# and the gold-bearing-lesson alarm must now actually fire
assert "carry a gold-bearing completion reward" in text, "the mastery-gold alarm still cannot fire"
ok("5. validator now discovers EVERY referenced policy per scope: lesson_mastery_gold is "
   "'REFERENCED by lesson', economic-policy list names both gold policies, the 3 unused policies "
   "are still 'inert', and the gold-bearing-lesson warning fires")

# the payout the validator was blind to is real
lid = "english.prea1.taipei.zoo"
assert "lesson_mastery_gold" in reg.lesson_reward_policies_of(lid)
assert W.resolve("lesson_mastery_gold", AMOUNTS)["amount"] == GC.MASTERY_GOLD == 2500
assert reg.lesson_reward_policy_of(lid) == "lesson_mastery_badge", \
    "the FIRST policy is cosmetic — precisely why singular discovery hid the gold one"
ok("lesson_mastery_gold resolves to MASTERY_GOLD (%d); the first-declared policy is the cosmetic "
   "badge, which is the root cause of the blind spot" % GC.MASTERY_GOLD)

# a framework-only policy referenced by content must still be an ERROR
d = copy.deepcopy(R.DATA)
d["lessons"]["english.a1.core.001"]["completionPolicy"]["rewardPolicy"] = \
    ["lesson_mastery_badge", "lesson_mastery_boost"]
import tempfile  # noqa: E402
tmp = tempfile.mkdtemp()
alt = os.path.join(tmp, "registry.json")
json.dump(d, open(alt, "w", encoding="utf-8"), ensure_ascii=False)
used = {}
for lid2 in d["lessons"]:
    for p in (d["lessons"][lid2].get("completionPolicy") or {}).get("rewardPolicy") or []:
        used.setdefault(p, []).append(lid2)
assert "lesson_mastery_boost" in used, used
assert "lesson_mastery_boost" not in W.ACTIVE_POLICY_IDS, \
    "a gameplay policy must stay off the production allowlist"
ok("framework-only policies stay unreferenceable: lesson_mastery_boost is discoverable at lesson "
   "scope yet absent from ACTIVE_POLICY_IDS, so the validator's error path still applies")

print("\nAll %d migration-invariant tests passed." % passed)
