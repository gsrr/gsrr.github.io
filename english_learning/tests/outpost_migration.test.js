"use strict";
// Phase 2A/2B — frontend attack-flow guards (source-level, no DOM framework).
// 2A: both attack UIs route through the server-authoritative /api/territory/attack; runBattle is replay-only.
// 2B: the request carries sourceTerritoryId + targetTerritoryId (territorial conquest), the client never
// submits winner/survivors, and valid sources come from World-Domain adjacency (advisory only).
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
const renderAttackPanel = extractFn(html, "function renderAttackPanel(");
const validAttackSources = extractFn(html, "function validAttackSources(");
const openRegion = extractFn(html, "function openRegion(key, name, pop, i)");

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

// 4) The attack UI delegates to the shared renderAttackPanel — and there is only ONE attack UI.
//
// RETARGETED in Phase 9G. This check has evolved twice:
//
//   Phase 2A  OLD: openOutpost must ALSO delegate to renderAttackPanel.
//   Phase 7G  OLD: openOutpost must expose no conquest surface at all, and must not gate anything on
//                  the local Rule B average.
//   Phase 9G  NEW: openOutpost does not exist, and neither does the board-map lesson node that was
//                  its only caller.
//
// WHY THE 7G FORM IS OBSOLETE: it grepped the body of `function openOutpost(a)`. Phase 9G deleted
// that function together with the 167-line board-map branch inside selectLevel() that wired its only
// click handler, so the assertion can no longer even locate its subject. The branch was unreachable
// for every level that exists — every level in lessons.json has a GEO_MAPS entry, so selectLevel()
// always returns through renderGeoMap() — and all 57 curriculum lessons now enter through Learning
// Home, so the board map was a second lesson-entry architecture with no way in.
//
// WHY THE NEW FORM IS NOT WEAKER: "the function is gone, and nothing can create the node that called
// it" strictly implies the old property — a deleted function cannot expose a conquest surface or a
// Rule B gate. The new form additionally pins what the old one never did: that exactly ONE conquest
// surface exists (openRegion → renderAttackPanel), that selectLevel() has no second lesson entry,
// and that no lesson-status helper reaches a world action.
assert(/renderAttackPanel\(/.test(openRegion), "openRegion must delegate to renderAttackPanel");
assert(html.indexOf("function openOutpost") < 0,
  "openOutpost() must stay deleted (Phase 9G removed the board-map lesson node)");
assert(html.indexOf("moveHeroThenGo") < 0,
  "the board-map hero-walk helper must stay deleted (its only callers were the board-map nodes)");
assert(!/className\s*=\s*["'`]map-node/.test(html) && !/class="map-node/.test(html),
  "nothing may create a .map-node — that class was the board-map lesson/boss node");
// selectLevel() must be a pure delegate to the geo engine: one call, no second lesson entry.
const selectLevel = extractFn(html, "function selectLevel(i)");
assert(/renderGeoMap\(/.test(selectLevel), "selectLevel must delegate to renderGeoMap");
["openOutpost", "selectArticle", "map-board", "articleTotal", "startLevelExam"].forEach(k =>
  assert(selectLevel.indexOf(k) < 0,
    "selectLevel must not reach '" + k + "' — it is a map delegate, not a lesson/exam entry"));
// and no client surface may gate a world action on the local practice average
["launchAttack", "renderAttackPanel"].forEach((sig, idx) => {
  const fn = idx === 0 ? launchAttack : renderAttackPanel;
  assert(!/lessonStatus\(|statusFromScores\(/.test(fn),
    sig + " must not gate a world action on the local Rule B average");
});
ok("canonical attacks route through the shared source→target panel; openOutpost, moveHeroThenGo and "
   + "the .map-node board-map lesson entry are gone, and selectLevel is a pure geo-map delegate");

// 5) Valid attack sources come from World-Domain adjacency (advisory), not SVG geometry/coordinates.
assert(/adjacentTerritoryIds/.test(validAttackSources), "validAttackSources must read World-Domain adjacentTerritoryIds");
assert(!/getBoundingClientRect|viewBox|\.x\b|\.y\b/.test(validAttackSources), "source selection must not use geometry/coordinates");
ok("valid sources derived from World-Domain adjacency (advisory), not geometry");

// 6) Non-adjacent / no-owned-source targets are represented in the UI (no valid source → clear message, no attack).
assert(/validAttackSources\(/.test(renderAttackPanel), "renderAttackPanel must compute valid sources");
assert(/adjacent territory you own/i.test(renderAttackPanel), "renderAttackPanel must show an advisory when no adjacent owned source exists");
ok("UI represents 'no adjacent owned source' (invalid/non-adjacent target) instead of attacking");

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
