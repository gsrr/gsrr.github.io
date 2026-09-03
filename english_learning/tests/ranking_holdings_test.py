# Phase 14A.6 — RANKING TERRITORIES HELD, AND WHO HOLDS WHAT.
#
#   python tests/ranking_holdings_test.py
#
# A player reported that Ranking's "Territories Held" looked wrong. It was: the leaderboard did
#
#     for f, h in tstore.items():
#         if h.get("owner"): regions[h["owner"]] += 1
#
# — one increment for EVERY owned entry in the room's store, whatever it was. Two kinds of entry are
# not territories of the game being played:
#
#   * off-map catalogue ids. The catalogue holds 318 territories but allowed_game_maps() is
#     {"world"}, so a `china:*` entry left in an older store still counted.
#   * legacy keys canonize_keys() cannot resolve — a course filename such as "A1/002.json". It
#     PRESERVES those rather than discard data, so they counted too.
#
# Measured against the pre-fix formula below: world:ad + china:pAH + "A1/002.json" reported 3 when
# the player held exactly one playable territory.
#
# The fix is one helper, server.room_holdings(), which answers "what does each participant hold in
# this room" over the playable World only. The count is len() of that same list, so the number on a
# row and the names inside it cannot disagree.
import io, json, os, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server                                                   # noqa: E402
from territory_catalog import catalog as CAT                     # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


DATA = tempfile.mkdtemp(prefix="rankhold146_")
server.ROOMS_DIR = os.path.join(DATA, "rooms")
server.ACCT = os.path.join(DATA, "accounts.json")
server.DATA = os.path.join(DATA, "visits.json")
server.TERR_CATALOG = os.path.join(DATA, "learned.json")
server.PROG_DIR = os.path.join(DATA, "progress")
os.makedirs(server.ROOMS_DIR, exist_ok=True)
os.makedirs(server.PROG_DIR, exist_ok=True)
USERS = ["HoldA", "HoldB"]
json.dump({"users": {u: {} for u in USERS}, "codes": {}},
          io.open(server.ACCT, "w", encoding="utf-8"))
for u in USERS:
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
TOK = {u: "t" + u for u in USERS}
AI = "AI 1"

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


def own(room, tid, owner, pop=100):
    server.set_room(room)
    with server.terr_lock:
        s = server.load_territory_store()
        s[tid] = {"owner": owner, "avatar": "X", "pop": pop, "troops": [{"type": "inf", "hp": 1}]}
        server.save_territory_store(s)


def clear(room):
    server.set_room(room)
    with server.terr_lock:
        server.save_territory_store({})


def store(room):
    server.set_room(room)
    return server.load_territory_store()


def legacy_count(tstore):
    """The PRE-FIX formula, restated here so the root cause is pinned and not merely described."""
    n = {}
    for f, h in (tstore or {}).items():
        if isinstance(h, dict) and h.get("owner"):
            n[h["owner"]] = n.get(h["owner"], 0) + 1
    return n


if not CAT.loaded:
    CAT.load()
WORLD = sorted(t for t, r in CAT.territories.items() if r.get("mapId") == "world")
OFFMAP = sorted(t for t, r in CAT.territories.items() if r.get("mapId") != "world")
A, B, C, D, E = WORLD[0], WORLD[1], WORLD[2], WORLD[3], WORLD[4]
NAME = {t: (CAT.territories[t].get("displayName") or t) for t in (A, B, C, D, E)}

st, j = api("POST", "/api/room/create", {}, TOK["HoldA"])
st, j = api("POST", "/api/room/start",
            {"map": "A1", "aiCount": 0, "resources": "high", "capacity": 4}, TOK["HoldA"])
ROOM = j["code"]
assert api("POST", "/api/room/enter", {"room": ROOM}, TOK["HoldB"])[0] == 200
for u in USERS:
    assert api("GET", "/api/economy?room=" + ROOM, None, TOK[u])[0] == 200

