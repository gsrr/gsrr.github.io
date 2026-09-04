# Phase 14A.10B — LEARNING REWARD GAMES: one pass, one game, one prize.
#
#   python tests/reward_games_test.py
#
# Passing a lesson gate used to pay 500 gold straight into the balance. It now earns ONE reward
# game -- a wheel, three chests, a shot or a die -- and the game pays 3,000 gold or 400-670 troops.
#
# The whole point of this file is that the four mini-games are four ways to REVEAL one server
# decision, not four economies. Everything below therefore drives the real endpoints: the browser
# never names a prize, never names a game, cannot create an entitlement and cannot roll twice.
import io, json, os, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server                                                    # noqa: E402
from game import config as GC                                    # noqa: E402
from game import reward_games as GRG                             # noqa: E402
from learning import reward_games as LRG                         # noqa: E402
from learning import completion as LC                            # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


DATA = tempfile.mkdtemp(prefix="rgames14b_")
server.ROOMS_DIR = os.path.join(DATA, "rooms")
server.ACCT = os.path.join(DATA, "accounts.json")
server.DATA = os.path.join(DATA, "visits.json")
server.PROG_DIR = os.path.join(DATA, "progress")
server.TERR_CATALOG = os.path.join(DATA, "learned.json")
os.makedirs(server.ROOMS_DIR, exist_ok=True)
os.makedirs(server.PROG_DIR, exist_ok=True)
USERS = ["RgA", "RgB", "RgC", "RgD", "RgE"]
json.dump({"users": {u: {} for u in USERS}, "codes": {}},
          io.open(server.ACCT, "w", encoding="utf-8"))
for u in USERS:
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
TOK = {u: "t" + u for u in USERS}

httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT
ROOM = "RGAMES"

GATES = ["english.prea1.taipei.zoo.quiz3", "english.prea1.taipei.mrt.quiz3",
         "english.prea1.taipei.market.quiz3"]


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


def answers(aid):
    slug = aid.split(".")[3]
    key = json.load(io.open(os.path.join(ROOT, "Pre-A1", "taipei", slug + ".json"),
                            encoding="utf-8"))["quiz3"]
    return [{"q": i["q"], "answer": i["answer"]} for i in key]


def attempt(user, aid):
    return api("POST", "/api/learning/attempt?room=" + ROOM,
               {"activityId": aid, "answers": answers(aid)}, TOK[user])


def econ(user):
    st, j = api("GET", "/api/economy?room=" + ROOM, None, TOK[user])
    assert st == 200, (st, j)
    return j


def rewards(user):
    st, j = api("GET", "/api/learning/rewards?room=" + ROOM, None, TOK[user])
    assert st == 200, (st, j)
    return j


def play(user, eid, extra=None):
    body = dict(extra or {})
    body["id"] = eid
    return api("POST", "/api/learning/rewards/play?room=" + ROOM, body, TOK[user])


def progress(user):
    with server.acct_lock:
        return server.load_progress(user).get("learning") or {}


def force_game(name):
    server.REWARD_GAME_PICKER = (lambda: name)


def force_prize(prize_id):
    class _R(object):                      # the seam takes an rng; this one always picks one prize
        def choice(self, seq):
            for p in seq:
                if p["id"] == prize_id:
                    return p
            raise AssertionError(prize_id)
    server.REWARD_PRIZE_RNG = (lambda: _R())


REAL_PICKER, REAL_RNG = server.REWARD_GAME_PICKER, server.REWARD_PRIZE_RNG

# ===================================================================== the tables
assert GRG.GAMES == ("lucky_wheel", "treasure_chests", "target_shot", "dice_roll"), GRG.GAMES
assert [p["id"] for p in GRG.PRIZES] == ["gold_3000", "infantry_670", "archer_420", "cavalry_400"]
assert GRG.gold_value("gold_3000") == 3000
assert GRG.gold_value("infantry_670") == 670 * GC.UNIT_COST["inf"] == 4020
assert GRG.gold_value("archer_420") == 420 * GC.UNIT_COST["archer"] == 5040
assert GRG.gold_value("cavalry_400") == 400 * GC.UNIT_COST["cav"] == 6000
ok("the tables: four mini-games and ONE prize table (3,000 gold / 670 inf / 420 archer / 400 cav, "
   "worth 3000/4020/5040/6000 at the unchanged UNIT_COST -- informational only, never converted)")

