#!/usr/bin/env python3
"""Phase 3E2 — server-authoritative Matching: rounds, first-try scoring, ownership, persistence.

    python3 tests/learning_matching_test.py

Covers §31 legacy parity, §32 server sample, §33 first-try, §34 ownership, §35 persistence,
§36 two real lessons, §37 no economy change, §38 Phase 3D dormancy.
"""
import copy
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from learning import api as L, matching as M, registry as R  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


svc = L.LearningService(content_root=ROOT, reward_amounts={"PASS_GOLD": 10000})
ZOO = "english.prea1.taipei.zoo.matching"
A1 = "english.a1.core.001.matching"


def start(state, aid=ZOO, seed=7, now=1000):
    state, view = svc.start_matching_round(state, aid, now, random.Random(seed))
    return state, view, view["roundId"]


def rs_of(state, rid):
    return state["matchingRounds"][rid]


def pos_of(state, rid, vocab_index):
    return rs_of(state, rid)["choices"].index(vocab_index)


def click(state, rid, vocab_index, now=1000, item=None):
    """Click the picture button whose position holds `vocab_index`."""
    cur = M.current_item_id(rs_of(state, rid)) if item is None else item
    return svc.matching_click(state, rid, cur, M.choice_id(rid, pos_of(state, rid, vocab_index)), now)


def correct_vi(state, rid):
    r = rs_of(state, rid)
    return r["order"][r["expected"]]


def any_wrong_vi(state, rid):
    """An unmatched picture that is NOT the current answer, or None if none exists.

    On the LAST word there is none: every other picture is already matched (and therefore inert), so
    a wrong first click is impossible. That is the legacy behaviour — the final word always scores —
    which means the minimum attainable score is 1/5, not 0/5.
    """
    r = rs_of(state, rid)
    want = r["order"][r["expected"]]
    matched = set(r["order"][:r["expected"]])
    return next((vi for vi in r["choices"] if vi != want and vi not in matched), None)


# ============================== §32 server sample ==============================
st, view, rid = start({})
assert len(view["items"]) == 5 and view["total"] == 5, view["total"]
assert len(view["choices"]) == 5
vocab = svc.matching_vocab(ZOO)
assert len(vocab) == 6, "the Zoo lesson has 6 vocab items; the sample takes 5 (legacy min(5, len))"
assert M.sample_size(6) == 5 and M.sample_size(3) == 3 and M.sample_size(0) == 0
words = {v["word"] for v in vocab}
assert {i["word"] for i in view["items"]} <= words, "sample contains only authoritative items"
assert len({i["itemId"] for i in view["items"]}) == 5, "item ids are unique"
assert all(i["itemId"].startswith(ZOO + "#item:") for i in view["items"])
assert all(c["choiceId"].startswith(rid + "#choice:") for c in view["choices"])
# the picture column is an INDEPENDENT shuffle of the same items (legacy behaviour)
r = rs_of(st, rid)
assert sorted(r["choices"]) == sorted(r["order"]), "same items, different order"
# the public view leaks no mapping whatsoever
blob = json.dumps(view)
for leak in ("order", "vocabIndex", "correct", "firstTry", "missedCurrent", "expected\": 0, \"order"):
    assert leak not in blob or leak == "expected", blob
assert "answer" not in blob
# seeded RNG is deterministic; different seeds give different draws
a = svc.start_matching_round({}, ZOO, 1, random.Random(3))[1]
b = svc.start_matching_round({}, ZOO, 1, random.Random(3))[1]
assert [i["word"] for i in a["items"]] == [i["word"] for i in b["items"]], "seeded draw is deterministic"
draws = {tuple(svc.start_matching_round({}, ZOO, 1, random.Random(s))[1]["items"][0]["word"]
               for _ in [0]) for s in range(25)}
assert len(draws) > 1, "the sample really is randomised across seeds"
ok("§32 server sample: n=min(5,len) from authoritative vocab, independent picture shuffle, no mapping leaked")

