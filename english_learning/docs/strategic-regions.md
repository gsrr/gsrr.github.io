# Strategic regions (Phase 13C)

Phase 13B answered *"is this territory exposed?"*. This answers the question a player with 47
territories actually asks:

> **Where is my empire under pressure?**

without making them inspect dozens of territories one at a time.

```
World
  └── strategic region        <-- 13C: an AGGREGATION / MANAGEMENT VIEW
        └── territory
              └── derived strategic state   (13B: frontier / interior / isolated)
```

> **A region is an aggregation view and nothing else.** It is **not** an ownership unit, a combat unit,
> an income unit, a supply unit, a technology unit, a building unit or an army unit. Nothing in
> `can_attack`, claim, release, re-entry, recruit, research, build, income, rewards, the AI or
> `learning/` consults it. Promoting regions into gameplay authority is a later, separately reviewed
> phase. This is asserted by test, not merely intended.

---

## 1. Membership source

`world-data/territories/<map>.json` → `metadata.continent`.

### The audit that chose it

Every existing concept that groups world territories was measured before anything was designed:

| candidate | source of truth | groups | assigned | unassigned | duplicates | deterministic | geography or gameplay | affects rendering | authoritative anywhere |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **`metadata.continent`** | `world-data/territories/world.json` | 6 | **244 / 250** *(before this phase)* | 6 | none | yes | geography | no | no — nothing read it |
| **`WORLD_CONTINENTS`** | `index.html` (client) | 6 | **250 / 250** | 0 | none | yes | geography | **yes** — the continent tint and the 12C camera presets | yes, client-side |
| `regionCode` | catalog | 250 | 250 | 0 | n/a | yes | it is the territory's **own** code (`ad`, `fr`), not a group | no | yes (identity) |
| `mapId` | catalog | 4 | 318 | 0 | none | yes | which SVG a territory belongs to | yes | yes |
| `childMaps` in `maps.json` | catalog | 1 relation (taiwan→taipei) | n/a | n/a | n/a | yes | the **retired container** relation | no | no — 10A.3 removed the route |
| `spec.drill` | (removed) | — | — | — | — | — | the retired container model | — | **gone in 12D** |

Two findings:

1. **`mapId` is not a candidate.** It answers "which map?", and the game has exactly one playable map.
2. **The complete partition already existed — in the client.** `metadata.continent` covered 244 of 250;
   the six it missed are exactly the six Phase 10C had to work around in `WORLD_CONTINENTS`, because
   `drawGeo()` filters on that table and an unlisted territory was *unreachable in the UI*. So the
   complete, single-valued, authored partition has shipped since 10C — just not in the data.

### What this phase did about that

Rather than leave membership split between a 244-value data file and a 250-value client table — the
exact drift hazard 13B was careful to avoid — the catalog was reconciled with the partition the product
already ships, using 10C's own documented rationale:

```
bv  Bouvet Island                        -> af    (South Atlantic)
go  Glorioso Islands                     -> af    (Mozambique Channel)
ju  Juan De Nova Island                  -> af    (Mozambique Channel)
tf  French Southern and Antarctic Lands  -> af    (Indian Ocean, nearest landmass Africa)
gs  South Georgia and South Sandwich Is. -> sa    (beside the Falklands, already sa)
hm  Heard Island and McDonald Islands    -> oc    (an Australian external territory)
```

This is a **metadata reconciliation, not a new partition** — every value already shipped. The diff is
six `metadata.continent` additions and nothing else: ids, adjacency, populations, `svgPathKeys` and
`mapId` are asserted unchanged. All six are zero-adjacency islands, so **no connectivity is created,
implied or changed**.

The client keeps its `WORLD_CONTINENTS` table, because the tint and the 12C camera presets depend on it
and this phase does not disturb the frozen camera. **A test asserts the two agree for all 250
territories**, which converts the duplicate from a latent drift bug into a pinned invariant.

## 2. Completeness proof

```
total      : 250
assigned   : 250
unassigned : NONE
regions    : {af: 62, as: 53, eu: 53, na: 41, oc: 26, sa: 15}   -> sums to 250
single-valued: True  (metadata.continent is one string per territory, so duplicates are structurally
                      impossible; asserted anyway)
client table agreement: 250 / 250, zero mismatches
```

