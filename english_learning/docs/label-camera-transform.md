# The board's one camera transform

Phase 13C review. Why territory labels used to drift away from their territories, what replaced the
old projection, and what is now pinned so it cannot come back.

## The defect

A label sat away from the territory it named, and the gap grew as the player zoomed in. Measured in
real Chrome, worst of seven named territories (France, Germany, Japan, Australia, Canada, Brazil,
Singapore):

| camera | worst label-to-territory distance |
| --- | --- |
| home (s = 1.32) | 214.4 px |
| 2× | 405.7 px |
| 4× | 968.4 px |
| 8× | 2093.9 px |
| pan only, no zoom | 214.4 px |

## The cause

The camera moves the map by putting a CSS transform on the `<svg>` element itself:

```
transform: translate(tx, ty) scale(s)      /* transform-origin: 0 0 */
```

`svg.getBoundingClientRect()` reports that element's box **after** that transform. The label layer
measured its basis from exactly there:

```js
const hr = holder.getBoundingClientRect(), sr = svg.getBoundingClientRect();
PK  = Math.min(sr.width / vw, sr.height / vh);        // sr.width === layoutWidth * s
POX = (sr.left - hr.left) + (sr.width - vw * PK) / 2; // sr.left already contains tx
```

and then applied the camera a **second** time when positioning:

```js
const fx = POX + tx + (L.cx - vx) * PK * s;
```

So `s` was applied twice and `tx` was added twice. The formula is only correct if the measurement
happens at exactly `s = 1, tx = ty = 0`, which never happened: `attachPanZoom()` calls `apply()` at
construction, when `s` is already `CAM_HOME = 1.32`.

There were two regimes, and the difference matters:

- **Steady state.** `captureGeom()` is not re-run on every camera change, so `PK` stayed frozen at
  `k0 · 1.32` while the position formula kept multiplying by the live `s`. The error is therefore
  **linear in s** — which is the doubling the table above shows.
- **After a resize.** `_geoRelayout()` re-runs `captureGeom()`. Phase 12D deliberately removed the
  old `if (labelState.s === 1)` guard so that a layout shift would re-measure — correct in intent,
  but with a camera-contaminated basis it meant `PK` became `k0 · s` and the error turned
  **quadratic**. Anyone who resized the window while zoomed in got the worse of the two.

Modelled against the same stub board, executing the shipped pre-13C block for a mid-map anchor:

| camera | steady-state error | after-resize error |
| --- | --- | --- |
| s = 2 | 129 px | 836 px |
| s = 4 | 417 px | 5 941 px |
| s = 8 | 993 px | 28 400 px |
| s = 16 | 2 146 px | 122 323 px |

The same contaminated basis fed `cam.focusRect()` through `toVp()`, so "jump the camera to Europe"
and "show this territory on the map" were computing both the wrong centre and the wrong zoom. That
was never reported as a bug because nothing on screen says where the camera *meant* to go.

## The fix

Stop deriving a camera at all. `svg.getScreenCTM()` **is** the browser's own matrix from this SVG's
user space (viewBox units) to screen pixels, and it already includes the CSS transform. Label anchors
are projected through it, so geometry and labels cannot disagree — there is no second formula to
drift:

```js
function captureCTM() {
  const m = svg.getScreenCTM();
  if (!m) { CTM = null; return; }
  const hr = holder.getBoundingClientRect();
  CTM = m; CTMox = hr.left; CTMoy = hr.top;
}
const projX = (x, y) => CTM.a * x + CTM.c * y + CTM.e - CTMox;
const projY = (x, y) => CTM.b * x + CTM.d * y + CTM.f - CTMoy;
```

`a·x + c·y + e` is the matrix's own definition, not an approximation of it. The matrix is read once
per relayout and applied arithmetically per label, so 250 labels cost one DOM read, not 250.

`PK`, `POX` and `POY` survive, demoted to what they always should have been: a **layout**
measurement, taken from the holder's untransformed `clientWidth`/`clientHeight`, which no CSS
transform touches. Two consumers, neither of them a camera:

- `cam.focusRect()`, which takes s = 1 viewport units and applies the camera itself;
- the label collision boxes and zoom thresholds, which are about apparent size at s = 1.

`geoOffScreen()` used to re-apply the camera by hand (`st.tx + c.x * st.s` on top of `toVp()`). That
was the second approximate camera formula, and it now goes through `projX`/`projY` like everything
else.

