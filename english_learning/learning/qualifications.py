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
    quals = _dict_slot(state, "qualifications")
    if quals is None:
        return state, False              # corrupt container: refuse the write, preserve the evidence
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
# Phase 7C.1: reads come in two flavours.
#   * the tolerant read (get_completion) keeps its historical behaviour — malformed means "no
#     evidence" — because display and grading must never crash on a damaged file;
#   * the STRICT read (completion_state) distinguishes ABSENT from CORRUPT, and is what anything
#     that mints economic value must use. "We cannot tell whether this was paid" is not the same
#     answer as "this was never paid".
VALID_PRESENT, VALID_ABSENT, CORRUPT = "valid_present", "valid_absent", "corrupt"


def _is_wellformed_completion(rec):
    """A completion record written by record_completion(): all three fields, correct types.

    record_completion() is the ONLY writer and has always written passedAt, pct and a bool
    `rewarded` together (Phase 3A wrote the same shape under a legacy key). A dict missing
    `rewarded`, or carrying a non-bool, therefore never came from this system and cannot be used to
    decide whether money was already paid.
    """
    return (isinstance(rec, dict)
            and isinstance(rec.get("rewarded"), bool)
            and not isinstance(rec.get("passedAt"), bool)
            and isinstance(rec.get("passedAt"), int)
            and not isinstance(rec.get("pct"), bool)
            and isinstance(rec.get("pct"), int))


def completion_state(state, key):
    """(status, record) for ONE key. See VALID_PRESENT / VALID_ABSENT / CORRUPT."""
    table = (state or {}).get("activityCompletions")
    if table is None:
        return VALID_ABSENT, None
    if not isinstance(table, dict):
        return CORRUPT, None                       # the whole table was clobbered
    if key not in table:
        return VALID_ABSENT, None
    rec = table[key]
    return (VALID_PRESENT, rec) if _is_wellformed_completion(rec) else (CORRUPT, None)


def completions_state(state, keys):
    """Fold the strict read across canonical + legacy aliases.

    CORRUPT anywhere wins: if any alias for this activity is unreadable we cannot prove the reward
    was not already paid through it, so the answer is "uncertain", never "unpaid".
    """
    status = VALID_ABSENT
    for k in (keys or []):
        s, _ = completion_state(state, k)
        if s == CORRUPT:
            return CORRUPT
        if s == VALID_PRESENT:
            status = VALID_PRESENT
    return status


def _dict_slot(state, key):
    """The dict stored at `key`, creating it when absent.

    Returns None when the slot holds something that is NOT a dict. Phase 7C.1: a clobbered container
    must neither crash the writer nor be silently replaced — replacing it would destroy the very
    evidence an operator needs, and crashing would turn a damaged file into a denial of service.
    The caller skips the write and the damaged bytes stay exactly where they are.
    """
    cur = state.get(key)
    if cur is None:
        cur = {}
        state[key] = cur
    return cur if isinstance(cur, dict) else None


def get_completion(state, key):
    table = (state or {}).get("activityCompletions")
    rec = table.get(key) if isinstance(table, dict) else None
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
    acts = _dict_slot(state, "activityCompletions")
    if acts is None:
        return None                      # corrupt container: refuse the write, preserve the evidence
    prior = acts.get(key)
    if prior is not None and not _is_wellformed_completion(prior):
        # Phase 7C.1: a malformed record is the ONLY evidence that something went wrong here.
        # Overwriting it would erase that evidence AND silently convert an unpayable state into a
        # payable one on the next attempt. Refuse the write; the settlement already refused the gold.
        return None
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
    table = _dict_slot(state, "activityScores")
    if table is None:
        return None                      # corrupt container: refuse the write, preserve the evidence
    table[activity_id] = {"correct": int(correct), "total": int(total), "pct": int(pct),
                          "updatedAt": now}
    return table[activity_id]
