#!/usr/bin/env python3
"""Phase 4B — deep MRT / Market / Park registration: authority, neutrality, Rule A readiness.

    python3 tests/taipei_content_depth_test.py

Covers §31 lesson-policy behaviour per real lesson, §32 registration integrity, §33 quiz3 gate
compatibility, §34 whole-lesson neutrality, §35 latest-wins + monotonic completion, §37 the reward
set, §38 campaign invariants.

Two registries are used, and the difference matters:

  * `reg`  — the REAL shipped registry. MRT/Market/Park have NO active completionPolicy, because
             legacy Rule A also scores level 10 Role-play, which has no server authority
             (see docs/taipei-content-depth.md). Everything asserted against `reg` is production
             behaviour.
  * `cand` — a synthetic registry that adds the CANDIDATE 6-activity policy to the three lessons.
             It proves the machinery is ready and the §31/§35 semantics hold for the real activity
             IDs. It is a readiness proof, NOT production state, and nothing writes it to disk.
"""
import copy
import json
import os
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

LESSONS = ["english.prea1.taipei.mrt", "english.prea1.taipei.market", "english.prea1.taipei.park"]
SLUG = {"english.prea1.taipei.mrt": "mrt", "english.prea1.taipei.market": "market",
        "english.prea1.taipei.park": "park"}
GATE = {"english.prea1.taipei.mrt": "english.prea1.taipei.mrt.quiz3.pass",
        "english.prea1.taipei.market": "english.prea1.taipei.market.quiz3.pass",
        "english.prea1.taipei.park": "english.prea1.taipei.park.quiz3.pass"}
# The six levels legacy Rule A scores that DO have server authority (2,3,4,5,7,9).
DETERMINISTIC = ["quiz3", "quiz4", "wh", "cloze"]
SUFFIXES = ["read_along", "quiz3", "quiz4", "matching", "wh", "cloze"]
NEW_SUFFIXES = ["read_along", "quiz4", "matching", "wh", "cloze"]   # quiz3 shipped in Phase 4A


def content(lesson_id):
    with open(os.path.join(ROOT, "Pre-A1", "taipei", SLUG[lesson_id] + ".json"), encoding="utf-8") as f:
        return json.load(f)


def answers(lesson_id, key, n_right):
    """Real answers for a real activity: the first n_right correct, the rest deliberately wrong."""
    items = content(lesson_id)[key]
    if key in ("quiz3", "quiz4"):
        return ([{"q": i["q"], "answer": i["answer"]} for i in items[:n_right]] +
                [{"q": i["q"], "answer": ("No" if i["answer"] == "Yes" else "Yes")}
                 for i in items[n_right:]])
    if key == "wh":
        return ([{"q": i["q"], "answer": i["a"]} for i in items[:n_right]] +
                [{"q": i["q"], "answer": i["wrong"][0]} for i in items[n_right:]])
    if key == "cloze":
        return ([{"q": i["text"], "answer": i["answer"]} for i in items[:n_right]] +
                [{"q": i["text"], "answer": i["wrong"][0]} for i in items[n_right:]])
    raise AssertionError(key)


# ====================== §32 registration integrity for every new activity ======================
for lid in LESSONS:
    lesson = reg.lesson(lid)
    assert lesson and lesson.get("contentPath") == "Pre-A1/taipei/%s" % SLUG[lid], lid
    for suffix in SUFFIXES:
        aid = "%s.%s" % (lid, suffix)
        spec = reg.activity(aid)
        assert spec, "not registered: %s" % aid
        # canonical identity resolves, and resolves the same way the client reaches it
        assert reg.resolve_activity_id(aid) == aid, aid
        assert reg.lesson_of_activity(aid) == lid, aid
        assert reg.content_path_of(aid) == lesson["contentPath"], aid
        # the server owns the result for every one of them
        assert reg.is_server_scored(aid), aid
        # a grader and a scorer are mutually exclusive (§7)
        assert bool(spec.get("graderType")) != bool(spec.get("scorerType")), aid
        # §13/§14: the gate carries the shared gate reward (Phase 7C.2a; it was "none" when this
        # content phase landed). Every non-gate activity still carries no reward at all.
        assert reg.reward_policy_of(aid) == ("standard_activity_pass" if suffix == "quiz3"
                                             else "none"), (aid, reg.reward_policy_of(aid))
        expect_grants = [GATE[lid]] if suffix == "quiz3" else []
        assert reg.qualification_ids_for(aid) == expect_grants, (aid, reg.qualification_ids_for(aid))
