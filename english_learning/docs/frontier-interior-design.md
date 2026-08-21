# Frontier / interior / isolated (Phase 13B)

The first foundation from [long-term-strategy-design.md](long-term-strategy-design.md): a large empire
should be managed by **strategic pressure**, not by repeating the same actions on every territory.

> **Phase 13B has NO gameplay effect.** The classification changes no legality, no economy, no reward
> and no learning state. It is strategic structure and presentation only, so the foundation can be
> validated before anything is balanced on top of it. This is asserted by test, not merely intended.

---

## 1. Authoritative inputs

Exactly two, both of which the game already owns:

| input | source | scope |
| --- | --- | --- |
| **ownership** | `room_path("territory.json")[territoryId]["owner"]`, guarded by `terr_lock` | per room |
| **adjacency** | the territory catalog's `adjacentTerritoryIds` (`world-data/territories/world.json`) | static |

Plus the requesting identity (`token_user`) — because "borders someone else" is meaningless without a
"me". Nothing else is consulted. The home base (`HOME_KEY`) is **excluded**: it is an economy record,
not a map territory, and it has no catalog entry and no adjacency.

## 2. The canonical algorithm

One definition, in `game/frontier.py`:

```python
def classify(territory_id, player, owner_of, neighbours_of):
    if not player:                              return None
    if owner_of(territory_id) != player:        return None      # not mine -> no classification
    nbrs = neighbours_of(territory_id)
    if not nbrs:                                return ISOLATED  # tested FIRST
    for n in nbrs:
        if owner_of(n) != player:               return FRONTIER  # neutral OR enemy OR AI
    return INTERIOR
```

`ISOLATED` is tested first and deliberately **overrides** the plain rule. A territory with no land
neighbours has no un-owned neighbour, so the plain rule would call it *interior* — true and useless.
"Safe" and "structurally unable to participate" are different facts, and the player needs the second.

The classifier is **pure**: no I/O, no catalog import, no mutation of its inputs (asserted by test). It
reaches adjacency only through the callback it is handed.

## 3. Edge cases — every one of them stated

| # | case | result | why |
| --- | --- | --- | --- |
| 1 | owned, adjacent to **enemy** | `frontier` | the enemy is "not mine" |
| 2 | owned, adjacent to **neutral** | `frontier` | an unclaimed neighbour is still a border you must watch — and it is the border you can most easily cross |
| 3 | owned, adjacent **only to my own** | `interior` | nothing to defend against by land |
| 4 | owned, **degree 0** | `isolated` | 90 of 250 world territories; see §4 |
| 5 | owned, **degree 1** | the ordinary rule — `frontier` if that one neighbour is not mine, `interior` if it is | no special case needed |
| 6 | a **fully-owned closed component** (e.g. UK + Ireland, the only 2-territory component) | `interior` for both | the rule is local. They are *also* structurally unreachable, which the local rule cannot express. Reported as a known limitation (§10) rather than given a fourth class this phase did not have a mandate to invent |
| 7 | **home base** (`HOME_KEY`) | never classified | not a map territory; no catalog entry, no adjacency |
| 8 | ownership changes after **combat** | recomputed on the next read | derived, never stored — see §5 |
| 9 | territory **released** | recomputed on the next read | same |
| 10 | **re-entry foothold** | classified like any other territory the moment it is owned | re-entry authority is untouched |
| 11 | **GLOBAL vs private rooms** | the store is per room, so classification is per room | the same account can be a 5-territory empire in one room and hold nothing in another |
| 12 | **AI-owned** territory | simply "not mine" → makes my neighbour `frontier`; the AI's own territory is classified for nobody | no special case in the classifier at all |

## 4. Zero-adjacency territories

Phase 13A measured 90 of 250 playable world territories with **degree 0** — 36 % of the map and 37 % of
world income, including Australia, Japan, Taiwan, Cuba, the Philippines, Singapore, New Zealand,
Greenland and Iceland. Because `can_attack` requires an owned *adjacent* source, each is claimable
while neutral and then permanently un-attackable.

13B does **not** pretend these are ordinary safe interior territories, and it does **not** invent
connectivity:

- they are classified `isolated`, a distinct status;
- the territory card says so in words: *"🏝️ Isolated — no land connection — sea routes are not
  modelled yet."*;
- Empire counts them separately, and its group description states that such a territory *"cannot be
  attacked over land, and it cannot attack out"*;
- the map gives them their own texture (dots, not the frontier hatch);
- and `game/frontier.py` is asserted by test to contain no mention of sea, port, ship or navy, with
  adjacency itself unchanged at 900 edge-ends and 0 cross-map edges.

