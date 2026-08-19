"""Phase 10A — a learning level has ZERO authority over game-map eligibility.

    python tests/map_eligibility_test.py

Learning and Game are separate systems. Learning owns curriculum, mastery, learning rewards and gold;
the Game owns one world of territories, ownership, claim, attack, adjacency, troops and stamina.

Until Phase 10A the server contradicted that: `_handle_territory_claim` called
`allowed_maps_for_level(room["map"])`, which mapped a CEFR level id to exactly one canonical map
(Pre-A1 -> taiwan, A1 -> china, A2/B1 -> world) and answered **400 wrong_map** for anything else. A
learner's course therefore decided which game map they could own territory on:

    room level   taiwan            taipei                     china             world
    Pre-A1       200 ok            403 qualification_required  400 wrong_map     400 wrong_map
    A1           400 wrong_map     400 wrong_map               200 ok            400 wrong_map
    A2           400 wrong_map     400 wrong_map               400 wrong_map     200 ok

What this suite pins:

  1. NO CEFR->MAP AUTHORITY. With identical game state, the room's legacy `map`/level field can be
     any of Pre-A1/A1/A2/B1 and the claim verdict for a given territory is IDENTICAL. This is the
     regression guard: if the coupling is ever reintroduced, the matrix stops being uniform.

  2. NO wrong_map FROM A LEVEL. A territory that exists in the canonical catalog is never refused
     because of the room's level. `wrong_map` is not produced by the server at all any more.

  3. GAME RULES STILL APPLY. Removing the level gate must not weaken anything: a territory outside
     the catalog is still refused, a qualification-gated territory still answers
     403 qualification_required, and troops are still required.

  4. ROOM ISOLATION IS UNTOUCHED. Ownership lives in /data/rooms/<CODE>/, so two rooms do not see
     each other's claims. That never depended on the map gate, and must not start depending on it.
"""
import json, os, sys, tempfile, threading, time
import urllib.error, urllib.request as U

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import server

_d = tempfile.mkdtemp()
server.ROOMS_DIR = os.path.join(_d, "rooms")
server.ACCT = os.path.join(_d, "a.json")
server.PROG_DIR = os.path.join(_d, "p")
server.DATA = os.path.join(_d, "v.json")
server.TERR_CATALOG = os.path.join(_d, "learned.json")
server.LEARNING.content_root = ROOT
json.dump({"users": {"S": {"code": "c"}, "T": {"code": "d"}},
           "codes": {"c": "S", "d": "T"}}, open(server.ACCT, "w"))
server._tokens["tok"] = {"user": "S", "exp": time.time() + 9999, "admin": False}
# a SECOND host: /api/room/start resolves the caller's own room (find_user_room), so one account can
# only ever host one room -- proving isolation therefore needs a second account, not a second start.
server._tokens["tok2"] = {"user": "T", "exp": time.time() + 9999, "admin": False}

from http.server import ThreadingHTTPServer
_srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
BASE = "http://127.0.0.1:%d" % _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()

passed = 0


def ok(msg):
    global passed
    passed += 1
    print("  ok - " + msg)


def call(method, path, body=None, tok="tok"):
    url = BASE + path + ("&" if "?" in path else "?") + "token=" + tok
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = U.urlopen(U.Request(url, data=data, method=method))
        return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def first_territory(map_id):
    p = os.path.join(ROOT, "world-data", "territories", map_id + ".json")
    return json.load(open(p, encoding="utf-8"))[0]["id"]


TROOPS = [{"type": "inf", "hp": 3}]
LEVELS = ["Pre-A1", "A1", "A2", "B1"]
# one existing territory per canonical map; taipei is separated out because it is qualification-gated
PLAIN = {m: first_territory(m) for m in ("taiwan", "china", "world")}
GATED = "taipei:daan"


def fresh_room(level, tok="tok"):
    """Restart this host's room at `level`. /api/room/start resets that room's world (territories,
    economy, events), so every call yields the SAME room with a clean slate and a new level field --
    which is exactly the control we want: only the legacy level differs between measurements."""
    call("POST", "/api/room/create", {}, tok)
    code = call("POST", "/api/room/start", {"map": level, "aiCount": 0}, tok)[1]["code"]
    call("GET", "/api/economy?room=" + code, None, tok)     # provision the starting economy
    return code


