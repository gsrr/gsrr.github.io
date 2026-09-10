"use strict";
// The lesson stage mini-game's reward modal is DISMISS-ONLY.
//
//     node tests/lesson_reward_modal.test.js
//
// A stage mini-game is played with the lesson -- and its persistent stage selector -- still on
// screen behind the modal. So the result screen shows the prize and nothing else: closing it with
// the ✕ leaves the learner exactly where they were, free to choose the next activity from the
// selector. "Continue Learning" would duplicate that selector and "Go to World" would take them
// somewhere they never asked to go.
//
// The SAME modal is still reached from the Academy's reward banner, where there is no lesson
// underneath and those two exits are the only way onward. This file therefore pins both halves: the
// lesson result is dismiss-only, and the Academy result is unchanged.
//
// The prize, the balances and the payout are the server's and are pinned elsewhere
// (tests/reward_games_test.py, tests/lesson_replay_idempotency_test.py). Nothing here re-tests them.

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

/* ---------------------------------------------------------------- a small real-enough DOM
 * innerHTML is genuinely parsed into a tree, because that is what the assertions are about: the
 * modal's markup is built as a STRING by rgResult and openModal, so a stub that only stored the
 * string could not tell whether a button exists or what the card says. */
function mk(tag) {
  const e = {
    tagName: String(tag).toLowerCase(), nodeType: 1, className: "", id: "", type: "",
    childNodes: [], parent: null, _text: "", _on: {}, _attrs: {}, onclick: null,
    classList: {
      contains(c) { return (" " + e.className + " ").indexOf(" " + c + " ") >= 0; },
      add(c) { if (!this.contains(c)) e.className = (e.className + " " + c).trim(); },
      remove(c) { e.className = (" " + e.className + " ").replace(" " + c + " ", " ").trim(); },
    },
    get textContent() {
      return e.childNodes.length
        ? e.childNodes.map(n => n.nodeType === 3 ? n.nodeValue : n.textContent).join("") : e._text;
    },
    set textContent(v) { e._text = String(v); e.childNodes = []; },
    get innerHTML() { return e._html || ""; },
    set innerHTML(v) { e._html = String(v); e.childNodes = []; parseInto(e, String(v)); },
    setAttribute(k, v) { e._attrs[k] = String(v); },
    getAttribute(k) { return e._attrs[k] == null ? null : e._attrs[k]; },
    appendChild(c) { c.parent = e; e.childNodes.push(c); return c; },
    removeChild(c) { e.childNodes = e.childNodes.filter(x => x !== c); return c; },
    remove() { if (e.parent) e.parent.removeChild(e); },
    addEventListener(ev, fn) { (e._on[ev] = e._on[ev] || []).push(fn); },
    click() { (e._on.click || []).forEach(f => f()); if (e.onclick) e.onclick(); },
    matches(sel) {
      return sel.split(",").map(s => s.trim()).filter(Boolean).some(one => {
        if (one.charAt(0) === "#") return e.id === one.slice(1);
        if (one.charAt(0) === ".") return e.classList.contains(one.slice(1));
        return e.tagName === one.toLowerCase();
      });
    },
    querySelector(sel) { return e.querySelectorAll(sel)[0] || null; },
    querySelectorAll(sel) {
      const out = [];
      (function walk(n) {
        n.childNodes.forEach(c => {
          if (c.nodeType !== 1) return;
          if (c.matches(sel)) out.push(c);
          walk(c);
        });
      })(e);
      return out;
    },
  };
  return e;
}
function txt(v) { return { nodeType: 3, nodeValue: v, textContent: v }; }

// tag soup: <tag attrs>…</tag> and bare text, which is all the modal markup uses
const TAG = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>|([^<]+)/g;
function parseInto(host, src) {
  const stack = [host];
  let m;
  TAG.lastIndex = 0;
  while ((m = TAG.exec(src))) {
    const [, closing, tag, attrs, text] = m;
    const top = stack[stack.length - 1];
    if (text != null) { if (text.trim()) top.appendChild(txt(text)); continue; }
    if (closing) { if (stack.length > 1) stack.pop(); continue; }
    const el = mk(tag);
    const c = /class="([^"]*)"/.exec(attrs || ""); if (c) el.className = c[1];
    const i = /id="([^"]*)"/.exec(attrs || ""); if (i) el.id = i[1];
    const a = /aria-label="([^"]*)"/.exec(attrs || ""); if (a) el.setAttribute("aria-label", a[1]);
    top.appendChild(el);
    if (!/\/$/.test(attrs || "") && tag.toLowerCase() !== "br") stack.push(el);
  }
}

