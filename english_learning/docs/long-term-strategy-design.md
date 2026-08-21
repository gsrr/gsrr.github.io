# Long-term strategy system design (Phase 13A)

**Design and audit only.** No production file is touched by this phase. Every number below is measured
from the code at `184a99f`, not estimated: the measurement commands are shown so any figure can be
re-derived.

---

## 1. Current-loop audit — actual behaviour, not intended

```
Academy (57 lessons)  --gold-->  home base
                                    |
                     recruit troops (gold only) ----> free troop pool
                                    |                       |
                       claim a neutral territory <-----------+
                                    |                  attack an adjacent enemy
                                    v
                            territory owned
                                    |
                        +-----------+------------+
                        |                        |
                 passive gold/hr        buildings + technology
                  (population)            (per territory)
```

| system | INPUT | OUTPUT | LIMIT | SINK | FEEDBACK LOOP | AUTHORITY |
| --- | --- | --- | --- | --- | --- | --- |
| **Gold** | learning rewards; passive income; +50 on a successful defence | the single currency | none — unbounded integer | troops, buildings, tech, re-entry levy, −50 on a failed attack | **positive, uncapped**: territory → population → gold → troops → territory | `game/economy.py` + `econ_lock` |
| **Passive income** | `round((homePop + Σ ownedPop) × 0.10)` per hour, catch-up capped at 72 h | gold | only the 72 h offline cap | — | **the main engine of the game** | `game/economy.py::calculate_passive_gold` |
| **Troops** | gold at 6 / 9 / 12 / 15 per unit, batches of 10 | garrison or free pool | building prerequisite per type | **combat losses only** | weak negative (losses) vs strong positive (income) | `/api/territory/recruit`, `game/recruitment.py` |
| **Population** | frozen `gamePopulation` from the catalog on claim | drives income | fixed per territory | **none — recruiting no longer costs population** | none | `territory_catalog`, `/claim` |
| **Buildings** | gold: armory 50, barracks 60, archery 80, stable 120 | unlock recruit types / research | 4 per territory, one-off | one-off purchase | none after purchase | `/api/territory/build` |
| **Technology** | gold: 160 / 320 / 560 per track | +10 % atk or def per level | `TECH_MAX = 3`, **per territory**, needs a local Armory | one-off purchase | none after cap | `/api/territory/research`, `game/technology.py` |
| **Territories** | claim (neutral) or attack (adjacent enemy) | population, income, a source to attack from | 250 on the world map | — | **positive** | `game/conquest.py::can_attack`, `/claim` |
| **Combat** | a squad from one owned adjacent territory | ownership transfer; survivors | adjacency + garrison | troops die; −50 gold on a loss | negative but tiny | `game/conquest.py`, server-side |
| **Re-entry** | 120 gold + committed troops | one foothold battle against a weak holder | offered only at zero territories; 4 candidates from the weakest quartile by defence | 120 gold levy | recovery valve | `game/conquest.py::reentry_state` |
| **AI** | tick every 20–30 min | claims neutrals, attacks player territory where it has an adjacent source | its home base is **off-map and unattackable** | — | pressure that never dies | `server.py::ai_move` |
| **"Stamina" (Energy)** | localStorage, 20/hr refill, 20 per test | gates `enterTestMode()` only | client-side | — | none | **none — client-only, forgeable, and it gates only the legacy practice surface, not the authoritative Academy** |

### The numbers that decide the design

```
$ python -c "…"   # game/config.py + learning/registry.json + territory_catalog
```

| measurement | value |
| --- | --- |
| gate rewards | 57 activities × `PASS_GOLD 160` = **9,120** |
| mastery rewards | 57 lessons × `MASTERY_GOLD 640` = **36,480** |
| **the ENTIRE curriculum, once, ever** | **45,600 gold** |
| passive income, 1 territory | 55 gold/hr → 1,320/day |
| passive income, 5 | 174/hr → 4,176/day |
| passive income, 20 | 608/hr → 14,592/day |
| passive income, 50 | 1,381/hr → 33,144/day |
| passive income, 100 | 2,500/hr → 60,000/day |
| passive income, all 250 | 4,485/hr → 107,640/day |
| full development of ONE territory | 310 buildings + 2,080 tech = **2,390** |
| full development of all 250 | 597,500 |
| 1,000 cavalry | 15,000 gold, **held for ever, no upkeep** |

**The single most important ratio in the game today:** the whole 57-lesson curriculum pays 45,600 gold
*once*, which a 50-territory empire out-earns by doing nothing for **33 hours** — and a 100-territory
empire in **18 hours**. Learning is a strong early-game boost and an economic rounding error by week
two. Everything in §2 and §11 follows from that.

### A second measured fact the brief underestimated

The brief lists six zero-adjacency islands (`bv go gs hm ju tf`). The catalog actually has **90**:

```
world territories        : 250  (population 44,603)
zero adjacency           :  90 (36.0%)  population 16,520 (37.0%)
degree 1                 :  18 ( 7.2%)  population  3,077
connected components     :  93   sizes [135, 23, 2, 1×90]
largest contestable mass : 135 territories, population 23,933
```

Among the 90: **Australia, Japan, Taiwan, Cuba, the Philippines, Sri Lanka, Singapore, New Zealand,
Greenland, Iceland, Madagascar, Cyprus**. Because `can_attack` requires an owned *adjacent* source,
each of these is:

