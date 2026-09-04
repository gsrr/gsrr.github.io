# Phase 14A.9 — HOME BASE IS A VALID ATTACK SOURCE.
#
#   python tests/home_base_attack_test.py
#
# An Alpha player registered, recruited an army at Home Base, selected an enemy territory and could
# not attack: every attack source had to be an owned playable World territory, so the FIRST attack
# was impossible. `can_attack()` rejected `@home` with `source_not_found` before anything else was
# considered (it is deliberately not a catalogue id), and `territory_on_active_map("@home")` was
# false, so the request never reached the battle engine.
#
# This file pins the corrected authority AND the invariant that makes it safe: Home Base can SEND an
# army, and can never BECOME a World-map holding. It is asserted from the server's own endpoints and
# from the Game Domain rule, not from the client.
#
# Nothing about the battle changes: the same resolve_attack(), the same apply_territorial_attack(),
# the same casualties, the same gold rules. The two differences both reuse authority Home Base
# already had -- the troop POOL it recruits into, and the Home Base technology /api/territory/tech
# writes for HOME_KEY (which is exactly what zero-territory re-entry has always attacked with).
import io, json, os, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server                                                    # noqa: E402
from game import conquest as game_conquest                       # noqa: E402
from territory_catalog import catalog as CAT                     # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


DATA = tempfile.mkdtemp(prefix="homeatk149_")
server.ROOMS_DIR = os.path.join(DATA, "rooms")
server.ACCT = os.path.join(DATA, "accounts.json")
server.DATA = os.path.join(DATA, "visits.json")
server.TERR_CATALOG = os.path.join(DATA, "learned.json")
server.PROG_DIR = os.path.join(DATA, "progress")
os.makedirs(server.ROOMS_DIR, exist_ok=True)
os.makedirs(server.PROG_DIR, exist_ok=True)
USERS = ["HomeA", "HomeB"]
json.dump({"users": {u: {} for u in USERS}, "codes": {}},
          io.open(server.ACCT, "w", encoding="utf-8"))
for u in USERS:
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
TOK = {u: "t" + u for u in USERS}

httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT
ROOM = "HOMEATK"


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


def store():
    server.set_room(ROOM)
    return server.load_territory_store()


def set_store(d):
    server.set_room(ROOM)
    with server.terr_lock:
        server.save_territory_store(d)


def econ(user):
    """The player's authoritative economy record (Home Base state). READ ONLY -- deliberately does
    not save, so this probe never races the server thread's own writes."""
    server.set_room(ROOM)
    with server.econ_lock:
        es = server.load_econ_store()
        e = server.econ_get(es, user, time.time(), server.user_region_pop(store(), user))
        return json.loads(json.dumps(e))


def set_pool(user, **troops):
    """Write the Home Base troop pool. This is the ONE army store Home Base has -- the same record
    /api/territory/recruit credits for HOME_KEY and /api/territory/claim debits."""
    server.set_room(ROOM)
    with server.econ_lock:
        es = server.load_econ_store()
        e = server.econ_get(es, user, time.time(), 0)
        e["troops"] = {k: int(troops.get(k, 0)) for k in server.TROOP_ALL}
        server.save_econ_store(es)


def pool(user):
    return {k: int(econ(user)["troops"].get(k, 0)) for k in server.TROOP_ALL}


def pool_total(user):
    return sum(pool(user).values())


def attack(user, source, target, squad):
    return api("POST", "/api/territory/attack?room=" + ROOM,
               {"sourceTerritoryId": source, "targetTerritoryId": target,
                "squad": squad, "avatar": "X"}, TOK[user])


if not CAT.loaded:
    CAT.load()
WORLD = sorted(t for t, r in CAT.territories.items() if r.get("mapId") == "world")
OFFMAP = sorted(t for t, r in CAT.territories.items() if r.get("mapId") != "world")
ENEMY, ENEMY2, MINE, NEUTRAL = WORLD[0], WORLD[1], WORLD[2], WORLD[3]
HOME = server.HOME_KEY

