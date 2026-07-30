"""Reward POLICY — the trust boundary between (untrusted) learning content and the game economy.

§15: a content pack must never be able to say `rewardGold: 999999999`. So content/registry may only
NAME a policy from this server-owned allowlist; it can never state an amount. The amount itself is
supplied at runtime by the caller from the authoritative game config (server.PASS_GOLD), keyed by
`amountKey` — this module deliberately contains no numbers.

Adding a policy is a code change (reviewed), not a content change (arbitrary/uploaded).
"""

DEFAULT_POLICY = "standard_activity_pass"

# policyId -> {type, amountKey, once}. `amountKey` is looked up in the caller-supplied amounts map.
POLICIES = {
    "none": {"type": "none", "amountKey": None, "once": True},
    "standard_activity_pass": {"type": "gold", "amountKey": "PASS_GOLD", "once": True},
}


def is_policy(policy_id):
    return policy_id in POLICIES


def policy_ids():
    return sorted(POLICIES)


def resolve(policy_id, amounts):
    """Return {'type', 'amount', 'once'} for a policy. Unknown/absent policy -> a zero reward.

    `amounts` maps an amountKey to the authoritative game-config value, e.g. {"PASS_GOLD": <config>}.
    A policy naming an amountKey the caller did not supply also yields 0 — fail closed, never guess.
    """
    spec = POLICIES.get(policy_id) or POLICIES["none"]
    if spec["type"] == "none" or not spec["amountKey"]:
        return {"type": "none", "amount": 0, "once": bool(spec["once"])}
    amount = (amounts or {}).get(spec["amountKey"])
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        return {"type": "none", "amount": 0, "once": bool(spec["once"])}
    return {"type": spec["type"], "amount": amount, "once": bool(spec["once"])}