- claimable by whoever reaches it first while it is neutral, and
- **permanently invulnerable afterwards** — no attack can ever be launched at it, and it can never
  attack out.

So **36 % of the map and 37 % of the world's income is un-contestable by design**, and the real
strategic game is played on a 135-territory landmass plus a 23-territory second component. This is not
an edge case to tidy up in a naval phase; it is the largest single distortion in the current game, and
§13 treats it as such.

---

## 2. Long-term failure modes

Severity: **S1** breaks the game · **S2** makes it boring · **S3** annoying.
Time-to-appear assumes a player doing 2–3 lessons a day and expanding steadily.

| # | failure | sev | appears | player-visible symptom | systemic cause |
| --- | --- | --- | --- | --- | --- |
| 1 | **technology caps** | S2 | ~1 week (per territory), ~1 month (everywhere) | "Research ▸" is greyed out; the Technology tab is a wall of *max* | `TECH_MAX = 3` on two tracks with no further axis; tech is a **one-off purchase**, not an ongoing decision |
| 2 | **buildings become irrelevant** | S2 | ~3 days per territory | four ✅ ticks; the tab is a checklist you never revisit | 4 one-off prerequisites, no specialisation, no trade-off — every territory wants the identical set |
| 3 | **many territories** | S1 | ~2 weeks (20+) | Forces/Buildings/Technology tables scroll for pages; nothing on them is a *decision* | development is **per territory** and territories are unbounded |
| 4 | **micromanagement explosion** | S1 | ~2 weeks | 50 territories × (4 buildings + 2 tech tracks + 4 recruit types) = **500 independent affordances** | management scales linearly with conquest, which is the thing the game rewards |
| 5 | **Gold inflation** | S1 | ~2 weeks | six-figure balance, nothing worth buying | income scales with territory; **all sinks are one-off**, and troops have **no upkeep** |
| 6 | **veteran vs newcomer** | S1 | ~1 month | a new player claims a neutral, is attacked at the next AI tick, and cannot out-recruit anyone | permanent tech + unbounded army + income proportional to holdings, with no catch-up term |
| 7 | **turtle-tech-then-expand** | S2 | ~1 week | the optimal opening is "don't play": bank learning gold, max tech at home, then roll out | tech is permanent and cheap relative to late income, and there is no cost to *not* expanding |
| 8 | **runaway snowball** | S1 | ~1 week | one player takes the 135-territory landmass and the game is decided | income → troops → territory → income, with no diminishing return anywhere in the loop |
| 9 | **permanent safe hinterland** | S2 | immediately | interior territories are pure income and never in danger, but still demand upgrade clicks | ownership is per territory; there is no notion of a front |
| 10 | **isolated islands** | S1 | immediately | 90 territories (37 % of income) can never be fought over | `can_attack` needs land adjacency; the catalog gives 90 territories none |
| 11 | **repetitive recruitment** | S3 | ~1 week | "Recruit ▸ ×10" pressed dozens of times | `RECRUIT_BATCH = 10` against five-figure balances |
| 12 | **repetitive upgrades** | S3 | ~1 week | the same four builds and six research levels, per territory, for ever | see 2 and 3 |
| 13 | **Academy gold loses value** | **S1** | **~3 days** | a mastered lesson pays 800 gold; the empire earns that in 35 minutes | measured in §1: the entire curriculum ≈ 33 h of a 50-territory empire's idle income |

Failure 13 is the one that matters most for this product: **the learning half of the app must not
become economically pointless**, and today it does, faster than a class finishes a term.

---

## 3. The core fantasy

> **Hold a shifting front line with an army that is genuinely scarce, and spend what you learn on the
> strategic options that scarcity denies you.**

Three commitments follow from that sentence, and the rest of this document is judged against them:

- **the army is scarce** — it costs to keep, not only to buy, so committing it anywhere is a decision;
- **only the front matters** — the interior is economy, not chores, so an empire growing does not make
  the game bigger, it makes the front longer;
- **learning buys options, not numbers** — what the Academy pays for is something gold cannot buy, so
  it is still worth doing in month six.

Explicitly **not** the fantasy: "upgrade everything", "make the numbers larger", "own all 250".

---

## 4. Territory role — recommendation

| model | management at 5 / 20 / 50 / 100 territories | verdict |
| --- | --- | --- |
| **A. every territory individually developed** (today) | 30 / 120 / 300 / 600 affordances | **reject** — this is failure 3/4 by construction |
| **B. territory = geography + income only** | 5 / 5 / 5 / 5 | tempting, but removes all local decisions; conquest becomes pure arithmetic |
| **C. territories grouped into administrative regions** | 3 / 6 / 8 / 10 regions | **recommend** |

**Recommendation: C, with B's discipline.** A territory contributes population, income, adjacency and a
garrison slot — and nothing that needs a click. Development happens at **region** scale, where a region
is a small set of adjacent territories (the existing continent metadata is a natural, already-authored
starting point: 6 groups; a later split into ~12–18 sub-regions keeps region count roughly constant as
empires grow).

Design target: **a 100-territory empire manages ~10 regions**, not 100 checklists. Management must grow
with the *logarithm* of conquest, not linearly.

---