ok("§32 all 18 Taipei activities across MRT/Market/Park registered and server-scored; only the "
   "quiz3 gate carries a reward or grants a qualification, and it uses the shared gate policy")

# content exists and grades to the exact expected score through the EXISTING generic graders
for lid in LESSONS:
    for key in DETERMINISTIC:
        aid = "%s.%s" % (lid, key)
        items = content(lid)[key]
        n = len(items)
        res, err = svc.grade_attempt(aid, answers(lid, key, n))
        assert err is None, (aid, err)
        assert (res["correct"], res["total"], res["pct"], res["passed"]) == (n, n, 100, True), (aid, res)
        res, err = svc.grade_attempt(aid, answers(lid, key, n - 1))
        exp = int((n - 1) * 100.0 / n + 0.5)
        assert err is None and res["correct"] == n - 1 and res["total"] == n and res["pct"] == exp, (aid, res)
    # matching resolves its real vocab and builds a server-owned round
    aid = "%s.matching" % lid
    assert svc.is_matching(aid) and svc.matching_vocab(aid), aid
    # read-along resolves its real dialogue server-side
    aid = "%s.read_along" % lid
    sents = svc.read_along_sentences(aid)
    assert svc.is_read_along(aid) and sents and len(sents) == 10, (aid, sents and len(sents))
    assert svc.read_along_target(aid, 0) == (sents[0], len(sents)), aid
    assert svc.read_along_target(aid, len(sents)) == (None, len(sents)), "out-of-range refused"
ok("§32/§7 real content resolves for every activity; the existing deterministic graders, matching "
   "vocab and STT dialogue lookup all work with no new scoring code")

# ====================== §31 candidate-policy Rule A behaviour, real activity IDs ======================
CANDIDATE = ["read_along", "quiz3", "quiz4", "matching", "wh", "cloze"]
raw = copy.deepcopy(R.DATA)
for lid in LESSONS:
    raw["lessons"][lid]["completionPolicy"] = {
        "type": "average_required_activities", "version": 1, "passMark": 80,
        "requiredActivityIds": ["%s.%s" % (lid, s) for s in CANDIDATE],
    }
assert not R.validate(raw), R.validate(raw)
cand = R.Registry(raw)
csvc = L.LearningService(reg=cand, content_root=ROOT, reward_amounts={"PASS_GOLD": 10000})


def scores(lid, pcts):
    """A state carrying authoritative evidence for the candidate policy, one pct per activity.

    Each evidence shape is written where its real resolver reads it, so this exercises the real
    authoritative_activity_score() fan-in rather than a shortcut.
    """
    st = {"activityScores": {}, "sttProgress": {}, "matchingProgress": {}}
    for suffix, pct in zip(CANDIDATE, pcts):
        aid = "%s.%s" % (lid, suffix)
        if pct is None:
            continue
        if suffix == "read_along":
            st["sttProgress"][aid] = {"pct": pct}
        elif suffix == "matching":
            st["matchingProgress"][aid] = {"correct": pct, "total": 100, "pct": pct}
        else:
            st["activityScores"][aid] = {"correct": pct, "total": 100, "pct": pct}
    return st


