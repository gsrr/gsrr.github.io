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

const FNS = ["renderRequirementPanel", "territoryRequirements", "missingQualifications", "qualTitle",
  "studyTargetFor", "studyArticleFor", "activityIdForContent", "maybeSubmitLearningAttempt",
  "offerStudyReturn", "findArticleByFile"].map(n => extractFn(html, "function " + n + "("));

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
    renderEmpire: () => {},
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

// 1) ZERO requirements -> the renderer declines, so the normal attack UI runs
[[], null].forEach(reqs => {
  const c = ctxFor(reqs), terr = el("div");
  assert.strictEqual(vm.runInContext("renderRequirementPanel", c)(terr, "t:target", null), false,
    "no requirements must return false (fall through to the attack UI)");
  assert.strictEqual(terr.innerHTML, "", "the renderer must not touch the panel when it declines");
});
// a satisfied requirement also falls through
{
  const c = ctxFor(["q.zoo"], ["q.zoo"]), terr = el("div");
  assert.strictEqual(vm.runInContext("renderRequirementPanel", c)(terr, "t:target", null), false);
}
ok("0 requirements (and fully satisfied requirements) fall through to the normal attack UI");

// 2) ONE requirement -> locked panel, human-readable title, one Study entry point
{
  const c = ctxFor(["q.zoo"], []), terr = el("div");
  assert.strictEqual(vm.runInContext("renderRequirementPanel", c)(terr, "t:target", null), true);
  assert(/🔒/.test(terr.innerHTML) && /Zoo — Yes\/No/.test(terr.innerHTML), terr.innerHTML);
  assert(/✗/.test(terr.innerHTML) && /req-missing/.test(terr.innerHTML));
  // singular copy: no "all of these", no plural noun
  assert(/you need this requirement:/.test(terr.innerHTML), "singular wording: " + terr.innerHTML);
  assert(!/all<\/b> of these|requirements:/.test(terr.innerHTML), "no plural/all wording for one requirement");
  assert(!/q\.zoo/.test(terr.innerHTML), "the raw opaque id must not be shown to a learner");
  const btns = allButtons(terr);
  assert.strictEqual(btns.length, 1, "one missing requirement -> one Study button");
  assert(/Study: Zoo — Yes\/No/.test(btns[0].textContent), btns[0].textContent);
}
ok("1 requirement: locked panel shows the human-readable title (never the raw id) + one Study entry");

// 3) MULTIPLE requirements -> every requirement listed independently with its own ✓/✗ and entry point
{
  const c = ctxFor(["q.greetings", "q.zoo"], ["q.greetings"]), terr = el("div");
  assert.strictEqual(vm.runInContext("renderRequirementPanel", c)(terr, "t:target", null), true);
  const items = terr.innerHTML.match(/<li[^>]*>.*?<\/li>/g) || [];
  assert.strictEqual(items.length, 2, "one <li> per requirement: " + terr.innerHTML);
  // plural copy keeps "all of these requirements"
  assert(/you need <b>all<\/b> of these requirements:/.test(terr.innerHTML),
    "plural wording: " + terr.innerHTML);
  assert(/✓ Basic Greetings/.test(items[0]) && /req-ok/.test(items[0]), items[0]);
  assert(/✗ Zoo — Yes\/No/.test(items[1]) && /req-missing/.test(items[1]), items[1]);
  const btns = allButtons(terr);
  assert.strictEqual(btns.length, 1, "only the MISSING requirement gets a Study button");
  // three requirements, two missing -> two independent Study buttons (no 'only one' assumption)
  const c3 = ctxFor(["q.greetings", "q.zoo", "q.unknown"], []), terr3 = el("div");
  vm.runInContext("renderRequirementPanel", c3)(terr3, "t:target", null);
  assert.strictEqual((terr3.innerHTML.match(/<li/g) || []).length, 3);
  const b3 = allButtons(terr3);
  assert.strictEqual(b3.length, 3, "one entry point per missing requirement");
  const unknown = b3.find(b => /q\.unknown/.test(b.textContent));
  assert(unknown && unknown.disabled === true, "a requirement with no installed content is disabled, not hidden");
  assert(/Not available yet/.test(unknown.textContent), unknown.textContent);
}
ok("N requirements: each rendered independently with ✓/✗, one entry point per missing one");

