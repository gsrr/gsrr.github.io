#!/usr/bin/env python3
"""Phase 2A — Game Domain unit tests (army / economy / recruitment / technology) +
config parity with server.py (proves the extraction changed no balance value).

    python3 tests/game_domain_test.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from game import config, army, economy, recruitment, technology  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ================= config parity with the live server.py constants =================
import server  # noqa: E402
assert config.GOLD_RATE == server.GOLD_RATE
assert config.PASS_GOLD == server.PASS_GOLD and config.DEFEND_GOLD == server.DEFEND_GOLD
assert config.ATTACK_FAIL_GOLD == server.ATTACK_FAIL_GOLD and config.GROW_SECONDS == server.GROW_SECONDS
assert config.ECON_MAX_CATCHUP == server.ECON_MAX_CATCHUP
assert config.UNIT_COST == server.UNIT_COST and config.RECRUIT_BATCH == server.RECRUIT_BATCH
assert config.UNIT_BUILDING == server.UNIT_BUILDING and config.BUILD_COST == server.BUILD_COST
assert config.TECH_COST == server.TECH_COST and config.TECH_MAX == server.TECH_MAX
assert tuple(config.TROOP_KINDS) == tuple(server.TROOP_KINDS)
ok("game.config matches server.py constants (no balance drift)")

# ================= army =================
assert army.normalize_pool({}) == {"cav": 0, "archer": 0, "inf": 0, "spear": 0}
assert army.normalize_pool(10) == {"cav": 2, "archer": 2, "inf": 4, "spear": 2}   # remainder→inf, mirrors _norm_troops
assert army.pool_total(10) == 10
assert army.normalize_pool({"cav": 3, "archer": 1}) == {"cav": 3, "archer": 1, "inf": 0, "spear": 0}
p = army.pool_add({"inf": 5}, "inf", 3); assert p["inf"] == 8
p2, okk = army.pool_sub({"inf": 5}, "inf", 3); assert okk and p2["inf"] == 2
p3, okk3 = army.pool_sub({"inf": 2}, "inf", 5); assert okk3 is False and p3["inf"] == 2   # too many → reject
p4 = army.pool_add({"inf": 5}, "dragon", 3); assert p4 == army.normalize_pool({"inf": 5})   # invalid unit ignored
assert army.pool_add({}, "cav", -5)["cav"] == 0                                              # negative clamped
g = [{"type": "inf", "hp": 10}, {"type": "cav", "hp": 0}, {"type": "bad", "hp": 5}]
assert army.alive_garrison(g) == [{"type": "inf", "hp": 10}] and army.garrison_total(g) == 10
assert army.merge_into_garrison([{"type": "inf", "hp": 10}], "inf", 5) == [{"type": "inf", "hp": 15}]
ok("army: normalize/total/add/sub(reject too-many)/invalid-unit/negative/garrison/merge")

# ================= economy =================
assert economy.calculate_passive_gold(0, 0, 0, 0, 3600) == (0, 3600)          # zero pop → 0 gold, clock advances
assert economy.calculate_passive_gold(0, 100, 0, 0, 3600) == (10, 3600)        # round(100*0.10)=10
assert economy.calculate_passive_gold(0, 100, 50, 0, 3600) == (15, 3600)       # (100+50)*0.10=15
assert economy.calculate_passive_gold(0, 100, 0, 0, 0) == (0, 0)               # zero elapsed → no change
assert economy.calculate_passive_gold(0, 100, 0, 0, 3 * 3600) == (30, 3 * 3600)  # 3 intervals
# repeated settlement doesn't double count
g1, l1 = economy.calculate_passive_gold(0, 100, 0, 0, 3600)
g2, l2 = economy.calculate_passive_gold(g1, 100, 0, l1, 3600)                   # same 'now' → no extra
assert g2 == g1 and l2 == l1
# catch-up cap
gcap, _ = economy.calculate_passive_gold(0, 100, 0, 0, 1000 * 3600)
assert gcap == config.ECON_MAX_CATCHUP * 10
ok("economy: zero/normal/region/zero-elapsed/multi-interval/no-double-count/catch-up cap")

# ================= recruitment =================
assert recruitment.unit_cost("cav", 10) == 50 and recruitment.unit_cost("inf", 10) == 20
assert recruitment.can_recruit("inf", 10, 20, True) == (True, 20, None)         # exact gold
assert recruitment.can_recruit("archer", 10, 39, True)[0] is False              # insufficient (needs 40)
assert recruitment.can_recruit("cav", 10, 50, True)[0] is True
assert recruitment.can_recruit("dragon", 5, 999, True)[0] is False              # invalid unit
assert recruitment.can_recruit("inf", 10, 999, True, owns_territory=False)[2] == "not_your_region"
assert recruitment.can_recruit("inf", 10, 999, False)[2] == "need_barracks"     # missing building
# client cannot override cost: cost is derived from config regardless of any client value
assert recruitment.can_recruit("cav", 10, 50, True)[1] == 10 * config.UNIT_COST["cav"]
ok("recruitment: costs/exact/insufficient/invalid-unit/ownership/building/cost-authoritative")

# ================= technology =================
assert technology.next_cost("atk", 0) == 80 and technology.next_cost("atk", 1) == 160 and technology.next_cost("atk", 2) == 280
assert technology.next_cost("atk", 3) is None                                   # maxed
assert technology.can_research("atk", 0, 80) == (True, 80, 1, None)
assert technology.can_research("atk", 0, 79)[0] is False                        # insufficient
assert technology.can_research("def", 3, 9999)[3] == "maxed"
assert technology.can_research("magic", 0, 999)[3] == "unknown_tech"
assert technology.can_research("atk", 0, 999, has_armory=False)[3] == "need_armory"
ok("technology: costs/success/insufficient/max/invalid/armory")

print("\nAll %d game-domain tests passed. config fingerprint = %s" % (passed, config.fingerprint()))
