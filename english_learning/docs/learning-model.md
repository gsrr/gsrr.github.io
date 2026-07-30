# Learning Progression Model (Phase 3B)

The reusable model that replaced Phase 3A's one-off Zoo→Da'an mapping. It describes how content
becomes identity, identity becomes a qualification, and a qualification becomes a territory gate —
without the Game Domain ever learning what a subject is.

```
Content Pack → Course → (Unit) → Lesson → Activity → Completion → Qualification → Territory Requirement
```

---

## 1. Identity hierarchy

Logical identity is dotted and lowercase, so a parent is always a **whole-segment prefix** of its
child. There is no lookup table and no naming convention beyond the dots (`learning/identity.py`).

| Level | Example | Required? |
|---|---|---|
| contentPackId | `english.prea1` | yes |
| courseId | `english.prea1.taipei` | yes |
| unitId | *(none today)* | **optional** — today's content skips it; the schema supports it |
| lessonId | `english.prea1.taipei.zoo` | yes |
| activityId | `english.prea1.taipei.zoo.quiz3` | yes |
| qualificationId | `english.prea1.taipei.zoo` | opaque to the Game Domain |

`identity.parent_id()` walks up a level; `identity.is_ancestor()` does segment-wise containment
(`english.prea1` contains `english.prea1.taipei.zoo` but **not** `english.prea10`).

**Qualification IDs are not required to follow the hierarchy** — they are opaque strings. The one
installed qualification kept its Phase 3A id (`english.prea1.taipei.zoo`, not
`…zoo.quiz3.pass`) because that exact string is already written into learners' progress files *and*
into `world-data/territories/taipei.json`. Renaming it would have been a destructive migration for
zero benefit, and §3 prefers compatibility over gratuitous renaming. Consequence to be aware of: the
installed qualification id happens to equal its lesson id. They live in separate registry sections and
are never interchangeable — this collision is a Phase 3A compatibility artifact, not a modelling rule.
New content should prefer a distinct qualification id such as `<lessonId>.<activity>.pass`.

## 2. Content path vs logical identity — the central separation

```
qualificationId  →  activityId  →  lessonId  →  contentPath  →  <CONTENT_ROOT>/<contentPath>.json
     (opaque)        (logical, stable)          (filesystem, may be renamed)
```

`Pre-A1/taipei/zoo` is a **content path**: where the JSON happens to live. `english.prea1.taipei.zoo`
is a **logical lesson id**: what a learner's record and a territory requirement refer to. Only the
registry joins them. Therefore:

- no lesson file has to be renamed to adopt logical identity (§4);
- moving or renaming content cannot invalidate earned qualifications;
- the Game Domain never sees a filesystem path (§4, §20).

## 3. Registry schema (`learning/registry.json`)

```jsonc
{
  "schemaVersion": 1,
  "contentPacks":   { "<packId>":   { "title": … } },
  "courses":        { "<courseId>": { "contentPackId": …, "title": … } },
  "units":          { "<unitId>":   { "courseId": …, "title": … } },        // optional level
  "lessons":        { "<lessonId>": { "courseId": …, "contentPath": …, "title": …,
                                      "unitId": <optional> } },
  "activities": {
    "<activityId>": {
      "lessonId":     "…",              // → contentPath
      "contentKey":   "quiz3",          // the activity's key INSIDE the lesson JSON
      "graderType":   "yes_no",         // dispatch key into grading.GRADERS
      "title":        "…",              // UI text; may change without affecting identity
      "grants":       ["<qualificationId>", …],      // 1..n — many-to-many capable
      "rewardPolicy": "standard_activity_pass",      // a NAME from the server allowlist, never an amount
      "legacyKeys":   ["Pre-A1/taipei/zoo#quiz3"]    // Phase 3A completion keys still honoured
    }
  },
  "qualifications": {
    "<qualificationId>": {
      "scope":       "activity",        // activity | lesson | unit | course  (only 'activity' is earnable)
      "title":       "…",
      "studyTarget": <optional override>
    }
  }
}
```

Deliberately **absent**: answer keys (the lesson JSON already owns them — duplicating them would
create a second source of truth) and reward amounts (§5 below).

## 4. Activity, completion, qualification — three distinct things

