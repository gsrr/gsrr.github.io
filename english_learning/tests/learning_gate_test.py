#!/usr/bin/env python3
"""Phase 3A — learning-qualification attack gate: pure rule + end-to-end HTTP vertical slice.

    python3 tests/learning_gate_test.py

Part 1 exercises game.conquest.can_attack's qualification layer in isolation (opaque IDs, ordering
vs the other eligibility checks, AI bypass). Part 2 drives the REAL Taipei vertical slice over HTTP:
locked taipei:daan vs unrestricted taipei:nangang, server-graded quiz3, one-time PASS_GOLD, unlock.
"""
import json
import os
import sys
import time
import threading
import tempfile
import urllib.request as U
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from game import conquest  # noqa: E402
import server  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ==================== Part 1 — pure can_attack qualification gate ====================
# A minimal fake World Domain. Note the requirement ids here are deliberately NOT English-course ids:
# the Game Domain must treat them as fully opaque strings.
class FakeWorld:
    def __init__(self, adjacency, requirements):
        self.adjacency, self.requirements = adjacency, requirements

    def is_canonical(self, tid):
        return tid in self.adjacency

    def map_of(self, tid):
        return "m" if tid in self.adjacency else None

    def are_adjacent(self, a, b):
        return b in self.adjacency.get(a, ())

    def attack_requirements(self, tid):
        return list(self.requirements.get(tid, ()))


WORLD = FakeWorld(
    {"m:home": ("m:gated", "m:open"), "m:gated": ("m:home",), "m:open": ("m:home",), "m:far": ()},
    # opaque, non-English requirement ids; m:far is gated AND unreachable (ordering probe)
    {"m:gated": ["biology.cell.unit03", "chem.atoms.unit01"], "m:far": ["biology.cell.unit03"]},
)
STORE = {
    "m:home": {"owner": "ALICE", "troops": [{"type": "cav", "hp": 100}]},
    "m:gated": {"owner": "BOB", "troops": [{"type": "inf", "hp": 5}]},
    "m:open": {"owner": "BOB", "troops": [{"type": "inf", "hp": 5}]},
    "m:far": {"owner": "BOB", "troops": [{"type": "inf", "hp": 5}]},
}
SQUAD = [{"type": "cav", "hp": 10}]


def elig(target, quals=None, require=True, source="m:home", squad=SQUAD):
    return conquest.can_attack("ALICE", source, target, squad, WORLD, STORE,
                               player_qualifications=quals, require_qualifications=require)

# RETARGETED (Phase 10A.3R).
#   OLD: a requirement-carrying target blocked with none/partial qualifications, named every missing
#        id in requirement order, and allowed once ALL were held.
#   WHY OBSOLETE: Learning has zero Conquest authority. A target's declared requirements are no
#        longer consulted, so none of those verdicts can occur.
#   NEW: a requirement-carrying target and a requirement-free one behave IDENTICALLY, and holding
#        none / some / all / unrelated qualifications makes no difference to either.
#   WHY NOT WEAKER: the old form pinned one gate's shape; this pins that the requirement metadata and
#        the player's qualifications are both inert for Conquest — the property that keeps them apart.
SETS = [None, {"biology.cell.unit03"}, {"biology.cell.unit03", "chem.atoms.unit01"},
        {"biology.cell.unit03", "chem.atoms.unit01", "unrelated.x"}]
for target in ("m:gated", "m:open"):
    verdicts = {(elig(target, q).allowed, elig(target, q).reason) for q in SETS}
    assert len(verdicts) == 1, (target, verdicts)
    assert next(iter(verdicts))[0] is True, (target, verdicts)
    assert elig(target).missing_qualifications == [], target
ok("gate retired: a requirement-carrying target and a requirement-free one behave identically, and "
   "none/partial/all/unrelated qualifications never change the verdict")

# the gate is the LAST check — it never masks (or is masked by) the structural rules
assert elig("m:gated", None, True, source="m:nope").reason == "source_not_found"
assert elig("m:far").reason == "not_adjacent", "adjacency is decided before the learning gate"
assert elig("m:gated", None, True, squad=[]).reason == "invalid_squad"
assert elig("m:gated", None, True, squad=[{"type": "cav", "hp": 9999}]).reason == "insufficient_source_garrison", \
    "an unaffordable squad fails on garrison, not on qualifications"
