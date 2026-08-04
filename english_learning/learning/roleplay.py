"""Server-authoritative Level 10 Role-play (Phase 4C).

Role-play is the only Rule A level whose score was still computed in the browser. It is stateful and
interactive, so it does not fit the stateless GRADERS table; like Read-Along and Matching it is a
`scorerType`, here `roleplay_local`.

The authority model is a SERVER-OWNED SESSION. The server owns the graph, the current node, the RNG
that picks branches, the classifier thresholds, and the turn/pass counters. The client owns rendering
and collecting the learner's words — nothing else. A client-submitted transcript is never accepted as
proof of what happened (§6): the server already knows.

Everything below is an EXACT port of the shipped browser implementation
(`roleplay/engine.js` + `roleplay/classifier.js`), not an improvement of it:

  * `tokens`/`content_words`/`close`/`has`/`coverage` mirror classifier.js character for character,
    including the duplicate-token behaviour of `coverage` (a target word repeated twice counts twice
    in both numerator and denominator).
  * `score_route` keeps the same three terms: best example coverage + keyword bonus
    (`min(0.35, 0.18 + 0.09*hits)`) + `meaning` coverage * 0.1, clamped to 1.
  * `classify` keeps the same four-way decision order: data-driven PARTIAL, floor, pass+objective,
    then the middle band.
  * `submit` increments `turns` on EVERY submission (PASS, PARTIAL and OFF_TOPIC alike) and only
    advances the node on PASS, exactly as the engine does.
  * `passes` counts history entries whose result is PASS.

Threshold note: the lesson caller constructs the classifier as
`new RP.classifiers.local({ pass: 0.5, floor: 0.2 })`, overriding the class defaults of 0.6 / 0.28.
Level 10 therefore scores against 0.5 / 0.2, and that pair is server-owned config here, never client
input.
"""
import hashlib
import math
import re
import secrets

SCORER_TYPE = "roleplay_local"

# classifier.js LocalClassifier defaults — kept for parity tests; NOT what level 10 uses.
DEFAULT_PASS = 0.6
DEFAULT_FLOOR = 0.28
# index.html startRolePlay(): new RP.classifiers.local({ pass: 0.5, floor: 0.2 })
LESSON_PASS = 0.5
LESSON_FLOOR = 0.2

SESSION_TTL = 6 * 3600      # an abandoned session is dropped after this many seconds (§30)
# Defensive only (§19). The shipped engine NEVER terminates on max_turns — it merely sets an
# unread `info.maxTurnsReached` flag — so a learner who never passes can loop forever. This ceiling
# exists to stop a corrupt or abandoned session growing without bound; it is set far above any real
# conversation (the authored Taipei graphs declare max_turns 24) so it cannot alter a valid flow.
HARD_TURN_CAP = 200

RESULT_PASS = "PASS"
RESULT_PARTIAL = "PARTIAL"
RESULT_OFF_TOPIC = "OFF_TOPIC"

STOP = set(
    ("a an the is are am was were be been to of and or but in on at it its i you he she we they "
     "me him her them my your his our this that these those do does did will would can could should "
     "have has had not no yes so if then there here as with for").split(" ")
)

_NON_TOKEN = re.compile(r"[^a-z0-9\s']")
_WS = re.compile(r"\s+")


# ============================== classifier.js text utilities ==============================
def tokens(s):
    """Exact port: lowercase, replace every char outside [a-z0-9\\s'] with a space, split on runs."""
    lowered = (s or "").lower()
    return [t for t in _WS.split(_NON_TOKEN.sub(" ", lowered)) if t]


def content_words(toks):
    """Drop stop-words; if a phrase is ALL stop-words, keep them (classifier.js does the same)."""
    c = [w for w in toks if w not in STOP]
    return c if c else toks


def close(a, b):
    """Short-word fuzzy match: prefix match, or edit distance <= 1. Absorbs STT slips."""
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 3 and (a.startswith(b) or b.startswith(a)):
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    i = j = e = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            e += 1
            if e > 1:
                return False
            if len(a) > len(b):
                i += 1
            elif len(b) > len(a):
                j += 1
            else:
                i += 1
                j += 1
    return e + (len(a) - i) + (len(b) - j) <= 1


def has(said_set, said_arr, w):
    return w in said_set or any(close(s, w) for s in said_arr)


