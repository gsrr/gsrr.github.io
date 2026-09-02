# Phase 14A (v0.1 PLAYABLE ALPHA) — GLOBAL CONQUEST.
#
#   python tests/global_conquest_test.py
#
# THE ALPHA RULE
#
#     OWNERSHIP determines target eligibility. ADJACENCY does not.
#
# A neutral World territory may be occupied regardless of adjacency; an enemy-held one may be
# attacked regardless of adjacency. Nothing else was relaxed: identity, room membership, source
# ownership, self-attack, squad validity, source garrison, battle rules and Gold all still decide.
#
# This file pins BOTH halves. Every "now allowed" case is paired with the non-geographic rule that
# still refuses, because a rule change that quietly removed a second guard would look identical to
# this one from the accepting side alone.
#
# It also pins that the adjacency DATA is untouched — 900 catalogue edge-ends, 642 on the World map,
# 0 cross-map, 90 degree-0 — and that Frontier / Interior / Isolated and the strategic regions still
# classify exactly as they did. Geography is still described; it simply grants nothing.
import io, json, os, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server                                                   # noqa: E402
from game import conquest, frontier as g_frontier, regions as g_regions   # noqa: E402
from territory_catalog import catalog as CAT                     # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ---------------------------------------------------------------- a real in-process server
DATA = tempfile.mkdtemp(prefix="alpha14a_")
server.ROOMS_DIR = os.path.join(DATA, "rooms")
server.ACCT = os.path.join(DATA, "accounts.json")
server.DATA = os.path.join(DATA, "visits.json")
server.TERR_CATALOG = os.path.join(DATA, "learned.json")
os.makedirs(server.ROOMS_DIR, exist_ok=True)
json.dump({"users": {"AlphaA": {}, "AlphaB": {}}, "codes": {}},
          io.open(server.ACCT, "w", encoding="utf-8"))
for u in ("AlphaA", "AlphaB"):
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
TOK_A, TOK_B = "tAlphaA", "tAlphaB"

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


if not CAT.loaded:
    CAT.load()
WORLD = sorted(t for t, rec in CAT.territories.items() if rec.get("mapId") == "world")
assert len(WORLD) == 250, len(WORLD)

st, j = api("POST", "/api/room/create", {}, TOK_A)
assert st == 200, (st, j)
st, j = api("POST", "/api/room/start",
            {"map": "A1", "aiCount": 0, "resources": "high", "capacity": 4}, TOK_A)
assert st == 200, (st, j)
CODE = j["code"]
st, j = api("POST", "/api/room/enter", {"room": CODE}, TOK_B)
assert st == 200, (st, j)
R = "?room=" + CODE


def claim(tid, tok, troops=None):
    return api("POST", "/api/territory/claim" + R,
               {"file": tid, "avatar": "X", "pop": 0,
                "troops": troops or [{"type": "inf", "hp": 5}]}, tok)


def attack(src, tgt, tok, squad=None):
    return api("POST", "/api/territory/attack" + R,
               {"sourceTerritoryId": src, "targetTerritoryId": tgt,
                "squad": squad or [{"type": "inf", "hp": 3}], "avatar": "X"}, tok)


def store():
    server.set_room(CODE)
    return server.load_territory_store()


# ---------------------------------------------------------------- pick the geography we need
def nbrs(t):
    return [n for n in (CAT.territories[t].get("adjacentTerritoryIds") or []) if n in CAT.territories]


CONNECTED = [t for t in WORLD if nbrs(t)]
ISLANDS = [t for t in WORLD if not nbrs(t)]
assert len(ISLANDS) == 90, len(ISLANDS)

HOME = CONNECTED[0]
ADJ_NEUTRAL = nbrs(HOME)[0]
FAR_NEUTRAL = next(t for t in CONNECTED
                   if t != HOME and t not in nbrs(HOME) and HOME not in nbrs(t))
ISLAND_NEUTRAL = ISLANDS[0]

# =========================================================== 1/2/3. CLAIM ignores adjacency
st, j = claim(HOME, TOK_A, [{"type": "inf", "hp": 9}])
assert st == 200, ("home claim", st, j)

st, j = claim(ADJ_NEUTRAL, TOK_A)
assert st == 200 and j.get("ok"), ("adjacent neutral", st, j)
assert store()[ADJ_NEUTRAL]["owner"] == "AlphaA"
ok("1. an ADJACENT neutral territory can still be occupied")

assert FAR_NEUTRAL not in nbrs(HOME) and HOME not in nbrs(FAR_NEUTRAL), "the fixture must be far"
st, j = claim(FAR_NEUTRAL, TOK_A)
assert st == 200 and j.get("ok"), ("non-adjacent neutral", st, j)
assert store()[FAR_NEUTRAL]["owner"] == "AlphaA"
ok("2. a NON-ADJACENT neutral territory can be occupied — adjacency is not a claim gate")

