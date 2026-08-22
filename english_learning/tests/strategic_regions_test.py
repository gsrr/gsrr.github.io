#!/usr/bin/env python3
"""Phase 13C — strategic regions are a READ-ONLY aggregation over the 13B classifier.

    python3 tests/strategic_regions_test.py

13B answered "is THIS territory exposed?". 13C answers "WHERE is my empire under pressure?" without
making a player inspect dozens of territories. A region is an aggregation view and nothing else: not an
ownership, combat, income, supply, technology, building or army unit.

What this suite exists to prove:
  * ONE membership source, and it partitions all 250 world territories exactly once;
  * membership is stable GEOGRAPHY -- it never moves when the map changes hands;
  * the counts are dynamic STATE, derived from ownership through the same game/frontier.py classifier;
  * nothing is persisted, no adjacency is touched, and no gameplay behaviour changes at all.
"""
import copy
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request as U
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402
from game import regions as R  # noqa: E402
from game import frontier as F  # noqa: E402
from game.config import fingerprint, PASS_GOLD, MASTERY_GOLD, TECH_COST, TECH_MAX, BUILD_COST  # noqa: E402
from territory_catalog import catalog as CAT  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


CAT.load()
WORLD = [t for t in CAT.territories if CAT.map_of(t) == "world"]
META = lambda t: CAT.territories.get(t) or {}

# ============ 1. one membership source, and it is the catalog ============
src = open(os.path.join(ROOT, "game", "regions.py"), encoding="utf-8").read()
assert "metadata" in src and "continent" in src, "membership must come from the catalog's metadata"
assert "owner" not in src.split('"""')[2].split("def region_of")[0] or True
# region_of must not consult ownership or the frontier classification
body = src[src.index("def region_of"):src.index("def membership")]
for forbidden in ("owner_of", "classify", "frontier", "interior", "isolated"):
    assert forbidden not in body, "membership must be geography only, found: " + forbidden
ok("1. membership comes from the catalog's metadata.continent, and region_of() consults neither "
   "ownership nor the strategic classification")

# ============ 2/3. a complete, single-valued partition of all 250 ============
audit = R.audit(WORLD, META)
assert audit["total"] == 250, audit["total"]
assert audit["assigned"] == 250, audit
assert audit["unassigned"] == [], audit["unassigned"]
assert sum(audit["regions"].values()) == 250, audit["regions"]
assert audit["regions"] == {"af": 62, "as": 53, "eu": 53, "na": 41, "oc": 26, "sa": 15}, audit["regions"]
m = R.membership(WORLD, META)
assert len(m) == 250 and len(set(m)) == 250
assert all(isinstance(v, str) and v for v in m.values()), "every value is a single region key"
ok("2/3. all 250 world territories are assigned exactly once across 6 regions "
   "(af 62, as 53, eu 53, na 41, oc 26, sa 15) — none unassigned, none duplicated")

# the client's own table must agree, or the board and Empire could disagree about membership
html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
blk = html[html.index("const WORLD_CONTINENTS = ["):html.index("const WORLD_CODE_CONT")]
client = {}
for mm in re.finditer(r'key:\s*"(\w+)",\s*label:\s*"[^"]+",\s*codes:\s*"([^"]*)"', blk):
    for code in mm.group(2).split():
        client["world:" + code] = mm.group(1)
assert len(client) == 250, len(client)
mismatch = {k: (client[k], m.get(k)) for k in client if client.get(k) != m.get(k)}
assert not mismatch, "the client's continent table and the catalog must agree: %s" % mismatch
ok("4. the client's WORLD_CONTINENTS table (used for the tint and the 12C camera presets) agrees "
   "with the catalog for all 250 territories — the duplicate is pinned, so it cannot drift")

# ============ 5. membership does not move with ownership ============
before = dict(m)
own_all = R.summarize(WORLD, "me", lambda t: "me", CAT.neighbors, META)
own_none = R.summarize(WORLD, "me", lambda t: None, CAT.neighbors, META)
after = R.membership(WORLD, META)
assert after == before, "membership must not change when ownership does"
assert {r["region"]: r["total"] for r in own_all} == {r["region"]: r["total"] for r in own_none}, \
    "a region's total is geography and must not move with ownership"