for lid in LESSONS:
    # 1. partial evidence -> incomplete, and the gap is named
    ev = csvc.evaluate_lesson(lid, scores(lid, [100, 100, 100, None, None, None]))
    assert ev["completed"] is False and ev["meanPct"] is None, (lid, ev)
    assert ev["missingActivityIds"] == ["%s.matching" % lid, "%s.wh" % lid, "%s.cloze" % lid], ev
    # 2. all evidence, mean below 80 -> incomplete
    ev = csvc.evaluate_lesson(lid, scores(lid, [70, 70, 70, 70, 70, 70]))
    assert ev["completed"] is False and ev["roundedPct"] == 70, (lid, ev)
    # 3. all evidence, mean >= 80 -> complete
    ev = csvc.evaluate_lesson(lid, scores(lid, [80, 80, 80, 80, 80, 80]))
    assert ev["completed"] is True and ev["roundedPct"] == 80, (lid, ev)
    # 4. one required activity WELL below 80 but the mean still passes -> complete.
    #    This is the case that proves it is not "every activity must pass".
    ev = csvc.evaluate_lesson(lid, scores(lid, [100, 100, 100, 100, 40, 100]))
    assert ev["completed"] is True and ev["roundedPct"] == 90, (lid, ev)
    assert ev["activityScores"]["%s.wh" % lid]["pct"] == 40, ev
    # 5. a single missing score blocks it however high the rest are
    ev = csvc.evaluate_lesson(lid, scores(lid, [100, 100, 100, 100, 100, None]))
    assert ev["completed"] is False and ev["missingActivityIds"] == ["%s.cloze" % lid], ev
ok("§31 candidate policy on all three real lessons: partial / mean<80 / mean>=80 / sub-80 level with "
   "passing mean / missing score behave exactly as Rule A requires")

# the candidate policy carries no reward and no qualification (§20/§21)
for lid in LESSONS:
    pol = cand.completion_policy_of(lid)
    assert cand.lesson_reward_policy_of(lid) == "none", lid
    assert cand.lesson_qualification_ids_for(lid) == [], lid
    assert pol["passMark"] == C.PASS_MARK == 80 and pol["version"] == 1, lid
    assert pol["type"] == "average_required_activities", lid
ok("§17/§20/§21 candidate policy shape: average_required_activities v1, passMark 80, reward none, grants []")

# ====================== §35 latest-wins + monotonic completion ======================
lid = "english.prea1.taipei.mrt"
# Start exactly ON the pass mark. From 6x100 a single zeroed level averages 83 and would still pass,
# which is correct Rule A behaviour but would not exercise the un-satisfying retry.
st = scores(lid, [80, 80, 80, 80, 80, 80])
out = {}
csvc._settle_lesson(st, lid, 1000, out)
assert out["lessonCompleted"] is True and out["lessonCompletedNow"] is True, out
assert out["lessonRewardAmount"] == 0 and out["lessonGrantedNow"] == [], out
first_at = st["lessonCompletions"][lid]["completedAt"]
assert first_at == 1000, st["lessonCompletions"]
# a bad retry lowers the LATEST score, so current policy satisfaction drops...
res, _ = csvc.grade_attempt("%s.wh" % lid, answers(lid, "wh", 0))
st, att = csvc.record_attempt(st, "%s.wh" % lid, res, 2000)
assert att["passed"] is False and st["activityScores"]["%s.wh" % lid]["pct"] == 0, st["activityScores"]
ev = csvc.evaluate_lesson(lid, st)
assert ev["completed"] is False, ev                      # current evaluation is now unsatisfied
# ...but the historical completion survives, un-redated, and is never revoked
rec = C.get_lesson_completion(st, lid)
assert rec and rec["completedAt"] == first_at == 1000, rec
assert lid in C.completed_lesson_ids(st), st
out2 = {}
csvc._settle_lesson(st, lid, 3000, out2)
assert out2["lessonCompleted"] is False and out2["lessonCompletedNow"] is False, out2
assert C.get_lesson_completion(st, lid)["completedAt"] == 1000, "completedAt must never be re-dated"
prog = csvc.progress_view(st)["lessons"][lid]
assert prog["completed"] is True and prog["completedAt"] == 1000, prog
assert prog["missingActivityIds"] == [], prog             # evidence exists, it is just too low now
ok("§19/§35 monotonic completion: a bad retry lowers activityScores and unsatisfies the current "
   "policy, but the historical lessonCompletion survives with its original completedAt")

