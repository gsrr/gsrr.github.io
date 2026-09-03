// Phase 14A.2 — ALPHA NAVIGATION / CHROME CLEANUP.
//
//   node tests/alpha_navigation.test.js
//
// Three redundancies an Alpha player reported, and the rules that keep them gone:
//
//   A  Empire was reachable TWICE from the World chrome -- the identity plaque's "Empire ▸" button
//      and the destination cluster's castle icon. The cluster is the canonical primary navigation
//      (Academy, My progress, Ranking, Empire, Multiplayer, World events), so the plaque's copy went.
//   C  Ranking's return control said "← Back". f216549 had already made the DESTINATION canonical;
//      the label had not caught up, so a screen reached from exactly one place named nothing and
//      still read as legacy chrome. It now says "← World Conquest".
//   D  #userChip IS the My Progress entry, and showScreen() revealed it on every in-app screen --
//      including My Progress itself. The page offered its own name as a link back to itself.
//
// B (removing the Multiplayer button) is deliberately NOT implemented; see the report. This file
// therefore also pins that the multiplayer domain is intact, so a later removal is a decision.
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

// ===================== 1. exactly one My Empire entry in the World chrome =====================
const plaque = slice("function renderHudPlayer() {", "function renderHudBoss()", "renderHudPlayer");
const controls = slice("function renderHudControls() {", "function renderHudCard()", "renderHudControls");
assert(plaque.indexOf("openEmpire") < 0, "the identity plaque no longer opens Empire");
assert(plaque.indexOf("hp-more") < 0, "...and its Empire button is gone, not merely hidden");
assert((controls.match(/openEmpire/g) || []).length === 1,
  "the destination cluster offers Empire exactly once");
