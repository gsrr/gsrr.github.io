"""Phase 9F — A2 and B1 are authoritative curriculum, and they are curriculum ONLY.

    python tests/a2b1_migration_test.py

Phase 9F registered A2 (12 units) and B1 (5 units), taking the registry from 40 to 57 authoritative
lessons. Every unit already existed on disk with a complete nine-activity content set; nothing was
authored, and no Conquest surface was extended.

What this suite pins, and why each check exists rather than being a census:

  1. INVENTORY. A2 = 12 lessons, B1 = 5, each cataloguing all 9 activity types the content supports.
     This suite owns the A2/B1 inventory, so those two numbers are asserted exactly here — and
     nowhere else, so a sixth family never has to edit this file.

  2. CATALOGUED != REQUIRED. Both families follow the A1 model settled in Phase 9E.2: 9 activities
     are OFFERED, 5 are REQUIRED for mastery (read_along, quiz3, matching, reorder, dictation). The
     optional four (quiz4, wh, cloze, roleplay) must be real, gradable activities that mint nothing
     and advance nothing. If a future edit quietly promotes them into the required set, the harder
     content would demand ~80% more work for the identical 800 gold — check 4 fails loudly.

  3. CURRICULUM, NOT CONQUEST. A2/B1 grant zero qualifications. The Conquest surface is exactly the
     four Taipei qualifications it was before Phase 9F. This is the invariant that keeps "add a
     reading level" from silently becoming "add a war objective".

  4. ONE PAYING GATE PER LESSON. Exactly one activity per lesson carries an economic reward policy,
     and the registry never names an AMOUNT (§15) — the amounts come from game/config.py.

  5. CONTENT PARITY. Every registered activity resolves to real on-disk content, and each lesson
     title is evidenced by its own content (the defect class found in A1/001, whose registry title
     described a different scene entirely).
"""
import io, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from game import config as GC
from learning import api as LA, registry as LR
from tests import curriculum_expectations as CX

reg = LR.REGISTRY
svc = LA.LearningService(content_root=".",
                         reward_amounts={"PASS_GOLD": GC.PASS_GOLD,
                                         "LESSON_MASTERY_GOLD": GC.MASTERY_GOLD})
passed = 0


def ok(msg):
    global passed
    passed += 1
    print("  ok - " + msg)


FAMILY9 = ["cloze", "dictation", "matching", "quiz3", "quiz4", "read_along", "reorder", "roleplay", "wh"]
REQUIRED5 = ["read_along", "quiz3", "matching", "reorder", "dictation"]
OPTIONAL4 = ["quiz4", "wh", "cloze", "roleplay"]
COURSES = {"english.a2.core": 12, "english.b1.core": 5}


def lessons_of(cid):
    return sorted(l for l in reg.lessons if reg.lesson(l)["courseId"] == cid)


def types_of(lid):
    return sorted(a.rsplit(".", 1)[-1] for a in reg.activities
                  if reg.activities[a]["lessonId"] == lid)


def required_of(lid):
    return [a.rsplit(".", 1)[-1] for a in reg.completion_policy_of(lid)["requiredActivityIds"]]


# ============================== 1. inventory ==============================
A2, B1 = lessons_of("english.a2.core"), lessons_of("english.b1.core")
assert len(A2) == COURSES["english.a2.core"], len(A2)
assert len(B1) == COURSES["english.b1.core"], len(B1)
NEW = A2 + B1
for cid, pack in (("english.a2.core", "english.a2"), ("english.b1.core", "english.b1")):
    assert cid in reg.courses, cid
    assert reg.courses[cid]["contentPackId"] == pack, reg.courses[cid]
    # a course-level reward policy would pay a second time for the same work
    assert not LA._W.is_economic(reg.course_reward_policy_of(cid)) if hasattr(LA, "_W") else True
assert len(NEW) == 17, len(NEW)
ok("1. A2 = 12 lessons and B1 = 5 lessons, each under its own contentPack and course")

for lid in NEW:
    assert types_of(lid) == FAMILY9, (lid, types_of(lid))
assert len([a for a in reg.activities if reg.activities[a]["lessonId"] in NEW]) == 17 * 9 == 153
ok("2. all 17 lessons catalogue the same nine activity types (%d activities)" % (17 * 9))

# ============================== 2. catalogued != required ==============================
for lid in NEW:
    assert required_of(lid) == REQUIRED5, (lid, required_of(lid))
    pol = reg.completion_policy_of(lid)
    assert pol["type"] == "average_required_activities", pol
    assert pol["passMark"] == 80, pol
    assert pol["grants"] == [], pol
    assert sorted(reg.lesson_reward_policies_of(lid)) == sorted(CX.MASTERY_POLICIES), lid
    assert reg.completion_available(lid), lid
