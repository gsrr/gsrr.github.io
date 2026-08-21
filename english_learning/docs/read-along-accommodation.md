# Accessible Read Along: typed input (Phase 12B.2)

Read Along is a **required** activity in all 57 lessons, and it was scored from speech only. So a
learner with no microphone, a denied permission, an unsupported or in-app browser, or a
speech-production need could not reach authoritative mastery in a single lesson — not because they
could not read, but because the only accepted *input* was their voice.

Phase 12A audited that gap. Phase 12B.1 made the speech path honest about failing. This phase closes
the gap itself, and it closes it in the narrowest way that works: **the input modality changes, and
nothing else does.**

```
speech  :  audio  ->  transcribe()  ->  stt_scoring.score_sentence  ->  record_read_along()
typed   :  text                     ->  stt_scoring.score_sentence  ->  record_read_along()
```

This is **not** "skip Read Along" and **not** "mark it complete". The learner still reads the same
sentence, is scored by the same scorer against the same target, must clear the same 80% mark, and
earns the same completion for the same activity id.

## What was NOT changed

| | |
| --- | --- |
| curriculum | no lesson content, no sentence, no ordering |
| `requiredActivityIds` | unchanged — Read Along stays required in all 57 lessons |
| activity identity | typed passes write `<lesson>.read_along`; **no shadow activity id exists** |
| scorer | `learning/stt_scoring.py::score_sentence` — the same function, unmodified |
| pass mark | the single shared `PASS_MARK = 80` |
| rewards | `PASS_GOLD = 160`, `MASTERY_GOLD = 640`, same policy, same idempotency |
| completion policy | `activePolicyCompleted` decided exactly as before |
| `game/config.py` fingerprint | `736503ae2c4f5fa5`, unchanged |

## Why there is no second mastery engine

`LearningService.record_read_along(state, activity_id, sentence_index, transcript, now)` already took
a **transcript** — plain text — and already did everything authoritative itself:

- resolves the target sentence from lesson content (the client cannot supply it);
- scores it with `stt_scoring.score_sentence`;
- keeps best-per-sentence retry semantics;
- on crossing `PASS_MARK`, routes through `record_attempt` for grants and the reward policy.

Typed mode therefore reuses that call unchanged. The only difference between the two modes is where
the text came from — audio through Whisper, or the learner's keyboard. Everything downstream is one
code path, which is why parity is a property of the design rather than something two engines have to
be kept in step about.

## Authority: `may_manage()`, and nothing else

An educator enables it; a learner never can. The authorization is the canonical relation from
[class-authority.md](class-authority.md):

```python
may_manage(manager, target, db)   # the manager owns the class the target joined, and they differ
```

Authority is **never** inferred from an account "type" (none exists — see the role audit in
class-authority.md), the role screen a user tapped, a display name, roster contents, or possession of
a class code. `may_manage()` refuses `manager == target`, so self-service is structurally impossible
rather than merely unimplemented.

| actor | outcome |
| --- | --- |
| the owning teacher | allowed |
| the learner themselves | `403 not_authorized` |
| a classmate | `403 not_authorized` |
| an unrelated teacher | `403 not_authorized` |
| a legacy display-name roster row | `403` — it is not an account, and never becomes one |
| no token / empty / forged token | `401 auth_required` |

An **unknown account and an unauthorized manager get the identical 403**, on purpose: a refusal must
not tell the caller whether an account exists or which class it is in.

## What is stored — and what deliberately is not

```
db["users"][<account>]["readAlongMode"]   = "typed"        # absent means speech
db["users"][<account>]["readAlongModeBy"] = <actor account>
db["users"][<account>]["readAlongModeAt"] = <epoch seconds>
```

Three fields: the permitted input, who set it, when. That is the whole record.

**Not stored anywhere, at any layer:** a diagnosis, a disability, a medical reason, a speech
condition, a teacher's note, or a free-text justification. The server has no use for any of it, so it
does not ask for it, does not accept it, and has no field to keep it in. A test asserts that none of
those words can appear in an account record, and another asserts none appears in the UI.

**Absent field == `speech`.** Every existing account keeps today's behaviour with no migration, and a
malformed or missing value can only ever fall back to speech.

## Endpoints

### `POST /api/accommodation/read-along`

Body `{account, mode}` where mode is `"speech"` or `"typed"`. Requires a token.

| condition | answer |
| --- | --- |
| no/invalid token | `401 auth_required` |
| mode not in `("speech", "typed")` | `400 bad_mode` |
| unknown target **or** not authorized | `403 not_authorized` |
| authorized | `200 {ok, account, readAlongMode}` |

Turning it off **pops** the field rather than writing `"speech"`, so a disabled account is
byte-identical to one that never had it.

### `POST /api/learning/read-along/typed`

Body `{activityId, sentenceIndex, text}`. A **separate route from `/api/stt` on purpose**: typed mode
must never touch the audio path, so it cannot request a microphone, cannot invoke `transcribe()`, and
does not depend on faster-whisper or ffmpeg being installed. It is in `ROOM_MUTATIONS`, because it
settles Gold exactly as the speech path does.