const empireOpeners = (code.match(/icoBtn\("[^"]*", "[^"]*Empire[^"]*", openEmpire\)/g) || []);
assert(empireOpeners.length === 1, "one icon button opens Empire: " + JSON.stringify(empireOpeners));
assert(!/hp-more/.test(html), "no .hp-more markup or styling is left behind");
ok("1. the World chrome exposes ONE My Empire control — the destination cluster's, with the " +
   "plaque's duplicate and its dead styling removed");

// ===================== 2. and it still opens the landed Empire workspace =====================
assert(/function openEmpire\(\) \{/.test(code), "openEmpire() is untouched");
assert(/loadEconomy\(function \(\) \{ loadTerritory\(renderEmpireModal\); \}\);/.test(code),
  "...and still refreshes through the canonical loads");
assert(/ov\.querySelector\("\.modal-card"\)\.classList\.add\("emp-modal"\);/.test(code),
  "the panel it opens is still the responsive Empire workspace landed in f216549");
assert(/\.modal-card\.emp-modal \{ max-width: 1040px; \}/.test(html), "...at its workspace width");
assert(/@media \(max-width: 860px\) \{[\s\S]{0,900}\.emp-tbl thead \{ display: none; \}/.test(html),
  "...with its stacked narrow layout intact");
for (const tab of ["empireOverview", "empireForces", "empireBuildings", "empireTechnology"])
  assert(code.indexOf("function " + tab + "(") >= 0, "Empire still has its " + tab + " area");
ok("2. the surviving control opens the same responsive Empire workspace, all four areas intact");

// ===================== 3/4. Multiplayer: NOT removed, and the domain is whole =====================
// The audit found openRooms() is the only player-facing route to three room operations -- join a
// game by code, create a private game, and return to the shared GLOBAL world -- so removal was
// stopped and reported instead. These pins make that state explicit rather than accidental.
assert(controls.indexOf("openRooms") < 0,
  "the primary destination cluster does not offer Multiplayer");
assert(!/icoBtn\([^)]*"Multiplayer/.test(code), "...and no icon button anywhere names it");
assert(!/HUD\.ct\.appendChild\([^)]*openRooms/.test(code), "...nothing appends it to the cluster");
const rooms = slice("function openRooms() {", "function loadLobby()", "openRooms");
assert(/clearActiveRoom\(\);/.test(rooms), "it is still the one explicit room-exit boundary");
assert(/function joinByCode\(\)/.test(code) && /enterRoom\(code, function \(err\)/.test(code),
  "join-a-game-by-code is still implemented");
assert(/function enterRoom\(code, onErr\) \{/.test(code) && /setActiveRoom\(o\.j\.code\);/.test(code),
  "room entry and the canonical active-room assignment are untouched");
assert(/function withRoom\(url\) \{[\s\S]{0,220}roomCode \|\| SANDBOX_ROOM/.test(code),
  "every world request still names its room");
assert(/function enterWorld\(\) \{ enterRoom\("GLOBAL"\); \}/.test(code),
  "returning to the shared GLOBAL world is still implemented");
assert(/function openMyRoom\(\)/.test(code), "private-game creation is still implemented");
assert(/function openJoin\(\) \{/.test(code), "the join-by-code surface is still implemented");
assert(/showScreen\(screenRooms\)/.test(code), "the rooms screen is still reachable in code");
assert(/id="screenRooms"/.test(html) && /id="joinRoomBtn"/.test(html) && /id="createRoomBtn"/.test(html),
  "the rooms screen and its controls are still in the document");
ok("3/4. standalone Multiplayer is ABSENT from primary World navigation while the whole " +
   "multiplayer/room domain remains implemented — screenRooms, openRooms, openJoin, joinByCode, " +
   "openMyRoom, enterRoom, enterWorld, GLOBAL, private games, roomCode, withRoom and the " +
   "room-exit boundary");

// ===================== 5. Ranking's return names its destination =====================
assert(/<button class="back-btn" id="backFromLeader">← World Conquest<\/button>/.test(html),
  "the visible Ranking return label is exactly '← World Conquest'");
assert(!/id="backFromLeader">← Back</.test(html), "the generic legacy label is gone");
ok("5. Ranking's return control reads '← World Conquest'");

// ===================== 6/7. and it uses the canonical World return =====================
const backHandler = slice('getElementById("backFromLeader").addEventListener("click", () => {',
                          "});", "the Ranking Back handler");
assert(/if \(authToken\(\) && authUser\(\)\) \{ goToGameMap\(\); return; \}/.test(backHandler),
  "it still calls the canonical World opener (f216549)");
assert(!/renderLevelGrid/.test(backHandler) && !/showScreen\(screenLevel\)/.test(backHandler),
  "it does not return to the legacy level/practice grid");
assert(!/history\.back|history\.go/.test(code), "no browser history is used anywhere");
ok("6/7. the label changed; the canonical destination did not — still goToGameMap(), never " +
   "screenLevel, never history");

// ===================== 8. the Ranking screen carries no retired chrome =====================
const rankScreen = html.slice(html.indexOf('<div id="screenLeader"'),
                              html.indexOf('<!-- 畫面 1：選等級 -->'));
assert(rankScreen.length > 200 && rankScreen.indexOf('id="leaderBody"') >= 0, "found the Ranking screen");
assert((rankScreen.match(/<button/g) || []).length === 1,
  "the Ranking screen has exactly one control: its return");
for (const retired of ["openRoomsBtn", "openLeaderBtn", "openEventsBtn", "pickLevelOpen",
                       "change map", "Competition"]) {
  assert(rankScreen.indexOf(retired) < 0, "the Ranking screen must not carry " + retired);
}
ok("8. the Ranking screen itself exposes no retired navigation — one return control and the board");

// ============ 4b. WORLD PRIMARY NAVIGATION IS THE GAME'S OWN DESTINATIONS ============
// Phase 14A.4: My Progress left the cluster. Player feedback was that the Academy already owns
// learning progression and it is not closely related to World Conquest. So the World offers the
// strategy game's destinations and nothing else — and the previous invariant ("My Progress
// reachable from World") is REPLACED by two: absent from the World, reachable through the Academy.
const clusterCalls = (controls.match(/HUD\.ct\.appendChild\(icoBtn\(/g) || []).length;
assert(clusterCalls === 4, "the World cluster appends exactly four destinations (" + clusterCalls + ")");
for (const fn of ["openLearningHome", "openLeaderboard", "openEmpire", "openEvents"])
  assert(controls.indexOf(fn) >= 0, "the cluster still offers " + fn);
assert(controls.indexOf("openProfileStats") < 0,
  "My Progress is NOT a World primary destination");
assert(controls.indexOf("openRooms") < 0, "...and neither is Multiplayer");
// removed as an ENTRY, not as a capability
assert(/function openProfileStats\(\) \{/.test(code), "openProfileStats() itself is untouched");
assert(/showScreen\(screenProfileStats\);/.test(code), "the My Progress screen still opens");
assert(/id="screenProfileStats"/.test(html), "...and is still in the document");
assert(/<span class="brand-t">My Progress<\/span>/.test(html), "...naming itself");
// and the Academy is where it now lives — ONE explicit, UNCONDITIONAL content entry
const awards = slice("function acAchievementsHTML() {", "\n  function acGuestFamilies", "acAchievementsHTML");
assert(/'<button type="button" id="homeProgress">📊 My Progress<\/button>' \+/.test(awards),
  "the Academy exposes an explicitly-labelled My Progress entry");
assert(!/owned\.length \?[^:]*homeProgress/.test(awards),
  "...and it is NOT conditional on owning an award — a fresh learner sees it");
assert((code.match(/id="homeProgress"/g) || []).length === 1,
  "...exactly once, so the Academy has no redundant second entry to the same screen");
assert(!/homeCollection/.test(code),
  "the old conditional 'View Collection' label is gone — converged, not duplicated");
assert(/if \(e\.target && e\.target\.id === "homeProgress"\) \{ openProfileStats\(\); return; \}/.test(code),
  "...and it calls the existing openProfileStats()");
assert(/userChip\.addEventListener\("click", \(\) => \{ if \(userName\) openProfileStats\(\); \}\)/.test(code),
  "the shared account chip still works too, as account chrome the Academy shows and the World hides");
assert(/body\.game-mode #userChip \{ display: none !important; \}/.test(html),
  "the account chip stays hidden on the board, so the World has no ghost My Progress either");
assert(!/\.hud-ico[^{]*display: none/.test(html),
  "the entry was removed by deleting its wiring, not by a broad CSS rule");
ok("4b. World primary navigation is Academy / Ranking / Empire / World Events — My Progress and " +
   "Multiplayer are absent as ENTRIES while both remain fully implemented, and My Progress is " +
   "reached through the Academy");

// ===================== 8b. Ranking says what it is, and how it really ranks =====================
assert(/<span class="learn-title">🏅 Ranking<\/span>/.test(html),
  "the heading matches the destination the navigation names");
assert(!/🏅 Leaderboard/.test(html), "the old heading is gone");
// the phrase survives only inside the comment that records why it was wrong, so this pins the
// VISIBLE copy rather than the string
assert(!/<p class="screen-intro">Top players by lessons passed/.test(html),
  "no visible copy claims the order comes from lessons passed");
assert(/<p class="screen-intro">Ranked by 👥 population, then by 🚩 territories held 🏆<\/p>/.test(html),
  "...it describes the real order");
// and that IS the real order: the client sorts on the same three keys the server does
const lb = slice("function renderLeaderboard(data, terr) {", 'getElementById("backFromLeader")',
                 "renderLeaderboard");
assert(/L\.sort\(\(a, b\) => \(b\.population - a\.population\) \|\| \(b\.regions - a\.regions\) \|\| a\.name\.toLowerCase\(\)\.localeCompare\(b\.name\.toLowerCase\(\)\)\);/
  .test(lb), "the sort is population, then regions, then name — and it is unchanged");
assert(/p\.regions = counts\[p\.name\] \|\| 0/.test(lb),
  "`regions` is the per-owner TERRITORY count, so 'territories held' is the honest word for it");
assert(lb.slice(lb.indexOf("L.sort")).indexOf("passed") < 0,
  "the lesson count decides no part of the order");
ok("8b. the screen is headed Ranking and its copy names the real authority — population, then " +
   "territories held — with the sort itself untouched");

// ===================== 9/10. My Progress does not link to itself =====================
assert(/userChip\.addEventListener\("click", \(\) => \{ if \(userName\) openProfileStats\(\); \}\)/.test(code),
  "#userChip is the My Progress entry");
// NB: the line after showScreen() is a `//` comment, which this file strips — so the slice ends at
// the next real declaration instead.
const show = slice("function showScreen(", "\n  function stopRolePlay()", "showScreen");
assert(/userChip\.classList\.toggle\("hidden", el === screenProfileStats\);/.test(show),
  "showScreen withdraws that entry on the My Progress screen itself");
assert((code.match(/userChip\.classList\.toggle\("hidden"/g) || []).length === 1,
  "...decided in exactly one place");
assert(show.indexOf('topRight.classList.toggle("hidden"') <
       show.indexOf('userChip.classList.toggle("hidden"'),
  "...right beside the existing top-right decision, so there is no second navigation model");
assert(/function openProfileStats\(\) \{[\s\S]{0,600}showScreen\(screenProfileStats\);/.test(code),
  "My Progress still opens normally");
ok("9/10. My Progress opens normally and withdraws its own entry while it is the destination — " +
   "one rule, in the one place navigation is observed");

// ============ 10b. ANY canonical return to the World restores the World's shell ============
// The board's shell -- body.game-mode, .hud-mode, the whole HUD grid -- exists only because
// drawGeo() built it, and showScreen() strips game-mode on the way out of the board. A return that
// showed screenArticle WITHOUT re-running drawGeo therefore left the board's DOM on screen with the
// app chrome over it: #userChip reappeared, and because #userChip IS the My Progress entry the
// World then offered My Progress twice -- the second half of the duplication the player reported.
// The guard that caused it compared the index that OPENED the board with the curriculum level the
// learner last browsed; a game-opened board passes -1, so it never matched.
const profBack = slice('getElementById("backFromStats").addEventListener("click", () => {',
                       "const bossEmojiEl", "the profile Back handler");
assert(/if \(curDrawArgs\) drawGeo\.apply\(null, curDrawArgs\);/.test(profBack),
  "the profile return replays the board's own last arguments whenever it has them");
assert(/else goToGameMap\(\);/.test(profBack),
  "...and falls back to the canonical opener when it has none");
assert(!/curDrawArgs\[2\] === selLevelIdx/.test(code),
  "the opener-index-vs-curriculum-level guard is gone from the whole client");
assert(profBack.indexOf("showScreen(screenArticle)") < profBack.indexOf("drawGeo.apply"),
  "showScreen runs first, then drawGeo — the other order would strip the game-mode drawGeo just added");
assert(!/userChip\.style/.test(code),
  "nothing special-cases the chip's inline display, on this screen or any other");
assert((code.match(/document\.body\.classList\.add\("game-mode"\)/g) || []).length === 1,
  "game-mode is added in exactly one place");
assert(/function drawGeo\(spec, backFn, i, lv\) \{\s*curDrawArgs = \[spec, backFn, i, lv\];/.test(code),
  "...that place is drawGeo, which is also what records the arguments a return replays");
ok("10b. every canonical return to the World goes back through drawGeo, so the shell, game-mode and " +
   "the chrome converge on one state — no second UI-state model and no per-screen special case");

// ===================== 11. Logout survives =====================
assert(/<button id="logoutChip" class="user-chip" type="button" title="Log out">/.test(html),
  "the Logout control is still in the top-right strip");
assert(/getElementById\("logoutChip"\)\.addEventListener\("click", \(\) => \{ clearAuth\(\);/.test(code),
  "...and still logs out");
assert(!/logoutChip\.classList\.toggle\("hidden"/.test(code),
  "nothing withdraws Logout — only the self-navigating item was removed");
ok("11. Logout remains available on My Progress; only the redundant self-link was withdrawn");

// ===================== 12. My Progress still returns to the current product =====================
assert(/const to = profileReturnTo && profileReturnTo\.to;/.test(code),
  "the profile return still uses the context its opener recorded");
assert(/profileReturnTo = \{ to: currentSurfaceKey\(\) \};/.test(code),
  "...recorded on open, from the current surface");
assert(/PROFILE_BACK_LABEL/.test(code), "...and its label names that destination");
ok("12. World -> My Progress -> back still resolves through the existing return context");

// ===================== 13/14/15. nothing about session, room or World state moved =====================
assert(!/clearAuth\(\)/.test(show) && !/clearActiveRoom\(\)/.test(show),
  "showScreen still clears neither the session nor the room");
assert(!/clearActiveRoom\(\)/.test(backHandler), "Ranking's return does not leave the room");
assert(/function setActiveRoom\(code\) \{ roomCode = \(code \|\| ""\)\.toUpperCase\(\); \}/.test(code),
  "the canonical room setter is unchanged");
assert(/if \(geoView && geoView\.room === _room/.test(code) && /cam\.restore\(geoView\.s/.test(code),
  "the World's camera/selection restore is unchanged");
assert(/function authToken\(\)/.test(code) && /function authUser\(\)/.test(code),
  "authentication accessors are unchanged");
ok("13/14/15. session, active room and World camera/selection restoration are all untouched by " +
   "this chrome cleanup");

console.log("\nAll " + passed + " Alpha-navigation checks passed.");
