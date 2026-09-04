"""Centralized gameplay configuration — the single authoritative source of balance constants.

All values are copied VERBATIM from the pre-Phase-2A implementation (server.py + index.html).
The only conflict resolved (per developer decision) is defense-tech: standardized to the
frontend/canonical +10% per level (the backend AI previously used +8%). No other rebalancing.
"""

# --- economy ---
# Phase 14A.10A: PASSIVE POPULATION INCOME IS DAILY, NOT HOURLY.
#
# 10% of (home base + owned territory) population per HOUR made simply leaving a server running the
# strongest strategy in the game: the 14A.10 audit measured one normal AI reaching ~2,700 troops by
# room-hour 50 and ~14,300 by room-hour 120, entirely from legitimately paid-for recruitment, with
# no troop minting anywhere. The same rate now pays once per DAY, so the passive economy is slow
# background growth and LEARNING is the strong active earner (see PASS_GOLD / MASTERY_GOLD below).
#
# The names carry their unit on purpose. This module's period is the PASSIVE-INCOME period only;
# conscription keeps its own hourly period in server.py, and the two must never be confused again.
GOLD_RATE = 0.10                 # of population, per PASSIVE_PERIOD_SECONDS
PASSIVE_PERIOD_SECONDS = 86400   # one day of elapsed wall-clock time (not a calendar date)
PASSIVE_MAX_CATCHUP_DAYS = 3     # at most three daily payouts are settled after a long absence
ECON_START_POP = 100
ECON_START_TROOPS = 100
# Phase 7C.2: study payouts are split between the gate and full mastery. Passing the gate proves
# eligibility and pays an acknowledgement; completing the whole unit pays the substantial reward.
# Phase 14A.10A raised both (160/640 -> 500/2500) so that STUDY, not idling, is how a player funds
# an army, against 15 gold a day for a starting home base. Phase 14A.10B then moved the GATE half
# out of gold entirely: a first pass earns a reward game paying 3000 gold or 400-670 troops, so the
# gate reward became bigger and more of an event, while mastery keeps paying its 2500 directly.
# Deliberately neutral names: this module knows economic amounts, never what is being studied.
# Phase 14A.10B: PASSING A GATE NO LONGER PAYS GOLD DIRECTLY -- it earns ONE REWARD GAME
# (game/reward_games.py), whose prize table is worth 3000-6000. PASS_GOLD is therefore 0, which
# makes `standard_activity_pass` resolve INERT through rewards.resolve() rather than paying a
# second, hidden reward on top of the game. It is kept as a named constant, not deleted, because
# the reward policy still names its amountKey and the fingerprint still pins it.
PASS_GOLD = 0                    # gate task passed -> a reward game, not gold
MASTERY_GOLD = 2500              # whole unit mastered, once ever
DEFEND_GOLD = 50
ATTACK_FAIL_GOLD = 50

# ---- Phase 10B: zero-territory re-entry ----------------------------------------------------------
# A player holding no territory on a fully-claimed map has no legal conquest action at all: a claim
# answers `held`, and an attack needs an owned source. Re-entry is the bounded exception.
#
# REENTRY_GOLD_COST is a LEVY, not a purchase: it buys no troops (the foothold force is debited from
# the player's existing pool, so troops still only ever move) and pays no reward. 120 is ~8 hours of
# a home base's passive income (population 150 x GOLD_RATE 0.10 = 15/day), so being wiped out stings
# and is still recoverable without any second economy.
#
# DELIBERATELY OUTSIDE fingerprint(): that hash is an explicit allowlist of the constants that decide
# BATTLE and REWARD outcomes, and its value is pinned by the migration tests. Re-entry changes
# neither, so adding it to the payload would churn a published fingerprint for nothing. It is pinned
# by tests/reentry_authority_test.py instead.
REENTRY_GOLD_COST = 120
REENTRY_CANDIDATES = 4            # how many footholds the server offers; small enough to reason about
REENTRY_FAIR_POOL = 0.25          # candidates are sampled from the weakest quartile by defence

# --- army / units (all four share base atk 10 / def 8; only counters differ) ---
TROOP_KINDS = ("cav", "archer", "inf", "spear")
UNIT_ATK = 10
UNIT_DEF = 8

# --- recruitment ---
# Phase 8B.2: unit prices tripled. Until Phase 8B.1 a client could mint troops for free, so these
# numbers priced nothing and were never load-bearing. With provisioning server-authoritative they
# became the army's real cost — and at 2-5 gold they barely bit: a fresh 500 bought 220 infantry,
# and the full campaign bought 1,850. Tripling makes an army a genuine competing sink against
# technology without making a starting garrison unaffordable (barracks + 50 infantry = 360 < 500).
UNIT_COST = {"inf": 6, "spear": 9, "archer": 12, "cav": 15}
RECRUIT_BATCH = 10
UNIT_BUILDING = {"inf": "barracks", "spear": "barracks", "archer": "archery", "cav": "stable"}
# Buildings are deliberately UNCHANGED: they are one-off prerequisites that gate access rather than
# an ongoing sink, and taxing entry was not the measured problem.
BUILD_COST = {"armory": 50, "barracks": 60, "archery": 80, "stable": 120}

# --- technology ---
# Phase 8B.2: tech doubled. It is the deepest strategic axis, and one full study unit's payout (800,
# so 1300 with the starting purse) used to max BOTH lines outright (armory + 1040). Doubling makes
# that payout fund ONE full line (armory + 1040 = 1090) and leaves the second line as a real later
# decision. A pleasant consequence: PASS_GOLD (160) is now exactly one level-1 upgrade.
TECH_COST = {"atk": [160, 320, 560], "def": [160, 320, 560]}
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
        "GOLD_RATE": GOLD_RATE, "PASSIVE_PERIOD_SECONDS": PASSIVE_PERIOD_SECONDS,
        "PASSIVE_MAX_CATCHUP_DAYS": PASSIVE_MAX_CATCHUP_DAYS,
        "PASS_GOLD": PASS_GOLD, "MASTERY_GOLD": MASTERY_GOLD,
        "DEFEND_GOLD": DEFEND_GOLD, "ATTACK_FAIL_GOLD": ATTACK_FAIL_GOLD,
        "UNIT_ATK": UNIT_ATK, "UNIT_DEF": UNIT_DEF, "UNIT_COST": UNIT_COST, "RECRUIT_BATCH": RECRUIT_BATCH,
        "UNIT_BUILDING": UNIT_BUILDING, "BUILD_COST": BUILD_COST,
        "TECH_COST": TECH_COST, "TECH_MAX": TECH_MAX,
        "TECH_ATK_PER_LEVEL": TECH_ATK_PER_LEVEL, "TECH_DEF_PER_LEVEL": TECH_DEF_PER_LEVEL,
        "DMG_SCALE": DMG_SCALE, "BATTLE_ROUND_CAP": BATTLE_ROUND_CAP,
        "ATK_COUNTERS": sorted(("%s>%s" % k, v) for k, v in _ATK_COUNTERS.items()),
        "DEF_COUNTERS": sorted(("%s>%s" % k, v) for k, v in _DEF_COUNTERS.items()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
