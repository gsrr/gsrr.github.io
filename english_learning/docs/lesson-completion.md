# Whole-lesson completion

> ## Phase 4D — ACTIVE: four Taipei lessons, policy version 2
>
> | | |
> |---|---|
> | Active policies | **4** — Zoo, MRT, Night Market, Park |
> | Type / version / passMark | `average_required_activities` / **2** / 80 |
> | Required activities | exactly **7** per lesson: levels 2, 3, 4, 5, 7, 9, **10** |
> | Reward | `rewardPolicy: "none"` — completion pays **0 gold** |
> | Qualifications | `grants: []` — completion grants **nothing** |
> | Territory gates | **unchanged**, still `quiz3`-based; whole-lesson completion is NOT an attack requirement |
> | `passcnt` | **retired in Phase 7F.2** — nothing writes or reads it; legacy values are inert |
> | Zoo v1 | **retired** (`retiredCompletionPolicyVersions: [1]`); the validator rejects any reuse |
>
> **Rule A is SEVEN levels** — `["2","3","4","5","7","9","10"]`. Level 10 Role-play became
> server-authoritative in Phase 4C (`docs/roleplay-authority.md`), which is what made an exact v2
> possible. Level 10 must be *present*, not *passed*: a 0/10 Role-play with the other six perfect
> still completes the lesson at 86.
>
> ### Two stores, and the difference matters
>
> ```
> lessonCompletions[lessonId]       = {completedAt, policyVersion}       LEGACY, first-ever, untouched
> lessonCompletionHistory[lessonId] = [{policyVersion, completedAt}, …]  NEW, append-only per version
> ```
>
> The legacy record is merged into the history **virtually, at read time**, so a file written before
> Phase 4D is never rewritten. A learner holding a retired-v1 Zoo record who then satisfies v2 keeps
> that v1 record byte-for-byte and gains a *separate* v2 entry.
>
> ### API: current satisfaction vs historical achievement
>
> | Field | Meaning |
> |---|---|
> | `currentPolicySatisfied` | the LATEST scores satisfy the ACTIVE policy — a live evaluation, may go true → false |
> | `historicallyCompleted` | some policy version has been completed, ever |
> | `activePolicyVersion` | the version the registry enforces now (2) |
> | `activePolicyCompleted` | the ACTIVE version has a persisted completion entry |
> | `activePolicyCompletedAt` | when that happened, else `null` |
> | `firstCompletedAt` / `firstCompletedPolicyVersion` | the legacy first-ever completion |
>
> **Deprecated but unchanged** for old readers: `lessonCompleted` (= `currentPolicySatisfied`), and
> progress's `completed` / `completedAt` / `policyVersion` (= the FIRST-EVER completion). New code
> should read the named fields above.

---

## Original Phase 3D inventory (Phase 3D STEP 1–3)

Everything below is the historical "before" record, kept because it is the evidence base. Where it was
later found to be wrong it is annotated in place rather than rewritten — see the level-10 corrections
in §2 and §3.

Inventory of the **existing** whole-lesson rule at commit `08b1328`, before any Phase 3D runtime
change. This is the "before" reference and the evidence for the §46 STOP determination at the end.
Everything here was read out of `index.html` / `server.py`, not inferred from names.

---

## 1. There are TWO different whole-lesson rules today

They are computed from the same data but are **not** the same rule, and they drive different things.

### Rule A — `statusFromScores()` / `lessonStatus()` — the "green light"

```js
function scoredLevelsFor(a) {
  // manifest carries levels (incl. 1 = listen, not scored); scored levels are 2 and above
  if (a.levels && a.levels.length) return a.levels.filter(l => l >= 2).map(String);
  … fallback derives 2,3,4,5 (+6/7/8/9 when the content key exists)
}

function statusFromScores(a, scores) {
  const need = scoredLevelsFor(a);
  const allScored = need.every(l => scores[l] && scores[l].total);      // EVERY scored level attempted
  let avg = null, passed = false;
  if (allScored) {
    avg = Math.round(need.reduce((s,l) => s + scores[l].correct/scores[l].total*100, 0) / need.length);
    passed = avg >= PASS_MARK;                                          // PASS_MARK = 80
  }
  return { need, scores, allScored, avg, passed };
}
```