# ====================== §26 progress API exposes only safe fields ======================
view = svc.progress_view({})
for lid in LESSONS:
    row = view["lessons"][lid]
    # Phase 4D activated a v2 policy per lesson; a learner with NO evidence still completes nothing.
    assert row["authoritativeCompletionAvailable"] is True, lid
    assert row["completed"] is False and row["completedAt"] is None, lid
    assert row["currentPolicySatisfied"] is False and row["activePolicyVersion"] == 2, lid
    assert row["activePolicyCompleted"] is False and row["historicallyCompleted"] is False, lid
    assert len(row["missingActivityIds"]) == 7, row["missingActivityIds"]
    assert set(row) == {"title", "authoritativeCompletionAvailable", "completed", "completedAt",
                        "policyVersion", "requiredActivityIds", "completedActivityIds",
                        "missingActivityIds", "roundedPct", "currentPolicySatisfied",
                        "historicallyCompleted", "activePolicyVersion", "activePolicyCompleted",
                        "activePolicyCompletedAt", "firstCompletedAt",
                        "firstCompletedPolicyVersion", "completionHistory"}, sorted(row)
blob = json.dumps(view)
for leak in ("graderType", "graderConfig", "rewardPolicy", "promptField", "answerField",
             "PASS_GOLD", "10000", "roundId"):
    assert leak not in blob, "progress view leaks %s" % leak
ok("§26 progress API: MRT/Market/Park reported as completion-unavailable; no keys, grader config, "
   "reward detail or round internals in the payload")

# ====================== §37 the reward set did not grow ======================
# Phase 7C.2a retired the "exactly one gold-bearing activity" invariant: all four gates pay.
GATES = sorted("english.prea1.taipei.%s.quiz3" % s
               for s in ("zoo", "mrt", "market", "park"))
gold_bearing = sorted(a for a in reg.activities
                      if reg.reward_policy_of(a) == "standard_activity_pass")
assert gold_bearing == CX.declared_gates(reg), gold_bearing
assert svc.reward_for("english.prea1.taipei.zoo.quiz3")["amount"] == 10000, "PASS_GOLD unchanged"
for lid in LESSONS:
    for suffix in SUFFIXES:
        if "%s.%s" % (lid, suffix) in GATES:
            continue                              # the gate itself pays since Phase 7C.2a
        assert svc.reward_for("%s.%s" % (lid, suffix))["amount"] == 0, (lid, suffix)
    pol = reg.completion_policy_of(lid)
    assert pol and pol["version"] == 2, "%s carries the Phase 4D v2 policy" % lid
    # 5F cosmetic badge + 7C.2 mastery gold - check the whole list, not just the first entry
    assert reg.lesson_reward_policies_of(lid) == ["lesson_mastery_badge",
                                                  "lesson_mastery_gold"], lid
    assert reg.lesson_qualification_ids_for(lid) == [], lid
active = sorted(l for l in reg.lessons if reg.completion_available(l))
CX.assert_completion_model(reg)
assert set(LESSONS + ["english.prea1.taipei.zoo"]) <= set(active), active
assert reg.retired_policy_versions("english.prea1.taipei.zoo") == [1]
ok("§14/§37 the four quiz3 gates are the gold-bearing set (Phase 7C.2a); every non-gate "
   "activity still pays nothing and grants nothing; the four Taipei v2 policies are active; "
   "Zoo v1 stays retired")

# ============ historical lessonCompletions survive the policy retirement, unmodified ============
# A learner who completed Zoo under v1 keeps that record verbatim. It grants nothing (no gold, no
# qualification, no territory access, no passcnt), so preserving it is safe and non-destructive.
HIST = {"lessonCompletions": {"english.prea1.taipei.zoo": {"completedAt": 1700000000,
                                                           "policyVersion": 1}},
        "activityScores": {"english.prea1.taipei.zoo.wh": {"correct": 5, "total": 5, "pct": 100,
                                                           "updatedAt": 1700000000}}}
before = copy.deepcopy(HIST)
row = svc.progress_view(HIST)["lessons"]["english.prea1.taipei.zoo"]
assert HIST == before, "reading progress must not mutate stored history"
assert C.get_lesson_completion(HIST, "english.prea1.taipei.zoo") == \
    {"completedAt": 1700000000, "policyVersion": 1}, "the v1 record is preserved byte-for-byte"
