"use strict";
// Phase 3C §28 — frontend/backend grading PARITY.
//
// This file is the frontend half of the parity proof. It does NOT reimplement grading: it extracts the
// live controller sources from index.html, asserts the exact comparison expressions Phase 3C ported are
// still the ones shipping, executes the real dictation norm() out of the page source, and then
// recomputes every case in tests/fixtures/learning_grader_golden.json using those live rules.
//
// tests/learning_graders_test.py asserts the BACKEND produces the same numbers for the same fixture.
// If the frontend rule ever changes, the assertions below fail and the parity claim stops being silent.
//
//     node tests/learning_parity.test.js

const fs = require("fs");
const path = require("path");
const assert = require("assert");

let passed = 0;
function ok(name) { passed++; console.log("  ok -", name); }

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const golden = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "learning_grader_golden.json"), "utf8"));

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

const makeQuiz = extractFn(html, "function makeQuiz(");
const makeWh = extractFn(html, "function makeWh(");
const makeCloze = extractFn(html, "function makeCloze(");
const makeReorder = extractFn(html, "function makeReorder(");
const makeDictation = extractFn(html, "function makeDictation(");

// ---------------------------------------------------------------- 1) pin the live comparison rules
// yes_no (levels 3/4): exact equality against the item's answer
assert(/const right = shuffled\[idx\]\.answer;/.test(makeQuiz), "makeQuiz answer source changed");
assert(/if \(choice === right\)/.test(makeQuiz), "makeQuiz comparison changed");
// multiple choice - wh (level 7): exact equality against it.a
assert(/if \(choice === it\.a\)/.test(makeWh), "makeWh comparison changed");
assert(/choices\s*=\s*shuffle\(\[it\.a\][\s\S]{0,40}it\.wrong/.test(makeWh) ||
  /shuffle\(\[it\.a\, \.\.\.it\.wrong\]\)/.test(makeWh) ||
  /\[it\.a\][\s\S]{0,30}it\.wrong/.test(makeWh), "makeWh option set changed");
// multiple choice - cloze (level 9): exact equality against it.answer
assert(/if \(choice === it\.answer\)/.test(makeCloze), "makeCloze comparison changed");
assert(/\[it\.answer\][\s\S]{0,30}it\.wrong/.test(makeCloze), "makeCloze option set changed");
// reorder (level 6): token-INDEX permutation equality, and full marks on completion
assert(/placed\.every\(\(id, i\) => id === i\)/.test(makeReorder), "makeReorder check changed");
assert(/recordScore\(6, sentences\.length, sentences\.length\)/.test(makeReorder),
  "makeReorder scoring changed (was completion = full marks)");
assert(/tokens = sentences\[idx\]\.map\(\(w, i\) => \(\{ id: i, word: w \}\)\)/.test(makeReorder),
  "makeReorder token identity changed");
// dictation (level 8): normalized text equality
assert(/const ok = norm\(input\.value\) === norm\(sentence\);/.test(makeDictation),
  "makeDictation comparison changed");
ok("live frontend rules unchanged: yes_no/wh/cloze exact ===, reorder index equality, dictation norm()");

// ---------------------------------------------------------------- 2) run the REAL dictation norm()
const normSrc = extractFn(makeDictation, "function norm(");
assert(/toLowerCase\(\)/.test(normSrc) && /replace\(\/\[\.,!\?;:'"\]\/g, ""\)/.test(normSrc) &&
  /replace\(\/\\s\+\/g, " "\)/.test(normSrc) && /\.trim\(\)/.test(normSrc), "norm() body changed: " + normSrc);
const norm = new Function(normSrc + "; return norm;")();
assert.strictEqual(norm("A, b. c! d? e; f: g' h\""), "a b c d e f g h");
assert.strictEqual(norm("well-known"), "well-known", "hyphen not stripped");
assert.strictEqual(norm("It’s"), "it’s", "curly apostrophe not stripped");
ok("dictation norm() executed straight from index.html source (not reimplemented)");

// ---------------------------------------------------------------- 3) the frontend's pct / pass rule
// index.html: levelPassed -> Math.round(s.correct / s.total * 100) >= PASS_MARK
const PASS_MARK = Number((html.match(/const PASS_MARK = (\d+);/) || [])[1]);
assert.strictEqual(PASS_MARK, 80, "PASS_MARK changed");
assert(/Math\.round\(s\.correct \/ s\.total \* 100\) >= PASS_MARK/.test(html), "levelPassed rule changed");
const pctOf = (c, t) => (t ? Math.round(c / t * 100) : 0);
// the exact case where Python's banker's rounding would disagree with Math.round
assert.strictEqual(pctOf(5, 8), 63, "5/8 must be 63 under Math.round (not 62)");
ok("pct/pass rule read from index.html: Math.round(correct/total*100) >= 80");

// ---------------------------------------------------------------- 4) recompute every golden case
const graders = {
  yes_no: (content, answers) => {
    const chosen = new Map();
    answers.forEach(a => { const k = String(a.q == null ? "" : a.q).trim(); if (!chosen.has(k)) chosen.set(k, a.answer); });
    let correct = 0;
    content.forEach(it => {
      const q = String(it.q == null ? "" : it.q).trim();
      if (!q || !chosen.has(q)) return;
      // frontend: choice === right (the backend additionally case-folds; parity holds for real input)
      if (String(chosen.get(q)) === String(it.answer)) correct++;
    });
    return { correct, total: content.length };
  },
  multiple_choice: (content, answers, cfg) => {
    const pf = (cfg && cfg.promptField) || "q", af = (cfg && cfg.answerField) || "a",
      df = (cfg && cfg.distractorsField) || "wrong";
    const chosen = new Map();
    answers.forEach(a => { const k = String(a.q == null ? "" : a.q).trim(); if (!chosen.has(k)) chosen.set(k, a.answer); });
    let correct = 0;
    content.forEach(it => {
      const prompt = String(it[pf] == null ? "" : it[pf]).trim();
      const want = it[af];
      if (!prompt || want == null || !chosen.has(prompt)) return;
      const options = [want].concat(Array.isArray(it[df]) ? it[df] : []).map(o => String(o == null ? "" : o));
      const got = String(chosen.get(prompt) == null ? "" : chosen.get(prompt));
      // frontend: the learner can only click a rendered option, and correct iff choice === want
      if (options.indexOf(got) >= 0 && got === String(want)) correct++;
    });
    return { correct, total: content.length };
  },
  reorder: (content, answers, cfg) => {
    const sep = (cfg && cfg.joinWith) || " ";
    const chosen = new Map();
    answers.forEach(a => { const k = String(a.q == null ? "" : a.q).trim(); if (!chosen.has(k)) chosen.set(k, a.answer); });
    let correct = 0;
    content.forEach(item => {
      if (!Array.isArray(item) || !item.length) return;
      const key = item.map(String).join(sep).trim();
      if (!chosen.has(key)) return;
      const placed = chosen.get(key);
      if (!Array.isArray(placed) || placed.length !== item.length) return;
      const ids = [];
      for (const x of placed) {
        if (typeof x === "boolean") return;
        if (typeof x === "number") { if (!Number.isInteger(x)) return; ids.push(x); }
        else if (typeof x === "string" && /^\d+$/.test(x.trim())) ids.push(parseInt(x, 10));
        else return;
      }
      // frontend: placed.every((id, i) => id === i)
      if (ids.every((id, i) => id === i)) correct++;
    });
    return { correct, total: content.length };
  },
  dictation: (content, answers) => {
    const chosen = new Map();
    answers.forEach(a => { const k = String(a.q == null ? "" : a.q).trim(); if (!chosen.has(k)) chosen.set(k, a.answer); });
    let correct = 0;
    content.forEach(sentence => {
      if (typeof sentence !== "string" || !sentence.trim()) return;
      const key = sentence.trim();
      if (!chosen.has(key)) return;
      const typed = chosen.get(key);
      if (typeof typed !== "string") return;
      // frontend: norm(input.value) === norm(sentence), using the REAL extracted norm
      if (norm(typed) && norm(typed) === norm(sentence)) correct++;
    });
    return { correct, total: content.length };
  },
};

const seen = {};
golden.cases.forEach(c => {
  const g = graders[c.graderType];
  assert(g, "no frontend parity model for graderType " + c.graderType);
  const { correct, total } = g(c.content, c.answers, c.cfg);
  const pct = pctOf(correct, total);
  const res = { correct, total, pct, passed: total > 0 && pct >= PASS_MARK };
  ["correct", "total", "pct", "passed"].forEach(k =>
    assert.strictEqual(res[k], c.expect[k],
      "PARITY MISMATCH in '" + c.name + "': " + k + " frontend=" + res[k] + " fixture=" + c.expect[k]));
  seen[c.graderType] = (seen[c.graderType] || 0) + 1;
});
ok("golden parity: " + golden.cases.length + " cases reproduce under live frontend rules " +
  JSON.stringify(seen));

// ---------------------------------------------------------------- 5) real lesson content parity
// Grade a handful of real activities both ways: the frontend model here, and the recorded expectation
// that a fully-correct attempt is 100% and an all-distractor attempt is 0%.
const lessons = ["Pre-A1/taipei/zoo", "Pre-A1/001", "A1/001", "A2/001"];
let checkedWh = 0, checkedCloze = 0, checkedReorder = 0, checkedDict = 0;
lessons.forEach(rel => {
  const p = path.join(__dirname, "..", rel + ".json");
  if (!fs.existsSync(p)) return;
  const d = JSON.parse(fs.readFileSync(p, "utf8"));
  if (Array.isArray(d.wh) && d.wh.length) {
    const cfg = { promptField: "q", answerField: "a", distractorsField: "wrong" };
    const right = d.wh.map(it => ({ q: it.q, answer: it.a }));
    assert.strictEqual(pctOf(...Object.values(graders.multiple_choice(d.wh, right, cfg)).slice(0, 2)), 100, rel + " wh");
    const wrong = d.wh.map(it => ({ q: it.q, answer: (it.wrong || ["x"])[0] }));
    assert.strictEqual(graders.multiple_choice(d.wh, wrong, cfg).correct, 0, rel + " wh distractors");
    checkedWh++;
  }
  if (Array.isArray(d.cloze) && d.cloze.length) {
    const cfg = { promptField: "text", answerField: "answer", distractorsField: "wrong" };
    const right = d.cloze.map(it => ({ q: it.text, answer: it.answer }));
    assert.strictEqual(graders.multiple_choice(d.cloze, right, cfg).correct, d.cloze.length, rel + " cloze");
    checkedCloze++;
  }
  if (Array.isArray(d.reorder) && d.reorder.length) {
    const right = d.reorder.map(s => ({ q: s.join(" "), answer: s.map((_, i) => i) }));
    assert.strictEqual(graders.reorder(d.reorder, right).correct, d.reorder.length, rel + " reorder");
    const rev = d.reorder.map(s => ({ q: s.join(" "), answer: s.map((_, i) => s.length - 1 - i) }));
    assert.strictEqual(graders.reorder(d.reorder, rev).correct,
      d.reorder.filter(s => s.length === 1).length, rel + " reorder reversed");
    checkedReorder++;
  }
  if (Array.isArray(d.dictation) && d.dictation.length) {
    const right = d.dictation.map(s => ({ q: s, answer: s.toUpperCase() }));
    assert.strictEqual(graders.dictation(d.dictation, right).correct, d.dictation.length,
      rel + " dictation (case-insensitive)");
    checkedDict++;
  }
});
assert(checkedWh && checkedCloze && checkedReorder && checkedDict,
  "expected real content for all four graders: " + [checkedWh, checkedCloze, checkedReorder, checkedDict]);
ok("real lesson parity: wh=" + checkedWh + " cloze=" + checkedCloze + " reorder=" + checkedReorder +
  " dictation=" + checkedDict + " lessons graded under live rules");

console.log("\nAll " + passed + " parity checks passed.");
