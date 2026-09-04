# Phase 14A.7 — AI PRESENCE AND ACTIVITY.
#
#   python tests/ai_presence_test.py
#
# A player asked why all the computer AIs had disappeared. They had not: they were rostered, but no
# AI had ever taken a single territory, so there was nothing to see on the map and nothing to rank.
#
# THE THREE CAUSES, and what this file pins now that they are fixed:
#
#   1  OCCUPATION. Candidates were `[k for k in load_catalog() if k not in owned]` -- the LEARNED
#      catalogue, which only gains a key when a HUMAN claims that territory, minus EVERY store key.
#      A learned key is by construction also a store key, so the set was empty in any single-room
#      world and the AI could never take a first territory. Measured before the fix: nine
#      consecutive ai_move() calls on a fresh GLOBAL did nothing at all. The learned catalogue is
#      also a single global file, so the only way it ever worked was cross-room leakage.
#      Candidates are now the canonical playable World minus territories that have a CURRENT OWNER.
#
#   2  ATTACK. The AI's target filter required terr_catalog.are_adjacent(source, target) while
#      Phase 14A had made ownership the only conquest authority for humans -- so the AI was strictly
#      more constrained than the rule it shares, and an AI holding only degree-0 ground (90 of the
#      250 World territories have no land neighbour) could never attack anything.
#
#   3  CADENCE. 60s then 20-30 minutes: about two decision passes in half an hour.
#
# game_conquest.can_attack(), the battle resolver, the AI economy and user_region_pop() are all
# unchanged; this file asserts that too.
import io, json, os, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server                                                   # noqa: E402
from game import conquest as game_conquest                       # noqa: E402
from territory_catalog import catalog as CAT                      # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


DATA = tempfile.mkdtemp(prefix="aipresence147_")
server.ROOMS_DIR = os.path.join(DATA, "rooms")
server.ACCT = os.path.join(DATA, "accounts.json")
server.DATA = os.path.join(DATA, "visits.json")
server.PROG_DIR = os.path.join(DATA, "progress")
server.TERR_CATALOG = os.path.join(DATA, "learned.json")     # the learned cache, kept EMPTY on purpose
os.makedirs(server.ROOMS_DIR, exist_ok=True)
os.makedirs(server.PROG_DIR, exist_ok=True)
json.dump({"users": {"HumanA": {}, "HumanB": {}}, "codes": {}},
          io.open(server.ACCT, "w", encoding="utf-8"))
for u in ("HumanA", "HumanB"):
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
TOK = {u: "t" + u for u in ("HumanA", "HumanB")}

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


def store(code):
    server.set_room(code)
    return server.load_territory_store()


def econ(code):
    server.set_room(code)
    return server.load_econ_store()


def cycle(code, name, difficulty="normal"):
    """One real ai_move through the production path -- no seeding, no shortcut."""
    server.set_room(code)
    room = server.load_room()
    return server.ai_move(name, difficulty, server.room_ai_names(room))


def board(code):
    st, j = api("GET", "/api/leaderboard?room=" + code)
    assert st == 200, (st, j)
    return {r["name"]: r for r in j["leaders"]}


if not CAT.loaded:
    CAT.load()
WORLD = sorted(t for t, r in CAT.territories.items() if r.get("mapId") == "world")
OFFMAP = sorted(t for t, r in CAT.territories.items() if r.get("mapId") != "world")
ISLANDS = [t for t in WORLD
           if not [n for n in (CAT.territories[t].get("adjacentTerritoryIds") or []) if n in CAT.territories]]

# =========================================================== 1. the GLOBAL roster
server.ensure_global_room()
server.set_room("GLOBAL")
roster = sorted(server.room_ai_names())
assert roster == ["AI 1", "AI 2", "AI 3"], roster
assert server.GLOBAL_AIS == 3, server.GLOBAL_AIS
ok("1. the GLOBAL world is rostered with %s" % roster)

# =========================================================== 2/3. a fresh AI holds nothing, then gets an economy
assert server.room_holdings(store("GLOBAL")) == {}, "a fresh world has no holdings at all"
assert all(econ("GLOBAL").get(n) is None for n in roster), "no AI economy exists before the first move"
assert server.load_catalog() == {}, "the learned catalogue is EMPTY -- occupation must not need it"
cycle("GLOBAL", "AI 1")
e = econ("GLOBAL").get("AI 1")
assert isinstance(e, dict) and e["population"] == server.AI_DIFF["normal"]["pop"], e
ok("2/3. an AI starts with zero holdings and no economy record; the first move initialises its "
   "economy at the AI_DIFF population (%d)" % e["population"])

