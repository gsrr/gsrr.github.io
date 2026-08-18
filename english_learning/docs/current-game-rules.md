# Current Game Rules (as implemented) — Phase 2A STEP 1

Describes the CURRENT implementation (frontend `index.html`, backend `server.py`). Values are
copied verbatim; nothing here is a proposal. File:line references are approximate.

> **Authority summary.** Economy, recruitment, and technology are **backend-authoritative**
> (server computes cost/outcome, deducts gold, returns new state). **Battle is the exception**
> and is a Phase-2A STOP condition — see §F/§conflict.

---

## A. Gold / Economy  (backend-authoritative)

- Stored in per-room `economy.json`: `{ user: { population, gold, lastGold, troops{cav,archer,inf,spear}, buildings, tech, conscript, conscriptBudget } }`.

## Learning authority (Phase 7F.3)

There is exactly ONE meaning for each learning concept, and it lives on the server.

| Concept | Authoritative source | Player wording |
|---|---|---|
| Current passing state | `currentPolicySatisfied` | Passing / Needs Review (live; may fall after a worse retry) |
| Permanent mastery | `activePolicyCompleted` | ⭐ Mastered (sticky — a worse retry never removes it) |
| Progress | `completedActivityIds` / `requiredActivityIds` / `missingActivityIds` | `x / y activities completed` |
| Conquest eligibility | server-held qualifications | requirement met / missing |
| Official shared completion | server-side count of `activePolicyCompleted` (`server.py _mastered_lesson_count`) | leaderboard |

**Client-local, non-authoritative.** `localStorage["score:<user>:<contentPath>"]` and the average over
it (historically "Rule B") are **practice data only**. They may mean: practice score, practice
average, personal best, immediate in-activity feedback, local navigation state (level-tab locking),
practice statistics and practice milestones. They may **not** mean: lesson completed, lesson
mastered, current passing state, qualification earned, territory unlocked, campaign completion,
reward eligibility, or official shared completion count.

Why: the local average is player-editable, carries no policy version, keys off manifest levels rather
than registry activity ids, and is all-or-nothing over levels that may never have been scored. Phase
7F.3 demonstrated five concrete divergences from the authoritative state (forged pass vs
unsatisfied policy; local fail vs earned mastery; real evidence with an empty cache; unreconciled
stale keys for retired content; version blindness).

**There is no Rule B exception. Phase 7G closed the last one.**

### Two map surfaces, two different concepts

| Surface | What it is | Conquest? |
|---|---|---|
| `openRegion()` — geo maps (Pre-A1 Taiwan, China, World) | **canonical territories** with catalog ids, populations and designer-owned learning requirements | yes — claim/attack, server-verified |
| `openOutpost()` — board-map nodes (levels with no geo map: A1 / A2 / B1) | **learning nodes**: a lesson's identity, its authoritative state, and one way into it | **no** |

A board-map node is **not a claimable territory** and never was: those nodes are keyed by lesson file
(`A1/001`), which is not a canonical territory id — `resolve_any('A1/001')` returns `None` and
`POST /api/territory/claim` answers `400 unresolved`. Until Phase 7G the panel nonetheless rendered
population, garrison, owner, Occupy/Deploy, buildings and an attack panel, gated by the local
practice average. Phase 7G removed that conquest half outright rather than disabling it, which also
removed the last place a local score controlled a world action.

Local practice scores unlock nothing anywhere in the product.

### Exam / checkpoint progression (Phase 7H.1)

The per-level boss exam writes `localStorage["exam:<user>:<levelId>"]`. It is a **recommended local
checkpoint**, and that is all:

- stored in local browser/profile state, and carried between devices only inside the opaque `sdata`
  snapshot the server stores **without interpreting**;
- **not server-authoritative** — `server.py` contains no concept of an exam and never validates it;
- **not** learning completion, mastery, qualification, campaign progress, reward, conquest authority
  or economic authority;
