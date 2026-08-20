// Phase 11F — My Progress reports what the server verified, and the management surfaces stop
// looking like a different application.
//
//   node tests/progress_admin_shell.test.js
//
// Before this phase My Progress was made almost entirely of LOCAL practice counters: Phase 6D.1 gave
// campaign progress a single owner and stripped mastery from here, so a learner asking "how am I
// doing?" saw device-local numbers and nothing the server had verified — with a "change map / level ·
// rooms · leaderboard" button as the page's first control. The teacher panel wore the old web
// styling and its Back dropped a teacher into the student Multiplayer lobby.
//
// These assertions read the shipped index.html. Browser behaviour is covered by
// scratchpad/accept_11f.js. What is guarded here is that the two kinds of number can never be merged
// again, that the retired duplicates cannot come back, and that no management element is lost.
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
let passed = 0;
function ok(name) { passed++; console.log("  ok -", name); }
function stripComments(src) {
  return src.replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\//g, "")
            .replace(/^[ \t]*\/\/.*$/gm, "");
}
const code = stripComments(html);
function screen(id) {
  const i = html.indexOf('<div id="' + id + '"');
  assert(i >= 0, "screen not found: " + id);
  const rest = html.slice(i + 1);
  const j = rest.indexOf('    <div id="screen');
  return stripComments(rest.slice(0, j > 0 ? j : 5000));
}
function fn(name) {
  const i = code.indexOf("function " + name);
  assert(i >= 0, "function not found: " + name);
  return code.slice(i, i + 3000);
}
const prog = screen("screenProfileStats");
const teach = screen("screenTeacher");
const level = screen("screenLevel");
const render = fn("renderProfileStats");

// ============ 1. My Progress identity ============
assert(/brand-plaque/.test(prog) && /brand-t/.test(prog),
  "My Progress must lead with the shared plaque, not a small tab label");
assert(/>My Progress</i.test(prog), "it must name itself");
assert(/mp-sub/.test(prog), "it needs a supporting line");
const sub = prog.slice(prog.indexOf("mp-sub"), prog.indexOf("mp-sub") + 200);
assert(/mastery/i.test(sub) && /achievements/i.test(sub),
  "the supporting line must say it holds mastery and achievements, not generic stats");
