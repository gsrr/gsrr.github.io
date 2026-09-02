# Phase 14A.1 ADDENDUM — ATTACK SETTLEMENT: what the client is entitled to reconcile from.
#
#   python tests/attack_settlement_test.py
#
# The Alpha bug was a client that had won a territory and still painted it for the defender. The fix
# is a client that reconciles from the server after every battle, by every exit route — so what this
# file pins is the SERVER side of that contract:
#
#   * a WIN transfers ownership in the store, immediately and atomically;
#   * a LOSS transfers nothing, no matter what the client does with the response;
#   * the response itself always names the SETTLED owner, so a client never has to guess;
#   * a re-read of /api/territory reports the same owner and a matching strategic classification,
#     because that endpoint — not the attack response — is the client's canonical refresh.
#
# It also pins the two geographies the Alpha rule opened up (non-adjacent, and an island source with
# no land neighbours), because "it recolours immediately" has to be true for those too.
#
# Nothing here changes the battle formula: every attack below is decided by the real resolver, and
# the fixtures simply make the outcome certain: a 1-hp defender, or 90 troops against one soldier.
import io, json, os, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server                                                   # noqa: E402
from territory_catalog import catalog as CAT                     # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ---------------------------------------------------------------- a real in-process server
DATA = tempfile.mkdtemp(prefix="settle141_")
server.ROOMS_DIR = os.path.join(DATA, "rooms")
server.ACCT = os.path.join(DATA, "accounts.json")
server.DATA = os.path.join(DATA, "visits.json")
server.TERR_CATALOG = os.path.join(DATA, "learned.json")
os.makedirs(server.ROOMS_DIR, exist_ok=True)
json.dump({"users": {"SettleA": {}, "SettleB": {}}, "codes": {}},
          io.open(server.ACCT, "w", encoding="utf-8"))
for u in ("SettleA", "SettleB"):
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
TOK_A, TOK_B = "tSettleA", "tSettleB"

httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT


def api(method, path, body=None, tok=None):
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


if not CAT.loaded:
    CAT.load()
WORLD = sorted(t for t, rec in CAT.territories.items() if rec.get("mapId") == "world")
assert len(WORLD) == 250, len(WORLD)

st, j = api("POST", "/api/room/create", {}, TOK_A)
assert st == 200, (st, j)
st, j = api("POST", "/api/room/start",
            {"map": "A1", "aiCount": 0, "resources": "high", "capacity": 4}, TOK_A)
assert st == 200, (st, j)
CODE = j["code"]
st, j = api("POST", "/api/room/enter", {"room": CODE}, TOK_B)
assert st == 200, (st, j)
R = "?room=" + CODE


def claim(tid, tok, troops):
    return api("POST", "/api/territory/claim" + R,
               {"file": tid, "avatar": "X", "pop": 0, "troops": troops}, tok)


def attack(src, tgt, tok, squad):
    return api("POST", "/api/territory/attack" + R,
               {"sourceTerritoryId": src, "targetTerritoryId": tgt, "squad": squad, "avatar": "A"}, tok)


def store():
    server.set_room(CODE)
    return server.load_territory_store()


def holders(tok=TOK_A):
    """What the client's canonical refresh (GET /api/territory) actually reports."""
    st, j = api("GET", "/api/territory" + R, None, tok)
    assert st == 200, (st, j)
    return j.get("holders") or {}


def nbrs(t):
    return [n for n in (CAT.territories[t].get("adjacentTerritoryIds") or []) if n in CAT.territories]


CONNECTED = [t for t in WORLD if nbrs(t)]
ISLANDS = [t for t in WORLD if not nbrs(t)]
HOME = CONNECTED[0]
ADJ = nbrs(HOME)[0]
FAR = next(t for t in CONNECTED if t != HOME and t not in nbrs(HOME) and HOME not in nbrs(t))
FAR2 = next(t for t in CONNECTED
            if t not in (HOME, ADJ, FAR) and t not in nbrs(HOME) and HOME not in nbrs(t))