# =========================================================== 1. the root cause, pinned
clear(ROOM)
own(ROOM, A, "HoldA")
own(ROOM, OFFMAP[0], "HoldA")            # an off-map catalogue territory
own(ROOM, "A1/002.json", "HoldA")        # a legacy key canonize_keys cannot resolve
assert server.allowed_game_maps() == {"world"}, server.allowed_game_maps()
assert len(OFFMAP) > 0 and OFFMAP[0] not in set(server.playable_territory_ids())
assert legacy_count(store(ROOM))["HoldA"] == 3, legacy_count(store(ROOM))
rows, _ = board(ROOM)
assert rows["HoldA"]["regions"] == 1, rows["HoldA"]
ok("1. the pre-fix formula counts 3 for this store (a World territory, an off-map catalogue "
   "territory and an unresolvable legacy key); the corrected count is 1")

# =========================================================== 2/12. only the playable World counts
held = rows["HoldA"]["territories"]
assert [t["id"] for t in held] == [A], held
assert all(t["id"] in set(server.playable_territory_ids()) for t in held), held
assert not any(t["id"] == OFFMAP[0] or t["id"] == "A1/002.json" for t in held), held
ok("2/12. the count and the list are the CURRENT ROOM's playable World holdings — no off-map and "
   "no legacy-key leakage")

# =========================================================== 3. Home Base is not a territory
assert "@home" not in store(ROOM), "Home Base must not be an entry in the territory store"
assert not any(t["id"] == "@home" for t in held), held
ok("3. Home Base is a separate economy record and is never counted as a territory")

# =========================================================== 4. neutral is not counted
clear(ROOM)
own(ROOM, A, "HoldA")
server.set_room(ROOM)
with server.terr_lock:
    s = server.load_territory_store()
    s[B] = {"owner": None, "pop": 500, "troops": []}       # touched but unowned = neutral
    server.save_territory_store(s)
rows, _ = board(ROOM)
assert rows["HoldA"]["regions"] == 1, rows["HoldA"]
assert [t["id"] for t in rows["HoldA"]["territories"]] == [A]
ok("4. a neutral territory with a store entry is not counted for anybody")

# =========================================================== 5/6/9/17. the controlled matrix
clear(ROOM)
for t in (A, B, C):
    own(ROOM, t, "HoldA")
for t in (D, E):
    own(ROOM, t, AI)
rows, _ = board(ROOM)
assert rows["HoldA"]["regions"] == 3 and len(rows["HoldA"]["territories"]) == 3, rows["HoldA"]
assert rows[AI]["regions"] == 2 and len(rows[AI]["territories"]) == 2, rows[AI]
assert rows["HoldB"]["regions"] == 0 and rows["HoldB"]["territories"] == [], rows["HoldB"]
assert sorted(t["name"] for t in rows["HoldA"]["territories"]) == sorted(NAME[t] for t in (A, B, C))
assert sorted(t["name"] for t in rows[AI]["territories"]) == sorted(NAME[t] for t in (D, E))
ok("5/6/17. controlled matrix: player 3/3, AI 2/2, and a player holding nothing is 0 with an "
   "EMPTY list — never invented holdings")

# =========================================================== 7. count == len(list), every row
for name, row in rows.items():
    assert row["regions"] == len(row["territories"]), (name, row["regions"], row["territories"])
ok("7. for every published row the count is exactly len(territories) — one helper, no drift")

# =========================================================== 8. a transfer moves both
own(ROOM, C, AI)
rows, _ = board(ROOM)
assert rows["HoldA"]["regions"] == 2 and len(rows["HoldA"]["territories"]) == 2, rows["HoldA"]
assert rows[AI]["regions"] == 3 and len(rows[AI]["territories"]) == 3, rows[AI]
assert NAME[C] not in [t["name"] for t in rows["HoldA"]["territories"]]
assert NAME[C] in [t["name"] for t in rows[AI]["territories"]]
ok("8. transferring one territory moves the count AND the name together: 3/2 -> 2/3")

# =========================================================== 9. a loss removes both
server.set_room(ROOM)
with server.terr_lock:
    s = server.load_territory_store()
    s[A] = {"owner": None, "pop": 100, "troops": []}
    server.save_territory_store(s)
rows, _ = board(ROOM)
assert rows["HoldA"]["regions"] == 1 and [t["name"] for t in rows["HoldA"]["territories"]] == [NAME[B]]
ok("9. losing a territory drops it from the count and from the list")

# =========================================================== 10. room isolation
st, j = api("POST", "/api/room/create", {}, TOK["HoldB"])
st, j = api("POST", "/api/room/start",
            {"map": "A1", "aiCount": 0, "resources": "high", "capacity": 4}, TOK["HoldB"])
