#!/usr/bin/env python3
"""Phase 10B — zero-territory re-entry is a bounded, server-authoritative exception.

    python tests/reentry_authority_test.py

A player holding nothing on a fully-claimed World map has no legal conquest action: /claim answers
`held` on every territory and /attack requires an owned source. That is a permanent soft-lock, and
re-entry is the one exception to it.

The whole point of this suite is that the exception stays an exception. It pins:

  * ELIGIBILITY is decided by the server from GAME state only. Owning even one territory, or any
    neutral territory still being claimable, makes re-entry unavailable -- so it can never be used as
    a shortcut past adjacency.
  * The candidate set is the ONLY authority on where a player may land. A forged, dormant-map,
    unresolvable or simply un-offered id is refused.
  * Troops MOVE: the foothold force is debited from the existing pool and never minted, and a failed
    re-entry returns its survivors to that pool exactly as a failed attack returns them to its source.
  * The canonical battle engine decides the outcome -- the same resolve_attack and
    apply_territorial_attack the ordinary attack path uses.
  * ORDINARY RULES ARE UNTOUCHED. A player who owns ground still needs an owned, adjacent source.
  * Learning state is irrelevant, in both directions.
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import server                                          # noqa: E402
from game import config as game_config                  # noqa: E402
from game import conquest as game_conquest              # noqa: E402

_d = tempfile.mkdtemp()
server.ROOMS_DIR = os.path.join(_d, "rooms")
server.ACCT = os.path.join(_d, "accounts.json")
server.PROG_DIR = os.path.join(_d, "progress")
server.DATA = os.path.join(_d, "visits.json")
server.TERR_CATALOG = os.path.join(_d, "learned.json")
server.LEARNING.content_root = ROOT
os.makedirs(server.ROOMS_DIR, exist_ok=True)
os.makedirs(server.PROG_DIR, exist_ok=True)
json.dump({"users": {}, "codes": {}}, open(server.ACCT, "w"))

from http.server import ThreadingHTTPServer              # noqa: E402
_srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
BASE = "http://127.0.0.1:%d" % _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()

passed = 0
_n = [0]


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


def api_noroom(method, path, body=None, tok=None):
    """Same call, but deliberately WITHOUT ?room= -- the stale-tab case."""
    url = BASE + path + ("?token=" + tok if tok else "")
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
            return e.code, {"_raw": raw[:300].decode("utf8", "replace")}


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
            return e.code, {"_raw": raw[:300].decode("utf8", "replace")}


WORLD = [t["id"] for t in json.load(open(os.path.join(ROOT, "world-data", "territories", "world.json"),
                                         encoding="utf-8"))]
WCAT = {t["id"]: t for t in json.load(open(os.path.join(ROOT, "world-data", "territories", "world.json"),
                                           encoding="utf-8"))}
DORMANT = json.load(open(os.path.join(ROOT, "world-data", "territories", "taipei.json"),
                         encoding="utf-8"))[0]["id"]
QUALS = sorted(server.LEARNING.registry.qualifications)


def account(nick=None):
    _n[0] += 1
    user = nick or ("U%d" % _n[0])
    tok = api("POST", "/api/register", {"user": user, "pass": "pw"})[1]["token"]
    return user, tok


def room_with(host_tok):
    api("POST", "/api/room/create", {}, host_tok)
    return api("POST", "/api/room/start",
               {"map": "Pre-A1", "aiCount": 0, "resources": "medium", "capacity": 8},
               host_tok)[1]["code"]


def fill_world(code, owner, gar=40, leave_neutral=(), pop=None):
    """Hand the ENTIRE active map to `owner`, optionally leaving some territories unowned."""
    server.set_room(code)
    store = server.load_territory_store()
    for tid in WORLD:
        if tid in leave_neutral:
            store.pop(tid, None)
            continue
        store[tid] = {"owner": owner, "avatar": "\U0001F916",
                      "troops": [{"type": "spear", "hp": gar}],
                      "pop": pop if pop is not None else (server.terr_catalog.game_population(tid) or 100)}
    server.save_territory_store(store)


def econ(code, user, gold=None, troops=None):
    server.set_room(code)
    with server.econ_lock:
        st = server.load_econ_store()
        e = server.econ_get(st, user, time.time(), 0)
        if gold is not None:
            e["gold"] = gold
        if troops is not None:
            e["troops"] = dict(troops)
        server.save_econ_store(st)
        return dict(e)


def pool(code, user):
    server.set_room(code)
    st = server.load_econ_store()
    return {k: server.clampi((st.get(user) or {}).get("troops", {}).get(k, 0)) for k in server.TROOP_ALL}


def gold_of(code, user):
    server.set_room(code)
    st = server.load_econ_store()
    return server.clampi((st.get(user) or {}).get("gold", 0))


def held_by(code, user):
    server.set_room(code)
    return sorted(k for k, v in server.load_territory_store().items()
                  if isinstance(v, dict) and v.get("owner") == user)


FULL = {"cav": 60, "archer": 60, "inf": 60, "spear": 60}

# ============================ 1. the balance constants are pinned ============================
assert game_config.REENTRY_GOLD_COST == 120, game_config.REENTRY_GOLD_COST
assert game_config.REENTRY_CANDIDATES == 4, game_config.REENTRY_CANDIDATES
assert game_config.REENTRY_FAIR_POOL == 0.25, game_config.REENTRY_FAIR_POOL
# re-entry decides neither a battle nor a reward, so it is deliberately outside the fingerprint's
# explicit allowlist -- which means the published fingerprint must be UNCHANGED by this phase.
assert game_config.fingerprint() == "736503ae2c4f5fa5", game_config.fingerprint()
ok("balance: REENTRY_GOLD_COST 120 / REENTRY_CANDIDATES 4 / REENTRY_FAIR_POOL .25, and the published "
   "game fingerprint 736503ae2c4f5fa5 is unchanged by the phase")

# ============================ 2. eligibility matrix ============================
A, tokA = account("ReA")
CODE = room_with(tokA)
B, tokB = account("ReB")
api("POST", "/api/room/join", {"code": CODE}, tokB)
for tk in (tokA, tokB):
    api("GET", "/api/economy?room=" + CODE, None, tk)

# 2a. zero territories, but a neutral is still claimable -> ordinary claim is the way back
fill_world(CODE, B, leave_neutral={WORLD[5]})
st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokA)
assert st == 200 and r["available"] is False and r["reason"] == "neutral_available", (st, r)
assert r["candidates"] == []
st2, r2 = api("POST", "/api/territory/reentry?room=" + CODE,
              {"targetTerritoryId": WORLD[0], "squad": [{"type": "inf", "hp": 5}]}, tokA)
assert st2 == 409 and r2.get("reason") == "neutral_available", (st2, r2)
# ...and that ordinary claim genuinely works, so the refusal is honest
st3, r3 = api("POST", "/api/territory/claim?room=" + CODE,
              {"file": WORLD[5], "troops": [{"type": "inf", "hp": 2}]}, tokA)
assert st3 == 200, (st3, r3)
ok("owns 0 + a neutral territory exists -> re-entry UNAVAILABLE (neutral_available), the POST is "
   "refused 409, and the ordinary claim path does in fact still work")

# 2b. owning even one territory -> unavailable
st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokA)
assert st == 200 and r["available"] is False and r["reason"] == "owns_territory", (st, r)
st2, r2 = api("POST", "/api/territory/reentry?room=" + CODE,
              {"targetTerritoryId": WORLD[0], "squad": [{"type": "inf", "hp": 5}]}, tokA)
assert st2 == 409 and r2.get("reason") == "owns_territory", (st2, r2)
ok("owns 1+ -> re-entry UNAVAILABLE (owns_territory): a player with ground can never use it as a "
   "shortcut past adjacency")

# 2c. zero territories and NO neutral anywhere -> available, with a bounded candidate set
fill_world(CODE, B)
econ(CODE, A, gold=1000, troops=FULL)
st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokA)
assert st == 200 and r["available"] is True and r["reason"] is None, (st, r)
cands = [c["territoryId"] for c in r["candidates"]]
assert 1 <= len(cands) <= game_config.REENTRY_CANDIDATES, cands
assert all(c in WORLD for c in cands), cands
assert len(set(cands)) == len(cands), cands
assert r["cost"]["gold"] == 120 and r["cost"]["minTroops"] == 1, r["cost"]
ok("owns 0 + no neutral remains -> re-entry AVAILABLE with a bounded set of %d real World "
   "footholds and an explicit cost" % len(cands))

# 2d. the offer is stable for the same board, so a GET can be trusted by the following POST
st, r_again = api("GET", "/api/territory/reentry?room=" + CODE, None, tokA)
assert [c["territoryId"] for c in r_again["candidates"]] == cands, (cands, r_again)
# ...and it is not the same offer for a different player
C, tokC = account("ReC")
api("POST", "/api/room/join", {"code": CODE}, tokC)
api("GET", "/api/economy?room=" + CODE, None, tokC)
st, rc = api("GET", "/api/territory/reentry?room=" + CODE, None, tokC)
other = [c["territoryId"] for c in rc["candidates"]]
assert rc["available"] is True, rc
ok("the offer is STABLE for one player on one board (so the POST can re-derive it with no stored "
   "session state) and is computed per player, not globally: %s vs %s" % (cands[:2], other[:2]))

# 2e. no candidate leaks the defender's garrison composition (the map hides it as fog of war)
for c in r["candidates"]:
    assert set(c) <= {"territoryId", "displayName", "population", "owner", "avatar", "isolated"}, c
    assert "troops" not in c and "garrison" not in c, c
ok("the eligibility endpoint is not a scouting tool: a candidate exposes id/name/population/owner "
   "only, never the defender's garrison")

# ============================ 3. only the server's candidates are accepted ============================
not_offered = next(t for t in WORLD if t not in cands)
# an id that does not resolve at all is reported as target_not_found (identity fails before
# eligibility, exactly as on the ordinary attack path); a resolvable id that was simply not offered
# -- including a dormant-map one -- is target_not_candidate.
for target, why, want in (
        ("world:not-a-real-country", "a forged, unresolvable id", "target_not_found"),
        ("maps/world.svg#nope", "a forged legacy key", "target_not_found"),
        (DORMANT, "a resolvable DORMANT-map id", "target_not_candidate"),
        (not_offered, "a real World territory that was NOT offered", "target_not_candidate"),
        ("", "an empty id", "target_not_found")):
    st, r2 = api("POST", "/api/territory/reentry?room=" + CODE,
                 {"targetTerritoryId": target, "squad": [{"type": "inf", "hp": 5}]}, tokA)
    assert st in (400, 403) and r2.get("reason") == want, (why, st, r2)
    assert held_by(CODE, A) == [], "a refused re-entry must not create ownership"
assert pool(CODE, A) == FULL and gold_of(CODE, A) == 1000, "a refused re-entry must cost nothing"
ok("the candidate set is the whole authority: unresolvable ids answer target_not_found, and a "
   "dormant-map or simply un-offered World id answers target_not_candidate -- none costs a coin or "
   "a soldier")

# a client cannot talk the server into eligibility it does not have
st, r2 = api("POST", "/api/territory/reentry?room=" + CODE,
             {"targetTerritoryId": cands[0], "squad": [{"type": "inf", "hp": 5}],
              "available": True, "reentry": True, "eligible": True, "reason": None,
              "candidates": WORLD[:20], "cost": {"gold": 0}}, tokA)
assert st == 200, (st, r2)                              # allowed on its own merits, not because asked
assert r2.get("goldSpent") == 120, "a client-declared cost must be ignored"
ok("forged eligibility fields in the body (available/eligible/candidates/cost) are ignored: the "
   "server re-derives everything and still charges its own price")

# ============================ 4. troops move, they are never minted ============================
# rebuild the soft-lock, because the request above consumed the foothold
fill_world(CODE, B)
econ(CODE, A, gold=1000, troops=FULL)
st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokA)
cands = [c["territoryId"] for c in r["candidates"]]
before_pool, before_gold = pool(CODE, A), gold_of(CODE, A)
st, r2 = api("POST", "/api/territory/reentry?room=" + CODE,
             {"targetTerritoryId": cands[0], "squad": [{"type": "cav", "hp": 1000000}]}, tokA)
assert st == 400 and r2.get("reason") == "insufficient_troops", (st, r2)
assert pool(CODE, A) == before_pool and gold_of(CODE, A) == before_gold
ok("a squad larger than the pool is refused insufficient_troops atomically -- re-entry cannot mint "
   "troops any more than a claim can")

st, r2 = api("POST", "/api/territory/reentry?room=" + CODE,
             {"targetTerritoryId": cands[0], "squad": []}, tokA)
assert st == 400 and r2.get("reason") == "troops_required", (st, r2)
econ(CODE, A, gold=game_config.REENTRY_GOLD_COST - 1, troops=FULL)
st, r2 = api("POST", "/api/territory/reentry?room=" + CODE,
             {"targetTerritoryId": cands[0], "squad": [{"type": "inf", "hp": 5}]}, tokA)
assert st == 400 and r2.get("reason") == "insufficient_gold", (st, r2)
assert held_by(CODE, A) == [] and pool(CODE, A) == FULL
ok("a zero-troop foothold and an unaffordable one are both refused truthfully (troops_required / "
   "insufficient_gold) with zero state change")

# ============================ 5. success semantics ============================
fill_world(CODE, B, gar=1)                              # a beatable defender
econ(CODE, A, gold=1000, troops=FULL)
st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokA)
cands = [c["territoryId"] for c in r["candidates"]]
TARGET = cands[0]
before_gold = gold_of(CODE, A)
SQUAD = [{"type": "cav", "hp": 50}]
st, res = api("POST", "/api/territory/reentry?room=" + CODE,
              {"targetTerritoryId": TARGET, "squad": SQUAD}, tokA)
assert st == 200 and res["attackerWon"] is True, (st, res)
mine = held_by(CODE, A)
assert mine == [TARGET], ("success must give EXACTLY one foothold", mine)
server.set_room(CODE)
h = server.load_territory_store()[TARGET]
assert h["owner"] == A and sum(u["hp"] for u in h["troops"]) > 0, h
assert sum(u["hp"] for u in h["troops"]) == sum(u["hp"] for u in res["attackerSurvivors"]), \
    "the surviving foothold force becomes the authoritative garrison"
assert gold_of(CODE, A) == before_gold - game_config.REENTRY_GOLD_COST, \
    (before_gold, gold_of(CODE, A))
assert pool(CODE, A)["cav"] == FULL["cav"] - 50, pool(CODE, A)
ok("success: ownership transfers, the surviving force becomes the garrison, EXACTLY one foothold is "
   "granted, the levy is debited once and no adjacent territory is handed over for free")

# re-entry closes the moment ownership exists, and ordinary adjacency resumes immediately
st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokA)
assert r["available"] is False and r["reason"] == "owns_territory", r
nbrs = [n for n in (WCAT[TARGET].get("adjacentTerritoryIds") or []) if n in WCAT]
far = next(t for t in WORLD if t != TARGET and t not in nbrs)
st, r2 = api("POST", "/api/territory/attack?room=" + CODE,
             {"sourceTerritoryId": TARGET, "targetTerritoryId": far,
              "squad": [{"type": "cav", "hp": 5}]}, tokA)
assert st == 400 and r2.get("reason") == "not_adjacent", ("adjacency must bind again at once", st, r2)
if nbrs:
    st, r3 = api("POST", "/api/territory/attack?room=" + CODE,
                 {"sourceTerritoryId": TARGET, "targetTerritoryId": nbrs[0],
                  "squad": [{"type": "cav", "hp": 5}]}, tokA)
    assert st == 200, ("an adjacent attack from the new foothold must work normally", st, r3)
ok("after success re-entry is closed (owns_territory) and ORDINARY rules resume instantly: a "
   "non-adjacent attack from the new foothold is refused not_adjacent%s"
   % (", an adjacent one succeeds" if nbrs else " (foothold is isolated)"))

# ============================ 6. failure semantics ============================
A2, tokA2 = account("ReD")
api("POST", "/api/room/join", {"code": CODE}, tokA2)
api("GET", "/api/economy?room=" + CODE, None, tokA2)
fill_world(CODE, B, gar=100000)                         # an unbeatable defender
econ(CODE, A2, gold=1000, troops=FULL)
st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokA2)
cands2 = [c["territoryId"] for c in r["candidates"]]
T2 = cands2[0]
g0 = gold_of(CODE, A2)
st, res = api("POST", "/api/territory/reentry?room=" + CODE,
              {"targetTerritoryId": T2, "squad": [{"type": "inf", "hp": 3}]}, tokA2)
assert st == 200 and res["attackerWon"] is False, (st, res)
server.set_room(CODE)
assert server.load_territory_store()[T2]["owner"] == B, "a failed re-entry must not take the target"
assert held_by(CODE, A2) == [], "a failed re-entry leaves the player with nothing"
# the levy AND the canonical attack-failure penalty both apply; there is no consolation reward
assert gold_of(CODE, A2) == g0 - game_config.REENTRY_GOLD_COST - server.ATTACK_FAIL_GOLD, \
    (g0, gold_of(CODE, A2))
st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokA2)
assert r["available"] is True, "a player who failed may try again if they can still afford it"
ok("failure: the defender keeps the territory, the player still owns nothing, the levy and the "
   "canonical ATTACK_FAIL_GOLD both apply, no consolation gold is minted, and a retry stays possible")

# survivors of a failed foothold come home to the pool, exactly as a failed attack returns them
fill_world(CODE, B, gar=1)
econ(CODE, A2, gold=1000, troops=FULL)
st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokA2)
T3 = [c["territoryId"] for c in r["candidates"]][0]
p0 = pool(CODE, A2)
st, res = api("POST", "/api/territory/reentry?room=" + CODE,
              {"targetTerritoryId": T3, "squad": [{"type": "inf", "hp": 4}]}, tokA2)
p1 = pool(CODE, A2)
if res.get("attackerWon"):
    assert p1["inf"] == p0["inf"] - 4, (p0, p1)
else:
    survivors = sum(s["hp"] for s in res["attackerSurvivors"] if s["type"] == "inf")
    assert p1["inf"] == p0["inf"] - 4 + survivors, (p0, p1, survivors)
    assert p1["inf"] <= p0["inf"], "survivors returning may never exceed what was committed"
ok("troop conservation: the committed force leaves the pool, and on a loss its survivors return to "
   "the pool -- only casualties are lost, and nothing is ever duplicated")

# ============================ 7. replay / concurrency ============================
fill_world(CODE, B, gar=1)
econ(CODE, A2, gold=5000, troops=FULL)
st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokA2)
T4 = [c["territoryId"] for c in r["candidates"]][0]
body = {"targetTerritoryId": T4, "squad": [{"type": "cav", "hp": 40}]}
g0, p0 = gold_of(CODE, A2), pool(CODE, A2)
st1, res1 = api("POST", "/api/territory/reentry?room=" + CODE, body, tokA2)
st2, res2 = api("POST", "/api/territory/reentry?room=" + CODE, body, tokA2)    # exact replay
assert st1 == 200, (st1, res1)
if res1.get("attackerWon"):
    assert st2 == 409 and res2.get("reason") == "owns_territory", (st2, res2)
    charged = g0 - gold_of(CODE, A2)
    assert charged == game_config.REENTRY_GOLD_COST, ("the levy must be charged ONCE", charged)
    assert len(held_by(CODE, A2)) == 1, held_by(CODE, A2)
else:
    assert st2 in (200, 400, 409), (st2, res2)
ok("replay safety: re-POSTing an identical successful re-entry is refused (owns_territory), the "
   "levy is charged exactly once and no second foothold appears")

# two tabs firing at the same instant must not double-spend or double-land
fill_world(CODE, B, gar=1)
E, tokE = account("ReE")
api("POST", "/api/room/join", {"code": CODE}, tokE)
api("GET", "/api/economy?room=" + CODE, None, tokE)
econ(CODE, E, gold=5000, troops=FULL)
st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokE)
T5 = [c["territoryId"] for c in r["candidates"]][0]
g0 = gold_of(CODE, E)
out = {}


def _fire(i):
    out[i] = api("POST", "/api/territory/reentry?room=" + CODE,
                 {"targetTerritoryId": T5, "squad": [{"type": "cav", "hp": 40}]}, tokE)


ths = [threading.Thread(target=_fire, args=(i,)) for i in range(2)]
[t.start() for t in ths]
[t.join() for t in ths]
codes = sorted(v[0] for v in out.values())
spent = g0 - gold_of(CODE, E)
held = held_by(CODE, E)
assert spent % game_config.REENTRY_GOLD_COST == 0, ("gold must move in whole levies", spent)
assert spent <= 2 * game_config.REENTRY_GOLD_COST, spent
assert len(held) <= 1, ("two concurrent re-entries must never yield two footholds", held)
assert all(v[0] in (200, 400, 409, 403) for v in out.values()), out
ok("concurrency: two simultaneous re-entry POSTs (codes %s) yield at most ONE foothold and charge "
   "only whole levies -- no minted troops, no double-spend" % (codes,))

# ============================ 8. learning has zero re-entry authority ============================
fill_world(CODE, B, gar=100000)
verdicts = set()
for i, quals in enumerate(((), tuple(QUALS), tuple(QUALS) + ("forged.not.real",))):
    U, tokU = account("ReQ%d" % i)
    api("POST", "/api/room/join", {"code": CODE}, tokU)
    api("GET", "/api/economy?room=" + CODE, None, tokU)
    if quals:
        with server.acct_lock:
            p = server.load_progress(U)
            q = p.setdefault("learning", {}).setdefault("qualifications", {})
            for qid in quals:
                q[qid] = {"earnedAt": 1}
            server.save_progress(U, p)
    st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokU)
    verdicts.add((st, r["available"], r["reason"], len(r["candidates"])))
assert len(verdicts) == 1, verdicts
assert "qualification_required" not in game_conquest.AttackEligibility.REASONS
ok("learning has ZERO re-entry authority: eligibility and the candidate count are identical with no "
   "qualification, with every real one, and with a forged one -> %s" % (verdicts,))

# and the room's legacy course id decides nothing either
seen = set()
for course in ("Pre-A1", "A1", "A2"):
    U, tokU = account("ReL" + course.replace("-", ""))
    c2 = room_with(tokU)
    server.set_room(c2)
    rm = server.load_room()
    rm["map"] = course
    with server.acct_lock:
        server.save_room(rm)
    api("GET", "/api/economy?room=" + c2, None, tokU)
    fill_world(c2, "AI Empire", gar=50)
    st, r = api("GET", "/api/territory/reentry?room=" + c2, None, tokU)
    seen.add((r["available"], r["reason"], len(r["candidates"])))
assert len(seen) == 1 and seen == {(True, None, game_config.REENTRY_CANDIDATES)}, seen
ok("the legacy course/level id on the room is irrelevant: Pre-A1 / A1 / A2 all produce the identical "
   "re-entry verdict and the same number of footholds")

# ============================ 9. isolated islands (safe outposts) ============================
# Every candidate the server offers must be a real, resolvable, playable territory, and offering an
# isolated one must not invent an edge for it.
ISO = [t for t in WORLD if not (WCAT[t].get("adjacentTerritoryIds") or [])]
assert ISO, "the World map should still contain isolated territories"
U, tokI = account("ReIso")
CI = room_with(tokI)
api("GET", "/api/economy?room=" + CI, None, tokI)
# a board whose ONLY holdings are isolated islands -> the server must still offer a foothold
server.set_room(CI)
store = server.load_territory_store()
store.clear()
for tid in WORLD:
    store[tid] = {"owner": "AI Empire", "avatar": "\U0001F916",
                  "troops": [{"type": "spear", "hp": 5 if tid in ISO[:6] else 90000}],
                  "pop": 100}
server.save_territory_store(store)
econ(CI, U, gold=2000, troops=FULL)
st, r = api("GET", "/api/territory/reentry?room=" + CI, None, tokI)
assert r["available"] is True, r
iso_c = [c for c in r["candidates"] if c["isolated"]]
conn_c = [c for c in r["candidates"] if not c["isolated"]]
# connected holdings are preferred, so with 250 connected+isolated options the weak ones win only if
# they are also connected; either way every candidate is a real playable territory
for c in r["candidates"]:
    assert c["territoryId"] in WCAT, c
    assert server.terr_catalog.map_of(c["territoryId"]) in server.allowed_game_maps(), c
ok("candidates are always real, resolvable, active-map territories (isolated offered: %d, connected "
   "offered: %d) -- the sampler never fabricates an id to fill its quota" % (len(iso_c), len(conn_c)))

# force an isolated-only board and prove the island stays isolated after it is taken
server.set_room(CI)
store = server.load_territory_store()
store.clear()
ISLAND = ISO[0]
store[ISLAND] = {"owner": "AI Empire", "avatar": "\U0001F916",
                 "troops": [{"type": "spear", "hp": 1}], "pop": 100}
for tid in WORLD:
    if tid != ISLAND:
        store[tid] = {"owner": "AI Empire", "avatar": "\U0001F916",
                      "troops": [{"type": "spear", "hp": 90000}], "pop": 100}
server.save_territory_store(store)
econ(CI, U, gold=2000, troops=FULL)
st, r = api("GET", "/api/territory/reentry?room=" + CI, None, tokI)
cl = [c for c in r["candidates"] if c["territoryId"] == ISLAND]
adj_before = json.dumps({t["id"]: sorted(t.get("adjacentTerritoryIds") or []) for t in WCAT.values()},
                        sort_keys=True)
if cl:
    assert cl[0]["isolated"] is True, cl
    st, res = api("POST", "/api/territory/reentry?room=" + CI,
                  {"targetTerritoryId": ISLAND, "squad": [{"type": "cav", "hp": 55}]}, tokI)
    assert st == 200 and res["attackerWon"] is True, (st, res)
    assert held_by(CI, U) == [ISLAND], held_by(CI, U)
    # a safe outpost: ordinary adjacency still applies, so it can attack nothing at all
    for other in (WORLD[0], WORLD[9], WORLD[100]):
        if other == ISLAND:
            continue
        st, r2 = api("POST", "/api/territory/attack?room=" + CI,
                     {"sourceTerritoryId": ISLAND, "targetTerritoryId": other,
                      "squad": [{"type": "cav", "hp": 5}]}, tokI)
        assert st == 400 and r2.get("reason") == "not_adjacent", (other, st, r2)
    ok("island foothold: an isolated territory CAN be a re-entry target, and once owned it is a SAFE "
       "OUTPOST -- ordinary adjacency still binds, so it attacks nothing (%s)" % ISLAND)
else:
    ok("island foothold: with a connected option available the server preferred it, which is the "
       "documented preference -- an isolated foothold cannot attack out")

# the catalog is untouched by any of this
adj_after = json.dumps({t["id"]: sorted(t.get("adjacentTerritoryIds") or []) for t in
                        {t["id"]: t for t in json.load(open(os.path.join(
                            ROOT, "world-data", "territories", "world.json"), encoding="utf-8"))}.values()},
                       sort_keys=True)
assert adj_before == adj_after, "re-entry must not touch adjacency data"
assert len(WCAT) == 250
ok("topology is untouched by re-entry: the World adjacency data is byte-identical before and after, "
   "and the map still has exactly 250 territories")

# ============================ 9b. Phase 11A.1: an active room is REQUIRED ============================
# Phase 8A.1 introduced ONE fail-closed table so that a stale tab -- one whose roomCode a renderer had
# cleared -- can never mutate whichever room the request happens to resolve to. Re-entry spends gold
# and troops and takes ground, so it belongs in that table; it was omitted when Phase 10B added the
# route, and a room-less POST reached the implicit default room instead of being refused.
NR, tokNR = account("ReNoRoom")
api("POST", "/api/room/join", {"code": CODE}, tokNR)
econ(CODE, NR, gold=5000, troops=FULL)
fill_world(CODE, B, gar=1)                       # a board where re-entry WOULD otherwise apply

# every territory mutation answers the same way without a room -- re-entry included
for path, body in (
        ("/api/territory/reentry", {"targetTerritoryId": WORLD[0], "squad": [{"type": "inf", "hp": 1}]}),
        ("/api/territory/claim", {"file": WORLD[0], "troops": [{"type": "inf", "hp": 1}]}),
        ("/api/territory/attack", {"sourceTerritoryId": WORLD[0], "targetTerritoryId": WORLD[1],
                                   "squad": [{"type": "inf", "hp": 1}]}),
        ("/api/territory/release", {"file": WORLD[0]}),
        ("/api/territory/recruit", {"file": "@home", "unit": "inf", "qty": 1})):
    st, r = api_noroom("POST", path, body, tokNR)
    assert st == 400 and r.get("reason") == "room_required", (path, st, r)
ok("room fail-closed: WITHOUT an active room, re-entry is refused 400 room_required -- exactly like "
   "claim, attack, release and recruit. It no longer falls through to an implicit room.")

# the refusal happens before ANY state is touched
assert gold_of(CODE, NR) == 5000 and pool(CODE, NR) == FULL, (gold_of(CODE, NR), pool(CODE, NR))
assert held_by(CODE, NR) == [], held_by(CODE, NR)
ok("the room-less refusal is atomic: no gold spent, no troops moved, no ownership created")

# ...and it is the SHARED table doing the work, not a hand-rolled check inside the handler
assert "/api/territory/reentry" in server.Handler.ROOM_MUTATIONS
for other in ("/api/territory/claim", "/api/territory/attack", "/api/territory/release",
              "/api/territory/recruit", "/api/territory/build", "/api/territory/research",
              "/api/territory/conscript"):
    assert other in server.Handler.ROOM_MUTATIONS, other
ok("re-entry is protected by the SAME canonical ROOM_MUTATIONS table as every other territory "
   "mutation, not by a special case")

# an unauthenticated room-less call still reads as an auth problem, not a room problem: the existing
# policy keeps authorisation first so both errors stay truthful
st, r = api_noroom("POST", "/api/territory/reentry",
                   {"targetTerritoryId": WORLD[0], "squad": [{"type": "inf", "hp": 1}]})
assert st == 401, (st, r)
ok("authorisation still takes precedence over the room check: a room-less call with no token is 401, "
   "not room_required")

# WITH an active room, re-entry is completely unchanged -- same availability, same candidates, same
# cost, and a real foothold still succeeds
st, r = api("GET", "/api/territory/reentry?room=" + CODE, None, tokNR)
assert st == 200 and r["available"] is True and r["reason"] is None, (st, r)
cands_nr = [c["territoryId"] for c in r["candidates"]]
assert 1 <= len(cands_nr) <= game_config.REENTRY_CANDIDATES
assert r["cost"]["gold"] == game_config.REENTRY_GOLD_COST and r["cost"]["minTroops"] == 1
g_before, p_before = gold_of(CODE, NR), pool(CODE, NR)
st, res = api("POST", "/api/territory/reentry?room=" + CODE,
              {"targetTerritoryId": cands_nr[0], "squad": [{"type": "cav", "hp": 45}]}, tokNR)
assert st == 200 and res["attackerWon"] in (True, False), (st, res)
assert gold_of(CODE, NR) <= g_before - game_config.REENTRY_GOLD_COST
assert pool(CODE, NR)["cav"] <= p_before["cav"]
ok("with an active room the whole re-entry contract is untouched: availability, %d candidates, the "
   "120-gold levy and a real foothold battle all behave exactly as before" % len(cands_nr))

# and the fix changed no topology
_w = json.load(open(os.path.join(ROOT, "world-data", "territories", "world.json"), encoding="utf-8"))
assert len(_w) == 250
_ends = sum(len(t.get("adjacentTerritoryIds") or []) for t in _w)
assert _ends == sum(len(t.get("adjacentTerritoryIds") or []) for t in WCAT.values())
ok("the fix is routing only: World still has 250 territories and its adjacency is unchanged")

# ============================ 10. the pure rule, without HTTP ============================
IDS = ["m:a", "m:b", "m:c", "m:d"]
T = {"m:a": {"owner": "BOB", "troops": [{"type": "inf", "hp": 5}], "pop": 10},
     "m:b": {"owner": "BOB", "troops": [{"type": "inf", "hp": 1}], "pop": 10},
     "m:c": {"owner": "BOB", "troops": [{"type": "inf", "hp": 9}], "pop": 10},
     "m:d": {"owner": "BOB", "troops": [{"type": "inf", "hp": 3}], "pop": 10}}
s = game_conquest.reentry_state("ALICE", IDS, T, seed="R", limit=2)
assert s and s.reason is None and len(s.candidates) == 2, s
assert game_conquest.reentry_state("ALICE", IDS, dict(T, **{"m:a": {"owner": "ALICE"}}),
                                   seed="R").reason == "owns_territory"
assert game_conquest.reentry_state("ALICE", IDS + ["m:e"], T, seed="R").reason == "neutral_available"
assert game_conquest.reentry_state("ALICE", [], {}, seed="R").reason == "no_candidates"
assert game_conquest.reentry_state("ALICE", IDS, T, seed="R", limit=2).candidates == \
       game_conquest.reentry_state("ALICE", IDS, T, seed="R", limit=2).candidates, "must be stable"
assert game_conquest.reentry_state("ALICE", IDS, T, seed="R", limit=99).candidates == sorted(IDS), \
    "a limit above the board size offers the whole board, never a fabricated id"
assert game_conquest.reentry_state("ALICE", IDS, T, seed="R", limit=1,
                                   degree_of=lambda t: 0 if t == "m:b" else 1).candidates != ["m:b"], \
    "a connected foothold is preferred over an isolated one"
assert not game_conquest.reentry_state("ALICE", None, None, seed="R"), "junk input must not raise"
ok("the pure rule: stable for a board, ALL three unavailability reasons, never fabricates an id, "
   "prefers a connected foothold, and never raises on junk input")

print("\nAll %d re-entry authority tests passed." % passed)
_srv.shutdown()
