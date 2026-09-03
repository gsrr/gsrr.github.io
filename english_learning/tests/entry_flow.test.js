// Phase 11B — the student entry contract, pinned against the SHIPPED index.html.
//
//   node tests/entry_flow_test.js
//
// The normal student path is login -> World Conquest: no lobby stop, no Learning Home stop, no room
// choice, no course choice, no map choice. Room stays backend infrastructure, and the permanent
// GLOBAL room is the normal public game.
//
// These assertions read the real file, so a regression that reintroduces a lobby stop, a course
// picker or a room-management step on the normal path fails here rather than in review.
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
let passed = 0;
function ok(name) { passed++; console.log("  ok -", name); }

// Brace-matched extraction, so assertions are about real function bodies and not nearby prose.
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
// Comments may still DISCUSS retired behaviour; only executable code counts.
function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^[ \t]*\/\/.*$/gm, "");
}
const code = stripComments(html);

// ============ 1. login and registration resume the world, not the lobby ============
const sAuth = stripComments(extractFn(html, "sAuth"));
assert(/enterGameDirect\(\)/.test(sAuth),
  "a successful student login/registration must resume the world directly");
assert(!/openRooms\(\)/.test(sAuth),
  "the student auth path must not route through the room lobby");
ok("1/3. student login AND registration go straight to the world (enterGameDirect), never to the lobby");