# ============================== 1. the level field cannot change a claim verdict ==============================
matrix = {}
for level in LEVELS:
    code = fresh_room(level)
    assert (server.load_room(code) or {}).get("map") == level, level   # the legacy field IS set
    row = {}
    for map_id, tid in PLAIN.items():
        c, b = call("POST", "/api/territory/claim?room=" + code, {"file": tid, "troops": TROOPS})
        row[map_id] = (c, b.get("reason") or "ok")
    matrix[level] = row

base = matrix[LEVELS[0]]
for level in LEVELS[1:]:
    assert matrix[level] == base, ("level changed the verdict", level, matrix[level], base)
ok("1. claim verdicts are IDENTICAL across rooms whose legacy level field is %s" % "/".join(LEVELS))

for map_id, (c, reason) in base.items():
    assert c == 200 and reason == "ok", (map_id, c, reason)
ok("2. a valid ungated territory on taiwan, china AND world is claimable from the same room "
   "(the old matrix allowed exactly one of the three)")

# ============================== 2. wrong_map is gone as a level verdict ==============================
for level in LEVELS:
    for map_id, (c, reason) in matrix[level].items():
        assert reason != "wrong_map", (level, map_id, reason)
assert not hasattr(server, "allowed_maps_for_level"), "the CEFR->map helper must stay retired"
assert not hasattr(server, "LEVEL_PRIMARY_MAP"), "the CEFR->map table must stay retired"
src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
exe = "\n".join(l for l in src.split("\n") if not l.strip().startswith("#"))
assert "wrong_map" not in exe, "no executable line may still answer wrong_map"
ok("3. no claim answers wrong_map, and neither the CEFR->map table nor its helper exists any more")

# ============================== 3. the game's own rules still hold ==============================
code = fresh_room("A2")
c, b = call("POST", "/api/territory/claim?room=" + code, {"file": "china:zzz", "troops": TROOPS})
assert c == 400 and b.get("reason") in ("unresolved", "not_in_catalog"), (c, b)
ok("4. a territory outside the canonical catalog is still refused (%s)" % b.get("reason"))

c, b = call("POST", "/api/territory/claim?room=" + code, {"file": PLAIN["world"]})
assert c == 400 and "troops" in json.dumps(b), (c, b)
ok("5. troops are still required")

c, b = call("POST", "/api/territory/claim?room=" + code, {"file": GATED, "troops": TROOPS})
assert c == 403 and b.get("reason") == "qualification_required", (c, b)
ok("6. a qualification-gated territory still answers 403 qualification_required — from an A2 room, "
   "which the old gate would have refused with wrong_map before ever checking the qualification")

# the gate is a property of the TERRITORY, not of the room's level: same answer at every level
for level in LEVELS:
    code_l = fresh_room(level)
    c, b = call("POST", "/api/territory/claim?room=" + code_l, {"file": GATED, "troops": TROOPS})
    assert c == 403 and b.get("reason") == "qualification_required", (level, c, b)
ok("7. that qualification gate answers identically at every level: learning ACHIEVEMENT gates a "
   "territory, learning LEVEL gates nothing")

# ============================== 4. room isolation still comes from the room store ==============================
a = fresh_room("Pre-A1")
b_ = fresh_room("A2", "tok2")          # a DIFFERENT host, hence a genuinely different room
assert a != b_, (a, b_)
tid = PLAIN["world"]
ca, _ = call("POST", "/api/territory/claim?room=" + a, {"file": tid, "troops": TROOPS})
assert ca == 200, ca
_, sa = call("GET", "/api/territory?room=" + a)
_, sb = call("GET", "/api/territory?room=" + b_, None, "tok2")
ha, hb = (sa.get("holders") or {}), (sb.get("holders") or {})     # {holders:{id:{owner,...}}, counts:{}}
assert (ha.get(tid) or {}).get("owner"), ha.get(tid)
assert not (hb.get(tid) or {}).get("owner"), hb.get(tid)
cb, _ = call("POST", "/api/territory/claim?room=" + b_, {"file": tid, "troops": TROOPS}, "tok2")
assert cb == 200, cb          # the same territory is independently free in the other room
ok("8. two rooms (different hosts) keep independent ownership of the same world territory — "
   "isolation comes from /data/rooms/<CODE>/, never from the retired map gate")