assert not nbrs(ISLAND_NEUTRAL), "the fixture must be degree-0"
st, j = claim(ISLAND_NEUTRAL, TOK_A)
assert st == 200 and j.get("ok"), ("degree-0 neutral", st, j)
assert store()[ISLAND_NEUTRAL]["owner"] == "AlphaA"
ok("3. a DEGREE-0 neutral territory can be occupied — having no neighbours blocks nothing")

# =========================================================== 4/5/6. ATTACK ignores adjacency
# B takes three targets: one bordering A's home, one far away, one an island.
B_ADJ = next(t for t in nbrs(HOME) if t != ADJ_NEUTRAL and not store().get(t, {}).get("owner"))
B_FAR = next(t for t in CONNECTED
             if not store().get(t, {}).get("owner") and t not in nbrs(HOME) and HOME not in nbrs(t))
B_ISLAND = next(t for t in ISLANDS if not store().get(t, {}).get("owner"))
for t in (B_ADJ, B_FAR, B_ISLAND):
    st, j = claim(t, TOK_B, [{"type": "inf", "hp": 1}])
    assert st == 200, ("B claim " + t, st, j)

# A needs a garrison to march with; HOME was claimed with 9
def garrison(t):
    return sum(x.get("hp", 0) for x in (store().get(t, {}).get("troops") or []))


assert garrison(HOME) >= 3, garrison(HOME)

st, j = attack(HOME, B_ADJ, TOK_A, [{"type": "inf", "hp": 1}])
assert st == 200 and j.get("ok") is True, ("adjacent enemy", st, j)
ok("4. an ADJACENT enemy territory can still be attacked")

st, j = attack(HOME, B_FAR, TOK_A, [{"type": "inf", "hp": 1}])
assert st == 200 and j.get("ok") is True, ("non-adjacent enemy", st, j)
assert j.get("sourceTerritoryId") == HOME and j.get("targetTerritoryId") == B_FAR
ok("5. a NON-ADJACENT enemy territory can be attacked — the Alpha rule, server-side")

st, j = attack(HOME, B_ISLAND, TOK_A, [{"type": "inf", "hp": 1}])
assert st == 200 and j.get("ok") is True, ("degree-0 enemy", st, j)
ok("6. a DEGREE-0 enemy territory can be attacked — an island is reachable now")

# and an attack OUT OF an island works too, which the old rule made impossible
if store()[ISLAND_NEUTRAL]["owner"] == "AlphaA" and garrison(ISLAND_NEUTRAL) > 0:
    tgt = next((t for t in (B_ADJ, B_FAR, B_ISLAND)
                if store().get(t, {}).get("owner") not in (None, "AlphaA")), None)
    if tgt:
        st, j = attack(ISLAND_NEUTRAL, tgt, TOK_A, [{"type": "inf", "hp": 1}])
        assert st == 200 and j.get("ok") is True, ("island as SOURCE", st, j)
        ok("6b. an ISLAND can be the attack SOURCE — 'isolated' withholds no authority")

# =========================================================== 7-10. what still refuses
own = next(t for t in (HOME, ADJ_NEUTRAL, FAR_NEUTRAL)
           if store().get(t, {}).get("owner") == "AlphaA" and t != HOME)
st, j = attack(HOME, own, TOK_A)
assert st in (400, 403) and j.get("reason") == "target_already_owned", (st, j)
ok("7. your OWN territory still cannot be attacked (target_already_owned)")

foe_src = next(t for t in (B_ADJ, B_FAR, B_ISLAND)
               if store().get(t, {}).get("owner") == "AlphaB")
st, j = attack(foe_src, HOME, TOK_A)
assert st in (400, 403) and j.get("reason") == "source_not_owned", (st, j)
ok("8. the SOURCE must still be owned by the attacker (source_not_owned)")

st, j = attack(HOME, foe_src, TOK_A, [{"type": "inf", "hp": 99999}])
assert st in (400, 403) and j.get("reason") == "insufficient_source_garrison", (st, j)
ok("9. troop availability is still enforced (insufficient_source_garrison)")

st, j = api("POST", "/api/territory/attack" + R,
            {"sourceTerritoryId": HOME, "targetTerritoryId": foe_src,
             "squad": [{"type": "inf", "hp": 1}], "avatar": "X"})      # no token
assert st in (400, 401, 403), (st, j)
st, j = api("POST", "/api/territory/attack?room=NOPE9",
            {"sourceTerritoryId": HOME, "targetTerritoryId": foe_src,
             "squad": [{"type": "inf", "hp": 1}], "avatar": "X"}, TOK_A)
assert st != 200, ("a bogus room must not resolve an attack", st, j)
ok("10. room and player authority are still enforced")

