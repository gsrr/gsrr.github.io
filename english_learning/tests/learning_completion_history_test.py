#!/usr/bin/env python3
"""Phase 4D — versioned lesson-completion history (Option A) and the v2 policy activation.

    python3 tests/learning_completion_history_test.py

Covers the eight approved persistence cases, the additive API clarity fields, exact Rule A goldens
under v2, retired-version enforcement, and reward/qualification/passcnt/territory neutrality.

Two stores, deliberately:
  lessonCompletions[lessonId]       = {completedAt, policyVersion}     LEGACY first-ever, untouched
  lessonCompletionHistory[lessonId] = [{policyVersion, completedAt}]   NEW, append-only per version
The legacy record is merged into the history VIRTUALLY at read time, so a pre-Phase-4D file is never
rewritten.
"""
import copy
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request as U

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))   # Phase 9B.1: shared registry-derived expectations
import curriculum_expectations as CX  # noqa: E402
from game import conquest  # noqa: E402
from learning import api as L, completion as C, registry as R, rewards as W  # noqa: E402
import territory_catalog  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


reg = R.REGISTRY
svc = L.LearningService(content_root=ROOT, reward_amounts={"PASS_GOLD": 10000})
SLUGS = ["zoo", "mrt", "market", "park"]
LIDS = {s: "english.prea1.taipei.%s" % s for s in SLUGS}
SUFFIX = ["read_along", "quiz3", "quiz4", "matching", "wh", "cloze", "roleplay"]
ZOO = LIDS["zoo"]


def scores_state(lid, pcts):
    """Authoritative evidence written where each real resolver reads it (one pct per level)."""
    st = {"activityScores": {}, "sttProgress": {}, "matchingProgress": {}, "roleplayProgress": {}}
    for suffix, pct in zip(SUFFIX, pcts):
        aid = "%s.%s" % (lid, suffix)
        if pct is None:
            continue
        if suffix == "read_along":
            st["sttProgress"][aid] = {"pct": pct}
        elif suffix == "matching":
            st["matchingProgress"][aid] = {"correct": pct, "total": 100, "pct": pct}
        elif suffix == "roleplay":
            st["roleplayProgress"][aid] = {"passes": pct, "turns": 100, "pct": pct}
        else:
            st["activityScores"][aid] = {"correct": pct, "total": 100, "pct": pct}
    return st


FULL = [90] * 7

# ====================== the four v2 policies are active and correctly shaped ======================
active = sorted(l for l in reg.lessons if reg.completion_available(l))
# Phase 9B.1: assert the POLICY SHAPE of every completable lesson instead of naming the set.
CX.assert_completion_model(reg)
assert set(LIDS.values()) <= set(active), active
for slug, lid in LIDS.items():
    pol = reg.completion_policy_of(lid)
    assert pol["type"] == "average_required_activities", lid
    assert pol["version"] == 2, (lid, pol["version"])
    assert pol["passMark"] == C.PASS_MARK == 80, lid
    assert pol["requiredActivityIds"] == ["%s.%s" % (lid, s) for s in SUFFIX], lid
    assert len(pol["requiredActivityIds"]) == 7, lid
    # §15: Phase 5F attached a COSMETIC badge here. What must stay true is that no lesson reward
    # moves the economy — the policy name alone was only ever a proxy for that.
    assert reg.lesson_reward_policy_of(lid) == "lesson_mastery_badge", lid
    assert not W.is_economic(reg.lesson_reward_policy_of(lid)), lid
    assert reg.lesson_qualification_ids_for(lid) == [], lid         # §16
    for aid in pol["requiredActivityIds"]:
        assert aid in reg.activities and reg.is_server_scored(aid), aid
        assert reg.lesson_of_activity(aid) == lid, aid
assert reg.retired_policy_versions(ZOO) == [1], "Zoo v1 stays retired"
ok("§14 exactly 4 active production policies, all average_required_activities v2 / passMark 80 / "
   "7 required activities / reward none / grants []; Zoo v1 remains retired")

