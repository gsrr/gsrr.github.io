"""Reward POLICY — the trust boundary between (untrusted) learning content and the game.

§15: a content pack must never be able to say `rewardGold: <any huge number>`. So content/registry
may only NAME a policy from this server-owned allowlist; it can never state an amount, item or scope.
Amounts are supplied at runtime by the caller from the authoritative game config, keyed by
`amountKey` — this module deliberately contains no numbers.

Adding or changing a policy is a code change (reviewed), not a content change (arbitrary/uploaded).

===============================================================================================
Phase 5E — the framework, deliberately INERT
===============================================================================================

A policy is `{type, scopes, amountKey?, itemId?, once}`:

    type      what kind of reward it is (see TYPES). The type decides who consumes it:
                gold      -> the caller adds `amount` to the economy (the ONLY economic type)
                cosmetic  -> recorded in the learner's reward ledger as an owned item
                profile   -> recorded in the ledger; intended for profile decoration
                gameplay  -> recorded in the ledger ONLY. Nothing applies a gameplay effect today;
                             wiring one is a separate, explicit product decision.
                none      -> nothing at all
    scopes    where the policy may legally be attached: "activity", "lesson", "course".
              A campaign trophy therefore cannot be pinned onto a single quiz by mistake, and the
              registry validator enforces it.
    amountKey looked up in the caller-supplied amounts map (gold only)
    itemId    the opaque item the learner comes to own (cosmetic/profile/gameplay only)
    once      grant at most once per (scope, sourceId, policy)

EVERYTHING EXCEPT `standard_activity_pass` IS UNUSED BY PRODUCTION CONTENT. The extra policies below
exist so each reward TYPE has a reference implementation that validation and tests can exercise;
they are inert until some registry entry names them, and `tools/validate_learning_registry.py`
reports exactly which policies are actually referenced.
"""

DEFAULT_POLICY = "standard_activity_pass"
# What a scope defaults to when content says nothing. Activities keep their historical default;
# lessons and courses default to paying NOTHING, so forgetting the field can never mint anything.
DEFAULT_BY_SCOPE = {"activity": DEFAULT_POLICY, "lesson": "none", "course": "none"}

SCOPES = ("activity", "lesson", "course")
# type -> whether the caller must move economy for it. Only `gold` is economic.
TYPES = {"none": {"economic": False}, "gold": {"economic": True},
         "cosmetic": {"economic": False}, "profile": {"economic": False},
         "gameplay": {"economic": False}}
ALL_SCOPES = SCOPES

POLICIES = {
    # ---- active in production ----
    "none": {"type": "none", "scopes": ALL_SCOPES, "amountKey": None, "itemId": None, "once": True},
    "standard_activity_pass": {"type": "gold", "scopes": ("activity",),
                               "amountKey": "PASS_GOLD", "itemId": None, "once": True},

    # ---- INERT reference implementations, one per type (Phase 5E). Nothing names these. ----
    # A lesson-scope gold reward. Its amount key is intentionally NOT PASS_GOLD: sizing a mastery
    # reward is a product decision, and the key stays unsupplied until that decision is made, so
    # resolve() yields 0 even if something did name it.
    "lesson_mastery_gold": {"type": "gold", "scopes": ("lesson",),
                            "amountKey": "LESSON_MASTERY_GOLD", "itemId": None, "once": True},
    "campaign_complete_gold": {"type": "gold", "scopes": ("course",),
                               "amountKey": "CAMPAIGN_COMPLETE_GOLD", "itemId": None, "once": True},
    "lesson_mastery_badge": {"type": "cosmetic", "scopes": ("lesson",),
                             "amountKey": None, "itemId": "badge.lesson.mastered", "once": True},
    "campaign_trophy": {"type": "cosmetic", "scopes": ("course",),
                        "amountKey": None, "itemId": "trophy.campaign.complete", "once": True},
    "campaign_profile_frame": {"type": "profile", "scopes": ("course",),
                               "amountKey": None, "itemId": "frame.campaign.complete", "once": True},
    "lesson_mastery_boost": {"type": "gameplay", "scopes": ("lesson",),
                             "amountKey": None, "itemId": "boost.lesson.mastered", "once": True},
}

# Policies production content is allowed to reference today. Anything else is framework-only and the
# validator will say so, so "we shipped an inert policy by accident" cannot happen quietly.
# Phase 5F activated the two COSMETIC policies as the first production use of the framework. The
# remaining four (gold x2, profile, gameplay) stay off this list and therefore stay unreferenceable.
ACTIVE_POLICY_IDS = ("none", "standard_activity_pass", "lesson_mastery_badge", "campaign_trophy")


def is_policy(policy_id):
    return policy_id in POLICIES


def policy_ids():
    return sorted(POLICIES)


def policy(policy_id):
    return POLICIES.get(policy_id)


def type_of(policy_id):
    return (POLICIES.get(policy_id) or POLICIES["none"])["type"]


def is_economic(policy_id):
    return bool(TYPES.get(type_of(policy_id), {}).get("economic"))


def scopes_of(policy_id):
    return tuple((POLICIES.get(policy_id) or POLICIES["none"]).get("scopes") or ())


def allows_scope(policy_id, scope):
    """True if this policy may be attached at `scope`. Unknown policy -> False (fail closed)."""
    return policy_id in POLICIES and scope in scopes_of(policy_id)


def default_for_scope(scope):
    return DEFAULT_BY_SCOPE.get(scope, "none")


def resolve(policy_id, amounts):
    """The runtime reward descriptor for a policy. Unknown/absent -> an inert zero reward.

    Returns {'type', 'amount', 'itemId', 'once'}. `amounts` maps an amountKey to the authoritative
    game-config value, e.g. {"PASS_GOLD": <config>}. A policy naming an amountKey the caller did not
    supply yields 0 — fail closed, never guess. Callers that predate Phase 5E read only
    `type`/`amount`/`once` and keep working unchanged.
    """
    spec = POLICIES.get(policy_id) or POLICIES["none"]
    out = {"type": spec["type"], "amount": 0, "itemId": spec.get("itemId"),
           "once": bool(spec["once"])}
    if spec["type"] == "none":
        return {"type": "none", "amount": 0, "itemId": None, "once": bool(spec["once"])}
    if spec["type"] == "gold":
        amount = (amounts or {}).get(spec.get("amountKey"))
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            # An unsized gold policy is inert rather than free money.
            return {"type": "none", "amount": 0, "itemId": None, "once": bool(spec["once"])}
        out["amount"] = amount
        return out
    # cosmetic / profile / gameplay: an item, never an amount. No item -> nothing to grant.
    if not out["itemId"]:
        return {"type": "none", "amount": 0, "itemId": None, "once": bool(spec["once"])}
    return out
