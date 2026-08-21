# World camera, territory interaction and Empire IA (Phase 12C audit)

Traced before any edit, from `index.html` as it stood at `cdca583`. Every row is classified
**A keep · B adapt · C retire continent semantics · D move to Empire · E dead/legacy**.

## 1. Map / camera

| behaviour | where it lives today | class | note |
| --- | --- | --- | --- |
| World SVG load | `drawGeo(spec…)` → `fetch(spec.file)` → `build(svgText)` | A | one file, `maps/world.svg`, never re-fetched per continent |
| authored viewBox | `0 0 1010 666` on the SVG | A | the map's own coordinate space |
| **viewBox rewritten to a continent bbox** | `if (grouped && contFilter) … svg.setAttribute("viewBox", …)` | **C** | this is the pathological Oceania strip: the *board* changes shape |
| SVG on-screen size derived from the viewBox aspect | `svg.style.maxWidth = max(320, innerHeight*0.82 * (vb[2]/vb[3]))` | **C** | so a continent bbox re-proportioned the whole viewport |
| pan/zoom | `attachPanZoom(svg, frame, onChange)` — CSS `translate()+scale()`, `s∈[1,6]` | **B** | keep the transform model; widen the range, add bounds |
| wheel zoom | `svg.addEventListener("wheel", …)` cursor-anchored | A | |
| pinch zoom | two-pointer `pointerdown/move`, `zoomAt(mid…)` | A | |
| drag pan | `onMove` — **only when `s > 1`** | **B** | must work at the home zoom too |
| snap-back | `if (s <= 1.001) { s = 1; tx = 0; ty = 0; }` | **B** | becomes "home camera", not "reset to fit" |
| double-click | resets to `s=1, tx=0, ty=0` | **B** | becomes "back to the World view" |
| drag-then-click suppression | capture-phase `click` handler with `moved` | A | keeps a pan from selecting a territory |
| `curDrawArgs` altitude replay | `refreshMap()` / profile restore | **B** | still needed for redraw; no longer carries a continent |
| continent bounds | `groups[ck]` bbox accumulation | **B** | becomes camera-shortcut presets |
| `spec.groupFilter` | the "which continent am I in" state | **C** | retire as an interaction mode |

## 2. Territory interaction

| behaviour | where | class | note |
| --- | --- | --- | --- |
| **territory click at World zoom → drill into continent** | `p.addEventListener("click", () => drawGeo({…groupFilter: ck}))` | **C** | the defect B5 forbids |
| territory click inside a continent → select + open panel | `hudSelect(key)` then `openRegion(...)` | **B** | selection stays; the panel is replaced by trays |
| `.geo-drill` continent tint | `geo-region geo-drill geo-cont geo-cont-<ck>` | **B** | tint may stay; `geo-drill` must go so ownership paints |
| ownership colouring skips drill rows | `colorize()`: `if (r.drill || !r.p) return` | **B** | no territory is a drill row afterwards, so ownership appears at every zoom for free |
| Taipei-style sub-map drill (`spec.drill`) | `drill[p.id]` branch | **E** | `worldMapSpec()` declares no `drill`; the Taiwan→Taipei container was already retired |
| tiny-island halo | `haloIfTiny(p)` | A | decorative, `pointer-events:none` |
| region index list | `.geo-index`, hover highlight + click | A | a keyboard/scan route to every territory |
| adjacency debug | `?debugAdjacency=1` | A | dev-only |

## 3. Labels

| behaviour | where | class |
| --- | --- | --- |
| HTML overlay, constant screen size | `.geo-labels` + `relayoutLabels(s,tx,ty)` | A |
| per-label `minZoom = 44 / screenWidthAt_s1` | `markerSpecs.forEach(...)` | **B** — the semantic-zoom hook already exists |
| priority = `drill ? 1e6 : screenWidth` | same | **B** |
| collision drop by priority | `placeMapLabels(cands, zoom)` | A |
| selected label always visible | `c.selected` exemption | A |
| continent label = drill trigger | `markerSpecs.push({… drill: true, open: drawGeo(…)})` | **C** → camera shortcut |

## 4. Combat

