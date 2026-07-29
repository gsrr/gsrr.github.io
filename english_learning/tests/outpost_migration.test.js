"use strict";
// Phase 2A — verify the legacy openOutpost combat flow was migrated to the server-authoritative
// /api/territory/attack path (the same one geo-map openRegion uses), and that client-side runBattle
// stays replay-only. Source-level guard: catches any regression that re-introduces client-authoritative
// territory combat on the non-geo trail map.
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

const outpost = extractFn(html, "function openOutpost(a)");
const region = extractFn(html, "function openRegion(key, name, pop, i)");

// 1) BOTH attack UIs route through the server-authoritative endpoint.
assert(/\/api\/territory\/attack\b/.test(outpost), "openOutpost must POST to /api/territory/attack");
assert(/\/api\/territory\/attack\b/.test(region), "openRegion must still POST to /api/territory/attack (geo-map unchanged)");
ok("both openOutpost and openRegion attack via the server-authoritative /api/territory/attack");

// 2) openOutpost no longer runs the client-authoritative battle chain.
assert(!/terrEngage\s*\(/.test(outpost), "openOutpost must not call terrEngage");
assert(!/terrAttackResult\s*\(/.test(outpost), "openOutpost must not call terrAttackResult");
assert(!/releaseTerritory\s*\(/.test(outpost), "openOutpost must not call releaseTerritory");
ok("openOutpost no longer calls terrEngage / terrAttackResult / releaseTerritory");

// 3) The specific legacy client-authoritative patterns are gone from the whole file.
assert(!/runBattle\(squad,\s*\(foe/.test(html), "the client-shuffle runBattle(squad, (foe...)) attack must be gone");
assert(!/if \(win\) releaseTerritory/.test(html), "client 'if (win) releaseTerritory(...)' neutralize must be gone");
assert(!/terrAttackResult\(file, win\)/.test(html), "client 'terrAttackResult(file, win)' gold report must be gone");
ok("legacy client-authoritative attack patterns removed from index.html");

// 4) openOutpost replays the server-decided battle (preOrdered=true) and does not mutate authoritative
//    state from the runBattle result (no client survivor pool-add on the attack path).
assert(/runBattle\(squad, order,[^;]*,\s*true\)/.test(outpost), "openOutpost must replay with runBattle(..., preOrdered=true)");
assert(!/poolAdd\s*\(/.test(outpost), "openOutpost must not poolAdd survivors client-side (server owns the pool)");
ok("openOutpost runBattle is replay-only (preOrdered=true); survivors/gold come from the server");

console.log("\nAll " + passed + " outpost-migration tests passed.");
