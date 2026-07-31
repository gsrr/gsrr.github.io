"""Level 5 Matching — server-owned rounds and first-try scoring. PURE (no I/O, no HTTP, no content).

Phase 3C had to block matching: its score is `firstTry / n`, which lives entirely in the click
history, so no end-state submission can prove it and asking the client for the count would be
trusting client-derived correctness. Phase 3E2 fixes that by giving the SERVER the round: it draws
the sample, holds the word→picture mapping, and observes every click.

Everything here is an exact port of `makeMatch` in index.html — see docs/matching-authority.md:
  * sample      : shuffle(vocab)[:min(5, len)], kept in shuffled order
  * left column : that order; matching is strictly SEQUENTIAL (only the current word can be matched)
  * right column: an INDEPENDENT second shuffle of the same items
  * first try   : a word scores iff no wrong click happened while it was the current word
  * wrong click : costs the point for that word only, permanently; the button is not disabled, so
                  clicking it again changes nothing
  * matched pic : inert — clicking it is a no-op, NOT a wrong attempt
  * completion  : every sampled word matched; correct = firstTry, total = n

Do not "improve" any of this. A different rule would silently re-grade every learner.
"""
import math

SCORER_TYPE = "matching_first_try"
SAMPLE_SIZE = 5          # index.html: n = Math.min(5, vocab.length)
PASS_MARK = 80           # matches index.html PASS_MARK / levelPassed("5")
ROUND_TTL = 6 * 3600     # an abandoned round is dropped after this many seconds (§30)


def sample_size(vocab_len):
    return min(SAMPLE_SIZE, max(0, int(vocab_len or 0)))


def pct_of(correct, total):
    """Math.round semantics (half up), like every other scorer in this codebase."""
    if not total:
        return 0
    return int(math.floor(correct * 100.0 / total + 0.5))


def item_id(activity_id, vocab_index):
    return "%s#item:%d" % (activity_id, int(vocab_index))


def choice_id(round_id, position):
    return "%s#choice:%d" % (round_id, int(position))


def build_round(activity_id, vocab, rng):
    """Draw a round: which items, in what left-column order, and the picture shuffle.

    `rng` must expose .sample()/.shuffle() (random.Random). Injectable so tests are deterministic —
    production passes a real Random, never anything client-supplied.
    Returns the round state dict (no player id: the caller stores it under the owning account).
    """
    n = sample_size(len(vocab or []))
    if not n:
        return None
    order = rng.sample(range(len(vocab)), n)      # == shuffle(vocab).slice(0, n)
    choices = list(order)
    rng.shuffle(choices)                          # == shuffle(seq) for the picture column
    return {"activityId": activity_id, "order": order, "choices": choices,
            "expected": 0, "missedCurrent": False, "firstTry": 0, "completed": False}


def is_expired(round_state, now):
    created = (round_state or {}).get("createdAt")
    return not isinstance(created, int) or (now - created) > ROUND_TTL


def public_view(round_id, round_state, vocab):
    """What the client may see: the words in order, and the pictures in shuffled order.

    Deliberately NOT included: which choice is correct, the vocab indexes behind the choices, or any
    mapping between the two columns. The client can render the game and nothing more.
    """
    order = (round_state or {}).get("order") or []
    choices = (round_state or {}).get("choices") or []
    return {
        "roundId": round_id,
        "activityId": round_state.get("activityId"),
        "total": len(order),
        "expected": round_state.get("expected", 0),
        "completed": bool(round_state.get("completed")),
        "items": [{"itemId": item_id(round_state.get("activityId"), vi),
                   "word": (vocab[vi] or {}).get("word")} for vi in order],
        "choices": [{"choiceId": choice_id(round_id, pos), "pic": (vocab[vi] or {}).get("pic")}
                    for pos, vi in enumerate(choices)],
    }


def current_item_id(round_state):
    order = (round_state or {}).get("order") or []
    i = (round_state or {}).get("expected", 0)
    return item_id(round_state.get("activityId"), order[i]) if 0 <= i < len(order) else None


def apply_click(round_state, round_id, item_id_arg, choice_id_arg):
    """Process one picture click. Returns (outcome, changed).

    outcome.status is one of:
      'correct'   — the current word was matched (point earned iff no earlier wrong click for it)
      'wrong'     — a wrong picture; the point for the current word is now lost
      'inert'     — an already-matched picture, or a repeat of a click that changes nothing.
                    Mirrors the legacy `if (btn.disabled …) return` — NOT a wrong attempt.
      'not_current' — the client named an item that is not the current one (out-of-order/duplicate
                    request). Rejected without touching first-try state, so a duplicated or
                    concurrent HTTP call can never cost or earn a second point (§29).
      'complete'  — this click matched the LAST word; the round is finished.
    """
    out = {"status": "inert", "roundId": round_id, "expected": round_state.get("expected", 0),
           "total": len(round_state.get("order") or []), "firstTry": round_state.get("firstTry", 0),
           "completed": bool(round_state.get("completed")), "scored": None}
    if round_state.get("completed"):
        return out, False
    order = round_state.get("order") or []
    choices = round_state.get("choices") or []
    i = round_state.get("expected", 0)
    if not (0 <= i < len(order)):
        return out, False
    # Identify the clicked button by POSITION, so the 4 lessons whose vocab reuses an emoji are still
    # unambiguous — exactly like the legacy closure over each button's own item.
    pos = _choice_position(round_id, choice_id_arg, len(choices))
    if pos is None:
        return out, False                                  # unknown choice -> inert, never an error
    clicked_vocab_index = choices[pos]
    if clicked_vocab_index in order[:i]:
        return out, False                                  # already matched -> inert (legacy no-op)
    # The client must name the word it believes is current; anything else is a stale/duplicate call.
    if item_id_arg is not None and item_id_arg != current_item_id(round_state):
        out["status"] = "not_current"
        return out, False
    if clicked_vocab_index == order[i]:
        scored = not round_state.get("missedCurrent")
        if scored:
            round_state["firstTry"] = round_state.get("firstTry", 0) + 1
        round_state["expected"] = i + 1
        round_state["missedCurrent"] = False
        out.update(status="correct", scored=scored, expected=round_state["expected"],
                   firstTry=round_state["firstTry"])
        if round_state["expected"] >= len(order):
            round_state["completed"] = True
            out.update(status="complete", completed=True)
        return out, True
    # wrong picture: the point for the CURRENT word is lost, permanently. Repeating it is harmless.
    changed = not round_state.get("missedCurrent")
    round_state["missedCurrent"] = True
    out["status"] = "wrong"
    return out, changed


def _choice_position(round_id, choice_id_arg, n_choices):
    prefix = "%s#choice:" % round_id
    if not isinstance(choice_id_arg, str) or not choice_id_arg.startswith(prefix):
        return None
    tail = choice_id_arg[len(prefix):]
    if not tail.isdigit():
        return None
    pos = int(tail)
    return pos if 0 <= pos < n_choices else None


def result_of(round_state):
    """Final score of a completed round: correct = firstTry, total = n (the legacy formula)."""
    total = len(round_state.get("order") or [])
    correct = int(round_state.get("firstTry", 0))
    pct = pct_of(correct, total)
    return {"correct": correct, "total": total, "pct": pct,
            "passed": total > 0 and pct >= PASS_MARK}