assert conquest.can_attack("CAROL", "m:home", "m:gated", SQUAD, WORLD, STORE).reason == "source_not_owned"
ok("gate ordering: source/target/adjacency/squad/garrison all still decided BEFORE the learning gate")

# AI policy: require_qualifications=False bypasses ONLY this layer, never the structural rules
assert elig("m:gated", None, require=False).allowed, "AI bypasses the human-learning gate"
assert not elig("m:far", None, require=False).allowed, "AI still bound by adjacency"
assert elig("m:far", None, require=False).reason == "not_adjacent"
assert conquest.can_attack("CAROL", "m:home", "m:open", SQUAD, WORLD, STORE,
                           require_qualifications=False).reason == "source_not_owned", \
    "AI bypass never grants ownership"
assert elig("m:gated", None, False, squad=[{"type": "cav", "hp": 9999}]).reason == "insufficient_source_garrison", \
    "AI bypass never conjures garrison"
ok("AI policy: qualification bypass only — ownership / adjacency / garrison still enforced")

# a world object that cannot answer attack_requirements must fail OPEN (never 500 the attack path)
class BrokenWorld(FakeWorld):
    def attack_requirements(self, tid):
        raise RuntimeError("world-data unavailable")


assert conquest.can_attack("ALICE", "m:home", "m:open", SQUAD, BrokenWorld(WORLD.adjacency, {}), STORE).allowed
assert "qualification_required" not in conquest.AttackEligibility.REASONS,     "the retired learning gate must not reappear as an eligibility reason"
ok("robustness: a raising attack_requirements is harmless because requirements are never consulted, "
   "and qualification_required is no longer a possible reason")

# real catalog wiring: the designer-owned Taipei requirement is actually readable by the Game Domain
import territory_catalog  # noqa: E402
_cat = territory_catalog.catalog
assert _cat.attack_requirements("taipei:daan") == ["english.prea1.taipei.zoo"], _cat.attack_requirements("taipei:daan")
assert _cat.attack_requirements("taipei:nangang") == [], "the comparison target carries no requirement"
# Phase 4A gated Xinyi with the MRT qualification, so Nangang is now the ungated control.
assert _cat.attack_requirements("taipei:xinyi") == ["english.prea1.taipei.mrt.quiz3.pass"]
assert _cat.attack_requirements("taipei:wenshan") == [] and _cat.attack_requirements("nope:nope") == []
ok("catalog: taipei:daan requires the slice qualification, taipei:nangang/unknown ids are unrestricted")


# ==================== Part 2 — end-to-end HTTP vertical slice ====================
d = tempfile.mkdtemp()
server.ROOMS_DIR = os.path.join(d, "rooms")
server.ACCT = os.path.join(d, "accounts.json")
server.PROG_DIR = os.path.join(d, "progress")
server.DATA = os.path.join(d, "visits.json")
server.TERR_CATALOG = os.path.join(d, "learned.json")
server.CONTENT_ROOT = ROOT                     # authoritative lesson JSON lives in the repo root
server.LEARNING.content_root = ROOT            # (the service captured it at construction)
os.makedirs(d, exist_ok=True)
json.dump({"users": {"ALICE": {"code": "LRNAAA"}, "BOB": {}}, "codes": {"LRNAAA": "ALICE"}}, open(server.ACCT, "w"))
for u in ("ALICE", "BOB"):
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
from http.server import ThreadingHTTPServer  # noqa: E402
srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % port


def call(method, path, tok, body=None):
    url = B + path + ("&" if "?" in path else "?") + "token=" + tok
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = U.urlopen(U.Request(url, data=data, method=method))
        return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


call("POST", "/api/room/create", "tALICE", {})
CODE = call("POST", "/api/room/start", "tALICE",
            {"map": "Pre-A1", "aiCount": 0, "resources": "medium", "capacity": 4})[1]["code"]