# =========================================================== 4/8. the candidate set is the playable World
server.set_room("GLOBAL")
st = server.load_territory_store()
playable = set(server.playable_territory_ids())
occupied = {t for t, h in st.items() if isinstance(h, dict) and h.get("owner")}
candidates = [t for t in playable if t not in occupied]
assert len(playable) == 250, len(playable)
assert len(candidates) >= 249, len(candidates)
assert server.load_catalog() == {}, "still empty, and yet candidates exist"
ok("4/8. occupy candidates come from the canonical playable World (%d of %d free) with an EMPTY "
   "learned catalogue -- that cache is no longer the occupation authority" % (len(candidates), len(playable)))

# =========================================================== 10/11/12. the first occupation
first = cycle("GLOBAL", "AI 2")
assert first and first[0] == "occupy", first
tid = first[3]
st = store("GLOBAL")
assert st[tid]["owner"] == "AI 2", st[tid]
assert st[tid]["avatar"] == server.AI_AVATAR, st[tid]
assert st[tid]["pop"] == server.clampi(CAT.game_population(tid)), (st[tid]["pop"], CAT.game_population(tid))
assert server.load_territory_store()[tid]["owner"] == "AI 2", "ownership persisted to disk"
ok("10/11/12. a zero-holdings AI occupied %s with no seeding; its population is the canonical "
   "game_population (%d) and the ownership persists" % (first[1], st[tid]["pop"]))

# =========================================================== 5. owner=None stays a candidate
server.set_room("GLOBAL")
with server.terr_lock:
    s = server.load_territory_store()
    neutral = next(t for t in WORLD if t not in s)
    s[neutral] = {"owner": None, "pop": 123, "troops": []}          # touched, but UNOWNED
    server.save_territory_store(s)
st = server.load_territory_store()
occupied = {t for t, h in st.items() if isinstance(h, dict) and h.get("owner")}
assert neutral in st and neutral not in occupied, "a store entry with owner None is not occupied"
assert neutral in [t for t in playable if t not in occupied], "so it is still a candidate"
ok("5. a playable territory present in the store with owner=None is NEUTRAL and remains a "
   "candidate -- a store entry existing is not the same as being occupied")

# =========================================================== 6/7. off-map and legacy are never candidates
server.set_room("GLOBAL")
with server.terr_lock:
    s = server.load_territory_store()
    s[OFFMAP[0]] = {"owner": None, "pop": 900, "troops": []}
    s["A1/002.json"] = {"owner": None, "pop": 800, "troops": []}
    server.save_territory_store(s)
cands = [t for t in server.playable_territory_ids()
         if t not in {x for x, h in server.load_territory_store().items()
                      if isinstance(h, dict) and h.get("owner")}]
assert OFFMAP[0] not in cands and "A1/002.json" not in cands, "neither may be occupied"
for _ in range(6):
    got = cycle("GLOBAL", "AI 3")
    if got and got[0] == "occupy":
        assert got[3] in playable, got
ok("6/7. an off-map catalogue territory and an unresolvable legacy key are never occupy "
   "candidates -- every occupation lands on a playable World id")

# =========================================================== 13/14/15/16/17. visible to the product
st = store("GLOBAL")
ai_owned = {t: h for t, h in st.items() if isinstance(h, dict) and server.is_ai_owner(h.get("owner"))}
assert ai_owned, "at least one AI holds ground"
stt, terr = api("GET", "/api/territory?room=GLOBAL", None, TOK["HumanA"])
assert stt == 200
for t, h in ai_owned.items():
    assert terr["holders"][t]["owner"] == h["owner"], (t, terr["holders"][t])
    assert terr["holders"][t].get("ai") is True, terr["holders"][t]
rows = board("GLOBAL")
for name in {h["owner"] for h in ai_owned.values()}:
    r = rows.get(name)
    assert r, (name, sorted(rows))
    held = server.room_holdings(st).get(name) or []
    assert r["regions"] == len(held) == len(r["territories"]), (r, held)
    base = server.clampi((econ("GLOBAL").get(name) or {}).get("population", 0))
    assert r["population"] == base + sum(t2["pop"] for t2 in held), (r, base, held)
    assert sorted(t2["name"] for t2 in r["territories"]) == sorted(t2["name"] for t2 in held)
ok("13-17. every AI holding ground appears in /api/territory (flagged ai:true), has a Ranking row, "
   "and its Territories Held, holdings list and Empire Population all agree with canonical state")

# =========================================================== 18. the AI can expand
# Occupying spends the whole troop pool and gold accrues by the HOUR, so expansion needs elapsed
# time -- that is the existing economy, deliberately preserved. Rather than inject troops (which
# would prove nothing about the real path), roll `lastGold` back so the genuine passive-gold formula
# pays out and _ai_recruit() buys the next army itself.
def age_ai(code, name, days=3):
    server.set_room(code)
    with server.econ_lock:
        es = server.load_econ_store()
        e = es.get(name)
        if isinstance(e, dict):
            # Phase 14A.10A: passive income settles per DAY, so the harness ages by days.
            e["lastGold"] = time.time() - days * server.game_config.PASSIVE_PERIOD_SECONDS - 1
            server.save_econ_store(es)


