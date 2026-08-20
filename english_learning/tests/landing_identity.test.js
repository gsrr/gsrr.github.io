// Phase 11C — the entry surfaces belong to WORLD CONQUEST, not to a reading website.
//
//   node tests/landing_identity.test.js
//
// The board says WORLD CONQUEST; before this phase the entry page said "English Reading", so the
// product introduced itself as one thing and handed the player another. These assertions read the
// shipped index.html, so a regression that re-promotes the reading identity, reintroduces a
// room/course choice on the landing page, or drops the returning-player loading state fails here.
"use strict";
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
let passed = 0;
function ok(name) { passed++; console.log("  ok -", name); }

function section(id) {
  const i = html.indexOf('<div id="' + id + '"');
  assert(i >= 0, "screen not found: " + id);
  // slice to the next top-level screen div, which is enough for these assertions
  const rest = html.slice(i + 1);
  const j = rest.indexOf('    <div id="screen');
  return rest.slice(0, j > 0 ? j : 4000);
}
function stripComments(src) {
  return src.replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\//g, "")
            .replace(/^[ \t]*\/\/.*$/gm, "");
}
const landing = stripComments(section("screenLanding"));
const acct = stripComments(section("screenStudentAcct"));
const code = stripComments(html);

// ============ 1. the landing page is World Conquest ============
assert(/World Conquest/i.test(landing), "the landing page must name the product");
assert(/brand-t/.test(landing), "the product name must use the brand plaque, not body copy");
const brandIdx = landing.indexOf("brand-t");
const academyIdx = landing.indexOf("brand-academy");
assert(brandIdx >= 0 && academyIdx > brandIdx,
  "World Conquest must come BEFORE the academy line in the document order");