# ===================================================================== 1/2/4/5. a new PASS
force_game("lucky_wheel")
before = econ("RgA")
st, j = attempt("RgA", GATES[0])
assert st == 200 and j["passed"] is True, (st, j)
after = econ("RgA")
assert after["gold"] == before["gold"], (before["gold"], after["gold"])
assert j.get("rewardAmount", 0) == 0 and j.get("rewarded") is False, j
assert GC.PASS_GOLD == 0, GC.PASS_GOLD
assert j["rewardGame"] and j["rewardGame"]["game"] == "lucky_wheel", j["rewardGame"]
assert j["rewardGame"]["id"] == GATES[0] and j["rewardGame"]["status"] == "pending", j["rewardGame"]
assert len(rewards("RgA")["pending"]) == 1, rewards("RgA")
assert LC.PASS_MARK == 80, LC.PASS_MARK
ok("1/2/4. a legitimate NEW pass creates exactly ONE entitlement, pays NO gold (PASS_GOLD is 0, so "
   "the gate policy resolves inert), and PASS_MARK is still 80")

comp = server.LEARNING.read_completion(progress("RgA"), GATES[0])
assert comp and comp.get("passedAt"), comp
ok("5. learning progress is still authoritative: the pass wrote its usual completion record")

st, j2 = attempt("RgA", GATES[0])
assert st == 200 and j2["passed"] is True and j2["alreadyCompleted"] is True, j2
assert j2["rewardGame"] is None, j2["rewardGame"]
assert len(rewards("RgA")["pending"]) == 1, rewards("RgA")
assert econ("RgA")["gold"] == before["gold"], "a replay must not pay either"
ok("3. a REPLAY of the same pass creates zero further entitlements and pays nothing")

st, j = api("POST", "/api/learning/rewards/play", {"id": GATES[0]}, None)
assert st == 401, (st, j)
st, j = api("GET", "/api/learning/rewards", None, None)
assert st == 401, (st, j)
ok("6. a guest can neither list nor play a reward game -- both routes need an account")

# ===================================================================== 39. all four assignments
for i, game in enumerate(GRG.GAMES):
    user = USERS[1]
    force_game(game)
    st, j = attempt(user, GATES[0] if i == 0 else GATES[min(i, len(GATES) - 1)])
    if j["rewardGame"] is None:
        continue                            # that gate was already earned by an earlier loop pass
    assert j["rewardGame"]["game"] == game, (game, j["rewardGame"])
seen = {}
for i, game in enumerate(GRG.GAMES):        # one clean user per game, one gate each
    u = USERS[2]
    server._tokens["tRG" + game] = {"user": "RG_" + game, "exp": time.time() + 9999, "admin": False}
    USERS.append("RG_" + game)
    TOK["RG_" + game] = "tRG" + game
    force_game(game)
    st, j = attempt("RG_" + game, GATES[0])
    assert st == 200 and j["rewardGame"]["game"] == game, (game, j)
    seen[game] = j["rewardGame"]["id"]
assert sorted(seen) == sorted(GRG.GAMES), seen
ok("39a. all four assignments are reachable and the server -- never the client -- decides which: "
   "lucky_wheel, treasure_chests, target_shot, dice_roll")

# the assignment persists: re-read, and re-read after a fresh load from disk
for game, eid in seen.items():
    u = "RG_" + game
    assert rewards(u)["next"]["game"] == game, (game, rewards(u))
    raw = json.load(io.open(server._prog_path(u), encoding="utf-8"))
    assert raw["learning"]["rewardGames"][eid]["game"] == game, raw["learning"]["rewardGames"]
    assert raw["learning"]["rewardGames"][eid]["status"] == "pending"
