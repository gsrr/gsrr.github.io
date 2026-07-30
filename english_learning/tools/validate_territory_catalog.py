#!/usr/bin/env python3
"""Phase 1A — validate the canonical territory catalog (stdlib only).

    python3 tools/validate_territory_catalog.py

Cross-checks world-data/ against maps/*.svg. Exits non-zero on any error.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORLD_DATA = os.path.join(ROOT, "world-data")

errors = []
warnings = []


def err(msg):
    errors.append(msg)


def svg_regions(map_id, svg_file):
    """Mirror index.html's isRegion rule → set of rendered path ids for this map."""
    try:
        s = open(os.path.join(ROOT, svg_file), encoding="utf-8").read()
    except Exception as e:
        err("cannot read svg %s (%s)" % (svg_file, e))
        return set()
    out = set()
    for tag in re.findall(r"<path\b.*?>", s, re.S):
        pid = (re.search(r'id="([^"]*)"', tag) or [None, None])[1] if re.search(r'id="([^"]*)"', tag) else None
        m_id = re.search(r'id="([^"]*)"', tag)
        pid = m_id.group(1) if m_id else ""
        m_al = re.search(r'aria-label="([^"]*)"', tag)
        label = m_al.group(1) if m_al else ""
        if map_id == "china":
            ok = re.match(r"^p[A-Z]{2}(_.*)?$", pid) is not None   # provinces: pXX or multi-path pXX_<n>
        elif map_id == "world":
            ok = re.match(r"^[a-z]{2}$", pid, re.I) is not None
        else:
            ok = bool(label)
        if ok and pid:
            out.add(pid)
    return out


