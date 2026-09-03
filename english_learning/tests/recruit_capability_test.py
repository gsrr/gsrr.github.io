# Phase 14A.3 — RECRUIT CAPABILITY: what a territory can actually recruit.
#
#   python tests/recruit_capability_test.py
#
# An Alpha player held a territory with a Barracks, an Archery Range and a Stable, opened
# Empire ▸ Forces ▸ Recruit, and was offered Infantry and Spear only. The server was never the
# problem — it gates each unit on that unit's own building, on that territory — so this file pins
# the AUTHORITY the client must mirror, case by case, and proves the client's model matches it.
#
# The canonical mapping is game/config.py:
#
#     UNIT_BUILDING = {"inf": "barracks", "spear": "barracks", "archer": "archery", "cav": "stable"}
#
# There is NO base-Barracks prerequisite: an Archery Range alone recruits Archers, a Stable alone
# recruits Cavalry. That is what the code says, so that is what the acceptance matrix below asserts
# rather than what a reader might assume.
import io, json, os, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server                                                       # noqa: E402
from game import config as game_config, recruitment as game_recruit  # noqa: E402
from territory_catalog import catalog as CAT                         # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ---------------------------------------------------------------- a real in-process server
DATA = tempfile.mkdtemp(prefix="recruit143_")
server.ROOMS_DIR = os.path.join(DATA, "rooms")
server.ACCT = os.path.join(DATA, "accounts.json")
server.DATA = os.path.join(DATA, "visits.json")
server.TERR_CATALOG = os.path.join(DATA, "learned.json")
os.makedirs(server.ROOMS_DIR, exist_ok=True)
json.dump({"users": {"RecA": {}}, "codes": {}}, io.open(server.ACCT, "w", encoding="utf-8"))
server._tokens["tRecA"] = {"user": "RecA", "exp": time.time() + 9999, "admin": False}
TOK = "tRecA"

httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT


def api(method, path, body=None, tok=TOK):
    url = BASE + path + (("&" if "?" in path else "?") + "token=" + tok if tok else "")
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "replace")}


# =========================================================== 1. the canonical mapping
assert game_config.UNIT_BUILDING == {"inf": "barracks", "spear": "barracks",
                                     "archer": "archery", "cav": "stable"}, game_config.UNIT_BUILDING
assert set(game_config.UNIT_COST) == {"inf", "spear", "archer", "cav"}, game_config.UNIT_COST
for unit, bld in game_config.UNIT_BUILDING.items():
    assert game_recruit.building_for(unit) == bld, (unit, bld)
    assert bld in game_config.BUILD_COST, bld
ok("1. the canonical building→troop mapping is barracks→inf+spear, archery→archer, stable→cav, "
   "and building_for() agrees with it for every unit")

# =========================================================== 2. RECRUIT_BATCH / costs unchanged
assert game_config.RECRUIT_BATCH == 10, game_config.RECRUIT_BATCH
assert game_config.UNIT_COST == {"inf": 6, "spear": 9, "archer": 12, "cav": 15}, game_config.UNIT_COST
assert game_config.BUILD_COST == {"armory": 50, "barracks": 60, "archery": 80, "stable": 120}
ok("2. RECRUIT_BATCH is still 10 and unit/building prices are unchanged — this phase fixes "
   "capability, not economy")

# =========================================================== 3. the pure rule, per building
for unit, need in game_config.UNIT_BUILDING.items():
    okno, _, reason = game_recruit.can_recruit(unit, 10, 100000, has_building=False)
    assert okno is False and reason == "need_" + need, (unit, reason)
    okyes, cost, r2 = game_recruit.can_recruit(unit, 10, 100000, has_building=True)
    assert okyes is True and r2 is None and cost == 10 * game_config.UNIT_COST[unit], (unit, cost, r2)
ok("3. the pure rule refuses every unit whose own building is missing and accepts it when present")

# ---------------------------------------------------------------- the room and the territories
st, j = api("POST", "/api/room/create", {})
assert st == 200, (st, j)
st, j = api("POST", "/api/room/start", {"map": "A1", "aiCount": 0, "resources": "high", "capacity": 4})
assert st == 200, (st, j)
CODE = j["code"]
R = "?room=" + CODE

if not CAT.loaded:
    CAT.load()
WORLD = sorted(t for t, rec in CAT.territories.items() if rec.get("mapId") == "world")

# CASE A..H: one territory per combination of the three production buildings
CASES = [
    ("A", []),
    ("B", ["barracks"]),
    ("C", ["archery"]),
    ("D", ["stable"]),
    ("E", ["barracks", "archery"]),
    ("F", ["barracks", "stable"]),
    ("G", ["archery", "stable"]),
    ("H", ["barracks", "archery", "stable"]),
]
TERR = {name: WORLD[i] for i, (name, _) in enumerate(CASES)}

# Building all eight combinations costs more than any starting purse, and GOLD is not the authority
# under test here — the building prerequisite is. So the fixture is funded through the server's own
# econ_add_gold(), the same function the battle path uses; test 9 below still proves the gold gate
# is intact.
server.set_room(CODE)
server.econ_add_gold("RecA", 50000)

for name, blds in CASES:
    tid = TERR[name]
    st, j = api("POST", "/api/territory/claim" + R,
                {"file": tid, "avatar": "R", "pop": 0, "troops": [{"type": "inf", "hp": 1}]})
    assert st == 200 and j.get("ok"), (name, tid, st, j)
    for b in blds:
        st, j = api("POST", "/api/territory/build" + R, {"file": tid, "building": b})
        assert st == 200 and j.get("ok"), ("build", name, b, st, j)


