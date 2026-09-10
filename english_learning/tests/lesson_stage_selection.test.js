"use strict";
// Lesson stage selection — the CLIENT half.
//
//     node tests/lesson_stage_selection.test.js
//
// Source-level, no DOM framework, following this suite's convention: the real stage-selector module
// and the real click-to-speak module are extracted out of index.html and executed against small
// stubs, so the assertions are about shipped code rather than a reimplementation.
//
// The economic guarantees are NOT asserted here -- they belong to the server and are covered by
// tests/lesson_replay_idempotency_test.py. What this file proves is that the UI offers free choice
// and replay, reads its status from the authoritative progress it is given, never invents a second
// source of truth, and does not start narrating navigation controls.

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const vm = require("vm");

let passed = 0;
function ok(name) { passed++; console.log("  ok -", name); }

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");

function extractFn(src, sig) {
  const s = src.indexOf(sig);
  assert(s >= 0, "cannot find " + sig);
  let i = src.indexOf("{", s), d = 0;
  for (; i < src.length; i++) {
    if (src[i] === "{") d++;
    else if (src[i] === "}") { d--; if (d === 0) return src.slice(s, i + 1); }
  }
  throw new Error("unbalanced braces for " + sig);
}
function region(src, a, b) {
  const i = src.indexOf(a); assert(i >= 0, "cannot find " + a);
  const j = src.indexOf(b, i); assert(j > i, "cannot find " + b);
  return src.slice(i, j);
}

// The stage-selector module, whole, as it ships (contract through lsOpenStage + the jump button).
const STAGE_SRC = region(html, "let lsRewardsByActivity", "function lsDecorateSteps(");
// The click-to-speak module, whole, so "a stage row must not speak" is tested against the real
// delegated listener rather than against a copy of its selector list.
const SPEAK_SRC = region(html, "const SPEAK_HOSTS", "function makeQuiz(");

/* ------------------------------------------------------------------ tiny DOM */
function el(tag, cls) {
  const e = {
    tagName: tag, nodeType: 1, className: cls || "", id: "", title: "", type: "",
    childNodes: [], parent: null, dataset: {}, disabled: false, _on: {}, _attrs: {},
    _text: "", _html: "", style: {},
    classList: {
      contains(c) { return (" " + e.className + " ").indexOf(" " + c + " ") >= 0; },
      add(c) { if (!this.contains(c)) e.className = (e.className + " " + c).trim(); },
      remove(c) { e.className = (" " + e.className + " ").replace(" " + c + " ", " ").trim(); },
      toggle(c, on) { if (on === undefined) { this.contains(c) ? this.remove(c) : this.add(c); } else if (on) this.add(c); else this.remove(c); },
    },
    get textContent() {
      return e.childNodes.length
        ? e.childNodes.map(n => n.nodeType === 3 ? n.nodeValue : n.textContent).join("") : e._text;
    },
    set textContent(v) { e._text = String(v); e.childNodes = []; },
    get innerHTML() { return e._html; },
    set innerHTML(v) { e._html = String(v); e.childNodes = []; },
    setAttribute(k, v) { e._attrs[k] = String(v); },
    getAttribute(k) { return e._attrs[k] == null ? null : e._attrs[k]; },
    appendChild(c) { c.parent = e; e.childNodes.push(c); return c; },
    addEventListener(ev, fn) { (e._on[ev] = e._on[ev] || []).push(fn); },
    click() { (e._on.click || []).forEach(f => f()); },
    matches(sel) {
      return sel.split(",").map(s => s.trim()).filter(Boolean).some(one => {
        const p = one.split(/\s+/), last = p[p.length - 1];
        if (!sm(e, last)) return false;
        if (p.length === 1) return true;
        for (let q = e.parent; q; q = q.parent) if (sm(q, p[0])) return true;
        return false;
      });
    },
    closest(sel) { for (let n = e; n; n = n.parent) if (n.matches && n.matches(sel)) return n; return null; },
    querySelector(sel) { return e.querySelectorAll(sel)[0] || null; },
    querySelectorAll(sel) {
      const out = [];
      (function walk(n) {
        n.childNodes.forEach(c => { if (c.nodeType !== 1) return; if (c.matches(sel)) out.push(c); walk(c); });
      })(e);
      return out;
    },
  };
  return e;
}
function sm(n, one) {
  if (one.charAt(0) === "#") return n.id === one.slice(1);
  if (one.charAt(0) === ".") return n.classList && n.classList.contains(one.slice(1));
  return n.tagName === one;
}