# ============================== §33 first-try semantics ==============================
# all first-click correct -> full marks
st, view, rid = start({})
for _ in range(5):
    st, o = click(st, rid, correct_vi(st, rid))
assert o["status"] == "complete" and o["result"] == {"correct": 5, "total": 5, "pct": 100, "passed": True}
# one wrong first-click then corrected -> that point is lost permanently
st, view, rid = start({})
st, o = click(st, rid, any_wrong_vi(st, rid))
assert o["status"] == "wrong" and o["scored"] is None and o["expected"] == 0
st, o = click(st, rid, correct_vi(st, rid))
assert o["status"] == "correct" and o["scored"] is False, "corrected after a miss earns NO point"
for _ in range(4):
    st, o = click(st, rid, correct_vi(st, rid))
assert o["result"] == {"correct": 4, "total": 5, "pct": 80, "passed": True}, o["result"]
# multiple wrong clicks on the same word cost nothing extra
st, view, rid = start({})
for _ in range(3):
    st, o = click(st, rid, any_wrong_vi(st, rid))
    assert o["status"] == "wrong"
st, o = click(st, rid, correct_vi(st, rid))
assert o["scored"] is False
for _ in range(4):
    st, o = click(st, rid, correct_vi(st, rid))
assert o["result"]["correct"] == 4, "3 wrong clicks on ONE word still cost exactly one point"
# miss every word that CAN be missed -> the floor is 1/5, because the last word has no wrong button
st, view, rid = start({})
missable = 0
for _ in range(5):
    w = any_wrong_vi(st, rid)
    if w is not None:
        missable += 1
        st, _ = click(st, rid, w)
    st, o = click(st, rid, correct_vi(st, rid))
assert missable == 4, "only the first 4 words can be missed; the last has no unmatched wrong picture"
assert o["result"] == {"correct": 1, "total": 5, "pct": 20, "passed": False}, o["result"]
ok("§31/§33 first-try parity: clean=5/5, one miss=4/5 (80, passes), repeated misses cost once, "
   "floor=1/5 (the last word cannot be missed)")

# an already-matched picture is INERT, not a wrong attempt (legacy `if (btn.disabled) return`)
st, view, rid = start({})
first = correct_vi(st, rid)
st, o = click(st, rid, first)
assert o["scored"] is True
st, o = click(st, rid, first)                       # click the matched picture again
assert o["status"] == "inert" and rs_of(st, rid)["missedCurrent"] is False, o
st, o = click(st, rid, correct_vi(st, rid))
assert o["scored"] is True, "clicking a matched picture must not have cost the next word's point"
ok("§33 inert clicks: re-clicking an already-matched picture is a no-op, never a wrong attempt")

# ============================== §29 duplicates / concurrency ==============================
st, view, rid = start({})
cur_item = M.current_item_id(rs_of(st, rid))
vi = correct_vi(st, rid)
st, o1 = click(st, rid, vi, item=cur_item)
assert o1["scored"] is True and o1["expected"] == 1
# the SAME request replayed: the item is no longer current -> refused, no second point
st, o2 = svc.matching_click(st, rid, cur_item, M.choice_id(rid, pos_of(st, rid, vi)), 1000)
assert o2["status"] in ("inert", "not_current") and rs_of(st, rid)["firstTry"] == 1, o2
assert rs_of(st, rid)["expected"] == 1, "a duplicate click cannot advance the round"
# a stale itemId (naming a word that is not current) is refused without touching first-try state
st, o3 = svc.matching_click(st, rid, ZOO + "#item:999",
                            M.choice_id(rid, pos_of(st, rid, correct_vi(st, rid))), 1000)
assert o3["status"] == "not_current" and rs_of(st, rid)["missedCurrent"] is False, o3
st, o4 = click(st, rid, correct_vi(st, rid))
assert o4["scored"] is True, "a refused stale request must not have cost the point"
ok("§29 duplicates: replayed/stale clicks are refused; firstTry counted exactly once")

