"""Phase 10A.2.1 — conquest adjacency is validated over GLOBAL territory ids, not per map.

    python tests/adjacency_global_id_test.py

Conquest adjacency and the navigation hierarchy are two different graphs. Navigation nests maps
(world -> taiwan -> taipei); conquest joins playable territories that share a land border. A border
can cross a map boundary — `taiwan:new-taipei-city` and `taipei:beitou` are on different maps but
would share real ground — so the validator must reason about territory ids globally.

Before this phase it could not. `tools/validate_territory_catalog.py` enforced same-map adjacency in
TWO places, both inside the per-map loop:

  1. a neighbour id had to start with the declaring map's id, and
  2. neighbour existence + symmetry were checked against that one map's id set.

This suite pins the new behaviour. It runs the real validator against synthetic world-data trees, so
it tests the shipped tool rather than a copy of its logic. Production data is never modified: today
world-data still contains 0 cross-map edges, so the validator's verdict on it is unchanged.
"""
import json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8")

VALIDATOR = os.path.join(ROOT, "tools", "validate_territory_catalog.py")
passed = 0


def ok(msg):
    global passed
    passed += 1
    print("  ok - " + msg)


def territory(tid, map_id, path_key, neighbours):
    return {
        "id": tid, "mapId": map_id, "regionCode": path_key,
        "displayName": tid, "localizedNames": {"en": tid},
        "svgPathKeys": [path_key], "administrativeCode": None,
        "gamePopulation": 100,
        "populationSource": {"value": None, "year": None, "sourceName": None, "sourceUrl": None},
        "metadata": {}, "terrainType": None, "settlementType": None, "features": [],
        "adjacentTerritoryIds": sorted(neighbours),
        "economy": None, "quests": [], "ai": None, "events": [],
        "_meta": {"schemaVersion": 1, "catalogVersion": 1, "generatedBy": "tests",
                  "generatedAt": "2026-01-01T00:00:00.000Z", "generatorVersion": "1.0.0",
                  "lastDesignerEdit": None},
    }


# For maps other than china/world the validator's isRegion rule requires an aria-label, mirroring
# index.html. The synthetic maps therefore carry one, exactly like maps/taiwan.svg does.
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
       '<path id="%s" aria-label="%s" d="M0,0 L1,0 L1,1 Z"/>'
       '<path id="%s" aria-label="%s" d="M2,2 L3,2 L3,3 Z"/></svg>')


def build(tmp, edges):
    """A two-map world: alpha{a1,a2}, beta{b1,b2}. `edges` is {tid: [neighbour, ...]}."""
    wd = os.path.join(tmp, "world-data")
    os.makedirs(os.path.join(wd, "territories"))
    os.makedirs(os.path.join(tmp, "maps"))
    json.dump({"schemaVersion": 1}, open(os.path.join(wd, "catalog.json"), "w"))
    maps = [{"id": "alpha", "svgFile": "maps/alpha.svg", "name": "Alpha",
             "childMaps": ["beta"]},
            {"id": "beta", "svgFile": "maps/beta.svg", "name": "Beta", "parentMap": "alpha"}]
    json.dump(maps, open(os.path.join(wd, "maps.json"), "w"))
    for mid, keys in (("alpha", ("a1", "a2")), ("beta", ("b1", "b2"))):
        open(os.path.join(tmp, "maps", mid + ".svg"), "w").write(
            SVG % (keys[0], keys[0], keys[1], keys[1]))
        rows = [territory("%s:%s" % (mid, k), mid, k,
                          edges.get("%s:%s" % (mid, k), [])) for k in keys]
        json.dump(rows, open(os.path.join(wd, "territories", mid + ".json"), "w"))
    return wd


