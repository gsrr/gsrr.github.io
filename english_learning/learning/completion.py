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
def get_lesson_completion(state, lesson_id):
    rec = ((state or {}).get("lessonCompletions") or {}).get(lesson_id)
    return rec if isinstance(rec, dict) else None


def record_lesson_completion(state, lesson_id, completed_at, policy_version_value):
    """Idempotent, first-completion-wins. Returns (state, newly_recorded).

    A later evaluation never re-dates an existing record, and never rewrites its policyVersion —
    the stored version is the one under which the lesson was actually completed.
    """
    if not isinstance(state, dict):
        state = {}
    table = state.setdefault("lessonCompletions", {})
    if lesson_id in table:
        return state, False
    table[lesson_id] = {"completedAt": completed_at, "policyVersion": policy_version_value}
    return state, True


def completed_lesson_ids(state):
    return set(((state or {}).get("lessonCompletions") or {}).keys())