# ============================== §34 round ownership + lifecycle ==============================
alice, view, rid = start({})
bob = {}
# Bob's state simply has no such round — ownership is structural, not a forgettable check
assert svc.matching_click(bob, rid, None, M.choice_id(rid, 0), 1000)[1] is None
for bad in ("", "nope", None, rid + "x"):
    assert svc.matching_click(alice, bad, None, M.choice_id(str(bad), 0), 1000)[1] is None, bad
# a completed round cannot be replayed to change the score
done, v2, rid2 = start({})
for _ in range(5):
    done, o = click(done, rid2, correct_vi(done, rid2))
assert o["status"] == "complete" and rid2 not in done["matchingRounds"], "completed round is compacted away"
assert svc.matching_click(done, rid2, None, M.choice_id(rid2, 0), 1000)[1] is None
assert done["matchingProgress"][ZOO]["pct"] == 100
# an expired round is refused
old, v3, rid3 = start({}, now=1000)
assert svc.matching_click(old, rid3, None, M.choice_id(rid3, 0), 1000 + M.ROUND_TTL + 1)[1] is None
# starting a new round retires the previous open one for the same activity (§30)
s2, v4, rid4 = start({})
s2, v5, rid5 = svc.start_matching_round(s2, ZOO, 2000, random.Random(9))[0], None, None
rid5 = [r for r in s2["matchingRounds"] if r != rid4]
assert rid4 not in s2["matchingRounds"] and len(s2["matchingRounds"]) == 1, s2["matchingRounds"].keys()
ok("§30/§34 ownership+lifecycle: cross-account impossible, unknown/expired/completed refused, one live round")

# ============================== §35 persistence + §22/§23 evidence ==============================
st, view, rid = start({})
st, _ = click(st, rid, any_wrong_vi(st, rid))          # miss the FIRST word (the last cannot be missed)
for _ in range(5):
    st, o = click(st, rid, correct_vi(st, rid), now=5000)
assert o["result"] == {"correct": 4, "total": 5, "pct": 80, "passed": True}, o["result"]
prog = st["matchingProgress"][ZOO]
assert sorted(prog) == ["correct", "latestRoundId", "pct", "total", "updatedAt"]
assert prog["correct"] == 4 and prog["pct"] == 80 and prog["updatedAt"] == 5000
assert st["activityCompletions"][ZOO]["pct"] == 80, "80 >= PASS_MARK -> a real activity completion"
st = json.loads(json.dumps(st))                       # survives the JSON round trip it is stored as
assert st["matchingProgress"][ZOO]["pct"] == 80
# latest-wins, exactly like the legacy recordScore: a WORSE later round overwrites the evidence
st, view, rid = start(st, now=6000)
for _ in range(5):
    w = any_wrong_vi(st, rid)
    if w is not None:
        st, _ = click(st, rid, w, now=6000)
    st, o = click(st, rid, correct_vi(st, rid), now=6000)
assert o["result"]["correct"] == 1
assert st["matchingProgress"][ZOO]["pct"] == 20, "latest-wins score evidence (legacy semantics)"
assert st["activityCompletions"][ZOO]["pct"] == 80, "the earlier PASS record is not revoked"
assert st["activityCompletions"][ZOO]["passedAt"] == 5000, "first passedAt frozen"
# a low-scoring round records evidence but fabricates no pass
fresh, view, rid = start({})
for _ in range(5):
    w = any_wrong_vi(fresh, rid)
    if w is not None:
        fresh, _ = click(fresh, rid, w)
    fresh, o = click(fresh, rid, correct_vi(fresh, rid))
assert o["result"]["passed"] is False and o["result"]["correct"] == 1
assert fresh["matchingProgress"][ZOO]["pct"] == 20
assert (fresh.get("activityCompletions") or {}) == {}, "a failed round is NOT an activity pass"
# malformed stored state fails safely
for junk in ({"matchingRounds": "nope"}, {"matchingRounds": {rid: "nope"}},
             {"matchingRounds": {rid: {}}}, {"matchingRounds": {rid: {"activityId": "nope"}}}):
    assert svc.matching_click(copy.deepcopy(junk), rid, None, M.choice_id(rid, 0), 1000)[1] is None
