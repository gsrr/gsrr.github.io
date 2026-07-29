"""Army domain: the three+one existing unit kinds. Parsing/serialization/validation only —
no UI, no new units. Mirrors server.py's _norm_troops / garrison behavior exactly."""
from . import config


def clampi(v, lo=0, hi=100000000):
    try:
        v = int(round(float(v)))
    except Exception:
        v = 0
    return max(lo, min(hi, v))


def normalize_pool(v):
    """Free-pool army {cav,archer,inf,spear}. Legacy int -> even 4-way split (remainder to inf)."""
    if isinstance(v, dict):
        return {k: clampi(v.get(k, 0)) for k in config.TROOP_KINDS}
    n = clampi(v)
    per = n // 4
    d = {k: per for k in config.TROOP_KINDS}
    d["inf"] += n - per * 4
    return d


def pool_total(pool):
    p = normalize_pool(pool)
    return sum(p[k] for k in config.TROOP_KINDS)


def pool_add(pool, unit, qty):
    p = normalize_pool(pool)
    if unit in config.TROOP_KINDS:
        p[unit] = clampi(p[unit] + clampi(qty))
    return p


def pool_sub(pool, unit, qty):
    """Subtract; returns (new_pool, ok). ok=False (no change) if insufficient — matches 'reject' behavior."""
    p = normalize_pool(pool)
    if unit not in config.TROOP_KINDS or clampi(qty) > p.get(unit, 0):
        return p, False
    p[unit] -= clampi(qty)
    return p, True


def alive_garrison(troops):
    """Garrison list [{type,hp}] -> only valid kinds with hp>0."""
    out = []
    for t in (troops or []):
        if isinstance(t, dict) and t.get("type") in config.TROOP_KINDS and clampi(t.get("hp", 0)) > 0:
            out.append({"type": t["type"], "hp": clampi(t["hp"])})
    return out


def garrison_total(troops):
    return sum(u["hp"] for u in alive_garrison(troops))


def merge_into_garrison(troops, unit, qty):
    """Add qty of unit into a garrison list, merging same type (matches recruit behavior)."""
    troops = [dict(t) for t in (troops or [])]
    slot = next((t for t in troops if isinstance(t, dict) and t.get("type") == unit), None)
    if slot:
        slot["hp"] = clampi(slot.get("hp", 0)) + clampi(qty)
    else:
        troops.append({"type": unit, "hp": clampi(qty)})
    return troops
