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
    """Eligibility for ALICE attacking `target` while holding `held` qualifications."""
    state = {}
    for q in held:
        state, _ = Q.grant_qualification(state, q, 1)
    return conquest.can_attack("ALICE", "m:home", target, SQUAD, W, STORE,
                               player_qualifications=Q.earned_qualification_ids(state))


# ---------------- §35 the requirement matrix ----------------
e = can("m:a")
assert e.allowed and e.reason is None and e.missing_qualifications == [], "A: zero requirements"
assert can("m:a", [Q1, Q2, Q3]).allowed, "A stays open however much you have learned"

e = can("m:b")
assert not e and e.reason == "qualification_required" and e.missing_qualifications == [Q1]
assert can("m:b", [Q1]).allowed, "B: allowed with exactly its requirement"
assert can("m:b", [Q2, Q3]).missing_qualifications == [Q1], "unrelated qualifications do not help"

e = can("m:c")
assert e.missing_qualifications == [Q1, Q2], "C: missing BOTH, reported in requirement order"
assert can("m:c", [Q1]).missing_qualifications == [Q2], "C: missing exactly one"
assert can("m:c", [Q2]).missing_qualifications == [Q1]
assert can("m:c", [Q1, Q2]).allowed, "C: ALL satisfied"
assert can("m:c", [Q1, Q2, Q3]).allowed, "extra qualifications never hurt"
assert not can("m:c", [Q1, Q3]).allowed, "ALL semantics: no OR groups in Phase 3B"

e = can("m:e")
assert e.missing_qualifications == [Q2, Q1, Q3], "declaration order is preserved verbatim in the report"
assert can("m:e", [Q1, Q3]).missing_qualifications == [Q2]
assert can("m:e", [Q1, Q2, Q3]).allowed
ok("§35 matrix: 0 requirements open; 1 and 2+ gate with exact missingQualificationIds; ALL semantics")

# ---------------- §36 many-to-many ----------------
# one qualification unlocks MULTIPLE territories
assert can("m:b", [Q1]).allowed and can("m:d", [Q1]).allowed, "Q1 unlocks both B and D"
assert not can("m:b").allowed and not can("m:d").allowed
# ...and it also partially satisfies a multi-requirement territory
assert can("m:c", [Q1]).missing_qualifications == [Q2]
# one territory requires MULTIPLE qualifications (already shown for C/E); and one activity may grant
# several qualifications — proven at the registry/service layer in tests/learning_domain_test.py.
state = {}
state, newly = Q.grant_qualifications(state, [Q1, Q3], 1)          # one activity -> two qualifications
assert newly == [Q1, Q3]
held = Q.earned_qualification_ids(state)
assert conquest.can_attack("ALICE", "m:home", "m:b", SQUAD, W, STORE, player_qualifications=held).allowed
assert conquest.can_attack("ALICE", "m:home", "m:d", SQUAD, W, STORE, player_qualifications=held).allowed
assert conquest.can_attack("ALICE", "m:home", "m:e", SQUAD, W, STORE,
                           player_qualifications=held).missing_qualifications == [Q2]
ok("§36 many-to-many: one qualification unlocks several territories; one activity grants several")

# duplicated requirement ids on a territory must not double-report
REQS["m:b"] = [Q1, Q1]
assert can("m:b").missing_qualifications == [Q1], "a duplicated requirement is reported once"
assert can("m:b", [Q1]).allowed
REQS["m:b"] = [Q1]
# junk in the requirement list is ignored rather than crashing the attack path
REQS["m:d"] = [Q1, "", None]
assert can("m:d", [Q1]).allowed, "empty/None requirement entries are not treated as unmet gates"
REQS["m:d"] = [Q1]
ok("requirement hygiene: duplicate ids collapse, empty/None entries never block or crash")

# the gate is player state only — it must not consult territory ownership, army or room
assert can("m:c", [Q1, Q2]).allowed
STORE["m:c"]["troops"] = [{"type": "spear", "hp": 9999}]      # a scarier defender is not a gate concern
assert can("m:c", [Q1, Q2]).allowed
STORE["m:c"]["troops"] = [{"type": "inf", "hp": 3}]
ok("gate purity: qualification eligibility is player state, independent of garrison strength")


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

# can_attack's contract stays machine-readable: a stable reason + opaque ids, never display text
e = can("m:c")
assert e.reason == "qualification_required" and e.reason in conquest.AttackEligibility.REASONS
assert e.missing_qualifications == [Q1, Q2], "raw ids, not titles — the UI resolves display names"
assert all(isinstance(q, str) for q in e.missing_qualifications)
assert "—" not in repr(e) and "Zoo" not in repr(e), "no human-readable course text leaks into the domain"
assert not can("m:c").allowed and bool(can("m:c", [Q1, Q2])) is True, "AttackEligibility stays truthy/falsy"
ok("§17 boundary: can_attack returns a stable reason + opaque ids only, never display strings")

print("\nAll %d learning-requirement tests passed." % passed)
