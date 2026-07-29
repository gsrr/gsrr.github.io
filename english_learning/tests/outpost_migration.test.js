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
const openOutpost = extractFn(html, "function openOutpost(a)");

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

// 4) Both attack UIs (geo-map openRegion + trail openOutpost) delegate to the shared renderAttackPanel.
assert(/renderAttackPanel\(/.test(openRegion), "openRegion must delegate to renderAttackPanel");
assert(/renderAttackPanel\(/.test(openOutpost), "openOutpost must delegate to renderAttackPanel");
ok("both openRegion and openOutpost route attacks through the shared source→target panel");

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

console.log("\nAll " + passed + " frontend attack-flow tests passed.");
