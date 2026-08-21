// Phase 13B — the client READS the classification and never derives it.
//
//   node tests/frontier_client.test.js
//
// The whole point of putting the classifier in game/frontier.py is that there is ONE definition of
// who is exposed. A second copy in JavaScript would drift, and then the board and the server would
// disagree about the front line — at which point the classification is worse than not having it.
// So the strongest thing this suite can assert is a negative: nowhere in index.html is frontier
// status computed from adjacency.
//
// It also pins the presentation constraints the phase set: the cue must not use a channel that
// ownership, selection or attack planning already own; it must not be colour-only; the map must not
// become a dashboard; and Empire must aggregate before it lists.
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

// ================= 1. the client never classifies =================
// Every way a client could derive this itself, forbidden by name.
for (const forbidden of ["function classifyTerritory", "function isFrontier", "function computeFrontier",
                         "function frontierOf", "adjacentTerritoryIds.some", "adjacentTerritoryIds.every",
                         "adjacentTerritoryIds.filter(n =>", "neighbours.every", "neighbors.every"]) {
  assert(code.indexOf(forbidden) === -1, "the client must not derive the classification: " + forbidden);
}
// the one legitimate read
assert(/\(holders\[r\.key\] \|\| \{\}\)\.strategic/.test(code),
  "the map must read the server's published class");
assert(/\(h \|\| \{\}\)\.strategic/.test(code), "the HUD card must read it too");
assert(/territory && territory\.strategicSummary/.test(code),
  "Empire must read the server's own summary");
ok("1. exactly one definition: the client reads holders[].strategic and territory.strategicSummary, " +
   "and derives nothing from adjacency itself");

// ================= 2. the cue does not steal a channel that is already taken =================
// ownership owns FILL on the land path; selection / attack source / attack target own STROKE.
const stratCss = html.slice(html.indexOf(".geo-strategic"), html.indexOf(".gl-frontier::before"));
// The cue must not use stroke as a SIGNAL — selection, attack source and attack target all do, and a
// fourth stroke would be unreadable. `stroke: none` is the opposite of a signal: it suppresses the
// land stroke the overlay would otherwise inherit from `.geo-svg path`, which really would have drawn
// a competing outline. So: no stroke colour and no stroke width, and an explicit stroke: none.
// Read the DECLARED VALUES rather than pattern-matching around them: a `stroke:\s*(?!none)` lookahead
// backtracks `\s*` to zero characters and then "matches" `stroke: none`, which is how this assertion
// first passed a version of the CSS it should have rejected.
const stratDecls = stratCss.replace(/\/\*[\s\S]*?\*\//g, "");
const strokeValues = (stratDecls.match(/stroke:\s*([^;}]+)/g) || []).map(v => v.split(":")[1].trim());
assert(strokeValues.length === 2 && strokeValues.every(v => v === "none"),
  "the overlay must declare stroke: none and nothing else — selection and attack own that channel " +
  "(found " + JSON.stringify(strokeValues) + ")");
