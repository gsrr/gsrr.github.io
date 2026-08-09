# Reward framework — registry-driven and scoped (Phase 5E, activated in 5F)

Phase 5D established that mastery has no gameplay consequence and that quiz3 carries almost all
mechanical value. Rather than answer that with a gold number, **Phase 5E** built the
**infrastructure** a reward decision would need and shipped it switched off. **Phase 5F** then turned
on the first production rewards, and deliberately chose the safest possible ones: two **cosmetic**
policies that move no gold, change no gameplay, and gate nothing.

Active today:

| Scope | Policy | Type | Grants |
|---|---|---|---|
| lesson (×4 Taipei) | `lesson_mastery_badge` | cosmetic | `badge.lesson.mastered`, once per lesson |
| lesson (×4 Taipei) | `lesson_mastery_gold` | gold | `MASTERY_GOLD` = 640, once per lesson (Phase 7C.2) |
| course (Taipei) | `campaign_trophy` | cosmetic | `trophy.campaign.complete`, once |
| activity (Zoo quiz3) | `standard_activity_pass` | gold | `PASS_GOLD` = 160 (Phase 7C.2; was 10000) |

A lesson carries **two** policies at once — the badge and the gold — because they are independent
grants with independent ledger keys, so each stays exactly-once on its own. The validator allows at
most one *economic* policy per lesson, which is what prevents mastery being paid twice.

Phase 7C.2 moved the learning economy from "the gate activity pays everything" to "mastery pays most
of it": passing the gate is a token acknowledgement (160) and finishing the whole lesson under Rule A
is the substantial reward (640). Still exactly one gold-bearing *activity*; the campaign trophy is
still worth nothing mechanically. Per-lesson learning value is therefore 800 for the Zoo (the only
lesson whose gate activity is gold-bearing) and 640 for the other three — 2720 for the whole Taipei
campaign.

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

Six reference implementations were added in Phase 5E, one per type/scope combination worth having.
Phase 5F promoted the two **cosmetic** ones into production; the other four — both gold policies, the
profile frame and the gameplay boost — remain **unreferenced**. `ACTIVE_POLICY_IDS` in
`learning/rewards.py` gates what content may name, and `tools/validate_learning_registry.py` fails if
that is ever violated, so activating a policy is a deliberate two-place change (allowlist + registry)
rather than an edit anyone can make in content alone.

```
reward framework: 8 policies defined, types ['cosmetic', 'gameplay', 'gold', 'none', 'profile']
  campaign_complete_gold     type=gold      scopes=course                 inert (unreferenced)
  campaign_profile_frame     type=profile   scopes=course                 inert (unreferenced)
  campaign_trophy            type=cosmetic  scopes=course                 REFERENCED by 1
  lesson_mastery_badge       type=cosmetic  scopes=lesson                 REFERENCED by 4
  lesson_mastery_boost       type=gameplay  scopes=lesson                 inert (unreferenced)
  lesson_mastery_gold        type=gold      scopes=lesson                 REFERENCED by 4
  none                       type=none      scopes=activity,lesson,course REFERENCED by 32
  standard_activity_pass     type=gold      scopes=activity               REFERENCED by 1
economic policies in use: ['lesson_mastery_gold', 'standard_activity_pass']
```

`campaign_complete_gold` still names an amount key the game config does **not** supply, so even if
something referenced it today it would resolve to zero. `lesson_mastery_gold` was in exactly that
state until Phase 7C.2, which activated it by adding `MASTERY_GOLD` to `game/config.py` — the amount
came from the game, never from the registry.

## 7. Campaign (course) scope

`LearningService.evaluate_course()` derives campaign completion from lesson completion: a lesson
counts when the **active** policy version has a persisted completion, so a later poor retry never
un-completes a campaign. A course with no completable lesson yields no lessons and can never fire a
course reward. `_settle_course()` runs after a lesson settles; since Phase 5F it grants the Taipei
campaign trophy the first time all four lessons are complete, and remains a no-op for every other
course. `progress_view` exposes a read-only `campaigns` block.

