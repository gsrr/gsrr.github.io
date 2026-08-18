#!/usr/bin/env python3
"""Phase 9B — a curriculum lesson is NOT a conquest gate. The A1/001 pilot proves the split.

    python3 tests/curriculum_pilot_test.py

Phase 9A found 57 content units on disk but only 4 completable lessons, and `english.a1.core.001`
registered with no completion policy (so invisible everywhere) and mislabelled with A1/002's title.
9B makes that ONE lesson authoritative as the migration template for the other 52.

The point of the pilot is the decoupling: `completionPolicy`, `rewardPolicy` and `grants` are three
independent registry fields, so a lesson can be completable and pay both learning rewards while
granting NO qualification — and therefore unlocking no territory. Every Taipei lesson grants one;
A1/001 deliberately grants none. That is what makes CEFR curriculum independent of the game map.
"""
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))   # Phase 9B.1 shared derived expectations
import curriculum_expectations as CX  # noqa: E402
from game import config as GC  # noqa: E402
from learning import (api as L, qualifications as Q, registry as R,  # noqa: E402
                      reward_ledger as LG, rewards as W)
import territory_catalog as TC  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


AMOUNTS = {"PASS_GOLD": GC.PASS_GOLD, "LESSON_MASTERY_GOLD": GC.MASTERY_GOLD}
svc = L.LearningService(content_root=ROOT, reward_amounts=AMOUNTS)
reg = R.REGISTRY

PILOT = "english.a1.core.001"
GATE = PILOT + ".quiz3"
REQUIRED = [PILOT + "." + s for s in ("read_along", "quiz3", "matching", "reorder", "dictation")]
TAIPEI4 = sorted("english.prea1.taipei." + s for s in ("zoo", "mrt", "market", "park"))
TAIPEI_QUALS = ["english.prea1.taipei.market.quiz3.pass", "english.prea1.taipei.mrt.quiz3.pass",
                "english.prea1.taipei.park.quiz3.pass", "english.prea1.taipei.zoo"]
A1 = json.load(open(os.path.join(ROOT, "A1", "001.json"), encoding="utf-8"))
ANSWERS = [{"q": i["q"], "answer": i["answer"]} for i in A1["quiz3"]]

# ============================== 1. the title describes the real content ==============================
title = reg.lesson(PILOT).get("title")
text = open(os.path.join(ROOT, "A1", "001"), encoding="utf-8").read()
assert reg.lesson(PILOT)["contentPath"] == "A1/001", reg.lesson(PILOT)
assert "Yesterday at the Park" in title, title
assert "My Weekend" not in title, "A1/002's title must not be on A1/001 (the Phase 9A mislabel)"
# the content itself: A1/001 is the park conversation, A1/002 is the weekend/zoo one
assert "park" in text.lower() and "yesterday" in text.lower(), text[:120]
assert "My Weekend" in json.load(open(os.path.join(ROOT, "lessons.json"), encoding="utf-8")
                                 )["levels"][1]["articles"][1]["title"], \
    "A1/002 keeps its own title — 9B must not have moved it"
ok("1. title fixed: A1/001 is %r and still points at contentPath A1/001; A1/002 untouched" % title)

# ============================== 2. authoritative completion is available ==============================
assert reg.completion_available(PILOT) is True, "the pilot must now declare a usable policy"
pol = reg.completion_policy_of(PILOT)
assert pol["type"] == "average_required_activities", pol
assert pol["version"] == 1 and pol["passMark"] == 80, pol
assert pol["requiredActivityIds"] == REQUIRED, pol["requiredActivityIds"]
assert reg.retired_policy_versions(PILOT) == [], "a brand-new policy retires nothing"
active = sorted(l for l in reg.lessons if reg.completion_available(l))
# Phase 9C: the pilot and Taipei must be active, but the POPULATION grows as curriculum migrates.
assert PILOT in active and set(TAIPEI4) <= set(active), active
ok("2. completion policy v1 active over its 5 registered activities; completable lessons 4 -> 5")

# ============================== 3/4. completes and masters through the server ==============================
def master(state, now=2000):
    """Seed authoritative evidence for every required activity, then let the service settle."""
    for aid in REQUIRED:
        if svc.is_matching(aid):
            state.setdefault("matchingProgress", {})[aid] = {"correct": 10, "total": 10, "pct": 100}
        elif svc.is_read_along(aid):
            state.setdefault("sttProgress", {})[aid] = {"pct": 100}
        else:
            Q.record_activity_score(state, aid, 10, 10, 100, now)
            Q.record_completion(state, svc.completion_key(aid), passed_at=now, pct=100, rewarded=True)
    out = {}
    svc._settle_lesson(state, PILOT, now, out)
    return state, out