- **Requires every scored level to have a score.** A missing level ⇒ `passed:false`, `avg:null`.
- Unweighted mean of per-level percentages, then `>= 80`.
- Source of `scores`: `localStorage["score:<user>:<file>"]`, written by `recordScore(level, correct, total)`.

### Rule B — `renderLessonSummary()` — the end-of-lesson screen, and the only thing that writes `passcnt`

```js
const visible = tabs.filter(not hidden && level !== "1");
visible.forEach(t => { const s = lessonScores[lv]; if (s && s.total) pcts.push(Math.round(s.correct/s.total*100)); });
const avg = pcts.length ? Math.round(sum(pcts)/pcts.length) : 0;
const passed = avg >= PASS_MARK;
if (passed && currentArticle && !_passCounted) { _passCounted = true; bumpPassCount(currentArticle.file); }
```

- Averages **only the levels that have a score**, not all scored levels — strictly more lenient than Rule A.
- Runs only when the last level of the lesson finishes.
- In practice the level-lock (`maxUnlockedIndex`: you cannot advance past a level you have not passed
  at ≥80) means a learner who reaches the last level has already scored ≥80 on every earlier level,
  so Rule B nearly always passes by construction.

### What each rule drives

| Consumer | Rule | Effect |
|---|---|---|
| Lesson green/🟢 state, per-level progress counts, dashboards | A | display only |
| `pendingOccupy` auto-jump back to a territory after studying | A | UI routing |
| Teacher/class overview aggregation | A | display only |
| ~~`bumpPassCount` → `POST /api/economy/pass` → `economy.json.passcnt[file]`~~ | B | **removed in Phase 7F.2** — the neutral-claim occupy gate is now the server-verified qualification alone (Phase 7D-0), so the counter, the endpoint and the client-side prerequisite were all retired |
| Gold | — | **none** — `/api/economy/pass` was retired as a gold source in Phase 3A and removed entirely in Phase 7F.2 |
| Qualifications | — | **none** |
| Territory attack requirements | — | **none** (those are activity-scope qualifications) |

**Storage:** both rules read `localStorage` only. `scheduleStudentSave()` uploads an opaque `sdata`
blob to `/api/student/save`, which the server stores **without interpreting it**. So lesson scores do
reach the server, but as untrusted client data — not authoritative state.

---

## 2. Exact semantics of the contributing pieces

| Question | Answer |
|---|---|
| Does level 1 (Listen) count? | **No** — excluded by `scoredLevelsFor` (`l >= 2`). It is auto-pass (`levelPassed("1")` always true). |
| Which levels count? | ~~Every level ≥2 the article declares. Zoo arcs: `[2,3,4,5,7,9]`.~~ **CORRECTED (Phase 4B):** every level ≥2 the article declares, **plus level 10 always**. Zoo/Taipei arcs: `[2,3,4,5,7,9,10]`. `lessons.json` articles: `[2,3,4,5,6,7,8,9,10]`. |
| Does any article include level 10 (roleplay)? | ~~**No.**~~ **CORRECTED (Phase 4B): YES — every lesson.** The `if (lv.indexOf("10") < 0) lv.push("10")` line sits **outside** the if/else in `scoredLevelsFor`, so it applies to declared-level arcs too. Level 10's tab is un-hidden for any lesson with a ≥2-sentence dialogue (all of them), authored scenarios exist for all four Taipei lessons, and `rpOnEnd` calls `recordScore(10, passes, turns)`. The row below was wrong for the same reason. See `docs/taipei-content-depth.md` §3 for the executed proof. |
| Do skipped activities count? | Rule A: a skipped level makes the lesson **not** passed. Rule B: skipped levels are simply omitted from the mean. |
| Retry: replace or best? | **Replace (latest wins).** `recordScore` overwrites `lessonScores[level]` unconditionally, then persists the whole map. No best-of tracking. |
| Threshold | `PASS_MARK = 80`, applied to the rounded mean, not per level. |
| Per-level pass | `levelPassed(lv)` = `Math.round(correct/total*100) >= 80`; level 1 always true. Used for tab locking, not for the lesson rule. |
| Rounding | `Math.round` (half-up) per level and again on the mean. |

