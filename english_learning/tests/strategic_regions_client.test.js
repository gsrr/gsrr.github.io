// Phase 13C — Empire is region-first, and a region is an aggregation view, never a map mode.
//
//   node tests/strategic_regions_client.test.js
//
// The retired container model (World -> continent -> territory) is exactly what 12C/12D spent two
// phases removing, and "regions" is the obvious name for bringing it back by accident. So the sharpest
// assertions here are negatives: a region row cannot redraw the board, cannot filter the territory set,
// cannot rewrite the viewBox, cannot open a modal, and cannot carry a management control.
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
let passed = 0;
function ok(name) { passed++; console.log("  ok -", name); }
function stripComments(src) {
  return src.replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\//g, "")
            .replace(/^[ \t]*\/\/.*$/gm, "");
}
const code = stripComments(html);
function slice(from, to, label) {
  const i = code.indexOf(from);
  assert(i > 0, "not found: " + (label || from));
  const j = code.indexOf(to, i + from.length);
  assert(j > i, "end marker not found for " + (label || from));
  return code.slice(i, j);
}
const overview = slice("function empireOverview(body, rows)", "\n  function empireForces", "empireOverview");
const camera = slice("function attachPanZoom", "\n  let curDrawArgs", "attachPanZoom");
const build = slice("function build(svgText)", "\n      function hudSlot", "build()");

// ================= 1. the client reads the server's aggregation and computes none of it =================
assert(/const regs = \(territory && territory\.regions\) \|\| \[\];/.test(overview),
  "the region rows must come from the server");
assert(/territory && territory\.regionNote/.test(overview), "as must the structural note");
for (const forbidden of ["function aggregateRegions", "function summarizeRegion", "reduce((acc",
                         "countFrontier", "regionCounts["]) {
  assert(code.indexOf(forbidden) === -1, "the client must not aggregate regions itself: " + forbidden);
}
// the only place the client touches metadata.continent is to pick a region's OWN members for the
// drill-down list and to compute a camera rectangle — never to produce a count
const contUses = (code.match(/\.continent/g) || []).length;
assert(contUses <= 3, "metadata.continent should be read only for grouping and the camera, got " +
  contUses + " uses");
assert(!/continent[^\n]*(owned|frontier\+\+|interior\+\+|isolated\+\+|count)/i.test(code),
  "the client must never derive a region COUNT from continent metadata");
ok("1. every region figure is the server's; the client reads territory.regions and never aggregates");

// ================= 2. region summary comes BEFORE the territory lists =================
const regIdx = overview.indexOf('<div class="emp-sec">Regions');
const allIdx = overview.indexOf('<div class="emp-sec">All territories');
const grpIdx = overview.indexOf("const GROUPS = [");
assert(regIdx > 0 && allIdx > regIdx && grpIdx > regIdx,
  "the region section must render before the per-class territory lists");
assert(/class="emp-stat"/.test(overview.slice(0, regIdx)),
  "and the empire-wide counts must come before the regions");
ok("2. the overview is three tiers in order: empire totals, then regions, then territory lists");

// ================= 3. compact rows, no wall, no management control =================
assert(/<details class="emp-reg"/.test(overview), "a region is a collapsed row");
assert(!/<details class="emp-reg"[^>]*\sopen/.test(overview), "closed by default");
assert(/data-region-pending=/.test(overview), "its contents are built lazily, on first open");
const regionBody = slice("function buildRegion(g)", "body.querySelectorAll(\".emp-reg\")", "buildRegion");
for (const forbidden of ["buildingsPanel", "openBuildingDetail", "deployPanel", "openTray",
                         "openConscriptDetail", "emp-act", "<input", "<select"]) {
  assert(regionBody.indexOf(forbidden) === -1 && overview.indexOf(forbidden) === -1,
    "no management control may appear in a region summary or drill-down: " + forbidden);
}
ok("3. regions are compact collapsed rows, built on first open, with no management control anywhere " +
   "in the summary or the drill-down");

