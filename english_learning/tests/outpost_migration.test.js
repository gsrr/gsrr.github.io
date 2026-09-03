"use strict";
// Phase 2A/2B — frontend attack-flow guards (source-level, no DOM framework).
// 2A: both attack UIs route through the server-authoritative /api/territory/attack; runBattle is replay-only.
// 2B: the request carries sourceTerritoryId + targetTerritoryId (territorial conquest), the client never
// submits winner/survivors, and valid sources come from authoritative ownership (Phase 14A: any
// territory you own with a garrison, wherever it is).
//
//     node tests/outpost_migration.test.js

const fs = require("fs");
const path = require("path");
const assert = require("assert");

let passed = 0;
function ok(name) { passed++; console.log("  ok -", name); }

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");

// Extract a top-level function body by brace-matching from its signature.
function extractFn(src, sig) {
  const start = src.indexOf(sig);
  assert(start >= 0, "cannot find " + sig);
  let i = src.indexOf("{", start), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}") { depth--; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error("unbalanced braces for " + sig);
}

const launchAttack = extractFn(html, "function launchAttack(");
const validAttackSources = extractFn(html, "function validAttackSources(");
// Phase 12D: the modal attack panel and the region modal that hosted it are GONE. The live attack UI
// is the in-board tray, so that is what these checks now read. See the header comment for the full
// OLD / WHY OBSOLETE / NEW / WHY NOT WEAKER record.
const trayRender = extractFn(html, "function renderTray()");
const trayConfirm = extractFn(html, "function trayConfirm()");

// 1) The attack request carries BOTH sourceTerritoryId and targetTerritoryId (Phase 2B), and NOTHING else
//    authoritative — the exact POST body is {sourceTerritoryId, targetTerritoryId, squad, avatar}.
assert(/\/api\/territory\/attack\b/.test(launchAttack), "launchAttack must POST to /api/territory/attack");
assert(/JSON\.stringify\(\{ sourceTerritoryId: source, targetTerritoryId: targetKey, squad: squad, avatar:[^}]*\}\)/.test(launchAttack),
  "attack body must be exactly {sourceTerritoryId, targetTerritoryId, squad, avatar}");
ok("attack request sends sourceTerritoryId + targetTerritoryId (territorial conquest intent)");

// 2) The client submits INTENT only — no winner/survivors/ownership in the POST body.
const body = (launchAttack.match(/JSON\.stringify\(\{[^}]*\}\)/) || [""])[0];
["attackerWon", "attackerSurvivors", "defenderSurvivors", "winner", "survivors", "owner"].forEach(k =>
  assert(body.indexOf(k) < 0, "attack body must not contain client-forged '" + k + "'"));
ok("attack request never submits winner / survivors / ownership (server decides)");

