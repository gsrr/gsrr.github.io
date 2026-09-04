# Phase 14A.10A — PASSIVE POPULATION INCOME IS DAILY, AND LEARNING PAYS 500 / 2500.
#
#   python tests/daily_passive_income_test.py
#
# The 14A.10 audit proved that nothing mints troops: one normal AI reached ~2,700 troops by
# room-hour 50 and ~14,300 by room-hour 120 purely by converting legitimately earned gold, because
# 10% of population per HOUR compounds with every territory taken and nothing ever removes a troop.
# Leaving a server running was therefore the strongest strategy in the game.
#
# This phase changes exactly two things: the passive-income PERIOD (hour -> day) and the two
# learning reward amounts (160/640 -> 500/2500). This file pins both, and pins the things that
# must NOT have moved with them -- conscription's own hourly period above all.
import io, json, os, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server                                                    # noqa: E402
from game import config as GC                                    # noqa: E402
from game import economy as GE                                   # noqa: E402
from learning import completion as LC                            # noqa: E402

passed = 0


def ok(name):
    global passed
    passed += 1
    print("  ok -", name)


DAY = GC.PASSIVE_PERIOD_SECONDS
pg = GE.calculate_passive_gold

# ===================================================================== the canonical constants
assert DAY == 86400, DAY
assert GC.PASSIVE_MAX_CATCHUP_DAYS == 3, GC.PASSIVE_MAX_CATCHUP_DAYS
assert GC.GOLD_RATE == 0.10, GC.GOLD_RATE
assert not hasattr(GC, "GROW_SECONDS"), "the ambiguous hourly name must not survive in game/config"
assert not hasattr(GC, "ECON_MAX_CATCHUP"), "...nor the ambiguous hourly catch-up name"
assert server.PASSIVE_PERIOD_SECONDS == DAY
assert server.PASSIVE_MAX_CATCHUP_DAYS == GC.PASSIVE_MAX_CATCHUP_DAYS
ok("the passive period is ONE DAY (86400s) with a 3-day catch-up, named so the unit cannot be "
   "misread, and server.py mirrors game/config.py rather than holding a second copy")

# ===================================================================== A/B/C. whole periods only
now = 1_000_000.0
g, last = pg(0, 150, 0, now - (DAY - 60), now)                 # 23h59m
assert (g, last) == (0, now - (DAY - 60)), (g, last)
ok("A. under 24 h there is NO passive payout and the clock does not move (no partial-day gold, "
   "no per-second trickle)")

g, last = pg(0, 150, 0, now - DAY, now)
assert g == 15 and last == now, (g, last)
ok("B. at exactly 24 h a home base of 150 people pays round(150 x 0.10) = 15 gold, once")

g, last = pg(0, 150, 0, now - 2 * DAY, now)
assert g == 30 and last == now, (g, last)
g, last = pg(0, 150, 0, now - 3 * DAY, now)
assert g == 45, g
ok("C. 48 h pays exactly two days (30) and 72 h exactly three (45) -- the rate is per day, not "
   "per hour")

# ===================================================================== D. the catch-up ceiling
g, _ = pg(0, 150, 0, now - 10 * DAY, now)
assert g == GC.PASSIVE_MAX_CATCHUP_DAYS * 15 == 45, g
g, last = pg(0, 150, 0, now - 1000 * DAY, now)
assert g == 45 and last == now, (g, last)
ok("D. a long absence settles at most PASSIVE_MAX_CATCHUP_DAYS (3) days, and the clock is still "
   "brought fully up to date so the unpaid remainder cannot accumulate as a debt")

# ===================================================================== E/F. what feeds the rate
g, _ = pg(0, 1000, 0, now - DAY, now)
assert g == 100, g
g, _ = pg(0, 10000, 0, now - DAY, now)
assert g == 1000, g
ok("E. home base population feeds the rate: 1,000 people = 100 gold/day, 10,000 = 1,000 gold/day")

g, _ = pg(0, 150, 850, now - DAY, now)
assert g == 100, g                                             # (150 + 850) * 0.10
ok("F. owned-territory population feeds the SAME rate through region_pop: (150 + 850) x 0.10 = "
   "100 gold/day")

# ===================================================================== G. which holdings count
DATA = tempfile.mkdtemp(prefix="daily14a10a_")
server.ROOMS_DIR = os.path.join(DATA, "rooms")
server.ACCT = os.path.join(DATA, "accounts.json")
server.DATA = os.path.join(DATA, "visits.json")
server.PROG_DIR = os.path.join(DATA, "progress")
server.TERR_CATALOG = os.path.join(DATA, "learned.json")
os.makedirs(server.ROOMS_DIR, exist_ok=True)
os.makedirs(server.PROG_DIR, exist_ok=True)
USERS = ["DayA"]
json.dump({"users": {u: {} for u in USERS}, "codes": {}},
          io.open(server.ACCT, "w", encoding="utf-8"))
for u in USERS:
    server._tokens["t" + u] = {"user": u, "exp": time.time() + 9999, "admin": False}
httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT
ROOM = "DAILY"


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


server.set_room(ROOM)
if not server.terr_catalog.loaded:
    server.terr_catalog.load()
WORLD = sorted(server.playable_territory_ids())
OFFMAP = sorted(t for t, r in server.terr_catalog.territories.items() if r.get("mapId") != "world")
with server.terr_lock:
    server.save_territory_store({
        WORLD[0]: {"owner": "DayA", "avatar": "A", "pop": 200, "troops": []},
        OFFMAP[0]: {"owner": "DayA", "avatar": "A", "pop": 5000, "troops": []},
        "A1/legacy.json": {"owner": "DayA", "avatar": "A", "pop": 9000, "troops": []},
    })