- **does not prevent access to a level.** Nothing in `selectLevel()` / `renderGeoMap()` consults it,
  so a level was always reachable. Before Phase 7H.1 the level card nonetheless showed a padlock and
  a disabled button; that presentation claimed a rule the code never enforced, so the padlock and the
  disable were removed. A level whose checkpoint is not yet done is shown as
  🧭 *"Recommended: pass the … test first"* and stays selectable.

Passing it reads "Checkpoint complete — *next level* is ready for you", never "unlocked", because
nothing was locked. It is genuine practice progress and is presented as such.

### Boss / checkpoint battle (Phase 8D)

The boss battle is a **client-local challenge simulation**. It has no authoritative consequence at
all:

- it does **not** consume, restore, damage or create the player's persistent troop pool. The squad
  you pick is **copied** into challenge-local units; damage lands on the copy;
- it grants **no** gold, qualification, mastery, territory or server progression;
- winning sets only the local checkpoint (`setExamPassed`, above);
- the boss army (`makeBossSquad`) and the question pool (`buildExamPool`) are assembled entirely on
  the client from static content, and correctness is judged on the client. Nothing is submitted to
  the server, so nothing can be forged into an authoritative result.

Until Phase 8D the flow called `poolSpend()` on charge and `poolAdd()` on the way out, then pushed
the adjusted pool to `/api/economy/set` — but Phase 8B.1 made the server **ignore** a client-declared
`troops` field, so the write was discarded and the response overwrote the local decrement with the
truth. The UI was charging a price the game never collected, and the result read "N troops return
home" for troops that had never left. Phase 8C proved there was no authority hole (forging the boss
yields nothing), so Phase 8D removed the pretence rather than introducing real attrition — which
would have been a balance change worth roughly 1050 gold of troops per attempt at Phase 8B.2 prices.

`poolSpend()`, `poolAdd()` and `saveEconomy()` are **deleted**; the boss was their only caller.
`/api/economy/set` still ignores `troops` server-side, which is what keeps a stale tab harmless.
Read-only helpers (`poolObj`, `poolTotal`, `poolAvail`, `poolBreakdown`) remain — they drive the
troop display and deployment budgets. Pinned by `tests/boss_challenge.test.js`.

Whether a boss attempt *should* cost troops remains an open product question, not a defect.

- `passcnt` is **retired** (Phase 7F.2). Files saved before it may still contain the key; nothing reads, normalises, serves or rewrites it — it is inert data left in place.
- Constants (`server.py`): `GOLD_RATE = 0.10`, `GROW_SECONDS = 3600`, `ECON_MAX_CATCHUP = 72`, `ECON_START_POP = 100`, `ECON_START_TROOPS = 100`, `PASS_GOLD = 160`, `MASTERY_GOLD = 640`, `DEFEND_GOLD = 50`, `ATTACK_FAIL_GOLD = 50`.
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
- **Gold sources:** passive settlement; `DEFEND_GOLD` (+50) on successful defense; (attacker −`ATTACK_FAIL_GOLD` 50 on failed attack); and **learning**, which since Phase 7C.2 pays in two places — `PASS_GOLD` (+160) once for the first server-verified pass of a gold-bearing activity, and `MASTERY_GOLD` (+640) once for mastering a whole lesson under Rule A. `/api/economy/pass` no longer exists (retired in Phase 7F.2) — there is no HTTP route by which a client can assert its own pass. Phase 9B added the first **curriculum** lesson (`english.a1.core.001`, the A1/001 pilot): it pays the same two learning rewards but grants **no qualification**, so gold-bearing activities went 4 → 5 and active completion policies 4 → 5 while qualifications stayed at **4** and world-data was untouched. Earning gold from learning and unlocking territory are separate consequences — see `docs/learning-integration.md` § Phase 9B. Phase 9C migrated the rest of the A1 course, Phase 9E migrated the 24 generic Pre-A1 units, and Phase 9F migrated A2 (12) and B1 (5), so there are now **57** gold-bearing gate activities and **57** active completion policies (Taipei x4 + Pre-A1 x24 + A1 x12 + A2 x12 + B1 x5) while qualifications remain **4** and world-data is untouched. Every migrated lesson pays the same PASS_GOLD 160 + MASTERY_GOLD 640 = 800 regardless of level, and no curriculum family outside Taipei grants a qualification.
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
- `UNIT_COST = {inf:6, spear:9, archer:12, cav:15}` (identical FE/BE), `RECRUIT_BATCH = 10`.
  Tripled in Phase 8B.2. Until Phase 8B.1 made troop provisioning server-authoritative these prices
  bound nothing (a client could mint troops for free), so they had never been balanced against real
  spending; at 2–5 gold a fresh 500 bought 220 infantry. A starting garrison is still affordable
  (barracks + 50 infantry = 360).