def expected_units(blds):
    """The client's model, restated independently: the UNION of what each built building enables."""
    out = []
    for unit in ("inf", "spear", "archer", "cav"):
        if game_config.UNIT_BUILDING[unit] in blds:
            out.append(unit)
    return out


def pool():
    st, j = api("GET", "/api/economy" + R)
    assert st == 200, (st, j)
    return j


# =========================================================== 4. the acceptance matrix, A–H
print("\n  ACCEPTANCE MATRIX — server truth per territory")
print("  %-5s %-28s %-22s %-22s" % ("case", "buildings", "accepted", "rejected"))
matrix = {}
for name, blds in CASES:
    tid = TERR[name]
    accepted, rejected = [], []
    for unit in ("inf", "spear", "archer", "cav"):
        before = pool()
        st, j = api("POST", "/api/territory/recruit" + R,
                    {"file": tid, "unit": unit, "qty": game_config.RECRUIT_BATCH})
        if st == 200 and j.get("ok"):
            accepted.append(unit)
            # the garrison of that territory grew by exactly one batch of that unit
            stt, jt = api("GET", "/api/territory" + R)
            g = {t["type"]: t["hp"] for t in (jt["holders"][tid].get("troops") or [])}
            assert g.get(unit, 0) >= game_config.RECRUIT_BATCH, (name, unit, g)
            after = pool()
            spent = (before.get("gold", 0) - after.get("gold", 0))
            assert spent == game_config.RECRUIT_BATCH * game_config.UNIT_COST[unit], \
                (name, unit, spent)
        else:
            rejected.append(unit)
            assert st == 400, (name, unit, st, j)
            assert ("need " + game_config.UNIT_BUILDING[unit]) in json.dumps(j), (name, unit, j)
    matrix[name] = (accepted, rejected)
    print("  %-5s %-28s %-22s %-22s" % (name, "+".join(blds) or "(none)",
                                        ",".join(accepted) or "-", ",".join(rejected) or "-"))
    assert accepted == expected_units(blds), (name, accepted, expected_units(blds))
ok("4. cases A–H: the server accepts exactly the union of the troop types the built buildings "
   "enable, and refuses every other type with that type's own missing-building reason")

# =========================================================== 5. the all-three case
assert matrix["H"][0] == ["inf", "spear", "archer", "cav"], matrix["H"]
assert matrix["H"][1] == [], matrix["H"]
ok("5. Barracks + Archery + Stable recruits ALL FOUR troop types — the player's reported case")

# =========================================================== 6. no base-Barracks prerequisite
assert matrix["C"][0] == ["archer"], matrix["C"]
assert matrix["D"][0] == ["cav"], matrix["D"]
ok("6. an Archery Range alone recruits Archers and a Stable alone recruits Cavalry — the "
   "repository defines no base-Barracks prerequisite, so none is invented")

# =========================================================== 7. capability is per territory
b_units, h_units = matrix["B"][0], matrix["H"][0]
assert b_units == ["inf", "spear"] and h_units == ["inf", "spear", "archer", "cav"]
st, j = api("POST", "/api/territory/recruit" + R,
            {"file": TERR["B"], "unit": "archer", "qty": 10})
assert st == 400 and "need archery" in json.dumps(j), (st, j)
st, j = api("POST", "/api/territory/recruit" + R, {"file": TERR["H"], "unit": "archer", "qty": 10})
assert st == 200 and j.get("ok"), (st, j)
ok("7. capability is territory-specific: the same unit is refused on a Barracks-only territory and "
   "accepted on the one that has the Archery Range")

# =========================================================== 8. ownership still gates it
st, j = api("POST", "/api/territory/recruit" + R,
            {"file": WORLD[40], "unit": "inf", "qty": 10})   # unowned
assert st in (400, 403) and not j.get("ok"), (st, j)
ok("8. an unowned territory still refuses recruitment — building capability is not ownership")

# =========================================================== 9. gold still gates it
st, econ = api("GET", "/api/economy" + R)
huge = 100000
st, j = api("POST", "/api/territory/recruit" + R, {"file": TERR["H"], "unit": "cav", "qty": huge})
assert st == 400 and "not enough gold" in json.dumps(j), (st, j)
ok("9. gold still gates recruitment — capability makes a type visible, never free")

# =========================================================== 10. the client's model matches
raw = io.open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
# the retired call survives in the comment that records why it was wrong, so pin the CODE
client = "\n".join(l for l in raw.split("\n") if not l.lstrip().startswith("//"))
assert 'if (builds.barracks) u = u.concat(["inf", "spear"]);' in client
assert 'if (builds.archery) u.push("archer");' in client
assert 'if (builds.stable) u.push("cav");' in client
assert "const units = producibleUnits(builds);" in client, \
    "Forces > Recruit must offer the union, not one building's units"
assert "openBuildingDetail(key, prod[0].id, reopen)" not in client, \
    "the first-production-building coupling must be gone from the code"
assert "prod[0]" not in client, "...and nothing else selects a single production building"
assert client.count("terrRecruit(key, btn.dataset.unit, RECRUIT_BATCH") == 1, \
    "there is exactly ONE recruit call site, shared by both surfaces"
ok("10. the client's producibleUnits() mirrors UNIT_BUILDING exactly, and Forces > Recruit is "
   "driven by that union rather than by whichever building happened to be first")

httpd.shutdown()
print("\nAll %d recruit-capability tests passed." % passed)
