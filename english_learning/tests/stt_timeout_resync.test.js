// Phase 12B.1.1 — a client timeout is "the browser stopped waiting", not "the attempt failed".
//
//   node tests/stt_timeout_resync.test.js
//
// Phase 12B.1 bounded the scoring request, and then MEASURED an uncomfortable fact: aborting the
// fetch does not stop the handler, which settles before it replies. On a real server with a slow
// transcriber, a timed-out read-along persisted its score, and the request that crossed the pass
// mark granted mastery and paid MASTERY_GOLD — while the browser still showed the old state and the
// learner was told the attempt "took too long".
//
// So after a timeout the lesson now runs a bounded, READ-ONLY reconciliation against the existing
// authoritative endpoints. What is guarded here is that it can never become a resubmission, can
// never invent progress, can never touch the wrong surface, and can never re-introduce copy that
// claims a failure the server has not reported. The behaviour itself is exercised end to end by
// scratchpad/accept_1211.js against a deliberately slow transcriber.
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
function fn(name, endMarker) {
  const i = code.indexOf("function " + name);
  assert(i > 0, "function not found: " + name);
  const j = endMarker ? code.indexOf(endMarker, i) : i + 2600;
  return code.slice(i, j > i ? j : i + 2600);
}
const score = fn("scorePronunciation", "\n  function stopRecording");
const resyncOnce = fn("sttResyncOnce", "function sttShowResyncResult");
const resultPanel = fn("sttShowResyncResult", "\n  function stopRecording");

// ============ 1. the schedule is bounded and named ============
assert(/const STT_RESYNC_DELAYS_MS = \[[^\]]+\];/.test(code),
  "the reconciliation schedule must be a named constant");
const delays = JSON.parse(code.match(/const STT_RESYNC_DELAYS_MS = (\[[^\]]+\]);/)[1]);
assert(Array.isArray(delays) && delays.length >= 2 && delays.length <= 4,
  "the schedule must be a small bounded list, got " + JSON.stringify(delays));
assert(delays.every((d, i) => i === 0 || d > delays[i - 1]), "delays must increase: " + delays);
assert(delays[0] >= 1000 && delays[delays.length - 1] <= 60000,
  "the window must be sane: " + JSON.stringify(delays));
assert(!/setInterval/.test(fn("sttScheduleResync", "function sttResyncOnce")),
  "reconciliation must never poll on an interval");
ok("1. the schedule is the named bounded constant STT_RESYNC_DELAYS_MS = " + JSON.stringify(delays) +
   " — finite, increasing, no polling");