---

## 8. Malformed ledger normalizes to empty — the decision taken in Phase 5F

**Behaviour.** A corrupt or non-dict `rewardLedger` — a string, a number, a list, or a dict whose
entries are not well-formed — reads as **empty**. `entries()`, `owned_items()` and `get_grant()` all
return nothing rather than raising, and ownership is never fabricated from junk.

Phase 5E flagged this as a decision that had to be made **before** any further reward went live,
because the moment a reward is activated the ledger becomes that reward's idempotency gate, and
"corruption reads as empty" starts to mean "corruption permits a re-grant". Phase 5F activated two
rewards, so the decision is now made:

**Decision: for cosmetic rewards, permit re-granting.** This is the third of the three options
Phase 5E listed, and it is the cheapest failure mode for this reward type. If a learner's ledger were
ever damaged, the worst outcome is that they re-earn a badge they already had and see the unlock
banner a second time. Nothing is duplicated that anyone can spend, trade or fight with.

What makes that acceptable is specifically that it applies to **cosmetics**:

- a cosmetic item confers nothing mechanical, so owning it twice is indistinguishable from owning it
  once — `owned_items()` de-duplicates by item id.
- `standard_activity_pass` is not gated by the ledger at all; it keeps its historical per-activity
  `rewarded` flag, so a wiped ledger cannot re-pay Zoo quiz3.
- since Phase 7C.2 one economic policy (`lesson_mastery_gold`) *is* ledger-gated — and it does **not**
  use these tolerant reads. It goes through the fail-closed path added in Phase 7C.1, below.

### The safety boundary (do not cross without a new decision)

State it plainly: **cosmetic ledger corruption FAILS OPEN and may allow a cosmetic re-grant.** That is
an accepted, bounded cost for cosmetics and nothing else.

**This fail-open policy must NOT be applied automatically to gold, profile or gameplay rewards.**
It was chosen because a duplicate badge is inert. A duplicate payout, a duplicate profile entitlement
or a duplicate gameplay effect is not.

**Precondition for any future non-cosmetic ledger-backed reward.** Before activating
`lesson_mastery_gold`, `campaign_complete_gold`, `campaign_profile_frame`, `lesson_mastery_boost`, or
any new policy of those types, a **fail-closed or recoverable** corruption policy must be defined and
implemented first — refuse to grant while the ledger is unreadable, or rebuild it from durable
recovery data before granting. Activating such a reward on top of today's fail-open read is a defect,
not a configuration choice.

### Phase 7C.1 — the precondition, met

`reward_ledger.is_corrupt()` is the fail-closed counterpart to the tolerant reads, and
`LearningService.economic_state_is_readable()` folds it together with the strict reads of the two
other stores that gate a payment (`qualifications.completion_state`,
`completion.history_is_corrupt`). An economic grant proceeds only when the store that authoritatively
gates *that* grant is readable; a missing record still pays (genuinely never paid), a malformed one
refuses. Corruption is preserved rather than repaired, so it stays diagnosable, and `grant_reward()`
re-checks independently as a last line of defence.

Note the scoping, which cost one iteration to get right: strictness applies to the store that gates
the grant, not to every store. A corrupt *cosmetic* ledger must not block the activity payout, which
is gated by its own per-activity `rewarded` flag — otherwise unrelated damage would deny a learner
money they had genuinely earned.

**Phase 7C.2 then activated `lesson_mastery_gold`** — the first ledger-backed economic reward, and the
first one for which the fail-open read above would have been unsafe. It went live only after the
paragraph above was true. The fail-open behaviour itself is unchanged for cosmetics.

## 9. What Phase 5F deliberately did not do

- No gold, gameplay or profile reward was activated; those four policies remain unreferenced.
- No qualification, territory requirement, `passcnt`, energy or conquest rule changed.
- The ledger format is unchanged — activation was a registry edit plus an allowlist entry.
- A cosmetic item is display-only. Nothing reads `owned_items()` to decide anything, and there is no
  inventory, equip, spend or trade path.