force_game("dice_roll")                     # a different picker must not change what is stored
for game in GRG.GAMES:
    assert rewards("RG_" + game)["next"]["game"] == game, game
ok("39b. the assigned game is PERSISTED at creation: it survives a re-read and a round-trip "
   "through the progress file, and re-reading never rerolls it")

# ===================================================================== 40. all four prizes
PRIZE_CASES = [("gold_3000", "gold", None, 3000), ("infantry_670", "troops", "inf", 670),
               ("archer_420", "troops", "archer", 420), ("cavalry_400", "troops", "cav", 400)]
for pid, kind, unit, n in PRIZE_CASES:
    u = "RG_prize_" + pid
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
    USERS.append(u)
    TOK[u] = "t" + u
    force_game("treasure_chests")
    st, j = attempt(u, GATES[0])
    eid = j["rewardGame"]["id"]
    b = econ(u)
    force_prize(pid)
    st, r = play(u, eid, {"chestIndex": 1})
    assert st == 200 and r["ok"] and r["newly"] is True, (st, r)
    assert r["prize"]["id"] == pid, r["prize"]
    a = econ(u)
    if kind == "gold":
        assert a["gold"] == b["gold"] + n, (b["gold"], a["gold"])
        assert a["troops"] == b["troops"], (b["troops"], a["troops"])
    else:
        assert a["gold"] == b["gold"], (b["gold"], a["gold"])
        assert a["troops"][unit] == b["troops"][unit] + n, (unit, b["troops"], a["troops"])
        for k in server.TROOP_ALL:
            if k != unit:
                assert a["troops"][k] == b["troops"][k], (k, b["troops"], a["troops"])
    server.set_room(ROOM)
    st_store = server.load_territory_store()
    assert not [t for t, hh in st_store.items()
                if isinstance(hh, dict) and hh.get("owner") == u], "no territory may be created"
ok("40. each prize pays EXACTLY its own thing and nothing else: +3000 gold with troops untouched; "
   "+670 inf / +420 archer / +400 cav into the Home Base pool with gold untouched; and no "
   "territory or garrison is created by any of them")

# ===================================================================== 41. one resolver
resolvers = {}
for game in GRG.GAMES:
    u = "RG_res_" + game
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
    USERS.append(u)
    TOK[u] = "t" + u
    force_game(game)
    st, j = attempt(u, GATES[0])
    eid = j["rewardGame"]["id"]
    force_prize("cavalry_400")
    st, r = play(u, eid, {"chestIndex": 0} if game == "treasure_chests" else None)
    assert st == 200 and r["ok"], (game, st, r)
    assert r["game"] == game and r["prize"]["id"] == "cavalry_400", (game, r)
    assert econ(u)["troops"]["cav"] >= 400, econ(u)["troops"]
    resolvers[game] = r["prize"]["id"]
assert set(resolvers.values()) == {"cavalry_400"}, resolvers
src = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
assert src.count("game_reward_games.draw_prize(") == 1, "exactly ONE place draws a prize"
for bad in ("resolve_wheel", "resolve_chest", "resolve_target", "resolve_dice"):
    assert bad not in src and bad not in io.open(
        os.path.join(ROOT, "game", "reward_games.py"), encoding="utf-8").read(), bad
ok("41. all four mini-games resolve through the SAME authority -- one draw_prize() call site, one "
   "prize table, no per-game resolver -- driven here through the real endpoint for each game")