/* ---------------------------------------------------------------- the sandbox */
function makeEnv() {
  const body = mk("body");
  const nav = [];                       // every navigation side effect the modal could cause
  const byId = {};
  const sandbox = {
    console,
    document: {
      createElement: mk,
      getElementById(id) { return byId[id] || body.querySelectorAll("#" + id)[0] || null; },
      get body() { return body; },
    },
    escapeHtml: s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"),
    // navigation collaborators: recorded, never executed
    rgOpenNextPending(cb) { nav.push("rgOpenNextPending"); if (cb) cb(false); },
    openLearningHome() { nav.push("openLearningHome"); },
    goToGameMap() { nav.push("goToGameMap"); },
    loadEconomy(cb) { nav.push("loadEconomy"); if (cb) cb(); },
    loadTerritory(cb) { nav.push("loadTerritory"); if (cb) cb(); },
    renderEmpire() { nav.push("renderEmpire"); },
    refreshMap() { nav.push("refreshMap"); },
  };
  vm.createContext(sandbox);
  vm.runInContext([
    extractFn(html, "function openModal("),
    extractFn(html, "function closeModal("),
    extractFn(html, "function rgIcon("),
    extractFn(html, "function rgLabel("),
    // the real declaration, so the default under test is the shipped one
    (html.match(/^[ \t]*let rgFrom = "academy";$/m) || ['let rgFrom = "academy";'])[0],
    extractFn(html, "function rgResult("),
  ].join("\n"), sandbox);
  // `rgFrom` is a script-scoped `let`, so it is NOT a property of the sandbox: it is read and
  // written by running code in the same context, which is how the real page reaches it too.
  const from = v => vm.runInContext(
    v === undefined ? "rgFrom" : ("rgFrom = " + JSON.stringify(v)), sandbox);
  return {
    sandbox, body, nav, from,
    modal() { return body.querySelectorAll(".modal-ov")[0] || null; },
    open() { return sandbox.document.getElementById("appModal"); },
  };
}

const TROOP_PRIZE = { id: "infantry_670", kind: "troops", unit: "inf", count: 670,
                      label: "670 Infantry", icon: "\u{1F6E1}" };
const GOLD_PRIZE = { id: "gold_3000", kind: "gold", amount: 3000,
                     label: "3,000 Gold", icon: "\u{1FA99}" };

/* ============================================================ 1-4. the lesson modal */
{
  const env = makeEnv();
  env.from("lesson");
  env.sandbox.rgResult({ ok: true, newly: true, prize: TROOP_PRIZE });
  const ov = env.modal();
  assert(ov, "a modal must be shown");
  const card = ov.querySelector(".rg-card");
  assert(card, "the reward card must be rendered");
  const text = card.textContent;

  // 1. the earned reward is shown, in words, with its destination
  assert(/YOU WON!/.test(text), text);
  assert(/670 Infantry/.test(text), "the reward amount/unit must be stated: " + text);
  assert(/Home Base/.test(text), "the destination must be stated: " + text);
  assert(ov.querySelector(".rg-prize-ic"), "the prize icon must be rendered");
  ok("1. the lesson reward modal shows the prize, its amount/unit and where it went");

  // 2/3. neither navigation control is rendered
  assert(!ov.querySelector("#rgMore"), "CONTINUE LEARNING must be absent");
  assert(!ov.querySelector("#rgWorld"), "GO TO WORLD must be absent");
  assert(!/CONTINUE LEARNING/i.test(text), text);
  assert(!/GO TO WORLD/i.test(text), text);
  assert(!ov.querySelector(".rg-foot"), "the exits footer must not be rendered at all");
  ok("2+3. neither 'CONTINUE LEARNING' nor 'GO TO WORLD' is rendered (no footer at all)");

  // 4/5. the close control is present and closes the modal
  const x = ov.querySelector(".modal-x");
  assert(x, "the top-right close control must be present");
  assert.strictEqual(x.getAttribute("aria-label"), "Close", "the close control must be labelled");
  assert(env.open(), "the modal should be open before the click");
  x.click();
  assert(!env.open(), "clicking the close control must remove the modal");
  ok("4+5. the top-right ✕ is present, labelled, and closing it removes the modal");

  // 6-9. closing navigates NOWHERE: no lesson change, no activity opened, no World
  assert.deepStrictEqual(env.nav, [],
    "closing must cause no navigation at all, got: " + env.nav.join(","));
  ok("6-9. closing triggers no navigation: the learner stays in the lesson, no activity is " +
     "auto-opened and the World is not entered");
}

/* ============================================================ gold prize wording */
{
  const env = makeEnv();
  env.from("lesson");
  env.sandbox.rgResult({ ok: true, newly: true, prize: GOLD_PRIZE });
  const t = env.modal().querySelector(".rg-card").textContent;
  assert(/3,000 Gold/.test(t) && /Added to your gold/.test(t), t);
  assert(!env.modal().querySelector("#rgMore") && !env.modal().querySelector("#rgWorld"), t);
  ok("a gold prize keeps its own destination wording and is equally dismiss-only");
}

