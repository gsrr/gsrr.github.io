#!/usr/bin/env python3
"""Phase 4A — Taipei curriculum progression: earning paths, gates, reachability, invariants.

    python3 tests/taipei_progression_test.py

Covers §34 earning paths, §35 territory requirements, §36 reachability, §37 Study navigation,
§38 Zoo/Daan backward compatibility, §39 reward neutrality, §40 world invariants.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))   # Phase 9B.1: shared registry-derived expectations
import curriculum_expectations as CX  # noqa: E402
from game import conquest  # noqa: E402
from learning import api as L, qualifications as Q, registry as R, rewards as W  # noqa: E402
import territory_catalog  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


reg = R.REGISTRY
svc = L.LearningService(content_root=ROOT, reward_amounts={"PASS_GOLD": 10000})
cat = territory_catalog.catalog
START = "taipei:wenshan"
ZOO_Q = "english.prea1.taipei.zoo"
MRT_Q = "english.prea1.taipei.mrt.quiz3.pass"
MKT_Q = "english.prea1.taipei.market.quiz3.pass"
PARK_Q = "english.prea1.taipei.park.quiz3.pass"
CURATED = {
    "taipei:daan": [ZOO_Q],
    "taipei:xinyi": [MRT_Q],
    "taipei:zhongzheng": [MKT_Q],
    "taipei:songshan": [PARK_Q],
    "taipei:zhongshan": [MKT_Q, ZOO_Q],
}
SANDBOX = ["taipei:beitou", "taipei:datong", "taipei:nangang", "taipei:neihu",
           "taipei:shilin", "taipei:wanhua"]
TAIPEI = json.load(open(os.path.join(ROOT, "world-data", "territories", "taipei.json"),
                        encoding="utf-8"))
BY_ID = {t["id"]: t for t in TAIPEI}

# ============================== the approved mapping is what shipped ==============================
for tid, qids in CURATED.items():
    assert cat.attack_requirements(tid) == qids, (tid, cat.attack_requirements(tid))
assert cat.attack_requirements(START) == [], "the start territory must be ungated"
for tid in SANDBOX:
    assert cat.attack_requirements(tid) == [], tid
gated = {t["id"] for t in TAIPEI if ((t.get("requirements") or {}).get("attackQualificationIds"))}
assert gated == set(CURATED), gated
assert len(TAIPEI) == 12 and len(gated) == 5
ok("mapping: exactly the 5 approved curated gates; start and the 6 sandbox districts stay ungated")

# ============================== §34 every requirement is earnable ==============================
granting = {}
for aid in reg.activities:
    for qid in reg.qualification_ids_for(aid):
        granting.setdefault(qid, []).append(aid)
for tid, qids in CURATED.items():
    for qid in qids:
        assert qid in reg.qualifications, (tid, qid)
        assert granting.get(qid), "%s requires %s which nothing can grant" % (tid, qid)
        for aid in granting[qid]:
            # the granting activity must be genuinely server-scored, not client-asserted
            assert reg.is_server_scored(aid), (qid, aid)
            spec = reg.activity(aid)
            items = svc.grade_attempt(aid, [])[0]
            assert items is not None and items["total"] > 0, "%s has no gradable content" % aid
assert granting[ZOO_Q] == ["english.prea1.taipei.zoo.quiz3"], "Zoo's granting route is unchanged"
for q, a in ((MRT_Q, "mrt"), (MKT_Q, "market"), (PARK_Q, "park")):
    assert granting[q] == ["english.prea1.taipei.%s.quiz3" % a], (q, granting[q])
ok("§34 earning paths: all 4 production qualifications are granted by real server-graded activities")

# each new activity really grades its real content
for slug in ("mrt", "market", "park"):
    aid = "english.prea1.taipei.%s.quiz3" % slug
    key = json.load(open(os.path.join(ROOT, "Pre-A1", "taipei", slug + ".json"),
                         encoding="utf-8"))["quiz3"]
    right = [{"q": i["q"], "answer": i["answer"]} for i in key]
    res, e = svc.grade_attempt(aid, right)
    assert e is None and res["passed"] is True and res["pct"] == 100, (aid, res)
    wrong = [{"q": i["q"], "answer": ("No" if i["answer"] == "Yes" else "Yes")} for i in key]
    assert svc.grade_attempt(aid, wrong)[0]["passed"] is False
    st, out = svc.record_attempt({}, aid, res, 1000)
    assert out["granted"] == ["english.prea1.taipei.%s.quiz3.pass" % slug]
    # Phase 7C.2a: these gates now pay the SAME gate reward as Zoo — the amount is whatever the
    # server injected, never a number named here — and, as always, exactly once.
    zoo_gate = svc.reward_for("english.prea1.taipei.zoo.quiz3")["amount"]
    assert out["rewarded"] is True and out["rewardAmount"] == zoo_gate > 0, (aid, out)
    _, again = svc.record_attempt(st, aid, res, 2000)
    assert again["rewarded"] is False and again["rewardAmount"] == 0, "a replayed gate pays nothing"
ok("§34 the 3 new activities grade their real lesson content, grant exactly their qualification, "
   "and pay the shared gate reward exactly once")

# ============================== §35 territory gates ==============================
STORE = {START: {"owner": "ALICE", "troops": [{"type": "cav", "hp": 100}]}}
for tid in list(CURATED) + SANDBOX:
    STORE[tid] = {"owner": "BOB", "troops": [{"type": "inf", "hp": 3}]}
SQUAD = [{"type": "cav", "hp": 10}]


def can(target, held=(), source=START):
    state = {}
    for q in held:
        state, _ = Q.grant_qualification(state, q, 1)
    return conquest.can_attack("ALICE", source, target, SQUAD, cat, STORE,
                               player_qualifications=Q.earned_qualification_ids(state))


# single-requirement gates adjacent to the start
for tid, qid in (("taipei:daan", ZOO_Q), ("taipei:xinyi", MRT_Q), ("taipei:zhongzheng", MKT_Q)):
    e = can(tid)
    assert not e and e.reason == "qualification_required" and e.missing_qualifications == [qid], (tid, e.reason)
    assert can(tid, [qid]).allowed, tid
    assert can(tid, [PARK_Q]).missing_qualifications == [qid], "an unrelated qualification does not help"
# the multi-requirement gate (reachable from daan once owned)
STORE["taipei:daan"] = {"owner": "ALICE", "troops": [{"type": "cav", "hp": 100}]}
e = can("taipei:zhongshan", source="taipei:daan")
assert e.reason == "qualification_required", e.reason
assert e.missing_qualifications == [MKT_Q, ZOO_Q], e.missing_qualifications
assert can("taipei:zhongshan", [ZOO_Q], source="taipei:daan").missing_qualifications == [MKT_Q]
assert can("taipei:zhongshan", [MKT_Q], source="taipei:daan").missing_qualifications == [ZOO_Q]
assert can("taipei:zhongshan", [MKT_Q, ZOO_Q], source="taipei:daan").allowed
STORE["taipei:daan"] = {"owner": "BOB", "troops": [{"type": "inf", "hp": 3}]}
# sandbox territories need nothing
assert can("taipei:nangang").allowed, "nangang is an open sandbox territory"
ok("§35 gates: single gates block with the exact missing id; Zhongshan needs BOTH; sandbox is open")

# curriculum order is RECOMMENDED, not enforced: MRT does not additionally require Zoo
assert cat.attack_requirements("taipei:xinyi") == [MRT_Q], "no cumulative prerequisite was added"
assert can("taipei:xinyi", [MRT_Q]).allowed, "a player may study MRT first and take Xinyi"
assert can("taipei:zhongzheng", [MKT_Q]).allowed, "…or Night Market first and take Zhongzheng"
ok("§curriculum order is recommended only — each normal gate needs its own qualification alone")

# ============================== §36 reachability (curated only) ==============================
adj = {t["id"]: list(t.get("adjacentTerritoryIds") or []) for t in TAIPEI}
owned, earned, steps = {START}, set(), []
progressed = True
while progressed:
    progressed = False
    frontier = {n for o in owned for n in adj[o] if n not in owned}
    for tid in sorted(frontier & set(CURATED)):
        earned.update(CURATED[tid])          # a player may study ahead
        owned.add(tid)
        steps.append(tid)
        progressed = True
assert set(CURATED) <= owned, "unreachable curated territories: %s" % (set(CURATED) - owned)
assert steps[0] in ("taipei:daan", "taipei:xinyi", "taipei:zhongzheng"), steps
# sandbox must NOT be what makes the curated route reachable
owned2 = {START}
progressed = True
while progressed:
    progressed = False
    for tid in sorted({n for o in owned2 for n in adj[o] if n not in owned2} & set(CURATED)):
        owned2.add(tid)
        progressed = True
assert set(CURATED) <= owned2, "curated route must be reachable without sandbox stepping stones"
# every curated territory is adjacent to the start or to another curated territory
for tid in CURATED:
    assert set(adj[tid]) & (set(CURATED) | {START}), tid
ok("§36 reachability: all 5 curated territories reachable from Wenshan without sandbox detours")

# ============================== §37 Study navigation ==============================
manifest_files = set()
for lv in json.load(open(os.path.join(ROOT, "lessons.json"), encoding="utf-8"))["levels"]:
    for a in lv.get("articles", []):
        manifest_files.add(a["file"])
ARCS = {"Pre-A1/taipei/zoo", "Pre-A1/taipei/mrt", "Pre-A1/taipei/market", "Pre-A1/taipei/park"}
pub = reg.public_view()
for qid in (ZOO_Q, MRT_Q, MKT_Q, PARK_Q):
    v = pub["qualifications"][qid]
    assert v["title"] and v["title"] != qid, qid
    assert "Taipei" in v["title"], v["title"]
    tgt = v["studyTarget"]
    assert tgt and tgt["contentPath"] in ARCS, (qid, tgt)
    assert os.path.isfile(os.path.join(ROOT, tgt["contentPath"] + ".json")), tgt
blob = json.dumps(pub)
for leak in ("answer", "rewardPolicy", "graderType", "graderConfig", "10000", "PASS_GOLD"):
    assert leak not in blob, "public registry leaks " + leak
ok("§37 Study navigation: every gate resolves a readable title + an existing lesson; no leakage")

# ============================== §38 Zoo/Daan backward compatibility ==============================
assert cat.attack_requirements("taipei:daan") == [ZOO_Q], "Daan's original gate is untouched"
assert reg.qualifications[ZOO_Q]["scope"] == "activity"
legacy = {"qualifications": {ZOO_Q: {"earnedAt": 1}}}
assert conquest.can_attack("ALICE", START, "taipei:daan", SQUAD, cat, STORE,
                           player_qualifications=Q.earned_qualification_ids(legacy)).allowed, \
    "an existing learner keeps the access they already earned"
# Phase 4B retired Zoo's v1 completionPolicy (legacy Rule A also scores level 10 Role-play, so a
# 6-activity policy did not reproduce it). That is a LEARNING-side change only: territory access has
# never depended on lesson completion, so Daan's gate and existing learner access are unaffected.
assert reg.completion_available("english.prea1.taipei.zoo") is True, "Zoo now carries v2"
assert reg.completion_policy_of("english.prea1.taipei.zoo")["version"] == 2
assert reg.retired_policy_versions("english.prea1.taipei.zoo") == [1], "v1 stays retired"
CX.assert_completion_model(reg)
assert set(CX.TAIPEI4) <= set(l for l in reg.lessons if reg.completion_available(l))
# Conquest has never depended on lesson completion, and Phase 4D did not change that: Daan's gate is
# still the Zoo quiz3 qualification, so activating v2 cannot harden any territory.
assert cat.attack_requirements("taipei:daan") == [ZOO_Q]
ok("§38 backward compatibility: Daan/Zoo gate unchanged and old progress still unlocks, even with "
   "four v2 lesson policies now active — conquest never depended on lesson completion")

# ============================== §39 reward neutrality ==============================
GATES = sorted("english.prea1.taipei.%s.quiz3" % s
               for s in ("zoo", "mrt", "market", "park"))
paying = sorted(a for a in reg.activities if reg.reward_policy_of(a) != "none")
assert paying == CX.declared_gates(reg), paying
# Phase 7C.2a: the three gates added in this content phase now pay the SAME gate reward as
# Zoo, through the same policy and the same injected amount. Nothing here names a number.
for aid in GATES:
    assert reg.reward_policy_of(aid) == "standard_activity_pass", aid
    assert svc.reward_for(aid)["amount"] == svc.reward_for(GATES[0])["amount"] > 0, aid
# Phase 5F: lessons now carry a cosmetic badge. Reward NEUTRALITY is about gold, so the check is
# that no lesson reward is economic — not that no lesson reward exists.
# A campaign still moves no gold at all. A lesson may carry AT MOST ONE economic policy (7C.2).
for l in reg.lessons:
    assert len([p for p in reg.lesson_reward_policies_of(l) if W.is_economic(p)]) <= 1, l
assert [c for c in reg.courses if W.is_economic(reg.course_reward_policy_of(c))] == []
ok("§39 reward shape: the 4 quiz3 gates share one gate policy, each lesson carries at most "
   "one economic mastery reward, and campaign completion still moves no gold")

# ============================== §40 world invariants ==============================
assert len(TAIPEI) == 12
for t in TAIPEI:
    src = BY_ID[t["id"]]
    assert src.get("gamePopulation") is not None, t["id"]
    assert set(t.get("adjacentTerritoryIds") or []) == set(adj[t["id"]])
    for nb in adj[t["id"]]:
        assert t["id"] in adj[nb], "adjacency must stay symmetric: %s/%s" % (t["id"], nb)
    allowed = {"attackQualificationIds"}
    assert set(t.get("requirements") or {}) <= allowed, t["id"]
assert cat.count_per_map()["taipei"] == 12
pops = {t["id"]: t["gamePopulation"] for t in TAIPEI}
assert pops["taipei:daan"] and pops["taipei:wenshan"], "populations present and untouched"
ok("§40 world invariants: 12 canonical ids, symmetric adjacency, populations intact, only "
   "requirements added")

print("\nAll %d Taipei progression tests passed." % passed)