assert(/body\.progress-mode > \.card > h1, body\.admin-mode > \.card > h1 \{ display: none/.test(html),
  "the reading masthead must step aside here as it does on the Academy and lesson pages");
ok("1. My Progress carries its own identity and is not called generic Stats");

// ============ 2/3. authoritative first, practice clearly secondary ============
const iMast = render.indexOf('"mp-h">Mastery');
const iAward = render.indexOf('"mp-h">Academy awards');
const iPract = render.indexOf('"mp-h">Practice on this device');
assert(iMast > 0 && iAward > iMast && iPract > iAward,
  "order must be Mastery -> Academy awards -> Practice");
assert(/mpFamilySummaryHTML\(\)/.test(render), "the authoritative roll-up must be rendered");
// compare positions inside the ASSIGNMENT -- statCards is declared earlier in the function, so
// searching the whole body would find its declaration rather than where it is emitted.
const assign = render.slice(render.indexOf("statsBody.innerHTML"));
assert(assign.indexOf("mpFamilySummaryHTML()") > 0 &&
       assign.indexOf("mpFamilySummaryHTML()") < assign.indexOf("statCards"),
  "the authoritative figures must be emitted BEFORE the local practice figures");
assert(/mp-practice/.test(render), "the practice figures must live in their own block");
assert(/statCards \+ badgeHtml \+ levelHtml/.test(assign) &&
       /mp-practice[\s\S]{0,700}statCards \+ badgeHtml \+ levelHtml/.test(assign),
  "every local counter must be INSIDE the practice block, not loose on the page");
assert(/not mastery/.test(render) && /this device/.test(render),
  "the practice block must state that it is not mastery and is device-local");
ok("2/3. authoritative mastery and awards lead; every local counter is nested and labelled");

// ============ 4. the five families, from the same source as the Academy ============
const famFn = fn("mpFamilySummaryHTML");
assert(/acFamilies\(\)/.test(famFn),
  "the family list must come from the same resolver the Academy uses, not a second one");
assert(/activePolicyCompleted === true/.test(famFn),
  "mastery counts must be the authoritative activePolicyCompleted");
assert(/courseKindLabel|f\.kind/.test(famFn), "Campaign/Course must be carried through");
assert(!/\b57\b/.test(famFn) && !/\b24\b/.test(famFn.replace(/[\d.]+px/g, "")),
  "no lesson count may be hard-coded");
assert(/verified by the server/.test(famFn),
  "the roll-up must say who verified it, so it cannot be read as a local tally");
assert(!/data-home-lesson|ac-row/.test(famFn),
  "My Progress must NOT reproduce the Academy's lesson catalogue");
assert(/\.stats-det:not\(\[open\]\) \.lesson-row/.test(html),
  "the by-level disclosure must actually collapse -- an explicit display on its rows escapes it");
ok("4. five family summaries from the Academy's own resolver, with no duplicated catalogue");

// ============ 5/6. achievements are Academy awards, never entitlements ============
assert(/achievementCabinetHTML\(\)/.test(render),
  "the server-granted award cabinet must still be shown");
assert(/Academy awards/.test(render), "and framed as Academy awards");
for (const banned of ["Unlocks territory", "Unlocks map", "Required for conquest",
                      "unlocks territory", "lets you claim"]) {
  assert(prog.indexOf(banned) < 0, "My Progress must not say: " + banned);
  assert(render.indexOf(banned) < 0, "the renderer must not emit: " + banned);
}
ok("5/6. qualifications are presented as Academy awards, with no conquest-unlock wording");

// ============ 7. a registered student does not need the legacy grid as a hub ============
assert(/id="pickLevelOpen"/.test(render), "the level picker must remain reachable");
assert(/Level picker &amp; checkpoint boss/.test(render),
  "its label must describe what is actually left there");
assert(!/rooms · leaderboard/.test(render) && !/Change map \/ level/.test(render),
  "the old hub label must be gone");
assert(/mp-secondary/.test(render), "and it must be a secondary control, not the page's first action");
ok("7. the legacy grid is a secondary level-picker route, no longer a hub");

// ============ 8/9. the duplicate social controls are gone, Events relocated ============
assert(level.indexOf('id="openRoomsBtn"') < 0, "Competition Rooms must be gone from the grid");
assert(level.indexOf('id="openLeaderBtn"') < 0, "Leaderboard must be gone from the grid");
assert(level.indexOf('id="openEventsBtn"') < 0, "Events must be gone from the grid");
// and their listeners with them -- binding to a removed element throws at boot
assert(!/getElementById\("openRoomsBtn"\)\.addEventListener/.test(code),
  "the removed Competition Rooms listener must go too");
assert(!/getElementById\("openLeaderBtn"\)\.addEventListener/.test(code),
  "the removed Leaderboard listener must go too");
assert(!/getElementById\("openEventsBtn"\)\.addEventListener/.test(code),
  "the removed Events listener must go too");
// nothing may be orphaned: all three actions keep a home
assert(/icoBtn\("\\u2694\\uFE0F", "Multiplayer/.test(code) || /"Multiplayer \\u2014 join or host a game", openRooms/.test(code),
  "Multiplayer must remain a HUD control");
assert(/"Ranking", openLeaderboard/.test(code), "Ranking must remain a HUD control");
assert(/"World events", openEvents/.test(code),
  "Events had no other route, so it must have been RELOCATED to the HUD, not deleted");
assert(/function openEvents\(\)/.test(code), "openEvents itself must be untouched");
ok("8/9. the two duplicates are retired and Events was relocated rather than orphaned");

// ============ 10/11. teacher/parent preserved ============
for (const id of ["acctUser", "acctPass", "acctLoginBtn", "acctRegisterBtn", "acctRefreshBtn",
                  "acctCode", "roomSetup", "dashboard", "acctMsg", "acctPanel", "acctTeacher"]) {
  assert(teach.indexOf('id="' + id + '"') >= 0, "the teacher panel must keep #" + id);
}
assert(/tp-t/.test(teach) && /TEACHER \/ PARENT|Teacher \/ Parent/i.test(teach),
  "the panel must identify itself");
assert(/English Reading Academy/.test(teach), "with the Academy as its supporting line");
assert(/#screenTeacher \.dict-play/.test(html) && /#screenTeacher \.acct-form input/.test(html),
  "the restyle must be SCOPED to the management screens, leaving the student auth form alone");
assert(!/^\s*\.acct-form input \{[^}]*rgba\(20,14,8/m.test(html),
  "the shared .acct-form must not have been restyled globally");
assert(/\/api\/admin\/overview/.test(code) && /function loadAdmin/.test(code),
  "admin routes must be untouched");
assert(/function renderDashboard/.test(code) && /studentCardsHTML/.test(code),
  "the roster renderer must be untouched");
ok("10/11. every teacher/parent element, route and renderer is preserved; the restyle is scoped");

// ============ 12/13. returns ============
assert(/const PROFILE_BACK_LABEL = \{ home: "← Academy", map: "← World Conquest"/.test(code),
  "the student's return must name the real surfaces");
assert((code.match(/PROFILE_BACK_LABEL/g) || []).length === 2,
  "there must be exactly ONE return-label mechanism (declaration + use)");
assert(/getElementById\("backFromTeacher"\)\.addEventListener\([\s\S]{0,120}showScreen\(screenRole\)/
  .test(code), "a teacher's Back must go to the role menu");
assert(!/backFromTeacher"\)\.addEventListener[\s\S]{0,120}openRooms\(\)/.test(code),
  "a teacher must never be dropped into the student Multiplayer lobby");
assert(/Role menu/.test(teach), "and the control must say where it goes");
ok("12/13. the student returns to World Conquest; the teacher returns to the role menu");

// ============ 14. mobile ============
assert(/body\.progress-mode \{ padding: 8px; \}/.test(html) &&
       /body\.admin-mode \{ padding: 8px; \}/.test(html),
  "both surfaces must reclaim the phone gutters");
assert(/classList\.toggle\("progress-mode", el === screenProfileStats\)/.test(code) &&
       /classList\.toggle\("admin-mode", el === screenTeacher \|\| el === screenAdmin\)/.test(code),
  "the layout modes must be set from showScreen");
assert(/\.mp-fam \{ margin: 0 0 9px;/.test(html),
  "family cards must stack in one column (block flow)");
assert(/@media \(max-width: 560px\)[\s\S]{0,2600}\.tp-btn \{ width: 100%; \}/.test(html),
  "management buttons must go full-width on a phone");
assert(/\.ac-back \{ font-size: 11\.5px; padding: 6px 10px; min-height: 38px; \}/.test(html),
  "the compact back control must keep a comfortable tap target");
ok("14. both surfaces are phone-shaped with comfortable tap targets");

console.log("\nAll " + passed + " progress/admin-shell tests passed.");