// ============ 2. it is READ-ONLY: never a resubmission ============
assert(!/\/api\/stt/.test(resyncOnce), "reconciliation must never call the STT endpoint");
assert(!/method:\s*"POST"/.test(resyncOnce), "reconciliation must issue no POST at all");
for (const banned of ["blob", "Blob", "activityId", "sentenceIndex", "scorePronunciation"]) {
  assert(resyncOnce.indexOf(banned) < 0,
    "reconciliation must not rebuild a submission: " + banned);
}
assert(/refreshLearning\(/.test(resyncOnce) && /loadEconomy\(/.test(resyncOnce),
  "it must reuse the existing authoritative reads");
ok("2. reconciliation is read-only: it reuses refreshLearning/loadEconomy and never resubmits audio");

// ============ 3. controls are freed at timeout, before any reconciliation ============
const fin = score.slice(score.indexOf(".finally("));
assert(/recBtn\.disabled = false/.test(fin) && /isScoring = false/.test(fin),
  "the controls must be released in finally, independent of reconciliation");
assert(/if \(!timedOut\) sttSupersedeResync\(ctxAtStart, snapAtStart\)/.test(fin),
  "a resolved response must supersede a pending reconciliation");
// ...but NOT by cancelling outright: a later success can report no settlement because an EARLIER
// timed-out request already paid, which left the visible balance stale. One final check remains.
const sup = fn("sttSupersedeResync", "function sttResyncOnce");
assert(/if \(!_sttResyncTimers\.length\) return;/.test(sup),
  "superseding must be a no-op when nothing was pending");
assert(/sttResyncOnce\(ctx, before, false\)/.test(sup),
  "the final check must be silent when nothing changed (isLast=false)");
assert(/const STT_RESYNC_SUPERSEDE_MS = \d+;/.test(code),
  "the supersede delay must be a named constant too");
ok("3. the controls are released immediately in finally; a real response cancels pending checks");

// ============ 4/5/6. late settlement is reported from AUTHORITATIVE state ============
assert(/renderLessonProgress\(\)/.test(resyncOnce),
  "a settled result must refresh the authoritative lesson surfaces");
assert(/now\.mastered !== before\.mastered/.test(resyncOnce),
  "mastery must be detected by comparing authoritative state, not assumed");
assert(/now\.done > before\.done/.test(resyncOnce),
  "activity completion must be detected by comparing authoritative state");
assert(/goldDelta = \(before\.gold != null && now\.gold != null\) \? \(now\.gold - before\.gold\)/
  .test(resyncOnce), "the Gold figure must be an authoritative delta");
assert(!/\b160\b/.test(resyncOnce) && !/\b640\b/.test(resyncOnce) &&
       !/\b160\b/.test(resultPanel) && !/\b640\b/.test(resultPanel),
  "no reward amount may be hard-coded in the reconciliation path");
assert(/\+' \+ goldDelta \+ ' Gold/.test(resultPanel),
  "the panel must print the measured delta");
assert(/goldDelta > 0/.test(resultPanel),
  "a Gold chip must appear only when Gold actually moved");
ok("4/5/6. late activity, mastery and Gold are all reported from authoritative deltas, never " +
   "from a hard-coded amount");

// ============ 7. nothing is invented when nothing settles ============
assert(/isLast/.test(resyncOnce), "the final check must be distinguishable");
const lastBranch = resyncOnce.slice(resyncOnce.indexOf("} else if (isLast)"));
assert(!/renderLessonProgress|sttShowResyncResult|lsFeedback/.test(lastBranch),
  "when nothing settled, no progress or reward may be rendered");
assert(/did not come back in time|Nothing was lost/.test(lastBranch),
  "the exhausted case must be stated honestly");
assert(!/failed|Failed/.test(lastBranch),
  "the exhausted case must not claim the reading failed");
ok("7. when nothing settles, nothing is rendered as progress and no failure is claimed");

// ============ 8. a failed reconciliation fetch is safe ============
assert(/refreshLearning\(function \(\)/.test(resyncOnce),
  "reconciliation must run inside the existing callback-style fetch helpers, which swallow errors");
// the helpers themselves must keep their catch, or a failed resync could throw into a timer
const rl = fn("refreshLearning", "function lessonIdForContent");
assert(/loadLearningRegistry\(/.test(rl), "refreshLearning must keep delegating to the loaders");
const le = fn("loadEconomy", "// Phase 8D");
assert(/\.catch\(/.test(le), "loadEconomy must keep its catch so a failed fetch cannot throw");
ok("8. a failed reconciliation fetch cannot throw into a timer: the existing loaders keep catching");

// ============ 9. a late callback can never touch the wrong surface ============
assert(/function sttContextNow/.test(code) && /function sttSameContext/.test(code),
  "there must be a surface-identity guard");
const ctxNow = fn("sttContextNow", "function sttSameContext");
for (const part of ["currentArticleKey", "authUser()", "activeRoom", "screenLearn"]) {
  assert(ctxNow.indexOf(part) >= 0, "the guard must capture " + part);
}
const same = fn("sttSameContext", "function sttSnapshot");
assert(/now\.onLesson/.test(same), "a callback must refuse when the lesson screen is not showing");
assert(/ctx\.path === now\.path/.test(same), "it must refuse a different lesson");
assert(/ctx\.user === now\.user/.test(same), "it must refuse a different account (logout / switch)");
assert(/ctx\.room === now\.room/.test(same), "it must refuse a different room");
// every stage of the async chain re-checks, not just the entry
assert((resyncOnce.match(/sttSameContext\(ctx\)/g) || []).length >= 3,
  "the guard must be re-checked after each async hop, not only once");
assert(/const ctxAtStart = sttContextNow\(\);/.test(score) &&
       /const snapAtStart = sttSnapshot\(ctxAtStart\.path\);/.test(score),
  "the context and the comparison baseline must be captured BEFORE the request");
assert(/sttCancelResync\(\)/.test(fn("stopAllLessonAudio", "function stopListenL1")),
  "leaving the lesson must cancel pending reconciliation outright");
ok("9. a late callback is bound to lesson + account + room + on-screen, re-checked after every hop, " +
   "and cancelled outright on leaving");

// ============ 10. idempotency is the server's, and the client must not double-count ============
assert(/sttCancelResync\(\);\s*\n\s*sttShowResyncResult/.test(resyncOnce) ||
       /sttCancelResync\(\);\s+\/\/ answered/.test(resyncOnce),
  "once a settlement is observed the remaining checks must stop, so it cannot be reported twice");
assert(!/myEcon\.gold =/.test(resyncOnce) && !/myEcon\.gold =/.test(resultPanel),
  "reconciliation must never write the balance itself — loadEconomy owns it");
ok("10. the first observed settlement stops the remaining checks, and the client never writes the " +
   "balance itself");

// ============ 11/12. timeout copy claims nothing, and academic failure stays separate ============
const timeoutBranch = score.slice(score.indexOf("if (timedOut ||"),
                                  score.indexOf('} else if (err && err.reason === "stt_busy")'));
assert(/taking longer than expected/.test(timeoutBranch),
  "the timeout must say the browser stopped waiting");
assert(/checked again shortly/.test(timeoutBranch),
  "and that progress will be re-checked");
for (const banned of ["failed", "Failed", "no Gold", "no mastery", "did not pass"]) {
  assert(timeoutBranch.indexOf(banned) < 0,
    "the timeout branch must not claim: " + banned);
}
assert(/sttScheduleResync\(ctxAtStart, snapAtStart\)/.test(timeoutBranch),
  "the timeout must start reconciliation");
// the 11E academic-failure wording must still exist, and only for a SCORED response
const lsRes = fn("lsShowActivityResult", "document.addEventListener");
assert(/did not pass, so it earned no Gold and no mastery credit/.test(lsRes),
  "the academic-failure wording must remain for a genuinely scored failure");
assert(!/timedOut|AbortError|stt_unavailable/.test(lsRes),
  "the academic-failure panel must never be driven by an infrastructure failure");
assert(!/lsShowActivityResult/.test(score),
  "the read-along path must not render the graded-attempt failure panel");
ok("11/12. the timeout claims no failure and starts reconciliation; the academic-failure wording " +
   "stays bound to genuinely scored attempts only");

console.log("\nAll " + passed + " STT timeout-resync tests passed.");
