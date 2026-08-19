"""Phase 10A.3R.1 — claim authority is GAME state only; no client state can buy territory.

    python tests/claim_authority_test.py

This suite used to prove that a learning QUALIFICATION gated a claim: an unqualified client got
403 qualification_required, a qualified one succeeded, multi-requirement territories were
ALL-required, and various forged client states could not substitute for the real credential.

Phase 10A.3R retired that contract. Learning and Game are separate systems: learning awards
progress, mastery, Gold and achievements, and none of it decides who may take ground. So the gate
this file was built around no longer exists.

What survives, and why the suite is not weaker for the change:

  * The FORGERY invariants were never really about qualifications — they were about the server
    refusing to believe client-supplied state. They are kept, retargeted at the World claim verdict:
    a planted `passcnt`, hand-written qualifications, and the retired self-assert endpoint must all
    leave the verdict exactly as it was.

  * The GATE assertions are replaced by something strictly stronger: a zero-effect matrix. The same
    World territory, from identical game state, must give an IDENTICAL verdict with no
    qualification, with forged ones, and with every real one held. The old form proved a specific
    gate behaved; this proves no learning state can influence a claim in any direction — which is
    what actually guards against the coupling coming back.

  * The GAME-side authority checks (ownership mutation, troop requirement, malformed ids, the
    dormant-map rule, replay) are preserved and now run on the active map.
"""
import json, os, sys, tempfile, threading, time
import urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import server
from game import conquest as game_conquest

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

from http.server import ThreadingHTTPServer
_srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
BASE = "http://127.0.0.1:%d" % _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()

passed = 0
_n = [0]


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


def api(method, path, body=None, tok=None):
    url = BASE + path + (("&" if "?" in path else "?") + "token=" + tok if tok else "")
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


# ---- fixtures on the ACTIVE map, resolved from the catalog rather than assumed ----
_W = json.load(open(os.path.join(ROOT, "world-data", "territories", "world.json"), encoding="utf-8"))
_by = {t["id"]: t for t in _W}
TARGET = _W[0]["id"]
OTHER = _W[1]["id"]
DORMANT = json.load(open(os.path.join(ROOT, "world-data", "territories", "taipei.json"),
                         encoding="utf-8"))[0]["id"]
QUALS = sorted(server.LEARNING.registry.qualifications)
assert QUALS, "the registry should still declare learning qualifications (achievements now)"


def fresh(quals=()):
    """A brand-new account in its own room, optionally holding real server-side qualifications."""
    _n[0] += 1
    user = "U%d" % _n[0]
    tok = api("POST", "/api/register", {"user": user, "pass": "pw"})[1]["token"]
    api("POST", "/api/room/create", {}, tok)
    code = api("POST", "/api/room/start",
               {"map": "Pre-A1", "aiCount": 0, "resources": "medium", "capacity": 4},
               tok)[1]["code"]
    api("GET", "/api/economy?room=" + code, None, tok)
    if quals:
        with server.acct_lock:
            p = server.load_progress(user)
            q = p.setdefault("learning", {}).setdefault("qualifications", {})
            for qid in quals:
                q[qid] = {"earnedAt": 1}
            server.save_progress(user, p)
    return user, tok, code


def claim(tok, code, target, troops=None):
    return api("POST", "/api/territory/claim?room=" + code,
               {"file": target,
                "troops": [{"type": "inf", "hp": 10}] if troops is None else troops}, tok)


def owner(code, target):
    server.set_room(code)
    return (server.load_territory_store().get(target) or {}).get("owner")


def verdict(quals=()):
    """Claim TARGET from a brand-new room whose account holds exactly `quals`."""
    user, tok, code = fresh(quals)
    st, r = claim(tok, code, TARGET)
    return (st, r.get("reason") or "ok"), user, code


# ====================== 1. learning qualification has ZERO effect ======================
none_v, u1, c1 = verdict([])
forged_v, u2, c2 = verdict(QUALS + ["forged.qualification.that.does.not.exist"])
real_v, u3, c3 = verdict(QUALS)
assert none_v == forged_v == real_v == (200, "ok"), (none_v, forged_v, real_v)
assert owner(c1, TARGET) == u1 and owner(c3, TARGET) == u3
ok("the SAME World claim gives an IDENTICAL verdict with no qualification, with forged ones, and "
   "with every real one held — learning cannot buy or block ground")

# and the pure rule agrees, from both directions
assert "qualification_required" not in game_conquest.AttackEligibility.REASONS
ok("'qualification_required' is not even a possible Conquest reason any more")

# ====================== 2. forged client state is still worthless ======================
# These were the strongest assertions in the old suite and they survive unchanged in spirit: the
# server believes its own state, never the client's.
user, tok, code = fresh()
server.set_room(code)
es = server.load_econ_store()
es.setdefault(user, {})["passcnt"] = {"Pre-A1/taipei/zoo": 999}
server.save_econ_store(es)
st, r = claim(tok, code, TARGET)
assert st == 200, (st, r)                       # allowed on GAME merit, not because of the counter
server.set_room(code)
assert ((server.load_econ_store().get(user) or {}).get("passcnt") or {}).get("Pre-A1/taipei/zoo") == 999
ok("a hand-planted passcnt in the economy store changes nothing: it neither grants nor blocks a "
   "claim, and the server never consults it")