// The ten activity tabs, in the page's own DOM order (= the pedagogical order).
const TAB_DEFS = [
  ["1", "Listen 👂"], ["2", "Read Along 🎤"], ["3", "Quiz ✅"], ["4", "Tricky Quiz 🤔"],
  ["5", "Matching 🖼️"], ["6", "Reorder 🧩"], ["7", "WH Questions ❓"], ["8", "Dictation ✍️"],
  ["9", "Fill in the Blank 📝"], ["10", "Role-play 🎭"],
];
const LESSON = "english.prea1.taipei.zoo";
const PATH = "Pre-A1/taipei/zoo";
// The registry shape the page actually receives from /api/learning/registry (public_view).
const ACTS = {};
[["read_along", "stt", null], ["quiz3", "deterministic", "quiz3"], ["quiz4", "deterministic", "quiz4"],
 ["matching", "matching", "vocab"], ["reorder", "deterministic", "reorder"],
 ["wh", "deterministic", "wh"], ["cloze", "deterministic", "cloze"],
 ["dictation", "deterministic", "dictation"], ["roleplay", "roleplay", null],
].forEach(([suffix, scored, key]) => {
  ACTS[LESSON + "." + suffix] = { contentPath: PATH, contentKey: key, scored: scored,
                                  title: "Zoo — " + suffix };
});

function makeEnv(opts) {
  opts = opts || {};
  const tabs = TAB_DEFS.map(([lv, name]) => {
    const t = el("div", "levelTab ls-step");
    t.dataset.level = lv; t.dataset.name = name;
    // `data-avail` is what applyRegistryTabs() stamps: does this LESSON offer the activity.
    t.dataset.avail = (opts.avail || ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]).indexOf(lv) >= 0 ? "1" : "0";
    if ((opts.doneTabs || []).indexOf(lv) >= 0) t.classList.add("done");
    if ((opts.lockedTabs || []).indexOf(lv) >= 0) t.classList.add("locked");
    return t;
  });
  const ids = {};
  function need(id) { if (!ids[id]) { const e = el("div"); e.id = id; ids[id] = e; } return ids[id]; }
  need("lsStages"); need("lsStageList"); need("lsStagesSub");
  need("finishGameBtn").classList.add("hidden");

  const calls = { tabClicks: [], listen: 0, rewardGames: [], fetches: [] };
  tabs.forEach(t => t.addEventListener("click", () => calls.tabClicks.push(t.dataset.level)));

  const spoken = [];
  const sandbox = {
    console,
    tabs: tabs,
    document: {
      getElementById: need,
      createElement: el,
      querySelector(sel) {
        const m = /^\.levelTab\[data-level="(\d+)"\]$/.exec(sel);
        if (m) return tabs.filter(t => t.dataset.level === m[1])[0] || null;
        return null;
      },
      querySelectorAll() { return []; },
      addEventListener(ev, fn) { (sandbox._doc = sandbox._doc || {})[ev] = fn; },
    },
    currentArticleKey: PATH,
    // the registry shape /api/learning/registry actually returns; `lessons` is what
    // lessonIdForContent() uses to find the progress row for this content path
    learningRegistry: {
      activities: ACTS, qualifications: {},
      lessons: { [LESSON]: { contentPath: PATH, title: "At the Zoo",
                             authoritativeCompletionAvailable: true } },
    },
    learningProgress: { lessons: opts.progress || {}, campaigns: {}, completedLessonIds: [] },
    myActivityDone: new Set(opts.serverDone || []),
    authToken: () => opts.token === undefined ? "tok" : opts.token,
    withRoom: u => u,
    fetch(u) {
      calls.fetches.push(u);
      const body = opts.rewards || { pending: [], resolved: [], prizes: [] };
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
    },
    rgPrizes: null,
    openRewardGame(ent) { calls.rewardGames.push(ent); },
    // collaborators lsShowStages touches
    synth: { cancel() {} }, stopListenL1() {}, stopRecordingIfAny() {}, stopRolePlay() {},
    updateScene() {}, enterListenMode() { calls.listen++; },
    onLevel1: true,
    levelFinish: el("div"), startTestWrap: el("div"),
    levelsBar: el("div"), levelNameEl: el("div"),
    level1El: el("div"), level2El: el("div"), level3El: el("div"), level4El: el("div"),
    level5El: el("div"), level6El: el("div"), level7El: el("div"), level8El: el("div"),
    level9El: el("div"), level10El: el("div"),
    loadLearningState(cb) { if (cb) cb(); }, loadLearningProgress(cb) { if (cb) cb(); },
    window: {},
    // ---- the pieces the module leans on, real, extracted ----
    TAB_BY_SCORED: null, TAB_BY_KEY: null,
    // ---- click-to-speak collaborators ----
    speakQuestion(t) { spoken.push(t); }, speakSequence(a) { a.forEach(t => spoken.push(t)); },
    isRecording: false, rpRecording: false, isPlaying: false,
  };
  vm.createContext(sandbox);
  // real level<->activity mapping + the real required/progress readers
  vm.runInContext(
    region(html, "const TAB_BY_SCORED", "// \"Taipei · At the Zoo") + "\n" +
    extractFn(html, "function lsRequiredTabs(") + "\n" +
    extractFn(html, "function progressForContent(") + "\n" +
    extractFn(html, "function lessonIdForContent(") + "\n" +
    extractFn(html, "function refreshLockedTabs(") + "\n" +
    STAGE_SRC + "\n" + SPEAK_SRC + "\n" +
    // the post-activity mini-game action lives beside showNextLevel, outside STAGE_SRC
    "const finishGameBtn = document.getElementById('finishGameBtn');\n" +
    extractFn(html, "function lsFinishGameFor("), sandbox);
  return { sandbox, tabs, ids, calls, spoken, need,
    rows() { return ids.lsStageList.querySelectorAll(".ls-stage"); },
    click(node) {
      for (let n = node; n; n = n.parent) if (n._on.click && n._on.click.length) { n._on.click.forEach(f => f()); break; }
      if (sandbox._doc && sandbox._doc.click) sandbox._doc.click({ target: node });
    },
  };
}