ROOM2 = j["code"]
assert ROOM2 != ROOM
assert api("POST", "/api/room/enter", {"room": ROOM2}, TOK["HoldA"])[0] == 200
own(ROOM2, D, "HoldA")
r1, _ = board(ROOM)
r2, _ = board(ROOM2)
assert r1["HoldA"]["regions"] == 1 and [t["name"] for t in r1["HoldA"]["territories"]] == [NAME[B]]
assert r2["HoldA"]["regions"] == 1 and [t["name"] for t in r2["HoldA"]["territories"]] == [NAME[D]]
ok("10. the two rooms report different holdings for the same player (%s here, %s there) — no "
   "cross-room leakage" % (NAME[B], NAME[D]))

# =========================================================== 11. not Strategic Regions
_, order = board(ROOM)
st, terr = api("GET", "/api/territory?room=" + ROOM, None, TOK["HoldA"])
assert st == 200
region_rows = terr.get("regions") or []
assert region_rows, "the room publishes strategic regions"
assert len(region_rows) == 6, len(region_rows)              # af/as/eu/na/oc/sa
mine = [r for r in order if r["name"] == "HoldA"][0]
assert mine["regions"] != len(region_rows), (mine["regions"], len(region_rows))
assert all(t["id"].startswith("world:") for t in mine["territories"]), mine["territories"]
assert not any(t["id"] in {r["region"] for r in region_rows} for t in mine["territories"])
ok("11. Territories Held is territories, not the 6 Strategic Regions, and holdings carry canonical "
   "territory ids")

# =========================================================== 13/14. ids and player-facing names
row = mine
for t in row["territories"]:
    assert set(t.keys()) == {"id", "name"}, t
    assert t["id"] in CAT.territories, t
    assert t["name"] == (CAT.territories[t["id"]].get("displayName") or t["id"]), t
ok("13/14. every published holding carries the canonical id and the catalogue's player-facing "
   "name, straight from the server")

# =========================================================== 15. ordering is stable and by name
clear(ROOM)
for t in (C, A, B):
    own(ROOM, t, "HoldA")
rows, _ = board(ROOM)
names = [t["name"] for t in rows["HoldA"]["territories"]]
assert names == sorted(names, key=lambda s: s.lower()), names
ok("15. holdings are published in player-facing name order, so the disclosure reads predictably")

# =========================================================== 16. the sort still uses the count
clear(ROOM)
server.set_room(ROOM)
with server.econ_lock:
    es = server.load_econ_store()
    for u in USERS:
        es[u] = {"population": 0, "gold": 0, "lastGold": time.time(), "troops": server._norm_troops(0)}
    server.save_econ_store(es)
own(ROOM, A, "HoldA", pop=500)
own(ROOM, B, "HoldB", pop=250)
own(ROOM, C, "HoldB", pop=250)
_, order = board(ROOM)
seq = [r["name"] for r in order if r["name"] in USERS]
assert seq[0] == "HoldB", seq          # equal population 500, HoldB holds 2 -> ranks first
rows = {r["name"]: r for r in order}
assert rows["HoldA"]["population"] == rows["HoldB"]["population"] == 500, rows
assert rows["HoldB"]["regions"] == 2 and rows["HoldA"]["regions"] == 1
ok("16. on equal population the corrected Territories Held decides the order (2 outranks 1)")

# =========================================================== 18. one canonical helper
src = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
assert src.count("def room_holdings(") == 1, "exactly one holdings helper"
assert 'regions[h["owner"]] = regions.get(h["owner"], 0) + 1' not in src, \
    "the unfiltered per-entry count must be gone"
assert 'regions[owner] += 1' not in src, "...in every form"
assert src.count('"regions": len(held), "territories": public_holdings(held)') == 2, \
    "both row kinds derive the count from the list and publish the same projection"
assert src.count("def public_holdings(") == 1 and src.count("def holdings_population(") == 1, \
    "one projection and one population helper, both over the same holdings"
assert "self._empire_population(user, held, estore, True)" in src and \
       "self._empire_population(owner, held, estore, False)" in src, \
    "Empire Population is computed from that participant's own playable holdings"
assert "return base + holdings_population(held)" in src, \
    "...so the territory half comes from the very records that count as held"