now = time.time()
LESSON, ACT, QID = "Pre-A1/taipei/zoo", "quiz3", "english.prea1.taipei.zoo"   # LESSON = content path
AID = "english.prea1.taipei.zoo.quiz3"          # Phase 3B canonical activity id
LEGACY_KEY = LESSON + "#" + ACT                 # Phase 3A completion key (must stay resolvable)
KEY = json.load(open(os.path.join(ROOT, LESSON + ".json"), encoding="utf-8"))[ACT]
RIGHT = [{"q": it["q"], "answer": it["answer"]} for it in KEY]
WRONG = [{"q": it["q"], "answer": ("No" if it["answer"] == "Yes" else "Yes")} for it in KEY]


def slice_state(owner="ALICE"):
    """ALICE holds taipei:wenshan; BOB holds the gated daan and the ungated nangang (side-by-side)."""
    server.set_room(CODE)
    server.save_catalog({"taipei:wenshan": 100, "taipei:daan": 100, "taipei:nangang": 100})
    server.save_territory_store({
        "taipei:wenshan": {"owner": owner, "avatar": "\U0001F466", "troops": [{"type": "cav", "hp": 300}], "pop": 100},
        "taipei:daan": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100},
        "taipei:nangang": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100},
    })
    es = server.load_econ_store()
    for u in (owner, "BOB", server.AI_OWNER):
        es.setdefault(u, {"population": 100, "gold": 0, "lastGold": now,
                          "troops": {"cav": 0, "archer": 0, "inf": 0, "spear": 0},
                          "buildings": {}, "tech": {}, "passcnt": {}})
        es[u]["lastGold"] = now
    server.save_econ_store(es)


def atk(target, source="taipei:wenshan", hp=100):
    return call("POST", "/api/territory/attack?room=" + CODE, "tALICE",
                {"sourceTerritoryId": source, "targetTerritoryId": target,
                 "squad": [{"type": "cav", "hp": hp}]})


def owner_of(tid):
    server.set_room(CODE)
    return (server.load_territory_store().get(tid) or {}).get("owner")


def gold():
    server.set_room(CODE)
    return server.load_econ_store()["ALICE"]["gold"]


def attempt(answers, extra=None):
    """Phase 3B canonical request: activity IDENTITY + answers, nothing else."""
    body = {"activityId": AID, "answers": answers}
    if extra:
        body.update(extra)
    return call("POST", "/api/learning/attempt?room=" + CODE, "tALICE", body)


def attempt_legacy(answers):
    """Phase 3A-shaped request (content path + activity key) — normalized inside the Learning Domain."""
    return call("POST", "/api/learning/attempt?room=" + CODE, "tALICE",
                {"lessonId": LESSON, "activity": ACT, "answers": answers})


# --- the public registry publishes identity + titles + study targets, never answer keys ---
code, reg = call("GET", "/api/learning/registry", "tALICE")
r = reg["registry"]
assert code == 200 and r["schemaVersion"] == 1
q = r["qualifications"][QID]
assert q["scope"] == "activity" and q["title"], q
assert q["studyTarget"] == {"activityId": AID, "lessonId": "english.prea1.taipei.zoo",
                            "contentPath": LESSON, "title": q["title"]}, q["studyTarget"]
a = r["activities"][AID]
assert a["contentPath"] == LESSON and a["contentKey"] == ACT and a["grants"] == [QID], a
blob = json.dumps(reg)
assert "answer" not in blob and "Tom is sad" not in blob, "the registry must not leak the answer key"
for leak in ("PASS_GOLD", "rewardPolicy", "graderType", "10000"):
    assert leak not in blob, "the public view must not leak reward amounts or grader internals: " + leak
ok("E2E registry: identity + title + studyTarget published; no answer keys, no reward/grader internals")

# --- RETARGETED: the E2E gate is gone; taipei is now a DORMANT map, refused on game grounds ---
#   OLD: attacking taipei:daan with no qualification gave 403 qualification_required + missing ids.
#   WHY OBSOLETE: no learning gate exists, and taipei is not the active conquest map at all.
#   NEW: the request is refused as inactive_map, and the refusal is still atomic.
#   WHY NOT WEAKER: it keeps the atomicity guarantee (no owner change, no gold change, source
#        garrison untouched) and additionally pins the single-active-map rule.
slice_state()
g0 = gold()
code, body = atk("taipei:daan")
assert code == 400 and body["reason"] == "inactive_map", (code, body)
assert "missingQualificationIds" not in body, body
assert owner_of("taipei:daan") == "BOB" and gold() == g0, "a refused attack is atomic: no owner, no gold change"
server.set_room(CODE)
assert server.load_territory_store()["taipei:wenshan"]["troops"][0]["hp"] == 300, "source garrison untouched"
ok("E2E: a dormant-map attack is refused inactive_map with no qualification vocabulary, and the "
   "refusal remains atomic")

