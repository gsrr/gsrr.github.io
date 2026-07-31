#!/usr/bin/env python3
"""Phase 4B §36 — cross-language Rule A parity against the REAL shipped frontend.

    python3 tests/learning_rule_a_parity_test.py

Every other Rule A test compares the backend against a Python restatement of the legacy rule. This
one executes the ACTUAL `scoredLevelsFor()` / `statusFromScores()` functions out of index.html in
node and compares them to `learning/completion.py`, for all four Taipei lessons.

It exists because a Python restatement got the required LEVEL SET wrong: `scoredLevelsFor()` appends
level 10 (Role-play) OUTSIDE its if/else, so it applies to declared-level lessons too, and every
Taipei lesson is therefore scored on seven levels — not the six that were assumed. The arithmetic was
right; the required set was not. This test pins both halves so the same class of drift cannot recur.

Skips (does not fail) when node is unavailable.
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from learning import completion as C, registry as R  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


if not shutil.which("node"):
    print("  SKIP - node not available; cannot execute the real frontend functions")
    sys.exit(0)

# The four Taipei arcs exactly as index.html declares them (levels array included).
ARCS = {
    "english.prea1.taipei.zoo": {"file": "Pre-A1/taipei/zoo", "levels": [1, 2, 3, 4, 5, 7, 9]},
    "english.prea1.taipei.mrt": {"file": "Pre-A1/taipei/mrt", "levels": [1, 2, 3, 4, 5, 7, 9]},
    "english.prea1.taipei.market": {"file": "Pre-A1/taipei/market", "levels": [1, 2, 3, 4, 5, 7, 9]},
    "english.prea1.taipei.park": {"file": "Pre-A1/taipei/park", "levels": [1, 2, 3, 4, 5, 7, 9]},
}

# Representative score vectors over levels 2,3,4,5,7,9,10 as (correct, total) or None for "unscored".
VECTORS = [
    [(4, 5)] * 7,                                              # every level exactly 80 -> 80
    [(5, 5)] * 7,                                              # perfect
    [(5, 5), (5, 5), (5, 5), (5, 5), (5, 5), (5, 5), (0, 10)],  # one zero, mean still passes
    [(4, 5), (4, 5), (4, 5), (4, 5), (4, 5), (4, 5), (38, 50)],  # 79.x -> rounds down
    [(2, 3)] * 7,                                              # unrounded per-level terms
    [(1, 1), (1, 1), (1, 1), (1, 1), (1, 1), (1, 1), (0, 100)],  # unweighted mean
    [(5, 5)] * 6 + [None],                                     # level 10 unscored -> blocked
    [None] + [(5, 5)] * 6,                                     # level 2 unscored -> blocked
    [(5, 5), None, (5, 5), None, (5, 5), (5, 5), (5, 5)],       # two gaps
    [(3, 5), (5, 5), (4, 5), (5, 5), (4, 5), (3, 4), (7, 9)],   # ragged real-ish vector
]

_JS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const body = src.slice(src.indexOf('function scoredLevelsFor'), src.indexOf('function lessonStatus'));
const statusFromScores = new Function('PASS_MARK', body + '; return statusFromScores;')(80);
const scoredLevelsFor  = new Function('PASS_MARK', body + '; return scoredLevelsFor;')(80);
const jobs = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
console.log(JSON.stringify(jobs.map(j => {
  const r = statusFromScores(j.arc, j.scores);
  return { need: scoredLevelsFor(j.arc), allScored: r.allScored, avg: r.avg, passed: r.passed };
})));
"""

LEVELS = ["2", "3", "4", "5", "7", "9", "10"]
ROLEPLAY = "10"


def run_js(jobs):
    """Run the REAL shipped statusFromScores()/scoredLevelsFor() over `jobs` in node."""
    tmp = os.path.join(ROOT, "tests", ".rule_a_parity_jobs.json")
    js = os.path.join(ROOT, "tests", ".rule_a_parity.js")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(jobs, f)
        with open(js, "w", encoding="utf-8") as f:
            f.write(_JS)
        out = subprocess.run(["node", js, os.path.join(ROOT, "index.html"), tmp],
                             capture_output=True, text=True, cwd=ROOT)
        assert out.returncode == 0, out.stderr
        got = json.loads(out.stdout)
    finally:
        for p in (tmp, js):
            if os.path.exists(p):
                os.remove(p)
    assert len(got) == len(jobs), (len(got), len(jobs))
    return got


jobs = []
for lid, arc in sorted(ARCS.items()):
    for vec in VECTORS:
        scores = {}
        for lv, cell in zip(LEVELS, vec):
            if cell is not None:
                scores[lv] = {"correct": cell[0], "total": cell[1]}
        jobs.append({"lesson": lid, "arc": arc, "scores": scores})

