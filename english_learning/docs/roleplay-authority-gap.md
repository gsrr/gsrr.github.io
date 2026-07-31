# Level 10 Role-play — the next Learning authority blocker

Evidence record, written in Phase 4B. It documents **what Level 10 does today** and **what the server
can currently see**. It deliberately proposes **no authority model** — that is the next phase's job.

Everything below was read out of `index.html`, `roleplay/engine.js`, `roleplay/classifier.js` and
`roleplay/scenarios/`, or observed by executing the shipped code.

---

## 1. Why this matters

`scoredLevelsFor()` appends level 10 **unconditionally**, so legacy Rule A for every Taipei lesson
requires seven scored levels: `["2","3","4","5","7","9","10"]`. Level 10 is the only one with no
server-authoritative implementation. Until it has one, no lesson can have a completion policy that
reproduces legacy Rule A — which is why Phase 4B activated none and retired Zoo's v1.

## 2. Exact frontend flow

| Step | Code | Behaviour |
|---|---|---|
| 1 | `index.html:1644` | selecting the Level 10 tab un-hides `#level10` and calls `startRolePlay()` |
| 2 | `startRolePlay()` | bails out with a message if `window.RP`/`RP.Engine`/`RP.classifiers` did not load |
| 3 | `rpLoadLessonScenario(key, cb)` | `fetch("roleplay/scenarios/lesson/" + key.replace(/\//g,"-") + ".json")`; returns the graph only if `g.nodes.length`, else `null` |
| 4 | `rpBuildLessonGraph()` | fallback: generates a linear graph from the lesson dialogue itself. Returns `null` if fewer than 2 lines or fewer than 2 speakers |
| 5 | `new RP.Engine(graph, {...})` | `classifier: new RP.classifiers.local({pass: 0.5, floor: 0.2})`, `strategy: "weighted"` |
| 6 | `eng.start()` → `_enter(graph.start)` | fires `onNode` → `rpOnNode` speaks the NPC line via TTS, then enables input |
| 7 | user answers | typed into `#rpText`, or spoken via `#rpMic` |
| 8 | `eng.submit(text)` | `turns++`, classify, push a history entry, fire `onResult`, and advance **only** on `PASS` with a valid next node |
| 9 | terminal node | `_enter` sees `node.end` (or no routes) and calls `_finish()` → `onEnd` → `rpOnEnd` |

The level tab is visible for any lesson whose dialogue has ≥2 sentences
(`tab10.classList.toggle("hidden", !(script && script.length >= 2))`) — i.e. all four Taipei lessons.

## 3. Scenario source

Authored graphs live in `roleplay/scenarios/lesson/<contentPath with '/'→'-'>.json`. All four Taipei
lessons have one:

```
roleplay/scenarios/lesson/Pre-A1-taipei-zoo.json
roleplay/scenarios/lesson/Pre-A1-taipei-mrt.json
roleplay/scenarios/lesson/Pre-A1-taipei-market.json
roleplay/scenarios/lesson/Pre-A1-taipei-park.json
```

So Level 10 is fully playable for every Taipei lesson today — it is not a dormant feature.

If an authored file is missing, `rpBuildLessonGraph()` synthesises a graph **from the lesson dialogue
in the browser**: it splits the script into `{npc lines, your line}` turns, sets each route's
`examples` to the learner's own line, and its `keywords` to that line's content words plus the
lesson's `vocab` words. `max_turns` is `turns.length + 4`.

**Consequence for authority:** the graph is not always a server-side artefact. In the fallback path
the graph is *computed on the client from client-visible content*. A server would have to recompute it
identically, or refuse the fallback path.

## 4. How `turns` is counted

`roleplay/engine.js`:

```js
Engine.prototype.reset = function () { … this.turns = 0; … };   // counts user turns
Engine.prototype.submit = function (userText) {
  if (this.done || !this.current) return Promise.resolve(null);
  this.turns++;                                                  // EVERY submission counts
  …
};
```

- `turns` increments on **every** submission, whatever the classification.
- A `PARTIAL` or `OFF_TOPIC` answer therefore **inflates the denominator** and the learner stays on
  the same node (`rpNudge` repeats the prompt without advancing).
- So `turns` is *not* a property of the lesson. It is a property of how many attempts the learner
  needed — unbounded above, except by `maxTurns` (`graph.max_turns` or 40), which only sets an
  `info.maxTurnsReached` flag and does **not** itself end the conversation.

## 5. How `passes` is counted

```js
Engine.prototype._finish = function () {
  …
  const passes = this.history.filter((h) => h.result === "PASS").length;
  this.cb.onEnd({ turns: this.turns, passes: passes, visited: …, history: …, endNode: … });
};
```

`passes` = the number of history entries classified `PASS`. Because a node only advances on `PASS`,
in practice `passes` ≈ the number of nodes traversed, and `turns − passes` = the number of fumbled
attempts.

## 6. What `rpOnEnd` records

