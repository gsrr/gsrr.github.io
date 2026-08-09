# Deterministic grader inventory (Phase 3C STEP 1–2)

Inventory of every candidate activity type as it exists at commit `737bd12`, **before** any Phase 3C
runtime change. Grading rules below were read out of `index.html`, not inferred from field names.
Content statistics were measured across all 57 lesson JSON files under `Pre-A1/ A1/ A2/ B1/`.

## Level → activity → content key map

| Level tab | JSON key | Frontend controller | Scoring call |
|---|---|---|---|
| 1 · Listen 👂 | *(article text)* | `loadScene` / listen mode | none — `levelPassed("1")` is always true |
| 2 · Read Along 🎤 | *(article text)* | shadowing + pronunciation scoring | `recordScore(2, avg, 100)` or completion fallback |
| 3 · Quiz ✅ | `quiz3` | `makeQuiz` | `recordScore(level, correct, m)` |
| 4 · Tricky Quiz 🤔 | `quiz4` | `makeQuiz` (same controller) | `recordScore(level, correct, m)` |
| 5 · Match 🖼️ | `vocab` | `makeMatch` | `recordScore(5, firstTry, seq.length)` |
| 6 · Reorder 🧩 | `reorder` | `makeReorder` | `recordScore(6, sentences.length, sentences.length)` |
| 7 · WH Questions ❓ | `wh` | `makeWh` | `recordScore(7, correct, m)` |
| 8 · Dictation ✍️ | `dictation` | `makeDictation` | `recordScore(8, correct, m)` |
| 9 · Fill Blank 📝 | `cloze` | `makeCloze` | `recordScore(9, correct, m)` |
| 10 · Role-play 🎭 | *(roleplay pack)* | `roleplay/engine.js` + `classifier.js` | `recordScore(10, passes, turns)` |

## Content shapes and coverage (measured)

| Key | Files | Shape | Notes |
|---|---|---|---|
| `quiz3` | 57 | `[{q, answer}]` | answer is `"Yes"`/`"No"` |
| `quiz4` | 57 | `[{q, answer}]` | identical shape to `quiz3` |
| `vocab` | 57 | `[{word, pic}]` | `pic` is an emoji |
| `wh` | 57 | `[{q, a, wrong:[…]}]` | **all 3 options**, 0 duplicate option texts across 513 items |
| `cloze` | 57 | `[{text, answer, wrong:[…]}]` | `text` contains `___`; also **all 3 options** |
| `clozeType` | 57 | `str` | `recognition`/`context`/`category`/`pos` — a *content-authoring* hint; the frontend grader ignores it |
| `reorder` | 29 | `[[token, …]]` | 116 sentences; **2 contain duplicate tokens** |
| `dictation` | 29 | `[str]` | 116 sentences; **0** contain curly quotes or hyphens |

## Per-type grading rules, as actually implemented

### `quiz3` / `quiz4` — `makeQuiz` (already migrated as `yes_no`)
- Items shuffled per attempt; options are the literal `["Yes","No"]`.
- Correct iff `choice === right` (exact string).
- `correct++` per item; `recordScore(level, correct, m)` where `m = items.length`.

### `wh` — `makeWh`
- `choices = shuffle([it.a, ...it.wrong])`; buttons carry `dataset.val = choice`.
- Correct iff **`choice === it.a`** — exact string equality, no trim, no case folding, no punctuation handling.
- Per-item scoring, `total = shuffled.length`. No partial credit inside an item, no duplicate-answer path (one click only, `answered` latch).

### `cloze` — `makeCloze`
- `choices = shuffle([it.answer, ...it.wrong])`; button text is the raw option.
- Correct iff **`choice === it.answer`** — exact string equality.
- Per-item scoring, `total = shuffled.length`. `clozeType` does not affect grading.

### `dictation` — `makeDictation`
- Learner types free text; correct iff `norm(input.value) === norm(sentence)` with

```js
function norm(s) {
  return (s || "").toLowerCase().replace(/[.,!?;:'"]/g, "").replace(/\s+/g, " ").trim();
}
```

- i.e. lowercase → strip `. , ! ? ; : ' "` → collapse whitespace runs to one space → trim.
- **Not** stripped: hyphens, curly quotes `’ “ ”`, other Unicode. No Unicode normalization. No article/synonym leniency. No multiple accepted answers.
- Measured: no real dictation sentence contains a curly quote or hyphen, so the rule is unambiguous on shipped content.
- Per-item scoring, `total = shuffled.length`; sentences are shuffled per attempt.

### `reorder` — `makeReorder`
- `tokens = sentences[idx].map((w,i) => ({id:i, word:w}))`; the pool is shuffled, re-shuffled if it happens to equal the original order.
- Check is `placed.every((id, i) => id === i)` — **token-index** equality, *not* text equality. Two identical words swapped therefore count as WRONG (matters for the 2 sentences with duplicate tokens).
- The learner cannot advance past a sentence until it is solved; on solving the last one the level records **full marks**: `recordScore(6, sentences.length, sentences.length)`.
- Sentence list is **not** shuffled (`sentences[idx]` in declaration order). Joined-by-space sentences are unique within every lesson (verified across all 57).

