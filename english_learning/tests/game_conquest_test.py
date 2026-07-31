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


# ============================ Phase 2B — territorial conquest over HTTP ============================
# Attacks now originate from an OWNED, ADJACENT source territory and commit that source's GARRISON
# (no longer the global pool). Win transfers ownership; loss returns survivors to the source.
def gsum(troops, ty=None):
    return sum(int(t.get("hp", 0) or 0) for t in (troops or [])
               if isinstance(t, dict) and (ty is None or t.get("type") == ty))


def atk(source, target, squad, extra=None):
    body = {"sourceTerritoryId": source, "targetTerritoryId": target, "squad": squad}
    if extra:
        body.update(extra)
    return call("POST", "/api/territory/attack?room=" + CODE, "tALICE", body)


# WIN: owned pBJ (Beijing) attacks adjacent enemy pHE (Hebei) → ownership TRANSFERS, survivors garrison target
set_state({"cav": 0, "archer": 0, "inf": 0, "spear": 0}, 100, {
    "china:pBJ": {"owner": "ALICE", "troops": [{"type": "cav", "hp": 100}], "pop": 100},
    "china:pHE": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100},
})
code, body = atk("china:pBJ", "china:pHE", [{"type": "cav", "hp": 100}])
assert code == 200 and body["attackerWon"] is True and body["owner"] == "ALICE", (code, body)
server.set_room(CODE)
ts = server.load_territory_store()
assert ts["china:pHE"]["owner"] == "ALICE", "win transfers TARGET ownership to the attacker (no separate claim needed)"
assert gsum(ts["china:pHE"]["troops"]) > 0, "attacker survivors become the new target garrison"
assert gsum(ts["china:pBJ"]["troops"]) == 0, "the committed squad left the SOURCE garrison"
assert server.load_econ_store()["ALICE"]["gold"] == 100, "win: no gold change"
assert server.load_econ_store()["ALICE"]["troops"] == {"cav": 0, "archer": 0, "inf": 0, "spear": 0}, \
    "the global pool is NOT the attack source (untouched)"
ok("2B attack WIN: owned+adjacent source → ownership transfers, survivors garrison target, source reduced, pool untouched")

# LOSS: owned pBJ (inf 10) attacks adjacent crushing spear garrison → owner kept, survivors RETURN to source
set_state({"cav": 0, "archer": 0, "inf": 0, "spear": 0}, 100, {
    "china:pBJ": {"owner": "ALICE", "troops": [{"type": "inf", "hp": 10}], "pop": 100},
    "china:pHE": {"owner": "BOB", "troops": [{"type": "spear", "hp": 300}], "pop": 100},
})
server.set_room(CODE)
bob0 = server.load_econ_store().get("BOB", {}).get("gold", 0)
code, body = atk("china:pBJ", "china:pHE", [{"type": "inf", "hp": 10}])
assert code == 200 and body["attackerWon"] is False, (code, body)
server.set_room(CODE)
ts = server.load_territory_store()
assert ts["china:pHE"]["owner"] == "BOB", "loss preserves the target owner"
assert gsum(ts["china:pBJ"]["troops"], "inf") == gsum(body["attackerSurvivors"], "inf"), \
    "attacker survivors RETURN to the SOURCE garrison (never the global pool, never vanish)"
assert server.load_econ_store()["ALICE"]["gold"] == 50, "loss: attacker -ATTACK_FAIL_GOLD"
assert server.load_econ_store()["BOB"]["gold"] == bob0 + 50, "loss: defender +DEFEND_GOLD"
assert server.load_econ_store()["ALICE"]["troops"] == {"cav": 0, "archer": 0, "inf": 0, "spear": 0}, \
    "the global pool is never touched by an attack"
ok("2B attack LOSS: owner kept, survivors return to SOURCE, attacker -50 / defender +50, pool untouched")

