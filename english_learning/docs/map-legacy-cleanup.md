# Continuous-map legacy cleanup (Phase 12D audit)

Phase 12C changed the product interaction model. This phase makes the implementation match it. Traced
from `index.html` at `d778dee`, before any edit.

Classification: **ACTIVE · COMPATIBILITY · UNREACHABLE DEAD · USED BY ANOTHER SURFACE**

## 1. Dead-path inventory

| path | evidence | class |
| --- | --- | --- |
| `spec.drill` / `drill[p.id]` container branch | `GAME_MAPS` has exactly one entry, `{world, grouped:true}` — **no `drill` key**. The Taiwan→Taipei container was retired in 10A.3. `spec.drill` is a *client spec* field; nothing in `world-data/` feeds it, so no data compatibility depends on it. | **UNREACHABLE DEAD** |
| `.geo-drill` / `.geo-marker-drill` / `.geo-lab.drill` CSS + `r.drill` guards + `gi-drill` index affordance + `gl-drill` legend | only reachable through the branch above | **UNREACHABLE DEAD** |
| `spec.groupFilter` | already removed in 12C; only mentioned in comments | **already gone** |
| old continent Back path / filtered redraw / continent viewBox fit | removed in 12C | **already gone** |
| **Region index row click → `r.open` → `openRegion` modal** | `btn.addEventListener("click", r.open)` — **still live**, so the 250-row directory was the one surviving route to the retired modal | **ACTIVE — a defect** |
| `openRegion()` | callers: the index row above; `regionReopenFor()`; and its own internal reopens. After the index is fixed, only `regionReopenFor` remains | **UNREACHABLE DEAD** (after D1) |
| `regionReopenFor()` | one caller: the `[data-region-study]` handler, which is rendered only by `regionLearningHTML()` **inside** `openRegion` | **UNREACHABLE DEAD** |
| `renderAttackPanel()` | one caller: `openRegion` | **UNREACHABLE DEAD** — replaced by the attack tray |
| `renderRequirementPanel()` | one caller: `renderAttackPanel`. Also returns false always (see below) | **UNREACHABLE DEAD** |
| `regionLearningHTML()` | one caller: `openRegion` | **UNREACHABLE DEAD** |
| `occupyLessonPlan()` / `selectOccupyLesson()` gated branch | reached only when `territoryRequirements(key)` is non-empty | **UNREACHABLE DEAD** |
| `pendingOccupy` | only setter is `openRegion`'s gated branch | **UNREACHABLE DEAD** |
| `pendingStudy` | only setter is `renderRequirementPanel` | **UNREACHABLE DEAD** |
| `lessonReturnTo = {to:"region"}` (3 setters) | all three live inside the `openRegion` web | **UNREACHABLE DEAD** |
| `returnToRegion()` + the `ctx.to === "region"` dispatch branch | nothing can produce that ctx once the setters are gone | **UNREACHABLE DEAD** |
| `showMapForTerritory()` | called by `returnToRegion` **and** documented as the contextual deep-link resolver | **USED BY ANOTHER SURFACE** — keep |
| `territoryRequirements()` / `missingQualifications()` | read the catalog's designer metadata; consumers are all in the dead web | **UNREACHABLE DEAD** as UI; the catalog data itself is untouched |
| old attack modal (`openModal` inside `openRegion`) | see `renderAttackPanel` | **UNREACHABLE DEAD** |
| old territory management modal | 12C already removed `buildingsPanel` from `openRegion` | **already gone** |
| old Base route (`openHomeBase` as a HUD destination) | 12C repointed the HUD icon to Empire; `openHomeBase` survives as the panel Empire opens | **USED BY ANOTHER SURFACE** — keep as a panel, not a hub |
| Recruit / Build / Research territory handlers | `openBuildingDetail` / `openConscriptDetail` / `buildingsPanel` | **USED BY ANOTHER SURFACE** — Empire ▸ Buildings / Forces / Technology |
| `deployPanel()` | still used by **re-entry** (`openReentry`) and the **checkpoint boss** | **USED BY ANOTHER SURFACE** — keep |
| `validAttackSources` / `launchAttack` / `claimTroops` | the attack and occupy trays | **ACTIVE** |
| legacy map-picker assumptions (`levelIdxForKey`, `selLevelIdx`) | the checkpoint boss is hosted on the map screen and needs the level index | **COMPATIBILITY** — keep |

### Why the requirement web really is unreachable — measured, not assumed

```
world territories                 : 250
...with attack_requirements       : 0
gated territories on ANY map      : 5   (all taipei:*, and taipei is not a playable map)
allowed_game_maps()               : {"world"}
```

