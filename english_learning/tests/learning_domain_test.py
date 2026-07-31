#!/usr/bin/env python3
"""Phase 3B — Learning Domain: grading, qualifications, reward policy, and the LearningService.

    python3 tests/learning_domain_test.py

The centrepiece is a SYNTHETIC, NON-ENGLISH content pack (`bio.cells`) driven through the exact same
LearningService the production Taipei slice uses. If any subject/lesson/activity-specific branch
existed anywhere in the Learning Domain, this file could not pass.
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from learning import (api as L, content as C, grading as G, qualifications as Q,   # noqa: E402
                      registry as R, rewards as W)

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ================= grading: dispatched by TYPE, never by activity name =================
KEY = [{"q": "A is true.", "answer": "Yes"}, {"q": "B is false.", "answer": "No"},
       {"q": "C is true.", "answer": "Yes"}, {"q": "D is true.", "answer": "Yes"},
       {"q": "E is false.", "answer": "No"}]
allright = [{"q": k["q"], "answer": k["answer"]} for k in KEY]
r = G.grade("yes_no", KEY, allright)
assert r == {"graderType": "yes_no", "correct": 5, "total": 5, "pct": 100, "passed": True}, r
assert G.grade("yes_no", KEY, list(reversed(allright)))["passed"] is True, "order-independent (match by q)"
assert G.grade("yes_no", KEY, [{"q": k["q"], "answer": k["answer"].upper()} for k in KEY])["passed"] is True
one_wrong = [dict(a) for a in allright]; one_wrong[0]["answer"] = "No"
assert G.grade("yes_no", KEY, one_wrong)["pct"] == 80 and G.grade("yes_no", KEY, one_wrong)["passed"] is True
two_wrong = [dict(a) for a in allright]; two_wrong[0]["answer"] = "No"; two_wrong[1]["answer"] = "Yes"
assert G.grade("yes_no", KEY, two_wrong)["passed"] is False, "3/5 = 60% fails"
assert G.grade("yes_no", KEY, [])["passed"] is False and G.grade("yes_no", [], allright)["passed"] is False
assert G.grade("yes_no", KEY, None)["passed"] is False
# a key item with a blank answer can never be scored correct (no free points)
assert G.grade("yes_no", [{"q": "x", "answer": ""}], [{"q": "x", "answer": ""}])["correct"] == 0
# unknown grader type -> never a pass, never an exception. THE OLD ACTIVITY-NAME API IS GONE.
for bad in ("quiz3", "quiz4", "match", "matching", "vocab", "pronunciation", "roleplay",
            None, "", "Yes_No"):
    assert G.grade(bad, KEY, allright)["passed"] is False and not G.is_supported(bad), bad
# Phase 3C added three deterministic graders. `matching` stays OUT on purpose (category B — its score
# depends on click history, see docs/deterministic-graders.md), as do pronunciation and roleplay.
assert G.grader_types() == ["dictation", "multiple_choice", "reorder", "yes_no"], G.grader_types()
assert G.PASS_MARK == 80
ok("grading: type-dispatched, order/case-independent, threshold 80, unknown type never passes")

# ================= reward policy: content may NAME a policy, never an amount (§15) =================
assert W.resolve("standard_activity_pass", {"PASS_GOLD": 10000}) == {"type": "gold", "amount": 10000, "once": True}
assert W.resolve("none", {"PASS_GOLD": 10000})["amount"] == 0
# an unknown/forged policy id, or a policy whose amount the server did not supply, pays NOTHING
for bogus in ("rewardGold", "custom_999999", "", None, "STANDARD_ACTIVITY_PASS"):
    assert W.resolve(bogus, {"PASS_GOLD": 10000})["amount"] == 0, bogus
assert W.resolve("standard_activity_pass", {})["amount"] == 0, "no injected amount -> fail closed"
assert W.resolve("standard_activity_pass", {"PASS_GOLD": -5})["amount"] == 0
assert W.resolve("standard_activity_pass", {"PASS_GOLD": True})["amount"] == 0, "bool is not an amount"
src = open(os.path.join(ROOT, "learning", "rewards.py"), encoding="utf-8").read()
assert "10000" not in src and "PASS_GOLD =" not in src, \
    "rewards.py must contain no amounts — the number lives in game config only"
ok("rewards: policy allowlist resolves amounts from injected game config; forged policy/amount pays 0")

# ================= qualifications: opaque, idempotent, many-to-many =================
st = {}
assert not Q.has_qualification(st, "biology.cell.unit03")
st, granted = Q.grant_qualification(st, "biology.cell.unit03", 100)
assert granted is True and Q.has_qualification(st, "biology.cell.unit03")
st, again = Q.grant_qualification(st, "biology.cell.unit03", 999)
assert again is False and st["qualifications"]["biology.cell.unit03"]["earnedAt"] == 100, "idempotent"
# §34: A -> Q1 ; B -> Q2 ; C -> Q1 + Q3  (a qualification is reusable across activities)
st2 = {}
st2, newA = Q.grant_qualifications(st2, ["q.one"], 1)
st2, newB = Q.grant_qualifications(st2, ["q.two"], 2)
st2, newC = Q.grant_qualifications(st2, ["q.one", "q.three"], 3)
assert newA == ["q.one"] and newB == ["q.two"], (newA, newB)
assert newC == ["q.three"], "re-granting q.one via another activity is a no-op, order preserved"
assert st2["qualifications"]["q.one"]["earnedAt"] == 1, "the FIRST grant's timestamp survives"
assert Q.earned_qualification_ids(st2) == {"q.one", "q.two", "q.three"}
st2, dup = Q.grant_qualifications(st2, ["q.four", "q.four"], 4)
assert dup == ["q.four"], "duplicates inside one grant list collapse"
assert Q.missing_qualifications(st2, ["q.one", "q.nope", "q.nope", "q.gone"]) == ["q.nope", "q.gone"]
assert Q.has_all_qualifications(st2, ["q.one", "q.three"]) and not Q.has_all_qualifications(st2, ["q.one", "q.x"])
assert Q.has_all_qualifications(st2, []) is True, "no requirements == satisfied"
assert Q.has_all_qualifications({}, ["q.one"]) is False
st3 = json.loads(json.dumps(st2))
assert Q.earned_qualification_ids(st3) == Q.earned_qualification_ids(st2), "survives JSON roundtrip"
ok("qualifications: opaque ids, idempotent, many-to-many grants, first timestamp wins, roundtrips")

# ================= completion records + legacy merge =================
stc = {}
Q.record_completion(stc, "a.b.c.d", 500, 100, True)
assert Q.get_completion(stc, "a.b.c.d") == {"passedAt": 500, "pct": 100, "rewarded": True}
assert Q.get_completion(stc, "nope") is None and Q.merge_completions(stc, ["nope"]) is None
# merging canonical + legacy: earliest pass wins, best pct wins, rewarded is sticky
stm = {"activityCompletions": {"canon": {"passedAt": 900, "pct": 80, "rewarded": False},
                               "legacy#k": {"passedAt": 100, "pct": 100, "rewarded": True}}}
assert Q.merge_completions(stm, ["canon", "legacy#k"]) == {"passedAt": 100, "pct": 100, "rewarded": True}
assert Q.merge_completions(stm, ["canon"]) == {"passedAt": 900, "pct": 80, "rewarded": False}
ok("completions: record/get, canonical+legacy merge keeps earliest pass and sticky rewarded")


# ============ THE GENERIC PIPELINE: a synthetic NON-ENGLISH pack through LearningService ============
tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, "packs", "bio"), exist_ok=True)
json.dump({"check": [{"q": "A cell has a membrane.", "answer": "Yes"},
                     {"q": "A cell is a mineral.", "answer": "No"},
                     {"q": "Mitochondria make ATP.", "answer": "Yes"},
                     {"q": "DNA is a protein.", "answer": "No"}],
           "review": [{"q": "Osmosis moves water.", "answer": "Yes"},
                      {"q": "Osmosis moves stone.", "answer": "No"}]},
          open(os.path.join(tmp, "packs", "bio", "cells.json"), "w", encoding="utf-8"))

SYNTH = {
    "schemaVersion": 1,
    "contentPacks": {"bio": {"title": "Biology"}},
    "courses": {"bio.cells": {"contentPackId": "bio", "title": "Cells"}},
    "units": {"bio.cells.u1": {"courseId": "bio.cells", "title": "Unit 1"}},
    "lessons": {"bio.cells.intro": {"courseId": "bio.cells", "unitId": "bio.cells.u1",
                                    "contentPath": "packs/bio/cells", "title": "Cell basics"}},
    "activities": {
        # A -> Q1
        "bio.cells.intro.check": {"lessonId": "bio.cells.intro", "contentKey": "check",
                                  "graderType": "yes_no", "title": "Cells — check",
                                  "grants": ["bio.q1"], "rewardPolicy": "standard_activity_pass",
                                  "legacyKeys": ["packs/bio/cells#check"]},
        # B -> Q1 + Q3 (one activity, multiple qualifications), and NO reward
        "bio.cells.intro.review": {"lessonId": "bio.cells.intro", "contentKey": "review",
                                   "graderType": "yes_no", "title": "Cells — review",
                                   "grants": ["bio.q1", "bio.q3"], "rewardPolicy": "none"},
    },
    "qualifications": {"bio.q1": {"scope": "activity", "title": "Cell basics — check"},
                       "bio.q3": {"scope": "activity", "title": "Cell basics — review"}},
}
assert R.validate(SYNTH) == [], R.validate(SYNTH)
svc = L.LearningService(R.Registry(SYNTH), content_root=tmp, reward_amounts={"PASS_GOLD": 10000})

# identity resolution: canonical, legacy key, logical lesson + key, content path + key
assert svc.resolve_activity("bio.cells.intro.check") == "bio.cells.intro.check"
assert svc.resolve_activity("packs/bio/cells#check") == "bio.cells.intro.check"
assert svc.resolve_activity(None, "bio.cells.intro", "check") == "bio.cells.intro.check"
assert svc.resolve_activity(None, "packs/bio/cells", "check") == "bio.cells.intro.check"
assert svc.resolve_activity("bio.cells.intro") is None, "a lesson id is not an activity id"
assert svc.resolve_activity("nope") is None and svc.resolve_activity(None, "nope", "check") is None
ok("service identity: canonical / legacy key / logical lesson / content path all resolve; unknown -> None")

# grading through the service — content and grader chosen by the registry, not the caller
RIGHT_A = [{"q": "A cell has a membrane.", "answer": "Yes"}, {"q": "A cell is a mineral.", "answer": "No"},
           {"q": "Mitochondria make ATP.", "answer": "Yes"}, {"q": "DNA is a protein.", "answer": "No"}]
res, reason = svc.grade_attempt("bio.cells.intro.check", RIGHT_A)
assert reason is None and res["passed"] is True and res["pct"] == 100, (res, reason)
res_bad, _ = svc.grade_attempt("bio.cells.intro.check", [{"q": "A cell has a membrane.", "answer": "No"}])
assert res_bad["passed"] is False and res_bad["pct"] == 0
assert svc.grade_attempt("nope.nope", RIGHT_A) == (None, L.REASON_NOT_GRADABLE)
assert svc.grade_attempt("bio.cells.intro.check", "Yes") == (None, L.REASON_BAD_ANSWERS)
assert svc.grade_attempt("bio.cells.intro.check", None) == (None, L.REASON_BAD_ANSWERS)
ok("service grading: registry picks content+grader; unknown activity and bad answers refused")

# completion + many-to-many grants + reward, all idempotent
state = {}
state, out = svc.record_attempt(state, "bio.cells.intro.check", res, 1000)
assert out["passed"] and out["granted"] == ["bio.q1"] and out["grantedNow"] == ["bio.q1"]
assert out["alreadyCompleted"] is False and out["rewarded"] is True and out["rewardAmount"] == 10000
assert state["activityCompletions"]["bio.cells.intro.check"] == {"passedAt": 1000, "pct": 100, "rewarded": True}
state, out2 = svc.record_attempt(state, "bio.cells.intro.check", res, 2000)
assert out2["alreadyCompleted"] is True and out2["grantedNow"] == [] and out2["rewarded"] is False
assert out2["rewardAmount"] == 0 and state["activityCompletions"]["bio.cells.intro.check"]["passedAt"] == 1000
# a FAILED attempt records nothing and grants nothing
before_completions = json.dumps(state.get("activityCompletions"), sort_keys=True)
before_quals = json.dumps(state.get("qualifications"), sort_keys=True)
state, out3 = svc.record_attempt(state, "bio.cells.intro.review", res_bad, 3000)
assert out3["passed"] is False and out3["granted"] == [] and out3["rewarded"] is False
# Phase 3F: a failure now persists the LATEST SCORE (Rule A needs it) but still grants nothing and
# still writes no completion record.
assert state["activityScores"]["bio.cells.intro.review"]["pct"] == res_bad["pct"]
assert json.dumps(state.get("activityCompletions"), sort_keys=True) == before_completions
assert json.dumps(state.get("qualifications"), sort_keys=True) == before_quals
# activity B grants TWO qualifications, one of which is already held, and carries NO reward
res_b, _ = svc.grade_attempt("bio.cells.intro.review",
                             [{"q": "Osmosis moves water.", "answer": "Yes"},
                              {"q": "Osmosis moves stone.", "answer": "No"}])
state, out4 = svc.record_attempt(state, "bio.cells.intro.review", res_b, 4000)
assert out4["granted"] == ["bio.q1", "bio.q3"] and out4["grantedNow"] == ["bio.q3"], out4
assert out4["rewarded"] is False and out4["rewardAmount"] == 0, "rewardPolicy 'none' pays nothing"
assert state["qualifications"]["bio.q1"]["earnedAt"] == 1000, "the earlier grant is not re-dated"
assert svc.player_qualification_ids(state) == {"bio.q1", "bio.q3"}
ok("service completion: many-to-many grants, per-activity reward policy, failures are no-ops, idempotent")

# legacy record honoured: prior reward + prior date carried forward, old key left intact
legacy_state = {"activityCompletions": {"packs/bio/cells#check": {"passedAt": 7, "pct": 100, "rewarded": True}}}
assert svc.read_completion(legacy_state, "bio.cells.intro.check") == {"passedAt": 7, "pct": 100, "rewarded": True}
legacy_state, out5 = svc.record_attempt(legacy_state, "bio.cells.intro.check", res, 9000)
assert out5["alreadyCompleted"] is True and out5["rewarded"] is False, "no double reward across a rename"
assert legacy_state["activityCompletions"]["packs/bio/cells#check"]["passedAt"] == 7, "old record untouched"
assert legacy_state["activityCompletions"]["bio.cells.intro.check"]["passedAt"] == 7, "date carried forward"
ok("service legacy: pre-rename records resolve, carry their date/reward forward, are never rewritten")

# content access is registry-allowlisted: an undeclared path is unreadable even if it exists on disk
json.dump({"check": [{"q": "x", "answer": "Yes"}]}, open(os.path.join(tmp, "secret.json"), "w"))
assert C.load_lesson("secret", tmp, svc.registry.approved_content_paths()) is None, "not registry-declared"
assert C.load_lesson("secret", tmp, None) is not None, "…but the file really is there (allowlist did the work)"
for esc in ("../server", "../../etc/passwd", "/etc/passwd", "packs\\bio\\cells", ".", "..", "", None):
    assert C.load_lesson(esc, tmp, svc.registry.approved_content_paths()) is None, esc
    assert C.resolve_path(esc, tmp, None) is None or not os.path.isfile(C.resolve_path(esc, tmp, None) or "x")
assert C.load_activity_items("packs/bio/cells", "nosuchkey", tmp, svc.registry.approved_content_paths()) is None
shutil.rmtree(tmp, ignore_errors=True)
ok("content access: registry allowlist + traversal guards; undeclared/escaping paths never read")


# ================= the REAL installed pack still wires up (Phase 3A slice preserved) =================
prod = L.LearningService(content_root=ROOT, reward_amounts={"PASS_GOLD": 10000})
AID = "english.prea1.taipei.zoo.quiz3"
assert prod.resolve_activity(AID) == AID
assert prod.resolve_activity(None, "Pre-A1/taipei/zoo", "quiz3") == AID, "Phase 3A client shape still resolves"
assert prod.resolve_activity("Pre-A1/taipei/zoo#quiz3") == AID, "Phase 3A completion key still resolves"
assert prod.qualifications_for_activity(AID) == ["english.prea1.taipei.zoo"]
assert prod.completion_keys(AID) == [AID, "Pre-A1/taipei/zoo#quiz3"]
assert prod.reward_for(AID) == {"type": "gold", "amount": 10000, "once": True}
zoo = json.load(open(os.path.join(ROOT, "Pre-A1", "taipei", "zoo.json"), encoding="utf-8"))["quiz3"]
res_zoo, reason = prod.grade_attempt(AID, [{"q": i["q"], "answer": i["answer"]} for i in zoo])
assert reason is None and res_zoo["passed"] is True and res_zoo["pct"] == 100, (res_zoo, reason)
ok("installed pack: the Zoo/quiz3 slice resolves via canonical AND both legacy shapes, and still grades")

print("\nAll %d learning-domain tests passed." % passed)