// the reading masthead must not compete with the product name on the entry surfaces
assert(/body\.entry-mode > \.card > h1, body\.booting > \.card > h1 \{ display: none/.test(html),
  "the English Reading masthead must be suppressed on the landing/account/boot surfaces");
ok("1. the landing page leads with WORLD CONQUEST in the brand plaque");

// ============ 2. English Reading is demoted, not deleted ============
assert(/English Reading/.test(landing), "English Reading should still be named as the Academy");
assert(/brand-academy/.test(landing),
  "English Reading must appear in the SUBORDINATE academy line");
const acadLine = landing.slice(landing.indexOf("brand-academy"), landing.indexOf("brand-academy") + 160);
assert(/English Reading/.test(acadLine), "the academy line is where English Reading belongs now");
assert(!/Fun English reading for ages/.test(landing),
  "the old top-level reading masthead copy must be gone");
ok("2. English Reading is demoted to the supporting Academy line, not deleted");

// ============ 3. one obvious primary student action ============
assert(/id="landLoginBtn"[^>]*class="btn-play"/.test(landing),
  "the primary action must be the play/login button");
assert(/id="landTryBtn"[^>]*class="btn-guest"/.test(landing),
  "the guest action must be the secondary style");
assert(landing.indexOf('id="landLoginBtn"') < landing.indexOf('id="landTryBtn"'),
  "the primary action must precede the secondary one");
ok("3. exactly one primary action (Play - Log in or Sign up), with guest clearly secondary");

// ============ 4. authentication is untouched ============
for (const id of ["sUser", "sPass", "sLoginBtn", "sRegUser", "sRegPass", "sRegisterBtn",
                  "toRegister", "toLogin"]) {
  assert(html.indexOf('id="' + id + '"') >= 0, "the account form must keep #" + id);
}
assert(/\/api\/student\/" \+ path/.test(code) || /\/api\/student\//.test(code),
  "the student auth endpoint must be unchanged");
assert(/getElementById\("sLoginBtn"\)\.addEventListener\("click", \(\) => sAuth\("login"\)\)/.test(code),
  "login must still call sAuth('login')");
assert(/getElementById\("sRegisterBtn"\)\.addEventListener\("click", \(\) => sAuth\("register"\)\)/.test(code),
  "registration must still call sAuth('register')");
ok("4. the account form, its ids, its handlers and the auth endpoint are all unchanged");

// ============ 5. the guest path and its copy stay truthful ============
assert(/Try the Academy as a guest/i.test(landing),
  "the guest button must say what a guest actually gets");
assert(!/Try it free<\/button>/.test(landing), "the vague old guest copy should be replaced");
assert(/guest can practise lessons on this device/i.test(landing),
  "the note must be truthful: a guest practises locally and does not get the persistent world");
assert(/startGuest/.test(code) && /selectProfile\("guest"\)/.test(code),
  "the guest route itself must be unchanged");
ok("5. guest copy is truthful about local practice, and the guest route is unchanged");

// ============ 6. teacher/parent access is discoverable and not redirected ============
assert(/id="landRoleBtn"/.test(landing), "the landing page must offer a teacher/parent entry");
assert(/For teachers/i.test(landing), "that entry must say who it is for");
assert(/getElementById\("landRoleBtn"\)\.addEventListener\("click", \(\) => showScreen\(screenRole\)\)/
  .test(code), "it must open the role screen, not the student world");
assert(/getElementById\("teacherRoleBtn"\)\.addEventListener\("click", openTeacher\)/.test(code),
  "the teacher panel must still open from the role screen");
ok("6. teacher/parent entry is discoverable from the landing page and never routed into the world");

// ============ 7/8. no room, course or map choice on the entry surfaces ============
for (const banned of ["Create Room", "Join Room", "Create private room", "Join room",
                      "Room Code", "room code", "Choose Course", "Choose Map", "Enter the World"]) {
  assert(landing.indexOf(banned) < 0, "the landing page must not offer: " + banned);
  assert(acct.indexOf(banned) < 0, "the account page must not offer: " + banned);
}
assert(!/<select/.test(landing) && !/<select/.test(acct),
  "no selector of any kind belongs on the entry surfaces");
assert(!/Pre-A1 → B1/.test(landing), "the CEFR ladder is Academy detail, not an entry promise");
ok("7/8. neither entry surface offers a room, a course, a map or any other pre-game choice");

// ============ 9. authenticated direct resume still goes to the world ============
assert(/enterGameDirect\(\)/.test(code), "the direct-resume entry must still exist");
const initLessons = code.slice(code.indexOf("async function initLessons"));
assert(/enterGameDirect\(\)/.test(initLessons.slice(0, 3000)),
  "a stored session must still resume the world on boot");
ok("9. an authenticated visitor still resumes World Conquest directly (11B contract intact)");

// ============ 10. the loading state removes the misleading login flash ============
assert(/id="screenBoot"/.test(html), "there must be a dedicated boot screen");
assert(/Loading your world/i.test(html), "the boot screen must say what is happening");
assert(/body\.booting #screenLanding \{ display: none/.test(html),
  "the landing page must be suppressed while a session resolves");
assert(/localStorage\.getItem\("auth:token"\)/.test(html) &&
       /classList\.add\("booting"\)/.test(html),
  "the decision must be made synchronously from the stored token, before first paint");
const showScreenFn = code.slice(code.indexOf("function showScreen"), code.indexOf("function showScreen") + 400);
assert(/classList\.remove\("booting"\)/.test(showScreenFn),
  "the first real screen must clear the boot state, so no path can strand it");
assert(/World Conquest/i.test(html.slice(html.indexOf('id="screenBoot"'),
                                        html.indexOf('id="screenBoot"') + 500)),
  "the boot screen must carry the product identity too");
ok("10. a stored session shows a World Conquest loading plaque instead of a stale login CTA");

// ============ 11. the entry surfaces are phone-shaped ============
assert(/@media \(max-width: 560px\)[\s\S]{0,700}\.btn-play, \.btn-guest \{ min-width: 0; width: 100%/
  .test(html), "the entry buttons must go full-width on a phone rather than overflow");
assert(/\.hero-wrap \{[^}]*max-width: 560px/.test(html) &&
       /@media \(max-width: 560px\)[\s\S]{0,700}\.hero-wrap \{ max-width: 100%/.test(html),
  "the hero must be bounded on desktop and fluid on a phone");
assert(/\.hero-svg \{[^}]*width: 100%[^}]*height: auto/.test(html),
  "the hero art must scale with its container");
ok("11. the entry surfaces are responsive: fluid hero and full-width actions under 560px");

// ============ the hero is decoration, never gameplay ============
// slice from the hero forwards -- indexOf("</svg>") from position 0 finds an earlier inline icon
const heroStart = html.indexOf('class="hero-wrap"');
// comments inside the hero block legitimately MENTION world.svg to say it is not used, so strip
// them before asserting -- the same rule the other checks follow.
const hero = stripComments(html.slice(heroStart, html.indexOf("</svg>", heroStart) + 6));
assert(/pointer-events: none/.test(html.slice(html.indexOf(".hero-svg"), html.indexOf(".hero-svg") + 200)),
  "the hero art must be pointer-events:none");
assert(/aria-hidden="true"/.test(hero), "the hero art must be hidden from assistive tech");
assert(!/geo-region/.test(hero) && !/world\.svg/.test(hero),
  "the hero must NOT reuse the interactive board or maps/world.svg");
assert(!/id="/.test(hero.replace(/id="screen[^"]*"/g, "")),
  "the hero must not introduce identified, addressable elements");
ok("the hero is pure decoration: no board reuse, no world.svg, no pointer events, aria-hidden");

console.log("\nAll " + passed + " landing-identity tests passed.");