// ================= 4. the drill-down groups by strategic class =================
assert(/\["frontier", "\\u2694\\uFE0F Frontier"\], \["interior"/.test(regionBody) ||
       /Frontier[\s\S]{0,120}Interior[\s\S]{0,120}Isolated/.test(regionBody),
  "a region's territories are grouped Frontier / Interior / Isolated");
assert(/\(holders\[m\.key\] \|\| \{\}\)\.strategic/.test(regionBody),
  "...using the SERVER's per-territory classification, not a client rule");
ok("4. a region drill-down groups its territories by the server's own Frontier/Interior/Isolated");

// ================= 5. Show on map is CAMERA ONLY — the container model stays dead =================
const focus = slice("geoFocusRegion = function (regionKey)", "geoOffScreen = function", "geoFocusRegion");
for (const forbidden of ["drawGeo", "renderGeoMap", "groupFilter", "setAttribute(\"viewBox\"",
                         "paths.filter", "openModal", "innerHTML", "hudSelect", "refreshMap"]) {
  assert(focus.indexOf(forbidden) === -1,
    "Show on map must move the camera and nothing else: " + forbidden);
}
assert(/focusBounds\(/.test(focus), "it moves the camera through the existing focus helper");
assert(/markerSpecs\.find\(L => L\.cont === regionKey/.test(focus),
  "and reuses the 12C continent camera presets when they line up");
const wire = regionBody.slice(regionBody.indexOf("data-region-map"));
assert(/closeModal\(\);[\s\S]{0,90}geoFocusRegion\(rk\)/.test(regionBody),
  "the button closes Empire and asks the camera to move");
ok("5. Show on map is navigation only: it reuses the 12C presets and cannot redraw, filter, " +
   "re-viewBox or modal");

// ================= 6. no region map mode, no region layer on the board =================
for (const forbidden of ["regionMode", "showRegionLayer", "geo-region-boundary", "geo-region-layer",
                         "data-region-tint", "filterRegion"]) {
  assert(code.indexOf(forbidden) === -1, "13C must add no map mode or region layer: " + forbidden);
}
// the board's own render path must not know about regions at all
assert(build.indexOf("territory.regions") === -1 && build.indexOf("emp-reg") === -1,
  "the board renderer must not consult the region aggregation");
assert(camera.indexOf("region") === -1, "the camera must not know what a region is");
ok("6. no region mode, no permanent region boundaries, no region layer — the board renderer and the " +
   "camera do not know regions exist");

// ================= 7. the frontier visual language is unchanged =================
assert(/\.geo-svg path\.geo-strat-frontier \{ fill: url\(#stratFrontier\); stroke: none; \}/.test(html),
  "the 13B frontier texture is untouched");
assert(/\.geo-svg path\.geo-strat-isolated \{ fill: url\(#stratIsolated\); stroke: none; \}/.test(html),
  "as is the isolated texture");
assert(/\[data-zoom="far"\] \.geo-strategic \{ display: none; \}/.test(html),
  "and its FAR-zoom suppression");
// the region pips carry a shape as well as a colour, matching the map's language
assert(/pip\("er-f", r\.frontier, "Frontier", "\\u2694"\)/.test(overview) &&
       /pip\("er-i", r\.interior, "Interior", "\\u25a0"\)/.test(overview) &&
       /pip\("er-o", r\.isolated, "Isolated", "\\u25cf"\)/.test(overview),
  "each region count carries a glyph, so it is not colour-only");
ok("7. the 13B map language is untouched, and the region counts carry glyphs rather than colour alone");

// ================= 8. the closed-component caveat is stated, not spun =================
// The copy is built by string concatenation across source lines, so join those seams before matching:
// otherwise a purely cosmetic re-wrap would fail an assertion about the WORDS.
const noteText = overview.replace(/'\s*\+\s*\n?\s*'/g, "");
assert(/Interior means every land neighbour is yours/.test(noteText),
  "the note must say what interior actually means");
assert(/not mean a territory is connected to a front/.test(noteText),
  "...and that it does NOT mean connected to a front");
assert(/sea routes are not modelled yet/.test(noteText),
  "...and that sea routes remain unmodelled");
for (const banned of ["safe supply", "supporting territory", "connected rear", "productive rear",
                      "secure logistics", "supply region", "development region", "army region"]) {
  assert(html.toLowerCase().indexOf(banned) === -1, "13C must not claim: " + banned);
}
ok("8. the note states what interior means and what it does not; none of the forbidden supply / rear " +
   "/ logistics language appears anywhere");

// ================= 9. nothing persisted, nothing cached =================
assert(!/localStorage[^\n]*(regions|continent|emp-reg)/i.test(code),
  "region state must never be persisted");
assert(/const empOpenRegions = new Set\(\);/.test(code),
  "which rows are expanded is a session-only Set");
ok("9. no region state is persisted; the expanded-row memory is a session-only Set");

// ================= 10. the existing management areas survive =================
const empire = slice("function renderEmpireModal()", "\n  function empireOverview", "renderEmpireModal");
assert(/\["overview", "🗺️ Overview"\]/.test(empire) && /\["forces", "⚔️ Forces"\]/.test(empire) &&
       /\["buildings", "🏛️ Buildings"\]/.test(empire) && /\["tech", "🏭 Technology"\]/.test(empire),
  "all four areas remain, Overview leading");
assert(/let empTab = "overview";/.test(code), "Overview is still the default");
ok("10. Forces, Buildings and Technology are untouched and still reachable; Overview still opens");

console.log("\nAll " + passed + " strategic-region client checks passed.");