## 5. Troop model comparison

| model | UI complexity | server authority complexity | strategy depth | micromanagement | naval fit | AI fit |
| --- | --- | --- | --- | --- | --- | --- |
| **A. permanently territory-local** (today) | low | **already built** | low — you cannot concentrate force | high (recruit per territory) | poor | already works |
| **B. movable garrisons** | medium | medium — a transfer endpoint + adjacency rules | medium | **high** — every border tile is a slider | medium | easy |
| **C. regional armies** | low | medium — armies belong to a region | medium-high | **low** | good | medium |
| **D. army objects moving over territory** | high — units on a map, paths, timing | high — position, arrival time, interception | **high** | medium | good | hard |
| **E. hybrid: thin garrisons + a few named field armies** | medium | medium-high | **high** | **low** | good | medium |

**Recommendation: E.** A territory keeps a small, mostly automatic **garrison** (defence, no
micromanagement). Offence uses a small number of **field armies** — objects the player names, keeps
supplied, and moves between adjacent owned territories. Depth comes from *which* front an army is on
and whether it is supplied, not from 250 sliders.

Why E over D: D needs travel time, interception and pathing — three new authority surfaces — before it
is playable. E reuses today's model almost exactly (an army is a garrison that can move, with a home)
and can ship in one phase.

Why E over B: B is the naive "add troop transfer" answer, and it makes failure 4 *worse* — every
border territory becomes another panel. The brief was right to forbid starting there.

---

## 6. Front line — recommendation

**Yes. Make the front line the primary object of the strategic game.**

It requires no new data. A territory is a **frontier** territory if any catalog neighbour is not owned
by the player; everything else is **interior**. That is one derived boolean over the existing adjacency:

```
frontier(t)  ==  any(neighbour not owned by me)      # derived, never stored
interior(t)  ==  not frontier(t)
```

Concrete recommendation:

- **interior territories need no management at all** — they pay income and supply the front, and their
  UI is a single regional summary line;
- **military pressure exists only at the frontier** — garrison strength, buildings that matter for
  defence, and army positioning are frontier concerns;
- **an interior territory becomes logistical**: it contributes supply capacity, which is what limits
  how many field armies a player can keep (see §10);
- **this shrinks management as the empire grows**, because a rounder empire has a *shorter* front
  relative to its size. Expansion then has a real strategic shape: consolidate to shorten your front,
  or stretch it for income.

Measured on the current map: a 50-territory holding on the main landmass (mean degree 2.57) has a front
of roughly 12–20 territories, so **~70 % of a large empire stops needing attention** — the direct
answer to failures 3, 4 and 9.

---

## 7. Technology redesign options

| option | solves "tech caps"? | solves "turtle then expand"? | infinite ladder? | verdict |
| --- | --- | --- | --- | --- |
| **A. current per-territory levels** | no — caps at 3 | no — the turtle's home tech travels with every attack | no | reject (failures 1, 7) |
| **B. empire-global permanent levels** | no — still caps | **worse** — one purchase buffs everything for ever | no | reject alone |
| **C. global tech tree with branches** | **partly** — choices remain even at cap | partly | no | strong component |
| **D. era / age progression** | yes, while eras remain | no | eventually | expensive; needs content per era |
| **E. temporary doctrines** (choose N active, swap freely) | **yes — permanently** | **yes** — a doctrine helps the front you are actually fighting | **no** | **strong component** |
| **F. research slots** (limited concurrent research) | partly | partly | no | good pacing tool |
| **G. diminishing returns** | no, but bounds runaway | partly | no | necessary safety, not sufficient |
| **H. unlocked by empire conditions, not gold alone** | yes | **yes** — you cannot buy what you have not done | no | **strong component** |

**Recommendation: C + E + H, with G as a guard rail.**

- **A branching global tree (C)** replaces per-territory levels. Two mutually exclusive branches per
  tier means a maxed tree is still a *different* tree from your opponent's.
- **Doctrines (E)** are the answer to "tech reaches max and becomes boring": a small number of active
  doctrine slots, freely swapped, chosen against the war you are actually in. The decision never ends
  because the situation never stops changing. Doctrines are **sidegrades, not upgrades** — this is the
  mechanism that avoids an infinite numeric ladder.
- **Condition-gated unlocks (H)** are the answer to turtling: a tier opens when the empire has *done*
  something (held a frontier under attack, integrated N regions, won a defence at a numeric
  disadvantage), not when it has banked enough gold. A turtle cannot pre-buy the late tree because it
  has not met the conditions.
- **Diminishing returns (G)** on every numeric effect, so stacked bonuses cannot produce the
  unbeatable veteran of failure 6.

> **Current invariant, unchanged until a future phase reviews it:** technology today is per-territory,
> capped at 3, `TECH_COST [160,320,560]`, requires a local Armory, and is **not** inherited on
> conquest. Everything in this section is a **proposed future change** (§20).

---

## 8. Conquest and technology inheritance

| model | turtle-tech abuse | newcomer experience | verdict |
| --- | --- | --- | --- |
| inherits all empire tech | none (nothing to farm) | conquest is instantly worth full value → snowball | reject |
| **starts undeveloped** (today) | **severe** — the turtle keeps home tech and the defender loses everything | brutal: taking a territory gains you an empty tile | reject as the only rule |
| inherits partial infrastructure | mild | reasonable | good |
| **requires integration time** | **low** | good — expansion is paced | **recommend** |
| global military tech, local buildings | low | good | **recommend, paired** |
| temporary occupation penalty | low | good | folds into integration |