def coverage(user_arr, user_set, target_toks):
    """Fraction of the target's CONTENT words present in the user's words.

    Duplicates are deliberately NOT collapsed: `content_words` returns a list, so a target word that
    appears twice is tested twice and counts twice in both hit and total — same as classifier.js.
    """
    words = content_words(target_toks)
    if not words:
        return 0
    hit = sum(1 for w in words if has(user_set, user_arr, w))
    return hit / float(len(words))


# ============================== LocalClassifier ==============================
class LocalClassifier:
    def __init__(self, pass_threshold=None, floor=None):
        self.PASS = DEFAULT_PASS if pass_threshold is None else pass_threshold
        self.FLOOR = DEFAULT_FLOOR if floor is None else floor

    def score_route(self, route, user_arr, user_set):
        best = 0
        for ex in (route.get("examples") or []):
            best = max(best, coverage(user_arr, user_set, tokens(ex)))
        kws = route.get("keywords") or []
        kw = 0
        if kws:
            hit = sum(1 for k in kws if has(user_set, user_arr, str(k).lower()))
            kw = min(0.35, 0.18 + 0.09 * hit) if hit else 0
        mean = coverage(user_arr, user_set, tokens(route.get("meaning"))) * 0.1
        return min(1, best + kw + mean)

    def objective_met(self, route, user_arr, user_set, user_text):
        obj = route.get("objective")
        markers = (obj or {}).get("markers") or []
        if not obj or not markers:
            return True                       # no explicit objective => met
        lc = (user_text or "").lower()
        for m in markers:
            mm = str(m).lower()
            if " " in mm:
                if mm in lc:                  # phrase marker
                    return True
            elif has(user_set, user_arr, mm):  # single-word marker
                return True
        return False

    def classify(self, user_text, node):
        """{result, intent, route, objectiveMet, scores, reason} — same decision order as JS."""
        user_arr = tokens(user_text)
        user_set = set(user_arr)
        routes = node.get("routes") or []

        scored = [{"route": r, "intent": r.get("intent"),
                   "score": self.score_route(r, user_arr, user_set)} for r in routes]
        # JS Array.prototype.sort is stable (ES2019+), and so is Python's — ties keep graph order.
        scored.sort(key=lambda x: -x["score"])
        scores = [{"intent": s["intent"], "score": _to_fixed3(s["score"])} for s in scored]

        def out(result, top, objective_met, reason):
            return {"result": result,
                    "intent": top["intent"] if top else None,
                    "route": top["route"] if top else None,
                    "objectiveMet": bool(objective_met),
                    "scores": scores,
                    "reason": reason}

        if not scored:
            return out(RESULT_OFF_TOPIC, None, False, "node has no routes")
        top = scored[0]
        # (a) data-driven PARTIAL: a route explicitly flagged partial
        if top["route"].get("partial") and top["score"] >= self.FLOOR:
            return out(RESULT_PARTIAL, top, False,
                       "matched a 'partial' route (semantically related, objective not met)")
        # (b) clear off-topic
        if top["score"] < self.FLOOR:
            return out(RESULT_OFF_TOPIC, None, False,
                       "top score %s < floor %s" % (_fixed2(top["score"]), self.FLOOR))
        # (c) confident enough to be a real answer
        if top["score"] >= self.PASS:
            met = self.objective_met(top["route"], user_arr, user_set, user_text)
            if met:
                return out(RESULT_PASS, top, True,
                           "top score %s >= pass %s" % (_fixed2(top["score"]), self.PASS))
            return out(RESULT_PARTIAL, top, False,
                       "intent matched but learning objective markers absent")
        # (d) middle band
        return out(RESULT_PARTIAL, top, False,
                   "top score %s in [%s,%s)" % (_fixed2(top["score"]), self.FLOOR, self.PASS))


def _to_fixed3(x):
    """JS `+score.toFixed(3)` — round-half-away-from-zero at 3dp, then back to a number."""
    return float(("%.3f" % x))


def _fixed2(x):
    return "%.2f" % x


def lesson_classifier():
    """The classifier level 10 actually uses: thresholds 0.5 / 0.2, server-owned."""
    return LocalClassifier(LESSON_PASS, LESSON_FLOOR)


