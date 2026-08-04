#!/usr/bin/env python3
"""Phase 4C §33/§34 — Role-play parity against the REAL shipped browser implementation.

    python3 tests/learning_roleplay_parity_test.py

Loads `roleplay/classifier.js` and `roleplay/engine.js` in node and compares them, case by case,
against the Python port in `learning/roleplay.py`:

  * classifier parity over every node of the real Zoo/MRT/Market/Park graphs
  * classifier parity over synthetic nodes that exercise the branches real content never reaches
    (`partial` routes, `objective.markers`, empty-route nodes)
  * weighted branch selection parity under a shared seeded RNG
  * FULL SESSION goldens: node sequence, per-turn classification, turns, passes, final pct

Skips (does not fail) when node is unavailable.
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from learning import roleplay as RP  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


if not shutil.which("node"):
    print("  SKIP - node not available; cannot execute the real Role-play implementation")
    sys.exit(0)

LESSONS = ["zoo", "mrt", "market", "park"]


def graph_of(slug):
    with open(os.path.join(ROOT, "roleplay", "scenarios", "lesson",
                           "Pre-A1-taipei-%s.json" % slug), encoding="utf-8") as f:
        return json.load(f)


GRAPHS = {s: graph_of(s) for s in LESSONS}

# Responses chosen to land in every band: verbatim examples, paraphrases, keyword-only answers,
# punctuation/case/duplicate variants, and clear nonsense.
RESPONSES = [
    "Wow! I can see a big lion.",
    "WOW!!!  I   CAN SEE a BIG   LION???",          # case + punctuation + whitespace runs
    "lion lion lion big big",                        # duplicate tokens
    "I see a lion",
    "big",                                           # keyword only -> bonus band
    "the a an of and to",                            # all stop-words
    "",                                              # empty
    "     ",                                         # whitespace only
    "purple bicycle refrigerator",                   # clear off-topic
    "I can see a panda too.",
    "The panda is black and white.",
    "Yes! The monkey can jump.",
    "we are at the zoo",
    "I want some noodles. I am hungry.",
    "The train is fast.",
    "We can sit under the tree.",
    "lionn",                                         # edit-distance-1 slip
    "lio",                                           # prefix slip
    "don't  it's  can't",                            # apostrophes survive tokenisation
    "café naïve 日本語",                               # non-ascii is stripped to separators
]

# Synthetic nodes for branches the real content never uses.
SYNTHETIC = [
    {"id": "syn_partial", "npc": {"text": "hi"}, "routes": [
        {"intent": "p", "partial": True, "examples": ["I want a big lion"],
         "keywords": ["lion"], "next_nodes": [{"id": "syn_partial", "weight": 1}]}]},
    {"id": "syn_obj", "npc": {"text": "hi"}, "routes": [
        {"intent": "o", "examples": ["I can see a big lion"], "keywords": ["lion", "big", "see"],
         "objective": {"markers": ["please"]},
         "next_nodes": [{"id": "syn_obj", "weight": 1}]}]},
    {"id": "syn_obj_phrase", "npc": {"text": "hi"}, "routes": [
        {"intent": "o2", "examples": ["I can see a big lion"], "keywords": ["lion", "big", "see"],
         "objective": {"markers": ["big lion"]},
         "next_nodes": [{"id": "syn_obj_phrase", "weight": 1}]}]},
    {"id": "syn_noroutes", "npc": {"text": "bye"}, "routes": []},
    {"id": "syn_meaning", "npc": {"text": "hi"}, "routes": [
        {"intent": "m", "meaning": "Anna sees a lion", "examples": [], "keywords": ["zzz"],
         "next_nodes": [{"id": "syn_meaning", "weight": 1}]}]},
]

_JS = r"""
global.window = global;
require(process.argv[2]);          // roleplay/classifier.js
require(process.argv[3]);          // roleplay/engine.js
const fs = require('fs');
const job = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));