# ====================== 1. fresh learner completes v2 ======================
st = scores_state(ZOO, FULL)
out = {}
svc._settle_lesson(st, ZOO, 1000, out)
assert out["currentPolicySatisfied"] is True and out["lessonCompletedNow"] is True, out
assert st["lessonCompletions"][ZOO] == {"completedAt": 1000, "policyVersion": 2}, st["lessonCompletions"]
assert st[C.HISTORY_KEY][ZOO] == [{"policyVersion": 2, "completedAt": 1000}], st[C.HISTORY_KEY]
assert C.merged_history(st, ZOO) == [{"policyVersion": 2, "completedAt": 1000}]
assert out["activePolicyVersion"] == 2 and out["activePolicyCompleted"] is True
assert out["activePolicyCompletedAt"] == 1000
assert out["firstCompletedAt"] == 1000 and out["firstCompletedPolicyVersion"] == 2
ok("case 1 fresh learner: legacy record created as v2, history holds v2 exactly once, and every "
   "active/first field agrees")

# ====================== 2. an existing v1 learner completes v2 ======================
V1 = {"completedAt": 1753900000, "policyVersion": 1}
st = scores_state(ZOO, FULL)
st["lessonCompletions"] = {ZOO: dict(V1)}
legacy_before = json.dumps(st["lessonCompletions"], sort_keys=True)
out = {}
svc._settle_lesson(st, ZOO, 1800000000, out)
assert json.dumps(st["lessonCompletions"], sort_keys=True) == legacy_before, \
    "the v1 legacy record must survive byte-for-byte"
assert st[C.HISTORY_KEY][ZOO] == [{"policyVersion": 2, "completedAt": 1800000000}], st[C.HISTORY_KEY]
assert C.merged_history(st, ZOO) == [{"policyVersion": 1, "completedAt": 1753900000},
                                     {"policyVersion": 2, "completedAt": 1800000000}]
assert out["lessonCompletedNow"] is True, "v2 is newly recorded even though v1 already existed"
assert out["activePolicyCompleted"] is True and out["activePolicyCompletedAt"] == 1800000000
assert out["firstCompletedPolicyVersion"] == 1, "the first-ever version stays 1"
assert out["firstCompletedAt"] == 1753900000
assert out["lessonRewardAmount"] == 0 and out["lessonGrantedNow"] == [], out
ok("case 2 v1 holder completes v2: v1 preserved byte-for-byte, v2 appended, activePolicyCompletedAt "
   "is the v2 timestamp, firstCompletedPolicyVersion stays 1, and nothing is paid or granted")

# ====================== 3. v1 holder SATISFIES v2 but has not settled yet ======================
st = scores_state(ZOO, FULL)
st["lessonCompletions"] = {ZOO: dict(V1)}
status = svc.lesson_status(ZOO, st)
assert status["currentPolicySatisfied"] is True, status
assert status["historicallyCompleted"] is True, status
assert status["activePolicyCompleted"] is False, "no v2 entry has been persisted yet"
assert status["activePolicyCompletedAt"] is None and status["activePolicyVersion"] == 2
assert status["firstCompletedPolicyVersion"] == 1
assert status["completionHistory"] == [{"policyVersion": 1, "completedAt": 1753900000}]
ok("case 3 satisfied-but-not-yet-materialised: currentPolicySatisfied true, historicallyCompleted "
   "true, activePolicyCompleted correctly FALSE until a normal settlement writes v2")

# ====================== 4. repeated v2 settlement is idempotent ======================
st = scores_state(ZOO, FULL)
svc._settle_lesson(st, ZOO, 5000, {})
snapshot = copy.deepcopy({"l": st["lessonCompletions"], "h": st[C.HISTORY_KEY]})
for later in (6000, 7000, 8000):
    out = {}
    svc._settle_lesson(st, ZOO, later, out)
    assert out["lessonCompletedNow"] is False, later
    assert out["currentPolicySatisfied"] is True and out["activePolicyCompletedAt"] == 5000
