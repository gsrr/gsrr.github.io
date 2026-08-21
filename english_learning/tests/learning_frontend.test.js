"use strict";
// Phase 3B — frontend requirement renderer + study navigation (§38). Source-level, no DOM framework:
// the requirement functions are extracted from index.html and executed against tiny fake stubs, so
// the assertions are about real shipped code rather than a reimplementation.
//
//     node tests/learning_frontend.test.js

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const vm = require("vm");

let passed = 0;
function ok(name) { passed++; console.log("  ok -", name); }

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");

function extractFn(src, sig) {
  const start = src.indexOf(sig);
  assert(start >= 0, "cannot find " + sig);
  let i = src.indexOf("{", start), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}") { depth--; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error("unbalanced braces for " + sig);
}

// Phase 7C.2 moved the gold-bar sync OUT of maybeSubmitLearningAttempt and into
// noteLessonCompletion, so that every authoritative endpoint (quiz / matching / read-along /
// role-play) syncs the balance in ONE place. noteLessonCompletion is therefore no longer a mere
// display hook that can be stubbed away — it now owns "the balance comes from the server response,
// never computed" — so the REAL one is extracted and run, with only its collaborators stubbed.
// Phase 12D: renderRequirementPanel, territoryRequirements, missingQualifications, studyArticleFor
// and offerStudyReturn were retired with the region modal. They were already unreachable -- no
// playable territory declares attackQualificationIds and the server enforces no learning gate -- so
// what survives here is this suite's real subject: the attempt request and its authority.
const FNS = ["qualTitle", "studyTargetFor", "activityIdForContent", "maybeSubmitLearningAttempt",
  "findArticleByFile", "noteLessonCompletion", "returnCtx"]
  .map(n => extractFn(html, "function " + n + "("));

// ---- a minimal DOM good enough for the renderer (element + classList + appendChild) ----
function el(tag) {
  return {
    tagName: tag, className: "", id: "", textContent: "", innerHTML: "", disabled: false,
    children: [], _on: {}, onclick: null,
    classList: { _s: new Set(),
      add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); }, contains(c) { return this._s.has(c); } },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(ev, fn) { this._on[ev] = fn; },
    click() { if (this._on.click) this._on.click(); else if (this.onclick) this.onclick(); },
  };
}
function allButtons(node, out) {
  out = out || [];
  node.children.forEach(c => { if (c.tagName === "button") out.push(c); allButtons(c, out); });
  return out;
}