# --- RETARGETED control: the refusal is about the MAP, not about any territory's requirements ---
#   OLD: the ungated neighbour taipei:nangang conquered normally, proving the gate was targeted rather
#        than global.
#   WHY OBSOLETE: there is no gate to be targeted, and taipei is dormant, so nothing on that map is
#        conquerable regardless of requirements.
#   NEW: the formerly GATED and formerly UNGATED taipei territories are refused identically.
#   WHY NOT WEAKER: it proves the refusal is a property of the active-map rule alone and cannot be
#        confused with a per-territory learning requirement — the distinction the old control drew.
code_gated, body_gated = atk("taipei:daan")
code_open, body_open = atk("taipei:nangang")
assert (code_gated, body_gated["reason"]) == (code_open, body_open["reason"]) == (400, "inactive_map"),     (code_gated, body_gated, code_open, body_open)
assert owner_of("taipei:nangang") != "ALICE", "a refused attack must not transfer ownership"
ok("E2E control: the formerly gated and formerly ungated taipei territories are refused identically "
   "as inactive_map — the rule is the active map, never a learning requirement")

# --- FAILED attempt: server grading rejects it, and forged passed/score/qualification are ignored ---
slice_state()
g0 = gold()
code, body = attempt(WRONG, {"passed": True, "pct": 100, "score": 100, "correct": 5, "total": 5,
                             "qualification": QID, "qualifications": [QID], "gold": 999999,
                             "rewardGold": 999999, "rewardPolicy": "standard_activity_pass",
                             "rewarded": True, "graderType": "yes_no"})
assert code == 200 and body["passed"] is False and body["pct"] == 0, (code, body)
assert body["qualification"] is None and body["qualifications"] == [] and body["grantedNow"] is False
assert body["rewarded"] is False and body["activityId"] == AID
assert gold() == g0, "a failed attempt mints no gold, even when the client claims passed=true"
assert call("GET", "/api/learning/state?room=" + CODE, "tALICE")[1]["qualifications"] == {}
# RETARGETED (Phase 10A.3R): the old line asserted the territory was "still locked" because the
# failed attempt granted no qualification. There is no lock to be still-locked: Conquest never reads
# learning state. What remains true and worth pinning is that the FAILED attempt changed no Conquest
# verdict at all — the refusal is the active-map rule, before and after, identically.
_before_fail = atk("taipei:daan")
assert (_before_fail[0], _before_fail[1].get("reason")) == (400, "inactive_map"), _before_fail
ok("E2E forge-proof: client-sent passed/pct/qualification/gold ignored — server grading decides, and "
   "the failed attempt leaves the Conquest verdict untouched")

# --- PASSING attempt: qualification granted + one-time PASS_GOLD ---
g0 = gold()
code, body = attempt(RIGHT)
assert code == 200 and body["passed"] is True and body["pct"] == 100, (code, body)
assert body["qualification"] == QID and body["qualifications"] == [QID]
assert body["grantedNow"] is True and body["grantedNowIds"] == [QID] and body["alreadyCompleted"] is False
assert body["rewarded"] is True and body["gold"] == g0 + server.PASS_GOLD, (g0, body)
assert gold() == g0 + server.PASS_GOLD, "PASS_GOLD amount unchanged, granted on the verified event"
ok("E2E pass: server re-grades 100%, grants the qualification, pays PASS_GOLD once")

# --- §13 LEGACY REQUEST SHAPE: a Phase 3A client (contentPath + activity) hits the SAME code path ---
g_leg = gold()
code, body = attempt_legacy(RIGHT)
assert code == 200 and body["passed"] is True and body["activityId"] == AID, (code, body)
assert body["rewarded"] is False and gold() == g_leg, \
    "the legacy request shape normalizes to the same canonical activity — no second reward"