assert {"l": st["lessonCompletions"], "h": st[C.HISTORY_KEY]} == snapshot, "no duplicate, no re-date"
assert len(st[C.HISTORY_KEY][ZOO]) == 1
ok("case 4 repeated settlement: no duplicate entry, completedAt unchanged, lessonCompletedNow False")

# ====================== 5. a future synthetic v3 appends independently ======================
st3 = copy.deepcopy(st)
st3["lessonCompletions"] = {ZOO: dict(V1)}
st3[C.HISTORY_KEY] = {ZOO: [{"policyVersion": 2, "completedAt": 5000}]}
st3, newly = C.record_lesson_completion(st3, ZOO, 9000, 3)
assert newly is True
assert C.merged_history(st3, ZOO) == [{"policyVersion": 1, "completedAt": 1753900000},
                                      {"policyVersion": 2, "completedAt": 5000},
                                      {"policyVersion": 3, "completedAt": 9000}]
assert st3["lessonCompletions"][ZOO] == V1, "v3 does not disturb the first-ever record either"
st3, newly = C.record_lesson_completion(st3, ZOO, 9999, 3)
assert newly is False and C.completion_for_version(st3, ZOO, 3) == 9000
ok("case 5 extensibility: a v3 completion appends beside v1 and v2, leaves both untouched, and is "
   "itself idempotent")

# ====================== 6. malformed / duplicate history is normalised safely ======================
JUNK = {"lessonCompletions": {ZOO: {"completedAt": "nope", "policyVersion": 1}},
        C.HISTORY_KEY: {ZOO: ["x", 5, None, {}, {"policyVersion": 0, "completedAt": 1},
                              {"policyVersion": -2, "completedAt": 1},
                              {"policyVersion": True, "completedAt": 1},
                              {"policyVersion": 2, "completedAt": None},
                              {"policyVersion": 2, "completedAt": 700},
                              {"policyVersion": 2, "completedAt": 900}]}}
assert C.merged_history(JUNK, ZOO) == [{"policyVersion": 2, "completedAt": 700}], \
    C.merged_history(JUNK, ZOO)
assert C.completion_for_version(JUNK, ZOO, 1) is None, "a malformed legacy record proves nothing"
# a corrupt table of ANY shape must read as "no completions", never raise
for junk in ("x", 5, None, [], {ZOO: "x"}, {ZOO: 5}, {ZOO: None}):
    assert C.merged_history({C.HISTORY_KEY: junk}, ZOO) == [], junk
    assert C.merged_history({"lessonCompletions": junk}, ZOO) == [], junk
    assert isinstance(C.completed_lesson_ids({"lessonCompletions": junk, C.HISTORY_KEY: junk}), set)
st6 = copy.deepcopy(JUNK)
out = {}
svc._settle_lesson(st6, ZOO, 1234, out)
assert out["lessonCompletedNow"] is False, "no evidence -> no completion, however odd the history"
assert out["lessonRewardAmount"] == 0 and out["lessonGrantedNow"] == []
ok("case 6 malformed history: bad entries dropped, duplicate versions collapse to the EARLIEST "
   "timestamp, a malformed legacy record grants nothing, and no reward is duplicated")

# ====================== 7. old-reader compatibility ======================
st = scores_state(ZOO, FULL)
st["lessonCompletions"] = {ZOO: dict(V1)}
svc._settle_lesson(st, ZOO, 1800000000, {})
row = svc.progress_view(st)["lessons"][ZOO]
# the deprecated trio keeps its exact historical meaning
assert row["completed"] is True, row
assert row["completedAt"] == V1["completedAt"], "completedAt is still the FIRST-EVER completion"
assert row["policyVersion"] == 1, "policyVersion is still the first-ever version"
# and the new fields say what is actually true now
assert row["currentPolicySatisfied"] is True and row["activePolicyVersion"] == 2
assert row["activePolicyCompleted"] is True and row["activePolicyCompletedAt"] == 1800000000
assert row["firstCompletedPolicyVersion"] == 1
assert svc.state_view(st)["lessonCompletionHistory"][ZOO] == [
    {"policyVersion": 2, "completedAt": 1800000000}]