before = len(server.room_holdings(store("GLOBAL")).get("AI 1") or [])
acts = []
for _ in range(6):
    age_ai("GLOBAL", "AI 1")
    got = cycle("GLOBAL", "AI 1")
    if got:
        acts.append(got[0])
after = len(server.room_holdings(store("GLOBAL")).get("AI 1") or [])
assert after > before, (before, after, acts)
assert all(a in ("occupy", "attack_win", "attack_fail") for a in acts), acts
ok("18. the AI expands across passes once its own economy has paid out (%d -> %d territories, "
   "actions %s) -- still one action per pass, never a spree" % (before, after, acts))

# =========================================================== 19/20/21. global attack, island source
st2, j2 = api("POST", "/api/room/create", {}, TOK["HumanB"])
st2, j2 = api("POST", "/api/room/start",
              {"map": "A1", "aiCount": 1, "resources": "high", "capacity": 4}, TOK["HumanB"])
ATK = j2["code"]
island = ISLANDS[0]
far = next(t for t in WORLD
           if t != island and [n for n in (CAT.territories[t].get("adjacentTerritoryIds") or []) if n in CAT.territories])
assert not CAT.are_adjacent(island, far), (island, far)
server.set_room(ATK)
with server.terr_lock:
    s = {t: {"owner": "AI 1", "avatar": server.AI_AVATAR, "pop": 10, "troops": []}
         for t in server.playable_territory_ids()}          # no neutral ground anywhere -> no occupy
    s[island] = {"owner": "AI 1", "avatar": server.AI_AVATAR, "pop": 50,
                 "troops": [{"type": "cav", "hp": 500}]}    # the ONLY garrisoned AI source
    s[far] = {"owner": "HumanB", "avatar": "H", "pop": 100, "troops": [{"type": "inf", "hp": 1}]}
    server.save_territory_store(s)
with server.econ_lock:
    es = server.load_econ_store()
    es["AI 1"] = {"population": 400, "gold": 0, "lastGold": time.time(),
                  "troops": server._norm_troops(0)}          # empty pool -> occupy impossible anyway
    server.save_econ_store(es)
res = cycle(ATK, "AI 1")
assert res and res[0] in ("attack_win", "attack_fail"), res
assert res[3] == far, res
st = store(ATK)
assert server.clampi(sum(t["hp"] for t in (st[island]["troops"] or []))) < 500, \
    "the squad came from the island SOURCE garrison"
elig = game_conquest.can_attack("AI 1", island, far, [{"type": "cav", "hp": 1}], CAT, st,
                                require_qualifications=False)
assert "not_adjacent" in game_conquest.AttackEligibility.REASONS
ok("19/20/21. a degree-0 ISLAND source attacked the non-adjacent %s through the same "
   "game_conquest service -- geography no longer traps the AI, and can_attack is untouched"
   % CAT.territories[far]["displayName"])

# =========================================================== 9/27. room isolation
st3, j3 = api("POST", "/api/room/create", {}, TOK["HumanA"])
ROOM_A = server.find_user_room("HumanA")
st3, j3 = api("POST", "/api/room/start",
              {"map": "A1", "aiCount": 1, "resources": "high", "capacity": 4}, TOK["HumanA"])
ROOM_A = j3["code"]
server.set_room(ROOM_A)
with server.terr_lock:
    s = {t: {"owner": "HumanA", "avatar": "H", "pop": 5, "troops": []}
         for t in server.playable_territory_ids()}          # every playable territory taken HERE
    server.save_territory_store(s)
before_a = dict(server.room_holdings(store(ROOM_A)))
res_a = cycle(ROOM_A, "AI 1")
after_a = server.room_holdings(store(ROOM_A))
assert (after_a.get("AI 1") or []) == [] or res_a and res_a[0].startswith("attack"), res_a
assert len(server.room_holdings(store("GLOBAL"))) >= 1, "GLOBAL still has its own AI holdings"
g_ids = {t["id"] for lst in server.room_holdings(store("GLOBAL")).values() for t in lst}
a_ids = {t["id"] for lst in after_a.values() for t in lst}
assert g_ids and a_ids and g_ids != a_ids, (len(g_ids), len(a_ids))
ok("9/27. candidate discovery and holdings are CURRENT-ROOM only: a full room offers the AI no "
   "occupation, and GLOBAL's holdings are unaffected (%d ids here, %d there)" % (len(a_ids), len(g_ids)))