Six regions: **Africa, Asia, Europe, N. America, Oceania, S. America.**

## 3. Aggregation algorithm

`game/regions.py`. One canonical aggregator, built **on top of** `game/frontier.py` — it never
re-implements the frontier rule (asserted: `summarize()` contains no adjacency logic).

```python
for tid in playable_territory_ids():
    r = region_of(tid, meta_of)              # stable geography
    row.total += 1
    owner = owner_of(tid)                    # authoritative ownership, this room
    if not owner:            row.neutral  += 1
    elif owner == player:    row.owned += 1; row[classify(tid, player, ...)] += 1
    else:                    row.others   += 1
```

Rows are sorted **most-exposed first** (frontier desc, then owned desc, then name), so the region a
player should look at is the one at the top, and the order does not jitter.

### Two orthogonal concepts, kept orthogonal

```
region_of(territory)                  stable GEOGRAPHY   — never ownership, never frontier state
classify(player, territory, room)     dynamic STATE      — the 13B rule, unchanged
```

Deriving region membership from ownership — or from frontier/interior — would collapse the two and make
*"where am I under pressure?"* unanswerable, because the grouping would move with the answer.

### Deliberately absent

No threat score, danger score, pressure percentage, supply strength, development level, region level,
or any "control" figure with gameplay meaning. Asserted by a scan over the module's **code** (its
docstring names them in the sentence that forbids them). `7 / 18 owned` is a display fraction and
nothing more.

## 4. API contract

The 13B strategic response is **extended**; no new endpoint. `GET /api/territory` gains:

```jsonc
{
  "holders": { ... },                  // unchanged
  "counts": { ... },                   // unchanged
  "strategicSummary": { ... },         // 13B, unchanged
  "regions": [                         // 13C: one row per region, six rows, never one per territory
    { "region": "eu", "label": "Europe", "total": 53, "owned": 4,
      "frontier": 2, "interior": 2, "isolated": 0, "neutral": 49, "others": 0 }
  ],
  "regionNote": { "isolatedOwned": 1 } // 13C: a bare count, see §6
}
```

- **six rows, not 250.** Measured: the whole `/api/territory` payload is **2,495 bytes** with six
  territories owned, of which the region block is **817 bytes**.
- **the catalogue is not resent.** A row carries no `displayName`, `adjacentTerritoryIds`,
  `svgPathKeys`, `localizedNames` or `gamePopulation` — the client already has all of it. Asserted.
- **`others` is a count only.** No identity, no strength, no garrison, no "how many different rivals".
  It is derivable from ownership the board already shows, so it leaks nothing new — asserted with a
  scan for the rival's account name and for troop/tech words.
- **each viewer sees their own empire.** `owned`/`frontier`/`interior`/`isolated` are the requesting
  player's; a rival's identical request aggregates theirs.
- **no exact-key test broke.** Nothing pinned the response's key set, so nothing was loosened; the new
  keys are now pinned by `tests/strategic_regions_test.py`.

## 5. Dynamic behaviour

Membership is stable; the counts are state. Proven through the real endpoints:

| action | effect |
| --- | --- |
| claim Canada (N. America) | that region: `owned 0→1`, `frontier 0→1`, `neutral 41→40`. Every other region untouched. |
| claim the United States | `owned 1→2`, and **Canada flips frontier → interior** in the same read, because the US completed its envelope |
| claim Australia (degree 0) | Oceania: `isolated 0→1`, `frontier` stays 0 |
| a rival claims Mexico | N. America: `others 0→1`; nothing else about them is published |
| release the US | the counts reverse and Canada is exposed again |
| the same account in another room | that room aggregates **nothing**; all 250 still neutral there |

**No migration and no persistence repair is possible, because nothing is persisted.** A test reads
`territory.json` and asserts the words `region`, `continent`, `frontier`, `interior`, `isolated` and
`strategic` appear nowhere in it.

## 6. The closed-component limitation — stated, not solved

13B proved that `interior` means **"every land neighbour is mine"**. It does **not** mean "connected to
a useful front", and this phase does not pretend otherwise. Interior is never called:

> ~~safe supply~~ · ~~supporting territory~~ · ~~connected rear~~ · ~~productive rear~~ ·
> ~~secure logistics~~ · ~~supply region~~ · ~~development region~~ · ~~army region~~

