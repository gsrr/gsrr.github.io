"""Deterministic server-side grading — PURE (no I/O, no LLM, no content knowledge).

Grading is GRADER-TYPE driven: an activity declares `graderType` (and optionally `graderConfig`) in
the registry, and dispatch happens through GRADERS. There is deliberately no `if lesson == …`, no
`if activityId == …` and no list of blessed activity names anywhere — the same grader serves any
activity of that type, in any course, in any content pack (see the synthetic non-English packs in
tests/learning_domain_test.py).

Every grader shares one contract:

    fn(key_items, answers, cfg) -> (correct, total)

`key_items` is the authoritative list straight out of the lesson JSON, `answers` is the client's
answer EVIDENCE, `cfg` is the activity's registry `graderConfig` (field names etc.) — never client
input. `grade()` wraps the pair into the GradeResult the rest of the system uses.

Answers are matched to key items BY PROMPT KEY (`normalization.prompt_key`), never by position, so
the client may shuffle freely — which every frontend controller does.

Trust boundary (documented, not disguised): answer keys are already client-visible (the browser
downloads the same lesson JSON to render the questions), so re-grading server-side cannot stop
someone who submits known-correct answers — that is equivalent to answering correctly. It DOES stop
forged `passed`/score, arbitrary-activity gold minting and self-granted qualifications.

Phase 3C ships four graders. `matching` (level 5) is deliberately absent: its score depends on click
history rather than a final answer state — see docs/deterministic-graders.md.
"""
import math

from . import normalization as N

PASS_MARK = 80        # must match index.html PASS_MARK


def _pct(correct, total):
    """Percentage using JS `Math.round` semantics — round HALF UP, not Python's banker's rounding.

    The frontend computes `Math.round(correct / total * 100)`; Python's round() would return 62 for
    5/8 where JS returns 63. Matching JS exactly is what keeps the reported pct identical on both
    sides (tests/learning_parity.test.js pins this).
    """
    if not total:
        return 0
    return int(math.floor(correct * 100.0 / total + 0.5))


def _cfg(cfg, key, default):
    v = (cfg or {}).get(key)
    return v if isinstance(v, str) and v else default


def _submitted(answers):
    """{prompt_key: raw submitted answer}. Later duplicates for one prompt do not overwrite the first."""
    out = {}
    for a in (answers or []):
        if isinstance(a, dict):
            k = N.prompt_key(a.get("q"))
            if k and k not in out:
                out[k] = a.get("answer")
    return out


# ---------------------------------------------------------------- yes_no (Phase 3A, unchanged)
def _grade_yes_no(key_items, answers, cfg=None):
    """Yes/No items [{"q":…, "answer":…}]. Case/whitespace-insensitive answer comparison.

    Kept exactly as Phase 3A shipped it (slightly more lenient than the frontend's `===`, which can
    only ever accept a differently-cased "yes"/"no"). A key item with a blank answer is never correct.
    """
    chosen = {}
    for a in (answers or []):
        if isinstance(a, dict):
            chosen[N.prompt_key(a.get("q"))] = str(a.get("answer", "")).strip().lower()
    total, correct = len(key_items), 0
    for item in key_items:
        q = N.prompt_key((item or {}).get("q"))
        want = str((item or {}).get("answer", "")).strip().lower()
        if want and q in chosen and chosen[q] == want:
            correct += 1
    return correct, total


# ---------------------------------------------------------------- multiple_choice (wh / cloze)
def _grade_multiple_choice(key_items, answers, cfg=None):
    """One-of-N choice items. Field names come from `cfg`, so the same grader serves any shape:

        wh    : {"promptField": "q",    "answerField": "a",      "distractorsField": "wrong"}
        cloze : {"promptField": "text", "answerField": "answer",  "distractorsField": "wrong"}

    Comparison is EXACT string equality, matching the frontend's `choice === it.a`: no trim, no case
    folding, no punctuation handling. A submission that is not one of the offered options counts as
    wrong (never as an error) — the same outcome the UI produces for a wrong click.
    """
    pf = _cfg(cfg, "promptField", "q")
    af = _cfg(cfg, "answerField", "a")
    df = _cfg(cfg, "distractorsField", "wrong")
    chosen = _submitted(answers)
    total, correct = len(key_items), 0
    for item in key_items:
        item = item or {}
        prompt = N.prompt_key(item.get(pf))
        want = item.get(af)
        if not prompt or want is None or prompt not in chosen:
            continue
        distractors = item.get(df)
        options = [want] + list(distractors if isinstance(distractors, list) else [])
        got = chosen[prompt]
        if N.exact_choice(got) in [N.exact_choice(o) for o in options] and \
                N.exact_choice(got) == N.exact_choice(want):
            correct += 1
    return correct, total


