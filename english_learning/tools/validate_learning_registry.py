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


def shape_problems(grader_type, cfg, items):
    """Does the real content match what `grader_type` needs? Returns a list of problem strings.

    A grader that cannot read its content would silently score 0/0 at runtime, so this is checked at
    validation time rather than discovered by a learner. Only the first offending item is reported per
    problem so the output stays readable.
    """
    probs = []
    if grader_type in ("yes_no", "multiple_choice"):
        pf = (cfg or {}).get("promptField") or "q"
        af = (cfg or {}).get("answerField") or ("answer" if grader_type == "yes_no" else "a")
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                probs.append("item %d is %s, expected an object" % (i, type(it).__name__))
                break
        else:
            missing_p = [i for i, it in enumerate(items) if not str(it.get(pf) or "").strip()]
            missing_a = [i for i, it in enumerate(items) if it.get(af) in (None, "")]
            if missing_p:
                probs.append("promptField %r missing/blank on item(s) %s" % (pf, missing_p[:5]))
            if missing_a:
                probs.append("answerField %r missing/blank on item(s) %s" % (af, missing_a[:5]))
            if grader_type == "multiple_choice":
                df = (cfg or {}).get("distractorsField") or "wrong"
                nodis = [i for i, it in enumerate(items) if not isinstance(it.get(df), list) or not it[df]]
                if nodis:
                    probs.append("distractorsField %r missing/empty on item(s) %s — the activity would "
                                 "offer only the correct answer" % (df, nodis[:5]))
    elif grader_type == "reorder":
        bad = [i for i, it in enumerate(items) if not isinstance(it, list) or not it]
        if bad:
            probs.append("reorder items must be non-empty token lists; offending item(s) %s" % bad[:5])
        else:
            joined = [" ".join(str(t) for t in it) for it in items]
            if len(set(joined)) != len(joined):
                probs.append("two reorder sentences join to the same text — answers could not be "
                             "attributed to the right sentence")
    elif grader_type == "dictation":
        bad = [i for i, it in enumerate(items) if not isinstance(it, str) or not it.strip()]
        if bad:
            probs.append("dictation items must be non-empty strings; offending item(s) %s" % bad[:5])
        elif len(set(s.strip() for s in items)) != len(items):
            probs.append("duplicate dictation sentences — answers could not be attributed")
    return probs


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

    # content files the registry promises must exist, expose the declared key, AND have a shape the
    # declared grader can actually read (§35) — this is what catches a graderType/graderConfig that
    # was pointed at the wrong content key.
    for aid, spec in sorted(reg.activities.items()):
        path = reg.content_path_of(aid)
        items = learning_content.load_activity_items(path, spec.get("contentKey"), ROOT,
                                                    reg.approved_content_paths())
        if items is None:
            err("activity %s: content %r has no usable %r list under CONTENT_ROOT"
                % (aid, path, spec.get("contentKey")))
            continue
        for msg in shape_problems(spec.get("graderType"), reg.grader_config_of(aid), items):
            err("activity %s (%s/%s): %s" % (aid, path, spec.get("contentKey"), msg))

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
    # per-activity coverage: which are gold-bearing and which certify a qualification (§22/§24)
    for aid in sorted(reg.activities):
        pol = reg.reward_policy_of(aid)
        print("    %-34s %-16s reward=%-24s grants=%s"
              % (aid, reg.grader_type_of(aid), pol, reg.qualification_ids_for(aid) or "[]"))
    paid = [a for a in reg.activities if reg.reward_policy_of(a) != "none"]
    print("  gold-bearing activities: %d/%d %s" % (len(paid), len(reg.activities), sorted(paid)))
    # Phase 3D: authoritative whole-lesson completion coverage. Expected to be 0 until Level 2 (STT)
    # and Level 5 (matching) have server-authoritative evidence — see docs/lesson-completion.md.
    with_policy = sorted(l for l in reg.lessons if reg.completion_available(l))
    print("  lessons with an active completionPolicy: %d/%d %s"
          % (len(with_policy), len(reg.lessons), with_policy or "[]"))
    for lid in with_policy:
        pol = reg.completion_policy_of(lid)
        print("    %-30s type=%s v=%s reward=%s grants=%s required=%d"
              % (lid, pol.get("type"), pol.get("version"), reg.lesson_reward_policy_of(lid),
                 reg.lesson_qualification_ids_for(lid) or "[]", len(pol.get("requiredActivityIds") or [])))
    paid_lessons = [l for l in with_policy if reg.lesson_reward_policy_of(l) != "none"]
    if paid_lessons:
        warn("cross-domain: %d lesson(s) carry a gold-bearing completion reward: %s"
             % (len(paid_lessons), paid_lessons))
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