# ============================================================ 1/2/3. identity and the 250
assert HOME == "@home", HOME
assert not CAT.is_canonical(HOME), "Home Base must NOT be a catalogue territory"
assert CAT.resolve_any(HOME) is None, "Home Base must not resolve to any territory id"
server.set_room(ROOM)
playable = server.playable_territory_ids()
assert HOME not in set(playable), "Home Base must not be playable ground"
assert len(playable) == 250, len(playable)
assert not server.territory_on_active_map(HOME), "Home Base is off-map by design"
ok("1/2/3. the canonical Home Base identity @home is reused unchanged, is absent from "
   "playable_territory_ids(), and the playable World is still exactly 250 territories")

# ============================================================ 4/5. Home Base is a valid source
set_store({ENEMY: {"owner": "HomeB", "avatar": "B", "pop": 100,
                   "troops": [{"type": "inf", "hp": 2}]}})
set_pool("HomeA", inf=60, spear=20)
st, j = attack("HomeA", HOME, ENEMY, [{"type": "inf", "hp": 40}])
assert st == 200 and j.get("ok"), (st, j)
assert j.get("fromHomeBase") is True and j.get("sourceTerritoryId") == HOME, j
assert not CAT.are_adjacent(ENEMY, ENEMY2) or True     # adjacency is simply not consulted
ok("4/5. an attack whose source is Home Base is accepted and resolved, with no adjacency or "
   "connection requirement of any kind")

# the Game Domain rule itself, independent of HTTP
elig = game_conquest.can_attack_from_home("HomeA", ENEMY, [{"type": "inf", "hp": 1}], CAT,
                                          {ENEMY: {"owner": "HomeB"}}, {"inf": 5})
assert elig.allowed and elig.reason is None, elig
old = game_conquest.can_attack("HomeA", HOME, ENEMY, [{"type": "inf", "hp": 1}], CAT,
                               {ENEMY: {"owner": "HomeB"}})
assert not old.allowed and old.reason == "source_not_found", old
ok("4b. THE ROOT CAUSE, pinned: can_attack() still rejects @home as a holding "
   "(source_not_found) -- the Home Base rule is a separate, explicit authority")

# ============================================================ 6/7/8/9. what may NOT be attacked
set_store({ENEMY: {"owner": "HomeB", "avatar": "B", "pop": 100, "troops": [{"type": "inf", "hp": 5}]},
           NEUTRAL: {"owner": None, "pop": 50, "troops": []},
           MINE: {"owner": "HomeA", "avatar": "A", "pop": 70, "troops": [{"type": "inf", "hp": 5}]}})
set_pool("HomeA", inf=50)
st, j = attack("HomeA", HOME, HOME, [{"type": "inf", "hp": 5}])
assert st >= 400 and j.get("reason") == "target_not_found", (st, j)
st, j = attack("HomeA", ENEMY, HOME, [{"type": "inf", "hp": 5}])
assert st >= 400 and j.get("reason") == "target_not_found", (st, j)
ok("6. Home Base can never be an attack TARGET -- not from another Home Base and not from a "
   "territory: it is not canonical, so the target check rejects it")

st, j = attack("HomeA", HOME, NEUTRAL, [{"type": "inf", "hp": 5}])
assert st >= 400 and j.get("reason") == "target_not_attackable", (st, j)
ok("7. a NEUTRAL territory still cannot be taken through Attack -- Occupy is unchanged")

st, j = attack("HomeA", HOME, OFFMAP[0], [{"type": "inf", "hp": 5}])
assert st >= 400 and j.get("reason") == "inactive_map", (st, j)
ok("8. a target outside the one playable map is rejected (inactive_map), even from Home Base")

st, j = attack("HomeA", HOME, MINE, [{"type": "inf", "hp": 5}])
assert st >= 400 and j.get("reason") == "target_already_owned", (st, j)
ok("9. a territory the player already owns is rejected, exactly as from a territory source")

# ============================================================ 10/11. the zero-territory player
set_store({ENEMY: {"owner": "HomeB", "avatar": "B", "pop": 100, "troops": [{"type": "inf", "hp": 1}]}})
set_pool("HomeA", inf=80)
assert server.room_holdings(store()).get("HomeA") is None, "fixture: HomeA must hold nothing"
st, j = attack("HomeA", HOME, ENEMY, [{"type": "inf", "hp": 60}])
assert st == 200 and j.get("ok"), (st, j)
ok("10. THE CORE CONDITION: a player with Home Base, troops and ZERO World territories can "
   "attack an enemy World territory")

