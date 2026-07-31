# Learning → Conquest integration — Phase 3A STEP 1 inventory & trust-boundary audit

*Inventory of the existing learning/pass flow as of commit `11d5ea6`, before any Phase 3A runtime
change. This is the "before" reference and the basis for the STOP-and-ask determination (§41).*

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
