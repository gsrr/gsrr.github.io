#!/usr/bin/env python3
# C1 + H3 — corrupt authoritative state fails CLOSED, and malformed requests get an HTTP answer.
#
#     python tests/state_corruption_test.py
#
# The invariant under test:
#
#     Corruption must never silently become fresh state.
#     Corrupt authoritative state -> preserved -> no destructive overwrite
#       -> no duplicate economic settlement -> controlled HTTP failure -> server stays alive.
#
# Everything below works on REAL temporary files and the REAL HTTP server. In-memory malformed dicts
# are deliberately not the subject: the whole point of C1 was that corruption arriving from DISK was
# converted to `{}` one layer below the domain guards that were built to refuse it, so a test that
# hands a malformed dict straight to a pure function would have passed before the fix and after.
import io, json, os, socket, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server                                                    # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


DATA = tempfile.mkdtemp(prefix="corrupt_")
server.ROOMS_DIR = os.path.join(DATA, "rooms")
server.ACCT = os.path.join(DATA, "accounts.json")
server.DATA = os.path.join(DATA, "visits.json")
server.PROG_DIR = os.path.join(DATA, "progress")
server.TERR_CATALOG = os.path.join(DATA, "learned.json")
os.makedirs(server.ROOMS_DIR, exist_ok=True)
os.makedirs(server.PROG_DIR, exist_ok=True)
USERS = ["CorA", "CorB", "CorC", "CorD", "CorE"]
# `readAlongMode: typed` is set so the typed Read-Along route is reachable without a speech model
# (faster-whisper is not a test dependency). It selects which INPUT the server accepts and changes
# no scoring, so it does not affect what is being tested here.
json.dump({"users": {u: {"readAlongMode": "typed"} for u in USERS}, "codes": {}},
          io.open(server.ACCT, "w", encoding="utf-8"))
for u in USERS:
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
TOK = {u: "t" + u for u in USERS}

httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT
ROOM = "CORRUPT"
LESSON = "english.prea1.taipei.zoo"
GATE = LESSON + ".quiz3"


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


def raw_request(text):
    """Send a byte-exact HTTP request. Returns (status_line, body); ("", "") if nothing came back.

    Needed because a malformed Content-Length cannot be produced through urllib -- and because
    "the connection was dropped with no response" is exactly the failure H3 is about, so the test
    has to be able to observe it rather than raise.
    """
    s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    try:
        s.sendall(text.encode())
        buf = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    except Exception:
        pass
    finally:
        s.close()
    if not buf:
        return "", ""
    head, _, body = buf.partition(b"\r\n\r\n")
    return head.split(b"\r\n")[0].decode("utf-8", "replace"), body.decode("utf-8", "replace")


def alive():
    st, j = api("GET", "/api/count")
    return st == 200 and "count" in j


def right_answers(aid):
    slug = aid.split(".")[3]
    key = json.load(io.open(os.path.join(ROOT, "Pre-A1", "taipei", slug + ".json"),
                            encoding="utf-8"))[aid.rsplit(".", 1)[1]]
    return [{"q": it["q"], "answer": it["answer"]} for it in key]


def gold_and_troops(u):
    _, j = api("GET", "/api/economy?room=" + ROOM, None, TOK[u])
    return int(j.get("gold") or 0), sum(int(v or 0) for v in (j.get("troops") or {}).values())


def write_bytes(path, blob):
    io.open(path, "wb").write(blob)
    server._clear_corrupt(path)          # forget any earlier verdict, so each case starts clean


# ==================================================================== missing vs valid
u = "CorA"
path = server._prog_path(u)
assert not os.path.exists(path)
p = server.load_progress(u)
assert p == {"students": {}, "sdata": {}}, p
db = server.load_accounts()
assert isinstance(db.get("users"), dict), db
ok("a MISSING progress/accounts file is first-run: normal empty state, no error")

