# Ownership reconciliation — how a conquest becomes visible

Phase 14A.1 addendum. Written because an Alpha player won a territory and the World map did not turn
it into their colour, and because both causes are the kind that come back if nobody writes them down.

## The contract

```
player commits a squad
  -> POST /api/territory/attack        the server resolves the battle and settles ownership
  -> the battle window replays the settled result
  -> the window is dismissed BY ANY ROUTE
  -> loadEconomy -> loadTerritory -> renderEmpire + refreshMap
  -> colorize() paints ownership from territory.holders
```

The server is the only authority. The client never decides an outcome, never writes an owner, and
never paints a territory from "I saw the word WIN". `/api/territory/attack` does report the settled
`owner`, but the client reconciles by re-reading `GET /api/territory`, because that response also
carries the strategic classification, the garrison and the per-owner counts — everything the board,
the inspector and Empire derive. One refresh, one derivation.

## Rule 1 — an owner's colour is an important INLINE fill, never a class alone

`colorize()` writes `path.style.setProperty("fill", col, "important")` for **every** owner, the
player included.

The player used to be a special case: `colorize()` added the `.geo-mine` class and let CSS supply the
green. `.geo-mine` and the continent tints `.geo-cont-*` are both single-class `!important` fill
rules, so specificity ties and **declaration order decides** — and the tints are declared later in
the stylesheet. The tint won. A territory the player had just conquered rendered in its continent's
tint, pixel-identical to unowned land in the same continent:

| | before | after |
|---|---|---|
| conquered territory (Asia) | `#e9c46a` — the Asia tint | `#16a34a` — the player's green |
| unowned territory (Asia) | `#e9c46a` | `#e9c46a` |

An important inline declaration is the one author fill that outranks both, which is why every *other*
owner was already correct.

So: **never give ownership its colour through a class while a later `!important` class rule paints the
same element.** `.geo-mine` still exists — it carries non-fill meaning, and `gi-mine` styles the index
row — and its fill now names the same green `ownerColor()` returns, so the stylesheet cannot disagree
with what the runtime paints. `ownerColor()` is the single authority for who is what colour.

## Rule 2 — the battle window settles by every exit

`runBattle()` has one `settle()`. It closes the window, then calls back into the reconciliation, and
it runs at most once. It is reached from:

* the result button (`✅ OK` / `↩ Retreat`);
* the window's `✕`;
* a backdrop click;
* the window being removed part-way through the animation (both the round loop and the
  strike-animation callback).

Reconciliation used to hang off the result button alone. A player who dismissed the window any other
way kept a client that still believed the defender held the ground, and the board stayed
enemy-coloured until some unrelated refresh — the "I won but nothing changed" that was reported.

`settle()` takes no authority from the replay: the reconciliation re-reads the server, so settling
early can only ask what happened sooner. A loss therefore cannot repaint ownership, and neither can a
dismissal.

## What this does not do

No reload, no route reload, no polling, no artificial delay, no second ownership cache, no direct
`targetPath.style.fill = myColor`. State is reconciled first and rendering follows canonical state,
so the map colour, the inspector, the strategic classification, the owners legend, Empire's counts
and attack-source eligibility all move together from one refresh.

## Known, deliberately not widened

`refreshMap()` rebuilds the board rather than repainting it in place, and the 13C.1 shell reflows when
the inspector's content changes. So an offset the camera set against a wider or taller map viewport
can sit a few pixels outside the current pan limit, and the rebuild corrects it inward. Measured at
1440×900: scale never changes, and the correction was `dtx = −7.3 px` in one case and `dty = +159.7 px`
in another — the second reproduces identically on the pre-addendum build, on the unmodified result
button. It is a pre-existing clamp/reflow interaction, not part of this fix.

## Tests

* `tests/attack_reconciliation.test.js` — the client rules above, including the prohibitions.
* `tests/attack_settlement_test.py` — the server contract the client reconciles from: a win transfers,
  a loss does not, the response names the settled owner, and a forged `attackerWon` is ignored.
* Real-browser acceptance (two players, no reload): adjacent win, non-adjacent win, a win launched
  from a territory with no land neighbours, and a loss — each measured for owner, colour, inspector,
  markers and camera.