Strategic connectivity for these territories is Phase 13H's job (sea zones + ports), and until then the
limitation is **visible instead of silently flattering**.

## 5. Why the classification is derived, not stored

Because combat changes neighbours. A stored `frontier: true` would be wrong the instant an adjacent
territory changed hands, and every ownership-changing path — claim, attack, release, re-entry, an AI
tick — would need to remember to repair the flags of every neighbour. That is a migration and a class
of bug in exchange for nothing: deriving it costs **0.09 ms for a 250-territory world** (measured).

A test reads `territory.json` after a sequence of real claims and asserts the words `frontier`,
`interior`, `isolated` and `strategic` appear nowhere in it.

**Proof that it is dynamic** (from the test suite, using real endpoints): Canada's only neighbour is the
United States, whose other neighbour is Mexico.

```
claim Canada            -> Canada: frontier      (the US is not mine)
claim the United States -> Canada: interior      <-- reclassified with no migration
                           the US: frontier      (it still borders Mexico)
a rival claims Mexico   -> the US: frontier      (same class, different reason)
                           Canada: interior      (unaffected)
```

## 6. API impact

`GET /api/territory` gains exactly two things:

```jsonc
{
  "holders": {
    "world:us": { "owner": "me", ..., "mine": true, "strategic": "frontier" },   // MY territory
    "world:mx": { "owner": "rival", "pop": 120, "hidden": true, "ai": false }    // unchanged: no class
  },
  "counts": { ... },                                                             // unchanged
  "strategicSummary": { "frontier": 1, "interior": 1, "isolated": 1, "total": 3 }
}
```

- `strategic` appears **only on territories the requesting player owns**. Classification is relative to
  an owner, and *"is that enemy territory interior?"* is a question about someone else's holdings.
  Publishing it would be a fog-of-war leak, so the endpoint does not answer it — asserted by test from
  both players' perspectives.
- `strategicSummary` describes **the requesting player's own empire only**.
- No existing field changed shape, and no test pinned the holder key set, so nothing was loosened to
  accommodate this. The new keys are pinned by `tests/frontier_classification_test.py`.
- **The `game/config.py` fingerprint is unchanged** (`736503ae2c4f5fa5`). Its payload is an explicit
  allowlist of *balance constants*; a derived classifier introduces none, so there was no fingerprint
  contract question to escalate.

## 7. Map presentation

Ownership already owns **fill** on the land path. Selection, attack-source and attack-target already
own **stroke**. A frontier cue may use neither without destroying something the player needs more, so
it gets its own channel:

- a **texture overlay** in its own `<g class="geo-strategic">`, above the land and below the markers and
  labels, `pointer-events: none` so it can never intercept a click;
- **frontier = diagonal hatch**, **isolated = dots**, **interior = nothing at all** (the quiet majority
  stays quiet);
- the overlay clones only the player's own frontier/isolated land paths — a handful of nodes, never 250;
- `stroke: none` on the overlay, so it does not inherit the land stroke and draw a competing outline;
- suppressed at **FAR** zoom, where 250 textures would be noise rather than information;
- **not colour alone**: two different *shapes*, plus the classification in words on the territory card.

Two bugs were found here and are worth recording, because both looked fine on screen:

1. The `<pattern>` was first created with `element.innerHTML`, which runs the **HTML** parser and puts
   `<pattern>` in the XHTML namespace. `fill: url(#stratFrontier)` then silently fell back to a solid
   colour — a colour-only cue, which is exactly what this phase forbids. Fixed with `createElementNS`.
2. `.geo-svg path { fill: #f2ddb0 }` has specificity (0,1,1) and beat `.geo-strat-frontier` (0,1,0), so
   the overlay rendered as a solid land-coloured patch. Fixed by selecting `path.geo-strat-*`.

Both were caught by asserting the **computed** fill rather than trusting the markup, and both are now
pinned by test — including a pin on the construction method, because the markup-looking version was
the bug.

The 12C/12D camera and selection contract is **frozen**: `attachPanZoom` and `hudSelect` are asserted
to contain no reference to the classification at all.

## 8. Empire presentation

Empire opens on a **strategic overview**, not on a management table:

```
🗺️ Overview   ⚔️ Forces   🏛️ Buildings   🏭 Technology     <- Overview is the default area

   47 Territories     12 Frontier     29 Interior     6 Isolated

 ▸ ⚔️ Frontier  12   Borders territory you do not control. This is where pressure matters.
 ▸ 🛡️ Interior  29   Every land neighbour is yours. Nothing here needs attention.
 ▸ 🏝️ Isolated   6   No land connection at all — it cannot be attacked over land, and it cannot
                     attack out. Sea routes are not modelled yet.
```

