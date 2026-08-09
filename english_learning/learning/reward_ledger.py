"""The learner's reward ledger — PURE (no I/O, no HTTP, no content knowledge).

Gold has always had somewhere to go (the economy). Cosmetic, profile and gameplay rewards did not,
so Phase 5E gives every reward a single append-only home:

    learning.rewardLedger[grantKey] = {policyId, rewardType, scope, sourceId,
                                       amount, itemId, grantedAt}

`grantKey` is `"<scope>:<sourceId>:<policyId>"`. It is derived, never client-supplied, and it is what
makes a `once` reward idempotent: the same lesson finishing twice, a retry, a replayed request or a
second settlement all resolve to the same key and the second write is refused.

Design notes:

  * append-only. An entry is never rewritten or re-dated, exactly like lessonCompletions — a reward
    is a historical fact.
  * the ledger records what was GRANTED, including gold. Gold is additionally applied to the economy
    by the caller, but the ledger is the audit trail of why the balance moved.
  * a corrupt or hand-edited ledger reads as "nothing granted" rather than raising, so a damaged
    progress file can never crash a lesson — and can never fabricate ownership either.

CORRUPTION POLICY — see docs/reward-framework.md §8. Since Phase 5F this ledger IS the idempotency
gate for the two live COSMETIC rewards, so "corruption reads as empty" does mean "corruption permits
a re-grant". That was decided and accepted for cosmetics: the worst case is re-earning a badge and
seeing the banner twice, and nothing cosmetic can be spent, traded or fought with. Gold is still NOT
gated here — `standard_activity_pass` keeps its historical per-activity `rewarded` flag, so a wiped
ledger cannot re-pay it.

SAFETY BOUNDARY: this read FAILS OPEN, and that is accepted for cosmetics ONLY. It must not be
applied automatically to gold, profile or gameplay rewards. Before activating any non-cosmetic
ledger-backed reward, a fail-closed or recoverable corruption policy has to be defined and
implemented first — refuse to grant while the ledger is unreadable, or rebuild it from durable
recovery data. Activating such a reward on top of today's fail-open read is a defect.
"""

LEDGER_KEY = "rewardLedger"


def grant_key(scope, source_id, policy_id):
    return "%s:%s:%s" % (scope, source_id, policy_id)


def _table(state):
    t = (state or {}).get(LEDGER_KEY)
    return t if isinstance(t, dict) else None


def get_grant(state, scope, source_id, policy_id):
    """The recorded grant, or None. Malformed entries count as absent."""
    t = _table(state)
    if t is None:
        return None
    rec = t.get(grant_key(scope, source_id, policy_id))
    return rec if isinstance(rec, dict) else None


def has_grant(state, scope, source_id, policy_id):
    return get_grant(state, scope, source_id, policy_id) is not None


def record_grant(state, scope, source_id, policy_id, reward, now):
    """Append one grant. Returns (state, newly_recorded).

    `reward` is a resolved descriptor from rewards.resolve(). A `once` policy already present is a
    no-op returning False — the caller uses that to decide whether to pay out. Nothing is ever
    overwritten, so a replay cannot re-date or double a grant.
    """
    if not isinstance(state, dict):
        state = {}
    if not scope or not source_id or not policy_id or not isinstance(reward, dict):
        return state, False
    if reward.get("type") == "none":
        return state, False                       # inert policy: nothing to record
    key = grant_key(scope, source_id, policy_id)
    table = state.get(LEDGER_KEY)
    if table is None:
        table = {}
        state[LEDGER_KEY] = table
    if not isinstance(table, dict):
        # Phase 7C.1: a clobbered ledger is evidence. Replacing it would destroy the only trace of
        # what went wrong and would silently reset every "already granted" answer it held. Refuse
        # the write and leave it exactly as found.
        return state, False
    if key in table and isinstance(table[key], dict):
        return state, False                       # already granted -> never re-granted, never re-dated
    table[key] = {"policyId": policy_id, "rewardType": reward.get("type"), "scope": scope,
                  "sourceId": source_id, "amount": int(reward.get("amount") or 0),
                  "itemId": reward.get("itemId"), "grantedAt": now}
    return state, True


def is_corrupt(state):
    """True when the ledger cannot be trusted to answer "was this already granted?".

    The tolerant reads below normalise a damaged ledger to empty, which Phase 5F accepted for
    COSMETIC rewards because a duplicate badge is inert. An economic grant may not use that answer:
    "unreadable" must never resolve to "unpaid". Phase 7C.1.
    """
    table = (state or {}).get(LEDGER_KEY)
    if table is None:
        return False
    if not isinstance(table, dict):
        return True
    for k, e in table.items():
        if not isinstance(k, str) or not isinstance(e, dict):
            return True
        if not isinstance(e.get("policyId"), str) or not isinstance(e.get("scope"), str):
            return True
        if not isinstance(e.get("rewardType"), str):
            return True
        if isinstance(e.get("amount"), bool) or not isinstance(e.get("amount"), int):
            return True
    return False


def entries(state):
    """Every well-formed ledger entry, ordered by grantedAt then key. Junk is dropped, not trusted."""
    t = _table(state)
    if not t:
        return []
    out = []
    for key, rec in t.items():
        if not isinstance(rec, dict) or not isinstance(rec.get("policyId"), str):
            continue
        at = rec.get("grantedAt")
        out.append({"grantKey": key, "policyId": rec["policyId"],
                    "rewardType": rec.get("rewardType"), "scope": rec.get("scope"),
                    "sourceId": rec.get("sourceId"),
                    "amount": rec["amount"] if isinstance(rec.get("amount"), int) else 0,
                    "itemId": rec.get("itemId"),
                    "grantedAt": at if isinstance(at, int) and not isinstance(at, bool) else None})
    out.sort(key=lambda e: (e["grantedAt"] if e["grantedAt"] is not None else 0, e["grantKey"]))
    return out


def owned_items(state):
    """Item ids the learner owns, deduped and sorted. Gold grants carry no item and are excluded."""
    return sorted({e["itemId"] for e in entries(state) if e.get("itemId")})


def total_granted(state, reward_type):
    """Sum of `amount` across grants of one type — the audit trail for gold actually paid out."""
    return sum(e["amount"] for e in entries(state) if e.get("rewardType") == reward_type)