# INTENDED PHASE 2B GAMEPLAY CHANGE — a NON-ADJACENT attack is now REJECTED (was explicitly ALLOWED in 2A).
set_state({"cav": 0, "archer": 0, "inf": 0, "spear": 0}, 100, {
    "china:pBJ": {"owner": "ALICE", "troops": [{"type": "cav", "hp": 100}], "pop": 100},
    "china:pSH": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100},   # Shanghai: NOT adjacent to Beijing
})
code, body = atk("china:pBJ", "china:pSH", [{"type": "cav", "hp": 50}])
assert code == 400 and body.get("reason") == "not_adjacent", (code, body)
server.set_room(CODE)
ts = server.load_territory_store()
assert ts["china:pSH"]["owner"] == "BOB" and gsum(ts["china:pBJ"]["troops"]) == 100, "rejected non-adjacent attack changes NOTHING"
ok("2B INTENDED CHANGE: non-adjacent attack REJECTED (reason=not_adjacent); atomically no state change")

# Eligibility over HTTP: source-not-owned → 403; unknown ids → 400; MISSING source → 400 (never inferred)
set_state({"cav": 0, "archer": 0, "inf": 0, "spear": 0}, 100, {
    "china:pBJ": {"owner": "CAROL", "troops": [{"type": "cav", "hp": 10}], "pop": 100},   # ALICE does NOT own source
    "china:pHE": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100},
})
assert atk("china:pBJ", "china:pHE", [{"type": "cav", "hp": 5}])[0] == 403, "attacking from a source you don't own → 403"
assert atk("china:zzz", "china:pHE", [{"type": "cav", "hp": 5}])[1].get("reason") == "source_not_found"
assert call("POST", "/api/territory/attack?room=" + CODE, "tALICE",
            {"targetTerritoryId": "china:pHE", "squad": [{"type": "cav", "hp": 5}]})[1].get("reason") == "source_not_found", \
    "omitting sourceTerritoryId is rejected, never inferred server-side"
server.set_room(CODE)
assert server.load_territory_store()["china:pHE"]["owner"] == "BOB", "every rejected eligibility case leaves state unchanged"
ok("2B eligibility HTTP: source ownership (403) / unknown ids / missing source all rejected, no state change")

# FORGE-PROOF (source API): forged winner/survivors/owner/gold are ignored; server decides authoritatively.
set_state({"cav": 0, "archer": 0, "inf": 0, "spear": 0}, 100, {
    "china:pBJ": {"owner": "ALICE", "troops": [{"type": "cav", "hp": 1}], "pop": 100},
    "china:pHE": {"owner": "BOB", "troops": [{"type": "spear", "hp": 200}], "pop": 100},
})
code, body = atk("china:pBJ", "china:pHE", [{"type": "cav", "hp": 1}],
                 {"attackerWon": True, "win": True, "gold": 999999, "owner": "ALICE",
                  "attackerSurvivors": [{"type": "cav", "hp": 99999}], "defenderSurvivors": []})
assert code == 200 and body["attackerWon"] is False, "server decides the winner, not the client"
assert body["owner"] == "BOB", "forged 'owner' cannot transfer the territory"
server.set_room(CODE)
assert server.load_territory_store()["china:pHE"]["owner"] == "BOB", "forged win must NOT transfer ownership"
assert server.load_econ_store()["ALICE"]["gold"] == 50, "forged 'win'/'gold' cannot dodge the loss penalty"
ok("2B forge-proof: client cannot override winner / survivors / ownership / gold on the source→target attack")


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

# ============================ Phase 2B — can_attack() domain rule (pure) ============================
W = server.terr_catalog                              # World Domain (authoritative adjacency from world-data)
W.load()
SQ = [{"type": "cav", "hp": 10}]


def terrs_base():
    return {
        "china:pBJ": {"owner": "ALICE", "troops": [{"type": "cav", "hp": 50}]},   # source (owned by ALICE)
        "china:pHE": {"owner": "BOB", "troops": [{"type": "inf", "hp": 5}]},       # adjacent enemy
        "china:pTJ": {"owner": "ALICE", "troops": [{"type": "cav", "hp": 5}]},     # adjacent, but OWNED by ALICE
        "china:pSH": {"owner": "BOB", "troops": [{"type": "inf", "hp": 5}]},       # NON-adjacent enemy
    }


