# Phase 14A.5 — RANKING POPULATION IS THE WHOLE EMPIRE.
#
#   python tests/ranking_population_test.py
#
# A player reported that Ranking Population looked like the Home Base figure alone. It was:
# /api/leaderboard published `estore[user]["population"]` and nothing else, so conquering half a
# continent did not move a player's rank. Worse, the client then INVENTED rows for territory owners
# missing from that list (the AI empires) whose population was the SUM of their territories — so one
# column meant two different things depending on the row.
#
# THE CANONICAL MODEL, pinned from the domain rather than from a label:
#
#   * every owned territory carries its own `pop` in the ROOM's territory store;
#   * Home Base is NOT a territory-store entry — it is the economy record's `population`;
#   * game.economy.calculate_passive_gold() earns on (population + region_pop), i.e. the home base
#     PLUS every owned territory. That is the game's own definition of the empire that produces, and
#     it is what a rank called Population must mean;
#   * AI players are built the same way (ai_econ gives them a base population and the same
#     region_pop gold), so the same formula applies to them.
#
# Empire Population = home base population + SUM(pop of every territory owned in the CURRENT ROOM)
#
# Sort keys are unchanged: population desc, territories desc, name asc.
import io, json, os, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server                                                   # noqa: E402
from game import economy as game_economy                        # noqa: E402
from territory_catalog import catalog as CAT                     # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


DATA = tempfile.mkdtemp(prefix="rankpop145_")
server.ROOMS_DIR = os.path.join(DATA, "rooms")
server.ACCT = os.path.join(DATA, "accounts.json")
server.DATA = os.path.join(DATA, "visits.json")
server.TERR_CATALOG = os.path.join(DATA, "learned.json")
server.PROG_DIR = os.path.join(DATA, "progress")
os.makedirs(server.ROOMS_DIR, exist_ok=True)
os.makedirs(server.PROG_DIR, exist_ok=True)
USERS = ["RankA", "RankB", "RankC"]
json.dump({"users": {u: {} for u in USERS}, "codes": {}},
          io.open(server.ACCT, "w", encoding="utf-8"))
for u in USERS:
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
TOK = {u: "t" + u for u in USERS}

httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT


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


def board(room):
    st, j = api("GET", "/api/leaderboard?room=" + room)
    assert st == 200, (st, j)
    return {r["name"]: r for r in j["leaders"]}, j["leaders"]


def store(room):
    server.set_room(room)
    return server.load_territory_store()


def set_pop(room, tid, owner, pop, avatar="X"):
    """Write ownership + population straight into the room's authoritative store, so the acceptance
    numbers are exact. Ownership and pop are the very fields the ranking must read."""
    server.set_room(room)
    with server.terr_lock:
        s = server.load_territory_store()
        h = s.get(tid) or {}
        h.update({"owner": owner, "avatar": avatar, "pop": pop,
                  "troops": h.get("troops") or [{"type": "inf", "hp": 1}]})
        s[tid] = h
        server.save_territory_store(s)


def base_pop(room, user):
    server.set_room(room)
    with server.econ_lock:
        e = server.load_econ_store().get(user)
    return server.clampi((e or {}).get("population", server.ECON_START_POP)) if isinstance(e, dict) \
        else server.ECON_START_POP


if not CAT.loaded:
    CAT.load()
WORLD = sorted(t for t, rec in CAT.territories.items() if rec.get("mapId") == "world")
A, B, C, D = WORLD[0], WORLD[1], WORLD[2], WORLD[3]

st, j = api("POST", "/api/room/create", {}, TOK["RankA"])
assert st == 200, (st, j)
st, j = api("POST", "/api/room/start",
            {"map": "A1", "aiCount": 0, "resources": "high", "capacity": 4}, TOK["RankA"])
assert st == 200, (st, j)
ROOM = j["code"]
for u in ("RankB", "RankC"):
    assert api("POST", "/api/room/enter", {"room": ROOM}, TOK[u])[0] == 200

# every account gets an economy record in this room, so `base` below is a real stored figure
for u in USERS:
    assert api("GET", "/api/economy?room=" + ROOM, None, TOK[u])[0] == 200

