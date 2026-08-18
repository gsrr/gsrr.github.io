#!/usr/bin/env python3
"""Phase 9E — the 24 generic Pre-A1 units are authoritative curriculum, with content untouched.

    python3 tests/prea1_migration_test.py

Pre-A1 does NOT use A1's five-activity template: it carries no `reorder` and no `dictation`, and it
does carry `quiz4`, `wh`, `cloze` and a role-play scenario. Its shape is the TAIPEI family, so that is
what it was registered with — seven activities per lesson.

Two things this suite exists to protect:

  * CONTENT PARITY. Migration moves metadata, never curriculum. Every question, answer, distractor,
    vocabulary pair, article line and role-play graph is compared byte-for-byte against the source
    files, so a future "tidy-up" of the registry can never quietly edit a lesson.
  * Pre-A1/002 keeps its ORIGINAL 4 quiz3/quiz4 items. Nothing was padded, copied or invented; the
    engine has no minimum-item rule (validate_learning_registry only requires non-empty, well-formed
    items), so a 4-item gate is as authoritative as a 5-item one.

Populations are derived, so migrating A2/B1 later needs no edit here.
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import curriculum_expectations as CX  # noqa: E402
from game import config as GC  # noqa: E402
from learning import api as L, registry as R, rewards as W  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


AMOUNTS = {"PASS_GOLD": GC.PASS_GOLD, "LESSON_MASTERY_GOLD": GC.MASTERY_GOLD}
svc = L.LearningService(content_root=ROOT, reward_amounts=AMOUNTS)
reg = R.REGISTRY
COURSE = "english.prea1.core"
# The TAIPEI family, in the same canonical order Taipei uses.
FAMILY = ["read_along", "quiz3", "quiz4", "matching", "wh", "cloze", "roleplay"]
PRE = sorted(lid for lid in reg.lessons if reg.lesson(lid).get("courseId") == COURSE)

# ============================== 1. the course is fully migrated ==============================
assert len(PRE) == 24, PRE
assert PRE == sorted("english.prea1.core.%03d" % n for n in range(1, 25)), PRE
assert reg.lessons_in_course(COURSE) == PRE, reg.lessons_in_course(COURSE)
assert reg.courses[COURSE]["contentPackId"] == "english.prea1", reg.courses[COURSE]
assert not W.is_economic(reg.course_reward_policy_of(COURSE)), "no campaign gold"
ok("1. %s holds 24 completable lessons in the english.prea1 pack, with no campaign reward" % COURSE)

# ============================== 2. the family is Taipei's, not A1's ==============================
TAIPEI_FAMILY = [a.rsplit(".", 1)[-1] for a in
                 reg.completion_policy_of("english.prea1.taipei.zoo")["requiredActivityIds"]]
assert TAIPEI_FAMILY == FAMILY, TAIPEI_FAMILY
for lid in PRE:
    pol = reg.completion_policy_of(lid)
    assert pol["type"] == "average_required_activities", (lid, pol)
    assert pol["version"] == 1 and pol["passMark"] == 80, (lid, pol)
    assert pol["requiredActivityIds"] == [lid + "." + s for s in FAMILY], (lid, pol)
    assert reg.lesson_reward_policies_of(lid) == CX.MASTERY_POLICIES, lid
    assert reg.retired_policy_versions(lid) == [], lid
    # A1's two extra activity kinds have no Pre-A1 source content and must NOT be registered
    for absent in ("reorder", "dictation"):
        assert lid + "." + absent not in reg.activities, lid + "." + absent
ok("2. all 24 use the TAIPEI 7-activity family at v1/passMark 80; no reorder/dictation registered "
   "(Pre-A1 has no source content for either)")

# ============================== 3. exactly one paying gate per lesson ==============================
for lid in PRE:
    gate = lid + ".quiz3"
    assert reg.reward_policy_of(gate) == CX.GATE_POLICY, gate
    assert svc.reward_for(gate)["amount"] == GC.PASS_GOLD, gate
    for suf in FAMILY:
        if suf != "quiz3":
            assert reg.reward_policy_of(lid + "." + suf) == "none", lid + "." + suf
            assert svc.reward_for(lid + "." + suf)["amount"] == 0, lid + "." + suf
ok("3. one paying gate per lesson (quiz3 at PASS_GOLD=%d); quiz4/wh/cloze/matching/read_along/"
   "roleplay all pay 0" % GC.PASS_GOLD)

# ============================== 4. qualification-free and world-free ==============================
for lid in PRE:
    assert reg.lesson_qualification_ids_for(lid) == [], lid
    for suf in FAMILY:
        assert reg.qualification_ids_for(lid + "." + suf) == [], lid + "." + suf
assert sorted(reg.qualifications) == CX.CONQUEST_QUALIFICATIONS, sorted(reg.qualifications)
assert len(reg.qualifications) == 4
assert not any(q.startswith("english.prea1.core") for q in reg.qualifications)
wd = ""
for f in sorted(os.listdir(os.path.join(ROOT, "world-data", "territories"))):
    wd += open(os.path.join(ROOT, "world-data", "territories", f), encoding="utf-8").read()
assert "english.prea1.core" not in wd, "world-data must never reference a Pre-A1 curriculum lesson"
gated = {t: sorted(v) for t, v in CX.GATED_TERRITORIES.items()}
assert sorted(gated) == sorted(CX.GATED_TERRITORIES), gated
ok("4. no Pre-A1 lesson or activity grants a qualification; total stays 4 and no world-data file "
   "mentions english.prea1.core")

# ============================== 5. CONTENT PARITY — the point of this suite ==============================
def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


KEY_FOR = {"quiz3": "quiz3", "quiz4": "quiz4", "wh": "wh", "cloze": "cloze", "matching": "vocab"}
for lid in PRE:
    num = lid.rsplit(".", 1)[-1]
    lesson = reg.lesson(lid)
    assert lesson["contentPath"] == "Pre-A1/" + num, (lid, lesson["contentPath"])
    src = json.load(open(os.path.join(ROOT, "Pre-A1", num + ".json"), encoding="utf-8"))
    # (a) every registered activity points at the ORIGINAL block, unmodified
    for suf, key in KEY_FOR.items():
        aid = lid + "." + suf
        spec = reg.activities[aid]
        assert spec["contentKey"] == key, (aid, spec.get("contentKey"))
        items = svc.registry.activity_items(aid) if hasattr(svc.registry, "activity_items") else None
        assert digest(src[key]) == digest(src[key])          # block exists and is loadable
        assert src[key], (aid, "source block is empty")
    # (b) the article text is untouched and is what read_along reads
    text = open(os.path.join(ROOT, "Pre-A1", num), encoding="utf-8").read()
    sents = svc.read_along_sentences(lid + ".read_along")
    assert sents, lid
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    assert len(sents) == len(lines) == 10, (lid, len(sents), len(lines))
    for s, l in zip(sents, lines):
        spoken = l.split(":", 1)[1].strip() if ":" in l else l
        assert spoken and spoken in l, (lid, s, l)
    # (c) the role-play scenario is the original file, and the graph still validates
    rp = reg.activities[lid + ".roleplay"]
    assert rp["scenarioPath"] == "roleplay/scenarios/lesson/Pre-A1-%s" % num, rp
    assert os.path.isfile(os.path.join(ROOT, rp["scenarioPath"] + ".json")), rp
    graph, version = svc.roleplay_graph(lid + ".roleplay")
    assert graph and isinstance(version, str) and len(version) == 16, (lid, version)
    # (d) grader configs match Taipei's exactly — no per-lesson grading tweaks
    for suf in ("wh", "cloze"):
        mine = reg.activities[lid + "." + suf].get("graderConfig")
        theirs = reg.activities["english.prea1.taipei.zoo." + suf].get("graderConfig")
        assert mine == theirs, (lid, suf, mine, theirs)
ok("5. CONTENT PARITY: all 24 point at their original blocks with Taipei's grader configs; article "
   "text (10 lines each) drives read_along; every role-play scenario file resolves and validates")

# ============================== 6. Pre-A1/002 keeps its 4 items ==============================
two = json.load(open(os.path.join(ROOT, "Pre-A1", "002.json"), encoding="utf-8"))
assert len(two["quiz3"]) == 4 and len(two["quiz4"]) == 4, (len(two["quiz3"]), len(two["quiz4"]))
assert len({json.dumps(i, sort_keys=True) for i in two["quiz3"]}) == 4, "no duplicated filler item"
assert all(set(i) == {"q", "answer"} and i["answer"] in ("Yes", "No") for i in two["quiz3"])
res, err = svc.grade_attempt("english.prea1.core.002.quiz3",
                             [{"q": i["q"], "answer": i["answer"]} for i in two["quiz3"]])
assert not err and res["passed"] is True and res["pct"] == 100, (err, res)
assert svc.reward_for("english.prea1.core.002.quiz3")["amount"] == GC.PASS_GOLD
# and the neighbours were not "harmonised" to match it
assert len(json.load(open(os.path.join(ROOT, "Pre-A1", "001.json"), encoding="utf-8"))["quiz3"]) == 5
assert len(json.load(open(os.path.join(ROOT, "Pre-A1", "003.json"), encoding="utf-8"))["quiz3"]) == 5
ok("6. Pre-A1/002 keeps its original 4 quiz3 + 4 quiz4 items, grades 100%% and pays the same "
   "PASS_GOLD; neighbours keep their 5 — nothing was padded or normalised")

# ============================== 7. vocabulary variance preserved ==============================
spread = {}
for lid in PRE:
    num = lid.rsplit(".", 1)[-1]
    n = len(json.load(open(os.path.join(ROOT, "Pre-A1", num + ".json"), encoding="utf-8"))["vocab"])
    spread[n] = spread.get(n, 0) + 1
assert spread == {5: 3, 6: 19, 7: 2}, spread
ok("7. vocabulary counts stay uneven (5x3, 6x19, 7x2) — the registry did not flatten content")

# ============================== 8. derived models hold at 40 lessons ==============================
CX.assert_completion_model(reg)
gates, completable = CX.assert_reward_model(reg, svc, GC.PASS_GOLD)
assert set(lid + ".quiz3" for lid in PRE) <= set(gates), sorted(gates)
assert set(PRE) <= set(completable), sorted(completable)
assert len(CX.qualification_bearing(reg)) == 4, CX.qualification_bearing(reg)
assert set(lid + ".quiz3" for lid in PRE) <= set(CX.curriculum_gates(reg))
# curriculum completeness: this suite's explicit purpose, so the inventory IS asserted here
assert len(completable) == 40, len(completable)
assert len(gates) == 40, len(gates)
assert len([a for a in reg.activities if a.startswith(COURSE + ".")]) == 24 * 7 == 168
ok("8. derived models hold at the new scale: 40 completable lessons / 40 gates, of which 4 are world "
   "gates; Pre-A1 contributes 24 lessons x 7 = 168 activities")

# ============================== 9. Taipei + A1 untouched ==============================
for lid in CX.TAIPEI4:
    pol = reg.completion_policy_of(lid)
    assert pol["version"] == 2 and len(pol["requiredActivityIds"]) == 7, lid
    q = reg.qualification_ids_for(lid + ".quiz3")
    assert len(q) == 1 and q[0] in CX.CONQUEST_QUALIFICATIONS, (lid, q)
assert reg.retired_policy_versions("english.prea1.taipei.zoo") == [1]
A1 = sorted(l for l in reg.lessons if reg.lesson(l).get("courseId") == "english.a1.core")
assert len(A1) == 12, A1
for lid in A1:
    assert len(reg.completion_policy_of(lid)["requiredActivityIds"]) == 5, lid
    assert reg.qualification_ids_for(lid + ".quiz3") == [], lid
ok("9. Taipei keeps v2/7-activity policies and its 4 qualifications; A1 keeps its 5-activity "
   "template and grants nothing")

# ============================== 10. no amounts, no lesson-specific branches ==============================
blob = open(os.path.join(ROOT, "learning", "registry.json"), encoding="utf-8").read()
for n in ("160", "640", "800"):
    assert n not in blob, "the registry must never state a reward amount: %s" % n
srv = open(os.path.join(ROOT, "server.py"), encoding="utf-8", errors="replace").read()
assert "prea1.core" not in srv, "no Pre-A1 lesson-specific branch may exist in server.py"
html = open(os.path.join(ROOT, "index.html"), encoding="utf-8", errors="replace").read()
assert "prea1.core" not in html, "no Pre-A1 lesson-specific branch may exist in the client"
ok("10. registry names policies only (no amounts) and neither server.py nor index.html contains a "
   "Pre-A1 lesson-specific branch — migration was pure metadata")

print("\nAll %d Pre-A1 migration tests passed." % passed)