FAR3 = next(t for t in CONNECTED
            if t not in (HOME, ADJ, FAR, FAR2) and t not in nbrs(HOME) and HOME not in nbrs(t))
ISLAND = ISLANDS[0]

# A holds a strong home and an island with no land neighbours; B holds four targets.
# 'high' resources start every player with 45 troops of each class, so both fixtures are built
# inside that budget: A gets a strong home plus an island foothold, B gets three token garrisons
# and one that cannot be beaten by a single soldier.
assert claim(HOME, TOK_A, [{"type": "inf", "hp": 45}, {"type": "spear", "hp": 45}])[0] == 200
assert claim(ISLAND, TOK_A, [{"type": "cav", "hp": 40}])[0] == 200
for t in (ADJ, FAR, FAR3):
    assert claim(t, TOK_B, [{"type": "inf", "hp": 1}])[0] == 200, t
assert claim(FAR2, TOK_B, [{"type": "spear", "hp": 45}, {"type": "archer", "hp": 45}])[0] == 200

# =========================================================== 1. a WIN settles ownership at once
before = store()[ADJ]["owner"]
assert before == "SettleB", before
st, res = attack(HOME, ADJ, TOK_A, [{"type": "inf", "hp": 20}])
assert st == 200 and res.get("ok"), (st, res)
assert res["attackerWon"] is True, res
assert store()[ADJ]["owner"] == "SettleA", store()[ADJ]
ok("1. a WIN transfers ownership in the authoritative store, in the same request")

# =========================================================== 2. the response names the settled owner
assert res.get("owner") == "SettleA", res
assert res.get("defender") == "SettleB", res
assert res.get("targetTerritoryId") == ADJ and res.get("sourceTerritoryId") == HOME, res
ok("2. the response reports the SETTLED owner, the previous defender and both endpoints — a client "
   "never has to infer ownership from 'attackerWon'")

# =========================================================== 3. the canonical refresh agrees
h = holders()
assert h.get(ADJ, {}).get("owner") == "SettleA", h.get(ADJ)
assert h.get(ADJ, {}).get("strategic") in ("frontier", "interior", "isolated"), h.get(ADJ)
assert (h.get(ADJ, {}).get("troops") or []), "the winner's survivors must be the new garrison"
ok("3. GET /api/territory — the client's ONE reconciliation path — reports the same owner, a "
   "strategic classification and the new garrison (%s)" % h[ADJ]["strategic"])

# =========================================================== 4. the response garrison matches
assert [(t["type"], t["hp"]) for t in (res.get("targetGarrison") or [])] == \
       [(t["type"], t["hp"]) for t in (h[ADJ]["troops"] or [])], (res.get("targetGarrison"), h[ADJ])
ok("4. the response garrison and the refreshed garrison are the same troops — one settlement, "
   "not two")

# =========================================================== 5. a LOSS transfers nothing
own_before = store()[FAR2]["owner"]
st, lose = attack(HOME, FAR2, TOK_A, [{"type": "inf", "hp": 1}])
assert st == 200 and lose.get("ok"), (st, lose)
assert lose["attackerWon"] is False, lose
assert store()[FAR2]["owner"] == own_before == "SettleB", (store()[FAR2], own_before)
ok("5. a LOSS leaves the target with its defender — the store is unchanged")

# =========================================================== 6. and says so in the response
assert lose.get("owner") == "SettleB" and lose.get("defender") == "SettleB", lose
assert holders().get(FAR2, {}).get("owner") == "SettleB", holders().get(FAR2)
ok("6. a losing response still names the defender as owner, so a client that repaints from `owner` "
   "on every battle cannot tint a lost territory")