res, err = svc.grade_attempt(GATE, ANSWERS)
assert not err and res["passed"] and res["pct"] == 100, (err, res)
st, gate_out = svc.record_attempt({}, GATE, res, 100)
assert gate_out["rewardAmount"] == GC.PASS_GOLD == 160, gate_out
assert gate_out.get("lessonRewardAmount", 0) == 0, "mastery must not pay at the gate"
ok("3. the gate grades server-side and pays PASS_GOLD (%d) exactly once" % GC.PASS_GOLD)

st, m = master(st)
assert m["lessonCompletedNow"] is True, m
assert m["lessonRewardAmount"] == GC.MASTERY_GOLD == 640, m
assert LG.total_granted(st, "gold") == GC.PASS_GOLD + GC.MASTERY_GOLD == 800, LG.total_granted(st, "gold")
assert LG.owned_items(st) == ["badge.lesson.mastered"], LG.owned_items(st)
ok("4. mastery completes server-side and pays MASTERY_GOLD (%d); 800 total, same as a Taipei lesson"
   % GC.MASTERY_GOLD)

# ============================== 5/6/7. exactly once ==============================
base = copy.deepcopy(st)
_, again = master(copy.deepcopy(base), now=3000)
assert again.get("lessonRewardAmount", 0) == 0, "replayed mastery pays nothing"
res2, _ = svc.grade_attempt(GATE, ANSWERS)
_, gate2 = svc.record_attempt(copy.deepcopy(base), GATE, res2, 3100)
assert gate2["rewardAmount"] == 0, "replayed gate pays nothing"
assert LG.total_granted(base, "gold") == 800, "the ledger total never grows on replay"
ok("5/6/7. replayed gate and replayed mastery both pay 0; ledger stays at 800")

# ============================== 8/9/10. NO qualification, anywhere ==============================
assert reg.qualification_ids_for(GATE) == [], "the pilot gate must grant NO qualification"
assert reg.lesson_qualification_ids_for(PILOT) == [], "the pilot lesson must grant NO qualification"
assert sorted(reg.qualifications) == TAIPEI_QUALS, sorted(reg.qualifications)
assert len(reg.qualifications) == 4, "qualification total stays 4 — 9B adds curriculum, not gates"
held = sorted((base.get("qualifications") or {}))
assert held == [], "mastering the pilot granted the learner no qualification at all: %r" % held
assert not svc.player_qualification_ids(base), svc.player_qualification_ids(base)
ok("8/9/10. pilot grants no qualification; registry total stays 4 (%s); a learner who mastered "
   "A1/001 holds none" % ", ".join(q.split(".")[-1] for q in TAIPEI_QUALS))

# ============================== the gold-bearing set grew by exactly one ==============================
gold_bearing = sorted(a for a in reg.activities if svc.reward_for(a)["amount"] > 0)
# Phase 9C: derived population. What stays pinned is the SPLIT: only Taipei gates grant a
# qualification, every curriculum gate grants none — that is the invariant, not the count.
assert gold_bearing == CX.declared_gates(reg), gold_bearing
CX.assert_reward_model(reg, svc, GC.PASS_GOLD)
for aid in gold_bearing:
    assert reg.reward_policy_of(aid) == "standard_activity_pass", aid
    assert svc.reward_for(aid)["amount"] == GC.PASS_GOLD, aid
# every gate grants a qualification EXCEPT the curriculum pilot — the whole point of Phase 9B
granting = sorted(a for a in gold_bearing if reg.qualification_ids_for(a))
assert granting == sorted(l + ".quiz3" for l in TAIPEI4), granting
ok("gold-bearing activities 4 -> 5, all through ONE shared policy at PASS_GOLD; 4 of the 5 grant a "
   "qualification and the curriculum pilot grants none")

# ============================== 11. forged client progress cannot complete it ==============================
for forged in (
        {"ruleB": {PILOT: 100}, "practice": {PILOT: 100}},
        {"checkpointDone": {"A1": True}, "examPassed": {"A1": True}},
        {"lessonCompletions": {PILOT: {"completedAt": 1, "policyVersion": 1}}},
        {"activityScores": {aid: {"pct": 100} for aid in REQUIRED}},
        {"passcnt": {PILOT: 99}, "average": 100, "completed": True, "mastered": True},
):
    ev = svc.evaluate_lesson(PILOT, copy.deepcopy(forged))
    assert ev["completed"] is False, ("forged client state completed the lesson", forged)
    out = {}
    s2 = svc._settle_lesson(copy.deepcopy(forged), PILOT, 4000, out)
    assert out.get("lessonRewardAmount", 0) == 0, ("forged state paid gold", forged, out)
    assert (s2.get("qualifications") or {}) == {}, ("forged state granted a qualification", forged)