T = terrs_base()
assert conquest.can_attack("ALICE", "china:pBJ", "china:pHE", SQ, W, T).allowed, "owned + adjacent + enemy → allowed"
assert conquest.can_attack("ALICE", "china:pHE", "china:pBJ", SQ, W, T).reason == "source_not_owned"
assert conquest.can_attack("ALICE", "china:pBJ", "china:pBJ", SQ, W, T).reason == "same_territory"
assert conquest.can_attack("ALICE", "china:pBJ", "china:pTJ", SQ, W, T).reason == "target_already_owned"
assert conquest.can_attack("ALICE", "china:pBJ", "china:pSH", SQ, W, T).reason == "not_adjacent"
assert conquest.can_attack("ALICE", "china:zzz", "china:pHE", SQ, W, T).reason == "source_not_found"
assert conquest.can_attack("ALICE", "china:pBJ", "china:zzz", SQ, W, T).reason == "target_not_found"
assert conquest.can_attack("ALICE", "china:pBJ", "china:pHE", [{"type": "cav", "hp": 9999}], W, T).reason == "insufficient_source_garrison"
assert conquest.can_attack("ALICE", "china:pBJ", "china:pHE", [], W, T).reason == "invalid_squad"
assert conquest.can_attack("ALICE", "china:pBJ", "china:pHE", [{"type": "dragon", "hp": 5}], W, T).reason == "invalid_squad"
Tn = terrs_base(); Tn["china:pTJ"] = {"troops": []}   # pTJ adjacent to pBJ but NEUTRAL now
assert conquest.can_attack("ALICE", "china:pBJ", "china:pTJ", SQ, W, Tn).reason == "target_not_attackable"
# canonical ids only: None / legacy keys are rejected as not-found (never resolved for attack)
assert conquest.can_attack("ALICE", None, "china:pHE", SQ, W, T).reason == "source_not_found"
assert conquest.can_attack("ALICE", "maps/china.svg#pBJ_1", "china:pHE", SQ, W, T).reason == "source_not_found"
ok("2B can_attack: ownership / same / already-owned / adjacency / unknown ids / garrison / squad / neutral / canonical-only")

# ============================ Phase 2B — adjacency uses real Phase 1C world-data ============================
# This block isolates ADJACENCY, so it opts out of the Phase 3A learning layer
# (require_qualifications=False) — otherwise a designer adding a learning requirement to any territory
# named here would masquerade as an adjacency failure. The gate itself is covered in
# tests/learning_gate_test.py; the assertion below pins that the two layers stay independent.
def can(src, tgt, require_quals=False):
    tt = {src: {"owner": "ALICE", "troops": [{"type": "cav", "hp": 20}]},
          tgt: {"owner": "BOB", "troops": [{"type": "inf", "hp": 3}]}}
    return conquest.can_attack("ALICE", src, tgt, [{"type": "cav", "hp": 5}], W, tt,
                               require_qualifications=require_quals)


assert can("china:pBJ", "china:pHE").allowed, "China: Beijing ↔ Hebei adjacent"
assert can("taiwan:changhua-county", "taiwan:nantou-county").allowed, "Taiwan: Changhua ↔ Nantou adjacent"
assert can("taipei:wenshan", "taipei:daan").allowed, "Taipei: Wenshan ↔ Da'an adjacent"
assert can("world:fr", "world:de").allowed, "World: France ↔ Germany adjacent"
assert can("world:jp", "world:kr").reason == "not_adjacent", "Japan ↔ Korea NOT adjacent (sea) — no fake adjacency"
assert can("china:pTW", "china:pFJ").reason == "not_adjacent", "Taiwan ↔ China(Fujian) NOT adjacent (strait)"
assert can("world:gb", "world:fr").reason == "not_adjacent", "UK ↔ France NOT adjacent (channel)"
assert can("world:au", "world:id").reason == "not_adjacent", "Australia ↔ Indonesia NOT adjacent (sea)"
# 3A cross-check: taipei:daan is adjacency-OK but learning-gated — the layers are orthogonal, and a
# learning requirement never turns into (or hides behind) an adjacency verdict.
assert can("taipei:wenshan", "taipei:daan", require_quals=True).reason == "qualification_required"
assert can("taipei:wenshan", "taipei:nangang", require_quals=True).allowed, "ungated neighbour unaffected"
# Phase 4A gated Xinyi too (MRT); Nangang is the remaining ungated Taipei neighbour of Wenshan.
assert can("taipei:wenshan", "taipei:xinyi", require_quals=True).reason == "qualification_required"
ok("2B adjacency: real Phase 1C positives (CN / TW / Taipei / World) + island/sea negatives, canonical ids only")

