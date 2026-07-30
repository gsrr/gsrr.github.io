"""Deterministic server-side grading for the Phase 3A vertical slice — PURE (no I/O, no LLM).

Only the Yes/No reading-comprehension activities (quiz3 / quiz4) are migrated to server-verified
grading in Phase 3A. Other activity types (match/reorder/wh/dict/cloze/pronunciation/roleplay) are
intentionally NOT graded here yet — migrating them is out of Phase 3A scope. The pass threshold
mirrors the frontend's PASS_MARK (index.html) so the server reproduces the same pass decision.
"""

PASS_MARK = 80                          # must match index.html PASS_MARK
YESNO_ACTIVITIES = ("quiz3", "quiz4")   # the only server-graded activity types in Phase 3A


def is_gradable(activity):
    return activity in YESNO_ACTIVITIES


def grade(activity, key_items, answers):
    """Grade one Yes/No activity against its authoritative key.

    key_items : the lesson's authoritative list, e.g. [{"q": "...", "answer": "Yes"}, ...].
    answers   : the student's submitted choices as [{"q": "...", "answer": "Yes"}, ...]. Matched to the
                key by question text, so the client may render questions in any (shuffled) order.
    Returns {correct, total, pct, passed}. Unknown activity / empty key -> not passed.

    Note (documented trust boundary): the answer keys are already client-visible (the client downloads
    the same lesson JSON to render), so this re-grade is authoritative but cannot stop a cheater who
    submits known-correct answers — equivalent to actually answering correctly. It DOES stop
    passed=true / forged score / arbitrary-lesson gold minting (those are handled by the endpoint).
    """
    if activity not in YESNO_ACTIVITIES or not isinstance(key_items, list) or not key_items:
        return {"correct": 0, "total": 0, "pct": 0, "passed": False}
    chosen = {}
    for a in (answers or []):
        if isinstance(a, dict):
            chosen[str(a.get("q", "")).strip()] = str(a.get("answer", "")).strip().lower()
    total = len(key_items)
    correct = 0
    for item in key_items:
        q = str((item or {}).get("q", "")).strip()
        want = str((item or {}).get("answer", "")).strip().lower()
        if want and q in chosen and chosen[q] == want:
            correct += 1
    pct = int(round(correct * 100.0 / total)) if total else 0
    return {"correct": correct, "total": total, "pct": pct, "passed": total > 0 and pct >= PASS_MARK}