ok("11. five shapes of forged client progress (Rule B, checkpoint, fake completion record, fake "
   "scores, passcnt/mastered flags) complete nothing, pay nothing and grant nothing")

# ============================== 15. world-data untouched, no territory unlocked ==============================
cat = TC.TerritoryCatalog(os.path.join(ROOT, "world-data")).load()
gated = sorted(t for t in cat.territories if cat.attack_requirements(t))
assert gated == ["taipei:daan", "taipei:songshan", "taipei:xinyi",
                 "taipei:zhongshan", "taipei:zhongzheng"], gated
for t in gated:
    for qid in cat.attack_requirements(t):
        assert qid in TAIPEI_QUALS, (t, qid)
        assert qid not in (reg.qualification_ids_for(GATE) or []), (t, qid)
# the learner who mastered the pilot satisfies no gate anywhere
for t in gated:
    need = set(cat.attack_requirements(t))
    assert not need <= set(base.get("qualifications") or {}), \
        "mastering A1/001 must not satisfy %s" % t
ok("15. the same 5 Taipei territories are gated by the same 4 qualifications; a learner who "
   "mastered the pilot satisfies none of them")

# ============================== 14. checkpoint content is untouched ==============================
# The pilot changed registry METADATA only. A1/001.json is what buildExamPool() reads, so its cloze
# block is the checkpoint dependency Phase 9A flagged; registering activities cannot alter it.
assert len(A1["cloze"]) == 4, len(A1["cloze"])
assert all(set(("text", "answer", "wrong")) <= set(i) for i in A1["cloze"])
# Phase 9E.2 catalogued cloze as an OPTIONAL activity. buildExamPool() reads the CONTENT file, not
# the registry, so the checkpoint source is unaffected either way; what matters is that the content
# block is untouched and that cloze never became mastery-required for the pilot.
assert PILOT + ".cloze" in reg.activities, "9E.2 catalogues cloze as optional practice"
assert PILOT + ".cloze" not in reg.completion_policy_of(PILOT)["requiredActivityIds"], \
    "cloze must remain OPTIONAL - the pilot still requires exactly its five"
assert svc.reward_for(PILOT + ".cloze")["amount"] == 0
ok("14. A1/001.json cloze block is unchanged; cloze is catalogued as inert OPTIONAL practice and is "
   "not mastery-required, so the checkpoint question source is unaffected")

# ============================== Taipei semantics are byte-identical ==============================
for lid in TAIPEI4:
    p = reg.completion_policy_of(lid)
    assert p["version"] == 2 and p["passMark"] == 80, (lid, p)
    assert len(p["requiredActivityIds"]) == 7, (lid, p)
    assert reg.lesson_reward_policies_of(lid) == ["lesson_mastery_badge", "lesson_mastery_gold"], lid
    assert reg.lesson_qualification_ids_for(lid) == [], lid
    q = reg.qualification_ids_for(lid + ".quiz3")
    assert len(q) == 1 and q[0] in TAIPEI_QUALS, (lid, q)
assert reg.retired_policy_versions("english.prea1.taipei.zoo") == [1], "Zoo v1 stays retired"
assert reg.qualification_ids_for("english.prea1.taipei.zoo.quiz3") == ["english.prea1.taipei.zoo"], \
    "the Zoo naming inconsistency is deliberately NOT normalised in 9B"
ok("Taipei regression: all four keep v2/7-activity policies, both reward policies, one "
   "qualification each, and Zoo keeps its legacy bare qualification id")

# ============================== the pilot pays through config, not content ==============================
assert W.is_economic("standard_activity_pass") and W.is_economic("lesson_mastery_gold")
assert "amount" not in json.dumps(reg.lesson(PILOT)), "content may never state an amount (§15)"
assert svc.reward_for(GATE)["amount"] == GC.PASS_GOLD, "the amount comes from game config"
blob = json.dumps({"lesson": reg.lesson(PILOT),
                   "activity": reg.activities[GATE]})
for n in ("160", "640", "800"):
    assert n not in blob, "the registry must not hardcode reward amounts: %s" % n
ok("amounts stay server-configured: the pilot's registry entry names policies only, no numbers")

print("\nAll %d curriculum-pilot tests passed." % passed)
