# Grader migration report (Phase 3C)

Companion to [deterministic-graders.md](deterministic-graders.md) (the inventory and classification).
This file records what was actually migrated, what was deferred, and what is blocked.

## Summary

| Grader type | Status | Content keys | Frontend function | Backend grader | Parity | Activities registered | Reward | Qualifications |
|---|---|---|---|---|---|---|---|---|
| `yes_no` | **migrated** (3A) + extended | `quiz3`, `quiz4` | `makeQuiz` | `_grade_yes_no` | tested | 2 | quiz3 `standard_activity_pass`; quiz4 `none` | quiz3 → 1; quiz4 → none |
| `multiple_choice` | **migrated** | `wh`, `cloze` | `makeWh`, `makeCloze` | `_grade_multiple_choice` | tested | 2 | `none` | none |
| `reorder` | **migrated** | `reorder` | `makeReorder` | `_grade_reorder` | tested | 1 | `none` | none |
| `dictation` | **migrated** | `dictation` | `makeDictation` | `_grade_dictation` | tested | 1 | `none` | none |
| `matching` | **BLOCKED (category B)** | `vocab` | `makeMatch` | — | n/a | 0 | — | — |
| pronunciation | **excluded (category C)** | *(article text)* | shadowing + STT | — | n/a | 0 | — | — |
| roleplay | **excluded (category C)** | roleplay pack | `roleplay/classifier.js` | — | n/a | 0 | — | — |

**6 activities registered, 4 grader types, 1 gold-bearing activity, 1 qualification** — verified by
`tools/validate_learning_registry.py --strict`, which prints this coverage table on every run.

## Migrated activities (representative set, §17)

| ActivityId | Content | graderType | graderConfig | rewardPolicy | grants |
|---|---|---|---|---|---|
| `english.prea1.taipei.zoo.quiz3` | `Pre-A1/taipei/zoo` `quiz3` | `yes_no` | — | `standard_activity_pass` | `english.prea1.taipei.zoo` |
| `english.prea1.taipei.zoo.quiz4` | `Pre-A1/taipei/zoo` `quiz4` | `yes_no` | — | `none` | — |
| `english.prea1.taipei.zoo.wh` | `Pre-A1/taipei/zoo` `wh` | `multiple_choice` | `q` / `a` / `wrong` | `none` | — |
| `english.prea1.taipei.zoo.cloze` | `Pre-A1/taipei/zoo` `cloze` | `multiple_choice` | `text` / `answer` / `wrong` | `none` | — |
| `english.a1.core.001.reorder` | `A1/001` `reorder` | `reorder` | — | `none` | — |
| `english.a1.core.001.dictation` | `A1/001` `dictation` | `dictation` | — | `none` | — |

Deliberately **not** bulk-enabled: 57 lessons carry `quiz3`/`quiz4`/`vocab`/`wh`/`cloze` and 29 also
carry `reorder`/`dictation`. Enabling all of them is a content-assignment decision, not a grading one,
and would need the reward/qualification review in §22–§24 first. Adding one is now a registry edit with
no code change.

One new content pack (`english.a1` → course `english.a1.core` → lesson `english.a1.core.001` →
`A1/001`) was added purely because `reorder`/`dictation` do not exist in any Pre-A1 lesson.

## Parity results (§28)

`tests/learning_parity.test.js` is the frontend half of the proof. It does not reimplement grading —
it extracts the live controller sources from `index.html`, **asserts the exact comparison expressions
are still the ones Phase 3C ported**, executes the real `norm()` straight out of the page source, and
recomputes every case in `tests/fixtures/learning_grader_golden.json`.
`tests/learning_graders_test.py` asserts the backend produces the same numbers for the same fixture.

Pinned expressions (a change to any of them fails the test rather than silently breaking parity):

| Rule | Live source |
|---|---|
| yes_no | `const right = shuffled[idx].answer;` … `if (choice === right)` |
| wh | `if (choice === it.a)` |
| cloze | `if (choice === it.answer)` |
| reorder | `placed.every((id, i) => id === i)` + `recordScore(6, sentences.length, sentences.length)` |
| dictation | `const ok = norm(input.value) === norm(sentence);` |
| pct / pass | `Math.round(s.correct / s.total * 100) >= PASS_MARK` with `PASS_MARK = 80` |

