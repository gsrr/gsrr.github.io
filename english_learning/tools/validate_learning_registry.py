#!/usr/bin/env python3
"""Validate learning/registry.json, and cross-check it against the World-Domain territory catalog.

    python3 tools/validate_learning_registry.py [--strict]

Two independent layers:

  A. REGISTRY VALIDATION (always fatal) — schema, referential integrity, grader types, reward
     policies, legacy-key uniqueness and the §7 rule that only 'activity'-scope qualifications may
     be earnable. Delegates to learning.registry.validate() so the CLI and the unit tests share one
     implementation.

  B. CROSS-DOMAIN REPORT (§27) — territory `requirements.attackQualificationIds` that no installed
     content pack knows about.

     DECISION: an unknown requirement id is a WARNING, not an error, by default.
     Rationale: content packs are meant to become independently installable, so a world map must
     stay loadable when an optional pack is absent — and the runtime already fails CLOSED
     (game.conquest.can_attack blocks a territory whose requirement nobody holds, and an
     unresolvable qualification simply renders with no Study button). Making it fatal would mean a
     missing optional pack could brick the entire world catalog. CI that ships world-data and its
     packs together should pass --strict to turn these warnings into errors.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from learning import registry as learning_registry   # noqa: E402
from learning import content as learning_content     # noqa: E402

errors, warnings = [], []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def territory_requirements(catalog_dir):
    """{territoryId: [qualificationId, ...]} straight from world-data (no game logic involved)."""
    out = {}
    maps_path = os.path.join(catalog_dir, "maps.json")
    try:
        with open(maps_path, encoding="utf-8") as f:
            maps = json.load(f)
    except Exception as e:
        err("cannot read %s: %s" % (maps_path, e))
        return out
    for m in maps:
        path = os.path.join(catalog_dir, "territories", m["id"] + ".json")
        try:
            with open(path, encoding="utf-8") as f:
                terrs = json.load(f)
        except Exception:
            continue                        # the territory-catalog validator owns this error
        for t in terrs:
            reqs = ((t or {}).get("requirements") or {}).get("attackQualificationIds") or []
            if reqs:
                out[t.get("id")] = list(reqs)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="treat unknown territory requirement ids as errors (ship-together CI)")
    args = ap.parse_args()

    # ---- A. registry ----
    data, load_errs = learning_registry.load_data()
    for e in load_errs:
        err(e)
    for e in learning_registry.validate(data):
        err("registry: " + e)
    reg = learning_registry.Registry(data)

    # content files the registry promises must actually exist and expose the declared activity keys
    for aid, spec in sorted(reg.activities.items()):
        path = reg.content_path_of(aid)
        items = learning_content.load_activity_items(path, spec.get("contentKey"), ROOT,
                                                    reg.approved_content_paths())
        if items is None:
            err("activity %s: content %r has no usable %r list under CONTENT_ROOT"
                % (aid, path, spec.get("contentKey")))

    # every earnable qualification should be reachable (have a study destination) for the UI
    for qid in sorted(reg.qualifications):
        if (reg.qualifications[qid] or {}).get("scope", "activity") == "activity":
            tgt = reg.study_target(qid)
            if not tgt or not tgt.get("contentPath"):
                err("qualification %s has no resolvable studyTarget (frontend cannot offer Study)" % qid)

    # ---- B. cross-domain ----
    terr_reqs = territory_requirements(os.path.join(ROOT, "world-data"))
    known = set(reg.qualifications)
    unknown = {}
    for tid, reqs in sorted(terr_reqs.items()):
        for q in reqs:
            if q not in known:
                unknown.setdefault(q, []).append(tid)
    for q, tids in sorted(unknown.items()):
        msg = ("territory requirement %r is not described by any installed content pack "
               "(required by %s) — territory stays locked and shows no Study link" % (q, ", ".join(tids)))
        (err if args.strict else warn)("cross-domain: " + msg)

    required_ids = {q for reqs in terr_reqs.values() for q in reqs}
    for q in sorted(known - required_ids):
        warn("cross-domain: qualification %r is earnable but no territory requires it (unused gate)" % q)

    # ---- report ----
    print("learning registry schema v%s: %d pack(s), %d course(s), %d unit(s), %d lesson(s), "
          "%d activity(ies), %d qualification(s)"
          % (reg.schema_version, len(reg.contentPacks), len(reg.courses), len(reg.units),
             len(reg.lessons), len(reg.activities), len(reg.qualifications)))
    print("  graders: %s | reward policies in use: %s"
          % (sorted({a.get("graderType") for a in reg.activities.values()}),
             sorted({reg.reward_policy_of(a) for a in reg.activities})))
    print("  territories with learning requirements: %d" % len(terr_reqs))
    for tid, reqs in sorted(terr_reqs.items()):
        print("    %s requires ALL of %s" % (tid, reqs))
    for w in warnings:
        print("  warning: " + w)
    if errors:
        for e in errors:
            print("  ERROR: " + e)
        print("VALIDATION FAILED (%d error(s))" % len(errors))
        return 1
    print("VALIDATION OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