- `cost = qty * UNIT_COST[unit]`; `qty` clamped 1..100000.
- Requires the producing building: `UNIT_BUILDING = {inf:barracks, spear:barracks, archer:archery, cav:stable}`.
- Territory recruit requires `owner == user`; home recruit (`@home`) needs the building in the economy.
- Deducts gold only (**no population cost**). Insufficient gold → 400 `{error, gold, cost}`.
- Frontend `UNIT_COST` is used only for display/preview; the server is authoritative.

## E. Technology  (backend-authoritative)

- Tracks: `atk` (forging), `def` (armor). `TECH_COST = {atk:[160,320,560], def:[160,320,560]}`, `TECH_MAX = 3` (identical FE/BE).
  Doubled in Phase 8B.2: one mastered lesson (800, so 1300 with the starting purse) used to max BOTH
  lines outright. One lesson now funds ONE full line (armory + 1040 = 1090) and the second line stays
  a later decision. `PASS_GOLD` (160) is exactly one level-1 upgrade.
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
  > **SUPERSEDED — historical (pre-Phase-2A).** Phase 2A made battle server-authoritative and moved
  > battle gold inside `/api/territory/attack`. **Phase 8E deleted `/api/territory/attack-result`
  > entirely** (route + handler); it had already been a `{"ok": true, "legacy": true}` no-op with no
  > callers. **There is no post-battle settlement callback today** — see §Attack below.

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
  - Neutral claim: `POST /api/territory/claim` — only on an unowned territory (backend validates identity/map/population, sets owner + garrison from client-sent surviving troops; population from catalog). No battle. Since Phase 7D-0 the backend also enforces the **learning-qualification gate** here, via the same `game.conquest.missing_qualifications()` rule and the same world-data as attack; an unqualified claim is refused with 403 `qualification_required`.
    - **Phase 8B.1:** the garrison is **debited from the authoritative troop pool** — a claim MOVES troops, it cannot declare them. Over-budget → 400 `insufficient_troops`.
    - **Phase 8B.3:** **acquiring** a territory must deploy **at least one troop** (`sum(hp) >= 1`); a claim that would deploy nothing is refused with 400 `troops_required` (`minTroops: 1`). Ownership carries the territory's passive income, and it used to be free — all seven ungated Taipei districts could be taken for 0 troops and 0 gold. The minimum is exactly one: a real commitment, not an economic barrier.
    - **Redeploying a territory you already own may leave it with ZERO garrison** — that is intentional and unchanged. The minimum guards ACQUISITION only, so your own ground can be stripped bare (and lost to an attacker) if you choose.
    - **Failure order** for a new territory: `room_required` → `held` → `qualification_required` → `troops_required` → `insufficient_troops`. Eligibility always answers before commitment, so an ineligible learner hears the qualification, not the troop count.
  - Attack (occupied): client `runBattle`; on win client calls `release` (territory → neutral) then `claim` (becomes owner with survivors). `attack-result` awards gold.
    - **SUPERSEDED — historical.** Since Phase 2B a single `POST /api/territory/attack` **settles
      completely**: it validates ownership/adjacency/source garrison and qualifications, resolves the
      battle server-side, applies casualties, transfers ownership, moves gold, and persists — then
      returns `attackerWon`, `defender`, `defenderOrder`, `defenderTech`, `gold`, both garrisons and
      both survivor lists, which is everything the UI renders (it replays `runBattle` with
      `preOrdered=true` for animation only). **Phase 8E removed `/api/territory/attack-result`**, so
      there is no settlement callback and no second settlement path.
      **Phase 8F.1 removed `/api/territory/engage`** — the old pre-battle garrison reveal — so there
      is no pre-battle preview endpoint either. It had no caller, and it returned `troops`/`tech` for
      any territory, which the canonical `/api/territory` deliberately withholds from other players
      (`hidden: true`); retiring it closed that fog-of-war bypass. The live conquest surface is now
      `/api/territory` (read) plus claim / attack / build / recruit / research / release / conscript,
      with **exactly one battle mutation endpoint**: `/api/territory/attack`.