| behaviour | where | class |
| --- | --- | --- |
| valid source derivation | `validAttackSources(targetKey)` — catalog adjacency ∩ owned ∩ garrisoned | A (authority, untouched) |
| attack request | `launchAttack(source, target, …)` → `POST /api/territory/attack` | A |
| battle replay from server order | `runBattle(squad, res.defenderOrder, …, preOrdered=true)` | A |
| **attack UI inside a modal** | `openRegion` → `renderAttackPanel(terr, …)` inside `openModal` | **C/D** → in-board tray |
| source picker | `<select id="atkSrc">` inside the modal | **B** → map highlight + tray chips |
| troop assignment | `deployPanel(...)` sliders | **B** → tray steppers, same `[{type,hp}]` payload |
| occupy | `deployPanel` → `claimTroops` → `POST /api/territory/claim` | **B** → tray, same call |
| re-entry | `.geo-reentry` panel + `openReentry` modal, server-offered | A |
| learning requirement panel | `renderRequirementPanel` | A (dead but authority-adjacent — kept) |

## 5. Empire / management surfaces (today: four competing entry points)

| surface | entry | what it does | class |
| --- | --- | --- | --- |
| `#empireBar` | retired in HUD mode (`display:none`) | old summary strip | E |
| `renderEmpireModal()` | HUD plaque "Empire ▸" | stats + home row + region rows, each → `openRegion` | **B** → becomes the hub |
| `openHomeBase()` | HUD icon "Base — recruit & build" | `buildingsPanel(HOME_KEY)` | **D** → Empire |
| `buildingsPanel(container,key,h)` | inside `openRegion` (mine) **and** `openHomeBase` | 4 buildings + conscription | **D** → Empire ▸ Buildings |
| `openBuildingDetail(key,id)` | a building card | armory → research; barracks/archery/stable → recruit | **D** → Empire ▸ Forces / Technology |
| garrison redeploy | `openRegion` (mine) → `deployPanel` → `claimTroops` | troop positioning on the selected map square | **B** → stays map-side, as a tray |
| HUD "Recruit" action | `actBtn("Recruit", openHomeBase)` on **every** selection | recruit at home | **D** — remove from the territory action row |
| HUD "Manage" action | `actBtn("Manage", openSel)` for an owned territory | modal with buildings+research | **D** |
| Holdings plaque | `renderHudPlayers()` | owner → territory count | A — summary, stays a summary |

## 6. Technology authority — measured, not assumed

**Technology is per-territory today, and it is NOT empire-global.**

| question | answer, from the server |
| --- | --- |
| where is it stored? | `store[territoryId]["tech"] = {atk, def}` — one record per territory. The home base has its own, separate: `econ[user]["tech"]`, which buffs the army you attack *with*. |
| scope | **territory-scoped** (plus one player-scoped home value). Not player-global, not room-global. |
| cost | `TECH_COST = {"atk": [160,320,560], "def": [160,320,560]}`, `TECH_MAX = 3`, paid from the player's single Gold pool |
| prerequisite | an **Armory in that same territory** (`has_armory=bool(h["buildings"]["armory"])`) |
| effect | `game_conquest.resolve_attack(squad, defTroops, srcTech, defTech)` — the *source* territory's tech attacks, the *target* territory's tech defends (+10%/level) |
| does a conquered territory inherit? | **No.** `apply_territorial_attack()` builds `new_target` from scratch on a win — `{owner, avatar, troops, pop}` — so **buildings and tech reset to nothing** on capture. |

Consequence for B18: the desired "empire-global technology" model **conflicts with current authority**. This
phase therefore reorganises the Technology *UI* only and states the per-territory truth on screen.
Making tech empire-global would change what an attack costs and what a conquest is worth — a
game-design and balance decision, explicitly out of scope, recorded as a follow-up phase.

## 7. What this phase will not touch

`server.py`, `game/*`, `world-data/*`, `learning/*`, `maps/world.svg`, territory ids, adjacency,
ownership/claim/attack/re-entry authority, troop costs, `BUILD_COST`, `TECH_COST`, economy constants.
The map camera, the selection semantics, the attack surface and the Empire IA are all client concerns,
and every server call the new UI makes already exists with the same payload.

---

# Outcome (implemented)

