// Phase 8D — the Boss / checkpoint battle is a CLIENT-LOCAL CHALLENGE SIMULATION.
//
// It does not consume, restore, damage or create the player's authoritative army, and it grants no
// gold, qualification, mastery, territory or server progression. Phase 8C proved it already had no
// authoritative consequence (Phase 8B.1 made /api/economy/set ignore client troops, which silently
// severed the boss's only write path) — so the UI was charging a price the game never collected.
// Phase 8D removed the pretence rather than inventing real attrition.
//
// These assertions read the SHIPPED index.html, so they fail if the fake economy path comes back.
// Run: node tests/boss_challenge.test.js
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
let passed = 0;
function ok(name) { passed++; console.log("  ok -", name); }

// Brace-matched extraction so we assert on real function bodies, not on nearby text.
function extractFn(src, name) {
  const i = src.indexOf("function " + name);
  if (i < 0) throw new Error("function not found: " + name);
  const open = src.indexOf("{", i);
  let depth = 0, k = open;
  for (; k < src.length; k++) {
    if (src[k] === "{") depth++;
    else if (src[k] === "}") { depth--; if (depth === 0) { k++; break; } }
  }
  return src.slice(i, k);
}

// Comments may still DISCUSS the removed helpers; only executable calls matter.
function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^[ \t]*\/\/.*$/gm, "");
}

const BOSS_FNS = ["startLevelExam", "examAnswer", "examWin", "examLose"];

// ============ §1 no boss function mutates the authoritative troop pool ============
for (const fn of BOSS_FNS) {
  const body = stripComments(extractFn(html, fn));
  for (const bad of ["poolSpend", "poolAdd", "saveEconomy"]) {
    assert(body.indexOf(bad) < 0,
      fn + "() must not call " + bad + "() — the boss army is a copy, not the real pool");
  }
  assert(!/myEcon\.troops\s*=/.test(body),
    fn + "() must not assign myEcon.troops");
}
ok("§1 startLevelExam / examAnswer / examWin / examLose call no pool mutator and never assign "
   + "myEcon.troops");

// ============ §2 the client-side pool mutators are gone entirely ============
const noComments = stripComments(html);
for (const gone of ["poolSpend", "poolAdd", "saveEconomy"]) {
  assert(noComments.indexOf(gone) < 0,
    gone + " must not exist anywhere in executable code (Phase 8D removed it)");
}
ok("§2 poolSpend / poolAdd / saveEconomy are removed from the client entirely — no mutator remains "
   + "for a future caller to reintroduce the pretence with");

// ...but the READ-ONLY pool helpers must survive: they drive display and deployment budgets.
for (const keep of ["poolObj", "poolTotal", "poolAvail", "poolBreakdown"]) {
  assert(noComments.indexOf("function " + keep) >= 0, keep + " must still exist (read-only)");
}
ok("§2 the read-only pool helpers (poolObj / poolTotal / poolAvail / poolBreakdown) survive");

// ============ §3 no boss copy claims troops were spent, lost or refunded ============
const bossText = BOSS_FNS.map(f => stripComments(extractFn(html, f))).join("\n");
const UNTRUE = [
  [/troops return home/i, '"troops return home" (implies a refund of troops never spent)'],
  [/your army fell/i, '"Your army fell" (implies the persistent army died)'],
  [/troops lost/i, '"troops lost"'],
  [/army restored/i, '"army restored"'],
];
for (const [re, why] of UNTRUE) {
  assert(!re.test(bossText), "boss copy must not say " + why);
}
ok("§3 boss result copy makes no false economic claim (no refund / no army death / no restoration)");

// and it must positively say the army is untouched, so the player is not left guessing
assert(/never spends it/i.test(bossText) || /army is untouched/i.test(bossText),
  "boss help/result copy should state that the real army is not spent");
assert(/challenge squad/i.test(bossText), "boss copy should name the challenge squad as such");
ok("§3 boss copy states the army is untouched and names the challenge squad explicitly");

