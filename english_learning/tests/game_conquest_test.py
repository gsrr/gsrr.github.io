#!/usr/bin/env python3
"""Phase 2A — conquest orchestration + server-authoritative attack endpoint.

    python3 tests/game_conquest_test.py
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
from game import recruitment as game_recruit  # noqa: E402
from game import technology as game_tech  # noqa: E402
from game import config as game_cfg  # noqa: E402
import server  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ---------- pure conquest.resolve_attack (rng=None keeps given defender order → deterministic) ----------
r = conquest.resolve_attack([{"type": "cav", "hp": 100}], [{"type": "inf", "hp": 1}], {}, {}, None)
assert r["attackerWon"] is True and r["attackerSurvivors"] and "defenderOrder" in r
r2 = conquest.resolve_attack([{"type": "inf", "hp": 1}], [], {}, {}, None)
assert r2["attackerWon"] is True                                   # undefended
r3 = conquest.resolve_attack([{"type": "cav", "hp": 1}], [{"type": "spear", "hp": 200}], {}, {}, None)
assert r3["attackerWon"] is False                                  # spear crushes lone cav
ok("resolve_attack: victory / undefended / defeat (deterministic with injected order)")

# ---------- HTTP: server-authoritative attack ----------
d = tempfile.mkdtemp()
server.ROOMS_DIR = os.path.join(d, "rooms")
server.ACCT = os.path.join(d, "accounts.json")
server.DATA = os.path.join(d, "visits.json")
server.TERR_CATALOG = os.path.join(d, "learned.json")
os.makedirs(d, exist_ok=True)
json.dump({"users": {"ALICE": {"code": "ATKAAA"}, "BOB": {}}, "codes": {"ATKAAA": "ALICE"}}, open(server.ACCT, "w"))
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
st = call("POST", "/api/room/start", "tALICE", {"map": "A1", "aiCount": 0, "resources": "medium", "capacity": 4})
CODE = st[1]["code"]
now = time.time()


def set_state(alice_pool, alice_gold, targets):
    server.set_room(CODE)
    es = server.load_econ_store()
    es["ALICE"] = {"population": 100, "gold": alice_gold, "lastGold": now, "troops": alice_pool,
                   "buildings": {}, "tech": {}, "passcnt": {}}
    es.setdefault("BOB", {"population": 100, "gold": 0, "lastGold": now,
                          "troops": {"cav": 0, "archer": 0, "inf": 0, "spear": 0}, "buildings": {}, "tech": {}, "passcnt": {}})
    server.save_econ_store(es)
    ts = server.load_territory_store()
    ts.update(targets)
    server.save_territory_store(ts)


# WIN: big cavalry vs a lone infantry defender (owned by BOB) → territory neutralized, survivors returned, no gold loss
set_state({"cav": 100, "archer": 0, "inf": 0, "spear": 0}, 100,
          {"china:pBJ": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100}})
code, body = call("POST", "/api/territory/attack?room=" + CODE, "tALICE",
                  {"file": "china:pBJ", "squad": [{"type": "cav", "hp": 100}]})
assert code == 200 and body["attackerWon"] is True, (code, body)
server.set_room(CODE)
assert "china:pBJ" not in server.load_territory_store(), "win neutralizes the territory (ownership via later claim)"
poolA = server.load_econ_store()["ALICE"]["troops"]
assert poolA["cav"] > 0 and server.load_econ_store()["ALICE"]["gold"] == 100, poolA   # survivors returned, no penalty
ok("attack win: backend resolves, territory neutralized, survivors returned, no gold penalty")

# LOSE: lone cavalry vs a huge spear garrison → attacker −50, defender +50, territory unchanged
set_state({"cav": 1, "archer": 0, "inf": 0, "spear": 0}, 100,
          {"china:pSH": {"owner": "BOB", "troops": [{"type": "spear", "hp": 200}], "pop": 100}})
code, body = call("POST", "/api/territory/attack?room=" + CODE, "tALICE",
                  {"file": "china:pSH", "squad": [{"type": "cav", "hp": 1}]})
assert code == 200 and body["attackerWon"] is False, (code, body)
server.set_room(CODE)
ts = server.load_territory_store()
assert ts.get("china:pSH", {}).get("owner") == "BOB", "defeat preserves the owner"
assert server.load_econ_store()["ALICE"]["gold"] == 50, "attacker loses ATTACK_FAIL_GOLD"
assert server.load_econ_store()["BOB"]["gold"] == 50, "defender gains DEFEND_GOLD"
ok("attack loss: owner preserved, attacker -50, defender +50")

# client cannot attack a neutral/unknown territory via /attack
set_state({"cav": 10, "archer": 0, "inf": 0, "spear": 0}, 100, {})
assert call("POST", "/api/territory/attack?room=" + CODE, "tALICE", {"file": "china:zzz", "squad": [{"type": "cav", "hp": 5}]})[0] == 400
ok("unknown territory rejected by attack endpoint")

# REGRESSION: adjacency is NOT enforced in Phase 2A — a geographically NON-adjacent attack is still allowed.
# china:pXJ (Xinjiang, far NW) and china:pHL do not border each other, but attack must still work.
set_state({"cav": 100, "archer": 0, "inf": 0, "spear": 0}, 100,
          {"china:pGD": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100}})
code, body = call("POST", "/api/territory/attack?room=" + CODE, "tALICE",
                  {"file": "china:pGD", "squad": [{"type": "cav", "hp": 100}]})
assert code == 200 and body["attackerWon"] is True, "non-adjacent attack must remain valid (no adjacency rule yet)"
ok("REGRESSION: non-adjacent attack still allowed (adjacency NOT enforced in Phase 2A)")

# ---------- FORGE-PROOF: the client cannot dictate winner / survivors / ownership / gold ----------
# ALICE sends a hopeless squad but LIES in the body: attackerWon/win/survivors are all forged.
# The server must ignore every client-supplied result field and decide the battle itself.
set_state({"cav": 1, "archer": 0, "inf": 0, "spear": 0}, 100,
          {"china:pXJ": {"owner": "BOB", "troops": [{"type": "spear", "hp": 200}], "pop": 100}})
code, body = call("POST", "/api/territory/attack?room=" + CODE, "tALICE",
                  {"file": "china:pXJ", "squad": [{"type": "cav", "hp": 1}],
                   "attackerWon": True, "win": True, "gold": 999999,
                   "attackerSurvivors": [{"type": "cav", "hp": 99999}], "defenderSurvivors": []})
assert code == 200 and body["attackerWon"] is False, "server decides the winner, not the client"
assert sum(s["hp"] for s in body["attackerSurvivors"]) == 0, "a wiped-out attacker cannot forge survivors"
server.set_room(CODE)
assert server.load_territory_store().get("china:pXJ", {}).get("owner") == "BOB", "forged 'win' must not neutralize the region"
poolA = server.load_econ_store()["ALICE"]
assert poolA["troops"]["cav"] == 0, "the lost squad is spent server-side, not restored by the forged survivors"
assert poolA["gold"] == 50, "forged 'win'/'gold' cannot dodge the ATTACK_FAIL_GOLD penalty"
ok("forge-proof: client cannot override winner / survivors / ownership / gold")

# ---------- NO DOUBLE-SPEND: a REJECTED attack must not deduct the squad or touch gold ----------
set_state({"cav": 5, "archer": 0, "inf": 0, "spear": 0}, 100,
          {"china:pSC": {"owner": "ALICE", "troops": [{"type": "inf", "hp": 1}], "pop": 100}})
assert call("POST", "/api/territory/attack?room=" + CODE, "tALICE",
            {"file": "china:pSC", "squad": [{"type": "cav", "hp": 3}]})[0] == 400, "cannot attack your own region"
server.set_room(CODE)
assert server.load_econ_store()["ALICE"]["troops"]["cav"] == 5 and server.load_econ_store()["ALICE"]["gold"] == 100, \
    "rejected (own-region) attack leaves pool + gold intact"
set_state({"cav": 2, "archer": 0, "inf": 0, "spear": 0}, 100,
          {"china:pYN": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100}})
assert call("POST", "/api/territory/attack?room=" + CODE, "tALICE",
            {"file": "china:pYN", "squad": [{"type": "cav", "hp": 50}]})[0] == 400, "cannot spend troops you do not have"
server.set_room(CODE)
assert server.load_econ_store()["ALICE"]["troops"]["cav"] == 2, "insufficient-troop attack must not deduct anything"
# a genuine LOSS returns survivors → net pool change = casualties only, squad state stays consistent
set_state({"cav": 0, "archer": 0, "inf": 10, "spear": 0}, 100,
          {"china:pGS": {"owner": "BOB", "troops": [{"type": "spear", "hp": 300}], "pop": 100}})
code, body = call("POST", "/api/territory/attack?room=" + CODE, "tALICE",
                  {"file": "china:pGS", "squad": [{"type": "inf", "hp": 10}]})
assert code == 200 and body["attackerWon"] is False
server.set_room(CODE)
assert server.load_econ_store()["ALICE"]["troops"]["inf"] == sum(s["hp"] for s in body["attackerSurvivors"] if s["type"] == "inf"), \
    "survivors returned to the pool exactly match the server's reported survivors (no lost/duplicated squad)"
ok("no double-spend: rejected attacks preserve pool+gold; a loss returns exactly the reported survivors")


def set_alice(**fields):   # reset ALICE econ then patch specific fields for a delegation test
    set_state({"cav": 0, "archer": 0, "inf": 0, "spear": 0}, fields.pop("gold", 0), {})
    server.set_room(CODE)
    es = server.load_econ_store()
    es["ALICE"].update(fields)
    server.save_econ_store(es)


# ---------- RECRUIT handler delegates to game.recruitment (same decision + authoritative cost) ----------
set_alice(gold=1000, buildings={"barracks": True}, troops={"cav": 0, "archer": 0, "inf": 0, "spear": 0})
dec_ok, dec_cost, dec_reason = game_recruit.can_recruit("inf", 10, 1000, True)
code, body = call("POST", "/api/territory/recruit?room=" + CODE, "tALICE",
                  {"file": "@home", "unit": "inf", "qty": 10, "cost": 1})   # client 'cost' must be ignored
assert (code == 200) == dec_ok, "recruit HTTP success mirrors can_recruit()"
server.set_room(CODE)
assert server.load_econ_store()["ALICE"]["gold"] == 1000 - dec_cost == 1000 - 10 * game_cfg.UNIT_COST["inf"], \
    "charged the authoritative config cost, not the client-supplied one"
assert server.load_econ_store()["ALICE"]["troops"]["inf"] == 10
# building gate: recruiting cav with no stable → need <building>, delegated reason
set_alice(gold=1000, buildings={}, troops={"cav": 0, "archer": 0, "inf": 0, "spear": 0})
code, body = call("POST", "/api/territory/recruit?room=" + CODE, "tALICE", {"file": "@home", "unit": "cav", "qty": 10})
assert game_recruit.can_recruit("cav", 10, 1000, False)[2] == "need_" + game_recruit.building_for("cav")
assert code == 400 and body["error"] == "need " + game_recruit.building_for("cav")
server.set_room(CODE)
assert server.load_econ_store()["ALICE"]["gold"] == 1000, "a gated recruit must not spend gold"
ok("recruit handler delegates to game.recruitment (success + building gate + authoritative cost)")

# ---------- RESEARCH handler delegates to game.technology (same decision + level/cost) ----------
set_alice(gold=1000, buildings={}, tech={})
assert game_tech.can_research("atk", 0, 1000, has_armory=False)[3] == "need_armory"
code, body = call("POST", "/api/territory/research?room=" + CODE, "tALICE", {"file": "@home", "track": "atk"})
assert code == 400 and body["error"] == "need armory", "no armory → delegated need_armory reason"
set_alice(gold=1000, buildings={"armory": True}, tech={})
d_ok, d_cost, d_nxt, d_reason = game_tech.can_research("atk", 0, 1000, has_armory=True)
code, body = call("POST", "/api/territory/research?room=" + CODE, "tALICE", {"file": "@home", "track": "atk"})
assert (code == 200) == d_ok, "research HTTP success mirrors can_research()"
server.set_room(CODE)
assert server.load_econ_store()["ALICE"]["tech"]["atk"] == d_nxt, "stored level matches technology.can_research()"
assert server.load_econ_store()["ALICE"]["gold"] == 1000 - d_cost, "charged the authoritative research cost"
set_alice(gold=9999, buildings={"armory": True}, tech={"def": game_cfg.TECH_MAX})
assert game_tech.can_research("def", game_cfg.TECH_MAX, 9999)[3] == "maxed"
code, body = call("POST", "/api/territory/research?room=" + CODE, "tALICE", {"file": "@home", "track": "def"})
assert code == 400 and body["error"] == "maxed", "maxed track rejected via delegated reason"
ok("research handler delegates to game.technology (armory gate + success + level/cost + maxed)")

# ---------- /claim CANNOT seize a HELD (enemy) territory — occupation is neutral/own only ----------
set_state({"cav": 10, "archer": 0, "inf": 0, "spear": 0}, 100,
          {"china:pHB": {"owner": "BOB", "troops": [{"type": "inf", "hp": 5}], "pop": 100}})
code, body = call("POST", "/api/territory/claim?room=" + CODE, "tALICE",
                  {"file": "china:pHB", "troops": [{"type": "cav", "hp": 5}], "avatar": "\U0001F466"})
assert code == 403 and body.get("reason") == "held", (code, body)
server.set_room(CODE)
assert server.load_territory_store()["china:pHB"]["owner"] == "BOB", "a held territory cannot be claimed without attacking"
code, body = call("POST", "/api/territory/claim?room=" + CODE, "tALICE",
                  {"file": "china:pTW", "troops": [{"type": "cav", "hp": 5}], "avatar": "\U0001F466"})   # neutral → OK
assert code == 200, (code, body)
server.set_room(CODE)
assert server.load_territory_store()["china:pTW"]["owner"] == "ALICE", "neutral territory occupied normally"
assert call("POST", "/api/territory/claim?room=" + CODE, "tALICE",
            {"file": "china:pTW", "troops": [{"type": "inf", "hp": 3}], "avatar": "\U0001F466"})[0] == 200, "own re-deploy still allowed"
ok("claim is neutral/own only: cannot seize a held enemy territory (must attack first)")

# ---------- /release is OWNER-ONLY — a client cannot neutralize an ENEMY territory ----------
set_state({"cav": 0, "archer": 0, "inf": 0, "spear": 0}, 100,
          {"china:pLN": {"owner": "BOB", "troops": [{"type": "spear", "hp": 9}], "pop": 100}})
code, body = call("POST", "/api/territory/release?room=" + CODE, "tALICE", {"file": "china:pLN"})
assert code == 403 and body.get("reason") == "not_owner", (code, body)
server.set_room(CODE)
assert server.load_territory_store()["china:pLN"]["owner"] == "BOB", "release must NOT neutralize an enemy territory"
code, body = call("POST", "/api/territory/release?room=" + CODE, "tBOB", {"file": "china:pLN"})   # owner self-abandon
assert code == 200 and body.get("released") is True, (code, body)
server.set_room(CODE)
assert "china:pLN" not in server.load_territory_store(), "owner can self-abandon their own region"
ok("release is owner-only: enemy neutralize blocked (403), self-abandon allowed")

# ---------- /attack-result is a NON-AUTHORITATIVE no-op — cannot forge gold / ownership / outcome ----------
set_state({"cav": 5, "archer": 0, "inf": 0, "spear": 0}, 100,
          {"china:pHE": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100}})
server.set_room(CODE)
bob_gold0 = server.load_econ_store()["BOB"]["gold"]
for win_flag in (True, False):                       # neither a claimed 'win' nor 'loss' may move any gold now
    code, body = call("POST", "/api/territory/attack-result?room=" + CODE, "tALICE",
                      {"file": "china:pHE", "win": win_flag})
    assert code == 200 and "gold" not in body, (code, body)
server.set_room(CODE)
assert server.load_econ_store()["ALICE"]["gold"] == 100, "attack-result must not change the attacker's gold"
assert server.load_econ_store()["BOB"]["gold"] == bob_gold0, "attack-result must not change the defender's gold"
assert server.load_territory_store()["china:pHE"]["owner"] == "BOB", "attack-result must not touch ownership"
ok("attack-result retired: non-authoritative no-op (cannot forge gold / ownership / outcome)")

# ---------- /engage is READ-ONLY — reveals the garrison but mutates nothing (no authority bypass) ----------
set_state({"cav": 7, "archer": 0, "inf": 0, "spear": 0}, 100,
          {"china:pHN": {"owner": "BOB", "troops": [{"type": "spear", "hp": 4}], "pop": 100}})
server.set_room(CODE)
snap_terr = json.dumps(server.load_territory_store(), sort_keys=True)
snap_econ = json.dumps(server.load_econ_store(), sort_keys=True)
code, body = call("POST", "/api/territory/engage?room=" + CODE, "tALICE", {"file": "china:pHN"})
assert code == 200 and body.get("owner") == "BOB", (code, body)
server.set_room(CODE)
assert json.dumps(server.load_territory_store(), sort_keys=True) == snap_terr, "engage must not mutate territory state"
assert json.dumps(server.load_econ_store(), sort_keys=True) == snap_econ, "engage must not mutate economy/pool/gold"
ok("engage is read-only: reveals garrison but mutates nothing (no authority bypass)")

srv.shutdown()
print("\nAll %d conquest tests passed." % passed)
