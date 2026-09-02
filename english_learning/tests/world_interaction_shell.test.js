// Phase 13C.1 — the World is a fixed interaction shell, not a page that grows downward.
//
//   node tests/world_interaction_shell.test.js
//
// THE DEFECT THIS PHASE REMOVED, measured in real Chrome before any edit:
//
//   viewport    document overflow   territory card    primary action
//   1440x900    210 px              in fold           borderline; below the fold once the action
//                                                     bar wrapped to a second line
//   1024x768    278 px              BELOW THE FOLD    BELOW THE FOLD
//   768x1024    131 px              in fold           in fold
//   360x780     149 px (+3 px H)    in fold           in fold
//
// The cause was structural: the HUD grid put the territory card, its action bar and the Holdings
// list in a THIRD row underneath the board, with the attack tray underneath that again. Occupying a
// territory at 1024x768 therefore began with a scroll.
//
// What is pinned here is the ARCHITECTURE — three layers, one inspector, one planner, nothing
// managerial on the board, and a projection that is still the single 13C authority. The geometry
// itself (shell fits the viewport, primary action in the fold, map stays dominant, 0 horizontal
// overflow) is measured end to end in real Chrome by scratchpad/audit_131.js and accept_131.js,
// because a rect is not something a source-string test can honestly claim.
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
// `code` drops whole-line // comments so that prose describing a rule can never satisfy a scan for
// the rule itself. (This project has been bitten by that before.)
const code = html.replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\//g, "")
                 .replace(/^[ \t]*\/\/.*$/gm, "");
const css = (html.match(/<style>([\s\S]*?)<\/style>/) || [, ""])[1];

let passed = 0;
function ok(name) { passed++; console.log("  ok -", name); }
function slice(from, to, label) {
  const i = code.indexOf(from);
  assert(i > 0, "not found: " + (label || from));
  const j = code.indexOf(to, i + from.length);
  assert(j > i, "end marker not found for " + (label || from));
  return code.slice(i, j);
}
// a CSS rule body, by selector
function rule(sel) {
  const i = css.indexOf(sel);
  assert(i >= 0, "css selector not found: " + sel);
  const open = css.indexOf("{", i);
  const close = css.indexOf("}", open);
  return css.slice(open + 1, close);
}

const buildHud = slice("function buildHud()", "\n      const HUD = buildHud", "buildHud");
const actions = slice("function renderHudActions()", "\n      hudRefresh = function", "renderHudActions");
const drawGeo = slice("function drawGeo", "\n  function selectLevel", "drawGeo");

// ============================ 1. one map workspace, one territory inspector ============================
assert(/grid\.className = "hud-grid"/.test(buildHud), "the shell is the hud-grid");
assert((buildHud.match(/className = "hud-map"/g) || []).length === 1,
  "exactly one map workspace");
assert((buildHud.match(/className = "hud-side"/g) || []).length === 1,
  "exactly one territory inspector");
assert((buildHud.match(/className = "hud-chrome"/g) || []).length === 1,
  "exactly one chrome strip");
// three layers and no fourth: the retired bottom-row slots must not come back
["hud-bl", "hud-bar", "hud-br"].forEach(dead => {
  assert(code.indexOf('"' + dead + '"') === -1,
    "the retired bottom HUD row slot " + dead + " must not be recreated");
});
assert(/\[chrome, mapSlot, side\]\.forEach/.test(buildHud),
  "the shell has exactly three regions: chrome, map, inspector");
ok("1. World has one chrome strip, one map workspace and one territory inspector — no fourth surface");

// ============================ 2. the inspector is shell-bound ============================
const grid = rule(".hud-grid {");
assert(/grid-template-rows:\s*auto minmax\(0, 1fr\)/.test(grid),
  "the shell is chrome + a workspace row that absorbs the remaining height");