st, econ = api("GET", "/api/economy?room=" + ROOM, None, "tDayA")
assert st == 200, (st, econ)
# region_pop for the ECONOMY is server.user_region_pop, the pre-existing authority -- this phase
# did not touch which records qualify, so the check is that the DAILY rate is applied to it.
server.set_room(ROOM)
rp = server.user_region_pop(server.load_territory_store(), "DayA")
assert econ["goldIncome"] == int(round((econ["population"] + rp) * GC.GOLD_RATE)), (econ, rp)
ok("G. the published rate is (home + the existing region-population authority) x 10%%, unchanged "
   "in WHICH records it reads -- only its period changed (goldIncome=%d/day)" % econ["goldIncome"])

# ===================================================================== H. no double credit
server.set_room(ROOM)
with server.econ_lock:
    es = server.load_econ_store()
    e = server.econ_get(es, "DayA", time.time(), 0)
    e["lastGold"] = time.time() - 2 * DAY
    e["gold"] = 0
    server.save_econ_store(es)
fixed = time.time()
server.set_room(ROOM)
with server.econ_lock:
    es = server.load_econ_store()
    first = server.econ_get(es, "DayA", fixed, 0)["gold"]
    again = server.econ_get(es, "DayA", fixed, 0)["gold"]
    third = server.econ_get(es, "DayA", fixed, 0)["gold"]
assert first == again == third, (first, again, third)
ok("H. repeated settlement at the same instant credits once (%d): `last` advances by the consumed "
   "periods, exactly as before" % first)

# ===================================================================== I. one authority, both sides
src = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
assert src.count("game_economy.calculate_passive_gold(") == 1, \
    "there must be exactly ONE passive-income call site"
ai_src = src[src.index("def ai_econ("):src.index("def _ai_recruit(")]
assert "econ_get(" in ai_src and "calculate_passive_gold" not in ai_src, \
    "the AI must earn through econ_get, not through a second formula"
assert "GOLD_RATE" not in ai_src, "no AI-specific rate or divisor"
g_human, _ = pg(0, 400, 0, now - DAY, now)
assert g_human == 40, g_human
ok("I. humans and the AI share ONE authority: ai_econ() delegates to econ_get() which calls the "
   "single calculate_passive_gold(), so a 400-population AI earns the same 40 gold/day the "
   "formula gives anybody with 400 people -- no AI divisor, no second implementation")

# ===================================================================== J. old timestamps
twelve_h_ago = now - 12 * 3600
g, last = pg(500, 150, 0, twelve_h_ago, now)
assert (g, last) == (500, twelve_h_ago), (g, last)
ok("J. an EXISTING lastGold written under the hourly rule is read as plain elapsed seconds: 12 "
   "hours ago earns nothing yet -- not 12 hourly payouts and not 12 daily ones")

# ===================================================================== conscription stays HOURLY
assert server.GROW_SECONDS == 3600, server.GROW_SECONDS
assert server.CONSCRIPT_MAX_CATCHUP == 24, server.CONSCRIPT_MAX_CATCHUP
cs = src[src.index("def conscript_tick("):src.index("def conscript_loop(")]
assert cs.count("GROW_SECONDS") == 4 and "PASSIVE_PERIOD_SECONDS" not in cs, \
    "conscription must still settle on the HOURLY period"
head = subprocess.run(["git", "show", "HEAD:english_learning/server.py"],
                      cwd=os.path.dirname(ROOT), capture_output=True, text=True,
                      encoding="utf-8").stdout
if head:
    a = head[head.index("def conscript_tick("):head.index("def conscript_loop(")]
    assert a == cs, "conscript_tick must be byte-identical to the committed version"
ok("conscription is UNCHANGED and still hourly: GROW_SECONDS is 3600, its 24-hour catch-up is "
   "intact, conscript_tick is byte-identical to the committed version, and it never reads the "
   "daily period")

# ===================================================================== learning reward amounts
assert (GC.PASS_GOLD, GC.MASTERY_GOLD) == (500, 2500), (GC.PASS_GOLD, GC.MASTERY_GOLD)
assert GC.PASS_GOLD + GC.MASTERY_GOLD == 3000
assert LC.PASS_MARK == 80, LC.PASS_MARK
assert server.PASS_GOLD == GC.PASS_GOLD and server.LESSON_MASTERY_GOLD == GC.MASTERY_GOLD
ok("PASS_GOLD 500, MASTERY_GOLD 2500, together 3000; PASS_MARK is still 80 and server.py still "
   "mirrors the constants instead of restating them")

st, econ2 = api("GET", "/api/economy?room=" + ROOM, None, "tDayA")
assert econ2["passGold"] == 500 and econ2["masteryGold"] == 2500, econ2
ok("the client is told the real amounts by /api/economy (passGold 500, masteryGold 2500), so no "
   "reward figure is hard-coded in the UI")

reg = io.open(os.path.join(ROOT, "learning", "registry.json"), encoding="utf-8").read()
for n in ("500", "2500", "3000"):
    assert n not in reg, "the registry must never state a reward amount: %s" % n
ok("content independence holds: registry.json names reward POLICIES and no amount at all")

# a GUEST still earns nothing: the reward path needs an account, and this phase changed only the
# AMOUNTS, never who may be paid.
st, j = api("POST", "/api/learning/attempt", {"activityId": "english.prea1.taipei.zoo.quiz3",
                                              "answers": []}, None)
assert st == 401 and "Not logged in" in json.dumps(j), (st, j)
ok("guest behaviour is unchanged: an unauthenticated attempt is refused 401, so neither the 500 "
   "nor the 2500 can reach an account-less caller")

httpd.shutdown()
print("\nAll %d daily-passive-income checks passed." % passed)
