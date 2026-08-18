# Learning → Conquest integration — Phase 3A STEP 1 inventory & trust-boundary audit

*Inventory of the existing learning/pass flow as of commit `11d5ea6`, before any Phase 3A runtime
change. This is the "before" reference and the basis for the STOP-and-ask determination (§41).*

> **Historical — do not read as current state.** Every mention below of `passcnt`, `passCount`,
> `bumpPassCount`, `_passCounted`, `POST /api/economy/pass` and the "occupy-unlock" counter describes a
> mechanism that **no longer exists**. Phase 7D-0 (2026-08-10) made the neutral-claim gate a
> server-verified qualification using the same rule as attack, and Phase 7F.2 (2026-08-10) then removed
> the counter, its endpoint and the client-side Random Challenge prerequisite. For current behaviour see
> `docs/current-game-rules.md`; this file is preserved as the audit that led there.

## A. How courses & lessons are represented

- **Manifest**: `lessons.json` (top-level, fetched once by `initLessons()` → `fetch("lessons.json")`).
  Shape: `{ levels: [ { id, name, icon, articles: [ {id, title, file, scene, levels:[…]} ] } ] }`.
  Per-level role-play "arcs" (`LEVEL_ARCS[lv.id]`, e.g. `tp-zoo`) are appended as extra articles.
- **Level = the closest thing to a "course"**: `lv.id` ∈ `{"Pre-A1","A1","A2","B1"}`. There is **no
  explicit courseId field**; the level id is the grouping.
- **Lesson content**: fetched at runtime from `article.file` (the article text) and
  `article.file + ".json"` (the questions). Content lives as static files under `Pre-A1/`, `A1/`,
  `A2/`, `B1/`, `roleplay/`, etc.

## B. Stable identifiers (STOP §41 #2 → FALSE, ids exist)

- **`article.file`** — path-like, stable, e.g. `"Pre-A1/taipei/zoo"`. This is the identity used
  everywhere: `passcnt` keys, `scoreKey(a.file)`, `progKey(a.file)`, occupy-unlock.
- **`article.id`** — short slug, stable, e.g. `"tp-zoo"`.
Either is a suitable opaque anchor for a qualification mapping. `file` is the more universal key.

## C. Pass / completion state & threshold

- **Threshold = 80%**, computed **entirely client-side** in the quiz summary (`index.html`); the
  score never leaves the browser.
- On a pass the client calls `bumpPassCount(currentArticle.file)` →
  `POST /api/economy/pass { file }` (guarded within one lesson view by `_passCounted`, which resets
  on re-entry).
- **Server-side pass state**: `economy.json → <user>.passcnt = { <file>: count }` (per user, **per
  room**). Used by the neutral-claim occupy gate (`passCount(file) > base`, client-side check).
- **Cloud snapshot**: `POST /api/student/save|load` stores an **opaque client blob** (`sdata`) in the
  per-account progress file — the server does not interpret it.

## D. `/api/economy/pass` behavior + PASS_GOLD (§5 trust-boundary audit)

```
_handle_economy_pass:  body = { file }   (any string; NOT validated against the manifest)
    passcnt[file] += 1
    gold += PASS_GOLD            # PASS_GOLD = 10000
    save
```

| Question (§5) | Answer |
|---|---|
| What does the client send? | Just `{ file }` — an arbitrary string. |
| What does the server verify? | **Nothing.** Only that the caller is logged in. |
| Can arbitrary lesson IDs be submitted? | **Yes** — no manifest/registry check. |
| Can repeated passes generate Gold? | **Yes** — `+10000` **every call**, unbounded. |
| Does server-side completion state exist? | Only `passcnt` counts (client-driven), no score/evidence. |
| Are duplicate reward claims prevented? | **No** — not idempotent; `_passCounted` is client-only. |
| Frontend vs backend authority for "passed"? | **Frontend** decides the 80% pass; server trusts it. |

## E. Learning UI navigation (STOP §41 #5 → FALSE)

`pendingOccupy = { file, reopen() }` already routes "study a lesson → return to the originating
territory panel" (used by the neutral-claim occupy flow). A locked-territory "Study requirement →
lesson → back to map" path can reuse this; no new UI framework needed.

## F. World-data generator ownership contract (STOP §41 #7 → FALSE)

`tools/gen_territory_catalog.js` has an explicit **`DESIGNER_FIELDS`** allowlist preserved on
`--merge` (never clobbered): `displayName, localizedNames, gamePopulation, populationSource,
terrainType, settlementType, features, adjacentTerritoryIds, economy, quests, ai, events`. A new
`requirements` (designer-owned) field slots cleanly into this list; the validator
(`tools/validate_territory_catalog.py`) and hardening tests extend alongside.

## G. Best flow for the vertical slice

The standard **quiz "pass ≥80%"** flow, keyed by `article.file`, already has server-recorded state
(`passcnt`) and existing back-navigation (`pendingOccupy`). It is the natural completion trigger — its
only weakness is that grading is client-side (see H).

## H. STOP-AND-ASK determination (§41)