// 3) runBattle in launchAttack is replay-only (preOrdered=true) and mutates no authoritative state.
assert(/runBattle\(squad, order,[^;]*,\s*true\)/.test(launchAttack), "launchAttack must replay with runBattle(..., preOrdered=true)");
assert(!/poolAdd\s*\(/.test(launchAttack) && !/poolSpend\s*\(/.test(launchAttack),
  "launchAttack must not mutate the client pool from the battle result");
ok("battle replay stays non-authoritative (preOrdered=true; no client pool mutation)");

// 4) There is exactly ONE attack UI, and it is the in-board tray.
//
// RETARGETED in Phase 12D. This check has evolved three times:
//   Phase 2A  OLD: openOutpost must ALSO delegate to renderAttackPanel.
//   Phase 7G  OLD: openOutpost must expose no conquest surface at all.
//   Phase 9G  OLD: openOutpost does not exist, and neither does the board-map lesson node.
//   Phase 12D NEW: renderAttackPanel does not exist either -- the attack UI is the board tray.
//
// WHY THE 9G FORM IS OBSOLETE: it grepped `function renderAttackPanel(`. Phase 12C moved attack
// planning out of the modal and into a tray below the map viewport, and 12D deleted the modal panel
// and the region modal that hosted it. The subject cannot be located any more.
//
// WHY THIS IS NOT WEAKER: the authority checks above are untouched (they read launchAttack and
// validAttackSources, both still live). This form additionally asserts what the old one could not:
// that only ONE attack surface exists in the file, and that the plan is captured before the tray is
// torn down -- the bug that shipped a null sourceTerritoryId in 12C.
assert(/trayValidSources\(\)/.test(trayRender) || /trayValidSources\(\)/.test(html),
  "the tray must derive its sources from the shared helper");
assert(/function trayValidSources\(\) \{ return hudSelKey \? validAttackSources\(hudSelKey\) : \[\]; \}/.test(html),
  "...which is validAttackSources, unchanged");
assert(/launchAttack\(src, key, name, h, squad\)/.test(trayConfirm),
  "the tray must fire the existing launchAttack with the captured source");
assert(/const key = hudSelKey, mode = trayMode, squad = traySquad\(\), src = traySrc;/.test(trayConfirm),
  "the whole plan must be captured before closeTray() resets it");
assert(!/function renderAttackPanel\(/.test(html) && !/function openRegion\(/.test(html),
  "the retired modal attack panel and region modal must not come back");
const attackUIs = (html.match(/launchAttack\(/g) || []).length;
assert(attackUIs === 2, "exactly one caller plus the definition of launchAttack: got " + attackUIs);
ok("Phase 12D: exactly ONE attack UI -- the in-board tray -- deriving sources from the same " +
   "helper, capturing the plan before teardown, and firing the same launchAttack");

// 5) Phase 14A: valid attack sources are the player's OWN GARRISONED territories, wherever they
//    are. The old assertion pinned that they came from World-Domain adjacentTerritoryIds rather
//    than from SVG geometry -- the point being "authoritative data, never pixels". That point is
//    preserved and strengthened: sources now come from the authoritative HOLDERS map, and the
//    assertion additionally forbids the geometry it always forbade AND the adjacency filter the
//    Alpha rule retired.
assert(/territory\.holders/.test(validAttackSources),
  "validAttackSources must read the authoritative holders map");
assert(!/adjacentTerritoryIds/.test(validAttackSources),
  "Alpha rule: sources are no longer filtered by adjacency");
["getBBox", "getBoundingClientRect", "clientX", "cx", "cy"].forEach(px => {
  assert(validAttackSources.indexOf(px) === -1,
    "sources must never come from pixels (" + px + ")");
});
assert(/k === targetKey/.test(validAttackSources),
  "a territory still cannot be its own attack source");
assert(/sumHp\(h\.troops\) > 0/.test(validAttackSources),
  "a source still needs a garrison");
assert(!/getBoundingClientRect|viewBox|\.x\b|\.y\b/.test(validAttackSources), "source selection must not use geometry/coordinates");
ok("valid sources derived from AUTHORITATIVE ownership (Alpha rule), never from geometry");

// 6) The UI must REPRESENT "you have no source to march with", not attack anyway.
//    Retargeted in 12D from renderAttackPanel to the tray, and reworded in 14A: the reason can no
//    longer be geography, because the Alpha rule has none. The message must still exist and must
//    still name the REAL obstacle -- a garrison -- so the player is told something actionable.
// Phase 14A.9: the real obstacle is no longer "no garrisoned territory" -- Home Base is a
// source too, so the only thing that can block an attack is having NO ARMY AT ALL, and the
// message must name the place a first army actually comes from.
assert(/You have no army to march with yet/.test(trayRender),
  "the tray must state why an attack is impossible");
assert(/Home Base/.test(trayRender) && /do not need to own a territory first/.test(trayRender),
  "...and must point at Home Base recruitment rather than at owning ground");
assert(!/No adjacent territory/.test(trayRender),
  "and it must not blame adjacency, which no longer blocks anything");
assert(/[Rr]ecruit/.test(trayRender),
  "the message must point at the action that fixes it");
// Phase 14A: the remedy is no longer "take a neighbouring territory" -- geography is not the
// Phase 14A.9: the remedy is no longer "leave a garrison somewhere" either -- the first army
// is recruited at Home Base, which is itself a valid source, so that is what the message says.
assert(/Recruit at .{0,12}Home Base in/.test(trayRender),
  "...and what the player would have to do first");
// Phase 14A: the isolated-island sentence is retired -- an island is reachable now, and saying
// otherwise would be false. The message must not resurrect that claim.
assert(!/cannot be reached by land/.test(trayRender),
  "the tray must not claim an island is unreachable");
// bound the slice to the no-source branch itself; the rest of renderTray legitimately builds the
// ATTACK button for the case where a source DOES exist
const noSrcBlock = trayRender.slice(trayRender.indexOf("if (!srcs.length)"),
                                    trayRender.indexOf("const budget = trayBudget()"));
// Phase 14A.1 renamed the footer controls tb-go / tb-cancel to af-go / af-cancel when the planner
// became a modal. The RULE is unchanged: with no valid source there is no commit control at all,
// only a way to close.
assert(noSrcBlock.length > 200 && noSrcBlock.indexOf("af-go") === -1 &&
       noSrcBlock.indexOf("tb-go") === -1,
  "with no valid source the planner must offer no ATTACK button at all");
assert(/af-cancel/.test(noSrcBlock), "...only a way to close it");
ok("UI represents 'you have no garrisoned source' instead of attacking anyway");

// 7) Regression: the legacy client-authoritative attack chain stays gone.
assert(!/runBattle\(squad,\s*\(foe/.test(html), "client-shuffle runBattle(squad,(foe...)) must be gone");
assert(!/if \(win\) releaseTerritory/.test(html), "client 'if (win) releaseTerritory' must be gone");
assert(!/terrAttackResult\(file, win\)/.test(html), "client 'terrAttackResult(file, win)' must be gone");
ok("legacy client-authoritative attack patterns remain removed");

// 8) Phase 9G positive invariant: the ONLY lesson-entry architecture left is the registry-driven
//    Learning Home door. Without this, a future change could reintroduce a second entry surface and
//    checks 4/7 above (which are absence-only) would still pass.
assert(/function openLessonFromHome\(/.test(html), "Learning Home must own the lesson door");
assert(/function applyRegistryTabs\(/.test(html) && /applyRegistryTabs\(article\.file\)/.test(html),
  "activity availability must stay registry-driven (Phase 9E.2)");
const openFromHome = extractFn(html, "function openLessonFromHome(");
assert(/contentPathForLessonId\(/.test(openFromHome) && /findArticleByFile\(/.test(openFromHome),
  "the lesson door must resolve a registry lessonId to its content path");
assert(html.indexOf("function articleTotal") < 0 && html.indexOf("function articleDone") < 0,
  "the callerless practice-count helpers must stay deleted (Phase 9G)");
ok("the registry-driven Learning Home door is the only lesson entry, and the callerless practice "
   + "helpers stay deleted");

console.log("\nAll " + passed + " frontend attack-flow tests passed.");