## The new camera

```
viewport  .geo-holder.geo-viewport   width: min(100%, --vp-h * --vp-ratio)
                                     aspect-ratio: --vp-ratio    <- BREAKPOINT, never geography
                                     1.6 desktop · 1.1 phone
map       svg.geo-svg                viewBox 0 0 1010 666 (authored, never rewritten)
                                     preserveAspectRatio="xMidYMid meet"  -> never distorted
camera    { s, tx, ty }              translate(tx,ty) scale(s), viewport pixels
          CAM_MIN 1                  the whole World
          CAM_HOME 1.32              the opening view
          CAM_MAX 16                 a single island is a comfortable tap target
          CAM_OVERSCROLL 0.12        bounded ocean margin; the map cannot leave the viewport
API       focusRect(x0,y0,x1,y1,o)   centre + zoom; the viewport's shape is never touched
          home()                     back to the World view (also the double-click action)
          zoomBy(k)                  the +/- controls
```

The height budget caps the **width**, because a `max-height` on an `aspect-ratio` box silently changes
the ratio — the very failure mode this phase removes. Measured at 1440×900: **979×612, ratio 1.600**,
identical before and after every camera move.

## Continent presets

A raw bounding box over a continent's members is useless as a camera target: Europe carries Russia,
N. America carries Greenland and the Caribbean, Oceania carries Heard & McDonald and Pitcairn. The
raw Europe box spanned most of the map, so the first implementation zoomed **out** to 1.04×. The
preset is now the 10th–90th percentile of member centroids, widened by the median member size, with
`minZoom: 2`. Measured: Europe 1.32 → 3.25×, Oceania 1.32 → 2.0×. Outliers are not hidden or filtered
— they stay ordinary clickable territories, reachable by panning.

## Semantic zoom

| band | camera | admitted |
| --- | --- | --- |
| FAR | s < 2 | continent presets, the widest territory labels, ownership colour, dimmed minor scenery |
| MID | 2 ≤ s < 4.2 | more territory labels as they become legible, full scenery |
| NEAR | s ≥ 4.2 | as many names as fit; continent presets step aside |

One map, three densities — `holder.dataset.zoom` drives CSS, and the existing `placeMapLabels`
priority/collision machinery is reused unchanged. The selected label is always exempt.

## Ownership at every zoom (a side effect worth naming)

`colorize()` skipped `r.drill` rows, and at the old top altitude **every** territory was a drill row —
so ownership was invisible on the World view. With no territory a container, ownership now paints at
every zoom for free. Nothing in `colorize()` changed.

## Technology: reorganised, not re-scoped

Empire ▸ Technology gathers the **per-territory** truth in one table and states it on screen: research
is per territory, needs an Armory in that same territory, caps at `TECH_MAX = 3`, costs
`TECH_COST = [160, 320, 560]`, the source territory's forge strengthens an attack while the target's
armour strengthens its defence, and a conquered territory arrives with nothing. No semantics changed.
Making technology empire-global would change what an attack costs and what a conquest is worth, so it
is recorded as a follow-up gameplay phase, not slipped into an IA phase.

## Follow-up gameplay questions (audited, deliberately unsolved here)

1. **Troop transfer between territories** — does not exist on the server. Forces therefore offers no
   transfer control and says so plainly rather than faking one.
2. **Coastal / naval movement** — adjacency is land-only; isolated islands cannot attack out.
3. **Technology becoming empire-global** — conflicts with current per-territory authority (above).
4. **Technology progression and cap design** — `TECH_MAX = 3` with three fixed prices is the whole
   system; no era, tree, upkeep or empire-size tax exists, and none was invented.
5. **New-territory inheritance** — a conquest resets buildings and tech; whether that is the wanted
   rule is a design question.
6. **Buildings balance** — `BUILD_COST` untouched.
7. **Long-term economy balance** — untouched.
8. **The Windows `os.replace` dev/test race** — `reentry_authority_test.py` still fails
   intermittently on this developer machine with `PermissionError: [WinError 5]` on
   `economy.json.tmp → economy.json`, a file-lock race in the test temp directory. It passes on
   rerun (28 checks) and production is Docker/Ubuntu.
