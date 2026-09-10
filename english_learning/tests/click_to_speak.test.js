"use strict";
// Click-to-speak — the shared pronunciation layer for learner-visible English.
//
// Source-level, no DOM framework. The click-to-speak module, plus the REAL speakSeq/speakQuestion/
// speakSequence pipeline it delegates to, are extracted out of index.html and executed against tiny
// stubs. Only the lowest-level audio primitives are faked (SpeechSynthesisUtterance, synth,
// clipFile, Audio), so what these assertions exercise is the shipped decision-making: which clicks
// speak, what text they resolve to, and how a new utterance treats the one in flight.
//
//     node tests/click_to_speak.test.js

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
// The click-to-speak module is one contiguous region: the SPEAK_* contract through both delegated
// listeners. Slicing it whole (rather than function by function) means the listeners under test are
// the ones that ship, registration included.
function extractRegion(src, startMark, endMark) {
  const a = src.indexOf(startMark);
  assert(a >= 0, "cannot find " + startMark);
  const b = src.indexOf(endMark, a);
  assert(b > a, "cannot find " + endMark);
  return src.slice(a, b);
}

const MODULE_SRC = extractRegion(html, "const SPEAK_HOSTS", "function makeQuiz(");
// The real pipeline the module hands text to.
const PIPELINE_SRC = [extractFn(html, "function speakSeq("),
  extractFn(html, "function speakQuestion("),
  extractFn(html, "function speakSequence(")].join("\n");

// ---------------------------------------------------------------- tiny DOM
function el(tag, cls) {
  const e = {
    tagName: tag, nodeType: 1, className: cls || "", id: "", title: "",
    childNodes: [], parent: null, dataset: {}, disabled: false, _on: {},
    _attrs: {},
    classList: {
      contains(c) { return (" " + e.className + " ").indexOf(" " + c + " ") >= 0; },
      add(c) { if (!this.contains(c)) e.className = (e.className + " " + c).trim(); },
      remove(c) { e.className = (" " + e.className + " ").replace(" " + c + " ", " ").trim(); },
    },
    get textContent() {
      if (!e.childNodes.length) return e._text || "";
      return e.childNodes.map(n => n.nodeType === 3 ? n.nodeValue : n.textContent).join("");
    },
    set textContent(v) { e._text = String(v); e.childNodes = []; },
    setAttribute(k, v) { e._attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(e._attrs, k) ? e._attrs[k] : null; },
    appendChild(c) { c.parent = e; e.childNodes.push(c); return c; },
    addEventListener(ev, fn) { e._on[ev] = fn; },
    // matches(): supports ".cls", "#id .cls" and comma lists — enough for SPEAK_HOSTS.
    matches(sel) {
      return sel.split(",").map(s => s.trim()).filter(Boolean).some(one => {
        const parts = one.split(/\s+/);
        const last = parts[parts.length - 1];
        if (!simpleMatch(e, last)) return false;
        if (parts.length === 1) return true;
        const anc = parts[0];
        for (let p = e.parent; p; p = p.parent) if (simpleMatch(p, anc)) return true;
        return false;
      });
    },
    closest(sel) { for (let n = e; n; n = n.parent) if (n.matches && n.matches(sel)) return n; return null; },
    querySelector(sel) {
      for (const c of e.childNodes) {
        if (c.nodeType !== 1) continue;
        if (c.matches(sel)) return c;
        const deep = c.querySelector(sel);
        if (deep) return deep;
      }
      return null;
    },
  };
  return e;
}
function simpleMatch(node, one) {
  if (one.charAt(0) === "#") return node.id === one.slice(1);
  if (one.charAt(0) === ".") return node.classList && node.classList.contains(one.slice(1));
  return node.tagName === one;
}
function text(v) { return { nodeType: 3, nodeValue: v, textContent: v }; }

