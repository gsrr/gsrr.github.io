# Current Game Rules (as implemented) — Phase 2A STEP 1

Describes the CURRENT implementation (frontend `index.html`, backend `server.py`). Values are
copied verbatim; nothing here is a proposal. File:line references are approximate.

> **Authority summary.** Economy, recruitment, and technology are **backend-authoritative**
> (server computes cost/outcome, deducts gold, returns new state). **Battle is the exception**
> and is a Phase-2A STOP condition — see §F/§conflict.

---

## A. Gold / Economy  (backend-authoritative)

- Stored in per-room `economy.json`: `{ user: { population, gold, lastGold, troops{cav,archer,inf,spear}, buildings, tech, passcnt, conscript, conscriptBudget } }`.
- Constants (`server.py`): `GOLD_RATE = 0.10`, `GROW_SECONDS = 3600`, `ECON_MAX_CATCHUP = 72`, `ECON_START_POP = 100`, `ECON_START_TROOPS = 100`, `PASS_GOLD = 10000`, `DEFEND_GOLD = 50`, `ATTACK_FAIL_GOLD = 50`.
- New player seeded from the room config (`startPop/startGold/startTroops`) via `econ_get`.
- **Passive gold (per settlement in `econ_get`):**
  ```
  hours = floor((now - lastGold) / GROW_SECONDS)
  gold  = clampi( gold + min(hours, ECON_MAX_CATCHUP) * round( (population + regionPop) * GOLD_RATE ) )
  lastGold += hours * GROW_SECONDS      # advances clock → no double settlement
  ```
  where `regionPop` = sum of `pop` over territories owned by the user (`user_region_pop`).
- Population does **not** grow (hourly pop growth was removed; gold accrual only).
- **Gold sinks:** buildings `BUILD_COST = {armory:50, barracks:60, archery:80, stable:120}`; recruitment (§D); technology (§E); conscription budget.
- **Gold sources:** passive settlement; `PASS_GOLD` (+10000) per lesson pass via `/api/economy/pass`; `DEFEND_GOLD` (+50) on successful defense; (attacker −`ATTACK_FAIL_GOLD` 50 on failed attack).
- Offline income: catch-up capped at `ECON_MAX_CATCHUP` (72 h). No other income cap.

## B. Population

- **Static** territory `gamePopulation` lives in `world-data` (Phase 1A). On claim the backend sets the dynamic territory `pop` = `catalog.game_population(id)` (`server.py` `_handle_territory_claim`), so the dynamic `pop` mirrors the static value (kept for gold calc + backward compatibility).
- Population is not grown, not consumed by recruitment, and not changed by battle. Conquest sets the new region's `pop` from the catalog. Economy `population` (home) is the seeded value.

## C. Army  (units: infantry, archer, cavalry, spear)

- Territory garrison: `troops: [{type, hp}]`. Free pool: `economy.troops = {cav, archer, inf, spear}` (counts).
- Unit stats (`index.html` `TROOPS`): **all four have `atk:10, def:8`** (identical base). Kinds: `TROOP_KINDS/TROOP_ALL = (cav, archer, inf, spear)`.
- Counter multipliers (identical FE `atkBonus`/`defBonus` and BE `_atk_bonus`/`_def_bonus`):
  - attack: spear→cav ×1.2, cav→archer ×1.1, archer→(spear|inf) ×1.2, else ×1.0
  - defense: cav vs archer ×1.1, else ×1.0
- Serialization: garrison list of `{type,hp}`; pool dict of 4 ints. `_norm_troops` splits a legacy int evenly across the 4 kinds.

## D. Recruitment  (backend-authoritative)

Flow: frontend `terrRecruit` → `POST /api/territory/recruit` → `_handle_territory_recruit` validates + mutates + returns new gold/troops.
- `UNIT_COST = {inf:2, spear:3, archer:4, cav:5}` (identical FE/BE), `RECRUIT_BATCH = 10`.
- `cost = qty * UNIT_COST[unit]`; `qty` clamped 1..100000.
- Requires the producing building: `UNIT_BUILDING = {inf:barracks, spear:barracks, archer:archery, cav:stable}`.
- Territory recruit requires `owner == user`; home recruit (`@home`) needs the building in the economy.
- Deducts gold only (**no population cost**). Insufficient gold → 400 `{error, gold, cost}`.
- Frontend `UNIT_COST` is used only for display/preview; the server is authoritative.

## E. Technology  (backend-authoritative)

- Tracks: `atk` (forging), `def` (armor). `TECH_COST = {atk:[80,160,280], def:[80,160,280]}`, `TECH_MAX = 3` (identical FE/BE).
- Scope: per-territory `tech{atk,def}` (region armory) and per-home `economy.tech`. Requires an `armory`.
- `research_technology`: `cost = TECH_COST[track][level]`; needs gold ≥ cost; `level += 1`; returns new gold/tech. Backend-authoritative; frontend `TECH_COST` is display only.
- **Effect (used only inside battle) DIVERGES** — see §F:
  - Frontend: `techAtk = 0.10*atk` (forge **+10%/level**), `techDef = 0.10*def` (armor **+10%/level**).
  - Backend: `forge = 1 + 0.10*atk` (**+10%/level**, matches), `armor = 1 + 0.08*def` (**+8%/level**, differs).

