#!/usr/bin/env python3
"""Phase 3B — learning identity + registry validation (§31, §32). Pure, no I/O beyond the real registry.

    python3 tests/learning_identity_test.py
"""
import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from learning import identity as I, registry as R, grading as G, rewards as W  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ================================ §31 identity ================================
for good in ("english", "english.prea1", "english.prea1.taipei.zoo", "english.prea1.taipei.zoo.quiz3",
             "bio.cells.u1", "a1.b-2.c_3", "x9"):
    assert I.is_id(good), good
for bad in ("", None, 0, [], "English.PreA1", "english..zoo", ".english", "english.",
            "english zoo", "english/zoo", "english#zoo", "-english", "_english", "..", ".",
            "Pre-A1/taipei/zoo", "english.prea1.taipei.zoo#quiz3"):
    assert not I.is_id(bad), bad
ok("identity: dotted lowercase ids accepted; empty/uppercase/spaces/slashes/hashes/edges rejected")

# hierarchy is pure segment prefixing — no table, no naming convention beyond the dots
assert I.parent_id("english.prea1.taipei.zoo.quiz3") == "english.prea1.taipei.zoo"
assert I.parent_id("english.prea1.taipei.zoo") == "english.prea1.taipei"
assert I.parent_id("english.prea1.taipei") == "english.prea1"
assert I.parent_id("english.prea1") == "english"
assert I.parent_id("english") is None and I.parent_id("bogus id") is None
assert I.segments("a.b.c") == ["a", "b", "c"] and I.segments("bad id") == []
assert I.is_ancestor("english.prea1", "english.prea1.taipei.zoo") is True
assert I.is_ancestor("english.prea1", "english.prea1") is True, "an id contains itself"
assert I.is_ancestor("english.prea1", "english.prea10") is False, "prefix match is on whole segments"
assert I.is_ancestor("english.prea1.taipei", "english.prea1") is False
assert I.is_ancestor("bad id", "english.prea1") is False
assert I.SCOPES == ("activity", "lesson", "unit", "course")
ok("identity hierarchy: parent_id walks levels, is_ancestor is segment-wise (prea1 !< prea10)")

# content paths: shape gate against traversal / absolutes / separators
for good in ("Pre-A1/taipei/zoo", "packs/bio/cells", "zoo", "A2/space/mars", "a b/c.d-e_f"):
    assert I.is_content_path(good), good
for bad in ("", None, "/etc/passwd", "../server", "a/../b", "a/./b", "..", ".", "a//b", "a/",
            "packs\\bio\\cells", "C:/Windows/win.ini", "a/b/.."):
    assert not I.is_content_path(bad), bad
ok("identity content paths: relative-only, traversal / absolute / backslash / empty-segment rejected")

# legacy Phase 3A completion keys round-trip and are distinguishable from canonical ids
assert I.legacy_completion_key("Pre-A1/taipei/zoo", "quiz3") == "Pre-A1/taipei/zoo#quiz3"
assert I.split_legacy_completion_key("Pre-A1/taipei/zoo#quiz3") == ("Pre-A1/taipei/zoo", "quiz3")
assert I.looks_legacy("Pre-A1/taipei/zoo#quiz3") and not I.looks_legacy("english.prea1.taipei.zoo.quiz3")
for bad in ("", None, "no-hash", "#quiz3", "path#", "a#b#c"):
    assert I.split_legacy_completion_key(bad) == (None, None), bad
    assert not I.looks_legacy(bad), bad
assert I.legacy_completion_key("", "quiz3") is None and I.legacy_completion_key("p", "") is None
ok("identity legacy keys: build/split/round-trip, malformed variants rejected, distinct from canonical")


