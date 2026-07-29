#!/usr/bin/env python3
"""Phase 1C — canonical territory adjacency (offline authoring tool, stdlib only).

    python3 tools/gen_adjacency.py --propose [--map MAP] [--tol RATIO]   # report only (default)
    python3 tools/gen_adjacency.py --check   [--map MAP]                 # compare vs world-data
    python3 tools/gen_adjacency.py --merge   --map MAP                   # write adjacency into world-data

Derives CANDIDATE land-border adjacency from SVG boundary-point proximity (no GIS deps).
Operates on LOGICAL (canonical) territories: a multi-path territory's components are merged.
Runtime never runs this — runtime reads world-data. Designer edits are preserved by --merge.
"""
import argparse
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORLD = os.path.join(ROOT, "world-data")
sys.path.insert(0, ROOT)
from territory_catalog import catalog  # noqa: E402

MAPS = ["taiwan", "taipei", "china", "world"]
# per-map proximity tolerance as a fraction of the map bounding-box diagonal (tunable per map)
DEFAULT_TOL = {"taiwan": 0.006, "taipei": 0.010, "china": 0.006, "world": 0.0035}
BEZIER_STEPS = 6
NUM = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:[eE]-?\d+)?")


def flatten_path(d):
    """Flatten an SVG path 'd' into a list of (x,y) boundary points (beziers sampled)."""
    toks = NUM.findall(d)
    pts, i, n = [], 0, len(toks)
    cx = cy = sx = sy = 0.0
    cmd = None

    def num():
        nonlocal i
        v = float(toks[i]); i += 1
        return v

    while i < n:
        t = toks[i]
        if re.match(r"[A-Za-z]", t):
            cmd = t; i += 1
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            x = num(); y = num()
            if rel: x += cx; y += cy
            cx, cy = x, y; sx, sy = x, y; pts.append((cx, cy)); cmd = "l" if rel else "L"
        elif c == "L":
            x = num(); y = num()
            if rel: x += cx; y += cy
            cx, cy = x, y; pts.append((cx, cy))
        elif c == "H":
            x = num()
            if rel: x += cx
            cx = x; pts.append((cx, cy))
        elif c == "V":
            y = num()
            if rel: y += cy
            cy = y; pts.append((cx, cy))
        elif c == "C":
            x1 = num(); y1 = num(); x2 = num(); y2 = num(); ex = num(); ey = num()
            if rel: x1 += cx; y1 += cy; x2 += cx; y2 += cy; ex += cx; ey += cy
            for s in range(1, BEZIER_STEPS + 1):
                u = s / BEZIER_STEPS; mu = 1 - u
                bx = mu**3 * cx + 3 * mu**2 * u * x1 + 3 * mu * u**2 * x2 + u**3 * ex
                by = mu**3 * cy + 3 * mu**2 * u * y1 + 3 * mu * u**2 * y2 + u**3 * ey
                pts.append((bx, by))
            cx, cy = ex, ey
        elif c in ("S", "Q", "T"):   # not used by these maps; approximate to endpoint pair(s)
            need = 4 if c in ("S", "Q") else 2
            xs = [num() for _ in range(need)]
            cx, cy = (xs[-2] + (cx if rel else 0), xs[-1] + (cy if rel else 0))
            pts.append((cx, cy))
        elif c == "A":               # arc (unused) → line to endpoint
            num(); num(); num(); num(); num(); x = num(); y = num()
            if rel: x += cx; y += cy
            cx, cy = x, y; pts.append((cx, cy))
        elif c == "Z":
            cx, cy = sx, sy; pts.append((cx, cy))
        else:
            i += 1
    return pts


