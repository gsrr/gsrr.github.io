"""Recruitment domain: authoritative cost + eligibility (backend). Pure decision; the HTTP
handler performs gold deduction + army mutation. Client cannot override cost."""
from . import config
from .army import clampi


def unit_cost(unit, qty):
    return clampi(qty) * config.UNIT_COST[unit]


def building_for(unit):
    return config.UNIT_BUILDING.get(unit)


def can_recruit(unit, qty, gold, has_building, owns_territory=True):
    """Return (ok, cost, reason). Mirrors _handle_territory_recruit validation."""
    if unit not in config.UNIT_COST:
        return False, 0, "unknown_unit"
    q = clampi(qty, 1, 100000)
    if not owns_territory:
        return False, 0, "not_your_region"
    if not has_building:
        return False, 0, "need_" + config.UNIT_BUILDING[unit]
    cost = q * config.UNIT_COST[unit]
    if clampi(gold) < cost:
        return False, cost, "not_enough_gold"
    return True, cost, None