// A progress row shaped exactly like /api/learning/progress emits one.
function progressRow(opts) {
  return {
    [LESSON]: Object.assign({
      title: "At the Zoo",
      authoritativeCompletionAvailable: true,
      requiredActivityIds: [LESSON + ".read_along", LESSON + ".quiz3", LESSON + ".quiz4",
                            LESSON + ".matching", LESSON + ".wh", LESSON + ".cloze",
                            LESSON + ".roleplay"],
      completedActivityIds: [],
      missingActivityIds: [],
      currentPolicySatisfied: false,
    }, opts || {}),
  };
}

/* ============================================================ 1. every configured activity shows */
{
  const env = makeEnv({ progress: progressRow() });
  env.sandbox.lsRenderStages();
  const rows = env.rows();
  assert.strictEqual(rows.length, 10, "expected all ten offered activities, got " + rows.length);
  const names = rows.map(r => r.querySelector(".ls-stage-nm").textContent.replace("★", ""));
  assert.deepStrictEqual(names, TAB_DEFS.map(d => d[1]), names.join(" | "));
  ok("the selector lists every activity the lesson offers, in the page's own pedagogical order");

  // a lesson with fewer activities shows fewer rows -- the set is not hard-coded
  const env2 = makeEnv({ progress: progressRow(), avail: ["1", "2", "3", "5"] });
  env2.sandbox.lsRenderStages();
  const got = env2.rows().map(r => r.dataset.level);
  assert.deepStrictEqual(got, ["1", "2", "3", "5"], got.join(","));
  ok("a lesson offering only 4 activities renders exactly those 4 (set comes from the registry)");

  // `data-avail`, not the transient `hidden` class, decides membership
  assert(/dataset\.avail !== "1"/.test(STAGE_SRC), "membership must read data-avail");
  assert(!/classList\.contains\("hidden"\)/.test(
    STAGE_SRC.slice(0, STAGE_SRC.indexOf("function lsRenderStages"))),
    "lsLessonStages must not consult the hidden class");
  ok("membership comes from data-avail (registry), never from the hidden class (navigation state)");
}