## F. Battle — TWO implementations (STOP condition)

### F1. Frontend `runBattle` (`index.html`) — authoritative for PLAYER attacks
- Input: attacker troops, defender troops, defender tech; attacker uses **home** tech, defender uses **region** tech.
- Model: **per-unit sequential duel**. Defender order is **randomly shuffled**; defender **strikes first** each engagement; a slain attacker unit cannot retaliate.
- Per hit: `baseHit(A,D) = max(1, round(10*(atkBonus(A,D)+extraAtk) − 8*(defBonus(D,A)+extraDef)))`; `troopHit = max(1, round(baseHit * A.hp / DMG_SCALE))`, `DMG_SCALE = 12`. `extraAtk/extraDef` come from tech (0.10/level) plus a "closing +10%×engage" term for non-archer vs archer.
- Round cap 16; then compare residual hp (attacker needs `sa > sd`, ties → defender holds). Winner: attacker wins only if defender wiped and attacker survives.
- **Authority:** the client decides winner + survivors, then calls `POST /api/territory/attack-result` (which only awards gold from `win`) and, on a win, `release` + `claim` (client sends surviving troops). The backend **does not recompute or verify** the battle.

### F2. Backend `ai_move` (`server.py`) — authoritative for AI attacks
- Model: **aggregate force comparison**. `_force_power(force, enemy) = Σ hp * Σ_over_enemy_mix( frac * atkBonus(ty,ety) / defBonus(ety,ty) )`.
- Resolution: `ap = _force_power(atk,def)/armor * U(0.85,1.15)`, `dp = _force_power(def,atk)*forge*1.10 * U(0.85,1.15)`; attacker wins iff `ap > dp`. Survivor fraction on win: `max(0.2, min(0.9, 1 - dp/(ap+1)))`; defender loses ≤25% on a successful defense.
- `forge = 1 + 0.10*atk`, `armor = 1 + 0.08*def` (region tech). Single uniform RNG per side.

### Battle implementation comparison
| Rule | Frontend JS (player) | Backend Python (AI) | Same? |
|---|---|---|---|
| model | per-unit sequential duel | aggregate force-power | **NO** |
| base unit atk/def | 10 / 8 (all) | (uses hp × counter mult) | **NO** (different math) |
| attack counter (spear→cav etc.) | ×1.2 / ×1.1 / ×1.2 | ×1.2 / ×1.1 / ×1.2 | yes |
| defense counter (cav vs archer) | ×1.1 | ×1.1 | yes |
| attack tech | +10%/level (into baseHit) | ×(1+0.10·lvl) | effect same %, applied differently |
| defense tech | **+10%/level** | **+8%/level** | **NO** |
| randomness | shuffle defender order | ×U(0.85,1.15) per side | **NO** |
| casualty rule | per-hit hp subtraction | fraction of force | **NO** |
| winner | defender wiped & attacker alive; else residual hp | `ap > dp` | **NO** |
| tie handling | defender holds | n/a (continuous) | **NO** |
| survivors | remaining per-unit hp | force fraction | **NO** |
| **authority** | **client (trusted by server)** | **server** | **NO** |

## G. Conquest

- **Neutral claim** and **attack** are SEPARATE flows (should stay separate):
  - Neutral claim: `POST /api/territory/claim` — only on an unowned territory (backend validates identity/map/population, sets owner + garrison from client-sent surviving troops; population from catalog). No battle.
  - Attack (occupied): client `runBattle`; on win client calls `release` (territory → neutral) then `claim` (becomes owner with survivors). `attack-result` awards gold.
- **Attack eligibility today:** attacker must be logged in and have troops; target must be owned by someone else. **No adjacency, no source territory, no course requirement.** Any territory may be attacked regardless of location.
- Defeat: attacker survivors return to pool (client-side); owner unchanged; attacker −50 gold, defender +50.

## H. Existing AI (compatibility only)

- `ai_loop` iterates started rooms; each AI: `ai_econ` (home gold), `_ai_recruit` (spends all gold on a balanced buy), then `ai_move`: pick `attack` (a non-AI-owned territory) or `occupy` (a known unowned territory from the learned catalog), resolve via `_force_power`, mutate the store directly, log an event. AI reads the same `territory.json`/`economy.json`/learned catalog and uses the **backend** battle math (F2). It does not call the player HTTP endpoints.

---

## Duplicated logic (candidates for centralization)
- Counter multipliers, `UNIT_COST`, `TECH_COST`, `TECH_MAX`, `BUILD_COST`, `RECRUIT_BATCH` exist in **both** `index.html` and `server.py` (values identical → safe to centralize as backend-authoritative config; frontend keeps display copies).
- Battle math exists twice and **differs materially** (above) → cannot be consolidated without changing behavior on one side.
