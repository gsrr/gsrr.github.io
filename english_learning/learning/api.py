"""Learning Domain API — the single entry point the HTTP layer talks to (§10).

server.py must not become the Learning Engine: it authenticates, loads/saves the progress blob and
moves gold. Everything else (identity resolution, content access, grading, completion, qualification
granting, reward policy) lives behind LearningService.

The service is stateless with respect to players — every method takes the player's `learning` dict
and returns it mutated for the caller to persist, exactly like the pure modules underneath.
"""
from . import (completion, content, grading, identity, matching, qualifications, registry,
               rewards, stt_scoring)

# stable machine reasons returned to the client (never internal exception detail)
REASON_NOT_GRADABLE = "not_gradable"
REASON_BAD_ANSWERS = "bad_answers"
REASON_CONTENT_UNAVAILABLE = "content_unavailable"


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
        """{'type','amount','once'} for this activity — resolved from the server-owned allowlist."""
        return rewards.resolve(self.registry.reward_policy_of(activity_id), self.reward_amounts)

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
        pay = reward["amount"] > 0 and not (reward["once"] and already_rewarded)
        if pay:
            out["rewardType"], out["rewardAmount"], out["rewarded"] = reward["type"], reward["amount"], True
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
        Every source therefore supplies an exact numerator/denominator, so Rule A can average the
        UNROUNDED per-level percentages exactly as index.html does.
        """
        state = state or {}
        if self.is_matching(activity_id):
            rec = (state.get("matchingProgress") or {}).get(activity_id)
            if isinstance(rec, dict) and isinstance(rec.get("total"), int) and rec["total"] > 0:
                return {"correct": int(rec.get("correct") or 0), "total": int(rec["total"]),
                        "pct": int(rec.get("pct") or 0)}
            return None
        if self.is_read_along(activity_id):
            rec = (state.get("sttProgress") or {}).get(activity_id)
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

    def _settle_lesson(self, state, lesson_id, now, out):
        """Record a first-time lesson completion + its configured grants/reward. Idempotent."""
        out.setdefault("lessonId", lesson_id)
        out.setdefault("lessonCompleted", False)
        out.setdefault("lessonCompletedNow", False)
        out.setdefault("lessonQualifications", [])
        out.setdefault("lessonGrantedNow", [])
        out.setdefault("lessonRewardAmount", 0)
        out.setdefault("lessonRewarded", False)
        if not lesson_id or not self.registry.completion_available(lesson_id):
            return state                       # no policy -> never completable, never a fallback
        ev = self.evaluate_lesson(lesson_id, state)
        out["lessonCompleted"] = ev["completed"]
        if not ev["completed"]:
            return state
        state, newly = completion.record_lesson_completion(
            state, lesson_id, now, ev["policyVersion"])
        out["lessonCompletedNow"] = newly
        if not newly:
            return state                       # already completed -> no re-grant, no second reward
        qids = self.registry.lesson_qualification_ids_for(lesson_id)
        state, granted_now = qualifications.grant_qualifications(state, qids, now)
        out["lessonQualifications"], out["lessonGrantedNow"] = qids, granted_now
        reward = rewards.resolve(self.registry.lesson_reward_policy_of(lesson_id), self.reward_amounts)
        if reward["amount"] > 0:
            out["lessonRewardAmount"], out["lessonRewarded"] = reward["amount"], True
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
            lessons[lid] = {
                "title": lesson.get("title"),
                "authoritativeCompletionAvailable": ev["available"],
                "completed": bool(rec) if ev["available"] else False,
                "completedAt": (rec or {}).get("completedAt"),
                "policyVersion": (rec or {}).get("policyVersion") or ev["policyVersion"],
                "requiredActivityIds": ev["requiredActivityIds"],
                "completedActivityIds": ev["completedActivityIds"],
                "missingActivityIds": ev["missingActivityIds"],
            }
        return {"lessons": lessons,
                "completedLessonIds": sorted(completion.completed_lesson_ids(state))}

    # ---- views ----
    def public_registry_view(self):
        return self.registry.public_view()

    def state_view(self, state):
        state = state or {}
        return {"qualifications": state.get("qualifications") or {},
                "activityCompletions": state.get("activityCompletions") or {},
                "lessonCompletions": state.get("lessonCompletions") or {},
                "sttProgress": state.get("sttProgress") or {},
                "matchingProgress": state.get("matchingProgress") or {},
                "activityScores": state.get("activityScores") or {}}

    def player_qualification_ids(self, state):
        return qualifications.earned_qualification_ids(state)


__all__ = ["LearningService", "identity", "REASON_NOT_GRADABLE", "REASON_BAD_ANSWERS",
           "REASON_CONTENT_UNAVAILABLE"]
