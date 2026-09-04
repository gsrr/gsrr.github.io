"""Reward-game ENTITLEMENTS on the learner's state — PURE (no I/O, no HTTP, no economy).

Phase 14A.10B. A legitimate FIRST pass of a gate activity earns exactly one reward game. This
module owns that entitlement's whole life:

    learning.rewardGames[activityId] = {game, status, prizeId, createdAt, resolvedAt}

Design, and why:

  * THE KEY IS THE ACTIVITY ID. It is the same identity the completion record already uses, it is
    server-derived, and it is naturally one-per-activity-forever -- so "a replay must not earn a
    second game" needs no counter, no client id and no extra guard. A create for an id that is
    already present is refused.
  * THE GAME IS CHOSEN AT CREATION and stored. A refresh, a re-login or a server restart therefore
    reveals the SAME mini-game; nothing rerolls.
  * RESOLUTION IS A ONE-WAY TRANSITION guarded by `status`. resolve() returns (state, prize_id,
    newly) and refuses to move an already-resolved entitlement, so a double click, a retried POST,
    two tabs or a restart mid-animation all end at one prize -- and a repeat request can still be
    answered with the SAME prizeId it already has.
  * PRIZES ARE OPAQUE HERE. This module stores a prize ID and never learns what it pays; sizing
    gold and troops belongs to game/reward_games.py. Learning decides that a reward was earned;
    Game decides what a reward is worth. That separation is the reason this file has no import of
    the game domain.
  * A CORRUPT table reads as "no entitlements" rather than raising, exactly like the reward ledger,
    and (unlike cosmetics) a corrupt table cannot MINT one either: creation writes only into a dict
    it can read back.
"""

KEY = "rewardGames"
PENDING = "pending"        # no prize drawn yet
AWARDED = "awarded"        # a prize is DRAWN and PERSISTED; the payout may not have landed yet
RESOLVED = "resolved"      # the payout has been confirmed applied by the economy

# Phase 14A.10B correction: `awarded` exists because the entitlement and the economy are two
# separate JSON documents. Drawing writes the prize FIRST; only then is the economy asked to apply
# it, idempotently, keyed by this entitlement's id. A crash between the two therefore leaves an
# `awarded` record whose prize is already fixed -- a retry pays THAT prize, never a new one.


def _table(state):
    t = (state or {}).get(KEY)
    return t if isinstance(t, dict) else None


def get(state, entitlement_id):
    """One entitlement, or None. A malformed record counts as absent."""
    t = _table(state)
    if t is None or not entitlement_id:
        return None
    rec = t.get(entitlement_id)
    return rec if isinstance(rec, dict) and rec.get("game") else None


def create(state, entitlement_id, game, now):
    """Record ONE pending entitlement. Returns (state, record_or_None).

    None means nothing was created -- the id already has one. Never overwrites, never re-dates,
    never rerolls the assigned game.
    """
    if not isinstance(state, dict):
        state = {}
    if not entitlement_id or not game:
        return state, None
    table = state.get(KEY)
    if not isinstance(table, dict):
        table = {}
        state[KEY] = table
    if isinstance(table.get(entitlement_id), dict) and table[entitlement_id].get("game"):
        return state, None                       # already earned: a replay adds nothing
    rec = {"game": game, "status": PENDING, "prizeId": None,
           "createdAt": int(now or 0), "resolvedAt": None}
    table[entitlement_id] = rec
    return state, dict(rec, id=entitlement_id)


def award(state, entitlement_id, prize_id, now):
    """Fix this entitlement's prize. Returns (state, prize_id, newly_drawn).

    THE ONE PLACE A PRIZE IS EVER WRITTEN. If a prize is already stored it is returned with
    newly=False and the caller must NOT draw again -- that is what makes "the prize never changes"
    true across retries, restarts and concurrent requests. `prize_id` is only consulted when
    nothing is stored yet, so a caller that drew speculatively simply discards its draw.
    """
    rec = get(state, entitlement_id)
    if rec is None:
        return state, None, False
    if rec.get("prizeId"):
        return state, rec["prizeId"], False
    if not prize_id:
        return state, None, False
    rec["prizeId"] = prize_id
    rec["status"] = AWARDED
    rec["awardedAt"] = int(now or 0)
    return state, prize_id, True


def mark_paid(state, entitlement_id, now):
    """Record that the economy confirmed the payout. Reporting only: the AUTHORITY for "already
    paid" is the economy record's own payment marker, which is written in the same file as the
    balance it moved. Never changes a prize."""
    rec = get(state, entitlement_id)
    if rec is None or not rec.get("prizeId"):
        return state, False
    if rec.get("status") == RESOLVED:
        return state, False
    rec["status"] = RESOLVED
    rec["resolvedAt"] = int(now or 0)
    return state, True


def pending(state):
    """Every entitlement whose payout is not confirmed, OLDEST FIRST (id as a stable tie-break).

    All of them: a learner who passes three gates before playing any of them keeps three, and
    claiming one never discards the others. An `awarded` record still counts as owed, so a crash
    between the draw and the payout leaves the player something to come back to -- and coming back
    pays the prize that was already drawn.
    """
    t = _table(state)
    if t is None:
        return []
    out = []
    for eid, rec in t.items():
        if isinstance(rec, dict) and rec.get("game") and rec.get("status") != RESOLVED:
            out.append({"id": eid, "game": rec["game"], "createdAt": int(rec.get("createdAt") or 0)})
    out.sort(key=lambda r: (r["createdAt"], r["id"]))
    return out


def resolved(state):
    """Every resolved entitlement with its prize id — the audit trail, oldest first."""
    t = _table(state)
    if t is None:
        return []
    out = []
    for eid, rec in t.items():
        if isinstance(rec, dict) and rec.get("game") and rec.get("status") == RESOLVED:
            out.append({"id": eid, "game": rec["game"], "prizeId": rec.get("prizeId"),
                        "resolvedAt": int(rec.get("resolvedAt") or 0)})
    out.sort(key=lambda r: (r["resolvedAt"], r["id"]))
    return out
