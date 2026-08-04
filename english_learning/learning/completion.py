"""Authoritative whole-lesson completion — PURE (no I/O, no HTTP, no content knowledge).

Phase 3D ships the MACHINERY only. No production lesson carries an active `completionPolicy`, because
two levels that contribute to the current whole-lesson rule have no server-authoritative evidence:

    Level 2 Read Along  — /api/stt returns a transcript only; the score is computed in the browser,
                          with a "completion = full marks" fallback when no backend is reachable.
    Level 5 Match       — score is firstTry/n, a function of click history (Phase 3C category B).

Until both are authoritative, declaring a real lesson "complete" from the server-verified subset alone
would be a DIFFERENT and easier rule than the one learners see today. So:

    a lesson with no completionPolicy is NOT completable — it is never "complete", and the evaluator
    never falls back to client scores, legacy green state or passcnt.

See docs/lesson-completion.md for the full inventory and the decision record.
"""
import math

POLICY_TYPES = ("all_required_activities", "average_required_activities")
PASS_MARK = 80          # the authoritative global threshold (index.html PASS_MARK); see pass_mark_of()
DEFAULT_VERSION = 1
# A lesson policy that names no reward pays nothing. NOTE this is deliberately NOT
# rewards.DEFAULT_POLICY — a lesson must never mint gold just because someone forgot the field.
DEFAULT_REWARD_POLICY = "none"


def policy_of(lesson):
    """The lesson's completion policy dict, or None when authoritative completion is unavailable."""
    p = (lesson or {}).get("completionPolicy")
    return p if isinstance(p, dict) and p else None


def is_available(lesson):
    """True iff this lesson can EVER be completed authoritatively (i.e. it declares a usable policy)."""
    p = policy_of(lesson)
    return bool(p) and p.get("type") in POLICY_TYPES


def required_activity_ids(policy):
    ids, seen = [], set()
    for a in ((policy or {}).get("requiredActivityIds") or []):
        if isinstance(a, str) and a and a not in seen:
            seen.add(a)
            ids.append(a)
    return ids


def policy_version(policy):
    v = (policy or {}).get("version")
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else DEFAULT_VERSION


def pass_mark_of(policy):
    """The threshold. Content may restate it but never weaken it — the validator pins it to PASS_MARK."""
    pm = (policy or {}).get("passMark")
    return pm if isinstance(pm, int) and not isinstance(pm, bool) else PASS_MARK


def _round_half_up(value):
    """JS Math.round semantics. Python's round() is banker's and would disagree on .5 means."""
    return int(math.floor(value + 0.5))


def rule_a_mean(scores, required):
    """Legacy Rule A arithmetic, exactly as index.html statusFromScores() does it:

        mean = sum(correct / total * 100  for each required level) / len(required)

    Note the per-level term is NOT rounded — only the final mean is (by the caller). Every evidence
    source supplies an exact correct/total pair, so this reproduces the client value bit for bit.
    """
    if not required:
        return None
    terms = []
    for aid in required:
        rec = (scores or {}).get(aid)
        if not isinstance(rec, dict) or not rec.get("total"):
            return None
        terms.append(rec["correct"] / float(rec["total"]) * 100)
    return sum(terms) / float(len(terms))


def grants_of(policy):
    return [q for q in ((policy or {}).get("grants") or []) if isinstance(q, str) and q]


def reward_policy_of(policy):
    rp = (policy or {}).get("rewardPolicy")
    return rp if isinstance(rp, str) and rp else DEFAULT_REWARD_POLICY


def evaluate(lesson_id, lesson, passed_activity_ids, activity_scores=None):
    """Decide whether `lesson` is complete, given the set of activity ids the player has PASSED.

    `passed_activity_ids` must come from server-authoritative activity completions only — the caller
    is responsible for that, and this function has no other input it could be fooled by.

    Returns a plain dict:
        available            — the lesson declares a usable policy at all
        completed            — every required activity is passed (False whenever not available)
        policyType/policyVersion
        requiredActivityIds / completedActivityIds / missingActivityIds  (ordered, deduped)

    An unavailable lesson yields completed=False with an empty required list. It never yields
    completed=True by default, and there is no "no requirements means done" shortcut.
    """
    held = set(passed_activity_ids or ())
    policy = policy_of(lesson)
    out = {"lessonId": lesson_id, "available": False, "completed": False,
           "policyType": None, "policyVersion": None,
           "requiredActivityIds": [], "completedActivityIds": [], "missingActivityIds": [],
           "activityScores": {}, "meanPct": None, "roundedPct": None, "passMark": None}
    if not policy or policy.get("type") not in POLICY_TYPES:
        return out
    required = required_activity_ids(policy)
    out.update(available=True, policyType=policy.get("type"), policyVersion=policy_version(policy),
               requiredActivityIds=required,
               completedActivityIds=[a for a in required if a in held],
               missingActivityIds=[a for a in required if a not in held])
    if policy["type"] == "all_required_activities":
        # An empty requirement list is a registry error (the validator rejects it); treat it as
        # NOT complete rather than vacuously true, so a malformed policy can never grant anything.
        out["completed"] = bool(required) and not out["missingActivityIds"]
    elif policy["type"] == "average_required_activities":
        # Legacy Rule A: EVERY required level must have a score, then the unweighted mean of the
        # per-level percentages must reach PASS_MARK. An individual level may be below it.
        scores = activity_scores or {}
        have = {a: scores.get(a) for a in required}
        out["activityScores"] = {a: (dict(v) if isinstance(v, dict) else None) for a, v in have.items()}
        out["completedActivityIds"] = [a for a in required if isinstance(have[a], dict)]
        out["missingActivityIds"] = [a for a in required if not isinstance(have[a], dict)]
        out["passMark"] = pass_mark_of(policy)
        if required and not out["missingActivityIds"]:
            mean = rule_a_mean(have, required)
            out["meanPct"] = mean
            out["roundedPct"] = _round_half_up(mean)
            out["completed"] = out["roundedPct"] >= out["passMark"]
    return out


