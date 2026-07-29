"""Centralized gameplay configuration — the single authoritative source of balance constants.

All values are copied VERBATIM from the pre-Phase-2A implementation (server.py + index.html).
The only conflict resolved (per developer decision) is defense-tech: standardized to the
frontend/canonical +10% per level (the backend AI previously used +8%). No other rebalancing.
"""

# --- economy ---
GOLD_RATE = 0.10
GROW_SECONDS = 3600
ECON_MAX_CATCHUP = 72
ECON_START_POP = 100
ECON_START_TROOPS = 100
PASS_GOLD = 10000
DEFEND_GOLD = 50
ATTACK_FAIL_GOLD = 50

# --- army / units (all four share base atk 10 / def 8; only counters differ) ---
TROOP_KINDS = ("cav", "archer", "inf", "spear")
UNIT_ATK = 10
UNIT_DEF = 8

# --- recruitment ---
UNIT_COST = {"inf": 2, "spear": 3, "archer": 4, "cav": 5}
RECRUIT_BATCH = 10
UNIT_BUILDING = {"inf": "barracks", "spear": "barracks", "archer": "archery", "cav": "stable"}
BUILD_COST = {"armory": 50, "barracks": 60, "archery": 80, "stable": 120}

# --- technology ---
TECH_COST = {"atk": [80, 160, 280], "def": [80, 160, 280]}
TECH_MAX = 3
TECH_ATK_PER_LEVEL = 0.10   # forging: attack multiplier bonus per level
TECH_DEF_PER_LEVEL = 0.10   # armor: canonical +10%/level (was 0.08 on the old AI path)

# --- battle (canonical = frontend runBattle semantics) ---
DMG_SCALE = 12
BATTLE_ROUND_CAP = 16
# counter matrices (identical FE/BE): attacker at vs defender df
_ATK_COUNTERS = {("spear", "cav"): 1.2, ("cav", "archer"): 1.1, ("archer", "spear"): 1.2, ("archer", "inf"): 1.2}
_DEF_COUNTERS = {("cav", "archer"): 1.1}


def atk_bonus(at, df):
    return _ATK_COUNTERS.get((at, df), 1.0)


def def_bonus(df, at):
    return _DEF_COUNTERS.get((df, at), 1.0)


def tech_atk(tech):
    return TECH_ATK_PER_LEVEL * ((tech or {}).get("atk", 0) or 0)


def tech_def(tech):
    return TECH_DEF_PER_LEVEL * ((tech or {}).get("def", 0) or 0)


def fingerprint():
    """Stable hash of the balance constants — proves no accidental change across refactors."""
    import hashlib
    import json
    payload = {
        "GOLD_RATE": GOLD_RATE, "GROW_SECONDS": GROW_SECONDS, "ECON_MAX_CATCHUP": ECON_MAX_CATCHUP,
        "PASS_GOLD": PASS_GOLD, "DEFEND_GOLD": DEFEND_GOLD, "ATTACK_FAIL_GOLD": ATTACK_FAIL_GOLD,
        "UNIT_ATK": UNIT_ATK, "UNIT_DEF": UNIT_DEF, "UNIT_COST": UNIT_COST, "RECRUIT_BATCH": RECRUIT_BATCH,
        "UNIT_BUILDING": UNIT_BUILDING, "BUILD_COST": BUILD_COST,
        "TECH_COST": TECH_COST, "TECH_MAX": TECH_MAX,
        "TECH_ATK_PER_LEVEL": TECH_ATK_PER_LEVEL, "TECH_DEF_PER_LEVEL": TECH_DEF_PER_LEVEL,
        "DMG_SCALE": DMG_SCALE, "BATTLE_ROUND_CAP": BATTLE_ROUND_CAP,
        "ATK_COUNTERS": sorted(("%s>%s" % k, v) for k, v in _ATK_COUNTERS.items()),
        "DEF_COUNTERS": sorted(("%s>%s" % k, v) for k, v in _DEF_COUNTERS.items()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
