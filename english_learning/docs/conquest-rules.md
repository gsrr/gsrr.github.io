# Conquest rules (Phase 2B — territorial attack)

*Authoritative summary of how territory combat works after Phase 2B. Battle math itself is unchanged
from Phase 2A (see `docs/current-game-rules.md`); this document covers the **conquest orchestration**
that surrounds the battle engine.*

## Core rule — attacks are territorial

An enemy-territory attack must originate from **one of your own territories that is adjacent to the
target**. The committed squad comes from that **source territory's garrison**, not the global pool.

```
you own SOURCE  →  SOURCE ↔ TARGET adjacent (World-Domain)  →  SOURCE garrison covers the squad
        →  backend battle (canonical engine)  →  WIN: TARGET becomes yours / LOSS: survivors return to SOURCE
```

## Eligibility — `game.conquest.can_attack(player, source, target, squad, world, territories)`

Pure Game-Domain function returning `AttackEligibility(allowed, reason)`. Stable reasons (safe for
UI/tests): `source_not_found`, `target_not_found`, `same_territory`, `source_not_owned`,
`target_already_owned`, `target_not_attackable` (neutral → use claim), `not_adjacent`,
`invalid_squad`, `insufficient_source_garrison`. Adjacency comes **only** from World-Domain
`are_adjacent()` (world-data `adjacentTerritoryIds`) — never SVG geometry or coordinates.

Phase 3A added a tenth reason, `qualification_required`, for a Learning gate at the end of this
function. **Phase 10A.3R retired it**: the reason is gone from `REASONS`, the gate is gone from the
body, and `player_qualifications` / `require_qualifications` remain in the signature only as
accepted-and-ignored parameters. The nine reasons above are the complete set again.

Map scope is enforced by the HTTP routes rather than by this pure function: since Phase 10A.3 both
`/api/territory/claim` and **both ends** of `/api/territory/attack` refuse a territory outside
`server.allowed_game_maps()` — today `{"world"}` — with `400 {"reason": "inactive_map"}`, before any
state changes.

## Source territory

- The authoritative request requires **`sourceTerritoryId`** + **`targetTerritoryId`** + `squad`.
  The backend canonicalizes both ids independently and **never infers the source** — an old client
  that omits it is rejected (`source_not_found`), not silently patched.
- The squad is committed from the source garrison. Committing the **entire** source garrison is
  allowed (no mandatory minimum garrison in Phase 2B).
- Attacker tech = the **source** territory's tech; defender tech = the **target** territory's tech.

## Survivor rule (server-authoritative, atomic)

| Outcome | Source territory | Target territory |
|---|---|---|
| **WIN** | garrison − committed squad | ownership → attacker; garrison = attacker survivors; population preserved; buildings/tech reset (fresh hold) |
| **LOSS** | (garrison − committed squad) **+ attacker survivors returned** | owner unchanged; garrison = defender survivors |

Survivors of a failed attack **return to the source garrison** — never the global pool, never vanish.
Gold is unchanged from 2A: WIN → no change; LOSS → attacker `−50`, real non-AI defender `+50`.

## Neutral claim exception (unchanged, separate flow)

`POST /api/territory/claim` still occupies a **neutral** (unowned) territory without a battle and
without adjacency — this is the bootstrap so a player with no territory can still start. Claim is
restricted server-side to **neutral or your own** territories (it cannot seize a held enemy region —
that requires an attack). Neutral expansion after you already own land is likewise still claim-based
(no battle) and was intentionally **not** forced into combat. A future phase may unify neutral
expansion; Phase 2B leaves it as-is.

## Island / no-neighbour limitation

Phase 1C models **land adjacency only**, so many territories have zero neighbours (Japan, Taiwan,
Australia, New Zealand, most islands; UK, and cross-strait pairs like Taiwan↔Fujian). Under Phase 2B
those territories **cannot be conquered by land** and cannot launch land attacks across the sea. This
is an expected, documented limitation — **no fake adjacency was added**. Sea routes / ports / special
connections are a future phase. The legacy non-geo "trail" lesson nodes (`openOutpost`) used to
share this limitation — their pseudo-territories were not in the adjacency graph. **Phase 7G removed
that conquest surface entirely**: those nodes are keyed by lesson file, never resolved to a canonical
territory (`/api/territory/claim` answered `400 unresolved`), and are now learning-only panels.

## Same-map rule

Attacks stay within one adjacency graph. Map hierarchy (e.g. `taiwan:taipei-city` → `taipei:*`) is for
rendering/navigation only, never an attack edge. Cross-map pairs are never adjacent, so `can_attack`
returns `not_adjacent` for them.

## AI attack source

AI uses the **same** `can_attack` + `resolve_attack` + `apply_territorial_attack` path — no AI-only
shortcut, no magic/global army for attacks. AI target selection preserves its prior "random enemy
region" flavour but is now restricted to targets that have an **adjacent AI-owned source with a
garrison**. When several owned sources border a target, the source is chosen deterministically:
**highest garrison total, ties broken by smallest canonical id**. If no valid (source, target) pair
exists (e.g. the AI only holds an island), the AI simply does not attack — it never throws. AI
neutral **occupy** still uses the AI's global pool (unchanged); AI recruitment/research timing is
unchanged.

## Global troop pool — remaining purposes after Phase 2B

The per-player global pool (`economy.json → <user>.troops`) is **no longer** the source of enemy
attacks. It remains in use for:
- **Recruitment staging** at `@home` (`POST /api/territory/recruit` with `@home`).
- **Neutral claim / occupy** (deploying troops onto an unowned territory).
- **Own-territory redeploy** (pool + garrison redeployment).
- A future reserve/revival system (not implemented).

Territory recruitment (`recruit` on an owned region) still adds directly to that region's garrison, so
garrisons — the new attack source — are filled by territory recruitment and the hourly garrison growth.

## Authority / security

The attack request is **intent only**. The server independently validates source ownership, source
garrison sufficiency, adjacency, target ownership, and the committed squad, then computes the battle
(seeded defender order) and all resulting state. Clients cannot forge winner, survivors, ownership,
gold, adjacency, or garrison — every such field in the request body is ignored. Frontend adjacency
filtering is **advisory** (highlighting valid sources) and never a source of authority.