// ============ §4 the checkpoint stays local UI, and grants nothing ============
const win = stripComments(extractFn(html, "examWin"));
assert(/setExamPassed\(/.test(win), "examWin must still set the LOCAL checkpoint (Phase 7H.1)");
for (const bad of ["/api/learning", "/api/economy", "/api/territory", "econ_add_gold"]) {
  assert(win.indexOf(bad) < 0, "examWin must not call " + bad + " — the checkpoint is local UI only");
}
ok("§4 examWin still records the local checkpoint (setExamPassed) and calls no learning / economy / "
   + "territory endpoint — no gold, qualification, mastery or territory consequence");

// ============ §5 the challenge squad is a COPY of the selection ============
const start = stripComments(extractFn(html, "startLevelExam"));
assert(/squad\.map\(u => \(\{ type: u\.type, hp: u\.hp, max: u\.hp \}\)\)/.test(start),
  "startLevelExam must copy the chosen squad into challenge-local units");
assert(/makeBossSquad\(/.test(start), "startLevelExam must build the enemy force via makeBossSquad");
ok("§5 the player's challenge squad is a copy of the selection; the enemy force is makeBossSquad");

// ============ §6 Phase 10A.3R: boss difficulty is a CURRICULUM value, never geography ============
// The budget used to be mapPopSum() over a per-course GAME map (Pre-A1 -> taiwan.svg, A1 ->
// china.svg, A2/B1 -> world.svg), which made a learning checkpoint depend on the game world. It is a
// table now. These are the exact sums measured immediately before the change, so a regression that
// re-derived them from geography — or silently rescaled the table — fails here.
const EXPECTED_BOSS = { "Pre-A1": 2468, "A1": 9677, "A2": 45878, "B1": 45878 };

// Evaluate the shipped table and resolver in a scope where NOTHING else exists. If either one
// touched GAME_MAPS, TERR_CATALOG, manifest or popForName, this would throw a ReferenceError.
function extractConst(src, name) {
  const i = src.indexOf("const " + name);
  if (i < 0) throw new Error("const not found: " + name);
  const end = src.indexOf(";", i);
  return src.slice(i, end + 1);
}
const bossSrc = [extractConst(noComments, "BOSS_ARMY_BY_LEVEL"),
                 extractConst(noComments, "BOSS_ARMY_DEFAULT"),
                 stripComments(extractFn(html, "bossArmyFor")),
                 "return { table: BOSS_ARMY_BY_LEVEL, dflt: BOSS_ARMY_DEFAULT, fn: bossArmyFor };"
                ].join("\n");
const boss = new Function('"use strict";' + bossSrc)();

assert.deepStrictEqual(boss.table, EXPECTED_BOSS,
  "BOSS_ARMY_BY_LEVEL must preserve the pre-change map population sums exactly");
for (const id of Object.keys(EXPECTED_BOSS)) {
  assert.strictEqual(boss.fn(id), EXPECTED_BOSS[id], "bossArmyFor(" + id + ")");
}
ok("§6 boss army per course is exactly Pre-A1 2468 / A1 9677 / A2 45878 / B1 45878 — the pre-change "
   + "map population sums, preserved to the unit");

// the resolver is total: an unknown or malformed course id gets the documented fallback, never NaN,
// never 0, never a crash — a boss with no army would be an unlosable checkpoint.
for (const junk of [undefined, null, "", "A3", "world", 0, {}, []]) {
  const v = boss.fn(junk);
  assert(typeof v === "number" && Number.isFinite(v) && v > 0,
    "bossArmyFor(" + JSON.stringify(junk) + ") must fall back to a positive finite army, got " + v);
  assert.strictEqual(v, boss.dflt, "unknown course ids all use BOSS_ARMY_DEFAULT");
}
ok("§6 bossArmyFor is total: every unknown/malformed course id falls back to one positive finite "
   + "default, so no checkpoint can end up with a zero or NaN boss");

// the map-derived machinery is gone from executable code, so nothing can re-couple the two
for (const gone of ["BOSS_MAP_SPECS", "mapPopSum", "GEO_MAPS"]) {
  assert(noComments.indexOf(gone) < 0,
    gone + " must not exist in executable code — boss difficulty must not be derived from a map");
}
ok("§6 BOSS_MAP_SPECS / mapPopSum / GEO_MAPS are absent from executable code — the course->map "
   + "association that fed boss difficulty cannot come back by accident");

// ...and neither the resolver nor the checkpoint that calls it reads map state
const bossFn = stripComments(extractFn(html, "bossArmyFor"));
for (const bad of ["GAME_MAPS", "TERR_CATALOG", "manifest", "popForName", ".svg", "mapPopSum"]) {
  assert(bossFn.indexOf(bad) < 0, "bossArmyFor must not read " + bad);
}
for (const bad of ["GAME_MAPS", "mapPopSum", ".svg", "popForName"]) {
  assert(start.indexOf(bad) < 0, "startLevelExam must not read " + bad + " to size the boss");
}
assert(/bossArmyFor\(\s*lv\.id\s*\)/.test(start),
  "startLevelExam must size the boss from bossArmyFor(lv.id) — the course id, not a map");
ok("§6 bossArmyFor and startLevelExam read no map, catalog or manifest state: the boss is sized from "
   + "the course id alone");

console.log("\nAll " + passed + " boss-challenge truthfulness tests passed.");
