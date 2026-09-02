# v0.1 Playable Alpha — conquest rules

## 1. Objective

Put the game in front of real players. Not to model the final strategy simulation — to find out
whether the loop is any fun. Alpha rules are deliberately simpler than the eventual game.

## 2. The Alpha conquest rule

> **Ownership determines target eligibility. Adjacency does not.**

- a **neutral** World territory may be occupied regardless of adjacency
- an **enemy-held** World territory may be attacked regardless of adjacency

You are building a world empire, so you do not have to border a territory to take it.

**Global conquest is an Alpha rule.** It is not necessarily the final strategy model, and it may
become stricter once real play tells us what it costs.

## 3. What adjacency still means

Everything except authority. The catalogue is untouched — 900 edge-ends (642 on the World map),
0 cross-map edges, 90 territories with no land neighbour, the same component structure — and
`are_adjacent()` still answers truthfully. It is geographic information the map draws and the
inspector describes:

- **Frontier** — you hold it and at least one land neighbour is not yours
- **Interior** — you hold it and every land neighbour is yours
- **Isolated** — it has no land neighbour at all

None of the three grants or withholds attack authority. "Interior" does not mean you cannot attack,
and "Isolated" does not mean you cannot attack out — an island can march anywhere, and can be
attacked from anywhere. Strategic Regions are likewise descriptive only.

## 4. Occupy

Select a neutral territory; **Occupy** appears in the territory inspector; the planner opens in place
and the server settles it. Unchanged: the claim endpoint, eligibility, population, Gold, room rules
and the fact that a claim **costs troops from your pool** — that is the usual reason a claim is
refused, and it has nothing to do with geography.

Selection never claims anything by itself.

## 5. Attack

Select an enemy territory; **Attack** appears; the planner opens in the inspector; the server
resolves the battle. Unchanged: `validAttackSources`, source selection, the four troop classes,
`launchAttack`, `/api/territory/attack`, the battle formula, and every non-geographic rule —
identity, room membership, source ownership, no self-attack, squad validity and source garrison.

## 6. Source territories still matter

An attack marches **from a territory you own**, and you choose which:

- the committed squad leaves that territory's garrison
- the attacker's technology is the **source** territory's technology
- the defender's technology is the **target** territory's technology

So `validAttackSources(target)` now means *your garrisoned territories*, where it used to mean *your
garrisoned neighbours of the target*. The source is still a real decision; only the geographic filter
is gone. Automatic source picking was deliberately **not** added — if players find choosing a source
tedious, that is worth learning from play rather than guessing.

## 7. Deliberately deferred

Not in Alpha, and not partially implemented anywhere:

strategic connectivity · supply · upkeep · range · transport cost · naval movement · sea zones ·
field armies · victory conditions · troop transfer between territories · global technology ·
economy or battle rebalancing.

## 8. The core player loop

```
register  ->  World  ->  Occupy a territory
                 |
                 +->  Academy  ->  complete an activity  ->  earn Gold
                 |
                 +->  Empire > Forces  ->  Recruit
                 |
                 +->  select an enemy territory  ->  Attack  ->  battle result  ->  continue
```

Measured on a fresh account: **7 clicks** from a cold landing page to owning a territory, across
landing → account → World. Academy, Empire → Forces → Recruit and the attack flow are all reachable
from the board's chrome without leaving the World shell.

## 9. What counts as an Alpha blocker

Only something that stops a normal new player from: entering the game, claiming territory, learning,
receiving the expected reward, recruiting through the current system, attacking another player,
seeing the result, and carrying on.

Not blockers: spacing, typography, texture, button placement, list length, card styling. Those go to
the backlog and do not open a phase.

## 10. Rules may get stricter

This document describes v0.1. If unrestricted global conquest turns out to make the map
uninteresting — no fronts, no defensible ground, no reason to hold a border — the answer is a
designed restriction informed by play, not a return to the old adjacency gate by default. The
`not_adjacent` refusal reason is retained, unused, so a future rule can re-use it.