---

## 3. Classification of every contributing activity (§4)

For the Zoo lesson (`Pre-A1/taipei/zoo`, scored levels `2,3,4,5,7,9`) and for a full
`lessons.json` article (scored levels `2..9`):

| Level | Activity | Content key | Class | Server-authoritative today? |
|---|---|---|---|---|
| 1 · Listen | listening | *(article text)* | **D** structural | n/a — excluded from the rule |
| 2 · Read Along | pronunciation / shadowing | *(article text)* | **C** non-deterministic | **NO** |
| 3 · Quiz | `yes_no` | `quiz3` | **A** | **YES** (Phase 3A) |
| 4 · Tricky Quiz | `yes_no` | `quiz4` | **A** | **YES** (Phase 3C) |
| 5 · Match | matching | `vocab` | **B** blocked | **NO** |
| 6 · Reorder | `reorder` | `reorder` | **A** | **YES** (Phase 3C) |
| 7 · WH | `multiple_choice` | `wh` | **A** | **YES** (Phase 3C) |
| 8 · Dictation | `dictation` | `dictation` | **A** | **YES** (Phase 3C) |
| 9 · Fill Blank | `multiple_choice` | `cloze` | **A** | **YES** (Phase 3C) |
| 10 · Role-play | roleplay | roleplay pack | ~~**C**~~ **A** | ~~**NO**~~ **YES (Phase 4C)** — server-owned session; it IS part of every lesson's rule (corrected in Phase 4B) |

### Why level 2 is not authoritative (§40)

`POST /api/stt` returns **only a transcript**:

```python
text = transcribe(audio, target)
self._send({"transcript": text, "target": target})
```

The *score* is computed in the browser (`pronScores[idx] = Math.max(pronScores[idx] || 0, pct)`, best
per sentence) and is never sent to or stored by the server. There is also a documented fallback: when
no scoring backend is reachable, level 2 records **completion = full marks**
(`recordScore(2, script.length, script.length)`). So level 2 today is a client-only score with an
environment-dependent fallback. There is no authoritative server STT result to consume.

### Why level 5 is not authoritative (§39)

Unchanged from Phase 3C: the score is `firstTry / n`, a function of the click history. Blocked,
category B. See [grader-migration-report.md](grader-migration-report.md).

---

## 4. Coverage: how much of each lesson is server-authoritative *right now*

| Lesson | Scored levels | Server-authoritative | Missing |
|---|---|---|---|
| `Pre-A1/taipei/zoo` (registered) | 2,3,4,5,7,9 | 3,4,7,9 (**4 of 6**) | 2 (STT), 5 (matching) |
| `A1/001` (partly registered) | 2..9 | 6,8 registered today (3,4,7,9 gradable but not yet registered) | 2, 5 |
| every other lesson | 2..9 or 2,3,4,5,7,9 | none registered | — |

**No lesson currently has 100% of its scored levels server-authoritative**, and none can, while
levels 2 and 5 remain non-authoritative.

---

## 5. `passcnt` (§22)

> **RETIRED — Phase 7F.2 (2026-08-10).** The recommendation below ("keep them separate") was accepted
> and then made moot: Phase 7D-0 moved the neutral-occupy gate to a server-verified qualification, which
> left this counter with no consumer, so Phase 7F.2 removed `passCount`/`bumpPassCount`, the
> `/api/economy/pass` endpoint and the client prerequisite they supported. The analysis below is kept as
> the record of *why* it was never bound to lesson completion — read it as history, not current state.
> Legacy `passcnt` values in already-saved economy files are ignored in place: not read, not migrated,
> not deleted.

