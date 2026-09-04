"""Shared, registry-DERIVED expectations for the maintained learning suites (Phase 9B.1).

Phase 9B migrated one curriculum lesson and had to edit twelve test files, because each of them
duplicated the current census — "the gold-bearing set is exactly these four ids", "the completable
lessons are exactly these four" — in its own Python list. That is a tax of O(files) on every content
migration, and 52 units are still to come.

The split this module draws:

  DERIVED (this module computes it from the registry)
      which activities pay, which lessons are completable, which activities grant a qualification.
      Those populations grow every time curriculum is migrated. A test that hardcodes them is
      asserting today's inventory, not a product rule.

  FIXED (this module pins it as a literal)
      the four Conquest qualification ids, and which territories require them. That IS a product
      contract: it is the entire coupling between learning and the game world, world-data names
      those exact strings, and it must not drift silently. Adding a qualification should cost a
      deliberate test edit.

So the rule is: derive the population, assert the semantics over every member, and keep the world
contract exact. `assert_reward_model()` below is deliberately stronger than the censuses it replaces
— it holds for any future population, including lessons that do not exist yet.
"""

# The four qualifications the Conquest world is built on. FIXED ON PURPOSE — see the docstring.
# `english.prea1.taipei.zoo` is bare rather than `...zoo.quiz3.pass` for historical reasons; the
# inconsistency is deliberately preserved (normalising it is a separate migration concern).
CONQUEST_QUALIFICATIONS = [
    "english.prea1.taipei.market.quiz3.pass",
    "english.prea1.taipei.mrt.quiz3.pass",
    "english.prea1.taipei.park.quiz3.pass",
    "english.prea1.taipei.zoo",
]

# The gated territories and what each requires. FIXED ON PURPOSE: this is world-data's side of the
# same contract, so a change here must be a conscious product decision, not a test refresh.
GATED_TERRITORIES = {
    "taipei:daan": ["english.prea1.taipei.zoo"],
    "taipei:songshan": ["english.prea1.taipei.park.quiz3.pass"],
    "taipei:xinyi": ["english.prea1.taipei.mrt.quiz3.pass"],
    "taipei:zhongshan": ["english.prea1.taipei.market.quiz3.pass", "english.prea1.taipei.zoo"],
    "taipei:zhongzheng": ["english.prea1.taipei.market.quiz3.pass"],
}

# The one activity-scope policy that pays, and the lesson-scope policies mastery grants. Naming the
# POLICY (not the members) is what makes these derivations migration-proof.
GATE_POLICY = "standard_activity_pass"
MASTERY_POLICIES = ["lesson_mastery_badge", "lesson_mastery_gold"]

# The four Taipei lessons — the original campaign. Named where a test is specifically about THEM
# (v2 policies, seven activities, Zoo's retired v1) rather than about the population as a whole.
TAIPEI4 = sorted("english.prea1.taipei." + s for s in ("market", "mrt", "park", "zoo"))


def declared_gates(reg):
    """Activities that DECLARE the paying policy. The population, derived."""
    return sorted(a for a in reg.activities if reg.reward_policy_of(a) == GATE_POLICY)


def completable_lessons(reg):
    """Lessons that declare a usable completion policy. The population, derived."""
    return sorted(lid for lid in reg.lessons if reg.completion_available(lid))


def qualification_bearing(reg):
    """Activities that grant at least one qualification. Derived; today a subset of the gates."""
    return sorted(a for a in reg.activities if reg.qualification_ids_for(a))


def curriculum_gates(reg):
    """Paying gates that grant NO qualification — ordinary CEFR curriculum (Phase 9B onward)."""
    return sorted(a for a in declared_gates(reg) if not reg.qualification_ids_for(a))