// LocalClassifier.classify returns a PROMISE (result() wraps in Promise.resolve), so every case
// must be awaited — reading the returned object directly would serialise an empty Promise.
function mk(seed) { let a = seed >>> 0; return function () {
  a |= 0; a = (a + 0x6D2B79F5) | 0;
  let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}; }

(async () => {
  const clsOut = [];
  for (const c of job.classify) {
    const k = new RP.classifiers.local({ pass: c.pass, floor: c.floor });
    const r = await k.classify(c.text, c.node);
    clsOut.push({ result: r.result, intent: r.intent, objectiveMet: r.objectiveMet, scores: r.scores });
  }
  const selOut = job.select.map(s => {
    const rng = mk(s.seed);
    const eng = new RP.Engine(s.graph, { strategy: 'weighted', rng: rng });
    const picks = [];
    for (let i = 0; i < s.draws; i++) { const r = eng._selectNext(s.route); picks.push(r ? r.id : null); }
    return picks;
  });
  console.log(JSON.stringify({ classify: clsOut, select: selOut }));
})();
"""

# The session half needs promise draining, so it gets its own async driver.
_JS_SESSION = r"""
global.window = global;
require(process.argv[2]);
require(process.argv[3]);
const fs = require('fs');
const job = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
function mk(seed) { let a = seed >>> 0; return function () {
  a |= 0; a = (a + 0x6D2B79F5) | 0;
  let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}; }