### `vocab` — `makeMatch` (level 5)
- Samples `n = min(5, vocab.length)` words, shuffles them for the left column and shuffles again for the picture column.
- The learner must click pictures **in left-column order**. A wrong click sets `missedCurrent = true` for the current word; a correct click increments `firstTry` **only if** `missedCurrent` was false.
- Score = `firstTry / n` — a function of the **click history**, not of a final answer state.
- The activity cannot end without every word matched, so `correct` is entirely determined by how many wrong clicks happened along the way.

### Level 2 (Read Along) and Level 10 (Role-play)
- Level 2 scores pronunciation from STT (`/api/stt`, Whisper) and falls back to "completion = full marks" when no scoring backend is reachable.
- Level 10 grades free-form role-play turns through `roleplay/classifier.js`.

## Classification

| Type | Class | Verdict | Reason |
|---|---|---|---|
| `yes_no` (`quiz3`, `quiz4`) | **A** | already server-authoritative | exact match, reproduced in Phase 3A |
| `multiple_choice` (`wh`) | **A** | migrate | exact string equality against `it.a`; all items 3-option, no duplicate option text |
| `multiple_choice` (`cloze`) | **A** | migrate | exact string equality against `it.answer`; `clozeType` irrelevant to grading |
| `reorder` | **A** | migrate | token-index permutation equality; deterministic and exactly portable |
| `dictation` | **A** | migrate | deterministic text normalization, fully specified above, unambiguous on real content |
| `matching` (`vocab`) | **B** | **STOP — not migrated** | see below |
| pronunciation (level 2) | **C** | excluded | requires STT; explicitly out of scope (§2) |
| roleplay (level 10) | **C** | excluded | free-form semantic classification; explicitly out of scope (§2) |

### Why `matching` is category B (STOP, §4 / §43.4 / §43.10)

The score is `firstTry / n`, where `firstTry` counts words whose **first** picture click was correct. That
number exists only in the interaction history — there is no final answer state that encodes it. The
final state of a completed match is always "every word matched", i.e. indistinguishable between a
perfect run and one with many wrong clicks.

Reproducing it server-side would require **inventing a new answer-evidence format** (an ordered
click stream: which picture was clicked, in what order, against which sampled word list) and a
server-side replay of the click state machine. Two further decisions have no current answer:

1. The word set is a random sample of `min(5, |vocab|)` chosen by the client. The server cannot
   verify the sample was drawn honestly; it can only check the words exist in the lesson's `vocab`.
2. Any simpler evidence (e.g. "which words were first-try") would be **client-derived correctness** —
   exactly what §8 and §43.10 forbid trusting.

Both are product decisions, so `matching` is reported and left unmigrated. Level 5 keeps its existing
client-side scoring, unchanged.

## Reward-economy finding (§22)

`PASS_GOLD` is 10000. Every one of the 57 lessons has `quiz3`, `quiz4`, `vocab`, `wh`, `cloze`, and 29
also have `reorder` and `dictation`. Attaching the existing `standard_activity_pass` policy to each
newly migrated activity would create **~270 additional one-time 10000-gold payouts** (≈2.7M gold)
versus the single payout that exists today — a material economy change and squarely outside Phase 3C.

> Superseded in part by Phase 7C.2: `PASS_GOLD` is now **160**, so the same fan-out would be ≈43k gold
> rather than ≈2.7M. The *decision* below is unchanged — 43k is still a material economy change, and
> grading support still stays separate from reward eligibility.

Therefore, per §23, every activity registered in Phase 3C uses `rewardPolicy: "none"`. Grading support
and reward eligibility stay separate registry concepts. The Zoo `quiz3` slice keeps
`standard_activity_pass` and remains the only gold-bearing activity.

> Superseded in part by Phase 7C.2a: the three other Taipei `quiz3` **gates** were later given the
> same policy, so the gold-bearing set is now those four activities. The separation asserted here
> still holds — the ~270 other migrated activities remain `rewardPolicy: "none"`, and reward
> activation stayed a deliberate, separate decision rather than a consequence of registering content.

## Qualification finding (§24)

Likewise, no qualification is invented for any newly migrated activity: all Phase 3C registrations use
an empty `grants` list. The only qualification in the system remains `english.prea1.taipei.zoo`,
granted only by `english.prea1.taipei.zoo.quiz3`.

This required one validator change — Phase 3B rejected an activity with an empty `grants` list; that
rule is now relaxed to "`grants` must be a list of known qualification ids, possibly empty", which is
what §24 requires. Reported as an intentional change.