def main():
    # ---- load catalog meta + maps ----
    try:
        catalog_meta = json.load(open(os.path.join(WORLD_DATA, "catalog.json"), encoding="utf-8"))
    except Exception as e:
        err("cannot load catalog.json: %s" % e)
        catalog_meta = {}
    cat_schema = catalog_meta.get("schemaVersion")
    if cat_schema is None:
        err("catalog.json missing schemaVersion")
    try:
        maps = json.load(open(os.path.join(WORLD_DATA, "maps.json"), encoding="utf-8"))
    except Exception as e:
        print("FATAL: cannot load maps.json:", e)
        return 2
    map_ids = [m["id"] for m in maps]
    if len(map_ids) != len(set(map_ids)):
        err("duplicate map id in maps.json")
    map_by_id = {m["id"]: m for m in maps}

    total = 0
    per_map = {}
    all_terr_ids = set()
    schema_versions = set()

    for m in maps:
        svg_ids = svg_regions(m["id"], m["svgFile"])
        try:
            terrs = json.load(open(os.path.join(WORLD_DATA, "territories", m["id"] + ".json"), encoding="utf-8"))
        except Exception as e:
            err("cannot load territories for map %s: %s" % (m["id"], e))
            continue
        per_map[m["id"]] = len(terrs)
        total += len(terrs)
        region_codes = set()
        path_owner = {}         # pathId -> territoryId (detect duplicate mappings)
        catalog_paths = set()
        for t in terrs:
            tid = t.get("id")
            if tid in all_terr_ids:
                err("duplicate territory id: %s" % tid)
            all_terr_ids.add(tid)
            if t.get("mapId") != m["id"]:
                err("%s: mapId mismatch (%s)" % (tid, t.get("mapId")))
            if not tid or not tid.startswith(m["id"] + ":"):
                err("%s: id must start with '%s:'" % (tid, m["id"]))
            if t.get("mapId") not in map_by_id:
                err("%s: references unknown map %s" % (tid, t.get("mapId")))
            keys = t.get("svgPathKeys") or []
            if not keys:
                err("%s: has no svgPathKeys" % tid)
            gp = t.get("gamePopulation")
            if not isinstance(gp, int) or gp < 0:
                err("%s: gamePopulation must be a non-negative integer (got %r)" % (tid, gp))
            ps = t.get("populationSource") or {}
            if ps.get("value") is not None and not (ps.get("year") and ps.get("sourceName")):
                err("%s: populationSource.value set without year/sourceName (unsupported provenance)" % tid)
            if not isinstance(t.get("localizedNames"), dict):
                err("%s: localizedNames must be an object" % tid)
            rc = t.get("regionCode")
            if rc in region_codes:
                err("%s: duplicate regionCode '%s' within map %s" % (tid, rc, m["id"]))
            region_codes.add(rc)
            adj = t.get("adjacentTerritoryIds") or []
            if adj != sorted(adj):
                err("%s: adjacentTerritoryIds must be sorted deterministically" % tid)
            if len(adj) != len(set(adj)):
                err("%s: duplicate neighbor in adjacentTerritoryIds" % tid)
            for nb in adj:
                if nb == tid:
                    err("%s: self-adjacency" % tid)
                if "#" in nb or "/" in nb:
                    err("%s: non-canonical neighbor id %r (legacy/SVG key)" % (tid, nb))
                if ":" not in nb or not nb.startswith(m["id"] + ":"):
                    err("%s: neighbor %r is not a same-map canonical id" % (tid, nb))
            if t.get("terrainType") is not None or t.get("settlementType") is not None:
                err("%s: terrain/settlement must be null in this phase" % tid)
            # Phase 3A: optional designer-owned learning gate. Missing == unrestricted (fine).
            if "requirements" in t:
                rq = t.get("requirements")
                if not isinstance(rq, dict):
                    err("%s: requirements must be an object" % tid)
                else:
                    unknown = set(rq) - {"attackQualificationIds"}
                    if unknown:
                        err("%s: unknown requirements keys %s" % (tid, sorted(unknown)))
                    qids = rq.get("attackQualificationIds", [])
                    if not isinstance(qids, list):
                        err("%s: requirements.attackQualificationIds must be a list" % tid)
                    else:
                        if not all(isinstance(q, str) and q.strip() for q in qids):
                            err("%s: attackQualificationIds must be non-empty strings" % tid)
                        if len(qids) != len(set(qids)):
                            err("%s: duplicate qualification id in attackQualificationIds" % tid)
                        if qids != sorted(qids):
                            err("%s: attackQualificationIds must be sorted deterministically" % tid)
            meta = t.get("_meta")
            if not isinstance(meta, dict):
                err("%s: missing _meta ownership block" % tid)
            else:
                sv = meta.get("schemaVersion")
                if sv is None:
                    err("%s: _meta.schemaVersion missing" % tid)
                else:
                    schema_versions.add(sv)
                    if cat_schema is not None and sv != cat_schema:
                        err("%s: schemaVersion %r != catalog %r" % (tid, sv, cat_schema))
                if not meta.get("generatorVersion"):
                    err("%s: _meta.generatorVersion missing" % tid)
            for pk in keys:
                if pk in path_owner:
                    err("duplicate svg path mapping '%s' (%s and %s)" % (pk, path_owner[pk], tid))
                path_owner[pk] = tid
                catalog_paths.add(pk)
                if pk not in svg_ids:
                    err("%s: svgPathKey '%s' not found in %s" % (tid, pk, m["svgFile"]))
        # all rendered SVG regions represented?
        missing = svg_ids - catalog_paths
        if missing:
            err("map %s: %d rendered SVG regions missing from catalog: %s"
                % (m["id"], len(missing), ", ".join(sorted(missing))[:200]))

        # ---- adjacency graph checks (exists, symmetry, components) ----
        ids = {t["id"] for t in terrs}
        adjm = {t["id"]: set(t.get("adjacentTerritoryIds") or []) for t in terrs}
        for tid, ns in adjm.items():
            for nb in ns:
                if nb not in ids:
                    err("%s: neighbor %r does not exist in map %s" % (tid, nb, m["id"]))
                elif tid not in adjm.get(nb, set()):
                    err("adjacency not symmetric: %s -> %s but not back" % (tid, nb))
        # connected components + isolated (INFO/warning, not error — islands are legitimate)
        seen, comps = set(), 0
        for t in ids:
            if t in seen:
                continue
            comps += 1
            stack = [t]
            while stack:
                u = stack.pop()
                if u in seen:
                    continue
                seen.add(u)
                stack.extend((adjm.get(u, set()) & ids) - seen)
        iso = sorted(t for t, ns in adjm.items() if not ns)
        warnings.append("map %s graph: %d edges, %d components, %d isolated%s"
                        % (m["id"], sum(len(v) for v in adjm.values()) // 2, comps, len(iso),
                           (" (" + ", ".join(iso[:8]) + ("…" if len(iso) > 8 else "") + ")" if iso else "")))

    if len(schema_versions) > 1:
        err("mixed schema versions across territories: %s" % sorted(schema_versions))
    print("Catalog v%s schema v%s: %d maps, %d territories (%s)"
          % (catalog_meta.get("catalogVersion", "?"), cat_schema, len(maps), total,
             ", ".join("%s=%d" % (k, per_map.get(k, 0)) for k in map_ids)))
    if warnings:
        for w in warnings:
            print("  warning:", w)
    if errors:
        print("VALIDATION FAILED (%d errors):" % len(errors))
        for e in errors[:50]:
            print("  -", e)
        return 1
    print("VALIDATION OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