p["learning"] = {"activityCompletions": {"a": {"passedAt": 1, "pct": 100, "rewarded": True}}}
p["sdata"] = {"avatar": "\U0001F466"}
server.save_progress(u, p)
back = server.load_progress(u)
assert back["learning"]["activityCompletions"]["a"]["rewarded"] is True, back
assert back["sdata"]["avatar"] == "\U0001F466", back
VALID = io.open(path, "rb").read()
json.loads(VALID.decode("utf-8"))                       # the saved bytes are valid JSON
ok("a VALID file round-trips unchanged: load -> mutate -> save -> reload preserves every field")

# ==================================================================== every corruption shape
CASES = [
    ("truncated JSON", VALID[:len(VALID) // 2]),
    ("syntactically invalid JSON", b'{"users":'),
    ("wrong top-level type: list", b'[]'),
    ("wrong top-level type: string", b'"hello"'),
    ("wrong top-level type: number", b'42'),
    ("undecodable bytes", b'\xff\xfe\x00\x01rubbish'),
    ("empty file", b''),
    ("nested 'learning' is a list", b'{"learning": [1, 2]}'),
    ("nested 'students' is a string", b'{"students": "x"}'),
    ("nested 'sdata' is a number", b'{"sdata": 0}'),
]
for label, blob in CASES:
    write_bytes(path, blob)
    try:
        server.load_progress(u)
        raise AssertionError("%s: load_progress returned instead of refusing" % label)
    except server.CorruptState as e:
        assert e.path == path, e
    # the bytes are exactly as found -- nothing repaired, replaced or truncated
    assert io.open(path, "rb").read() == blob, "%s: bytes were modified" % label
    assert server.state_is_corrupt(path), "%s: path should be marked corrupt" % label
    # and an ordinary save cannot destroy the evidence
    try:
        server.save_progress(u, {"students": {}, "sdata": {}})
        raise AssertionError("%s: save_progress overwrote a corrupt file" % label)
    except server.CorruptState:
        pass
    assert io.open(path, "rb").read() == blob, "%s: save damaged the file" % label
ok("all %d corruption shapes refuse to load, are never returned as {}, keep their exact bytes, "
   "and cannot be overwritten by a normal save" % len(CASES))

# repair -> the mark clears itself, no tooling needed
write_bytes(path, VALID)
assert server.load_progress(u)["learning"]["activityCompletions"]["a"]["rewarded"] is True
assert not server.state_is_corrupt(path)
server.save_progress(u, server.load_progress(u))         # writable again
ok("repairing the file by hand clears the corrupt mark and writes are allowed again")

# ==================================================================== C1 over HTTP
u = "CorB"
st, j = api("POST", "/api/learning/attempt?room=" + ROOM,
            {"activityId": GATE, "answers": right_answers(GATE)}, TOK[u])
assert st == 200 and j.get("passed") is True, j
st, play = api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
assert st == 200 and play.get("newly") is True, play
PRIZE = play["prize"]["id"]
PAID = gold_and_troops(u)
ppath = server._prog_path(u)
BEFORE = io.open(ppath, "rb").read()
assert b"rewarded" in BEFORE, "the payment evidence should be on disk"

# §20 the economically significant case: previously paid, then the evidence is damaged
write_bytes(ppath, BEFORE[:len(BEFORE) // 2])
st, j = api("POST", "/api/learning/attempt?room=" + ROOM,
            {"activityId": GATE, "answers": right_answers(GATE)}, TOK[u])
assert st == 500 and j.get("reason") == "corrupt_state", (st, j)
assert "Traceback" not in json.dumps(j) and DATA not in json.dumps(j), j
assert gold_and_troops(u) == PAID, "a corrupt-evidence attempt moved the economy: %s" % (gold_and_troops(u),)
assert io.open(ppath, "rb").read() == BEFORE[:len(BEFORE) // 2], "the corrupt file was rewritten"
ok("§20 an attempt whose payment evidence is corrupt answers 500 corrupt_state, pays nothing, "
   "leaks no internals and leaves the damaged bytes exactly as found")

# a settlement request is refused for the same reason -- it cannot be told "never paid"
st, j = api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
assert st == 500 and j.get("reason") == "corrupt_state", (st, j)
assert gold_and_troops(u) == PAID, gold_and_troops(u)
ok("a reward settlement with corrupt evidence is refused rather than treated as unpaid")

# §21 a SECOND request must not magically see a fresh account
for _ in range(3):
    st, j = api("GET", "/api/learning/state?room=" + ROOM, None, TOK[u])
    assert st == 500 and j.get("reason") == "corrupt_state", (st, j)
st, j = api("GET", "/api/learning/progress?room=" + ROOM, None, TOK[u])
assert st == 500 and j.get("reason") == "corrupt_state", (st, j)
assert alive()
ok("§21 repeated requests keep failing closed -- corruption never becomes a fresh {} on retry")

# and once repaired, the ORIGINAL evidence is still there and still blocks a second payout
write_bytes(ppath, BEFORE)
st, j = api("POST", "/api/learning/attempt?room=" + ROOM,
            {"activityId": GATE, "answers": right_answers(GATE)}, TOK[u])
assert st == 200 and j.get("alreadyCompleted") is True, j
assert not j.get("rewardGame"), j
st, play2 = api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
assert play2.get("newly") is False and play2["prize"]["id"] == PRIZE, play2
assert gold_and_troops(u) == PAID, gold_and_troops(u)
ok("after repair the preserved evidence still prevents a duplicate payout (same prize, +0)")

# ==================================================================== economy.json corruption
# This file holds the balance AND the reward payment markers, so reading it as empty is a direct
# double-pay path.
u = "CorC"
api("POST", "/api/learning/attempt?room=" + ROOM,
    {"activityId": GATE, "answers": right_answers(GATE)}, TOK[u])
api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
epath = server.room_path("economy.json", ROOM)
EBEFORE = io.open(epath, "rb").read()
assert server.REWARD_PAID_KEY.encode() in EBEFORE, "the payment marker should be on disk"
write_bytes(epath, b'{"broken":')
st, j = api("POST", "/api/learning/rewards/play?room=" + ROOM, {"id": GATE}, TOK[u])
assert st == 500 and j.get("reason") == "corrupt_state", (st, j)
assert io.open(epath, "rb").read() == b'{"broken":', "the corrupt economy file was rewritten"
ok("a corrupt economy.json (balance + payment markers) refuses settlement instead of "
   "re-paying, and its bytes survive")
write_bytes(epath, EBEFORE)

# ==================================================================== accounts corruption
ABEFORE = io.open(server.ACCT, "rb").read()
write_bytes(server.ACCT, b'{"users": ')
try:
    server.load_accounts()
    raise AssertionError("load_accounts returned instead of refusing")
except server.CorruptState:
    pass
# registering must NOT be allowed to write a one-user file over everyone's credentials
st, j = api("POST", "/api/register", {"user": "newbie", "pass": "pw"})
assert st == 500 and j.get("reason") == "corrupt_state", (st, j)
assert io.open(server.ACCT, "rb").read() == b'{"users": ', "accounts.json was replaced!"
st, j = api("POST", "/api/login", {"user": "CorA", "pass": "pw"})
assert st == 500 and j.get("reason") == "corrupt_state", (st, j)
assert alive()
ok("corrupt accounts.json is never read as \"no accounts exist\": register/login answer 500 and "
   "the file is not replaced")

# nested corruption in accounts is caught too
write_bytes(server.ACCT, b'{"users": [], "codes": {}}')
try:
    server.load_accounts()
    raise AssertionError("a list 'users' should be refused")
except server.CorruptState:
    pass
st, j = api("POST", "/api/register", {"user": "newbie2", "pass": "pw"})
assert st == 500 and j.get("reason") == "corrupt_state", (st, j)
assert io.open(server.ACCT, "rb").read() == b'{"users": [], "codes": {}}'
ok("a nested 'users' of the wrong type is refused as well, and the file is left alone")
write_bytes(server.ACCT, ABEFORE)
# a real round trip through the restored file: register, then log in with the same credentials
st, j = api("POST", "/api/register", {"user": "afterRepair", "pass": "pw-123"})
assert st == 200 and j.get("token"), (st, j)
st, j = api("POST", "/api/login", {"user": "afterRepair", "pass": "pw-123"})
assert st == 200 and j.get("token"), (st, j)
st, j = api("POST", "/api/login", {"user": "afterRepair", "pass": "wrong"})
assert st == 401, (st, j)
# and the pre-existing users are still there -- the corrupt-file episode replaced nothing
db = server.load_accounts()
assert all(x in db["users"] for x in USERS), sorted(db["users"])
ok("restoring accounts.json restores full service (register + login + wrong-password 401) and "
   "every pre-existing account is still present")

# ==================================================================== H3: request framing
for cl, reason in [("abc", "bad_content_length"), ("-1", "bad_content_length"),
                   ("1.5", "bad_content_length"), ("+1", "bad_content_length"),
                   ("", "bad_content_length"), ("  ", "bad_content_length"),
                   ("0x10", "bad_content_length"), ("99999999999999999999", "body_too_large")]:
    line, body = raw_request(
        "POST /api/register HTTP/1.1\r\nHost: t\r\nContent-Length: %s\r\nConnection: close\r\n\r\n" % cl)
    assert line, "Content-Length %r dropped the connection with no response" % cl
    assert " 400 " in line, "Content-Length %r -> %s" % (cl, line)
    j = json.loads(body)
    assert j.get("reason") == reason, (cl, j)
    assert "Traceback" not in body and "server.py" not in body and DATA not in body, body
    assert alive(), "server died after Content-Length %r" % cl
ok("8 malformed/oversized Content-Length values each answer 400 with a machine reason, leak no "
   "internals, and leave the server serving")

# the STT upload path parses the same header, so it is protected too
line, body = raw_request(
    "POST /api/stt?activityId=x HTTP/1.1\r\nHost: t\r\nContent-Length: abc\r\nConnection: close\r\n\r\n")
assert " 400 " in line, line
assert json.loads(body).get("reason") == "bad_content_length", body
assert alive()
ok("/api/stt (the other Content-Length reader) answers 400 rather than dropping the connection")

# a body that is not JSON keeps its historical tolerance: the handler answers its own 400
st, j = api("POST", "/api/register", None)
assert st == 400 and "Missing" in (j.get("error") or ""), (st, j)
ok("an absent/unparseable BODY still reaches the handler's own validation (behaviour unchanged)")

# ==================================================================== H3: exception boundary
original = server.Handler._handle_dashboard


def _boom(self):
    raise RuntimeError("synthetic failure mentioning " + DATA)


server.Handler._handle_dashboard = _boom
try:
    line, body = raw_request("GET /api/dashboard HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
    assert line, "an unexpected exception dropped the connection"
    assert " 500 " in line, line
    j = json.loads(body)
    assert j.get("reason") == "server_error", j
    assert "synthetic failure" not in body, "the exception message leaked"
    assert DATA not in body and "Traceback" not in body and "server.py" not in body, body
    assert alive(), "server died after an unexpected handler exception"
finally:
    server.Handler._handle_dashboard = original
st, j = api("GET", "/api/dashboard?room=" + ROOM, None, TOK["CorA"])
assert st == 200, (st, j)
ok("an unexpected handler exception answers a generic 500, leaks neither message nor path, and the "
   "route works again afterwards")

# a response already sent is never followed by a second one
sent_original = server.Handler._handle_events


def _send_then_raise(self):
    self._send({"events": []})
    raise RuntimeError("after the response")


server.Handler._handle_events = _send_then_raise
try:
    line, body = raw_request("GET /api/events HTTP/1.1\r\nHost: t\r\nConnection: close\r\n\r\n")
    assert " 200 " in line, line
    assert body.count("{") == 1, "a second response body was appended: %r" % body
    assert alive()
finally:
    server.Handler._handle_events = sent_original
ok("an exception raised AFTER the response is logged without corrupting the reply already sent")

# ==================================================================== §24 malformed nested state
u = "CorD"
api("POST", "/api/learning/attempt?room=" + ROOM,
    {"activityId": GATE, "answers": right_answers(GATE)}, TOK[u])
BASE_STATE = json.load(io.open(server._prog_path(u), encoding="utf-8"))
BASE_ECON = gold_and_troops(u)


def with_slot(slot, value):
    """A realistic, VALID outer progress file whose nested container is malformed."""
    st_ = json.loads(json.dumps(BASE_STATE))
    st_.setdefault("learning", {})[slot] = value
    blob = json.dumps(st_).encode("utf-8")
    write_bytes(server._prog_path(u), blob)
    return blob


# Each slot is paired with a route that actually WRITES it -- matching/start, for instance, touches
# matchingRounds but not matchingProgress, so a corrupt matchingProgress legitimately does not stop
# it. Testing a slot against a route that never writes it would prove nothing.
CHECKS = [
    ("matchingRounds", "POST", "/api/learning/matching/start",
     {"activityId": LESSON + ".matching"}),
    ("sttProgress", "POST", "/api/learning/read-along/typed",
     {"activityId": LESSON + ".read_along", "sentenceIndex": 0, "text": "hi"}),
]
BAD_VALUES = [[], "x", 0, 7.5, True]
n = 0
for slot, method, route, body in CHECKS:
    for bad in BAD_VALUES:
        blob = with_slot(slot, bad)
        st, j = api(method, route + "?room=" + ROOM, body, TOK[u])
        assert st == 500 and j.get("reason") == "corrupt_state", \
            "%s=%r on %s -> %s %s" % (slot, bad, route, st, j)
        assert "Traceback" not in json.dumps(j) and DATA not in json.dumps(j), j
        # refused, so nothing was written and the malformed bytes stand
        assert io.open(server._prog_path(u), "rb").read() == blob, \
            "%s=%r on %s mutated the file" % (slot, bad, route)
        assert gold_and_troops(u) == BASE_ECON, "%s=%r moved the economy" % (slot, bad)
        assert alive(), "server died on %s=%r" % (slot, bad)
        n += 1
ok("§24 %d malformed nested containers ([], \"x\", 0, float, bool across matchingRounds / "
   "sttProgress) each answer 500 corrupt_state: no crash, no write, no payout, server alive, "
   "slot NOT normalised to {}" % n)

# roleplayProgress, like matchingProgress, is written only at SETTLEMENT, so it is reached by
# playing a session out. The graph is read off disk to answer correctly -- the client is never told
# the routes.
GRAPH = json.load(io.open(os.path.join(
    ROOT, "roleplay", "scenarios", "lesson", "Pre-A1-taipei-zoo.json"), encoding="utf-8"))
NODES = {nd.get("id"): nd for nd in (GRAPH.get("nodes") or [])}


def good_reply(node_id):
    for r in ((NODES.get(node_id) or {}).get("routes") or []):
        for ex in (r.get("examples") or []):
            return ex
    return "Yes."


write_bytes(server._prog_path(u), json.dumps(BASE_STATE).encode("utf-8"))
st, rp = api("POST", "/api/learning/roleplay/start?room=" + ROOM,
             {"activityId": LESSON + ".roleplay"}, TOK[u])
assert st == 200 and rp.get("sessionId"), (st, rp)
live = json.load(io.open(server._prog_path(u), encoding="utf-8"))
live["learning"]["roleplayProgress"] = "x"                # damage ONLY the settlement target
blob = json.dumps(live).encode("utf-8")
write_bytes(server._prog_path(u), blob)
refused = False
for _ in range(30):
    st, nxt = api("POST", "/api/learning/roleplay/respond?room=" + ROOM,
                  {"sessionId": rp["sessionId"], "response": good_reply((rp.get("prompt") or {}).get("nodeId")),
                   "seq": rp.get("turn")}, TOK[u])
    if st == 500 and nxt.get("reason") == "corrupt_state":
        refused = True
        break
    if st != 200 or not nxt:
        break
    rp = nxt
    if rp.get("completed"):
        break
assert refused, "settling a role-play session with a malformed roleplayProgress should be refused"
after = json.load(io.open(server._prog_path(u), encoding="utf-8"))
assert after["learning"]["roleplayProgress"] == "x",     "the malformed slot was normalised: %r" % (after["learning"]["roleplayProgress"],)
assert gold_and_troops(u) == BASE_ECON
assert alive()
ok("settling a role-play session whose roleplayProgress is malformed is refused at the write, "
   "leaving the damaged slot and the economy untouched")

# matchingProgress is written only when a ROUND COMPLETES, so it is reached the long way: start a
# round on valid state, damage just that slot, then play the round out.
write_bytes(server._prog_path(u), json.dumps(BASE_STATE).encode("utf-8"))
st, rd = api("POST", "/api/learning/matching/start?room=" + ROOM,
             {"activityId": LESSON + ".matching"}, TOK[u])
assert st == 200 and rd.get("roundId"), (st, rd)
live = json.load(io.open(server._prog_path(u), encoding="utf-8"))
live["learning"]["matchingProgress"] = []                 # damage ONLY the completion target
blob = json.dumps(live).encode("utf-8")
write_bytes(server._prog_path(u), blob)
refused = False
for _ in range(80):
    items, choices = rd.get("items") or [], rd.get("choices") or []
    i = rd.get("expected", 0)
    if i >= len(items):
        break
    moved = False
    for ch in choices:
        st, out = api("POST", "/api/learning/matching/attempt?room=" + ROOM,
                      {"roundId": rd["roundId"], "itemId": items[i]["itemId"],
                       "choiceId": ch["choiceId"]}, TOK[u])
        if st == 500 and out.get("reason") == "corrupt_state":
            refused = True
            break
        if st == 200 and out.get("status") in ("correct", "complete"):
            rd["expected"] = out.get("expected", i + 1)
            moved = True
            break
    if refused or not moved:
        break
assert refused, "completing a round with a malformed matchingProgress should have been refused"
# The intermediate clicks legitimately persist the ROUND's own progress, so the file is expected to
# change on the way; what must not change is the damaged slot itself.
after = json.load(io.open(server._prog_path(u), encoding="utf-8"))
assert after["learning"]["matchingProgress"] == [],     "the malformed slot was normalised: %r" % (after["learning"]["matchingProgress"],)
assert gold_and_troops(u) == BASE_ECON
assert alive()
ok("finishing a matching round whose matchingProgress is malformed is refused at the write, "
   "leaving the damaged slot and the economy untouched")

# activityCompletions keeps its PRE-EXISTING Phase 7C.1 behaviour, which this task must not change:
# the write is refused and the payout is blocked by completions_state() == CORRUPT, so the economic
# invariant holds even though the request itself still answers 200.
for bad in BAD_VALUES:
    blob = with_slot("activityCompletions", bad)
    st, j = api("POST", "/api/learning/attempt?room=" + ROOM,
                {"activityId": GATE, "answers": right_answers(GATE)}, TOK[u])
    assert st == 200, (bad, st, j)
    assert j.get("rewarded") is False and not j.get("rewardGame"), (bad, j)
    assert gold_and_troops(u) == BASE_ECON, "activityCompletions=%r paid out" % (bad,)
    after = json.load(io.open(server._prog_path(u), encoding="utf-8"))
    assert after["learning"]["activityCompletions"] == bad, \
        "the malformed reward table was replaced: %r" % (after["learning"]["activityCompletions"],)
    assert alive()
ok("a malformed activityCompletions table keeps its documented fail-closed behaviour: the "
   "completion write is refused, no reward is paid, and the damaged table is NOT normalised")

# the nested per-activity record is protected too, not just the table
blob = with_slot("sttProgress", {LESSON + ".read_along": "not-a-record"})
st, j = api("POST", "/api/learning/read-along/typed?room=" + ROOM,
            {"activityId": LESSON + ".read_along", "sentenceIndex": 0, "text": "hi"}, TOK[u])
assert st == 500 and j.get("reason") == "corrupt_state", (st, j)
assert io.open(server._prog_path(u), "rb").read() == blob
blob = with_slot("sttProgress", {LESSON + ".read_along": {"sentences": []}})
st, j = api("POST", "/api/learning/read-along/typed?room=" + ROOM,
            {"activityId": LESSON + ".read_along", "sentenceIndex": 0, "text": "hi"}, TOK[u])
assert st == 500 and j.get("reason") == "corrupt_state", (st, j)
assert io.open(server._prog_path(u), "rb").read() == blob
ok("a malformed per-activity STT record, and a malformed nested 'sentences', are both refused "
   "rather than silently reset (they are the evidence Rule A averages)")

# a VALID nested state still works, so the guard is not simply refusing everything
write_bytes(server._prog_path(u), json.dumps(BASE_STATE).encode("utf-8"))
st, j = api("POST", "/api/learning/matching/start?room=" + ROOM,
            {"activityId": LESSON + ".matching"}, TOK[u])
assert st == 200 and j.get("roundId"), (st, j)
ok("with valid nested state the same routes behave exactly as before (the guard is type-only)")

# ==================================================================== §25 atomic write helper
apath = os.path.join(DATA, "atomic.json")
server.save_json_state(apath, {"a": 1})
assert json.load(io.open(apath, encoding="utf-8")) == {"a": 1}
assert not os.path.exists(apath + ".tmp"), "a temp file was left behind"
ok("save_json_state writes valid JSON and leaves no temp file")


class Unserialisable:
    pass


GOOD = io.open(apath, "rb").read()
try:
    server.save_json_state(apath, {"bad": Unserialisable()})
    raise AssertionError("an unserialisable object should propagate, not be masked")
except TypeError:
    pass
assert io.open(apath, "rb").read() == GOOD, "a failed save damaged the destination"
assert not os.path.exists(apath + ".tmp"), "a failed save left a temp file"
ok("a failed serialisation propagates, leaves the destination byte-for-byte intact, and cleans up")

# a destination that cannot be replaced (its parent is a FILE, not a directory) must not mask either
blocked = os.path.join(apath, "child.json")
try:
    server.save_json_state(blocked, {"a": 1})
    raise AssertionError("writing under a file path should fail")
except (OSError, server.CorruptState):
    pass
assert io.open(apath, "rb").read() == GOOD
ok("an impossible write path reports its failure instead of silently doing nothing")

# durability: the helper fsyncs the contents before the rename
src = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
body_src = src[src.index("def save_json_state("):src.index("# --- accounts.json")]
assert "f.flush()" in body_src and "os.fsync(f.fileno())" in body_src, body_src
assert body_src.index("os.fsync(f.fileno())") < body_src.index("os.replace("), \
    "fsync must happen BEFORE the rename"
assert "os.replace(" in body_src
ok("the helper flushes and fsyncs the contents before os.replace (durability, not just atomicity)")

# and it is the ONLY atomic-write implementation left in the file
assert src.count("os.replace(") == 1, \
    "%d os.replace() call sites: there should be exactly one, inside save_json_state" % src.count("os.replace(")
assert "except Exception:\n        db = {}" not in src and "except Exception:\n        p = {}" not in src, \
    "a broad corruption-laundering except survives"
ok("exactly one os.replace() remains (inside the shared helper) and no loader launders corruption "
   "into empty state")

# ==================================================================== liveness
assert alive()
st, j = api("GET", "/api/learning/registry?room=" + ROOM, None, TOK["CorA"])
assert st == 200, (st, j)
ok("after every corruption and malformed-request case, ordinary requests still succeed")

httpd.shutdown()
print("\nAll %d state-corruption / HTTP-hardening checks passed." % passed)
