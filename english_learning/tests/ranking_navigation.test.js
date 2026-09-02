// Phase 14A.1 addendum C — RANKING BACK RETURNS TO THE WORLD.
//
//   node tests/ranking_navigation.test.js
//
// An Alpha player pressed Back on the Ranking screen and landed on an old page. Ranking is a World
// HUD control, but its Back ran:
//
//     renderLevelGrid(); showScreen(screenLevel);
//
// -- the legacy practice/level grid. The current product reaches that screen only as a FALLBACK for a
// room with no learning content (see the #backToLevels handler), and its first control is the retired
// "change map / level - rooms - leaderboard" bar. So Back navigated to a page the game no longer
// navigates to, from a control the player uses constantly.
//
// The fix reuses goToGameMap() -- the canonical current World opener, the same one the Academy's Back
// calls -- so the room, the session and the remembered camera/selection all round-trip through the
// existing restore inside drawGeo(). No history, no new navigation stack.
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

const backHandler = slice('getElementById("backFromLeader").addEventListener("click", () => {',
                          "});", "the Ranking Back handler");

// ===================== 1. Back goes to the World, through the canonical opener =====================
assert(/if \(authToken\(\) && authUser\(\)\) \{ goToGameMap\(\); return; \}/.test(backHandler),
  "Ranking Back calls goToGameMap() for a signed-in player");
assert(/function goToGameMap\(\) \{ openGameMap\(GAME_WORLD_MAP_ID\); \}/.test(code),
  "goToGameMap is the canonical World opener");
assert(/document\.getElementById\("backFromHome"\)\.addEventListener\("click", \(\) => \{\s*goToGameMap\(\);/
  .test(code), "...the same one the Academy's Back already uses");
ok("1. Ranking Back returns to the World through the canonical opener, not a bespoke route");

// ===================== 2. the legacy destination is gone from this control =====================
assert(!/renderLevelGrid/.test(backHandler), "Back no longer renders the legacy level grid");
assert(!/showScreen\(screenLevel\)/.test(backHandler), "...and no longer shows that screen");
for (const forbidden of ["openLearningHome", "openRooms", "showMapForTerritory", "selectLevel",
                         "enterWorld", "openProfileStats", "showScreen(screenLearn)"]) {
  assert(backHandler.indexOf(forbidden) < 0, "Back must not reach " + forbidden);
}
ok("2. Back reaches no legacy landing, no lobby, no old level/region screen, no deprecated home and " +
   "not the Academy");

// ===================== 3. a signed-out visitor still gets somewhere sane =====================
assert(/showScreen\(screenLanding\);/.test(backHandler),
  "a visitor with no session lands on the landing page rather than an empty board");
assert(backHandler.indexOf("authToken()") < backHandler.indexOf("screenLanding"),
  "...and that is the fallback, not the default");
ok("3. the signed-out path is explicit: no session, no World, so the landing page");

// ===================== 4. no browser history is involved =====================
assert(!/history\.back|history\.go|history\.pushState|history\.replaceState/.test(code),
  "the client uses no browser history at all, so Back cannot walk into legacy UI");
assert(!/window\.onpopstate|addEventListener\("popstate"/.test(code), "...and listens for none");
ok("4. no history.back(), no history stack — the destination is named, not guessed");

// ===================== 5. Ranking stores no stale previous screen =====================
const open = slice("function openLeaderboard() {", "function renderLeaderboard(", "openLeaderboard");
assert(/showScreen\(screenLeader\);/.test(open), "Ranking is its own screen");
assert(!/lessonReturnTo|prevScreen|lastScreen|returnTo\s*=/.test(open),
  "opening Ranking records no previous-screen value, so Back cannot restore a stale one");
assert(/if \(terr && terr\.holders\) territory = terr;/.test(open),
  "Ranking refreshes territory through the same canonical assignment, so returning to the World " +
  "shows current ownership");
ok("5. Ranking keeps no navigation memory of its own — the fix needs none, and none can go stale");

// ===================== 6. the same stale helper elsewhere: reported, not silently changed ======
// Two CURRENT controls still navigate to the legacy grid: the local exam's Done and Back. They
// belong to Learning, which this addendum's scope freeze forbids touching, so they are pinned here
// as KNOWN and unchanged -- if someone changes them, that is a decision, not a drift.
const legacyButtons = (code.match(/getElementById\("(\w+)"\)\.addEventListener\("click", \(\) => \{ renderLevelGrid\(\); showScreen\(screenLevel\); \}\)/g) || []);
assert(legacyButtons.length === 2,
  "exactly two controls still go straight to the legacy grid (found " + legacyButtons.length + ")");
assert(legacyButtons.join(" ").indexOf("examDone") >= 0 &&
       legacyButtons.join(" ").indexOf("examBack") >= 0,
  "and they are the local exam's Done and Back: " + JSON.stringify(legacyButtons.map(s => (s.match(/"(\w+)"/) || [])[1])));
assert(legacyButtons.join(" ").indexOf("backFromLeader") < 0,
  "Ranking is no longer one of them");
ok("6. the two remaining legacy-grid controls are the local exam's, recorded as known and " +
   "deliberately unchanged (Learning is outside this scope)");

// ===================== 7. the level grid is still reachable where it is MEANT to be =====================
assert(/if \(e\.target && e\.target\.id === "pickLevelOpen"\) \{ renderLevelGrid\(\); showScreen\(screenLevel\); \}/
  .test(code), "an explicit 'pick a level' control still opens the level grid — that is its purpose");
assert(/if \(homeCampaigns\(\)\.length\) \{ openLearningHome\(\); return; \}/.test(code),
  "and the lesson Back still prefers the current Academy, falling back to the grid only when a room " +
  "has no campaign");
ok("7. the level grid is not deleted — it stays where it is intentional, and Ranking simply stops " +
   "being one of those places");

// ===================== 8. World state semantics preserved =====================
assert(/if \(geoView && geoView\.room === _room && isFinite\(geoView\.s\) && geoView\.s >= CAM_MIN\) \{/
  .test(code), "the board still restores a remembered camera for the same room");
assert(/cam\.restore\(geoView\.s, geoView\.tx, geoView\.ty\);/.test(code), "...through the camera's own restore");
assert(/if \(geoView\.key\) hudSelKey = geoView\.key;/.test(code), "...and the remembered selection");
assert(!/clearActiveRoom\(\)/.test(backHandler) && !/clearAuth\(\)/.test(backHandler),
  "Back clears neither the room nor the session");
ok("8. the existing same-tab camera/selection restoration and the active room and session are " +
   "untouched by this change");

console.log("\nAll " + passed + " Ranking-navigation checks passed.");