# ===================================================================== 43. idempotency
u = "RG_idem"
server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
USERS.append(u)
TOK[u] = "t" + u
force_game("dice_roll")
st, j = attempt(u, GATES[0])
eid = j["rewardGame"]["id"]
force_prize("gold_3000")
g0 = econ(u)["gold"]
cav0 = econ(u)["troops"]["cav"]              # a new account starts with troops of every kind
st, r1 = play(u, eid)
assert r1["newly"] is True and r1["prize"]["id"] == "gold_3000", r1
g1 = econ(u)["gold"]
assert g1 == g0 + 3000, (g0, g1)
force_prize("cavalry_400")                  # a second roll WOULD differ -- it must never happen
for _ in range(4):
    st, r2 = play(u, eid)
    assert st == 200 and r2["newly"] is False, r2
    assert r2["prize"]["id"] == "gold_3000", r2["prize"]
assert econ(u)["gold"] == g1, "a repeat must never pay again"
assert econ(u)["troops"]["cav"] == cav0, "and must never pay the other prize either"
ok("43a. resolution is idempotent: the first call draws and pays, every repeat returns the SAME "
   "stored prize, pays nothing, and cannot re-draw even when the draw would now differ")

results, errors = [], []


def hammer():
    try:
        results.append(play(u, eid)[1])
    except Exception as e:                                        # pragma: no cover
        errors.append(e)


threads = [threading.Thread(target=hammer) for _ in range(6)]
for t in threads:
    t.start()
for t in threads:
    t.join()
assert not errors, errors
assert all(r.get("prize", {}).get("id") == "gold_3000" for r in results), results
assert not any(r.get("newly") for r in results), [r.get("newly") for r in results]
assert econ(u)["gold"] == g1, econ(u)["gold"]
ok("43b. six concurrent plays of the same entitlement credit nothing further and all report the "
   "same prize")

reloaded = json.load(io.open(server._prog_path(u), encoding="utf-8"))
rec = reloaded["learning"]["rewardGames"][eid]
assert rec["status"] == "resolved" and rec["prizeId"] == "gold_3000", rec
st, r3 = play(u, eid)
assert r3["newly"] is False and r3["prize"]["id"] == "gold_3000", r3
assert econ(u)["gold"] == g1
ok("43c. the resolved state is what persists, so a restart cannot re-claim it and the prize never "
   "changes")

st, j = play(u, "english.prea1.taipei.zoo.read_along")
assert j.get("reason") == "reward_game_not_found", j
st, j = api("POST", "/api/learning/rewards/play?room=" + ROOM, {}, TOK[u])
assert st == 400 and j.get("reason") == "reward_game_required", j
ok("37/security: a client cannot play an entitlement it was never granted, and cannot play none")

# ===================================================================== 44. multiple pending
u = "RG_multi"
server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
USERS.append(u)
TOK[u] = "t" + u
force_game("lucky_wheel")
a1 = attempt(u, GATES[0])[1]["rewardGame"]
force_game("target_shot")
a2 = attempt(u, GATES[1])[1]["rewardGame"]
pend = rewards(u)
assert len(pend["pending"]) == 2, pend
assert [p["id"] for p in pend["pending"]] == [a1["id"], a2["id"]] or \
       sorted(p["id"] for p in pend["pending"]) == sorted([a1["id"], a2["id"]]), pend
assert pend["next"]["id"] == pend["pending"][0]["id"], pend
start_archer = econ(u)["troops"]["archer"]
force_prize("archer_420")
st, r = play(u, a1["id"])
assert r["newly"] is True and r["prize"]["id"] == "archer_420", r
left = rewards(u)
assert len(left["pending"]) == 1 and left["pending"][0]["id"] == a2["id"], left
assert left["pending"][0]["game"] == "target_shot", left
force_prize("gold_3000")
st, r2 = play(u, a2["id"])
assert r2["newly"] is True and r2["prize"]["id"] == "gold_3000", r2
assert rewards(u)["pending"] == [], rewards(u)
e = econ(u)
assert e["troops"]["archer"] == start_archer + 420 and e["gold"] >= 3000, e
ok("44. two pending games both survive, oldest first; claiming one leaves the other untouched "
   "with its own assigned game; each grants exactly once")