def assert_completion_model(reg, pass_mark=80):
    """Every completable lesson is well-formed; every other lesson declares no policy at all.

    This replaces "the completable lessons are exactly these four ids". Comparing a test's own
    `completion_available` scan against an identical helper scan would be vacuous, so instead assert
    the PROPERTY each member must satisfy — which a hardcoded id list never checked:

      * the policy type is one the engine actually implements
      * the pass mark is the single global threshold (no per-lesson difficulty drift)
      * requiredActivityIds is non-empty, deduped, and every id is a REGISTERED activity of THAT
        lesson (a policy requiring a foreign or missing activity can never be satisfied)
      * a lesson with no policy advertises no completion, so it can never be "completed by default"
    """
    import learning.completion as C
    for lid in reg.lessons:
        pol = reg.completion_policy_of(lid)
        if not reg.completion_available(lid):
            assert not pol or pol.get("type") not in C.POLICY_TYPES, (lid, pol)
            continue
        assert pol["type"] in C.POLICY_TYPES, (lid, pol)
        assert pol.get("passMark", pass_mark) == pass_mark, (lid, pol)
        assert isinstance(pol.get("version"), int) and pol["version"] >= 1, (lid, pol)
        req = pol.get("requiredActivityIds") or []
        assert req, (lid, "a completable lesson must require at least one activity")
        assert len(req) == len(set(req)), (lid, req)
        for aid in req:
            assert aid in reg.activities, (lid, aid, "policy requires an unregistered activity")
            assert reg.activities[aid].get("lessonId") == lid, (lid, aid, "foreign activity")


def assert_reward_model(reg, svc, pass_gold):
    """The reward invariants, over whatever population the registry currently declares.

    Stronger than the censuses this replaces: these hold for any future set of lessons, so migrating
    curriculum cannot quietly change WHAT paying means — only how many things pay.
    """
    gates = declared_gates(reg)
    paying = sorted(a for a in reg.activities if reg.reward_policy_of(a) == "standard_activity_pass")
    # 1. paying == declaring. Nothing pays without naming the policy, and naming it always pays.
    assert paying == gates, (paying, gates)
    # 2. every gate resolves the ONE shared policy to the SAME descriptor -- no per-lesson amounts.
    #    Phase 14A.10B: with PASS_GOLD 0 that descriptor is the inert one, because a pass now earns a
    #    REWARD GAME instead of gold. The shape is still asserted from the caller's `pass_gold`, so
    #    this holds whatever the amount is.
    expect = ({"type": "gold", "amount": pass_gold, "itemId": None, "once": True} if pass_gold > 0
              else {"type": "none", "amount": 0, "itemId": None, "once": True})
    for aid in gates:
        assert svc.reward_for(aid) == expect, (aid, svc.reward_for(aid))
    # 3. every non-gate activity declares no gate policy...
    for aid in reg.activities:
        if aid not in gates:
            assert reg.reward_policy_of(aid) != "standard_activity_pass", aid
    # 3b. ...and NO activity may declare a policy that is not valid at activity scope. Phase
    #     14A.10B: this is the guard that used to be carried by "a gate pays PASS_GOLD" -- with
    #     PASS_GOLD 0 an amount can no longer tell a mis-scoped policy from a gate one, but the
    #     policy's own declared scopes still can. A lesson-scope policy (lesson_mastery_gold) on an
    #     ACTIVITY would pay lesson money for one pass, and must be rejected.
    from learning import rewards as _rewards
    for aid in reg.activities:
        pid = reg.reward_policy_of(aid)
        spec = _rewards.POLICIES.get(pid)
        assert spec is not None, (aid, pid)
        assert "activity" in spec["scopes"], (aid, pid, spec["scopes"])
    # 4. a paying gate must belong to a lesson that can actually be completed — a gate on a
    #    non-completable lesson would pay for progress toward nothing
    completable = set(completable_lessons(reg))
    for aid in gates:
        lid = reg.activities[aid].get("lessonId")
        assert lid in completable, (aid, lid)
    # 5. every completable lesson grants the cosmetic badge and at most ONE economic mastery reward
    import learning.rewards as W
    for lid in completable:
        pols = reg.lesson_reward_policies_of(lid)
        assert pols == MASTERY_POLICIES, (lid, pols)
        assert len([p for p in pols if W.is_economic(p)]) == 1, (lid, pols)
        # a lesson never issues a qualification itself; only an activity does
        assert reg.lesson_qualification_ids_for(lid) == [], lid
    # 6. THE WORLD CONTRACT: qualifications are exactly the four Conquest ones, and only the Taipei
    #    gates grant them. A migrated curriculum lesson may pay, but must never mint a world unlock.
    assert sorted(reg.qualifications) == CONQUEST_QUALIFICATIONS, sorted(reg.qualifications)
    assert qualification_bearing(reg) == sorted(l + ".quiz3" for l in TAIPEI4), \
        qualification_bearing(reg)
    granted = sorted({q for a in reg.activities for q in reg.qualification_ids_for(a)})
    assert granted == CONQUEST_QUALIFICATIONS, granted
    return gates, sorted(completable)