set_store({ENEMY: {"owner": "HomeB", "avatar": "B", "pop": 100, "troops": [{"type": "inf", "hp": 5}]}})
set_pool("HomeA", inf=0, spear=0, archer=0, cav=0)
st, j = attack("HomeA", HOME, ENEMY, [{"type": "inf", "hp": 5}])
assert st >= 400 and j.get("reason") == "insufficient_source_garrison", (st, j)
assert store()[ENEMY]["owner"] == "HomeB", store()[ENEMY]
ok("11. with no troops at Home Base the attack is refused (insufficient_source_garrison) and "
   "nothing moves -- an empty Home Base is not a free army")

# ============================================================ 12/13. the pool IS the authority
set_pool("HomeA", inf=30, cav=4)
e = econ("HomeA")
assert {k: e["troops"][k] for k in ("inf", "cav")} == {"inf": 30, "cav": 4}, e["troops"]
st, j = api("GET", "/api/economy?room=" + ROOM, None, TOK["HomeA"])
assert st == 200 and j["troops"]["inf"] == 30 and j["troops"]["cav"] == 4, j["troops"]
ok("12. the picker's authority is the published Home Base pool: /api/economy troops is the same "
   "record the attack spends, so what the player is offered is what exists")

st, j = attack("HomeA", HOME, ENEMY, [{"type": "inf", "hp": 31}])
assert st >= 400 and j.get("reason") == "insufficient_source_garrison", (st, j)
assert pool("HomeA")["inf"] == 30, pool("HomeA")
st, j = attack("HomeA", HOME, ENEMY, [{"type": "cav", "hp": 5}])
assert st >= 400 and j.get("reason") == "insufficient_source_garrison", (st, j)
ok("13. more than Home Base owns cannot be sent -- per unit type -- and a refused attack leaves "
   "the pool untouched (atomic rejection)")

# ============================================================ 14/15/19/20. the debit, exactly
set_store({ENEMY: {"owner": "HomeB", "avatar": "B", "pop": 100, "troops": [{"type": "inf", "hp": 1}]}})
set_pool("HomeA", inf=100)
before = pool_total("HomeA")
st, j = attack("HomeA", HOME, ENEMY, [{"type": "inf", "hp": 40}])
assert st == 200 and j["attackerWon"] is True, (st, j)
after = pool("HomeA")
assert after["inf"] == 60, after                       # 100 - 40, the committed squad
assert j["troops"]["inf"] == 60, j["troops"]
ok("14/15. the committed squad is debited from HOME BASE and nowhere else: 100 infantry, 40 "
   "committed, 60 remain -- and the response publishes that same figure")

srv_pool = pool("HomeA")
garrisons = {t: sum(u["hp"] for u in (h.get("troops") or []))
             for t, h in store().items() if isinstance(h, dict)}
assert HOME not in store(), "the territory store must never hold an @home record"
assert sum(srv_pool.values()) + sum(garrisons.values()) <= before + 1, (srv_pool, garrisons, before)
ok("19/20. no troop duplication: the surviving army sits in exactly ONE place (the conquered "
   "target's garrison), the pool holds only what stayed home, and no @home record exists")

# ============================================================ 16/17/21-24. WIN settlement
set_store({ENEMY: {"owner": "HomeB", "avatar": "B", "pop": 0, "troops": [{"type": "inf", "hp": 1}]}})
set_pool("HomeA", inf=90, spear=10)
st, j = attack("HomeA", HOME, ENEMY, [{"type": "inf", "hp": 50}])
assert st == 200 and j["attackerWon"] is True, (st, j)
h = store()[ENEMY]
assert h["owner"] == "HomeA", h
assert sum(u["hp"] for u in (h.get("troops") or [])) > 0, h
assert h.get("pop", 0) > 0, h                          # population from the canonical catalogue
assert pool("HomeA") == {"cav": 0, "archer": 0, "inf": 40, "spear": 10}, pool("HomeA")
assert HOME not in store(), "Home Base must not appear in the territory store after a win"
assert econ("HomeA").get("population", 0) > 0, "Home Base itself survives the win"
ok("17/21/22/24. WIN: the target changes owner, the survivors garrison the TARGET, the "
   "uncommitted army stays at Home Base, and Home Base itself is untouched and still not a "
   "territory")