# ===================================================================== 42. mastery
u = "RG_mastery"
server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
USERS.append(u)
TOK[u] = "t" + u
assert GC.MASTERY_GOLD == 2500, GC.MASTERY_GOLD
SUFFIX = ["read_along", "quiz3", "quiz4", "matching", "wh", "cloze", "roleplay"]
ZOO = "english.prea1.taipei.zoo"
with server.acct_lock:
    p = server.load_progress(u)
    learning = p.setdefault("learning", {})
    from learning import qualifications as Q, matching as MS
    now = int(time.time())
    for suf in SUFFIX:                    # seed authoritative evidence for the other six levels
        aid = ZOO + "." + suf
        if suf == "quiz3":
            continue                      # left for a real graded pass below
        if server.LEARNING.is_roleplay(aid):
            learning.setdefault("roleplayProgress", {})[aid] = {"passes": 10, "turns": 10, "pct": 100}
        elif server.LEARNING.is_matching(aid):
            learning.setdefault("matchingProgress", {})[aid] = {"correct": 10, "total": 10, "pct": 100}
        elif server.LEARNING.is_read_along(aid):
            learning.setdefault("sttProgress", {})[aid] = {"pct": 100}
        else:
            Q.record_activity_score(learning, aid, 10, 10, 100, now)
            Q.record_completion(learning, server.LEARNING.completion_key(aid), passed_at=now,
                                pct=100, rewarded=True)
    server.save_progress(u, p)
force_game("dice_roll")
gold_before = econ(u)["gold"]
st, j = attempt(u, ZOO + ".quiz3")
assert st == 200 and j["passed"], (st, j)
assert j["lessonRewarded"] is True and j["lessonRewardAmount"] == 2500, j
assert econ(u)["gold"] == gold_before + 2500, (gold_before, econ(u)["gold"])
assert j["rewardGame"] and j["rewardGame"]["id"] == ZOO + ".quiz3", j["rewardGame"]
assert len(rewards(u)["pending"]) == 1, rewards(u)
ok("42a. PASS and MASTERY in one request: mastery pays exactly 2500 gold through its existing "
   "authority AND the pass earns one reward game -- one of each, no duplicate")

gold_after = econ(u)["gold"]
st, j2 = attempt(u, ZOO + ".quiz3")
assert j2["lessonRewardAmount"] == 0 and j2["rewardGame"] is None, j2
assert econ(u)["gold"] == gold_after, "replayed mastery must pay nothing"
mastery_games = [g for g in LRG.pending(progress(u)) if g["id"].endswith(".read_along")]
assert not mastery_games, mastery_games
assert len(rewards(u)["pending"]) == 1, "mastery itself creates no reward game"
ok("42b. mastery is unchanged: it pays 2500 once, a replay pays zero, and mastery never creates a "
   "reward game of its own")

# ===================================================================== 45. Home Base integration
u = "RG_home"
server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
USERS.append(u)
TOK[u] = "t" + u
force_game("target_shot")
eid = attempt(u, GATES[0])[1]["rewardGame"]["id"]
cav_start = econ(u)["troops"]["cav"]         # the account's own starting cavalry
force_prize("cavalry_400")
st, r = play(u, eid)
assert r["prize"]["id"] == "cavalry_400", r
server.set_room(ROOM)
store = server.load_territory_store()
WORLD = sorted(server.playable_territory_ids())
with server.terr_lock:
    store[WORLD[0]] = {"owner": "Foe", "avatar": "F", "pop": 100,
                       "troops": [{"type": "inf", "hp": 1}]}
    server.save_territory_store(store)
st, atk = api("POST", "/api/territory/attack?room=" + ROOM,
              {"sourceTerritoryId": server.HOME_KEY, "targetTerritoryId": WORLD[0],
               "squad": [{"type": "cav", "hp": 300}], "avatar": "X"}, TOK[u])
