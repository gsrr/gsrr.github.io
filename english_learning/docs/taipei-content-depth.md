# Taipei content depth — MRT / Night Market / Park (Phase 4B)

Phase 4A registered just enough of MRT, Night Market and Park to carry their `quiz3` conquest
qualifications. Phase 4B registers **every remaining activity that an existing server-authoritative
engine can score**, so all three lessons now accumulate authoritative evidence for their whole
length instead of only their gate.

No new scoring code was written. No lesson-specific branch exists anywhere. The registry gained 15
rows; `game/`, `server.py`, `index.html` and `world-data/` were not touched at all.

**The headline finding is in [§6](#6-stop-review--why-no-lesson-policy-was-activated): legacy Rule A
scores SEVEN levels per Taipei lesson, not six.** Level 10 Role-play is one of them, it has no
server-authoritative implementation, and implementing it is out of Phase 4B scope. So the three
lessons are registered to their authoritative maximum (6/7) but **no completion policy was
activated**.

> ### Approved correction (developer decision, end of Phase 4B)
>
> The STOP was confirmed and Rule A must not be silently redefined. Accordingly:
>
> - **MRT / Market / Park stay unactivated.**
> - **Zoo's v1 policy was RETIRED**, because a 6-of-7 policy does not reproduce legacy Rule A.
> - **Production authoritative lesson policies: 0.** This is now the *expected* value, and
>   `tools/validate_content_coverage.py` treats an active policy over an incompletely-covered lesson
>   as an **error**, not a note.
> - **Existing Zoo `lessonCompletions` are preserved verbatim.** They are historical legacy records
>   under `policyVersion: 1` and grant no gold, no qualification, no territory access and no
>   `passcnt`, so keeping them is safe and non-destructive.
> - **Version 1 is spent.** `learning/registry.json` records
>   `"retiredCompletionPolicyVersions": [1]` on the Zoo lesson, and the registry validator rejects any
>   future policy that reuses it — a record's version must always identify the rule that produced it.
> - Level 10 is the next explicit Learning authority blocker: see
>   **[`docs/roleplay-authority-gap.md`](roleplay-authority-gap.md)**.

---

## 1. Content structure — all four Taipei lessons are schema-identical

Every lesson is a pair of files under `Pre-A1/taipei/`:

| File | Role |
|---|---|
| `<slug>` (no extension) | the Tom & Anna dialogue, 10 `Speaker: text` lines — the Read-Along script |
| `<slug>.json` | `{quiz3[5], quiz4[5], vocab[6], wh[5], cloze[4], clozeType}` |

The four `.json` files have **identical key sets and identical item shapes**; only the strings
differ. That is why registration alone was sufficient — the Zoo entries were reproduced verbatim in
shape, with different content paths.

```
quiz3/quiz4 item : {"q": "...", "answer": "Yes"|"No"}
vocab item       : {"word": "train", "pic": "🚊"}
wh item          : {"q": "...", "a": "...", "wrong": ["...", "..."]}
cloze item       : {"text": "... ___ ...", "answer": "...", "wrong": ["...", "..."]}
```

None of the three declares `reorder` or `dictation`, so levels 6 and 8 are correctly absent from
their Rule A sets (the generic graders for both exist and stay unused here).

## 2. Per-lesson inventory

### Taipei 2 · On the MRT

| Field | Value |
|---|---|
| LessonId | `english.prea1.taipei.mrt` |
| contentPath | `Pre-A1/taipei/mrt` |
| Manifest arc | `tp-mrt`, title *Taipei 2 · On the MRT*, `levels: [1,2,3,4,5,7,9]` |
| Dialogue | 10 sentences |
| Roleplay scenario | `roleplay/scenarios/lesson/Pre-A1-taipei-mrt.json` (authored, exists) |

### Taipei 3 · The Night Market

| Field | Value |
|---|---|
| LessonId | `english.prea1.taipei.market` |
| contentPath | `Pre-A1/taipei/market` |
| Manifest arc | `tp-market`, title *Taipei 3 · The Night Market*, `levels: [1,2,3,4,5,7,9]` |
| Dialogue | 10 sentences |
| Roleplay scenario | `roleplay/scenarios/lesson/Pre-A1-taipei-market.json` (authored, exists) |

### Taipei 4 · At the Park

| Field | Value |
|---|---|
| LessonId | `english.prea1.taipei.park` |
| contentPath | `Pre-A1/taipei/park` |
| Manifest arc | `tp-park`, title *Taipei 4 · At the Park*, `levels: [1,2,3,4,5,7,9]` |
| Dialogue | 10 sentences |
| Roleplay scenario | `roleplay/scenarios/lesson/Pre-A1-taipei-park.json` (authored, exists) |

## 3. Exact legacy Rule A required level set — SEVEN levels

`scoredLevelsFor()` in `index.html`:

```js
function scoredLevelsFor(a) {
  let lv;
  if (a.levels && a.levels.length) lv = a.levels.filter(l => l >= 2).map(String);
  else { lv = ["2","3","4","5"]; …derive 6/7/8/9 from content keys… }
  if (lv.indexOf("10") < 0) lv.push("10");   // Level 10 Role-play：所有課都有對話，一律計分
  return lv;
}
```

The `push("10")` is **outside the if/else**. It therefore applies to lessons that declare their own
`levels` array too — which is all four Taipei arcs. Executing the shipped function on the real arc
objects:

```
Pre-A1/taipei/zoo      => ["2","3","4","5","7","9","10"]
Pre-A1/taipei/mrt      => ["2","3","4","5","7","9","10"]
Pre-A1/taipei/market   => ["2","3","4","5","7","9","10"]
Pre-A1/taipei/park     => ["2","3","4","5","7","9","10"]
```

Level 10 is not vestigial. It is reachable, playable and scored:

- the tab is un-hidden for any lesson with a ≥2-sentence dialogue → all four
  (`tab10.classList.toggle("hidden", !(script && script.length >= 2))`)
- all four have hand-authored branch scenarios on disk
- finishing a conversation calls `recordScore(10, summary.passes, summary.turns)`

And it materially changes the outcome — the real `statusFromScores()` on an MRT-shaped arc:

| Evidence | `allScored` | `avg` | `passed` |
|---|---|---|---|
| levels 2,3,4,5,7,9 all perfect, **no** level 10 | `false` | `null` | **`false`** |
| same + level 10 = 8/10 | `true` | 97 | `true` |
| same + level 10 = 0/10 | `true` | 86 | `true` |

Without a level-10 score a Taipei lesson can **never** satisfy legacy Rule A.

> **Correction to `docs/lesson-completion.md`.** The Phase 3D inventory recorded "no article
> includes level 10 … so it never enters `scoredLevelsFor`" and "Roleplay required = FALSE". Both
> were wrong: they read the `if` branch as returning early. The arithmetic in that document is
> correct; the required level set is not. The affected rows are now annotated in place.

## 4. Authoritative coverage table

Category key — **A** already registered and authoritative · **B** existing generic scorer supports
it, registry-only registration needed · **C** frontend authority migration needed · **D**
unsupported / genuine blocker.

Identical for all three lessons (`<L>` ∈ `mrt`, `market`, `park`):

| Level | Activity | Source field | Frontend controller | Engine | Before | Action | After |
|---|---|---|---|---|---|---|---|
| 2 · Read Along | pronunciation | dialogue file | `scorePronunciation` | `read_along_stt` | **B** | registered | **A** |
| 3 · Quiz | `yes_no` | `quiz3` | `quiz3Ctl` (`makeQuiz`) | `yes_no` | **A** (Phase 4A) | unchanged | **A** |
| 4 · Tricky Quiz | `yes_no` | `quiz4` | `quiz4Ctl` (`makeQuiz`) | `yes_no` | **B** | registered | **A** |
| 5 · Match | matching | `vocab` | `matchCtl` (`makeMatch`) | `matching_first_try` | **B** | registered | **A** |
| 7 · WH | `multiple_choice` | `wh` | `whCtl` (`makeWh`) | `multiple_choice` | **B** | registered | **A** |
| 9 · Fill Blank | `multiple_choice` | `cloze` | `clozeCtl` (`makeCloze`) | `multiple_choice` | **B** | registered | **A** |
| **10 · Role-play** | free conversation | roleplay pack | `startRolePlay` | — | **D** | **none — blocker** | **D** |

Nothing was category **C**: see [§7](#7-why-no-frontend-change-was-needed).

Coverage before → after, per lesson: **1/7 → 6/7**.

## 5. Registered activities

15 new rows, 5 per lesson. `<L>` ∈ `mrt`, `market`, `park`:

| ActivityId | contentKey | Engine | rewardPolicy | grants |
|---|---|---|---|---|
| `english.prea1.taipei.<L>.read_along` | *(dialogue)* | `scorerType: read_along_stt` | `none` | `[]` |
| `english.prea1.taipei.<L>.quiz4` | `quiz4` | `graderType: yes_no` | `none` | `[]` |
| `english.prea1.taipei.<L>.matching` | `vocab` | `scorerType: matching_first_try` | `none` | `[]` |
| `english.prea1.taipei.<L>.wh` | `wh` | `graderType: multiple_choice` | `none` | `[]` |
| `english.prea1.taipei.<L>.cloze` | `cloze` | `graderType: multiple_choice` | `none` | `[]` |

`wh` and `cloze` carry the same `graderConfig` field maps as Zoo (`q`/`a`/`wrong` and
`text`/`answer`/`wrong`). Logical IDs are dotted and carry no filesystem path; `contentPath` lives on
the lesson and is the only join to disk.

Unchanged from Phase 4A: `english.prea1.taipei.<L>.quiz3`, still granting
`english.prea1.taipei.<L>.quiz3.pass`, still `rewardPolicy: none`. No qualification was renamed,
replaced or added — the registry still holds exactly 4.

## 6. STOP review — why no lesson policy was activated

Phase 4B §42 conditions, evaluated per lesson. The result is identical for MRT, Market and Park:

| # | Condition | Verdict |
|---|---|---|
| 1 | Rule A scored set differs in an unsupported way | **TRUE** — it includes level 10 Role-play |
| 2 | A required activity has no server-authoritative implementation | **TRUE** — level 10 |
| 3 | Current frontend grading cannot be reproduced | **TRUE** for level 10 (see below) |
| 4 | Registering it would require new grading semantics | **TRUE** for level 10 |
| 5 | Cannot reach authoritative completion without changing its legacy meaning | **TRUE** |
| 6 | Activation would create new Gold rewards | FALSE |
| 7 | Activation would change territory gate semantics | FALSE |
| 8 | Activation would require new lesson qualifications | FALSE |
| 9 | Content path / identity ambiguous | FALSE |
| 10 | STT / Matching schema differs materially | FALSE — byte-identical schemas |

Conditions 6–10 are all clear, which is why the **activity registration** went ahead in full. Only
the **policy activation** is blocked.

### Why level 10 is not a small job

- **Free-form semantic scoring.** `roleplay/classifier.js` scores an arbitrary typed/spoken sentence
  by token coverage against a route's examples and keywords. The classifier itself is deterministic
  and portable, so this part is not the obstacle.
- **The denominator is client-random.** The score is `passes / turns`, and `turns` depends on the
  path taken through a branching graph selected by `strategies.weighted(...)` using
  `rng: Math.random`. The server cannot reproduce or verify a conversation it did not conduct.
- Making it authoritative therefore means server-owned conversation rounds — the Matching
  round-ownership pattern, but over a stateful multi-turn graph with per-turn classification. That is
  a phase of work, and Phase 4B §2 explicitly excludes roleplay grading.

### The three options, none of which Phase 4B may choose unilaterally

1. **Implement authoritative Role-play** (a Phase 4C). Then all four lessons reach true 7/7 legacy
   Rule A parity. Most faithful, largest scope.
2. **Redefine whole-lesson completion** as "the server-authoritative levels", i.e. formally accept
   the 6-level rule. Activates MRT/Market/Park immediately with zero new engine work — but it is a
   deliberate product redefinition and it retroactively legitimises Zoo's current policy.
3. **Leave the three unactivated** (what shipped). Registration and evidence are complete; the
   completion verdict stays legacy/client-side, exactly as before Phase 4B.

### The same divergence existed in production, on Zoo — and was corrected

Zoo's Phase 3F policy required 6 activities (levels 2,3,4,5,7,9); legacy Rule A for Zoo requires 7.
So the active production policy was already the 6-level rule while the frontend display used the
7-level rule. That was a pre-existing divergence, not something Phase 4B introduced.

**Resolved by retiring it** (option 3 applied to Zoo as well as to the three new lessons). The policy
block was removed from `learning/registry.json` and replaced by
`"retiredCompletionPolicyVersions": [1]`. Persisted learner `lessonCompletions` live in per-account
progress files, not in the registry, so removing the policy does not touch them — they remain exactly
as written, and `progress_view` now reports the lesson as `authoritativeCompletionAvailable: false`
rather than claiming a pass under a rule that was never right.

`tools/validate_content_coverage.py` prints the coverage and the retirement on every run, and
`tests/learning_rule_a_parity_test.py` fails if either half of the finding silently changes.

## 7. Why no frontend change was needed

All three authority paths in `index.html` resolve activities out of the **public registry** at
runtime, by content path — not by any hardcoded lesson list:

```js
activityIdForContent(contentPath, contentKey)  // deterministic graders → /api/learning/attempt
readAlongActivityId(contentPath)               // acts[aid].scored === "stt"
matchingActivityId()                           // acts[aid].scored === "matching"
```

Registering the rows was therefore sufficient to switch MRT/Market/Park onto server authority: the
same code that already drove Zoo now drives them, and each falls back to its documented backendless
practice mode when unauthenticated. `index.html` has a **zero-byte diff** in Phase 4B — which is the
strongest available evidence for §3 (no lesson-specific scoring branches).

## 8. Behaviour after Phase 4B

| Aspect | Behaviour |
|---|---|
| `activityScores` | written on every deterministic attempt, pass **or** fail, latest-wins, for all 15 new activities |
| `activityCompletions` | written only on a pass (≥80) — a failed attempt is evidence, not completion |
| STT | unchanged: server resolves the target sentence, scores it, best-per-sentence, 503 on outage, no full-marks fallback |
| Matching | unchanged: server-owned round, server-selected sample of 5, independent shuffles, firstTry/n, latest-wins |
| Score resolution | the existing `authoritative_activity_score` fan-in (`activityScores` / `sttProgress` / `matchingProgress`) — the policy never learns where a score lives |
| `lessonCompletions` | no lesson can produce one: there is no active policy anywhere. Pre-existing Zoo records under retired `policyVersion: 1` are preserved verbatim and grant nothing |
| Gold | 0 from every new activity. Gold-bearing activities: **1** (`english.prea1.taipei.zoo.quiz3` @ PASS_GOLD 10000) |
| Qualifications | unchanged at 4. Only `quiz3` grants anything |
| `passcnt` | untouched; still the separate legacy Rule B counter |
| Territory gates | unchanged. All five curated gates byte-identical |

## 9. Intentional UX consequence (Phase 4B §23)

**A player can conquer a territory after `quiz3` alone, long before finishing the lesson.** Gates are
deliberately still tied to the Phase 4A activity qualifications, not to whole-lesson completion.
Phase 4B deepens what is *available* behind a gate; it does not make conquest harder.

Turning "quiz3 qualifies attack" into "the whole lesson qualifies attack" is a separate product
decision and was not made here. See [§10](#10-product-observation) for why it now matters more.

## 10. Product observation

- **Study is genuinely deeper.** Each of the three lessons went from one authoritative gate question
  to six authoritative activities — a dialogue read-along, two Yes/No quizzes, word/picture matching,
  WH questions and a cloze. Roughly 25 graded items plus 10 spoken sentences per lesson.
- **The incentive gradient now points the wrong way.** The gate pays out at level 3 of 10. Gold
  (Zoo only), the qualification, and the territory unlock all land on `quiz3`. Levels 4–10 currently
  grant *nothing* an authoritative system recognises — no gold, no qualification, and (for these
  three) not even a lesson completion record.
- **So yes, players will very likely stop at quiz3.** A learner optimising for the map has no
  mechanical reason to continue, and the map is the game's motivator.
- **This is a real design tension, not a bug.** Phase 4B built the evidence layer that makes any fix
  measurable, and deliberately did not resolve it. The options worth weighing next: make whole-lesson
  completion the gate for *later* territories while keeping quiz3 for early ones; attach a
  non-gold reward to completion; or surface authoritative lesson progress in the territory panel so
  the remaining levels are at least visible. All are product decisions.

## 11. Deferred

- **Authoritative Role-play (level 10).** The one blocker to true 7/7 Rule A parity, and the next
  explicit Learning authority blocker. Evidence record: `docs/roleplay-authority-gap.md`. No authority
  model has been proposed yet, by decision.
- **Zoo's replacement policy.** Must take a version other than 1; the validator enforces this.
- **API naming.** `lessonCompleted` (current policy satisfaction) vs `completed` (historical
  monotonic completion) remains ambiguous. Deferred again: with no new policy activated, no new
  consumer was introduced, so an additive rename would have been churn without a caller.
- **Remote Docker STT gate** — unchanged release task, not a development blocker:
  `faster_whisper` import, `ffmpeg` present, Whisper model load, one real transcription,
  authoritative `sttProgress` write, 503 on failure. Cannot be certified in this environment.

## 12. Verification

| Check | Result |
|---|---|
| Regression | 28/28 suites, 0 failed |
| `validate_territory_catalog.py --strict` | VALIDATION OK |
| `validate_learning_registry.py --strict` | VALIDATION OK |
| `validate_progression.py --strict` | VALIDATION OK |
| `validate_content_coverage.py --strict` | VALIDATION OK (5 notes — the documented level-10 gap) |
| Game config fingerprint | `bd773cc3298c14eb` unchanged |
| `git diff` on `game/`, `server.py`, `index.html`, `world-data/` | empty |
| Gold-bearing activities | 1 |
| Active production completion policies | **0** (expected, until level 10 is authoritative) |
| Qualifications | 4 |