blob = json.dumps(svc.progress_view(st))
for leak in ("answer", "graderType", "graderConfig", "rewardPolicy", "scenarioPath", "keywords",
             "next_nodes", "roundId", "sessionId", "PASS_GOLD", "10000"):
    assert leak not in blob, "progress view leaks %s" % leak
ok("§19/§20 old readers unaffected: completed/completedAt/policyVersion keep first-ever semantics "
   "while the new active-policy fields carry the truth; no internals leak")

# ====================== 8. neutrality: reward, qualification, passcnt, gates ======================
# Phase 7C.2a: all FOUR gate activities are gold-bearing. Identity, not merely count.
GATES = sorted("english.prea1.taipei.%s.quiz3" % s
               for s in ("zoo", "mrt", "market", "park"))
gold_bearing = sorted(a for a in reg.activities if svc.reward_for(a)["amount"] > 0)
assert gold_bearing == CX.declared_gates(reg), gold_bearing
assert svc.reward_for("english.prea1.taipei.zoo.quiz3")["amount"] == 10000
st = {}
for slug, lid in LIDS.items():
    # merge per store — a plain dict.update() would REPLACE each sub-table and keep only one lesson
    for store, rows in scores_state(lid, FULL).items():
        st.setdefault(store, {}).update(rows)
for slug, lid in LIDS.items():
    out = {}
    svc._settle_lesson(st, lid, 4242, out)
    assert out["lessonCompletedNow"] is True and out["lessonRewardAmount"] == 0, (lid, out)
    assert out["lessonQualifications"] == [] and out["lessonGrantedNow"] == [], (lid, out)
assert (st.get("qualifications") or {}) == {}, "no qualification from any lesson completion"
assert sorted(reg.qualifications) == [
    "english.prea1.taipei.market.quiz3.pass", "english.prea1.taipei.mrt.quiz3.pass",
    "english.prea1.taipei.park.quiz3.pass", "english.prea1.taipei.zoo"], sorted(reg.qualifications)
assert "passcnt" not in json.dumps(st), "lesson completion never touches passcnt"
assert len(C.completed_lesson_ids(st)) == 4
# territory gates are untouched and still quiz3-based
cat = territory_catalog.catalog
EXPECTED_GATES = {"taipei:daan": ["english.prea1.taipei.zoo"],
                  "taipei:xinyi": ["english.prea1.taipei.mrt.quiz3.pass"],
                  "taipei:zhongzheng": ["english.prea1.taipei.market.quiz3.pass"],
                  "taipei:songshan": ["english.prea1.taipei.park.quiz3.pass"],
                  "taipei:zhongshan": ["english.prea1.taipei.market.quiz3.pass",
                                       "english.prea1.taipei.zoo"]}
for tid, qids in EXPECTED_GATES.items():
    assert cat.attack_requirements(tid) == qids, (tid, cat.attack_requirements(tid))
# a learner who completed all four lessons but earned no quiz3 qualification still cannot attack
STORE = {"taipei:wenshan": {"owner": "ALICE", "troops": [{"type": "cav", "hp": 100}]},
         "taipei:xinyi": {"owner": "BOB", "troops": [{"type": "inf", "hp": 3}]}}
# RETARGETED (Phase 10A.3R): the old form proved whole-lesson completion was NOT an attack
# requirement while quiz3 qualifications WERE. The second half is retired — nothing learning-side is
# an attack requirement now — so this asserts the general rule instead: no learning state, whether
# completion history or a held qualification, changes the Conquest verdict.
e_none = conquest.can_attack("ALICE", "taipei:wenshan", "taipei:xinyi", [{"type": "cav", "hp": 10}],
                             cat, STORE, player_qualifications=[])
