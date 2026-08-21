// Phase 12B.2 — the typed Read Along client is an INPUT accommodation, not a bypass.
//
//   node tests/read_along_typed_client.test.js
//
// The server already refuses a typed submission from an account whose mode is "speech", so the UI is
// not the security boundary. What the UI *must* get right is different: it must never reach for a
// microphone in typed mode, never call the speech endpoint, never start the timeout reconciliation
// that only makes sense for a slow transcriber, never compute a score or a Gold amount itself, and
// never offer an educator a control that cannot possibly be authorized. It must also be operable
// from a keyboard and labelled for a screen reader, since the learners who need it are exactly the
// learners least able to work around a control that is mouse-only or unlabelled.
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
function slice(from, to, label) {
  const i = code.indexOf(from);
  assert(i > 0, "not found: " + (label || from));
  const j = code.indexOf(to, i + from.length);
  assert(j > i, "end marker not found for " + (label || from));
  return code.slice(i, j);
}
const typedFn = slice("function submitTypedReading", "typedCheckBtn.addEventListener", "submitTypedReading");
const renderShadow = slice("function renderShadow", "\n  listenBtn.addEventListener", "renderShadow");
const cards = slice("function studentCardsHTML", "\n  function renderDashboard", "studentCardsHTML");
const dash = slice("function renderDashboard", "\n  function renderAdmin", "renderDashboard");
const level2 = slice('<div id="level2"', '<div id="level3"', "#level2 markup");

// ================= 1. the permitted mode comes from the server, and defaults to speech =================
assert(/let myReadAlongMode = "speech";/.test(code),
  "the mirror must start as speech");
assert(/myReadAlongMode = \(j && j\.readAlongMode === "typed"\) \? "typed" : "speech";/.test(code),
  "the mode must be read from the server response, with anything else meaning speech");