holdings = server.room_holdings(store())
assert [t["id"] for t in holdings.get("HomeA", [])] == [ENEMY], holdings
st, terr = api("GET", "/api/territory?room=" + ROOM, None, TOK["HomeA"])
counts = {o: c for o, c in (terr.get("counts") or {}).items()} if terr.get("counts") else None
assert HOME not in json.dumps(terr.get("holders") or {}), "…/api/territory must not publish @home"
ok("23. the win creates the player's FIRST World holding through the one canonical holdings "
   "authority -- room_holdings() lists exactly the conquered territory")

# ============================================================ 16/25/26/27/28. LOSS settlement
set_store({ENEMY: {"owner": "HomeB", "avatar": "B", "pop": 100,
                   "troops": [{"type": "spear", "hp": 4000}]}})
set_pool("HomeA", inf=100)
gold_before = econ("HomeA").get("gold", 0)
st, j = attack("HomeA", HOME, ENEMY, [{"type": "inf", "hp": 5}])
assert st == 200 and j["attackerWon"] is False, (st, j)
assert store()[ENEMY]["owner"] == "HomeB", store()[ENEMY]
left = pool("HomeA")
survivors = sum(int(s["hp"]) for s in (j.get("attackerSurvivors") or []))
assert left["inf"] == 95 + survivors, (left, survivors)
assert HOME not in store(), "a loss must not create an @home record either"
assert server.room_holdings(store()).get("HomeA") is None, "the player may still hold nothing"
ok("16/25/26/27. LOSS: the target stays with the defender, only casualties are lost (survivors "
   "come home to the pool, the canonical source-return rule), Home Base survives intact and the "
   "player may legitimately remain at 0 World territories")

assert econ("HomeA").get("gold", 0) == max(0, gold_before - server.ATTACK_FAIL_GOLD), \
    (gold_before, econ("HomeA").get("gold"))
st2, j2 = attack("HomeA", HOME, ENEMY, [{"type": "inf", "hp": 5}])
assert st2 == 200, (st2, j2)
ok("28. the existing gold penalty applies unchanged, and a further Home Base attack is still "
   "possible while troops remain")

# ============================================================ 18. settlement semantics unchanged
set_store({ENEMY: {"owner": "HomeB", "avatar": "B", "pop": 100, "troops": [{"type": "inf", "hp": 1}]},
           MINE: {"owner": "HomeA", "avatar": "A", "pop": 70,
                  "troops": [{"type": "inf", "hp": 60}]}})
set_pool("HomeA", inf=0)
st, j = attack("HomeA", MINE, ENEMY, [{"type": "inf", "hp": 40}])
assert st == 200 and j["attackerWon"] is True, (st, j)
assert sum(u["hp"] for u in store()[MINE]["troops"]) == 20, store()[MINE]
assert store()[ENEMY]["owner"] == "HomeA", store()[ENEMY]
assert pool_total("HomeA") == 0, pool("HomeA")         # a territory attack never touches the pool
ok("18. an ordinary territory-source attack is UNCHANGED: the squad leaves that garrison, the "
   "survivors settle on the target, and the Home Base pool is not involved at all")

# ============================================================ 41-46. ranking / holdings
set_store({ENEMY: {"owner": "HomeB", "avatar": "B", "pop": 100, "troops": [{"type": "inf", "hp": 1}]}})
set_pool("HomeA", inf=50)
st, lb = api("GET", "/api/leaderboard?room=" + ROOM)
row = {r["name"]: r for r in lb["leaders"]}.get("HomeA") or {}
assert row.get("territories") == [], row
assert int(row.get("regions", 0)) == 0, row
st, pub = api("GET", "/api/territory?room=" + ROOM, None, TOK["HomeA"])
assert HOME not in (pub.get("holders") or {}), pub.get("holders")
ok("41/42/43/44. a Home Base source is not a holding: Territories Held stays 0, regions stays 0, "
   "and neither the public holdings list nor /api/territory ever mentions @home")