(async () => {
  const out = [];
  for (const s of job.sessions) {
    const rng = mk(s.seed);
    let summary = null;
    const eng = new RP.Engine(s.graph, {
      classifier: new RP.classifiers.local({ pass: s.pass, floor: s.floor }),
      strategy: 'weighted', rng: rng,
      onEnd: (sum) => { summary = sum; },
    });
    eng.start();
    const trace = [{ node: eng.current ? eng.current.id : null }];
    for (const text of s.inputs) {
      if (eng.done) break;
      const info = await eng.submit(text);
      trace.push({ result: info ? info.result : null,
                   node: eng.current ? eng.current.id : null,
                   turns: eng.turns, passes: eng.history.filter(h => h.result === 'PASS').length });
    }
    out.push({ trace: trace, done: eng.done, turns: eng.turns,
               passes: eng.history.filter(h => h.result === 'PASS').length,
               summary: summary });
  }
  console.log(JSON.stringify(out));
})();
"""


def run_node(src, job):
    tmp = os.path.join(ROOT, "tests", ".rp_parity_job.json")
    js = os.path.join(ROOT, "tests", ".rp_parity.js")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(job, f)
        with open(js, "w", encoding="utf-8") as f:
            f.write(src)
        r = subprocess.run(["node", js,
                            os.path.join(ROOT, "roleplay", "classifier.js"),
                            os.path.join(ROOT, "roleplay", "engine.js"), tmp],
                           capture_output=True, text=True, cwd=ROOT, encoding="utf-8")
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)
    finally:
        for p in (tmp, js):
            if os.path.exists(p):
                os.remove(p)


class Mulberry32:
    """Same PRNG as the node side, so both languages draw the identical float sequence."""

    def __init__(self, seed):
        self.a = seed & 0xFFFFFFFF

    def random(self):
        self.a = (self.a + 0x6D2B79F5) & 0xFFFFFFFF
        t = self.a
        t = (_imul(t ^ (t >> 15), 1 | t)) & 0xFFFFFFFF
        t = (t + _imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF ^ t
        t &= 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0


def _imul(a, b):
    """C-like 32-bit signed multiply, matching JS Math.imul."""
    a &= 0xFFFFFFFF
    b &= 0xFFFFFFFF
    r = (a * b) & 0xFFFFFFFF
    return r


# ============================== 1. classifier parity ==============================
cases = []
for slug in LESSONS:
    for node in GRAPHS[slug]["nodes"]:
        for text in RESPONSES:
            cases.append({"node": node, "text": text,
                          "pass": RP.LESSON_PASS, "floor": RP.LESSON_FLOOR})
for node in SYNTHETIC:
    for text in RESPONSES + ["please I can see a big lion", "I can see a big lion"]:
        cases.append({"node": node, "text": text,
                      "pass": RP.LESSON_PASS, "floor": RP.LESSON_FLOOR})
# also pin the CLASS DEFAULTS (0.6 / 0.28), which level 10 overrides but parity must still hold for
for node in GRAPHS["zoo"]["nodes"]:
    for text in RESPONSES[:8]:
        cases.append({"node": node, "text": text,
                      "pass": RP.DEFAULT_PASS, "floor": RP.DEFAULT_FLOOR})

# ============================== 2. weighted selection parity ==============================
MULTI = {"start": "a", "nodes": [
    {"id": "a", "npc": {"text": "a"}, "routes": [{"intent": "i", "examples": ["x"],
     "next_nodes": [{"id": "a", "weight": 1}, {"id": "b", "weight": 3}, {"id": "c", "weight": 96}]}]},
    {"id": "b", "npc": {"text": "b"}, "end": True},
    {"id": "c", "npc": {"text": "c"}, "end": True}]}
MULTI_ROUTE = MULTI["nodes"][0]["routes"][0]
selects = [{"graph": MULTI, "route": MULTI_ROUTE, "seed": seed, "draws": 40}
           for seed in (1, 7, 12345, 99991)]

# ============================== 3. full-session goldens ==============================
ZOO, MRT = GRAPHS["zoo"], GRAPHS["mrt"]
# One correct answer per node along arrive -> lion -> panda -> monkey -> fun -> bye (terminal).
STRONG_ZOO = ["Wow! I can see a big lion.", "I like the lion. It is big.",
              "Look! I can see a panda too.", "Yes! The monkey can jump.",
              "This zoo is fun. I am happy."]
sessions = [
    # 1. all strong answers
    {"graph": ZOO, "inputs": STRONG_ZOO, "seed": 5, "pass": RP.LESSON_PASS, "floor": RP.LESSON_FLOOR},
    # 2. mixed: nonsense, a partial, then strong
    {"graph": ZOO, "seed": 11, "pass": RP.LESSON_PASS, "floor": RP.LESSON_FLOOR,
     "inputs": ["purple bicycle", "lion", "Wow! I can see a big lion.", "purple bicycle",
                "I like the lion. It is big.", "Look! I can see a panda too."]},
    # 3. repeated OFF_TOPIC only — never advances, never completes
    {"graph": ZOO, "seed": 3, "pass": RP.LESSON_PASS, "floor": RP.LESSON_FLOOR,
     "inputs": ["purple bicycle refrigerator"] * 6},
    # 4. multi-branch weighted graph
    {"graph": MULTI, "seed": 42, "pass": RP.LESSON_PASS, "floor": RP.LESSON_FLOOR,
     "inputs": ["x", "x", "x"]},
    # 5. a real MRT run to terminal
    {"graph": MRT, "seed": 8, "pass": RP.LESSON_PASS, "floor": RP.LESSON_FLOOR,
     "inputs": ["Yes. The train is fast.", "We can sit here. Come on.",
                "We can go to the night market.", "Me too. I want some food.",
                "The train is clean and quiet.", "Look! This is our stop.", "Okay! Let us go."]},
]

js_cls = run_node(_JS, {"classify": cases, "select": selects, "sessions": []})
mismatch = []
for c, got in zip(cases, js_cls["classify"]):
    k = RP.LocalClassifier(c["pass"], c["floor"])
    mine = k.classify(c["text"], c["node"])
    if (mine["result"] != got["result"] or mine["intent"] != got["intent"]
            or mine["objectiveMet"] != got["objectiveMet"]
            or [s["score"] for s in mine["scores"]] != [s["score"] for s in got["scores"]]):
        mismatch.append((c["node"]["id"], c["text"], mine["result"], got["result"],
                         [s["score"] for s in mine["scores"]], [s["score"] for s in got["scores"]]))
assert not mismatch, mismatch[:4]
seen = {}
for c, got in zip(cases, js_cls["classify"]):
    seen[got["result"]] = seen.get(got["result"], 0) + 1
assert set(seen) == {"PASS", "PARTIAL", "OFF_TOPIC"}, seen
ok("§33 classifier parity: %d (node, response, thresholds) cases match the real classifier.js "
   "exactly — result, intent, objectiveMet and every rounded route score (%s)"
   % (len(cases), ", ".join("%s=%d" % kv for kv in sorted(seen.items()))))

# weighted selection
for s, got in zip(selects, js_cls["select"]):
    rng = Mulberry32(s["seed"])
    mine = [RP.select_next(s["route"], s["graph"], rng) for _ in range(s["draws"])]
    assert mine == got, (s["seed"], mine[:8], got[:8])
assert len({tuple(p) for p in js_cls["select"]}) > 1, "seeds must produce different paths"
assert len(set(js_cls["select"][0])) > 1, "the 1/3/96 weighting must actually vary"
ok("§11 weighted branch selection parity: 4 seeds x 40 draws over a 1/3/96 weighted route match "
   "strategies.weighted exactly")

# ============================== full sessions ==============================
js_sess = run_node(_JS_SESSION, {"sessions": sessions})
for s, got in zip(sessions, js_sess):
    rng = Mulberry32(s["seed"])
    k = RP.LocalClassifier(s["pass"], s["floor"])
    version = RP.graph_version(json.dumps(s["graph"], sort_keys=True))
    sess = RP.start_session(s["graph"], version, "x", 1000)
    trace = [{"node": sess["currentNodeId"]}]
    for text in s["inputs"]:
        if sess["completed"]:
            break
        status, info = RP.apply_response(sess, s["graph"], text, rng, 1000, classifier=k)
        assert status == "ok", (status, text)
        trace.append({"result": info["result"], "node": sess["currentNodeId"],
                      "turns": sess["turns"], "passes": sess["passes"]})
    assert trace == got["trace"], (s["seed"], trace, got["trace"])
    assert sess["completed"] == got["done"], (sess["completed"], got["done"])
    assert sess["turns"] == got["turns"] and sess["passes"] == got["passes"], (sess, got)
    if got["summary"]:
        assert got["summary"]["turns"] == sess["turns"], got["summary"]
        assert got["summary"]["passes"] == sess["passes"], got["summary"]
        # rpOnEnd would call recordScore(10, passes, turns) with exactly these two numbers
        assert RP.result_of(sess)["passes"] == got["summary"]["passes"]
        assert RP.result_of(sess)["turns"] == got["summary"]["turns"]

# the fixtures must genuinely cover the required shapes
assert js_sess[0]["done"] is True and js_sess[0]["passes"] == js_sess[0]["turns"], js_sess[0]
assert js_sess[2]["done"] is False and js_sess[2]["passes"] == 0 and js_sess[2]["turns"] == 6, \
    "repeated OFF_TOPIC must never advance, never complete, and still count 6 turns"
assert js_sess[1]["passes"] < js_sess[1]["turns"], "the mixed run must have a lossy denominator"
assert RP.result_of({"passes": 0, "turns": 6})["pct"] == 0
ok("§34 full-session goldens: 5 seeded conversations (all-strong / mixed / repeated off-topic / "
   "multi-branch weighted / real MRT to terminal) reproduce the real Engine's node sequence, "
   "per-turn result, turns, passes and final summary exactly")

# ============================== the shipped score is passes/turns ==============================
assert RP.result_of({"passes": 8, "turns": 8}) == {"passes": 8, "turns": 8, "pct": 100}
assert RP.result_of({"passes": 3, "turns": 6}) == {"passes": 3, "turns": 6, "pct": 50}
assert RP.result_of({"passes": 2, "turns": 3})["pct"] == 67, "Math.round(66.67) = 67, half-up"
assert RP.result_of({"passes": 1, "turns": 8})["pct"] == 13, "Math.round(12.5) = 13, half-up"
assert RP.result_of({"passes": 0, "turns": 0}) == {"passes": 0, "turns": 0, "pct": 0}
ok("§20 score evidence equals recordScore(10, passes, turns) with JS half-up rounding for pct")

print()
print("All %d Role-play parity tests passed." % passed)