(all eight are asserted absent from the whole of `index.html`).

What the aggregation *may* report is factual counts, and `regionNote` carries exactly one:
`isolatedOwned`. The Empire copy accompanying it says:

> *"N of your territories have no land connection at all. Interior means every land neighbour is yours —
> it does not mean a territory is connected to a front, and sea routes are not modelled yet."*

The map's only fully-owned closed component (the UK + Ireland pair) still reports `interior` for both,
which is the local rule's honest answer. Whether that deserves its own class is recorded as a product
decision in `docs/long-term-strategy-design.md` §21 item 11. **No connectivity gameplay was created.**

## 7. Map behaviour

**No new map mode.** There is no region mode, no container mode, no filtered map, no region ownership
layer and no region modal — the six names 12C/12D spent two phases removing. Asserted by name, and the
board renderer and the camera are asserted to contain no reference to regions at all.

A region row offers **"🗺 Show on map"**, which may only: close Empire, and move the existing camera.
`geoFocusRegion()` is a thin lookup over the **12C continent camera presets** — which are keyed by the
very continent codes the catalog uses, so a region resolves to an existing preset with no new geometry.
The fallback (if a future region set does not line up) computes a focus rectangle from the region's own
members; still a camera move, still nothing else. It is asserted unable to reach `drawGeo`,
`renderGeoMap`, `groupFilter`, a `viewBox` write, `paths.filter`, `openModal`, `innerHTML`, `hudSelect`
or `refreshMap`.

Measured: Show on map moved the camera `1.32 → 3.25×` while **all 250 territories stayed rendered**, the
viewBox stayed `0 0 1010 666`, the viewport ratio stayed 1.6, and the selection was preserved.

**No permanent region boundaries were added to the board.** Ownership and the 13B frontier/isolated
textures already consume the available visual channels, so region information lives in Empire. The
region counts there carry a **glyph** as well as a colour (⚔ frontier, ■ interior, ● isolated), so they
are not colour-only.

## 8. Empire information architecture

```
🗺️ Overview    ⚔️ Forces    🏛️ Buildings    🏭 Technology

   47 Territories     12 Frontier     29 Interior     6 Isolated      <- empire (13B)

REGIONS · 3 of 6 with holdings                                        <- regions (13C)
 ▸ Europe        4 / 53 owned      ⚔ 2   ■ 2
 ▸ N. America    2 / 41 owned      ⚔ 1   ■ 1
 ▸ Oceania       1 / 26 owned              ● 1

ALL TERRITORIES                                                       <- 13B lists, unchanged
 ▸ ⚔️ Frontier  12 · ▸ 🛡️ Interior  29 · ▸ 🏝️ Isolated  6
```

- three tiers, in that order — asserted by index position, not by eye;
- region rows are **compact and closed by default**, and their contents are **built on first open**;
- a drill-down lists that region's own territories **grouped Frontier / Interior / Isolated**, using the
  server's per-territory classification, and ends with the factual remainder:
  *"50 unclaimed · 0 held by others · 53 in the region."*;
- **no management control appears in any region summary or drill-down** — asserted against
  `buildingsPanel`, `openBuildingDetail`, `deployPanel`, `openTray`, `openConscriptDetail`, `emp-act`,
  `<input>` and `<select>`. Territory management stays in Forces / Buildings / Technology, untouched;
- a territory chip drills down **to the board**, not into a form;
- which rows are expanded is remembered for the session only (a plain `Set`, never stored), because
  `openEmpire()` paints once from cache and again when fresh data lands.

## 9. Performance

| measurement | result |
| --- | --- |
| `frontier.classify_all` over 250 territories | **0.09 ms** (13B, unchanged) |
| `regions.summarize` over 250 territories | **0.33 ms** |
| `/api/territory` payload | **2,495 bytes**, of which the region block is **817** |
| Empire initial render, 5 → 250 owned | **1.5 – 3.0 ms**, flat |
| 30 camera zoom steps | **0 fetches**, **0 territory DOM rebuilds** |
| opening/closing a region | the map is **not** redrawn — same `<svg>` node, same 250 paths |

### Scale: O(regions), not O(owned)