# ---------------------------------------------------------------- reorder (sentence building)
def _grade_reorder(key_items, answers, cfg=None):
    """Sentence-reordering items: each key item is a token list, e.g. ["I","went","to","the","park"].

    Evidence per sentence: {"q": "<tokens joined by a single space>", "answer": [tokenIndex, …]}.
    A sentence is correct iff the submitted order is exactly [0, 1, …, n-1] — TOKEN-INDEX equality,
    mirroring the frontend's `placed.every((id, i) => id === i)`. Index equality (not text equality)
    is what makes two identical words in one sentence non-interchangeable, exactly as the UI behaves.

    Scoring is per sentence over ALL key sentences. The UI cannot advance past an unsolved sentence,
    so its only attainable outcome is every-sentence-correct = 100%; grading each sentence
    independently reproduces that and additionally refuses to pass a forged partial submission.
    """
    sep = _cfg(cfg, "joinWith", " ")
    chosen = _submitted(answers)
    total, correct = len(key_items), 0
    for item in key_items:
        if not isinstance(item, list) or not item:
            continue
        key = N.prompt_key(sep.join(str(t) for t in item))
        if not key or key not in chosen:
            continue
        got = chosen[key]
        if not isinstance(got, list) or len(got) != len(item):
            continue                                  # wrong length / not a list -> wrong, not an error
        order, bad = [], False
        for x in got:
            # Strictly integral only. A float like 2.5 must NOT be truncated into a valid index, and
            # a JSON boolean is not a token position — both are simply wrong answers.
            if isinstance(x, bool):
                bad = True
            elif isinstance(x, int):
                order.append(x)
            elif isinstance(x, str) and x.strip().isdigit():
                order.append(int(x.strip()))           # a JSON client may send indices as strings
            else:
                bad = True
            if bad:
                break
        if not bad and order == list(range(len(item))):
            correct += 1
    return correct, total


# ---------------------------------------------------------------- dictation (typed text)
def _grade_dictation(key_items, answers, cfg=None):
    """Typed-dictation items: each key item is the sentence string the learner must type.

    Evidence per sentence: {"q": "<the authoritative sentence>", "answer": "<what the learner typed>"}.
    Using the sentence as the match key is safe — it is already client-visible, since the browser
    downloads the same lesson JSON to play and check it.

    Correct iff normalization.dictation_text(typed) == dictation_text(sentence), which is a direct port
    of the frontend's `norm()`. This is TEXT COMPARISON ONLY: no STT, no pronunciation scoring, no
    fuzzy or semantic acceptance (see docs/deterministic-graders.md).
    """
    chosen = _submitted(answers)
    total, correct = len(key_items), 0
    for item in key_items:
        if not isinstance(item, str) or not item.strip():
            continue
        key = N.prompt_key(item)
        if key not in chosen:
            continue
        got = chosen[key]
        if not isinstance(got, str):
            continue                                  # only typed text is gradable here
        if N.dictation_text(got) and N.dictation_text(got) == N.dictation_text(item):
            correct += 1
    return correct, total


GRADERS = {
    "yes_no": _grade_yes_no,
    "multiple_choice": _grade_multiple_choice,
    "reorder": _grade_reorder,
    "dictation": _grade_dictation,
}


def grader_types():
    return sorted(GRADERS)


def is_supported(grader_type):
    return grader_type in GRADERS


def grade(grader_type, key_items, answers, cfg=None):
    """Grade one attempt. Returns {graderType, correct, total, pct, passed}.

    An unsupported grader type, or an empty/invalid key, yields a non-pass with total=0 — never an
    exception, and never a pass by default. `cfg` is registry data; it is never taken from a request.
    """
    if not is_supported(grader_type) or not isinstance(key_items, list) or not key_items:
        return {"graderType": grader_type, "correct": 0, "total": 0, "pct": 0, "passed": False}
    # Malformed evidence (a scalar, a dict, None) is graded as "answered nothing", never an error —
    # graders below may then assume a list. The HTTP layer still rejects a non-list `answers` outright.
    if not isinstance(answers, list):
        answers = []
    correct, total = GRADERS[grader_type](key_items, answers, cfg)
    correct = max(0, min(int(correct), int(total)))
    pct = _pct(correct, total)
    return {"graderType": grader_type, "correct": correct, "total": total, "pct": pct,
            "passed": total > 0 and pct >= PASS_MARK}