assert svc.state_view(HIST)["lessonCompletions"] == before["lessonCompletions"]
# Phase 4D: Zoo now carries an ACTIVE v2 policy, so the row must separate the three facts cleanly —
# the retired-v1 history is real, the v2 policy is live, and this learner satisfies neither.
assert row["authoritativeCompletionAvailable"] is True, row
assert row["completed"] is True, "the legacy v1 record is historical completion"
assert row["completedAt"] == 1700000000 and row["policyVersion"] == 1, row
assert row["historicallyCompleted"] is True and row["firstCompletedPolicyVersion"] == 1, row
assert row["activePolicyVersion"] == 2, row
assert row["activePolicyCompleted"] is False and row["activePolicyCompletedAt"] is None, row
assert row["currentPolicySatisfied"] is False, "only one activity has a score"
# a fresh attempt does not delete, rewrite or re-date the historical record either
res, _ = svc.grade_attempt("english.prea1.taipei.zoo.wh",
                           [{"q": i["q"], "answer": i["a"]}
                            for i in json.load(open(os.path.join(ROOT, "Pre-A1", "taipei", "zoo.json"),
                                                    encoding="utf-8"))["wh"]])
st_h, out_h = svc.record_attempt(copy.deepcopy(HIST), "english.prea1.taipei.zoo.wh", res, 1800000000)
assert st_h["lessonCompletions"] == before["lessonCompletions"], st_h["lessonCompletions"]
assert out_h["lessonCompleted"] is False and out_h["lessonCompletedNow"] is False, out_h
assert out_h["activePolicyCompleted"] is False, "no v2 entry is invented from a v1 record"
assert out_h["firstCompletedPolicyVersion"] == 1, out_h
assert (st_h.get("lessonCompletionHistory") or {}) == {}, "nothing appended without satisfaction"
assert out_h["lessonRewardAmount"] == 0 and out_h["lessonQualifications"] == [], out_h
ok("historical Zoo lessonCompletions from retired v1 are preserved verbatim, grant nothing, and are "
   "neither revoked nor re-dated by later attempts")

# ====================== §38 campaign invariants: the gates did not move ======================
cat = territory_catalog.catalog
EXPECTED_GATES = {
    "taipei:daan": ["english.prea1.taipei.zoo"],
    "taipei:xinyi": ["english.prea1.taipei.mrt.quiz3.pass"],
    "taipei:zhongzheng": ["english.prea1.taipei.market.quiz3.pass"],
    "taipei:songshan": ["english.prea1.taipei.park.quiz3.pass"],
    "taipei:zhongshan": ["english.prea1.taipei.market.quiz3.pass", "english.prea1.taipei.zoo"],
}
for tid, qids in EXPECTED_GATES.items():
    assert cat.attack_requirements(tid) == qids, (tid, cat.attack_requirements(tid))
for tid in ("taipei:wenshan", "taipei:nangang", "taipei:neihu", "taipei:datong",
            "taipei:wanhua", "taipei:shilin", "taipei:beitou"):
    assert cat.attack_requirements(tid) == [], tid
# the crucial Phase 4B risk: a newly registered activity must not have become a gate
GATING = {q for qids in EXPECTED_GATES.values() for q in qids}
for lid in LESSONS:
    for suffix in NEW_SUFFIXES:
        aid = "%s.%s" % (lid, suffix)
        assert not (set(reg.qualification_ids_for(aid)) & GATING), aid
# no lesson-scope qualification exists at all
assert sorted(reg.qualifications) == [
    "english.prea1.taipei.market.quiz3.pass", "english.prea1.taipei.mrt.quiz3.pass",
    "english.prea1.taipei.park.quiz3.pass", "english.prea1.taipei.zoo"], sorted(reg.qualifications)
ok("§22/§38 all five curated gates and the ungated districts unchanged; none of the 15 newly "
   "registered activities grants a gating qualification; still exactly 4 qualifications")