# ---- persistence helpers (state is the player's `learning` dict) --------------------------------
#
# Phase 4D uses TWO stores, and the split is deliberate:
#
#   lessonCompletions[lessonId]       = {completedAt, policyVersion}      LEGACY, unchanged semantics
#       The FIRST-EVER completion of this lesson, under whatever policy version was active then.
#       First-completion-wins; never re-dated, never re-versioned. Old readers keep working.
#
#   lessonCompletionHistory[lessonId] = [{policyVersion, completedAt}, …]  NEW, append-only
#       At most one entry per (lessonId, policyVersion), earliest completedAt wins for that version.
#
# A policy version is retired once it has been active (see registry retiredCompletionPolicyVersions),
# so "completed under v1" and "completed under v2" are genuinely different facts about a learner and
# both must survive. The legacy record alone could only ever hold one of them.
#
# READ MODEL: `merged_history()` merges the legacy record INTO the history VIRTUALLY, at read time.
# Nothing is migrated on disk: a file that predates Phase 4D and has only a legacy v1 record reads as
# history [v1] without being rewritten, and a later v2 completion simply APPENDS v2. This was chosen
# over lazy on-write materialisation because it touches no existing bytes at all — there is no
# rewrite path that could re-date a record or disturb unrelated player state.
HISTORY_KEY = "lessonCompletionHistory"


def get_lesson_completion(state, lesson_id):
    """The LEGACY first-ever completion record, exactly as older builds wrote and read it."""
    table = (state or {}).get("lessonCompletions")
    rec = table.get(lesson_id) if isinstance(table, dict) else None
    return rec if isinstance(rec, dict) else None


def _version_of(rec):
    v = (rec or {}).get("policyVersion")
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def _at_of(rec):
    t = (rec or {}).get("completedAt")
    return t if isinstance(t, int) and not isinstance(t, bool) else None


def merged_history(state, lesson_id):
    """The learner's full versioned completion history for one lesson, normalised.

    Merges the legacy record with the append-only history, keeping at most one entry per version and
    the EARLIEST completedAt for each. Malformed entries are dropped rather than trusted, so a
    hand-edited or truncated file can never fabricate a completion. Ordered by policyVersion.
    """
    best = {}

    def offer(rec):
        v, at = _version_of(rec), _at_of(rec)
        if v is None or at is None:
            return
        if v not in best or at < best[v]:
            best[v] = at

    offer(get_lesson_completion(state, lesson_id))       # legacy record, merged virtually
    table = (state or {}).get(HISTORY_KEY)
    entries = table.get(lesson_id) if isinstance(table, dict) else None
    if isinstance(entries, list):
        for e in entries:
            if isinstance(e, dict):
                offer(e)
    return [{"policyVersion": v, "completedAt": best[v]} for v in sorted(best)]


def completion_for_version(state, lesson_id, version):
    """The completedAt for one policy version, or None if that version was never completed."""
    for e in merged_history(state, lesson_id):
        if e["policyVersion"] == version:
            return e["completedAt"]
    return None


def has_any_completion(state, lesson_id):
    return bool(merged_history(state, lesson_id))


def record_lesson_completion(state, lesson_id, completed_at, policy_version_value):
    """Record a completion of `policy_version_value`. Returns (state, newly_recorded_for_version).

    Idempotent PER VERSION:
      * the version is already in the merged history -> nothing is written, `newly` is False
      * otherwise the version is APPENDED to the history, and the legacy record is created only when
        the learner has no first-ever record at all
    An existing legacy record is never re-dated, re-versioned or removed — completing v2 leaves a v1
    record byte-for-byte intact.
    """
    if not isinstance(state, dict):
        state = {}
    if completion_for_version(state, lesson_id, policy_version_value) is not None:
        return state, False
    hist = state.setdefault(HISTORY_KEY, {})
    existing = hist.get(lesson_id) if isinstance(hist.get(lesson_id), list) else []
    # Normalise only what is already IN the history list. The legacy record is deliberately NOT
    # folded in here: it stays where it is and is merged virtually on read, so this write can never
    # copy, re-date or otherwise disturb a pre-Phase-4D record.
    best = {}
    for e in existing + [{"policyVersion": policy_version_value, "completedAt": completed_at}]:
        v, at = _version_of(e), _at_of(e)
        if v is not None and at is not None and (v not in best or at < best[v]):
            best[v] = at
    hist[lesson_id] = [{"policyVersion": v, "completedAt": best[v]} for v in sorted(best)]
    table = state.setdefault("lessonCompletions", {})
    if lesson_id not in table:                  # first-ever completion of this lesson, any version
        table[lesson_id] = {"completedAt": completed_at, "policyVersion": policy_version_value}
    return state, True


def completed_lesson_ids(state):
    """Lessons the learner has completed under ANY policy version (legacy record or history)."""
    legacy = (state or {}).get("lessonCompletions")
    out = set(legacy.keys()) if isinstance(legacy, dict) else set()
    hist = (state or {}).get(HISTORY_KEY)
    if isinstance(hist, dict):
        out |= {lid for lid in hist if merged_history(state, lid)}
    return out
