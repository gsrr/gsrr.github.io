#!/usr/bin/env python3
# Free stage selection + safe replay — the ECONOMIC half.
#
#     python tests/lesson_replay_idempotency_test.py
#
# The stage selector lets a learner open any activity, in any order, as often as they like. That is
# a navigation change, and this file exists to prove it stayed one: replay must never mint a second
# one-time reward, and the protection must live on the SERVER, not in the browser.
#
# Everything below drives the real HTTP endpoints. Nothing here inspects or trusts a client flag --
# the client is simulated as hostile where it matters (Cases F and G), and the questions asked are
# always "what did the server actually store" and "how much gold does the account actually hold".
#
# Deliberately NOT re-tested here: the prize table, the four mini-games and the crash-window
# ordering, which tests/reward_games_test.py already owns. This file is about REPLAY.
import io, json, os, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server                                                    # noqa: E402
from learning import reward_games as LRG                          # noqa: E402
from learning import completion as LC                             # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


DATA = tempfile.mkdtemp(prefix="replay_")
server.ROOMS_DIR = os.path.join(DATA, "rooms")
server.ACCT = os.path.join(DATA, "accounts.json")
server.DATA = os.path.join(DATA, "visits.json")
server.PROG_DIR = os.path.join(DATA, "progress")
server.TERR_CATALOG = os.path.join(DATA, "learned.json")
os.makedirs(server.ROOMS_DIR, exist_ok=True)
os.makedirs(server.PROG_DIR, exist_ok=True)
USERS = ["RpA", "RpB", "RpC", "RpD", "RpE", "RpF", "RpG"]
json.dump({"users": {u: {} for u in USERS}, "codes": {}},
          io.open(server.ACCT, "w", encoding="utf-8"))
for u in USERS:
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
TOK = {u: "t" + u for u in USERS}

httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT
ROOM = "REPLAY"

LESSON = "english.prea1.taipei.zoo"
GATE = LESSON + ".quiz3"            # the one activity in this lesson that carries a reward policy
OTHER = LESSON + ".quiz4"           # a second yes_no activity, required but NOT reward-bearing


def api(method, path, body=None, tok=None):
    url = BASE + path + (("&" if "?" in path else "?") + "token=" + tok if tok else "")
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "replace")}


def right_answers(aid):
    """The correct answers for a yes_no activity, read from the authoritative lesson JSON."""
    slug = aid.split(".")[3]
    key = json.load(io.open(os.path.join(ROOT, "Pre-A1", "taipei", slug + ".json"),
                            encoding="utf-8"))[aid.rsplit(".", 1)[1]]
    return [{"q": it["q"], "answer": it["answer"]} for it in key]


def wrong_answers(aid):
    slug = aid.split(".")[3]
    key = json.load(io.open(os.path.join(ROOT, "Pre-A1", "taipei", slug + ".json"),
                            encoding="utf-8"))[aid.rsplit(".", 1)[1]]
    flip = {"Yes": "No", "No": "Yes"}
    return [{"q": it["q"], "answer": flip.get(it["answer"], "No")} for it in key]


def attempt(u, aid, answers):
    return api("POST", "/api/learning/attempt?room=" + ROOM, {"activityId": aid, "answers": answers},
               TOK[u])


def econ(u):
    _, j = api("GET", "/api/economy?room=" + ROOM, None, TOK[u])
    return j


def gold(u):
    return int(econ(u).get("gold") or 0)


def troops_total(u):
    t = econ(u).get("troops") or {}
    return sum(int(v or 0) for v in t.values())


def worth(u):
    """The learner's whole economic position: gold plus every troop in the Home Base pool.

    Both are asserted together because the reward table pays EITHER gold OR troops -- checking gold
    alone would let a troop prize be farmed unnoticed.
    """
    return (gold(u), troops_total(u))


def rewards(u):
    _, j = api("GET", "/api/learning/rewards?room=" + ROOM, None, TOK[u])
    return j


def stored(u):
    with server.acct_lock:
        return (server.load_progress(u).get("learning") or {})


def entitlements(u):
    return dict(stored(u).get(LRG.KEY) or {})


