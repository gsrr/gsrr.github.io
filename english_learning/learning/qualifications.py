"""Player learning state — server-authoritative, content-independent, PURE (no I/O).

Operates on a plain "learning state" dict:

    { "activityCompletions": { "<activityId>": {passedAt, pct, rewarded} },
      "qualifications":      { "<qualificationId>": {earnedAt} } }

Phase 3B keeps the Phase 3A shape and adds many-to-many grants. Higher-level blocks
(lessonCompletions / unitCompletions / courseCompletions) are intentionally NOT created: §8 says do
not create empty persistence blocks, and §7 says do not claim a completion the server cannot prove.

Game Domain depends only on these small operations + opaque qualification IDs — never on what a
qualification teaches. Qualification is PLAYER state: independent of territory ownership, army and
room, so a player who loses every territory keeps their qualifications.
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
    """Idempotent grant. Returns (state, granted_now). A repeat leaves the original earnedAt intact."""
    if not isinstance(state, dict):
        state = {}
    quals = state.setdefault("qualifications", {})
    if not qid or qid in quals:
        return state, False
    quals[qid] = {"earnedAt": earned_at}
    return state, True


def grant_qualifications(state, qids, earned_at):
    """Grant several at once (one activity may certify more than one). Returns (state, newly_granted).

    Order of `qids` is preserved in the returned list; duplicates within the input are collapsed.
    """
    newly = []
    for qid in (qids or []):
        state, now = grant_qualification(state, qid, earned_at)
        if now:
            newly.append(qid)
    return state, newly


# ---- activity completion records -------------------------------------------------------------
def get_completion(state, key):
    rec = ((state or {}).get("activityCompletions") or {}).get(key)
    return rec if isinstance(rec, dict) else None


def merge_completions(state, keys):
    """Fold the records at `keys` (canonical first, then legacy aliases) into one logical record.

    Phase 3A wrote `"<contentPath>#<activity>"`; Phase 3B writes the canonical activityId. Reading
    through BOTH is what makes the migration non-destructive: `passedAt` is the earliest known pass
    and `rewarded` is true if ANY alias was already paid, so nobody is paid twice and nobody loses
    credit for work done before Phase 3B.
    """
    recs = [r for r in (get_completion(state, k) for k in (keys or [])) if r]
    if not recs:
        return None
    passed_ats = [r["passedAt"] for r in recs if isinstance(r.get("passedAt"), int)]
    pcts = [r["pct"] for r in recs if isinstance(r.get("pct"), int)]
    return {"passedAt": min(passed_ats) if passed_ats else None,
            "pct": max(pcts) if pcts else 0,
            "rewarded": any(bool(r.get("rewarded")) for r in recs)}


def record_completion(state, key, passed_at, pct, rewarded):
    """Write/refresh one activity-completion record. Returns the stored record."""
    if not isinstance(state, dict):
        state = {}
    acts = state.setdefault("activityCompletions", {})
    acts[key] = {"passedAt": passed_at, "pct": pct, "rewarded": bool(rewarded)}
    return acts[key]


# ---- authoritative latest SCORE evidence (Phase 3F) --------------------------------------------
# Deliberately separate from activityCompletions:
#   activityScores      = the latest authoritative score, whether the attempt passed or not
#   activityCompletions = the authoritative "this activity was passed" record (never written on fail)
# Legacy recordScore() is latest-wins, so this store is latest-wins too — a worse retry lowers the
# score while leaving the earlier completion (and its one-time reward) untouched.
def get_activity_score(state, activity_id):
    table = (state or {}).get("activityScores")
    if not isinstance(table, dict):
        return None                      # malformed stored state -> no evidence, never a crash
    rec = table.get(activity_id)
    return rec if isinstance(rec, dict) else None


def record_activity_score(state, activity_id, correct, total, pct, now):
    """Latest-wins. Keeps exact correct/total so Rule A can average unrounded percentages."""
    if not isinstance(state, dict):
        state = {}
    table = state.setdefault("activityScores", {})
    table[activity_id] = {"correct": int(correct), "total": int(total), "pct": int(pct),
                          "updatedAt": now}
    return table[activity_id]
