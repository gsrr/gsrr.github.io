#!/usr/bin/env python3
"""Phase 1C — territory adjacency graph tests (World Domain, not Game Domain).

    python3 tests/adjacency_test.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from territory_catalog import TerritoryCatalog, catalog  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


catalog.load()

# ---------- query API on the real authoritative catalog ----------
assert catalog.neighbors("world:fr") == sorted(catalog.neighbors("world:fr")), "neighbors sorted"
assert catalog.are_adjacent("world:fr", "world:de") and catalog.are_adjacent("world:de", "world:fr")
assert catalog.degree("china:pBJ") == len(catalog.neighbors("china:pBJ"))
assert catalog.neighbors("world:doesnotexist") == [] and catalog.degree("world:doesnotexist") == 0
assert catalog.connected_component("world:doesnotexist") == set()
ok("neighbors / are_adjacent / degree / unknown handled")

# ---------- symmetry, no self, no dup, sorted — across the WHOLE catalog ----------
selfx = dupx = unsorted = asym = 0
for tid, t in catalog.territories.items():
    a = t.get("adjacentTerritoryIds") or []
    if tid in a:
        selfx += 1
    if len(a) != len(set(a)):
        dupx += 1
    if a != sorted(a):
        unsorted += 1
    for nb in a:
        if tid not in (catalog.territories.get(nb, {}).get("adjacentTerritoryIds") or []):
            asym += 1
assert selfx == 0 and dupx == 0 and unsorted == 0 and asym == 0, (selfx, dupx, unsorted, asym)
ok("whole catalog: no self-edges, no duplicates, sorted, fully symmetric")

# ---------- canonical ids only (no legacy/SVG/suffix identities) ----------
bad = []
for tid, t in catalog.territories.items():
    for nb in (t.get("adjacentTerritoryIds") or []):
        if "#" in nb or "/" in nb or nb not in catalog.territories:
            bad.append((tid, nb))
assert not bad, bad[:5]
ok("adjacency uses canonical territory ids only (no legacy/SVG/suffix)")

# ---------- representative positive land borders per map ----------
assert catalog.are_adjacent("world:us", "world:mx")
assert catalog.are_adjacent("world:gb", "world:ie")        # NI/ROI real land border
assert catalog.are_adjacent("china:pBJ", "china:pHE")      # Beijing enclosed by Hebei
assert catalog.are_adjacent("taipei:xinyi", "taipei:daan")
# taiwan: a real adjacent county pair
assert catalog.degree("taiwan:taichung-city") > 0
ok("representative positive land borders present (taiwan/taipei/china/world)")

# ---------- mandated NEGATIVE cases (sea proximity must NOT be land adjacency) ----------
for a, b in [("world:tw", "world:cn"), ("world:jp", "world:kr"),
             ("world:gb", "world:fr"), ("world:au", "world:id")]:
    assert not catalog.are_adjacent(a, b), (a, b)
ok("negative cases excluded (tw~cn, jp~kr, gb~fr, au~id)")

# ---------- legitimate islands are isolated (INFO, not error) ----------
assert catalog.degree("china:pTW") == 0 and catalog.degree("china:pHI") == 0
assert catalog.degree("world:jp") == 0 and catalog.degree("world:au") == 0
assert catalog.degree("taiwan:penghu-county") == 0
ok("island territories are legitimately isolated")

# ---------- connected components ----------
assert len(catalog.map_components("taipei")) == 1          # districts fully connected
assert len(catalog.map_components("world")) > 1            # many island components — valid
comp_bj = catalog.connected_component("china:pBJ")
assert "china:pTW" not in comp_bj                          # Taiwan island not in mainland component
ok("connected components computed (taipei connected; world multi-component; china mainland excludes island)")

# ---------- multi-path territory = ONE logical node (union of neighbours, no suffix leak) ----------
d = tempfile.mkdtemp()
os.makedirs(os.path.join(d, "territories"))
json.dump({"catalogVersion": 1, "schemaVersion": 1, "generatorVersion": "t", "maps": 1, "territories": 3},
          open(os.path.join(d, "catalog.json"), "w"))
json.dump([{"id": "test", "svgFile": "maps/none.svg", "name": "T"}], open(os.path.join(d, "maps.json"), "w"))


def terr(i, keys, adj):
    return {"id": i, "mapId": "test", "regionCode": i.split(":")[1], "displayName": i,
            "localizedNames": {"en": i}, "svgPathKeys": keys, "administrativeCode": None,
            "gamePopulation": 1, "populationSource": {"value": None, "year": None, "sourceName": None, "sourceUrl": None},
            "metadata": {}, "terrainType": None, "settlementType": None, "features": [],
            "adjacentTerritoryIds": adj, "economy": None, "quests": [], "ai": None, "events": [],
            "_meta": {"schemaVersion": 1, "catalogVersion": 1, "generatedBy": "t", "generatedAt": "T",
                      "generatorVersion": "t", "lastDesignerEdit": None}}


# test:pA is a multi-path territory (pA_1 + pA_2); its components touch different neighbours
json.dump([terr("test:pA", ["pA_1", "pA_2"], ["test:x", "test:y"]),
           terr("test:x", ["x1"], ["test:pA"]),
           terr("test:y", ["y1"], ["test:pA"])],
          open(os.path.join(d, "territories", "test.json"), "w"))
tc = TerritoryCatalog(base_dir=d).load()
assert tc.neighbors("test:pA") == ["test:x", "test:y"], tc.neighbors("test:pA")   # union, sorted
assert tc.are_adjacent("test:pA", "test:x") and tc.are_adjacent("test:x", "test:pA")
# no SVG suffix identity ever appears in the graph
allnb = [nb for t in tc.territories.values() for nb in (t.get("adjacentTerritoryIds") or [])]
assert not any(n.endswith("_1") or n.endswith("_2") for n in allnb), allnb
assert tc.canonical_from_legacy("maps/none.svg#pA_1") == "test:pA"                # both components -> one node
ok("multi-path territory is one logical node (union of neighbours, no suffix leak)")

print("\nAll %d adjacency tests passed." % passed)