`economy.json → <user>.passcnt[<contentPath>]` is an integer counter, incremented by Rule B via the
retired-for-gold `/api/economy/pass`. Its **only** consumer is the neutral-claim occupy bootstrap:

```js
const cleared = pending && pending.key === key && passCount(pending.file) > pending.base;
```

i.e. "has this lesson been passed one more time than when you started this occupy attempt". It is a
**legacy game mechanic keyed by content path**, not a record of lesson completion:

- it counts *events*, not state (it can be 5);
- it is per-room (economy is per-room) while learning state is per-account;
- it is keyed by content path, not canonical `LessonId`;
- it is written from a client assertion (it mints no gold, but the count itself is client-driven).

Binding authoritative lesson completion to `passcnt` would therefore change the meaning of both.
Recommendation is to keep them separate; flagged as §46.7.

---

## 6. §46 STOP determination

| # | Condition | Verdict | Evidence |
|---|---|---|---|
| 1 | Lesson completion depends on **matching** | **TRUE** | level 5 is in `scoredLevelsFor` for every lesson |
| 2 | Depends on **client-only scores** | **TRUE** | both rules read `localStorage`; levels 2 and 5 have no server evidence |
| 3 | **STT evidence** cannot be consumed authoritatively | **TRUE** | `/api/stt` returns a transcript only; the score is client-side, with a "full marks" fallback |
| 4 | **Roleplay** required | ~~FALSE~~ **TRUE (corrected in Phase 4B)** | `scoredLevelsFor` appends level 10 unconditionally, so every lesson's Rule A requires a roleplay score. This did mean Zoo's Phase 3F policy covered only 6 of the 7 legacy levels, so **that policy was retired in Phase 4B**. **Phase 4C then made level 10 server-authoritative**, so all seven levels now have an authoritative source and exact Rule A *can* be reproduced server-side — but production is still at **0 active completion policies**, because activation is a separate approved step. See `docs/roleplay-authority.md`. |
| 5 | Legacy average **cannot be reproduced** from server state | **TRUE** | follows from 1–3 |
| 6 | Choosing required activities changes the meaning of completion | **TRUE** | any server-only subset drops levels 2 and 5 |
| 7 | `passcnt` semantics conflict | **TRUE** | it is an occupy-bootstrap event counter, not lesson state (§5 above) |
| 8 | Backfill would fabricate evidence | **PARTIAL** | activity completions have real `passedAt`; a lesson `completedAt` would have to be derived (max of them) or stamped at migration |
| 9 | Lesson reward would alter the economy | **TRUE if enabled** | any lesson reward is new gold; must stay opt-in |
| 10 | A policy choice would silently make lessons easier/harder | **TRUE** | a server-only policy is a strictly weaker bar than the legacy 6-level average |

**Six conditions are TRUE.** Per §2, §5 and §45 STEP 3, implementation was **halted** pending a
developer decision on the completion policy.

---

# 7. DECISION (developer, Phase 3D)

> **Option 2 — machinery, zero production lessons configured.**
>
> Do NOT redefine whole-lesson completion using only the currently server-verified subset. The
> current semantics depend on Level 2 and Level 5, so excluding them would make lesson completion
> semantically different and potentially easier. Proceed with Phase 3D as an
> infrastructure/capability phase only.

Consequences, all of which are enforced by tests:

- The machinery exists and is fully tested — on **synthetic** content packs.
- **No production lesson carries a `completionPolicy`.** Validator prints
  `lessons with an active completionPolicy: 0/2`.
- A lesson without a policy is **never** completable. There is no fallback to client scores, legacy
  green state, or `passcnt`. A player who passes *every* registered production activity still
  completes zero lessons — asserted directly.
- Both legacy client rules (A and B above) are **unchanged and remain the live UI/gameplay
  behaviour**. Neither is authoritative, and Phase 3D does not claim otherwise.
- `passcnt` is untouched and stays separate (see §5 above).
- No lesson reward is enabled anywhere in production; the Zoo `quiz3` activity reward is unchanged.
- Nothing was backfilled — no historical `completedAt` was invented for anyone.

# 8. The authoritative model (as built)