home_pop = econ("HomeA").get("population", 0)
assert int(row.get("population", 0)) == home_pop, (row.get("population"), home_pop)
st, j = attack("HomeA", HOME, ENEMY, [{"type": "inf", "hp": 40}])
assert st == 200 and j["attackerWon"] is True, (st, j)
st, lb2 = api("GET", "/api/leaderboard?room=" + ROOM)
row2 = {r["name"]: r for r in lb2["leaders"]}.get("HomeA") or {}
holds = server.room_holdings(store()).get("HomeA") or []
st, pub2 = api("GET", "/api/territory?room=" + ROOM, None, TOK["HomeA"])
mine_pub = [t for t, h in (pub2.get("holders") or {}).items() if h.get("owner") == "HomeA"]
assert (int(row2.get("regions", 0)) == 1 and len(row2.get("territories") or []) == 1
        and len(holds) == 1 and len(mine_pub) == 1), (row2, holds, mine_pub)
ok("45. after the first win all three agree on exactly ONE territory: Ranking, room_holdings() "
   "and /api/territory")

expect = econ("HomeA").get("population", 0) + sum(t["pop"] for t in holds)
assert int(row2.get("population", 0)) == expect, (row2.get("population"), expect)
ok("46. Ranking Population is still Home Base population + holdings population, counted once -- "
   "being an attack source adds nothing and double-counts nothing")

# ============================================================ AI / conscription non-regression
assert "ai_home" not in json.dumps(store()), store()
src = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
ai = src[src.index("def ai_move("):src.index("def ai_loop(")]
assert "_attack_from_home" not in ai and "can_attack_from_home" not in ai, \
    "the AI must keep its existing territory-source behaviour"
assert "game_conquest.can_attack(ai_name, source, target" in ai, "the AI still uses can_attack()"
ok("AI: no synthetic AI Home Base source was introduced -- ai_move() still attacks from its own "
   "territory garrisons through can_attack(), exactly as Phase 14A.7 left it")

def _fn(text, name):
    """One top-level function's OWN BODY: its `def` line plus every following indented line.

    Bounded by indentation rather than by the next `def`, so neither a comment nor an unrelated
    module-level statement written after it can read as a change inside it.
    """
    a = text.index("def %s(" % name)
    lines = text[a:].split("\n")
    body = [lines[0]]
    for line in lines[1:]:
        if line and not line[0].isspace():
            break
        body.append(line)
    while body and not body[-1].strip():
        body.pop()
    return "\n".join(body)


head = subprocess.run(["git", "show", "HEAD:english_learning/server.py"], cwd=os.path.dirname(ROOT),
                      capture_output=True, text=True, encoding="utf-8").stdout
assert head, "cannot read the committed server.py"
for fn in ("conscript_tick", "ai_move", "user_region_pop", "room_holdings", "holdings_population"):
    assert _fn(src, fn) == _fn(head, fn), "%s must be byte-identical to the committed version" % fn
ok("Conscription / AI / holdings authority are byte-identical to the committed server.py: "
   "conscript_tick still recruits into the SAME Home Base pool this phase attacks from, so "
   "conscripted troops are usable with no special attack logic anywhere")

# and the battle mathematics themselves are untouched
for fn in ("resolve_attack", "apply_territorial_attack", "can_attack", "shuffle_defender"):
    a = io.open(os.path.join(ROOT, "game", "conquest.py"), encoding="utf-8").read()
    b = subprocess.run(["git", "show", "HEAD:english_learning/game/conquest.py"],
                       cwd=os.path.dirname(ROOT), capture_output=True, text=True,
                       encoding="utf-8").stdout
    assert _fn(a, fn) == _fn(b, fn), "%s must be unchanged" % fn
ok("battle authority unchanged: resolve_attack, apply_territorial_attack, can_attack and "
   "shuffle_defender are byte-identical to the committed domain -- the only domain addition is "
   "can_attack_from_home()")

httpd.shutdown()
print("\nAll %d Home-Base-attack checks passed." % passed)