```js
function rpOnEnd(summary) {
  …
  const total = Math.max(1, summary.turns), pct = Math.round(summary.passes / total * 100);
  … shows "You gave <passes> good replies over <turns> turns (pct%)" …
  recordScore(10, summary.passes, summary.turns);   // 計入該課通過分數
  markLevelDone(10);
}
```

- `recordScore(10, passes, turns)` writes `localStorage["score:<user>:<file>"]["10"] = {correct: passes, total: turns}`.
- Note the display uses `Math.max(1, turns)` but `recordScore` is passed the raw `turns`. A
  conversation that ends with **zero** user turns (a graph whose start node is terminal) would store
  `{correct: 0, total: 0}`, and `statusFromScores` treats a falsy `total` as "unscored".
- Nothing is sent to the server. There is no `/api/learning/attempt` call on this path.

## 7. Retry semantics

- Re-entering the Level 10 tab calls `startRolePlay()` again, which does `rpEng = null` and rebuilds
  from scratch, so a retry is a **whole new conversation**, not a resumption.
- The scenario is re-fetched, and for `strategy: "weighted"` the branch choices are re-randomised.
- `recordScore` overwrites unconditionally → **latest-wins**, exactly like every other level. There is
  no best-of tracking, so a worse second conversation lowers the stored level-10 score.

## 8. Does scoring depend on an LLM, semantic evaluation, or client decisions?

| Dimension | Answer |
|---|---|
| LLM? | **No.** The active classifier is `RP.classifiers.local` — pure lexical scoring, fully offline. |
| Semantic evaluation? | **Lexical, not semantic.** `scoreRoute` = max content-word `coverage` over the route's `examples`, plus a keyword bonus (`min(0.35, 0.18 + 0.09·hits)`) and a `meaning` nudge (`coverage × 0.1`), clamped to 1. `close()` adds prefix / edit-distance-1 fuzziness to absorb STT slips. |
| Deterministic given the same input? | **The classifier is.** `classify()` has no randomness — same text + same node ⇒ same result. |
| Client decisions? | **Yes, three of them.** ① `strategy: "weighted"` selects the next node with `rng: Math.random` — the *path* is client-random. ② the thresholds are passed in by the caller (`{pass: 0.5, floor: 0.2}`), overriding the classifier's own defaults (`0.6`/`0.28`). ③ in the fallback path the client also builds the graph. |
| A remote scorer exists? | Only as an unused adapter. `RP.classifiers.remote` documents a contract (`POST /api/classify → {scores:[{intent,score}]}`) but **no such endpoint exists**, and it is off by default. |

**The core difficulty is not the classifier — it is the denominator.** `passes/turns` depends on the
learner's whole conversation path, and that path is selected by client-side `Math.random` over
`next_nodes[].weight`. A server cannot verify or reproduce a conversation it did not conduct.

## 9. What evidence the server currently sees

| Channel | What the server gets | Authoritative? |
|---|---|---|
| `POST /api/stt` (no `text`, no `activityId`) | the audio blob; returns `{transcript, target, authoritative: false}` | **No.** This is the legacy target-less mode, which creates **no** learning state — see `docs/stt-authority.md`. It only turns speech into text for the classifier. |
| `POST /api/learning/attempt` | **never called for level 10** | — |
| `POST /api/student/save` | the whole `localStorage` blob as an opaque `sdata`, including `score:<user>:<file>["10"]` | **No.** The server stores it without interpreting it. |
| `learning.activityScores` / `sttProgress` / `matchingProgress` | nothing — no level-10 activity is registered | — |

So today the server sees **individual transcripts it does not score**, and **a client-authored score
it does not trust**. It has no record of which node was current, which route matched, how many turns
were taken, or whether the conversation completed.

### Confirmed by test

`tests/learning_rule_a_parity_test.py` pins both halves of the consequence:

- the shipped `scoredLevelsFor()` returns `["2","3","4","5","7","9","10"]` for all four Taipei lessons
- perfect scores on levels 2/3/4/5/7/9 with level 10 **missing** ⇒ legacy Rule A `allScored:false`,
  `avg:null`, `passed:false`; adding a level-10 score of even **0/10** completes the lesson at 86

That second pair is the important one: **omitting level 10 is not a conservative approximation of
Rule A, it is a different rule.**

## 10. Open questions for the next phase

Recorded, not answered:

1. Should the server own the conversation (rounds, like Matching), or should it re-score a
   client-submitted transcript log against a server-held graph?
2. Is `passes/turns` the score the product actually wants, given that it penalises exploration and is
   unbounded in the denominator? Changing it changes legacy Rule A parity.
3. What happens to the `rpBuildLessonGraph()` fallback — recompute it server-side, or require an
   authored scenario for any lesson that wants authoritative completion?
4. Does the `weighted` branch strategy need to become server-chosen (or seeded) so the path is
   reproducible?
5. Does the STT leg of a spoken answer need to become authoritative too, or is a client transcript
   acceptable input to a server-side classifier?
6. Which policy version does Zoo's replacement take? Version 1 is retired and recorded as such in
   `learning/registry.json` (`retiredCompletionPolicyVersions`), and the registry validator rejects
   any attempt to reuse it.