## Offsets: map space versus screen space

There are **no authored map-space label offsets**. Every anchor is the territory path's own bbox
centre in viewBox units, verified over all 250 (`max authored map-space offset: 0`). So there is
nothing that a zoom could fail to transform.

The pill is centred on its anchor by CSS, `transform: translate(-50%, -50%)`, which resolves to
`matrix(1, 0, 0, 1, dx, dy)` — a pure **screen-space** translation with scale 1, applied after
projection. A camera zoom therefore cannot multiply it. The label layer itself carries no transform.

One consequence worth naming, because it is not a bug and must not be "fixed" with a nudge: for a
small or thin territory the pill is wider than the land, so it visually overhangs into the sea
(Portugal at the home camera is the clearest case). The anchor is exact; the pill is just bigger than
the country. Moving it would reintroduce exactly the kind of empirical offset this phase removed.

## Semantic zoom

The zoom band (`far` < 2, `mid` < 4.2, `near`) reaches the label layer only as `placeMapLabels`'
`zoom` argument. It changes **visibility, density and priority** — never the geographic anchor.
Measured across 20 camera states, each territory's anchor, inverse-projected back into viewBox units,
is identical to within 0.006 map units (floating-point noise in the harness's own matrix inverse).
Density rises with the band: 35 → 58 → 211 territory labels visible at far / mid / near. Continent
shortcuts lead at far (6 visible) and step aside at near (0). A selected label is always shown, keeps
its anchor, and is exempt from its zoom band.

## Measurements after the fix

Worst label-to-territory distance across 20 camera states — home, `restore` at s = 1/2/4/8/16, wheel
in and out, drag with and without zoom, a two-pointer pinch, all six continent shortcuts, and three
viewport resizes including 390×844:

**0.05 px**, at s = 16. Every state is exact to within 0.05 px. Changing `{s, tx, ty}` adds no
label-to-territory error beyond the home camera. Round trips through Empire, Academy, My Progress,
Ranking and Multiplayer all return to 0.01 px.

The camera also now goes where it was aimed: the Europe, Asia and Oceania shortcuts centre their
preset box to within 0.4 px of the viewport centre and all zoom in (`s >= 2`), and
`geoFocusKey("France")` centres France to within 1.0 px.

Cost of 30 camera operations: **0 network requests, 0 rebuilt SVG paths**, all 250 territory paths
intact, and an average of **4.5 ms** per camera update (median 4.4, worst 9.1) for 256 labels — the
labels move by `style.left`/`style.top`, and no path is ever re-created.

## What is pinned

`tests/label_transform.test.js` (15 checks) extracts the shipped projection block from `index.html`
and **executes** it against stub geometry whose `getBoundingClientRect` deliberately disagrees with
its untransformed client box — the exact condition the old code got wrong. It asserts on numbers, not
on the presence of strings:

- the layout basis comes from the untransformed box;
- that basis is identical at s = 1/2/8/16 (the s² regression) and identical under pan (the doubled-tx
  regression);
- `toVp()`, and therefore `cam.focusRect()`'s input, is camera-independent;
- `projX`/`projY` equal the reported matrix exactly, and a projected anchor round-trips back to its
  map coordinate at every camera;
- a missing matrix is reported as `null` rather than guessed at;
- `captureGeom()` re-measures after a resize, at any camera position;
- exactly one `getScreenCTM()` call site exists, and `geoOffScreen` uses the same projection;
- a camera update sets only `left`/`top`/`display` — no `innerHTML`, `appendChild`, `createElement`,
  `getBBox` or `fetch`;
- the pill centring is `translate(-50%, -50%)` with no scale of its own;
- the zoom band changes only `.visible`, never `fx`, `fy` or the collision box, and a selected label
  keeps its anchor.

Browser geometry is measured too, in the review harness (`accept_13clab.js`, 35 checks in real
Chrome): it drives the wheel, a real drag, a two-pointer pinch, every continent shortcut and three
viewport sizes, and compares every one of the 250 labels against `getScreenCTM()`. The maintained
suite deliberately stays browser-free — the repo's tests are stdlib-only Python and plain Node, and
adding Playwright to them would be a new dependency for the whole project. The maintained tests
therefore execute the real projection arithmetic, and the browser harness is what proves the
arithmetic matches a live Chrome.
