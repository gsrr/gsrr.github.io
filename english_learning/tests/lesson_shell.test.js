// Phase 11E — the lesson page belongs to the Academy, and its audio cleans up after itself.
//
//   node tests/lesson_shell.test.js
//
// Before this phase, opening a lesson dropped the learner into the old product: capsules numbered
// "1".."10" that named no activity and implied a difficulty ladder, the local session counter as the
// most prominent progress figure, no indication of which activities count toward mastery, no reward
// moment at all, and a play()/pause() race that raised an unhandled AbortError on every exit.
//
// These assertions read the shipped index.html. Behaviour that only a browser can prove is covered
// by scratchpad/accept_11e.js and scratchpad/audio_probe.js; the server's actual payouts are pinned
// end-to-end by tests/lesson_reward_shell_test.py. What is guarded here is that the client cannot
// drift back to numbering activities, hard-coding reward amounts, or inventing progress.
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
const lessonStart = html.indexOf('<div id="screenLearn"');
assert(lessonStart > 0, "#screenLearn not found");
const shell = stripComments(html.slice(lessonStart, lessonStart + 6000));
function fn(name) {
  const i = code.indexOf("function " + name);
  assert(i >= 0, "function not found: " + name);
  return code.slice(i, i + 3200);
}

// ============ 1. identity: Academy > Course/Campaign > lesson ============
assert(/id="lsCrumb"/.test(shell), "the lesson needs an identity crumb");
assert(/id="learnTitle"/.test(shell), "the lesson title element must survive");
assert(shell.indexOf('id="lsCrumb"') < shell.indexOf('id="learnTitle"'),
  "the crumb must sit above the lesson title");
const ident = fn("lsRenderIdentity");
assert(/Academy/.test(ident), "the crumb must name the Academy");
assert(/courseKindLabel/.test(fn("lsCourseOf")),
  "Campaign/Course must reuse the registry-derived label, not a new rule");
assert(/lessonTitleOf\(a\.file\)/.test(code),
  "the title must still come from the authoritative lessonTitleOf()");
ok("1. identity is Academy > Course/Campaign > lesson, from authoritative data");

// ============ 2. no stale "Level N" anywhere the learner reads ============
assert(!/>Level \d/.test(shell), "no 'Level N' label may be rendered in the lesson shell");
assert(/class="lvl" hidden/.test(shell),
  "the numeric capsule must be hidden (kept in the DOM only so nothing that reads it breaks)");