| # | Condition | Verdict | Evidence |
|---|---|---|---|
| 1 | Completion entirely client-asserted, no server-verifiable pass evidence | **TRUE** | 80% grading is 100% client-side; `/economy/pass` receives only `{file}`, no score/answers. |
| 2 | No stable lesson/course identifiers | FALSE | `article.file` / `article.id` are stable (§B). |
| 3 | Qualification persistence needs destructive migration | FALSE | Additive per-user key/file; no migration. |
| 4 | PASS_GOLD trivially repeatable & integration worsens it | **TRUE** | `+10000` per call, no idempotency/validation; attaching qualification to it → self-grant any qualification by POSTing any file. |
| 5 | Learning UI can't return to territory | FALSE | `pendingOccupy.reopen()` exists (§E). |
| 6 | Incompatible pass semantics | FALSE | Uniform 80% pass concept. |
| 7 | Requirement config conflicts with generator ownership | FALSE | `DESIGNER_FIELDS` allowlist supports a new designer-owned field (§F). |

**Conditions #1 and #4 are TRUE** — the exact trust boundary the phase flagged (§5/§18/§38/§39/§41).

## I. What this means for Phase 3A

The phase goal is a **server-authoritative *qualification*** layer, which is achievable **without**
server-side grading:
- Qualification **storage** and **enforcement** (`can_attack`) become server-authoritative; a client
  cannot directly write qualification state.