- **Attack eligibility today:** attacker must be logged in and have troops; target must be owned by someone else. **No adjacency, no source territory, no course requirement.** Any territory may be attacked regardless of location.
- Defeat: attacker survivors return to pool (client-side); owner unchanged; attacker −50 gold, defender +50.

## H. Existing AI (compatibility only)

- `ai_loop` iterates started rooms; each AI: `ai_econ` (home gold), `_ai_recruit` (spends all gold on a balanced buy), then `ai_move`: pick `attack` (a non-AI-owned territory) or `occupy` (a known unowned territory from the learned catalog), resolve via `_force_power`, mutate the store directly, log an event. AI reads the same `territory.json`/`economy.json`/learned catalog and uses the **backend** battle math (F2). It does not call the player HTTP endpoints.

---

## Duplicated logic (candidates for centralization)
- Counter multipliers, `UNIT_COST`, `TECH_COST`, `TECH_MAX`, `BUILD_COST`, `RECRUIT_BATCH` exist in **both** `index.html` and `server.py` (values identical → safe to centralize as backend-authoritative config; frontend keeps display copies).
  **Resolved server-side in Phase 8B.2:** `server.py` no longer holds its own literals — it aliases
  `game/config.py`, which is now the single source of every balance constant. The 8B.2 reprice
  changed `config.py` while `server.py` silently kept the old numbers, and `game_domain_test.py`
  caught the drift; aliasing makes that class of bug impossible. `index.html` still keeps display
  copies (the server prices every purchase), so those two must be kept in step by hand.
- Battle math exists twice and **differs materially** (above) → cannot be consolidated without changing behavior on one side.

> The sections A–H above are the **pre-2A** snapshot. Phase 2A retired the client/AI battle divergence (single canonical engine) and made all combat server-authoritative. The section below is the **Phase 2A baseline** that Phase 2B builds on.

---

# Phase 2A Baseline — current attack flow (the "before" reference for Phase 2B)

*As of commit `91d5b49`. This is the exact runtime behavior Phase 2B modifies.*

### 1. Where attacking troops come from
The attacker commits a **squad from the player's GLOBAL troop pool** (`economy.json → <user>.troops`, a `{cav,archer,inf,spear}` count map). The squad is a list `[{type,hp}]` (≤4 entries). Territory **garrisons** (`territory.json → <id>.troops`) are NOT the attack source in 2A.

### 2. How the global pool is represented
Per-player, per-room `economy.json`: `troops` = `{cav,archer,inf,spear}` integer counts (normalized by `_norm_troops`/`game.army.normalize_pool`). Recruitment at `@home` adds here; territory recruit adds to that region's garrison list instead.

### 3. Target validation (`POST /api/territory/attack`, `_handle_territory_attack`)
- login required; `file` → `_canon` to a canonical id (else 400 `unresolved`).
- target must exist **and be owned** (else 400 `neutral` — "use claim, not attack").
- target must **not** be owned by the attacker (else 400 `own`).
- **No adjacency check. No source territory. Any owned target is attackable from anywhere.**