| condition | answer |
| --- | --- |
| no/invalid token | `401 auth_required` |
| the account's mode is not `typed` | `403 typed_not_enabled` |
| not a read-along activity | `400 not_scorable` |
| sentence index does not resolve | `400 bad_sentence` |
| `text` is not a string | `400 no_text` |
| otherwise | `200`, mirroring the `/api/stt` response plus `"inputMode": "typed"` |

The submitted text is **evidence, never a verdict.** Any `score`, `passed`, `rewarded` or `target`
field in the body is simply not read; the server resolves its own sentence and scores what was typed.

### `GET /api/learning/state`

Gains exactly one key, `readAlongMode` — **this account's own** permitted input. No reason (none
exists), no actor, no other learner's state. `tests/learning_gate_test.py` pins the full key set, so
any further growth of this surface fails a test.

### `GET /api/dashboard`

Each **authoritative** member row gains `readAlongMode`, so an educator's control can show real state.
Legacy name-keyed rows do not: `may_manage()` cannot authorize them, and offering a control that must
fail would be a lie.

## The learner's surface

A typed-enabled account gets, for the same required activity:

```
sentence  ->  Listen 🔊  ->  [ text field ]  ->  Check reading  ->  server score
```

- **Listen stays.** The accommodation replaces the learner's answer, not the model audio.
- The recorder is hidden **and refuses to run** — hiding a control is presentation, not protection,
  and the endpoint refuses independently of both.
- The next sentence is still gated on a submitted attempt, exactly as it was gated on a recording.
- The completion summary reads *"⌨ Reading: N%"* rather than *"🎤 Pronunciation: N%"*. Same
  server-verified number; calling a typed result a pronunciation score would be untrue.
- Nothing about the number is computed in the browser: no threshold, no reward amount, no pass
  decision. Measured in a real browser — no `getUserMedia`, no `MediaRecorder` constructed, no
  `/api/stt` call, and no timeout reconciliation (there is no slow inference to reconcile).

Accessibility of the control itself matters more here than usual, since the learners who need it are
the least able to work around a control that is mouse-only or unlabelled: a real `<label for>` (never
a placeholder), an `aria-describedby` hint, Enter to submit, a visible focus outline, 16px+ text so
iOS does not zoom, and a 44px+ target at 360px width.

## The educator's surface

On each authoritative class-member card in the Teacher / Parent dashboard:

> ☐ **Allow typed Read Along**
> Lets this learner type the sentence instead of speaking it. Same sentences, same scoring, same pass
> mark.

Functional wording only — what the setting *does*, never why a learner might need it. The checkbox
only **requests** the change: the box is reconciled to whatever the server reports back, reverts on
refusal, and says plainly *"You cannot change this learner's settings."* Legacy rows and the admin
overview render no control at all.

## Properties guaranteed by test

`tests/read_along_accommodation_test.py` (17 checks), `tests/read_along_typed_client.test.js`
(10 checks), plus 51 browser-acceptance checks against the real server:

1. Every existing account defaults to speech with the field absent — no migration.
2. A learner cannot enable it for themselves; nor can a classmate or an unrelated teacher. Zero
   mutation on refusal.
3. Tokens fail closed; an unknown target is indistinguishable from an unauthorized one.
4. A legacy roster name can never receive it, and never becomes an account.
5. Provenance is actor + timestamp only. No diagnosis/reason/note is storable or stored.
6. A speech-only account calling the typed endpoint **directly** is refused, with no progress and no
   Gold. The hidden text box is not the protection.
7. Forged `score`/`passed`/`rewarded`/`target` fields are ignored.
8. Typed and speech score **identically** across exact text, capitalisation, punctuation, whitespace,
   a missing word, a wrong word and a poor answer.
9. The threshold is the one shared `PASS_MARK`; typed mode has no easier bar.
10. Typed completion writes the existing read-along activity id; the required set stays at 5 (A1).
11. Read-along pays no gate reward in either mode; the quiz gate still pays 160 and mastery still
    pays 640 once, through the same settlement.
12. Speech-after-typed and typed-after-typed both pay zero and never re-grant mastery.
13. Disabling preserves completion, mastery and Gold exactly; later typed submissions are refused.
14. A class move removes the old teacher's authority at once and grants it to the new owner; a stale
    roster copy cannot restore it.
15. The setting never appears in another learner's view or the leaderboard, and no salt/hash/token
    leaks to a teacher.
16. Curriculum invariants unchanged: 57 lessons / 457 activities / read-along required in all 57,
    `PASS_GOLD` 160, `MASTERY_GOLD` 640, fingerprint `736503ae2c4f5fa5`.

## Known limitations

- **Typing is not reading aloud.** This measures whether the learner can render the sentence in
  writing, which is the closest thing the existing scorer can assess without audio. It is an
  accessibility accommodation, not an equivalent assessment of pronunciation, and an educator turning
  it on should understand that. Nothing in the product claims otherwise.
- **A copy-paste can score 100%.** So can a perfect recording of someone else's voice; neither mode
  has ever been proof-of-identity, and this phase did not add one.
- **No self-service.** A learner with a genuine need and no teacher in the product cannot enable it.
  That is deliberate: the alternative is self-asserted authority over their own assessment.
- **No audit trail.** Only the latest actor and timestamp are kept, not a history of changes.
- **Legacy roster rows can never be accommodated**, because they cannot be bound to an account
  without guessing an identity.
