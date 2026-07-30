"""Player qualification state — server-authoritative, content-independent, PURE (no I/O).

Operates on a plain "learning state" dict of the shape:

    { "activityCompletions": { "<lessonId>#<activity>": {passedAt, pct, rewarded} },
      "qualifications":      { "<qualificationId>": {earnedAt} } }

Game Domain depends only on these small operations + opaque qualification IDs — never on what a
qualification teaches. Qualification is PLAYER state: it is independent of territory ownership, army,
and room state, so a player who loses every territory keeps their qualifications (future revival).
"""


def _quals(state):
    return (state or {}).get("qualifications") or {}


def has_qualification(state, qid):
    return bool(qid) and qid in _quals(state)


def has_all_qualifications(state, qids):
    return all(has_qualification(state, q) for q in (qids or []))


def missing_qualifications(state, qids):
    """Ordered list of the required ids the player does NOT hold (dedup, order preserved)."""
    out, seen = [], set()
    for q in (qids or []):
        if q and q not in seen and not has_qualification(state, q):
            out.append(q)
            seen.add(q)
    return out


def earned_qualification_ids(state):
    return set(_quals(state).keys())


def grant_qualification(state, qid, earned_at):
    """Idempotent grant. Returns (state, granted_now: bool). Mutates & returns state for caller
    persistence; a repeated grant leaves the original earnedAt untouched and returns granted_now=False."""
    if not isinstance(state, dict):
        state = {}
    quals = state.setdefault("qualifications", {})
    if qid in quals:
        return state, False
    quals[qid] = {"earnedAt": earned_at}
    return state, True
