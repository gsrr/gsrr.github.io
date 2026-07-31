"""Read-Along (Level 2) pronunciation scoring — PURE, and an EXACT port of the frontend rule.

Phase 3E1 moves Level 2 scoring from the browser to the server. Nothing here is an improvement on the
old rule: it is a line-for-line port of `pronWords()` + `showPron()` in index.html, so a learner's
score does not change when authority moves. Do NOT make this more linguistically clever — a "better"
scorer would silently re-grade every learner.

The rule, in words:
  * both sides are lowercased, curly apostrophes folded to ASCII, everything except [a-z' ] replaced
    by a space, then split on whitespace, then each word expanded through a fixed contraction table;
  * the TRANSCRIPT becomes a multiset of words;
  * each whitespace token of the TARGET is expanded the same way and matches only if EVERY one of its
    expanded words is still available in the multiset — matching consumes them (greedy, left to right);
  * a target token that reduces to no letters is skipped entirely (counts neither way);
  * pct = round(matched / total * 100), half-up, and 0 when there is nothing to match.

Word ORDER in the transcript is irrelevant, and extra transcript words are harmless. That is the
existing behaviour, documented in docs/stt-authority.md — not a new decision.

This module is text-only: it never touches audio, the STT provider, or the network.
"""
import math
import re

# The scorer is English-specific (the character class and this table). That is declared here, and by
# `scorerType: "read_along_stt"` in the registry — never by special-casing a lesson or course.
LANGUAGE = "en"
SCORER_TYPE = "read_along_stt"
PASS_MARK = 80        # matches index.html PASS_MARK / levelPassed("2")

# Ported verbatim from index.html CONTRACTIONS (48 entries).
CONTRACTIONS = {
    "i'm": "i am",
    "you're": "you are",
    "we're": "we are",
    "they're": "they are",
    "he's": "he is",
    "she's": "she is",
    "it's": "it is",
    "that's": "that is",
    "what's": "what is",
    "here's": "here is",
    "there's": "there is",
    "who's": "who is",
    "let's": "let us",
    "i've": "i have",
    "you've": "you have",
    "we've": "we have",
    "they've": "they have",
    "i'll": "i will",
    "you'll": "you will",
    "we'll": "we will",
    "they'll": "they will",
    "he'll": "he will",
    "she'll": "she will",
    "it'll": "it will",
    "i'd": "i would",
    "you'd": "you would",
    "we'd": "we would",
    "they'd": "they would",
    "he'd": "he would",
    "she'd": "she would",
    "won't": "will not",
    "can't": "can not",
    "cannot": "can not",
    "don't": "do not",
    "doesn't": "does not",
    "didn't": "did not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "haven't": "have not",
    "hasn't": "has not",
    "hadn't": "had not",
    "wouldn't": "would not",
    "shouldn't": "should not",
    "couldn't": "could not",
    "mustn't": "must not",
    "ain't": "is not",
}

_APOSTROPHES = re.compile("[\u2019\u02bc]")     # ’ and ʼ -> '
_NON_WORD = re.compile(r"[^a-z' ]")
_WS = re.compile(r"\s+")


def pron_words(value):
    """Port of pronWords(): normalize to a list of expanded lowercase words."""
    s = "" if value is None else str(value)
    s = _APOSTROPHES.sub("'", s.lower())
    s = _NON_WORD.sub(" ", s)
    out = []
    for w in _WS.split(s):
        if w:
            out.extend((CONTRACTIONS.get(w) or w).split(" "))
    return [w for w in out if w]


def _pct(matched, total):
    """Math.round semantics (half up) — Python's round() is banker's and would disagree."""
    if not total:
        return 0
    return int(math.floor(matched * 100.0 / total + 0.5))


def score_sentence(target, transcript):
    """Score one spoken sentence. Returns {pct, matchedTokens, totalTokens}.

    `target` must come from authoritative lesson content and `transcript` from the server's own STT —
    neither may be taken from the request body.
    """
    counts = {}
    for w in pron_words(transcript):
        counts[w] = counts.get(w, 0) + 1
    total = matched = 0
    for token in _WS.split("" if target is None else str(target)):
        if not token:
            continue
        subs = pron_words(token)
        if not subs:
            continue                                  # no letters in this token -> not counted
        total += 1
        if all(counts.get(x, 0) > 0 for x in subs):
            for x in subs:
                counts[x] -= 1
            matched += 1
    return {"pct": _pct(matched, total), "matchedTokens": matched, "totalTokens": total}


# ---- level aggregation + best-per-sentence retry semantics -------------------------------------
def best_scores(progress):
    """{sentenceIndex(int): best score} out of a stored sttProgress record, ignoring junk."""
    out = {}
    for k, v in ((progress or {}).get("sentences") or {}).items():
        try:
            i = int(k)
        except (TypeError, ValueError):
            continue
        s = (v or {}).get("score") if isinstance(v, dict) else None
        if isinstance(s, int) and not isinstance(s, bool) and 0 <= s <= 100:
            out[i] = s
    return out


def activity_pct(progress, total_sentences):
    """Port of the Level 2 aggregate: mean of best-per-sentence over ALL sentences, unscored = 0."""
    if not total_sentences or total_sentences <= 0:
        return 0
    best = best_scores(progress)
    # index.html: sum over EVERY sentence (unscored counts as 0), then Math.round(sum / script.length)
    total = sum(best.get(i, 0) for i in range(total_sentences))
    return int(math.floor(total / float(total_sentences) + 0.5))


def apply_sentence_score(progress, sentence_index, score, total_sentences, now):
    """Best-per-sentence update. Returns (progress, improved). A worse retry never lowers a score."""
    if not isinstance(progress, dict):
        progress = {}
    sentences = progress.setdefault("sentences", {})
    key = str(int(sentence_index))
    prior = sentences.get(key) if isinstance(sentences.get(key), dict) else None
    prior_score = prior.get("score") if prior and isinstance(prior.get("score"), int) else None
    improved = prior_score is None or score > prior_score
    if improved:
        sentences[key] = {"score": int(score), "updatedAt": now}
    progress["totalSentences"] = int(total_sentences)
    progress["pct"] = activity_pct(progress, total_sentences)
    return progress, improved
