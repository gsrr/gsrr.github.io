#!/usr/bin/env python3
"""Phase 3C — deterministic graders: golden cases + per-type edge cases + real-content smoke.

    python3 tests/learning_graders_test.py

The golden cases in tests/fixtures/learning_grader_golden.json are shared with
tests/learning_parity.test.js, which derives the SAME expectations from the live frontend rules in
index.html. If the two disagree, one of the two files fails.
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from learning import grading as G, normalization as N  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


GOLDEN = json.load(open(os.path.join(ROOT, "tests", "fixtures", "learning_grader_golden.json"),
                        encoding="utf-8"))["cases"]

# ============================== golden cases ==============================
by_type = {}
for case in GOLDEN:
    res = G.grade(case["graderType"], case["content"], case["answers"], case.get("cfg"))
    exp = case["expect"]
    for k in ("correct", "total", "pct", "passed"):
        assert res[k] == exp[k], "%s: %s expected %r got %r" % (case["name"], k, exp[k], res[k])
    by_type.setdefault(case["graderType"], 0)
    by_type[case["graderType"]] += 1
ok("golden: %d cases across %s" % (len(GOLDEN), sorted(by_type)))

# ============================== shared contract ==============================
for gt in G.grader_types():
    assert G.is_supported(gt)
    # empty / invalid key -> non-pass, total 0, never an exception
    for bad_key in ([], None, "nope", {}, 0):
        r = G.grade(gt, bad_key, [{"q": "x", "answer": "y"}])
        assert r == {"graderType": gt, "correct": 0, "total": 0, "pct": 0, "passed": False}, (gt, bad_key, r)
    # malformed answer evidence -> safe non-pass, never an exception
    for bad_ans in (None, "Yes", 5, {}, [None], [5], ["Yes"], [{"answer": "x"}], [{"q": None}]):
        r = G.grade(gt, [{"q": "Q1", "a": "A1", "answer": "A1", "wrong": []}], bad_ans,
                    {"promptField": "q", "answerField": "a"})
        assert r["passed"] is False and r["total"] == 1, (gt, bad_ans, r)
    assert set(G.grade(gt, [{"q": "a", "a": "b", "answer": "b"}], []).keys()) == \
        {"graderType", "correct", "total", "pct", "passed"}
for unknown in ("matching", "reorder", "dictation", "quiz3", "wh", "cloze", None, "", "MULTIPLE_CHOICE"):
    if unknown in G.GRADERS:
        continue
    assert not G.is_supported(unknown)
    assert G.grade(unknown, [{"q": "a", "a": "b"}], [{"q": "a", "answer": "b"}])["passed"] is False
assert G.PASS_MARK == 80
ok("contract: uniform GradeResult, empty/invalid key and malformed evidence fail safely, unknown type never passes")

# ============================== multiple_choice edge cases ==============================
WH_CFG = {"promptField": "q", "answerField": "a", "distractorsField": "wrong"}
K = [{"q": "Q1", "a": "A1", "wrong": ["B1", "C1"]}, {"q": "Q2", "a": "A2", "wrong": ["B2", "C2"]}]
# a duplicate submission for one prompt keeps the FIRST answer (no last-write-wins farming)
assert G.grade("multiple_choice", K, [{"q": "Q1", "answer": "B1"}, {"q": "Q1", "answer": "A1"},
                                      {"q": "Q2", "answer": "A2"}], WH_CFG)["correct"] == 1
assert G.grade("multiple_choice", K, [{"q": "Q1", "answer": "A1"}, {"q": "Q1", "answer": "B1"},
                                      {"q": "Q2", "answer": "A2"}], WH_CFG)["correct"] == 2
# prompt matching tolerates surrounding whitespace (prompt_key strips) but answers stay exact
assert G.grade("multiple_choice", K, [{"q": "  Q1  ", "answer": "A1"}], WH_CFG)["correct"] == 1
assert G.grade("multiple_choice", K, [{"q": "Q1", "answer": " A1"}], WH_CFG)["correct"] == 0
# an item whose answer field is missing/None can never be scored correct
assert G.grade("multiple_choice", [{"q": "Q1", "wrong": ["B"]}], [{"q": "Q1", "answer": "B"}],
               WH_CFG)["correct"] == 0
assert G.grade("multiple_choice", [{"q": "Q1", "a": None}], [{"q": "Q1", "answer": None}],
               WH_CFG)["correct"] == 0
# a blank prompt is unscorable (cannot be keyed)
assert G.grade("multiple_choice", [{"q": "", "a": "A"}], [{"q": "", "answer": "A"}], WH_CFG)["correct"] == 0
# distractors absent / not a list -> the correct answer is still the only accepted option
assert G.grade("multiple_choice", [{"q": "Q1", "a": "A1"}], [{"q": "Q1", "answer": "A1"}], WH_CFG)["correct"] == 1
assert G.grade("multiple_choice", [{"q": "Q1", "a": "A1", "wrong": "B1"}],
               [{"q": "Q1", "answer": "A1"}], WH_CFG)["correct"] == 1
# non-string option values compare by their string form (numeric maths content)
assert G.grade("multiple_choice", [{"q": "2+2", "a": 4, "wrong": [5]}],
               [{"q": "2+2", "answer": 4}], WH_CFG)["correct"] == 1
# cfg defaults: promptField q / answerField a / distractorsField wrong when cfg is absent
assert G.grade("multiple_choice", K, [{"q": "Q1", "answer": "A1"}, {"q": "Q2", "answer": "A2"}])["pct"] == 100
# correct can never exceed total even with a pathological key
assert G.grade("multiple_choice", K, [{"q": "Q1", "answer": "A1"}] * 9, WH_CFG)["correct"] <= 2
ok("multiple_choice: first-answer-wins, exact option compare, missing/None/blank/duplicate handled, cfg defaults")

# ============================== reorder edge cases ==============================
R = [["I", "went", "home"], ["She", "sings"]]
assert G.grade("reorder", R, [{"q": "I went home", "answer": [0, 1, 2]},
                              {"q": "She sings", "answer": [0, 1]}])["pct"] == 100
# string indices are coerced (a JSON client may send them), but non-numeric is simply wrong
assert G.grade("reorder", R, [{"q": "I went home", "answer": ["0", "1", "2"]}])["correct"] == 1
for junk in ([0, 1, "x"], [0, 1, None], [0, 1, 2.5], "012", {"0": 1}, None, [], [0, 1, 2, 3]):
    assert G.grade("reorder", [["I", "went", "home"]],
                   [{"q": "I went home", "answer": junk}])["correct"] == 0, junk
# 2.5 must NOT be silently truncated to 2
assert G.grade("reorder", [["a", "b", "c"]], [{"q": "a b c", "answer": [0, 1, 2.5]}])["correct"] == 0
# an out-of-range index is wrong, not a crash
assert G.grade("reorder", [["a", "b"]], [{"q": "a b", "answer": [0, 99]}])["correct"] == 0
# a non-list / empty key item is skipped but still counted in the total
assert G.grade("reorder", [["a", "b"], "nope", []], [{"q": "a b", "answer": [0, 1]}])["correct"] == 1
assert G.grade("reorder", [["a", "b"], "nope", []], [{"q": "a b", "answer": [0, 1]}])["total"] == 3
# single-token sentence
assert G.grade("reorder", [["Hello"]], [{"q": "Hello", "answer": [0]}])["pct"] == 100
# duplicate submissions for one sentence keep the FIRST
assert G.grade("reorder", [["a", "b"]], [{"q": "a b", "answer": [1, 0]},
                                         {"q": "a b", "answer": [0, 1]}])["correct"] == 0
ok("reorder: index equality, string coercion, junk/out-of-range/wrong-length wrong, first-answer-wins")

# ============================== dictation edge cases ==============================
D = ["I went to the park.", "She sings."]
assert G.grade("dictation", D, [{"q": "I went to the park.", "answer": "i went to the park"},
                                {"q": "She sings.", "answer": "SHE SINGS"}])["pct"] == 100
# norm() strips exactly these 8 ASCII marks, nothing else
assert N.dictation_text("A, b. c! d? e; f: g' h\"") == "a b c d e f g h"
assert N.dictation_text("well-known") == "well-known", "hyphen is NOT stripped"
assert N.dictation_text("It’s") == "it’s", "curly apostrophe is NOT stripped"
assert N.dictation_text("  a   b  ") == "a b" and N.dictation_text(None) == "" and N.dictation_text(5) == "5"
# only typed strings are gradable; numbers/lists/None are wrong rather than errors
for junk in (5, ["a"], None, {"a": 1}, True):
    assert G.grade("dictation", ["one two"], [{"q": "one two", "answer": junk}])["correct"] == 0, junk
# a blank/whitespace key item is skipped but still counted
assert G.grade("dictation", ["one two", "", "   "], [{"q": "one two", "answer": "one two"}])["correct"] == 1
assert G.grade("dictation", ["one two", "", "   "], [{"q": "one two", "answer": "one two"}])["total"] == 3
# a non-string key item is never scorable
assert G.grade("dictation", [5, None, ["a"]], [{"q": "5", "answer": "5"}])["correct"] == 0
# typing punctuation-only against a real sentence is not a free pass
assert G.grade("dictation", ["one two"], [{"q": "one two", "answer": ".,!?"}])["correct"] == 0
# duplicate submissions for one sentence keep the FIRST
assert G.grade("dictation", ["one two"], [{"q": "one two", "answer": "wrong"},
                                          {"q": "one two", "answer": "one two"}])["correct"] == 0
ok("dictation: exact norm() port, only 8 marks stripped, junk/blank/punct-only wrong, first-answer-wins")

# ============================== real content smoke (no lesson files embedded) ==============================
n_wh = n_cloze = 0
for f in sorted(glob.glob(os.path.join(ROOT, "Pre-A1", "**", "*.json"), recursive=True))[:6]:
    d = json.load(open(f, encoding="utf-8"))
    wh = d.get("wh") or []
    if wh:
        ans = [{"q": it["q"], "answer": it["a"]} for it in wh]
        r = G.grade("multiple_choice", wh, ans, WH_CFG)
        assert r["pct"] == 100 and r["passed"] is True, (f, r)
        wrong = [{"q": it["q"], "answer": (it.get("wrong") or ["x"])[0]} for it in wh]
        assert G.grade("multiple_choice", wh, wrong, WH_CFG)["correct"] == 0, f
        n_wh += 1
    cz = d.get("cloze") or []
    if cz:
        cfg = {"promptField": "text", "answerField": "answer", "distractorsField": "wrong"}
        ans = [{"q": it["text"], "answer": it["answer"]} for it in cz]
        assert G.grade("multiple_choice", cz, ans, cfg)["pct"] == 100, (f, cz)
        n_cloze += 1
assert n_wh and n_cloze
ok("real content: %d wh + %d cloze activities grade 100%% with their own keys, 0%% with distractors"
   % (n_wh, n_cloze))

# ============================== normalization module ==============================
assert N.prompt_key("  a  ") == "a" and N.prompt_key(None) == "" and N.prompt_key(5) == "5"
assert N.exact_choice(None) == "" and N.exact_choice(4) == "4" and N.exact_choice(" a ") == " a "
ok("normalization: prompt_key trims, exact_choice does not")

print("\nAll %d grader tests passed." % passed)