ok("3. every A2/B1 lesson requires the same five activities at passMark 80 and carries the mastery "
   "reward policies, with no grants")

for lid in NEW:
    cat, req = set(types_of(lid)), set(required_of(lid))
    assert cat - req == set(OPTIONAL4), (lid, sorted(cat - req))
    for suf in OPTIONAL4:
        aid = lid + "." + suf
        assert aid in reg.activities, aid
        assert reg.reward_policy_of(aid) != "standard_activity_pass", aid          # mints nothing
        assert reg.qualification_ids_for(aid) == [], aid        # unlocks nothing
        assert reg.activities[aid]["grants"] == [], aid
        assert reg.reward_policy_of(aid) == "none", aid
ok("4. the four optional activities (%s) are catalogued but unpaid, ungranting and outside the "
   "mastery denominator" % ", ".join(OPTIONAL4))

# an optional activity must still be a REAL activity: gradable, and inert when graded
sample = ["english.a2.core.001", "english.a2.core.007", "english.b1.core.003"]
for lid in sample:
    cp = reg.lesson(lid)["contentPath"]
    key = json.load(io.open(cp + ".json", encoding="utf-8"))
    for suf, build in (("quiz4", lambda k: [{"q": i["q"], "answer": i["answer"]} for i in k["quiz4"]]),
                       ("wh", lambda k: [{"q": i["q"], "answer": i["a"]} for i in k["wh"]]),
                       ("cloze", lambda k: [{"q": i["text"], "answer": i["answer"]} for i in k["cloze"]])):
        aid = lid + "." + suf
        res, err = svc.grade_attempt(aid, build(key))
        assert not err and res["passed"] and res["pct"] == 100, (aid, err, res)
        st, out = svc.record_attempt({}, aid, res, 1000)
        assert out["rewardAmount"] == 0 and not out["granted"], (aid, out)
        ev = svc.evaluate_lesson(lid, st)
        assert ev["completed"] is False, aid
        assert ev["completedActivityIds"] == [], (aid, ev["completedActivityIds"])
        assert len(ev["requiredActivityIds"]) == 5, aid
ok("5. a full-marks optional attempt is graded authoritatively yet mints 0 gold and leaves the "
   "mastery numerator at 0 of 5")

# ============================== 3. curriculum, not Conquest ==============================
for lid in NEW:
    for aid in (lid + "." + s for s in FAMILY9):
        assert reg.qualification_ids_for(aid) == [], aid
        assert reg.activities[aid]["grants"] == [], aid
assert sorted(reg.qualifications) == CX.CONQUEST_QUALIFICATIONS, sorted(reg.qualifications)
# qualification_bearing() reports ACTIVITY ids; the four bearers are the Taipei quiz3 gates
BEARERS = sorted(l + ".quiz3" for l in CX.TAIPEI4)
assert sorted(CX.qualification_bearing(reg)) == BEARERS, CX.qualification_bearing(reg)
assert not any(("a2" in q or "b1" in q) for q in reg.qualifications), sorted(reg.qualifications)
ok("6. A2/B1 grant no qualification: the Conquest surface is still exactly the four Taipei gates")

# ============================== 4. one paying gate, no amounts in the registry ==============================
raw = io.open("learning/registry.json", encoding="utf-8", newline="").read()
assert "\r" not in raw, "registry.json must stay LF (Phase 9E.3)"
for lid in NEW:
    # Phase 14A.10B: a gate is identified by the POLICY it declares -- PASS_GOLD is 0 now, so an
    # amount test would find nothing. The invariant is unchanged: quiz3 alone is the gate.
    paying = [s for s in FAMILY9
              if reg.reward_policy_of(lid + "." + s) == "standard_activity_pass"]
    assert paying == ["quiz3"], (lid, paying)
    assert reg.reward_policy_of(lid + ".quiz3") == CX.GATE_POLICY, lid
    assert svc.reward_for(lid + ".quiz3")["amount"] == GC.PASS_GOLD, lid
assert not re.search(r'"(amount|gold|goldAmount|reward)"\s*:\s*\d', raw), "registry names an AMOUNT"
ok("7. exactly one paying gate per lesson (quiz3 -> %s = %d gold), and the registry names policies "
   "but never amounts" % (CX.GATE_POLICY, GC.PASS_GOLD))

# mastery pays MASTERY_GOLD once; the full lesson is worth PASS_GOLD + MASTERY_GOLD
from learning import qualifications as Q, reward_ledger as LG