# =========================================================== 1. the domain model, pinned
assert "population" in game_economy.calculate_passive_gold.__doc__
assert "region_pop" in game_economy.calculate_passive_gold.__doc__
g1, _ = game_economy.calculate_passive_gold(0, 100, 0, 0, 10 ** 9)
g2, _ = game_economy.calculate_passive_gold(0, 0, 100, 0, 10 ** 9)
assert g1 == g2 and g1 > 0, (g1, g2)
ok("1. the domain earns identically on home-base population and territory population — the empire "
   "that produces is base + territories, which is what a rank called Population must mean")

# =========================================================== 2. the controlled 100 + 200 + 300
for tid, pop in ((A, 100), (B, 200), (C, 300)):
    set_pop(ROOM, tid, "RankA", pop)
rows, _ = board(ROOM)
baseA = base_pop(ROOM, "RankA")
assert server.user_region_pop(store(ROOM), "RankA") == 600, server.user_region_pop(store(ROOM), "RankA")
assert rows["RankA"]["population"] == baseA + 600, (rows["RankA"], baseA)
assert rows["RankA"]["regions"] == 3, rows["RankA"]
ok("2. three owned territories of 100 + 200 + 300 contribute exactly 600 to the ranking "
   "(base %d + 600 = %d), with 3 territories held" % (baseA, rows["RankA"]["population"]))

# =========================================================== 3. Home Base counted exactly once
assert C not in ("@home", server.HOME_KEY if hasattr(server, "HOME_KEY") else "@home")
assert "@home" not in store(ROOM), "Home Base must not be an entry in the territory store"
assert rows["RankA"]["population"] - 600 == baseA, "the base appears exactly once, not twice"
ok("3. Home Base is a separate economy record, is absent from the territory store, and is added "
   "exactly once (base %d)" % baseA)

# =========================================================== 4. an occupied neutral contributes
set_pop(ROOM, D, "RankA", 55)
rows, _ = board(ROOM)
assert rows["RankA"]["population"] == baseA + 655, rows["RankA"]
assert rows["RankA"]["regions"] == 4
ok("4. occupying a further territory adds its population to the total (+55 -> %d)"
   % rows["RankA"]["population"])

# =========================================================== 5. conquest transfers the contribution
set_pop(ROOM, C, "RankB", 300)          # C changes hands, population unchanged
rows, _ = board(ROOM)
baseB = base_pop(ROOM, "RankB")
assert rows["RankA"]["population"] == baseA + 355, rows["RankA"]     # 100+200+55
assert rows["RankA"]["regions"] == 3, rows["RankA"]
assert rows["RankB"]["population"] == baseB + 300, rows["RankB"]
assert rows["RankB"]["regions"] == 1, rows["RankB"]
ok("5. a conquered territory's 300 leaves the former owner and arrives at the new one, following "
   "canonical ownership")

# =========================================================== 6. a lost territory stops counting
server.set_room(ROOM)
with server.terr_lock:
    s = server.load_territory_store()
    s[D] = {"owner": None, "pop": 55, "troops": []}
    server.save_territory_store(s)
rows, _ = board(ROOM)
assert rows["RankA"]["population"] == baseA + 300, rows["RankA"]     # 100 + 200
assert rows["RankA"]["regions"] == 2, rows["RankA"]
ok("6. a territory that is no longer owned stops contributing entirely")

# =========================================================== 7. room isolation
# a second room must be hosted by someone else: /api/room/create returns the host's existing room
st, j = api("POST", "/api/room/create", {}, TOK["RankB"])
assert st == 200, (st, j)
st, j = api("POST", "/api/room/start",
            {"map": "A1", "aiCount": 0, "resources": "high", "capacity": 4}, TOK["RankB"])
assert st == 200, (st, j)
ROOM2 = j["code"]
assert ROOM2 != ROOM, (ROOM, ROOM2)
assert api("POST", "/api/room/enter", {"room": ROOM2}, TOK["RankA"])[0] == 200
assert api("GET", "/api/economy?room=" + ROOM2, None, TOK["RankA"])[0] == 200
set_pop(ROOM2, A, "RankA", 7)
r1, _ = board(ROOM)
r2, _ = board(ROOM2)
base2 = base_pop(ROOM2, "RankA")
assert r1["RankA"]["population"] == baseA + 300 and r1["RankA"]["regions"] == 2, r1["RankA"]
assert r2["RankA"]["population"] == base2 + 7 and r2["RankA"]["regions"] == 1, r2["RankA"]
ok("7. the two rooms rank independently — %d/%d territories here, %d/%d there, no leakage"
   % (r1["RankA"]["population"], r1["RankA"]["regions"],
      r2["RankA"]["population"], r2["RankA"]["regions"]))