# ============================== graph validation (§10) ==============================
def validate_graph(graph):
    """Return a list of human-readable errors; empty means the graph is safe to run."""
    errs = []
    if not isinstance(graph, dict):
        return ["graph must be an object"]
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return ["graph.nodes must be a non-empty list"]

    ids = []
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            errs.append("node %d is not an object" % i)
            continue
        nid = n.get("id")
        if not isinstance(nid, str) or not nid.strip():
            errs.append("node %d has a missing/malformed id" % i)
            continue
        ids.append(nid)
        npc = n.get("npc")
        terminal = bool(n.get("end")) or not (n.get("routes") or [])
        if not isinstance(npc, dict) or not isinstance(npc.get("text"), str) or not npc["text"]:
            errs.append("node %s has no npc.text to display" % nid)
        routes = n.get("routes")
        if routes is not None and not isinstance(routes, list):
            errs.append("node %s routes must be a list" % nid)
            continue
        for j, r in enumerate(routes or []):
            if not isinstance(r, dict):
                errs.append("node %s route %d is not an object" % (nid, j))
                continue
            if not isinstance(r.get("intent"), str) or not r["intent"]:
                errs.append("node %s route %d has no intent" % (nid, j))
            ex = r.get("examples")
            kw = r.get("keywords")
            if ex is not None and not isinstance(ex, list):
                errs.append("node %s route %s examples must be a list" % (nid, r.get("intent")))
            if kw is not None and not isinstance(kw, list):
                errs.append("node %s route %s keywords must be a list" % (nid, r.get("intent")))
            if not (ex or kw):
                errs.append("node %s route %s can never match: no examples and no keywords"
                            % (nid, r.get("intent")))
            nxt = r.get("next_nodes")
            if not isinstance(nxt, list) or not nxt:
                errs.append("node %s route %s has no next_nodes" % (nid, r.get("intent")))
                continue
            for c in nxt:
                if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not c["id"]:
                    errs.append("node %s route %s has a malformed next_node" % (nid, r.get("intent")))
                    continue
                w = c.get("weight")
                if w is not None and (isinstance(w, bool) or not isinstance(w, (int, float))
                                      or w <= 0 or w != w or w in (float("inf"),)):
                    errs.append("node %s route %s next_node %s has a malformed weight %r"
                                % (nid, r.get("intent"), c["id"], w))
        if terminal and (n.get("routes") or []):
            errs.append("node %s is marked end but still declares routes" % nid)

    if len(ids) != len(set(ids)):
        errs.append("graph has duplicate node ids")
    known = set(ids)
    for n in nodes:
        if not isinstance(n, dict):
            continue
        for r in (n.get("routes") or []):
            if not isinstance(r, dict):
                continue
            for c in (r.get("next_nodes") or []):
                if isinstance(c, dict) and isinstance(c.get("id"), str) and c["id"] not in known:
                    errs.append("node %s route %s targets unknown node %r"
                                % (n.get("id"), r.get("intent"), c["id"]))
    start = graph.get("start")
    if not isinstance(start, str) or start not in known:
        errs.append("graph.start %r is not a known node id" % (start,))
    if not any(bool(n.get("end")) or not (n.get("routes") or [])
               for n in nodes if isinstance(n, dict)):
        errs.append("graph has no terminal node, so a session could never complete")
    mt = graph.get("max_turns")
    if mt is not None and (isinstance(mt, bool) or not isinstance(mt, int) or mt < 1):
        errs.append("graph.max_turns must be a positive integer when present")
    strat = graph.get("strategy")
    if strat is not None and strat not in ("weighted",):
        errs.append("graph.strategy %r is not supported server-side" % (strat,))
    return errs


def graph_version(raw_text):
    """Short content hash. Binds a session to the exact graph it started on."""
    return hashlib.sha256((raw_text or "").encode("utf-8")).hexdigest()[:16]


def _nodes_by_id(graph):
    return {n["id"]: n for n in (graph.get("nodes") or [])
            if isinstance(n, dict) and isinstance(n.get("id"), str)}


def is_terminal(node):
    """engine.js `_enter`: a node ends the conversation if it is flagged end or has no routes."""
    return bool(node.get("end")) or not (node.get("routes") or [])


