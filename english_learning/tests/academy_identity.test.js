// Phase 11D — the Academy is a module of WORLD CONQUEST, not a reading website beside it.
//
//   node tests/academy_identity.test.js
//
// The Academy worked before this phase but still looked and behaved like the old product: an
// "English Reading" h1 above a small "Academy" tab, one course expanded with the other four hidden
// behind a disclosure, and all 57 lessons flattened into a single list. These assertions read the
// shipped index.html, so a regression that re-promotes the reading identity, re-hides the
// curriculum, hard-codes a lesson count, implies Gold can be farmed by replaying, or offers a guest
// a world they cannot enter fails here.
//
// Behaviour that only a browser can prove (the round trip, the guest journey, mobile overflow) is
// pinned by asserting the CODE that implements it; scratchpad/accept_11d.js exercises it for real.
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
function screen(id) {
  const i = html.indexOf('<div id="' + id + '"');
  assert(i >= 0, "screen not found: " + id);
  const rest = html.slice(i + 1);
  const j = rest.indexOf('    <div id="screen');
  return rest.slice(0, j > 0 ? j : 6000);
}
const home = stripComments(screen("screenHome"));
const code = stripComments(html);
// the renderer, sliced out so assertions cannot accidentally match some other screen's code
const rStart = code.indexOf("function renderLearningHome()");
assert(rStart > 0, "renderLearningHome not found");
const render = code.slice(rStart, code.indexOf("function contentPathForLessonId", rStart));
assert(render.length > 500, "renderLearningHome slice looks wrong");

// ============ 1. ACADEMY is the top identity ============
assert(/brand-plaque/.test(home) && /brand-t/.test(home),
  "the Academy must lead with the shared brand plaque, not a small tab label");