// ============ 2. the direct-resume entry uses the permanent GLOBAL room ============
const direct = stripComments(extractFn(html, "enterGameDirect"));
assert(/enterRoom\("GLOBAL"/.test(direct),
  "enterGameDirect must resume the permanent GLOBAL room");
assert(/authToken\(\)/.test(direct) && /authUser\(\)/.test(direct),
  "enterGameDirect must require an authenticated identity before entering a room");
assert(/showScreen\(screenLanding\)/.test(direct),
  "an unauthenticated caller must be sent to the landing page, not into a room");
ok("2/6. entry resumes the permanent GLOBAL room and refuses to enter one without an identity");

// ============ 4/5. no lobby and no Learning Home stop on the normal path ============
const enterRoom = stripComments(extractFn(html, "enterRoom"));
assert(/selectLevel\(idx\)/.test(enterRoom), "entering a game must still draw the board");
assert(!/openLearningHome\(\)/.test(enterRoom),
  "entering a game must NOT open Learning Home first -- the board is the destination");
assert(/setActiveRoom\(/.test(enterRoom),
  "the active room must be established from the server's echoed code before the board loads");
ok("4/5. entering a game lands on the BOARD: no Learning Home stop, and the active room is set first");

// a stored session and an already-signed-in student also skip the lobby. Anchor on the BOOT
// function -- renderProfiles() is called from two places, and the first is not the boot path.
const boot = stripComments(extractFn(html, "initLessons"));
assert(/enterGameDirect\(\)/.test(boot), "a stored session must resume the world on boot");
assert(!/openRooms\(\)/.test(boot), "boot must not route a stored session through the lobby");
const roleBtn = code.slice(code.indexOf('getElementById("studentRoleBtn")'));
assert(/enterGameDirect\(\)/.test(roleBtn.slice(0, 420)),
  "an already-signed-in student picking Student must resume the world");
ok("4b. a stored session and an already-signed-in student both resume the world, skipping the lobby");

// ============ 7-11. every secondary destination is reachable from the board ============
const controls = code.slice(code.indexOf("function renderHudControls"),
                            code.indexOf("function renderHudCard"));
// Phase 12C retargeted this from "Base" to "Empire". Base was a SECOND management hub that could
// only reach the home base; Empire reaches the home base and every territory, so the duplicate was
// retired. The capability is asserted to have survived the move, not merely the label.
// ===== Phase 14A.2: MULTIPLAYER IS NO LONGER A PRIMARY DESTINATION (product decision) =====
// This list used to include "openRooms": "Multiplayer". The Alpha does not want Multiplayer in the
// primary cluster -- a signed-in player is auto-entered into GLOBAL -- so the ENTRY was removed. The
// invariant it protected has been replaced, not dropped: the cluster must not offer Multiplayer,
// and the room/multiplayer capability must still be implemented (asserted immediately below, and in
// tests/alpha_navigation.test.js).
// ===== Phase 14A.4: MY PROGRESS IS NO LONGER A WORLD DESTINATION (product decision) =====
// This list also used to include "openProfileStats": "Profile". Player feedback: learning
// progression belongs to the ACADEMY, which already owns it, and it is not closely related to World
// Conquest. So the World ENTRY was removed and the invariant replaced, not dropped: the World
// cluster must not offer My Progress, and My Progress must remain reachable through the Academy
// (both asserted immediately below). The screen, openProfileStats() and progress authority are
// untouched.
const wanted = { "openLearningHome": "Academy",
                 "openLeaderboard": "Ranking", "openEmpire": "Empire" };
Object.keys(wanted).forEach(fn => {
  assert(controls.indexOf(fn) >= 0, wanted[fn] + " must be reachable from the board HUD (" + fn + ")");
});
assert(controls.indexOf("openRooms") < 0,
  "standalone Multiplayer must be ABSENT from the primary World navigation");
assert(controls.indexOf("openProfileStats") < 0,
  "My Progress must be ABSENT from the primary World navigation (14A.4)");
assert(/function openProfileStats\(\) \{/.test(code) && /showScreen\(screenProfileStats\)/.test(code),
  "...while the My Progress screen itself remains implemented");
assert(/userChip\.addEventListener\("click", \(\) => \{ if \(userName\) openProfileStats\(\); \}\)/.test(code),
  "...and reachable from the account chip, which the Academy shows");
assert(/if \(e\.target && e\.target\.id === "homeProgress"\) \{ openProfileStats\(\); return; \}/.test(code),
  "...as well as from the Academy's own explicit My Progress entry");
assert(/'<button type="button" id="homeProgress">📊 My Progress<\/button>' \+/.test(code),
  "...which is UNCONDITIONAL — a fresh learner sees it too");
assert(!/homeCollection/.test(code),
  "the conditional 'View Collection' label it replaced is gone, not duplicated");
for (const fn of ["function openRooms()", "function openJoin()", "function joinByCode()",
                  "function openMyRoom()", "function enterRoom(", "function enterWorld()",
                  "function withRoom("]) {
  assert(code.indexOf(fn) >= 0, "...while room/multiplayer authority remains implemented: " + fn);
}
assert(/Academy/.test(controls) && /Empire/.test(controls) && /Ranking/.test(controls),
  "the HUD must use the player-facing vocabulary");
// what Base used to do must still be reachable: the home base appears in all three Empire areas,
// and the same building/recruit panel is what opens for it
["empireForces", "empireBuildings", "empireTechnology"].forEach(fn => {
  const body = extractFn(html, fn);
  assert(body.indexOf("HOME_KEY") >= 0, fn + " must cover the home base");
});
assert(/buildingsPanel\(host, HOME_KEY/.test(stripComments(extractFn(html, "openHomeBase"))),
  "the home-base building panel itself is unchanged");
ok("7-11. Academy, Ranking and Empire are reachable from the board HUD, standalone Multiplayer " +
   "and My Progress are not, both remain implemented and reachable elsewhere, and Empire still covers the home " +
   "base that the retired Base hub used to own");

// ============ 12/13. join and create still exist, with game vocabulary ============
assert(/id="joinRoomBtn"/.test(html) && /Join Game/.test(html), "Join Game must exist");
assert(/id="createRoomBtn"/.test(html) && /Create Private Game/.test(html),
  "Create Private Game must exist");
const joinByCode = stripComments(extractFn(html, "joinByCode"));
assert(/enterRoom\(code/.test(joinByCode), "Join Game must enter the joined game");
assert(/game code/i.test(joinByCode) || /Game code/.test(html),
  "the join prompt should ask for a game code");
ok("12/13. Join Game and Create Private Game survive, in player-facing game vocabulary");

// ============ 14. no Course anywhere in create-game ============
const myRoom = stripComments(extractFn(html, "renderMyRoom"));
assert(!/rmCourse/.test(myRoom), "the private-game form must not contain a Course selector");
assert(!/Course</.test(myRoom), "the private-game form must not label a Course field");
assert(!/ROOM_COURSES/.test(code), "the course option list must be retired from executable code");
assert(!/map:\s*box\.querySelector/.test(myRoom),
  "the client must not send a course as the room's map compatibility field");
ok("14. no Course field, no course option list and no course sent when creating a private game");

// ============ 15. no room/map/course choice on the normal entry path ============
for (const gone of ["Enter the World<", "Choose Course", "Choose Map", "mapPicker"]) {
  assert(code.indexOf(gone) < 0, gone + " must not appear on the entry surface");
}
assert(!/Create private room/.test(html) && !/Join room</.test(html),
  "room-management vocabulary must not be the player-facing wording");
ok("15. the normal entry path offers no room, course or map choice");

// ============ 16. logout clears client auth ============
const logout = code.slice(code.indexOf('getElementById("logoutChip")'));
assert(/clearAuth\(\)/.test(logout.slice(0, 300)), "logout must clear client auth");
assert(/showScreen\(screenLanding\)/.test(logout.slice(0, 300)),
  "logout must return to the landing page");
ok("16. logout clears client auth and returns to the landing page");

// ============ 17. the guest decision is pinned ============
const guest = stripComments(extractFn(html, "startGuest"));
assert(/selectProfile\("guest"\)/.test(guest),
  "guests keep the local practice route: they hold no token, and every room route needs one");
assert(!/enterGameDirect/.test(guest) && !/enterRoom/.test(guest),
  "a guest must NOT be routed into a room -- that would need an identity it does not have");
const selProfile = stripComments(extractFn(html, "selectProfile"));
assert(/clearActiveRoom\(\)/.test(selProfile),
  "picking a local profile stays a pre-room surface (Phase 8A boundary)");
ok("17. guests keep the tokenless local practice route and never enter a room");

// ============ 18. teacher/parent/admin paths preserved ============
assert(/getElementById\("teacherRoleBtn"\)\.addEventListener\("click", openTeacher\)/.test(code),
  "the teacher/parent panel must still be reachable from the role screen");
assert(/backFromTeacher/.test(code), "the teacher panel must keep its exit");
assert(/loadAdmin\(\)/.test(code), "the admin path must be preserved");
ok("18. teacher/parent and admin paths are preserved and do not go through the student entry");

// ============ 20. learning stays map-independent ============
for (const gone of ["Pre-A1 -> taiwan", "attackQualificationIds\":", "qualification_required"]) {
  assert(code.indexOf(gone) < 0, gone + " must not be executable client logic");
}
assert(/Academy/.test(html), "the learning surface is presented as the Academy");
assert(!/Unlocks /.test(code) && !/Helps unlock/.test(code),
  "no map-unlock language may return to the learning surface");
ok("20. learning remains map-independent: no unlock language, no qualification gate, no course->map");

// ============ the lobby is now Multiplayer, and its duplicate links are gone ============
assert(/id="hubTitle"/.test(html), "the multiplayer surface keeps its title element");
const openRoomsFn = stripComments(extractFn(html, "openRooms"));
assert(/Multiplayer/.test(openRoomsFn), "the former lobby must present itself as Multiplayer");
assert(/clearActiveRoom\(\)/.test(openRoomsFn),
  "leaving a game for the multiplayer surface must stay the explicit room-exit boundary");
for (const dead of ["lobbyLevelsBtn", "hubStatsBtn", "hubLeaderBtn", "hubEventsBtn"]) {
  assert(code.indexOf(dead) < 0,
    dead + " was retired with the lobby's duplicate links; a listener bound to a removed element " +
    "throws at boot");
}
ok("the lobby is now Multiplayer, keeps the room-exit boundary, and its retired links leave no " +
   "dangling listeners");

console.log("\nAll " + passed + " entry-flow tests passed.");
