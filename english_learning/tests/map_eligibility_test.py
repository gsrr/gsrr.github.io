"""Phase 10A.3R — ONE active conquest map, and Learning has ZERO authority over it.

    python tests/map_eligibility_test.py

Learning and Game are separate systems. Learning owns curriculum, mastery, learning rewards and the
Gold they mint. The Game owns one world of territories: ownership, claim, attack, adjacency, troops
and stamina. This suite is the anti-regression guard for that separation, and it has now protected
two different couplings in turn:

  Phase 10A    retired `allowed_maps_for_level()`. A CEFR level id used to select exactly one
               canonical map (Pre-A1 -> taiwan, A1 -> china, A2/B1 -> world) and refuse everything
               else, so a learner's COURSE decided which map they could own territory on.

  Phase 10A.3R retired the learning-qualification gate. Holding (or lacking) a learning achievement
               used to decide whether a territory could be claimed or attacked, answering
               403 qualification_required. Learning no longer unlocks ground at all.

What is pinned here:

  1. THE ACTIVE MAP IS GAME CONFIGURATION. `allowed_game_maps()` is a single-element set decided by
     the game, never by a course. World territories are playable; the dormant taiwan/taipei/china
     datasets answer `inactive_map` for everyone.

  2. THE LEGACY LEVEL FIELD IS INERT. With identical game state, a room's `map`/level value can be
     any of Pre-A1/A1/A2/B1 and every verdict is IDENTICAL. If the coupling is ever reintroduced,
     the matrix stops being uniform.

  3. QUALIFICATION HAS ZERO CONQUEST EFFECT. The same World territory returns the same verdict with
     no qualification, with a FORGED client-supplied one, and with every real server-granted one.
     This is deliberately stronger than deleting the old gate assertion: it actively guards against
     re-coupling instead of merely noting that the gate is gone.

  4. GAME RULES STILL APPLY. Removing learning authority must not weaken anything: non-catalog ids
     are refused, troops are still required, adjacency and source-ownership still decide attacks,
     and two rooms keep independent ownership.
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
# /api/room/start resolves the CALLER's own room, so proving isolation needs a second account.
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


def terrs(map_id):
    return json.load(open(os.path.join(ROOT, "world-data", "territories", map_id + ".json"),
                          encoding="utf-8"))


TROOPS = [{"type": "inf", "hp": 3}]
LEVELS = ["Pre-A1", "A1", "A2", "B1"]
ACTIVE = "world"
DORMANT = ["taiwan", "taipei", "china"]

# A real adjacent pair on the active map, taken from the catalog rather than assumed.
_by = {t["id"]: t for t in terrs(ACTIVE)}
SRC = ADJ = None
for _t in terrs(ACTIVE):
    for _a in (_t.get("adjacentTerritoryIds") or []):
        if _a in _by:
            SRC, ADJ = _t["id"], _a
            break
    if SRC:
        break
assert SRC and ADJ, "the active map must contain at least one adjacent pair"
FAR = next(t for t in _by
           if t not in (SRC, ADJ) and t not in (_by[SRC].get("adjacentTerritoryIds") or []))
DORMANT_SAMPLE = {m: terrs(m)[0]["id"] for m in DORMANT}


def fresh_room(level, tok="tok"):
    """Restart this host's room at `level`. /api/room/start resets that room's world, so each call
    gives the SAME room with a clean slate and a new legacy level — exactly the control we want."""
    call("POST", "/api/room/create", {}, tok)
    code = call("POST", "/api/room/start", {"map": level, "aiCount": 0}, tok)[1]["code"]
    call("GET", "/api/economy?room=" + code, None, tok)
    return code


# ============================== 1. the active map is game configuration ==============================
assert server.allowed_game_maps() == {ACTIVE}, server.allowed_game_maps()
assert not hasattr(server, "allowed_maps_for_level"), "the CEFR->map helper must stay retired"
assert not hasattr(server, "LEVEL_PRIMARY_MAP"), "the CEFR->map table must stay retired"
ok("1. allowed_game_maps() == {%r}: one active map, decided by the game — the CEFR->map helper and "
   "table stay retired" % ACTIVE)

# ============================== 2. the legacy level field is inert ==============================
matrix = {}
for level in LEVELS:
    code = fresh_room(level)
    assert (server.load_room(code) or {}).get("map") == level, level      # the legacy field IS set
    row = {}
    c, b = call("POST", "/api/territory/claim?room=" + code, {"file": SRC, "troops": TROOPS})
    row[ACTIVE] = (c, b.get("reason") or "ok")
    for m, tid in DORMANT_SAMPLE.items():
        c, b = call("POST", "/api/territory/claim?room=" + code, {"file": tid, "troops": TROOPS})
        row[m] = (c, b.get("reason") or "ok")
    matrix[level] = row

base = matrix[LEVELS[0]]
for level in LEVELS[1:]:
    assert matrix[level] == base, ("the level changed a verdict", level, matrix[level], base)
ok("2. claim verdicts are IDENTICAL across rooms whose legacy level field is %s" % "/".join(LEVELS))

assert base[ACTIVE] == (200, "ok"), base
for m in DORMANT:
    assert base[m] == (400, "inactive_map"), (m, base[m])
ok("3. the active map is claimable and every dormant map answers 400 inactive_map, for all four "
   "level values alike (%s)" % ", ".join("%s=%s" % (m, base[m][1]) for m in [ACTIVE] + DORMANT))

# ============================== 3. attack obeys the same rule ==============================
atk = {}
for level in LEVELS:
    code = fresh_room(level)
    call("POST", "/api/territory/claim?room=" + code,
         {"file": SRC, "troops": [{"type": "inf", "hp": 9}]})
    a1 = call("POST", "/api/territory/attack?room=" + code,
              {"sourceTerritoryId": SRC, "targetTerritoryId": ADJ, "squad": TROOPS})
    a2 = call("POST", "/api/territory/attack?room=" + code,
              {"sourceTerritoryId": SRC, "targetTerritoryId": FAR, "squad": TROOPS})
    a3 = call("POST", "/api/territory/attack?room=" + code,
              {"sourceTerritoryId": ADJ, "targetTerritoryId": SRC, "squad": TROOPS})
    a4 = call("POST", "/api/territory/attack?room=" + code,
              {"sourceTerritoryId": SRC, "targetTerritoryId": DORMANT_SAMPLE["taipei"],
               "squad": TROOPS})
    atk[level] = {"adjacent": (a1[0], a1[1].get("reason") or "ok"),
                  "non_adjacent": (a2[0], a2[1].get("reason") or "ok"),
                  "unowned_source": (a3[0], a3[1].get("reason") or "ok"),
                  "dormant_target": (a4[0], a4[1].get("reason") or "ok")}
base_atk = atk[LEVELS[0]]
for level in LEVELS[1:]:
    assert atk[level] == base_atk, ("the level changed an attack verdict", level, atk[level])
ok("4. attack verdicts are IDENTICAL across all four legacy level values")

assert base_atk["dormant_target"] == (400, "inactive_map"), base_atk
assert base_atk["non_adjacent"][1] != "ok", base_atk
assert base_atk["unowned_source"][1] == "source_not_owned", base_atk
ok("5. an attack into a dormant map is refused inactive_map, while adjacency (%r) and source "
   "ownership (%r) still decide attacks on the active map"
   % (base_atk["non_adjacent"][1], base_atk["unowned_source"][1]))

# ============================== 4. qualification has ZERO conquest effect ==============================
# The most important guard in this file: same territory, same game state, three different learning
# qualification states, one identical verdict.
QUALS = sorted(server.LEARNING.registry.qualifications)
assert QUALS, "the registry should still declare learning qualifications (they are achievements now)"


def verdict_with(qualifications):
    """Claim SRC in a clean room whose ACCOUNT holds exactly `qualifications`."""
    code = fresh_room("A2")
    prog = server.load_progress("S") or {}
    learning = prog.get("learning") or {}
    learning["qualifications"] = {q: {"grantedAt": 1} for q in qualifications}
    prog["learning"] = learning
    server.save_progress("S", prog)
    c, b = call("POST", "/api/territory/claim?room=" + code, {"file": SRC, "troops": TROOPS})
    return c, (b.get("reason") or "ok")


none_v = verdict_with([])
forged_v = verdict_with(QUALS + ["forged.qualification.that.does.not.exist"])
real_v = verdict_with(QUALS)
assert none_v == forged_v == real_v == (200, "ok"), (none_v, forged_v, real_v)
ok("6. claiming the SAME World territory gives an IDENTICAL verdict with no qualification, with a "
   "FORGED one, and with every real one held: %r — learning cannot unlock ground" % (none_v,))

import game.conquest as gc
assert "qualification_required" not in gc.AttackEligibility.REASONS, gc.AttackEligibility.REASONS
_store = {SRC: {"owner": "S", "troops": [{"type": "inf", "hp": 9}], "pop": 100},
          ADJ: {"owner": "X", "troops": [{"type": "inf", "hp": 1}], "pop": 100}}
_squad = [{"type": "inf", "hp": 3}]
e_none = gc.can_attack("S", SRC, ADJ, _squad, server.terr_catalog, _store,
                       player_qualifications=set())
e_all = gc.can_attack("S", SRC, ADJ, _squad, server.terr_catalog, _store,
                      player_qualifications=set(QUALS + ["forged.one"]))
assert (e_none.allowed, e_none.reason) == (e_all.allowed, e_all.reason), (e_none, e_all)
ok("7. the pure attack rule returns the same eligibility with an empty and a full qualification set, "
   "and 'qualification_required' is no longer even a possible reason")

# ============================== 5. the game's own rules still hold ==============================
code = fresh_room("A2")
c, b = call("POST", "/api/territory/claim?room=" + code,
            {"file": "world:not-a-country", "troops": TROOPS})
assert c == 400 and b.get("reason") in ("unresolved", "not_in_catalog"), (c, b)
ok("8. a territory outside the canonical catalog is still refused (%s)" % b.get("reason"))

c, b = call("POST", "/api/territory/claim?room=" + code, {"file": SRC})
assert c == 400 and "troops" in json.dumps(b), (c, b)
ok("9. troops are still required to acquire a territory")

# ============================== 6. room isolation is unchanged ==============================
a = fresh_room("Pre-A1")
b_ = fresh_room("A2", "tok2")
assert a != b_, (a, b_)
ca, _ = call("POST", "/api/territory/claim?room=" + a, {"file": SRC, "troops": TROOPS})
assert ca == 200, ca
_, sa = call("GET", "/api/territory?room=" + a)
_, sb = call("GET", "/api/territory?room=" + b_, None, "tok2")
ha, hb = (sa.get("holders") or {}), (sb.get("holders") or {})
assert (ha.get(SRC) or {}).get("owner"), ha.get(SRC)
assert not (hb.get(SRC) or {}).get("owner"), hb.get(SRC)
cb, _ = call("POST", "/api/territory/claim?room=" + b_, {"file": SRC, "troops": TROOPS}, "tok2")
assert cb == 200, cb
ok("10. two rooms with different hosts keep independent ownership of the same World territory — "
   "isolation comes from /data/rooms/<CODE>/, never from the map rule")

# ============================== 7. no game route reads the room's level ==============================
src_txt = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
handlers, cur = {}, None
for line in src_txt.splitlines():
    st = line.strip()
    if st.startswith("def _handle_"):
        cur = st.split("(")[0][len("def _handle_"):]
        handlers[cur] = []
    elif cur is not None:
        handlers[cur].append(line)
GAME_ROUTES = ["territory", "territory_claim", "territory_attack", "territory_release",
               "territory_build", "territory_research", "territory_recruit", "territory_conscript"]
for h in GAME_ROUTES:
    assert h in handlers, h
    body = os.linesep.join(x for x in handlers[h] if not x.strip().startswith("#"))
    for bad in ("allowed_maps_for_level", "LEVEL_PRIMARY_MAP", "qualification_required",
                "_player_qualifications", 'load_room().get("map")'):
        assert bad not in body, (h, bad)
ok("11. none of the %d game routes reads the room level, the retired map table, or any learning "
   "qualification" % len(GAME_ROUTES))

print("\nAll %d single-world map-eligibility tests passed." % passed)
_srv.shutdown()