# ============================== 5. attack is decided by adjacency, never by a level ==============================
# Attack was never level-gated (allowed_maps_for_level lived only in the claim handler). The point of
# this block is that removing the claim gate did not leak into attack, and that adjacency still rules.
world = json.load(open(os.path.join(ROOT, "world-data", "territories", "world.json"), encoding="utf-8"))
by_id = {t["id"]: t for t in world}
pair = None
for t in world:
    for adj in (t.get("adjacentTerritoryIds") or []):
        if adj in by_id:
            pair = (t["id"], adj)
            break
    if pair:
        break
assert pair, "world.json should contain at least one adjacent pair"
SRC, ADJ = pair
FAR = next(t["id"] for t in world
           if t["id"] not in (SRC, ADJ)
           and t["id"] not in (by_id[SRC].get("adjacentTerritoryIds") or []))

atk = {}
for level in LEVELS:
    code = fresh_room(level)
    call("POST", "/api/territory/claim?room=" + code,
         {"file": SRC, "troops": [{"type": "inf", "hp": 9}]})
    a1 = call("POST", "/api/territory/attack?room=" + code,
              {"sourceTerritoryId": SRC, "targetTerritoryId": ADJ, "squad": [{"type": "inf", "hp": 3}]})
    a2 = call("POST", "/api/territory/attack?room=" + code,
              {"sourceTerritoryId": SRC, "targetTerritoryId": FAR, "squad": [{"type": "inf", "hp": 3}]})
    a3 = call("POST", "/api/territory/attack?room=" + code,
              {"sourceTerritoryId": ADJ, "targetTerritoryId": SRC, "squad": [{"type": "inf", "hp": 3}]})
    atk[level] = {"adjacent": (a1[0], a1[1].get("reason") or "ok"),
                  "non_adjacent": (a2[0], a2[1].get("reason") or "ok"),
                  "unowned_source": (a3[0], a3[1].get("reason") or "ok")}

base_atk = atk[LEVELS[0]]
for level in LEVELS[1:]:
    assert atk[level] == base_atk, ("the level changed an attack verdict", level, atk[level], base_atk)
ok("9. attack verdicts are IDENTICAL across all four legacy level values (%s -> %s, non-adjacent %s, "
   "unowned source %s)" % (SRC, base_atk["adjacent"][1], base_atk["non_adjacent"][1],
                           base_atk["unowned_source"][1]))

assert base_atk["non_adjacent"][1] != "ok", base_atk
assert base_atk["unowned_source"][1] == "source_not_owned", base_atk
ok("10. adjacency and source ownership are still enforced, so nothing was weakened to decouple the map")

# ============================== 6. no game route reads the room's level ==============================
src_txt = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
handlers, cur = {}, None
for line in src_txt.splitlines():
    st = line.strip()
    if st.startswith("def _handle_"):
        cur = st.split("(")[0][len("def _handle_"):]      # "_handle_territory_claim" -> "territory_claim"
        handlers[cur] = []
    elif cur is not None:
        handlers[cur].append(line)
GAME_ROUTES = ["territory", "territory_claim", "territory_attack", "territory_release",
               "territory_build", "territory_research", "territory_recruit", "territory_conscript"]
for h in GAME_ROUTES:
    assert h in handlers, h
    body = os.linesep.join(x for x in handlers[h] if not x.strip().startswith("#"))
    for bad in ("allowed_maps_for_level", "LEVEL_PRIMARY_MAP", "wrong_map"):
        assert bad not in body, (h, bad)
    assert 'load_room().get("map")' not in body, (h, "still reads the room level")
ok("11. none of the %d game routes (%s) reads the room level or the retired map table"
   % (len(GAME_ROUTES), ", ".join(GAME_ROUTES)))


print("\nAll %d map-eligibility tests passed." % passed)
_srv.shutdown()