st, j = attack(HOME, HOME, TOK_A)
assert st in (400, 403) and j.get("reason") == "same_territory", (st, j)
st, j = attack(HOME, "world:zzzz", TOK_A)
assert st in (400, 403) and j.get("reason") == "target_not_found", (st, j)
ok("10b. self-attack and unknown ids are still refused, unchanged")

# =========================================================== 11/12. technology semantics
# The attacker's technology is the SOURCE territory's; the defender's is the TARGET's. Phase 14A
# changed neither, and the pure rule is where that is decided.
src_code = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
# the PLAYER's call site (the AI has its own, with the same shape); anchor on the player's locals
i = src_code.index('src.get("tech")')
seg = src_code[max(0, i - 300):i + 120]
assert "game_conquest.resolve_attack(squad," in seg, seg
assert "def_tech" in seg, seg
assert 'def_tech = tgt.get("tech")' in src_code, "defender tech is the TARGET territory's"
ok("11/12. attacker tech is still the SOURCE territory's and defender tech the TARGET's")

# =========================================================== 13. the adjacency DATA is untouched
edge_all = sum(len(CAT.neighbors(t) or ()) for t in CAT.territories)
edge_world = sum(len(CAT.neighbors(t) or ()) for t in WORLD)
cross = sum(1 for t in CAT.territories for n in (CAT.neighbors(t) or ())
            if CAT.map_of(n) != CAT.map_of(t))
deg0 = sum(1 for t in WORLD if not CAT.neighbors(t))
assert (edge_all, edge_world, cross, deg0) == (900, 642, 0, 90), (edge_all, edge_world, cross, deg0)
comps = sorted((len(c) for c in CAT.map_components("world")), reverse=True)
assert comps[:3] == [135, 23, 2] and comps.count(1) == 90, comps
ok("13. the adjacency catalogue is UNCHANGED: 900 edge-ends (World 642), 0 cross-map, 90 degree-0, "
   "components [135, 23, 2] + 90 singletons")

# it is also still *reachable* as information — the rule stopped consulting it, nothing deleted it
assert CAT.are_adjacent(HOME, nbrs(HOME)[0]) is True
assert CAT.are_adjacent(HOME, FAR_NEUTRAL) is False
ok("13b. are_adjacent() still answers truthfully — geography is information, not authority")

# =========================================================== 14/15. Frontier classification
owner_of = lambda t: (store().get(t) or {}).get("owner")
nb_of = lambda t: CAT.neighbors(t) or ()
S = store()
_own = lambda t: (S.get(t) or {}).get("owner")
assert g_frontier.classify(ISLAND_NEUTRAL, "AlphaA", _own, nb_of) == "isolated", \
    "a degree-0 holding is still ISOLATED"
mine_connected = [t for t in WORLD if _own(t) == "AlphaA" and nb_of(t)]
for t in mine_connected:
    cls = g_frontier.classify(t, "AlphaA", _own, nb_of)
    expect = "frontier" if any(_own(n) != "AlphaA" for n in nb_of(t)) else "interior"
    assert cls == expect, (t, cls, expect)
assert g_frontier.classify(foe_src, "AlphaA", _own, nb_of) is None, "not mine -> None"
ok("14/15. Frontier / Interior / Isolated classify exactly as before — isolated first, then any "
   "non-mine land neighbour, then interior")

# =========================================================== 16. Strategic regions
meta_of = lambda t: CAT.territories.get(t) or {}
mem = g_regions.membership(WORLD, meta_of)
sizes = {}
for r in mem.values():
    sizes[r] = sizes.get(r, 0) + 1
assert sizes == {"af": 62, "as": 53, "eu": 53, "na": 41, "oc": 26, "sa": 15}, sizes
aud = g_regions.audit(WORLD, meta_of)
assert aud["assigned"] == 250 and not aud["unassigned"], aud
ok("16. strategic regions unchanged: af 62 / as 53 / eu 53 / na 41 / oc 26 / sa 15, "
   "250 assigned, 0 unassigned")

# =========================================================== the pure rule, directly
W = CAT
T = {HOME: {"owner": "AlphaA", "troops": [{"type": "inf", "hp": 9}], "pop": 100},
     FAR_NEUTRAL: {"owner": "AlphaB", "troops": [{"type": "inf", "hp": 1}], "pop": 100}}
SQ = [{"type": "inf", "hp": 1}]
e = conquest.can_attack("AlphaA", HOME, FAR_NEUTRAL, SQ, W, T)
assert e.allowed and e.reason is None, e.reason
assert not W.are_adjacent(HOME, FAR_NEUTRAL), "and they really are not adjacent"
assert "not_adjacent" in conquest.AttackEligibility.REASONS, \
    "the reason string is retained for a stricter post-Alpha rule"
ok("the pure rule agrees with the endpoint, and 'not_adjacent' survives as an unused reason string")

httpd.shutdown()
print("\nAll %d global-conquest tests passed." % passed)