**25 golden cases** reproduce identically on both sides (10 multiple_choice, 8 reorder, 7 dictation),
plus real-content parity over 4 lessons for wh/cloze and 2 for reorder/dictation.

One genuine divergence was found and fixed during this work: Python's `round()` is banker's rounding
while JS `Math.round` is half-up, so `5/8` produced **62** server-side and **63** in the browser. The
backend now uses an explicit half-up `_pct()`. No realistic item count puts a half-way value at the 80
threshold, so no pass/fail verdict ever differed — only the reported percentage could. Recorded as an
intentional change.

## Normalization rules ported (§15)

`learning/normalization.py` contains only rules that already existed:

- `dictation_text` — exact port of `makeDictation.norm()`: lowercase → strip the 8 ASCII marks
  `. , ! ? ; : ' "` → collapse whitespace → trim. **Not** stripped: hyphens, curly quotes, any other
  Unicode. No stemming, synonyms, article stripping or fuzzy distance.
- `prompt_key` — `.strip()` only, used to match a submitted answer to its authoritative item (every
  frontend controller shuffles, so positional matching would be wrong).
- `exact_choice` — deliberately does nothing but `str()`, because the multiple-choice frontends compare
  with `===`.

## Known edge cases

- **reorder duplicate tokens** — 2 of 116 real sentences contain a repeated word. The frontend compares
  token *indices*, so swapping two identical words is WRONG there; the backend does the same. Grading by
  text would have diverged. A golden case pins this.
- **reorder attainable outcomes** — the UI cannot advance past an unsolved sentence, so its only
  attainable result is 100%. The backend grades each sentence independently, which reproduces that and
  additionally refuses to pass a forged partial submission. Strictly stricter, never looser.
- **reorder / dictation item keys** — reorder keys on the space-joined sentence and dictation on the
  sentence itself. Verified unique within every lesson (all 57); the validator now rejects a lesson
  where two items would collide.
- **dictation prompt is the answer** — the evidence `{q: sentence, answer: typed}` includes the
  sentence. That leaks nothing: the browser already downloads the lesson JSON to play and check it.
- **first-answer-wins** — if evidence contains two entries for one prompt, the first is graded. Prevents
  "submit every option" farming.
- **`clozeType`** (`recognition`/`context`/`category`/`pos`) is an authoring hint the frontend grader
  ignores; the backend ignores it too.
- **quiz4 is now server-graded but unrewarded** — passing level 4 of the Zoo lesson records a
  completion and grants nothing. Intentional (§23).
- **`yes_no` answer comparison** stays case-insensitive (as Phase 3A shipped), marginally more lenient
  than the frontend's `===`. It can only ever accept a differently-cased "yes"/"no", so no real
  attempt differs. Left unchanged rather than tightened, to avoid altering 3A behaviour.

## Blocked: `matching` (level 5, `vocab`)

`recordScore(5, firstTry, seq.length)` where `firstTry` counts words whose **first** picture click was
correct. That number lives only in the click history — a completed match always ends in "every word
matched", so the final state cannot distinguish a perfect run from a messy one.

Migrating it would require inventing a new answer-evidence format (an ordered click stream against a
client-chosen random sample of `min(5, |vocab|)` words) plus a server-side replay of the click state
machine. Two unresolved product questions:

1. the word sample is drawn by the client and cannot be verified as honest, only as in-vocabulary;
2. any simpler evidence ("which words were first-try") is **client-derived correctness**, which §8 and
   §43.10 forbid trusting.

Both are product decisions, so per §4 this is reported rather than migrated. Level 5 keeps its existing
client-side scoring, untouched, and `makeMatch` deliberately contains no attempt submission — pinned by
an assertion in `tests/learning_frontend.test.js`.

## Excluded: pronunciation (level 2), roleplay (level 10)

Category C — STT and free-form semantic classification. Explicitly out of scope (§2), untouched.

## Browser acceptance (§37)

One real activity driven in real Chrome per migrated grader type, against the real server: yes_no
(level 4), multiple_choice (level 7 `wh` **and** level 9 `cloze`), reorder (level 6), dictation
(level 8). Each was failed then passed; completions, zero reward and zero qualifications were verified
through the API, plus a regression pass on the Zoo `quiz3` slice (qualification + PASS_GOLD once) and a
check that completing level 5 matching records nothing. See the Phase 3C final report for results.