e_full = conquest.can_attack("ALICE", "taipei:wenshan", "taipei:xinyi", [{"type": "cav", "hp": 10}],
                             cat, STORE,
                             player_qualifications=["english.prea1.taipei.mrt.quiz3.pass"])
assert (e_none.allowed, e_none.reason) == (e_full.allowed, e_full.reason), (e_none, e_full)
ok("§15/§16/§17/§18 four lesson completions pay 0 gold, grant 0 qualifications and never write "
   "passcnt; and neither completion history nor a held qualification changes the attack verdict")

# ====================== §25 exact Rule A goldens under v2, per lesson ======================
CASES = [
    ("all seven exactly 80", [80] * 7, True, 80),
    ("one level below 80, mean >= 80", [100, 100, 100, 100, 100, 100, 60], True, 94),
    ("level 10 = 0 but mean >= 80", [100, 100, 100, 100, 100, 100, 0], True, 86),
    ("level 10 = 0 and others only 80", [80] * 6 + [0], False, 69),
    ("mean 79.43 -> rounds to 79", [80] * 6 + [76], False, 79),
]
for slug, lid in LIDS.items():
    for name, pcts, want, rounded in CASES:
        ev = svc.evaluate_lesson(lid, scores_state(lid, pcts))
        assert ev["completed"] is want and ev["roundedPct"] == rounded, (slug, name, ev["roundedPct"])
    # a MISSING level blocks it, whatever the others are — level 10 included
    for idx, suffix in enumerate(SUFFIX):
        pcts = [100] * 7
        pcts[idx] = None
        ev = svc.evaluate_lesson(lid, scores_state(lid, pcts))
        assert ev["completed"] is False and ev["meanPct"] is None, (slug, suffix)
        assert ev["missingActivityIds"] == ["%s.%s" % (lid, suffix)], (slug, suffix)
ok("§25 exact Rule A on all four real lessons: 80-flat / sub-80 level with passing mean / level 10 "
   "at ZERO still passing at 86 / 79.43 rounding down / every single missing level blocking")

# ====================== §26 monotonic history vs falling satisfaction ======================
for slug, lid in LIDS.items():
    st = scores_state(lid, [80] * 7)
    out = {}
    svc._settle_lesson(st, lid, 1000, out)
    assert out["lessonCompletedNow"] is True
    # a worse retry on one level drops the mean below 80
    st["activityScores"]["%s.wh" % lid] = {"correct": 0, "total": 100, "pct": 0}
    out2 = {}
    svc._settle_lesson(st, lid, 2000, out2)
    assert out2["currentPolicySatisfied"] is False, (lid, out2["roundedPct"])
    assert out2["historicallyCompleted"] is True and out2["activePolicyCompleted"] is True
    assert out2["activePolicyCompletedAt"] == 1000, "never re-dated"
    assert C.merged_history(st, lid) == [{"policyVersion": 2, "completedAt": 1000}]
ok("§9/§26 monotonic model intact on all four lessons: a worse retry flips currentPolicySatisfied to "
   "false while the v2 history entry survives, un-redated")

# ====================== §27 retired v1 cannot come back ======================
reuse = copy.deepcopy(R.DATA)
reuse["lessons"][ZOO]["completionPolicy"]["version"] = 1
assert any("reuses retired policy version" in e for e in R.validate(reuse)), R.validate(reuse)
assert R.validate(R.DATA) == [], R.validate(R.DATA)
# a v1 record alone never implies current v2 satisfaction
only_v1 = {"lessonCompletions": {ZOO: dict(V1)}}
s1 = svc.lesson_status(ZOO, only_v1)
assert s1["historicallyCompleted"] is True and s1["currentPolicySatisfied"] is False, s1
assert s1["activePolicyCompleted"] is False, s1
assert svc.evaluate_lesson(ZOO, only_v1)["missingActivityIds"] == \
    ["%s.%s" % (ZOO, s) for s in SUFFIX], "v1 history grants no evidence for v2"