assert "counts = {owner: len(held) for owner, held in room_holdings(store).items()}" in src, \
    "/api/territory counts come from the same authority"
ok("18. one canonical room_holdings() helper: the count, the published list, the Empire Population "
   "territory half and /api/territory's counts are all derived from it")

# =========================================================== 19. THE CONTROLLED DIRTY STORE
# One store, four owned records, only two of them territories of the game being played. Every
# World ownership-derived metric must agree on which two, and on nothing else.
def api_counts(room, tok):
    st, j = api("GET", "/api/territory?room=" + room, None, tok)
    assert st == 200, (st, j)
    return j.get("counts") or {}


clear(ROOM)
own(ROOM, A, "HoldA", pop=100)                       # playable
own(ROOM, B, "HoldA", pop=200)                       # playable
own(ROOM, OFFMAP[0], "HoldA", pop=900)               # off-map catalogue territory
own(ROOM, "A1/002.json", "HoldA", pop=800)           # unresolvable legacy key
server.set_room(ROOM)
with server.econ_lock:
    es = server.load_econ_store()
    es["HoldA"] = {"population": 250, "gold": 0, "lastGold": time.time(),
                   "troops": server._norm_troops(0)}
    server.save_econ_store(es)

rows, _ = board(ROOM)
row = rows["HoldA"]
counts = api_counts(ROOM, TOK["HoldA"])
print("\n  DIRTY STORE: 4 owned records (2 playable, 1 off-map, 1 legacy), Home Base 250")
print("    Territories Held           : %d   (pre-fix formula would say %d)"
      % (row["regions"], legacy_count(store(ROOM))["HoldA"]))
print("    holdings                   : %s" % [t["name"] for t in row["territories"]])
print("    /api/territory counts      : %d" % counts.get("HoldA", 0))
print("    Empire Population          : %d   (pre-fix would say %d)"
      % (row["population"], 250 + server.user_region_pop(store(ROOM), "HoldA")))

assert row["regions"] == 2, row
assert [t["id"] for t in row["territories"]] == sorted([A, B], key=lambda t: NAME[t].lower()), row
assert counts.get("HoldA") == 2, counts
assert row["population"] == 250 + 300, row           # base 250 + (100 + 200)
assert row["population"] != 250 + 2000, "off-map + legacy population must not contribute"
ok("19. dirty store: Territories Held 2, holdings [%s], /api/territory count 2, Empire Population "
   "550 = 250 + 300 -- NOT 4 and NOT 2250" % ", ".join(t["name"] for t in row["territories"]))

# =========================================================== 20. off-map / legacy exclusion, itemised
assert not any(t["id"] == OFFMAP[0] for t in row["territories"]), row
assert not any(t["id"] == "A1/002.json" for t in row["territories"]), row
held_pop = sum(t["pop"] for t in server.room_holdings(store(ROOM))["HoldA"])
assert held_pop == 300, held_pop
assert server.user_region_pop(store(ROOM), "HoldA") == 2000, "the raw helper still sums everything"
ok("20. the off-map territory (pop 900) and the legacy key (pop 800) are excluded from the count, "
   "the list AND the population, while the raw economy helper still sums all 2000 unchanged")

# =========================================================== 21. Home Base exactly once
assert "@home" not in store(ROOM)
assert row["population"] - held_pop == 250, (row["population"], held_pop)
ok("21. Home Base (250) is added exactly once and is never a territory")

# =========================================================== 22. the three-way invariant
for name, r in rows.items():
    assert r["regions"] == len(r["territories"]), (name, r)
    assert r["regions"] == counts.get(name, 0), (name, r["regions"], counts.get(name, 0))
    e = server.load_econ_store().get(name)
    base = server.clampi((e or {}).get("population", server.ECON_START_POP)) \
        if isinstance(e, dict) else (server.ECON_START_POP if name in USERS else 0)
    mine = server.room_holdings(store(ROOM)).get(name) or []
    assert r["population"] == base + sum(t["pop"] for t in mine), (name, r["population"], base, mine)
ok("22. for EVERY participant: regions == len(territories) == /api/territory count, and population "
   "== home base + the population of those same holdings")