ok("E2E legacy request: lessonId+activity normalizes to the canonical activityId (one grading path)")

# --- IDEMPOTENT: replaying the same passing attempt pays nothing and does not re-date the grant ---
g1 = gold()
st_before = call("GET", "/api/learning/state?room=" + CODE, "tALICE")[1]
code, body = attempt(RIGHT)
assert code == 200 and body["passed"] is True, body
assert body["grantedNow"] is False and body["alreadyCompleted"] is True and body["rewarded"] is False
assert body["gold"] is None and gold() == g1, "replaying a completed activity is worth 0 gold"
st_after = call("GET", "/api/learning/state?room=" + CODE, "tALICE")[1]
assert st_after["qualifications"][QID]["earnedAt"] == st_before["qualifications"][QID]["earnedAt"]
assert st_after["activityCompletions"][AID]["passedAt"] == \
    st_before["activityCompletions"][AID]["passedAt"], "passedAt is first-pass, not last-pass"
for _ in range(3):
    attempt(RIGHT)
assert gold() == g1, "gold cannot be farmed by replaying the verified endpoint"
ok("E2E idempotent: replays grant no gold, earnedAt/passedAt frozen at the first pass")

# --- persistence shape: activity-scoped completion, separate from the qualification ledger ---
st = call("GET", "/api/learning/state?room=" + CODE, "tALICE")[1]
rec = st["activityCompletions"][AID]
assert sorted(rec) == ["passedAt", "pct", "rewarded"] and rec["pct"] == 100 and rec["rewarded"] is True
assert isinstance(rec["passedAt"], int) and rec["passedAt"] > 0
assert sorted(st["qualifications"][QID]) == ["earnedAt"]
for not_a_key in ("english.prea1.taipei.zoo", LESSON, "english.prea1.taipei"):
    assert not_a_key not in st["activityCompletions"], \
        "completion is keyed by ACTIVITY id, never by lesson/course/content path: " + not_a_key
# §8: higher-level blocks are NOT invented. Phase 3D added authoritative LESSON completion, but no
# production lesson declares a completionPolicy, so the block must stay empty — and unit/course
# completion still does not exist at all.
# Phase 12B.2 adds exactly ONE key to this surface: readAlongMode, the input mode the server
# permits for THIS account. It is here because the learner's own page must know which control to
# draw. It carries no reason, no actor and no other account's state -- there is nothing else to
# carry, because nothing else is stored.
assert set(st) == {"qualifications", "activityCompletions", "lessonCompletions",
                   "lessonCompletionHistory", "sttProgress", "matchingProgress",
                   "roleplayProgress", "rewardLedger", "activityScores",
                   "readAlongMode"}, st.keys()
assert st["readAlongMode"] == "speech", "an account with no accommodation reads as speech"
for leak in ("readAlongModeBy", "readAlongModeAt", "reason", "joinedClass", "salt", "hash"):
    assert leak not in st, "the learning state must not expose " + leak
# Phase 5E: the ledger mirrors what was actually paid — activity passes only. No lesson or
# campaign reward exists in production, so nothing else can appear here.
assert sorted(e["scope"] for e in st["rewardLedger"].values()) == ["activity"], st["rewardLedger"]
assert all(e["policyId"] == "standard_activity_pass" and e["itemId"] is None
           for e in st["rewardLedger"].values()), st["rewardLedger"]
assert "roleplaySessions" not in st, "in-flight Role-play session state is never exposed"
assert st["lessonCompletions"] == {}, "no production lesson can be authoritatively complete yet"
assert st["sttProgress"] == {}, "this player has recorded no Read-Along evidence"
assert st["matchingProgress"] == {}, "this player has played no matching round"
assert "unitCompletions" not in st and "courseCompletions" not in st
ok("E2E persistence: activityCompletions['<activityId>'] + qualifications['<id>'], no faked aggregates")

