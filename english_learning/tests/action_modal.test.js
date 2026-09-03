// Phase 14A.1 — the conquest ACTION MODAL and its fast troop picker.
//
//   node tests/action_modal.test.js
//
// WHY THIS EXISTS. Real Alpha play found two concrete problems with planning inside the fixed
// Territory Inspector:
//
//   A  the troop controls and the commit button fell below the narrow rail's own viewport, so the
//      player had to scroll a ~300 px column to deploy troops;
//   B  the only controls were +1 / -1, so deploying 200 troops meant about 200 clicks.
//
// The planner is now a dedicated action modal with a numeric field, per-class MAX and 25/50/75/MAX
// quick deploy. This file pins the picker's ARITHMETIC by executing the shipped setter and the
// shipped quick-deploy function, and pins the surrounding architecture structurally. Rects and
// real typing are measured in real Chrome by scratchpad/accept_141.js — a source test cannot
// honestly claim a pixel.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
// prose that NAMES a rule must never satisfy a scan for the rule itself
const code = html.split(/\r?\n/).map(L => L.replace(/^\s*\/\/.*$/, "")).join("\n");
const css = (html.match(/<style>([\s\S]*?)<\/style>/) || [, ""])[1];

let passed = 0;
function ok(n) { passed++; console.log("  ok -", n); }
function slice(from, to, label) {
  const i = code.indexOf(from);
  assert.ok(i > 0, "not found: " + (label || from));
  const j = code.indexOf(to, i + from.length);
  assert.ok(j > i, "end marker not found for " + (label || from));
  return code.slice(i, j);
}

const render = slice("function renderTray()", "\n      function trayBindClose", "renderTray");
const buildHud = slice("function buildHud()", "\n      const HUD = buildHud", "buildHud");
const confirm = slice("function trayConfirm()", "\n      function renderHudActions", "trayConfirm");

// ============================================================================================
// EXECUTED: the picker arithmetic, from the shipped source
// ============================================================================================
// traySet / trayTotal / trayQuick are extracted and run against a controlled budget. This is the
// arithmetic the +/- buttons, the numeric field, per-class MAX and the quick row all share.
const setterSrc = slice("function traySet(ty, raw)", "\n      function renderTray", "picker maths");
const FACTORY = vm.runInNewContext(
  "(function (TROOPS, budget) {\n" +
  "  var trayAmt = {};\n" +
  "  function trayBudget() { return budget; }\n" + setterSrc +
  "\n  return { set: traySet, total: trayTotal, quick: trayQuick,\n" +
  "           amt: function () { return trayAmt; } };\n})",
  { Math: Math, Number: Number, isFinite: isFinite });

const CLASSES = [{ id: "cav" }, { id: "archer" }, { id: "inf" }, { id: "spear" }];
// The factory runs in its own VM realm, so the objects it returns do not share this realm's
// Object.prototype and deepStrictEqual would reject them on identity alone. Copy into a plain
// same-realm object before comparing.
const plain = o => ({ cav: o.cav, archer: o.archer, inf: o.inf, spear: o.spear });
const mk = budget => { const P = FACTORY(CLASSES, budget);
  return { set: P.set, total: P.total, quick: P.quick, amt: () => plain(P.amt()) }; };

// ---- 1/2/3/4. plus, minus, floor at 0, ceiling at available ----
{
  const P = mk({ cav: 92, archer: 186, inf: 347, spear: 5 });
  assert.strictEqual(P.set("inf", 0), 0);
  assert.strictEqual(P.set("inf", (P.amt().inf || 0) + 1), 1, "+ increments by exactly 1");
  assert.strictEqual(P.set("inf", P.amt().inf + 1), 2);
  assert.strictEqual(P.set("inf", P.amt().inf - 1), 1, "- decrements by exactly 1");
  assert.strictEqual(P.set("inf", P.amt().inf - 1), 0);
  assert.strictEqual(P.set("inf", P.amt().inf - 1), 0, "cannot go below 0");
  assert.strictEqual(P.set("inf", 347), 347);
  assert.strictEqual(P.set("inf", 348), 347, "cannot exceed available");
  assert.strictEqual(P.set("inf", 999999), 347, "a huge value clamps to available");
  ok("1/2/3/4. +1 and -1 step by exactly one; the value is bounded by [0, available]");
}