- The completion **trigger** stays client-asserted — the *same trust level as the existing
  `PASS_GOLD`* — which must be **documented honestly, not disguised as verified** (§5 "do not invent
  fake security"). True server-side grading = moving quiz evaluation into the backend = a Learning
  Engine change, explicitly **out of scope** (§3).
- Per §39, qualification granting must **not** be bolted onto the unsafe generic `/api/economy/pass`.
  Use a **narrow, idempotent completion endpoint** instead.

See the STEP 1 report / recommended design below (awaiting developer go-ahead before implementing the
mutation flow, per §5 "report findings before changing semantics").

---

# Phase 3A — as-built (rollout A, approved design)

Scope note: Phase 3A migrates **one activity type on one lesson** to a server-verified completion
path. It is deliberately NOT a migration of all learning activity types, and NOT a redefinition of
whole-lesson completion.

## 1. What the qualification represents — an ACTIVITY, not a whole lesson

`english.prea1.taipei.zoo` means **"passed the `quiz3` Yes/No reading-comprehension activity of
`Pre-A1/taipei/zoo`, server-verified"**. It does **not** assert that the whole lesson was completed.

The pre-existing whole-lesson rule is untouched and still lives in the client
(`index.html`: average of all scored activities ≥ `PASS_MARK` 80 → green/pass →
`bumpPassCount`/`passcnt`). Two independent notions now coexist:

| Concept | Where decided | Where stored | Trust |
|---|---|---|---|
| Whole-lesson pass (green light, occupy-unlock passcnt) | client (average ≥ 80%) | `economy.json → passcnt` | client-asserted (unchanged) |
| Activity completion (`quiz3`) | **server** (re-grades against the lesson JSON) | `progress → learning.activityCompletions` | **server-verified** |
| Qualification (conquest gate) | **server** (granted only by the above) | `progress → learning.qualifications` | **server-authoritative** |

A future authoritative *whole-lesson* completion can be added as a separate key
(e.g. `learning.lessonCompletions`) **without changing the meaning of any record written today**.

## 2. PASS_GOLD trigger semantics after the change

`PASS_GOLD` (**10000, amount unchanged**) is now minted at exactly one place: the first server-verified
pass of a **registered** activity, via `POST /api/learning/attempt`.

```
client POSTs its ANSWERS (never passed/score/qualification/gold)
        ↓
registry whitelist: (lessonId, activity) must map to a qualification
        ↓
server re-grades against the authoritative <lessonId>.json  (grading.PASS_MARK = 80)
        ↓ passed
grant qualification (idempotent)  +  PASS_GOLD once, iff activityCompletions[key].rewarded is falsy
```

**This is a temporary Phase 3A vertical-slice reward policy.** PASS_GOLD here is the one-time reward
for completing *the designated conquest requirement*, not the generic whole-course/whole-lesson
reward model. When authoritative whole-lesson completion lands, the reward trigger is expected to
move; the qualification IDs and the persistence schema are designed to survive that move unchanged.

Idempotency: replaying a passing attempt returns `{passed:true, grantedNow:false,
alreadyCompleted:true, rewarded:false, gold:null}` and mints nothing. `earnedAt` and `passedAt` are
frozen at the first pass. Scope: the qualification/`rewarded` flag is **per account** (so the reward
cannot be re-farmed by switching rooms), while the gold itself lands in the player's current room
economy, consistent with the existing per-room economy model.

## 3. Learning flows that TEMPORARILY stop granting PASS_GOLD

**All of them except the migrated slice.** Concretely, every whole-lesson pass across every level and
lesson — the entire `bumpPassCount` → `/api/economy/pass` path — now grants **0 gold**. Only
`Pre-A1/taipei/zoo#quiz3` pays PASS_GOLD, and only on its first verified pass.

This is the accepted cost of rollout A: no compatibility bridge, no weaker fallback. Un-migrated
lessons regain PASS_GOLD as they are migrated to server-verified completion.

Unaffected: hourly population gold, `DEFEND_GOLD`, `ATTACK_FAIL_GOLD`, building/recruit/tech costs.

## 4. Remaining client-asserted reward paths — none

No endpoint mints gold from a bare client assertion. `/api/economy/set` accepts only `troops` (it
cannot set gold or population). `/api/territory/attack-result` was already retired as non-authoritative.
Gold now changes only through: server-resolved battles, server-side hourly growth, server-priced
purchases, and the server-graded learning attempt. There is no fallback path.

## 5. Can `/api/economy/pass` still mint Gold? — No

It is retired **as a gold source and can never grant a qualification**. It still exists and still
increments `economy.json → passcnt`, because that counter feeds the *neutral-claim occupy* bootstrap
gate, which Phase 3A intentionally does not tie to learning. Its response no longer contains a `gold`
field and carries `legacy: true`. Posting arbitrary/forged `file` values is now worthless.

## 6. Activity-completion persistence schema

Per account, in the user's progress file (`/data/progress/<hash>.json`):

```jsonc
"learning": {
  "activityCompletions": {
    "Pre-A1/taipei/zoo#quiz3": {   // key is "<lessonId>#<activity>" — never a bare lessonId
      "passedAt": 1753848000,      // int epoch seconds, FIRST pass (never re-dated)
      "pct":      100,             // server-computed percentage of the latest pass
      "rewarded": true             // PASS_GOLD already paid for this activity → one-time
    }
  }
}
```

## 7. Qualification persistence schema

```jsonc
"learning": {
  "qualifications": {
    "english.prea1.taipei.zoo": { "earnedAt": 1753848000 }   // int epoch seconds, first grant
  }
}
```

Both blocks are additive (no migration). Qualification is **player state**, independent of territory
ownership, army and room — a player who loses every territory keeps their qualifications.

**Registry** (`learning/registry.json`, Learning-Domain content-pack config, never imported by the
Game Domain): `qualificationId → {lessonId, activity, title}`. The ID is stable across UI text
changes; `title` is the only thing that may change. `GET /api/learning/registry` publishes
`{id: {lessonId, activity, title}}` and no answer keys.

**World-Domain requirement** (designer-owned, on the territory, preserved by the generator's
`DESIGNER_FIELDS` allowlist and checked by the validator):

```jsonc
"requirements": { "attackQualificationIds": ["english.prea1.taipei.zoo"] }
```

The Game Domain (`game/conquest.py`) sees only opaque strings — no "english" special-casing.

## 8. Attack-unlock end-to-end test result — PASS

`tests/learning_gate_test.py` — **17/17 pass** (pure gate + real HTTP against the real Taipei catalog):

- **UNLOCK (the headline case)**: `taipei:wenshan → taipei:daan` returns **403
  `qualification_required`** with `missingQualificationIds:["english.prea1.taipei.zoo"]` and zero state
  change; after passing `quiz3`, the *same* attack returns 200 and transfers ownership.
- **Side-by-side control**: `taipei:wenshan → taipei:xinyi` (no requirement) conquers normally with an
  empty learning state — the gate is targeted, not global.
- **Forge-proof**: an attempt carrying wrong answers plus `passed:true, pct:100, score:100,
  qualification:…, gold:999999` is graded 0% — no qualification, no gold.
- **Idempotent**: 4 replays of the passing attempt → 0 extra gold, `earnedAt`/`passedAt` unchanged.
- **Gate ordering**: source / target / same / adjacency / squad / garrison are all still decided
  *before* the learning gate; a raising `attack_requirements` degrades to unrestricted (fails open, no 500).
- **AI policy**: `require_qualifications=False` bypasses only this layer — `ai_move()` conquers the
  gated `taipei:daan` while still obeying source ownership, adjacency, source garrison and the
  canonical Battle Engine; it cannot bypass ownership or conjure troops.
- **Retired endpoint**: `/api/economy/pass` still counts `passcnt`, mints 0 gold for real *and*
  arbitrary lesson ids, and grants no qualification.
- **Hardening**: unregistered lesson / ungradable activity / `../server` / `../../etc/passwd` /
  missing answers / anonymous caller are all refused.
- **Scope**: qualification survives losing every territory, crosses rooms, never leaks between players.

Full suite re-run: `adjacency 8, catalog_hardening 7, game_battle 5, game_conquest 17,
game_domain 5, learning_domain 3, learning_gate 17, territory_catalog 10, territory_identity 12`,
all 5 node test files, and `validate_territory_catalog.py → VALIDATION OK`.

`tests/game_conquest_test.py`'s adjacency block now opts out of the learning layer
(`require_qualifications=False`) so that a designer adding a requirement can never masquerade as an
adjacency failure, plus two new assertions pinning that the two layers stay orthogonal.

## 9. Manual Taipei vertical-slice — see §Manual test script (not executed here)

The automated E2E above drives the identical server endpoints, and the frontend wiring was verified
statically (inline scripts parse; `world-data/territories/*.json` is fetched raw by
`loadTerritoryCatalog()`, so `requirements` reaches `TERR_CATALOG.terrById`). A browser click-through
was **not** performed. Steps to reproduce manually:

1. Teacher: create + start a room on map **Pre-A1**; a student logs in and takes `taipei:wenshan`
   with a garrison; ensure `taipei:daan` and `taipei:xinyi` are enemy-held.
2. Click **taipei:xinyi** → normal attack panel (source picker + squad) → attack works. *(control)*
3. Click **taipei:daan** → 🔒 lock panel listing "Taipei · At the Zoo — Yes/No reading
   comprehension" with a **📖 Study** button.
4. Press Study → lands on the Zoo lesson → complete **Level 3 (Yes/No)** at ≥80%.
5. Expect the toast **"✅ Learned: … — territory unlocked!"** and gold **+10000** once.
6. Return to the map, click **taipei:daan** → the normal attack panel now renders; the attack succeeds.
7. Retake Level 3 → still passes, but **no additional gold** (idempotent).
8. Complete any other lesson end-to-end → green pass as before, **no gold** (expected under rollout A).

---

# Phase 3B — generalization (as-built)

Phase 3A's one-off mapping is gone; the architecture is now content-neutral. The full model —
identity hierarchy, registry schema, reward-policy trust boundary, grader dispatch, study navigation,
validation and the cross-domain decision — lives in **[docs/learning-model.md](learning-model.md)**.
This section records only what changed relative to Phase 3A and what is *deliberately* still narrow.

## What generalized

| Phase 3A | Phase 3B |
|---|---|
| `registry.json` = `{qid: {lessonId, activity, title}}` | pack → course → (unit) → lesson → activity → qualification sections |
| lesson id **was** the content path | logical `lessonId` **separate from** `contentPath` |
| no activity id | canonical `activityId`, e.g. `english.prea1.taipei.zoo.quiz3` |
| grading gated on `activity in ("quiz3","quiz4")` | dispatch on registry `graderType` (`GRADERS`) |
| one activity → one qualification | `grants: [...]`, many-to-many throughout |
| `PASS_GOLD` hardcoded in the HTTP handler | `rewardPolicy` name → server-owned allowlist → game config |
| completion key `Pre-A1/taipei/zoo#quiz3` | canonical `activityId`, legacy key still read |
| `server.py` did resolution + content + grading | `LearningService` facade; handlers delegate |
| lock UI assumed a single requirement | generic renderer: 0 / 1 / N, one Study entry per missing |
| study nav found the article from `lessonId` | from qualification metadata (`studyTarget`) |
| filesystem read guarded by traversal check | registry allowlist + shape + realpath containment |

## What is deliberately still narrow

- **One grader** (`yes_no`). `wh` / `match` / `reorder` / `dict` / `cloze` are **not** migrated (§30) —
  that is Phase 3C.
- **One earnable scope** (`activity`). `lesson` / `unit` / `course` are reserved in the schema and the
  validator *rejects* granting them, so no aggregate completion can be faked (§7).
- **One production requirement** — the Taipei slice. Many-to-many is proven in domain tests, not by
  inventing curriculum (§18, §36).
- **ALL semantics only** — no OR groups (§6).
- **No pack install infrastructure** — model compatibility only (§19).

## Reward semantics — unchanged from Phase 3A

`PASS_GOLD` is still `10000`, still granted only by a server-verified pass of a registered activity,
still once per activity, still not mintable from `/api/economy/pass`, and still a **temporary
vertical-slice reward policy** rather than the generic whole-lesson/whole-course model. Phase 3B only
moved *where the number comes from* (game config via a named policy) — not the amount, the trigger or
the idempotency.

## Migration report

Nothing was rewritten or discarded. See learning-model.md §14 for the table; the behaviour is proven
by `tests/learning_gate_test.py` ("E2E backward compat") and `tests/learning_domain_test.py`
("service legacy"): a pre-3B record keeps its original `passedAt`, is left byte-for-byte intact, and
its `rewarded` flag prevents a second payout under the new canonical key.

## Test inventory

| File | Covers |
|---|---|
| `tests/learning_identity_test.py` (10) | §31 identity, §32 registry validation, lookups, public view |
| `tests/learning_domain_test.py` (10) | §33 generic grader via a synthetic non-English pack, §34 qualifications, §37 reward authority, content allowlist |
| `tests/learning_requirements_test.py` (6) | §35 0/1/2+ matrix, §36 many-to-many, §20 Game-Domain content-independence, §17 boundary |
| `tests/learning_gate_test.py` (19) | §39 the original slice end-to-end, §13 legacy request shape, §42 legacy record compat, endpoint hardening, AI policy |
| `tests/learning_frontend.test.js` (6) | §38 0/1/N requirement rendering, metadata-driven study nav, client submits no authority |
| `tools/validate_learning_registry.py` | §26 registry validation, §27 cross-domain report (`--strict`) |

---

# Phase 3D — authoritative whole-lesson completion (capability only)

Full inventory, the decision record and the model are in
**[docs/lesson-completion.md](lesson-completion.md)**. The short version:

The current whole-lesson rule (there are actually **two** client rules — `statusFromScores` for the
green light, `renderLessonSummary` for `passcnt`) depends on **Level 2 (STT)** and **Level 5
(matching)**, neither of which has server-authoritative evidence. Declaring a lesson complete from the
server-verified subset alone would be a *different and easier* rule, so the approved decision was to
build the machinery and configure **zero production lessons**.

| | Phase 3C | Phase 3D |
|---|---|---|
| Lesson completion | client-only (legacy, two rules) | authoritative model exists, **0 lessons enabled** |
| Persistence | `activityCompletions`, `qualifications` | `+ lessonCompletions` (created only on real completion) |
| Qualification scopes earnable | `activity` | `activity`, **`lesson`** (registry-configured only) |
| Rewards | activity policy | `+ lesson completion policy` — **none enabled in production** |
| Read API | `/api/learning/{registry,state}` | `+ GET /api/learning/progress` (read-only) |
| Role-play (Phase 4C) | client-side engine, client score | `POST /api/learning/roleplay/{start,respond}` — server-owned session |
| Lesson completion (Phase 4D) | client Rule A display only | four ACTIVE v2 policies; `currentPolicySatisfied` / `historicallyCompleted` / `activePolicy*` / `firstCompleted*` on attempt + progress |
| `passcnt` | occupy-bootstrap counter | **unchanged, deliberately kept separate** |
| Legacy client rules | live | **live and unchanged** — Phase 3D does not claim they are authoritative |

There is deliberately **no** client mutation route (`POST /api/learning/completeLesson` does not
exist); completion is derived from server state after an authoritative activity attempt. Nothing was
backfilled, and no historical `completedAt` was invented.

**Before a real lesson can be enabled:** authoritative evidence for Level 2 (STT scoring persisted
server-side) and Level 5 (matching click-stream evidence). Both explicitly out of scope here.


---

# Phase 3E1 — Read-Along / STT becomes server-authoritative

Full inventory, the exact ported formula and the design are in
**[docs/stt-authority.md](stt-authority.md)**. Summary of the change:

| | Before | After |
|---|---|---|
| Target sentence | client sent `?text=` | **server** resolves it from lesson content by `sentenceIndex` |
| Per-sentence score | computed in the browser | **server** (exact port of `pronWords`/`showPron`) |
| Level 2 pct | browser | **server** `activityPct` |
| Persistence | `localStorage` only | `learning.sttProgress`, per account, room-independent |
| Retry | best-per-sentence (browser memory) | best-per-sentence (**server state**) — rule unchanged |
| Backend outage | recorded **full marks** | **503, zero evidence** — no score, completion, qualification or reward |
| Reward / qualification | — | still **none** (`rewardPolicy: "none"`, `grants: []`) |

`/api/stt` gained an authoritative mode (`activityId` + `sentenceIndex` + token); `?text=` is ignored
there. The legacy target-less mode still exists and is what roleplay uses — it creates no state.

The full-marks fallback survives **only as a local, non-authoritative convenience** for the backendless
GitHub Pages deployment, so learners there are not trapped by the level lock. It can never become
server evidence.

Production lesson `completionPolicy` count is still **0**: Level 5 matching remains the last blocker.


---

# Phase 3E2 — Matching becomes server-authoritative

Detailed design in **[docs/matching-authority.md](matching-authority.md)**. What changed:

| | Before | After (backend mode) |
|---|---|---|
| Sample | client `shuffle(vocab).slice(0,5)` | **server** draws it (injectable RNG; deterministic in tests) |
| Word→picture mapping | client | **server only** — never sent to the client |
| first-try state | browser memory | **server** round state |
| Score | client `firstTry / n` | **server** `POST /api/learning/matching/attempt` result |
| Persistence | `localStorage` | `learning.matchingProgress`, per account, latest-wins |
| Round identity | none | opaque `roundId`, stored inside the owner's own state |

`POST /api/learning/matching/start` returns `{roundId, items[{itemId, word}], choices[{choiceId, pic}],
total}` — **no** pairing. `POST /api/learning/matching/attempt` takes `{roundId, itemId, choiceId}`
and returns `{status, expected, total, scored, completed}` plus `result` on the final click.

Deliberately preserved, unchanged:

- `n = min(5, len(vocab))` (always 5 for shipped content) and the independent picture shuffle;
- strictly sequential matching, and a wrong click costing the current word's point permanently;
- clicking an already-matched picture is **inert**, not a wrong attempt;
- **the last word can never be missed** (every other picture is already matched), so the theoretical
  score floor is 1/5 = 20%, not 0. This artifact is intentionally kept — fixing it would be a product
  change, not an authority migration;
- restart re-rolls the sample and the score is **latest-wins**, so a learner may retry until clean.
  Documented trust implication: the score proves "a clean round happened", not "clean first time".

Choice identity is the **button position** (`<roundId>#choice:<pos>`), not the emoji, so the 4 lessons
whose vocab reuses a glyph stay unambiguous. Item identity is `<activityId>#item:<vocabIndex>` —
derived from content, requiring no lesson-JSON change.

**Backendless mode** (GitHub Pages / not logged in / lesson not registered) keeps the legacy local
implementation, clearly labelled as local practice. Its score is never uploaded and can never become
### Level 10 Role-play (Phase 4C)

| Aspect | Before | After |
|---|---|---|
| Conversation graph | fetched/derived in the browser | server-loaded from `scenarioPath`, validated, version-hashed |
| Current node | client `rpEng.current` | server `session.currentNodeId` |
| Branch choice | client `Math.random` over weights | server RNG, same weighted algorithm |
| Classification | client `RP.classifiers.local` | exact Python port, thresholds server-owned (0.5 / 0.2) |
| turns / passes | client counters | server counters; `turns` still counts EVERY submission |
| Score | client `recordScore(10, passes, turns)` | server `roleplayProgress`, latest-wins |

`POST /api/learning/roleplay/start` takes `{activityId}` and returns
`{sessionId, prompt:{nodeId,text,gender,objective}, turn, passes, completed, you, npc, title}` — one
node at a time, and **no** routes, keywords, examples, weights or next_nodes.
`POST /api/learning/roleplay/respond` takes `{sessionId, response, seq}` and returns
`{result, hint, prompt, turn, passes, completed}` plus `score` on completion. `seq` is the turn the
client believes it is answering; a mismatch is refused as `stale_turn` without counting, which is what
makes duplicate submits and two-tab races safe. Everything else a client might send —
node, graph, version, turns, passes, score, completed, result, thresholds, rng, reward,
qualification, policyVersion — is ignored.

Backendless mode keeps the legacy local engine as practice only, chosen *before* the session starts;
a mid-session backend failure shows a retryable error and never invents a turn or a local score.

`matchingProgress`. A *backend failure* is handled differently from backendless mode: the UI shows a
retryable state and never silently falls back to local authoritative scoring.

Reward and qualification neutrality: both matching activities use `rewardPolicy: "none"` with no
grants, so gold-bearing activities remain **1/10** and production `completionPolicy` count remains **0**.

# Phase 9B — curriculum lesson != conquest gate (the A1/001 pilot)

Phase 9A inventoried **57 complete content units** on disk (24 Pre-A1 + 12 A1 + 12 A2 + 5 B1 + 4
Taipei) but found only the **4 Taipei lessons** completable. `english.a1.core.001` was registered
with no `completionPolicy` — so invisible on every surface — and carried A1/**002**'s title
("My Weekend") while pointing at `A1/001` ("Yesterday at the Park").

9B migrates that ONE lesson as the template for the other 52. It changes registry metadata only.

## The decoupling this establishes

`completionPolicy` (lesson), `rewardPolicy` (activity/lesson/course) and `grants` (activity) are
three **independent** registry fields. Therefore:

- A lesson can be **completable** and pay **both** learning rewards while granting **no
  qualification**. Completion, mastery and reward do NOT imply a world unlock.
- A **qualification is an optional game/world consequence**, not a property of learning. Only
  `world-data/territories/*.json` decides what a qualification unlocks, and it names qualification
  ids — never lesson ids.
- A **CEFR course is not a game map.** `english.a1.core` is curriculum; the China map is a game
  board. They are keyed alike today only by the client's `GEO_MAPS` convention, which 9B does not
  touch and future migrations must not deepen.

The four Taipei gates each grant a qualification because five Taipei territories are gated on them.
The A1/001 gate grants nothing, and that is the point: it is curriculum, not a gate.

## As-built

| | Taipei x4 | A1/001 pilot |
|---|---|---|
| completion policy | `average_required_activities` v2, 7 activities | `average_required_activities` v1, 5 activities |
| gate activity | `<lesson>.quiz3` | `english.a1.core.001.quiz3` |
| gate reward | `standard_activity_pass` (PASS_GOLD) | `standard_activity_pass` (PASS_GOLD) |
| mastery reward | badge + `lesson_mastery_gold` (MASTERY_GOLD) | badge + `lesson_mastery_gold` (MASTERY_GOLD) |
| qualification granted | 1 each | **none** |
| world consequence | 5 gated territories | **none** |

Invariant transition: gold-bearing activities **4 -> 5**, active completion policies **4 -> 5**,
qualifications **4 -> 4**, world-data **unchanged**. Amounts stay server-configured; the registry
names policies and never states a number (§15).

## Representation rule

Only **migrated, authoritative** lessons may be presented as available modern lessons. The A1
campaign therefore shows `0 / 1 Lessons Mastered`, not `1 / 12` — the other 11 A1 units are not yet
registered, and claiming them would be untrue.

The remaining **53** generic units are **content awaiting registry migration, not dead content**.
They are still live today as the checkpoint question bank: `buildExamPool()` fetches all 57
`<contentPath>.json` files for their `cloze` items (Pre-A1 112 / A1 48 / A2 48 / B1 20 questions).
Deleting that content would empty the checkpoints, so content deletion and legacy-UI deletion are
separate decisions.

# Phase 9B.1 — migration infrastructure (no content migrated)

9B migrated one lesson and had to edit **twelve** maintained test files, because each duplicated the
current census in its own Python list. With 52 units still to migrate that cost is O(files) per
phase. 9B.1 removes it, fixes a reward-validator blind spot, and records the template 9C will follow.
No lesson was registered, no reward or qualification changed, world-data and lesson content are
byte-identical.

## Registry-derived invariant testing

`tests/curriculum_expectations.py` draws one line:

- **DERIVED** — which activities pay, which lessons are completable, which activities grant a
  qualification. These populations grow every time curriculum is migrated, so a test that hardcodes
  them asserts today's inventory rather than a product rule.
- **FIXED** — the four Conquest qualification ids and the five territories that require them. That
  *is* the product contract: it is the entire coupling between learning and the game world, and
  world-data names those exact strings. Adding a qualification should cost a deliberate test edit.

Two helpers assert semantics over whatever population exists: `assert_completion_model()` (policy
type is implemented, the pass mark is the single global threshold, `requiredActivityIds` is non-empty,
deduped, registered and belongs to that same lesson) and `assert_reward_model()` (paying == declaring,
every gate pays exactly PASS_GOLD through the one shared policy, non-gates pay nothing, every gate's
lesson is completable, every completable lesson carries the badge + at most one economic mastery
reward, and qualifications are exactly the four Conquest ones).

`tests/migration_invariants_test.py` proves those guards can actually fail: eight negative controls
mutate the registry and require rejection. The deliberate loosening is scoped precisely — a new
activity that *declares* the gate policy is accepted (that is what migration looks like), while a
curriculum gate that *grants a qualification* is rejected.

## Reward-policy validator discovery

A lesson carries a **list** of reward policies. `lesson_reward_policy_of()` returns the **first**, and
the Taipei lessons declare `["lesson_mastery_badge", "lesson_mastery_gold"]` — cosmetic first. Both
the validator and `learning_rewards_test.py` collected usage through that singular accessor, so
`lesson_mastery_gold` was reported *"inert (unreferenced)"*, `economic policies in use` listed only
`standard_activity_pass`, and the "did a lesson start paying GOLD" warning could never fire — while
four lessons had been paying MASTERY_GOLD since Phase 7C.2. `ACTIVE_POLICY_IDS` was stale for the
same reason: nothing ever detected the reference.

Fixed by collecting usage **per scope** from `lesson_reward_policies_of()` (plural), reporting
`REFERENCED by activity xN, lesson xN, course xN`, validating that each policy is attached only where
its own `scopes` allow, and adding `lesson_mastery_gold` to the production allowlist. The three truly
unused policies (`campaign_complete_gold`, `campaign_profile_frame`, `lesson_mastery_boost`) still
report inert and remain unreferenceable.

## The Phase 9C migration template (descriptive — no generator yet)

Derived from the A1/001 pilot. For each unit `<LEVEL>/<NNN>`:

| Field | Value |
|---|---|
| lesson id | `english.<pack>.<course>.<NNN>` (e.g. `english.a1.core.002`) |
| title | `<LEVEL> · <NNN> <the title in lessons.json>` — **verify against the content file** |
| contentPath | `<LEVEL>/<NNN>` |
| courseId / contentPack | `english.a1.core` / `english.a1` |
| activities | `read_along` (stt), `quiz3` (yes_no), `matching` (vocab), `reorder`, `dictation` |
| PASS_GOLD gate | `<lesson>.quiz3`, `rewardPolicy: standard_activity_pass`, `grants: []` |
| other activities | `rewardPolicy: "none"`, `grants: []` |
| completionPolicy | `average_required_activities`, `version: 1`, `passMark: 80` |
| requiredActivityIds | the five above, in canonical tab order |
| lesson rewardPolicy | `["lesson_mastery_badge", "lesson_mastery_gold"]` |
| lesson grants | `[]` |
| qualification | **none** — ordinary curriculum grants no world unlock |
| world-data | **no change** |

Per unit this yields PASS_GOLD 160 + MASTERY_GOLD 640 = 800, one new gold-bearing activity and one
new completion policy, and **zero** new qualifications.

## A1 activity-shape findings

All twelve A1 units have a text file, a role-play scenario, and `quiz3`(5), `quiz4`(5), `wh`(5),
`cloze`(4), `reorder`(4), `dictation`(4); `clozeType` is `category` throughout. The only variation is
`vocab` item count — 10 (001), 7 (002), 6 (003-012) — which is a content quantity, not a structural
variant. Per-item key shapes are identical to the registered Taipei reference for every grader-
relevant block, every `quiz3`/`quiz4` answer is `Yes`/`No`, and every `wh`/`cloze` item carries
distractors. **A1/002-012 can therefore use one template mechanically, and `quiz3` is available for
all twelve.**

The template registers 5 of the 8 available blocks. `quiz4`, `wh` and `cloze` are deliberately left
unregistered: `cloze` is the checkpoint question source (`buildExamPool()`), and widening the required
set is a separate product decision to take once for all 53 units, not per lesson.

## Ordinary curriculum is qualification-free

A paying gate is either a **world gate** (grants a Conquest qualification; today the four Taipei
`quiz3` activities) or a **curriculum gate** (grants nothing, still pays PASS_GOLD; today only
A1/001). The invariant is expressed over the derived split, never over a named list, so future A1,
A2, B1 and Pre-A1 lessons need no test edit merely for being qualification-free.

## Two open UI truthfulness items (documented, not fixed)

**Course vs Campaign.** `index.html` appends the literal word `" Campaign"` to the server course
title at four sites (`6335`, `6341`, `5915`, and `SCOPE_GROUPS` at `5901`). Course metadata carries
only `contentPackId`, `title` and `rewardPolicy`, and the campaigns view emits only
`title/lessonIds/completed/...`, so nothing distinguishes curriculum from campaign. The recommended
model is for the **client to derive the term from world consequence** — a course whose lessons grant a
qualification that world-data requires is a Campaign; otherwise it is a Course. That needs no new
registry field and matches the 9B definition, but it does define a user-facing concept across four
sites, so it belongs to a later UI phase rather than an infrastructure one.

**Pre-A1 "24 lessons".** `index.html:4280` takes `n = lv.articles.length` from `lessons.json` (24 for
Pre-A1) and `4294` renders `n + ' lessons'` whenever nothing is mastered, while `tracked` — the count
of articles with an authoritative row — is 0. The card therefore advertises 24 lessons none of which
is an openable modern lesson, and `lv.articles` does not even include the four Taipei lessons that
are. The truthful form is to distinguish available *readings* from migrated *lessons*, e.g.
`24 readings · 0 migrated`, deriving the second number from the registry. One line, but it is a
user-facing copy decision, so it is recorded here rather than changed.

# Phase 9C — the A1 course is migrated (12 authoritative curriculum lessons)

A1/002-012 were registered using the Phase 9B.1 template verbatim. **Registry metadata only** — no
server, client, world-data, `lessons.json` or content change.

| | Before | After |
|---|---|---|
| registered lessons | 5 | **16** (Taipei x4 + A1 x12) |
| registered activities | 33 | **88** |
| gold-bearing activities | 5 | **16** |
| active completion policies | 5 | **16** |
| **qualifications** | 4 | **4** |
| courses emitting a campaign | 2 | 2 |
| A1 authoritative lessons | 1 | **12** |

Each A1 lesson: five authoritative activities (`read_along`, `quiz3`, `matching`, `reorder`,
`dictation`), `average_required_activities` v1 at passMark 80, `quiz3` as the only paying gate
(`standard_activity_pass`), mastery paying the badge + `lesson_mastery_gold`. **Worth 800 total
(160 + 640), and granting nothing.**

`quiz4`, `wh` and `cloze` stay unregistered. `cloze` in particular is the checkpoint question source:
`buildExamPool()` still reads all 57 `<contentPath>.json` files, and the A1 pool is still 48 questions
with each A1 file contributing exactly once.

## A1 lessons are curriculum, not gates

No A1 lesson or activity grants a qualification; the registry total stays at **4**, all Taipei. No
`world-data` file mentions `english.a1`, the same five Taipei territories remain gated by the same four
qualifications, and a learner who masters all twelve A1 lessons unlocks no territory. A CEFR course is
game-independent: it pays into the shared gold economy and stops there.

## Remaining unmigrated content

53 units at the start of 9C, **42 after it**: 24 generic Pre-A1, 12 A2, 5 B1 (plus the A1 `quiz4`/`wh`
blocks that remain content-only). They are still live as the checkpoint question bank, so they are
content awaiting migration, not dead content.

## What the test-census work bought

9B needed twelve test-file edits to migrate ONE lesson. 9C migrated ELEVEN and needed **nine**
assertion conversions — all of them censuses that 9B.1 had missed, none a product invariant. The
derived helpers introduced in 9B.1 absorbed the growth without change. The residual censuses were:
`READ_ALONG`/`MATCHING` name sets and the deterministic-activity equality in
`learning_attempt_test.py`, its `AVAILABLE` roster, `badged` in `learning_rewards_test.py`, the
availability predicate in `learning_lesson_completion_test.py`, the completable-lesson lists in
`learning_roleplay_test.py` and `learning_rule_a_parity_test.py`, and two censuses in
`curriculum_pilot_test.py` itself. All are now derived; `ROLEPLAY`'s Taipei-only name census is the one
known remaining census and will need attention only if role-play is ever registered elsewhere.

# Phase 9E — Pre-A1 migrated: 40 authoritative curriculum lessons

The 24 generic Pre-A1 units are now server-authoritative. **Registry metadata only** — no server,
client, world-data, `lessons.json` or content change.

| | Before | After |
|---|---|---|
| registered lessons | 16 | **40** (Taipei 4 + A1 12 + Pre-A1 24) |
| registered activities | 88 | **256** |
| gold-bearing activities | 16 | **40** |
| active completion policies | 16 | **40** |
| role-play activities | 4 | **28** |
| **qualifications** | 4 | **4** |
| courses emitting a campaign | 2 | **3** |

## Pre-A1 uses the TAIPEI family, not A1's

Pre-A1 carries no `reorder` and no `dictation`, and it *does* carry `quiz4`, `wh`, `cloze` and a
role-play scenario. Its shape is Taipei's, so the family is the Taipei seven:

`read_along · quiz3 · quiz4 · matching(vocab) · wh · cloze · roleplay`

`average_required_activities` v1 at passMark 80 over those seven; `quiz3` is the single paying gate
(`standard_activity_pass`); mastery pays the badge + `lesson_mastery_gold`. **800 per lesson, and no
qualification.** New course `english.prea1.core` ("Pre-A1 Core Readings") in the existing
`english.prea1` pack, with no campaign reward.

The activity-set decision is therefore **per content family**, not global: A1 = five activities,
Pre-A1/Taipei = seven. A2/B1 must be inspected on their own terms before 9F.

## Pre-A1/002 keeps its four questions

`Pre-A1/002` has 4 `quiz3` and 4 `quiz4` items where every sibling has 5. Nothing was padded, copied
or invented: the engine has **no minimum-item rule** — `validate_learning_registry.shape_problems()`
requires only non-empty, well-formed items — so a 4-item gate grades 100% and pays the same
PASS_GOLD. Vocabulary counts likewise stay uneven (5×3, 6×19, 7×2). Content was not flattened to fit
the registry.

## Role-play census retired

`learning_attempt_test.py` asserted the role-play set was *exactly* the four Taipei ids. That count
has no product meaning — every migrated family brings its own role-play — while the real invariant is
that a role-play is a stateful server-owned session and is therefore **not** reachable through the
stateless attempt endpoint. The census is now semantic: unique ids, every `lessonId` resolves (no
orphans), the id matches its lesson, no `contentKey`, grants nothing — plus the existing
not-gradable-via-`/attempt` assertion. Future curriculum growth needs no edit.

## Presentation

The level grid's "24 lessons" for Pre-A1 is now **true**: all 24 articles have authoritative rows
(measured 24/24, versus 0/24 before). Learning Home derives everything from the registry — no
separate hardcoded count exists. Home expands one campaign card and collapses the rest behind
"N more campaigns"; that is pre-existing behaviour and 9E did not redesign it.

## Remaining unmigrated content

**17 units: 12 A2 + 5 B1.** They stay live as part of the checkpoint question bank — `buildExamPool()`
still reads all 57 `<contentPath>.json` files (Pre-A1 112 / A1 48 / A2 48 / B1 20 questions,
unchanged) — so they are content awaiting migration, not dead content.

`lessons.json`, `LEVEL_ARCS`, `screenLevel`, `screenArticle`, `findArticleByFile()` and
`buildExamPool()` all remain **load-bearing**. The board-map branch and `openOutpost()` remain
unreachable dead code, as they were before 9E. Retirement belongs to a dedicated cleanup phase.