def run(tmp):
    """Run the real validator FROM INSIDE the sandbox. It resolves world-data from its own
    __file__, so the copy under tmp/tools/ is what isolates the synthetic tree."""
    r = subprocess.run([sys.executable, os.path.join(tmp, "tools", "validate_territory_catalog.py")],
                       cwd=tmp, capture_output=True, text=True, errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# the validator resolves world-data relative to its own location, so copy it into the sandbox
def sandbox(edges):
    tmp = tempfile.mkdtemp()
    build(tmp, edges)
    os.makedirs(os.path.join(tmp, "tools"))
    shutil.copy(VALIDATOR, os.path.join(tmp, "tools", "validate_territory_catalog.py"))
    shutil.copy(os.path.join(ROOT, "territory_catalog.py"), os.path.join(tmp, "territory_catalog.py"))
    code, out = run(tmp)
    shutil.rmtree(tmp, ignore_errors=True)
    return code, out


# ============================== 1. same-map edges still valid ==============================
code, out = sandbox({"alpha:a1": ["alpha:a2"], "alpha:a2": ["alpha:a1"]})
assert code == 0, out[-800:]
ok("1. a symmetric SAME-map edge still validates (no regression for today's data)")

# ============================== 2. cross-map symmetric edge is valid ==============================
code, out = sandbox({"alpha:a1": ["beta:b1"], "beta:b1": ["alpha:a1"]})
assert code == 0, out[-800:]
assert "cross-map adjacency edge-end" in out, out[-500:]
ok("2. a symmetric CROSS-map edge validates and is reported as such — this is what the whole "
   "container migration needs and what the old per-map validator made impossible")

# ============================== 3. cross-map asymmetric edge fails ==============================
code, out = sandbox({"alpha:a1": ["beta:b1"]})
assert code != 0, out[-800:]
assert "not symmetric" in out, out[-500:]
ok("3. a one-directional cross-map edge is REJECTED (symmetry is enforced globally, not per map)")

# ============================== 4. unknown global id fails ==============================
code, out = sandbox({"alpha:a1": ["beta:nope"], "beta:b1": []})
assert code != 0, out[-800:]
assert "does not exist in any map" in out, out[-500:]
ok("4. a neighbour id that exists on no map is REJECTED")

# ============================== 5. unknown map prefix fails ==============================
code, out = sandbox({"alpha:a1": ["ghost:x"]})
assert code != 0, out[-800:]
assert "unknown map" in out, out[-500:]
ok("5. a neighbour naming an unknown map is REJECTED")

# ============================== 6. self-edge fails ==============================
code, out = sandbox({"alpha:a1": ["alpha:a1"]})
assert code != 0, out[-800:]
assert "self-adjacency" in out, out[-500:]
ok("6. a self-edge is still REJECTED")

# ============================== 7. non-canonical id fails ==============================
code, out = sandbox({"alpha:a1": ["maps/alpha.svg#a2"]})
assert code != 0, out[-800:]
assert "non-canonical" in out or "canonical territory id" in out, out[-500:]
ok("7. a legacy/SVG-key neighbour is still REJECTED")

# ============================== 8. production data is untouched and still clean ==============
prod = json.load(open(os.path.join(ROOT, "world-data", "maps.json"), encoding="utf-8"))
adj, ids = {}, set()
for m in prod:
    for t in json.load(open(os.path.join(ROOT, "world-data", "territories", m["id"] + ".json"),
                            encoding="utf-8")):
        ids.add(t["id"])
        adj[t["id"]] = list(t.get("adjacentTerritoryIds") or [])
cross = [(a, b) for a, ns in adj.items() for b in ns
         if b in ids and b.split(":", 1)[0] != a.split(":", 1)[0]]
assert len(ids) == 318, len(ids)
assert sum(len(v) for v in adj.values()) == 900, sum(len(v) for v in adj.values())
assert not cross, cross[:5]
r = subprocess.run([sys.executable, VALIDATOR], cwd=ROOT, capture_output=True, text=True,
                   errors="replace")
assert r.returncode == 0, (r.stdout or "")[-600:]
ok("8. production world-data is unchanged (318 territories, 900 edge-ends, 0 cross-map edges) and "
   "still validates — the widened rule is strictly permissive, so today's verdict is identical")

print("\nAll %d global-id adjacency tests passed." % passed)