// ---- 5/6/7. direct numeric entry, including large values and junk ----
{
  const P = mk({ cav: 92, archer: 186, inf: 347, spear: 5 });
  assert.strictEqual(P.set("inf", "120"), 120, "typing 120 sets 120 in one action");
  assert.strictEqual(P.set("archer", "186"), 186);
  assert.strictEqual(P.set("cav", "1e3"), 92, "exponent notation cannot exceed availability");
  assert.strictEqual(P.set("inf", "12.9"), 12, "a decimal cannot produce fractional troops");
  assert.strictEqual(P.set("inf", "-40"), 0, "a negative cannot be submitted");
  assert.strictEqual(P.set("inf", "abc"), 0, "junk becomes 0, never NaN");
  assert.strictEqual(P.set("inf", ""), 0, "an empty field reads as 0");
  assert.strictEqual(P.set("inf", null), 0);
  assert.strictEqual(P.set("inf", undefined), 0);
  // a class never touched simply has no entry; what matters is that every entry that EXISTS is a
  // non-negative integer, so nothing fractional, negative or NaN can reach the payload
  Object.keys(P.amt()).forEach(k => {
    const v = P.amt()[k];
    if (v === undefined) return;
    assert.ok(Number.isInteger(v) && v >= 0,
      "every stored amount stays a non-negative integer (" + k + " = " + v + ")");
  });
  ok("5/6/7. a large number is typed in ONE action; decimals, negatives, junk and blanks can " +
     "never reach the payload");
}

// ---- 8. per-class MAX touches only that class ----
{
  const P = mk({ cav: 92, archer: 186, inf: 347, spear: 5 });
  P.set("cav", 10); P.set("archer", 10);
  const budget = { cav: 92, archer: 186, inf: 347, spear: 5 };
  P.set("inf", budget.inf);
  assert.strictEqual(P.amt().inf, 347, "per-class MAX fills that class");
  assert.strictEqual(P.amt().cav, 10, "...and leaves the others alone");
  assert.strictEqual(P.amt().archer, 10);
  ok("8. per-class MAX sets that class to its own availability and touches nothing else");
}

// ---- 9/10/11/12/13. quick deploy is deterministic, per class, floored ----
{
  const budget = { cav: 92, archer: 186, inf: 347, spear: 7 };
  const P = mk(budget);
  P.quick(0.5);
  assert.deepStrictEqual(P.amt(), { cav: 46, archer: 93, inf: 173, spear: 3 },
    "50% floors each class against its OWN availability");
  assert.strictEqual(P.total(), 46 + 93 + 173 + 3, "the total is the sum of the classes");
  P.quick(0.25);
  assert.deepStrictEqual(P.amt(), { cav: 23, archer: 46, inf: 86, spear: 1 }, "25%");
  P.quick(0.75);
  assert.deepStrictEqual(P.amt(), { cav: 69, archer: 139, inf: 260, spear: 5 }, "75%");
  P.quick(1);
  assert.deepStrictEqual(P.amt(), plain(budget), "MAX is every available troop");
  assert.strictEqual(P.total(), 92 + 186 + 347 + 7);
  P.quick(0);
  assert.deepStrictEqual(P.amt(), { cav: 0, archer: 0, inf: 0, spear: 0 }, "Clear zeroes it");
  assert.strictEqual(P.total(), 0);
  // floor is the documented rule, and it never over-commits
  const odd = mk({ cav: 3, archer: 1, inf: 0, spear: 9 });
  odd.quick(0.5);
  assert.deepStrictEqual(odd.amt(), { cav: 1, archer: 0, inf: 0, spear: 4 },
    "floor rounding: 3->1, 1->0, 9->4, and an empty class stays 0");
  ok("9/10/11/12/13. 25/50/75/MAX/Clear are deterministic, per class, floored, and never exceed " +
     "availability; totals follow");
}

// ---- one canonical state ----
{
  assert.ok(/trayAmt\[ty\] = /.test(setterSrc),
    "traySet is the single writer of the proposed squad");
  const writers = (render.match(/trayAmt\[[a-z.]+\] = /g) || []);
  assert.ok(writers.length <= 1,
    "the planner does not write trayAmt except through the setter (found " + writers.length + ")");
  assert.ok(/traySet\(ty, \(trayAmt\[ty\] \|\| 0\) \+ 1\)/.test(render) &&
            /traySet\(ty, \(trayAmt\[ty\] \|\| 0\) - 1\)/.test(render) &&
            /traySet\(ty, trayBudget\(\)\[ty\] \|\| 0\)/.test(render) &&
            /traySet\(ty, digits === "" \? 0 : digits\)/.test(render),
    "plus, minus, per-class MAX and the numeric field all go through traySet");
  assert.ok(/trayQuick\(parseFloat\(bt\.dataset\.pct\)\)/.test(render),
    "and so does quick deploy");
  assert.ok(!/type="range"/.test(render), "no slider was added -- the numeric field is the fix");
  ok("one canonical proposed squad: every control writes it through the same setter");
}

