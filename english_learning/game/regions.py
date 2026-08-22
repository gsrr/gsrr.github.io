"""Strategic regions — aggregation over the Phase 13B frontier classification (Phase 13C).

Phase 13B answered "is THIS territory exposed?". This answers the question a player with 47
territories actually asks:

    "WHERE is my empire under pressure?"

without making them inspect dozens of territories one at a time.

WHAT A REGION IS, IN THIS PHASE
    an AGGREGATION / MANAGEMENT VIEW over stable geography, and nothing else.

WHAT A REGION IS NOT (deliberately, and asserted by test)
    not an ownership unit      not a combat unit      not an income unit
    not a supply unit          not a technology unit  not a building unit
    not an army unit

Nothing here is consulted by can_attack, claim, release, re-entry, recruit, research, build, income,
rewards, the AI or anything in learning/. Promoting regions into gameplay authority is a later,
separately reviewed phase.

TWO ORTHOGONAL CONCEPTS, KEPT ORTHOGONAL
    region_of(territory)                       stable geography, from the catalog. Never ownership.
    classify(territory, player, ...)           dynamic strategic state, from game/frontier.py.

Membership is *geography*, so it does not move when the map changes hands; the counts are *state*, so
they do. Deriving region membership from ownership -- or from frontier/interior -- would collapse the
two and make "where am I under pressure?" unanswerable, because the grouping would move with the
answer.

MEMBERSHIP SOURCE
    world-data/territories/<map>.json -> metadata.continent

Measured at the time of writing: a complete, single-valued partition of all 250 world territories into
6 groups, with no duplicates and none unassigned. (The catalog carried 244 of 250 until Phase 13C wrote
in the six values the client's WORLD_CONTINENTS table had already shipped since Phase 10C -- see
docs/strategic-regions.md. Those six are all zero-adjacency islands and no connectivity was created.)

Nothing is stored. Region membership is read from the catalog; the counts are derived per request from
ownership, exactly like the 13B classification they are built on.
"""

from . import frontier as _frontier

# Display names live with the data they name, so a caller never has to invent one. The keys are the
# catalog's own `metadata.continent` values.
REGION_LABELS = {
    "af": "Africa",
    "as": "Asia",
    "eu": "Europe",
    "na": "N. America",
    "oc": "Oceania",
    "sa": "S. America",
}
UNASSIGNED = "unassigned"


def region_of(territory_id, meta_of):
    """The stable region a territory belongs to, or None. `meta_of(tid)` returns that territory's
    catalog record. Geography only -- ownership is never consulted."""
    rec = meta_of(territory_id) or {}
    c = ((rec.get("metadata") or {}) if isinstance(rec, dict) else {}).get("continent")
    return c or None


def membership(territory_ids, meta_of):
    """{territoryId: region} for every territory that has one. A territory with no continent is
    omitted rather than guessed at; `audit()` is how a caller finds out that happened."""
    out = {}
    for tid in territory_ids or ():
        r = region_of(tid, meta_of)
        if r:
            out[tid] = r
    return out


def audit(territory_ids, meta_of):
    """Completeness of the partition, so a gap is reported rather than silently absorbed.
    Returns {"total", "assigned", "unassigned": [...], "regions": {region: count}}."""
    ids = list(territory_ids or ())
    regions, unassigned = {}, []
    for tid in ids:
        r = region_of(tid, meta_of)
        if r:
            regions[r] = regions.get(r, 0) + 1
        else:
            unassigned.append(tid)
    return {"total": len(ids), "assigned": len(ids) - len(unassigned),
            "unassigned": sorted(unassigned), "regions": regions}


def summarize(territory_ids, player, owner_of, neighbours_of, meta_of):
    """The canonical aggregation: one row per region that contains at least one territory.

    Every number below is derived from AUTHORITATIVE ownership plus the ONE canonical classifier in
    game/frontier.py -- this module never re-implements the frontier rule, and never invents a figure
    that ownership does not directly supply.

        region     the catalog's continent key
        label      its display name
        total      territories in the region, on this map        (geography: constant)
        owned      territories in it that `player` owns          (state)
        frontier   of those, classified frontier by 13B          (state)
        interior   of those, classified interior by 13B          (state)
        isolated   of those, classified isolated by 13B          (state)
        neutral    territories in it with no owner at all        (state, directly from ownership)
        others     territories in it owned by somebody else      (state, directly from ownership)

    Deliberately ABSENT, because the data does not support them and inventing them would be a lie:
    threat score, danger score, pressure percentage, supply strength, development level, region level,
    or any "control" figure with gameplay meaning. `owned` / `total` is a display fraction, nothing
    more.

    `others` is a COUNT ONLY. It is derivable from ownership the client can already see (the board
    shows every territory's owner), so it leaks nothing new -- and it deliberately does not say WHO,
    HOW MANY DIFFERENT rivals, or anything at all about their strength or garrisons.
    """
    rows = {}
    for tid in territory_ids or ():
        r = region_of(tid, meta_of)
        if not r:
            continue
        row = rows.get(r)
        if row is None:
            row = rows[r] = {"region": r, "label": REGION_LABELS.get(r, r), "total": 0,
                             "owned": 0, "frontier": 0, "interior": 0, "isolated": 0,
                             "neutral": 0, "others": 0}
        row["total"] += 1
        owner = owner_of(tid)
        if not owner:
            row["neutral"] += 1
            continue
        if player and owner == player:
            row["owned"] += 1
            cls = _frontier.classify(tid, player, owner_of, neighbours_of)
            if cls in row:
                row[cls] += 1
        else:
            row["others"] += 1
    # a stable, meaningful order: most exposed first, then most owned, then alphabetical -- so the
    # region a player should look at is the one at the top, and the order does not jitter.
    return sorted(rows.values(),
                  key=lambda r: (-r["frontier"], -r["owned"], r["label"]))


def structural_note(region_rows):
    """Factual counts only, for the closed-component caveat Phase 13B surfaced.

    13B proved that `interior` means "every land neighbour is mine" -- NOT "connected to a useful
    front", and NOT "safe supply". This reports how many owned territories are isolated, so a caller
    can state that fact, and says nothing whatsoever about connectivity, supply or support: modelling
    that is a later phase's job and this phase must not imply it exists.
    """
    return {"isolatedOwned": sum(r["isolated"] for r in region_rows or ())}


__all__ = ["REGION_LABELS", "UNASSIGNED", "region_of", "membership", "audit", "summarize",
           "structural_note"]