**Recommendation: global military technology + local buildings + an integration period.**

- **Military technology is empire-global** — an army fights with your doctrine wherever it is. This
  removes the per-territory tech table entirely (failures 1, 3, 4) and removes the turtle's asymmetric
  advantage, because the defender has doctrine too.
- **Buildings stay local** and are **partially inherited**: a captured territory keeps its
  infrastructure at reduced effect, which makes conquering a *developed* region meaningfully better
  than conquering an empty one, and gives the defender something to lose.
- **Integration**: for a period after capture, a territory pays reduced income and cannot host a field
  army. This is the pacing brake on snowballing (failure 8) and the reason blitzing 20 territories is
  not strictly better than taking 5 and holding them.

Turtle analysis under this model: banking gold buys troops and buildings, but not tier progression
(condition-gated) and not doctrine advantage (symmetric). The turtle emerges with a big army against an
opponent who has *met the conditions* — a fair fight rather than a solved opening.

---

## 9. Buildings

Today: `armory 50 / barracks 60 / archery 80 / stable 120` — four one-off unlocks, identical in every
territory, and the correct play is always "build all four everywhere you fight".

**Recommendation: regional specialisation, frontier-weighted.**

- Move production buildings to **region** scope: a region that builds a Stable produces cavalry *for
  that region's armies*. Region count is bounded (§4), so the panel count is bounded.
- Make them **mutually constraining**, not cumulative: a region has limited build capacity, so
  specialising into cavalry means *not* specialising into archers. That is a decision; "build all
  four" is not.
- Keep a small number of **territory-level** structures that only matter at the **frontier** (a
  fortification improving defence, a depot extending supply). These are exactly the tiles the player
  is already looking at, so they add decisions without adding chores.
- Interior territories need **no buildings at all**.

> **Current invariant:** `BUILD_COST = {armory 50, barracks 60, archery 80, stable 120}`, per
> territory, one-off, prerequisite for recruiting the matching unit. Unchanged by this phase.

---

## 10. Gold economy

The current model has **no recurring sink whatsoever**. Every purchase is one-off; troops, once bought,
are free to keep for ever. Income, meanwhile, is proportional to holdings and unbounded. That is
failure 5, and no price curve fixes it — the brief is right to forbid solving it with exponentially
rising prices, because rising prices only delay the inevitable and punish newcomers hardest.

**Recommendation: introduce recurring sinks proportional to what the player is doing, and cap the
stockpile.**

| lever | why it works |
| --- | --- |
| **army upkeep** — each unit costs gold per hour | the missing negative feedback loop. A big army becomes a *choice* with an ongoing price, so gold stays scarce at every empire size, and "recruit for ever" stops being free |
| **supply capacity** — field armies require supply generated by interior territory | ties the army ceiling to the *shape* of the empire, not the balance. Rewards consolidation over sprawl |
| **integration cost** — capturing costs gold to integrate | paces expansion (§8) and makes blitzing expensive |
| **operations** — one-off strategic actions (forced march, emergency levy, fortify) | converts surplus gold into *decisions* rather than storage |
| **a soft stockpile cap** — gold above a ceiling decays or stops accruing | prevents the returning-veteran wall of gold; the ceiling scales with regions, so it is a *goal* early and a *constraint* late |

Anti-inflation: income is capped by territory; expenditure now scales with army size and front length,
both of which grow with the empire. Anti-irrelevance: upkeep and operations mean gold is always
spendable on something that matters *this hour*.

> **Current invariant:** `GOLD_RATE 0.10`, `GROW_SECONDS 3600`, `ECON_MAX_CATCHUP 72`,
> `UNIT_COST {inf 6, spear 9, archer 12, cav 15}`, `RECRUIT_BATCH 10`, `DEFEND_GOLD 50`,
> `ATTACK_FAIL_GOLD 50`, `REENTRY_GOLD_COST 120`, recruiting costs **no population**, troops have
> **no upkeep**. All unchanged by this phase.

---

## 11. Learning ↔ strategy contract

This is the section the product lives or dies by. Measured position: the whole curriculum is worth
45,600 gold once — **33 hours** of a mid-size empire's idle income. Paying learning in the same
currency as idle time guarantees learning loses.

**Recommendation: learning must stop paying gold as its primary reward, and start paying a resource
that idle time cannot produce.**

Call it a **Mandate** (name to be decided). Properties:

- **only learning produces it** — no territory, no income, no combat, no timer;
- **it does not inflate**, because the supply is bounded by curriculum progress and its sinks are
  ongoing;
- **it buys options, not numbers**: a doctrine slot, a strategic operation, a replacement levy after a
  defeat, an integration accelerated, a research condition satisfied early;
- **it never buys legality.** A Mandate cannot make an illegal attack legal, cannot cross adjacency,
  cannot bypass ownership. It buys *capability the rules already permit*, and the server still decides
  every action.

This keeps the two halves separated exactly as they are today:

```
learning  ->  earns strategic RESOURCES and OPPORTUNITIES
game      ->  decides what is LEGAL, and settles every outcome
```