/* ============================================================ 2. free, out-of-order selection */
{
  const env = makeEnv({ progress: progressRow() });
  env.sandbox.lsRenderStages();
  const rows = env.rows();
  // pick the LAST activity first, then jump about
  const order = ["10", "7", "3", "6"];
  order.forEach(lv => {
    const row = rows.filter(r => r.dataset.level === lv)[0];
    assert(row, "no row for level " + lv);
    row._on.click.forEach(f => f());
  });
  assert.deepStrictEqual(env.calls.tabClicks, order, env.calls.tabClicks.join(","));
  ok("activities open in any order the learner picks (last-first, then 7 → 3 → 6)");

  // nothing is disabled and nothing is marked locked
  assert(rows.every(r => r.disabled === false), "no stage row may be disabled");
  assert(rows.every(r => !r.classList.contains("locked")), "no stage row may be locked");
  ok("no stage row is disabled or locked — there is no sequential gate");

  // and the shipped lock helper now only ever CLEARS locks
  const env2 = makeEnv({ lockedTabs: ["4", "5", "6"] });
  env2.sandbox.refreshLockedTabs();
  assert(env2.tabs.every(t => !t.classList.contains("locked")),
    "refreshLockedTabs must clear every lock");
  ok("refreshLockedTabs() clears locks rather than applying them (the score gate is gone)");
}

/* ============================================================ 3/4. completed rows stay replayable */
{
  // completion from the SERVER's lesson row (required activities)
  const env = makeEnv({ progress: progressRow({ completedActivityIds: [LESSON + ".quiz3", LESSON + ".matching"] }) });
  env.sandbox.lsRenderStages();
  const by = {};
  env.rows().forEach(r => { by[r.dataset.level] = r; });
  assert(by["3"].classList.contains("is-done"), "quiz3 should be ticked");
  assert(by["5"].classList.contains("is-done"), "matching should be ticked");
  assert(!by["6"].classList.contains("is-done"), "reorder should not be ticked");
  assert.strictEqual(by["3"].querySelector(".ls-stage-ico").textContent, "✓");
  assert.strictEqual(by["6"].querySelector(".ls-stage-ico").textContent, "○");
  assert.strictEqual(by["3"].querySelector(".ls-stage-go").textContent, "Replay");
  assert.strictEqual(by["6"].querySelector(".ls-stage-go").textContent, "Start");
  assert(/Completed · Replay/.test(by["3"].querySelector(".ls-stage-sub").textContent),
    by["3"].querySelector(".ls-stage-sub").textContent);
  assert.strictEqual(by["3"].disabled, false, "a completed activity must stay selectable");
  by["3"]._on.click.forEach(f => f());
  assert.deepStrictEqual(env.calls.tabClicks, ["3"], "clicking a completed row replays it");
  ok("completed rows show ✓ / \"Completed · Replay\", stay enabled, and replay when clicked");

  // completion of an OPTIONAL activity comes from the account's own pass records
  const env2 = makeEnv({
    progress: progressRow({ completedActivityIds: [] }),
    serverDone: [LESSON + ".dictation"],          // dictation is not in requiredActivityIds
  });
  env2.sandbox.lsRenderStages();
  const d = env2.rows().filter(r => r.dataset.level === "8")[0];
  assert(d.classList.contains("is-done"), "an optional activity's own pass record must tick it");
  assert(/Optional practice|Completed/.test(d.querySelector(".ls-stage-sub").textContent));
  ok("an OPTIONAL activity is ticked from the account's authoritative pass records");

  // guest / offline: the pre-existing local `.done` mark still works
  const env3 = makeEnv({ progress: {}, token: null, doneTabs: ["7"] });
  env3.sandbox.lsRenderStages();
  const w = env3.rows().filter(r => r.dataset.level === "7")[0];
  assert(w.classList.contains("is-done"), "the local done mark is the guest fallback");
  ok("a guest with no server row still sees local completion (existing fallback preserved)");
}

/* ============================================================ 5. required vs optional labelling */
{
  const env = makeEnv({ progress: progressRow() });
  env.sandbox.lsRenderStages();
  const by = {};
  env.rows().forEach(r => { by[r.dataset.level] = r; });
  assert(by["3"].classList.contains("is-required"), "quiz3 is in requiredActivityIds");
  assert(!by["8"].classList.contains("is-required"), "dictation is not required by this policy");
  assert.strictEqual(by["3"].querySelector(".ls-stage-sub").textContent, "Required for mastery");
  assert.strictEqual(by["8"].querySelector(".ls-stage-sub").textContent, "Optional practice");
  assert.strictEqual(by["1"].querySelector(".ls-stage-sub").textContent, "Read & listen");
  const sub = env.ids.lsStagesSub.textContent;
  assert(/0 of 10 done/.test(sub) && /0\/7 required/.test(sub), sub);
  ok("required/optional/reading labels and the summary line all come from the server's row");
}

