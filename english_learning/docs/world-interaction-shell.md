# The World interaction shell

Phase 13C.1. The World screen becomes a fixed application workspace: the map pans and zooms inside a
stable viewport, and the territory inspector stays on screen beside it. This is a layout and
interaction phase — no gameplay authority changed.

## 1. The old layout, and the scroll problem as measured

The HUD grid had three rows: a plaque strip, the board, and then a row holding the territory card,
its action bar and the Holdings list. The attack tray sat below that again, and the Region index below
that. Document height was therefore chrome + board + HUD + tray + index, and the actions a player
needs were the furthest thing down the page.

Measured in real Chrome before any edit (`scratchpad/audit_131.js`):

| viewport | document overflow | territory card | primary action |
| --- | --- | --- | --- |
| 1440×900 | **210 px** | in fold | borderline — below the fold once the action bar wrapped to two lines |
| 1024×768 | **278 px** | **below the fold** (top 686, bottom 795) | **below the fold** — needed a scroll |
| 768×1024 | 131 px | in fold | in fold |
| 360×780 | 149 px | in fold | in fold, but **3 px horizontal overflow** |

So at 1024×768 occupying a territory began with a scroll, and at 1440×900 whether it did depended on
how many buttons the action bar happened to be showing.

## 2. The desktop shell

Two rows. Chrome, then a workspace that absorbs the remaining viewport height.

```
+--------------------------------------------------------------+
| player | WORLD CONQUEST | controls          (chrome strip)    |
+---------------------------------------------+----------------+
|                                             | TERRITORY      |
|              MAP WORKSPACE                  | INSPECTOR      |
|          pan / zoom / select                |  name + status |
|                                             |  owner, pop,   |
|                                             |  armies, nbrs  |
|                                             |  strategic role|
|                                             |  ACTIONS       |
|                                             |  planner       |
|                                             |  Holdings      |
+---------------------------------------------+----------------+
   (below the shell, in normal flow: Region index, legend, owners)
```

`--shell-h` is set by `fitShell()` from the shell's own offset in the document — a layout
measurement. It reads nothing from the camera and nothing from geography. Measured results:

| viewport | shell height | shell bottom / viewport | map | inspector |
| --- | --- | --- | --- | --- |
| 1440×900 | 861 px | 888 / 900 ✓ | 1040×734 | 331×734 |
| 1024×768 | 729 px | 756 / 768 ✓ | 672×602 | 288×602 |

The inspector shares the workspace row with the map, so panning and zooming never moves it. If its
content exceeds the row it scrolls internally (`overflow-y: auto`, `min-height: 0`); the map does not
move because the inspector has more to say.

The map viewport fills its cell (`aspect-ratio: auto`, `height: 100%`). The geography keeps its own
proportions inside it through `preserveAspectRatio="xMidYMid meet"`, so the shell's shape is never
derived from a continent and the viewBox is never rewritten.

## 3. The mobile shell

Below 900 px the shell becomes one column: chrome, map, then a full-width territory sheet. It is not
the desktop rail squeezed narrow.

```
+---------------------+
| chrome              |
+---------------------+
|                     |
|     MAP             |
|                     |
+---------------------+
| Andorra    YOURS    |
| owner / pop / armies|
| Frontier — ...      |
| [Garrison][Centre]  |
| Holdings            |
+---------------------+
```

The map row carries a **floor** (`minmax(150px, 1fr)`) so a tall sheet can never squeeze it away, and
the sheet row stays `auto` so the row and the sheet agree on a height.

**A defect found and fixed during this phase.** The first implementation capped the sheet with
`max-height: 46%`. That resolved against the grid row to 160 px while the sheet's content needed
347 px, so the sheet clipped its own action buttons and left a 187 px hole inside the shell. Worse,
the harness did not catch it: `getBoundingClientRect()` reports layout position and ignores clipping
by an ancestor's overflow, so a clipped button still measured "in the fold". The fix is threefold —
the sheet takes its natural height, the cap became a safety valve in viewport units (`62dvh`,
deliberately larger than ordinary content), and only the card's **numeric detail rows** are bounded
(`.hc-rows`, 56 px, scrollable). The territory's identity, its strategic role and its actions are
never the thing that gets clipped. The acceptance harness now walks clipping ancestors.

Measured after the fix:

| viewport | chrome | map | sheet | sheet clips? | actions truly visible |
| --- | --- | --- | --- | --- | --- |
| 768×1024 | 82 px | 738×651 | 738×244 | no (scrollH == clientH) | yes |
| 360×780 | 82 px | 330×407 | 330×244 | no | yes |

