# Read-Along availability (Phase 12B.1)

Every one of the 57 lessons requires its `read_along` activity for mastery, and that activity is
scored from speech. This document records what happens when the speech path is slow, busy or broken,
and why each decision was taken. **Nothing here changes what mastery requires** — `requiredActivityIds`,
the completion policies, `PASS_GOLD` (160), `MASTERY_GOLD` (640) and the qualification set are exactly
as they were before this phase.

## What speech recognition needs

| piece | where it comes from |
| --- | --- |
| `faster-whisper` | installed in the image (`Dockerfile`), `pip3 install faster-whisper` |
| model `base.en` | **downloaded at build time**, so the running container needs no network |
| `ffmpeg` | installed in the image; used to convert the browser's webm to 16 kHz mono wav |
| model name | `WHISPER_MODEL` env var, default `base.en` |

A developer checkout normally has none of these. That is why `/api/stt` answers `503
stt_unavailable` locally, and it is **not** evidence that production lacks speech recognition.

## Startup policy: probe, report, keep serving

`stt_warmup()` loads the model once at startup and records the outcome. It is called from
`if __name__ == "__main__":` **only** — never at import time, because the unit tests import `server`
and replace `transcribe()`, and no test should ever pull in a multi-hundred-megabyte model.

Readiness is deliberately tri-state:

| `_stt_ready` | meaning | `/api/stt` behaviour |
| --- | --- | --- |
| `None` | never probed (tests, or any embedding that skips warm-up) | unchanged: the lazy path decides |
| `True` | the probe loaded the model | normal |
| `False` | the probe **ran and failed** | immediate, truthful `503 stt_unavailable` |

**The application still starts when the probe fails.** The Academy, the World board, every quiz,
matching, reorder, dictation, cloze and role-play work without speech recognition, so refusing to
boot would take the whole product down over one activity's dependency. A failed probe is loud in the
log and makes read-along scoring fail honestly from the first request:

```
[stt] warming up model base.en ...
[stt] UNAVAILABLE (ModuleNotFoundError) -- read-along scoring will answer 503 stt_unavailable;
      the rest of the app is unaffected
```

`stt_status()` exposes `{probed, available, reason}` for operators. `reason` is the exception *type*
only — never a message, path or stack trace.

## Concurrency: inference stays serialised

`_infer_lock` is **kept deliberately.** The server is a `ThreadingHTTPServer`, so several children
pressing Record land in different threads on a single shared CTranslate2 model instance. There is no
evidence in this repository that concurrent `transcribe()` on one shared instance is safe, so the
lock stays and read-alongs are graded one at a time.

The cost is throughput, and it is real: with one model on CPU, a class reading simultaneously queues.
What Phase 12B.1 adds is a **bound** on that queue, not more speed:

- `STT_MAX_WAITING` (default 4, env-overridable) caps how many requests may be in the transcription
  section at once. Beyond it the server answers `503 stt_busy`, which the client shows as
  "Speech scoring is busy right now."
- Without that cap, each waiting child parked a thread *and* their audio in memory for as long as the
  queue took to drain — a leak, not a queue.

If concurrent inference is ever shown to be safe, or a model-per-worker design is adopted, this is
the single place to revisit.

## Client abort vs server inference — an honest distinction

The browser bounds the **request**: `STT_REQUEST_TIMEOUT_MS` (25 s) with an `AbortController`. On
timeout the request is aborted, the panel leaves "Scoring…", Record becomes usable and a retry works.

That is a *user* guarantee, not a *server* one. **Aborting the fetch does not stop a running
transcription, and it does not stop the handler.** Python cannot safely terminate a thread
mid-inference, and killing one would risk the shared model, so no attempt is made. An abandoned
inference runs to completion in the background and releases `_infer_lock` when it finishes.

### An abandoned request still settles — measured, not assumed

`_handle_stt()` does its persistence and settlement **before** it writes the response:

```
transcribe(...)  ->  record_read_along(...)  ->  save_progress(...)  ->  econ_add_gold(...)  ->  _send(...)
```

Only the final `_send()` fails on an aborted socket (`ConnectionAbortedError`). Everything before it
has already happened. Measured on the real handler by cutting the client socket mid-inference:

- reading a sentence: the per-sentence best score was persisted and the activity appeared in
  `completedActivityIds` — client gone, state written;
- abandoning the request that crosses the 80% pass mark on the last required activity:
  `activePolicyCompleted` went `False -> True` and the balance moved `660 -> 1300`, i.e.
  **`MASTERY_GOLD` (640) was paid on a request the learner had already abandoned.**

So a timed-out read-along **can** award mastery and Gold that the learner does not see at the time.

This is deliberate and is **not** an authority or reward defect:

- the learner really did speak, and the server really did grade it — nothing is fabricated;
- settlement stays idempotent: repeating that sentence afterwards paid `1300 -> 1300`, no double
  payment;
- the state is authoritative and appears on the learner's next progress read, so it is *delayed*
  visibility, not hidden credit;
- the alternative — discarding a genuine result because the socket closed — would lose work the
  learner actually did.

What the learner sees in that window is the honest timeout message. When they retry, the sentence is
already at its best score, so the retry is harmless.

Accumulation is bounded structurally by `STT_MAX_WAITING` rather than by cancellation. True
cancellation would need inference in a separate process, which is a larger architectural change and
is out of scope for this phase. If the delayed-visibility window is ever considered a product problem,
the fix belongs in the client (re-read progress after a timeout), not in discarding server work.

## What a learner is told

Each failure gets its own truthful sentence. None of them mentions Docker, GitHub Pages, Whisper,
a model name, a path or a stack trace.

| situation | message |
| --- | --- |
| request timed out | ⏱ Speech scoring took too long. Please try again. |
| `stt_busy` | ⏳ Speech scoring is busy right now. Please try again in a moment. |
| `stt_unavailable`, or any other server error | ⚠️ Speech scoring is temporarily unavailable. Please try again. |
| network unreachable | ⚠️ Could not reach speech scoring. Check your connection and try again. |
| session expired (401) | ⚠️ Please log in again to save your read-along score. |
| microphone denied or absent | ⚠️ Cannot use the microphone. Please allow mic permission and try again. |
| browser cannot record | ⚠️ Your browser does not support recording. Use a recent Chrome / Edge / Safari. |
| in-app browser | 🎤 Recording needs an external browser… |

The previous behaviour printed one sentence for all of these, blaming "the server (Docker build)" and
"GitHub Pages" — which a browser cannot know and which is false on a working deployment.

## Infrastructure failure is never academic evidence

For every infrastructure failure — timeout, `stt_unavailable`, `stt_busy`, network error, empty audio,
a `transcribe()` exception — the outcome is the same: no attempt recorded, nothing passed, no mastery,
no Gold, and a retry always possible. A genuine poor reading is different: it scores (possibly 0),
records evidence, pays nothing, and can be improved by reading again, with the best score per sentence
kept. Those two are kept strictly apart.

Note one pre-existing, deliberately non-authoritative behaviour that this phase did not change: with
no scoring backend at all, the read-along *level tab* still unlocks locally so a learner is not stuck
mid-lesson. That is local display and tab progression only — it never becomes server-side evidence,
and it never grants lesson mastery or Gold.

## Not in this phase

No accessibility accommodation. A learner with no microphone, a denied permission or a speech
limitation still cannot reach mastery, because read-along remains required in all 57 lessons. That is
a real product gap, audited in Phase 12A and deliberately left for Phase 12B.2 — it needs a
server-owned, non-self-asserted substitute, not an availability fix.