/* ============================================================ 10. replay is identical */
{
  // A replay of a settled entitlement reports newly:false and the prize already stored. The result
  // screen is the same dismiss-only screen -- the learner sees what they won, and closes it.
  const env = makeEnv();
  env.from("lesson");
  env.sandbox.rgResult({ ok: true, newly: false, prize: TROOP_PRIZE });
  const ov = env.modal();
  const t = ov.querySelector(".rg-card").textContent;
  assert(/670 Infantry/.test(t) && /Home Base/.test(t), t);
  assert(!ov.querySelector("#rgMore") && !ov.querySelector("#rgWorld"),
    "a replay result must not gain navigation controls");
  ov.querySelector(".modal-x").click();
  assert(!env.open());
  assert.deepStrictEqual(env.nav, [], env.nav.join(","));
  ok("10. replaying a settled mini-game shows the same prize in the same dismiss-only modal");

  // 11. and the modal itself can mint nothing: it reads `res`, it never posts
  const resultSrc = extractFn(html, "function rgResult(");
  assert(!/fetch\(/.test(resultSrc), "the result screen must not call the server");
  assert(!/rgPlay\(/.test(resultSrc), "the result screen must not settle anything");
  assert(!/myEcon/.test(resultSrc), "the result screen must not touch the balance");
  ok("11. the result screen posts nothing and touches no balance, so re-showing it cannot " +
     "duplicate a reward (idempotency stays entirely server-side)");
}

/* ============================================================ 12. the Academy is unchanged */
{
  const env = makeEnv();               // default context: "academy"
  assert.strictEqual(env.from(), "academy", "the default must remain the Academy behaviour");
  env.sandbox.rgResult({ ok: true, newly: true, prize: TROOP_PRIZE });
  const ov = env.modal();
  const more = ov.querySelector("#rgMore"), world = ov.querySelector("#rgWorld");
  assert(more && world, "the Academy result must still offer both exits");
  assert(/CONTINUE LEARNING/.test(more.textContent), more.textContent);
  assert(/GO TO WORLD/.test(world.textContent), world.textContent);
  // CONTINUE LEARNING still picks up a second pending game rather than discarding it
  more.click();
  assert(!env.open(), "the exit must close the modal");
  assert.deepStrictEqual(env.nav, ["rgOpenNextPending", "openLearningHome"], env.nav.join(","));
  ok("12. the Academy result screen is unchanged: CONTINUE LEARNING still opens the next pending " +
     "game and falls back to the Academy");

  const env2 = makeEnv();
  env2.sandbox.rgResult({ ok: true, newly: true, prize: GOLD_PRIZE });
  env2.modal().querySelector("#rgWorld").click();
  assert(!env2.open());
  assert.deepStrictEqual(env2.nav, ["loadEconomy", "loadTerritory", "renderEmpire", "refreshMap",
                                    "goToGameMap"], env2.nav.join(","));
  ok("12. ...and GO TO WORLD still reconciles the caches before taking the existing World route");
}

/* ============================================================ the shipped wiring */
{
  // The context is threaded from the CALL SITE, so it cannot be inferred (or mis-inferred) later.
  const openFn = extractFn(html, "function openRewardGame(");
  assert(/function openRewardGame\(ent, from\)/.test(openFn), "openRewardGame must take a context");
  assert(/rgFrom = from === "lesson" \? "lesson" : "academy";/.test(openFn),
    "an unrecognised context must fall back to the Academy behaviour, not the lesson's");
  assert(/let rgFrom = "academy";/.test(html), "the default context must be the Academy's");

  // every lesson entry point says so; the Academy's does not
  const lessonCalls = html.match(/openRewardGame\([^)]*"lesson"\)/g) || [];
  assert.strictEqual(lessonCalls.length, 3,
    "expected the 3 lesson entry points (auto-open, stage row, finish panel), got " +
    lessonCalls.length);
  assert(/if \(j\.next\) \{ openRewardGame\(j\.next\); if \(cb\) cb\(true\); \}/.test(html),
    "the Academy path must keep the default context");
  ok("the context is passed by the call site: 3 lesson entry points say \"lesson\", the Academy " +
     "path keeps the default, and an unknown value falls back to the Academy");

  // and the lesson's activity result screens still expose no redundant navigation
  ["nextLevelBtn", "backToStagesBtn", "shadowNextLevel", "lsStagesBtn"].forEach(function (id) {
    assert(html.indexOf(id) < 0, id + " still exists in the page");
  });
  const bare = html.replace(/<!--[\s\S]*?-->/g, "")
                   .replace(/\/\*[\s\S]*?\*\//g, "")
                   .replace(/^\s*\/\/[^\n]*$/gm, "");
  ["Back to Lesson", "Back to lessons", "Next Level"].forEach(function (label) {
    assert(bare.indexOf(label) < 0, "the label '" + label + "' survives in the page");
  });
  ok("lesson activity result screens still expose no 'Next' and no 'Back to Lesson' -- the " +
     "persistent stage selector remains the only lesson navigation");
}

console.log("\nAll " + passed + " lesson reward-modal checks passed.");