The map is the larger surface in both. Horizontal overflow is **0 px at all four viewports** — the
pre-existing 3 px overflow at 360 px came from the chrome control cluster's natural width, and the
cluster is now allowed to shrink. Moving that cluster from a 2-wide to a 3-wide block also dropped
the chrome strip from 118 px to 82 px, which the map absorbed.

## 4. Territory inspector ownership

The World screen has exactly three conceptual layers and no fourth:

1. **chrome** — player, title, global controls (Academy, My Progress, Ranking, Empire, Multiplayer,
   World events)
2. **map workspace** — geography, labels, strategic overlays, selection and attack highlights
3. **territory inspector** — the selected territory and its immediate actions

The inspector shows: name + ownership badge; owner, population, armies, garrison composition (own
territories only — fog of war is unchanged), neighbour count; the 13B strategic role in words; then
the actions. With nothing selected it says so plainly and offers a disabled prompt rather than
placeholder data.

Empire and the Academy were **removed** from the action row. Both were already in the chrome control
cluster, and in a bounded inspector a duplicate costs the space a territory action needs. No
capability was lost: both remain one click away and always on screen (measured in the fold at all four
viewports).

## 5. Occupy

Selecting an unheld territory puts **Occupy _name_** in the inspector immediately — no modal is needed
to discover it. Pressing it opens the planner inside the inspector; the confirm control is reachable
without scrolling. Verified end to end against the real server: the territory is unowned before,
`POST /api/territory/claim` succeeds, the server records the new owner, the selection survives, the
camera is not reset to the World home, and labels stay anchored (worst 0.01 px over 250 labels).
Claim authority, eligibility, gold and room rules are untouched.

## 6. Attack

Selecting an enemy-held territory puts **Attack _name_** in the inspector. Pressing it opens the same
single planner, which is a planning tool and not a second information panel. Verified with a real
rival player holding an adjacent territory:

- `validAttackSources` returns the adjacent holding; the planner shows 1 source, 1 target
- source outline `stroke-dasharray: 5px, 3px` (dashed) vs target `none` (solid) — they differ by
  **style**, not colour alone
- the map still pans and zooms while the plan is open, and the plan survives it
- labels stay anchored during planning (worst 0.01 px)
- the launch control is reachable without scrolling, and the attack goes through the existing
  `launchAttack` / `/api/territory/attack` path

Cancelling or navigating away returns to the inspector without resetting the camera. The 12D
lifecycle is intact: Empire, Academy, My Progress, Ranking and Multiplayer all cancel a plan.

## 7. The re-entry exception

Re-entry keeps its confirmation, as 12D decided, because it costs gold and is decided by a battle.
It is a deliberate two-step surface and not a `window.confirm()`:

1. the inspector's **Foothold** action only scrolls to the server-driven panel and focuses the first
   candidate — it performs nothing and calls no endpoint;
2. a candidate opens a modal stating the gold cost and that the enemy garrison is unknown;
3. only an explicit **Re-enter** action POSTs.

This exception was not broadened. No other territory action opens a modal.

## 8. The Empire boundary

Empire remains the single management destination and still owns all four areas — Overview, Forces,
Buildings, Technology — each with its own renderer. The inspector summarises a territory's garrison
and offers nothing managerial: no Recruit, no troop transfer, no Buildings, no Technology, no bulk
management, and no per-territory Manage button. Troop transfer is **not** implemented in this phase;
where Forces says it is unavailable, that remains true.

## 9. Camera and projection preservation

The 13C projection architecture is frozen and untouched. `svg.getScreenCTM()` is still the only
map→screen projection authority (exactly one call site), labels are still projected through the
browser's own matrix, and there are no empirical per-territory offsets and no second camera formula.
`fitShell()` reads `window.innerHeight` and the shell's offset — never the camera, never `CTM`.

A viewport change re-clamps through `cam.restore()`, which runs `apply()` and therefore the one
`clamp()` that has ever existed. No second bounds calculation was added.

Label anchoring after the shell change, worst over all 250 labels:

| camera | worst drift |
| --- | --- |
| s = 1 | 0.00 px |
| s = 4 | 0.01 px |
| s = 8 | 0.01 px |
| s = 16 | 0.06 px |
| after a drag | 0.00 px |
| during attack planning | 0.01 px |
| after every screen round trip | 0.01 px |

`tests/label_transform.test.js` passes unchanged — none of its projection assertions were weakened.

Camera behaviour verified: home, zoom in/out, wheel, pinch, drag, continent shortcuts, persistence
through Empire / Academy / My Progress / Ranking / Multiplayer, and resizing between desktop and
mobile and back. A region shortcut moves the camera and changes nothing else — the shell geometry is
identical before and after (861 px → 861 px), and the selection is untouched.