# ================================ §32 registry ================================
BASE = {
    "schemaVersion": 1,
    "contentPacks": {"p": {"title": "P"}},
    "courses": {"p.c": {"contentPackId": "p", "title": "C"}},
    "units": {},
    "lessons": {"p.c.l": {"courseId": "p.c", "contentPath": "packs/x/l", "title": "L"}},
    "activities": {"p.c.l.a": {"lessonId": "p.c.l", "contentKey": "a", "graderType": "yes_no",
                               "title": "A", "grants": ["p.q1"], "rewardPolicy": "standard_activity_pass",
                               "legacyKeys": ["packs/x/l#a"]}},
    "qualifications": {"p.q1": {"scope": "activity", "title": "Q1"}},
}
assert R.validate(BASE) == [], R.validate(BASE)
ok("registry: a minimal valid registry validates clean")


def broken(mutate):
    d = copy.deepcopy(BASE)
    mutate(d)
    return R.validate(d)


def rejects(mutate, needle):
    errs = broken(mutate)
    assert errs, "expected a validation error for: " + needle
    assert any(needle in e for e in errs), (needle, errs)


rejects(lambda d: d.update(schemaVersion=2), "schemaVersion")
rejects(lambda d: d.update(bogusSection={}), "unknown top-level sections")
rejects(lambda d: d.update(activities=[]), "activities must be an object")
rejects(lambda d: d["activities"].update({"": dict(d["activities"]["p.c.l.a"])}), "malformed")
rejects(lambda d: d["activities"].update({"Bad.ID": dict(d["activities"]["p.c.l.a"])}), "malformed")
rejects(lambda d: d["qualifications"].update({"": {"scope": "activity"}}), "malformed")
# referential integrity, every level
rejects(lambda d: d["courses"]["p.c"].update(contentPackId="nope"), "unknown contentPackId")
rejects(lambda d: d["lessons"]["p.c.l"].update(courseId="nope"), "unknown courseId")
rejects(lambda d: d["lessons"]["p.c.l"].update(unitId="nope"), "unknown unitId")
rejects(lambda d: d["activities"]["p.c.l.a"].update(lessonId="nope"), "unknown lessonId")
rejects(lambda d: d["activities"]["p.c.l.a"].update(grants=["nope"]), "grants unknown qualification")
rejects(lambda d: d["units"].update({"p.u": {"courseId": "nope"}}), "unknown courseId")
# content mapping
rejects(lambda d: d["lessons"]["p.c.l"].update(contentPath="../etc/passwd"), "malformed contentPath")
rejects(lambda d: d["lessons"]["p.c.l"].update(contentPath="/abs"), "malformed contentPath")
rejects(lambda d: d["lessons"]["p.c.l"].pop("contentPath"), "malformed contentPath")
rejects(lambda d: d["activities"]["p.c.l.a"].pop("contentKey"), "missing/invalid contentKey")
# grader
rejects(lambda d: d["activities"]["p.c.l.a"].update(graderType="matching"), "unknown graderType")
rejects(lambda d: d["activities"]["p.c.l.a"].update(graderType="quiz3"), "unknown graderType")
rejects(lambda d: d["activities"]["p.c.l.a"].update(graderType="pronunciation"), "unknown graderType")
rejects(lambda d: d["activities"]["p.c.l.a"].pop("graderType"), "unknown graderType")
# Phase 3C graderConfig validation
rejects(lambda d: d["activities"]["p.c.l.a"].update(graderConfig="nope"), "graderConfig must be an object")
rejects(lambda d: d["activities"]["p.c.l.a"].update(graderConfig={"bogusKey": "q"}), "unknown keys")
rejects(lambda d: d["activities"]["p.c.l.a"].update(graderConfig={"promptField": ""}), "non-empty string")
rejects(lambda d: d["activities"]["p.c.l.a"].update(graderConfig={"answerField": 5}), "non-empty string")
rejects(lambda d: d["activities"]["p.c.l.a"].update(grants="p.q1"), "grants must be a list")
# titles + grants
rejects(lambda d: d["activities"]["p.c.l.a"].pop("title"), "no title")
# Phase 3C §24: an activity may be server-graded WITHOUT granting a qualification, so empty grants is
# now valid — but the qualification it used to grant must then have another route (or not exist).
import copy as _copy  # noqa: E402
_no_grants = _copy.deepcopy(BASE)
_no_grants["activities"]["p.c.l.a"]["grants"] = []
_no_grants["qualifications"] = {}
assert R.validate(_no_grants) == [], R.validate(_no_grants)
assert R.Registry(_no_grants).qualification_ids_for("p.c.l.a") == []
rejects(lambda d: d["activities"]["p.c.l.a"].update(grants=["p.q1", "p.q1"]), "duplicate qualification in grants")
rejects(lambda d: d["qualifications"].update({"p.orphan": {"scope": "activity"}}), "no activity grants it")
# reward policy trust boundary (§15)
rejects(lambda d: d["activities"]["p.c.l.a"].update(rewardPolicy="jackpot"), "invalid rewardPolicy")
for money in ("rewardGold", "gold", "rewardAmount", "amount"):
    rejects(lambda d, m=money: d["activities"]["p.c.l.a"].update({m: 999999999}),
            "may not set")