/* ============================================================ 6. the selector is PERMANENT */
{
  const env = makeEnv({ progress: progressRow() });
  env.sandbox.lsShowStages();
  assert(!env.ids.lsStages.classList.contains("hidden"), "the list must be visible");
  assert.strictEqual(env.sandbox.levelsBar.style.display, "none",
    "the tab strip must not be a second navigation surface");
  // opening a stage leaves the list ON SCREEN -- that is what makes Back/Next unnecessary
  env.sandbox.lsOpenStage("6");
  assert(!env.ids.lsStages.classList.contains("hidden"),
    "the stage list must stay visible while an activity is open");
  assert.strictEqual(env.sandbox.levelsBar.style.display, "none", "the strip stays hidden");
  assert.deepStrictEqual(env.calls.tabClicks, ["6"]);
  // and it is still usable: another activity can be chosen straight away, with no "back" step
  env.sandbox.lsRenderStages();
  env.rows().filter(r => r.dataset.level === "9")[0]._on.click.forEach(f => f());
  assert.deepStrictEqual(env.calls.tabClicks, ["6", "9"],
    "the visible list must remain usable with an activity open");
  ok("the selector stays visible AND usable while an activity is open, so no in-activity " +
     "'back to lesson' control is needed");

  // Listen has its own screen, so it routes through enterListenMode(), not through a tab
  const env2 = makeEnv({ progress: progressRow() });
  env2.sandbox.lsOpenStage("1");
  assert.strictEqual(env2.calls.listen, 1, "Listen must reuse enterListenMode()");
  assert.deepStrictEqual(env2.calls.tabClicks, [], "Listen is not a tab click");
  assert(!env2.ids.lsStages.classList.contains("hidden"),
    "the reading view keeps the list above it too");
  ok("choosing Listen opens the reading view with the list still above it");

  // opening an unknown level cannot strand the learner
  const env3 = makeEnv({ progress: progressRow() });
  env3.sandbox.lsOpenStage("99");
  assert(!env3.ids.lsStages.classList.contains("hidden"), "an unknown stage returns to the list");
  ok("an unknown stage id falls back to the list rather than a blank screen");

  // leaving an activity stops its audio
  const env4 = makeEnv({ progress: progressRow() });
  let cancelled = 0, stoppedRec = 0;
  env4.sandbox.synth = { cancel() { cancelled++; } };
  env4.sandbox.stopRecordingIfAny = function () { stoppedRec++; };
  env4.sandbox.lsShowStages();
  assert(cancelled >= 1 && stoppedRec >= 1, "returning to the list must silence speech and recording");
  ok("returning to the list cancels speech and stops any recording");
}

