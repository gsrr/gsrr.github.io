#!/usr/bin/env python3
"""Phase 12B.1.2 — a class roster is accounts, not names, and a code is not authority.

    python3 tests/class_membership_test.py

Phase 12B.2's authority audit stopped implementation after proving three things: a student account
recorded no class membership at all; a teacher's roster was keyed by DISPLAY NAME inside the
teacher's own progress file; and /api/class/sync authenticated the class CODE only -- so an
unauthenticated client that knew a code could inject arbitrary names into any teacher's dashboard.
"Teacher X may manage student Y" was therefore unprovable, and anything built on it (an accessibility
accommodation, for one) would have been a privilege-escalation path.

This suite is the adversarial proof that the repair holds. It reproduces the original exploit and
requires it to fail with zero mutation, then attacks the new model from every direction the
authority can be got wrong: cross-teacher claims, impersonation, self-management, duplicate display
names, forged fields, dangling codes, and class moves.
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request as U
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


import tempfile  # noqa: E402

d = tempfile.mkdtemp()
server.ROOMS_DIR = os.path.join(d, "rooms")
server.ACCT = os.path.join(d, "accounts.json")
server.PROG_DIR = os.path.join(d, "progress")
server.DATA = os.path.join(d, "visits.json")
server.TERR_CATALOG = os.path.join(d, "learned.json")
server.LEARNING.content_root = ROOT

srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % PORT


def call(method, path, body=None, tok=None):
    url = B + path
    if tok is not None:
        url += ("&" if "?" in url else "?") + "token=" + tok
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = U.urlopen(U.Request(url, data=data, method=method))
        return r.getcode(), json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def mk(user):
    c, j = call("POST", "/api/register", {"user": user, "pass": "pw123456"})
    assert c == 200, (user, c, j)
    return j["token"], j["code"]


def accounts():
    with open(server.ACCT) as f:
        return json.load(f)


def dash(tok):
    return call("GET", "/api/dashboard", tok=tok)[1]


TA, CODE_A = mk("TEACH_A")
TB, CODE_B = mk("TEACH_B")
S1, _ = mk("STUD_1")
S2, _ = mk("STUD_2")

# ====================== 1. defaults ======================
db = accounts()
assert "joinedClass" not in db["users"]["STUD_1"], db["users"]["STUD_1"]
assert server.class_membership_of(db, "STUD_1") == (None, None)
assert server.may_manage("TEACH_A", "STUD_1", db) is False
ok("1. a fresh account has NO membership, and no teacher may manage it")

# ====================== 2. the original exploit must now fail ======================
before_db = json.dumps(accounts(), sort_keys=True)
before_dash = json.dumps(dash(TA), sort_keys=True)
code, out = call("POST", "/api/class/sync?code=" + CODE_A,
                 {"students": {"NotMyStudent": {"scores": {}}, "STUD_1": {"scores": {}}}})
assert code == 401 and out.get("reason") == "auth_required", (code, out)
assert json.dumps(accounts(), sort_keys=True) == before_db, "an unauthenticated call mutated accounts"
assert json.dumps(dash(TA), sort_keys=True) == before_dash, "an unauthenticated call mutated the roster"
ok("2. the original exploit -- unauthenticated POST + a known class code + arbitrary names -- is "
   "refused 401 with ZERO mutation to accounts or roster")

# ====================== 3. bad tokens fail closed ======================
for tok, label in [("", "empty token"), ("bogus", "forged token"),
                   ("deadbeef" * 6, "well-formed but unknown token")]:
    code, out = call("POST", "/api/class/sync?code=" + CODE_A, {"displayName": "x"}, tok=tok)
    assert code == 401, (label, code, out)
assert json.dumps(accounts(), sort_keys=True) == before_db, "a bad token mutated state"
ok("3. empty, forged and unknown tokens all fail closed with no mutation")

# ====================== 4. an authenticated student joins ======================
code, out = call("POST", "/api/class/sync?code=" + CODE_A,
                 {"displayName": "Jimmy", "progress": {"scores": {"a": 1}}}, tok=S1)
assert code == 200 and out.get("ok") is True, (code, out)
assert out.get("account") == "STUD_1" and out.get("joinedClass") == CODE_A, out
db = accounts()
assert db["users"]["STUD_1"]["joinedClass"] == CODE_A
assert isinstance(db["users"]["STUD_1"].get("joinedClassAt"), float)
assert server.class_membership_of(db, "STUD_1") == (CODE_A, "TEACH_A")
ok("4. an authenticated student join records membership on the STUDENT'S OWN account, and "
   "ownership derives to the right teacher")

# ====================== 5. the canonical authority helper ======================
db = accounts()
assert server.may_manage("TEACH_A", "STUD_1", db) is True
assert server.may_manage("TEACH_B", "STUD_1", db) is False
assert server.may_manage("TEACH_A", "STUD_2", db) is False
assert server.may_manage("TEACH_A", "NO_SUCH_ACCOUNT", db) is False
assert server.may_manage("NO_SUCH_TEACHER", "STUD_1", db) is False
assert server.may_manage("STUD_1", "STUD_1", db) is False
assert server.may_manage("", "STUD_1", db) is False
assert server.may_manage("TEACH_A", "", db) is False
assert server.class_members_of("TEACH_A", db) == ["STUD_1"]
assert server.class_members_of("TEACH_B", db) == []
ok("5. may_manage(): owning teacher True; other teacher, unjoined student, unknown account, "
   "self-management and empty ids all False")

# ====================== 6. the teacher sees the account, not a name ======================
dA = dash(TA)
assert "STUD_1" in (dA.get("members") or {}), dA
assert dA["members"]["STUD_1"]["displayName"] == "Jimmy"
assert dA["members"]["STUD_1"]["account"] == "STUD_1"
assert dash(TB).get("members") == {}, "teacher B must not see teacher A's member"
ok("6. the owning teacher's dashboard lists the ACCOUNT (with its display label); the other "
   "teacher's roster stays empty")

# ====================== 7. no account field leaks to the teacher ======================
blob = json.dumps(dA)
for secret in ("salt", "hash", "\"pass\"", "token"):
    assert secret not in blob, ("the dashboard leaked %s" % secret, blob[:400])
ok("7. the dashboard exposes no salt, password hash or token")

# ====================== 8. a teacher cannot fabricate membership ======================
before = json.dumps(accounts(), sort_keys=True)
# teacher B tries to claim STUD_1 by naming them, through every shape available
code, out = call("POST", "/api/class/sync?code=" + CODE_B,
                 {"displayName": "STUD_1", "account": "STUD_1", "user": "STUD_1",
                  "students": {"STUD_1": {"scores": {}}}, "progress": {}}, tok=TB)
db = accounts()
assert server.may_manage("TEACH_B", "STUD_1", db) is False, "teacher B acquired authority by naming"
assert db["users"]["STUD_1"]["joinedClass"] == CODE_A, "STUD_1's membership was altered by someone else"
ok("8. a teacher cannot acquire authority over another teacher's student by naming them, nor by "
   "sending account/user/students fields (result: %s)" % code)

# ====================== 9. a student cannot act for another student ======================
code, out = call("POST", "/api/class/sync?code=" + CODE_B,
                 {"displayName": "Jimmy", "account": "STUD_1", "user": "STUD_1",
                  "progress": {"scores": {"hacked": 1}}}, tok=S2)
assert code == 200, (code, out)
assert out.get("account") == "STUD_2", ("the token must decide the account, not a body field", out)
db = accounts()
assert db["users"]["STUD_1"]["joinedClass"] == CODE_A, "STUD_2's request moved STUD_1"
assert server.may_manage("TEACH_B", "STUD_1", db) is False
mB = dash(TB).get("members") or {}
assert list(mB) == ["STUD_2"], mB
assert "STUD_1" not in mB
ok("9. forged account/user fields are ignored: the token decides the account, so STUD_2 cannot "
   "join, move or impersonate STUD_1")

# ====================== 10. duplicate display names stay distinct ======================
# STUD_2 is in class B with the label "Jimmy"; STUD_1 is in class A with the label "Jimmy"
assert (dash(TA)["members"]["STUD_1"]["displayName"] ==
        dash(TB)["members"]["STUD_2"]["displayName"] == "Jimmy")
assert server.may_manage("TEACH_A", "STUD_2", accounts()) is False
assert server.may_manage("TEACH_B", "STUD_1", accounts()) is False
ok("10. two accounts sharing the display name 'Jimmy' remain separate identities in separate "
   "classes, and neither teacher gains cross-class authority")

# ====================== 11. a display-name change cannot change identity ======================
call("POST", "/api/class/sync?code=" + CODE_A, {"displayName": "Renamed"}, tok=S1)
db = accounts()
assert db["users"]["STUD_1"]["joinedClass"] == CODE_A
assert dash(TA)["members"]["STUD_1"]["displayName"] == "Renamed"
assert list(dash(TA)["members"]) == ["STUD_1"], "a rename created a second identity"
assert server.may_manage("TEACH_A", "STUD_1", db) is True
ok("11. renaming the display label updates the label only -- identity, membership and authority "
   "are unchanged, and no duplicate roster row appears")

# ====================== 12. rejoining the same class is idempotent ======================
first_at = accounts()["users"]["STUD_1"]["joinedClassAt"]
joined_at = dash(TA)["members"]["STUD_1"]["joinedAt"]
call("POST", "/api/class/sync?code=" + CODE_A, {"displayName": "Renamed"}, tok=S1)
assert list(dash(TA)["members"]) == ["STUD_1"], "rejoining duplicated the roster identity"
assert dash(TA)["members"]["STUD_1"]["joinedAt"] == joined_at, "joinedAt must not be rewritten"
assert accounts()["users"]["STUD_1"]["joinedClass"] == CODE_A
ok("12. rejoining the same class is idempotent: one roster identity, original joinedAt preserved")

# ====================== 13. invalid and self class codes ======================
before = json.dumps(accounts(), sort_keys=True)
code, out = call("POST", "/api/class/sync?code=ZZZZZ", {"displayName": "x"}, tok=S1)
assert code == 404 and out.get("reason") == "bad_class_code", (code, out)
# every account owns a code, so joining your own class is reachable -- and refused
own = accounts()["users"]["STUD_1"]["code"]
code, out = call("POST", "/api/class/sync?code=" + own, {"displayName": "x"}, tok=S1)
assert code == 400 and out.get("reason") == "self_class", (code, out)
# a dangling code index entry is not authority
with server.acct_lock:
    db = server.load_accounts()
    db["codes"]["GHOST"] = "NO_SUCH_USER"
    server.save_accounts(db)
code, out = call("POST", "/api/class/sync?code=GHOST", {"displayName": "x"}, tok=S1)
assert code == 404 and out.get("reason") == "bad_class_code", (code, out)
assert server.class_owner_of(server.load_accounts(), "GHOST") is None
assert accounts()["users"]["STUD_1"]["joinedClass"] == CODE_A, "a failed join changed membership"
ok("13. an unknown code, a learner's own code and a dangling code index entry are all refused, "
   "with membership unchanged")

# ====================== 14. moving class transfers authority ======================
code, out = call("POST", "/api/class/sync?code=" + CODE_B, {"displayName": "Jimmy B"}, tok=S1)
assert code == 200, (code, out)
db = accounts()
assert db["users"]["STUD_1"]["joinedClass"] == CODE_B
assert server.may_manage("TEACH_B", "STUD_1", db) is True, "the new teacher must gain authority"
assert server.may_manage("TEACH_A", "STUD_1", db) is False, "the OLD teacher must lose authority"
mA, mB = dash(TA).get("members") or {}, dash(TB).get("members") or {}
assert "STUD_1" not in mA, ("the old teacher still lists the learner", mA)
assert sorted(mB) == ["STUD_1", "STUD_2"], mB
assert server.class_members_of("TEACH_A", db) == []
ok("14. an authoritative move removes the old teacher's authority and roster row and grants the "
   "new teacher both -- with no duplicated membership")

# ====================== 15. legacy name-keyed data is never authority ======================
with server.acct_lock:
    p = server.load_progress("TEACH_A")
    p.setdefault("students", {})["LegacyKid"] = {"scores": {}, "avatar": "\U0001F466"}
    server.save_progress("TEACH_A", p)
dA = dash(TA)
assert "LegacyKid" in (dA.get("students") or {}), "legacy rows must be preserved"
assert dA.get("legacyStudents") is True, "legacy rows must be reported as legacy"
assert "LegacyKid" not in (dA.get("members") or {}), "legacy rows must not become members"
assert server.may_manage("TEACH_A", "LegacyKid", accounts()) is False
assert "LegacyKid" not in accounts()["users"], "a legacy row must never become an account"
ok("15. a pre-existing name-keyed roster row is preserved, reported separately, and confers no "
   "authority -- it is never promoted to an account")

# ====================== 16. teacher's own-device sync cannot forge members ======================
before_members = json.dumps(server.load_progress("TEACH_A").get("members") or {}, sort_keys=True)
code, out = call("POST", "/api/sync", {"students": {"Injected": {"scores": {}}}}, tok=TA)
after_members = json.dumps(server.load_progress("TEACH_A").get("members") or {}, sort_keys=True)
assert after_members == before_members, "/api/sync wrote into the authoritative member list"
assert server.may_manage("TEACH_A", "Injected", accounts()) is False
assert "Injected" not in (dash(TA).get("members") or {})
ok("16. the teacher's own-device /api/sync still writes only legacy name-keyed data and cannot "
   "create an authoritative member")

# ====================== 17. membership is private to the learner and their teacher ======================
dB = dash(TB)
assert "STUD_2" in dB["members"] and "STUD_1" in dB["members"]
# an unrelated account learns nothing about anyone's membership from its own dashboard
_, dS2 = call("GET", "/api/dashboard", tok=S2)
assert (dS2.get("members") or {}) == {}, ("a learner's dashboard must not list other accounts", dS2)
lb = call("GET", "/api/leaderboard")[1]
assert "joinedClass" not in json.dumps(lb), "membership leaked into the leaderboard"
st = call("GET", "/api/learning/state", tok=S1)[1]
assert "joinedClass" not in json.dumps(st), "membership leaked into learning state"
ok("17. membership is not exposed through another learner's dashboard, the leaderboard or the "
   "learning state")

# ====================== 12B.1.2R: the role boundary is a RELATIONSHIP, not an account type ======
# The role audit found no authoritative account role: /api/register and /api/student/register are the
# same handler and produce identical records, there is no role field and no is_student()/is_teacher(),
# and every account owns a class code. So "student" here means "an account that voluntarily joined
# this teacher's class" -- nothing more. These assertions pin what that must and must not imply.
# compare two FRESHLY registered accounts, one per route -- accounts already used in this suite
# carry membership, which would mask the comparison
call("POST", "/api/register", {"user": "FRESH_VIA_TEACHER", "pass": "pw123456"})
call("POST", "/api/student/register", {"user": "FRESH_VIA_STUDENT", "pass": "pw123456"})
db = accounts()
viaT = sorted(db["users"]["FRESH_VIA_TEACHER"])
viaS = sorted(db["users"]["FRESH_VIA_STUDENT"])
assert viaT == viaS == ["code", "created", "hash", "salt"],     ("the two registration routes must produce structurally identical records", viaT, viaS)
for acct in ("FRESH_VIA_TEACHER", "FRESH_VIA_STUDENT"):
    assert not [k for k in db["users"][acct]
                if k.lower() in ("role", "kind", "type", "isteacher", "isstudent")],         "no role field may have appeared; this phase must not invent one"
assert server.may_manage("FRESH_VIA_TEACHER", "FRESH_VIA_STUDENT", db) is False,     "registering through the student route must NOT by itself make an account manageable"
ok("19. accounts carry NO role field, and the two registration routes produce identical records -- "
   "authority is a relationship, never an account type")

# Fresh accounts, so these properties do not depend on where earlier cases left STUD_1/STUD_2.
TC, CODE_C = mk("TEACH_C")          # owns class C
TD, CODE_D = mk("TEACH_D")          # will JOIN class C
SC, _ = mk("STUD_C")                # a member of class C
SD, _ = mk("STUD_D")                # another member of class C
call("POST", "/api/class/sync?code=" + CODE_C, {"displayName": "member C"}, tok=SC)
call("POST", "/api/class/sync?code=" + CODE_C, {"displayName": "member D"}, tok=SD)

# an account joining another class becomes manageable BY that class's owner (its own choice) and
# gains authority over nobody
code, out = call("POST", "/api/class/sync?code=" + CODE_C, {"displayName": "D as member"}, tok=TD)
assert code == 200 and out.get("account") == "TEACH_D", (code, out)
db = accounts()
assert server.may_manage("TEACH_C", "TEACH_D", db) is True, "C owns the class D joined"
assert server.may_manage("TEACH_D", "TEACH_C", db) is False, "joining grants the joiner nothing"
assert server.may_manage("TEACH_D", "STUD_C", db) is False,     "joining a class must not grant authority over its other members"
assert server.may_manage("TEACH_D", "STUD_D", db) is False
ok("20. an account that joins a class becomes manageable by that class's owner and gains authority "
   "over NO other member -- co-membership is not authority")

# co-members cannot manage each other
assert server.may_manage("STUD_C", "STUD_D", db) is False
assert server.may_manage("STUD_D", "STUD_C", db) is False
assert server.may_manage("STUD_C", "STUD_C", db) is False
ok("21. two members of the same class cannot manage each other, nor themselves")

# a join request cannot nominate a different account
before = accounts()["users"]["STUD_D"]["joinedClass"]
code, out = call("POST", "/api/class/sync?code=" + CODE_C,
                 {"account": "STUD_D", "user": "STUD_D", "student": "STUD_D",
                  "teacher": "TEACH_D", "students": {"STUD_D": {}}, "displayName": "STUD_D"},
                 tok=SC)
assert out.get("account") == "STUD_C", ("the token must decide the account", out)
assert accounts()["users"]["STUD_D"]["joinedClass"] == before, "another account was moved"
ok("22. forged account / user / student / teacher / students fields cannot nominate or move a "
   "different account -- the token alone decides")

# D: a stale roster copy must never preserve authority, because may_manage re-derives from the
# account record. This is what makes partial roster cleanup harmless without a transaction.
with server.acct_lock:
    dbx = server.load_accounts()
    dbx["users"]["STUD_1"]["joinedClass"] = CODE_B          # authoritative move
    server.save_accounts(dbx)
    pa = server.load_progress("TEACH_A")
    pa.setdefault("members", {})["STUD_1"] = {"displayName": "stale copy left behind"}
    server.save_progress("TEACH_A", pa)
db = accounts()
assert "STUD_1" in (server.load_progress("TEACH_A").get("members") or {}), "fixture check"
assert server.may_manage("TEACH_A", "STUD_1", db) is False,     "an orphaned roster copy must NOT preserve authority"
assert server.may_manage("TEACH_B", "STUD_1", db) is True
assert "STUD_1" not in (dash(TA).get("members") or {}),     "the dashboard re-derives membership, so a stale copy is not listed"
ok("23. an orphaned roster copy left by a partial class switch grants no authority and is not "
   "listed -- authority is always re-derived from joinedClass")

# F: a legacy row sharing a real account's name cannot shadow or override the authoritative member
with server.acct_lock:
    pb = server.load_progress("TEACH_B")
    pb.setdefault("students", {})["STUD_1"] = {"scores": {"legacy": 1}}
    server.save_progress("TEACH_B", pb)
dB = dash(TB)
assert dB["members"]["STUD_1"]["account"] == "STUD_1", "the authoritative member must win"
assert "legacy" not in json.dumps(dB["members"]["STUD_1"]),     "legacy content must not leak into the authoritative record"
assert "STUD_1" in (dB.get("students") or {}) and dB.get("legacyStudents") is True
ok("24. a legacy row with the same name as a real account neither shadows nor contaminates the "
   "authoritative member, and stays reported as legacy")

# ====================== 18. the learning/game contract is untouched ======================
from learning import registry as R  # noqa: E402
from game.config import PASS_GOLD, MASTERY_GOLD, fingerprint  # noqa: E402
reg = R.REGISTRY
stt = [a for a in reg.activities if reg.scorer_type_of(a) == "read_along_stt"]
assert (len(reg.lessons), len(reg.activities), len(stt)) == (57, 457, 57)
req_ok = 0
for lid in reg.lessons:
    pol = reg.completion_policy_of(lid) or {}
    r = pol.get("requiredActivityIds") or []
    mine = [a for a in stt if reg.activities[a]["lessonId"] == lid]
    if any(a in r for a in mine):
        req_ok += 1
    assert len(r) == (7 if lid.startswith("english.prea1") else 5), (lid, len(r))
assert req_ok == 57
assert (PASS_GOLD, MASTERY_GOLD) == (160, 640)
assert len(reg.qualifications) == 4
assert fingerprint() == "736503ae2c4f5fa5"
assert sorted(server.allowed_game_maps()) == ["world"]
ok("18. unchanged by this phase: 57 lessons / 457 activities / read-along required 57 of 57, "
   "Pre-A1+Taipei 7 and A1/A2/B1 5, PASS_GOLD 160, MASTERY_GOLD 640, 4 qualifications, "
   "fingerprint 736503ae2c4f5fa5, allowed_game_maps {'world'}")

print("\nAll %d class-membership tests passed." % passed)