const plaque = home.slice(home.indexOf("brand-plaque"), home.indexOf("brand-plaque") + 200);
assert(/>Academy</i.test(plaque), "the plaque must name the Academy");
assert(/body\.academy-mode > \.card > h1 \{ display: none/.test(html),
  "the reading h1 masthead must step aside on the Academy, or it re-inverts the hierarchy");
assert(/classList\.toggle\("academy-mode", el === screenHome\)/.test(code),
  "academy-mode must be set from showScreen so every routing path agrees");
ok("1. ACADEMY is the top identity, and the old h1 masthead no longer sits above it");

// ============ 2. English Reading is subordinate, not deleted ============
assert(/ac-sub/.test(home), "the Academy needs its supporting identity line");
const sub = home.slice(home.indexOf("ac-sub"), home.indexOf("ac-sub") + 240);
assert(/English Reading/.test(sub), "English Reading belongs in the supporting line");
assert(/Gold/.test(sub), "the supporting line should say what learning is FOR");
assert(home.indexOf("brand-plaque") < home.indexOf("ac-sub"),
  "the Academy name must come before the English Reading line");
ok("2. English Reading is named as the supporting identity, below the Academy");

// ============ 3. no unlock / conquest-entitlement copy ============
for (const banned of ["Unlock territory", "Unlock map", "Required for conquest", "unlocks",
                      "Unlocks", "lets you claim", "enter Taipei"]) {
  assert(home.indexOf(banned) < 0, "the Academy must not promise: " + banned);
  assert(render.indexOf(banned) < 0, "the Academy renderer must not emit: " + banned);
}
assert(!/territoriesForLesson|lessonWorldLineHTML/.test(render),
  "the retired territory-unlock line must not come back");
ok("3. no unlock, territory or map-entitlement copy anywhere in the Academy");

// ============ 4/5. all five families, Campaign vs Course preserved ============
assert(/acFamilies\(\)/.test(render), "the renderer must build the family list");
assert(/F\.fams\.forEach\(f => \{ out \+= acFamilyCardHTML/.test(render),
  "EVERY family must get a card -- not the first with the rest behind a disclosure");
assert(!/more campaign/i.test(render),
  "the '4 more campaigns' disclosure that hid Pre-A1 must not return");
assert(/courseKindLabel/.test(code) && /courseIsCampaign/.test(code),
  "Campaign/Course must still be derived from the registry's grants, never hard-coded");
assert(/function courseIsCampaign\(cid\)[\s\S]{0,400}grants/.test(code),
  "courseIsCampaign must keep deciding from `grants`");
assert(!/taipei/i.test(render) || /split\("\."\)\.pop\(\)/.test(render),
  "no course id may be hard-coded in the renderer");
ok("4/5. every family gets a card, and Campaign/Course is still derived from the registry");

// ============ 6. lesson counts come from authoritative data, never literals ============
assert(!/\b57\b/.test(render) && !/\b24\b/.test(render.replace(/[\d.]+px/g, "")),
  "lesson counts must never be hard-coded in the renderer");
assert(/camps\[cid\]\.lessonIds/.test(code),
  "a campaign's lessons must come from the server's own ordered lessonIds array");
assert(/\(camps\[cid\]\.lessonIds \|\| \[\]\)\s*\n?\s*\.filter\(l => rows\[l\]\)/.test(code),
  "homeCampaigns must WALK lessonIds (ordered), not filter the progress map's incidental key order");
ok("6. lesson counts and order come from the server's ordered lessonIds, not from literals");

// ============ 7/8. the authoritative denominator, uninflated ============
assert(/requiredActivityIds/.test(render),
  "the denominator must be requiredActivityIds");
assert(!/activityIds\b(?!.*required)/.test(render.replace(/requiredActivityIds/g, "")
        .replace(/completedActivityIds/g, "").replace(/missingActivityIds/g, "")),
  "the Academy must not count ALL activities -- optional ones would inflate the denominator");
assert(/function acRequiredNote/.test(code) &&
       /requiredActivityIds \|\| \[\]\)\.length/.test(code),
  "the per-family 'required activities per lesson' note must read requiredActivityIds");
assert(/activePolicyCompleted === true/.test(render),
  "mastery must be the authoritative activePolicyCompleted, not a local counter");
ok("7/8. mastery uses activePolicyCompleted and the denominator uses requiredActivityIds only");

// ============ 9. Gold copy cannot be read as a replay reward ============
assert(/once per lesson, not per replay/.test(render),
  "the reward line must say the reward is once per lesson");
// Phase 14A.10B: a PASS no longer pays gold at all -- it earns a REWARD GAME -- so the copy
// advertises the game for the pass and the server's own figure for mastery. The invariant that
// matters is unchanged: no reward AMOUNT is hard-coded in the client.
assert(/reward game/.test(render), "the pass half of the loop must promise a reward game");
assert(/ec\.masteryGold/.test(render),
  "the mastery amount must come from the economy payload, not be hard-coded");
assert(!/Pass the quiz \+/.test(render) && !/passGold/.test(render),
  "and no direct pass-gold promise may survive anywhere in the Academy copy");
assert(!/\b160\b/.test(render) && !/\b640\b/.test(render) && !/\b800\b/.test(render),
  "reward constants must never be hard-coded in the client");
ok("9. Gold copy is server-sourced and explicitly once-per-lesson, never per replay");

// ============ 10. Continue uses the existing resolver ============
assert(/function continueTargetIn\(list\)/.test(code),
  "the STEP 5 rule must exist in exactly one place");
assert(/function homeContinueTarget\(\)[\s\S]{0,400}continueTargetIn\(all\)/.test(code),
  "the page-level Continue must call the shared resolver");
assert(/data-home-continue/.test(render),
  "Continue must go through the existing delegated handler");
assert((code.match(/const started = list\.find/g) || []).length === 1,
  "there must be exactly ONE definition of the progression rule (no second algorithm)");
assert(/continueTargetIn\(f\.list\)/.test(code),
  "a per-family Continue must reuse the same resolver on that family's lessons");
ok("10. Continue Learning reuses the single existing progression resolver");

// ============ 11. the World return is explicit ============
assert(/id="backFromHome"/.test(home), "the Academy must keep its return control");
assert(/World Conquest/.test(home.slice(home.indexOf("backFromHome") - 80,
                                       home.indexOf("backFromHome") + 140)),
  "the return must name World Conquest, not a generic Home or Map");
assert(/getElementById\("backFromHome"\)\.addEventListener/.test(code) &&
       /goToGameMap\(\)/.test(code), "its handler must still open the game world");
assert(!/Lobby/i.test(home), "no Lobby route on the Academy");
ok("11. the Academy returns explicitly to World Conquest, with no Lobby route");

// ============ 12/13. the guest Academy, without a false world ============
assert(/function acGuestFamilies/.test(code),
  "a guest has no account-scoped campaigns, so the Academy must build families from the registry");
assert(/openLearningHome\(\)/.test(code.slice(code.indexOf("function startGuest"),
                                             code.indexOf("function startGuest") + 320)),
  "a guest must actually REACH the Academy -- it was previously unreachable for them");
assert(/back\.classList\.toggle\("hidden", !tracked\)/.test(render),
  "the World return must be hidden for a guest who cannot enter the world");
assert(/practising as a <b>guest<\/b>/.test(render),
  "the guest note must say plainly that this is guest practice");
assert(/progress, mastery and Gold need an account/.test(render),
  "the guest note must be truthful about what requires an account");
assert(/tracked \? homeContinueTarget\(\) : null/.test(render),
  "no Continue target may be invented for a guest with no authoritative progress");
ok("12/13. the guest Academy works, and is offered no world and no invented progress");

// ============ 14. the authenticated round trip ============
assert(/lessonReturnTo = \{ to: "home" \}/.test(code),
  "a lesson opened from the Academy must remember to return there");
assert(/if \(ctx\.to === "home"\) \{ openLearningHome\(\); return; \}/.test(code),
  "Back from a lesson must return to the Academy");
const openHome = code.slice(code.indexOf("function openLearningHome"),
                            code.indexOf("function openLearningHome") + 700);
assert(/refreshLearning\(renderLearningHome\)/.test(openHome) &&
       /loadEconomy\(renderLearningHome\)/.test(openHome),
  "returning to the Academy must re-fetch progress AND economy so mastery and Gold refresh");
ok("14. Academy -> lesson -> Academy refreshes authoritative progress and Gold");

// ============ 15. mobile ============
assert(/body\.academy-mode \{ padding: 8px; \}/.test(html) &&
       /body\.academy-mode > \.card \{ padding: 12px; \}/.test(html),
  "the Academy must reclaim the page gutters on a phone as the entry screens do");
assert(/@media \(max-width: 560px\)[\s\S]{0,900}\.ac-card \{ border-width: 2px; \}/.test(html),
  "the Academy needs a phone breakpoint");
assert(/\.ac-card \{ margin: 0 0 12px;/.test(html),
  "course cards must stack in one column (block flow), never a horizontal strip");
assert(!/\.ac-card[^{]*\{[^}]*display:\s*inline/.test(html),
  "course cards must not be laid out inline");
ok("15. the Academy is phone-shaped: reclaimed gutters, one column, no overflow");

// ============ decoration is never gameplay ============
const decoStart = home.indexOf('class="ac-deco"');
assert(decoStart > 0, "the Academy decoration must exist");
const deco = home.slice(decoStart, home.indexOf("</svg>", decoStart) + 6);
assert(/aria-hidden="true"/.test(deco), "the decoration must be hidden from assistive tech");
assert(/pointer-events: none/.test(html.slice(html.indexOf(".ac-deco"),
                                              html.indexOf(".ac-deco") + 220)),
  "the decoration must be pointer-events:none");
assert(!/id="/.test(deco), "the decoration must introduce no addressable elements");
assert(!/geo-region/.test(deco) && !/world\.svg/.test(deco),
  "the Academy must NOT reuse territory map geometry as decoration");
ok("decoration only: aria-hidden, pointer-events:none, no ids, no territory geometry");

console.log("\nAll " + passed + " academy-identity tests passed.");
