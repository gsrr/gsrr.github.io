#!/usr/bin/env python3
"""Validate the curated learning-campaign progression on a map, and print a design report.

    python3 tools/validate_progression.py [--map taipei] [--start taipei:wenshan] [--strict]

This is CURRICULUM/TOPOLOGY reachability, not a battle simulation: it assumes any eligible attack can
eventually be won, and only asks whether the content graph lets a player get there at all.

It classifies every territory on the map into three groups (kept separate on purpose):

  1. CURATED   — carries learning requirements; part of the designed campaign
  2. SANDBOX   — no requirements; freely conquerable, an optional detour, NOT a campaign step
  3. UNASSIGNED— no requirements and outside the curated design (reported honestly, not a failure)

Crucially, curated reachability is computed WITHOUT letting sandbox territories act as stepping
stones. An ungated path must never be what makes the learning route "reachable".

Errors (always fatal):
  - a requirement naming a qualification that does not exist
  - a qualification with no server-authoritative earning path (nothing can grant it)
  - a curated territory unreachable from the start through curated/start territories
  - the start territory itself carrying a requirement
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from learning import registry as learning_registry  # noqa: E402

errors, warnings = [], []


def err(m):
    errors.append(m)


def warn(m):
    warnings.append(m)


def load_map(map_id):
    path = os.path.join(ROOT, "world-data", "territories", map_id + ".json")
    with open(path, encoding="utf-8") as f:
        terrs = json.load(f)
    adj, reqs, names = {}, {}, {}
    for t in terrs:
        tid = t.get("id")
        adj[tid] = list(t.get("adjacentTerritoryIds") or [])
        names[tid] = t.get("displayName") or tid
        r = ((t.get("requirements") or {}).get("attackQualificationIds") or [])
        if r:
            reqs[tid] = list(r)
    return adj, reqs, names


def earning_paths(reg):
    """qualificationId -> [activityId, ...] that can authoritatively grant it."""
    out = {}
    for aid in reg.activities:
        for qid in reg.qualification_ids_for(aid):
            out.setdefault(qid, []).append(aid)
    for lid in reg.lessons:
        for qid in reg.lesson_qualification_ids_for(lid):
            out.setdefault(qid, []).append(lid + " (lesson completion)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="taipei")
    ap.add_argument("--start", default="taipei:wenshan")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = ap.parse_args()

    reg = learning_registry.REGISTRY
    adj, reqs, names = load_map(args.map)
    paths = earning_paths(reg)

    if args.start not in adj:
        err("start territory %r is not on map %r" % (args.start, args.map))
        print("VALIDATION FAILED")
        return 1
    if args.start in reqs:
        err("start territory %s must not carry a learning requirement" % args.start)

    # ---- every production requirement must be earnable (§20/§34) ----
    for tid, qids in sorted(reqs.items()):
        for qid in qids:
            if qid not in reg.qualifications:
                err("%s requires %r, which is not a known qualification" % (tid, qid))
            elif not paths.get(qid):
                err("%s requires %r, which NOTHING can grant — the territory would be permanently "
                    "locked" % (tid, qid))
            else:
                tgt = reg.study_target(qid)
                if not tgt or not tgt.get("contentPath"):
                    err("%s requires %r, which has no resolvable Study target" % (tid, qid))
                if not reg.title_of_qualification(qid) or \
                        reg.title_of_qualification(qid) == qid:
                    warn("%s requires %r, which has no human-readable title" % (tid, qid))

    # ---- curated reachability, WITHOUT using sandbox territories as stepping stones ----
    curated = set(reqs)
    owned = {args.start}
    earned = set()
    order = []
    progressed = True
    while progressed:
        progressed = False
        frontier = {n for o in owned for n in adj.get(o, []) if n not in owned}
        for tid in sorted(frontier & curated):
            missing = [q for q in reqs[tid] if q not in earned]
            # a player may study ahead: any qualification with an earning path can be earned freely
            earnable = [q for q in missing if paths.get(q)]
            if len(earnable) == len(missing):
                earned.update(missing)
                owned.add(tid)
                order.append((tid, reqs[tid]))
                progressed = True
    unreachable = sorted(curated - owned)
    for tid in unreachable:
        err("curated territory %s is not reachable from %s through curated territories" %
            (tid, args.start))

    sandbox = sorted(t for t in adj if t not in curated and t != args.start)

    # ---- report ----
    print("progression: map=%s start=%s" % (args.map, args.start))
    print("  curated campaign territories: %d" % len(curated))
    for tid, qids in order:
        print("    %-20s %-22s <- %s" % (tid, names[tid],
              " + ".join(reg.title_of_qualification(q) for q in qids)))
    print("  optional/sandbox (ungated, NOT campaign steps): %d %s" % (len(sandbox), sandbox))
    print("  qualifications in use: %d" % len({q for v in reqs.values() for q in v}))
    for qid in sorted({q for v in reqs.values() for q in v}):
        print("    %-42s <- %s" % (qid, paths.get(qid)))
    for w in warnings:
        print("  warning: " + w)
    if args.strict and warnings:
        errors.extend("strict: " + w for w in warnings)
    if errors:
        for e in errors:
            print("  ERROR: " + e)
        print("VALIDATION FAILED (%d error(s))" % len(errors))
        return 1
    print("VALIDATION OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