# =========================================================== 8. AI means the same thing
AI = "AI 1"
set_pop(ROOM, D, AI, 400, avatar="🤖")
rows, order = board(ROOM)
assert AI in rows, sorted(rows)
assert rows[AI]["regions"] == 1
assert rows[AI]["population"] == server.user_region_pop(store(ROOM), AI) + \
    (server.clampi((server.load_econ_store().get(AI) or {}).get("population", 0))
     if isinstance(server.load_econ_store().get(AI), dict) else 0), rows[AI]
assert rows[AI]["population"] == 400, rows[AI]      # no economy record yet -> territories only
ok("8. an AI empire is ranked by the SAME formula and is published by the server, not invented by "
   "the client (AI population %d from its own ground)" % rows[AI]["population"])

# an AI that HAS an economy record contributes its base too, exactly like a human
server.set_room(ROOM)
with server.econ_lock:
    es = server.load_econ_store()
    es[AI] = {"population": 90, "gold": 0, "lastGold": time.time(), "troops": server._norm_troops(0)}
    server.save_econ_store(es)
rows, _ = board(ROOM)
assert rows[AI]["population"] == 90 + 400, rows[AI]
ok("8b. ...and once that AI has an economy record its base counts too — one rule for every row")

# =========================================================== 9/10/11. the sort keys
def rank_with(pairs):
    """pairs: {user: (population_target, territory_count)} -> ordered names from the server."""
    server.set_room(ROOM)
    with server.terr_lock:
        s = server.load_territory_store()
        for t in list(s):
            s[t] = {"owner": None, "pop": 0, "troops": []}
        server.save_territory_store(s)
    with server.econ_lock:
        es = server.load_econ_store()
        for u in USERS:
            es[u] = {"population": 0, "gold": 0, "lastGold": time.time(),
                     "troops": server._norm_troops(0)}
        es.pop(AI, None)
        server.save_econ_store(es)
    idx = 0
    for user, (pop, n) in pairs.items():
        per = pop // n
        rest = pop - per * (n - 1)
        for k in range(n):
            set_pop(ROOM, WORLD[10 + idx], user, per if k < n - 1 else rest)
            idx += 1
    _, order = board(ROOM)
    return [r["name"] for r in order if r["name"] in pairs], {r["name"]: r for r in order}


names, rows = rank_with({"RankA": (1000, 2), "RankB": (900, 10)})
assert rows["RankA"]["population"] == 1000 and rows["RankB"]["population"] == 900
assert names.index("RankA") < names.index("RankB"), names
ok("9. population is the PRIMARY key: 1000/2 territories outranks 900/10")

names, rows = rank_with({"RankA": (1000, 2), "RankB": (1000, 3)})
assert rows["RankA"]["population"] == rows["RankB"]["population"] == 1000
assert names.index("RankB") < names.index("RankA"), names
ok("10. territories held is the SECONDARY key: on equal population, 3 outranks 2")

names, rows = rank_with({"RankC": (500, 2), "RankA": (500, 2)})
assert rows["RankA"]["population"] == rows["RankC"]["population"] == 500
assert names.index("RankA") < names.index("RankC"), names
ok("11. name ascending is the TERTIARY key: RankA before RankC on an exact tie")

# =========================================================== 12. no client-side ranking authority
client = io.open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
code = "\n".join(l for l in client.split("\n") if not l.lstrip().startswith("//"))
assert "botPop" not in code and "botAva" not in code, \
    "the client must not maintain its own population figures for any row"
assert "p.population == null" not in code, "no invented default population"
assert 'fetch(withRoom("/api/leaderboard"))' in code, "the Ranking must be fetched for the room"
assert code.count('fetch(withRoom("/api/leaderboard"))') == 1, "exactly one leaderboard fetch"
assert 'fetch("/api/leaderboard")' not in code, "no room-less leaderboard fetch survives"
ok("12. the client keeps no population model of its own and asks for the CURRENT room's ranking")

httpd.shutdown()
print("\nAll %d ranking-population tests passed." % passed)