// ---------------------------------------------------------------- audio spies
function makeEnv(opts) {
  opts = opts || {};
  const spoken = [];          // every utterance handed to the synthesiser, in order
  const events = [];          // cancel / clip / speak, so ordering can be asserted
  const clicks = [];          // the page's own click handlers, to prove they still run
  const docListeners = {};
  const synth = {
    cancel() { events.push("cancel"); },
    speak(u) { events.push("speak:" + u.text); spoken.push(u); if (u.onend) u._onend = u.onend; },
    getVoices() { return []; },
  };
  const sandbox = {
    console,
    synth,
    stopAudio() { events.push("stopAudio"); },
    clipFile: opts.clipFile || function () { return undefined; },
    currentClip: null,
    playMedia(elm, what) { events.push("clip:" + what); return null; },
    Audio: function (src) { this.src = src; this.onended = null; },
    SpeechSynthesisUtterance: function (t) { this.text = t; this.lang = ""; this.rate = 0; this.voice = null; this.onend = null; },
    maleVoice: null, femaleVoice: null,
    // the read-along / role-play audio-owner flags the module consults
    isRecording: false, rpRecording: false, isPlaying: false,
    document: {
      addEventListener(ev, fn) { docListeners[ev] = fn; },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(PIPELINE_SRC + "\n" + MODULE_SRC, sandbox);
  assert(typeof docListeners.click === "function", "module must register a delegated click listener");
  assert(typeof docListeners.keydown === "function", "module must register a keydown listener");
  return {
    sandbox, spoken, events, clicks, docListeners,
    // Simulate a real bubble-phase click: the element's own handler runs first (as it does in the
    // browser, being bound directly to the element), then the document listener.
    click(target) {
      for (let n = target; n; n = n.parent) if (n._on && n._on.click) { clicks.push(n); n._on.click(); break; }
      docListeners.click({ target: target });
    },
    keydown(target, key) { docListeners.keydown({ target: target, key: key, preventDefault() {} }); },
    said() { return spoken.map(u => u.text); },
  };
}

// ================================================================ 1. the contract is opt-in
{
  const hosts = (MODULE_SRC.match(/const SPEAK_HOSTS = ([^;]+);/) || [])[1] || "";
  assert(/\.opt/.test(hosts) && /\.chip/.test(hosts) && /\.mword/.test(hosts), "hosts: " + hosts);
  assert(/\.line/.test(hosts) && /\.rp-b/.test(hosts), "hosts: " + hosts);
  // The exclusions that keep exercises honest and the app chrome quiet.
  assert(!/\.mpic/.test(hosts), "matching PICTURE buttons must never be a speech host");
  assert(!/dict-/.test(hosts), "no dictation control may be a speech host");
  assert(!/quiz-next|dict-play|speak-q|back-btn|pick-card|avatar-opt/.test(hosts),
    "action/navigation/game buttons must not be speech hosts: " + hosts);
  ok("SPEAK_HOSTS is an explicit allowlist: no .mpic, no dict-*, no navigation/action buttons");
}

// ================================================================ 2. learning content speaks
{
  const env = makeEnv();
  // ---- quiz Yes / No (makeQuiz builds .opt with a bare textContent) ----
  const optsBox = el("div", "quiz-opts");
  const yes = el("button", "opt"); yes.textContent = "Yes";
  const no = el("button", "opt"); no.textContent = "No";
  let graded = [];
  yes.addEventListener("click", () => graded.push("Yes"));
  no.addEventListener("click", () => graded.push("No"));
  optsBox.appendChild(yes); optsBox.appendChild(no);
  env.click(yes);
  env.click(no);
  assert.deepStrictEqual(env.said(), ["Yes", "No"], env.said().join("|"));
  assert.deepStrictEqual(graded, ["Yes", "No"], "the quiz's own answer handler still ran");
  ok("Yes / No pronounce themselves through the generic learning-choice path (grading unaffected)");

  // ---- reorder tokens ----
  const env2 = makeEnv();
  const pool = el("div", "reorder-pool");
  ["I", "like", "playing", "soccer."].forEach(w => {
    const c = el("button", "chip"); c.textContent = w; pool.appendChild(c);
  });
  pool.childNodes.forEach(c => env2.click(c));
  assert.deepStrictEqual(env2.said(), ["I", "like", "playing", "soccer."], env2.said().join("|"));
  ok("each reorder token pronounces itself, trailing punctuation kept natural (\"soccer.\")");

  // ---- boss-exam options (same .opt contract, a 9th activity found in the page) ----
  const env3 = makeEnv();
  const bo = el("div", "battleOpts");
  const b = el("button", "opt"); b.textContent = "library"; bo.appendChild(b);
  env3.click(b);
  assert.deepStrictEqual(env3.said(), ["library"]);
  ok("boss-exam answer choices speak (inherited from .opt, no per-activity speech code)");
}

// ================================================================ 3. decorations are not spoken
{
  // ---- makeWh: visible "1. …" but data-val holds the clean choice (and grades on it) ----
  const env = makeEnv();
  const w = el("button", "opt");
  w.dataset.val = "The zoo is next to the park.";
  w.textContent = "1. The zoo is next to the park.";
  // makeWh marks its options data-speak="off" and speaks the sequence itself; prove the resolver
  // would still have produced the undecorated sentence had it been the one to speak.
  const resolved = env.sandbox.speechTextFor({ dataset: { val: w.dataset.val }, querySelector: () => null });
  assert.strictEqual(resolved, "The zoo is next to the park.", resolved);
  assert.ok(!/^1\./.test(resolved), "the option number must not be pronounced");
  ok("WH choices resolve to the full sentence, without the \"1. \" numbering");

  // ---- a numbered option with no data-val still loses its prefix ----
  assert.strictEqual(env.sandbox.speakableText("2) cat"), "cat");
  assert.strictEqual(env.sandbox.speakableText("10. bird"), "bird");
  ok("enumeration prefixes are stripped by the shared normaliser");

  // ---- makeMatch word row: .num index + .wword + wmark ✓/✗ slot ----
  const row = el("div", "mword");
  row.id = "mword-0";
  const num = el("span", "num"); num.textContent = "1";
  const word = el("span", "wword"); word.appendChild(text("apple"));
  const mark = el("span", ""); mark.id = "wmark-0"; mark.textContent = " ✓";
  row.appendChild(num); row.appendChild(word); row.appendChild(mark);
  const env2 = makeEnv();
  env2.click(row);
  assert.deepStrictEqual(env2.said(), ["apple"], env2.said().join("|"));
  ok("matching word speaks \"apple\" only — not its index number, not its ✓ mark");

  // ---- read-along line: .who speaker label is decoration ----
  const line = el("div", "line female");
  const dlg = el("div", ""); dlg.id = "dialogue"; dlg.appendChild(line);
  const who = el("span", "who"); who.textContent = "Anna";
  const say = el("span", "say"); say.appendChild(text("Where is the zoo?"));
  line.appendChild(who); line.appendChild(say);
  const env3 = makeEnv();
  env3.click(line);
  assert.deepStrictEqual(env3.said(), ["Where is the zoo?"], env3.said().join("|"));
  ok("read-along line speaks the sentence, never the speaker name");

  // ---- role-play bubble: .rp-who is decoration, the line is a bare text node ----
  const bubble = el("div", "rp-b npc");
  const convo = el("div", "rp-convo"); convo.id = "rpConvo"; convo.appendChild(bubble);
  const rwho = el("span", "rp-who"); rwho.textContent = "🧑 Shopkeeper";
  bubble.appendChild(rwho); bubble.appendChild(text("Turn left."));
  const env4 = makeEnv();
  env4.click(bubble);
  assert.deepStrictEqual(env4.said(), ["Turn left."], env4.said().join("|"));
  ok("role-play bubble speaks the utterance, never the 🧑 speaker chip");

  // ---- emoji / marks / hints anywhere in a label ----
  const env5 = makeEnv();
  assert.strictEqual(env5.sandbox.speakableText("🔊 Listen"), "Listen");
  assert.strictEqual(env5.sandbox.speakableText("apple ✓"), "apple");
  assert.strictEqual(env5.sandbox.speakableText("✅ correct"), "correct");
  assert.strictEqual(env5.sandbox.speakableText("don’t"), "don’t", "curly apostrophe kept");
  assert.strictEqual(env5.sandbox.speakableText("co-operate"), "co-operate", "hyphen kept");
  ok("emoji and ✓/✗/✅ marks are stripped; real word punctuation is preserved");
}

// ================================================================ 4. chrome stays silent
{
  const env = makeEnv();
  const cases = [
    ["button", "quiz-next", "✓ Check"],
    ["button", "dict-play", "🔊 Listen"],
    ["button", "dict-speed", "🐢 Slow"],
    ["button", "speak-q", "🔊"],
    ["button", "mpic", "🍎"],
    ["button", "back-btn", "← Back"],
    ["button", "pick-card", "Knight"],
    ["button", "avatar-opt", "👦"],
    ["button", "", "Next"],
    ["button", "", "Submit"],
    ["button", "", "Login"],
    ["button", "rp-mic", "🎤"],
  ];
  cases.forEach(([tag, cls, label]) => {
    const b = el(tag, cls); b.textContent = label;
    env.click(b);
  });
  assert.deepStrictEqual(env.said(), [], "chrome spoke: " + env.said().join("|"));
  ok("Next / Back / Submit / Login / Check / Listen / speed / mic / picture / avatar say nothing (" +
     cases.length + " controls)");
}

// ================================================================ 5. blank and unspeakable input
{
  const env = makeEnv();
  [null, undefined, "", "   ", "\t\n ", "‍", "️"].forEach(v => {
    assert.strictEqual(env.sandbox.speakableText(v), "", "should be blank: " + JSON.stringify(v));
    assert.strictEqual(env.sandbox.speakEnglish(v), false, "speakEnglish must decline " + JSON.stringify(v));
  });
  // punctuation-only reorder tokens
  ["?", ".", "!", ",", "—", "...", "✓"].forEach(v => {
    assert.strictEqual(env.sandbox.speakableText(v), "", "punctuation-only should be silent: " + v);
  });
  assert.deepStrictEqual(env.said(), [], "nothing should have reached the synthesiser");
  // and via a real click on a punctuation-only chip
  const chip = el("button", "chip"); chip.textContent = "?";
  env.click(chip);
  assert.deepStrictEqual(env.said(), [], "a punctuation-only token must stay silent");
  ok("null / undefined / \"\" / whitespace / punctuation-only produce no speech and never throw");
}

// ================================================================ 6. cancellation policy
{
  const env = makeEnv();
  const a = el("button", "chip"); a.textContent = "apple";
  const b = el("button", "chip"); b.textContent = "banana";
  env.click(a);
  env.click(b);
  assert.deepStrictEqual(env.said(), ["apple", "banana"], env.said().join("|"));
  // Each utterance is preceded by a cancel of whatever was in flight: click B stops A rather than
  // queueing behind it.
  assert.deepStrictEqual(env.events, ["cancel", "stopAudio", "speak:apple",
                                      "cancel", "stopAudio", "speak:banana"], env.events.join(","));
  // Ten rapid clicks must leave ten cancels and ten speaks — never a growing backlog.
  const env2 = makeEnv();
  for (let i = 0; i < 10; i++) { const c = el("button", "chip"); c.textContent = "w" + i; env2.click(c); }
  assert.strictEqual(env2.said().length, 10);
  assert.strictEqual(env2.events.filter(e => e === "cancel").length, 10, "one cancel per click");
  ok("click A → click B cancels A and speaks B; 10 rapid clicks queue nothing (10 cancels/10 speaks)");
}

// ================================================================ 7. the shared pipeline is reused
{
  // TTS path: en-US and the project's existing rate/voice policy, straight out of speakSeq.
  const env = makeEnv();
  env.sandbox.speakEnglish("apple");
  assert.strictEqual(env.spoken.length, 1);
  assert.strictEqual(env.spoken[0].text, "apple");
  assert.strictEqual(env.spoken[0].lang, "en-US", "must speak English");
  assert.strictEqual(env.spoken[0].rate, 0.85, "reuses speakSeq's rate, not a new one");
  ok("speakEnglish routes through the existing speakSeq pipeline (lang=en-US, rate=0.85)");

  // Prerecorded-clip path wins when a clip exists, exactly as the lesson already behaved.
  const env2 = makeEnv({ clipFile: (t) => (t === "apple" ? "apple.mp3" : undefined) });
  env2.sandbox.speakEnglish("apple");
  assert.strictEqual(env2.spoken.length, 0, "a real recording must be preferred over TTS");
  assert(env2.events.some(e => e.indexOf("clip:") === 0), env2.events.join(","));
  env2.sandbox.speakEnglish("banana");
  assert.deepStrictEqual(env2.spoken.map(u => u.text), ["banana"], "no clip -> falls back to TTS");
  ok("prerecorded mp3 is used when present, TTS only as the fallback (unchanged policy)");

  // No parallel TTS implementation was introduced.
  const raw = MODULE_SRC;
  assert(!/new SpeechSynthesisUtterance/.test(raw),
    "the click-to-speak layer must not construct utterances itself");
  assert(!/synth\.speak/.test(raw), "the click-to-speak layer must not call synth.speak directly");
  ok("no second TTS implementation: the module never builds an utterance or calls synth.speak");
}

// ================================================================ 8. missing browser TTS
{
  const env = makeEnv();
  env.sandbox.SpeechSynthesisUtterance = undefined;   // in-app browser with no speech support
  const chip = el("button", "chip"); chip.textContent = "apple";
  assert.doesNotThrow(() => env.click(chip), "a click must survive a browser with no TTS");
  assert.strictEqual(env.said().length, 0);
  ok("with no SpeechSynthesisUtterance the click still completes and nothing throws");
}

// ================================================================ 9. audio-owner guards
{
  ["isRecording", "rpRecording", "isPlaying"].forEach(flag => {
    const env = makeEnv();
    env.sandbox[flag] = true;
    const chip = el("button", "chip"); chip.textContent = "apple";
    let graded = false;
    chip.addEventListener("click", () => { graded = true; });
    env.click(chip);
    assert.deepStrictEqual(env.said(), [], "must stay silent while " + flag);
    assert.strictEqual(graded, true, "the learning action must still run while " + flag);
  });
  ok("silent while recording (read-along / role-play) or auto-playing, yet the click still acts");
}

// ================================================================ 10. data-speak contract
{
  const env = makeEnv();
  // "off" — the activity speaks for itself (WH / cloze)
  const off = el("button", "opt"); off.textContent = "cat"; off.dataset.speak = "off";
  env.click(off);
  assert.deepStrictEqual(env.said(), [], "data-speak=off must suppress the shared layer");
  // explicit override for a label the DOM cannot express
  const exp = el("button", "opt"); exp.textContent = "🍎 x3"; exp.dataset.speak = "apple";
  env.click(exp);
  assert.deepStrictEqual(env.said(), ["apple"], env.said().join("|"));
  ok("data-speak=\"off\" suppresses, data-speak=\"apple\" overrides an unspeakable label");
}

// ================================================================ 11. keyboard reachability
{
  const env = makeEnv();
  const row = el("div", "mword");
  const word = el("span", "wword"); word.appendChild(text("apple"));
  row.appendChild(word);
  env.keydown(row, "Enter");
  env.keydown(row, " ");
  assert.deepStrictEqual(env.said(), ["apple", "apple"], env.said().join("|"));
  env.keydown(row, "a");
  assert.strictEqual(env.said().length, 2, "an ordinary key must not speak");
  // a non-host element is not keyboard-speakable either
  const other = el("div", "quiz-progress"); other.textContent = "Question 1 / 5";
  env.keydown(other, "Enter");
  assert.strictEqual(env.said().length, 2, "only .mword answers Enter/Space");
  ok("matching word answers Enter/Space (role=button tabindex=0); other keys/elements do not");
}

// ================================================================ 12. shipped wiring (real source)
{
  // The delegated listener must be plain `click` — not mousedown — so touch and the native keyboard
  // activation of a <button> both route through it.
  assert(/document\.addEventListener\("click"/.test(MODULE_SRC), "must delegate on click");
  assert(!/addEventListener\("mousedown"/.test(MODULE_SRC), "must not use a desktop-only path");
  // Speech is presentation only: it may never cancel or defer the learning action.
  assert(!/preventDefault\(\)/.test(MODULE_SRC.split('"keydown"')[0]),
    "the click path must never preventDefault");
  assert(!/stopPropagation|stopImmediatePropagation/.test(MODULE_SRC),
    "the click path must never stop propagation");
  ok("delegated on click, never preventDefault/stopPropagation on the click path");

  // makeMatch: the picture side is still not a host, and the word side became focusable.
  const mm = extractFn(html, "function makeMatch(");
  assert(/w\.setAttribute\("role", "button"\)/.test(mm) && /w\.setAttribute\("tabindex", "0"\)/.test(mm),
    "matching words must be focusable");
  assert(/b\.className = "mpic"/.test(mm), "picture buttons unchanged");
  assert(!/mpic[\s\S]{0,400}data-speak|dataset\.speak/.test(mm.split('"mpic"')[1] || ""),
    "picture buttons must not opt into speech");
  ok("makeMatch: word column focusable, picture column still silent and unchanged");

  // makeReorder: token identity and grading are untouched by this feature.
  const ro = extractFn(html, "function makeReorder(");
  assert(/tokens = sentences\[idx\]\.map\(\(w, i\) => \(\{ id: i, word: w \}\)\)/.test(ro),
    "reorder token identity changed");
  assert(/placed\.every\(\(id, i\) => id === i\)/.test(ro), "reorder grading rule changed");
  assert(/c\.textContent = tokens\[id\]\.word/.test(ro), "chip text source changed");
  assert(!/dataset\.speak/.test(ro), "reorder needed no per-element speech wiring");
  ok("makeReorder: {id, word} identity, index-equality grading and chip text all unchanged");

  // makeDictation: nothing in it opts into speech, and its controls are not hosts.
  const dict = extractFn(html, "function makeDictation(");
  assert(!/dataset\.speak|speakEnglish/.test(dict),
    "dictation must not gain click-to-speak: its target sentence is what the exercise tests");
  assert(/playBtn\.addEventListener\("click", \(\) => playAt\(sentence\)\)/.test(dict),
    "the intentional Listen/replay behaviour must remain");
  ok("makeDictation: no click-to-speak added; the deliberate Listen replay is intact");

  // makeQuiz still grades on button text, so speech must not have rewritten labels.
  const quiz = extractFn(html, "function makeQuiz(");
  assert(/if \(b\.textContent === right\)/.test(quiz), "quiz grading key changed");
  assert(/btn\.textContent = choice/.test(quiz), "quiz option label changed");
  ok("makeQuiz: option labels and the textContent grading key are unchanged");

  // makeWh / makeCloze speak the clicked choice FIRST, through the shared sequence helper.
  const wh = extractFn(html, "function makeWh(");
  assert(/btn\.dataset\.speak = "off"/.test(wh), "WH options must defer to answer()");
  assert(/speakEnglishSeq\(choice === it\.a \? \[it\.a\] : \[choice, it\.a\]\)/.test(wh),
    "WH must speak the clicked choice then the correct sentence");
  assert(/if \(b\.dataset\.val === it\.a\)/.test(wh), "WH grading key changed");
  const cloze = extractFn(html, "function makeCloze(");
  assert(/btn\.dataset\.speak = "off"/.test(cloze), "cloze options must defer to answer()");
  assert(/speakEnglishSeq\(\[choice, it\.text\.replace\("___", it\.answer\)\]\)/.test(cloze),
    "cloze must speak the candidate then the completed sentence");
  assert(/if \(b\.textContent === it\.answer\)/.test(cloze), "cloze grading key changed");
  ok("makeWh / makeCloze: clicked choice spoken first, then the existing follow-up; keys unchanged");
}

// ================================================================ 13. WH / cloze ordering, executed
{
  // The ordered sequence really does put the clicked item first (speakSeq chains on onend).
  const env = makeEnv();
  env.sandbox.speakEnglishSeq(["cat", "I like the cat."]);
  assert.deepStrictEqual(env.said(), ["cat"], "only the first utterance starts immediately");
  env.spoken[0].onend();                                  // the synthesiser finishes utterance 1
  assert.deepStrictEqual(env.said(), ["cat", "I like the cat."], env.said().join("|"));
  ok("speakEnglishSeq speaks the clicked item first, then chains the follow-up sentence");

  // A correct WH pick is not read twice.
  const env2 = makeEnv();
  env2.sandbox.speakEnglishSeq(["The zoo is next to the park."]);
  assert.deepStrictEqual(env2.said(), ["The zoo is next to the park."]);
  ok("a correct WH choice is spoken once, not duplicated");

  // Blanks inside a sequence are dropped rather than producing a pause.
  const env3 = makeEnv();
  assert.strictEqual(env3.sandbox.speakEnglishSeq(["", null, "  ", "✓"]), false);
  assert.deepStrictEqual(env3.said(), []);
  ok("a sequence of only blank/decorative entries speaks nothing");
}

// ================================================================ 14. no double-speak per click
{
  // A click on a nested span inside a host resolves to exactly ONE utterance, even though the event
  // passes through several ancestors.
  const env = makeEnv();
  const row = el("div", "mword");
  const word = el("span", "wword"); word.appendChild(text("apple"));
  row.appendChild(word);
  env.click(word);                                    // learner taps the text, not the row
  assert.deepStrictEqual(env.said(), ["apple"], "one click must speak once: " + env.said().join("|"));
  // Nested hosts (a chip inside an answer area) still speak once.
  const env2 = makeEnv();
  const area = el("div", "reorder-answer");
  const chip = el("button", "chip"); chip.textContent = "like";
  area.appendChild(chip);
  env2.click(chip);
  assert.deepStrictEqual(env2.said(), ["like"]);
  ok("one click = one utterance, including clicks landing on a nested child");
}

console.log("\nAll " + passed + " click-to-speak checks passed.");