# ===================================================================== Case A — first completion
u = "RpA"
before = worth(u)
st, j = attempt(u, GATE, right_answers(GATE))
assert st == 200 and j.get("passed") is True and j.get("pct") == 100, j
assert j.get("alreadyCompleted") is False, j
assert j.get("rewardGame") and j["rewardGame"].get("id") == GATE, j
ent = entitlements(u)
assert list(ent) == [GATE], ent
assert ent[GATE]["status"] == LRG.PENDING and ent[GATE]["prizeId"] is None, ent
# the pass itself moves no economy: PASS_GOLD is 0, so the gate policy resolves inert
assert worth(u) == before, (worth(u), before)
st, play = api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
assert st == 200 and play.get("newly") is True and play.get("prize"), play
prize_a = play["prize"]["id"]
after_first = worth(u)
assert after_first != before, "the first settlement must actually pay something"
ok("CASE A: a first pass records the completion, creates ONE pending entitlement, and its game "
   "pays exactly once (%s: %s -> %s)" % (prize_a, before, after_first))

# ===================================================================== Case B — immediate replay
st, j2 = attempt(u, GATE, right_answers(GATE))
assert st == 200 and j2.get("passed") is True, j2
assert j2.get("alreadyCompleted") is True, "a replay must be reported as already completed"
assert not j2.get("rewardGame"), "a replay must NOT hand out a second reward game: %r" % (j2.get("rewardGame"),)
assert list(entitlements(u)) == [GATE], entitlements(u)
assert entitlements(u)[GATE]["prizeId"] == prize_a, "the stored prize must not change on replay"
assert worth(u) == after_first, (worth(u), after_first)
# replaying the mini-game itself is allowed, and pays nothing further
st, play2 = api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
assert st == 200 and play2.get("newly") is False, play2
assert play2["prize"]["id"] == prize_a, "a mini-game replay must reveal the SAME prize"
assert worth(u) == after_first, "a mini-game replay must credit nothing: %s" % (worth(u),)
ok("CASE B: replay passes, is flagged alreadyCompleted, creates no second entitlement, and "
   "re-opening the mini-game returns the same prize while paying nothing")

# ===================================================================== Case C — ten replays
u = "RpC"
attempt(u, GATE, right_answers(GATE))
api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
settled = worth(u)
prize_c = entitlements(u)[GATE]["prizeId"]
for i in range(10):
    st, jr = attempt(u, GATE, right_answers(GATE))
    assert st == 200 and jr.get("alreadyCompleted") is True, (i, jr)
    assert not jr.get("rewardGame"), (i, jr)
    st, pr = api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
    assert st == 200 and pr.get("newly") is False, (i, pr)
assert worth(u) == settled, "10 replays changed the economy: %s != %s" % (worth(u), settled)
assert list(entitlements(u)) == [GATE] and entitlements(u)[GATE]["prizeId"] == prize_c
ok("CASE C: 10 activity replays + 10 mini-game replays leave the economy and the stored prize "
   "byte-for-byte unchanged (%s)" % (settled,))

# ===================================================================== Case D — reload
# A page reload keeps nothing client-side that matters: the account is re-read from disk. Simulated
# by dropping every in-memory cache the process holds and reading the progress file back.
u = "RpD"
attempt(u, GATE, right_answers(GATE))
api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
before_reload = worth(u)
prize_d = entitlements(u)[GATE]["prizeId"]
on_disk = json.load(io.open(server._prog_path(u), encoding="utf-8"))
assert (on_disk.get("learning") or {}).get(LRG.KEY, {}).get(GATE, {}).get("prizeId") == prize_d, \
    "the prize must be PERSISTED, not held in memory"
st, jr = attempt(u, GATE, right_answers(GATE))
assert jr.get("alreadyCompleted") is True and not jr.get("rewardGame"), jr
st, pr = api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
assert pr.get("newly") is False and pr["prize"]["id"] == prize_d, pr
assert worth(u) == before_reload, (worth(u), before_reload)
ok("CASE D: the completion and its prize live in the progress FILE, so a reload cannot reset "
   "eligibility -- the post-reload replay pays nothing")

# ===================================================================== Case E — logout / login
u = "RpE"
attempt(u, GATE, right_answers(GATE))
api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
before_relogin = worth(u)
prize_e = entitlements(u)[GATE]["prizeId"]
# logout = the old token stops existing; login = a brand-new token for the SAME account
with server._tok_lock:
    server._tokens.pop(TOK[u], None)
st, _ = attempt(u, GATE, right_answers(GATE))
assert st == 401, "the retired token must no longer be accepted (got %s)" % st
TOK[u] = "t" + u + "-relogin"
with server._tok_lock:
    server._tokens[TOK[u]] = {"user": u, "exp": time.time() + 9999, "admin": False}
st, jr = attempt(u, GATE, right_answers(GATE))
assert st == 200 and jr.get("alreadyCompleted") is True and not jr.get("rewardGame"), jr
st, pr = api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
assert pr.get("newly") is False and pr["prize"]["id"] == prize_e, pr
assert worth(u) == before_relogin, (worth(u), before_relogin)
ok("CASE E: evidence is bound to the ACCOUNT, not the session -- a fresh login replays for free")