# scope: only 'activity' may be earnable (§7)
rejects(lambda d: d["qualifications"]["p.q1"].update(scope="course"), "only 'activity' scope is earnable")
rejects(lambda d: d["qualifications"]["p.q1"].update(scope="galaxy"), "invalid scope")
# legacy keys
rejects(lambda d: d["activities"]["p.c.l.a"].update(legacyKeys=["no-hash"]), "malformed legacyKey")
rejects(lambda d: d["activities"].update({"p.c.l.b": {
    "lessonId": "p.c.l", "contentKey": "b", "graderType": "yes_no", "title": "B",
    "grants": ["p.q1"], "legacyKeys": ["packs/x/l#a"]}}), "claimed by both")
# studyTarget override must point at a real activity
rejects(lambda d: d["qualifications"]["p.q1"].update(studyTarget={"activityId": "nope"}), "unknown activity")
assert R.validate("not a dict") == ["registry must be a JSON object"]
ok("registry validation: schema/refs/content/grader/title/grants/reward/scope/legacy/studyTarget all enforced")

# a duplicate JSON key is an authoring error, not silent last-wins
import json  # noqa: E402
try:
    json.loads('{"a": 1, "a": 2}', object_pairs_hook=R._no_dup_keys)
    raise AssertionError("duplicate key must raise")
except ValueError as e:
    assert "duplicate key" in str(e)
data, errs = R.load_data(os.path.join(ROOT, "tests", "nonexistent-registry.json"))
assert data == {} and errs and "cannot load" in errs[0]
ok("registry loading: duplicate JSON keys rejected, unreadable file reported not crashed")

# ---- lookups + derived views on a registry with several activities and a shared qualification ----
MULTI = copy.deepcopy(BASE)
MULTI["lessons"]["p.c.l2"] = {"courseId": "p.c", "contentPath": "packs/x/l2", "title": "L2"}
MULTI["qualifications"]["p.q2"] = {"scope": "activity", "title": "Q2"}
MULTI["activities"]["p.c.l2.a"] = {"lessonId": "p.c.l2", "contentKey": "a", "graderType": "yes_no",
                                  "title": "A2", "grants": ["p.q1", "p.q2"]}