### 4. Battle invocation
Server-authoritative: `game.conquest.resolve_attack(squad, def_troops, attacker_home_tech, target_tech, random.Random())`. Attacker tech = the player's **home** economy tech; defender tech = the **target region** tech. Defender order is seeded server-side and returned as `defenderOrder` for non-authoritative frontend replay.

### 5. Survivor placement
On **both** win and loss, attacker survivors are returned to the **global pool** (`pool[type] += survivor.hp`). The committed squad was deducted from the pool first (server-side, validated against pool counts).

### 6. Ownership transfer
On **win**: the target is **NEUTRALIZED** (`del store[target]`) — ownership does **not** transfer to the attacker. The attacker must then use the separate **neutral claim** flow to occupy it, which since Phase 7D-0 re-checks the territory's own learning requirements server-side. A territory that declares **no** requirements is claimed directly — Phase 7F.2 retired the client-side bootstrap that made an unrestricted territory appear to need a lesson. On **loss**: owner unchanged.

### 7. Neutralization behavior
Win → `del store[target]` (garrison/growth discarded). Defender garrison is **not** wounded on a repelled attack in the human path (it stays at full pre-battle strength); the AI path *does* set `defender = defenderSurvivors` on its loss (minor human/AI inconsistency).

### 8. Gold effects
Win → no gold change. Loss → attacker `−ATTACK_FAIL_GOLD (50)`; if the defender is a real, non-AI player → defender `+DEFEND_GOLD (50)` (applied via `econ_add_gold` **outside** `terr_lock`). Losing to an AI therefore *destroys* the 50 rather than transferring it.

"Non-AI" is decided by `is_ai_owner()` = the room's AI roster (`room_ai_names()`, which `/api/room/start` fills with `AI 1`…`AI 7`) **∪** `{AI_OWNER, AI_OWNER_LEGACY}` — the same union the client's `isAiOwner()` uses. Phase 8F.3 fixed a defect here: the guard previously compared only against `AI_OWNER` (`"AI Empire"`), a name no room AI ever has, so every room AI collected `DEFEND_GOLD` from a failed human attack and `_ai_recruit` turned it into troops. `conscript_tick` shared the same stale guard (latent — a captured region loses its `conscript` flag) and now uses `is_ai_owner()` too.

### 9. AI attack origin behavior (`ai_move`)
AI attacks from its **global pool** (`ae["troops"]`), targeting a **random** non-AI-owned territory (no adjacency, no source). Win → AI takes ownership immediately with survivors as garrison (AI is exempt from the lesson/claim gate). Loss → target owner keeps it, garrison set to defender survivors. The AI pool is cleared (`_norm_troops(0)`) after any attack. AI occupy places its whole pool as the new garrison.

### 10. Frontend attack UI flow
ONE target-first surface — `openRegion` (SVG geo-map drill-down) — POSTs `{file, squad}` to `/api/territory/attack` and replays via `runBattle(..., preOrdered=true)` (non-authoritative). Phase 7G removed the second surface: `openOutpost` (board-map lesson nodes) had an attack branch over pseudo-territories that could never resolve, and is now a learning-only panel.
Squad budget = the global pool (`poolAvail()`); the player picks any owned enemy region and assigns troops. After a win the frontend offers the neutral claim: for a **gated** region it names the lesson granting the missing qualification, and for an **ungated** one it goes straight to troop deployment (Phase 7F.2).

### 11. Files that Phase 2B modifies
- `game/conquest.py` — add `can_attack()` + territorial state transition (`apply_territorial_attack`).
- `server.py` — `_handle_territory_attack` (require source, enforce adjacency, commit from source garrison); `ai_move` (source/target selection).
- `index.html` — `openRegion` attack branch (source selection, squad from source garrison). The `openOutpost` branch this phase also touched was removed in Phase 7G.
- `tests/*` — new `game_conquest_test.py` cases; the "non-adjacent allowed" regression flips to "non-adjacent rejected".
- `docs/conquest-rules.md` — new.
