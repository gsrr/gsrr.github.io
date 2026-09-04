#!/usr/bin/env python3
"""Phase 8F.3 — battle gold is paid to HUMANS ONLY, and room AIs are identified by the room roster.

    python3 tests/battle_economy_test.py

Phase 8F.2 concluded "a human loss against an AI destroys the 50". That conclusion was drawn from a
fixture that staged the AI with owner == server.AI_OWNER ("AI Empire"). Real rooms never use that
name: /api/room/start rosters its AIs as "AI 1".."AI 7" and ai_loop drives them by that name, so the
old `defender != AI_OWNER` guard let every real room AI collect DEFEND_GOLD. These tests therefore
build their AI fixture from the roster the running server actually created — never from AI_OWNER
alone — so the same fixture mistake cannot hide the defect again.
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
from game import config as game_cfg  # noqa: E402
import server  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


d = tempfile.mkdtemp()
server.ROOMS_DIR = os.path.join(d, "rooms")
server.ACCT = os.path.join(d, "accounts.json")
server.PROG_DIR = os.path.join(d, "progress")
server.DATA = os.path.join(d, "visits.json")
server.TERR_CATALOG = os.path.join(d, "learned.json")
os.makedirs(d, exist_ok=True)
json.dump({"users": {"ALICE": {"code": "ATKAAA"}, "BOB": {}}, "codes": {"ATKAAA": "ALICE"}},
          open(server.ACCT, "w"))
for u in ("ALICE", "BOB"):
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
from http.server import ThreadingHTTPServer  # noqa: E402
srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % srv.server_address[1]

DEFEND = game_cfg.DEFEND_GOLD
FAIL = game_cfg.ATTACK_FAIL_GOLD
SRC, TGT = "world:cn", "world:ru"          # adjacent pair on the A1 map


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
            {"map": "A1", "aiCount": 2, "resources": "medium", "capacity": 4})[1]["code"]
call("POST", "/api/room/create", "tBOB", {})       # a SECOND host -> a genuinely separate room
OTHER = call("POST", "/api/room/start", "tBOB",
             {"map": "A1", "aiCount": 1, "resources": "medium", "capacity": 4})[1]["code"]
assert OTHER != CODE, "the isolation fixture needs two distinct rooms"

# The AI fixture comes from the ROOM ROSTER the server just built — not from AI_OWNER.
server.set_room(CODE)
ROSTER = sorted(server.room_ai_names())
AI1 = ROSTER[0]
assert ROSTER == ["AI 1", "AI 2"], ROSTER
assert AI1 != server.AI_OWNER, "the roster name must differ from the legacy default, or this test proves nothing"
ok("room roster AIs are %s; server.AI_OWNER (%r) is NOT one of them" % (ROSTER, server.AI_OWNER))


def purses(code=CODE):
    server.set_room(code)
    return {k: int((v or {}).get("gold", 0)) for k, v in server.load_econ_store().items()}


def stage(target_owner, src_troops, tgt_troops, code=CODE, alice_gold=500):
    """Put ALICE on SRC and `target_owner` on TGT, with known purses everywhere."""
    server.set_room(code)
    server.save_catalog({SRC: 100, TGT: 100})     # both known+owned -> AI has no neutral to occupy
    server.save_territory_store({
        SRC: {"owner": "ALICE", "troops": list(src_troops), "pop": 100},
        TGT: {"owner": target_owner, "troops": list(tgt_troops), "pop": 100},
    })
    es = server.load_econ_store()
    for who, gold in (("ALICE", alice_gold), ("BOB", 0), (AI1, 0), (ROSTER[1], 0),
                      (server.AI_OWNER, 0)):
        es[who] = {"population": 100, "gold": gold, "lastGold": time.time(),
                   "troops": {"cav": 0, "archer": 0, "inf": 0, "spear": 0},
                   "buildings": {}, "tech": {}, "passcnt": {}}
    server.save_econ_store(es)


def attack(squad, extra=None, code=CODE):
    body = {"sourceTerritoryId": SRC, "targetTerritoryId": TGT, "squad": squad}
    if extra:
        body.update(extra)
    return call("POST", "/api/territory/attack?room=" + code, "tALICE", body)


def deltas(before, after):
    return {k: after[k] - before.get(k, 0) for k in after if after[k] != before.get(k, 0)}


LOSING_SQUAD = [{"type": "inf", "hp": 10}]
CRUSHING = [{"type": "spear", "hp": 300}]

# ============================ CASE 1 — human loses to a HUMAN: transfer, net 0 ============================
stage("BOB", [{"type": "inf", "hp": 10}], CRUSHING)
b = purses()
code, body = attack(LOSING_SQUAD)
a = purses()
assert code == 200 and body["attackerWon"] is False, (code, body)
assert a["ALICE"] - b["ALICE"] == -FAIL, "attacker pays exactly ATTACK_FAIL_GOLD"
assert a["BOB"] - b["BOB"] == DEFEND, "human defender is paid exactly DEFEND_GOLD"
assert (a["ALICE"] - b["ALICE"]) + (a["BOB"] - b["BOB"]) == 0, "human-vs-human is a pure transfer, net 0"
ok("CASE 1 human loses to HUMAN: attacker -%d / defender +%d, net 0 transfer" % (FAIL, DEFEND))

# ============================ CASE 2 — human loses to a ROOM AI: sink, nobody is paid ============================
stage(AI1, [{"type": "inf", "hp": 10}], CRUSHING)
b = purses()
code, body = attack(LOSING_SQUAD)
a = purses()
assert code == 200 and body["attackerWon"] is False, (code, body)
assert a["ALICE"] - b["ALICE"] == -FAIL, "attacker still pays exactly ATTACK_FAIL_GOLD"
assert a[AI1] == b[AI1], "the defending ROOM AI (%s) must receive NOTHING" % AI1
gained = [k for k, v in deltas(b, a).items() if v > 0]
assert not gained, "no purse anywhere may gain gold from a loss vs an AI; gained=%r" % gained
assert sum(deltas(b, a).values()) == -FAIL, "the %d is destroyed, not transferred" % FAIL
ok("CASE 2 human loses to ROOM AI %s: attacker -%d, AI +0, no purse gains -> %d destroyed"
   % (AI1, FAIL, FAIL))

# the same must hold for the legacy/default AI identity, which the OLD guard happened to cover
stage(server.AI_OWNER, [{"type": "inf", "hp": 10}], CRUSHING)
b = purses()
attack(LOSING_SQUAD)
a = purses()
assert a[server.AI_OWNER] == b[server.AI_OWNER], "legacy AI_OWNER must still receive nothing"
assert not [k for k, v in deltas(b, a).items() if v > 0], "no purse gains against the legacy AI either"
ok("CASE 2b legacy %r defender also receives nothing (no regression on the old guard)" % server.AI_OWNER)

# ============================ CASE 3 — AI attacks a human and loses: human is paid ============================
# Deterministic: the catalog holds only these two regions and both are owned, so `unowned_known` is
# empty -> occupy is impossible -> ai_move must attack, and there is exactly one legal target.
server.set_room(CODE)
server.save_catalog({SRC: 100, TGT: 100})
server.save_territory_store({
    SRC: {"owner": AI1, "avatar": "\U0001F916", "troops": [{"type": "cav", "hp": 1}], "pop": 100},
    TGT: {"owner": "ALICE", "troops": CRUSHING, "pop": 100},
})
es = server.load_econ_store()
for who in ("ALICE", AI1):
    es[who] = {"population": 100, "gold": 500 if who == "ALICE" else 0, "lastGold": time.time(),
               "troops": {"cav": 0, "archer": 0, "inf": 0, "spear": 0},
               "buildings": {}, "tech": {}, "passcnt": {}}
server.save_econ_store(es)
b = purses()
logged = server.ai_move(AI1, "normal", set(ROSTER))
a = purses()
assert logged and logged[0] == "attack_fail", "the AI attack must have been repelled; got %r" % (logged,)
server.set_room(CODE)
assert server.load_territory_store()[TGT]["owner"] == "ALICE", "the human keeps the defended territory"
assert a["ALICE"] - b["ALICE"] == DEFEND, "human defender is paid exactly DEFEND_GOLD by the AI path"
ok("CASE 3 ROOM AI %s attacks human and loses: human +%d, territory kept" % (AI1, DEFEND))

# ============================ CASE 4 — human WINS: no battle gold at all ============================
stage("BOB", [{"type": "cav", "hp": 100}], [{"type": "inf", "hp": 1}])
b = purses()
code, body = attack([{"type": "cav", "hp": 100}])
a = purses()
assert code == 200 and body["attackerWon"] is True, (code, body)
assert deltas(b, a) == {}, "a win pays NOBODY any battle gold; deltas=%r" % deltas(b, a)
ok("CASE 4 human WINS: zero battle-gold payout to any purse")

# ============================ AI recruit side effect ============================
# The erroneous +50 used to land in the room AI's purse, which _ai_recruit turns straight into troops.
stage(AI1, [{"type": "inf", "hp": 10}], CRUSHING)
server.set_room(CODE)
ai_before = dict(server.load_econ_store()[AI1])
attack(LOSING_SQUAD)
server.set_room(CODE)
ai_after = server.load_econ_store()[AI1]
assert ai_after["gold"] == ai_before["gold"] == 0, "a failed human attack must not fund the AI purse"
assert ai_after["troops"] == ai_before["troops"], "and therefore cannot indirectly finance _ai_recruit"
ok("AI recruit side effect: failed human attack leaves the AI purse AND troop pool untouched")

# ============================ forged client payout fields ============================
stage(AI1, [{"type": "inf", "hp": 10}], CRUSHING)
b = purses()
code, body = attack(LOSING_SQUAD, {
    "DEFEND_GOLD": 99999, "ATTACK_FAIL_GOLD": 0, "defendGold": 99999,
    "reward": 99999, "gold": 99999, "attackerWon": True, "winner": "ALICE",
})
a = purses()
assert code == 200 and body["attackerWon"] is False, "the client cannot declare itself the winner"
assert a["ALICE"] - b["ALICE"] == -FAIL, "payout amount comes from server config, never the request"
assert a[AI1] == b[AI1], "a forged defendGold cannot pay the AI"
assert not [k for k, v in deltas(b, a).items() if v > 0], "no purse gains from forged payout fields"
ok("forgery: DEFEND_GOLD/ATTACK_FAIL_GOLD/defendGold/reward/gold/attackerWon/winner all ignored")

# ============================ room isolation ============================
# The battle above happened in CODE; the same account's purse in OTHER must be untouched.
server.set_room(OTHER)
es = server.load_econ_store()
es["ALICE"] = {"population": 100, "gold": 777, "lastGold": time.time(),
               "troops": {"cav": 0, "archer": 0, "inf": 0, "spear": 0},
               "buildings": {}, "tech": {}, "passcnt": {}}
server.save_econ_store(es)
stage("BOB", [{"type": "inf", "hp": 10}], CRUSHING)
other_before = purses(OTHER)
attack(LOSING_SQUAD)
other_after = purses(OTHER)
assert other_after == other_before, "a battle in one room must not move any purse in another room"
assert other_after["ALICE"] == 777, "the same account's other-room purse is untouched"
ok("room isolation: battle gold lands only in the room that hosted the battle")

# ============================ same identity rule: conscript_tick ============================
# conscript_tick asks the same question ("is this owner a room AI?") and used the same stale guard.
# It is latent today — apply_territorial_attack rebuilds a captured region without the `conscript`
# flag, so no AI region normally carries one — but stale data or a future writer would revive it.
# The control region proves the fixture really does conscript, so this cannot pass vacuously.
server.set_room(CODE)
server.save_catalog({SRC: 100, TGT: 100})
# Phase 14A.10A: two PASSIVE periods (days), not two conscription periods (hours).
long_ago = time.time() - 2 * server.PASSIVE_PERIOD_SECONDS
conscripting = {"conscript": True, "conscriptBudget": 60, "buildings": {"barracks": True},
                "lastConscript": long_ago, "pop": 100}
server.save_territory_store({
    SRC: dict(conscripting, owner="ALICE", troops=[]),
    TGT: dict(conscripting, owner=AI1, avatar="\U0001F916", troops=[]),
})
es = server.load_econ_store()
for who in ("ALICE", AI1):
    es[who] = {"population": 100, "gold": 1000, "lastGold": time.time(),
               "troops": {"cav": 0, "archer": 0, "inf": 0, "spear": 0},
               "buildings": {}, "tech": {}, "passcnt": {}}
server.save_econ_store(es)
server.conscript_tick()
server.set_room(CODE)
ts = server.load_territory_store()
assert sum(t["hp"] for t in ts[SRC]["troops"]), "control: a HUMAN-owned region must still conscript"
assert ts[SRC]["lastConscript"] > long_ago, "control: the human region's conscription clock advanced"
assert ts[TGT]["troops"] == [], "a ROOM AI's region must be skipped by conscription"
assert ts[TGT]["lastConscript"] == long_ago, "and its conscription clock must not advance"
ok("conscript_tick: room AI %s skipped by the same identity rule; human region still conscripts" % AI1)

srv.shutdown()
print("\nAll %d battle-economy tests passed." % passed)
