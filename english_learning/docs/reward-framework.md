# Reward framework — registry-driven, scoped, and inert (Phase 5E)

Phase 5D established that mastery has no gameplay consequence and that quiz3 carries almost all
mechanical value. Rather than answer that with a gold number, Phase 5E builds the **infrastructure**
a reward decision would need, and ships it switched off. **No new reward is active.** Production is
byte-for-byte the same economy it was before this phase: one gold-bearing activity, no lesson reward,
no campaign reward.

Reward *tuning* is a separate product decision that comes after this framework exists.

---

## 1. What a policy is

A reward policy is a server-owned record in `learning/rewards.py`:

```
{type, scopes, amountKey?, itemId?, once}
```

| Field | Meaning |
|---|---|
| `type` | `none` \| `gold` \| `cosmetic` \| `profile` \| `gameplay`. Decides who consumes the reward. |
| `scopes` | Where the policy may legally be attached: `activity`, `lesson`, `course`. |
| `amountKey` | Looked up in the caller-supplied game-config amounts map. **Gold only.** |
| `itemId` | The opaque item the learner comes to own. Cosmetic/profile/gameplay only. |
| `once` | Grant at most once per `(scope, sourceId, policyId)`. |

Only **`gold` is economic** — it is the one type that asks the caller to move currency. Everything
else is fully discharged by writing a ledger entry.

Adding or changing a policy is a **code change** (reviewed), not a content change (arbitrary,
uploaded). `learning/rewards.py` deliberately contains no numbers; a test asserts this.

## 2. Scopes

`activity`, `lesson` and `course` (a course is a campaign). Defaults when content says nothing:

| Scope | Default policy |
|---|---|
| activity | `standard_activity_pass` (historical behaviour, preserved) |
| lesson | `none` |
| course | `none` |

Lessons and campaigns default to paying **nothing**, so forgetting the field can never mint anything.

## 3. The four safety rules

1. **Content may NAME a policy, never size one.** `learning/registry.py` rejects `rewardGold`,
   `gold`, `rewardAmount`, `amount` and `itemId` on activities, lessons and courses alike. Amounts
   come only from the authoritative game config, keyed by `amountKey`.
2. **Scope is enforced by validation.** A campaign trophy cannot be pinned onto a single quiz; the
   activity pass policy cannot be attached to a lesson. `allows_scope()` returns `False` for an
   unknown policy — fail closed.
3. **An unsized gold policy is inert, not free money.** If the config does not supply the policy's
   `amountKey`, `resolve()` yields `{type: "none", amount: 0}` rather than guessing.
4. **One grant path.** `LearningService.grant_reward(state, scope, sourceId, policyId, now)` is the
   only way a reward is recorded, for every scope and every type.

## 4. The ledger

`learning/reward_ledger.py` keeps an append-only table on the learner's own state under
`rewardLedger`. The key is derived from `(scope, sourceId, policyId)`, so `once` idempotency comes
for free: retries, replays and double settlement cannot double-grant, and an existing entry is never
re-dated. Each entry records `policyId`, `rewardType`, `scope`, `sourceId`, `amount`, `itemId` and
`grantedAt`.

The activity payout keeps its historical `rewarded` flag exactly as it was — that flag is what
existing behaviour depends on — and the ledger is written alongside it as the audit trail.

## 5. Gameplay rewards are recorded, not applied

A `gameplay` policy writes a ledger entry and **nothing else**. No code path in this repository reads
one and changes stamina, combat, income or any other mechanic. Wiring an effect is an explicit,
separate product decision. The type exists now so that decision does not also have to invent
storage, idempotency and validation.

## 6. Current policy table

Six reference implementations were added, one per type/scope combination worth having. All are
**unreferenced by production content**. `ACTIVE_POLICY_IDS` in `learning/rewards.py` gates what
content may name, and `tools/validate_learning_registry.py` fails if that is ever violated.

```
reward framework: 8 policies defined, types ['cosmetic', 'gameplay', 'gold', 'none', 'profile']
  campaign_complete_gold     type=gold      scopes=course                 inert (unreferenced)
  campaign_profile_frame     type=profile   scopes=course                 inert (unreferenced)
  campaign_trophy            type=cosmetic  scopes=course                 inert (unreferenced)
  lesson_mastery_badge       type=cosmetic  scopes=lesson                 inert (unreferenced)
  lesson_mastery_boost       type=gameplay  scopes=lesson                 inert (unreferenced)
  lesson_mastery_gold        type=gold      scopes=lesson                 inert (unreferenced)
  none                       type=none      scopes=activity,lesson,course REFERENCED by 37
  standard_activity_pass     type=gold      scopes=activity               REFERENCED by 1
economic policies in use: ['standard_activity_pass']
```

`lesson_mastery_gold` and `campaign_complete_gold` name amount keys the game config does **not**
supply, so even if something did reference them today they would resolve to zero.

## 7. Campaign (course) scope

`LearningService.evaluate_course()` derives campaign completion from lesson completion: a lesson
counts when the **active** policy version has a persisted completion, so a later poor retry never
un-completes a campaign. A course with no completable lesson yields no lessons and can never fire a
course reward. `_settle_course()` runs after a lesson settles; today it is a no-op for every course
because every course policy is `none`. `progress_view` exposes a read-only `campaigns` block.

---

## 8. Known pre-activation concern — malformed ledger normalizes to empty

**Current behaviour.** A corrupt or non-dict `rewardLedger` — a string, a number, a list, or a dict
whose entries are not well-formed — reads as **empty**. `entries()`, `owned_items()` and
`get_grant()` all return nothing rather than raising, and ownership is never fabricated from junk.

**Why this is safe today.** Nothing in production depends on it. The only active reward,
`standard_activity_pass`, still guards its payout with the historical per-activity `rewarded` flag,
not with the ledger — so a wiped ledger cannot re-pay Zoo quiz3 gold. Today the ledger is an audit
trail, not a gate.

**Why it must be decided before activating anything else.** The moment a lesson, campaign, cosmetic,
profile or gameplay reward goes live, the ledger *becomes* the idempotency gate for it. At that point
"corruption reads as empty" means "corruption permits a re-grant". Before activating additional
production rewards, decide explicitly which of these applies:

- **fail closed** — refuse to grant while the ledger is unreadable, and surface the error;
- **use recovery data** — rebuild the ledger from another durable source before granting;
- **permit re-granting** — accept the duplicate as the cheaper failure mode for that reward type
  (defensible for a cosmetic item, probably not for gold).

The answer may legitimately differ per reward type. This behaviour is **deliberately unchanged in
Phase 5E**: no existing test shows it puts the current production reward at risk, and changing it
without an activation decision would be guessing at the requirement.