| Concept | Meaning | Storage |
|---|---|---|
| **Activity completion** | this specific activity was passed, server-verified | `learning.activityCompletions["<activityId>"] = {passedAt, pct, rewarded}` |
| **Qualification** | an opaque certificate the Game Domain can gate on | `learning.qualifications["<id>"] = {earnedAt}` |
| **Reward** | a one-time economy payout for a verified pass | not stored as such — `rewarded` on the completion record is the idempotency flag |

An activity completion is **not** whole-lesson completion. The pre-existing whole-lesson rule (client
average ≥ `PASS_MARK`, stored as `passcnt`) is untouched and unrelated.

`lessonCompletions` / `unitCompletions` / `courseCompletions` are **not created** — §8 forbids empty
blocks and §7 forbids claiming a completion the server cannot prove. The `scope` field reserves the
vocabulary; the validator **rejects** any activity that grants a non-`activity`-scope qualification,
so a higher-level qualification cannot become earnable by accident. Adding real aggregation later
means adding a new block and a new grant path — no existing record changes meaning.

## 5. Reward policy and the untrusted-content boundary

```
registry (untrusted content)          server (authoritative)
  rewardPolicy: "standard_activity_pass"   →   rewards.POLICIES[...] = {type: gold, amountKey: PASS_GOLD}
                                                        ↓
                                         LearningService(reward_amounts={"PASS_GOLD": PASS_GOLD})
                                                        ↓
                                                  amount = game config
```

- Content may only **name** a policy from `learning/rewards.py`'s allowlist. `rewards.py` contains
  **no numbers at all** (a unit test asserts this).
- An unknown/forged policy, or a policy whose `amountKey` the server did not inject, resolves to a
  **zero** reward — fail closed.
- The validator rejects any activity carrying `rewardGold` / `gold` / `rewardAmount` / `amount`.
- `PASS_GOLD` remains `10000`, in `server.py`/`game/config.py`, unchanged.

So a future user-uploaded pack cannot mint gold: the worst it can do is name `none` or an unknown
policy and get nothing.

## 6. Grader architecture

`grading.GRADERS` maps `graderType → fn(key_items, answers) → (correct, total)`. Phase 3B ships
exactly one: `yes_no`. Dispatch is by **type**, never by activity name — the old
`YESNO_ACTIVITIES = ("quiz3","quiz4")` list is gone, and `grade("quiz3", …)` now returns a non-pass.

Adding a grader in Phase 3C = add a function to `GRADERS` (the registry validator picks up the new
type automatically). Unsupported type → non-pass, never an exception, never a pass by default.

`PASS_MARK = 80` mirrors `index.html`.

## 7. Territory requirements (World Domain)

```jsonc
"requirements": { "attackQualificationIds": ["<qualificationId>", …] }
```

Designer-owned, preserved by the generator's `DESIGNER_FIELDS` allowlist, validated by
`tools/validate_territory_catalog.py` (sorted, unique, non-empty strings). The World Domain owns
**only the ids** — never answers, content, grading rules or reward amounts.

**Semantics: ALL.** A player must hold every listed qualification. No OR groups in this phase.
Duplicate ids collapse; empty/`None` entries are ignored rather than acting as unmeetable gates.

Many-to-many is fully supported and tested: one qualification may gate several territories, one
territory may require several qualifications, and one activity may grant several qualifications.
Production data still carries only the single Taipei slice (§18) — the combinations are proven in
domain tests rather than by inventing curriculum.

## 8. Game / Learning boundary

```
Game Domain (game/*)                    Learning Domain (learning/*)
────────────────────                    ────────────────────────────
can_attack(..., player_qualifications,  LearningService: identity, content,
           require_qualifications)      grading, completion, grants, reward policy
   ↓ returns
reason: "qualification_required"
missingQualificationIds: [opaque ids]   →  UI resolves ids → titles + studyTarget
```

- `game/` contains **no** content vocabulary and never imports `learning` — enforced by a regression
  test that greps every `game/*.py` for `english|zoo|pre-a1|quiz|lesson|course|activity|subject|…`.
- `can_attack` never returns display text; the frontend resolves titles from
  `GET /api/learning/registry`.
- Qualification is **player** state: independent of territory, army and room, so losing every
  territory does not cost a qualification.

