#!/usr/bin/env python3
"""Phase 1A backend tests — catalog load, validation, legacy resolution, freeze.

    python3 tests/territory_catalog_test.py
"""
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from territory_catalog import TerritoryCatalog  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


def make_catalog(maps, terrs):
    """Build a throwaway catalog dir and return a loaded TerritoryCatalog."""
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "territories"), exist_ok=True)
    json.dump(maps, open(os.path.join(d, "maps.json"), "w"))
    for mid, ts in terrs.items():
        json.dump(ts, open(os.path.join(d, "territories", mid + ".json"), "w"))
    return TerritoryCatalog(base_dir=d).load()


def terr(tid, mid, code, pop=100, keys=None):
    return {"id": tid, "mapId": mid, "regionCode": code, "displayName": code,
            "localizedNames": {"en": code}, "svgPathKeys": keys or [code],
            "administrativeCode": None, "gamePopulation": pop,
            "populationSource": {"value": None, "year": None, "sourceName": None, "sourceUrl": None},
            "metadata": {}, "terrainType": None, "settlementType": None,
            "features": [], "adjacentTerritoryIds": []}


# --- 1. real catalog loads and validates ---
real = TerritoryCatalog().load()
assert real.validate() == [], real.validate()
counts = real.count_per_map()
assert counts.get("world", 0) > 0 and counts.get("china", 0) > 0, counts
ok("real catalog loads + validates (%s)" % counts)

# --- 2. duplicate territory id fails ---
c = make_catalog([{"id": "m", "svgFile": "maps/x.svg", "name": "M"}],
                 {"m": [terr("m:a", "m", "a"), terr("m:a", "m", "a")]})
assert any("duplicate territory id" in e for e in c.validate())
ok("duplicate territory id fails")

# --- 3. duplicate map id fails ---
c = make_catalog([{"id": "m", "svgFile": "a", "name": "M"}, {"id": "m", "svgFile": "b", "name": "M2"}],
                 {"m": [terr("m:a", "m", "a")]})
assert any("duplicate map id" in e for e in c.validate())
ok("duplicate map id fails")

# --- 4. invalid map reference fails ---
c = make_catalog([{"id": "m", "svgFile": "a", "name": "M"}],
                 {"m": [terr("x:a", "x", "a")]})
assert any("unknown map" in e for e in c.validate())
ok("invalid map reference fails")

# --- 5. negative population fails ---
c = make_catalog([{"id": "m", "svgFile": "a", "name": "M"}],
                 {"m": [terr("m:a", "m", "a", pop=-5)]})
assert any("bad gamePopulation" in e for e in c.validate())
ok("negative population fails")

# --- 6/7. legacy world + china keys resolve ---
assert real.canonical_from_legacy("maps/world.svg#us") == "world:us"
assert real.canonical_from_legacy("maps/china.svg#pBJ") == "china:pBJ"
ok("legacy world + china keys resolve to canonical ids")

# --- 8. unknown legacy key handled safely ---
assert real.canonical_from_legacy("maps/world.svg#zzz") is None
assert real.canonical_from_legacy("garbage") is None
ok("unknown legacy key returns None (no crash, not discarded silently)")

# --- 9. multi-path region resolves to one logical territory ---
c = make_catalog([{"id": "m", "svgFile": "maps/m.svg", "name": "M"}],
                 {"m": [terr("m:big", "m", "big", keys=["p1", "p2", "p3"])]})
ids = {c.canonical_from_legacy("maps/m.svg#" + p) for p in ("p1", "p2", "p3")}
assert ids == {"m:big"}, ids
ok("multi-path region resolves to ONE territory (p1/p2/p3 -> m:big)")

# --- 10. population lookup uses gamePopulation ---
assert real.game_population("china:pBJ") == real.territories["china:pBJ"]["gamePopulation"]
ok("population lookup returns gamePopulation")

# --- 11. deterministic legacy fallback value is frozen correctly ---
# Reproduce index.html popForName's hash (no POP_TABLE hit for China names) in Python
# and confirm the catalog froze that exact value.
def js_pop_hash(name):
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return 60 + (h % 241)

bj = real.territories["china:pBJ"]
assert bj["displayName"] == "Beijing 北京", bj["displayName"]
assert bj["gamePopulation"] == js_pop_hash("Beijing 北京"), (bj["gamePopulation"], js_pop_hash("Beijing 北京"))
ok("deterministic hash population frozen correctly (china:pBJ = %d)" % bj["gamePopulation"])

print("\nAll %d backend catalog tests passed." % passed)
