// Phase 12C — one continuous World camera, direct territory selection, in-board combat, and Empire
// as the single management destination.
//
//   node tests/world_camera.test.js
//
// The defect this phase removed was structural, not cosmetic. The board's on-screen size was derived
// from the SVG's viewBox aspect ratio, and "entering" a continent REWROTE that viewBox to the
// continent's bounding box — so navigating to Oceania re-proportioned the entire board into a shallow
// horizontal strip and drew Australia wrong. On top of that, a single tap meant two different things
// depending on an invisible altitude: at the World view it drilled into a continent, and only inside
// a continent did it select a territory.
//
// What is pinned here: the viewport owns its shape and the map moves inside it under a camera; a tap
// always selects; continents are camera presets and nothing more; combat is planned in the board
// rather than in a modal; and repetitive empire administration lives in Empire, not on every
// territory. Behaviour itself is exercised end to end by scratchpad/accept_12c.js against the real
// server (84 checks in real Chrome).
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
const camera = slice("function attachPanZoom", "\n  let curDrawArgs", "attachPanZoom");
const drawGeo = slice("function drawGeo", "\n  function selectLevel", "drawGeo");
const build = slice("function build(svgText)", "\n      function hudSlot", "build()");

// ================= 1. ONE continuous map =================
assert(!/groupFilter/.test(code.replace(/[^\n]*groupFilter[^\n]*is gone[^\n]*/g, "")) ||
       !/spec\.groupFilter/.test(code),
  "no code may read spec.groupFilter any more");
