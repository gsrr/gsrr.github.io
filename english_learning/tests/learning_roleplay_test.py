#!/usr/bin/env python3
"""Phase 4C — server-owned Role-play sessions: authority, ownership, neutrality, dormancy.

    python3 tests/learning_roleplay_test.py

Covers §10 graph validation, §12/§13 session identity and state, §19 termination + defensive cap,
§20 score evidence, §21 latest-wins retry, §22 the central resolver, §29 duplicate turns,
§30 expiry, §31 public metadata, §32 the security audit, §35 real lessons, §36 session ownership,
§37 reward/qualification neutrality and §38 lesson-policy dormancy.

Classifier and full-session parity against the real browser implementation live in
tests/learning_roleplay_parity_test.py.
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
from learning import api as L, registry as R, roleplay as RP  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


reg = R.REGISTRY
svc = L.LearningService(content_root=ROOT, reward_amounts={"PASS_GOLD": 10000})
SLUGS = ["zoo", "mrt", "market", "park"]
AIDS = {s: "english.prea1.taipei.%s.roleplay" % s for s in SLUGS}
LIDS_ = {s: "english.prea1.taipei.%s" % s for s in SLUGS}
WALK = {}
# The happy path for each lesson is DERIVED from its own graph — the first example utterance of the
# first route at each node — so the walk always matches the shipped content instead of being guessed.
def walk_of(graph):
    by_id = {n["id"]: n for n in graph["nodes"]}
    node, out, seen = by_id[graph["start"]], [], set()
    while node.get("routes") and node["id"] not in seen:
        seen.add(node["id"])
        route = node["routes"][0]
        out.append(route["examples"][0])
        node = by_id[route["next_nodes"][0]["id"]]
    return out


JUNK = "purple bicycle refrigerator"


# ====================== §7/§8/§31 registration and public metadata ======================
for slug, aid in AIDS.items():
    spec = reg.activity(aid)
    assert spec, "not registered: %s" % aid
    assert reg.scorer_type_of(aid) == "roleplay_local", aid
    assert spec.get("graderType") is None and spec.get("contentKey") is None, aid
    assert reg.is_server_scored(aid) is True, aid
    assert reg.reward_policy_of(aid) == "none", aid            # §23
    assert reg.qualification_ids_for(aid) == [], aid           # §24
    assert reg.lesson_of_activity(aid) == "english.prea1.taipei.%s" % slug, aid
    assert reg.scenario_path_of(aid) == "roleplay/scenarios/lesson/Pre-A1-taipei-%s" % slug, aid
pub = svc.public_registry_view()
for aid in AIDS.values():
    row = pub["activities"][aid]
    assert row["serverGraded"] is True and row["scored"] == "roleplay", row
    assert row["grants"] == [] and row["contentKey"] is None, row
blob = json.dumps(pub)
for leak in ("scenarioPath", "roleplay/scenarios", "keywords", "next_nodes", "examples",
             "rewardPolicy", "graderType", "0.5", "0.2"):
    assert leak not in blob, "public registry leaks %s" % leak
ok("§7/§8/§31 four Role-play activities registered with scorerType roleplay_local, reward none, "
   "grants []; public view exposes only identity/serverGraded/scored and leaks no graph or threshold")

# ====================== §10 graph validation ======================
for slug, aid in AIDS.items():
    graph, version = svc.roleplay_graph(aid)
    assert graph and isinstance(version, str) and len(version) == 16, (aid, version)
    assert RP.validate_graph(graph) == [], RP.validate_graph(graph)
    WALK[slug] = walk_of(graph)
    assert len(WALK[slug]) >= 4, (slug, WALK[slug])
GOOD, _v = svc.roleplay_graph(AIDS["zoo"])


def rejects(mutate, needle):
    g = copy.deepcopy(GOOD)
    mutate(g)
    errs = RP.validate_graph(g)
    assert any(needle in e for e in errs), (needle, errs[:3])


rejects(lambda g: g.update(start="nope"), "is not a known node id")
rejects(lambda g: g.update(start=None), "is not a known node id")
rejects(lambda g: g.update(nodes=[]), "non-empty list")
rejects(lambda g: g["nodes"].append(dict(g["nodes"][0])), "duplicate node ids")
rejects(lambda g: g["nodes"][0]["routes"][0]["next_nodes"].append({"id": "ghost", "weight": 1}),
        "targets unknown node")
rejects(lambda g: g["nodes"][0]["routes"][0]["next_nodes"][0].update(weight=0), "malformed weight")
rejects(lambda g: g["nodes"][0]["routes"][0]["next_nodes"][0].update(weight="3"), "malformed weight")
rejects(lambda g: g["nodes"][0]["routes"][0].update(next_nodes=[]), "has no next_nodes")
rejects(lambda g: g["nodes"][0]["routes"][0].update(examples=[], keywords=[]), "can never match")
rejects(lambda g: g["nodes"][0]["routes"][0].pop("intent"), "has no intent")
rejects(lambda g: g["nodes"][0].pop("npc"), "no npc.text")
rejects(lambda g: g.update(strategy="mystery"), "not supported")
rejects(lambda g: g.update(max_turns=0), "positive integer")
rejects(lambda g: [n.pop("end", None) for n in g["nodes"]] and g["nodes"][-1].update(
    routes=g["nodes"][0]["routes"]), "no terminal node")
ok("§10 graph validation rejects bad start / empty or duplicate nodes / dangling targets / bad "
   "weights / unmatchable routes / missing npc text / unknown strategy / no terminal node")

# a graph that fails validation is never runnable, so no session can start on it
BROKEN = R.Registry({"schemaVersion": 1,
                     "contentPacks": {"p": {"title": "p"}},
                     "courses": {"c": {"contentPackId": "p", "title": "c"}},
                     "lessons": {"c.l": {"courseId": "c", "contentPath": "Pre-A1/taipei/zoo",
                                         "title": "l"}},
                     "activities": {"c.l.rp": {"lessonId": "c.l", "scorerType": "roleplay_local",
                                               "scenarioPath": "Pre-A1/taipei/zoo",  # not a graph
                                               "title": "rp", "grants": [],
                                               "rewardPolicy": "none"}},
                     "qualifications": {}})
bsvc = L.LearningService(reg=BROKEN, content_root=ROOT, reward_amounts={"PASS_GOLD": 10000})
assert bsvc.roleplay_graph("c.l.rp") == (None, None), "a non-graph document must not load"
assert bsvc.start_roleplay_session({}, "c.l.rp", 1, random.Random(1))[1] is None
ok("§9 a scenarioPath whose document is not a valid graph fails closed: no graph, no session")

# ====================== §35 every real lesson runs with no special cases ======================
finals = {}
for slug, aid in AIDS.items():
    st, view = svc.start_roleplay_session({}, aid, 1000, random.Random(4))
    assert view and view["turn"] == 0 and view["completed"] is False, (slug, view)
    assert set(view["prompt"]) == {"nodeId", "text", "gender", "objective"}, view["prompt"]
    sid = view["sessionId"]
    for i, line in enumerate(WALK[slug]):
        st, v, err = svc.roleplay_respond(st, sid, line, i, 1001 + i, random.Random(4))
        assert err is None and v["result"] == "PASS", (slug, i, err, v and v["result"])
    assert v["completed"] is True, (slug, v)
    rec = st["roleplayProgress"][aid]
    assert rec["passes"] == rec["turns"] == len(WALK[slug]) and rec["pct"] == 100, (slug, rec)
    assert svc.authoritative_activity_score(st, aid) == {"correct": rec["turns"],
                                                         "total": rec["turns"], "pct": 100}, slug
    finals[slug] = st
assert len({tuple(WALK[s]) for s in SLUGS}) == 4, "the four lessons run genuinely different graphs"
assert len({finals[s]["roleplayProgress"][AIDS[s]]["sessionId"] for s in SLUGS}) == 4, \
    "each session gets its own unpredictable id"
ok("§35 all four real Taipei Role-plays run to their terminal node through the same generic code "
   "path — no lesson-specific branches — and each persists exact passes/turns evidence")

# ====================== §18/§19 turn/pass semantics and termination ======================
st, view = svc.start_roleplay_session({}, AIDS["zoo"], 1000, random.Random(4))
sid = view["sessionId"]
for i in range(4):
    st, v, err = svc.roleplay_respond(st, sid, JUNK, i, 1001 + i, random.Random(4))
    assert err is None and v["result"] == "OFF_TOPIC", (i, v)
    assert v["turn"] == i + 1 and v["passes"] == 0, v
    assert v["prompt"]["nodeId"] == "arrive", "an off-topic answer must not advance the node"
    assert v["completed"] is False and v["hint"], v
# a PARTIAL also counts a turn and does not advance. ("look" scores 0.333 at the zoo start node:
# above the 0.2 floor, below the 0.5 pass mark — the middle band.)
st, v, err = svc.roleplay_respond(st, sid, "look", 4, 1010, random.Random(4))
assert v["result"] == "PARTIAL" and v["turn"] == 5 and v["passes"] == 0, v
assert v["prompt"]["nodeId"] == "arrive", v
# then a PASS advances and counts
st, v, err = svc.roleplay_respond(st, sid, WALK["zoo"][0], 5, 1011, random.Random(4))
assert v["result"] == "PASS" and v["turn"] == 6 and v["passes"] == 1, v
assert v["prompt"]["nodeId"] == "lion", v
assert (st.get("roleplayProgress") or {}) == {}, "nothing is persisted until the session completes"
ok("§18 turns increments on EVERY submission (PASS, PARTIAL and OFF_TOPIC alike) while passes "
   "counts only PASS, and only PASS advances the node — the unbounded denominator is preserved")

# the defensive cap ends a runaway session without altering any valid flow
st2, view2 = svc.start_roleplay_session({}, AIDS["zoo"], 1000, random.Random(4))
sid2 = view2["sessionId"]
for i in range(RP.HARD_TURN_CAP):
    st2, v2, err = svc.roleplay_respond(st2, sid2, JUNK, i, 1001, random.Random(4))
    assert err is None, (i, err)
    if v2["completed"]:
        break
assert v2["completed"] is True and v2["turn"] == RP.HARD_TURN_CAP, v2
assert RP.HARD_TURN_CAP > 24 * 4, "the cap must sit far above any authored graph's max_turns"
assert st2["roleplayProgress"][AIDS["zoo"]] == {
    "passes": 0, "turns": RP.HARD_TURN_CAP, "pct": 0,
    "sessionId": sid2, "updatedAt": 1001}, st2["roleplayProgress"]
ok("§19 the defensive cap (%d turns) ends a runaway session and still records exact evidence; the "
   "shipped engine never terminates on max_turns, so no valid flow is affected" % RP.HARD_TURN_CAP)

# ====================== §21 latest-wins retry ======================
st = copy.deepcopy(finals["zoo"])
assert st["roleplayProgress"][AIDS["zoo"]]["pct"] == 100
st, view = svc.start_roleplay_session(st, AIDS["zoo"], 2000, random.Random(4))
sid = view["sessionId"]
seq = 0
for line in [JUNK, JUNK] + WALK["zoo"]:
    st, v, err = svc.roleplay_respond(st, sid, line, seq, 2001, random.Random(4))
    assert err is None, (line, err)
    seq = v["turn"]
    if v["completed"]:
        break
rec = st["roleplayProgress"][AIDS["zoo"]]
n = len(WALK["zoo"])
assert rec["passes"] == n and rec["turns"] == n + 2, rec       # two junk turns inflate the denominator
assert rec["pct"] == int(n * 100.0 / (n + 2) + 0.5), rec
assert rec["sessionId"] == sid, "the newest session owns the evidence"
assert svc.authoritative_activity_score(st, AIDS["zoo"])["total"] == n + 2, "latest-wins, not best-of"
assert AIDS["zoo"] not in (st.get("activityCompletions") or {}), \
    "Role-play has no independent pass definition, so it records no activityCompletion"
ok("§21 a worse retry REPLACES the previous Level 10 evidence (latest-wins, matching recordScore's "
   "unconditional overwrite) and never writes an activityCompletion")

# ====================== §29/§30 duplicate turns, expiry, replay ======================
st, view = svc.start_roleplay_session({}, AIDS["mrt"], 3000, random.Random(4))
sid = view["sessionId"]
st, v, err = svc.roleplay_respond(st, sid, WALK["mrt"][0], 0, 3001, random.Random(4))
assert err is None and v["turn"] == 1
before = copy.deepcopy(st["roleplaySessions"][sid])
for bad_seq in (0, 5, -1):
    st, v, err = svc.roleplay_respond(st, sid, WALK["mrt"][1], bad_seq, 3002, random.Random(4))
    assert v is None and err == "stale_turn", (bad_seq, err)
assert st["roleplaySessions"][sid] == before, "a refused turn must not touch the counters"
st, v, err = svc.roleplay_respond(st, "nope" * 8, "hi", 0, 3003, random.Random(4))
assert v is None and err == "unknown_session", err
st, v, err = svc.roleplay_respond(st, sid, WALK["mrt"][1], 1,
                                  3000 + RP.SESSION_TTL + 1, random.Random(4))
assert v is None and err == "session_expired", err
assert sid not in st["roleplaySessions"], "an expired session is dropped"
# a completed session can never be replayed to change evidence
done = copy.deepcopy(finals["park"])
sid_done = list(done["roleplaySessions"])[0]
snapshot = copy.deepcopy(done["roleplayProgress"])
done, v, err = svc.roleplay_respond(done, sid_done, WALK["park"][0], 0, 4000, random.Random(4))
assert v is None and err in ("session_complete", "stale_turn"), err
assert done["roleplayProgress"] == snapshot, "completed evidence is immutable"
ok("§29/§30 duplicate/stale/negative seq refused without counting; unknown session refused; "
   "expired session refused and dropped; a completed session cannot be replayed")

# expiry never destroys completed evidence
aged = copy.deepcopy(finals["zoo"])
aged["roleplaySessions"] = {k: dict(v, createdAt=1) for k, v in aged["roleplaySessions"].items()}
aged, view = svc.start_roleplay_session(aged, AIDS["mrt"], 10 ** 7, random.Random(4))
assert aged["roleplayProgress"][AIDS["zoo"]]["pct"] == 100, "pruning must not touch progress"
ok("§30 pruning expired sessions leaves authoritative completed evidence untouched")

# ====================== §22 the resolver, and malformed evidence ======================
assert svc.authoritative_activity_score({}, AIDS["zoo"]) is None
for junk in ({"roleplayProgress": "x"}, {"roleplayProgress": {AIDS["zoo"]: "x"}},
             {"roleplayProgress": {AIDS["zoo"]: {}}},
             {"roleplayProgress": {AIDS["zoo"]: {"passes": 1, "turns": 0}}}):
    assert svc.authoritative_activity_score(junk, AIDS["zoo"]) is None, junk
assert svc.authoritative_activity_score(
    {"roleplayProgress": {AIDS["zoo"]: {"passes": 3, "turns": 4, "pct": 75}}}, AIDS["zoo"]) == \
    {"correct": 3, "total": 4, "pct": 75}
ok("§22 the central resolver reads Role-play from roleplayProgress as exact passes/turns; a "
   "0-turn or malformed record is 'unscored', exactly as a falsy total is in statusFromScores")

# ====================== §37/§38 reward, qualification, lesson dormancy ======================
combined = {}
for slug in SLUGS:
    combined.setdefault("roleplayProgress", {}).update(
        finals[slug].get("roleplayProgress") or {})
assert (combined.get("qualifications") or {}) == {}
GATES = sorted("english.prea1.taipei.%s.quiz3" % s
               for s in ("zoo", "mrt", "market", "park"))
gold_bearing = sorted(a for a in reg.activities if svc.reward_for(a)["amount"] > 0)
assert gold_bearing == GATES, gold_bearing   # Phase 7C.2a: four gates, still no role-play gold
for aid in AIDS.values():
    assert svc.reward_for(aid)["amount"] == 0, aid
assert sorted(reg.qualifications) == [
    "english.prea1.taipei.market.quiz3.pass", "english.prea1.taipei.mrt.quiz3.pass",
    "english.prea1.taipei.park.quiz3.pass", "english.prea1.taipei.zoo"], sorted(reg.qualifications)
assert sorted(l for l in reg.lessons if reg.completion_available(l)) == ["english.prea1.taipei.market", "english.prea1.taipei.mrt", "english.prea1.taipei.park", "english.prea1.taipei.zoo"], \
    "the four Taipei v2 policies are active (Phase 4D)"
pv = svc.progress_view(combined)
# Role-play evidence ALONE never completes a lesson: the other six required levels are unscored here.
assert pv["completedLessonIds"] == [], pv["completedLessonIds"]
assert all(r["completed"] is False for r in pv["lessons"].values())
assert all(r["currentPolicySatisfied"] is False for r in pv["lessons"].values())
for slug, lid in ((s, LIDS_[s]) for s in SLUGS):
    row = pv["lessons"][lid]
    assert row["authoritativeCompletionAvailable"] is True, lid
    assert row["activePolicyVersion"] == 2 and row["activePolicyCompleted"] is False, lid
    assert "%s.roleplay" % lid not in row["missingActivityIds"], "roleplay evidence IS present"
    assert len(row["missingActivityIds"]) == 6, row["missingActivityIds"]
ok("§23/§24/§37/§38 Role-play pays 0 gold, grants 0 qualifications, adds no lesson policy: "
   "gold-bearing activities are the 4 quiz3 gates, qualifications still 4, active policies 0")

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
json.dump({"users": {"ALICE": {"code": "RPLAY"}, "BOB": {"code": "RPLAYB"}},
           "codes": {"RPLAY": "ALICE", "RPLAYB": "BOB"}}, open(server.ACCT, "w"))
server._tokens["tA"] = {"user": "ALICE", "exp": time.time() + 9999, "admin": False}
server._tokens["tB"] = {"user": "BOB", "exp": time.time() + 9999, "admin": False}
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


def gold(user="ALICE"):
    server.set_room(CODE)
    return (server.load_econ_store().get(user) or {}).get("gold", 0)


def passcnt():
    server.set_room(CODE)
    return dict((server.load_econ_store().get("ALICE") or {}).get("passcnt") or {})


def lstate(tok="tA"):
    return call("GET", "/api/learning/state?room=" + CODE, tok=tok)[1]


g0, pc0 = gold(), passcnt()

# §36 anonymous and cross-account access
assert call("POST", "/api/learning/roleplay/start", {"activityId": AIDS["zoo"]}, tok="bogus")[0] == 401
assert call("POST", "/api/learning/roleplay/respond", {"sessionId": "x", "response": "y"},
            tok="bogus")[0] == 401
code, start = call("POST", "/api/learning/roleplay/start?room=" + CODE, {"activityId": AIDS["zoo"]})
assert code == 200 and start["sessionId"] and start["turn"] == 0, start
SID = start["sessionId"]
code, r = call("POST", "/api/learning/roleplay/respond?room=" + CODE,
               {"sessionId": SID, "response": WALK["zoo"][0], "seq": 0}, tok="tB")
assert code == 400 and r["reason"] == "unknown_session", r
# a non-roleplay activity cannot be started as one
assert call("POST", "/api/learning/roleplay/start?room=" + CODE,
            {"activityId": "english.prea1.taipei.zoo.quiz3"})[1]["reason"] == "not_scorable"
ok("§36 anonymous start/respond are 401; another account's sessionId does not exist for BOB; a "
   "non-Role-play activity cannot be started as a session")

# §32 the client cannot forge anything that matters
FORGED = {"sessionId": SID, "response": JUNK, "seq": 0,
          "currentNodeId": "bye", "nextNodeId": "bye", "graph": {"nodes": []},
          "graphVersion": "deadbeef", "turns": 99, "passes": 99, "score": 100, "pct": 100,
          "completed": True, "result": "PASS", "classification": "PASS",
          "thresholds": {"pass": 0.0, "floor": 0.0}, "pass": 0.0, "floor": 0.0,
          "rng": 0.0, "rewardAmount": 10000, "qualifications": ["english.prea1.taipei.zoo"],
          "policyVersion": 1, "lessonCompleted": True}
code, r = call("POST", "/api/learning/roleplay/respond?room=" + CODE, FORGED)
assert code == 200, r
assert r["result"] == "OFF_TOPIC", "forged thresholds must not turn junk into a PASS"
assert r["turn"] == 1 and r["passes"] == 0, r
assert r["prompt"]["nodeId"] == "arrive", "forged currentNode/nextNode must be ignored"
assert r["completed"] is False, "the client cannot declare the session finished"
assert "score" not in r and "pct" not in r, r
assert gold() == g0, "no gold from a forged turn"
st = lstate()
assert (st.get("roleplayProgress") or {}) == {}, "an unfinished session persists no evidence"
assert st["qualifications"] == {}, st["qualifications"]
# the graph/answer key is never returned
blob = json.dumps(r)
for leak in ("keywords", "examples", "next_nodes", "weight", "intent", "routes", "0.5"):
    assert leak not in blob, "respond leaks %s" % leak
ok("§32 forged node/graph/version/turns/passes/score/completed/result/thresholds/rng/reward/"
   "qualification/policyVersion are ALL ignored; the response leaks no graph internals")

# a clean run over HTTP produces the authoritative score, and pays nothing
code, start = call("POST", "/api/learning/roleplay/start?room=" + CODE, {"activityId": AIDS["mrt"]})
SID = start["sessionId"]
seq = 0
for line in WALK["mrt"]:
    code, r = call("POST", "/api/learning/roleplay/respond?room=" + CODE,
                   {"sessionId": SID, "response": line, "seq": seq})
    assert code == 200 and r["result"] == "PASS", (line, r)
    seq = r["turn"]
    if r["completed"]:
        break
m = len(WALK["mrt"])
assert r["completed"] is True and r["score"] == {"passes": m, "turns": m, "pct": 100}, r
assert r["qualifications"] == [] and r["rewarded"] is False and r["gold"] is None, r
assert r["lessonCompleted"] is False and r["lessonCompletedNow"] is False, r
st = lstate()
assert st["roleplayProgress"][AIDS["mrt"]]["pct"] == 100, st["roleplayProgress"]
assert st["lessonCompletions"] == {}, st["lessonCompletions"]
assert gold() == g0 and passcnt() == pc0, (gold() - g0, passcnt())
assert "roleplaySessions" not in st, "in-flight session state is never exposed to the client"
ok("§20/§37/§38 a full HTTP conversation persists authoritative passes/turns/pct, pays 0 gold, "
   "grants 0 qualifications, creates no lessonCompletion and leaves passcnt untouched")

srv.shutdown()
print()
print("All %d Role-play session tests passed." % passed)
