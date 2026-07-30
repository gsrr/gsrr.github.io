#!/usr/bin/env python3
"""Phase 3A — Learning Domain unit tests (qualifications + grading), pure & content-independent.

    python3 tests/learning_domain_test.py
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from learning import qualifications as Q, grading as G, content as C, registry as R  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ================= qualifications (pure, idempotent, opaque) =================
st = {}
assert not Q.has_qualification(st, "english.test.q1")            # empty state
st, granted = Q.grant_qualification(st, "english.test.q1", 100)
assert granted is True and Q.has_qualification(st, "english.test.q1")
first_earned = st["qualifications"]["english.test.q1"]["earnedAt"]
st, granted2 = Q.grant_qualification(st, "english.test.q1", 999)  # duplicate grant
assert granted2 is False, "duplicate grant returns granted_now=False"
assert st["qualifications"]["english.test.q1"]["earnedAt"] == first_earned, "idempotent: earnedAt unchanged"
assert not Q.has_qualification(st, "english.test.q2")            # missing
st, _ = Q.grant_qualification(st, "english.test.q2", 200)
assert Q.has_all_qualifications(st, ["english.test.q1", "english.test.q2"])   # has all
assert not Q.has_all_qualifications(st, ["english.test.q1", "english.test.q3"])
assert Q.missing_qualifications(st, ["english.test.q1", "english.test.q3", "english.test.q4"]) == \
    ["english.test.q3", "english.test.q4"], "missing preserves order, dedups"
assert Q.missing_qualifications(st, ["english.test.q1", "english.test.q1"]) == []
assert Q.earned_qualification_ids(st) == {"english.test.q1", "english.test.q2"}
# serialization roundtrip
st2 = json.loads(json.dumps(st))
assert Q.has_all_qualifications(st2, ["english.test.q1", "english.test.q2"]), "survives JSON roundtrip"
# arbitrary opaque NON-English id treated identically
st3 = {}
st3, g3 = Q.grant_qualification(st3, "biology.cell.unit03", 1)
assert g3 and Q.has_qualification(st3, "biology.cell.unit03") and not Q.has_qualification(st3, "english.anything")
ok("qualifications: empty/grant/duplicate-idempotent/has/missing/has-all/roundtrip/opaque-non-english")

# ================= grading (deterministic Yes/No, matches by question text) =================
KEY = [{"q": "A is true.", "answer": "Yes"}, {"q": "B is false.", "answer": "No"},
       {"q": "C is true.", "answer": "Yes"}, {"q": "D is true.", "answer": "Yes"},
       {"q": "E is false.", "answer": "No"}]
allright = [{"q": k["q"], "answer": k["answer"]} for k in KEY]
r = G.grade("quiz3", KEY, allright)
assert r == {"correct": 5, "total": 5, "pct": 100, "passed": True}, r
# shuffled order still grades correctly (match by q, not position)
r_sh = G.grade("quiz3", KEY, list(reversed(allright)))
assert r_sh["correct"] == 5 and r_sh["passed"] is True, "order-independent"
# 4/5 = 80 => passes exactly at threshold
one_wrong = [dict(a) for a in allright]; one_wrong[0]["answer"] = "No"
assert G.grade("quiz3", KEY, one_wrong) == {"correct": 4, "total": 5, "pct": 80, "passed": True}
# 3/5 = 60 => fails
two_wrong = [dict(a) for a in allright]; two_wrong[0]["answer"] = "No"; two_wrong[1]["answer"] = "Yes"
assert G.grade("quiz3", KEY, two_wrong)["passed"] is False
# empty answers, unknown activity, empty key -> not passed
assert G.grade("quiz3", KEY, [])["passed"] is False
assert G.grade("match", KEY, allright)["passed"] is False and not G.is_gradable("match")
assert G.grade("quiz3", [], allright)["passed"] is False
assert G.is_gradable("quiz3") and G.is_gradable("quiz4")
ok("grading: all-correct/shuffled/threshold-80/fail/empty/unknown-activity/empty-key")

# ================= registry + content (vertical slice wiring) =================
assert R.qualification_for("Pre-A1/taipei/zoo", "quiz3") == "english.prea1.taipei.zoo"
assert R.qualification_for("Pre-A1/taipei/zoo", "match") is None       # only registered activity
assert R.qualification_for("nonexistent", "quiz3") is None
pv = R.public_view()
assert "english.prea1.taipei.zoo" in pv and "answer" not in json.dumps(pv), "registry view carries no answer keys"
les = C.load_lesson("Pre-A1/taipei/zoo", ROOT)
assert isinstance(les, dict) and isinstance(les.get("quiz3"), list) and les["quiz3"], "slice lesson loads"
# path traversal / escape attempts are refused
assert C.load_lesson("../server", ROOT) is None
assert C.load_lesson("../../etc/passwd", ROOT) is None
assert C.load_lesson("", ROOT) is None
# grading the REAL slice lesson with its own key passes
real_ans = [{"q": it["q"], "answer": it["answer"]} for it in les["quiz3"]]
assert G.grade("quiz3", les["quiz3"], real_ans)["passed"] is True
ok("registry/content: slice mapping, no-keys public view, path-traversal refused, real lesson grades")

print("\nAll %d learning-domain tests passed." % passed)