and it means a month-six player with a maxed empire still has a reason to open the Academy, because the
one thing they cannot idle their way into is a Mandate.

**Explicitly preserved:** curriculum completion is **not** a conquest gate. Phase 10A.3R removed the
last learning gate from `/api/territory/claim` and `/attack`, and this design does not bring it back —
§19 lists it as an invariant. Learning must remain *worth* doing without ever becoming *required* to
play.

> Re-reading the Read Along accommodation in this light: because learning pays strategic resources and
> never legality, an accommodated learner earns exactly the same Mandates as anyone else. The
> accommodation stays an input change, and nothing in this design creates a second class of player.

---

## 12. New player vs veteran

| scenario | today | under the recommendation |
| --- | --- | --- |
| newcomer enters an established world | claims a neutral, is attacked at the next AI tick, cannot out-recruit anyone | only the **front** matters, so a small empire defends a short front; upkeep means the veteran's huge army costs them every hour |
| small vs huge empire | huge wins on every axis | huge pays upkeep on a long front, and integration slows its growth; diminishing returns cap its tech edge |
| returning inactive player | 72 h of catch-up gold and a stale empire | the same, plus a stockpile cap so the return is not a wall of unusable gold |
| defeated player | re-entry: 120 gold, 4 weak candidates | unchanged — it already works; Mandates give a defeated player a *replacement levy* that gold cannot buy |
| veteran mathematically unbeatable | **real risk**: permanent tech + unbounded army | mitigated by upkeep (army ceiling), diminishing returns (tech ceiling), integration (growth rate), and doctrine symmetry |

**Catch-up mechanisms recommended:** front-length-proportional upkeep (big empires pay more to hold
more), integration delay on capture, diminishing returns on all numeric tech, and Mandates as a
learning-driven equaliser that a lapsed veteran has no stock of.

---

## 13. Naval / islands

The brief asks about six islands. The measurement says **90 territories (36 % of the map, 37 % of
income) have zero adjacency**, plus 18 more with a single neighbour, and the map has **93 connected
components**. Australia, Japan, Taiwan, Cuba, the Philippines and Singapore are all currently
un-attackable once claimed.

| option | new authority | geography created | complexity | verdict |
| --- | --- | --- | --- | --- |
| explicit naval adjacency (hand-authored edges) | none — reuses `adjacentTerritoryIds` | crude: islands become "just more land" | low | acceptable stopgap |
| coastal range (attack any coast within N) | a distance rule | vague; hard to read on a map | medium | reject — unreadable |
| **sea zones + a port requirement** | one new derived relation + one building | **strong** — chokepoints, staging, islands as objectives | medium | **recommend** |
| ships as units | a whole unit class, transport capacity | strong | high | later, if ever |
| special island claim rules | none | weak — papers over the hole | low | reject |

**Recommendation: sea zones with ports — the simplest rule that creates real geography.**

- Each coastal territory belongs to one or more **sea zones** (authored once, as data, alongside the
  existing adjacency).
- A territory with a **Port** can attack, and be attacked from, any territory in a shared sea zone.
- No ships, no travel time, no transport capacity in the first version: a sea zone is simply a second
  kind of adjacency that requires infrastructure at both ends.

Consequences: Japan and Australia become genuine strategic objectives rather than safe money; island
chains become chokepoints; a naval front is a front like any other, so §6 covers it for free. And it
degrades gracefully — with no port anywhere, the game is exactly today's game.

> **Current invariant:** adjacency is the catalog's `adjacentTerritoryIds`, 900 edge-ends, 0 cross-map,
> and `can_attack` requires land adjacency. Sea zones are a **proposed future change**.

---

## 14. Game time scale

| cadence | what should happen | what actually happens today |
| --- | --- | --- |
| seconds | pan, zoom, select, inspect | ✅ correct (Phase 12C/12D) |
| minutes | plan and resolve a battle; commit an army | ✅ battles; ❌ **recruitment** is also here, and it should not be a per-minute chore |
| hours | income accrues; garrisons recover; upkeep is paid | ⚠️ income only (`GROW_SECONDS 3600`); no recovery, no upkeep |
| days | expand a front; integrate a region; shift a doctrine | ❌ **nothing operates at this scale** — expansion is limited only by clicking speed |
| weeks | develop the empire; open a tech tier | ❌ tech is exhausted in days |
| months | competitive arc | ❌ does not exist |

**Systems at the wrong scale today:**

1. **Recruitment** — `RECRUIT_BATCH 10` against five-figure balances makes an hours-scale decision into
   a minutes-scale chore. Should be a standing policy ("this region reinforces to N"), not a button.
2. **Technology** — a weeks-scale system exhausted in days. Condition-gated tiers move it back.
3. **Expansion** — a days-scale decision with no brake at all. Integration provides one.
4. **Conquest reward** — instantaneous. Integration spreads it over hours.
5. **The AI** — 20–30 min ticks are right for pressure, but its **off-map unattackable home base**
   means AI pressure never diminishes no matter how well the player plays. That is a wrong-scale
   feedback loop: the player's success should reduce it.

---

## 15. Micromanagement budget

**Target: a meaningful session is 10–20 *decisions*, and it must not grow with empire size.**

