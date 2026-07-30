#!/usr/bin/env python3
"""Phase 3A — learning-qualification attack gate: pure rule + end-to-end HTTP vertical slice.

    python3 tests/learning_gate_test.py

Part 1 exercises game.conquest.can_attack's qualification layer in isolation (opaque IDs, ordering
vs the other eligibility checks, AI bypass). Part 2 drives the REAL Taipei vertical slice over HTTP:
locked taipei:daan vs unrestricted taipei:xinyi, server-graded quiz3, one-time PASS_GOLD, unlock.
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

# no qualifications at all -> blocked, and the response names every missing id (in requirement order)
e = elig("m:gated")
assert not e and e.reason == "qualification_required", (e.allowed, e.reason)
assert e.missing_qualifications == ["biology.cell.unit03", "chem.atoms.unit01"], e.missing_qualifications
# PARTIAL qualification is still blocked, and only the genuinely missing id is reported
e = elig("m:gated", {"biology.cell.unit03"})
assert not e and e.missing_qualifications == ["chem.atoms.unit01"], e.missing_qualifications
# holding ALL required ids -> allowed; extra unrelated ids are harmless
assert elig("m:gated", {"biology.cell.unit03", "chem.atoms.unit01"}).allowed
assert elig("m:gated", {"biology.cell.unit03", "chem.atoms.unit01", "unrelated.x"}).allowed
# a territory with NO requirements is unrestricted for a player holding nothing
e_open = elig("m:open")
assert e_open.allowed and e_open.reason is None and e_open.missing_qualifications == []
ok("gate: blocks with none/partial, allows with all, unrestricted target needs nothing, ids are opaque")

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
assert "qualification_required" in conquest.AttackEligibility.REASONS
ok("gate robustness: a raising attack_requirements degrades to unrestricted, reason string is stable")

# real catalog wiring: the designer-owned Taipei requirement is actually readable by the Game Domain
import territory_catalog  # noqa: E402
_cat = territory_catalog.catalog
assert _cat.attack_requirements("taipei:daan") == ["english.prea1.taipei.zoo"], _cat.attack_requirements("taipei:daan")
assert _cat.attack_requirements("taipei:xinyi") == [], "the comparison target carries no learning requirement"
assert _cat.attack_requirements("taipei:wenshan") == [] and _cat.attack_requirements("nope:nope") == []
ok("catalog: taipei:daan requires the slice qualification, taipei:xinyi/unknown ids are unrestricted")


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
    """ALICE holds taipei:wenshan; BOB holds the gated daan and the ungated xinyi (side-by-side test)."""
    server.set_room(CODE)
    server.save_catalog({"taipei:wenshan": 100, "taipei:daan": 100, "taipei:xinyi": 100})
    server.save_territory_store({
        "taipei:wenshan": {"owner": owner, "avatar": "\U0001F466", "troops": [{"type": "cav", "hp": 300}], "pop": 100},
        "taipei:daan": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100},
        "taipei:xinyi": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100},
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

# --- LOCKED: no qualification -> attack on taipei:daan refused, nothing changes ---
slice_state()
g0 = gold()
code, body = atk("taipei:daan")
assert code == 403 and body["reason"] == "qualification_required", (code, body)
assert body["missingQualificationIds"] == [QID], body
assert owner_of("taipei:daan") == "BOB" and gold() == g0, "a refused attack is atomic: no owner, no gold change"
server.set_room(CODE)
assert server.load_territory_store()["taipei:wenshan"]["troops"][0]["hp"] == 300, "source garrison untouched"
ok("E2E locked: taipei:daan -> 403 qualification_required + missing ids, zero state change")

# --- SIDE-BY-SIDE control: the ungated neighbour is conquerable with the same (empty) learning state ---
code, body = atk("taipei:xinyi")
assert code == 200 and body["attackerWon"] is True and owner_of("taipei:xinyi") == "ALICE", (code, body)
ok("E2E control: taipei:xinyi (no requirement) conquers normally — the gate is targeted, not global")

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
assert atk("taipei:daan")[0] == 403, "still locked after a failed attempt"
ok("E2E forge-proof: client-sent passed/pct/qualification/gold ignored — server grading decides")

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
# §8: higher-level blocks are NOT invented — nothing claims lesson/unit/course completion yet
assert set(st) == {"qualifications", "activityCompletions"}, st.keys()
ok("E2E persistence: activityCompletions['<activityId>'] + qualifications['<id>'], no faked aggregates")

# --- UNLOCK: the same attack that was 403 now succeeds ---
code, body = atk("taipei:daan")
assert code == 200 and body["attackerWon"] is True, (code, body)
assert owner_of("taipei:daan") == "ALICE", "the gated territory is conquered after the verified pass"
ok("E2E UNLOCK: locked taipei:daan -> pass quiz3 -> same attack now conquers (end-to-end)")

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
for bad in ({"lessonId": LESSON, "activity": "match", "answers": []},          # real lesson, unregistered activity
            {"lessonId": LESSON, "activity": "wh", "answers": []},
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

# --- RETIRED: /api/economy/pass still counts occupy-unlock passes but can no longer mint Gold ---
slice_state()
g0 = gold()
code, body = call("POST", "/api/economy/pass?room=" + CODE, "tALICE", {"file": "Pre-A1/taipei/zoo"})
assert code == 200 and body["ok"] is True and body["count"] == 1 and body.get("legacy") is True, body
assert "gold" not in body, "the retired endpoint must not even report a gold balance as a reward"
assert gold() == g0, "the client-asserted pass endpoint mints NO gold"
for f in ("anything/at/all", "made/up/lesson", "Pre-A1/taipei/zoo"):
    call("POST", "/api/economy/pass?room=" + CODE, "tALICE", {"file": f})
assert gold() == g0, "the old unlimited-gold exploit is closed for arbitrary lesson ids too"
server.set_room(CODE)
assert server.load_econ_store()["ALICE"]["passcnt"]["Pre-A1/taipei/zoo"] == 2, "occupy passcount still recorded"
assert call("GET", "/api/learning/state?room=" + CODE, "tALICE")[1]["qualifications"].keys() == {QID}, \
    "the retired endpoint can never grant a qualification"
ok("E2E retired: /api/economy/pass keeps passcnt, mints 0 gold, grants 0 qualifications")

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