The server also enforces no learning gate on `/api/territory/claim` or `/api/territory/attack`
(Phase 10A.3R removed it). So `renderRequirementPanel()` can never return true and no territory can
ever enter the gated-study flow. The catalog metadata stays exactly as it is — this phase removes
**client navigation behaviour**, never data.

## 2. Modal inventory (World)

| modal | provides | class | action |
| --- | --- | --- | --- |
| `openReentry` — Establish Foothold | short, destructive, priced confirmation before a battle | **B: essential confirmation** | KEEP |
| `runBattle` — the battle animation | the fight itself | **A: combat** | KEEP |
| `renderEmpireModal` — Empire | the single management hub | management, but *not* territory-scoped | KEEP (it is the destination, not a per-territory detour) |
| `openHomeBase` / `openBuildingDetail` / `openConscriptDetail` | building + recruit + research panels | opened **from Empire** | KEEP as Empire's panels |
| World Events | unrelated feature | **E** | KEEP |
| `openRegion` | duplicated territory info **and** attack planning **and** the dead gated flow | **C + D** | RETIRE |
| `renderAttackPanel` inside it | attack planning | **D** (superseded by the tray) | RETIRE |

## 3. What is retained for compatibility, and why

- **`showMapForTerritory(key)`** — the contextual deep-link resolver. Keeping it means a future
  "take me to this territory" link needs no new machinery.
- **`levelIdxForKey` / `selLevelIdx`** — the checkpoint boss is hosted on the map screen and is
  addressed by curriculum level, not geography.
- **`deployPanel`** — re-entry and the boss both use it; only the *territory* uses of it are retired.
- **`territoryRequirements`** in the catalog — data, not behaviour. Untouched.
- **`grouped: true`** on the World spec — it selects which SVG paths are territories (it excludes the
  background frame) and drives the continent tint and camera presets. It is not an interaction mode.

---

# Outcome (implemented)

## Removed

| what | why it was safe |
| --- | --- |
| the `spec.drill` container branch, `const drill`, `geo-drill` / `geo-marker-drill` / `.geo-lab.drill` / `.gi-drill` / `.gl-drill`, and every `r.drill` / `L.drill` guard | `GAME_MAPS` declares one playable surface with no `drill` key; the branch could not run |
| `openRegion`, `renderAttackPanel`, `renderRequirementPanel`, `regionLearningHTML`, `regionReopenFor`, `regionMappedLessons`, `regionLessonPaths`, `occupyLessonPlan`, `selectOccupyLesson`, `territoryRequirements`, `missingQualifications`, `studyArticleFor` | after the Region index was fixed, the only remaining entry was the gated-study web, which **0 of 250** playable territories can enter |
| `pendingOccupy`, `pendingStudy`, `offerStudyReturn`, `returnToRegion`, the `to:"region"` dispatch branch, the `[data-region-study]` listener, the `region` mode of `refreshCompletionCards` | all fed only by the above |
| the post-lesson "a qualification unlocked a region — go back to it" branch | unreachable since 10A.3R and dependent on the retired modal |

`index.html` **net shrank by 111 lines** (469 added, 580 removed) across the whole phase.

Three references survived the first pass and were found by grepping every removed name back through
the file: a live `openRegion` call in the per-territory `open` closure, an assignment to the deleted
`pendingOccupy` inside `endChallengeIfUnsatisfied` (which in sloppy mode would have silently created a
global), and the orphaned `studyArticleFor`. A comment-stripped identifier sweep now confirms no
removed name is referenced in executable JS.

## Retained, and why

`showMapForTerritory` (contextual deep-link resolver) · `levelIdxForKey` / `selLevelIdx` (the
checkpoint boss is hosted on the map screen and addressed by curriculum level) · `deployPanel`
(re-entry and the boss) · `openHomeBase` / `buildingsPanel` / `openBuildingDetail` /
`openConscriptDetail` (Empire's own panels) · `studyTargetFor` (the registry's qualification → lesson
mapping) · `grouped: true` (path selection, tint, camera presets — not an interaction mode) ·
`endChallengeIfUnsatisfied` as an explicit no-op (Back and the lesson exits both call it; a future
lesson-scoped transaction belongs there rather than scattered across callers) · the requirement
metadata in the catalog (**data, never behaviour**).

## Two defects found and fixed during the phase

1. **The Region index still opened the retired modal.** Every one of the 250 directory rows wired
   `click → r.open → openRegion`. 12C had missed it. A row now selects the territory and points the
   camera at it. Hovering used to call `hudSelect` and then half-clear `geoSelectedKey` on mouseleave,
   so brushing the list mutated the selection; hover is now highlight-only.
