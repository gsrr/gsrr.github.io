"""Text normalization for deterministic graders — PURE, and deliberately minimal.

Every rule here is a straight PORT of a rule that already exists in the frontend, so server grading
reproduces the current learner-visible behaviour exactly. This is NOT a general "smart answer
matcher": there is no stemming, no synonym table, no article stripping, no fuzzy distance, and no
Unicode folding beyond what the frontend already does. Adding leniency here would silently change
what counts as a pass, so don't.

See docs/deterministic-graders.md for where each rule comes from.
"""
import re

# index.html makeDictation.norm():
#   (s||"").toLowerCase().replace(/[.,!?;:'"]/g,"").replace(/\s+/g," ").trim()
# NOTE the punctuation class is exactly these 8 ASCII characters — hyphens, curly quotes and any
# other Unicode punctuation are intentionally NOT stripped, matching the frontend.
_DICTATION_STRIP = re.compile(r"[.,!?;:'\"]")
_WS_RUN = re.compile(r"\s+")


def dictation_text(value):
    """Port of makeDictation.norm(): lowercase, drop 8 ASCII punctuation marks, collapse WS, trim."""
    s = "" if value is None else str(value)
    s = s.lower()
    s = _DICTATION_STRIP.sub("", s)
    s = _WS_RUN.sub(" ", s)
    return s.strip()


def prompt_key(value):
    """Key used to match a submitted answer back to its authoritative item.

    Only `.strip()` — the same thing the Phase 3A yes_no grader has always done. It exists so the
    client may shuffle question order freely; it is not part of answer comparison.
    """
    return "" if value is None else str(value).strip()


def exact_choice(value):
    """Identity-with-str() for option comparison.

    The frontend multiple-choice graders compare with `choice === it.a` — no trim, no case folding.
    Keeping that strictness is what makes server grading match the learner's experience, so this
    deliberately does nothing except coerce to str.
    """
    return "" if value is None else str(value)
