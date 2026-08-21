"""Frontier / interior / isolated classification — the ONE canonical definition (Phase 13B).

Phase 13A's recommendation was that the strategic game should be about a front line rather than about
every owned territory, so that management stops growing linearly with conquest. This module is the
first foundation of that: it answers, for one player, what role each of their territories plays.

    frontier  the territory borders at least one territory that player does not own
    interior  every land neighbour is owned by that same player
    isolated  the territory has no land neighbours at all

It is a PURE function of two authoritative facts the game already owns:

    ownership   territory.json[territoryId]["owner"]      (per room, terr_lock)
    adjacency   catalog adjacentTerritoryIds              (static world-data)

Nothing here is stored. There is deliberately no `frontier: true` field in any persistence, because a
stored classification would be wrong the instant a neighbour changed hands, and combat changes
neighbours. Deriving it costs one pass over the player's own territories (measured: ~0.1 ms for a
250-territory world), which is cheaper than the bugs a cache would buy.

WHY THIS LIVES IN game/ RATHER THAN IN THE CLIENT
Phase 13A's roadmap has later phases where this becomes gameplay authority: interior territory
generates supply (13E) and field armies are hosted at the frontier (13D). A classification that will
decide legality must be decided by the server, and there must be exactly ONE definition of it — a
second copy in JavaScript would drift, and the two would disagree about who is exposed. The client
therefore READS this result and never recomputes it.

PHASE 13B HAS NO GAMEPLAY EFFECT. Nothing in this module is consulted by can_attack, claim,
recruitment, research, building, income, rewards, re-entry or the AI. It is strategic structure and
presentation only, so that the foundation can be validated before anything is balanced on top of it.
"""

FRONTIER = "frontier"
INTERIOR = "interior"
ISOLATED = "isolated"
CLASSES = (FRONTIER, INTERIOR, ISOLATED)


def classify(territory_id, player, owner_of, neighbours_of):
    """The canonical classifier. Returns FRONTIER / INTERIOR / ISOLATED, or None when `player` does
    not own `territory_id` — classification is meaningful only relative to an owner, because
    "borders someone else" has no meaning without a "me".

    `owner_of(tid)`      -> the owning player id, or None/"" for a neutral territory.
    `neighbours_of(tid)` -> the canonical adjacency list for that territory.

    ISOLATED is tested FIRST and is a property of the MAP, not of ownership: a territory with no land
    neighbours can never be attacked over land and can never attack out, whoever holds it. The plain
    rule would call it interior (it has no un-owned neighbour), which would be true and useless --
    "safe" and "structurally unable to participate" are different facts and the player needs the
    second one. See docs/frontier-interior-design.md.
    """
    if not player:
        return None
    if _norm(owner_of(territory_id)) != _norm(player):
        return None
    nbrs = neighbours_of(territory_id) or ()
    if not nbrs:
        return ISOLATED
    me = _norm(player)
    for n in nbrs:
        if _norm(owner_of(n)) != me:      # neutral OR another player OR an AI: all "not mine"
            return FRONTIER
    return INTERIOR


def classify_all(player, territory_ids, owner_of, neighbours_of):
    """{territoryId: class} for every territory in `territory_ids` that `player` owns."""
    out = {}
    for tid in territory_ids or ():
        c = classify(tid, player, owner_of, neighbours_of)
        if c:
            out[tid] = c
    return out


def summarize(classes):
    """Authoritative counts for the strategic overview. `total` is the number of territories the
    player holds, which is by construction frontier + interior + isolated."""
    counts = {c: 0 for c in CLASSES}
    for c in (classes or {}).values():
        if c in counts:
            counts[c] += 1
    counts["total"] = sum(counts[c] for c in CLASSES)
    return counts


def _norm(owner):
    """Ownership comparison is exact on the stored id, with None/"" meaning neutral. Deliberately not
    case-folded: the territory store and token_user() both use the account id verbatim, and inventing
    a looser comparison here would let two spellings of one name disagree about who owns what."""
    return owner if owner else None


__all__ = ["FRONTIER", "INTERIOR", "ISOLATED", "CLASSES", "classify", "classify_all", "summarize"]
