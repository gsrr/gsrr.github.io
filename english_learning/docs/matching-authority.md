# Level 5 · Match — authority (Phase 3E2)

Inventory of the **existing** Matching implementation at commit `1016881`, then the Phase 3E2 design
that makes it server-authoritative. §1–§3 were read out of `index.html`, not inferred.

---

## 1. Legacy implementation (`makeMatch`, Level 5)

### Content

`vocab` in the lesson JSON: `[{ "word": "Tom", "pic": "👦" }, …]`. Measured across all 57 lessons:

| Property | Value |
|---|---|
| lessons with `vocab` | 57 |
| items per lesson | 5 (×3), 6 (×45), 7 (×8), 10 (×1) — **always ≥ 5** |
| duplicate `word` within a lesson | **0** |
| duplicate `pic` (emoji) within a lesson | **4 lessons** |

The pairing source is the `vocab` array itself: item *i*'s word pairs with item *i*'s picture. There
are no explicit ids in the content.

### Sample

```js
const n = Math.min(5, vocab.length);
seq = shuffle(vocab).slice(0, n);      // random sample, kept in shuffled order
```

- `n` is therefore **always 5** for shipped content.
- The **left column** shows `seq` in that order, numbered 1…n.
- The **right column** is an *independent* second shuffle of the same n items:
  `shuffle(seq).forEach(item => … clickPic(item.word, b) …)`.
- Each picture button closes over **its own item's word**, so the 4 lessons with duplicate emojis
  still behave correctly — identity is the item, not the glyph.

### Interaction and first-try scoring

```js
function clickPic(word, btn) {
  if (btn.disabled || expected >= seq.length) return;      // matched pictures are inert
  if (word === seq[expected].word) {                        // ONLY the current word counts
    btn.disabled = true;
    if (!missedCurrent) firstTry++;                         // the point
    mark = missedCurrent ? " ✗" : " ✓";
    expected++; missedCurrent = false;
  } else {
    missedCurrent = true;                                   // point lost for THIS word, permanently
    // the wrong button is NOT disabled — it can be clicked again (still wrong, still no point)
  }
}
```

- Matching is **strictly sequential**: only the word at `expected` can be matched next.
- "First attempt" means *the first click made while that word is current*. A wrong click on any
  picture sets `missedCurrent`, which is only cleared when the word is finally matched.
- Clicking an **already-matched** picture is a no-op — not a wrong attempt.
- Clicking the same wrong picture repeatedly costs nothing extra (the point is already lost).
- Every sampled word must eventually be matched; there is no way to finish early or skip.

### Completion and score

```js
recordScore(5, firstTry, seq.length);   // correct = firstTry, total = n
markLevelDone(5);
```

`levelPassed("5")` uses the generic rule `Math.round(correct/total*100) >= 80`, so with n = 5 a
learner passes at **4 of 5 first-try**. There is no separate matching threshold.

### Restart / retry — **explicitly allowed, and it re-rolls the sample**

Three paths call `build()`, and `build()` always draws a **new random sample** and resets `firstTry`:

| Path | Trigger |
|---|---|
| `resetEl` ("Try Again", shown on completion) | learner clicks it |
| `finishRetry` → `matchCtl.restart()` | the level-finish bar |
| `setData(v)` | the lesson (re)loads |

`recordScore` is **latest-wins**, so a re-run overwrites the previous Level 5 score — better *or*
worse. A learner may therefore retry until they get 5/5.

**Trust implication (§20).** This is the existing product behaviour, so Phase 3E2 preserves it: a new
round is a new scored attempt, and the latest completed round is the one that counts. It is
deliberately *not* changed to best-of or to a one-shot rule — that would be a product decision, not
an authority migration. The consequence is that the score proves "the learner eventually did a clean
round", not "the learner did it clean first time ever".

### Storage

`localStorage` only, via `recordScore` → `score:<user>:<file>`. Nothing about matching reaches the
server today.

