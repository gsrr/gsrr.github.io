"""Deterministic server-side grading — PURE (no I/O, no LLM, no content knowledge).

Phase 3B makes grading GRADER-TYPE driven rather than activity-name driven: an activity declares
`graderType` in the registry and dispatch happens through GRADERS. There is deliberately no
`if lesson == "Pre-A1/taipei/zoo"` and no list of blessed activity names anywhere — the same
`yes_no` grader serves any activity of that type, in any course, in any future content pack.

Phase 3B ships ONE grader (`yes_no`), which is all the current content needs. Adding
multiple_choice / reorder / cloze / matching / dictation is Phase 3C: register a function in
GRADERS and add the type to the registry validator — no other module changes.

Trust boundary (unchanged from 3A, documented not disguised): answer keys are already client-visible
(the browser downloads the same lesson JSON to render the questions), so re-grading server-side
cannot stop someone who submits known-correct answers — that is equivalent to answering correctly.
It DOES stop forged `passed`/score, arbitrary-activity gold minting and self-granted qualifications.
"""

PASS_MARK = 80        # must match index.html PASS_MARK


def _grade_yes_no(key_items, answers):
    """Yes/No (or any single-token answer) items: [{"q": ..., "answer": ...}, ...].

    Submissions are matched to the key BY QUESTION TEXT, so the client may shuffle freely.
    Comparison is case/whitespace-insensitive; a key item with a blank answer can never be scored
    correct (it would otherwise silently award a free point).
    """
    chosen = {}
    for a in (answers or []):
        if isinstance(a, dict):
            chosen[str(a.get("q", "")).strip()] = str(a.get("answer", "")).strip().lower()
    total, correct = len(key_items), 0
    for item in key_items:
        q = str((item or {}).get("q", "")).strip()
        want = str((item or {}).get("answer", "")).strip().lower()
        if want and q in chosen and chosen[q] == want:
            correct += 1
    return correct, total


GRADERS = {"yes_no": _grade_yes_no}          # graderType -> fn(key_items, answers) -> (correct, total)


def grader_types():
    return sorted(GRADERS)


def is_supported(grader_type):
    return grader_type in GRADERS


def grade(grader_type, key_items, answers):
    """Grade one attempt. Returns {graderType, correct, total, pct, passed}.

    An unsupported grader type or an empty/invalid key yields a non-pass with total=0 — never an
    exception, and never a pass by default.
    """
    if not is_supported(grader_type) or not isinstance(key_items, list) or not key_items:
        return {"graderType": grader_type, "correct": 0, "total": 0, "pct": 0, "passed": False}
    correct, total = GRADERS[grader_type](key_items, answers)
    pct = int(round(correct * 100.0 / total)) if total else 0
    return {"graderType": grader_type, "correct": correct, "total": total, "pct": pct,
            "passed": total > 0 and pct >= PASS_MARK}