assert R.validate(MULTI) == [], R.validate(MULTI)
reg = R.Registry(MULTI)
assert reg.content_path_of("p.c.l.a") == "packs/x/l" and reg.content_path_of("nope") is None
assert reg.approved_content_paths() == {"packs/x/l", "packs/x/l2"}
assert reg.qualification_ids_for("p.c.l2.a") == ["p.q1", "p.q2"], "order preserved"
assert sorted(reg.granted_by("p.q1")) == ["p.c.l.a", "p.c.l2.a"], "a qualification may have several routes"
assert reg.granted_by("p.q2") == ["p.c.l2.a"] and reg.granted_by("nope") == []
assert reg.reward_policy_of("p.c.l.a") == "standard_activity_pass"
assert reg.reward_policy_of("p.c.l2.a") == W.DEFAULT_POLICY, "an omitted policy falls back to the default"
assert reg.grader_type_of("p.c.l.a") == "yes_no" and G.is_supported(reg.grader_type_of("p.c.l.a"))
assert reg.legacy_keys_for("p.c.l.a") == ["packs/x/l#a"] and reg.legacy_keys_for("p.c.l2.a") == []
# study target: derived from the granting activity, deterministic when several routes exist
assert reg.study_target("p.q1") == {"activityId": "p.c.l.a", "lessonId": "p.c.l",
                                    "contentPath": "packs/x/l", "title": "A"}
assert reg.study_target("p.q2")["activityId"] == "p.c.l2.a"
assert reg.study_target("nope") is None
assert reg.title_of_qualification("p.q1") == "Q1" and reg.title_of_qualification("unknown.q") == "unknown.q"
# an explicit override wins
OVR = copy.deepcopy(MULTI)
OVR["qualifications"]["p.q1"]["studyTarget"] = {"activityId": "p.c.l2.a"}
assert R.Registry(OVR).study_target("p.q1")["activityId"] == "p.c.l2.a", "explicit studyTarget override wins"
# a title-only edit must not change identity (§3: ids stable across UI text changes)
TITLED = copy.deepcopy(MULTI)
TITLED["qualifications"]["p.q1"]["title"] = "Completely different wording"
assert set(R.Registry(TITLED).qualifications) == set(reg.qualifications)
assert R.Registry(TITLED).study_target("p.q1")["activityId"] == reg.study_target("p.q1")["activityId"]
ok("registry lookups: paths/grants/routes/policies/legacy keys, derived + overridden studyTarget, stable ids")

# public view: identity + titles only — no answer keys, grader types or reward policies
pv = reg.public_view()
blob = json.dumps(pv)
for leaked in ("graderType", "rewardPolicy", "legacyKeys", "answer", "contentKey\": \"secret"):
    assert leaked not in blob, leaked
assert set(pv) == {"schemaVersion", "qualifications", "activities", "lessons"}
assert pv["qualifications"]["p.q1"]["title"] == "Q1" and pv["qualifications"]["p.q1"]["studyTarget"]
assert pv["activities"]["p.c.l2.a"]["grants"] == ["p.q1", "p.q2"]
assert R.Registry({}).public_view()["qualifications"] == {}, "an empty/absent registry degrades quietly"
assert R.Registry(None).approved_content_paths() == set()
ok("registry public view: identity/titles/studyTargets only; empty registry degrades without error")

# the REAL installed registry validates and exposes the Phase 3A slice under canonical identity
assert R.LOAD_ERRORS == [], R.LOAD_ERRORS
assert R.validate(R.DATA) == [], R.validate(R.DATA)
prod = R.REGISTRY
assert prod.resolve_activity_id("english.prea1.taipei.zoo.quiz3") == "english.prea1.taipei.zoo.quiz3"
assert prod.content_path_of("english.prea1.taipei.zoo.quiz3") == "Pre-A1/taipei/zoo"
assert I.is_ancestor("english.prea1", "english.prea1.taipei.zoo.quiz3"), "pack contains the activity"
assert I.parent_id("english.prea1.taipei.zoo.quiz3") in prod.lessons, "activity's parent IS its lesson"
assert prod.lessons["english.prea1.taipei.zoo"]["courseId"] in prod.courses
assert prod.courses["english.prea1.taipei"]["contentPackId"] in prod.contentPacks
ok("installed registry: validates, and pack/course/lesson/activity ids form a real prefix hierarchy")

print("\nAll %d learning-identity tests passed." % passed)
