#!/usr/bin/env python3
"""Report how much of each lesson's LEGACY Rule A is backed by server-authoritative evidence.

    python3 tools/validate_content_coverage.py [--strict]

Phase 4B §29. A lesson can only get an authoritative `average_required_activities` policy if EVERY
level that legacy Rule A scores has a server-authoritative activity behind it. This tool makes the
gap between "registered" and "complete" impossible to miss, so an incomplete registration can never
be mistaken for a finished lesson.

The required level set is not hardcoded here — it is derived from the SAME two sources the browser
uses, so editing either one shows up as a coverage change:

  1. the manifest arc `levels: [...]` array in index.html      (which levels the lesson declares)
  2. the `scoredLevelsFor()` rule                               (levels >= 2, plus level 10 always)

Level 10 (Role-play) is appended UNCONDITIONALLY by `scoredLevelsFor()` — every lesson with a
dialogue is scored on it. Phase 4C made it server-authoritative (a server-owned session owns the
graph, the branch RNG, the classifier and the turn/pass counters), so it now counts as covered.
Coverage reaching 7/7 is READINESS, not activation: enabling a lesson policy remains a separate,
explicitly approved step.

Errors (always fatal):
  - a lesson with an ACTIVE completionPolicy whose required set is not exactly its covered set
  - a required activity that is not registered, or not server-scored, or belongs to another lesson
Warnings (fatal under --strict) — actionable authoring gaps:
  - a required level that a generic scorer ALREADY supports but no activity is registered for
Notes (never fatal) — documented design state:
  - a required level with no server-authoritative implementation at all (level 10 Role-play)
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from learning import registry as learning_registry  # noqa: E402

errors, warnings, notes = [], [], []

# Level -> the registry activity suffix that carries its authoritative evidence. Levels absent from
# this map have no server-authoritative implementation at all (1 = listening, which Rule A does not
# score). Level 10 Role-play joined the list in Phase 4C.
LEVEL_ACTIVITY = {
    "2": "read_along",
    "3": "quiz3",
    "4": "quiz4",
    "5": "matching",
    "6": "reorder",
    "7": "wh",
    "8": "dictation",
    "9": "cloze",
    "10": "roleplay",
}
LEVEL_NAME = {
    "1": "Listen", "2": "Read Along", "3": "Quiz", "4": "Tricky Quiz", "5": "Match",
    "6": "Reorder", "7": "WH Questions", "8": "Dictation", "9": "Fill Blank", "10": "Role-play",
}
ROLEPLAY_LEVEL = "10"
# Phase 4D: the lessons approved to carry an active policy in production. Anything else with a
# policy, or any of these without one, is an authoring drift worth flagging.
EXPECTED_ACTIVE = {"english.prea1.taipei.zoo", "english.prea1.taipei.mrt",
                   "english.prea1.taipei.market", "english.prea1.taipei.park"}

_ARC = re.compile(r'file:\s*"([^"]+)"[^}]*?levels:\s*\[([0-9,\s]+)\]')


def manifest_levels():
    """{contentPath: [declared level ints]} read out of the index.html manifest."""
    with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as f:
        html = f.read()
    out = {}
    for m in _ARC.finditer(html):
        out[m.group(1)] = [int(x) for x in m.group(2).replace(" ", "").split(",") if x]
    return out


def scored_levels_for(declared):
    """Port of index.html scoredLevelsFor() for a lesson that DECLARES its levels.

    Both halves matter: `levels.filter(l => l >= 2)`, then `if (lv.indexOf("10") < 0) lv.push("10")`
    — the push is outside the if/else, so it applies to declared-level lessons too.
    """
    lv = [str(l) for l in declared if l >= 2]
    if ROLEPLAY_LEVEL not in lv:
        lv.append(ROLEPLAY_LEVEL)
    return lv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="exit non-zero on warnings too")
    args = ap.parse_args()

    reg = learning_registry.REGISTRY
    if learning_registry.LOAD_ERRORS:
        for e in learning_registry.LOAD_ERRORS:
            errors.append("registry: %s" % e)

    levels_by_path = manifest_levels()
    rows = []
    for lid in sorted(reg.lessons):
        lesson = reg.lessons[lid]
        path = lesson.get("contentPath")
        declared = levels_by_path.get(path)
        if not declared:
            continue                      # not a manifest arc (e.g. a plain lessons.json article)
        need = scored_levels_for(declared)
        covered, missing = [], []
        for lv in need:
            suffix = LEVEL_ACTIVITY.get(lv)
            aid = "%s.%s" % (lid, suffix) if suffix else None
            if aid and aid in reg.activities and reg.is_server_scored(aid) \
                    and reg.lesson_of_activity(aid) == lid:
                covered.append((lv, aid))
            else:
                missing.append(lv)
        policy = reg.completion_policy_of(lid)
        rows.append((lid, path, need, covered, missing, policy))

    print("authoritative Rule A coverage (required level set derived from index.html):")
    for lid, path, need, covered, missing, policy in rows:
        retired = reg.retired_policy_versions(lid)
        state = ("ACTIVE policy v%s" % policy.get("version")) if policy else (
            "no policy (retired v%s)" % ",".join(str(v) for v in retired) if retired else "no policy")
        print("  %-32s %-22s %d/%d  %s" % (lid.replace("english.prea1.taipei.", "…taipei."),
                                           path, len(covered), len(need), state))
        print("       required : %s" % ", ".join("%s %s" % (l, LEVEL_NAME.get(l, "?")) for l in need))
        if covered:
            print("       covered  : %s" % ", ".join("%s→%s" % (l, a.rsplit(".", 1)[1]) for l, a in covered))
        if missing:
            print("       UNCOVERED: %s" % ", ".join("%s %s" % (l, LEVEL_NAME.get(l, "?")) for l in missing))

        req = list((policy or {}).get("requiredActivityIds") or [])
        if policy:
            for aid in req:
                if aid not in reg.activities:
                    errors.append("%s: policy requires unregistered activity %s" % (lid, aid))
                elif not reg.is_server_scored(aid):
                    errors.append("%s: policy requires non-authoritative activity %s" % (lid, aid))
                elif reg.lesson_of_activity(aid) != lid:
                    errors.append("%s: policy requires %s which belongs to %s"
                                  % (lid, aid, reg.lesson_of_activity(aid)))
            if sorted(req) != sorted(a for _, a in covered):
                errors.append("%s: ACTIVE policy required set != authoritative coverage "
                              "(policy=%d, covered=%d) — an active policy must not silently drop or "
                              "invent a scored level" % (lid, len(req), len(covered)))

        # An uncovered level is an actionable REGISTRATION gap only if a generic scorer already
        # supports it. Otherwise it is a capability gap and belongs in the design record.
        for lv in missing:
            where = "ACTIVE policy" if policy else "no policy"
            if LEVEL_ACTIVITY.get(lv):
                warnings.append("%s: level %s %s is supported by an existing generic scorer but no "
                                "activity is registered for it (%s)"
                                % (lid, lv, LEVEL_NAME.get(lv, "?"), where))
            else:
                notes.append("%s: level %s %s is scored by legacy Rule A but has NO server-"
                             "authoritative implementation (%s)"
                             % (lid, lv, LEVEL_NAME.get(lv, "?"), where))

    active = [lid for lid, _, _, _, _, p in rows if p]
    full = [r[0] for r in rows if not r[4]]
    print()
    print("  lessons inventoried            : %d" % len(rows))
    print("  fully authoritative (no gaps)  : %d %s" % (len(full), full))
    print("  active completion policies     : %d %s" % (len(active), active))
    print("  EXPECTED active policies       : %d  (the four approved Taipei Rule A lessons)"
          % len(EXPECTED_ACTIVE))
    unexpected = sorted(set(active) - EXPECTED_ACTIVE)
    absent = sorted(EXPECTED_ACTIVE - set(active))
    for lid in unexpected:
        warnings.append("%s has an active policy but is not in the approved production set" % lid)
    for lid in absent:
        warnings.append("%s is in the approved production set but has NO active policy" % lid)
    for lid in sorted(reg.lessons):
        rv = reg.retired_policy_versions(lid)
        if rv:
            print("  retired policy versions        : %s -> %s (never reusable)" % (lid, rv))
    # Phase 4B revised acceptance: an active policy is a DEFECT while any of its lesson's legacy
    # Rule A levels lack server authority, because it silently redefines the rule.
    for lid, _, need, covered, missing, policy in rows:
        if policy and missing:
            errors.append("%s: policy is ACTIVE but legacy Rule A also scores %s, which has no "
                          "server authority — activating it silently redefines Rule A"
                          % (lid, ", ".join("level %s %s" % (l, LEVEL_NAME.get(l, "?"))
                                            for l in missing)))

    for n in notes:
        print("NOTE  %s" % n)
    for w in warnings:
        print("WARN  %s" % w)
    for e in errors:
        print("ERROR %s" % e)
    if errors or (args.strict and warnings):
        print("VALIDATION FAILED")
        return 1
    print("VALIDATION OK" + (" (with %d note(s))" % len(notes) if notes else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
