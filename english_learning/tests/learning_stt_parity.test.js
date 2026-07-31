"use strict";
// Phase 3E1 §23 — Read-Along scoring PARITY between the legacy frontend rule and the server port.
//
// This file does not reimplement the rule. It extracts `pronWords`, the `CONTRACTIONS` table and the
// scoring core of `showPron` from the live index.html, executes them, and recomputes every case in
// tests/fixtures/learning_stt_golden.json. tests/learning_stt_test.py asserts the BACKEND produces the
// same numbers for the same fixture, so any drift between the two fails one of them.
//
//     node tests/learning_stt_parity.test.js

const fs = require("fs");
const path = require("path");
const assert = require("assert");

let passed = 0;
function ok(name) { passed++; console.log("  ok -", name); }

const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const golden = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "learning_stt_golden.json"), "utf8"));

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

// ---------------------------------------------------------------- 1) the LIVE table + normalizer
const cStart = html.indexOf("const CONTRACTIONS = {");
assert(cStart >= 0, "CONTRACTIONS table not found");
const CONTRACTIONS = eval("(" + html.slice(cStart + "const CONTRACTIONS = ".length,
  html.indexOf("};", cStart) + 1) + ")");
const pronWordsSrc = extractFn(html, "function pronWords(");
assert(/toLowerCase\(\)/.test(pronWordsSrc) && /\[’ʼ\]/.test(pronWordsSrc) &&
  /\[\^a-z' \]/.test(pronWordsSrc) && /CONTRACTIONS\[w\]/.test(pronWordsSrc),
  "pronWords() body changed: " + pronWordsSrc);
const pronWords = new Function("CONTRACTIONS", pronWordsSrc + "; return pronWords;")(CONTRACTIONS);
assert.strictEqual(Object.keys(CONTRACTIONS).length, 48, "contraction table size changed");
assert.deepStrictEqual(pronWords("I'm"), ["i", "am"]);
assert.deepStrictEqual(pronWords("It’s"), ["it", "is"]);
ok("live pronWords() + 48-entry CONTRACTIONS table executed straight from index.html");

// ---------------------------------------------------------------- 2) the LIVE scoring core
// showPron still scores by consuming a multiset of transcript words, one target whitespace token at
// a time, all-or-nothing per token, then Math.round(matched/total*100).
const showPronSrc = extractFn(html, "function showPron(");
assert(/pronWords\(said\)\.forEach\(w => \{ sCount\[w\] = \(sCount\[w\] \|\| 0\) \+ 1; \}\)/.test(showPronSrc),
  "showPron transcript multiset changed");
assert(/target\.split\(\/\\s\+\/\)\.map\(tok =>/.test(showPronSrc), "showPron target tokenization changed");
assert(/const subs = pronWords\(tok\);/.test(showPronSrc), "showPron target expansion changed");
assert(/subs\.every\(x => sCount\[x\] > 0\)/.test(showPronSrc), "showPron match test changed");
assert(/subs\.forEach\(x => sCount\[x\]--\)/.test(showPronSrc), "showPron consumption changed");
assert(/total \? Math\.round\(matched \/ total \* 100\) : 0/.test(showPronSrc),
  "showPron percentage rule changed");
// best-per-sentence retry, and the authoritative-vs-local split introduced by Phase 3E1
assert(/pronScores\[idx\] = Math\.max\(pronScores\[idx\] \|\| 0, pct\)/.test(showPronSrc),
  "best-per-sentence retry rule changed");
assert(/if \(serverPct == null\) pronScores\[idx\]/.test(showPronSrc),
  "local score must only be stored when there is NO authoritative server score");
assert(/const pct = \(serverPct != null\) \? serverPct :/.test(showPronSrc),
  "the displayed score must prefer the server's authoritative value");
ok("live showPron() scoring core pinned, incl. best-per-sentence and the server-authority split");

// ---------------------------------------------------------------- 3) recompute every golden case
function scoreLikeFrontend(target, said) {
  const sCount = {};
  pronWords(said).forEach(w => { sCount[w] = (sCount[w] || 0) + 1; });
  let total = 0, matched = 0;
  String(target == null ? "" : target).split(/\s+/).forEach(tok => {
    const subs = pronWords(tok);
    if (!subs.length) return;
    total++;
    if (subs.every(x => sCount[x] > 0)) { subs.forEach(x => sCount[x]--); matched++; }
  });
  return { pct: total ? Math.round(matched / total * 100) : 0, matchedTokens: matched, totalTokens: total };
}
golden.cases.forEach(c => {
  const got = scoreLikeFrontend(c.target, c.transcript);
  ["pct", "matchedTokens", "totalTokens"].forEach(k =>
    assert.strictEqual(got[k], c.expect[k],
      "PARITY MISMATCH in '" + c.name + "': " + k + " frontend=" + got[k] + " fixture=" + c.expect[k]));
});
ok("golden parity: " + golden.cases.length + " cases reproduce under the live frontend rule");

// ---------------------------------------------------------------- 4) real lesson sentences
// Score every real sentence of two lessons against a perfect reading: must be 100 on both sides.
["Pre-A1/taipei/zoo", "A1/001"].forEach(rel => {
  const raw = fs.readFileSync(path.join(__dirname, "..", rel), "utf8");
  const sentences = raw.split(/\r?\n/).map(s => s.trim()).filter(Boolean)
    .map(l => { const m = l.match(/^([^:：]+)[:：]\s*(.*)$/); return m ? m[2].trim() : null; })
    .filter(Boolean);
  assert(sentences.length >= 8, rel + " should have sentences");
  sentences.forEach(s => {
    assert.strictEqual(scoreLikeFrontend(s, s.toLowerCase()).pct, 100, rel + ": " + s);
    assert.strictEqual(scoreLikeFrontend(s, "").pct, 0, rel + " empty: " + s);
  });
});
ok("real lessons: every Zoo and A1/001 sentence scores 100 read perfectly, 0 read not at all");

// ---------------------------------------------------------------- 5) the client sends no authority
const scoreFn = extractFn(html, "function scorePronunciation(");
assert(/activityId=/.test(scoreFn) && /sentenceIndex=/.test(scoreFn),
  "the client must submit activity identity, not the target text");
assert(/d\.authoritative/.test(scoreFn), "the client must branch on the server's authoritative flag");
assert(/sttAuthPct = d\.activityPct/.test(scoreFn), "the level pct must come from the server");
["score:", "pct:", "passed:", "rewardGold", "qualification"].forEach(k =>
  assert(scoreFn.indexOf(k) < 0, "scorePronunciation must not submit " + k));
// the legacy ?text= path survives only for the non-authoritative case (roleplay / no login)
assert(/text=/.test(scoreFn), "legacy hint mode must remain for the unauthenticated/no-registry case");
// the full-marks fallback must be clearly local-only
const shadow = html.slice(html.indexOf("const scoredCount = Object.keys(pronScores).length;") - 400,
  html.indexOf("const scoredCount = Object.keys(pronScores).length;") + 1400);
assert(/if \(sttAuthPct != null\)\s*\{\s*recordScore\(2, sttAuthPct, 100\)/.test(shadow),
  "the authoritative server pct must take priority when recording Level 2");
assert(/recordScore\(2, script\.length, script\.length\)/.test(shadow),
  "the offline convenience fallback is expected to remain (local only)");
ok("client submits identity only; server pct wins; offline fallback remains local convenience");

console.log("\nAll " + passed + " STT parity checks passed.");
