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

srv.shutdown()
print("\nAll %d conquest tests passed." % passed)
