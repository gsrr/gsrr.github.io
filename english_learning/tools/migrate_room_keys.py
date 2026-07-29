#!/usr/bin/env python3
"""Phase 1B — migrate room ownership keys from legacy SVG keys to canonical territory ids.

    python3 tools/migrate_room_keys.py --rooms /data/rooms            # dry-run (default)
    python3 tools/migrate_room_keys.py --rooms /data/rooms --apply    # writes + .bak backups

Legacy key  'maps/china.svg#pLN_1'  ->  canonical  'china:pLN'.
- dry-run by default; --apply writes and backs up each file to <file>.bak
- idempotent (already-canonical keys unchanged)
- collision detection: two source keys resolving to one canonical with DIFFERENT owners
  is reported and that file is skipped (never silently merged)
- unknown territories are reported and KEPT (never silently discarded)
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from territory_catalog import catalog  # noqa: E402


def migrate_store(store):
    """Pure: {key: holder} -> (new_store, report). Does not write anything."""
    catalog._ensure()
    new, owners, report = {}, {}, {"changed": [], "unknown": [], "collisions": [], "kept": 0}
    for key, holder in store.items():
        canon = catalog.resolve_any(key)
        if not canon:
            new[key] = holder                 # unknown → keep, report
            report["unknown"].append(key)
            report["kept"] += 1
            continue
        owner = holder.get("owner") if isinstance(holder, dict) else None
        if canon in new:
            prev_owner = owners.get(canon)
            if prev_owner != owner:
                report["collisions"].append((canon, key, prev_owner, owner))
                continue                       # conflicting owners → do not merge
            # same owner → idempotent duplicate, keep first
            continue
        new[canon] = holder
        owners[canon] = owner
        if canon != key:
            report["changed"].append((key, canon))
    report["idempotent"] = not report["changed"] and not report["collisions"]
    return new, report


def _iter_files(args):
    if args.file:
        yield args.file
    if args.rooms and os.path.isdir(args.rooms):
        for d in sorted(os.listdir(args.rooms)):
            p = os.path.join(args.rooms, d, "territory.json")
            if os.path.isfile(p):
                yield p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rooms", help="directory of room subdirs each containing territory.json")
    ap.add_argument("--file", help="a single territory.json to migrate")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    files = list(_iter_files(args))
    if not files:
        print("no territory.json files found (use --rooms DIR or --file PATH)")
        return 0

    total_changed = total_collision = 0
    for path in files:
        try:
            store = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print("SKIP %s (%s)" % (path, e))
            continue
        new, rep = migrate_store(store)
        tag = "IDEMPOTENT" if rep["idempotent"] else ("COLLISION" if rep["collisions"] else "CHANGED")
        print("%s  %s  (+%d changed, %d unknown, %d collisions)"
              % (tag, path, len(rep["changed"]), len(rep["unknown"]), len(rep["collisions"])))
        for old, cn in rep["changed"][:20]:
            print("    %s -> %s" % (old, cn))
        for c in rep["collisions"]:
            print("    COLLISION %s: %s (owners %r vs %r)" % (c[0], c[1], c[2], c[3]))
        for u in rep["unknown"][:20]:
            print("    UNKNOWN (kept): %s" % u)
        total_changed += len(rep["changed"])
        total_collision += len(rep["collisions"])
        if args.apply and rep["changed"] and not rep["collisions"]:
            bak = path + ".bak"
            if not os.path.exists(bak):
                json.dump(store, open(bak, "w"))          # backup original once
            tmp = path + ".tmp"
            json.dump(new, open(tmp, "w"))
            os.replace(tmp, path)
            print("    WROTE (backup at %s)" % bak)

    print("\n%s: %d file(s), %d key(s) to canonicalize, %d collision(s)"
          % ("APPLIED" if args.apply else "DRY-RUN", len(files), total_changed, total_collision))
    return 1 if total_collision else 0


if __name__ == "__main__":
    sys.exit(main())