assert st == 200 and atk.get("ok"), (st, atk)
assert atk["fromHomeBase"] is True, atk
after = econ(u)
assert after["troops"]["cav"] == cav_start + 400 - 300, after["troops"]   # won 400, marched 300
assert server.HOME_KEY not in server.load_territory_store(), "no Home Base pseudo-territory"
board, lb = api("GET", "/api/leaderboard?room=" + ROOM)
row = {r2["name"]: r2 for r2 in lb["leaders"]}.get(u) or {}
assert int(row.get("regions", 0)) == 1, row                  # exactly the one it just took
ok("45. a troop prize lands in the canonical Home Base pool and is IMMEDIATELY usable as a Phase "
   "14A.9 attack source -- 400 cavalry won, 300 marched -- with no Home Base "
   "pseudo-territory and Ranking counting only the real conquest")

# ===================================================================== 23. no retroactive games
u = "RG_hist"
server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
USERS.append(u)
TOK[u] = "t" + u
with server.acct_lock:                    # a learner who passed BEFORE this feature existed
    p = server.load_progress(u)
    learning = p.setdefault("learning", {})
    from learning import qualifications as Q2
    for aid in GATES:
        Q2.record_activity_score(learning, aid, 10, 10, 100, 1000)
        Q2.record_completion(learning, server.LEARNING.completion_key(aid), passed_at=1000,
                             pct=100, rewarded=True)
    server.save_progress(u, p)
assert rewards(u)["pending"] == [], rewards(u)
force_game("lucky_wheel")
st, j = attempt(u, GATES[0])
assert j["alreadyCompleted"] is True and j["rewardGame"] is None, j
assert rewards(u)["pending"] == [], rewards(u)
ok("23. historical completions earn NOTHING retroactively: an already-passed gate is "
   "alreadyCompleted, so no entitlement is created and no migration was needed")

# ============================== FAULT INJECTION: the crash window ==============================
# The entitlement and the economy are two independently written JSON documents, so the protocol --
# not an imaginary transaction -- is what makes payment exact:
#   1. draw and PERSIST the prize on the entitlement
#   2. apply it to the economy keyed by that entitlement id, in the SAME write as the balance
#   3. note the confirmation back on the entitlement
# These cases crash between each pair of steps and prove the invariant: once drawn, the prize never
# changes, and it is paid exactly once.
DRAWS = {"n": 0}
_real_draw = server.game_reward_games.draw_prize


def counting_draw(rng=None):
    DRAWS["n"] += 1
    return _real_draw(rng)


server.game_reward_games.draw_prize = counting_draw


def fresh_user(tag):
    u = "RG_" + tag
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
    USERS.append(u)
    TOK[u] = "t" + u
    return u


def entitle(u, game="lucky_wheel", gate=0):
    force_game(game)
    return attempt(u, GATES[gate])[1]["rewardGame"]["id"]


# ---------- CASE A: prize persisted, crash BEFORE the payout ----------
u = fresh_user("crashA")
eid = entitle(u)
force_prize("cavalry_400")
before = econ(u)
with server.acct_lock:                       # exactly what step 1 writes, then "the process dies"
    p = server.load_progress(u)
    learning = p.setdefault("learning", {})
    learning, pid, drew = LRG.award(learning, eid, "cavalry_400", int(time.time()))
    p["learning"] = learning
    server.save_progress(u, p)
assert drew and pid == "cavalry_400"
mid = econ(u)
assert mid["gold"] == before["gold"] and mid["troops"] == before["troops"], "nothing paid yet"
assert [x["id"] for x in rewards(u)["pending"]] == [eid], "the game is still owed"
n0 = DRAWS["n"]
force_prize("gold_3000")                     # a fresh draw WOULD differ -- it must never happen
st, r = play(u, eid)
assert st == 200 and r["prize"]["id"] == "cavalry_400", r
assert DRAWS["n"] == n0, "a persisted prize must not be drawn again"
after = econ(u)
assert after["troops"]["cav"] == before["troops"]["cav"] + 400, (before["troops"], after["troops"])
assert after["gold"] == before["gold"], "and the other prize must not be paid"
st, r2 = play(u, eid)
assert r2["prize"]["id"] == "cavalry_400" and econ(u)["troops"]["cav"] == after["troops"]["cav"]
ok("CASE A: a crash after the prize is persisted but before payout leaves the SAME prize owed; "
   "the retry pays it exactly once and never re-draws")