// ---- the sandbox: exactly the collaborators the extracted functions touch ----
function makeCtx(over) {
  const ctx = Object.assign({
    TERR_CATALOG: { terrById: {} },
    learningRegistry: { qualifications: {}, activities: {}, lessons: {} },
    myQualifications: new Set(),
    manifest: { levels: [] },
    LEVEL_ARCS: {},
    pendingStudy: null,
    myEcon: { gold: 0 },
    escapeHtml: s => String(s == null ? "" : s).replace(/[&<>"]/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])),
    regionDisplayName: k => "Region " + k,
    closeModal: () => { ctx.log.push("closeModal"); },
    selectArticle: a => { ctx.log.push("selectArticle:" + a.file); },
    selectLevel: () => { ctx.log.push("selectLevel"); },
    showLockedMsg: m => { ctx.log.push("toast:" + m); },
    renderEmpire: () => { ctx.log.push("renderEmpire"); },
    // Phase 5A/7C.2: the completion hook. The REAL function now runs (see FNS above); these are the
    // collaborators it reaches for, and __log is how the existing "noteCompletion:" assertions still
    // observe that it was called.
    __log: m => { ctx.log.push(m); },
    _grantedNow: { lesson: null, course: null, gold: 0 },
    // Phase 7E.1: the lesson now carries the surface that opened it. returnCtx() is the REAL
    // normalizer (extracted above); returnToRegion is the navigation effect, stubbed like every
    // other collaborator so the test can observe it without a map.
    lessonReturnTo: null,
    returnToRegion: c => { ctx.log.push("returnToRegion:" + (c && c.key)); },
    // the region return is deferred so the learner can read the consequence toast; run the
    // scheduled callback immediately so the test observes it deterministically.
    setTimeout: (fn) => { fn(); return 0; },
    clearTimeout: () => {},
    loadLearningProgress: () => { ctx.log.push("loadLearningProgress"); },
    refreshLessonSurfaces: () => {},
    authToken: () => "tok",
    withRoom: u => u,
    synth: { cancel() {} }, stopListenL1() {}, stopRecordingIfAny() {},
    selLevelIdx: 0,
    document: { getElementById: id => ctx._byId[id] || null, body: el("body"),
      createElement: t => el(t) },
    fetch: (url, opts) => { ctx.calls.push({ url, body: JSON.parse(opts.body) }); return ctx._fetch(url, opts); },
    _byId: {}, calls: [], log: [],
    _fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
  }, over || {});
  ctx.document.createElement = t => el(t);
  vm.createContext(ctx);
  vm.runInContext(FNS.join("\n"), ctx);
  // Wrap the real noteLessonCompletion so its invocation stays observable without replacing it.
  vm.runInContext(
    "var __realNote = noteLessonCompletion;" +
    "noteLessonCompletion = function (j) {" +
    "  __log('noteCompletion:' + (j && j.lessonCompletedNow));" +
    "  return __realNote(j); };", ctx);
  return ctx;
}

// production-shaped registry: two qualifications from two different lessons
const REG = {
  qualifications: {
    "q.greetings": { scope: "activity", title: "Basic Greetings",
      studyTarget: { activityId: "q.greetings.a", lessonId: "l.greet", contentPath: "Pre-A1/basics/greet" } },
    "q.zoo": { scope: "activity", title: "Zoo — Yes/No",
      studyTarget: { activityId: "a.zoo", lessonId: "l.zoo", contentPath: "Pre-A1/taipei/zoo" } },
  },
  activities: {
    "a.zoo": { lessonId: "l.zoo", contentPath: "Pre-A1/taipei/zoo", contentKey: "quiz3",
      title: "Zoo — Yes/No", grants: ["q.zoo"] },
    "q.greetings.a": { lessonId: "l.greet", contentPath: "Pre-A1/basics/greet", contentKey: "quiz3",
      title: "Basic Greetings", grants: ["q.greetings"] },
  },
  lessons: {},
};
const MANIFEST = { levels: [{ id: "Pre-A1", articles: [
  { id: "tp-zoo", file: "Pre-A1/taipei/zoo", title: "At the Zoo" },
  { id: "greet", file: "Pre-A1/basics/greet", title: "Greetings" }] }] };

function ctxFor(requirements, held) {
  const c = makeCtx({ learningRegistry: REG, manifest: MANIFEST, myQualifications: new Set(held || []) });
  c.TERR_CATALOG.terrById["t:target"] = requirements === null ? {}
    : { requirements: { attackQualificationIds: requirements } };
  return c;
}

// 1-4) RETARGETED in Phase 12D.
//
// OLD            : renderRequirementPanel's rendering behaviour -- the lock copy, one ✓/✗ row per
//                  requirement, one Study entry per MISSING requirement, and metadata-driven
//                  navigation (studyTarget -> contentPath) with no hardcoded lesson.
// WHY OBSOLETE   : the panel is gone (12D), and it was already unreachable: 0 of 250 playable
//                  territories declare attackQualificationIds, and Phase 10A.3R removed the gate from
//                  /api/territory/claim and /attack, so it could never render.
// NEW            : assert the property those tests were really protecting -- that requirement
//                  metadata is READ-ONLY DATA and no client path gates conquest on learning, and that
//                  the surviving registry readers still hardcode no content.
// WHY NOT WEAKER : checks 5 and 6 below (the attempt request carries identity + answers ONLY, and the
//                  endpoint routing) are this suite's authority checks and are untouched. This form
//                  additionally forbids what the old one could not: a client-side learning gate
//                  reappearing anywhere on the conquest path.
{
  const conquest = ["trayConfirm", "trayValidSources", "launchAttack", "claimTroops",
                    "renderHudActions"].map(n => extractFn(html, "function " + n + "("));
  const gateWords = ["myQualifications", "attackQualificationIds", "qualificationIds",
                     "missingQualifications", "territoryRequirements", "studyTarget"];
  conquest.forEach((body, k) => gateWords.forEach(w => assert(body.indexOf(w) === -1,
    "no conquest path may consult learning state (" + w + " in fn #" + k + ")")));
  // and the metadata is still only ever READ, never used to refuse an action
  assert(!/attackQualificationIds[^\n]*(return false|disabled|refus|blocked|locked)/i.test(html),
    "requirement metadata must not gate anything client-side");
}
const src = FNS.join("\n");
[/zoo/i, /taipei/i, /pre-a1/i, /quiz3/, /english\./i].forEach(re =>
  assert(!re.test(src), "registry/study code must not hardcode content: " + re));
ok("1-4 (retargeted): requirement metadata is read-only data — no conquest path consults learning " +
   "state, and the surviving registry readers hardcode no content");

// 5) the attempt request submits IDENTITY + answers only — never authority
{
  const c = makeCtx({ learningRegistry: REG, manifest: MANIFEST });
  vm.runInContext("maybeSubmitLearningAttempt", c)("Pre-A1/taipei/zoo", "quiz3", [{ q: "x", answer: "Yes" }]);
  assert.strictEqual(c.calls.length, 1, "a registered activity is submitted");
  const body = c.calls[0].body;
  assert.deepStrictEqual(Object.keys(body).sort(), ["activityId", "answers"], body);
  assert.strictEqual(body.activityId, "a.zoo", "the content path + key resolved to the canonical id");
  ["passed", "pct", "score", "correct", "total", "qualification", "qualifications", "gold",
    "rewarded", "rewardGold", "rewardPolicy", "graderType"].forEach(k =>
    assert(!(k in body), "client must not submit " + k));
  assert(/\/api\/learning\/attempt/.test(c.calls[0].url));
  // an UNREGISTERED activity is simply not submitted (no guessing, no fallback endpoint)
  const c2 = makeCtx({ learningRegistry: REG, manifest: MANIFEST });
  vm.runInContext("maybeSubmitLearningAttempt", c2)("Pre-A1/taipei/zoo", "quiz4", []);
  vm.runInContext("maybeSubmitLearningAttempt", c2)("A2/space/mars", "quiz3", []);
  assert.strictEqual(c2.calls.length, 0, "unregistered content/activity is never submitted");
}
ok("attempt request carries {activityId, answers} only — no score/passed/qualification/gold/reward");

// 6b) Phase 3C — every migrated controller collects answer EVIDENCE and submits it to the one
//     authoritative endpoint, resets it per attempt, and still leaves scoring authority to the server.
{
  const CONTROLLERS = [
    { fn: "makeQuiz", push: /chosen\.push\(\{ q: shuffled\[idx\]\.q, answer: choice \}\)/,
      submit: /maybeSubmitLearningAttempt\(currentArticleKey, "quiz" \+ level, chosen\)/ },
    { fn: "makeWh", push: /chosen\.push\(\{ q: it\.q, answer: choice \}\)/,
      submit: /maybeSubmitLearningAttempt\(currentArticleKey, "wh", chosen\)/ },
    { fn: "makeCloze", push: /chosen\.push\(\{ q: it\.text, answer: choice \}\)/,
      submit: /maybeSubmitLearningAttempt\(currentArticleKey, "cloze", chosen\)/ },
    { fn: "makeDictation", push: /chosen\.push\(\{ q: sentence, answer: input\.value \}\)/,
      submit: /maybeSubmitLearningAttempt\(currentArticleKey, "dictation", chosen\)/ },
    { fn: "makeReorder", push: /chosen\.push\(\{ q: sentences\[idx\]\.join\(" "\), answer: placed\.slice\(\) \}\)/,
      submit: /maybeSubmitLearningAttempt\(currentArticleKey, "reorder", chosen\)/ },
  ];
  CONTROLLERS.forEach(c => {
    const src = extractFn(html, "function " + c.fn + "(");
    assert(/let chosen = \[\]/.test(src), c.fn + " must declare an evidence buffer");
    assert(c.push.test(src), c.fn + " must record {q, answer} evidence");
    assert(/chosen = \[\]/.test(src.replace(/let chosen = \[\]/, "")), c.fn + " must reset evidence per attempt");
    assert(c.submit.test(src), c.fn + " must submit its evidence to the authoritative endpoint");
    // the controller must not compute authority: no gold, no qualification, no pass declaration
    ["myQualifications.add", "myEcon.gold =", "PASS_GOLD", "qualification"].forEach(bad =>
      assert(src.indexOf(bad) < 0, c.fn + " must not touch " + bad));
  });
  // reorder submits only AFTER the last sentence, so evidence covers the whole activity
  const ro = extractFn(html, "function makeReorder(");
  assert(/recordScore\(6, sentences\.length, sentences\.length\);[\s\S]{0,120}maybeSubmitLearningAttempt/.test(ro),
    "reorder must submit once, at the end of the activity");
  // Phase 3E2: matching migrated to its OWN server-owned round endpoints (not the attempt endpoint)
  const match = extractFn(html, "function makeMatch(");
  assert(match.indexOf("maybeSubmitLearningAttempt") < 0,
    "makeMatch must not use the deterministic attempt endpoint - it has its own round API");
  assert(/\/api\/learning\/matching\/start/.test(match), "makeMatch must start a server-owned round");
  assert(/\/api\/learning\/matching\/attempt/.test(match), "clicks must go to the attempt endpoint");
  // the activityId comes from registry metadata, never hardcoded
  assert(/acts\[aid\]\.contentPath === currentArticleKey && acts\[aid\]\.scored === "matching"/.test(match),
    "the matching activityId must be resolved from registry metadata");
  [/zoo/i, /taipei/i, /pre-a1/i].forEach(re =>
    assert(!re.test(match), "makeMatch must not hardcode content: " + re));
  // the START request carries only the activity identity
  const startBody = (match.match(/JSON\.stringify\(\{ activityId: aid \}\)/) || [])[0];
  assert(startBody, "start request must be exactly {activityId}");
  // the ATTEMPT request carries only round/item/choice identity - no authority
  const attemptBody = (match.match(/JSON\.stringify\(\{ roundId:[^}]*\}\)/) || [])[0] || "";
  assert(/roundId: round\.roundId/.test(attemptBody) && /itemId: item\.itemId/.test(attemptBody) &&
    /choiceId: choice\.choiceId/.test(attemptBody), "attempt body: " + attemptBody);
  ["firstTry", "score", "pct", "passed", "correct", "total", "sample", "qualification", "reward"]
    .forEach(k => assert(attemptBody.indexOf(k) < 0, "attempt request must not submit " + k));
  // the FINAL score comes from the server result, fed to recordScore for legacy display only
  assert(/if \(d\.status === "complete" && d\.result\) finish\(d\.result\.correct, d\.result\.total\)/.test(match),
    "the completion score must come from the server result");
  assert(/recordScore\(5, correct, n\)/.test(match), "recordScore is display/progression only");
  // a backend failure must NOT fall back to local authoritative scoring (§8)
  assert(/Couldn't start the matching round/.test(match), "start failure must offer a retryable state");
  assert(!/buildLocal\(\);?\s*\}\)\s*;?\s*$/m.test(match.slice(match.indexOf(".catch("))),
    "the start .catch must not silently switch to the local path");
  // the local practice path survives for backendless mode only
  assert(/if \(!aid \|\| !tok\) \{ buildLocal\(\); return; \}/.test(match),
    "local practice mode is entered only when there is no registered activity or no login");
  assert(/const n = Math\.min\(5, vocab\.length\)/.test(match), "legacy local sample rule preserved");
  // in-flight guard (§6)
  assert(/if \(!round \|\| inFlight/.test(match), "a click while a request is in flight must be ignored");
}
ok("Phase 3C/3E2: quiz/wh/cloze/dictation/reorder use the attempt endpoint; matching uses its own " +
   "server-owned round API and submits no authority");

// 6) the client treats the server response as the authority and cannot self-grant
const settle = () => new Promise(r => setImmediate(r));

(async function () {
  // a NON-pass response grants nothing, even when it also claims a qualification and gold
  const c = makeCtx({ learningRegistry: REG, manifest: MANIFEST });
  c._fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(
    { ok: true, passed: false, qualifications: ["q.zoo"], rewarded: true, gold: 999999 }) });
  vm.runInContext("maybeSubmitLearningAttempt", c)("Pre-A1/taipei/zoo", "quiz3", []);
  await settle();
  assert.strictEqual(c.myQualifications.size, 0, "passed:false grants nothing client-side");
  assert.strictEqual(c.myEcon.gold, 0, "no gold is applied when the server says not passed");
  // Phase 5A: a lesson can newly complete on a FAILING attempt (the failing score still lands in
  // activityScores and the Rule A mean may stay >= 80), so the hook must run before the early return.
  assert(c.log.includes("noteCompletion:undefined"),
    "a failing attempt still reports its lesson-completion outcome");
  const c1b = makeCtx({ learningRegistry: REG, manifest: MANIFEST });
  c1b._fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(
    { ok: true, passed: false, lessonCompletedNow: true, lessonId: "l.zoo" }) });
  vm.runInContext("maybeSubmitLearningAttempt", c1b)("Pre-A1/taipei/zoo", "quiz3", []);
  await settle();
  assert(c1b.log.includes("noteCompletion:true"),
    "lessonCompletedNow on a failing attempt is forwarded to the UI hook");
  assert.strictEqual(c1b.myQualifications.size, 0, "…and still grants nothing client-side");

  // a PASSING response is mirrored (display only). The fixture carries rewardAmount because a real
  // settling response does: the server publishes the granted amount alongside the new balance, and
  // sends a balance ONLY when it actually credited.
  const c2 = makeCtx({ learningRegistry: REG, manifest: MANIFEST });
  c2._fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(
    { ok: true, passed: true, qualifications: ["q.zoo"], rewarded: true, rewardAmount: 160,
      lessonRewardAmount: 0, gold: 12345 }) });
  vm.runInContext("maybeSubmitLearningAttempt", c2)("Pre-A1/taipei/zoo", "quiz3", []);
  await settle();
  assert(c2.myQualifications.has("q.zoo"), "server-confirmed pass updates the display mirror");
  assert(c2.log.includes("noteCompletion:undefined"),
    "Phase 5A: every authoritative response is offered to the completion-banner hook");
  assert.strictEqual(c2.myEcon.gold, 12345, "gold comes from the server response, never computed");
  assert(c2.log.some(l => /^toast:/.test(l) && /Zoo — Yes\/No/.test(l)), c2.log);

  // RETARGETED in Phase 12D.
  //
  // OLD            : after a pass, the "#studyReturn — <region> unlocked — back to the map" button is
  //                  offered, and clicking it returns to and reopens the originating territory; and a
  //                  region-opened lesson whose last requirement just landed is pulled back to that
  //                  region with a "Requirement complete" toast.
  // WHY OBSOLETE   : both behaviours were fed only by state the region modal set (`pendingStudy` from
  //                  renderRequirementPanel, `lessonReturnTo = {to:"region"}` from the same web).
  //                  Neither could occur on a real device -- 0 of 250 playable territories declare a
  //                  requirement and the server enforces no gate -- and 12D removed them.
  // NEW            : assert that NO orphaned return affordance is offered, and that a pass pulls the
  //                  learner nowhere. The authority assertions above (mirror, completion hook,
  //                  server-supplied gold, qualification toast) are kept verbatim.
  // WHY NOT WEAKER : it replaces "this navigation happens" with "no navigation is invented", which is
  //                  the stronger claim now that nothing can legitimately set it up -- a reappearing
  //                  study-return button would be a stale-state bug, and this catches it.
  assert(!c2.document.body.children.some(x => x.id === "studyReturn"),
    "no orphaned study-return affordance may be offered");
  assert(!c2.log.some(l => /^returnToRegion/.test(l) || /^selectLevel/.test(l)),
    "a graded pass must not navigate the learner anywhere: " + c2.log);
  assert(!c2.log.some(l => /^toast:/.test(l) && /Requirement complete/.test(l)),
    "…and must not claim a conquest consequence that no longer exists");

  // Phase 7C.2a-fix: the balance is synced on an ECONOMIC SETTLEMENT, identified by the granted
  // amounts — never by `rewarded` alone, and never from a response that reports no settlement.
  // (i) lesson mastery pays while the ACTIVITY's own reward is 0 — this must still sync, because
  //     gating on `rewarded` is exactly the stale-gold-bar bug Phase 7C.2 fixed.
  const cM = makeCtx({ learningRegistry: REG, manifest: MANIFEST });
  cM._fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(
    { ok: true, passed: true, qualifications: [], rewarded: false, rewardAmount: 0,
      lessonRewarded: true, lessonRewardAmount: 640, lessonCompletedNow: true, gold: 2100 }) });
  vm.runInContext("maybeSubmitLearningAttempt", cM)("Pre-A1/taipei/zoo", "quiz3", []);
  await settle();
  assert.strictEqual(cM.myEcon.gold, 2100,
    "lesson mastery gold syncs even though the activity itself paid nothing");
  assert(cM.log.includes("renderEmpire"), "…and the gold bar is redrawn");

  // (ii) a retry settles nothing: every granted amount is 0, so no response-driven gold update,
  //      even if the response still carries a balance.
  const cR = makeCtx({ learningRegistry: REG, manifest: MANIFEST });
  cR._fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(
    { ok: true, passed: true, qualifications: ["q.zoo"], rewarded: false, rewardAmount: 0,
      lessonRewarded: false, lessonRewardAmount: 0, gold: 987654 }) });
  vm.runInContext("maybeSubmitLearningAttempt", cR)("Pre-A1/taipei/zoo", "quiz3", []);
  await settle();
  assert.strictEqual(cR.myEcon.gold, 0,
    "a replay grants nothing, so no balance is taken from the response");
  assert(!cR.log.includes("renderEmpire"), "…and the gold bar is not redrawn");

  // (iii) campaign completion is cosmetic: courseRewardAmount 0 means no economic sync is needed.
  const cC = makeCtx({ learningRegistry: REG, manifest: MANIFEST });
  cC._fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(
    { ok: true, passed: true, qualifications: [], rewarded: false, rewardAmount: 0,
      lessonRewardAmount: 0, courseCompletedNow: true, courseRewardAmount: 0,
      courseRewardItemId: "trophy.campaign.complete", gold: 555 }) });
  vm.runInContext("maybeSubmitLearningAttempt", cC)("Pre-A1/taipei/zoo", "quiz3", []);
  await settle();
  assert.strictEqual(cC.myEcon.gold, 0,
    "a cosmetic campaign completion moves no gold, so nothing is synced from it");

  // a partially-satisfied return context does NOT offer the return yet
  const c3 = makeCtx({ learningRegistry: REG, manifest: MANIFEST });
  c3.pendingStudy = { qualificationIds: ["q.zoo", "q.greetings"], label: "R", reopen: () => {} };
  c3._fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(
    { ok: true, passed: true, qualifications: ["q.zoo"] }) });
  vm.runInContext("maybeSubmitLearningAttempt", c3)("Pre-A1/taipei/zoo", "quiz3", []);
  await settle();
  assert(!c3.document.body.children.some(x => x.id === "studyReturn"),
    "with a requirement still outstanding the territory is not announced as unlocked");
  ok("server response is authority: no self-grant on failure; pass mirrors state + offers return");
  console.log("\nAll " + passed + " learning-frontend tests passed.");
})().catch(e => { console.error(e); process.exit(1); });
