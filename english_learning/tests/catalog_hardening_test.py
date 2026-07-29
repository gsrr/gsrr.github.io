#!/usr/bin/env python3
"""Phase 1A.5 — validator hardening tests (schema/metadata ownership).

    python3 tests/catalog_hardening_test.py
"""
import json
import os
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


def meta(sv=1):
    return {"schemaVersion": sv, "catalogVersion": 1, "generatedBy": "gen",
            "generatedAt": "T0", "generatorVersion": "1.0.0", "lastDesignerEdit": None}


def terr(tid, mid, code, keys=None, sv=1, with_meta=True):
    t = {"id": tid, "mapId": mid, "regionCode": code, "displayName": code,
         "localizedNames": {"en": code}, "svgPathKeys": keys or [code],
         "administrativeCode": None, "gamePopulation": 100,
         "populationSource": {"value": None, "year": None, "sourceName": None, "sourceUrl": None},
         "metadata": {}, "terrainType": None, "settlementType": None, "features": [],
         "adjacentTerritoryIds": [], "economy": None, "quests": [], "ai": None, "events": []}
    if with_meta:
        t["_meta"] = meta(sv)
    return t


def build(maps, terrs, catalog=None):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "territories"), exist_ok=True)
    json.dump(maps, open(os.path.join(d, "maps.json"), "w"))
    if catalog is not None:
        json.dump(catalog, open(os.path.join(d, "catalog.json"), "w"))
    for mid, ts in terrs.items():
        json.dump(ts, open(os.path.join(d, "territories", mid + ".json"), "w"))
    return TerritoryCatalog(base_dir=d).load()


CAT = {"catalogVersion": 1, "schemaVersion": 1, "generatorVersion": "1.0.0", "maps": 1, "territories": 1}
MAPS = [{"id": "m", "svgFile": "maps/m.svg", "name": "M"}]

# 1. real catalog still validates clean
real = TerritoryCatalog().load()
assert real.validate() == [], real.validate()
ok("real catalog validates clean with schema+meta checks")

# 2. invalid (mismatched) schema version
c = build(MAPS, {"m": [terr("m:a", "m", "a", sv=2)]}, CAT)
assert any("schemaVersion" in e and "!= catalog" in e for e in c.validate()), c.validate()
ok("territory schemaVersion mismatching catalog is rejected")

# 3. missing _meta ownership block
c = build(MAPS, {"m": [terr("m:a", "m", "a", with_meta=False)]}, CAT)
assert any("missing _meta" in e for e in c.validate()), c.validate()
ok("missing _meta ownership block is rejected")

# 4. duplicate ownership (same svg path mapped by two territories)
c = build(MAPS, {"m": [terr("m:a", "m", "a", keys=["p"]), terr("m:b", "m", "b", keys=["p"])]}, CAT)
assert any("duplicate svg path mapping" in e for e in c.validate()), c.validate()
ok("duplicate svg path ownership is rejected")

# 5. duplicate territory ids
c = build(MAPS, {"m": [terr("m:a", "m", "a"), terr("m:a", "m", "a2")]}, CAT)
assert any("duplicate territory id" in e for e in c.validate()), c.validate()
ok("duplicate territory id is rejected")

# 6. mixed schema versions across territories
c = build(MAPS, {"m": [terr("m:a", "m", "a", sv=1), terr("m:b", "m", "b", sv=2)]}, CAT)
errs = c.validate()
assert any("mixed schema versions" in e for e in errs), errs
ok("mixed schema versions are rejected")

# 7. catalog.json missing schemaVersion
c = build(MAPS, {"m": [terr("m:a", "m", "a")]}, {"catalogVersion": 1})
assert any("catalog.json missing schemaVersion" in e for e in c.validate()), c.validate()
ok("catalog.json without schemaVersion is rejected")

print("\nAll %d hardening validator tests passed." % passed)