| empire size | today (affordances) | recommended (decisions per session) |
| --- | --- | --- |
| 5 territories | ~30 | 5–8 |
| 20 | ~120 | 8–12 |
| 50 | ~300 | 10–15 |
| 100 | ~600 | 12–18 |

Where the recommended budget goes at 50 territories: **1** glance at a regional summary, **2–4** front
decisions (reinforce, fortify, attack), **1–2** army movements, **0–1** doctrine swaps, **1–2**
Mandate spends, **1** region build decision. Interior territories: **zero actions**.

The rule that keeps it bounded: **anything that would have to be repeated per territory must become a
policy set per region, or be removed.** Prefer decisions over chores.

---

## 16. Three complete architectures

### OPTION 1 — Minimal change

| dimension | design |
| --- | --- |
| territory role | unchanged: individually developed |
| troops | movable garrisons (B) — add a transfer endpoint between adjacent owned territories |
| front line | none (derived highlight only, cosmetic) |
| buildings | unchanged, per territory |
| technology | unchanged per-territory levels; raise `TECH_MAX` |
| conquest inheritance | unchanged (resets) |
| gold sinks | raise prices; add more tech levels |
| Academy | unchanged (gold), amounts increased |
| naval | hand-author adjacency edges for the 90 isolated territories |
| newcomer balance | none beyond re-entry |
| micromanagement | **worse** — transfer adds a panel per border territory |

**Honest assessment:** this is the "just add troop transfer" path the brief warns against. It delivers
a visible feature in one phase and makes failures 3, 4, 5 and 13 *worse*. Raising `TECH_MAX` and prices
buys weeks, not months. Not recommended.

### OPTION 2 — Moderate redesign

| dimension | design |
| --- | --- |
| territory role | territory = geography + income; **frontier/interior** distinction derived from adjacency |
| troops | hybrid (E): automatic garrisons + a few field armies moving between adjacent owned territories |
| front line | **primary** — only frontier territories need attention |
| buildings | frontier-only structures; production stays per territory but is hidden for interior tiles |
| technology | **empire-global** branching tree replacing per-territory levels; diminishing returns; cap retained |
| conquest inheritance | global military tech applies; buildings partially inherited; short integration delay |
| gold sinks | **army upkeep** + integration cost |
| Academy | pays gold **and** a small Mandate stream; Mandates buy operations |
| naval | sea zones + ports |
| newcomer balance | upkeep + integration + diminishing returns |
| micromanagement | 8–12 decisions at 50 territories |

Coherent, and implementable in ~4 phases. Leaves failure 1 partly open (a maxed tree is still maxed)
and keeps a gold reward path for learning, so failure 13 is softened rather than solved.

### OPTION 3 — Strong long-term redesign

| dimension | design |
| --- | --- |
| territory role | **regions** are the unit of development; territories are geography, income and garrison slots |
| troops | hybrid (E): garrisons automatic per region policy; named field armies limited by **supply** |
| front line | primary; interior converts to **logistics** (supply capacity for armies) |
| buildings | **regional specialisation with limited build capacity** + frontier structures; interior needs none |
| technology | global **branching tree + doctrine slots + condition-gated tiers**; diminishing returns |
| conquest inheritance | global military tech; local buildings partially inherited; **integration period** with reduced income and no army hosting |
| gold sinks | **upkeep, supply, integration, operations, soft stockpile cap** |
| Academy | **Mandates are the primary learning reward** — the only source of doctrine slots, operations, replacement levies and early research conditions; gold becomes a minor secondary |
| naval | sea zones + ports; islands become objectives |
| newcomer balance | short front, upkeep on the veteran, integration brake, diminishing tech, Mandate equaliser |
| micromanagement | 10–15 decisions at 50 territories; **flat** in empire size |

Solves all thirteen failure modes. Costs the most, and needs the most product decisions (§21).

---

## 17. Recommended architecture

**Recommend OPTION 3, implemented incrementally through OPTION 2 as its first two phases.**

Why:

- **It stays interesting long-term** because its central loop is a *situation*, not a ladder: where is
  my front, what can I supply, which doctrine fits this war. Situations do not cap.
- **It avoids upgrade fatigue** because the repeated actions are sidegrades and positioning, not
  purchases. A maxed empire still has a different *shape* every week.
- **Learning stays valuable** because Mandates are the one resource idle time cannot produce — the
  direct fix for the measured 45,600-gold-once problem.
- **Growth does not create chores** because development is regional and management is frontier-scoped,
  so the action budget is flat in empire size (§15).
- **It is incrementally reachable from today's authority model.** Every step reuses existing
  server-owned concepts: adjacency already exists (frontier is derived from it), garrisons already
  exist (a field army is a garrison with a home), the reward ledger already handles idempotent grants
  (Mandates are a ledger scope), and rooms already isolate worlds. Nothing in §18 requires rewriting
  combat, ownership or grading.

The one thing to do *first* is the thing the brief refused to start with: **not** troop transfer, but
the **frontier/interior distinction**, because it is free (derived from existing data), it immediately
reduces micromanagement, and every later phase depends on it.

---

## 18. Migration roadmap

Phases derived from the recommendation, each independently shippable and reviewable.

