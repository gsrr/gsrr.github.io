"""Learning Domain API — the single entry point the HTTP layer talks to (§10).

server.py must not become the Learning Engine: it authenticates, loads/saves the progress blob and
moves gold. Everything else (identity resolution, content access, grading, completion, qualification
granting, reward policy) lives behind LearningService.

The service is stateless with respect to players — every method takes the player's `learning` dict
and returns it mutated for the caller to persist, exactly like the pure modules underneath.
"""
from . import (completion, content, grading, identity, matching, qualifications, registry,
               reward_ledger, rewards, roleplay, stt_scoring)

# stable machine reasons returned to the client (never internal exception detail)
REASON_NOT_GRADABLE = "not_gradable"
REASON_BAD_ANSWERS = "bad_answers"
REASON_CONTENT_UNAVAILABLE = "content_unavailable"


def _stored(state, table, key):
    """One record out of a per-account progress table, tolerating corrupt stored state.

    Persisted JSON can be malformed (hand-edited, truncated, or written by an older build), and a
    non-dict table must never crash a read — an unreadable record simply means "no evidence yet".
    """
    tbl = (state or {}).get(table)
    if not isinstance(tbl, dict):
        return None
    rec = tbl.get(key)
    return rec if isinstance(rec, dict) else None


class LearningService:
    def __init__(self, reg=None, content_root=None, reward_amounts=None):
        self.registry = reg if isinstance(reg, registry.Registry) else registry.REGISTRY
        self.content_root = content_root
        # Authoritative reward amounts, injected by the caller from GAME CONFIG (§14/§15).
        # Content/registry can only name a policy; the number lives here and nowhere else.
        self.reward_amounts = dict(reward_amounts or {})

    # ---- identity ----
    def resolve_activity(self, activity_id=None, lesson_id=None, activity=None):
        """Canonical activityId from canonical OR legacy Phase 3A input; None if unregistered."""
        return self.registry.resolve_activity_id(activity_id, lesson_id, activity)

    def get_activity(self, activity_id):
        return self.registry.activity(activity_id)

    def completion_key(self, activity_id):
        """The key NEW writes use — always the canonical activityId."""
        return activity_id

    def completion_keys(self, activity_id):
        """Canonical key first, then every legacy alias — the read order for merge_completions()."""
        return [activity_id] + self.registry.legacy_keys_for(activity_id)

    def qualifications_for_activity(self, activity_id):
        return self.registry.qualification_ids_for(activity_id)

    # ---- grading ----
    def grade_attempt(self, activity_id, answers):
        """(result, error_reason). Content and grader are chosen by the REGISTRY, never by the client."""
        spec = self.registry.activity(activity_id)
        if not spec:
            return None, REASON_NOT_GRADABLE
        grader_type = spec.get("graderType")
        if not grading.is_supported(grader_type):
            return None, REASON_NOT_GRADABLE
        if not isinstance(answers, list):
            return None, REASON_BAD_ANSWERS
        items = content.load_activity_items(
            self.registry.content_path_of(activity_id), spec.get("contentKey"),
            self.content_root, self.registry.approved_content_paths())
        if items is None:
            return None, REASON_CONTENT_UNAVAILABLE
        # graderConfig comes from the REGISTRY, never from the request (§8) — a client cannot point a
        # grader at a different field to make its own answer look correct.
        return grading.grade(grader_type, items, answers,
                             self.registry.grader_config_of(activity_id)), None

    # ---- reward policy ----
    def reward_for(self, activity_id):
        """{'type','amount','itemId','once'} for this activity — from the server-owned allowlist."""
        return rewards.resolve(self.registry.reward_policy_of(activity_id), self.reward_amounts)

    def economic_state_is_readable(self, state, activity_id=None, lesson_id=None):
        """Can this learner's payment history answer "already paid?" with certainty?

        Strictness is scoped to the store that AUTHORITATIVELY records the payment for that grant:

          activity gold -> activityCompletions[key].rewarded
          lesson  gold -> lessonCompletionHistory (+ the legacy lessonCompletions record)

        The reward ledger is deliberately NOT consulted here. Phase 5E documents it as the audit
        trail written alongside the activity payout, not its gate, and it also holds cosmetics — so
        letting a damaged COSMETIC ledger veto a legitimate gold payment would punish the learner for
        an unrelated record. reward_ledger.record_grant() separately refuses to overwrite a corrupt
        ledger, so the evidence still survives.

        Returns False on corruption, which callers turn into "no payout" — never into "pay again".
        Nothing is repaired or erased: the damaged bytes stay on disk so the problem stays
        diagnosable.
        """
        if activity_id is not None:
            if qualifications.completions_state(
                    state, self.completion_keys(activity_id)) == qualifications.CORRUPT:
                return False
        if lesson_id is not None:
            if completion.history_is_corrupt(state, lesson_id):
                return False
        return True

    def grant_reward(self, state, scope, source_id, policy_id, now):
        """Resolve a policy and record it in the learner's ledger. Returns (state, granted_or_None).

        ONE path for every scope and every reward type (Phase 5E). The ledger key is derived from
        (scope, sourceId, policyId), so a `once` reward is idempotent against retries, replays and
        double settlements without each call site inventing its own guard.

        Returns the resolved descriptor when this call actually granted it, else None. Only a `gold`
        descriptor asks the CALLER to move the economy; cosmetic/profile/gameplay rewards are fully
        discharged by the ledger entry, and nothing in this codebase applies a gameplay effect yet.
        """
        reward = rewards.resolve(policy_id, self.reward_amounts)
        if reward["type"] == "none":
            return state, None
        state, newly = reward_ledger.record_grant(state, scope, source_id, policy_id, reward, now)
        return state, (reward if newly else None)

    def reward_ledger_view(self, state):
        """Read-only ledger: what was granted, when, and which items the learner now owns."""
        return {"entries": reward_ledger.entries(state),
                "ownedItems": reward_ledger.owned_items(state),
                "goldGranted": reward_ledger.total_granted(state, "gold")}

    # ---- completion + qualification ----
    def read_completion(self, state, activity_id):
        """The player's logical completion for this activity, merged across canonical + legacy keys."""
        return qualifications.merge_completions(state, self.completion_keys(activity_id))

    def record_attempt(self, state, activity_id, result, now):
        """Apply a graded attempt to the player's learning state. Idempotent; mutates & returns state.

        A pass:
          - writes/refreshes the CANONICAL completion record (legacy aliases are left untouched, so
            Phase 3A progress is preserved and readable, never rewritten or deleted);
          - grants every qualification the activity certifies (idempotent, many-to-many);
          - awards the reward only on the first pass across ALL aliases (`once`).
        A failure changes nothing at all.
        """
        # §1: the authoritative LATEST score is persisted for every graded attempt, pass or fail,
        # independently of the completion record below. Rule A averages these, not the pass records.
        if isinstance(result, dict) and isinstance(result.get("total"), int) and result["total"] > 0:
            if not isinstance(state, dict):
                state = {}
            qualifications.record_activity_score(
                state, activity_id, result.get("correct") or 0, result["total"],
                result.get("pct") or 0, now)
        prior = self.read_completion(state, activity_id)
        out = {"activityId": activity_id, "passed": bool(result and result.get("passed")),
               "alreadyCompleted": bool(prior and prior.get("passedAt")),
               "granted": [], "grantedNow": [], "rewardType": "none", "rewardAmount": 0,
               "rewarded": False}
        if not out["passed"]:
            # Still settle the lesson so the outcome shape is uniform for callers. A failure adds no
            # pass, so it can never newly complete anything it has not already earned.
            self._settle_lesson(state, self.registry.lesson_of_activity(activity_id), now, out)
            return state, out
        state, newly = qualifications.grant_qualifications(
            state, self.qualifications_for_activity(activity_id), now)
        out["granted"] = self.qualifications_for_activity(activity_id)
        out["grantedNow"] = newly
        reward = self.reward_for(activity_id)
        already_rewarded = bool(prior and prior.get("rewarded"))
        # Phase 7C.1: an ECONOMIC payout may only proceed when the payment history is readable.
        # A missing record still pays (the learner genuinely has not passed before); a malformed one
        # refuses, because we cannot prove the money was not already handed over.
        pay = reward["amount"] > 0 and not (reward["once"] and already_rewarded)
        if pay and rewards.is_economic(self.registry.reward_policy_of(activity_id)):
            if not self.economic_state_is_readable(state, activity_id=activity_id):
                out["rewardBlocked"] = "corrupt_payment_history"
                pay = False
        if pay:
            out["rewardType"], out["rewardAmount"], out["rewarded"] = reward["type"], reward["amount"], True
        # Phase 5E: the activity payout keeps its historical `rewarded` idempotency EXACTLY as it was
        # (that flag is what existing behaviour and tests depend on); the ledger is written alongside
        # it as the audit trail, and is what carries non-gold activity rewards if any are ever added.
        if pay or reward["type"] not in ("none", "gold"):
            state, _ = self.grant_reward(state, "activity", activity_id,
                                         self.registry.reward_policy_of(activity_id), now)
        qualifications.record_completion(
            state, self.completion_key(activity_id),
            passed_at=(prior or {}).get("passedAt") or now,     # first pass wins, never re-dated
            pct=int(result.get("pct") or 0),
            rewarded=already_rewarded or pay)
        # §14: a server-authoritative activity pass may complete its parent lesson. Derived here, never
        # asserted by the client, and a no-op for every lesson without an active completionPolicy.
        self._settle_lesson(state, self.registry.lesson_of_activity(activity_id), now, out)
        return state, out

    # ---- Read-Along / STT (Phase 3E1) ----
    def is_read_along(self, activity_id):
        return self.registry.scorer_type_of(activity_id) == stt_scoring.SCORER_TYPE

    def read_along_sentences(self, activity_id):
        """The authoritative spoken script for this activity, or None. Server-resolved, never client."""
        if not self.is_read_along(activity_id):
            return None
        return content.load_dialogue(self.registry.content_path_of(activity_id),
                                     self.content_root, self.registry.approved_content_paths())

    def read_along_target(self, activity_id, sentence_index):
        """(target_sentence, total) for a validated index, or (None, total) when out of range."""
        sentences = self.read_along_sentences(activity_id)
        if not sentences:
            return None, 0
        # Strictly integral only. A float must NOT be truncated into a valid index, and a boolean is
        # not a sentence position — both are malformed requests, not sentence 1.
        if isinstance(sentence_index, bool):
            return None, len(sentences)
        if isinstance(sentence_index, int):
            i = sentence_index
        elif isinstance(sentence_index, str) and sentence_index.strip().isdigit():
            i = int(sentence_index.strip())          # the query string always arrives as text
        else:
            return None, len(sentences)
        if i < 0 or i >= len(sentences):
            return None, len(sentences)
        return sentences[i], len(sentences)

    def record_read_along(self, state, activity_id, sentence_index, transcript, now):
        """Score one spoken sentence server-side and fold it into authoritative state.

        The target comes from lesson content and the transcript from the server's own STT — neither is
        taken from the request. Best-per-sentence retry semantics are preserved exactly (§10).
        Returns (state, outcome) or (state, None) when the activity/index cannot be resolved.
        """
        target, total = self.read_along_target(activity_id, sentence_index)
        if target is None:
            return state, None
        if not isinstance(state, dict):
            state = {}
        res = stt_scoring.score_sentence(target, transcript)
        table = state.setdefault("sttProgress", {})
        prog = table.get(activity_id)
        prog = prog if isinstance(prog, dict) else {}
        prog, improved = stt_scoring.apply_sentence_score(
            prog, int(sentence_index), res["pct"], total, now)
        table[activity_id] = prog
        out = {"activityId": activity_id, "sentenceIndex": int(sentence_index), "target": target,
               "score": res["pct"], "improved": improved, "totalSentences": total,
               "activityPct": prog["pct"],
               "activityPassed": prog["pct"] >= stt_scoring.PASS_MARK,
               "granted": [], "grantedNow": [], "rewardAmount": 0, "rewarded": False,
               "alreadyCompleted": False}
        # A Read-Along level has a real 80% threshold, so crossing it is a normal activity completion
        # and goes through the SAME machinery (grants + reward policy) as every deterministic activity.
        if out["activityPassed"]:
            state, act_out = self.record_attempt(
                state, activity_id, {"passed": True, "pct": prog["pct"]}, now)
            for k in ("granted", "grantedNow", "rewardAmount", "rewarded", "alreadyCompleted"):
                out[k] = act_out[k]
            for k in ("lessonId", "lessonCompleted", "lessonCompletedNow", "lessonQualifications",
                      "lessonRewardAmount", "lessonRewarded"):
                out[k] = act_out[k]
        return state, out

    # ---- Role-play (Phase 4C) - server-owned sessions ----
    def is_roleplay(self, activity_id):
        return self.registry.scorer_type_of(activity_id) == roleplay.SCORER_TYPE

    def roleplay_graph(self, activity_id):
        """(graph, version) for a Role-play activity, or (None, None).

        The path comes from the REGISTRY, never from the request, and passes the same three gates as
        every other content read (allowlist -> path shape -> realpath containment). The graph is then
        structurally validated before it is ever run, so a malformed scenario fails closed instead of
        producing a bogus score.
        """
        if not self.is_roleplay(activity_id):
            return None, None
        path = self.registry.scenario_path_of(activity_id)
        graph, raw = content.load_json_document(
            path, self.content_root, self.registry.approved_scenario_paths())
        if not graph or roleplay.validate_graph(graph):
            return None, None
        return graph, roleplay.graph_version(raw)

    @staticmethod
    def _roleplay_prompt(graph, session):
        """The safe display payload for the CURRENT node: the NPC line and nothing else.

        Deliberately excludes routes, examples, keywords, weights and next_nodes - the client must
        not be able to read (or replay) the answer key it is being scored against.
        """
        node = {n.get("id"): n for n in (graph.get("nodes") or [])}.get(session["currentNodeId"])
        node = node or {}
        npc = node.get("npc") or {}
        return {"nodeId": node.get("id"), "text": npc.get("text") or "",
                "gender": npc.get("gender") or graph.get("npc_gender") or "female",
                "objective": node.get("learning_objective") or []}

    def roleplay_view(self, graph, session_id, session):
        """Everything the UI needs, all of it server-derived."""
        res = roleplay.result_of(session)
        return {"sessionId": session_id, "activityId": session.get("activityId"),
                "you": graph.get("you"), "npc": graph.get("npc"),
                "title": graph.get("title"),
                "prompt": self._roleplay_prompt(graph, session),
                "turn": int(session.get("turns") or 0),
                "passes": int(session.get("passes") or 0),
                "completed": bool(session.get("completed")),
                "pct": res["pct"] if session.get("completed") else None}

    def start_roleplay_session(self, state, activity_id, now, rng=None):
        """Open a server-owned session. Returns (state, view) or (state, None).

        Starting a session retires any other open session for the same activity (the UI shows one at
        a time) and prunes expired ones, so live state cannot accumulate.
        """
        graph, version = self.roleplay_graph(activity_id)
        if not graph:
            return state, None
        if not isinstance(state, dict):
            state = {}
        sessions = roleplay.prune_sessions(state.get("roleplaySessions"), now)
        for sid in [s for s, v in sessions.items()
                    if (v or {}).get("activityId") == activity_id and not (v or {}).get("completed")]:
            sessions.pop(sid, None)
        session = roleplay.start_session(graph, version, activity_id, now)
        if not session:
            return state, None
        sid = roleplay.new_session_id()
        sessions[sid] = session
        state["roleplaySessions"] = sessions
        if session["completed"]:                 # a start node that is already terminal
            self._settle_roleplay(state, sid, session, now)
        return state, self.roleplay_view(graph, sid, session)

    def roleplay_respond(self, state, session_id, text, seq, now, rng):
        """One authoritative turn. Returns (state, view_or_None, reason).

        A session lives inside the learning state of the account that owns it, so another account
        simply has no such session - ownership is structural, not a check that can be forgotten.
        `seq` is the turn index the client believes it is answering; a mismatch means a duplicate
        submit, a double-click or a second tab, and is refused without touching the counters.
        """
        if not isinstance(state, dict):
            return state, None, "unknown_session"
        sessions = state.get("roleplaySessions")
        if not isinstance(sessions, dict):
            return state, None, "unknown_session"
        session = sessions.get(session_id)
        if not isinstance(session, dict):
            return state, None, "unknown_session"
        if roleplay.is_expired(session, now):
            sessions.pop(session_id, None)
            return state, None, "session_expired"
        if session.get("completed"):
            return state, None, "session_complete"
        if seq is not None and seq != int(session.get("turns") or 0):
            return state, None, "stale_turn"          # duplicate / out-of-order submit
        graph, version = self.roleplay_graph(session.get("activityId"))
        if not graph:
            return state, None, "content_unavailable"
        if session.get("graphVersion") != version:
            return state, None, "graph_changed"       # never score against a different graph
        status, info = roleplay.apply_response(session, graph, text, rng, now)
        if status != "ok":
            return state, None, status
        view = self.roleplay_view(graph, session_id, session)
        view.update(result=info["result"], hint=info["hint"])
        if session["completed"]:
            view.update(self._settle_roleplay(state, session_id, session, now))
        else:
            view.update(granted=[], grantedNow=[], rewardAmount=0, rewarded=False,
                        lessonCompleted=False, lessonCompletedNow=False,
                        lessonQualifications=[], lessonRewardAmount=0, lessonRewarded=False)
        return state, view, None

    def _settle_roleplay(self, state, session_id, session, now):
        """Persist authoritative Level 10 evidence, LATEST-WINS, and settle the parent lesson.

        Latest-wins matches the shipped behaviour: recordScore overwrites unconditionally, so a
        second (worse) conversation replaces the first. Role-play has no independent pass definition
        beyond its numeric score, so no activityCompletion is written and nothing is granted or paid.
        """
        activity_id = session.get("activityId")
        res = roleplay.result_of(session)
        out = {"granted": [], "grantedNow": [], "rewardAmount": 0, "rewarded": False}
        if res["turns"] > 0:
            prog = state.setdefault("roleplayProgress", {})
            prog[activity_id] = {"passes": res["passes"], "turns": res["turns"], "pct": res["pct"],
                                 "sessionId": session_id, "updatedAt": now}
        state["roleplaySessions"] = roleplay.prune_sessions(state.get("roleplaySessions"), now)
        self._settle_lesson(state, self.registry.lesson_of_activity(activity_id), now, out)
        out["score"] = res
        return out

    # ---- Matching (Phase 3E2) — server-owned rounds ----
    def is_matching(self, activity_id):
        return self.registry.scorer_type_of(activity_id) == matching.SCORER_TYPE

    def matching_vocab(self, activity_id):
        """The authoritative word/picture pairs, or None. Server-resolved; never client-supplied."""
        if not self.is_matching(activity_id):
            return None
        spec = self.registry.activity(activity_id) or {}
        items = content.load_activity_items(
            self.registry.content_path_of(activity_id), spec.get("contentKey") or "vocab",
            self.content_root, self.registry.approved_content_paths())
        if not items:
            return None
        ok = [i for i in items if isinstance(i, dict) and str(i.get("word") or "").strip()
              and str(i.get("pic") or "").strip()]
        return ok or None

    def start_matching_round(self, state, activity_id, now, rng):
        """Draw a new server-owned round. Returns (state, public_view) or (state, None).

        Starting a round RETIRES any other open round for the same activity (the UI only ever shows
        one), and drops expired rounds, so live state cannot accumulate (§30).
        """
        vocab = self.matching_vocab(activity_id)
        if not vocab:
            return state, None
        if not isinstance(state, dict):
            state = {}
        rounds = state.setdefault("matchingRounds", {})
        for rid in [r for r, v in rounds.items()
                    if (v or {}).get("activityId") == activity_id or matching.is_expired(v, now)]:
            rounds.pop(rid, None)
        rs = matching.build_round(activity_id, vocab, rng)
        if not rs:
            return state, None
        rs["createdAt"] = now
        round_id = self._new_round_id()
        rounds[round_id] = rs
        return state, matching.public_view(round_id, rs, vocab)

    @staticmethod
    def _new_round_id():
        import secrets
        return secrets.token_hex(16)

    def matching_click(self, state, round_id, item_id, choice_id, now):
        """Process one click against a round the player owns. Returns (state, outcome) or (state, None).

        A round lives inside its owner's learning state, so another account simply has no such round —
        ownership is structural, not a check that can be forgotten. Unknown/expired/completed rounds
        are refused, so nothing can be replayed to alter a score.
        """
        if not isinstance(state, dict):
            return state, None
        rounds = state.get("matchingRounds")
        if not isinstance(rounds, dict):
            return state, None            # malformed stored state -> refuse, never crash
        rs = rounds.get(round_id)
        if not isinstance(rs, dict) or rs.get("completed") or matching.is_expired(rs, now):
            return state, None
        activity_id = rs.get("activityId")
        vocab = self.matching_vocab(activity_id)
        if not vocab:
            return state, None
        out, _changed = matching.apply_click(rs, round_id, item_id, choice_id)
        if out["status"] != "complete":
            return state, out
        # Round finished: compact it into evidence and run it through the normal activity machinery.
        res = matching.result_of(rs)
        state["matchingRounds"].pop(round_id, None)
        prog = state.setdefault("matchingProgress", {})
        prog[activity_id] = {"latestRoundId": round_id, "correct": res["correct"],
                             "total": res["total"], "pct": res["pct"], "updatedAt": now}
        out["result"] = res
        out.update(granted=[], grantedNow=[], rewardAmount=0, rewarded=False, alreadyCompleted=False,
                   lessonCompleted=False, lessonCompletedNow=False, lessonQualifications=[],
                   lessonRewardAmount=0, lessonRewarded=False)
        if res["passed"]:
            state, act = self.record_attempt(state, activity_id, res, now)
            for k in ("granted", "grantedNow", "rewardAmount", "rewarded", "alreadyCompleted",
                      "lessonCompleted", "lessonCompletedNow", "lessonQualifications",
                      "lessonRewardAmount", "lessonRewarded"):
                out[k] = act[k]
        return state, out


    # ---- authoritative per-activity score for Rule A (Phase 3F) ----
    def authoritative_activity_score(self, state, activity_id):
        """{correct, total, pct} for one activity, or None when there is no server evidence yet.

        One resolver for all evidence shapes, so the lesson policy never learns where a score lives:
          deterministic graders -> activityScores  (exact correct/total, latest-wins)
          Read-Along (STT)      -> sttProgress     (legacy recordScore(2, avg, 100) => correct=pct,
                                                    total=100, so the pair is already exact)
          Matching              -> matchingProgress(legacy recordScore(5, firstTry, n) => correct/total
                                                    stored verbatim)
          Role-play             -> roleplayProgress(legacy recordScore(10, passes, turns) =>
                                                    correct=passes, total=turns)
        Every source therefore supplies an exact numerator/denominator, so Rule A can average the
        UNROUNDED per-level percentages exactly as index.html does.
        """
        state = state or {}
        if self.is_roleplay(activity_id):
            rec = _stored(state, "roleplayProgress", activity_id)
            if isinstance(rec, dict) and isinstance(rec.get("turns"), int) and rec["turns"] > 0:
                # legacy stores {correct: passes, total: turns}; a 0-turn session is "unscored",
                # exactly as statusFromScores treats a falsy total.
                return {"correct": int(rec.get("passes") or 0), "total": int(rec["turns"]),
                        "pct": int(rec.get("pct") or 0)}
            return None
        if self.is_matching(activity_id):
            rec = _stored(state, "matchingProgress", activity_id)
            if isinstance(rec, dict) and isinstance(rec.get("total"), int) and rec["total"] > 0:
                return {"correct": int(rec.get("correct") or 0), "total": int(rec["total"]),
                        "pct": int(rec.get("pct") or 0)}
            return None
        if self.is_read_along(activity_id):
            rec = _stored(state, "sttProgress", activity_id)
            if isinstance(rec, dict) and isinstance(rec.get("pct"), int):
                return {"correct": int(rec["pct"]), "total": 100, "pct": int(rec["pct"])}
            return None
        rec = qualifications.get_activity_score(state, activity_id)
        if isinstance(rec, dict) and isinstance(rec.get("total"), int) and rec["total"] > 0:
            return {"correct": int(rec.get("correct") or 0), "total": int(rec["total"]),
                    "pct": int(rec.get("pct") or 0)}
        return None

    def authoritative_activity_scores(self, state, activity_ids):
        return {aid: self.authoritative_activity_score(state, aid) for aid in (activity_ids or [])}

    # ---- whole-lesson completion (Phase 3D) ----
    def passed_activity_ids(self, state):
        """Activity ids the player has authoritatively PASSED (canonical + legacy keys merged)."""
        out = set()
        for aid in self.registry.activities:
            rec = self.read_completion(state, aid)
            if rec and rec.get("passedAt"):
                out.add(aid)
        return out

    def evaluate_lesson(self, lesson_id, state):
        """Pure-ish evaluation of one lesson against server-authoritative activity state only."""
        lesson = self.registry.lesson(lesson_id)
        required = completion.required_activity_ids(completion.policy_of(lesson))
        return completion.evaluate(lesson_id, lesson, self.passed_activity_ids(state),
                                   self.authoritative_activity_scores(state, required))

    def lesson_status(self, lesson_id, state, ev=None):
        """The unambiguous per-lesson status (Phase 4D §19).

        `lessonCompleted` / `completed` have historically meant two different things, so the truth is
        now spelled out in named fields:

          currentPolicySatisfied   — the LATEST authoritative scores satisfy the ACTIVE policy. May
                                     go true -> false after a worse retry; it is a live evaluation.
          historicallyCompleted    — some policy version has been completed at some point, ever.
          activePolicyVersion      — the version the registry currently enforces.
          activePolicyCompleted    — the ACTIVE version has a persisted completion entry.
          activePolicyCompletedAt  — when that happened, else None.
          firstCompletedAt         — the legacy first-ever completion timestamp.
          firstCompletedPolicyVersion — the version of that first-ever completion (may be retired).
        """
        ev = ev if ev is not None else self.evaluate_lesson(lesson_id, state)
        legacy = completion.get_lesson_completion(state, lesson_id)
        history = completion.merged_history(state, lesson_id)
        active = ev["policyVersion"] if ev["available"] else None
        at = completion.completion_for_version(state, lesson_id, active) if active else None
        return {"currentPolicySatisfied": bool(ev["available"] and ev["completed"]),
                "historicallyCompleted": bool(history),
                "activePolicyVersion": active,
                "activePolicyCompleted": at is not None,
                "activePolicyCompletedAt": at,
                "firstCompletedAt": (legacy or {}).get("completedAt"),
                "firstCompletedPolicyVersion": (legacy or {}).get("policyVersion"),
                "completionHistory": history}

    def _settle_lesson(self, state, lesson_id, now, out):
        """Record a completion of the ACTIVE policy version + its grants/reward. Idempotent."""
        out.setdefault("lessonId", lesson_id)
        out.setdefault("lessonCompleted", False)
        out.setdefault("lessonCompletedNow", False)
        out.setdefault("lessonQualifications", [])
        out.setdefault("lessonGrantedNow", [])
        out.setdefault("lessonRewardAmount", 0)
        out.setdefault("lessonRewarded", False)
        # Defaulted here too, so the response shape is IDENTICAL for a lesson with and without an
        # active policy — a caller never has to probe for the presence of a key.
        out.setdefault("missingActivityIds", [])
        out.setdefault("roundedPct", None)
        if not lesson_id or not self.registry.completion_available(lesson_id):
            out.update(self.lesson_status(lesson_id, state))
            return state                       # no policy -> never completable, never a fallback
        ev = self.evaluate_lesson(lesson_id, state)
        # DEPRECATED name, kept for compatibility: lessonCompleted has always meant "the active
        # policy is satisfied right now", i.e. currentPolicySatisfied.
        out["lessonCompleted"] = ev["completed"]
        out["missingActivityIds"] = ev["missingActivityIds"]
        out["roundedPct"] = ev["roundedPct"]
        if not ev["completed"]:
            out.update(self.lesson_status(lesson_id, state, ev))
            return state
        # Phase 7C.2: economic readability is established BEFORE the completion record is
        # written. Checking here means a corrupt history is REPORTED as corrupt, instead of being
        # swallowed by the container guard in record_lesson_completion() and looking like an
        # ordinary "already recorded" no-op. It also avoids writing a completion into a store we
        # have just judged untrustworthy.
        lesson_policies = self.registry.lesson_reward_policies_of(lesson_id)
        if any(rewards.is_economic(p) for p in lesson_policies) and \
                not self.economic_state_is_readable(state, lesson_id=lesson_id):
            out["lessonRewardBlocked"] = "corrupt_payment_history"
            out.update(self.lesson_status(lesson_id, state, ev))
            self._settle_course(state, self.registry.course_of_lesson(lesson_id), now, out)
            return state
        state, newly = completion.record_lesson_completion(
            state, lesson_id, now, ev["policyVersion"])
        out["lessonCompletedNow"] = newly
        out.update(self.lesson_status(lesson_id, state, ev))
        if not newly:
            return state                  # this VERSION already recorded -> no re-grant, no re-pay
        qids = self.registry.lesson_qualification_ids_for(lesson_id)
        state, granted_now = qualifications.grant_qualifications(state, qids, now)
        out["lessonQualifications"], out["lessonGrantedNow"] = qids, granted_now
        # Phase 7C.2: a mastered lesson grants several independent rewards (a cosmetic badge and
        # gold). Each is its own policy with its own ledger key, so each is exactly-once on its own.
        # Economic readability was established above, before anything was written.
        for lesson_policy in lesson_policies:
            state, reward = self.grant_reward(state, "lesson", lesson_id, lesson_policy, now)
            if not reward:
                continue
            if reward["amount"] > 0:            # the economic one
                out["lessonRewardAmount"], out["lessonRewarded"] = reward["amount"], True
                out["lessonRewardGoldType"] = reward["type"]
            else:                               # the cosmetic one
                out["lessonRewardType"] = reward["type"]
                out["lessonRewardItemId"] = reward["itemId"]
        # A finished lesson may finish its campaign. Derived here; never asserted by the client.
        self._settle_course(state, self.registry.course_of_lesson(lesson_id), now, out)
        return state

    # ---- campaign / course scope (Phase 5E) ----
    def evaluate_course(self, course_id, state):
        """Is every completable lesson in this course completed under its ACTIVE policy?

        Campaign completion is derived from lesson completion, exactly as the UI computes it: a
        lesson counts when the active policy version has a persisted completion, so a later poor
        retry never un-completes a campaign.
        """
        lids = self.registry.lessons_in_course(course_id) if course_id else []
        done = [lid for lid in lids
                if completion.completion_for_version(
                    state, lid, completion.policy_version(
                        completion.policy_of(self.registry.lesson(lid)))) is not None]
        return {"courseId": course_id, "available": bool(lids),
                "completed": bool(lids) and len(done) == len(lids),
                "lessonIds": lids, "completedLessonIds": done,
                "missingLessonIds": [l for l in lids if l not in done]}

    def _settle_course(self, state, course_id, now, out):
        """Record a campaign completion reward. Idempotent; a no-op for every course today."""
        out.setdefault("courseId", course_id)
        out.setdefault("courseCompleted", False)
        out.setdefault("courseCompletedNow", False)
        out.setdefault("courseRewardAmount", 0)
        out.setdefault("courseRewarded", False)
        if not course_id:
            return state
        ev = self.evaluate_course(course_id, state)
        out["courseCompleted"] = ev["completed"]
        if not ev["completed"]:
            return state
        policy_id = self.registry.course_reward_policy_of(course_id)
        state, reward = self.grant_reward(state, "course", course_id, policy_id, now)
        if reward:
            out["courseCompletedNow"] = True
            out["courseRewardType"] = reward["type"]
            out["courseRewardItemId"] = reward["itemId"]
            if reward["amount"] > 0:
                out["courseRewardAmount"], out["courseRewarded"] = reward["amount"], True
        return state

    def progress_view(self, state):
        """Read-only per-lesson progress. Carries no answer keys, grader config or reward detail."""
        lessons = {}
        passed = self.passed_activity_ids(state)
        for lid, lesson in self.registry.lessons.items():
            required = completion.required_activity_ids(completion.policy_of(lesson))
            ev = completion.evaluate(lid, lesson, passed,
                                     self.authoritative_activity_scores(state, required))
            rec = completion.get_lesson_completion(state, lid)
            status = self.lesson_status(lid, state, ev)
            lessons[lid] = {
                "title": lesson.get("title"),
                "authoritativeCompletionAvailable": ev["available"],
                # DEPRECATED trio, unchanged semantics for old readers: `completed` is historical
                # (any version), `completedAt`/`policyVersion` describe the FIRST-EVER completion.
                "completed": bool(rec) if ev["available"] else False,
                "completedAt": (rec or {}).get("completedAt"),
                "policyVersion": (rec or {}).get("policyVersion") or ev["policyVersion"],
                "requiredActivityIds": ev["requiredActivityIds"],
                "completedActivityIds": ev["completedActivityIds"],
                "missingActivityIds": ev["missingActivityIds"],
                "roundedPct": ev["roundedPct"],
            }
            lessons[lid].update(status)
        campaigns = {}
        for cid in sorted({l.get("courseId") for l in self.registry.lessons.values()
                           if l.get("courseId")}):
            ev = self.evaluate_course(cid, state)
            if not ev["available"]:
                continue                       # no completable lesson -> not a campaign
            course = self.registry.course(cid) or {}
            campaigns[cid] = {"title": course.get("title"), "completed": ev["completed"],
                              "lessonIds": ev["lessonIds"],
                              "completedLessonIds": ev["completedLessonIds"],
                              "missingLessonIds": ev["missingLessonIds"]}
        return {"lessons": lessons, "campaigns": campaigns,
                "completedLessonIds": sorted(completion.completed_lesson_ids(state))}

    # ---- views ----
    def public_registry_view(self):
        return self.registry.public_view()

    def state_view(self, state):
        state = state or {}
        return {"qualifications": state.get("qualifications") or {},
                "activityCompletions": state.get("activityCompletions") or {},
                "lessonCompletions": state.get("lessonCompletions") or {},
                "lessonCompletionHistory": state.get(completion.HISTORY_KEY) or {},
                "sttProgress": state.get("sttProgress") or {},
                "matchingProgress": state.get("matchingProgress") or {},
                "roleplayProgress": state.get("roleplayProgress") or {},
                "rewardLedger": state.get(reward_ledger.LEDGER_KEY) or {},
                "activityScores": state.get("activityScores") or {}}
        # NOTE: roleplaySessions is deliberately NOT exposed — an in-flight session holds the
        # current node, and revealing it would tell the client where the conversation is going.

    def player_qualification_ids(self, state):
        return qualifications.earned_qualification_ids(state)


__all__ = ["LearningService", "identity", "REASON_NOT_GRADABLE", "REASON_BAD_ANSWERS",
           "REASON_CONTENT_UNAVAILABLE"]