assert(/if \(!t\) \{ myQualifications = new Set\(\); myReadAlongMode = "speech";/.test(code),
  "signing out must return the mirror to speech");
assert(!/localStorage[^\n]*readAlongMode|readAlongMode[^\n]*localStorage/.test(code),
  "the mode must never be cached client-side where a learner could edit it");
ok("1. the permitted input mode is mirrored from /api/learning/state, defaults to speech, is never " +
   "persisted locally, and resets on logout");

// ================= 2. typed mode never touches the audio path =================
for (const forbidden of ["MediaRecorder", "mediaDevices", "getUserMedia", "/api/stt",
                         "sttScheduleResync", "sttSupersedeResync", "STT_REQUEST_TIMEOUT_MS",
                         "AbortController", "recordings["]) {
  assert(typedFn.indexOf(forbidden) === -1,
    "the typed path must not reference " + forbidden);
}
assert(/fetch\(withRoom\("\/api\/learning\/read-along\/typed\?token="/.test(typedFn),
  "the typed path must post to its own endpoint, carrying the room like the speech path does");
assert(/if \(readAlongTypedAllowed\(\)\) return;/.test(code),
  "the record button must refuse to run in typed mode even if it is somehow activated");
ok("2. the typed path invokes no MediaRecorder, requests no microphone, never calls /api/stt and " +
   "never starts timeout reconciliation; the record button itself refuses in typed mode");

// ================= 3. the browser computes no score, no pass and no Gold =================
assert(/sttAuthPct = d\.activityPct;/.test(typedFn) && /pronScores\[sIdx\] = d\.score;/.test(typedFn),
  "the displayed score must be the server's");
assert(/if \(!d \|\| !d\.authoritative\) throw/.test(typedFn),
  "a response that is not authoritative must be treated as a failure, never as a pass");
assert(!/\b(160|640|PASS_GOLD|MASTERY_GOLD)\b/.test(typedFn),
  "no reward amount may appear in the typed path");
assert(!/(>=|>)\s*80|PASS_MARK/.test(typedFn),
  "the typed path must not decide the pass mark itself");
assert(/noteLessonCompletion\(d\)/.test(typedFn),
  "lesson completion must go through the existing server-driven notifier");
ok("3. the typed path renders the server's score, gates on d.authoritative, and contains no " +
   "threshold, no reward amount and no client-side pass decision");

// ================= 4. the input is labelled, described and keyboard-operable =================
assert(/<label class="typed-read-label" for="typedReadInput">/.test(level2),
  "the textarea needs a real <label for>, not a placeholder");
assert(/Read Along .{0,3} Type what you read/.test(level2),
  "the label must name the activity and the action");
assert(/<textarea id="typedReadInput"[^>]*aria-describedby="typedReadHint"/.test(level2),
  "the hint must be programmatically associated with the field");
assert(!/<textarea id="typedReadInput"[^>]*placeholder=/.test(level2),
  "placeholder-only labelling is not labelling");
assert(/<button id="typedCheckBtn" type="button">/.test(level2) && /Check reading/.test(level2),
  "a real button with visible text");
assert(/typedReadInput\.addEventListener\("keydown", e => \{\s*if \(e\.key === "Enter" && !e\.shiftKey\)/
  .test(code), "Enter must submit from the keyboard");
assert(/#typedReadInput:focus-visible[^}]*outline: 3px/.test(html) &&
       /#typedCheckBtn:focus-visible[^}]*outline: 3px/.test(html),
  "focus must be visible on both the field and the button");
assert(/\.ra-mode input:focus-visible[^}]*outline: 3px/.test(html),
  "focus must be visible on the educator control too");
ok("4. the field has a real label and an associated hint, no placeholder labelling, Enter submits, " +
   "and focus is visibly indicated on every new control");

// ================= 5. the surface swaps input, not curriculum =================
assert(/const typedMode = readAlongTypedAllowed\(\);/.test(renderShadow),
  "renderShadow must branch on the permitted mode");
assert(/recBtn\.hidden = typedMode;/.test(renderShadow) && /myPlayBtn\.hidden = typedMode;/.test(renderShadow),
  "the recording controls must go away in typed mode");
assert(/typedRead\.classList\.toggle\("hidden", !typedMode\);/.test(renderShadow),
  "the typed panel must be shown only in typed mode");
assert(renderShadow.indexOf("listenBtn.hidden") === -1 && renderShadow.indexOf("speedBtn.hidden") === -1,
  "Listen must remain available: the accommodation replaces the answer, not the model audio");
assert(/nextBtn\.disabled = !done;/.test(renderShadow),
  "typed mode must gate the next sentence on a submitted attempt, exactly as recording did");
assert(/shadowText\.textContent = line\.text;/.test(renderShadow),
  "the same sentence is still presented");
ok("5. typed mode hides only the recorder, keeps Listen and the same sentences, and still requires " +
   "an attempt per sentence before advancing");

// ================= 6. the finish summary does not claim pronunciation was measured =================
assert(/readAlongTypedAllowed\(\) \? "⌨ Reading: " : "🎤 Pronunciation: "/.test(code),
  "a typed result must not be reported as a pronunciation score");
ok("6. the completion summary names the input that was actually assessed");

// ================= 7. the educator control exists only where authority can exist =================
assert(/if \(useLabel && st\.__mode\) \{/.test(cards),
  "the control must be gated on the authoritative-member card model");
assert(/__mode: m\.readAlongMode === "typed" \? "typed" : "speech"/.test(dash),
  "the state shown must come from the server's per-member report");
const legacyCall = dash.slice(dash.indexOf("Earlier records"));
assert(/studentCardsHTML\(legacy\)/.test(legacyCall) && !/studentCardsHTML\(legacy, true\)/.test(dash),
  "legacy rows must render without the label/control mode");
assert(/studentCardsHTML\(acc\.students\)/.test(code),
  "the admin overview must also render without the control");
ok("7. the control appears only on authoritative class-member cards -- never on legacy name-keyed " +
   "rows or the admin overview, where may_manage() could not authorize it");

// ================= 8. the control is a request, and the server's answer wins =================
const wire = slice('host.querySelectorAll(".ra-mode-box")', "\n  function renderAdmin", "control wiring");
assert(/fetch\("\/api\/accommodation\/read-along\?token="/.test(wire),
  "the control must post to the accommodation endpoint");
assert(/box\.checked = res\.j\.readAlongMode === "typed";/.test(wire),
  "the checkbox must be reconciled to what the server reports, not to the click");
assert(/box\.checked = !box\.checked;/.test(wire),
  "a refused change must visibly revert");
assert(/reason === "not_authorized" \? "You cannot change this learner's settings\."/.test(wire),
  "a refusal must be stated plainly to the educator");
assert(!/readAlongMode\s*=\s*"typed"/.test(wire),
  "the dashboard must not write the mode into any client-side state of its own");
ok("8. the educator control only REQUESTS the change: the box follows the server's answer, reverts " +
   "on refusal, and says so");

// ================= 9. wording stays functional -- no diagnosis anywhere in the UI =================
const banned = ["disabilit", "disabled learner", "diagnos", "impair", "special needs", "medical",
                "speech therapy", "condition", "autis", "dyslex", "mute", "handicap"];
const uiTexts = [level2, cards, dash, typedFn].join("\n").toLowerCase();
for (const b of banned) {
  assert(uiTexts.indexOf(b) === -1, "clinical or stigmatising wording in the UI: " + b);
}
assert(/Allow typed Read Along/.test(cards),
  "the control must describe what it does");
assert(/Same sentences, same scoring, same pass mark\./.test(cards),
  "the educator must be told this is not an easier route");
ok("9. every string is functional: what the setting does, never why a learner might need it -- no " +
   "diagnosis, disability or medical wording exists in the UI at all");

// ================= 10. a stale mirror self-corrects, and nothing else changed =================
assert(/reason === "typed_not_enabled"[\s\S]{0,220}myReadAlongMode = "speech";/.test(typedFn),
  "a server refusal must correct the local mirror");
assert(/typedDone = \{\}/.test(code) && (code.match(/typedDone = \{\}/g) || []).length >= 3,
  "typed attempts must be cleared on lesson load and on Try Again");
assert(/id="recBtn">/.test(level2) && /id="listenBtn">/.test(level2) && /id="myPlayBtn"/.test(level2),
  "the speech controls must still exist for every other learner");
assert(/const url = withRoom\(\(aid && tok\)/.test(code) && /"\/api\/stt\?activityId="/.test(code),
  "the speech scoring path must be untouched");
ok("10. a rejected submission corrects the stale mirror, typed attempts reset with the lesson, and " +
   "the speech path is left exactly as it was");

console.log("\nAll " + passed + " typed Read Along client checks passed.");