# ============================ Phase 2B — apply_territorial_attack state transition (pure) ============================
src0 = {"owner": "A", "troops": [{"type": "cav", "hp": 100}, {"type": "inf", "hp": 20}], "tech": {"atk": 1}}
tgt0 = {"owner": "B", "troops": [{"type": "spear", "hp": 5}], "tech": {"def": 2}, "pop": 77, "buildings": {"armory": True}}
squad0 = [{"type": "cav", "hp": 60}]
win = {"attackerWon": True, "attackerSurvivors": [{"type": "cav", "hp": 40}], "defenderSurvivors": []}
ns, nt = conquest.apply_territorial_attack(src0, tgt0, squad0, win, "A", "\U0001F9D1")
assert gsum(ns["troops"], "cav") == 40 and gsum(ns["troops"], "inf") == 20, "WIN: source keeps (garrison − committed squad)"
assert nt["owner"] == "A" and gsum(nt["troops"], "cav") == 40, "WIN: ownership transfers, survivors garrison the target"
assert nt.get("pop") == 77 and not nt.get("buildings") and not nt.get("tech"), "WIN: population preserved, buildings/tech reset"
loss = {"attackerWon": False, "attackerSurvivors": [{"type": "cav", "hp": 15}], "defenderSurvivors": [{"type": "spear", "hp": 3}]}
ns2, nt2 = conquest.apply_territorial_attack(src0, tgt0, squad0, loss, "A", "\U0001F9D1")
assert gsum(ns2["troops"], "cav") == 55 and gsum(ns2["troops"], "inf") == 20, "LOSS: source = (garrison − squad) + returned survivors"
assert nt2["owner"] == "B" and gsum(nt2["troops"], "spear") == 3, "LOSS: owner kept, garrison = defender survivors"
assert nt2.get("buildings") == {"armory": True} and nt2.get("pop") == 77, "LOSS: target buildings/pop preserved"
ok("2B apply_territorial_attack: win transfers+garrisons+resets; loss keeps owner, returns survivors to source")

# ============================ Phase 2B — AI obeys the same source + adjacency rule ============================
# AI must attack only from an AI-owned source adjacent to an enemy target, committing that source's garrison
# (no magic/global army, no AI-only bypass, same game.conquest service).
server.set_room(CODE)
server.save_catalog({"china:pBJ": 100, "china:pHE": 100})   # learned catalog = only these → no neutral to occupy
server.save_territory_store({
    "china:pBJ": {"owner": server.AI_OWNER, "avatar": "\U0001F916", "troops": [{"type": "cav", "hp": 80}], "pop": 100},
    "china:pHE": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100},
})
es = server.load_econ_store()
es.setdefault(server.AI_OWNER, {"population": 100, "gold": 0, "lastGold": now,
                                "troops": {"cav": 0, "archer": 0, "inf": 0, "spear": 0},
                                "buildings": {}, "tech": {}, "passcnt": {}})
server.save_econ_store(es)
server.ai_move()                                     # only valid action = attack pHE from adjacent owned pBJ
server.set_room(CODE)
ts = server.load_territory_store()
assert ts["china:pHE"]["owner"] == server.AI_OWNER, "AI conquered the adjacent enemy from its owned source"
assert gsum(ts["china:pBJ"]["troops"]) < 80, "AI committed troops from its SOURCE garrison (not a global/magic army)"
ok("2B AI attack: source is AI-owned + adjacent, squad from source garrison, same conquest service (no bypass)")

# AI on an ISOLATED island (no land neighbours) cannot cross the sea → must not throw, must not attack
server.set_room(CODE)
server.save_catalog({"world:jp": 100, "world:kr": 100})
server.save_territory_store({
    "world:jp": {"owner": server.AI_OWNER, "avatar": "\U0001F916", "troops": [{"type": "cav", "hp": 50}], "pop": 100},
    "world:kr": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 100},
})
server.ai_move()                                     # jp ↮ kr not adjacent, nothing unowned → AI safely skips
server.set_room(CODE)
assert server.load_territory_store()["world:kr"]["owner"] == "BOB", "AI cannot cross a sea gap (island limitation, no bypass)"
ok("2B AI isolated: no adjacent source → AI skips attack without error")

srv.shutdown()
print("\nAll %d conquest tests passed." % passed)