assert(/height:\s*var\(--shell-h/.test(grid),
  "the shell takes an explicit height so it cannot grow past the viewport");
const side = rule(".hud-side {");
assert(/grid-area:\s*2 \/ 2 \/ 3 \/ 3/.test(side),
  "the inspector shares the WORKSPACE row with the map — it is not a row below the board");
assert(/min-height:\s*0/.test(side),
  "min-height:0 is what stops inspector content dictating the workspace height");
assert(/overflow-y:\s*auto/.test(side),
  "an over-full inspector scrolls internally instead of moving the map");
const mapCell = rule(".hud-map {");
assert(/min-height:\s*0/.test(mapCell) && /min-width:\s*0/.test(mapCell),
  "the map cell may shrink in both axes rather than push the shell open");
assert(/aspect-ratio:\s*auto/.test(rule(".hud-mode .hud-map > .geo-holder.geo-viewport {")),
  "the map viewport fills the workspace cell rather than holding a fixed ratio");
ok("2. the inspector is bound to the workspace row beside the map, and scrolls itself when full");

// ============================ 3. stacked shell becomes a bottom sheet ============================
const sheetBlock = css.slice(css.indexOf("@media (max-width: 899px)"),
                             css.indexOf("@media (max-width: 899px)") + 1600);
assert(/grid-template-columns:\s*minmax\(0, 1fr\)/.test(sheetBlock),
  "the stacked shell is ONE column — not a narrow right rail squeezed onto a phone");
// The map row carries a FLOOR. Without one a tall sheet could squeeze the map away; and the sheet
// row must stay `auto` so the row and the sheet agree on a height -- a percentage cap here shrank
// the sheet inside a larger row, which clipped the action buttons and left a 187 px hole.
assert(/grid-template-rows:\s*auto minmax\(\d+px, 1fr\) auto/.test(sheetBlock),
  "stacked order is chrome, map (with a floor), then the territory sheet");
assert(/\.hud-side\s*\{[^}]*grid-area:\s*3 \/ 1 \/ 4 \/ 2/.test(sheetBlock),
  "the inspector moves BELOW the map when stacked");
// the cap is a SAFETY VALVE in viewport units, deliberately larger than ordinary sheet content,
// and what actually gets bounded is the card's numeric detail strip -- never its identity, its
// strategic line or its actions.
assert(/\.hud-side\s*\{[^}]*max-height:\s*\d+dvh/.test(sheetBlock),
  "the sheet cap is expressed in viewport units, not as a percentage of its own row");
assert(/\.hc-rows\s*\{[^}]*max-height:\s*\d+px[^}]*overflow-y:\s*auto/.test(sheetBlock),
  "only the numeric detail rows are bounded on the stacked shell");
assert(!/\.hud-side\s*\{[^}]*max-height:\s*\d+%/.test(sheetBlock),
  "the sheet must not be capped by a percentage of its own grid row (that is what clipped it)");
ok("3. below the landscape breakpoint the inspector becomes a full-width bottom sheet, height-capped");

// ============================ 4/5. Occupy and Attack come from selection state ============================
assert(/const h = key && territory && territory\.holders \? territory\.holders\[key\] : null;/.test(actions),
  "the action is chosen from the authoritative holders map, not from local state");
