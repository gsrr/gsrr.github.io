#!/usr/bin/env python3
"""Phase 1C — populate authoritative territory adjacency from CURATED land-border data.

    python3 tools/populate_adjacency.py --report [--map MAP]      # review report (default; no writes)
    python3 tools/populate_adjacency.py --merge  --map MAP         # write reviewed adjacency into world-data

Curated data (world-data/curated/*.reviewed.json) is the AUTHORITATIVE source of
land-border adjacency. SVG geometry (generated/territory-adjacency.json) is used only
for cross-validation (diff), never as the source. Land borders only — no sea connections.

Curated file formats:
  base "curated":  {"map","provenance","base":"curated","borders": {code: [code,...]}}
  base "geometry": {"map","provenance","base":"geometry","isolate":[id...],
                    "remove":[[id,id]...],"add":[[id,id]...]}   # human review of geometry candidates
Ids/codes are catalog regionCodes or canonical ids; the tool normalizes to canonical.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORLD = os.path.join(ROOT, "world-data")
CURATED = os.path.join(WORLD, "curated")
sys.path.insert(0, ROOT)
from territory_catalog import catalog  # noqa: E402

MAPS = ["taiwan", "taipei", "china", "world"]


def canon(map_id, x):
    """Accept a canonical id or a bare regionCode; return canonical id if it is a real territory."""
    catalog._ensure()
    if x in catalog.territories:
        return x
    cid = map_id + ":" + x
    return cid if cid in catalog.territories else None


def geometry_edges(map_id):
    p = os.path.join(ROOT, "generated", "territory-adjacency.json")
    try:
        j = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}
    return {t: set(ns) for t, ns in (j.get("maps", {}).get(map_id, {}).get("adjacency", {}) or {}).items()}


def reviewed_edges(map_id):
    """Return (adj, unresolved, provenance): the curated/reviewed symmetric adjacency (canonical)."""
    path = os.path.join(CURATED, map_id + ".reviewed.json")
    cur = json.load(open(path, encoding="utf-8"))
    unresolved = []
    adj = {t["id"]: set() for t in load_terr(map_id)}

    def add_edge(a, b):
        ca, cb = canon(map_id, a), canon(map_id, b)
        if not ca:
            unresolved.append(a); return
        if not cb:
            unresolved.append(b); return
        if ca == cb:
            return
        adj[ca].add(cb); adj[cb].add(ca)

    if cur.get("base") == "curated":
        for a, nbrs in (cur.get("borders") or {}).items():
            for b in nbrs:
                add_edge(a, b)
    elif cur.get("base") == "geometry":
        geo = geometry_edges(map_id)
        isolate = set(canon(map_id, x) for x in (cur.get("isolate") or []) if canon(map_id, x))
        for a, nbrs in geo.items():
            if a in isolate:
                continue
            for b in nbrs:
                cb = canon(map_id, b)
                if cb and cb not in isolate:
                    add_edge(a, b)
        for a, b in (cur.get("remove") or []):
            ca, cb = canon(map_id, a), canon(map_id, b)
            if ca and cb:
                adj[ca].discard(cb); adj[cb].discard(ca)
        for a, b in (cur.get("add") or []):
            add_edge(a, b)
    return adj, sorted(set(unresolved)), cur.get("provenance", "")


def load_terr(map_id):
    return json.load(open(os.path.join(WORLD, "territories", map_id + ".json"), encoding="utf-8"))


def save_terr(map_id, arr):
    p = os.path.join(WORLD, "territories", map_id + ".json")
    json.dump(arr, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(p, "a", encoding="utf-8").write("\n")


def components(adj):
    seen, comps = set(), []
    for t in adj:
        if t in seen:
            continue
        stack, cur = [t], []
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u); cur.append(u); stack.extend(adj[u] - seen)
        comps.append(sorted(cur))
    return comps


def report(map_ids):
    catalog._ensure()
    lines = ["# Territory Adjacency — curated review report (Phase 1C, Solution A)\n",
             "Authoritative source = curated land borders (`world-data/curated/*.reviewed.json`). "
             "SVG geometry is cross-validation only. Land borders only; islands are legitimately isolated.\n"]
    for map_id in map_ids:
        adj, unresolved, prov = reviewed_edges(map_id)
        geo = geometry_edges(map_id)
        degs = {t: len(ns) for t, ns in adj.items()}
        edges = sum(degs.values()) // 2
        isolated = sorted(t for t, dg in degs.items() if dg == 0)
        comps = components(adj)
        avg = (sum(degs.values()) / len(adj)) if adj else 0
        # diff vs geometry
        cur_pairs = {frozenset((a, b)) for a, ns in adj.items() for b in ns}
        geo_pairs = {frozenset((a, b)) for a, ns in geo.items() for b in ns if a in adj and b in adj}
        geo_only = sorted(tuple(sorted(p)) for p in (geo_pairs - cur_pairs))
        cur_only = sorted(tuple(sorted(p)) for p in (cur_pairs - geo_pairs))
        lines.append("\n## %s — %d territories, %d edges, avg degree %.2f, %d isolated, %d components"
                     % (map_id, len(adj), edges, avg, len(isolated), len(comps)))
        lines.append("- provenance: " + (prov or "(none)"))
        lines.append("- isolated (land-border degree 0): " + (", ".join(isolated) if isolated else "none"))
        lines.append("- geometry-only edges NOT in curated (likely sea/estuary, excluded): %d%s"
                     % (len(geo_only), (" e.g. " + ", ".join("%s~%s" % e for e in geo_only[:12]) if geo_only else "")))
        lines.append("- curated-only edges (geometry missed): %d%s"
                     % (len(cur_only), (" e.g. " + ", ".join("%s~%s" % e for e in cur_only[:12]) if cur_only else "")))
        if unresolved:
            lines.append("- UNRESOLVED curated ids not in catalog (ignored, review): " + ", ".join(unresolved[:20]))
    return "\n".join(lines) + "\n"


def do_merge(map_id):
    adj, unresolved, prov = reviewed_edges(map_id)
    arr = load_terr(map_id)
    ids = {t["id"] for t in arr}
    for t in arr:
        cur = set(t.get("adjacentTerritoryIds") or [])            # preserve any designer edits (never remove)
        rev = {x for x in adj.get(t["id"], set()) if x in ids and x != t["id"]}
        t["adjacentTerritoryIds"] = sorted(cur | rev)
    # symmetry closure
    by = {t["id"]: t for t in arr}
    for t in arr:
        for nb in list(t["adjacentTerritoryIds"]):
            o = by.get(nb)
            if o and t["id"] not in (o.get("adjacentTerritoryIds") or []):
                o["adjacentTerritoryIds"] = sorted(set(o.get("adjacentTerritoryIds") or []) | {t["id"]})
    save_terr(map_id, arr)
    return sum(len(t["adjacentTerritoryIds"]) for t in arr) // 2, unresolved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--map", choices=MAPS)
    args = ap.parse_args()
    maps = [args.map] if args.map else MAPS
    if args.merge:
        if not args.map:
            print("--merge requires --map"); return 2
        edges, unresolved = do_merge(args.map)
        print("merged %s: %d edges written; %d unresolved curated ids" % (args.map, edges, len(unresolved)))
        return 0
    md = report(maps)
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    open(os.path.join(ROOT, "docs", "territory-adjacency-review.md"), "w", encoding="utf-8").write(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