/* ============================================================ 7. the shipped wiring (real source) */
{
  // COMPLETING AN ACTIVITY MUST RENDER NEITHER "Back to Lesson" NOR "Next".
  // Both controls, and every reference to them, are gone from the page -- not merely hidden.
  ["nextLevelBtn", "backToStagesBtn", "shadowNextLevel", "lsStagesBtn"].forEach(function (id) {
    assert(html.indexOf(id) < 0, id + " still exists in the page");
  });
  // Labels are checked against the page with COMMENTS STRIPPED: the removal is deliberately
  // explained in prose where the buttons used to be, and prose is not a rendered control.
  const bare = html.replace(/<!--[\s\S]*?-->/g, "")
                   .replace(/\/\*[\s\S]*?\*\//g, "")
                   .replace(/^\s*\/\/[^\n]*$/gm, "");
  ["Back to Lesson", "Back to lessons", "Next Level"].forEach(function (label) {
    assert(bare.indexOf(label) < 0, "the label '" + label + "' survives in the page");
  });
  // the finish panel now offers exactly Try Again + the mini-game action
  const finishPanel = region(html, 'id="levelFinish"', "</div>\n    </div>");
  const finishBtns = (finishPanel.match(/<button[^>]*id="([^"]+)"/g) || [])
    .map(function (m) { return /id="([^"]+)"/.exec(m)[1]; });
  assert.deepStrictEqual(finishBtns, ["finishRetry", "finishGameBtn"], finishBtns.join(","));
  // the read-along finish panel likewise keeps only Try Again
  const shadowPanel = region(html, 'id="shadowFinish"', "</div>\n    </div>");
  const shadowBtns = (shadowPanel.match(/<button[^>]*id="([^"]+)"/g) || [])
    .map(function (m) { return /id="([^"]+)"/.exec(m)[1]; });
  assert.deepStrictEqual(shadowBtns, ["shadowRetry"], shadowBtns.join(","));
  // and showNextLevel neither advances nor leaves the lesson
  const nextFn = extractFn(html, "function showNextLevel(");
  assert(!/\.click\(\)/.test(nextFn), "completing an activity must not open another one");
  assert(!/selectLevel\(/.test(nextFn), "completing an activity must not leave the lesson");
  assert(/lsFinishGameFor\(/.test(nextFn), "the mini-game action must be offered");
  assert(/lsRenderStages\(\)/.test(nextFn), "the selector must be repainted on completion");
  ok("activity completion renders NEITHER 'Back to Lesson' NOR 'Next': both finish panels hold " +
     "only [Try Again] + [mini-game], and showNextLevel neither advances nor navigates away");

  // Back/Next elsewhere in the app are untouched
  ["backToList", "backToLevels", "battleBack", "backToRole", "backFromTeacher", "backFromAdmin"]
    .forEach(function (id) {
      assert(html.indexOf('id="' + id + '"') >= 0, "unrelated control " + id + " was removed");
    });
  ok("unrelated Back controls (Academy, Levels, Boss battle, role/teacher/admin screens) remain");

  // the score gate is gone from the tab handler, and no unlock helper survives.
  // Comments are stripped first: this is an assertion about CODE, and the removal is deliberately
  // explained in prose right where the gate used to be.
  const strip = s => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
  const tabHandler = strip(region(html, "tabs.forEach(tab => tab.addEventListener",
                                   "function restoreProgress("));
  assert(!/maxUnlockedIndex/.test(tabHandler), "the tab handler must not consult an unlock index");
  assert(!/showLockedMsg\(\)/.test(tabHandler), "the tab handler must not refuse a tab");
  assert(!/classList\.toggle\("locked"/.test(tabHandler), "nothing may re-apply a lock");
  assert(!/function maxUnlockedIndex/.test(strip(html)), "the unlock helper should be retired");
  ok("the tab click handler no longer gates on score, nothing re-applies a lock, and " +
     "maxUnlockedIndex() is retired");

  // entering practice lands on the list rather than auto-opening the first activity
  const enter = strip(extractFn(html, "function enterTestMode("));
  assert(/lsShowStages\(\)/.test(enter), "entering practice must show the stage list");
  assert(!/firstVisible/.test(enter), "it must not auto-open the first activity");
  assert(!/\.click\(\)/.test(enter), "entering practice must open no activity at all");
  assert(/spendStamina\(STAMINA_COST\)/.test(enter), "the energy rule must be unchanged");
  ok("enterTestMode() lands on the stage list, spends energy exactly as before, and auto-opens nothing");

  // grading, thresholds and authority are untouched by this change
  assert(/const PASS_MARK = 80;/.test(html), "PASS_MARK changed");
  const quiz = extractFn(html, "function makeQuiz(");
  assert(/if \(b\.textContent === right\)/.test(quiz), "quiz grading key changed");
  const wh = extractFn(html, "function makeWh(");
  assert(/if \(b\.dataset\.val === it\.a\)/.test(wh), "WH grading key changed");
  const ro = extractFn(html, "function makeReorder(");
  assert(/placed\.every\(\(id, i\) => id === i\)/.test(ro), "reorder grading changed");
  assert(/tokens = sentences\[idx\]\.map\(\(w, i\) => \(\{ id: i, word: w \}\)\)/.test(ro),
    "reorder token identity changed");
  const dict = extractFn(html, "function makeDictation(");
  assert(/norm\(input\.value\) === norm\(sentence\)/.test(dict), "dictation comparison changed");
  ok("PASS_MARK and every grading key (quiz/WH/reorder/dictation) are unchanged");

  // completion is only ever ADDED, never cleared, so a replay cannot un-complete history
  const mark = extractFn(html, "function markLevelDone(");
  assert(/classList\.add\("done"\)/.test(mark) && !/classList\.remove\("done"\)/.test(mark),
    "markLevelDone must only ever add");
  const deco = extractFn(html, "function lsDecorateSteps(");
  assert(/classList\.add\("done"\)/.test(deco) && !/classList\.remove\("done"\)/.test(deco),
    "lsDecorateSteps must never clear a completion");
  assert(!/removeAttribute|delete .*completedActivityIds|\.done = false/.test(STAGE_SRC),
    "the stage selector must never clear completion state");
  ok("nothing in the new code clears a completion: replay cannot rewrite history");
}

/* ============================================================ 8. click-to-speak is not regressed */
{
  // The stage rows must NOT be treated as learner English. This runs the REAL delegated listener.
  const env = makeEnv({ progress: progressRow({ completedActivityIds: [LESSON + ".quiz3"] }) });
  env.sandbox.lsRenderStages();
  const rows = env.rows();
  rows.forEach(r => {
    env.click(r);                                       // whole row
    env.click(r.querySelector(".ls-stage-nm"));         // its label
    env.click(r.querySelector(".ls-stage-go"));         // its Start/Replay pill
    env.click(r.querySelector(".ls-stage-ico"));        // its ✓/○
  });
  assert.deepStrictEqual(env.spoken, [],
    "the stage selector must never speak: " + env.spoken.join(" | "));
  ok("clicking a stage row, its name, its ✓/○ or its Start/Replay pill speaks nothing (" +
     (rows.length * 4) + " clicks)");

  // the jump-back and Back-to-Lesson controls are equally silent
  const nav = [el("button", "ls-back-btn"), el("button", "ac-back"), el("button", "ls-stage-game")];
  nav[0].textContent = "📋 Back to Lesson";
  nav[1].textContent = "📋 Activities";
  nav[2].textContent = "🎰 Play again (no extra reward)";
  nav.forEach(b => env.click(b));
  assert.deepStrictEqual(env.spoken, [], "navigation controls spoke: " + env.spoken.join(" | "));
  ok("Back to Lesson / Activities / Play-again controls are not speech hosts");

  // and real learning content inside an activity still speaks, through the same listener
  const opt = el("button", "opt"); opt.textContent = "Yes";
  env.click(opt);
  const chip = el("button", "chip"); chip.textContent = "soccer.";
  env.click(chip);
  const word = el("div", "mword");
  const ww = el("span", "wword"); ww.textContent = "apple"; word.appendChild(ww);
  env.click(word);
  assert.deepStrictEqual(env.spoken, ["Yes", "soccer.", "apple"], env.spoken.join(" | "));
  ok("Yes/No, reorder tokens and matching vocabulary still speak inside an activity");

  // the selector's class names cannot collide with a speech host
  const hosts = (SPEAK_SRC.match(/const SPEAK_HOSTS = ([^;]+);/) || [])[1] || "";
  ["ls-stage", "ls-stage-go", "ls-stage-nm", "ls-stage-ico", "ls-stage-game", "ls-back-btn"]
    .forEach(c => assert(hosts.indexOf(c) < 0, c + " must not be a speech host"));
  ok("no stage-selector class appears in SPEAK_HOSTS");
}

/* ============================================================ 9. reward state is reported, not decided */
(async function rewardsAsync() {
  const env = makeEnv({
    progress: progressRow({ completedActivityIds: [LESSON + ".quiz3"] }),
    rewards: {
      pending: [{ id: LESSON + ".wh", game: "dice_roll", createdAt: 2 }],
      resolved: [{ id: LESSON + ".quiz3", game: "lucky_wheel", prizeId: "gold_3000", resolvedAt: 1 }],
      prizes: [{ id: "gold_3000", label: "3,000 Gold" }],
    },
  });
  await new Promise(res => env.sandbox.lsSyncRewards(res));
  env.sandbox.lsRenderStages();
  const by = {};
  env.rows().forEach(x => { by[x.dataset.level] = x; });
  assert(/★/.test(by["3"].querySelector(".ls-stage-nm").textContent), "a settled reward needs ★");
  assert(!/★/.test(by["7"].querySelector(".ls-stage-nm").textContent),
    "a pending reward is not yet earned, so no ★");
  const games = env.ids.lsStageList.querySelectorAll(".ls-stage-game");
  assert.strictEqual(games.length, 2, "a settled and a pending entitlement each offer their game");
  assert(/Play again \(no extra reward\)/.test(games[0].textContent), games[0].textContent);
  assert(/Open your reward game/.test(games[1].textContent), games[1].textContent);
  // association is by ACTIVITY ID, never by row position
  games[0]._on.click.forEach(f => f({ stopPropagation() {} }));
  games[1]._on.click.forEach(f => f({ stopPropagation() {} }));
  assert.deepStrictEqual(env.calls.rewardGames.map(e => e.id + ":" + e.game),
    [LESSON + ".quiz3:lucky_wheel", LESSON + ".wh:dice_roll"],
    env.calls.rewardGames.map(e => e.id).join(","));
  ok("★ and the mini-game buttons come from the server's entitlement list, keyed by activity id " +
     "(settled → play again for fun; pending → open your reward game)");

  // a guest has no entitlements to show and no request is made
  const env2 = makeEnv({ progress: progressRow(), token: null });
  await new Promise(res => env2.sandbox.lsSyncRewards(res));
  assert.deepStrictEqual(env2.calls.fetches, [], "a guest must not be asked about rewards");
  env2.sandbox.lsRenderStages();
  assert.strictEqual(env2.ids.lsStageList.querySelectorAll(".ls-stage-game").length, 0);
  ok("a guest sees no reward-game rows and triggers no reward request");

  // ---- the ONE post-activity action: the mini-game this activity earned ----
  // pending -> "Play Mini-game"; already settled -> "Play again (no extra reward)"; none -> hidden.
  const envG = makeEnv({
    progress: progressRow({ completedActivityIds: [LESSON + ".quiz3"] }),
    rewards: {
      pending: [{ id: LESSON + ".wh", game: "dice_roll", createdAt: 2 }],
      resolved: [{ id: LESSON + ".quiz3", game: "lucky_wheel", prizeId: "gold_3000", resolvedAt: 1 }],
      prizes: [],
    },
  });
  const gameBtn = envG.ids.finishGameBtn;
  // level 7 = wh, whose entitlement is still waiting to be played
  envG.sandbox.lsFinishGameFor("7");
  await new Promise(res => setTimeout(res, 0));
  assert(!gameBtn.classList.contains("hidden"), "a pending entitlement must offer its game");
  assert(/Play Mini-game/.test(gameBtn.textContent), gameBtn.textContent);
  gameBtn.onclick();
  assert.strictEqual(envG.calls.rewardGames[0].id, LESSON + ".wh",
    "the button must open the game belonging to the activity that just finished");
  // level 3 = quiz3, already settled -> replay for practice, stated as paying nothing
  envG.sandbox.lsFinishGameFor("3");
  await new Promise(res => setTimeout(res, 0));
  assert(!gameBtn.classList.contains("hidden"));
  assert(/Play again \(no extra reward\)/.test(gameBtn.textContent), gameBtn.textContent);
  gameBtn.onclick();
  assert.strictEqual(envG.calls.rewardGames[1].id, LESSON + ".quiz3");
  // level 6 = reorder, which earned nothing -> no action at all
  envG.sandbox.lsFinishGameFor("6");
  await new Promise(res => setTimeout(res, 0));
  assert(gameBtn.classList.contains("hidden"),
    "an activity with no entitlement must offer no post-activity action");
  ok("the post-activity panel offers exactly one action, the mini-game for THIS activity: " +
     "'Play Mini-game' when pending, 'Play again (no extra reward)' when settled, nothing otherwise");

  // the module contains no economic reasoning of its own
  const bare = STAGE_SRC.replace(/\/\/[^\n]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
  ["PASS_GOLD", "MASTERY", "rewardAmount", "econ_apply", "gold ="].forEach(t =>
    assert(bare.indexOf(t) < 0, "stage selector must not reason about " + t));
  assert(!/rewardAlreadyClaimed|alreadyClaimed/.test(bare),
    "the client must never hold a 'reward already claimed' flag of its own");
  ok("the stage-selector code holds no amount, payout or 'already claimed' logic — settlement is the server's");

  console.log("\nAll " + passed + " stage-selection checks passed.");
})().catch(e => { console.error(e); process.exit(1); });
