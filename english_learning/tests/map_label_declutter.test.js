// Phase 14A.11A — WORLD MAP LABEL DECLUTTER.
//
//   node tests/map_label_declutter.test.js
//
// The 14A.11 audit measured the World overview at the home camera (zoom 1.32, 1440x900): 40
// territory name pills, 18 of them wider than the territory they named, all in the heaviest visual
// style on the board -- so the map read as a wall of words rather than as a strategy map.
//
// Three behavioural changes answer that, and nothing else changed: the admission threshold is
// stronger, a label must actually FIT the ground it names, and the territory the player selected is
// exempt from both. The pre-existing collision pass, the zoom model, the priority model and the
// label styling are all untouched, and there is deliberately NO global cap on how many labels may
// appear -- density is an outcome of the rules, not a hard-coded ceiling.
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const code = html.split(/\r?\n/).filter(l => !/^\s*\/\//.test(l)).join("\n");

let passed = 0;
function assert(c, m) { if (!c) { console.error("  FAIL - " + m); process.exit(1); } }
function ok(n) { passed++; console.log("  ok -", n); }

function slice(from, to, label) {
  const a = code.indexOf(from);
  assert(a >= 0, "cannot find " + label + " start: " + from);
  const b = code.indexOf(to, a + from.length);
  assert(b > a, "cannot find " + label + " end: " + to);
  return code.slice(a, b);
}

const place = slice("const LABEL_MIN_TERR_PX", "let hudSelKey", "placeMapLabels");
const build = slice("markerSpecs.forEach(L => {", "relayoutLabels = function", "label build");
const relay = slice("relayoutLabels = function", "_geoResel = function", "relayoutLabels");

// ===================== A/B. still zoom-dependent, through a stronger bar =====================
assert(/L\.minZoom = Math\.max\(0, LABEL_MIN_TERR_PX \/ Math\.max\(6, restW\)\)/.test(build),
  "a territory's zoom threshold is still derived from how much room it has");
assert(/const LABEL_MIN_TERR_PX = 90;/.test(code), "the threshold is 90px of territory at s=1");
assert(/zoom >= c\.minZoom && zoom <= c\.maxZoom/.test(place),
  "the zoom band is still what admits a label");
assert(code.indexOf("46 / Math.max(6, restW)") < 0, "the old permissive 46 is gone");
ok("A/B. territory labels remain zoom-dependent through the SAME formula, with a stronger named " +
   "threshold (90px of territory at s=1) instead of the audited 46");

// ===================== C. real rendered width, not a character count =====================
assert(/L\.w = \(Math\.round\(el\.getBoundingClientRect\(\)\.width\) \|\| 0\)/.test(build),
  "each label is measured once, from the DOM, while it is still displayed");
// Phase 14A.11B: a normal label lost its pill, so the measured width no longer includes the box
// the admission geometry was tuned against. LABEL_PAD_PX restores exactly that horizontal chrome
// for the fit/collision maths, which is why a restyle does not become a density rollback.
assert(/\+ \(L\.cont \? 0 : LABEL_PAD_PX\)/.test(build),
  "...and a bare label is credited the breathing room its pill used to provide");
assert(/const LABEL_PAD_PX = 19;/.test(code),
  "that padding is the pill's own 8px+1.5px chrome on both sides, so geometry is preserved");
assert(/const w = L\.w \|\| \(txt\.length \* FS \* 0\.56 \+ PADX\)/.test(relay),
  "...and that measurement is what every later decision uses, with the old estimate only as a " +
  "fallback for a label that could not be measured");
assert(/box: \{ x0: fx - w \/ 2/.test(relay),
  "the collision box uses the same one width -- there is no second geometry system");
ok("C. the ACTUAL rendered label width participates in visibility: measured once from the DOM and " +
   "shared by the fit rule and the collision box");

// ===================== D/E. the fit rule =====================
assert(/const terrW = \(L\.restW \|\| 0\) \* s;/.test(relay),
  "the territory's CURRENT screen width is derived from its width at s=1 and the live zoom");
assert(/const fits = !!L\.cont \|\| terrW <= 0 \|\| w <= terrW \* LABEL_FIT_RATIO;/.test(relay),
  "a label fits when it is no wider than its territory, times the ratio");
assert(/const LABEL_FIT_RATIO = 1\.0;/.test(code),
  "the ratio is 1.0 -- a name must fit the ground it names");
assert(/c\.fits !== false/.test(place), "a label that does not fit is not admitted");
assert(/L\.restW = restW;/.test(build), "the territory width is carried on the spec for that test");
ok("D/E. an oversized label is rejected and a fitting one is admitted: the rule compares the " +
   "measured pill against the territory's live screen width, so it re-decides at every zoom");

// ===================== F/G/H/I. the selected territory =====================
assert(/selected: !!\(L\.key && L\.key === hudSelKey\)/.test(relay),
  "the label layer reads the EXISTING selection authority, hudSelKey");
assert(!/let geoSelectedKey/.test(code) && !/geoSelectedKey =/.test(code),
  "the dead second selection variable is gone, not merely bypassed");
assert(/const eligible = cands\.filter\(c => c\.selected \|\|/.test(place),
  "the selected label is admitted whatever the zoom band says");
assert(/c\.selected \|\|\s*\(zoom >= c\.minZoom && zoom <= c\.maxZoom && c\.fits !== false\)/.test(place),
  "...and whatever the fit rule says");
assert(/eligible\.sort\(\(a, b\) => \(b\.selected \? 1 : 0\) - \(a\.selected \? 1 : 0\) \|\| b\.priority - a\.priority\)/
  .test(place), "the selected label is sorted FIRST, so it is placed before any ordinary label");
assert(/if \(c\.selected\) \{ c\.visible = true; placed\.push\(c\.box\); return; \}/.test(place),
  "...and it reserves its box, so no ordinary label is drawn on top of it");
assert(/hudSelKey = key;[\s\S]{0,400}if \(_geoResel\) _geoResel\(\);/.test(code),
  "changing the selection re-lays out the labels, so the exemption follows the current selection");
ok("F/G/H/I. the selected territory bypasses both the zoom threshold and the fit rule, is placed " +
   "before every ordinary label, and follows the one existing selection authority");

// ===================== J. continents unchanged =====================
const cont = slice("if (L.cont) {", "} else {", "continent branch");
assert(/L\.priority = 1e6 \+ restW;/.test(cont) && /L\.minZoom = 0; L\.maxZoom = 4\.2;/.test(cont),
  "continent labels keep their own band and their top priority");
assert(/const fits = !!L\.cont \|\|/.test(relay),
  "a continent names no territory, so it is never a fit candidate");
ok("J. continent labels are untouched: same 0-4.2 band, same priority, and exempt from the fit " +
   "rule by construction");

// ===================== 14A.11B: what the labels LOOK like =====================
// Density was 14A.11A's job. This is the other half: a country name must read as ink printed on
// the map, while the two labels that really are UI -- the selected territory and the continent
// camera shortcuts -- keep the board-game pill.
const baseCss = html.slice(html.indexOf(".geo-lab { position: absolute"),
                          html.indexOf(".geo-lab.sel {"));
const selStart = html.indexOf(".geo-lab.sel {");
const selCss = html.slice(selStart, html.indexOf("}", selStart) + 1);
const contCss = html.slice(html.indexOf(".geo-lab.cont { pointer-events"),
                           html.indexOf(".geo-lab.cont:hover"));
assert(/background: none;/.test(baseCss) && /border: 0;/.test(baseCss) &&
       /box-shadow: none;/.test(baseCss) && /border-radius: 0;/.test(baseCss),
  "D. a normal territory label has no fill, no border, no radius and no box shadow");
assert(!/linear-gradient/.test(baseCss), "...and no gradient pill of its own");
assert(/font-size: 13px; font-weight: 800/.test(baseCss),
  "E. it keeps the readable child-facing size and weight -- it was not shrunk into hiding");
assert(/color: #3b2a15;/.test(baseCss) && (baseCss.match(/#fff6e2/g) || []).length >= 6,
  "E2. it is dark ink over a multi-directional cream halo, so it stays legible on any fill");
assert(/linear-gradient\(#3fae5f, #1d7c3c\)/.test(selCss) &&
       /border: 1\.5px solid #fff/.test(selCss) && /box-shadow:/.test(selCss),
  "F. the SELECTED label is visibly stronger: it keeps the pill, in the selection green");
assert(/linear-gradient\(#3d5a80, #263b57\)/.test(contCss) &&
       /cursor: pointer/.test(contCss) && /box-shadow:/.test(contCss) &&
       /text-transform: uppercase/.test(contCss),
  "G. continent labels keep their own clickable blue pill -- they are camera buttons");
ok("D-G. normal names are map ink; the selected territory and the continent shortcuts keep the " +
   "pill, so the only boxed labels on the board are the two that are genuinely UI");

// ===================== what was deliberately NOT done =====================
assert(!/MAX_LABELS|maxLabels|labelCap/.test(code),
  "C. no global or per-viewport label cap was introduced");
assert(/eligible\.forEach\(c => \{/.test(place) &&
       /const hit = placed\.some\(b => rectsOverlap\(c\.box, b\)\)/.test(place),
  "the pre-existing collision pass still decides the rest, unchanged and uncapped");
assert(/const CAM_MIN = 1;/.test(code) && /const CAM_MAX = 16;/.test(code),
  "K. the camera limits are unchanged");
assert(/\.geo-lab \{ position: absolute; transform: translate\(-50%, -50%\)/.test(html),
  "the label layer is still the same positioned HTML overlay -- no new architecture");
ok("C/K. no label cap, no priority redesign, no camera change and no new label architecture");

console.log("\nAll " + passed + " map-label-declutter checks passed.");