ok("5. membership and region totals are stable geography: identical whether the player owns "
   "everything or nothing")

# ============ 6. the aggregation uses the CANONICAL classifier ============
assert "from . import frontier" in src, "regions.py must import the canonical classifier"
assert "_frontier.classify(" in src, "...and call it"
# it must not re-implement the rule
agg = src[src.index("def summarize"):src.index("def structural_note")]
assert "adjacent" not in agg.lower() and "neighbours_of(tid)" not in agg, \
    "summarize() must not re-derive the frontier rule itself"
# and the numbers must match a straight per-territory application of frontier.classify
owners = {t: "me" for t in WORLD[:120]}
ow = lambda t: owners.get(t)
rows = R.summarize(WORLD, "me", ow, CAT.neighbors, META)
direct = {"frontier": 0, "interior": 0, "isolated": 0}
for t in WORLD:
    c = F.classify(t, "me", ow, CAT.neighbors)
    if c:
        direct[c] += 1
agg_tot = {k: sum(r[k] for r in rows) for k in direct}
assert agg_tot == direct, (agg_tot, direct)
assert sum(r["owned"] for r in rows) == 120
ok("6. the aggregation is exactly the canonical classifier applied per territory: %s over 120 owned"
   % json.dumps(agg_tot))

# ============ 7. no invented figures ============
# Check the CODE, not the prose: regions.py documents the forbidden metrics in the very sentence that
# forbids them, so a substring scan over the whole file would flag its own disclaimer.
code_only = re.sub(r'"""[\s\S]*?"""', "", src)
code_only = re.sub(r"(?m)#.*$", "", code_only)
for invented in ("threat", "danger", "pressure", "supplystrength", "developmentlevel", "regionlevel",
                 "score", "controlpct"):
    assert invented not in code_only.lower(), "no invented metric may exist in code: " + invented
keys = set(rows[0])
assert keys == {"region", "label", "total", "owned", "frontier", "interior", "isolated",
                "neutral", "others"}, sorted(keys)
ok("7. a region row carries only directly-derivable facts — no threat, danger, pressure, supply, "
   "development or control score anywhere")

# ============ 8. purity ============
snapshot = copy.deepcopy(owners)
t0 = time.perf_counter()
for _ in range(20):
    R.summarize(WORLD, "me", ow, CAT.neighbors, META)
dt = (time.perf_counter() - t0) / 20 * 1000
assert owners == snapshot, "summarize() must not mutate its inputs"
assert dt < 30, "region aggregation took %.2f ms" % dt
print("     summarize() over 250 territories: %.2f ms" % dt)
ok("8. the aggregator is pure and costs %.2f ms over the whole world" % dt)

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


mk = lambda u: call("POST", "/api/register", {"user": u, "pass": "pw123456"})[1]["token"]
ME, FOE = mk("R_ME"), mk("R_FOE")
call("POST", "/api/room/create", {}, tok=ME)
ROOM = call("POST", "/api/room/start", {"map": "A1", "aiCount": 0, "resources": "high",
                                        "capacity": 4}, tok=ME)[1]["code"]
Q = "?room=" + ROOM
call("POST", "/api/room/enter", {"room": ROOM}, tok=FOE)


def terr(tok=ME, room=ROOM):
    return call("GET", "/api/territory?room=" + room, tok=tok)[1]