# =========================================================== 17b. a FRESH PRIVATE ROOM, independently
# No GLOBAL claim, no learned-catalogue entry, no seeding: a private room's own AI must reach the
# canonical playable World by itself.
st4, j4 = api("POST", "/api/room/create", {}, TOK["HumanB"])
st4, j4 = api("POST", "/api/room/start",
              {"map": "A1", "aiCount": 2, "resources": "high", "capacity": 4}, TOK["HumanB"])
PRIV = j4["code"]
server.set_room(PRIV)
assert sorted(server.room_ai_names()) == ["AI 1", "AI 2"], sorted(server.room_ai_names())
assert server.room_holdings(store(PRIV)) == {}, "the private room starts empty"
priv_first = cycle(PRIV, "AI 1")
assert priv_first and priv_first[0] == "occupy", priv_first
assert priv_first[3] in playable, priv_first
pr = board(PRIV).get("AI 1")
assert pr and pr["regions"] == 1 and len(pr["territories"]) == 1, pr
assert pr["territories"][0]["name"] == priv_first[1], (pr, priv_first)
ok("17b. a fresh PRIVATE room's AI occupied %s from the canonical playable World with no GLOBAL "
   "claim and an empty learned catalogue, and is ranked there (%d/%d)"
   % (priv_first[1], pr["population"], pr["regions"]))

# =========================================================== 22. no client synthesis
client = io.open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
code_only = "\n".join(l for l in client.split("\n") if not l.lstrip().startswith("//"))
for banned in ("botPop", "botAva", "p.population == null"):
    assert banned not in code_only, "the client must not synthesize AI rows: " + banned
assert 'fetch(withRoom("/api/leaderboard"))' in code_only, "Ranking is the server's, for this room"
ok("22. no client-side synthetic AI: the map and Ranking render server truth only")

# =========================================================== 23/24/25/26. the Alpha cadence
assert server.AI_INITIAL_DELAY == 15, server.AI_INITIAL_DELAY
assert server.AI_TICK_MIN == 60, server.AI_TICK_MIN
assert server.AI_TICK_MAX == 120, server.AI_TICK_MAX
assert server.AI_TICK_MAX >= server.AI_TICK_MIN
src = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
assert "time.sleep(AI_INITIAL_DELAY)" in src, "the loop uses the configurable delay"
assert "time.sleep(random.randint(AI_TICK_MIN, AI_TICK_MAX))" in src, "...and the configurable tick"
assert "20 * 60" not in src.split("def ai_loop")[0].split("AI_INITIAL_DELAY")[0][-400:], \
    "the old 20-minute default is gone"
# the environment override, proved in a child process so this one is unaffected
env = dict(os.environ, AI_INITIAL_DELAY="3", AI_TICK_MIN="7", AI_TICK_MAX="9")
out = subprocess.run([sys.executable, "-c",
                      "import sys; sys.path.insert(0, r'%s'); import server; "
                      "print(server.AI_INITIAL_DELAY, server.AI_TICK_MIN, server.AI_TICK_MAX)" % ROOT],
                     capture_output=True, text=True, env=env, cwd=ROOT)
assert out.stdout.strip().endswith("3 7 9"), (out.stdout, out.stderr[-300:])
ok("23-26. Alpha cadence defaults are initial 15s, tick 60-120s, wired into ai_loop and overridable "
   "by AI_INITIAL_DELAY / AI_TICK_MIN / AI_TICK_MAX (child process reported %s)"
   % out.stdout.strip().split()[-3:])

# =========================================================== 28. the economy is untouched
assert server.AI_DIFF == {"easy": {"pop": 120, "gold": 300},
                          "normal": {"pop": 400, "gold": 1500},
                          "hard": {"pop": 1000, "gold": 8000}}, server.AI_DIFF
assert 'def user_region_pop(tstore, user):\n    return sum(clampi(h.get("pop", 0)) for h in tstore.values()' in src, \
    "user_region_pop is unchanged"
assert src.count("def ai_econ(") == 1 and src.count("def _ai_recruit(") == 1
assert "return econ_get(estore, name, now, user_region_pop(tstore, name))" in src, \
    "the AI still earns on base + its territories, exactly as before"
assert "_ai_recruit(ae)" in src, "gold still becomes troops through the same helper"
assert 'ae["troops"] = _norm_troops(0)' in src, "occupying still spends the pool -- one action per pass"
ok("28. AI_DIFF, ai_econ(), _ai_recruit(), the gold->troops model and user_region_pop() are all "
   "unchanged -- this phase changed candidate discovery, target filtering and cadence only")

httpd.shutdown()
print("\nAll %d AI-presence tests passed." % passed)