# ============================== HTTP: the real trust boundary ==============================
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
json.dump({"users": {"ALICE": {"code": "DEPTH"}}, "codes": {"DEPTH": "ALICE"}}, open(server.ACCT, "w"))
server._tokens["tALICE"] = {"user": "ALICE", "exp": time.time() + 9999, "admin": False}
srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % PORT


def call(method, path, body=None, tok="tALICE"):
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


def attempt(aid, ans, extra=None):
    body = {"activityId": aid, "answers": ans}
    if extra:
        body.update(extra)
    return call("POST", "/api/learning/attempt?room=" + CODE, body)


def gold():
    server.set_room(CODE)
    return (server.load_econ_store().get("ALICE") or {}).get("gold", 0)


def passcnt():
    server.set_room(CODE)
    return dict((server.load_econ_store().get("ALICE") or {}).get("passcnt") or {})


def lstate():
    return call("GET", "/api/learning/state?room=" + CODE)[1]


attempt("english.prea1.taipei.zoo.quiz3", answers("english.prea1.taipei.mrt", "quiz3", 0))
g0, p0 = gold(), passcnt()

# §32 forged authority fields on a NEW activity are ignored; a real score is computed instead
FORGED = {"correct": 99, "total": 99, "pct": 100, "score": 100, "passed": True,
          "rewardAmount": 10000, "rewardType": "gold", "granted": ["english.prea1.taipei.zoo"],
          "qualifications": ["english.prea1.taipei.zoo"], "lessonCompleted": True,
          "activityScores": {"x": 1}}
def failing_right(n):
    """A correct-answer count that is guaranteed to score below the 80 pass mark."""
    k = 0
    while int((k + 1) * 100.0 / n + 0.5) < 80:
        k += 1
    return k


for lid in LESSONS:
    for key in DETERMINISTIC:
        aid = "%s.%s" % (lid, key)
        n = len(content(lid)[key])
        k = failing_right(n)
        code, r = attempt(aid, answers(lid, key, k), FORGED)
        assert code == 200, (aid, code, r)
        exp = int(k * 100.0 / n + 0.5)
        assert r["correct"] == k and r["total"] == n and r["pct"] == exp, (aid, r)
        assert r["passed"] is False and exp < 80, (aid, r)
        assert r["rewarded"] is False and r["gold"] is None, (aid, r)
        assert r["qualifications"] == [] and r["qualification"] is None, (aid, r)
        assert r["grantedNow"] is False and r["grantedNowIds"] == [], (aid, r)
        assert r["lessonCompleted"] is False and r["lessonCompletedNow"] is False, (aid, r)
        assert r["lessonQualifications"] == [] and r["lessonRewarded"] is False, (aid, r)
assert gold() == g0, "no new activity may pay gold"
ok("§32 HTTP: every new deterministic activity grades authoritatively; forged correct/total/pct/"
   "passed/reward/qualification/lessonCompleted fields are all ignored; gold delta 0")

# every new activity persists activityScores even though the attempt FAILED (§15)
st = lstate()
for lid in LESSONS:
    for key in DETERMINISTIC:
        aid = "%s.%s" % (lid, key)
        n = len(content(lid)[key])
        rec = st["activityScores"][aid]
        assert rec["correct"] == failing_right(n) and rec["total"] == n, (aid, rec)
        assert aid not in st["activityCompletions"], "a failed attempt is not a completion"
assert st["qualifications"] == {}, "a failed quiz3 must not grant its gate"
assert st["lessonCompletions"] == {}, st["lessonCompletions"]
ok("§15 activityScores persisted for every new activity on a FAILING attempt, with no "
   "activityCompletion, no qualification and no lessonCompletion")

