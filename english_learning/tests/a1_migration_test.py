#!/usr/bin/env python3
"""Phase 9C — the whole A1 course is authoritative curriculum, and no title drifted.

    python3 tests/a1_migration_test.py

Phase 9A found `english.a1.core.001` carrying A1/**002**'s title ("My Weekend") while pointing at
A1/001 ("Yesterday at the Park"). Phase 9C migrates eleven more lessons, so that failure mode now has
eleven more chances to happen — and a shifted title is invisible to every structural test.

Guard here: each registry title is checked against TWO independent sources — the `lessons.json`
manifest AND keyword evidence inside the lesson's own content files. Nothing in this test restates the
registry's own titles, so it cannot pass by agreeing with the thing it is checking.

Everything else is asserted over the DERIVED A1 population (Phase 9B.1), so 9D/9E can migrate
Pre-A1/A2/B1 without editing this file.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import curriculum_expectations as CX  # noqa: E402
from game import config as GC  # noqa: E402
from learning import api as L, registry as R  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


AMOUNTS = {"PASS_GOLD": GC.PASS_GOLD, "LESSON_MASTERY_GOLD": GC.MASTERY_GOLD}
svc = L.LearningService(content_root=ROOT, reward_amounts=AMOUNTS)
reg = R.REGISTRY
COURSE = "english.a1.core"
TEMPLATE = ["read_along", "quiz3", "matching", "reorder", "dictation"]
# derived, not hardcoded: whatever lessons this course actually holds
A1 = sorted(lid for lid in reg.lessons if reg.lesson(lid).get("courseId") == COURSE)
STOP_WORDS = {"a", "an", "the", "at", "in", "on", "my", "of", "and", "to", "for", "with"}

# ============================== 1. the course is fully migrated ==============================
assert len(A1) == 12, A1
assert A1 == sorted("english.a1.core.%03d" % n for n in range(1, 13)), A1
assert reg.lessons_in_course(COURSE) == A1, reg.lessons_in_course(COURSE)
ok("1. english.a1.core holds 12 lessons and every one is completable (course emits all 12)")

# ============================== 2. titles verified against TWO independent sources ==========
man = json.load(open(os.path.join(ROOT, "lessons.json"), encoding="utf-8"))
arts = {a["id"]: a["title"] for a in
        [lv for lv in man["levels"] if lv["id"] == "A1"][0]["articles"]}
assert len(arts) == 12, sorted(arts)
for lid in A1:
    num = lid.rsplit(".", 1)[-1]
    lesson = reg.lesson(lid)
    assert lesson["contentPath"] == "A1/" + num, (lid, lesson["contentPath"])
    # (a) the manifest's own title for THIS number, independently parsed
    manifest_title = arts[num].split("·", 1)[1].strip()
    assert lesson["title"] == "A1 · %s %s" % (num, manifest_title), \
        (lid, lesson["title"], manifest_title)
    # (b) keyword evidence in the lesson's OWN content — catches a title/content shift even if the
    #     manifest itself were wrong (which is exactly how the A1/001 defect survived)
    body = (open(os.path.join(ROOT, "A1", num), encoding="utf-8").read() + " " +
            json.dumps(json.load(open(os.path.join(ROOT, "A1", num + ".json"), encoding="utf-8")),
                       ensure_ascii=False)).lower()
    words = [w for w in re.findall(r"[a-z']+", manifest_title.lower())
             if w not in STOP_WORDS and len(w) > 2]
    assert words, (lid, manifest_title)
    for w in words:
        stem = w[:-3] if w.endswith("ing") else w.rstrip("s")
        assert w in body or stem in body, \
            ("title keyword %r is absent from %s's own content — a shifted title?" % (w, lid))
    # (c) no OTHER A1 lesson claims this title
    same = [o for o in A1 if o != lid and reg.lesson(o)["title"] == lesson["title"]]
    assert not same, (lid, same)
ok("2. all 12 titles agree with lessons.json AND with keyword evidence in their own content; "
   "no two A1 lessons share a title")

# the specific historical defect stays fixed, and its neighbour is not disturbed
assert reg.lesson("english.a1.core.001")["title"].endswith("Yesterday at the Park")
assert reg.lesson("english.a1.core.002")["title"].endswith("My Weekend")
ok("2b. the Phase 9A title shift stays fixed: 001 = Yesterday at the Park, 002 = My Weekend")

# ============================== 3. every lesson follows the template ==============================
for lid in A1:
    pol = reg.completion_policy_of(lid)
    assert pol["type"] == "average_required_activities", (lid, pol)
    assert pol["version"] == 1 and pol["passMark"] == 80, (lid, pol)
    assert pol["requiredActivityIds"] == [lid + "." + s for s in TEMPLATE], (lid, pol)
    assert reg.lesson_reward_policies_of(lid) == CX.MASTERY_POLICIES, lid
    assert reg.retired_policy_versions(lid) == [], lid
    for suf in TEMPLATE:
        aid = lid + "." + suf
        assert aid in reg.activities, aid
        assert reg.activities[aid]["lessonId"] == lid, aid
    # Phase 9E.2 CATALOGUED the four practice activities A1 already showed learners, WITHOUT making
    # them mastery-required. So they must now be present, absent from requiredActivityIds, and inert.
    for suf in ("quiz4", "wh", "cloze", "roleplay"):
        aid = lid + "." + suf
        assert aid in reg.activities, ("9E.2 catalogued this practice activity", aid)
        assert aid not in pol["requiredActivityIds"], ("must stay OPTIONAL for mastery", aid)
        assert reg.reward_policy_of(aid) == "none", aid
        assert reg.reward_policy_of(aid) != "standard_activity_pass", aid
        assert reg.qualification_ids_for(aid) == [], aid
ok("3. every A1 lesson requires the 5-activity template at v1/passMark 80 with both mastery "
   "policies, and additionally CATALOGUES quiz4/wh/cloze/roleplay as inert optional practice")

# ============================== 4. exactly one paying gate per lesson =========================
for lid in A1:
    gate = lid + ".quiz3"
    assert reg.reward_policy_of(gate) == CX.GATE_POLICY, gate
    assert svc.reward_for(gate)["amount"] == GC.PASS_GOLD, gate
    others = [lid + "." + s for s in TEMPLATE if s != "quiz3"]
    for aid in others:
        assert reg.reward_policy_of(aid) == "none", aid
        assert reg.reward_policy_of(aid) != "standard_activity_pass", aid
ok("4. each A1 lesson has exactly ONE paying activity (quiz3 at PASS_GOLD); the other four pay 0")

# ============================== 5. qualification-free, world-free =============================
for lid in A1:
    assert reg.lesson_qualification_ids_for(lid) == [], lid
    for suf in TEMPLATE:
        assert reg.qualification_ids_for(lid + "." + suf) == [], lid + "." + suf
assert sorted(reg.qualifications) == CX.CONQUEST_QUALIFICATIONS, sorted(reg.qualifications)
assert set(A1) <= set(CX.completable_lessons(reg))
assert set(lid + ".quiz3" for lid in A1) <= set(CX.curriculum_gates(reg))
assert not any(q.startswith("english.a1") for q in reg.qualifications)
wd = ""
for f in sorted(os.listdir(os.path.join(ROOT, "world-data", "territories"))):
    wd += open(os.path.join(ROOT, "world-data", "territories", f), encoding="utf-8").read()
assert "english.a1" not in wd, "world-data must never reference an A1 lesson or qualification"
ok("5. no A1 lesson or activity grants a qualification, qualifications stay at 4, and no world-data "
   "file mentions english.a1 — the whole course is curriculum, not a gate")

# ============================== 6. the derived models still hold ==============================
CX.assert_completion_model(reg)
gates, completable = CX.assert_reward_model(reg, svc, GC.PASS_GOLD)
# Phase 9E: these were GLOBAL totals inside an A1-scoped suite, so migrating another content
# family broke them. Scope them to A1 (what this file is about) and keep the world contract exact.
assert set(lid + ".quiz3" for lid in A1) <= set(gates), sorted(gates)
assert set(A1) <= set(completable), sorted(completable)
assert len(CX.qualification_bearing(reg)) == 4, CX.qualification_bearing(reg)
assert len([g for g in CX.curriculum_gates(reg) if g.startswith("english.a1.core.")]) == 12
ok("6. derived models hold: all 12 A1 gates/lessons are in the derived populations, exactly 4 world "
   "gates and 12 are curriculum gates")

# ============================== 7. Taipei untouched ==============================
for lid in CX.TAIPEI4:
    pol = reg.completion_policy_of(lid)
    assert pol["version"] == 2 and pol["passMark"] == 80 and len(pol["requiredActivityIds"]) == 7, lid
    assert reg.lesson_reward_policies_of(lid) == CX.MASTERY_POLICIES, lid
    q = reg.qualification_ids_for(lid + ".quiz3")
    assert len(q) == 1 and q[0] in CX.CONQUEST_QUALIFICATIONS, (lid, q)
assert reg.retired_policy_versions("english.prea1.taipei.zoo") == [1]
assert reg.qualification_ids_for("english.prea1.taipei.zoo.quiz3") == ["english.prea1.taipei.zoo"]
ok("7. Taipei regression: four v2/7-activity policies, one qualification each, Zoo's retired v1 and "
   "its legacy bare qualification id all unchanged")

# ============================== 8. content and amounts untouched ==============================
blob = open(os.path.join(ROOT, "learning", "registry.json"), encoding="utf-8").read()
for n in ("500", "2500", "3000"):        # 14A.10A amounts; the registry still names none
    assert n not in blob, "the registry must never state a reward amount: %s" % n
# Phase 9E: A1 owns 12 lessons x 5 activities. The GLOBAL activity total is not this suite's
# business — other content families may migrate freely — so assert only A1's own footprint.
assert set(CX.TAIPEI4) <= set(reg.lessons), sorted(reg.lessons)
a1_acts = [a for a in reg.activities if a.startswith("english.a1.core.")]
# Phase 9E.2: A1 CATALOGUES 9 activities per lesson (5 required + 4 optional practice), so the
# footprint is 12 x 9. The mastery-required footprint is asserted separately.
assert len(a1_acts) == 12 * 9 == 108, len(a1_acts)
a1_required = [a for l in A1 for a in reg.completion_policy_of(l)["requiredActivityIds"]]
assert len(a1_required) == 12 * len(TEMPLATE) == 60, len(a1_required)
ok("8. registry names policies only (no amounts); A1 owns 12 lessons x 9 = 108 CATALOGUED "
   "activities of which 12 x 5 = 60 are mastery-required; Taipei is still registered alongside it")

print("\nAll %d A1-migration tests passed." % passed)