# --- RETARGETED: earning the qualification unlocks NOTHING ---
#   OLD: the same attack that was 403 now succeeded, proving pass -> unlock end-to-end.
#   WHY OBSOLETE: Learning has zero Conquest authority, so a verified pass cannot open ground. The
#        qualification is still granted and asserted above; it is simply an achievement now.
#   NEW: after the verified pass, the very same attack returns the very same verdict as before it.
#   WHY NOT WEAKER: the old form proved one unlock path worked; this proves no learning success can
#        change Conquest eligibility — the property that keeps the systems separate.
code, body = atk("taipei:daan")
assert (code, body.get("reason")) == (_before_fail[0], _before_fail[1].get("reason")),     (code, body, _before_fail)
assert owner_of("taipei:daan") != "ALICE", "a verified learning pass must not hand over territory"
assert call("GET", "/api/learning/state?room=" + CODE, "tALICE")[1]["qualifications"].get(QID),     "the qualification IS earned and recorded — it just has no Conquest effect"
ok("E2E: a verified quiz3 pass grants the qualification but leaves the Conquest verdict IDENTICAL — "
   "earning unlocks no ground")

# --- qualification is PLAYER state: it survives losing every territory, and is room-independent ---
server.set_room(CODE)
server.save_territory_store({})                     # ALICE now owns nothing at all
assert call("GET", "/api/learning/state?room=" + CODE, "tALICE")[1]["qualifications"].get(QID), \
    "qualifications are account state, not territory/room state"
assert call("GET", "/api/learning/state?room=OTHER", "tALICE")[1]["qualifications"].get(QID)
assert call("GET", "/api/learning/state?room=" + CODE, "tBOB")[1]["qualifications"] == {}, \
    "one player's qualification never leaks to another"
ok("E2E scope: qualification is per-account (survives total defeat, crosses rooms, not shared)")

# --- only registry-whitelisted, gradable activities are accepted; ids cannot escape CONTENT_ROOT ---
for bad in ({"lessonId": LESSON, "activity": "vocab", "answers": []},   # real lesson, UNREGISTERED activity
            {"lessonId": LESSON, "activity": "match", "answers": []},   # matching stays unmigrated (cat. B)
            {"lessonId": "A2/space/mars", "activity": "quiz3", "answers": []},  # unregistered lesson
            {"lessonId": "../server", "activity": "quiz3", "answers": []},      # traversal via legacy shape
            {"lessonId": "../../etc/passwd", "activity": "quiz3", "answers": []},
            {"lessonId": "", "activity": "quiz3", "answers": []},
            {"activityId": "made.up.activity", "answers": []},                  # traversal/forgery via 3B shape
            {"activityId": AID + ".bogus", "answers": []},
            {"activityId": "english.prea1.taipei.zoo", "answers": []},          # a LESSON id is not an activity
            {"activityId": "../../etc/passwd", "answers": []},
            {"activityId": "", "answers": []}):
    c, b = call("POST", "/api/learning/attempt?room=" + CODE, "tALICE", bad)
    assert c == 400 and b["reason"] == "not_gradable", (bad, c, b)
for missing in ({"activityId": AID}, {"activityId": AID, "answers": "Yes"}, {"activityId": AID, "answers": {}}):
    c, b = call("POST", "/api/learning/attempt?room=" + CODE, "tALICE", missing)
    assert c == 400 and b["reason"] == "bad_answers", (missing, c, b)
assert call("POST", "/api/learning/attempt", "bogus-token", {"activityId": AID, "answers": RIGHT})[0] == 401
ok("E2E endpoint hardening: unregistered/ungradable/traversal/bad-answers/anonymous all refused")

# --- §42 BACKWARD COMPATIBILITY: a pre-Phase-3B record is honoured, not rewritten or re-rewarded ---
with server.acct_lock:
    p = server.load_progress("BOB")
    p["learning"] = {"activityCompletions": {LEGACY_KEY: {"passedAt": 1000, "pct": 100, "rewarded": True}},
                     "qualifications": {QID: {"earnedAt": 1000}}}
    server.save_progress("BOB", p)
code, body = call("POST", "/api/learning/attempt?room=" + CODE, "tBOB", {"activityId": AID, "answers": RIGHT})
assert code == 200 and body["passed"] is True, (code, body)
assert body["alreadyCompleted"] is True, "the legacy record proves prior completion"
assert body["rewarded"] is False and body["gold"] is None, "an already-rewarded legacy pass is never paid twice"
assert body["grantedNow"] is False, "the qualification was already held"
st = call("GET", "/api/learning/state?room=" + CODE, "tBOB")[1]
assert st["activityCompletions"][LEGACY_KEY] == {"passedAt": 1000, "pct": 100, "rewarded": True}, \
    "the Phase 3A record is left byte-for-byte intact (non-destructive migration)"
