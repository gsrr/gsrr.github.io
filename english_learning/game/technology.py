"""Technology domain: authoritative research cost + eligibility (backend). Pure decision.
Definitions/config separate from a player's/territory's current levels. Client cannot override."""
from . import config
from .army import clampi

TRACKS = ("atk", "def")


def next_cost(track, level):
    lvl = clampi(level)
    if track not in config.TECH_COST or lvl >= config.TECH_MAX:
        return None
    return config.TECH_COST[track][lvl]


def can_research(track, level, gold, has_armory=True):
    """Return (ok, cost, next_level, reason). Mirrors _handle_territory_research."""
    if track not in config.TECH_COST:
        return False, 0, None, "unknown_tech"
    if not has_armory:
        return False, 0, None, "need_armory"
    lvl = clampi(level)
    if lvl >= config.TECH_MAX:
        return False, 0, None, "maxed"
    cost = config.TECH_COST[track][lvl]
    if clampi(gold) < cost:
        return False, cost, lvl + 1, "not_enough_gold"
    return True, cost, lvl + 1, None
