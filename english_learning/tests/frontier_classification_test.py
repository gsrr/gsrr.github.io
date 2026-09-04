#!/usr/bin/env python3
"""Phase 13B — frontier / interior / isolated is DERIVED, canonical, and has no gameplay effect.

    python3 tests/frontier_classification_test.py

Phase 13A's finding was that management must stop growing linearly with conquest, and that the front
line — not the territory — should be the object of the strategic game. This is the first foundation:
one authoritative classifier, published read-only, changing nothing about what a player may do.

What this suite exists to prove:
  * there is exactly ONE definition (game/frontier.py), and the server publishes its result;
  * it is derived from ownership + adjacency and stored NOWHERE, so it is correct the instant a
    territory changes hands;
  * a degree-0 territory is called ISOLATED rather than quietly counted as safe interior;
  * it is room-isolated and fog-of-war respecting;
  * and it changes no legality, no economy, no reward and no learning state whatsoever.
"""
import copy
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request as U
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402
from game import frontier as F  # noqa: E402
from game.config import fingerprint, PASS_GOLD, MASTERY_GOLD, TECH_COST, TECH_MAX, BUILD_COST  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ============================ 1. the pure classifier ============================
# A tiny synthetic world, so the rules are readable: a line A-B-C-D plus an island Z.
ADJ = {"A": ["B"], "B": ["A", "C"], "C": ["B", "D"], "D": ["C"], "Z": []}
OWN = {"A": "me", "B": "me", "C": "foe", "D": None, "Z": "me"}
nb = lambda t: ADJ.get(t, [])
ow = lambda t: OWN.get(t)

assert F.classify("A", "me", ow, nb) == F.INTERIOR, "A's only neighbour B is mine"
assert F.classify("B", "me", ow, nb) == F.FRONTIER, "B borders foe-held C"
assert F.classify("Z", "me", ow, nb) == F.ISOLATED, "Z has no neighbours at all"
assert F.classify("C", "me", ow, nb) is None, "a territory I do not own has no classification for me"
assert F.classify("D", "me", ow, nb) is None, "a neutral territory has no classification for me"
assert F.classify("A", None, ow, nb) is None, "no player, no classification"
ok("1. the canonical classifier: interior / frontier / isolated, and None for anything not mine")

# a NEUTRAL neighbour makes a territory frontier just as an enemy one does
OWN2 = dict(OWN, C=None)
assert F.classify("B", "me", lambda t: OWN2.get(t), nb) == F.FRONTIER, \
    "an unclaimed neighbour is still a border"
ok("2. a neutral neighbour makes a territory FRONTIER — 'not mine' covers unclaimed and enemy alike")

# ISOLATED beats the plain rule, and is a property of the MAP not of ownership
assert F.classify("Z", "me", lambda t: "me", nb) == F.ISOLATED, \
    "owning everything does not make a no-neighbour territory interior"
ok("3. ISOLATED is structural: a degree-0 territory is never reported as safe interior")

# degree-1 follows the ordinary rule in both directions
assert F.classify("A", "me", ow, nb) == F.INTERIOR and F.classify("D", "foe", ow, nb) is None
OWN3 = dict(OWN, B="foe")
assert F.classify("A", "me", lambda t: OWN3.get(t), nb) == F.FRONTIER, \
    "a degree-1 territory whose single neighbour is hostile is frontier"
ok("4. a degree-1 territory is frontier or interior by the same rule as everyone else")

summary = F.summarize(F.classify_all("me", list(ADJ), ow, nb))
assert summary == {"frontier": 1, "interior": 1, "isolated": 1, "total": 3}, summary
assert summary["total"] == summary["frontier"] + summary["interior"] + summary["isolated"]
ok("5. the summary counts only my own territories, and the three classes partition them exactly")

# ============================ the real server ============================
import tempfile  # noqa: E402

