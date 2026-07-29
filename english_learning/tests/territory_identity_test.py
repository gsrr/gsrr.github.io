#!/usr/bin/env python3
"""Phase 1B — territory identity: migration + backend authority.

    python3 tests/territory_identity_test.py
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
sys.path.insert(0, os.path.join(ROOT, "tools"))
import server                                   # noqa: E402
from migrate_room_keys import migrate_store     # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


def H(owner):
    return {"owner": owner, "troops": [], "pop": 100}


# ============ migration (pure) ============
# legacy room
new, rep = migrate_store({"maps/china.svg#pBJ": H("A"), "maps/world.svg#us": H("A")})
assert set(new.keys()) == {"china:pBJ", "world:us"}, new.keys()
assert rep["idempotent"] is False and len(rep["changed"]) == 2
ok("legacy room migrates to canonical ids")

# mixed room (already-canonical + legacy)
new, rep = migrate_store({"china:pBJ": H("A"), "maps/world.svg#us": H("A")})
assert set(new.keys()) == {"china:pBJ", "world:us"} and len(rep["changed"]) == 1
ok("mixed room: legacy converted, canonical untouched")

# canonical room is idempotent
new, rep = migrate_store({"china:pBJ": H("A"), "world:us": H("B")})
assert rep["idempotent"] and new == {"china:pBJ": H("A"), "world:us": H("B")}
ok("canonical room is idempotent (no changes)")

# unknown territory kept + reported
new, rep = migrate_store({"maps/world.svg#zzz": H("A"), "Pre-A1/001": H("A")})
assert "maps/world.svg#zzz" in new and "Pre-A1/001" in new and len(rep["unknown"]) == 2
ok("unknown territories are kept and reported, never discarded")

# multi-path legacy keys collapse to ONE canonical (same owner) — no collision
new, rep = migrate_store({"maps/china.svg#pLN_1": H("A"), "maps/china.svg#pLN_2": H("A")})
assert set(new.keys()) == {"china:pLN"}, new.keys()
ok("multi-path legacy keys collapse to one canonical territory")

# duplicate/collision: two legacy keys -> one canonical with DIFFERENT owners -> reported, not merged
new, rep = migrate_store({"maps/china.svg#pLN_1": H("A"), "maps/china.svg#pLN_2": H("B")})
assert len(rep["collisions"]) == 1, rep
ok("conflicting duplicate ownership is detected as a collision")

# ============ backend authority (HTTP) ============
d = tempfile.mkdtemp()
server.ROOMS_DIR = os.path.join(d, "rooms")
server.ACCT = os.path.join(d, "accounts.json")
server.DATA = os.path.join(d, "visits.json")
server.TERR_CATALOG = os.path.join(d, "learned_catalog.json")
os.makedirs(d, exist_ok=True)
json.dump({"users": {"ALICE": {"code": "ROOMAA"}}, "codes": {"ROOMAA": "ALICE"}},
          open(server.ACCT, "w"))
server._tokens["tA"] = {"user": "ALICE", "exp": time.time() + 9999, "admin": False}

from http.server import ThreadingHTTPServer  # noqa: E402
srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % port


def call(method, path, body=None):
    url = B + path + ("&" if "?" in path else "?") + "token=tA"
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = U.urlopen(U.Request(url, data=data, method=method))
        return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# start a china (A1) room hosted by ALICE
assert call("POST", "/api/room/create", {})[0] == 200
st = call("POST", "/api/room/start", {"map": "A1", "aiCount": 0, "resources": "medium", "capacity": 4})
assert st[0] == 200, st
CODE = st[1]["code"]

troops = [{"type": "inf", "hp": 10}]

# claim by canonical id -> stored under canonical
code, body = call("POST", "/api/territory/claim?room=" + CODE,
                  {"file": "china:pBJ", "troops": troops, "avatar": "👦"})
assert code == 200 and body.get("territory") == "china:pBJ", (code, body)
server.set_room(CODE)
store = server.load_territory_store()
assert "china:pBJ" in store and store["china:pBJ"]["owner"] == "ALICE", list(store)
ok("claim by canonical id stores under canonical key")

# claim by LEGACY multi-path key -> resolves to one canonical (china:pLN)
code, body = call("POST", "/api/territory/claim?room=" + CODE,
                  {"file": "maps/china.svg#pLN_1", "troops": troops, "avatar": "👦"})
assert code == 200 and body.get("territory") == "china:pLN", (code, body)
server.set_room(CODE)
store = server.load_territory_store()
assert "china:pLN" in store and "maps/china.svg#pLN_1" not in store, list(store)
ok("legacy multi-path claim resolves + stores as china:pLN (never raw path)")

# population is authoritative from the catalog, not the client
assert store["china:pLN"]["pop"] == server.terr_catalog.game_population("china:pLN")
ok("claim population comes from the catalog (client pop ignored)")

# unknown territory rejected
code, body = call("POST", "/api/territory/claim?room=" + CODE,
                  {"file": "china:zzz", "troops": troops})
assert code == 400 and body.get("reason") in ("unresolved", "not_in_catalog"), (code, body)
ok("unknown territory is rejected")

# wrong map rejected (world territory in a china room)
code, body = call("POST", "/api/territory/claim?room=" + CODE,
                  {"file": "world:us", "troops": troops})
assert code == 400 and body.get("reason") == "wrong_map", (code, body)
ok("territory from a different map is rejected")

# legacy store on disk still loads (read) and canonicalizes in memory
server.set_room(CODE)
p = server.room_path("territory.json")
json.dump({"maps/china.svg#pSH_1": H("ALICE")}, open(p, "w"))
store = server.load_territory_store()
assert "china:pSH" in store, list(store)
ok("legacy room JSON still loads and canonicalizes on read")

srv.shutdown()
print("\nAll %d identity tests passed." % passed)