def svg_path_points(svg_file):
    """Return {pathId: [pts]} for every <path id=..> in the svg."""
    s = open(os.path.join(ROOT, svg_file), encoding="utf-8").read()
    out = {}
    for tag_m in re.finditer(r"<path\b[\s\S]*?>", s):
        tag = tag_m.group(0)
        pid = (re.search(r'id="([^"]*)"', tag) or [None, None])
        pid = re.search(r'id="([^"]*)"', tag)
        if not pid:
            continue
        pid = pid.group(1)
        dm = re.search(r'\sd="([^"]*)"', tag)
        if not dm:
            continue
        out.setdefault(pid, []).extend(flatten_path(dm.group(1)))
    return out


def territory_points(map_id):
    """Merge SVG path points into LOGICAL (canonical) territories via the catalog."""
    catalog._ensure()
    m = catalog.map_by_id[map_id]
    raw = svg_path_points(m["svgFile"])
    terr = {}   # canonical id -> [pts]
    for pid, pts in raw.items():
        canon = catalog.by_map_path.get((map_id, pid))
        if not canon:
            continue                       # not a catalog territory (background/unmapped)
        terr.setdefault(canon, []).extend(pts)
    return terr


def adjacency_for_map(map_id, tol_ratio):
    terr = territory_points(map_id)
    all_pts = [p for pts in terr.values() for p in pts]
    if not all_pts:
        return {}, {}, 0.0
    xs = [p[0] for p in all_pts]; ys = [p[1] for p in all_pts]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    tol = diag * tol_ratio
    cell = tol
    # spatial grid: (gx,gy) -> list of (tid, x, y)
    grid = {}
    for tid, pts in terr.items():
        for (x, y) in pts:
            grid.setdefault((int(x // cell), int(y // cell)), []).append((tid, x, y))
    weights = {}   # frozenset({a,b}) -> count of close point-pairs (border strength proxy)
    for (gx, gy), bucket in grid.items():
        neigh = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neigh.extend(grid.get((gx + dx, gy + dy), ()))
        for (ta, xa, ya) in bucket:
            for (tb, xb, yb) in neigh:
                if ta == tb:
                    continue
                if (xa - xb) ** 2 + (ya - yb) ** 2 <= tol * tol:
                    weights[frozenset((ta, tb))] = weights.get(frozenset((ta, tb)), 0) + 1
    adj = {t: set() for t in terr}
    for pair in weights:
        a, b = tuple(pair)
        adj[a].add(b); adj[b].add(a)
    return adj, weights, tol


def components(adj):
    seen, comps = set(), 0
    for t in adj:
        if t in seen:
            continue
        comps += 1
        stack = [t]
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            stack.extend(adj[u] - seen)
    return comps


def build_all(tol_override):
    result = {}
    for map_id in MAPS:
        tr = tol_override if tol_override is not None else DEFAULT_TOL[map_id]
        adj, weights, tol = adjacency_for_map(map_id, tr)
        result[map_id] = {"adj": adj, "weights": weights, "tol": tol, "tolRatio": tr}
    return result


def report(result, only_map=None):
    lines = ["# Territory Adjacency — candidate report (Phase 1C)\n",
             "Geometry-derived LAND-border candidates from SVG boundary proximity. "
             "Review before merging; designer edits stay authoritative.\n"]
    jsonout = {"maps": {}}
    for map_id in MAPS:
        if only_map and map_id != only_map:
            continue
        r = result[map_id]; adj = r["adj"]
        degs = {t: len(ns) for t, ns in adj.items()}
        edges = sum(degs.values()) // 2
        isolated = sorted(t for t, dg in degs.items() if dg == 0)
        comps = components(adj)
        avg = (sum(degs.values()) / len(adj)) if adj else 0
        # suspicious: very short shared border (few close point-pairs), or very high degree
        suspicious = []
        for pair, w in r["weights"].items():
            if w <= 2:
                a, b = tuple(pair); suspicious.append((sorted((a, b)), w))
        hi = sorted([(dg, t) for t, dg in degs.items() if dg >= 12], reverse=True)
        lines.append("\n## %s — %d territories, %d edges, avg degree %.2f, %d isolated, %d components (tol=%.3f, ratio=%.4f)"
                     % (map_id, len(adj), edges, avg, len(isolated), comps, r["tol"], r["tolRatio"]))
        if isolated:
            lines.append("- isolated: " + ", ".join(isolated))
        if hi:
            lines.append("- high degree: " + ", ".join("%s(%d)" % (t, d) for d, t in hi[:10]))
        if suspicious:
            lines.append("- short-border (<=2 pts) candidates: " + ", ".join("%s~%s" % (p[0], p[1]) for p, w in suspicious[:20]))
        jsonout["maps"][map_id] = {
            "territories": len(adj), "edges": edges, "avgDegree": round(avg, 3),
            "isolated": isolated, "components": comps,
            "adjacency": {t: sorted(ns) for t, ns in adj.items()},
            "suspicious": [[p, w] for p, w in [(sorted(tuple(pr)), w) for pr, w in r["weights"].items()] if w <= 2],
        }
    return "\n".join(lines) + "\n", jsonout


def load_terr_file(map_id):
    return json.load(open(os.path.join(WORLD, "territories", map_id + ".json"), encoding="utf-8"))


def save_terr_file(map_id, arr):
    p = os.path.join(WORLD, "territories", map_id + ".json")
    json.dump(arr, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(p, "a", encoding="utf-8").write("\n")


def do_merge(map_id, result):
    """Write symmetric, sorted, deduped adjacency into world-data. Adds geometry candidates
    to whatever is already there (designer edits preserved). Never introduces non-canonical ids."""
    adj = result[map_id]["adj"]
    arr = load_terr_file(map_id)
    ids = {t["id"] for t in arr}
    added = 0
    for t in arr:
        cur = set(t.get("adjacentTerritoryIds") or [])
        cand = set(adj.get(t["id"], set()))
        merged = {x for x in (cur | cand) if x in ids and x != t["id"]}   # canonical, no self, no orphan
        if merged != cur:
            added += len(merged - cur)
        t["adjacentTerritoryIds"] = sorted(merged)
    # enforce symmetry across the file
    by_id = {t["id"]: t for t in arr}
    for t in arr:
        for nb in list(t["adjacentTerritoryIds"]):
            o = by_id.get(nb)
            if o and t["id"] not in (o.get("adjacentTerritoryIds") or []):
                o["adjacentTerritoryIds"] = sorted(set(o.get("adjacentTerritoryIds") or []) | {t["id"]})
    save_terr_file(map_id, arr)
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--propose", action="store_true")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--map", choices=MAPS)
    ap.add_argument("--tol", type=float, help="override per-map tolerance ratio")
    args = ap.parse_args()

    result = build_all(args.tol)

    if args.merge:
        if not args.map:
            print("--merge requires --map (merge one map at a time, for review)"); return 2
        n = do_merge(args.map, result)
        print("merged %s: +%d adjacency entries" % (args.map, n))
        return 0

    md, js = report(result, args.map)
    if args.check:
        # compare candidate edges vs current world-data
        for map_id in ([args.map] if args.map else MAPS):
            cur = {t["id"]: set(t.get("adjacentTerritoryIds") or []) for t in load_terr_file(map_id)}
            cand = {t: ns for t, ns in result[map_id]["adj"].items()}
            missing = sum(len(cand.get(t, set()) - cur.get(t, set())) for t in cand) // 2
            extra = sum(len(cur.get(t, set()) - cand.get(t, set())) for t in cur) // 2
            print("check %s: candidate-only edges=%d, world-data-only edges=%d" % (map_id, missing, extra))
        return 0

    # --propose (default): write report, do not touch world-data
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "generated"), exist_ok=True)
    open(os.path.join(ROOT, "docs", "territory-adjacency.md"), "w", encoding="utf-8").write(md)
    json.dump(js, open(os.path.join(ROOT, "generated", "territory-adjacency.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