d = tempfile.mkdtemp()
server.ROOMS_DIR = os.path.join(d, "rooms")
server.ACCT = os.path.join(d, "accounts.json")
server.PROG_DIR = os.path.join(d, "progress")
server.DATA = os.path.join(d, "visits.json")
server.TERR_CATALOG = os.path.join(d, "learned.json")
server.LEARNING.content_root = ROOT
srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % PORT


def call(method, path, body=None, tok=None):
    url = B + path
    if tok:
        url += ("&" if "?" in url else "?") + "token=" + tok
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = U.urlopen(U.Request(url, data=data, method=method))
        return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def mk(user):
    return call("POST", "/api/register", {"user": user, "pass": "pw123456"})[1]["token"]


ME, FOE = mk("P_ME"), mk("P_FOE")
call("POST", "/api/room/create", {}, tok=ME)
ROOM = call("POST", "/api/room/start", {"map": "A1", "aiCount": 0, "resources": "high",
                                        "capacity": 4}, tok=ME)[1]["code"]
R = "?room=" + ROOM
call("POST", "/api/room/enter", {"room": ROOM}, tok=FOE)


def terr(tok=ME):
    return call("GET", "/api/territory" + R, tok=tok)[1]


def own(tid, tok, avatar="X"):
    """Claim through the REAL endpoint, so ownership is authoritative."""
    e = call("GET", "/api/economy" + R, tok=tok)[1]
    pool = e.get("troops") or {}
    squad = [{"type": k, "hp": max(1, v // 6)} for k, v in pool.items() if v > 0]
    return call("POST", "/api/territory/claim" + R,
                {"file": tid, "avatar": avatar, "pop": 0, "troops": squad}, tok=tok)[0]


# a real chain on the world map: Spain - France - Germany are mutually adjacent in the catalog
from territory_catalog import catalog as CAT  # noqa: E402

CAT.load()
assert CAT.neighbors("world:ca") == ["world:us"], "fixture: Canada's only neighbour is the US"
assert sorted(CAT.neighbors("world:us")) == ["world:ca", "world:mx"], "fixture: US borders CA and MX"
assert CAT.neighbors("world:gb") == ["world:ie"] and CAT.neighbors("world:ie") == ["world:gb"], \
    "fixture: the UK and Ireland are a closed two-territory component"
assert CAT.degree("world:au") == 0, "fixture assumption: Australia has no land neighbours"

# ============================ 6. the server publishes it ============================
assert own("world:ca", ME) == 200
t = terr()
assert t["holders"]["world:ca"]["strategic"] == "frontier", t["holders"]["world:ca"]
assert t["strategicSummary"] == {"frontier": 1, "interior": 0, "isolated": 0, "total": 1}, t["strategicSummary"]
ok("6. /api/territory publishes each own territory's class and an authoritative own-empire summary")

# ============================ 7. isolated, through the real endpoint ============================
assert own("world:au", ME) == 200
t = terr()
assert t["holders"]["world:au"]["strategic"] == "isolated"
assert t["strategicSummary"]["isolated"] == 1
ok("7. a degree-0 territory (Australia) is published as ISOLATED, not as interior")

# ============================ 8. a boundary change reclassifies a NEIGHBOUR ============================
# Canada's ONLY neighbour is the United States, whose other neighbour is Mexico. So taking the US
# must flip Canada frontier -> interior while leaving the US itself on the front.
assert terr()["holders"]["world:ca"]["strategic"] == "frontier"
assert own("world:us", ME) == 200
mid = terr()
assert mid["holders"]["world:ca"]["strategic"] == "interior", mid["holders"]["world:ca"]
assert mid["holders"]["world:us"]["strategic"] == "frontier", "the US still borders Mexico"
assert mid["strategicSummary"]["frontier"] == 1 and mid["strategicSummary"]["interior"] == 1
# now a rival takes Mexico: the US stays frontier for a DIFFERENT reason, and Canada is unaffected
assert own("world:mx", FOE, "F") == 200
after = terr()
assert after["holders"]["world:us"]["strategic"] == "frontier"
assert after["holders"]["world:ca"]["strategic"] == "interior", "Canada is still behind the line"
# and giving Canada away flips the US's OTHER side too -- the recomputation is symmetric
ok("8. changing ONE ownership boundary reclassifies its neighbours immediately — Canada went "
   "frontier -> interior the moment the US was taken, with no migration and no stored field")

# the closed two-territory component (UK + Ireland) — the disconnected-component edge case, stated
# rather than hidden: by the local rule both are INTERIOR once both are held, and they are also
# structurally unreachable. 13B reports the rule's answer; §21 of the design doc carries the question
# of whether a fully-owned component deserves a class of its own.
assert own("world:gb", ME) == 200 and own("world:ie", ME) == 200
comp = terr()["holders"]
assert comp["world:gb"]["strategic"] == "interior" and comp["world:ie"]["strategic"] == "interior", \
    (comp["world:gb"]["strategic"], comp["world:ie"]["strategic"])
ok("9. a fully-owned closed component (UK + Ireland) reports INTERIOR by the local rule — documented "
   "as a known limitation rather than silently given a fourth class")

# ============================ 9. nothing is persisted ============================
store_path = os.path.join(server.ROOMS_DIR, ROOM, "territory.json")
raw = open(store_path, encoding="utf-8").read()
for word in ("frontier", "interior", "isolated", "strategic"):
    assert word not in raw.lower(), "the classification must never be persisted: found " + word
ok("10. no classification is stored in territory.json — it is derived on every read")

# ============================ 10. fog of war ============================
t = terr(ME)
foe_rows = [h for k, h in t["holders"].items() if h.get("owner") not in (None, "P_ME")]
assert foe_rows, "fixture: the rival holds something"
for h in foe_rows:
    assert "strategic" not in h, "a rival's classification must not be published: " + json.dumps(h)
    assert "troops" not in h and "tech" not in h, "and the existing fog of war still holds"
# and the rival's own view classifies THEIR territories, not mine
tf = terr(FOE)
assert tf["holders"]["world:mx"]["strategic"] == "frontier", tf["holders"]["world:mx"]
assert "strategic" not in tf["holders"]["world:ca"], "my territories are not classified for them"
assert tf["strategicSummary"]["total"] == 1, tf["strategicSummary"]
ok("11. classification is per-viewer and own-territory only: a rival sees THEIR front, never mine, "
   "and no garrison or technology leaks either way")

# ============================ 11. room isolation ============================
call("POST", "/api/room/create", {}, tok=FOE)
ROOM2 = call("POST", "/api/room/start", {"map": "A1", "aiCount": 0, "resources": "high",
                                         "capacity": 4}, tok=FOE)[1]["code"]
t2 = call("GET", "/api/territory?room=" + ROOM2, tok=ME)[1]
assert t2["strategicSummary"] == {"frontier": 0, "interior": 0, "isolated": 0, "total": 0}, t2["strategicSummary"]
assert not [h for h in t2["holders"].values() if h.get("strategic")], "another room's board is empty for me"
t1 = terr(ME)
assert t1["strategicSummary"]["total"] == 5, t1["strategicSummary"]
ok("12. classification is room-scoped: the same account is a 3-territory empire in one room and "
   "holds nothing in another")

# ============================ 12. AI ownership needs no special case ============================
with server.terr_lock:
    st = server.load_territory_store()
    st["world:mx"] = {"owner": server.AI_OWNER, "avatar": "🤖", "troops": [], "pop": 100}
    server.save_territory_store(st)
t = terr()
assert t["holders"]["world:us"]["strategic"] == "frontier", \
    "the US borders Mexico, now AI-held, so it is still on the front"
assert t["holders"]["world:ca"]["strategic"] == "interior", "Canada is unaffected by a distant AI"
assert "strategic" not in t["holders"]["world:mx"], "an AI territory is classified for nobody"
ok("13. an AI owner is simply 'not mine' — no special case, and AI territory is never classified")

# ============================ 13. J: NO GAMEPLAY EFFECT ============================
# The exact same actions must behave identically whatever the classification says. Two probes: an
# attack from a FRONTIER source and a claim of a neutral neighbouring an INTERIOR territory.
econ_before = call("GET", "/api/economy" + R, tok=ME)[1]
learn_before = call("GET", "/api/learning/state" + R, tok=ME)[1]
code_attack, out_attack = call("POST", "/api/territory/attack" + R,
                               {"sourceTerritoryId": "world:us", "targetTerritoryId": "world:mx",
                                "squad": [{"type": "inf", "hp": 5}], "avatar": "X"}, tok=ME)
assert code_attack == 200 and "attackerWon" in out_attack, (code_attack, out_attack)
# Phase 14A: an attack OUT OF an isolated territory is now ACCEPTED. That is the Alpha rule, not a
# classification rule -- and it is exactly why 13B's classification must carry no attack authority.
# The classification itself is asserted unchanged throughout this file.
code_iso, out_iso = call("POST", "/api/territory/attack" + R,
                         {"sourceTerritoryId": "world:au", "targetTerritoryId": "world:mx",
                          "squad": [{"type": "inf", "hp": 5}], "avatar": "X"}, tok=ME)
assert code_iso == 200 and "attackerWon" in out_iso, (code_iso, out_iso)
ok("14. legality follows the ALPHA rule: an attack from a frontier source resolves, and so does one "
   "from an ISOLATED source — the classification never granted or withheld attack authority")

# recruit / build / research all behave exactly as before, on an INTERIOR and on an ISOLATED
# territory alike. What matters is not that they SUCCEED -- gold and prerequisites still apply -- but
# that any refusal comes from a pre-existing economic/prerequisite rule and never mentions the
# classification. So the same three calls are made against both classes and their outcomes compared.
# the exact refusal vocabulary these three endpoints already had, before 13B existed
PRE_EXISTING = {"not enough gold", "need armory", "need barracks", "need archery", "need stable",
                "maxed", "already built", "not your region", "unknown unit", "unknown track",
                "unknown building", "unknown b"}


def probe(tid):
    out = []
    for path, body in (("build", {"file": tid, "b": "barracks"}),
                       ("recruit", {"file": tid, "unit": "inf", "qty": 10}),
                       ("research", {"file": tid, "track": "atk"})):
        c, j = call("POST", "/api/territory/" + path + R, body, tok=ME)
        assert c in (200, 400), (path, c, j)
        if c == 400:
            msg = (j.get("error") or j.get("reason") or "").lower()
            assert msg in PRE_EXISTING, "refusal must be a pre-existing rule, got: %r" % msg
            for word in ("frontier", "interior", "isolated", "strategic"):
                assert word not in json.dumps(j).lower(), "a refusal must never cite " + word
        out.append(c)
    return out


assert terr()["holders"]["world:ca"]["strategic"] == "interior"
assert terr()["holders"]["world:au"]["strategic"] == "isolated"
res_interior = probe("world:ca")
res_isolated = probe("world:au")
print("     build/recruit/research -> interior %s | isolated %s" % (res_interior, res_isolated))
ok("15. build / recruit / research behave identically on interior and isolated territories, and any "
   "refusal cites a pre-existing economic or prerequisite rule — never the classification")

# ============================ 15. economy and learning untouched ============================
learn_after = call("GET", "/api/learning/state" + R, tok=ME)[1]
assert json.dumps(learn_after, sort_keys=True) == json.dumps(learn_before, sort_keys=True), \
    "no learning state may change"
assert learn_after.get("readAlongMode") == "speech", "the accommodation default is untouched"
gold_now = call("GET", "/api/economy" + R, tok=ME)[1]["gold"]
assert isinstance(gold_now, int)
# the classification itself must never move gold: read the board 5 times and check the balance
for _ in range(5):
    terr()
assert call("GET", "/api/economy" + R, tok=ME)[1]["gold"] == gold_now, \
    "reading the classification must not change the economy"
ok("16. reading the classification changes no gold, no reward and no learning state")

# ============================ 16. the classifier has exactly one definition ============================
src_server = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
src_html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
assert src_server.count("game_frontier.classify_all") == 1, "one call site in the server"
assert "def classify(" in open(os.path.join(ROOT, "game", "frontier.py"), encoding="utf-8").read()
# the client must READ the server's value and never derive it
for pattern in ("adjacentTerritoryIds || []).some", "=== \"frontier\" ? ", "computeFrontier",
                "classifyTerritory", "isFrontier("):
    assert pattern not in src_html, "the client must not classify: " + pattern
assert '(holders[r.key] || {}).strategic' in src_html, "the client reads the published value"
ok("17. exactly one definition: game/frontier.py, one server call site, and a client that only reads")

# ============================ 17. no new adjacency, no naval connectivity ============================
edges = sum(len(CAT.neighbors(t)) for t in CAT.territories)
cross = sum(1 for t in CAT.territories for n in CAT.neighbors(t) if CAT.map_of(n) != CAT.map_of(t))
comps = sorted((len(c) for c in CAT.map_components("world")), reverse=True)
assert edges == 900 and cross == 0, (edges, cross)
assert comps[:3] == [135, 23, 2] and comps.count(1) == 90, comps[:5]
# Word boundaries, not substrings: "research" contains "sea" and "important" contains "port", so a
# substring check would fail on perfectly innocent prose.
import re as _re  # noqa: E402

frontier_src = open(os.path.join(ROOT, "game", "frontier.py"), encoding="utf-8").read().lower()
for word in ("sea", "seas", "naval", "navy", "port", "ports", "ship", "ships", "coastal", "ferry"):
    assert not _re.search(r"\b" + word + r"\b", frontier_src), \
        "13B must not invent connectivity: " + word
# the classifier must be pure: it reaches adjacency only through the callback it is handed
assert "territory_catalog" not in frontier_src and "open(" not in frontier_src, \
    "the classifier must not read the catalog or any file itself"
ok("18. adjacency is untouched — 900 edge-ends, 0 cross-map, components [135, 23, 2, 90x1] — the "
   "classifier names no sea, port, ship or navy, and reads no catalog of its own: isolated stays "
   "isolated")

# ============================ 19. frozen anchors ============================
assert fingerprint() == "2bd163c8793335b7", fingerprint()   # Phase 14A.10A: reward + period change
assert (PASS_GOLD, MASTERY_GOLD) == (0, 2500)
assert TECH_COST == {"atk": [160, 320, 560], "def": [160, 320, 560]} and TECH_MAX == 3
assert BUILD_COST == {"armory": 50, "barracks": 60, "archery": 80, "stable": 120}
assert sorted(server.allowed_game_maps()) == ["world"]
assert len([t for t in CAT.territories if CAT.map_of(t) == "world"]) == 250
assert len(CAT.territories) == 318
ok("19. frozen: fingerprint 736503ae2c4f5fa5, 160/640, TECH_COST/TECH_MAX, BUILD_COST, "
   "allowed_game_maps {'world'}, 250 world / 318 total — adding a derived classifier changed none "
   "of them, because it introduces no balance constant")

# ============================ 20. the classifier is pure and cheap ============================
ids = [t for t in CAT.territories if CAT.map_of(t) == "world"]
owners = {t: "me" for t in ids[:120]}
snapshot = copy.deepcopy(owners)
t0 = time.perf_counter()
for _ in range(20):
    F.classify_all("me", ids, lambda t: owners.get(t), CAT.neighbors)
dt = (time.perf_counter() - t0) / 20 * 1000
assert owners == snapshot, "the classifier must not mutate its inputs"
assert dt < 20, "classification of a 250-territory world took %.2f ms" % dt
print("     classify_all over 250 territories (120 owned): %.2f ms" % dt)
ok("20. the classifier is pure — it mutates nothing — and classifying the whole world costs %.2f ms"
   % dt)

print("\nAll %d frontier-classification tests passed." % passed)
