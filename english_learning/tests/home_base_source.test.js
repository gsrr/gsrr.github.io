// Phase 14A.9 — HOME BASE IS AN ATTACK SOURCE IN THE PLANNER.
//
//   node tests/home_base_source.test.js
//
// The Attack planner enumerated sources from `territory.holders` only, so a player who held no
// World territory was told "None of your territories has a garrison to march with" while a full
// army sat at Home Base. Home Base is now offered as a source in its own right.
//
// These pins are about the CLIENT surface only: the enumeration, the label, the troop figures it
// reads, the identity it submits and the reconciliation afterwards. The authority -- eligibility,
// the troop debit, the battle and the settlement -- is pinned server-side in
// tests/home_base_attack_test.py, and nothing here may duplicate it.
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const code = html.split(/\r?\n/).filter(l => !/^\s*\/\//.test(l)).join("\n");

let passed = 0;
function assert(c, m) { if (!c) { console.error("  FAIL - " + m); process.exit(1); } }
function ok(n) { passed++; console.log("  ok -", n); }

function slice(from, to, label) {
  const a = code.indexOf(from);
  assert(a >= 0, "cannot find " + label + " start: " + from);
  const b = code.indexOf(to, a + from.length);
  assert(b > a, "cannot find " + label + " end: " + to);
  return code.slice(a, b);
}

const srcFn = slice("function validAttackSources(targetKey) {", "function isHomeSource(",
                    "validAttackSources");
const helpers = slice("function isHomeSource(key)", "function launchAttack(", "source helpers");
const tray = slice("function renderTray() {", "function trayBindClose(", "renderTray");
const budget = slice("function trayBudget() {", "function closeTray(", "trayBudget");

// ===================== 29/31. the planner offers Home Base =====================
assert(/return \(poolTotal\(\) > 0 \? \[HOME_KEY\] : \[\]\)\.concat\(owned\);/.test(srcFn),
  "Home Base is added to the source list whenever its pool has troops");
assert(/const owned = Object\.keys\(holders\)\.filter/.test(srcFn),
  "...and the existing owned-and-garrisoned rule is kept, not replaced");
assert(srcFn.indexOf("HOME_KEY") < srcFn.indexOf("concat(owned)"),
  "Home Base is offered FIRST, so a zero-territory player sees it immediately");
assert(!/owned\.length\s*(===|==|<|>)\s*0\s*\?\s*\[HOME_KEY\]/.test(srcFn),
  "Home Base is NOT conditional on owning nothing -- it is never auto-hidden");
ok("29/31. the Attack planner enumerates Home Base as a source whenever it has troops, listed " +
   "first, and it is never hidden merely because the player also owns territories");

// ===================== 30. the label is player-facing =====================
assert(/function sourceLabel\(key\) \{[\s\S]{0,240}Home Base/.test(helpers),
  "the source label says Home Base");
assert(/isHomeSource\(key\) \? "\\u\{1F3E0\}" \+ " Home Base"/.test(helpers),
  "...as the player-facing name for the canonical key");
assert(/const HOME_KEY = "@home";/.test(code), "the canonical identity is unchanged");
const shown = tray.match(/\+ sourceLabel\(sk\) \+/);
assert(shown, "the source button renders sourceLabel(), not the raw key");
assert(tray.indexOf('"@home"') < 0 && tray.indexOf("'@home'") < 0,
  "@home is never written into the planner's markup as a display string");
ok("30. the player-facing label is 'Home Base'; the raw canonical id @home is never shown");

// ===================== 32. the troop figures are the authoritative ones =====================
assert(/function sourceAvail\(key\) \{\s*if \(isHomeSource\(key\)\) return poolAvail\(\);/.test(helpers),
  "Home Base availability is the free pool");
assert(/return squadByType\(\(\(holders\[key\] \|\| \{\}\)\.troops\) \|\| \[\]\);/.test(helpers),
  "...and a territory's is still its own garrison");
assert(/function poolAvail\(\) \{ const p = poolObj\(\)/.test(code) &&
       /function poolObj\(\)/.test(code),
  "poolAvail reads the existing published economy pool -- no second troop store");
assert(/' \\u00b7 \\u\{1F6E1\}' \+ sourceStrength\(sk\)/.test(tray),
  "each source button shows that source's own strength");
assert(/function sourceStrength\(key\) \{\s*const a = sourceAvail\(key\);/.test(helpers),
  "...computed from the same availability the picker spends");
ok("32. Home Base troop counts are read from the authoritative economy pool the server publishes " +
   "-- the same figures Forces and the HUD show, with no client-side synthesis");

// ===================== 33. selecting it re-bases the picker =====================
assert(/if \(trayMode === "attack"\) \{\s*return sourceAvail\(traySrc\);/.test(budget),
  "the committed-squad budget follows the CHOSEN source");
assert(/traySrc = bt\.dataset\.src;/.test(code) &&
       /const nb = trayBudget\(\);\s*TROOPS\.forEach\(t => trayAmt\[t\.id\] = nb\[t\.id\] \|\| 0\);/.test(code),
  "choosing a source re-bases the proposed squad on that source's availability");
assert(/if \(srcs\.indexOf\(traySrc\) < 0\) traySrc = srcs\[0\];/.test(tray),
  "an invalid source falls back to the first offered one");
assert(/aria-pressed="' \+ \(sk === traySrc\)/.test(tray),
  "the chosen source is announced, so selection stays explicit");
ok("33. Home Base can be selected like any other source, and selecting it re-bases the troop " +
   "picker on the Home Base pool");

// ===================== 34/35. existing sources and explicit selection =====================
assert(/escapeHtml\(regionDisplayName\(key\) \|\| key\)/.test(helpers),
  "territory sources still render their display name");
assert(/class="act-src" data-src="' \+ escapeHtml\(sk\)/.test(tray),
  "every source is still its own button");
assert(!/traySrc = \[/.test(code) && !/sources\.reduce/.test(code),
  "no multi-source merge was introduced");
assert((tray.match(/launchAttack\(/g) || []).length === 0 &&
       /launchAttack\(src, key, name, h, squad\);/.test(code),
  "one attack still has one source, submitted through the single existing launcher");
ok("34/35. existing territory sources render exactly as before, selection remains explicit, and " +
   "one attack still has exactly one source");

// ===================== 36. the fast troop picker is untouched =====================
assert(/function trayQuick\(pct\) \{[\s\S]{0,220}Math\.floor\(\(budget\[t\.id\] \|\| 0\) \* pct\)/.test(code),
  "the 25/50/75/MAX row still floors against availability");
assert(/function traySet\(ty, raw\) \{\s*const max = trayBudget\(\)\[ty\] \|\| 0;/.test(code),
  "every amount is still clamped by traySet against the budget");
assert(/\[\["25%", 0\.25\], \["50%", 0\.5\], \["75%", 0\.75\]\]/.test(tray) &&
       /data-pct="1">MAX/.test(tray) && /data-pct="0">Clear/.test(tray),
  "the quick-deploy row is unchanged");
assert(/inputmode="numeric"/.test(tray), "and typing a number still works");
ok("36. the Phase 14A.1 fast troop picker is unchanged and clamps to the Home Base pool through " +
   "the same one canonical proposed squad");

// ===================== 37. what Confirm submits =====================
assert(/const key = hudSelKey, mode = trayMode, squad = traySquad\(\), src = traySrc;/.test(code),
  "the whole plan is captured before teardown, including the source");
assert(/JSON\.stringify\(\{ sourceTerritoryId: source, targetTerritoryId: targetKey, squad: squad, avatar: avatarOf\(userName\) \}\)/
  .test(code), "Confirm posts the canonical source identity to the existing attack endpoint");
assert(/fetch\(withRoom\("\/api\/territory\/attack\?token="/.test(code),
  "...the same endpoint as before -- no new route");
assert((code.match(/\/api\/territory\/attack/g) || []).length === 1,
  "exactly one attack endpoint reference in the client");
ok("37. Confirm sends the canonical Home Base identity (@home) as sourceTerritoryId to the one " +
   "existing attack endpoint");

// ===================== 38/39. reconciliation after the attack =====================
assert(/loadEconomy\(function \(\) \{ loadTerritory\(function \(\) \{ renderEmpire\(\); refreshMap\(\); \}\); \}\);/
  .test(code), "settlement reloads economy AND territory, then repaints");
assert((code.match(/loadEconomy\(function \(\) \{ loadTerritory\(function \(\) \{ renderEmpire\(\); refreshMap\(\); \}\); \}\);/g) || []).length >= 2,
  "...on the success path and on the refusal path alike");
assert(/if \(res\.gold != null && myEcon\) myEcon\.gold = res\.gold;/.test(code),
  "the server's gold figure is taken, never computed");
assert(!/myEcon\.troops\[[^\]]+\]\s*-=/.test(code) && !/poolObj\(\)\[[^\]]+\]\s*=/.test(code),
  "the client never debits the Home Base pool itself");
ok("38/39. after an attack the Home Base troop count and the target's ownership colour both come " +
   "from a reload of the authoritative caches -- no optimistic client arithmetic");

// ===================== 40. no new surface =====================
assert(tray.indexOf("openModal") > 0, "the planner still uses the one action modal");
assert(!/homeBaseModal|openHomeAttack|attackFromHomeModal/.test(code),
  "no new modal was introduced for this capability");
assert(!/showScreen\("screenHome"\)/.test(slice("function trayConfirm() {", "function renderHudActions",
                                                "trayConfirm")),
  "and no navigation away from the board was introduced");
assert(/title: "Plan an attack on " \+ name \+ " from your Home Base or any territory you own"/.test(code),
  "the board's Attack control says Home Base counts");
ok("40. no new modal, screen or navigation step: the capability is entirely inside the existing " +
   "action modal");

// ===================== the invariant: Home Base is not a territory =====================
assert(!/holders\[HOME_KEY\]\s*=/.test(code) && !/territory\.holders\[HOME_KEY\]\s*=/.test(code),
  "the client never writes a holders entry for Home Base");
assert(/function markMap\(\) \{[\s\S]{0,900}trayValidSources\(\)\.forEach\(sk => paint\(sk, "geo-src"\)\)/
  .test(code), "map marking still derives only from the plan state");
assert(/isHomeSource\(traySrc\)\s*\?\s*' \\u00b7 \\u\{1F3E0\} Home Base is off the map/.test(tray),
  "...and the planner says plainly that Home Base has no outline on the map");
ok("invariant: Home Base gains no map identity in the client -- no holders entry, no region, and " +
   "the planner states that it is off the map");

console.log("\nAll " + passed + " Home-Base-source checks passed.");