## 10. Region index decision

**Retained, classified as useful secondary navigation and an accessibility/search aid.** All 250 rows
keep their accessible names ("Select Andorra and point the camera at it"), and a row still selects the
territory and points the camera at it — no modal, no `openRegion`.

It lives **outside** the shell, as a sibling in normal flow below it. That is structural, not
cosmetic: because the shell is the board container's first child and the index comes after it, the
index's height is incapable of moving anything inside the shell. The document still scrolls to reach
the index and the other reference rows (about 230 px of secondary content), which is the intent —
primary territory actions never require it.

## 11. Accessibility

- the inspector is a labelled landmark: `role="complementary"`, `aria-label="Territory inspector"`
- it is keyboard reachable, and its actions take visible focus
- action names carry the territory: "Occupy Australia", "Attack Spain", "Set the garrison of
  Andorra", "Point the camera at Australia" — none generic
- selection is announced once through a polite live region, from `hudSelect()` only. Pan and zoom do
  not re-announce (verified: the announcement text is unchanged across a zoom)
- no `contextmenu`, no right-click menu, no hover-only and no double-click-only route to any primary
  action
- selection, attack source, attack target, frontier and isolated all carry a non-colour cue: outline
  style for source/target, SVG texture patterns for frontier/isolated, and words in the inspector
- touch targets on the stacked sheet remain full-height buttons at 360 px

## 12. Performance

30 camera operations, measured in the browser:

| | result |
| --- | --- |
| fetches | **0** |
| territory paths rebuilt | **0** (250 intact) |
| shell / inspector / card element identity | unchanged — no rebuild |
| average camera update | 3.9–6.3 ms (inside one 60 fps frame) |
| 12 successive selections | 0 paths rebuilt, ~8 ms each |
| scrolling the inspector | does not move the camera |

No polling was added.

## 13. Browser acceptance

`scratchpad/accept_131.js`, real Chrome against the real local server, four viewports, with a real
rival player so "enemy" is a genuine rival holding: **163 checks passed, 0 failed**, no page errors
and no failed requests.

The five `400 Bad Request` console entries are all `POST /api/territory/claim` and are the harness's
own fixture over-claiming — the server correctly refuses with "Not enough troops" once the troop pool
is exhausted. They are not a product fault.

Screenshots: `shell_1440x900.png`, `shell_1024x768.png`, `shell_768x1024.png`, `shell_360x780.png`,
`planner_1440x900.png`, `planner_360x780.png`, plus the before/after inventory shots
`a5_before_*.png` / `a5_after_*.png`.

## 14. Known limitations

- **The document still scrolls, by design.** About 230 px of secondary reference content (Region
  index, legend, owner list, boss and replay rows) sits below the shell. Primary territory actions
  never need it, which is what this phase set out to guarantee.
- **The Boss checkpoint button remains in the inspector.** It is not territory-scoped, so by the
  three-layer model it belongs in the chrome. It is the only route to the level checkpoint battle, and
  moving it would risk the curriculum-entry path, so it was left in place rather than churned. A
  follow-up should relocate it to the chrome cluster.
- **On a phone the title truncates** ("WORLD CONQUES…") and the chrome strip still costs 82 px of a
  780 px screen. Reworking the masthead is outside this phase's file boundary.
- **Re-entry's live panel could not be exercised in the browser** because it only appears once the
  player has lost every territory, which this fixture cannot reach deterministically. Its two-step
  confirmation is pinned by `tests/world_interaction_shell.test.js` #11 against the shipped source
  instead, and the harness says so rather than claiming a pass it did not earn.
- **The garrison action stays in the inspector.** It positions the garrison of one territory and is
  neither recruitment nor a transfer between territories, so it is read as that territory's immediate
  action. If a later phase introduces real troop movement, this is the first thing to re-examine.
- **Attack outcome is battle-decided**, so the acceptance harness verifies that the attack was
  launched through the existing flow rather than asserting a particular winner.

## 15. Future extension points

These are extension **points**, not implemented behaviour:

- **Troop transfer** would extend the planner, which already models a source, a target and four troop
  classes. The inspector would gain a "move from here" affordance; the Forces area in Empire is where
  a bulk view belongs. Nothing in this phase presumes it.
- **Naval movement / sea zones (13H)** would change what `neighbours_of` returns. Because the 13B
  classifier takes adjacency as a callback, `isolated` stops being a dead end without the inspector
  changing at all — the strategic line it already prints would simply say something different.
- **Field armies (13D)** would need a unit surface. The shell has room for it as a fourth region in
  the workspace, but that is a decision for that phase, not a slot reserved here.
- **A wider inspector on very large screens** is possible: `--insp-w` is a single clamped token.