// ============================================================================================
// STRUCTURAL: the surrounding architecture
// ============================================================================================
// ---- 14/15/20. the planner is a modal, and the inspector holds no planner ----
assert.ok(/openTray\("occupy"\)/.test(code) && /openTray\("attack"\)/.test(code),
  "Occupy and Attack still open the planner");
assert.ok(/openModal\(html\)/.test(render), "the planner is rendered into the shared modal");
assert.ok(/classList\.add\("act-modal"\)/.test(render), "on the dedicated action-modal surface");
assert.ok(buildHud.indexOf("hud-tray") === -1 && buildHud.indexOf("hudTray") === -1,
  "the inspector builds no planner element at all");
assert.ok(code.indexOf('id = "hudTray"') === -1, "and none is left dormant anywhere");
assert.ok(/hudSlot\("hud-card"\)/.test(buildHud) && /hudSlot\("hud-actions"\)/.test(buildHud) &&
          /hudSlot\("hud-facts"\)/.test(buildHud),
  "the inspector still owns identity, the action choice and the detail");
assert.strictEqual((code.match(/function renderTray\(\)/g) || []).length, 1,
  "there is exactly one planning surface");
ok("14/15/20. Occupy and Attack open ONE action modal; the inspector keeps no planner");

// ---- 16/23. the payloads are the existing ones ----
assert.ok(/const key = hudSelKey, mode = trayMode, squad = traySquad\(\), src = traySrc;/.test(confirm),
  "the whole plan is still captured before teardown");