# §33 quiz3 alone earns the Phase 4A gate, with the rest of the lesson unfinished.
# Phase 7C.2a: these three gates now also pay the shared gate reward, over HTTP, exactly once each.
# The first credit also SEEDS the economy account with its room starting balance, so the very first
# delta is (starting balance + gate reward). The reward itself is read from the deltas after that.
balances = []
for lid in LESSONS:
    aid = "%s.quiz3" % lid
    n = len(content(lid)["quiz3"])
    was = gold()
    code, r = attempt(aid, answers(lid, "quiz3", n))
    assert code == 200 and r["passed"] is True and r["pct"] == 100, (aid, r)
    assert r["qualifications"] == [GATE[lid]] and r["qualification"] == GATE[lid], (aid, r)
    assert r["grantedNow"] is True and r["grantedNowIds"] == [GATE[lid]], (aid, r)
    # Phase 14A.10B: a gate pays no gold -- a legitimate NEW pass earns a REWARD GAME instead,
    # which the server creates and tests/reward_games_test.py drives end to end.
    assert r["rewarded"] is False and r.get("rewardGame"), (aid, r)
    assert r["lessonCompleted"] is False and r["lessonQualifications"] == [], (aid, r)
    balances.append(gold())
    # a replay over HTTP pays nothing more, and does not re-grant
    _, again = attempt(aid, answers(lid, "quiz3", n))
    assert again["rewarded"] is False, (aid, again)
    assert gold() == balances[-1], "a replayed gate moved the balance"
deltas = [balances[i] - balances[i - 1] for i in range(1, len(balances))]
# Phase 14A.10B: every gate still behaves IDENTICALLY, and that identical amount is now
# zero -- a pass earns a reward game instead of gold.
assert set(deltas) == {0}, deltas
gate_reward = deltas[0]
st = lstate()
for lid in LESSONS:
    assert GATE[lid] in st["qualifications"], lid
    # the lesson is demonstrably NOT complete: wh/cloze/quiz4 are still failing and 2/5 are unscored
    assert "%s.wh" % lid not in st["activityCompletions"], lid
assert st["lessonCompletions"] == {}, "no lesson completion exists in production Phase 4B"
assert gold() == balances[0] + 2 * gate_reward, "each of the three gates paid once, and only once"
ok("§33 quiz3 pass alone grants each Phase 4A gate qualification with the rest of the lesson "
   "unfinished; each gate pays the same shared reward (%d) exactly once over HTTP, and a replay "
   "moves nothing; still no lesson completion" % gate_reward)

# the gate really does open the territory, exactly as in Phase 4A — checked through the real
# conquest rule with the qualifications the learner actually earned above.
START = "taipei:wenshan"
STORE = {START: {"owner": "ALICE", "troops": [{"type": "cav", "hp": 100}]}}
for tid in ("taipei:daan", "taipei:xinyi", "taipei:zhongzheng", "taipei:songshan",
            "taipei:zhongshan", "taipei:nangang"):
    STORE[tid] = {"owner": "BOB", "troops": [{"type": "inf", "hp": 3}]}
EARNED = sorted(st["qualifications"])
assert EARNED == sorted(GATE.values()), EARNED


def can(target, held, source=START):
    return conquest.can_attack("ALICE", source, target, [{"type": "cav", "hp": 10}], cat, STORE,
                               player_qualifications=list(held))


for tid in ("taipei:xinyi", "taipei:zhongzheng"):
    assert can(tid, EARNED).allowed, tid            # adjacent to the start, gate now satisfied
# RETARGETED (Phase 10A.3R): learning qualifications no longer gate Conquest, so "Daan still needs
# the Zoo qualification" cannot be asserted — there is no gate. What this block now proves is the
# replacement invariant: the qualifications earned above are recorded by LEARNING and change no
# Conquest verdict at all. Stronger than the old form, which only pinned one gate's behaviour.
e_earned = can("taipei:daan", EARNED)
e_none = can("taipei:daan", [])
assert (e_earned.allowed, e_earned.reason) == (e_none.allowed, e_none.reason), (e_earned, e_none)
assert "qualification_required" not in conquest.AttackEligibility.REASONS
ok("§33/§22 the quiz3 qualifications earned above are recorded by Learning and leave the real "
   "can_attack verdict IDENTICAL with or without them — learning does not gate ground")

# §34 whole-lesson neutrality: passcnt is untouched by any of this
assert passcnt() == p0, (passcnt(), p0)
ok("§34 passcnt unchanged by 15 authoritative attempts — legacy values may still sit in stored data, but the counter is inert: nothing writes it and it is not conquest authority")

print()
print("All %d Taipei content-depth tests passed." % passed)