legacy = run_js(jobs)

# ---------- 1. the required LEVEL SET, straight from the shipped function ----------
for job, got in zip(jobs, legacy):
    assert got["need"] == LEVELS, (job["lesson"], got["need"])
ok("§5 legacy scoredLevelsFor() scores SEVEN levels for every Taipei lesson — 2,3,4,5,7,9 and 10 "
   "Role-play, which is appended unconditionally outside the if/else")

# ---------- 2. arithmetic parity, level for level ----------
mismatches = []
for job, got in zip(jobs, legacy):
    required = ["L%s" % lv for lv in LEVELS]
    scores = {"L%s" % lv: {"correct": v["correct"], "total": v["total"]}
              for lv, v in job["scores"].items()}
    mean = C.rule_a_mean(scores, required)
    if mean is None:
        mine = {"allScored": False, "avg": None, "passed": False}
    else:
        rounded = C._round_half_up(mean)
        mine = {"allScored": True, "avg": rounded, "passed": rounded >= C.PASS_MARK}
    theirs = {"allScored": got["allScored"], "avg": got["avg"], "passed": got["passed"]}
    if mine != theirs:
        mismatches.append((job["lesson"], job["scores"], mine, theirs))
assert not mismatches, mismatches[:3]
ok("§18/§36 backend rule_a_mean + half-up rounding matches the real statusFromScores() exactly on "
   "%d (lesson, score-vector) pairs across all four Taipei lessons" % len(jobs))

# ---------- 3. pin the DOCUMENTED divergence between legacy Rule A and the active policy ----------
reg = R.REGISTRY
COVERED = ["read_along", "quiz3", "quiz4", "matching", "wh", "cloze"]     # levels 2,3,4,5,7,9
for lid in ARCS:
    for suffix in COVERED:
        aid = "%s.%s" % (lid, suffix)
        assert aid in reg.activities and reg.is_server_scored(aid), aid
    # level 10 has no registered activity of any kind, under any name
    assert not [a for a in reg.activities
                if reg.lesson_of_activity(a) == lid and a.rsplit(".", 1)[1]
                not in COVERED], "an unexpected activity appeared on %s" % lid
assert len(LEVELS) == 7, LEVELS
# No lesson may carry an active policy while level 10 has no server authority: a 6-activity policy
# would silently redefine Rule A. Zoo's v1 was retired for exactly this reason.
for lid in ARCS:
    assert reg.completion_policy_of(lid) is None, \
        "%s must not be activated while level 10 has no server authority" % lid
assert [l for l in reg.lessons if reg.completion_available(l)] == [], \
    "production authoritative lesson policies must be 0"
assert reg.retired_policy_versions("english.prea1.taipei.zoo") == [1], "Zoo v1 is spent"
ok("§42 correction pinned: 0 active lesson policies, because a 6-of-7 policy would silently "
   "redefine Rule A; Zoo's retired v1 can never be reused")

# ---------- 4. the exact case that must never be assumed away again ----------
# Perfect scores on the six authoritative levels, level 10 absent -> legacy Rule A is INCOMPLETE.
perfect_six = {"lesson": "english.prea1.taipei.mrt", "arc": ARCS["english.prea1.taipei.mrt"],
               "scores": {lv: {"correct": 5, "total": 5} for lv in LEVELS if lv != ROLEPLAY}}
with_ten = {"lesson": perfect_six["lesson"], "arc": perfect_six["arc"],
            "scores": dict(perfect_six["scores"], **{ROLEPLAY: {"correct": 0, "total": 10}})}
legacy2 = run_js([perfect_six, with_ten])
assert legacy2[0]["allScored"] is False and legacy2[0]["avg"] is None \
    and legacy2[0]["passed"] is False, legacy2[0]
# and a ZERO on level 10 is enough to make it complete, which is why the level cannot be dropped:
# omitting it is not "assuming the worst", it is a different rule.
assert legacy2[1]["allScored"] is True and legacy2[1]["passed"] is True \
    and legacy2[1]["avg"] == 86, legacy2[1]
# the backend agrees on both, given the true 7-level required set
assert C.rule_a_mean({"L%s" % k: v for k, v in perfect_six["scores"].items()},
                     ["L%s" % lv for lv in LEVELS]) is None
assert C._round_half_up(C.rule_a_mean({"L%s" % k: v for k, v in with_ten["scores"].items()},
                                      ["L%s" % lv for lv in LEVELS])) == 86
ok("§ regression: perfect 2/3/4/5/7/9 with level 10 MISSING is legacy-Rule-A INCOMPLETE, while a "
   "level-10 score of 0/10 completes it at 86 — the six-level assumption cannot return")

print()
print("All %d Rule A parity tests passed." % passed)
