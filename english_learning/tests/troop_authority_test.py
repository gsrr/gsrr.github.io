#!/usr/bin/env python3
"""Phase 8B.1 — troop provisioning is SERVER-AUTHORITATIVE.

    python3 tests/troop_authority_test.py

Before this phase a client could declare troops into existence two ways: POST
/api/economy/set wrote the authoritative pool straight from the request body
(4,000,000 troops for 0 gold), and /api/territory/claim accepted any garrison
without debiting anything. UNIT_COST therefore constrained nobody.

The invariant proved here: a troop may only enter play through server-side
recruitment that debited UNIT_COST gold, and a garrison may only MOVE troops out
of the authoritative pool. Conservation is checked PER TYPE, not just in total.
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request as U

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402
from game import config as GC  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


# ---------------- isolated server ----------------
import tempfile  # noqa: E402

d = tempfile.mkdtemp()
server.ROOMS_DIR = os.path.join(d, "rooms")
server.ACCT = os.path.join(d, "accounts.json")
server.PROG_DIR = os.path.join(d, "progress")
server.DATA = os.path.join(d, "visits.json")
server.TERR_CATALOG = os.path.join(d, "learned.json")
server.LEARNING.content_root = ROOT
json.dump({"users": {"ALICE": {"code": "TROOP"}}, "codes": {"TROOP": "ALICE"}}, open(server.ACCT, "w"))
server._tokens["tALICE"] = {"user": "ALICE", "exp": time.time() + 9999, "admin": False}
from http.server import ThreadingHTTPServer  # noqa: E402

srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
B = "http://127.0.0.1:%d" % srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


def call(method, path, body=None, tok="tALICE"):
    url = B + path + ("&" if "?" in path else "?") + "token=" + tok
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = U.urlopen(U.Request(url, data=data, method=method))
        return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


call("POST", "/api/room/create", {})
CODE = call("POST", "/api/room/start", {"map": "Pre-A1", "aiCount": 0,
                                        "resources": "medium", "capacity": 4})[1]["code"]
R = "?room=" + CODE
call("GET", "/api/economy" + R)                      # materialise the economy row

ZOO = json.load(open(os.path.join(ROOT, "Pre-A1", "taipei", "zoo.json"), encoding="utf-8"))
QUIZ3 = [{"q": i["q"], "answer": i["answer"]} for i in ZOO["quiz3"]]
# Phase 10A.3R: no territory is learning-gated any more, so these are simply two neutral
# active-map territories. Two distinct subjects are still needed so that claiming one cannot be
# confused with claiming the other.
TARGET = "world:af"
OTHER = "world:tm"
TYPES = ("cav", "archer", "inf", "spear")


def pool():
    server.set_room(CODE)
    e = server.load_econ_store().get("ALICE") or {}
    return {k: int((e.get("troops") or {}).get(k, 0)) for k in TYPES}


def gold():
    server.set_room(CODE)
    return int((server.load_econ_store().get("ALICE") or {}).get("gold", 0))


def garrisons():
    """{type: total} across every territory ALICE owns."""
    server.set_room(CODE)
    out = {k: 0 for k in TYPES}
    for h in server.load_territory_store().values():
        if isinstance(h, dict) and h.get("owner") == "ALICE":
            for u in (h.get("troops") or []):
                if u.get("type") in out:
                    out[u["type"]] += int(u.get("hp", 0))
    return out


def total():
    p, g = pool(), garrisons()
    return {k: p[k] + g[k] for k in TYPES}


def claim(key, troops):
    return call("POST", "/api/territory/claim" + R, {"file": key, "troops": troops})


# ====================== §1 /api/economy/set may not declare troops ======================
base = pool()
for forged in ({"cav": 999999, "archer": 999999, "inf": 999999, "spear": 999999},
               {"inf": 10 ** 9}, 500000, "lots", None, [], {"cav": -5}, {"bogus": 10}):
    code, _ = call("POST", "/api/economy/set" + R, {"troops": forged})
    assert code == 200, (forged, code)                 # ignored, never a crash
    assert pool() == base, (forged, pool(), base)
assert gold() == 500, gold()
ok("§1 /api/economy/set ignores every client-declared troop value (8 shapes) — pool and gold "
   "unchanged, no crash, no silent creation or destruction")

# ====================== §2 conservation across a claim ======================
call("POST", "/api/learning/attempt" + R,
     {"activityId": "english.prea1.taipei.zoo.quiz3", "answers": QUIZ3})   # qualify + gold
N0 = total()
assert N0 == {"cav": 25, "archer": 25, "inf": 25, "spear": 25}, N0
code, body = claim(TARGET, [{"type": "cav", "hp": 10}, {"type": "inf", "hp": 5}])
assert code == 200, (code, body)
assert pool() == {"cav": 15, "archer": 25, "inf": 20, "spear": 25}, pool()
assert garrisons() == {"cav": 10, "archer": 0, "inf": 5, "spear": 0}, garrisons()
assert total() == N0, (total(), N0)
ok("§2 conservation: a claim MOVES troops — pool+garrisons is identical per type before and after")

# ====================== §3 the forged-garrison exploit is closed ======================
before_pool, before_total = pool(), total()
code, body = claim(OTHER, [{"type": "cav", "hp": 500000}])
assert code == 400 and body["reason"] == "insufficient_troops", (code, body)
assert body["available"]["cav"] == before_pool["cav"], body
assert pool() == before_pool and total() == before_total, (pool(), total())
server.set_room(CODE)
assert OTHER not in server.load_territory_store(), "a refused claim must not create the territory"
ok("§3 a garrison larger than the pool is refused with insufficient_troops — no ownership, no "
   "garrison, no pool change, and NO troops minted")

# ============ §3b Phase 8B.3: ACQUIRING a territory costs at least one troop ============
# Ownership carries the territory's passive income, and it used to be free: an empty (or all-zero)
# garrison claimed a neutral district for 0 troops and 0 gold. The minimum is ONE.
z_pool, z_total, z_gold = pool(), total(), gold()
ZERO = [([], "empty list"),
        ([{"type": "inf", "hp": 0}], "one zero entry"),
        ([{"type": "inf", "hp": 0}, {"type": "cav", "hp": 0}], "several zero entries"),
        ([{"type": "inf", "hp": -5}], "negative sanitised to zero"),
        ([{"type": "inf", "hp": 0.4}], "fraction sanitised to zero"),
        ([{"type": "dragon", "hp": 9}], "only an unknown type -> nothing deployable"),
        ([{"nope": 1}], "only a malformed entry")]
for troops, label in ZERO:
    code, body = call("POST", "/api/territory/claim" + R, {"file": OTHER, "troops": troops})
    assert code == 400 and body.get("reason") == "troops_required", (label, code, body)
    assert body.get("minTroops") == 1, (label, body)
    assert pool() == z_pool and total() == z_total and gold() == z_gold, label
    server.set_room(CODE)
    assert OTHER not in server.load_territory_store(), label
ok("§3b a neutral claim that would deploy ZERO troops is refused with troops_required (%d shapes, "
   "including negatives/fractions/unknown types that sanitise to nothing) — no ownership, no pool "
   "or gold movement" % len(ZERO))

# exactly one troop is enough, of any type, including a mixed request totalling 1
for troops, label, key in (([{"type": "inf", "hp": 1}], "one infantry", OTHER),
                           ([{"type": "cav", "hp": 1}], "one cavalry", "world:kp"),
                           ([{"type": "inf", "hp": 0}, {"type": "spear", "hp": 1}],
                            "mixed request totalling 1", "world:mn")):
    b_pool, b_total = pool(), total()
    code, body = call("POST", "/api/territory/claim" + R, {"file": key, "troops": troops})
    assert code == 200, (label, code, body)
    server.set_room(CODE)
    assert (server.load_territory_store().get(key) or {}).get("owner") == "ALICE", label
    moved = sum(b_pool[k] - pool()[k] for k in TYPES)
    assert moved == 1, (label, b_pool, pool())
    assert total() == b_total, (label, total(), b_total)
    call("POST", "/api/territory/release" + R, {"file": key})      # release destroys that troop
ok("§3b exactly ONE troop acquires a territory — any single type, or a mixed request whose total is "
   "1; the pool drops by exactly 1 and conservation holds")

# RETARGETED (Phase 10A.3R).
#   OLD: a gated territory answered qualification_required BEFORE troops_required, proving the
#        learning gate spoke first.
#   WHY OBSOLETE: learning qualifications no longer gate Conquest at all, so the ordering it pinned
#        cannot occur; there is no qualification_required reason left to order.
#   NEW: troop authority is the ONLY thing that speaks here — the same request answers
#        troops_required whatever the learner holds.
#   WHY NOT WEAKER: it still pins the truthful refusal for a zero-troop claim, and additionally
#        proves that learning state cannot change that verdict, which the old form never checked.
code, body = call("POST", "/api/territory/claim" + R, {"file": "world:cn", "troops": []})
assert code == 400 and body.get("reason") == "troops_required", (code, body)
ok("§3b a zero-troop claim answers troops_required — troop authority is the only gate, and no "
   "learning state can pre-empt or override it")

# (the "gated + qualified + zero troops" case needs a gated territory ALICE does NOT already own —
#  TARGET is hers by now, so that claim would be a redeploy. It is covered in §9 below.)

# ====================== §4 the claim failure matrix ======================
snap_pool, snap_total, snap_gold = pool(), total(), gold()
# Requests that must be REFUSED outright: they ask for more than the pool holds.
OVER = [([{"type": "cav", "hp": snap_pool["cav"] + 1}], "one troop too many"),
        ([{"type": "cav", "hp": 10 ** 9}], "forged huge count"),
        ([{"type": "cav", "hp": snap_pool["cav"]}, {"type": "cav", "hp": 1}], "split over budget")]
for troops, label in OVER:
    code, body = call("POST", "/api/territory/claim" + R, {"file": OTHER, "troops": troops})
    assert code == 400 and body.get("reason") == "insufficient_troops", (label, code, body)
    assert pool() == snap_pool and total() == snap_total and gold() == snap_gold, label
    server.set_room(CODE)
    assert OTHER not in server.load_territory_store(), label
ok("§4 over-budget requests (%d shapes) are refused with insufficient_troops; ownership, garrison, "
   "pool and gold all untouched" % len(OVER))

# Malformed shapes keep their PRE-EXISTING sanitisation (negative/garbage -> 0, unknown type
# dropped). The authority property is what matters: none of them may mint a troop, so whatever
# survives sanitisation is still debited from the pool and conservation still holds.
MALFORMED = [([{"type": "cav", "hp": -5}], "negative count"),
             ([{"type": "dragon", "hp": 5}], "unknown troop type"),
             ([{"nope": 1}], "malformed object"),
             (["cav"], "non-dict entry"),
             ([{"type": "cav", "hp": 2.9}], "fractional count")]
for troops, label in MALFORMED:
    code, body = call("POST", "/api/territory/claim" + R, {"file": OTHER, "troops": troops})
    assert code in (200, 400), (label, code, body)
    assert total() == snap_total, (label, total(), snap_total)      # never mints, never destroys
    assert all(v >= 0 for v in pool().values()), (label, pool())
    if code == 200:                                                 # sanitised claim -> undo it
        call("POST", "/api/territory/release" + R, {"file": OTHER})
        snap_total = total()                                        # release destroys the garrison
ok("§4 malformed troop shapes (%d) keep their existing sanitisation and mint nothing — the total "
   "never rises and the pool never goes negative" % len(MALFORMED))

code, body = call("POST", "/api/territory/claim" + R, {"file": OTHER, "troops": "not-a-list"})
assert code == 400, (code, body)
ok("§4 a non-list troops field is still rejected outright (existing rule preserved)")
snap_pool, snap_total, snap_gold = pool(), total(), gold()

# a claim of exactly the available troops succeeds and empties that type
avail_spear = pool()["spear"]
code, body = claim(OTHER, [{"type": "spear", "hp": avail_spear}])
assert code == 200, (code, body)
assert pool()["spear"] == 0, pool()
assert total() == snap_total, (total(), snap_total)
ok("§4 claiming EXACTLY the available troops succeeds, empties that type and still conserves")

# ====================== §5 redeploy returns the old garrison to the pool ======================
before = total()
code, body = claim(TARGET, [{"type": "cav", "hp": 2}])       # was cav 10 + inf 5
assert code == 200, (code, body)
g = garrisons()
assert g["cav"] == 2 + 0 and g["inf"] == 0, g               # OTHER holds spear only
assert total() == before, (total(), before)
ok("§5 redeploying a held territory returns its garrison to the pool first — conserved, and the "
   "unassigned remainder stays in the pool exactly as before")

# ====================== §6 recruitment is the ONLY way to create troops ======================
g0, p0 = gold(), pool()
code, body = call("POST", "/api/territory/recruit" + R,
                  {"file": server.HOME_KEY, "unit": "cav", "qty": 10})
assert code == 400 and "need" in body.get("error", ""), (code, body)   # no stable yet
assert pool() == p0 and gold() == g0, "a refused recruit changes nothing"
ok("§6 recruiting without the required building is refused (server-held building state) — no "
   "troops, no gold movement")

call("POST", "/api/territory/build" + R, {"file": server.HOME_KEY, "building": "stable"})
g1, p1 = gold(), pool()
code, body = call("POST", "/api/territory/recruit" + R,
                  {"file": server.HOME_KEY, "unit": "cav", "qty": 10})
assert code == 200, (code, body)
assert gold() == g1 - 10 * GC.UNIT_COST["cav"], (gold(), g1)
assert pool()["cav"] == p1["cav"] + 10, (pool(), p1)
ok("§6 recruitment is the sole troop source: 10 cavalry costs exactly 10 x UNIT_COST[cav] = %d "
   "gold and credits exactly 10 to the pool" % (10 * GC.UNIT_COST["cav"]))

# a forged unit price / post-purchase count cannot change the settlement
g2, p2 = gold(), pool()
code, body = call("POST", "/api/territory/recruit" + R,
                  {"file": server.HOME_KEY, "unit": "cav", "qty": 10,
                   "cost": 0, "price": 0, "gold": 999999, "troops": {"cav": 999999}})
assert code == 200, (code, body)
assert gold() == g2 - 10 * GC.UNIT_COST["cav"], (gold(), g2)
assert pool()["cav"] == p2["cav"] + 10, (pool(), p2)
ok("§6 forged cost/price/gold/troops fields in a recruit request are ignored — the server prices "
   "it from UNIT_COST and credits exactly what it sold")

# ====================== §7 recruit cannot outspend the authoritative gold ======================
code, body = call("POST", "/api/territory/recruit" + R,
                  {"file": server.HOME_KEY, "unit": "cav", "qty": 100000})
assert code == 400 and body.get("error") == "not enough gold", (code, body)
assert gold() >= 0, gold()
ok("§7 a recruit beyond the authoritative gold is refused; gold never goes negative")

# ====================== §8 concurrency: two claims racing for the same pool ======================
# terr_lock serialises every claim and the econ debit is nested inside it (acct -> terr -> econ,
# the same order recruitment uses), so the read-check-write of the pool cannot interleave.
call("POST", "/api/territory/release" + R, {"file": OTHER})
call("POST", "/api/territory/release" + R, {"file": TARGET})
server.set_room(CODE)
_st = server.load_econ_store()
_st["ALICE"]["troops"] = {"cav": 100, "archer": 0, "inf": 0, "spear": 0}
server.save_econ_store(_st)
assert pool()["cav"] == 100, pool()

RACE = ["world:pl", "world:ru"]       # both ungated, both neutral
results = {}


def _racer(idx):
    results[idx] = call("POST", "/api/territory/claim" + R,
                        {"file": RACE[idx], "troops": [{"type": "cav", "hp": 80}]})


ths = [threading.Thread(target=_racer, args=(i,)) for i in range(2)]
for t in ths:
    t.start()
for t in ths:
    t.join()
wins = [i for i in results if results[i][0] == 200]
assert len(wins) == 1, ("exactly one 80-of-100 claim may win", results)
loser = [i for i in results if i not in wins][0]
assert results[loser][1].get("reason") == "insufficient_troops", results[loser]
assert pool()["cav"] == 20, pool()
assert total()["cav"] == 100, total()
assert all(v >= 0 for v in pool().values()), pool()
ok("§8 concurrency: two simultaneous claims for 80 of 100 cavalry — exactly one wins, the other "
   "gets insufficient_troops, the pool lands on 20 and 100 cavalry are conserved (no duplication, "
   "no negative pool)")

# ====== §9 Phase 8B.3: the acquisition minimum applies uniformly, and NOT to redeploy ======
# RETARGETED (Phase 10A.3R). OLD: this block took a learning-gated territory, granted the required
# qualification, and proved the troop minimum was the one remaining requirement — i.e. that the two
# requirements composed. WHY OBSOLETE: qualifications are no longer a claim requirement at all.
# NEW: the same territory is claimed while the account holds that qualification anyway, proving the
# troop minimum is the ONLY acquisition requirement and that holding learning credentials neither
# waives it nor adds to it. WHY NOT WEAKER: every assertion below is unchanged; the qualification is
# still granted, so this now also pins that granting it changes nothing.
ACQUIRE = "world:ir"
with server.acct_lock:
    p = server.load_progress("ALICE")
    p.setdefault("learning", {}).setdefault("qualifications", {})[
        "english.prea1.taipei.mrt.quiz3.pass"] = {"earnedAt": 1}
    server.save_progress("ALICE", p)
server.set_room(CODE)
_st = server.load_econ_store()
_st["ALICE"]["troops"] = {"cav": 5, "archer": 0, "inf": 0, "spear": 0}
server.save_econ_store(_st)
code, body = call("POST", "/api/territory/claim" + R, {"file": ACQUIRE, "troops": []})
assert code == 400 and body.get("reason") == "troops_required", (code, body)
server.set_room(CODE)
assert ACQUIRE not in server.load_territory_store(), "a refused claim must not create ownership"
code, body = call("POST", "/api/territory/claim" + R, {"file": ACQUIRE, "troops": [{"type": "cav", "hp": 1}]})
assert code == 200, (code, body)
assert pool()["cav"] == 4, pool()
ok("§9 the acquisition minimum applies uniformly: holding a learning qualification does not "
   "waive it (troops_required on an empty squad), and one cavalry then acquires the territory")

# redeploy KEEPS the documented right to leave your own ground undefended
before = total()
code, body = call("POST", "/api/territory/claim" + R, {"file": ACQUIRE, "troops": []})
assert code == 200, ("owned redeploy to zero must stay legal", code, body)
server.set_room(CODE)
h = server.load_territory_store().get(ACQUIRE) or {}
assert h.get("owner") == "ALICE" and not (h.get("troops") or []), h
assert pool()["cav"] == 5, ("the garrison came home to the pool", pool())
assert total() == before, (total(), before)
ok("§9 redeploying a territory you ALREADY hold to zero troops remains legal — ownership kept, the "
   "garrison returns to the pool, conservation holds; the minimum guards ACQUISITION only")

print("\nAll %d troop-authority tests passed." % passed)