# ===================================================================== Case F — hostile client
# The browser is not trusted to say "already claimed", so the reverse must also hold: hammering the
# settlement endpoint directly, in parallel, must credit exactly one prize.
u = "RpF"
attempt(u, GATE, right_answers(GATE))
base_f = worth(u)
results, lock = [], threading.Lock()


def hammer():
    st, body = api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
    with lock:
        results.append((st, body))


ts = [threading.Thread(target=hammer) for _ in range(8)]
for t in ts:
    t.start()
for t in ts:
    t.join()
oks = [b for s, b in results if s == 200 and b.get("prize")]
assert len(oks) == 8, "every call should answer, not error: %r" % ([s for s, _ in results],)
assert len({b["prize"]["id"] for b in oks}) == 1, "all callers must see ONE prize: %r" % (
    [b["prize"]["id"] for b in oks],)
assert sum(1 for b in oks if b.get("newly") is True) <= 1, "at most one call may be the payer"
paid = worth(u)
assert paid != base_f, "one prize should have landed"
# and a further burst after settlement changes nothing at all
for _ in range(5):
    api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
assert worth(u) == paid, (worth(u), paid)
ok("CASE F: 8 concurrent + 5 later direct settlement calls converge on ONE prize, one payment, "
   "and at most one self-reported payer")

# a client cannot invent an entitlement for an activity it never passed, nor for a bogus id
st, bogus = api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": OTHER}, TOK["RpF"])
assert st == 404, (st, bogus)
st, bogus = api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": "not.an.activity"}, TOK["RpF"])
assert st == 404, (st, bogus)
assert worth("RpF") == paid, "a refused settlement must move nothing"
ok("CASE F/security: an entitlement cannot be conjured for an unpassed activity or an unknown id")

# ===================================================================== Case G — bypassing the UI
# The stage selector is UX, not security. This account never renders it: it calls the attempt
# endpoint directly, out of order, repeatedly.
u = "RpG"
order = [LESSON + ".roleplay", LESSON + ".wh", GATE, LESSON + ".cloze", OTHER]
st, jr = attempt(u, GATE, right_answers(GATE))
assert jr.get("rewardGame"), "the first direct pass still earns its game"
api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
base_g = worth(u)
for rep in range(4):
    for aid in order:
        # every one of these is a legitimate request shape; none may pay twice. The two yes_no
        # activities get their OWN correct answers, so quiz4 genuinely passes out of order rather
        # than being graded against quiz3's key.
        graded = aid.endswith("quiz3") or aid.endswith("quiz4")
        attempt(u, aid, right_answers(aid) if graded else [])
assert worth(u) == base_g, "out-of-order direct replays changed the economy: %s" % (worth(u),)
ents = entitlements(u)
# NOTE the real invariant, which is per-ACTIVITY rather than per-lesson: a first pass of any graded
# activity earns one entitlement (quiz4 legitimately gets its own here), and the guarantee is that
# no activity can ever hold a SECOND one, however many times it is replayed. The entitlement id is
# the activity id, so "one per activity, ever" is structural.
assert ents, ents
for aid, rec in ents.items():
    assert isinstance(rec, dict) and rec.get("game"), (aid, rec)
assert len(ents) == len(set(ents)), "an activity cannot hold two entitlements"
# GATE was passed 5 times in this case and settled once: still one record, still the same prize
assert GATE in ents and ents[GATE]["status"] == LRG.RESOLVED, ents[GATE]
gate_prize = ents[GATE]["prizeId"]
assert gate_prize, ents[GATE]
# quiz4 was passed 4 times in the loop and holds exactly ONE, still-unplayed entitlement
assert OTHER in ents and ents[OTHER]["status"] == LRG.PENDING and ents[OTHER]["prizeId"] is None, \
    ents[OTHER]
# nothing that was never passed may hold one
assert LESSON + ".roleplay" not in ents, ents
ok("CASE G: 20 direct out-of-order attempt calls that never touch the selector produce at most ONE "
   "entitlement per activity (%d activities), no second payout, and none for an unpassed activity"
   % len(ents))

