// Phase 12B.1 — the read-along request is bounded, and what the learner is told is true.
//
//   node tests/stt_client_timeout.test.js
//
// Two defects from the Phase 12A audit are guarded here:
//
//   1. scorePronunciation() had NO timeout. Speech inference is serialised on the server, so a slow
//      or wedged transcription left the panel reading "Scoring…" for ever with Record disabled --
//      measured in a real browser, the control never came back.
//   2. every failure printed the same sentence blaming "the server (Docker build)" and "GitHub
//      Pages". A browser cannot know that, and on a working deployment it is false.
//
// Behaviour is exercised for real by scratchpad/accept_12b1.js (hanging route, 503, mic denied,
// MediaRecorder removed). What is guarded here is that the client cannot drift back to an unbounded
// request, to deployment-guessing copy, or -- most importantly -- to deciding a score for itself.
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
const i = code.indexOf("function scorePronunciation");
assert(i > 0, "scorePronunciation not found");
const fn = code.slice(i, code.indexOf("\n  function stopRecording", i));
assert(fn.length > 500 && fn.length < 6000, "scorePronunciation slice looks wrong: " + fn.length);

// ============ 1. the budget is a named constant, not a buried number ============
assert(/const STT_REQUEST_TIMEOUT_MS = \d+;/.test(code),
  "the timeout must be a named constant");
const ms = parseInt(code.match(/const STT_REQUEST_TIMEOUT_MS = (\d+);/)[1], 10);
assert(ms >= 5000 && ms <= 60000,
  "the budget must be generous enough for CPU inference but bounded: got " + ms);
assert(/STT_REQUEST_TIMEOUT_MS/.test(fn), "the constant must actually be used by the request");
ok("1. the request budget is the named constant STT_REQUEST_TIMEOUT_MS = " + ms + "ms");