ok("§22/§23/§35 persistence: evidence schema, latest-wins, low score is no pass, malformed state safe")

# ============================== §36 two real lessons ==============================
st2, v2, rid2 = start({}, aid=A1, seed=11)
assert v2["total"] == 5 and {i["word"] for i in v2["items"]} <= {v["word"] for v in svc.matching_vocab(A1)}
for _ in range(5):
    st2, o = click(st2, rid2, correct_vi(st2, rid2))
assert o["result"]["pct"] == 100 and st2["matchingProgress"][A1]["pct"] == 100
assert ZOO not in st2["matchingProgress"], "activities keep separate evidence"
# both real lessons run through the identical code path
assert svc.is_matching(ZOO) and svc.is_matching(A1)
assert not svc.is_matching("english.prea1.taipei.zoo.quiz3")
assert svc.matching_vocab("english.prea1.taipei.zoo.quiz3") is None
assert svc.start_matching_round({}, "nope", 1, random.Random(1))[1] is None
ok("§36 two real lessons (Zoo + A1/001) behave identically — no lesson-specific code")

# duplicate-emoji lessons stay unambiguous because choices are keyed by POSITION
dupes = [f for f in os.listdir(os.path.join(ROOT, "Pre-A1")) if f.endswith(".json")]
vv = svc.matching_vocab(ZOO)
st3, v3, rid3 = start({})
positions = {c["choiceId"] for c in v3["choices"]}
assert len(positions) == 5, "each button has its own id even if two share an emoji"
ok("choice identity is per-button position, so duplicate emojis in vocab remain unambiguous")

# ============================== §37 no economy change + §38 dormancy ==============================
st4, v4, rid4 = start({})
for _ in range(5):
    st4, o = click(st4, rid4, correct_vi(st4, rid4))
assert o["rewarded"] is False and o["rewardAmount"] == 0 and o["granted"] == []
assert (st4.get("qualifications") or {}) == {}
assert svc.registry.reward_policy_of(ZOO) == "none" and svc.registry.qualification_ids_for(ZOO) == []
assert svc.reward_for(ZOO)["amount"] == 0
assert [a for a in svc.registry.activities if svc.registry.reward_policy_of(a) != "none"] == \
    ["english.prea1.taipei.zoo.quiz3"], "Zoo quiz3 is still the only paying activity"
assert o["lessonCompleted"] is False and o["lessonCompletedNow"] is False
assert st4.get("lessonCompletions") is None or st4["lessonCompletions"] == {}
active = [l for l in svc.registry.lessons if svc.registry.completion_available(l)]
assert active == [], active
ok("§37/§38 neutrality: matching pays 0 gold, grants 0 qualifications, production policies still 0")

# ============================== §39 validator ==============================
BASE = copy.deepcopy(R.DATA)
assert R.validate(BASE) == []


def rejects(mutate, needle):
    d = copy.deepcopy(BASE)
    mutate(d)
    errs = R.validate(d)
    assert any(needle in e for e in errs), (needle, errs)


A = lambda d: d["activities"][ZOO]  # noqa: E731
rejects(lambda d: A(d).pop("contentKey"), "must name the content key")
rejects(lambda d: A(d).update(contentKey=5), "must name the content key")
rejects(lambda d: A(d).update(scorerType="matching_v2"), "unknown scorerType")
rejects(lambda d: A(d).update(graderType="yes_no"), "declares both graderType and scorerType")
rejects(lambda d: A(d).update(rewardGold=1), "may not set")
rejects(lambda d: A(d).update(grants=["nope"]), "grants unknown qualification")
# the public registry view must not expose the pairing or the scorer internals
pv = R.Registry(BASE).public_view()
blob = json.dumps(pv)
assert pv["activities"][ZOO]["scored"] == "matching"
for leak in ("scorerType", "matching_first_try", "vocab\": [", "pic\":"):
    assert leak not in blob, leak
ok("§39 validator: matching scorerType + contentKey validated; public view exposes no pairing")

print("\nAll %d matching tests passed." % passed)
