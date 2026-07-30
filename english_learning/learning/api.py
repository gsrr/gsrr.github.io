"""Learning Domain API — the single entry point the HTTP layer talks to (§10).

server.py must not become the Learning Engine: it authenticates, loads/saves the progress blob and
moves gold. Everything else (identity resolution, content access, grading, completion, qualification
granting, reward policy) lives behind LearningService.

The service is stateless with respect to players — every method takes the player's `learning` dict
and returns it mutated for the caller to persist, exactly like the pure modules underneath.
"""
from . import content, grading, identity, qualifications, registry, rewards

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
        return grading.grade(grader_type, items, answers), None

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
        prior = self.read_completion(state, activity_id)
        out = {"activityId": activity_id, "passed": bool(result and result.get("passed")),
               "alreadyCompleted": bool(prior and prior.get("passedAt")),
               "granted": [], "grantedNow": [], "rewardType": "none", "rewardAmount": 0,
               "rewarded": False}
        if not out["passed"]:
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
        return state, out

    # ---- views ----
    def public_registry_view(self):
        return self.registry.public_view()

    def state_view(self, state):
        state = state or {}
        return {"qualifications": state.get("qualifications") or {},
                "activityCompletions": state.get("activityCompletions") or {}}

    def player_qualification_ids(self, state):
        return qualifications.earned_qualification_ids(state)


__all__ = ["LearningService", "identity", "REASON_NOT_GRADABLE", "REASON_BAD_ANSWERS",
           "REASON_CONTENT_UNAVAILABLE"]
