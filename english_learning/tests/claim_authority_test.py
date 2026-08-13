#!/usr/bin/env python3
"""Phase 7D-0 — neutral territory CLAIM is qualification-gated by the SERVER.

    python3 tests/claim_authority_test.py

Attacking a gated territory has been server-authoritative since Phase 3A. Claiming a *neutral* one
was not: the only gate was a client-side comparison of a client-bumped counter
(`passCount(file) > base`), and `/api/territory/claim` checked nothing at all — so any client could
POST one request and take a gated district while holding zero qualifications.

Both routes now resolve the SAME rule from the SAME world-data through
`game.conquest.missing_qualifications()`. These tests speak straight to the API the way a forged
client would, and assert the rule from the outside rather than from the helper.
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server                                                        # noqa: E402
from game import conquest as game_conquest                           # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


DATA = tempfile.mkdtemp(prefix="claimauth-")
server.ROOMS_DIR = os.path.join(DATA, "rooms")
server.ACCT = os.path.join(DATA, "accounts.json")
server.PROG_DIR = os.path.join(DATA, "progress")
for d in (server.ROOMS_DIR, server.PROG_DIR):
    os.makedirs(d, exist_ok=True)

from http.server import ThreadingHTTPServer                          # noqa: E402
httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]

DAAN, ZHONGSHAN, WENSHAN = "taipei:daan", "taipei:zhongshan", "taipei:wenshan"
ZOO_Q = "english.prea1.taipei.zoo"
MARKET_Q = "english.prea1.taipei.market.quiz3.pass"
MRT_Q = "english.prea1.taipei.mrt.quiz3.pass"
_n = [0]


def api(method, path, body=None, tok=None):
    sep = "&" if "?" in path else "?"
    req = urllib.request.Request(
        BASE + path + ((sep + "token=" + tok) if tok else ""), method=method,
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


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
               {"file": target, "troops": troops or [{"type": "inf", "hp": 10}]}, tok)


def stock(code, user, n=200):
    """Phase 8B.1: a claim garrison is now debited from the authoritative troop pool, so a test that
    deploys more than a room's starting troops has to own them first. These tests are about the
    QUALIFICATION gate, not troop budgeting — stocking the pool keeps every assertion below about
    exactly what it was written to prove."""
    server.set_room(code)
    es = server.load_econ_store()
    es.setdefault(user, {})["troops"] = {"cav": n, "archer": n, "inf": n, "spear": n}
    server.save_econ_store(es)


def owner(code, target):
    server.set_room(code)
    return (server.load_territory_store().get(target) or {}).get("owner")


def denied(res, *expect_missing):
    st, r = res
    return (st == 403 and r.get("reason") == "qualification_required"
            and (not expect_missing or r.get("missingQualificationIds") == list(expect_missing)))


# ====================== single requirement ======================
user, tok, code = fresh()
res = claim(tok, code, DAAN)
assert denied(res, ZOO_Q), res
assert owner(code, DAAN) is None, "a refused claim must not change ownership"
ok("single requirement: an unqualified client is refused 403 qualification_required, is told exactly "
   "which id is missing, and the territory stays unowned (atomic refusal)")

user, tok, code = fresh([ZOO_Q])
st, r = claim(tok, code, DAAN)
assert st == 200 and r.get("ok"), (st, r)
assert owner(code, DAAN) == user
ok("single requirement: a genuinely qualified client claims normally — the gate adds no new "
   "obstacle to an honest player")

# ====================== ALL-required, never first-missing ======================
user, tok, code = fresh()
assert denied(claim(tok, code, ZHONGSHAN), MARKET_Q, ZOO_Q)
user, tok, code = fresh([MARKET_Q])
assert denied(claim(tok, code, ZHONGSHAN), ZOO_Q)
user, tok, code = fresh([ZOO_Q])
assert denied(claim(tok, code, ZHONGSHAN), MARKET_Q)
user, tok, code = fresh([MARKET_Q, ZOO_Q])
st, r = claim(tok, code, ZHONGSHAN)
assert st == 200 and owner(code, ZHONGSHAN) == user, (st, r)
ok("Zhongshan multi-requirement is ALL-required at the server: neither/either held is refused with "
   "the FULL missing list, both held is allowed — first-missing stays a client lesson-picking rule")

# ====================== ungated is untouched ======================
user, tok, code = fresh()
st, r = claim(tok, code, WENSHAN)
assert st == 200 and owner(code, WENSHAN) == user, (st, r)
assert game_conquest.missing_qualifications(server.terr_catalog, WENSHAN, set()) == []
ok("an ungated territory invents no requirement: claimed with zero qualifications, exactly as before")

# ====================== qualification, NOT mastery ======================
user, tok, code = fresh([ZOO_Q])
st, pv = api("GET", "/api/learning/progress?room=" + code, None, tok)
row = (pv.get("lessons") or {}).get("english.prea1.taipei.zoo") or {}
assert row.get("activePolicyCompleted") is False, row
st, r = claim(tok, code, DAAN)
assert st == 200 and owner(code, DAAN) == user, (st, r)
ok("the credential is the QUALIFICATION, not mastery: a qualified learner whose lesson is provably "
   "not mastered still claims — mastery keeps paying gold, it does not gate conquest")

# ====================== forged client state cannot substitute ======================
# Phase 7F.2 retired POST /api/economy/pass, so the counter can no longer even be written over HTTP.
# The forgery is therefore staged one level DEEPER than any client could reach — straight into the
# saved economy file — which makes this a strictly stronger test than bumping the old endpoint.
user, tok, code = fresh()
server.set_room(code)
with server.econ_lock:
    st = server.load_econ_store()
    st.setdefault(user, {})["passcnt"] = {"Pre-A1/taipei/zoo": 999, "made/up/lesson": 42}
    server.save_econ_store(st)
assert denied(claim(tok, code, DAAN), ZOO_Q)
server.set_room(code)
assert ((server.load_econ_store().get(user) or {}).get("passcnt") or {}).get("Pre-A1/taipei/zoo") == 999, \
    "the legacy counter is ignored in place — the refused claim neither reads nor rewrites it"
ok("passcnt is NOT authority: a hand-forged counter planted directly in the economy store buys "
   "nothing — the qualification store is the only gate")

st, _ = api("POST", "/api/economy/pass?room=" + code, {"file": "Pre-A1/taipei/zoo"}, tok)
assert st == 404, "the endpoint that used to let a client assert its own passes must be GONE, %s" % st
assert denied(claim(tok, code, DAAN), ZOO_Q)
ok("the client-asserted pass endpoint is retired: there is no HTTP route left for a client to "
   "declare a lesson passed, and the claim gate is unchanged by its absence")

user, tok, code = fresh()
api("POST", "/api/learning/attempt?room=" + code,
    {"activityId": "english.prea1.taipei.zoo.quiz3", "answers": [],
     "passed": True, "pct": 100, "qualifications": [ZOO_Q], "rewarded": True,
     "rewardAmount": 10000}, tok)
st, learn = api("GET", "/api/learning/state?room=" + code, None, tok)
assert not (learn.get("qualifications") or {}), learn
assert denied(claim(tok, code, DAAN), ZOO_Q)
ok("a forged completion payload grants no qualification and therefore no territory: the claim gate "
   "reads authoritative learning state, never anything the client asserted")

user, tok, code = fresh()
assert denied(claim(tok, code, DAAN, [{"type": "cav", "hp": 100000}]), ZOO_Q)
assert denied(claim(tok, code, DAAN, []), ZOO_Q) or claim(tok, code, DAAN, [])[0] == 400
ok("neither a huge forged squad nor a malformed one buys past the gate")

# ====================== redeploying your OWN territory still works ======================
user, tok, code = fresh([ZOO_Q])
assert claim(tok, code, DAAN)[0] == 200
with server.acct_lock:                                   # simulate losing the qualification later
    p = server.load_progress(user)
    p["learning"]["qualifications"] = {}
    server.save_progress(user, p)
st, r = claim(tok, code, DAAN, [{"type": "inf", "hp": 25}])
assert st == 200, (st, r)
server.set_room(code)
assert (server.load_territory_store().get(DAAN) or {}).get("troops") == [{"type": "inf", "hp": 25}]
ok("the gate guards ACQUISITION, not garrison management: re-deploying troops into a territory you "
   "already hold is unaffected, so the new rule cannot strand an existing holding")

# ====================== attack is unchanged and shares the rule ======================
user, tok, code = fresh([ZOO_Q])
bob = api("POST", "/api/register", {"user": "DEF1", "pass": "pw"})[1]["token"]
api("POST", "/api/room/enter?room=" + code, {"code": code}, bob)
api("GET", "/api/economy?room=" + code, None, bob)
with server.acct_lock:
    p = server.load_progress("DEF1")
    p.setdefault("learning", {}).setdefault("qualifications", {})[MRT_Q] = {"earnedAt": 1}
    server.save_progress("DEF1", p)
stock(code, "DEF1")
stock(code, user)
assert api("POST", "/api/territory/claim?room=" + code,
           {"file": "taipei:xinyi", "troops": [{"type": "inf", "hp": 20}]}, bob)[0] == 200
assert claim(tok, code, DAAN, [{"type": "inf", "hp": 50}])[0] == 200
st, r = api("POST", "/api/territory/attack?room=" + code,
            {"sourceTerritoryId": DAAN, "targetTerritoryId": "taipei:xinyi",
             "squad": [{"type": "inf", "hp": 40}]}, tok)
assert st == 403 and r.get("reason") == "qualification_required"
assert r.get("missingQualificationIds") == [MRT_Q], r
ok("attack behaviour is unchanged and now provably shares one rule with claim: the same missing-id "
   "list, from the same world-data, through the same helper")

# ====================== the helper itself is content-independent ======================
assert game_conquest.missing_qualifications(server.terr_catalog, DAAN, set()) == [ZOO_Q]
assert game_conquest.missing_qualifications(server.terr_catalog, DAAN, {ZOO_Q}) == []
assert game_conquest.missing_qualifications(server.terr_catalog, "no:such:place", set()) == []


class _Boom(object):
    def attack_requirements(self, _):
        raise RuntimeError("world unavailable")


assert game_conquest.missing_qualifications(_Boom(), DAAN, set()) == []
ok("the shared helper is total: unknown territory and a raising world both yield 'unrestricted' "
   "rather than an exception, so a world-data fault can never brick claiming")

print("\nAll %d claim-authority tests passed." % passed)
httpd.shutdown()