### 13B — Frontier model (foundational, read-only)
- **authority:** none. `frontier(t)` is derived from existing adjacency + ownership.
- **API:** `/api/territory` may return a derived `frontier` boolean (or the client derives it).
- **state migration:** none.
- **UI:** the board distinguishes frontier from interior; Empire collapses interior territories into
  regional summary rows.
- **tests:** frontier derivation is a pure function; interior territories expose no per-tile controls.
- **compatibility:** total — nothing stored changes.
- **rollback risk:** none.

### 13C — Regions and regional policy
- **authority:** region membership is data (start from the existing continent metadata); *reinforcement
  policy* becomes server state.
- **API:** region read model; set-policy endpoint.
- **migration:** additive; absent policy == today's manual behaviour.
- **UI:** Empire becomes region-first.
- **tests:** region membership is derived from authored data, never client-supplied; a policy cannot
  create troops the player has not paid for.
- **rollback:** drop the policy field.

### 13D — Field armies and movement
- **authority:** a new army object; movement legality (adjacency, ownership) is server-decided.
- **API:** create / move / disband; attack takes an army id instead of a squad.
- **migration:** existing garrisons stay garrisons; armies start empty.
- **UI:** army markers on the board; the attack tray targets an army.
- **tests:** movement obeys adjacency; an army cannot teleport, split for free, or exceed its source.
- **rollback:** moderate — armies must be dissolved back into garrisons.

### 13E — Upkeep, supply and the stockpile cap
- **authority:** recurring economy. **The highest-risk phase** — it changes the meaning of a stored
  balance.
- **API:** economy read model gains upkeep/supply figures.
- **migration:** grandfather existing balances; introduce upkeep gradually.
- **UI:** upkeep and supply on the player plaque.
- **tests:** upkeep is charged exactly once per hour (the `calculate_passive_gold` catch-up pattern
  already solves this class of bug); upkeep can never take gold below zero or delete troops silently.
- **rollback:** set upkeep to zero — behaviour returns to today's.

### 13F — Global technology and doctrines
- **authority:** technology moves from per-territory to per-player; doctrine slots are new state.
- **API:** `/api/territory/research` is superseded by an empire-level research endpoint.
- **migration:** **needs a product decision** — convert existing per-territory levels into a global
  level (max? mean? refund?). §21.
- **UI:** Empire ▸ Technology becomes a tree + doctrine slots.
- **tests:** the tree is server-authoritative; a doctrine cannot make an illegal action legal; combat
  maths is pinned before and after.
- **rollback:** hard once converted — this phase needs the most review.

### 13G — Mandates (the learning ↔ strategy contract)
- **authority:** a new reward scope in the existing ledger; spend endpoints for operations.
- **API:** learning state reports a Mandate balance; spend endpoints.
- **migration:** additive. **Do not** retroactively grant for past lessons without a product decision.
- **UI:** Academy shows what learning now buys; Empire shows Mandate sinks.
- **tests:** Mandates are granted idempotently (reuse the `grantKey` discipline), can never be
  client-asserted, and **can never make an illegal action legal**.
- **rollback:** easy — stop granting; balances become inert.

### 13H — Sea zones and ports
- **authority:** a second adjacency relation, authored as data.
- **API:** the catalog publishes sea zones; `can_attack` accepts a naval path when both ends have ports.
- **migration:** additive; no port == today's rules.
- **UI:** sea zones on the board; Port in the building set.
- **tests:** adjacency authority stays server-side; a naval attack without ports at both ends is
  refused; the 900 land edge-ends are unchanged.
- **rollback:** easy — ignore sea zones.

### 13I — AI adaptation
- **authority:** AI behaviour only.
- Give the AI a **real, attackable** home so player success reduces pressure; teach it fronts, supply
  and doctrines.
- **tests:** the AI obeys exactly the same `can_attack` as a human (it already does).

### 13J — Balance pass
- Only after 13B–13I are live and measurable. Re-tune `GOLD_RATE`, upkeep, integration and Mandate
  prices against real sessions, not against a spreadsheet.

**Suggested order of value:** 13B (free, immediate relief) → 13C → 13G (protects the product's whole
premise) → 13E → 13D → 13F → 13H → 13I → 13J. Note 13G is deliberately early: failure 13 is the
soonest-appearing S1 in the audit.

---

## 19. CURRENT INVARIANTS — preserved unless a future phase explicitly reviews them

1. **Learning authority** — the server grades; the client submits `{activityId, answers}` and never
   score, passed, qualification or gold.
2. **Reward idempotency** — the ledger's `grantKey` (`scope:sourceId:policyId`) is derived, never
   client-supplied; `PASS_GOLD 160`, `MASTERY_GOLD 640`, paid once.
3. **Territory identity** — canonical ids; 250 world / 318 total; the frozen `gamePopulation`.
4. **Adjacency authority** — the catalog's `adjacentTerritoryIds`; 900 edge-ends; 0 cross-map; land
   adjacency required for attack.
5. **Server-authoritative combat** — `can_attack` decides legality; `resolve_attack` decides the
   outcome; the client replays a pre-ordered result.
6. **Room isolation** — `ROOM_MUTATIONS` + `_require_room()` fail closed before any state change.
7. **Class authority** — `may_manage()` is the only educator→learner relation; no self-management.
8. **Typed Read Along accommodation** — an educator-authorized *input* change only: same activity id,
   same `PASS_MARK 80`, same `record_read_along()`, same settlement.