def select_next(route, graph, rng):
    """engine.js `_selectNext` + `strategies.weighted`, with the RNG supplied by the SERVER.

    Note for the current Taipei content: every route declares exactly one next_node, so the weighted
    draw always has a single candidate and is effectively deterministic. The algorithm is ported
    faithfully anyway so multi-branch graphs behave identically to the browser.
    """
    by_id = _nodes_by_id(graph)
    cands = [c for c in (route.get("next_nodes") or [])
             if isinstance(c, dict) and c.get("id") in by_id]
    if not cands:
        return None
    total = sum((c.get("weight") or 1) for c in cands)
    r = rng.random() * total
    for c in cands:
        r -= (c.get("weight") or 1)
        if r <= 0:
            return c["id"]
    return cands[-1]["id"]


# ============================== session lifecycle ==============================
def new_session_id():
    return secrets.token_hex(16)


def start_session(graph, version, activity_id, now):
    """A fresh server-owned session sitting on the graph's start node."""
    by_id = _nodes_by_id(graph)
    start = graph.get("start")
    node = by_id.get(start)
    if node is None:
        return None
    session = {"activityId": activity_id, "graphVersion": version, "currentNodeId": start,
               "turns": 0, "passes": 0, "visited": [start],
               "createdAt": now, "updatedAt": now,
               # engine.js `_enter` finishes immediately if the start node is terminal
               "completed": is_terminal(node)}
    return session


def is_expired(session, now):
    created = (session or {}).get("createdAt")
    return not isinstance(created, int) or (now - created) > SESSION_TTL


def apply_response(session, graph, text, rng, now, classifier=None):
    """One authoritative turn. Returns (status, info); `session` is mutated only on 'ok'.

    Mirrors engine.js `submit` exactly:
      * `turns` increments for EVERY submission, whatever the classification
      * the node advances only on PASS with a resolvable next node
      * `passes` is the running count of PASS results
    """
    if not isinstance(session, dict):
        return "unknown", None
    if session.get("completed"):
        return "complete", None
    by_id = _nodes_by_id(graph)
    node = by_id.get(session.get("currentNodeId"))
    if node is None:
        return "corrupt", None

    cls = (classifier or lesson_classifier()).classify(text, node)
    session["turns"] = int(session.get("turns") or 0) + 1
    next_id = None
    if cls["result"] == RESULT_PASS:
        session["passes"] = int(session.get("passes") or 0) + 1
        next_id = select_next(cls["route"], graph, rng)
        if next_id:
            session["currentNodeId"] = next_id
            if next_id not in session.setdefault("visited", []):
                session["visited"].append(next_id)
            if is_terminal(by_id[next_id]):
                session["completed"] = True
    # Defensive ceiling only — see HARD_TURN_CAP. Never reached by a real conversation.
    capped = False
    if not session["completed"] and session["turns"] >= HARD_TURN_CAP:
        session["completed"] = True
        capped = True
    session["updatedAt"] = now

    hint = None
    fallback = node.get("fallback") or {}
    if cls["result"] == RESULT_PARTIAL:
        hint = ((cls.get("route") or {}).get("hint")
                or ((fallback.get("partial") or {}).get("message")))
    elif cls["result"] == RESULT_OFF_TOPIC:
        hint = (fallback.get("off_topic") or {}).get("message")

    info = {"result": cls["result"], "intent": cls["intent"], "hint": hint,
            "nextNodeId": next_id, "capped": capped}
    return "ok", info


def result_of(session):
    """Level 10 evidence: recordScore(10, passes, turns). `pct` uses JS Math.round semantics."""
    turns = int((session or {}).get("turns") or 0)
    passes = int((session or {}).get("passes") or 0)
    pct = int(math.floor(passes / float(turns) * 100 + 0.5)) if turns > 0 else 0
    return {"passes": passes, "turns": turns, "pct": pct}


def prune_sessions(sessions, now, keep=8):
    """Drop expired sessions and compact completed ones, oldest first."""
    if not isinstance(sessions, dict):
        return {}
    live = {sid: s for sid, s in sessions.items()
            if isinstance(s, dict) and not is_expired(s, now)}
    done = sorted((sid for sid, s in live.items() if s.get("completed")),
                  key=lambda sid: live[sid].get("updatedAt") or 0)
    for sid in done[:-keep] if len(done) > keep else []:
        live.pop(sid, None)
    return live