// ============ 2. the pending request is really terminated ============
assert(/new AbortController\(\)/.test(fn), "an AbortController must bound the request");
assert(/opts\.signal = ctl\.signal/.test(fn), "the signal must be passed to fetch");
assert(/ctl\.abort\(\)/.test(fn), "the timer must abort the request, not merely paint a message");
assert(/setTimeout\(/.test(fn) && /clearTimeout\(timer\)/.test(fn),
  "the timer must be cleared so a fast response does not later fire an abort");
assert(/typeof AbortController === "function"/.test(fn),
  "AbortController must be feature-detected rather than assumed");
ok("2. a timer aborts the pending request, and the timer is always cleared");

// ============ 3. the UI always leaves the scoring state ============
const fin = fn.slice(fn.indexOf(".finally("));
assert(/isScoring = false/.test(fin), "scoring state must be cleared in finally");
assert(/recBtn\.disabled = false/.test(fin), "Record must be re-enabled in finally");
assert(/clearTimeout/.test(fin), "the timer must be cleared in finally");
assert(fn.indexOf(".finally(") > fn.indexOf(".catch("),
  "finally must run after the catch, so every failure path re-enables the control");
ok("3. Record and the navigation buttons are re-enabled on EVERY path, including timeout");

// ============ 4. the copy is truthful and distinct per failure ============
// the OUTER failure handler: there is an inner .catch(() => null) that reads the error body, so
// anchoring on the first .catch( would slice in the success branch as well.
const finAt = fn.indexOf(".finally(");
const c = fn.slice(fn.lastIndexOf("      .catch(", finAt), finAt);
assert(/let msg;/.test(c), "the outer catch handler was not located: " + c.slice(0, 60));
assert(!/Docker build/.test(fn) && !/GitHub Pages/.test(fn),
  "the browser must not guess at deployment internals");
const wanted = [
  // Phase 12B.1.1 replaced "took too long" -- which reads as a verdict on the attempt -- with a
  // statement about the BROWSER, because the server may still be settling this very request. The
  // requirement is unchanged: the timeout must still have its own distinct message.
  [/taking longer than expected/i, "timeout"],
  [/busy right now/i, "server busy"],
  [/temporarily unavailable/i, "service unavailable"],
  [/Could not reach/i, "network"],
];
for (const [re, label] of wanted) {
  assert(re.test(fn), "a distinct message is required for: " + label);
}
assert(/err\.reason === "stt_busy"/.test(fn) && /err\.reason === "stt_unavailable"/.test(fn),
  "the server's own reason code must drive which message is shown");
assert(/timedOut \|\| \(err && err\.name === "AbortError"\)/.test(fn),
  "a timeout must be recognised distinctly from a server error");
// Phase 12B.1.1: and it must not pass judgement on the attempt, which may still be settling
const tob = fn.slice(fn.indexOf("if (timedOut ||"),
                     fn.indexOf('} else if (err && err.reason === "stt_busy")'));
for (const claim of ["took too long", "failed", "Failed", "no Gold", "no mastery", "did not pass"]) {
  assert(tob.indexOf(claim) < 0, "the timeout message must not claim: " + claim);
}
assert(/checked again shortly/.test(tob),
  "the timeout must tell the learner their progress will be re-checked");
// nothing internal may reach a child
for (const leak of ["whisper", "Whisper", "base.en", "faster", "stack", "Traceback", "/api/stt?"]) {
  const shown = c;
  assert(shown.indexOf(leak) < 0, "the error copy must not expose: " + leak);
}
ok("4. four distinct truthful messages, chosen by the server's reason code, leaking nothing");

// ============ 5. the browser-capability and microphone messages stay distinct ============
assert(/does not support recording/.test(code),
  "the unsupported-recording explanation must be kept");
assert(/Cannot use the microphone/.test(code),
  "the microphone-permission explanation must be kept");
assert(/Recording needs an external browser/.test(code),
  "the in-app-browser explanation must be kept");
// these are recording-time messages: they must NOT be produced by the scoring request
const scoreCatch = fn.slice(fn.lastIndexOf("      .catch(", fn.indexOf(".finally(")));
assert(!/does not support recording/.test(scoreCatch) &&
       !/Cannot use the microphone/.test(scoreCatch),
  "a scoring failure must not be reported as a microphone or browser problem");
ok("5. microphone, browser-capability and scoring failures remain three separate explanations");

// ============ 6. a timeout fabricates nothing ============
for (const banned of ["noteLessonCompletion", "recordScore", "showPron", "pronScores",
                      "sttAuthPct", "activePolicyCompleted", "rewardAmount"]) {
  assert(c.indexOf(banned) < 0,
    "the failure path must not touch scoring or completion state: " + banned);
}
assert(/pronResult\.innerHTML = sttFailHTML\(msg\)/.test(c),
  "the failure path may only paint a message");
ok("6. a timeout or outage writes no score, no completion and no reward -- it only shows a message");

// ============ 7. scoring authority stays on the server ============
assert(/d\.authoritative/.test(fn), "the client must honour the server's authoritative flag");
assert(/sttAuthPct = d\.activityPct/.test(fn), "the percentage must come from the server");
assert(/pronScores\[sIdx\] = d\.score/.test(fn), "the per-sentence score must come from the server");
assert(/activityId=" \+ encodeURIComponent\(aid\)/.test(fn) && /sentenceIndex=" \+ sIdx/.test(fn),
  "the authoritative request still carries only activityId and sentenceIndex");
assert(!/passed:\s*true/.test(fn) && !/score:\s*\d/.test(fn),
  "the client must never send a score or a pass");
assert(/method: "POST", body: blob/.test(fn), "the body must remain the audio blob");
ok("7. the client still sends only audio + activityId + sentenceIndex and reads the score back");

// ============ 8. a request budget is not a recording limit ============
assert(!/mediaRecorder[\s\S]{0,60}STT_REQUEST_TIMEOUT_MS/.test(code),
  "the request budget must not be wired into the recorder");
const rec = code.slice(code.indexOf('recBtn.addEventListener'),
                       code.indexOf('recBtn.addEventListener') + 1600);
assert(!/STT_REQUEST_TIMEOUT_MS/.test(rec),
  "recording length must stay bounded by the learner pressing Stop, not by the request budget");
ok("8. the budget bounds the scoring REQUEST only; recording is still ended by the learner");

console.log("\nAll " + passed + " STT client-timeout tests passed.");