st, _ = api("POST", "/api/economy/pass", {"file": "Pre-A1/taipei/zoo"}, tok)
assert st == 404, "the endpoint that let a client assert its own passes must stay GONE, got %s" % st
ok("the client-asserted pass endpoint is still retired — no HTTP route lets a client vouch for "
   "itself")

user, tok, code = fresh()
st, r = api("POST", "/api/territory/claim?room=" + code,
            {"file": TARGET, "troops": [{"type": "inf", "hp": 10}],
             "qualifications": QUALS, "qualification": QUALS[0], "passed": True}, tok)
assert st == 200, (st, r)
p = server.load_progress(user)
assert not ((p.get("learning") or {}).get("qualifications") or {}), \
    "a claim body must never write qualifications into authoritative learning state"
ok("qualification fields smuggled into the claim body are ignored and never persisted")

# ====================== 3. game-side claim authority is intact ======================
user, tok, code = fresh()
st, r = claim(tok, code, TARGET, troops=[])
assert st == 400 and r.get("reason") == "troops_required", (st, r)
assert owner(code, TARGET) is None, "a refused claim must not change ownership"
ok("a zero-troop claim is refused troops_required and mutates nothing")

st, r = claim(tok, code, "world:not-a-real-country")
assert st == 400 and r.get("reason") in ("unresolved", "not_in_catalog"), (st, r)
ok("a malformed/unknown territory id is refused truthfully")

# RETAINED FROM THE OLD SUITE. Its "neither a huge forged squad nor a malformed one buys past the
# gate" check carried a second property that had nothing to do with qualifications: an oversized or
# ill-shaped squad must be refused on the server's own figures, atomically. That still holds and is
# asserted here directly rather than left to troop_authority_test.py.
for squad, why in (([{"type": "cav", "hp": 10 ** 9}], "a squad larger than the whole pool"),
                   ([{"type": "bogus", "hp": 5}], "an unknown troop type"),
                   ("not-a-list", "a squad that is not a list")):
    st, r = claim(tok, code, OTHER, troops=squad)
    assert st == 400, (why, st, r)
    # a machine `reason` where the request was well-formed but unaffordable; a plain troop error
    # where the payload itself was the problem. Either way it names troops, never something else.
    assert (r.get("reason") in ("insufficient_troops", "troops_required")
            or "troops" in (r.get("error") or "")), (why, st, r)
    assert owner(code, OTHER) is None, "%s must not create ownership" % why
ok("a forged squad buys nothing: oversized, unknown-type and non-list squads are all refused on the "
   "server's own figures, and none of them creates the territory")

# RETAINED FROM THE OLD SUITE. Its final check proved the shared requirement helper was TOTAL, so a
# world-data fault could never brick claiming. The helper no longer gates anything, but claim's own
# totality is still worth pinning: a catalog whose requirement lookup EXPLODES must not stop an
# otherwise valid claim, because nothing consults it any more.
_orig = server.terr_catalog.attack_requirements


def _boom(_tid):
    raise RuntimeError("world-data unavailable")


server.terr_catalog.attack_requirements = _boom
try:
    user4, tok4, code4 = fresh()
    st, r = claim(tok4, code4, TARGET)
    assert st == 200, ("a raising attack_requirements must not affect a claim", st, r)
    assert owner(code4, TARGET) == user4
finally:
    server.terr_catalog.attack_requirements = _orig
ok("claim is total with respect to requirement metadata: even an attack_requirements that RAISES "
   "cannot block a valid claim, because the claim route never consults it")

st, r = claim(tok, code, DORMANT)
assert st == 400 and r.get("reason") == "inactive_map", (st, r)
assert owner(code, DORMANT) is None
ok("a territory on a dormant (non-active) map is refused inactive_map and mutates nothing")

st, r = claim(tok, code, TARGET)
assert st == 200 and owner(code, TARGET) == user, (st, r)
st2, _ = claim(tok, code, TARGET)
assert owner(code, TARGET) == user, "re-claiming your own territory must not hand it away"
ok("a valid neutral claim takes ownership authoritatively, and re-claiming your own ground is safe")

# a second account cannot take a held territory by claiming it
user2, tok2, code2 = fresh()
server.set_room(code)
st, r = claim(tok2, code, TARGET)
assert st == 403 and r.get("reason") == "held", (st, r)
assert owner(code, TARGET) == user, "a refused claim must not transfer ownership"
ok("a held territory cannot be claimed out from under its owner — it must be attacked (403 held)")

print("\nAll %d claim-authority tests passed." % passed)
_srv.shutdown()