def master(lid, now=2000):
    st = {}
    cp = reg.lesson(lid)["contentPath"]
    key = json.load(io.open(cp + ".json", encoding="utf-8"))
    res, err = svc.grade_attempt(lid + ".quiz3",
                                [{"q": i["q"], "answer": i["answer"]} for i in key["quiz3"]])
    assert not err, err
    st, gate = svc.record_attempt(st, lid + ".quiz3", res, now - 500)
    for aid in reg.completion_policy_of(lid)["requiredActivityIds"]:
        if svc.is_matching(aid):
            st.setdefault("matchingProgress", {})[aid] = {"correct": 10, "total": 10, "pct": 100}
        elif svc.is_read_along(aid):
            st.setdefault("sttProgress", {})[aid] = {"pct": 100}
        else:
            Q.record_activity_score(st, aid, 10, 10, 100, now)
            Q.record_completion(st, svc.completion_key(aid), passed_at=now, pct=100, rewarded=True)
    out = {}
    svc._settle_lesson(st, lid, now, out)
    return st, gate, out


for lid in ["english.a2.core.001", "english.a2.core.012", "english.b1.core.001", "english.b1.core.005"]:
    st, gate, out = master(lid)
    assert svc.evaluate_lesson(lid, st)["completed"] is True, lid
    assert gate["rewardAmount"] == GC.PASS_GOLD, (lid, gate)
    assert out["lessonRewardAmount"] == GC.MASTERY_GOLD, (lid, out)
    assert LG.total_granted(st, "gold") == GC.PASS_GOLD + GC.MASTERY_GOLD, lid
    assert not st.get("qualifications"), (lid, st.get("qualifications"))
    again = {}
    svc._settle_lesson(st, lid, 9000, again)
    assert again.get("lessonRewardAmount", 0) == 0, (lid, again)
ok("8. mastering the five required activities pays %d + %d = %d gold exactly once, replay pays 0, "
   "and no qualification is granted" % (GC.PASS_GOLD, GC.MASTERY_GOLD, GC.PASS_GOLD + GC.MASTERY_GOLD))

# ============================== 5. content parity ==============================
CONTENT_KEY = {"quiz3": "quiz3", "quiz4": "quiz4", "wh": "wh", "cloze": "cloze",
               "matching": "vocab", "reorder": "reorder", "dictation": "dictation"}
man = json.load(io.open("lessons.json", encoding="utf-8"))
mtitle = {a["file"]: a["title"] for lv in man["levels"] for a in lv["articles"]}
STOP = {"the", "and", "for", "with", "our", "his", "her", "was", "are"}
for lid in NEW:
    cp = reg.lesson(lid)["contentPath"]
    assert os.path.isfile(cp) and os.path.isfile(cp + ".json"), cp
    src = json.load(io.open(cp + ".json", encoding="utf-8"))
    for suf, key in CONTENT_KEY.items():
        assert reg.activities[lid + "." + suf]["contentKey"] == key, (lid, suf)
        assert src.get(key), (lid, key)                      # non-empty on disk
    assert svc.read_along_sentences(lid + ".read_along"), lid
    graph, _ = svc.roleplay_graph(lid + ".roleplay")
    assert graph, lid
    # title evidence: at least one title word (>=3 letters, stemmed to 4 chars) occurs in the content
    body = (io.open(cp, encoding="utf-8").read() + json.dumps(src, ensure_ascii=False)).lower()
    tail = mtitle[cp].split("·")[-1].strip()
    assert tail and tail in reg.lesson(lid)["title"], (lid, tail, reg.lesson(lid)["title"])
    words = [w for w in re.findall(r"[A-Za-z]{3,}", tail) if w.lower() not in STOP]
    assert any(w.lower()[:4] in body for w in words), (lid, tail)
ok("9. all 17 lessons resolve to real on-disk content for every catalogued activity, and each title "
   "is evidenced by its own content")

# ============================== 6. existing families untouched ==============================
CX.assert_completion_model(reg)
gates, completable = CX.assert_reward_model(reg, svc, GC.PASS_GOLD)
for lid in CX.TAIPEI4:
    assert len(required_of(lid)) == 7, lid
for lid in (l for l in reg.lessons if reg.lesson(l)["courseId"] == "english.prea1.core"):
    assert len(required_of(lid)) == 7, lid
    assert "reorder" not in types_of(lid) and "dictation" not in types_of(lid), lid
for lid in (l for l in reg.lessons if reg.lesson(l)["courseId"] == "english.a1.core"):
    assert len(types_of(lid)) == 9 and required_of(lid) == REQUIRED5, lid
assert len(completable) == len(reg.lessons) == len(gates), (len(completable), len(gates))
ok("10. Pre-A1/Taipei still require 7 with no reorder/dictation, A1 still offers 9 and requires 5, "
   "and all %d registry lessons remain completable and gated" % len(reg.lessons))

print("\nAll %d A2/B1 migration tests passed." % passed)