assert(!/stroke-width/.test(stratDecls), "...and no stroke width either");
assert(/fill: url\(#stratFrontier\)/.test(html) && /fill: url\(#stratIsolated\)/.test(html),
  "it uses a pattern fill on its OWN overlay layer, not on the land path");
assert(/\.geo-strategic \{ pointer-events: none; \}/.test(html),
  "the overlay must never intercept a click");
// the land path keeps every existing state class untouched
for (const kept of [".geo-region.geo-sel", ".geo-region.geo-src", ".geo-region.geo-tgt",
                    ".geo-mine", ".geo-open"]) {
  assert(html.indexOf(kept) >= 0, "existing state styling must survive: " + kept);
}
ok("2. the cue is a texture on its own pointer-events:none layer — ownership fill, selection stroke " +
   "and the attack outlines are all untouched");

// ================= 3. not colour alone =================
// The patterns are built with createElementNS, not innerHTML: assigning innerHTML on an SVG element
// runs the HTML parser, which puts <pattern> in the wrong namespace and makes fill:url(#...) fall
// back to a SOLID COLOUR -- silently defeating the whole point. So this pins the construction method
// as well as the shapes, because the markup-looking version was the bug.
assert(/id: "stratFrontier"[\s\S]{0,260}_mkEl\("line"/.test(code),
  "frontier must be a hatch (a line shape) built in the SVG namespace");
assert(/id: "stratIsolated"[\s\S]{0,200}_mkEl\("circle"/.test(code),
  "isolated must be a dot pattern (a circle shape) built in the SVG namespace");
assert(!/_defs\.innerHTML/.test(code),
  "the pattern defs must never be built with innerHTML — the HTML parser breaks the namespace");
assert(/document\.createElementNS\(NSU, tag\)/.test(code), "...they use createElementNS");
assert(/STRAT_COPY = \{/.test(code) && /Frontier/.test(code) && /Isolated/.test(code),
  "and the classification is stated in WORDS in the territory card");
ok("3. the distinction survives colour-blindness and greyscale: two different textures plus words");

// ================= 4. the map stays a map =================
const paint = slice("function paintStrategic()", "colorize();", "paintStrategic");
assert(/if \(cls !== "frontier" && cls !== "isolated"\) return;/.test(paint),
  "interior gets NO decoration — the quiet majority stays quiet");
assert(/if \(!r\.key \|\| !r\.p \|\| r\.dup\) return;/.test(paint),
  "only real, non-duplicate territories are considered");
assert(/\[data-zoom="far"\] \.geo-strategic \{ display: none; \}/.test(html),
  "semantic zoom suppresses the texture at FAR, where 250 textures would be noise");
for (const forbidden of ["fetch(", "loadTerritory", "hudSelect", "openTray", "claimTroops"]) {
  assert(paint.indexOf(forbidden) === -1, "painting must not " + forbidden);
}
ok("4. the map is not a dashboard: interior is undecorated, the texture is suppressed at FAR zoom, " +
   "and painting fetches nothing and changes no selection");

// ================= 5. camera and selection are untouched (12C/12D frozen) =================
const camera = slice("function attachPanZoom", "\n  let curDrawArgs", "attachPanZoom");
for (const forbidden of ["strategic", "frontier", "isolated", "paintStrategic"]) {
  assert(camera.indexOf(forbidden) === -1, "the camera must know nothing about classification");
}
const sel = slice("window.hudSelect = function (key)", "\n      const legend", "hudSelect");
assert(sel.indexOf("strategic") === -1 && sel.indexOf("paintStrategic") === -1,
  "selection must not depend on classification");
assert(/geoOffScreen\(key\)\) geoFocusKey\(key, \{ keepZoom: true \}\)/.test(sel),
  "the 12D camera-assist rule is unchanged");
ok("5. the 12C/12D camera and selection contract is frozen — neither knows the classification exists");

// ================= 6. attack planning is untouched =================
const confirm = slice("function trayConfirm()", "\n      function renderHudActions", "trayConfirm");
const tray = slice("function renderTray()", "\n      function traySquad", "renderTray");
for (const forbidden of ["strategic", "frontier", "interior", "isolated"]) {
  assert(confirm.indexOf(forbidden) === -1 && tray.indexOf(forbidden) === -1,
    "attack planning must not consult the classification: " + forbidden);
}
assert(/const key = hudSelKey, mode = trayMode, squad = traySquad\(\), src = traySrc;/.test(confirm),
  "the plan is still captured before teardown");
assert(/launchAttack\(src, key, name, h, squad\)/.test(confirm), "and still fires the same call");
ok("6. attack planning and execution are byte-identical — the classification gates nothing");

// ================= 7. Empire aggregates before it lists =================
const overview = slice("function empireOverview(body, rows)", "\n  function empireForces", "empireOverview");
assert(/let empTab = "overview";/.test(code), "Empire opens on the overview");
assert(/class="emp-stat"/.test(overview) && /Territories<\/small>/.test(overview) &&
       /Frontier<\/small>/.test(overview) && /Interior<\/small>/.test(overview) &&
       /Isolated<\/small>/.test(overview),
  "the overview answers size / exposure / safety / isolation in four counts");
assert(/<details class="emp-group"/.test(overview),
  "territories live inside collapsed groups — a drill-down, not the first thing shown");
assert(!/<details class="emp-group"[^>]*open/.test(overview),
  "and those groups are CLOSED by default, so a 50-territory empire renders no territory rows");
assert(/sum \? sum\[k\] : byClass\[k\]\.length/.test(overview),
  "the counts prefer the SERVER's summary over anything counted locally");
assert(!/threat/i.test(overview), "no invented threat level — the server publishes no enemy strength");
ok("7. Empire leads with four authoritative counts; individual territories are inside closed groups");

// ================= 8. drill-down goes to the BOARD, not to a management form =================
assert(/closeModal\(\);[\s\S]{0,120}window\.hudSelect\(key\)/.test(overview),
  "a territory chip closes Empire and selects that territory on the board");
assert(/geoFocusKey\(key, \{ pad: 3\.2, minZoom: 2\.2 \}\)/.test(overview),
  "...and points the camera at it");
for (const forbidden of ["buildingsPanel", "openBuildingDetail", "deployPanel", "openTray"]) {
  assert(overview.indexOf(forbidden) === -1,
    "the overview must not open a management form: " + forbidden);
}
ok("8. the overview drills down to the map, never into a per-territory management form");

// ================= 9. the territory card states the class in words =================
const card = slice("function renderHudCard()", "\n      function renderHudPlayers", "renderHudCard");
assert(/borders territory you do not control/.test(card), "frontier copy");
assert(/every land neighbour is yours/.test(card), "interior copy");
assert(/no land connection/.test(card) && /sea routes are not modelled yet/.test(card),
  "isolated copy must state the structural limitation honestly");
assert(/const sc = mine \? \(h \|\| \{\}\)\.strategic : null;/.test(card),
  "shown only for territories the player owns, because that is all the server classifies");
assert(card.indexOf("openModal") === -1 && card.indexOf("openRegion") === -1,
  "no modal, and the retired region panel stays retired");
ok("9. the selected territory states its classification in short honest copy, with no modal");

// ================= 10. nothing persisted, nothing invented =================
assert(!/localStorage[^\n]*(strategic|frontier|interior|isolated)/i.test(code),
  "the classification must never be cached in localStorage");
assert(!/frontier:\s*(true|false)/.test(code) && !/interior:\s*(true|false)/.test(code),
  "no boolean flag may be stored anywhere");
// no fake connectivity anywhere in the client either
for (const invented of ["seaZone", "naval", "portTo", "canReachBySea"]) {
  assert(code.indexOf(invented) === -1, "13B must invent no connectivity: " + invented);
}
ok("10. no persisted flag, no localStorage cache, and no invented sea connectivity");

console.log("\nAll " + passed + " frontier client checks passed.");