assert(!/Object\.assign\(\{\}, spec, \{ groupFilter/.test(code),
  "nothing may re-draw the board with a continent filter");
// Exactly ONE viewBox write may exist, and it may only INSTALL the authored value when the file
// itself carries none. A write derived from geometry is the shallow-strip defect.
const vbWrites = code.match(/[^\n]*setAttribute\("viewBox"[^\n]*/g) || [];
assert(vbWrites.length === 1, "only one viewBox write may exist, got " + vbWrites.length);
assert(/if \(!svg\.getAttribute\("viewBox"\) && spec\.viewBox\)/.test(vbWrites[0]),
  "that write must be the install-if-absent fallback, not a rewrite: " + vbWrites[0].trim());
assert(!/setAttribute\("viewBox",[^\n]*(x0|y0|x1|y1|bbox|getBBox|bounds)/.test(code),
  "no viewBox may ever be computed from geometry — that was the shallow-strip defect");
assert(/const grouped = !!spec\.grouped;/.test(build) && !/contFilter/.test(build.replace(/\/\/[^\n]*/g, "")),
  "continent metadata may remain, but not as an interaction mode");
ok("1. one continuous World map: no continent filter, no territory-set swap, no viewBox rewrite");

// ================= 2/3. a tap always selects, and never drills =================
// The wiring for a TERRITORY starts after the legacy `spec.drill` sub-map guard. That guard belongs
// to the old Taiwan->Taipei container, which the playable spec does not declare, so it is unreachable
// on the World: asserted below rather than assumed.
// Phase 12D: there is no longer a `spec.drill` guard to skip -- the container branch was REMOVED,
// not left dormant -- so the territory wiring is the whole loop.
const clickWiring = build.slice(build.indexOf("paths.forEach(p => {"));
assert(/p\.addEventListener\("click", \(\) => \{ if \(window\.hudSelect\) window\.hudSelect\(key\); \}\);/
  .test(clickWiring), "a territory click must call hudSelect(key)");
assert(!/p\.addEventListener\("click", open\)/.test(clickWiring),
  "a territory click must no longer open the region modal");
assert(!/drawGeo\(Object\.assign/.test(build), "no click may re-enter drawGeo with another spec");
// Phase 12D: the container model is gone from the implementation, so these are now WHOLE-FILE
// assertions rather than per-branch ones -- strictly stronger than what 12C could claim.
assert(!/spec\.drill|drill\[p\.id\]|geo-drill|geo-marker-drill|geo-lab\.drill/.test(code),
  "no container (drill) implementation may remain anywhere");
assert(!/\br\.drill\b|\bL\.drill\b/.test(code), "no code may branch on a drill row any more");
assert(!/\.gi-drill|\.gl-drill/.test(html), "the container affordances must be gone from the CSS too");
ok("2/3. a territory tap SELECTS at every zoom, and no territory tap drills into a continent");

// ================= 4. continent labels are camera-only =================
const labels = build.slice(build.indexOf("markerSpecs.forEach(L => {"));
assert(/if \(L\.cont\) \{/.test(labels), "continent labels are a distinct kind of label");
const contBlock = labels.slice(labels.indexOf("if (L.cont) {"), labels.indexOf("} else {"));
assert(/focusBounds\(L\.bounds/.test(contBlock), "a continent label moves the camera");
for (const forbidden of ["drawGeo", "hudSelect", "openRegion", "groupFilter", "refreshMap"]) {
  assert(contBlock.indexOf(forbidden) === -1,
    "a continent label must not " + forbidden + " — it is a camera shortcut only");
}
assert(/role", "button"/.test(contBlock) && /tabindex", "0"/.test(contBlock) && /keydown/.test(contBlock),
  "the camera shortcut must be operable from a keyboard");
ok("4. a continent label only moves the camera: no mode, no selection, no redraw, no Back stack");

// ================= 5. the viewport owns its shape =================
assert(/holder\.style\.setProperty\("--vp-ratio", window\.innerWidth <= 560 \? "1\.1" : "1\.6"\);/.test(build),
  "the aspect ratio must come from the BREAKPOINT, never from geography");
assert(!/--vp-ratio[^\n]*(bbox|bounds|cont|x1 - x0)/.test(code),
  "no continent or bounding box may feed the viewport ratio");
assert(/svg\.setAttribute\("preserveAspectRatio", "xMidYMid meet"\);/.test(build),
  "the map keeps its own proportions inside the viewport");
assert(/aspect-ratio: var\(--vp-ratio/.test(html), "the viewport is sized by aspect-ratio");
assert(/width: min\(100%, calc\(var\(--vp-h/.test(html),
  "the height budget must cap the WIDTH, so a max-height cannot silently change the ratio");
ok("5. the viewport keeps one breakpoint-chosen aspect ratio; geography never reshapes the board");

// ================= 6/7. semantic zoom, and the selected label =================
assert(/holder\.dataset\.zoom = s < 2 \? "far" : \(s < 4\.2 \? "mid" : "near"\);/.test(build),
  "zoom bands must be derived from the camera scale");
assert(/\[data-zoom="far"\]/.test(html) && /\[data-zoom="mid"\]/.test(html),
  "the bands must drive presentation density in CSS");
assert(/L\.minZoom = Math\.max\(0, 46 \/ Math\.max\(6, restW\)\);/.test(labels),
  "territory labels are admitted as they become legible");
assert(/L\.priority = restW;/.test(labels),
  "...and are prioritised purely by how much room they have");
assert(/L\.maxZoom = 4\.2;/.test(contBlock),
  "continent labels step aside once the player is zoomed in");
const place = slice("function placeMapLabels", "\n  let hudSelKey", "placeMapLabels");
assert(/c\.selected \|\| \(zoom >= c\.minZoom && zoom <= c\.maxZoom\)/.test(place) &&
       /if \(c\.selected\) \{ c\.visible = true;/.test(place),
  "the selected territory's label must always be visible, whatever the zoom");
ok("6/7. one map with three densities; the selected label is always exempt from the zoom filter");

// ================= 8/9. the camera never touches game state =================
for (const forbidden of ["fetch(", "loadTerritory", "loadEconomy", "refreshMap", "drawGeo",
                         "claimTroops", "launchAttack", "hudSelect", "colorize"]) {
  assert(camera.indexOf(forbidden) === -1,
    "the camera must not " + forbidden + " — panning and zooming are render-only");
}
assert(/svg\.style\.transform = "translate\(/.test(camera),
  "camera movement is a CSS transform on the existing svg");
assert(/CAM_MIN|CAM_MAX|CAM_HOME|CAM_OVERSCROLL/.test(code), "the camera bounds must be named");
const camMax = +(code.match(/const CAM_MAX = ([\d.]+);/) || [])[1];
const camMin = +(code.match(/const CAM_MIN = ([\d.]+);/) || [])[1];
const camHome = +(code.match(/const CAM_HOME = ([\d.]+);/) || [])[1];
assert(camMin === 1 && camMax >= 8 && camHome > camMin && camHome < camMax,
  "min = the whole World, max = a usable island, home in between: " + [camMin, camHome, camMax]);
assert(/function clamp\(\)/.test(camera) && /CAM_OVERSCROLL/.test(camera),
  "pan must be bounded so the map cannot be dragged off-screen");
ok("8/9. pan/zoom mutates no game state, fetches nothing, and is bounded by named limits");

// ================= 10. selection assist is not a zoom change =================
const sel = slice("window.hudSelect = function (key)", "\n      const legend", "hudSelect");
assert(/geoOffScreen\(key\)\) geoFocusKey\(key, \{ keepZoom: true \}\)/.test(sel),
  "camera assist must only run for an off-screen territory, and must not change the zoom");
assert(/if \(key !== hudSelKey\) closeTray\(\);/.test(sel),
  "changing the selection must abandon a plan for the previous territory");
ok("10. selecting centres a territory only when it is off-screen, and never re-zooms");

// ================= 11/12/13. combat is in the board =================
const tray = slice("function renderTray()", "\n      function traySquad", "renderTray");
const confirm = slice("function trayConfirm()", "\n      function renderHudActions", "trayConfirm");
const actions = slice("function renderHudActions()", "\n      hudRefresh = function", "renderHudActions");
assert(/openTray\("attack"\)/.test(actions), "Attack must open the tray");
assert(!/openRegion/.test(actions), "no territory action may open the region modal");
assert(tray.indexOf("openModal") === -1 && confirm.indexOf("openModal") === -1,
  "attack planning must not open a modal");
assert(/HUD\.tray\.hidden = false;/.test(tray), "the tray is shown in place");
assert(/tray\.className = "hud-tray"/.test(code) && /wrap\.appendChild\(tray\)/.test(code),
  "the tray lives in the board's own container, below the viewport");
assert(/trayValidSources\(\)\.forEach\(sk => paint\(sk, "geo-src"\)\)/.test(drawGeo),
  "valid sources must be highlighted on the map");
assert(/paint\(hudSelKey, trayMode === "attack" \? "geo-tgt" : "geo-sel"\)/.test(drawGeo),
  "the target must be visually distinguishable from the sources");
assert(/function trayValidSources\(\) \{ return hudSelKey \? validAttackSources\(hudSelKey\) : \[\]; \}/.test(drawGeo),
  "the source list must come from the existing advisory helper, unchanged");
assert(/launchAttack\(src, key, name, h, squad\)/.test(confirm),
  "the attack must go through the existing launchAttack, with the captured source");
assert(/const key = hudSelKey, mode = trayMode, squad = traySquad\(\), src = traySrc;/.test(confirm),
  "the whole plan must be captured BEFORE closeTray() resets it");
assert(confirm.indexOf("traySrc") === confirm.lastIndexOf("traySrc"),
  "traySrc must be read exactly once, before the tray is torn down");
assert(/claimTroops\(key, squad, pop,/.test(confirm),
  "occupy and garrison must go through the existing claim endpoint");
ok("11/12/13. Attack/Occupy/Garrison are planned in an in-board tray with the map still visible, " +
   "target and sources are distinct, and the authoritative identities reach the same endpoints");

// ================= 14. the map is not an administration surface =================
for (const forbidden of ["Recruit", "openHomeBase", "buildingsPanel", "Research", "Buildings",
                         "openBuildingDetail", "Manage"]) {
  assert(actions.indexOf(forbidden) === -1,
    "the territory action row must not offer " + forbidden);
}
assert(/actBtn\("\\u\{1F3F0\}", "Empire", openEmpire/.test(actions),
  "management must be one link to Empire");
// Phase 12D: the per-territory modal is not merely free of management panels -- it does not exist.
[["openRegion", "the region modal"], ["renderAttackPanel", "the modal attack panel"],
 ["renderRequirementPanel", "the requirement panel"], ["regionLearningHTML", "the region learning block"],
 ["regionReopenFor", "the region reopen closure"], ["returnToRegion", "the region return"],
 ["offerStudyReturn", "the study-return button"], ["occupyLessonPlan", "the gated-occupy planner"],
 ["selectOccupyLesson", "the gated-occupy selector"], ["pendingOccupy", "the occupy transaction"],
 ["pendingStudy", "the study transaction"]].forEach(pair => {
  assert(!new RegExp("[^a-zA-Z_.$]" + pair[0] + "\\b").test(code),
    pair[1] + " (" + pair[0] + ") must be gone, not dormant");
});
ok("14. Recruit, Buildings, Research and the catch-all Manage are gone from territory interaction, " +
   "and the region modal they lived in no longer exists at all");

// ================= 15/16/17. Empire provides all three areas =================
const empire = slice("function renderEmpireModal()", "\n  function empireForces", "renderEmpireModal");
assert(/\["forces", "⚔️ Forces"\], \["buildings", "🏛️ Buildings"\], \["tech", "🏭 Technology"\]/.test(empire),
  "Empire must offer exactly Forces, Buildings and Technology");
assert(/role="tablist"/.test(empire) && /role="tab"/.test(empire) && /aria-selected/.test(empire),
  "the three areas must be a real tablist");
const forces = slice("function empireForces", "\n  function openRecruitFor", "empireForces");
assert(/TROOPS\.map\(t => '<th>' \+ troopIcon\(t\.id\)/.test(forces),
  "Forces must show the four real troop classes");
assert(/HOME_KEY/.test(forces) && /rows\.forEach/.test(forces),
  "Forces must list the home base and every owned territory");
assert(!/transfer|move troops between|Move ▸/i.test(forces.replace(/moving troops between territories is not[^']*/, "")),
  "Forces must not invent troop movement, which the server does not have");
assert(/moving troops between territories is not a rule the game has yet/.test(html),
  "...and must say so plainly instead of hiding it");
const blds = slice("function empireBuildings", "\n  function empireTechnology", "empireBuildings");
assert(/BUILD_COST\[b\.id\]/.test(blds) && /BUILDINGS\.map/.test(blds),
  "Buildings must use the real building list and the real costs");
assert(/buildingsPanel\(host, key, st\.h, reopen\)/.test(blds),
  "Buildings must reuse the existing panel, not a reimplementation");
const tech = slice("function empireTechnology", "\n  function openHomeBase", "empireTechnology");
assert(/TECH_COST\[k\]\[lvl\(k\)\]/.test(tech) && /TECH_MAX/.test(tech),
  "Technology must use the real costs and cap");
assert(/openBuildingDetail\(b\.dataset\.tech, "armory", reopen\)/.test(tech),
  "Technology must open the existing armory panel");
// Phase 12D sharpened this copy: because Technology now LIVES inside Empire, it has to say in one
// breath that it is managed centrally and still per-territory in authority, or the location implies
// pooling. Asserting the specific sentences is stricter than the old substring pair.
// The copy is built by string concatenation across source lines, so join those seams before matching
// -- otherwise a purely cosmetic re-wrap would fail an assertion about the WORDS.
const techText = tech.replace(/'\s*\+\s*\n?\s*'/g, "");
assert(/per territory/.test(techText) && /Armory <b>in that same territory<\/b>/.test(techText),
  "Technology must state its real, per-territory scope");
assert(/Managed here, but stored and effective per territory/.test(techText),
  "...and must not let its central LOCATION imply central authority");
assert(/does not pool it/.test(techText), "...saying plainly that research is not pooled");
assert(/arrives with no buildings and no technology/.test(techText) &&
       /research starts again/.test(techText),
  "...and that a conquered territory inherits nothing");
for (const invented of ["upkeep", "tech tax", "era", "research tree", "empire-wide bonus"]) {
  assert(tech.toLowerCase().indexOf(invented) === -1,
    "Technology must not invent " + invented + " — that is a balance decision, not an IA one");
}
ok("15/16/17. Empire provides Forces, Buildings and Technology, each built on the existing " +
   "authority, costs and caps — and Technology states the per-territory truth rather than implying " +
   "an empire-global model the server does not have");

// ================= 18. Holdings stays a summary =================
const holdings = slice("function renderHudPlayers()", "\n      function markMap", "renderHudPlayers");
for (const forbidden of ["button", "openEmpire", "openRegion", "buildingsPanel", "openTray",
                         "addEventListener"]) {
  assert(holdings.indexOf(forbidden) === -1,
    "Holdings must stay a read-only summary, not a second hub (" + forbidden + ")");
}
assert(/Holdings<\/div>/.test(holdings) && /hpl-n/.test(holdings),
  "Holdings still shows who holds how much");
ok("18. Holdings is a read-only summary with no controls — Empire is the only management hub");

// ============================================================================================
// ============== Phase 12D: legacy cleanup and interaction hardening =========================
// ============================================================================================

// ---- 19. camera + selection memory, and its boundaries ----
assert(/let geoView = null;/.test(code) && /function geoRememberView\(\)/.test(code),
  "the remembered board position must be a named, session-scoped value");
assert(!/localStorage[^\n]*geoView|geoView[^\n]*localStorage/.test(code),
  "a camera position must never be persisted — it is a view concern, not saved state");
assert(!/geoView[^\n]*(fetch|api\/)/.test(code), "...and must never be sent to the server");
const restoreBlk = slice("if (geoView && geoView.room === _room", "cam.home();", "restore");
assert(/geoView\.room === _room/.test(restoreBlk),
  "a remembered position may only be restored in the SAME room");
assert(/cam\.restore\(geoView\.s, geoView\.tx, geoView\.ty\)/.test(restoreBlk),
  "restoring must go through the camera, so the same clamp applies");
const camApi = slice("function restore(ns, ntx, nty)", "return { focusRect", "cam.restore");
assert(/Math\.max\(CAM_MIN, Math\.min\(CAM_MAX/.test(camApi) && /apply\(\)/.test(camApi),
  "a restored camera must be clamped and applied like any other move");
assert(/function clearActiveRoom\(\)[\s\S]{0,260}geoForgetView\(\)/.test(code),
  "changing room must forget the remembered position");
assert(/function clearAuth\(\)[\s\S]{0,360}geoForgetView\(\)/.test(code),
  "signing out must forget the remembered position");
ok("20. the remembered camera/selection is session-only, room-scoped, clamped on restore, never " +
   "persisted or sent anywhere, and forgotten on room change and logout");

// ---- 20. selection and camera stay independent ----
assert(camera.indexOf("hudSelKey") === -1 && camera.indexOf("hudSelect") === -1,
  "pan/zoom must not touch the selection");
assert(/geoOffScreen\(key\)\) geoFocusKey\(key, \{ keepZoom: true \}\)/.test(sel),
  "selecting must not change the zoom");
assert(contBlock.indexOf("hudSelKey") === -1 && contBlock.indexOf("hudSelect") === -1,
  "a continent shortcut must not touch the selection");
ok("21. pan, zoom and continent shortcuts never clear the selection, and selecting never re-zooms");

// ---- 21. the attack-plan lifecycle ----
const nav = slice('if (el !== screenArticle && !screenArticle.classList.contains("hidden"))',
                  "].forEach(s => s.classList.add", "showScreen guard");
assert(/geoRememberView\(\)/.test(nav) && /geoTrayClose\(\)/.test(nav),
  "leaving the board must remember the camera AND cancel the plan, in one place");
assert(/if \(key !== hudSelKey\) closeTray\(\);/.test(sel),
  "retargeting must cancel the previous plan");
assert(/function clearAuth\(\)[\s\S]{0,360}geoTrayClose\(\)/.test(code),
  "signing out must cancel the plan");
assert(/const key = hudSelKey, mode = trayMode, squad = traySquad\(\), src = traySrc;/.test(confirm),
  "the plan must be captured before teardown (the 12C source_not_found bug)");
assert(confirm.indexOf("traySrc") === confirm.lastIndexOf("traySrc"), "...and read exactly once");
ok("22. a plan dies with the board: navigation, retargeting and logout all cancel it, and no stale " +
   "source/target id can be confirmed");

// ---- 22. the Region index selects; it opens nothing ----
const rindex = slice('const idx = document.createElement("div"); idx.className = "geo-index";',
                     "const drawer = document.createElement", "region index");
assert(/window\.hudSelect\(r\.key\)/.test(rindex) && /geoFocusKey\(r\.key/.test(rindex),
  "a directory row must select the territory and point the camera at it");
for (const forbidden of ["r.open", "openRegion", "openModal", "drawGeo", "groupFilter", "drill"]) {
  assert(rindex.indexOf(forbidden) === -1,
    "a directory row must not " + forbidden + " — it is a selection shortcut, not a container");
}
assert(!/mouseenter[^\n]*hudSelect/.test(rindex),
  "hovering the directory must not mutate the selection");
assert(/setAttribute\("aria-label", btn\.title\)/.test(rindex),
  "every row needs an accessible name saying what it does");
ok("23. the Region index selects and centres — the one surviving route into the old modal is gone, " +
   "and hovering no longer mutates the selection");

// ---- 23. camera shortcut and control wording ----
assert(/Jump the camera to/.test(contBlock), "a continent shortcut must say it moves the camera");
assert(!/(Enter|Go into|Back to) (Europe|Asia|Africa|Oceania|the continent)/i.test(html),
  "no container wording may survive");
const camBar = slice("const camBar = document.createElement", "holder.appendChild(camBar)", "camera controls");
assert(/Zoom in/.test(camBar) && /Zoom out/.test(camBar) && /whole World/.test(camBar),
  "the visible controls are zoom in, zoom out and camera-home");
assert(/setAttribute\("aria-label", spec\[1\]\)/.test(camBar) && /b\.title = spec\[1\]/.test(camBar),
  "...each with an accessible name");
assert(/\.geo-cam button:focus-visible/.test(html), "...and a visible focus ring");
assert(/zoomBy/.test(camBar) && /cam\.home\(\)/.test(camBar),
  "the controls must drive the SAME camera as wheel/pinch/drag");
ok("24. one navigation mechanism: zoom in / zoom out / jump-to-World, all on the same camera, all " +
   "keyboard-reachable with visible focus, and no container wording anywhere");

// ---- 24. highlights do not depend on colour alone ----
assert(/\.geo-region\.geo-src[^}]*stroke-dasharray: 5 3/.test(html),
  "a valid attack source must be distinguishable without colour");
assert(/\.geo-region\.geo-tgt[^}]*stroke-dasharray: none/.test(html),
  "...and the target must differ from it in that same non-colour channel");
assert(/solid outline/.test(code) && /dashed outline/.test(code),
  "the tray must name the two roles in words as well");
assert(/\.geo-region\.geo-sel[^}]*stroke: #fff/.test(html),
  "a plain selection still has its own outline");
ok("25. attack target and source differ by outline STYLE, not only colour, and the tray says which " +
   "is which in words");

// ---- 25. Empire is the only management hub ----
const hudCtrls = slice("function renderHudControls", "function renderHudCard", "renderHudControls");
assert(/openEmpire/.test(hudCtrls), "the HUD must reach Empire");
for (const gone of ["openHomeBase", "Recruit", "Research", "Manage"]) {
  assert(hudCtrls.indexOf(gone) === -1, "the HUD must not offer a competing hub: " + gone);
}
assert(/function openHomeBase\(\)/.test(code) && /buildingsPanel\(host, HOME_KEY/.test(code),
  "the home-base PANEL survives, because Empire opens it — only the competing route is gone");
assert(/function endChallengeIfUnsatisfied\(\) \{/.test(code) &&
       !/endChallengeIfUnsatisfied\(\) \{[\s\S]{0,80}pendingOccupy/.test(code),
  "the lesson-scoped transaction hook must be an explicit no-op, not a dangling assignment");
ok("26. one management hub: Empire. The Base route is gone while the panel it used to own is still " +
   "the one Empire opens, and no removed identifier is left assigned anywhere");

// ================= extra: nothing authoritative was rewritten =================
assert(/const TROOPS = \[/.test(code) && /{ id: "cav",/.test(code) && /{ id: "spear",/.test(code),
  "the troop classes are untouched");
assert(/const BUILD_COST = \{ armory: 50, barracks: 60, archery: 80, stable: 120 \};/.test(code),
  "BUILD_COST is untouched");
assert(/const TECH_COST = \{ atk: \[160, 320, 560\], def: \[160, 320, 560\] \};/.test(code) &&
       /const TECH_MAX = 3;/.test(code), "TECH_COST and TECH_MAX are untouched");
assert(/function validAttackSources\(targetKey\)/.test(code) &&
       /adjacentTerritoryIds/.test(slice("function validAttackSources", "function launchAttack", "sources")),
  "attack adjacency still comes from the catalog");
assert(/\/api\/territory\/attack/.test(code) && /\/api\/territory\/claim/.test(code) &&
       /\/api\/territory\/reentry/.test(code) && /\/api\/territory\/research/.test(code),
  "every conquest endpoint is still the one the server owns");
assert(/function renderReentry\(st\)/.test(code) && /if \(!st \|\| !st\.available\)/.test(code),
  "re-entry is still entirely server-offered");
ok("19. troop classes, build/tech costs, adjacency-derived sources, every conquest endpoint and the " +
   "server-offered re-entry panel are all unchanged");

console.log("\nAll " + passed + " World-camera / Empire-IA checks passed.");