---

## 2. §42 STOP determination — **no stop**

| # | Condition | Verdict | Evidence |
|---|---|---|---|
| 1 | Sample/restart semantics ambiguous | FALSE | all three restart paths call the same `build()`; new sample + latest-wins, unambiguous (§1) |
| 2 | Server cannot reproduce the sample algorithm | FALSE | it is `shuffle(vocab).slice(0, min(5,len))`; the server does the same draw with its own RNG. Player experience is identical: 5 random items |
| 3 | Stable item identity impossible without rewriting content | FALSE | `vocab` index is stable and deterministic → derived ids, no content change |
| 4 | firstTry needs browser state not representable as click attempts | FALSE | it is exactly a function of the click stream, which the new API carries |
| 5 | Retry semantics conflict between UI paths | FALSE | all three paths are the same `build()` |
| 6 | Server-owned sample changes the experience materially | FALSE | same size, same source, same randomness |
| 7 | Persistent round state needs destructive migration | FALSE | additive keys only |
| 8 | Score cannot map into the Learning evidence model | FALSE | `correct/total/pct` maps like every other activity |
| 9 | Reward would change | FALSE | `rewardPolicy: "none"` |
| 10 | Lesson completion would silently activate | FALSE | production `completionPolicy` count stays 0 |

---

## 3. Phase 3E2 design (as built)

### Why the final state was insufficient

A completed match always ends in "every word matched". The score lives entirely in *how many wrong
clicks happened along the way*, so no end-state submission can prove it — and asking the client for
`firstTry` would be trusting client-derived correctness (Phase 3C §8/§43.10). Hence **server-owned
rounds**: the server draws the sample, holds the answer mapping, and observes every click.

### Identity (§16)

Derived deterministically from the authoritative content, no lesson JSON change:

```
itemId   = "<activityId>#item:<vocabIndex>"      e.g. english.prea1.taipei.zoo.matching#item:3
choiceId = "<roundId>#choice:<position>"          position = index in the server's picture shuffle
```

`choiceId` is per **button position**, not per emoji, so the 4 lessons with duplicate emojis are
unambiguous — exactly like the legacy closure over `item.word`.

### Round model (§6, §7)

```jsonc
matchingRounds[roundId] = {
  "activityId": …, "createdAt": …,
  "order":  [vocabIndex, …],        // the sampled items, in left-column order
  "choices":[vocabIndex, …],        // the picture shuffle, by position
  "expected": 0,                    // how many are matched so far
  "missedCurrent": false,           // a wrong click has already happened for the current word
  "firstTry": 0,
  "completed": false
}
```

`roundId` is `secrets.token_hex` — unguessable, stored **inside the owning account's learning state**,
so a round can only ever be reached by its owner. It is bound to one activityId and one sample.

### Lifecycle (§30)

- Starting a round for an activity **retires any other open round for that activity** (only one live
  round per activity per player — matches the UI, which only ever shows one).
- A completed round is compacted into `matchingProgress[activityId]` and removed from the live table.
- Open rounds older than `ROUND_TTL` are dropped on the next start, so state cannot accumulate.
- A completed/unknown/expired roundId is rejected; it cannot be replayed to change a score.

### Evidence (§22, §23)

```jsonc
"matchingProgress": {
  "<activityId>": { "latestRoundId": …, "correct": n, "total": 5, "pct": 0-100, "updatedAt": … }
}
```

Latest-wins, mirroring `recordScore`. When `pct >= PASS_MARK` the normal
`activityCompletions[activityId]` record is written through the existing machinery (grants + reward
policy — both "none" here). A low-scoring completed round records the evidence but **not** a pass.

### Backendless mode (§27)

Without a backend (GitHub Pages) or without a registered matching activity, the UI keeps its existing
local behaviour and is clearly local practice only. A locally computed score is never uploaded and can
never become server evidence.