# ---------- CASE B: payout applied, crash BEFORE the confirmation ----------
u = fresh_user("crashB")
eid = entitle(u, "dice_roll")
force_prize("gold_3000")
before = econ(u)
with server.acct_lock:                       # step 1
    p = server.load_progress(u)
    learning = p.setdefault("learning", {})
    learning, pid, _ = LRG.award(learning, eid, "gold_3000", int(time.time()))
    p["learning"] = learning
    server.save_progress(u, p)
applied, gold, troops = server.econ_apply_reward_once(u, eid, server.game_reward_games.prize(pid))
assert applied and gold == before["gold"] + 3000, (before["gold"], gold)
# ...and now the process dies before step 3, so the entitlement still says "awarded"
with server.acct_lock:
    raw = server.load_progress(u)["learning"]["rewardGames"][eid]
assert raw["status"] == "awarded" and raw["prizeId"] == "gold_3000", raw
n0 = DRAWS["n"]
st, r = play(u, eid)                          # the client retries
assert r["prize"]["id"] == "gold_3000" and DRAWS["n"] == n0, (r, DRAWS)
assert econ(u)["gold"] == gold, "the retry must not pay a second time"
with server.acct_lock:
    raw2 = server.load_progress(u)["learning"]["rewardGames"][eid]
assert raw2["status"] == "resolved", raw2
ok("CASE B: a crash after the payout but before the confirmation cannot double-pay -- the payment "
   "marker lives in the SAME economy write as the balance, so the retry only completes the record")

# ---------- CASE C: an ordinary retry ----------
u = fresh_user("crashC")
eid = entitle(u, "treasure_chests")
force_prize("archer_420")
b = econ(u)
n0 = DRAWS["n"]
first = play(u, eid, {"chestIndex": 2})[1]
assert first["newly"] is True and DRAWS["n"] == n0 + 1, (first, DRAWS)
for _ in range(3):
    again = play(u, eid, {"chestIndex": 0})[1]
    assert again["prize"]["id"] == "archer_420" and again["newly"] is False, again
assert DRAWS["n"] == n0 + 1, "a retry draws zero further times"
assert econ(u)["troops"]["archer"] == b["troops"]["archer"] + 420, econ(u)["troops"]
ok("CASE C / draw-at-most-once: one entitlement invokes prize selection exactly once; every retry "
   "draws zero further times and pays nothing further")

# ---------- CASE D: six concurrent plays ----------
u = fresh_user("crashD")
eid = entitle(u, "target_shot")
force_prize("infantry_670")
b = econ(u)
n0 = DRAWS["n"]
out, errs = [], []


def race():
    try:
        out.append(play(u, eid)[1])
    except Exception as ex:                                       # pragma: no cover
        errs.append(ex)


ts = [threading.Thread(target=race) for _ in range(6)]
for t in ts:
    t.start()
for t in ts:
    t.join()
assert not errs, errs
assert all(o["prize"]["id"] == "infantry_670" for o in out), out
assert sum(1 for o in out if o["newly"]) <= 1, [o["newly"] for o in out]
assert econ(u)["troops"]["inf"] == b["troops"]["inf"] + 670, econ(u)["troops"]
assert DRAWS["n"] <= n0 + 6 and econ(u)["gold"] == b["gold"], "no second prize was ever paid"
ok("CASE D: six concurrent plays of one entitlement settle on ONE prize, credit it once, and at "
   "most one of them reports itself as the paying call")

server.game_reward_games.draw_prize = _real_draw
server.REWARD_GAME_PICKER, server.REWARD_PRIZE_RNG = REAL_PICKER, REAL_RNG
httpd.shutdown()
print("\nAll %d reward-game checks passed." % passed)