9. **Camera / selection separation** — pan, zoom and shortcuts never mutate selection; selection never
   forces zoom; the camera never fetches or mutates authority.
10. **No learning gate on conquest** — 0 of 250 playable territories declare a requirement, and the
    server enforces none.
11. **Frozen constants** — fingerprint `736503ae2c4f5fa5`; `allowed_game_maps() == {"world"}`;
    `BUILD_COST`, `TECH_COST`, `TECH_MAX`, `GOLD_RATE`, `UNIT_COST`, `REENTRY_GOLD_COST`.

## 20. PROPOSED FUTURE CHANGES — each needs its own reviewed phase

| # | proposed change | phase | invariant it touches |
| --- | --- | --- | --- |
| P1 | derive frontier/interior from adjacency | 13B | none (read-only) |
| P2 | regions as the development unit; regional reinforcement policy | 13C | none stored today |
| P3 | field armies with server-decided movement | 13D | adds authority; combat entry point changes |
| P4 | **army upkeep, supply, stockpile cap** | 13E | economy semantics — a stored balance changes meaning |
| P5 | **technology becomes empire-global** with a tree, doctrines and condition-gated tiers | 13F | **directly changes invariant 11's `TECH_COST`/`TECH_MAX` semantics and the per-territory model** |
| P6 | conquest: global military tech, partial building inheritance, integration period | 13F | changes what a conquest is worth |
| P7 | **Mandates as the primary learning reward** | 13G | extends invariant 2 with a new scope; must preserve idempotency and must never grant legality |
| P8 | **sea zones + ports** as a second adjacency relation | 13H | **extends invariant 4** — land adjacency stops being the only path |
| P9 | the AI gets an attackable home | 13I | AI behaviour only |
| P10 | retire or server-own the client-side "Energy" stamina | any | it is currently forgeable localStorage gating one legacy surface |

## 21. Unresolved product decisions

These are **not** engineering questions, and none of them should be answered by an implementer:

1. **Is this a competitive game or a classroom tool?** Upkeep, stockpile caps and catch-up mechanics
   are right for competition and may be unwelcome friction in a classroom. Everything in §10 and §12
   depends on this answer.
2. **What happens to existing per-territory technology when it goes global** — take the maximum, the
   mean, or refund and reset? Real players have real purchases.
3. **Do past lessons retroactively grant Mandates?** Generous (a veteran learner is rewarded) versus
   clean (no retroactive economy). This one has a fairness dimension for existing students.
4. **What is a Mandate actually called, and does it appear in the Academy UI as a reward?** Naming a
   learning reward after a military concept has a tone implication for a children's education product.
5. **How large is a region** — 6 continents, or ~15 sub-regions? Decides whether region count stays
   flat as empires grow.
6. **Should an empire have a size limit at all?** Upkeep and supply create a *soft* ceiling; a hard cap
   is simpler and blunter.
7. **Does island conquest need naval units eventually**, or are ports enough for good? Ports are much
   cheaper to build and to understand.
8. **Is a 90-territory un-contestable third of the map acceptable in the meantime?** If sea zones slip,
   should those territories be temporarily excluded from claiming so the map is not 37 % free income?
9. **Should the AI ever be beatable to zero**, or is permanent pressure the point?
10. **How much of a school term is a "long-term arc"?** The 1-day / 1-week / 1-month / 3-month /
    6-month framing in the brief implies a persistent world; a classroom may want a resettable season.

---

## Addendum — implementation findings from Phase 13B

Recorded because §21 asked for unresolved product decisions and implementation surfaced two more. The
design above is **not** rewritten; these are additions.

**A. The front-line definition needed a third class.** §6 defines a two-way split
(`frontier = any neighbour not owned by me`, `interior = otherwise`). Under that rule a degree-0
territory has no un-owned neighbour and is therefore reported *interior* — technically true and
actively misleading, since 90 of 250 world territories can never be attacked or attack out. Phase 13B
adds **`isolated`** as a distinct derived class, using terminology the product already had: the server
has published `isolated` on re-entry candidates since Phase 10B, and the HUD card has said *"No land
neighbours — safe, but it cannot attack out"* since 10C.1. So the third class was named from existing
product language rather than invented. See [frontier-interior-design.md](frontier-interior-design.md).

**B. A new product question, added to §21 as item 11.** The rule is *local* (it looks only at a
territory's own neighbours), so a **fully-owned closed component** reports `interior` for every member.
The map has exactly one such component besides the singletons: the UK + Ireland pair. Those two are as
structurally unreachable as any island, but the local rule cannot express it. Options:

1. leave it (13B's choice — the rule stays simple and the limitation is documented);
2. redefine `isolated` as "in a component you own entirely" rather than "degree 0", which would make
   the class ownership-dependent rather than structural;
3. add a fourth class for it.

This matters more once §10's supply model lands, because a closed component's interior would generate
supply for a front it can never reach.

**C. Measured, for later balance work.** `classify_all` over the whole 250-territory world costs
**0.09 ms**, and Empire's aggregate overview renders in **0.6–2.6 ms flat** from 5 to 250 territories.
The §15 micromanagement budget is therefore not constrained by rendering cost at any empire size the
map allows — the constraint is purely how many *decisions* the design asks for.