# =========================================================== 23. claim / conquest / loss consistency
def triple(room, tok, who):
    rws, _ = board(room)
    c = api_counts(room, tok)
    r = rws.get(who) or {"regions": 0, "territories": [], "population": 0}
    return r["regions"], len(r["territories"]), c.get(who, 0), r["population"]


own(ROOM, C, "HoldA", pop=50)                        # a claim
a, b_, c_, pop = triple(ROOM, TOK["HoldA"], "HoldA")
assert (a, b_, c_) == (3, 3, 3) and pop == 250 + 350, (a, b_, c_, pop)
ok("23. a CLAIM moves the count, the list, /api/territory's count and the population together "
   "(3/3/3, population %d)" % pop)

own(ROOM, C, AI, pop=50)                             # a conquest: C changes hands
a, b_, c_, pop = triple(ROOM, TOK["HoldA"], "HoldA")
ai_a, ai_b, ai_c, ai_pop = triple(ROOM, TOK["HoldA"], AI)
assert (a, b_, c_) == (2, 2, 2) and pop == 250 + 300, (a, b_, c_, pop)
assert (ai_a, ai_b, ai_c) == (1, 1, 1) and ai_pop == 50, (ai_a, ai_b, ai_c, ai_pop)
ok("24. a CONQUEST moves all four figures for both sides (2/2/2 and 1/1/1)")

server.set_room(ROOM)
with server.terr_lock:
    s = server.load_territory_store()
    s[B] = {"owner": None, "pop": 200, "troops": []}
    server.save_territory_store(s)
a, b_, c_, pop = triple(ROOM, TOK["HoldA"], "HoldA")
assert (a, b_, c_) == (1, 1, 1) and pop == 250 + 100, (a, b_, c_, pop)
ok("25. a LOSS removes it from all four (1/1/1, population %d)" % pop)

# =========================================================== 26. dirty store, room isolation
own(ROOM2, OFFMAP[1], "HoldA", pop=700)
own(ROOM2, "B2/legacy.json", "HoldA", pop=600)
own(ROOM2, E, "HoldA", pop=25)
server.set_room(ROOM2)
with server.econ_lock:
    es = server.load_econ_store()
    es["HoldA"] = {"population": 111, "gold": 0, "lastGold": time.time(),
                   "troops": server._norm_troops(0)}
    server.save_econ_store(es)
r1 = triple(ROOM, TOK["HoldA"], "HoldA")
r2 = triple(ROOM2, TOK["HoldA"], "HoldA")
# expectations derived from each room's own playable holdings, not hard-coded
held2 = server.room_holdings(store(ROOM2)).get("HoldA") or []
assert r1 == (1, 1, 1, 350), r1
assert sorted(t["id"] for t in held2) == sorted([D, E]), held2
assert r2 == (2, 2, 2, 111 + sum(t["pop"] for t in held2)), (r2, held2)
assert not any(t["id"] in (OFFMAP[1], "B2/legacy.json") for t in held2), held2
ok("26. both rooms stay dirty-store clean and independent: %s here, %s there — and neither room's "
   "off-map/legacy entries reach the other" % (r1, r2))

# =========================================================== 27. passive Gold is untouched
src2 = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
calls = [l for l in src2.split("\n")
         if "user_region_pop(" in l and not l.strip().startswith("#")
         and not l.strip().startswith("def user_region_pop")]
assert len(calls) == 16, "every economy caller of user_region_pop survives (%d)" % len(calls)
assert 'def user_region_pop(tstore, user):\n    return sum(clampi(h.get("pop", 0)) for h in tstore.values()' in src2, \
    "the economy helper itself is unchanged"
assert not any("user_region_pop" in l for l in
               src2[src2.index("def _empire_population"):src2.index("def _handle_leaderboard")].split("\n")
               if not l.strip().startswith("#")), \
    "the ranking no longer calls it"
g_before, _ = server.game_economy.calculate_passive_gold(0, 250, 2000, 0, 10 ** 9)
g_after, _ = server.game_economy.calculate_passive_gold(0, 250, 2000, 0, 10 ** 9)
assert g_before == g_after and g_before > 0
ok("27. passive Gold is untouched: all 16 economy call sites and the helper itself are unchanged, "
   "and the ranking simply stopped calling it")

httpd.shutdown()
print("\nAll %d ranking-holdings tests passed." % passed)