## Policy — trusted Learning registry only

```jsonc
"lessons": {
  "<lessonId>": {
    "courseId": …, "contentPath": …, "title": …,
    "completionPolicy": {                       // OPTIONAL. Absent ⇒ completion NOT available.
      "type": "all_required_activities",        // the only type implemented
      "version": 1,                             // stored with the completion record
      "requiredActivityIds": [ … ],             // must be non-empty, and belong to THIS lesson
      "grants": [ … ],                          // optional; each must have scope "lesson"
      "rewardPolicy": "none"                    // optional; defaults to "none", NEVER to a paying policy
    }
  }
}
```

The policy lives in the same trusted registry as everything else in the Learning Domain — never in
world-data, never in the Game Domain, never in a client request.

## Evaluation — `learning/completion.py`, pure

```
evaluate(lesson_id, lesson, passed_activity_ids) -> {
    available, completed, policyType, policyVersion,
    requiredActivityIds, completedActivityIds, missingActivityIds
}
```

Its only input is the set of activity ids the player has **authoritatively passed** (canonical +
legacy completion keys merged). `available:false` ⇒ `completed:false`, always. An empty requirement
list is treated as *not* complete rather than vacuously true, so a malformed policy can never grant
anything.

## Persistence — additive, minimal, first-completion-wins

```jsonc
"learning": {
  "activityCompletions": { … },                 // Phase 3A/3B/3C — unchanged
  "qualifications":      { … },                 // unchanged
  "lessonCompletions": {
    "<lessonId>": { "completedAt": 1785…, "policyVersion": 1 }
  }
}
```

Re-evaluation never re-dates an existing record and never rewrites its `policyVersion` — the stored
version is the one the lesson was actually completed under. No `pct` is stored: there is no approved
aggregation rule, so inventing one would be exactly the kind of silent product decision §19 forbids.
The block is only created when a completion actually happens.

## Flow (§14) — derived, never asserted

```
server-graded activity attempt
        ↓ (activity completion updated)
evaluate the parent lesson against authoritative activity state
        ↓ (only if the policy exists and every required activity is passed)
record lessonCompletion once
        ↓
grant configured lesson-scope qualification(s)  ·  resolve configured reward policy
```

There is **no** `POST /api/learning/completeLesson`. The read-only `GET /api/learning/progress`
returns per-lesson `authoritativeCompletionAvailable`, `completed`, `completedAt`, `policyVersion`,
and the required/completed/missing activity id lists — no answer keys, grader config or reward detail.

## Scope discipline

| Granter | May grant |
|---|---|
| an activity | `scope: "activity"` qualifications only |
| a lesson `completionPolicy` | `scope: "lesson"` qualifications only |
| — | `unit` / `course` scope remain **un-earnable**; the validator rejects any such qualification |

# 9. Remaining blockers before a production lesson can be enabled

1. ~~**Level 2 · Read Along (STT)**~~ — **RESOLVED in Phase 3E1.** The server now resolves the target
   sentence from lesson content, scores the transcript with an exact port of the frontend rule,
   persists best-per-sentence evidence per account, and records a normal activity completion at the
   80% threshold. An STT outage produces no evidence at all. See [stt-authority.md](stt-authority.md).
2. ~~**Level 5 · Match (matching)**~~ — **RESOLVED in Phase 3E2.** The server now owns the round: it
   draws the sample, holds the word→picture mapping, observes every click and computes `firstTry / n`.
   See [matching-authority.md](matching-authority.md).

**No evidence blocker remains for Zoo.** Every scored level of the legacy Rule A set
(`2, 3, 4, 5, 7, 9`) now has server-authoritative evidence — see the readiness table in the Phase 3E2
report. Enabling a production `completionPolicy` is nevertheless a **separate, explicitly approved
step**; the production count remains **0** until then.

Once both exist, a lesson's `completionPolicy.requiredActivityIds` can list the full scored set and
authoritative completion becomes semantically equal to the legacy rule — at which point migrating the
UI off Rule A/Rule B is a separate, deliberate step.