2. **A TDZ `ReferenceError` reported as a network failure.** The camera-restore block called
   `renderHudCard()` before `const HUD = buildHud()` had run, so a redraw *with a remembered
   selection* threw — and `drawGeo`'s `.catch(() => …)` rewrote it as *"Could not load map
   maps/world.svg. (Needs the server or GitHub Pages.)"*, leaving an empty board and discarding the
   reason. Symptom: leaving the board and coming back worked, unless you had selected something
   first. Fixed both halves — the restore block sets state only, and `drawGeo` now distinguishes a
   fetch failure from a draw failure and logs the real error.

## Camera and selection persistence

`geoView = { room, key, s, tx, ty }`, a plain module variable — **never** localStorage, never sent to
the server, never in authoritative game data, gone with the tab. Restored only when the room matches,
through `cam.restore()` so the same clamp bounds it as a drag. Forgotten on room change and on logout.
A restored selection is exactly as powerless as a fresh click.

## Attack-plan lifecycle

| event | plan |
| --- | --- |
| pan / zoom / pinch | **kept** — the map is what you are aiming at |
| tap a valid source of the current plan | **kept** — that chooses the source, by design |
| tap any other territory | cancelled |
| Empire (a modal, so it needed its own hook at `openEmpire`) | cancelled |
| Academy / My Progress / Ranking / Multiplayer / a lesson | cancelled at `showScreen` |
| logout | cancelled |

## Test migration record

| suite | OLD | WHY OBSOLETE | NEW | WHY NOT WEAKER |
| --- | --- | --- | --- | --- |
| `world_camera` (2/3) | the territory wiring starts after the `spec.drill` guard | the guard is gone | whole-file: no `spec.drill` / `geo-drill` / `r.drill` / `.gi-drill` may exist | a file-wide absence is stronger than "not in this branch" |
| `world_camera` (6/7) | `L.minZoom = L.drill ? 0 : …` | the ternary is gone | `L.minZoom = …` plus `L.priority = restW` | adds an assertion about priority the old form lacked |
| `world_camera` (14) | `openRegion`'s body must not contain `buildingsPanel` | `openRegion` does not exist | eleven removed names must be absent as identifiers | "gone" is stronger than "present but clean" |
| `world_camera` (15/16/17) | `/per territory/` and `/Armory in/` | copy sharpened for B15 | the specific sentences, seam-joined before matching | asserts the exact claims, not substrings |
| `outpost_migration` (4) | the attack UI must be `renderAttackPanel` | replaced by the tray, then deleted | the tray derives sources from `validAttackSources`, fires `launchAttack` with the captured source, and is the ONLY attack UI | adds "exactly one attack UI" and the plan-capture bug guard; every authority check untouched |
| `outpost_migration` (6) | `renderAttackPanel` must represent "no adjacent owned source" | same subject | the tray states it, names the remedy, covers the isolated island, and offers **no** ATTACK button | adds the no-button assertion |
| `learning_frontend` (1-4) | `renderRequirementPanel` rendering behaviour | the panel is gone and was unreachable (0/250) | no conquest path may consult learning state; registry readers hardcode no content | forbids a client-side learning gate reappearing — which the old test allowed |
| `learning_frontend` (5 tail) | the `#studyReturn` button appears after a pass and returns to the region | fed only by state the retired modal set | no orphaned return affordance, and a pass navigates nowhere | "no navigation is invented" is the stronger claim now that nothing can set it up |

**Not touched:** every authority assertion in both suites — the attack POST body, no
winner/survivors/ownership, non-authoritative battle replay, adjacency-derived sources, and
`{activityId, answers}`-only attempts.

## Known limitations

- `endChallengeIfUnsatisfied` is an empty hook. Deliberate: two callers already invoke it.
- The decoration "altitude compensation" always resolves to 1 now (the viewBox is never rewritten). It
  is kept as one division, documented as inert, because a future map with a different authored viewBox
  would need it.
- `lessonCompactHTML`'s `opts.study` parameter has no caller; kept so the compact card keeps one
  shape, documented as a no-op.
- Camera memory is per-tab. A reload starts at the home camera — deliberate, since persisting a view
  position would make it state.
- `reentry_authority_test.py` still fails intermittently on this Windows dev machine
  (`PermissionError [WinError 5]` on `economy.json.tmp → economy.json`) and passes standalone with 28
  checks. Not repaired here: it is a test-harness persistence race, and production is Docker/Ubuntu.