assert st["activityCompletions"][AID]["passedAt"] == 1000, \
    "the canonical record inherits the ORIGINAL passedAt — credit is carried forward, not reset"
assert st["qualifications"][QID]["earnedAt"] == 1000, "earnedAt untouched"
ok("E2E backward compat: Phase 3A completion key still resolves — additive, idempotent, no double reward")

# --- REMOVED (Phase 7F.2): /api/economy/pass is gone, and a legacy passcnt is inert data ---
# The endpoint's last consumer was the client-side Random-Challenge prerequisite, which Phase 7F.2
# retired: an ungated territory is occupied directly, and a gated one needs the qualification the
# server itself verifies. Two properties replace the old "neutered handler" assertions:
#   1. the route no longer exists, for any lesson id, valid or forged;
#   2. legacy `passcnt` already sitting in a saved economy file is ignored IN PLACE — it is not read,
#      not migrated, not converted into gold or a qualification, and not deleted.
slice_state()
g0 = gold()
for f in ("Pre-A1/taipei/zoo", "anything/at/all", "made/up/lesson"):
    code, body = call("POST", "/api/economy/pass?room=" + CODE, "tALICE", {"file": f})
    assert code == 404, "retired route answered %s for %r: %s" % (code, f, body)
    assert "gold" not in body and "count" not in body, body
assert gold() == g0, "a route that does not exist cannot mint gold for any lesson id"

# A pre-7F.2 save file: real ids, forged ids, and hostile value types side by side.
server.set_room(CODE)
with server.econ_lock:
    st = server.load_econ_store()
    st.setdefault("ALICE", {})["passcnt"] = {"Pre-A1/001": 5, "made/up": 999,
                                            "Pre-A1/taipei/zoo": "not-a-number", "": 1}
    server.save_econ_store(st)
code, econ = call("GET", "/api/economy?room=" + CODE, "tALICE")
assert code == 200, (code, econ)
assert "passcnt" not in econ, "the retired counter must not be served to the client any more"
assert econ["gold"] == g0, "loading a legacy passcnt mints nothing"
server.set_room(CODE)
saved = server.load_econ_store()["ALICE"]
assert saved["passcnt"] == {"Pre-A1/001": 5, "made/up": 999,
                            "Pre-A1/taipei/zoo": "not-a-number", "": 1}, \
    "legacy passcnt is left byte-identical — no normalisation, no migration, no destructive cleanup"
assert call("GET", "/api/learning/state?room=" + CODE, "tALICE")[1]["qualifications"].keys() == {QID}, \
    "a legacy counter can never grant a qualification"
ok("E2E removed: /api/economy/pass 404s for every lesson id, and a legacy passcnt (including forged "
   "ids and non-numeric values) loads cleanly, is never served, and mints no gold or qualification")

# --- AI POLICY over HTTP: the AI conquers the gated territory (it holds no qualifications) ---
server.set_room(CODE)
server.save_catalog({"taipei:wenshan": 100, "taipei:daan": 100})
server.save_territory_store({
    "taipei:wenshan": {"owner": server.AI_OWNER, "avatar": "\U0001F916",
                       "troops": [{"type": "cav", "hp": 300}], "pop": 100},
    "taipei:daan": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100},
})
server.ai_move()                                    # only legal action: attack the gated daan from wenshan
assert owner_of("taipei:daan") == server.AI_OWNER, "AI is not blocked by the human-learning gate"
server.set_room(CODE)
ts = server.load_territory_store()
src_hp = sum(int(t.get("hp", 0) or 0) for t in (ts["taipei:wenshan"]["troops"] or []))
assert src_hp < 300 and sum(int(t.get("hp", 0) or 0) for t in (ts["taipei:daan"]["troops"] or [])) > 0, \
    "AI still committed real troops from its own adjacent source garrison, survivors garrison the target"
ok("E2E AI: bypasses only the learning gate — same source/adjacency/garrison/battle rules as a human")

srv.shutdown()
print("\nAll %d learning-gate tests passed." % passed)