assert.ok(/claimTroops\(key, squad, pop,/.test(confirm),
  "occupy still goes through the existing claim path");
assert.ok(/launchAttack\(src, key, name, h, squad\)/.test(confirm),
  "attack still goes through the existing launch path with the chosen source");
const squadFn = slice("function traySquad()", "\n      function trayConfirm", "traySquad");
assert.ok(/TROOPS\.filter\(t => \(trayAmt\[t\.id\] \|\| 0\) > 0\)/.test(squadFn) &&
          /hp: trayAmt\[t\.id\]/.test(squadFn),
  "the payload is built from the same canonical trayAmt, zero classes omitted");
ok("16/23. what the player types reaches the EXISTING claim and attack payloads unchanged");

// ---- 17/18/19/25/26. cancel, close and success all tear the plan down ----
const close = slice("function closeTray()", "\n      function openTray", "closeTray");
assert.ok(/trayMode = null; traySrc = null; trayAmt = {};/.test(close),
  "closing clears the proposed plan");
assert.ok(/closeModal\(\)/.test(close), "and closes the modal");
assert.ok(/markMap\(\)/.test(close),
  "and repaints, so the source/target outlines cannot outlive the modal");
assert.ok(/\.af-cancel"\)\.addEventListener\("click", closeTray\)/.test(render),
  "Cancel routes to that one teardown");
const bind = slice("function trayBindClose(ov)", "\n      function traySquad", "trayBindClose") ||
  code.slice(code.indexOf("function trayBindClose(ov)"));
assert.ok(/x\.addEventListener\("click", closeTray\)/.test(bind),
  "the modal's X routes to it too, not to the bare closeModal");
assert.ok(/if \(e\.target === ov\) closeTray\(\)/.test(bind),
  "and so does a backdrop dismissal");
assert.ok(/closeTray\(\);\n *launchAttack/.test(confirm.replace(/\r/g, "")) ||
          /closeTray\(\);/.test(confirm),
  "a successful action tears the plan down as well");
assert.ok(close.indexOf("fetch(") === -1 && close.indexOf("/api/") === -1,
  "closing without submitting changes no authoritative state");
ok("17/18/19/25/26. Cancel, X, backdrop and success all use ONE teardown; closing mutates nothing");

// ---- 21/22/24/27/28. attack source semantics are the Phase 14A rule, unchanged ----
assert.ok(/srcs = trayValidSources\(\);/.test(render),
  "the source list is the existing global helper");
const sources = slice("function validAttackSources(targetKey)", "\n  function launchAttack",
  "validAttackSources");
assert.ok(/territory\.holders/.test(sources) && sources.indexOf("adjacentTerritoryIds") === -1,
  "Phase 14A stands: every garrisoned territory you own, adjacency irrelevant");
assert.ok(/if \(srcs\.indexOf\(traySrc\) < 0\) traySrc = srcs\[0\];/.test(render),
  "a source is always explicitly held in state, never inferred at submit time");
assert.ok(/aria-pressed="' \+ \(sk === traySrc\)/.test(render),
  "and which one is chosen is announced, not just coloured");
// Phase 14A.9: the ceiling is still the CHOSEN SOURCE's own army -- read through
// sourceAvail(), which answers the Home Base pool for @home and that territory's garrison
// otherwise. The picker gained a source kind, not a second budget rule.
assert.ok(/return sourceAvail\(traySrc\);/.test(
  slice("function trayBudget()", "\n      function closeTray", "trayBudget")),
  "the picker's ceiling for an attack is the chosen SOURCE's own availability");
assert.ok(/if \(isHomeSource\(key\)\) return poolAvail\(\);/.test(code) &&
  /return squadByType\(\(\(holders\[key\] \|\| \{\}\)\.troops\) \|\| \[\]\);/.test(code),
  "...and sourceAvail resolves that to the Home Base pool or the territory garrison");
ok("21/22/24/27/28. the source stays explicit, its garrison bounds the picker, and the global " +
   "Alpha source rule is untouched");

// ---- 29/30/31. no camera or map work from the modal ----
["geoCam", "cam.home", "cam.restore", "cam.focusRect", "getScreenCTM", "drawGeo", "refreshMap",
 "createElementNS", "captureCTM"].forEach(bad => {
  assert.ok(render.indexOf(bad) === -1,
    "the planner must not touch the camera or rebuild the map (" + bad + ")");
});
assert.ok(close.indexOf("geoCam") === -1 && close.indexOf("drawGeo") === -1 &&
          close.indexOf("refreshMap") === -1,
  "and neither must closing it");
assert.strictEqual((code.match(/getScreenCTM\(\)/g) || []).length, 1,
  "the single projection authority is untouched");
ok("29/30/31. opening, editing and closing the modal do no camera work and rebuild no map paths");

// ---- 32/33. the shell and the Empire boundary are unchanged ----
const grid = css.slice(css.indexOf(".hud-grid {"), css.indexOf(".hud-grid {") + 400);
assert.ok(/height: var\(--shell-h/.test(grid) && /grid-template-rows: auto minmax\(0, 1fr\)/.test(grid),
  "the fixed shell is unchanged");
const actions = slice("function renderHudActions()", "\n      hudRefresh = function", "actions");
["Recruit", "openHomeBase", "buildingsPanel", "Research", "Buildings", "Technology"].forEach(m => {
  assert.ok(actions.indexOf(m) === -1, "the inspector still offers no " + m);
});
// The modal may NAME Recruit -- "Recruit in Empire > Forces first" is a pointer, and pointing at
// the right destination is the boundary working. What it must not contain is a management
// OPERATION, so the OPERATIONS are what this forbids.
["recruitTroops", "openHomeBase", "buildingsPanel", "openBuildingDetail", "empireForces",
 "empireBuildings", "empireTechnology", "/api/territory/recruit", "/api/territory/build",
 "/api/territory/research"].forEach(op => {
  assert.ok(render.indexOf(op) === -1,
    "the action modal must not perform empire management (" + op + ")");
});
assert.ok(/Empire \\u25B8 Forces/.test(render) || /Empire ▸ Forces/.test(render),
  "when there are no troops the modal POINTS at Empire rather than recruiting inline");
ok("32/33. the fixed shell stands, and Empire remains the only management destination");

// ---- double submission ----
assert.ok(/goEl\.disabled = true;/.test(render),
  "the commit button disables itself on click, so a double click cannot submit twice");
ok("a double click cannot submit the same action twice");

// ---- no new interaction routes ----
["contextmenu", "oncontextmenu"].forEach(bad =>
  assert.ok(code.indexOf(bad) === -1, "no " + bad + " route may exist"));
assert.ok(!/addEventListener\("dblclick",[^)]*openTray/.test(code),
  "the planner needs no double click");
ok("no context menu, no long-press-only and no double-click-only route was introduced");

console.log("\nAll " + passed + " action-modal checks passed.");