# =========================================================== 7. a loss cannot be talked into a win
# The client sends no outcome at all. Posting fabricated result fields must change nothing.
st, forged = api("POST", "/api/territory/attack" + R,
                 {"sourceTerritoryId": HOME, "targetTerritoryId": FAR2,
                  "squad": [{"type": "inf", "hp": 1}], "avatar": "A",
                  "attackerWon": True, "owner": "SettleA", "winner": "SettleA"}, TOK_A)
assert st == 200 and forged.get("ok"), (st, forged)
assert forged["attackerWon"] is False and forged.get("owner") == "SettleB", forged
assert store()[FAR2]["owner"] == "SettleB", store()[FAR2]
ok("7. a client-supplied winner/owner is ignored — the battle is decided server-side and the "
   "response still settles to the defender")

# =========================================================== 8. NON-ADJACENT win settles identically
assert FAR not in nbrs(HOME) and HOME not in nbrs(FAR), "the fixture must be non-adjacent"
st, res2 = attack(HOME, FAR, TOK_A, [{"type": "inf", "hp": 20}])
assert st == 200 and res2.get("ok") and res2["attackerWon"] is True, (st, res2)
assert res2.get("owner") == "SettleA", res2
assert store()[FAR]["owner"] == "SettleA" and holders().get(FAR, {}).get("owner") == "SettleA"
ok("8. a NON-ADJACENT conquest settles and refreshes exactly like an adjacent one")

# =========================================================== 9. island (no neighbours) source
assert not nbrs(ISLAND), "the fixture source must have no land neighbours"
st, res3 = attack(ISLAND, FAR3, TOK_A, [{"type": "cav", "hp": 40}])
assert st == 200 and res3.get("ok") and res3["attackerWon"] is True, (st, res3)
assert res3.get("owner") == "SettleA", res3
assert store()[FAR3]["owner"] == "SettleA" and holders().get(FAR3, {}).get("owner") == "SettleA"
ok("9. a conquest launched from a territory with no land neighbours settles and refreshes the same "
   "way — nothing about reconciliation depends on geography")

# =========================================================== 10. every derived field is republished
h = holders()
mine = [t for t, rec in h.items() if rec.get("owner") == "SettleA"]
assert set(mine) >= {HOME, ISLAND, ADJ, FAR, FAR3}, sorted(mine)
counts = (api("GET", "/api/territory" + R, None, TOK_A)[1].get("counts") or {})
assert counts.get("SettleA") == len(mine), (counts, len(mine))
for t in (ADJ, FAR, FAR3):
    assert h[t].get("strategic") in ("frontier", "interior", "isolated"), (t, h[t])
ok("10. one refresh republishes ownership, the per-owner counts and the strategic classification "
   "for every conquest — the client derives none of it (%d held)" % len(mine))

# =========================================================== 11. a refused attack settles nothing
snapshot = json.dumps({t: (store().get(t) or {}).get("owner") for t in (ADJ, FAR, FAR2, FAR3)},
                      sort_keys=True)
st, ref = attack(FAR2, ADJ, TOK_A, [{"type": "inf", "hp": 1}])     # source is the defender's
assert st in (400, 403) and not ref.get("ok"), (st, ref)
assert ref.get("reason") == "source_not_owned", ref
assert json.dumps({t: (store().get(t) or {}).get("owner") for t in (ADJ, FAR, FAR2, FAR3)},
                  sort_keys=True) == snapshot
ok("11. a refused attack changes no ownership at all, so the client's refresh-on-failure is a "
   "no-op rather than a repaint")

# =========================================================== 12. the adjacency catalogue is untouched
edges = sum(len(nbrs(t)) for t in CAT.territories)
assert edges == 900, edges
assert len([t for t in WORLD if not nbrs(t)]) == 90
ok("12. the adjacency catalogue is byte-identical — 900 edge-ends, 90 World territories with no "
   "land neighbour")

httpd.shutdown()
print("\nAll %d attack-settlement tests passed." % passed)