ok("§27 Zoo v1 cannot be reactivated (validator rejects), and a v1 record alone implies neither "
   "current v2 satisfaction nor any v2 evidence")

# ============================== HTTP: forgery and the real trust boundary ==============================
import tempfile  # noqa: E402
import server  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

d = tempfile.mkdtemp()
server.ROOMS_DIR = os.path.join(d, "rooms")
server.ACCT = os.path.join(d, "accounts.json")
server.PROG_DIR = os.path.join(d, "progress")
server.DATA = os.path.join(d, "visits.json")
server.TERR_CATALOG = os.path.join(d, "learned.json")
server.LEARNING.content_root = ROOT
json.dump({"users": {"ALICE": {"code": "P4D"}}, "codes": {"P4D": "ALICE"}}, open(server.ACCT, "w"))
server._tokens["tA"] = {"user": "ALICE", "exp": time.time() + 9999, "admin": False}
srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % PORT


def call(method, path, body=None, tok="tA"):
    url = B + path + ("&" if "?" in path else "?") + "token=" + tok
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = U.urlopen(U.Request(url, data=data, method=method))
        return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


call("POST", "/api/room/create", {})
CODE = call("POST", "/api/room/start", {"map": "Pre-A1", "aiCount": 0, "resources": "medium",
                                        "capacity": 4})[1]["code"]
ZOOJ = json.load(open(os.path.join(ROOT, "Pre-A1", "taipei", "zoo.json"), encoding="utf-8"))


def gold():
    server.set_room(CODE)
    return (server.load_econ_store().get("ALICE") or {}).get("gold", 0)


def passcnt():
    server.set_room(CODE)
    return dict((server.load_econ_store().get("ALICE") or {}).get("passcnt") or {})


g0, pc0 = gold(), passcnt()
FORGED = {"activityId": "%s.wh" % ZOO,
          "answers": [{"q": i["q"], "answer": i["a"]} for i in ZOOJ["wh"]],
          "currentPolicySatisfied": True, "historicallyCompleted": True,
          "activePolicyVersion": 99, "activePolicyCompleted": True,
          "activePolicyCompletedAt": 1, "firstCompletedAt": 1,
          "firstCompletedPolicyVersion": 9, "policyVersion": 99, "roundedPct": 100,
          "meanPct": 100, "requiredActivityIds": [], "lessonCompletedNow": True,
          "completedAt": 1, "rewardAmount": 10000,
          "qualifications": ["english.prea1.taipei.zoo"],
          "lessonCompletionHistory": {ZOO: [{"policyVersion": 2, "completedAt": 1}]}}
code, r = call("POST", "/api/learning/attempt?room=" + CODE, FORGED)
assert code == 200 and r["passed"] is True and r["pct"] == 100, r
# only wh is scored, so the lesson is NOT satisfied and nothing forged survived
assert r["currentPolicySatisfied"] is False, r
assert r["activePolicyVersion"] == 2, r["activePolicyVersion"]
assert r["activePolicyCompleted"] is False and r["activePolicyCompletedAt"] is None, r
assert r["historicallyCompleted"] is False and r["lessonCompletedNow"] is False, r
assert r["firstCompletedAt"] is None and r["firstCompletedPolicyVersion"] is None, r
assert len(r["missingActivityIds"]) == 6, r["missingActivityIds"]
assert r["rewarded"] is False, r
st = call("GET", "/api/learning/state?room=" + CODE)[1]
assert st["lessonCompletions"] == {} and st["lessonCompletionHistory"] == {}, st
assert gold() == g0 and passcnt() == pc0
ok("§22 HTTP: forged currentPolicySatisfied / historicallyCompleted / activePolicyVersion / "
   "activePolicyCompletedAt / firstCompleted* / policyVersion / roundedPct / requiredActivityIds / "
   "lessonCompletionHistory / reward / qualification are ALL ignored and derived server-side")

srv.shutdown()
print()
print("All %d completion-history tests passed." % passed)
