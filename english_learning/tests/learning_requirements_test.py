#!/usr/bin/env python3
"""Phase 3B — territory requirement model: ALL semantics, many-to-many, Game-Domain independence.

    python3 tests/learning_requirements_test.py

§35 the 0 / 1 / 2-requirement matrix, §36 many-to-many (one qualification unlocking several
territories and one territory needing several qualifications), §20 a regression test proving the
Game Domain contains no content vocabulary at all.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from game import conquest  # noqa: E402
from learning import qualifications as Q  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# A synthetic world. Requirement ids are deliberately from three DIFFERENT subjects, none of them
# English, to make any subject-specific branch in the Game Domain impossible to hide.
Q1, Q2, Q3 = "biology.cell.unit03", "maths.fractions.u1", "history.meiji.u2"
ADJ = {"m:home": ("m:a", "m:b", "m:c", "m:d", "m:e"),
       "m:a": ("m:home",), "m:b": ("m:home",), "m:c": ("m:home",), "m:d": ("m:home",), "m:e": ("m:home",)}
REQS = {
    "m:a": [],                # A: no requirements            -> plain Phase 2B behaviour
    "m:b": [Q1],              # B: one requirement
    "m:c": [Q1, Q2],          # C: two requirements (ALL)
    "m:d": [Q1],              # D: SAME requirement as B      -> one qualification, many territories
    "m:e": [Q2, Q1, Q3],      # E: three, declared out of order
}


class World:
    def is_canonical(self, tid):
        return tid in ADJ

    def map_of(self, tid):
        return "m" if tid in ADJ else None

    def are_adjacent(self, a, b):
        return b in ADJ.get(a, ())

    def attack_requirements(self, tid):
        return list(REQS.get(tid, []))


W = World()
STORE = {"m:home": {"owner": "ALICE", "troops": [{"type": "cav", "hp": 100}]}}
for t in ("m:a", "m:b", "m:c", "m:d", "m:e"):
    STORE[t] = {"owner": "BOB", "troops": [{"type": "inf", "hp": 3}]}
SQUAD = [{"type": "cav", "hp": 10}]


def can(target, held=()):
    """Conquest eligibility for ALICE attacking `target` while holding `held` qualifications.
    Phase 10A.3R: learning qualifications are NOT consulted here any more, so this is used below to
    prove `held` cannot change the verdict."""
    state = {}
    for q in held:
        state, _ = Q.grant_qualification(state, q, 1)
    return conquest.can_attack("ALICE", "m:home", target, SQUAD, W, STORE,
                               player_qualifications=Q.earned_qualification_ids(state))


def missing(target, held=()):
    """Which of `target`'s declared requirement ids the player does NOT hold.

    Phase 10A.3R: this resolver survives as LEARNING metadata — it answers "what does this territory
    still ask of me?" for reporting/UI — but it is no longer wired into Conquest authority. The
    matrix below therefore still pins its full semantics (ALL-required, declaration order preserved,
    duplicates collapsed, junk ignored, ids opaque); what it no longer claims is that any of it
    decides an attack."""
    state = {}
    for q in held:
        state, _ = Q.grant_qualification(state, q, 1)
    return conquest.missing_qualifications(W, target, Q.earned_qualification_ids(state))


# ---------------- §35 the requirement matrix ----------------
# RETARGETED (Phase 10A.3R). OLD: this matrix asserted that requirements GATED an attack —
# `can(...)` returned qualification_required with the exact missing ids until all were held.
# WHY OBSOLETE: Conquest no longer reads requirements or player qualifications at all.
# NEW: the identical matrix is asserted against the RESOLVER, which still answers "what does this
# territory still ask of me?" for Learning reporting — every semantic the old form protected
# (0 requirements, 1, 2+, ALL-required with no OR groups, verbatim declaration order, unrelated ids
# not helping, extras harmless) is preserved verbatim. WHY NOT WEAKER: nothing was dropped, and the
# zero-Conquest-effect block below adds a guarantee the old form could not state.
assert missing("m:a") == [], "A: zero requirements"
assert missing("m:a", [Q1, Q2, Q3]) == [], "A stays open however much you have learned"

assert missing("m:b") == [Q1]
assert missing("m:b", [Q1]) == [], "B: satisfied with exactly its requirement"
assert missing("m:b", [Q2, Q3]) == [Q1], "unrelated qualifications do not help"

assert missing("m:c") == [Q1, Q2], "C: missing BOTH, reported in requirement order"
assert missing("m:c", [Q1]) == [Q2], "C: missing exactly one"
assert missing("m:c", [Q2]) == [Q1]
assert missing("m:c", [Q1, Q2]) == [], "C: ALL satisfied"
assert missing("m:c", [Q1, Q2, Q3]) == [], "extra qualifications never hurt"
assert missing("m:c", [Q1, Q3]) == [Q2], "ALL semantics: no OR groups"

assert missing("m:e") == [Q2, Q1, Q3], "declaration order is preserved verbatim in the report"
assert missing("m:e", [Q1, Q3]) == [Q2]
assert missing("m:e", [Q1, Q2, Q3]) == []
ok("§35 requirement matrix (Learning metadata): 0 requirements empty; 1 and 2+ report the exact "
   "missing ids in declaration order; ALL semantics, extras harmless, unrelated ids do not help")

# ---------------- Phase 10A.3R: and NONE of it touches Conquest ----------------
SETS = [(), (Q1,), (Q2, Q3), (Q1, Q2), (Q1, Q2, Q3), (Q1, "forged.not.a.real.id")]
for target in ("m:a", "m:b", "m:c", "m:d", "m:e"):
    verdicts = {(can(target, h).allowed, can(target, h).reason) for h in SETS}
    assert len(verdicts) == 1, (target, verdicts)
assert "qualification_required" not in conquest.AttackEligibility.REASONS
ok("zero Conquest effect: for every requirement shape (none/one/several/all/forged) the attack "
   "verdict is IDENTICAL, and qualification_required is not a possible reason")

# ---------------- §36 many-to-many ----------------
# one qualification satisfies MULTIPLE territories' requirement lists
assert missing("m:b", [Q1]) == [] and missing("m:d", [Q1]) == [], "Q1 satisfies both B and D"
assert missing("m:b") == [Q1] and missing("m:d") == [Q1]
# ...and it also partially satisfies a multi-requirement territory
assert missing("m:c", [Q1]) == [Q2]
# one territory requires MULTIPLE qualifications (already shown for C/E); and one activity may grant
# several qualifications — proven at the registry/service layer in tests/learning_domain_test.py.
state = {}
state, newly = Q.grant_qualifications(state, [Q1, Q3], 1)          # one activity -> two qualifications
assert newly == [Q1, Q3]
held = Q.earned_qualification_ids(state)
assert conquest.missing_qualifications(W, "m:b", held) == []
assert conquest.missing_qualifications(W, "m:d", held) == []
assert conquest.missing_qualifications(W, "m:e", held) == [Q2]
ok("§36 many-to-many: one qualification satisfies several territories' requirement lists; one "
   "activity grants several qualifications")

# duplicated requirement ids on a territory must not double-report
REQS["m:b"] = [Q1, Q1]
assert missing("m:b") == [Q1], "a duplicated requirement is reported once"
assert missing("m:b", [Q1]) == []
REQS["m:b"] = [Q1]
# junk in the requirement list is ignored rather than crashing the resolver
REQS["m:d"] = [Q1, "", None]
assert missing("m:d", [Q1]) == [], "empty/None requirement entries are never reported as unmet"
REQS["m:d"] = [Q1]
ok("requirement hygiene: duplicate ids collapse, empty/None entries never block or crash")

# the gate is player state only — it must not consult territory ownership, army or room
assert missing("m:c", [Q1, Q2]) == []
STORE["m:c"]["troops"] = [{"type": "spear", "hp": 9999}]   # garrison is not a requirement concern
assert missing("m:c", [Q1, Q2]) == []
STORE["m:c"]["troops"] = [{"type": "inf", "hp": 3}]
ok("resolver purity: what a territory still asks of a player is player state only, independent of "
   "garrison strength")


# ---------------- §20 Game Domain content-independence regression ----------------
GAME_DIR = os.path.join(ROOT, "game")
FORBIDDEN = ("english", "zoo", "pre-a1", "prea1", "quiz", "lesson", "taipei", "vocab", "cloze",
             "grammar", "course", "activity", "subject", "biology", "maths", "history", "japanese")
offences = []
for name in sorted(os.listdir(GAME_DIR)):
    if not name.endswith(".py"):
        continue
    text = open(os.path.join(GAME_DIR, name), encoding="utf-8").read().lower()
    for word in FORBIDDEN:
        if re.search(r"\b" + re.escape(word), text):
            offences.append("%s: %r" % (name, word))
assert not offences, "Game Domain must contain no learning-content vocabulary: %s" % offences
# ...not even via imports
for name in sorted(os.listdir(GAME_DIR)):
    if name.endswith(".py"):
        text = open(os.path.join(GAME_DIR, name), encoding="utf-8").read()
        assert "import learning" not in text and "from learning" not in text, \
            "%s must not import the Learning Domain" % name
ok("§20 regression: game/*.py contains no content vocabulary and never imports the Learning Domain")

# Both boundaries stay machine-readable: stable reasons on the Game side, opaque ids on the
# Learning side, never display text. RETARGETED (Phase 10A.3R): the truthy/falsy probe used to
# swing `can_attack` with a qualification; it now swings it with a GAME fact (adjacency), which is
# what the assertion was really about — that AttackEligibility is usable in a boolean context.
ids = missing("m:c")
assert ids == [Q1, Q2], "raw ids, not titles — the UI resolves display names"
assert all(isinstance(q, str) for q in ids)
assert "qualification_required" not in conquest.AttackEligibility.REASONS

# Phase 14A: a NON-ADJACENT attack is allowed now, so the falsy-eligibility example has to be a
# rule that still refuses. Source ownership is the natural one -- it is structural, non-geographic,
# and it is what this assertion was really about: that AttackEligibility works in a boolean context.
e_bad = conquest.can_attack("ALICE", "m:a", "m:b", SQUAD, W, STORE)   # m:a is BOB's
assert not e_bad and e_bad.allowed is False and e_bad.reason == "source_not_owned", e_bad.reason
# and the geography that used to refuse it no longer does: whatever this fixture's far pair fails
# on now, it is NOT distance.
STORE["m:a"]["owner"] = "ALICE"
e_far = conquest.can_attack("ALICE", "m:a", "m:b", SQUAD, W, STORE)
STORE["m:a"]["owner"] = "BOB"
assert e_far.reason != "not_adjacent", "Alpha rule: distance no longer refuses an attack"
e_good = can("m:c")
assert bool(e_good) is True and e_good.reason is None
assert "—" not in repr(e_bad) and "Zoo" not in repr(e_bad),     "no human-readable content text leaks into the domain"
ok("§17 boundary: can_attack returns a stable reason only and stays truthy/falsy; the requirement "
   "resolver returns opaque ids only — neither leaks display strings")

print("\nAll %d learning-requirement tests passed." % passed)