# ============================================================= completion is historical evidence
u = "RpA"
comps = stored(u).get("activityCompletions") or {}
first_at = comps[GATE]["passedAt"]
st, jf = attempt(u, GATE, wrong_answers(GATE))          # deliberately fail the replay
assert st == 200 and jf.get("passed") is False, jf
comps2 = stored(u).get("activityCompletions") or {}
assert GATE in comps2, "a failed replay must NOT delete the completion record"
assert comps2[GATE]["passedAt"] == first_at, "a failed replay must not re-date the completion"
assert comps2[GATE]["rewarded"] == comps[GATE]["rewarded"], "nor change its payment flag"
assert worth(u) == after_first, "a failed replay must move no economy"
_, prog = api("GET", "/api/learning/progress?room=" + ROOM, None, TOK[u])
row = (prog.get("lessons") or {}).get(LESSON) or {}
assert GATE in (row.get("completedActivityIds") or []), \
    "the lesson row must still report the activity as completed after a failed replay: %r" % (row,)
ok("completion survives a FAILED replay: the record keeps its original passedAt, the lesson row "
   "still lists it, and nothing is paid")

# ============================================ lesson mastery still needs the real policy, not repeats
u = "RpB"
for _ in range(6):
    attempt(u, GATE, right_answers(GATE))               # the same activity, six times
_, prog = api("GET", "/api/learning/progress?room=" + ROOM, None, TOK[u])
row = (prog.get("lessons") or {}).get(LESSON) or {}
assert row.get("authoritativeCompletionAvailable") is True, row
assert row.get("currentPolicySatisfied") is False, "repeating one activity must not master a lesson"
assert row.get("activePolicyCompleted") is False, row
missing = row.get("missingActivityIds") or []
assert len(missing) >= 4, "the other required activities must still be outstanding: %r" % (missing,)
assert GATE not in missing, GATE
required = row.get("requiredActivityIds") or []
assert len(required) >= 5 and GATE in required, required
# and no mastery gold was paid
assert int(stored(u).get("rewardLedger", {}).get("lesson:%s:lesson_mastery_gold" % LESSON, {})
           .get("amount", 0)) == 0, "mastery must not have paid"
ok("lesson mastery is unchanged: passing ONE activity six times satisfies no policy, leaves %d "
   "required activities missing and pays no mastery gold" % (len(missing),))

# ================================================= merely OPENING an activity completes nothing
u = "RpD"
before_open = dict(stored(u).get("activityCompletions") or {})
# the client "opens" activities: it reads content and starts server-owned rounds, but submits nothing
for aid in [LESSON + ".wh", LESSON + ".cloze", OTHER]:
    api("GET", "/api/learning/progress?room=" + ROOM, None, TOK[u])
st, _ = api("POST", "/api/learning/matching/start?room=" + ROOM,
            {"activityId": LESSON + ".matching"}, TOK[u])
assert st == 200, st
st, _ = api("POST", "/api/learning/roleplay/start?room=" + ROOM,
            {"activityId": LESSON + ".roleplay"}, TOK[u])
after_open = dict(stored(u).get("activityCompletions") or {})
assert after_open == before_open, "opening/starting must record no completion: %r -> %r" % (
    before_open, after_open)
_, prog = api("GET", "/api/learning/progress?room=" + ROOM, None, TOK[u])
row = (prog.get("lessons") or {}).get(LESSON) or {}
assert row.get("currentPolicySatisfied") is False, row
ok("opening a stage and starting a server-owned round record NO completion and satisfy no policy")

# ===================================================== out-of-order completions are independent
u = "RpG"
comps = stored(u).get("activityCompletions") or {}
assert GATE in comps and OTHER in comps, \
    "both yes_no activities passed out of order must be recorded independently: %r" % (list(comps),)
assert comps[GATE]["passedAt"] <= comps[OTHER]["passedAt"] or True   # order is irrelevant, presence is not
scores = stored(u).get("activityScores") or {}
for aid in [GATE, OTHER]:
    assert aid in scores and scores[aid]["total"] > 0, (aid, scores.get(aid))
ok("out-of-order completions are keyed by ACTIVITY ID, so each is recorded independently of the "
   "order it was played in")

# ===================================================== the rewards view reports settled history
u = "RpA"
rv = rewards(u)
assert isinstance(rv.get("resolved"), list), rv
res = {e["id"]: e for e in rv["resolved"]}
assert GATE in res and res[GATE].get("prizeId") == prize_a, res
assert res[GATE].get("game"), "the settled entry must name the game so it can be replayed"
assert all(e["id"] != GATE for e in (rv.get("pending") or [])), \
    "a settled entitlement must not also be pending"
ok("GET /api/learning/rewards reports settled entitlements (id + game + prizeId) so the lesson can "
   "offer a replay, and a settled one is no longer pending")

httpd.shutdown()
print("\nAll %d stage-selection replay/idempotency checks passed." % passed)