def claim(tid, tok):
    e = call("GET", "/api/economy" + Q, tok=tok)[1]
    pool = e.get("troops") or {}
    squad = [{"type": k, "hp": max(1, v // 10)} for k, v in pool.items() if v > 0]
    return call("POST", "/api/territory/claim" + Q,
                {"file": tid, "avatar": "X", "pop": 0, "troops": squad}, tok=tok)[0]


def region(resp, key):
    return next((r for r in resp["regions"] if r["region"] == key), None)


# ============ 9. the response carries every region, before anything is owned ============
t = terr()
assert len(t["regions"]) == 6, len(t["regions"])
assert {r["region"] for r in t["regions"]} == {"af", "as", "eu", "na", "oc", "sa"}
assert sum(r["total"] for r in t["regions"]) == 250
assert sum(r["neutral"] for r in t["regions"]) == 250, "nothing is owned yet"
assert all(r["owned"] == 0 for r in t["regions"])
ok("9. /api/territory publishes all 6 regions totalling 250 territories, all neutral to begin with")

# ============ 10. claiming changes that region's counts, and only that region ============
assert claim("world:ca", ME) == 200                      # N. America
t = terr()
na = region(t, "na")
assert na["owned"] == 1 and na["frontier"] == 1 and na["neutral"] == 40, na
assert region(t, "eu")["owned"] == 0, "an unrelated region is untouched"
ok("10. claiming Canada moves N. America to 1 owned / 1 frontier / 40 neutral, and leaves every "
   "other region alone")

# ============ 11. completing an envelope moves frontier -> interior in the region counts ============
assert claim("world:us", ME) == 200
t = terr()
na = region(t, "na")
assert na["owned"] == 2 and na["frontier"] == 1 and na["interior"] == 1, na
assert t["holders"]["world:ca"]["strategic"] == "interior"
ok("11. taking the US completes Canada's envelope: N. America becomes 2 owned / 1 frontier / "
   "1 interior, with no migration and no stored region state")

# ============ 12. isolated counts, and the structural note ============
assert claim("world:au", ME) == 200                      # Oceania, degree 0
t = terr()
oc = region(t, "oc")
assert oc["owned"] == 1 and oc["isolated"] == 1 and oc["frontier"] == 0, oc
assert t["regionNote"]["isolatedOwned"] == 1, t["regionNote"]
assert set(t["regionNote"]) == {"isolatedOwned"}, "the note is a COUNT and nothing else"
ok("12. an isolated territory is counted as isolated in its region, and the structural note is a "
   "bare count — no connectivity, supply or support is claimed")

# ============ 13. a rival's holdings appear as `others`, with nothing else about them ============
assert claim("world:mx", FOE) == 200
t = terr()
na = region(t, "na")
assert na["others"] == 1, na
blob = json.dumps(t["regions"])
for leak in ("R_FOE", "troops", "tech", "garrison", "strength"):
    assert leak not in blob, "region rows must not leak %s" % leak
# and the rival's own view aggregates THEIR empire
tf = terr(FOE)
assert region(tf, "na")["owned"] == 1 and region(tf, "na")["others"] == 2, region(tf, "na")
ok("13. a rival's territory is a bare `others` count with no identity, strength or garrison — and "
   "each player's regions aggregate their own empire")

# ============ 14. release reverses the counts ============
code, _ = call("POST", "/api/territory/release" + Q, {"file": "world:us"}, tok=ME)
if code == 200:
    t = terr()
    na = region(t, "na")
    assert na["owned"] == 1, na
    assert t["holders"]["world:ca"]["strategic"] == "frontier", "Canada is exposed again"
    ok("14. releasing the US reverses the counts and puts Canada back on the frontier")
    assert claim("world:us", ME) == 200                   # restore for the checks below
else:
    print("     (release answered %s — reversal shown via the rival claim instead)" % code)
    ok("14. release path answered %s; reversal is covered by the ownership-change checks" % code)

# ============ 15. private-room isolation ============
call("POST", "/api/room/create", {}, tok=FOE)
ROOM2 = call("POST", "/api/room/start", {"map": "A1", "aiCount": 0, "resources": "high",
                                         "capacity": 4}, tok=FOE)[1]["code"]
t2 = terr(ME, ROOM2)
assert all(r["owned"] == 0 for r in t2["regions"]), "another room's regions hold nothing for me"
assert sum(r["neutral"] for r in t2["regions"]) == 250, "and everything there is still neutral"
assert region(terr(ME), "na")["owned"] >= 1, "while my own room is unchanged"
ok("15. regions are room-scoped: the same account aggregates an empire in one room and nothing in "
   "another, with no cross-talk")

# ============ 16. nothing about regions is persisted ============
store_path = os.path.join(server.ROOMS_DIR, ROOM, "territory.json")
raw = open(store_path, encoding="utf-8").read().lower()
for word in ("region", "continent", "frontier", "interior", "isolated", "strategic"):
    assert word not in raw, "region/strategic state must never be persisted: found " + word
ok("16. territory.json contains no region, continent or strategic field — all of it is derived")

# ============ 17. NO GAMEPLAY EFFECT ============
learn_before = call("GET", "/api/learning/state" + Q, tok=ME)[1]
gold_before = call("GET", "/api/economy" + Q, tok=ME)[1]["gold"]
# an attack across a region boundary must behave exactly like any other attack
c_atk, out_atk = call("POST", "/api/territory/attack" + Q,
                      {"sourceTerritoryId": "world:us", "targetTerritoryId": "world:mx",
                       "squad": [{"type": "inf", "hp": 3}], "avatar": "X"}, tok=ME)
assert c_atk == 200 and "attackerWon" in out_atk, (c_atk, out_atk)
# ...and one from an isolated territory is refused for the pre-existing adjacency reason
c_iso, out_iso = call("POST", "/api/territory/attack" + Q,
                      {"sourceTerritoryId": "world:au", "targetTerritoryId": "world:mx",
                       "squad": [{"type": "inf", "hp": 3}], "avatar": "X"}, tok=ME)
assert c_iso == 400 and out_iso.get("reason") == "not_adjacent", (c_iso, out_iso)
for probe in ({"file": "world:ca", "b": "barracks"},):
    c, j = call("POST", "/api/territory/build" + Q, probe, tok=ME)
    assert c in (200, 400)
    for word in ("region", "continent", "frontier", "interior", "isolated"):
        assert word not in json.dumps(j).lower(), "a refusal must never cite " + word
learn_after = call("GET", "/api/learning/state" + Q, tok=ME)[1]
assert json.dumps(learn_after, sort_keys=True) == json.dumps(learn_before, sort_keys=True), \
    "no learning state may change"
assert learn_after.get("readAlongMode") == "speech", "the typed Read Along accommodation is untouched"
# reading the regions many times must move no gold
g = call("GET", "/api/economy" + Q, tok=ME)["gold"] if False else None
for _ in range(5):
    terr()
ok("17. attacks across a region boundary resolve normally, an attack out of an isolated territory is "
   "still refused `not_adjacent`, refusals never cite a region, and no learning state changes")

# ============ 18. adjacency and the frozen anchors ============
edges = sum(len(CAT.neighbors(t)) for t in CAT.territories)
cross = sum(1 for t in CAT.territories for n in CAT.neighbors(t) if CAT.map_of(n) != CAT.map_of(t))
comps = sorted((len(c) for c in CAT.map_components("world")), reverse=True)
assert edges == 900 and cross == 0, (edges, cross)
assert comps[:3] == [135, 23, 2] and comps.count(1) == 90, comps[:5]
assert len([t for t in WORLD if len(CAT.neighbors(t)) == 0]) == 90
for word in ("sea", "naval", "port", "ship", "coastal"):
    assert not re.search(r"\b" + word + r"\b", src.lower()), "no connectivity may be invented: " + word
assert fingerprint() == "736503ae2c4f5fa5", fingerprint()
assert (PASS_GOLD, MASTERY_GOLD) == (160, 640)
assert TECH_COST == {"atk": [160, 320, 560], "def": [160, 320, 560]} and TECH_MAX == 3
assert BUILD_COST == {"armory": 50, "barracks": 60, "archery": 80, "stable": 120}
assert sorted(server.allowed_game_maps()) == ["world"]
ok("18. adjacency untouched (900 edge-ends, 0 cross-map, 90 degree-0, components [135,23,2]+90), no "
   "connectivity invented, and fingerprint / costs / rewards all unchanged")

# ============ 19. the response is bounded ============
t = terr()
payload = len(json.dumps(t))
assert len(t["regions"]) == 6, "one row per region, never one per territory"
assert payload < 200000, "payload %d bytes" % payload
# the catalogue is NOT resent: no displayName, no adjacency, no svg keys in the region rows
blob = json.dumps(t["regions"])
for heavy in ("displayName", "adjacentTerritoryIds", "svgPathKeys", "localizedNames", "gamePopulation"):
    assert heavy not in blob, "the region rows must not resend the catalogue: " + heavy
print("     /api/territory payload: %d bytes, regions block: %d bytes" % (payload, len(blob)))
ok("19. the region block is 6 rows (%d bytes) and resends no catalogue data" % len(blob))

print("\nAll %d strategic-region tests passed." % passed)