// 4) Study navigation comes from Learning METADATA (studyTarget -> contentPath -> article)
{
  const c = ctxFor(["q.zoo"], []), terr = el("div");
  vm.runInContext("renderRequirementPanel", c)(terr, "t:target", function () { c.log.push("reopen"); });
  allButtons(terr)[0].click();
  assert.deepStrictEqual(c.log, ["closeModal", "selectArticle:Pre-A1/taipei/zoo"], c.log);
  assert(c.pendingStudy && c.pendingStudy.qualificationIds.includes("q.zoo"), "return context is captured");
  assert.strictEqual(c.pendingStudy.label, "Region t:target");
  // metadata drives it: point the SAME qualification at the other lesson and navigation follows
  const c2 = makeCtx({
    learningRegistry: { qualifications: { "q.zoo": { title: "Zoo — Yes/No",
      studyTarget: { activityId: "a.zoo", lessonId: "l.greet", contentPath: "Pre-A1/basics/greet" } } },
      activities: REG.activities, lessons: {} },
    manifest: MANIFEST });
  c2.TERR_CATALOG.terrById["t:target"] = { requirements: { attackQualificationIds: ["q.zoo"] } };
  const terr2 = el("div");
  vm.runInContext("renderRequirementPanel", c2)(terr2, "t:target", null);
  allButtons(terr2)[0].click();
  assert.deepStrictEqual(c2.log, ["closeModal", "selectArticle:Pre-A1/basics/greet"],
    "changing only the metadata changes where Study goes — no hardcoded lesson anywhere");
}
// and there is genuinely no hardcoded content branch in the shipped source
const src = FNS.join("\n");
[/zoo/i, /taipei/i, /pre-a1/i, /quiz3/, /english\./i].forEach(re =>
  assert(!re.test(src), "requirement/study code must not hardcode content: " + re));
ok("Study navigation is metadata-driven (studyTarget -> contentPath); no hardcoded Zoo/lesson logic");

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
  // level 5 (matching) is deliberately NOT migrated - it must have no attempt submission
  const match = extractFn(html, "function makeMatch(");
  assert(match.indexOf("maybeSubmitLearningAttempt") < 0,
    "makeMatch must NOT submit: matching is category B and stays client-scored in Phase 3C");
  assert(/recordScore\(5, firstTry, seq\.length\)/.test(match), "makeMatch keeps its existing scoring");
}
ok("Phase 3C: quiz/wh/cloze/dictation/reorder submit evidence to one endpoint; matching left unmigrated");

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

  // a PASSING response is mirrored (display only) and the return-to-territory offer appears
  const c2 = makeCtx({ learningRegistry: REG, manifest: MANIFEST });
  c2.pendingStudy = { qualificationIds: ["q.zoo"], label: "Region t:target",
    reopen: () => c2.log.push("reopen") };
  c2._fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(
    { ok: true, passed: true, qualifications: ["q.zoo"], rewarded: true, gold: 12345 }) });
  vm.runInContext("maybeSubmitLearningAttempt", c2)("Pre-A1/taipei/zoo", "quiz3", []);
  await settle();
  assert(c2.myQualifications.has("q.zoo"), "server-confirmed pass updates the display mirror");
  assert.strictEqual(c2.myEcon.gold, 12345, "gold comes from the server response, never computed");
  assert(c2.log.some(l => /^toast:/.test(l) && /Zoo — Yes\/No/.test(l)), c2.log);
  const btn = c2.document.body.children.find(x => x.id === "studyReturn");
  assert(btn && /unlocked/.test(btn.textContent), "return-to-territory offer is shown");
  btn.click();
  assert(c2.log.includes("selectLevel") && c2.log.includes("reopen"),
    "clicking it goes back to the map and reopens the originating territory");
  assert.strictEqual(c2.pendingStudy, null, "the return context is consumed once");

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