| owned | region rows | territory rows | visible | management controls | DOM nodes | render | source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 3 | 0 | 0 | 0 | 56 | 3.0 ms | real |
| 20 | 6 | 0 | 0 | 0 | 78 | 1.5 ms | real |
| 50 | 6 | 0 | 0 | 0 | 81 | 1.8 ms | synthetic |
| 100 | 6 | 0 | 0 | 0 | 85 | 1.7 ms | synthetic |
| **250** | **6** | **0** | **0** | **0** | **83** | **1.7 ms** | synthetic |

Region rows cap at six because there are six regions. Opening **one** region at 250 owned then yields
62 chips (Africa, the largest) — a deliberate drill-down, and still zero management controls.

*(5 and 20 are real server state. 50/100/250 feed the client a synthetic ownership cache computed by the
same rule the server uses, because claiming costs troops and a real empire stalls near 45 in a fresh
room; the rows are labelled accordingly.)*

## 10. No gameplay effect

Asserted, not assumed: an attack across a region boundary resolves normally; an attack out of an
isolated territory is still refused `not_adjacent` by the pre-existing adjacency rule; build / recruit /
research behave exactly as before and **no refusal ever cites a region**; the learning state is
byte-identical before and after; and the typed Read Along accommodation is untouched. Adjacency remains
900 edge-ends, 0 cross-map, 90 degree-0 territories, components [135, 23, 2] + 90 singletons.

## 11. Future dependency graph

```
13B frontier classifier ──┬─> 13C region aggregation  (this phase: view only)
                          │        │
                          │        ├─> 13D field armies      needs "which region is a front?"
                          │        ├─> 13E supply / upkeep    needs per-region interior counts
                          │        └─> 13I AI                 can read the same aggregation
                          │
                          └─> 13H sea zones            changes what `neighbours_of` returns, so BOTH
                                                       the classifier and this aggregation follow for
                                                       free — and `isolated` stops being a dead end
```

Regions are deliberately **not** called supply regions, development regions or army regions: those
decisions have not been made. When one of them is made, this module is where the counts already are —
but the promotion from *view* to *authority* is a separate reviewed phase.

## 12. Review addendum: why `WORLD_CONTINENTS` stays

The 13C review asked whether the client's `WORLD_CONTINENTS` table could be generated from — or
replaced by — the catalogue, so that region membership has exactly one authority instead of two
tables that agree by inspection.

**It cannot, not without widening this phase's scope.** The reason is what the table actually drives.
`WORLD_CONTINENTS` is expanded once into `WORLD_CODE_CONT`, and that map decides which SVG paths are
territories at all:

```js
const grouped = !!spec.grouped;                                      // GAME_MAPS.world sets it true
if (grouped) paths = paths.filter(p => WORLD_CODE_CONT[(p.id || "").toLowerCase()]);
```

It also feeds `worldContinentKey(p.id)`, which builds `contBounds` and therefore the six continent
camera presets. So the table is not a second copy of region membership; it is the client's
**presentation and path-selection** data, which happens to be keyed by the same continent codes.

Making that filter catalogue-driven would put the board's first paint behind a fetch.
`loadTerritoryCatalog()` is invoked once at boot with no callback and nothing awaits it, and
`drawGeo()` documents a fallback for the catalogue being absent. Measured in real Chrome with the
catalogue fetch blocked:

| | normal | `world-data/maps.json` blocked |
| --- | --- | --- |
| `TERR_CATALOG.loaded` | `true` | `false` |
| catalogue entries | 318 | 0 |
| board drawn | yes | yes |
| `path.geo-region` territories | 250 | **250** |
| continent shortcuts | 6 | 6 |
| page errors | none | none |

The board renders every territory and every camera shortcut with no catalogue at all. Removing
`WORLD_CONTINENTS` in favour of catalogue data would change initial map loading and offline/static
behaviour, both of which this review put out of scope.

**Decision.** `metadata.continent` in `world-data/` remains the single *region* authority: it is what
`game/regions.py` reads, what the server aggregates, and what the Empire UI and the Show-on-map
camera jump follow. `WORLD_CONTINENTS` remains *presentation and path-selection* data. The equality
test stays — `tests/strategic_regions_client.test.js` pins that the two tables agree for all 250
territories — so the pair cannot silently diverge, and the day the client's boot order is reworked is
the day the duplication can actually be removed.
