#!/usr/bin/env python3
"""Phase 1B — territory identity: migration + backend authority.

    python3 tests/territory_identity_test.py

Identity is a CATALOG-WIDE concern and stays that way under the single-World model (Phase 10A.3):
every canonical id, legacy `maps/<map>.svg#<path>` key and `mapId#pathId` form must resolve to
exactly one canonical territory, whatever map it belongs to. Whether that territory may then be
PLAYED is a separate question owned by tests/map_eligibility_test.py — this suite proves the two
layers are distinct, so a dormant-map id is refused as `inactive_map` rather than mislabelled
`unresolved`.

The pure migrate_store() section below is map-agnostic and unchanged, so the real multi-path China
data (china:pLN x2 paths, china:pSH x3) still backs the collapse and collision invariants. The HTTP
claim path can no longer reach those territories, so multi-path claiming is exercised against a
synthetic catalog on the ACTIVE map, with a mutation proof that the check has teeth.
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


# start a room hosted by ALICE. Phase 10A: the course id is Learning-side only — it selects no map,
# and every room plays the same single World.
assert call("POST", "/api/room/create", {})[0] == 200
st = call("POST", "/api/room/start", {"map": "A1", "aiCount": 0, "resources": "medium", "capacity": 4})
assert st[0] == 200, st
CODE = st[1]["code"]

troops = [{"type": "inf", "hp": 10}]
ACTIVE = json.load(open(os.path.join(ROOT, "world-data", "territories", "world.json"),
                        encoding="utf-8"))[0]["id"]
DORMANT = json.load(open(os.path.join(ROOT, "world-data", "territories", "china.json"),
                         encoding="utf-8"))[0]["id"]

# claim by canonical id -> stored under canonical
# RETARGETED (Phase 10A.3): the subject moves from china:pBJ to an active-map id. The assertion is
# unchanged in substance — a canonical id must be stored verbatim as the store key — and it now runs
# on the map claims actually happen on.
code, body = call("POST", "/api/territory/claim?room=" + CODE,
                  {"file": ACTIVE, "troops": troops, "avatar": "👦"})
assert code == 200 and body.get("territory") == ACTIVE, (code, body)
server.set_room(CODE)
store = server.load_territory_store()
assert ACTIVE in store and store[ACTIVE]["owner"] == "ALICE", list(store)
ok("claim by canonical id stores under canonical key")

# population is authoritative from the catalog, not the client
assert store[ACTIVE]["pop"] == server.terr_catalog.game_population(ACTIVE)
ok("claim population comes from the catalog (client pop ignored)")

# unknown territory rejected. Checked on the active map AND behind a dormant map prefix: an id that
# is not in the catalog must be reported as unresolved, never as a map-eligibility problem, because
# identity resolution runs first.
for junk in ("world:zzz", "world:not-a-country", "china:zzz"):
    code, body = call("POST", "/api/territory/claim?room=" + CODE, {"file": junk, "troops": troops})
    assert code == 400 and body.get("reason") in ("unresolved", "not_in_catalog"), (junk, code, body)
ok("an id absent from the catalog is rejected as unresolved, whichever map its prefix names")

# RETARGETED TWICE — the history matters, because each rewrite tracked a real product change.
#   ORIGINAL (Phase 1B): a world territory claimed from an "A1" room had to fail 400 wrong_map,
#     because allowed_maps_for_level() let a CEFR course pick the canonical map (Pre-A1 -> taiwan,
#     A1 -> china, A2/B1 -> world).
#   PHASE 10A: Learning and Game were separated, that helper/table/reason were deleted, and the
#     assertion became "any canonical id resolves and is claimable".
#   PHASE 10A.3: conquest runs on ONE map (World); the other maps are dormant content.
#   NEW: identity and eligibility are proven to be SEPARATE layers. A dormant-map id — canonical or
#     legacy — still RESOLVES, which is the invariant this suite owns, and is then refused
#     `inactive_map` by the game layer rather than mislabelled `unresolved`.
#   WHY NOT WEAKER: this asserts strictly more than either earlier form — a positive resolution
#     result AND a truthful, specific rejection AND that the refusal writes no key of any shape.
#     Which maps are playable is pinned by tests/map_eligibility_test.py.
assert server.terr_catalog.resolve_any(DORMANT) == DORMANT
assert server.terr_catalog.map_of(DORMANT) == "china"
code, body = call("POST", "/api/territory/claim?room=" + CODE,
                  {"file": DORMANT, "troops": [{"type": "inf", "hp": 1}]})
assert code == 400 and body.get("reason") == "inactive_map", (code, body)
server.set_room(CODE)
assert DORMANT not in server.load_territory_store()
ok("a dormant-map canonical id still resolves in the catalog and is refused inactive_map, not "
   "unresolved — identity and map eligibility are separate layers")

# the same for a LEGACY MULTI-PATH dormant key: one canonical id out of the resolver, then refused
assert server.terr_catalog.resolve_any("maps/china.svg#pLN_1") == "china:pLN"
assert server.terr_catalog.resolve_any("maps/china.svg#pLN_2") == "china:pLN"
code, body = call("POST", "/api/territory/claim?room=" + CODE,
                  {"file": "maps/china.svg#pLN_1", "troops": troops})
assert code == 400 and body.get("reason") == "inactive_map", (code, body)
server.set_room(CODE)
assert not [k for k in server.load_territory_store() if "#" in k or k.startswith("china:")], \
    "a refused claim must not leave a key of ANY shape behind"
ok("a legacy multi-path dormant key resolves to one canonical id and is then refused inactive_map, "
   "never stored raw")

# ---- multi-path identity ON THE ACTIVE MAP, via a synthetic catalog ----
# All 8 multi-path territories live on dormant China (china:pTW/pLN/pHE/pSH/pFJ/pGD/pHK/pMO), and
# production World has none, so the HTTP claim path can no longer reach a multi-path territory
# through shipped data. It is exercised here against a purpose-built catalog whose active-map
# territory owns THREE svg paths — the same shape as china:pSH — proving the claim route collapses
# every accepted identifier form to the one canonical key before storing.
from territory_catalog import TerritoryCatalog       # noqa: E402


def synth_catalog(path_keys):
    """A minimal one-map catalog on the ACTIVE map id, with a single multi-path territory."""
    sd = tempfile.mkdtemp()
    os.makedirs(os.path.join(sd, "territories"))
    json.dump({"catalogVersion": "synthetic-test"}, open(os.path.join(sd, "catalog.json"), "w"))
    json.dump([{"id": server.GAME_WORLD_MAP_ID, "svgFile": "maps/world.svg", "name": "World"}],
              open(os.path.join(sd, "maps.json"), "w"))
    json.dump([{"id": "world:synthia", "mapId": server.GAME_WORLD_MAP_ID,
                "displayName": "Synthia", "svgPathKeys": list(path_keys),
                "gamePopulation": 4242, "adjacentTerritoryIds": []}],
              open(os.path.join(sd, "territories", "world.json"), "w"))
    return TerritoryCatalog(sd).load()


# a one-soldier squad, because the room's real army is finite and this block claims four times
SYN_SQUAD = [{"type": "cav", "hp": 1}]
_real_catalog = server.terr_catalog
try:
    server.terr_catalog = synth_catalog(["syn_1", "syn_2", "syn_3"])
    for key in ("maps/world.svg#syn_1", "maps/world.svg#syn_3", "world#syn_2", "world:synthia"):
        server.set_room(CODE)                      # each form starts from the territory unowned
        st_ = server.load_territory_store()
        st_.pop("world:synthia", None)
        server.save_territory_store(st_)
        code, body = call("POST", "/api/territory/claim?room=" + CODE,
                          {"file": key, "troops": SYN_SQUAD, "avatar": "👦"})
        assert code == 200 and body.get("territory") == "world:synthia", (key, code, body)
        server.set_room(CODE)
        st_ = server.load_territory_store()
        assert "world:synthia" in st_ and not [k for k in st_ if "#" in k], (key, list(st_))
        assert st_["world:synthia"]["pop"] == 4242, st_["world:synthia"]
    ok("every svg path of a multi-path ACTIVE-map territory — legacy key, mapId#pathId, and the "
       "canonical id alike — collapses to one canonical store key with catalog population")

    # MUTATION PROOF that the check above has teeth: drop syn_3 from the catalog and its legacy key
    # must stop resolving. If the claim route were deriving ids by string surgery instead of reading
    # svgPathKeys, this claim would still be accepted and the test would fail here.
    server.terr_catalog = synth_catalog(["syn_1", "syn_2"])
    code, body = call("POST", "/api/territory/claim?room=" + CODE,
                      {"file": "maps/world.svg#syn_3", "troops": SYN_SQUAD})
    assert code == 400 and body.get("reason") in ("unresolved", "not_in_catalog"), (code, body)
    ok("mutation proof: a path key removed from the catalog stops resolving — the claim route really "
       "reads svgPathKeys rather than parsing the identifier")
finally:
    server.terr_catalog = _real_catalog

# Legacy store on disk still loads (read) and canonicalizes in memory. Deliberately kept on a
# DORMANT multi-path subject (china:pSH has 3 svg paths): reading and canonicalizing a store is an
# identity operation with no eligibility opinion, so an old room's data must never be silently
# dropped just because its map is no longer playable.
server.set_room(CODE)
p = server.room_path("territory.json")
json.dump({"maps/china.svg#pSH_1": H("ALICE"), "maps/china.svg#pSH_2": H("ALICE")}, open(p, "w"))
store = server.load_territory_store()
assert list(store) == ["china:pSH"], list(store)
ok("legacy room JSON still loads and canonicalizes on read — including collapsing several svg paths "
   "of a dormant-map territory into one canonical key")

srv.shutdown()
print("\nAll %d identity tests passed." % passed)