for (const step of ["Listen", "Read Along", "Quiz", "Tricky Quiz", "Matching", "Reorder",
                    "WH Questions", "Dictation", "Fill in the Blank", "Role-play"]) {
  assert(new RegExp('class="ls-s-nm">' + step.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&") + "<")
    .test(shell), "the stepper must name the activity: " + step);
}
ok("2. every step carries its semantic name and no level number is shown");

// ============ 3. the stepper keeps all existing routing ============
for (let lv = 1; lv <= 10; lv++) {
  assert(new RegExp('data-level="' + lv + '"').test(shell),
    "data-level routing must be preserved for tab " + lv);
}
assert(/class="levelTab ls-step/.test(shell),
  "the stepper must keep the .levelTab class the existing controllers select on");
assert(/data-name="Role-play/.test(shell), "data-name values must be preserved");
assert(/TAB_BY_SCORED/.test(code) && /TAB_BY_KEY/.test(code),
  "the existing activity->tab routing table must be untouched");
ok("3. the stepper is presentation only: data-level, .levelTab and data-name all preserved");

// ============ 4. required vs optional, derived not hard-coded ============
const dec = fn("lsDecorateSteps");
assert(/lsRequiredTabs/.test(dec), "the tags must come from the lesson's required set");
assert(/requiredActivityIds/.test(fn("lsRequiredTabs")),
  "required must be read from requiredActivityIds");
assert(/levelTabForActivity/.test(fn("lsRequiredTabs")),
  "it must map through the existing routing table, not a new one");
assert(/Required/.test(dec) && /Optional/.test(dec), "both states must be labelled");
assert(!/\b5\b/.test(dec.replace(/[\d.]+px/g, "")) && !/\b7\b/.test(dec),
  "the required COUNT must never be hard-coded in the client");
ok("4. Required/Optional is derived from requiredActivityIds, with no count hard-coded");

// ============ 5. authoritative progress leads; the session counter is a footnote ============
assert(/id="lessonProgress"/.test(shell), "the authoritative progress card must be present");
assert(shell.indexOf('id="lessonProgress"') < shell.indexOf('class="ls-practice"'),
  "authoritative mastery must appear BEFORE the session practice counter");
assert(/Practised this session/.test(shell),
  "the local counter must be labelled as session practice, not as progress");
assert(/activity screens/.test(shell),
  "it must say WHAT it counts, so it cannot be mistaken for the mastery denominator");
assert(/body\.lesson-mode > \.card > h1 \{ display: none/.test(html),
  "the reading masthead must step aside on the lesson page too");
assert(/#lessonProgress \.comp-card \{[^}]*linear-gradient/.test(html),
  "the authoritative card must be reskinned in the Academy's language on the lesson page");
assert(/#lessonProgress \.comp-cont \{ display: none; \}/.test(html),
  "the card's Continue must not duplicate the stepper on the page it points at");
assert(/id="progText"/.test(shell) && /id="progFill"/.test(shell),
  "the existing counter elements must survive (updateProgress still writes them)");
assert(/\.ls-practice \{[^}]*font-size: 11\.5px/.test(html),
  "the session counter must be visually demoted");
ok("5. authoritative mastery is primary; the session counter is kept but demoted");

// ============ 6. the reward moment is server-sourced ============
const res = fn("lsShowActivityResult");
assert(/j\.rewarded && j\.rewardAmount/.test(res), "the gate payout must come from the response");
assert(/j\.lessonRewarded && j\.lessonRewardAmount/.test(res),
  "the mastery payout must come from the response");
assert(!/\b160\b/.test(res) && !/\b640\b/.test(res) && !/\b800\b/.test(res),
  "no reward amount may be hard-coded in the lesson shell");
assert(/\+0 Gold/.test(res), "a replay, an optional pass and a failure must say +0 explicitly");
assert(/once per lesson/.test(res), "the +0 case must explain itself truthfully");
assert(/j\.passed/.test(res), "pass/fail must come from the server, never from a local score");
assert(/lsShowActivityResult\(j, aid\)/.test(code),
  "the panel must be fed by the attempt response");
assert(/if \(typeof lsShowActivityResult === "function"\) \{[\s\S]{0,120}try \{ lsShowActivityResult/
  .test(code),
  "a presentation failure must not be able to abort the authoritative handling that follows it");
const feed = code.slice(code.indexOf("lsShowActivityResult(j, aid)") - 900,
                        code.indexOf("lsShowActivityResult(j, aid)") + 120);
assert(/noteLessonCompletion\(j\)/.test(feed),
  "the panel must be shown alongside the existing authoritative sync");
assert(code.indexOf("lsShowActivityResult(j, aid)") <
       code.indexOf('if (!j || !j.ok || !j.passed) return;'),
  "the panel must be reached on FAILING responses too, or +0 could never be shown");
ok("6. the reward moment uses only the server's settlement report, and shows +0 truthfully");

// ============ 7. completion feedback distinguishes the cases ============
assert(/Required activity complete/.test(res), "a required pass must say so");
assert(/Optional practice complete/.test(res), "an optional pass must say so");
assert(/Try again/.test(res), "a failure must offer a retry, not a reward");
assert(/did not pass, so it earned no Gold and no mastery credit/.test(res),
  "a failure must state plainly that nothing was earned");
assert(/Optional practice does not change what mastery requires/.test(res),
  "optional completion must not imply the denominator moved");
ok("7. completion feedback separates required, optional and failed outcomes");

// ============ 8. the next action, chosen by the learner ============
assert(/data-ls-next/.test(res), "there must be a next-activity action");
assert(/Next activity/.test(res), "it must be named");
assert(/Lesson mastered/.test(res), "mastery must be announced");
assert(/data-ls-academy/.test(res), "there must be a route back to the Academy");
assert(!/setTimeout[\s\S]{0,80}openLearningHome/.test(res),
  "the shell must never auto-redirect the learner");
assert(/missingActivityIds/.test(res),
  "the next target must come from the server's own missing list");
ok("8. the next action is explicit, server-derived, and never automatic");

// ============ 9. navigation ============
assert(/id="backToList"/.test(shell), "the primary exit must keep its id");
assert(/← Academy/.test(shell), "the primary exit must name the Academy");
assert(!/← Lessons/.test(shell), "the stale 'Lessons' label must be gone");
assert(/id="lsWorldBtn"/.test(shell), "an authenticated learner gets a direct World route");
assert(/classList\.toggle\("hidden", !\(authToken\(\) && authUser\(\)\)\)/.test(fn("lsRenderNav")),
  "the World route must be hidden for a guest");
assert(!/Lobby/i.test(shell), "no Lobby route in the lesson shell");
assert(/if \(ctx\.to === "home"\) \{ openLearningHome\(\); return; \}/.test(code),
  "Back must still restore the Academy context that opened the lesson");
ok("9. the lesson exits to the Academy, offers World only to an account, and keeps no Lobby");

// ============ 10. guest copy is truthful ============
const guest = fn("lsGuestNoteHTML");
assert(/guest/.test(guest), "the guest must be told they are a guest");
assert(/mastery and Gold are only saved with an account/.test(guest),
  "the guest note must be truthful about persistence");
assert(/el\.innerHTML = card \|\| lsGuestNoteHTML\(\)/.test(code),
  "the guest note must actually be RENDERED, not merely defined");
ok("10. the guest is told plainly that mastery and Gold need an account");

// ============ 11. B9 — the audio fix ============
assert(/function playMedia\(el, what\)/.test(code), "the play() helper must exist");
assert(/function stopMedia\(el\)/.test(code), "the deliberate-stop helper must exist");
const pm = fn("playMedia");
assert(/el\._deliberateStop = false/.test(pm), "a fresh attempt must clear the interruption flag");
assert(/name === "AbortError" && el\._deliberateStop/.test(pm),
  "ONLY an AbortError on a deliberately stopped element may be swallowed");
assert(/console\.warn\("\[audio\] "/.test(pm),
  "every other rejection must be reported, not silently dropped");
assert(!/catch\s*\(\s*\)\s*\{\s*\}/.test(pm), "the handler must not be an empty catch");
assert(/_deliberateStop = true/.test(fn("stopMedia")),
  "stopMedia must mark the element before pausing it");
// no bare play() may remain, and nothing global may be suppressed
const bare = code.match(/(?<!function )\w+\.play\(\)/g) || [];
assert(bare.filter(m => !/el\.play\(\)/.test(m)).length === 0,
  "every play() must go through playMedia: found " + JSON.stringify(bare));
assert(!/unhandledrejection/.test(code),
  "promise errors must not be suppressed globally");
assert(/function stopAllLessonAudio/.test(code),
  "navigation needs one place that silences every lesson audio source");
const all = fn("stopAllLessonAudio");
assert(/synth\.cancel/.test(all) && /stopAudio\(\)/.test(all) && /stopMyRecording/.test(all),
  "it must cover the clip, the synthesiser AND the learner's own recording");
assert(/function stopListenL1\(\) \{ stopAllLessonAudio\(\); finishL1\(\); \}/.test(code),
  "the Back handlers' existing stop path must route through it");
ok("11. audio: deliberate interruptions are handled, real failures are reported, nothing is " +
   "globally suppressed, and navigation silences every source");

// ============ 12. mobile ============
assert(/body\.lesson-mode \{ padding: 8px; \}/.test(html) &&
       /body\.lesson-mode > \.card \{ padding: 12px; \}/.test(html),
  "the lesson page must reclaim the phone gutters");
assert(/classList\.toggle\("lesson-mode", el === screenLearn\)/.test(code),
  "lesson-mode must be set from showScreen");
assert(/\.ls-steps \{[^}]*overflow-x: auto/.test(html),
  "the stepper must scroll inside itself rather than widen the page");
assert(/@media \(max-width: 560px\)[\s\S]{0,1600}\.ls-fb-acts button \{ flex: 1 1 100%/.test(html),
  "the feedback actions must stack full-width on a phone");
assert(/@media \(max-width: 560px\)[\s\S]{0,1600}\.ls-world \{ flex: 1 1 100%/.test(html),
  "the secondary World control must take its own row rather than sit under the user chip");
ok("12. the lesson page is phone-shaped: reclaimed gutters, self-scrolling stepper, stacked actions");

// ============ 13. no activity type was removed ============
for (let lv = 1; lv <= 10; lv++) {
  assert(new RegExp('<div id="level' + lv + '"').test(html),
    "activity container level" + lv + " must still exist");
}
for (const ctl of ["quiz3Ctl", "quiz4Ctl", "matchCtl", "reorderCtl", "whCtl", "dictCtl", "clozeCtl"]) {
  assert(code.indexOf(ctl) >= 0, "grader controller must survive: " + ctl);
}
assert(/roleplay/i.test(code) && /read_along|stt/i.test(code),
  "role-play and read-along must survive");
assert(/\/api\/learning\/attempt/.test(code) && /\/api\/learning\/matching\/start/.test(code) &&
       /\/api\/learning\/roleplay\/start/.test(code) && /\/api\/stt/.test(code),
  "no grading route may change");
ok("13. all ten activities, their controllers and their routes are preserved");

console.log("\nAll " + passed + " lesson-shell tests passed.");