- the four counts come from **the server's own `strategicSummary`**, never from anything counted
  client-side, so Empire and the board cannot disagree;
- the three groups are **closed by default and built on first open**, so a 100-territory empire puts
  *zero* territory chips in the DOM until the player asks for them;
- a chip is a **drill-down to the board** — it closes Empire, selects that territory and points the
  camera at it. It is never a management form;
- expanded groups are remembered for the session, because `openEmpire()` paints once from cache and
  again when fresh data lands, and without that the second paint collapsed what the player had opened;
- **no "threat level"** is shown. The server publishes no enemy strength for territory the player does
  not own, so any threat figure would be invented.

Forces, Buildings and Technology are unchanged and still one click away.

### Management burden, measured

`node scratchpad/burden_13b.js` and `burden2_13b.js`, counting what Empire renders **before** any
deliberate drill-down (50/100/250 use a synthetic ownership cache, since claiming costs troops and a
real empire stalls near 45 in a fresh room — labelled as such in the output):

| territories | rows in the DOM | visible rows | management forms | render | the pre-13B default area (Forces) would render |
| --- | --- | --- | --- | --- | --- |
| 5 | 0 | 0 | 0 | 2.6 ms | 6 rows, 6 Recruit buttons |
| 20 | 0 | 0 | 0 | 1.5 ms | 21 rows, 21 buttons |
| 50 | 0 | 0 | 0 | 1.8 ms | 51 rows, 51 buttons |
| 100 | 0 | 0 | 0 | 0.6 ms | 101 rows, 101 buttons |
| 250 | 0 | 0 | 0 | 0.8 ms | 251 rows, 251 buttons |

Opening the Frontier group at 100 territories then yields 58 chips — because the player asked for them.
The burden is now **flat in empire size**, which is the whole point of Phase 13A's §15 budget.

## 9. Performance

| measurement | result |
| --- | --- |
| `classify_all` over 250 territories (120 owned) | **0.09 ms** |
| Empire overview render, 5 → 250 territories | **0.6 – 2.6 ms**, flat |
| 30 camera zoom steps | **0 fetches**, **0 territory DOM rebuilds**, **3.7 ms/step** |
| map redraw | the overlay clones only own frontier/isolated paths (a handful), on `colorize()` and on fresh territory data — never per pointermove |

Nothing expensive runs on camera movement: the camera is asserted by test to contain no reference to
the classification, and `paintStrategic()` is asserted to fetch nothing.

## 10. Known limitations

- **A fully-owned closed component reports `interior`.** The UK + Ireland pair (the map's only
  2-territory component) is unreachable by land once both are held, but the local rule cannot say so.
  Whether that deserves a fourth class — or whether `isolated` should mean "in a fully-owned closed
  component" rather than "degree 0" — is a product decision, added to §21 of the design doc.
- **The frontier texture is per-territory, not a drawn border line.** A true front *line* would need
  edge geometry the catalog does not carry.
- **Interior is invisible on the map by design.** A player cannot tell interior from unowned-but-quiet
  at a glance; ownership colour already carries that.
- **No threat information at all.** Correct for now (fog of war), but it means "where pressure is
  likely to matter" is answered only by *count*, not by strength.
- `reentry_authority_test.py` still fails intermittently on this Windows dev machine
  (`PermissionError [WinError 5]` on `economy.json.tmp → economy.json`) and passes standalone with 28
  checks. A test-harness persistence race; production is Docker/Ubuntu.

## 11. Future hooks

Deliberately **not** built, but this is what later phases attach to:

| phase | what it needs from here |
| --- | --- |
| **13C** regions | group frontier/interior counts per region rather than per empire |
| **13D** field armies | armies are hosted at the **frontier**; `classify` becomes gameplay authority, which is why it already lives in `game/` |
| **13E** supply / upkeep | **interior** territory generates supply; the count is already authoritative |
| **13H** sea zones | `isolated` stops being a dead end: the classifier gains a second adjacency source and its `neighbours_of` callback is the only thing that changes |
| **13I** AI | the AI can read the same classifier to prefer pressure at a real front |

The signature was chosen with that in mind: `classify(tid, player, owner_of, neighbours_of)` takes
adjacency as a **callback**, so adding sea routes in 13H changes what is passed in, not the rule.
