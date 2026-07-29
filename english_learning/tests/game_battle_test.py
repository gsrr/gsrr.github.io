#!/usr/bin/env python3
"""Phase 2A — battle engine: equivalence with the JS reference (golden master) + unit checks.

    python3 tests/game_battle_test.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from game import battle, config  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ---- js_round matches JavaScript Math.round (half toward +inf), unlike Python round() ----
assert battle.js_round(2.5) == 3 and battle.js_round(3.5) == 4 and battle.js_round(-2.5) == -2
assert round(2.5) == 2  # (sanity: Python banker's rounding would have broken parity)
ok("js_round replicates JS Math.round (half-up)")

# ---- empty / undefended handling ----
r = battle.resolve_battle([{"type": "inf", "hp": 10}], [])
assert r["attackerWon"] and r["undefended"] and r["attackerSurvivors"] == [{"type": "inf", "hp": 10}]
r0 = battle.resolve_battle([], [{"type": "inf", "hp": 10}])
assert r0["attackerWon"] is False
ok("empty/undefended armies handled")

# ---- deterministic: same inputs -> identical result ----
a = [{"type": "cav", "hp": 40}, {"type": "archer", "hp": 30}]
d = [{"type": "inf", "hp": 45}, {"type": "spear", "hp": 25}]
r1 = battle.resolve_battle(a, d, 0.1, 0.0, 0.0, 0.2)
r2 = battle.resolve_battle(a, d, 0.1, 0.0, 0.0, 0.2)
assert r1 == r2
ok("resolve_battle is deterministic given inputs (RNG is caller-injected order)")

# ---- GOLDEN-MASTER equivalence with JS battleResolve ----
gold = json.load(open(os.path.join(ROOT, "tests", "fixtures", "battle_golden.json"), encoding="utf-8"))
for c in gold["cases"]:
    r = battle.resolve_battle(
        [{"type": u["type"], "hp": u["hp"]} for u in c["att"]],
        [{"type": u["type"], "hp": u["hp"]} for u in c["def"]],
        config.tech_atk(c["atkTech"]), config.tech_def(c["atkTech"]),
        config.tech_atk(c["defTech"]), config.tech_def(c["defTech"]),
    )
    assert r["attackerWon"] == c["attackerWon"], (c["name"], "winner", r["attackerWon"], c["attackerWon"])
    assert r["attackerSurvivors"] == c["attackerSurvivors"], (c["name"], "attSurv", r["attackerSurvivors"], c["attackerSurvivors"])
    assert r["defenderSurvivors"] == c["defenderSurvivors"], (c["name"], "defSurv", r["defenderSurvivors"], c["defenderSurvivors"])
ok("Python engine matches JS golden master on all %d cases (winner + casualties + survivors)" % len(gold["cases"]))

# ---- counter / tech representative behavior (from the golden set) ----
byname = {c["name"]: c for c in gold["cases"]}
assert byname["spear_vs_cav"]["attackerWon"] is True          # spear counters cavalry
assert byname["inf_vs_inf"]["attackerWon"] is False           # mirror match → defender first-strike holds
assert byname["atk_tech3"]["attackerWon"] is True             # attack tech flips the mirror match
assert byname["def_tech3"]["attackerWon"] is False
ok("counter + technology effects behave as in the reference implementation")

print("\nAll %d battle tests passed. config fingerprint = %s" % (passed, config.fingerprint()))