assert(/openTray\("occupy"\)/.test(actions), "Occupy is offered from the inspector");
assert(/openTray\("attack"\)/.test(actions), "Attack is offered from the inspector");
// Phase 13C.2: the empty state returns EARLY and renders no buttons at all, so the ownership
// branches are no longer an `else if` chain hanging off it. The behaviour pinned is the same --
// enemy gets Attack, unheld gets Occupy -- and the empty state is now pinned as showing NO action
// furniture, which is a stronger statement than "a disabled prompt".
assert(/if \(enemy\) \{[\s\S]*?openTray\("attack"\)/.test(actions),
  "Attack is the action for an ENEMY-held territory");
assert(/} else \{[\s\S]*?openTray\("occupy"\)/.test(actions),
  "Occupy is the action for an unheld territory");
assert(/if \(!key\) \{[\s\S]*?HUD\.acts\.hidden = true;[\s\S]*?return;/.test(actions),
  "with nothing selected the inspector renders NO action buttons, not a disabled placeholder");
assert(actions.indexOf("disabled: true") === -1,
  "no disabled placeholder button may be kept merely for layout symmetry");
ok("4/5. Occupy and Attack are rendered from the selected territory's authoritative ownership");

// ============================ 6. selection mutates nothing ============================
const sel = slice("window.hudSelect = function (key)", "\n      const legend", "hudSelect");
["claimTroops", "launchAttack", "fetch(", "/api/territory/claim", "/api/territory/attack"].forEach(m => {
  assert(sel.indexOf(m) === -1, "selecting a territory must not " + m);
});
assert(/hudSelKey = key;/.test(sel) && /renderHudCard\(\); renderHudActions\(\);/.test(sel),
  "selection sets the view state and redraws the inspector, and that is all");
ok("6. selection is a view change: no claim, no attack, no fetch");

// ============================ 7. no right-click / hover-only primary action ============================
["contextmenu", "oncontextmenu"].forEach(bad => {
  assert(code.indexOf(bad) === -1, "no " + bad + " handler may exist anywhere in the client");
});
assert(!/addEventListener\("mouseenter",[^)]*hudSelect/.test(code),
  "hover must not select a territory");
assert(!/addEventListener\("mouseover",[^)]*openTray/.test(code),
  "hover must not open the action planner");
assert(!/addEventListener\("dblclick",[^)]*openTray/.test(code),
  "the planner must not need a double click");
ok("7. no contextmenu, no hover-only and no double-click-only route to a primary action");

// ============================ 8. no region modal resurrection ============================
["openRegion", "regionModal", "openTerritoryModal"].forEach(dead => {
  assert(code.indexOf(dead) === -1, dead + " must not exist");
});
assert(actions.indexOf("openModal") === -1, "no territory action may open a modal");
// Phase 14A.1: planning IS a modal now -- see the note in world_camera.test.js. The rule that
// mattered is that no TERRITORY ACTION opens a modal to be discovered (asserted just above, on
// renderHudActions) and that the retired region modal stays retired.
const trayFn = slice("function renderTray()", "\n      function trayBindClose", "renderTray");
assert(/openModal\(html\)/.test(trayFn),
  "planning opens the shared action modal");
assert(trayFn.indexOf("openRegion") === -1, "and never the retired region modal");
ok("8. the retired region modal stays retired — no openRegion, no per-territory modal");

// ============================ 9. no management controls in the inspector ============================
["Recruit", "recruitTroops", "openHomeBase", "buildingsPanel", "openBuildingDetail",
 "Research", "Buildings", "Technology", "Manage", "transferTroops"].forEach(forbidden => {
  assert(actions.indexOf(forbidden) === -1,
    "the territory inspector must not offer " + forbidden);
});
assert(buildHud.indexOf("Recruit") === -1 && buildHud.indexOf("Buildings") === -1,
  "the inspector's structure must not host management panels either");
ok("9. Recruit / Buildings / Technology / transfer are absent from the territory inspector");

// ============================ 10. exactly one attack planner ============================
// Phase 14A.1: the planner is no longer a persistent element inside the inspector -- Alpha play
// showed a narrow rail is the wrong workspace for a four-class military decision. It is built into
// the shared action modal on demand. "Exactly one planner" is still the rule and is still pinned;
// the inspector is additionally pinned to hold NO planner element, which it could not be before.
assert((code.match(/function renderTray\(\)/g) || []).length === 1,
  "exactly one planning surface exists");
assert(buildHud.indexOf("hud-tray") === -1 && buildHud.indexOf("hudTray") === -1,
  "the inspector holds no planner element at all");
assert(code.indexOf('id = "hudTray"') === -1,
  "and no dormant tray element is left anywhere");
assert(/hudSlot\("hud-card"\)/.test(buildHud) && /hudSlot\("hud-actions"\)/.test(buildHud) &&
       /hudSlot\("hud-facts"\)/.test(buildHud),
  "the inspector still owns identity, the action choice and the detail");
ok("10. one planning surface, in a dedicated action modal — no duplicate attack UI, and no " +
   "dormant planner left in the inspector");

// ============================ 11. re-entry keeps its confirmation ============================
// Re-entry's confirmation is not window.confirm(): it is a deliberate TWO-STEP surface, retained
// from 12D. The inspector's Foothold action only points at the panel; a candidate opens a modal
// that states the gold cost and the unknown garrison; and only an explicit go button POSTs.
const reentry = slice("function renderReentry", "\n      function loadReentry", "renderReentry");
const reOpen = code.slice(code.indexOf("function openReentry"),
  code.indexOf("function openReentry") + 4000);
assert(/b\.addEventListener\("click", \(\) => openReentry\(c, st\)\);/.test(reentry),
  "a re-entry candidate opens the confirmation surface rather than acting immediately");
assert(reentry.indexOf("/api/territory/reentry") === -1,
  "listing candidates must never POST re-entry");
assert(/openModal/.test(reOpen), "the confirmation is an explicit modal, deliberately kept");
assert(/costs .*gold|cost\.gold/.test(reOpen), "the confirmation states the gold cost up front");
assert(/onGo:/.test(reOpen) && /Re-enter/.test(reOpen),
  "only an explicit Re-enter action performs the mutation");
assert(/method: "POST"/.test(reOpen), "and that action is what POSTs");
assert(actions.indexOf("/api/territory/reentry") === -1,
  "the inspector must not call the re-entry endpoint directly");
assert(/Foothold/.test(actions) && /reWrap\.scrollIntoView/.test(actions),
  "the inspector only points at the re-entry panel");
ok("11. re-entry keeps its cost statement and its explicit confirmation");

// ============================ 12. camera code does not rebuild the shell ============================
const camOnChange = slice("const cam = attachPanZoom(svg, holder, (s, tx, ty) => {",
  "\n      geoCam = cam;", "camera onChange");
["buildHud", "hud-grid", "innerHTML", "appendChild", "fitShell"].forEach(bad => {
  assert(camOnChange.indexOf(bad) === -1,
    "a camera update must not " + bad + " — that would rebuild the shell every frame");
});
const relayout = slice("relayoutLabels = function (s, tx, ty)", "\n      _geoResel = function",
  "relayoutLabels");
["innerHTML", "appendChild", "createElement", "getBBox("].forEach(bad => {
  assert(relayout.indexOf(bad) === -1, "a camera update must not " + bad);
});
ok("12. camera movement repositions labels only — it never rebuilds the shell or the map");

// ============================ 13. the 13C projection authority is intact ============================
assert((code.match(/getScreenCTM\(\)/g) || []).length === 1,
  "there must be exactly one map->screen projection authority");
assert(/const projX = \(x, y\) => CTM\.a \* x \+ CTM\.c \* y \+ CTM\.e - CTMox;/.test(code),
  "labels are projected through the browser's own matrix");
assert(!/PK\s*\*\s*s\b/.test(code), "no manual camera scale multiplication for labels");
assert(!/(POX|POY)\s*\+\s*t[xy]\b/.test(code), "no manual tx/ty label transform");
const geom = slice("function captureGeom()", "\n      let CTM = null", "captureGeom");
assert(/holder\.clientWidth/.test(geom) && geom.indexOf("getBoundingClientRect") === -1,
  "the layout basis still comes from the untransformed client box");
// the shell's own sizing must be layout, not camera
const fit = slice("function fitShell()", "\n      fitShell();", "fitShell");
["cam.", "CTM", "labelState", "projX", "projY"].forEach(bad => {
  assert(fit.indexOf(bad) === -1, "fitShell must not read the camera or the projection (" + bad + ")");
});
assert(/window\.innerHeight/.test(fit), "fitShell measures the viewport, which is a layout fact");
ok("13. one projection authority, untouched; the shell's height is layout and never camera");

// ============================ 14. re-clamp goes through the camera authority ============================
const reshell = slice("_geoReshell = function ()", "\n      const _room =", "_geoReshell");
assert(/cam\.restore\(st\.s, st\.tx, st\.ty\)/.test(reshell),
  "a viewport change re-clamps through cam.restore(), the existing authority");
assert(!/CAM_OVERSCROLL|Math\.min\(slack/.test(reshell),
  "no second clamp calculation may exist outside attachPanZoom");
ok("14. resizing re-clamps the camera through cam.restore() — no second bounds calculation");

// ============================ 15. primary controls are independent of the Region index ============================
// The index and the other reference rows are siblings of the shell, in normal flow BELOW it, so
// their height is structurally incapable of moving anything inside the shell.
assert(/wrap\.insertBefore\(grid, wrap\.firstChild\)/.test(buildHud),
  "the shell is the FIRST child of the board container");
assert(/const below = document\.createElement\("div"\); below\.className = "hud-below";/.test(buildHud) &&
       /wrap\.appendChild\(below\)/.test(buildHud),
  "secondary reference content is appended after the shell, not inside it");
assert(!/side\.appendChild\(below\)/.test(buildHud) && !/grid\.appendChild\(below\)/.test(buildHud),
  "the Region index must never live inside the shell");
assert(/geo-idx/.test(code), "the Region index itself is retained, not deleted");
assert(!/openRegion/.test(code), "and it still does not open a modal");
ok("15. the Region index is retained BELOW the shell — primary actions cannot be pushed off screen");

// ============================ 16. mobile overflow + Empire boundary ============================
const phone = css.slice(css.indexOf("@media (max-width: 560px)"));
assert(/\.hud-tr\s*\{[^}]*min-width:\s*0/.test(phone),
  "the phone chrome cluster must be allowed to shrink — its natural width overflowed 360px by 3px");
assert(/\.hud-plaque\.hud-ctrls\s*\{[^}]*max-width:\s*100%/.test(phone),
  "the control cluster is bounded by its column on a phone");
const controls = slice("function renderHudControls()", "\n      function renderHudCard", "renderHudControls");
assert((controls.match(/openEmpire/g) || []).length === 1,
  "Empire is reachable from the World chrome");
assert(actions.indexOf("openEmpire") === -1,
  "and it is NOT duplicated inside the territory inspector");
assert(/Empire \\u2014 forces, buildings & technology/.test(controls),
  "the Empire launcher still says what it is for");
// Empire still owns all four management areas, pinned at their own tab table rather than by a bare
// substring search (which any comment would have satisfied).
const empTabs = slice("const TABS = [", "];", "Empire TABS");
["overview", "forces", "buildings", "tech"].forEach(area => {
  assert(empTabs.indexOf('"' + area + '"') > 0, "Empire must still own the " + area + " area");
});
// the tech branch is a bare `else`, so pin the four RENDERERS rather than four tab comparisons
assert(/empireOverview\(/.test(code) && /empireForces\(/.test(code) &&
       /empireBuildings\(/.test(code) && /empireTechnology\(/.test(code),
  "each Empire area still has its own renderer");
["empireForces", "empireBuildings"].forEach(fn => {
  assert(actions.indexOf(fn) === -1, "the territory inspector must not call " + fn);
});
ok("16. no phone overflow, and Empire remains the single management destination");

// ==================================================================================================
// ============================ Phase 13C.2: ownership and hierarchy ================================
// ==================================================================================================
const controls2 = slice("function renderHudControls()", "\n      function renderHudCard", "renderHudControls");
const card2 = slice("function renderHudCard()", "\n      function markMap", "renderHudCard");

// ---- 17. Boss is not owned by the selected territory ----
// Audited before moving: startLevelExam takes a CURRICULUM level index, its army comes from
// bossArmyFor(lv.id), its questions from that level, and its pass flag is local
// `exam:<user>:<levelId>` state the server has never heard of. None of it changes when the
// selection changes, so it cannot belong to the territory inspector.
assert(actions.indexOf("startLevelExam") === -1,
  "the Boss checkpoint must not be a territory action");
assert(actions.indexOf("examPassed") === -1,
  "the inspector must not read checkpoint state either");
// It lives on the BOARD IDENTITY plaque rather than in the destination-icon cluster: a seventh
// icon there wrapped the cluster to three rows and cost 49 px of chrome at 1024 (measured), and the
// checkpoint belongs with the board's own identity rather than with the generic destinations.
const boss2 = slice("function renderHudBoss()", "\n      function renderHudTitle", "renderHudBoss");
assert(/HUD\.ti\.appendChild/.test(boss2),
  "the Boss checkpoint is rendered into the World chrome identity plaque");
assert(boss2.indexOf("HUD.acts") === -1,
  "and never into the territory action row");
assert((code.match(/startLevelExam\(i\)/g) || []).length === 1,
  "exactly ONE Boss control exists on the board");
assert(code.indexOf("geo-boss-btn") === -1,
  "the duplicate below-the-board Boss button is retired");
// placement only: the call, its condition and its state are untouched
assert(/if \(backFn \|\| !lv\) return;/.test(boss2),
  "Boss eligibility is unchanged: a curriculum level opened this board");
assert(/examPassed\(lv\.id\)/.test(boss2), "it still reads the same pass flag");
assert(/Level checkpoint battle for/.test(boss2),
  "its accessible name says LEVEL checkpoint and names the LEVEL, never a territory");
assert(/startLevelExam\(i\)/.test(boss2),
  "it still calls exactly the same entry point -- placement only");
assert(controls2.indexOf("startLevelExam") === -1,
  "it is not duplicated among the destination icons");
ok("17. Boss is a World-chrome curriculum checkpoint: one control, not a territory action");

// ---- 18. Holdings is not a territory fact ----
assert(code.indexOf("renderHudPlayers") === -1 && code.indexOf("hud-players") === -1,
  "the per-owner Holdings plaque must not live in the territory inspector");
assert(/owners.innerHTML = present/.test(code),
  "the board scoreboard survives below the board");
assert(/<small>Territories<\/small>/.test(code),
  "Empire Overview still owns the player's own territory total");
assert(/Territories you hold/.test(code),
  "the World chrome keeps one compact count of the player's own territories");
ok("18. Holdings is board-global: it left the inspector, the scoreboard and Empire keep it");

// ---- 19. the inspector reads identity, then ACTION, then detail ----
const buildOrder = buildHud.indexOf('hudSlot("hud-card")') < buildHud.indexOf('hudSlot("hud-actions")') &&
                   buildHud.indexOf('hudSlot("hud-actions")') < buildHud.indexOf('hudSlot("hud-facts")');
assert(buildOrder,
  "the inspector is built identity -> actions -> facts, so the action precedes the numbers");
assert(/HUD.facts.innerHTML/.test(card2),
  "the numeric rows are written to the facts block, below the action");
// The identity card must render only the name, the status badge and the qualitative role; the
// numeric rows belong to the facts block below the action. Compare the two ASSIGNMENTS rather
// than the whole function, which legitimately builds the rows string earlier. lastIndexOf skips
// the empty-state branch, which writes both elements first.
const cardAssign = card2.slice(card2.lastIndexOf("HUD.card.innerHTML"),
                               card2.lastIndexOf("HUD.facts.innerHTML"));
const factsAssign = card2.slice(card2.lastIndexOf("HUD.facts.innerHTML"));
assert(cardAssign.length > 0 && factsAssign.length > 0, "both inspector blocks are written");
["Population", "Neighbours", "Armies", "hc-rows"].forEach(numeric => {
  assert(cardAssign.indexOf(numeric) === -1,
    numeric + " must not be rendered into the identity card");
});
assert(/hc-rows/.test(factsAssign),
  "the numeric rows are rendered into the facts block, below the action");
assert(/hc-strat/.test(card2),
  "the strategic role stays with identity, so it survives on the compact mobile sheet");
ok("19. identity and the primary action outrank the numeric detail");

// ---- 20. Centre is camera-only, and quieter than a gameplay action ----
assert(/quiet: true/.test(actions) && /geoFocusKey\(key/.test(actions),
  "Centre is a camera move, rendered as a quiet action");
const centre = actions.slice(actions.indexOf('"Centre"'), actions.indexOf('"Centre"') + 400);
["claimTroops", "launchAttack", "openTray", "openRegion", "openModal"].forEach(bad => {
  assert(centre.indexOf(bad) === -1, "Centre must not " + bad);
});
assert(/ha-quiet/.test(css), "the quiet variant is a real, weaker visual treatment");
assert(/ha-primary/.test(actions) === false || /primary: true/.test(actions),
  "only Occupy and Attack carry the primary treatment");
ok("20. Centre moves the camera only, and is visually subordinate to Occupy/Attack");

// ---- 21. the product identity survives the phone chrome ----
const phone2 = css.slice(css.indexOf("@media (max-width: 560px)"));
assert(/WORLD CONQUEST/.test(html), "the product identity is present");
assert(!/\.ht-t[^{]*\{[^}]*display:\s*none/.test(phone2),
  "the phone must not hide the product title");
assert(/\.hud-tr\s*\{[^}]*grid-row:\s*2/.test(phone2),
  "the control cluster moves to its own line so the title gets the full width");
assert(/\.hud-title\s\.ht-t\s*\{[^}]*clamp\(/.test(phone2),
  "the title is responsively sized rather than clipped");
assert(html.indexOf("English Reading") === -1 || !/ht-t/.test(html.slice(html.indexOf("English Reading") - 200,
  html.indexOf("English Reading") + 200)),
  "the top-level product identity is not renamed back to the old course name");
ok("21. WORLD CONQUEST keeps a readable line of its own on a phone");

// ==================================================================================================
// ============================ Phase 14A: global conquest (v0.1 Alpha) =============================
// ==================================================================================================
const sources = slice("function validAttackSources(targetKey)", "\n  function launchAttack",
  "validAttackSources");
// ---- 22. sources are ownership, not geography ----
assert(/territory\.holders/.test(sources),
  "attack sources come from the authoritative holders map");
assert(sources.indexOf("adjacentTerritoryIds") === -1,
  "Alpha rule: sources are no longer filtered by adjacency");
assert(/k === targetKey/.test(sources), "a territory still cannot attack itself");
assert(/sumHp\(h\.troops\) > 0/.test(sources), "a source still needs a garrison");
["getBBox", "getBoundingClientRect", "clientX", "elementFromPoint"].forEach(px => {
  assert(sources.indexOf(px) === -1, "sources must never be derived from pixels (" + px + ")");
});
// a degree-0 owned territory is reachable by this rule: nothing consults neighbour counts
assert(sources.indexOf("adjacent") === -1 && sources.indexOf("degree") === -1,
  "no geographic term may appear in the source derivation at all");
ok("22. attack sources are every garrisoned territory you own -- ownership, never geography");

// ---- 23. the copy no longer promises an adjacency rule ----
["No adjacent territory", "cannot be reached by land", "cannot attack out",
 "from an adjacent territory you own"].forEach(stale => {
  assert(code.indexOf(stale) === -1,
    "retired Alpha-false copy must not return: " + JSON.stringify(stale));
});
assert(/from any territory you own/.test(actions),
  "the Attack action says an attack may march from any territory you own");
ok("23. no surviving copy tells the player that geography limits conquest");

// ---- 24. the Alpha rule is explained once, in a secondary surface ----
const rules = slice('rules.className = "hd-drawer geo-rules"', "\n      HUD.below.appendChild(rules)",
  "rules surface");
assert(/How conquest works/.test(code), "there is a short rules surface");
assert(/anywhere in the world/.test(rules), "it states the Alpha rule in player words");
assert(/v0\.1 Alpha rule/.test(rules), "and says plainly that it is an Alpha rule");
["adjacency", "degree-0", "connected component", "adjacencyGraph"].forEach(jargon => {
  assert(rules.indexOf(jargon) === -1,
    "the rules copy must not expose implementation terminology (" + jargon + ")");
});
assert(/HUD\.below\.appendChild\(rules\)/.test(code),
  "it lives BELOW the shell, so it cannot push a primary action off screen");
assert(rules.indexOf("openModal") === -1, "and it is not a modal");
ok("24. one short rules surface explains the Alpha rule, below the shell, in player words");

console.log("\nAll " + passed + " World-interaction-shell checks passed.");