## 9. Study navigation

`qualificationId → studyTarget → contentPath → article`. `studyTarget` is **derived** from the
granting activity (so it cannot drift out of sync) and may be overridden per qualification. When
several activities grant the same qualification, the lowest activity id wins — deterministic.

The frontend has no `if qualification == zoo` branch; a test asserts the shipped requirement/study
code contains no content words at all, and that repointing only the metadata changes where Study goes.

**Return to game**: clicking Study stores `pendingStudy = {qualificationIds, label, reopen()}` — the
same lightweight closure pattern the existing occupy flow uses (`pendingOccupy`). When the server
confirms every outstanding requirement is met, a single button offers a return to the originating
territory panel. No router, no framework.

## 10. AI policy (unchanged from 3A)

`require_qualifications=False` bypasses **only** the human-learning layer. The AI still obeys source
ownership, adjacency, source garrison, the canonical conquest rules and the canonical Battle Engine.
It is one explicit policy argument, not scattered `if ai` branches.

## 11. Neutral claim (unchanged)

Learning requirements apply to **enemy conquest eligibility** only. The neutral-claim bootstrap is
untouched and is deliberately not learning-gated in this phase.

## 12. CONTENT_ROOT hardening

Three independent gates stand between a request and a filesystem read:

1. **Allowlist** — the path must be in `Registry.approved_content_paths()`. A request path never
   reaches `content.py`; only a registry-resolved path does.
2. **Shape** — `identity.is_content_path()` rejects absolute paths, backslashes and `.`/`..` segments.
3. **Containment** — the `realpath` must sit inside `CONTENT_ROOT`, so symlinks cannot escape either.

`CONTENT_ROOT` resolution is identical in all three environments: the container sets it explicitly
(`ENV CONTENT_ROOT=/var/www/html`), local runs and tests default to the directory holding
`server.py`. A test proves a file that exists on disk but is not registry-declared cannot be read.

## 13. Validation

`tools/validate_learning_registry.py` (shares `registry.validate()` with the unit tests):

- schema version, unknown sections, malformed/empty ids;
- referential integrity at every level (pack ← course ← unit ← lesson ← activity → qualification);
- missing/malformed `contentPath`, missing `contentKey`, unknown `graderType`, missing `title`;
- `grants` non-empty, no duplicates within one activity, all targets known;
- reward policy in the allowlist, and no amount-bearing keys;
- only `activity`-scope qualifications may be granted; every activity-scope qualification has a route;
- `legacyKeys` well-formed and never claimed by two activities;
- duplicate JSON keys are an error (not silent last-wins);
- the declared content files really exist and expose the declared activity keys.

**Cross-domain (§27) decision — WARNING, not error.** A territory requirement id that no installed
content pack describes is reported as a warning. Rationale: content packs are meant to become
independently installable, so a missing optional pack must not make the world catalog unloadable —
and the runtime already fails **closed** (the territory stays locked, and the UI renders the
requirement with a disabled "Not available yet" button). CI that ships world-data and its packs
together should run `--strict`, which promotes these to errors. The reverse case (an earnable
qualification no territory requires) is always an informational warning.

## 14. Backward compatibility

| Phase 3A artifact | Phase 3B treatment |
|---|---|
| `qualifications["english.prea1.taipei.zoo"]` | **unchanged** — same id, no migration |
| `activityCompletions["Pre-A1/taipei/zoo#quiz3"]` | **retained and read** via `activities[…].legacyKeys` |
| request `{lessonId, activity, answers}` | still accepted, normalized to `activityId` immediately |
| `world-data` requirement ids | unchanged |

New writes use the canonical `activityId`. Reads merge canonical + legacy: **earliest** `passedAt`
wins and `rewarded` is sticky, so credit carries forward and nobody is paid twice. The legacy record
is never rewritten or deleted — the migration is additive, idempotent and non-destructive.

## 15. Future content-pack direction (model only)

The schema is already pack-shaped: `contentPacks` is the top level, everything below it is namespaced
by the pack id, and `approved_content_paths()` means a pack's files are the only ones the server may
read. That is the full extent of Phase 3B's preparation — **no** upload, ZIP import, marketplace, AI
generation or install infrastructure exists or is implied.
