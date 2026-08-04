# Level 10 Role-play — server-authoritative sessions (Phase 4C)

Role-play was the last Rule A level whose score was computed in the browser. Phase 4C moved it behind
a **server-owned session**: the server owns the graph, the current node, the branch RNG, the
classifier thresholds and the turn/pass counters. The client sends only what the learner said.

This document is both the **exact legacy inventory** (§1–§7, unchanged evidence carried forward from
the Phase 4B gap record) and the **new authority model** (§8 onwards). Nothing here was approximated:
every claim was read out of `index.html`, `roleplay/engine.js`, `roleplay/classifier.js` and
`roleplay/scenarios/`, or produced by executing the shipped code.

---

## 1. Why this mattered

`scoredLevelsFor()` appends level 10 **unconditionally**, so legacy Rule A for every Taipei lesson
scores seven levels: `["2","3","4","5","7","9","10"]`. Level 10 was the only one without server
authority, which is why Phase 4B retired Zoo's 6-activity policy rather than let it silently redefine
the rule. With Phase 4C, **all seven levels are authoritative** — see §14.

## 2. Exact legacy flow (unchanged by this phase, except where §11 says so)

| Step | Code | Behaviour |
|---|---|---|
| 1 | `index.html` level-tab handler | selecting Level 10 un-hides `#level10` and calls `startRolePlay()` |
| 2 | `rpLoadLessonScenario(key, cb)` | `fetch("roleplay/scenarios/lesson/" + key.replace(/\//g,"-") + ".json")`; used only if `g.nodes.length` |
| 3 | `rpBuildLessonGraph()` | fallback: builds a linear graph from the lesson dialogue in the browser |
| 4 | `new RP.Engine(graph, …)` | `classifier: new RP.classifiers.local({pass: 0.5, floor: 0.2})`, `strategy: "weighted"` |
| 5 | `eng.start()` → `_enter(start)` | `onNode` → `rpOnNode` speaks the NPC line, then enables input |
| 6 | user answers | typed into `#rpText`, or spoken via `#rpMic` (target-less `/api/stt`, transcript only) |
| 7 | `eng.submit(text)` | `turns++`, classify, push history, `onResult`, advance **only** on PASS |
| 8 | terminal node | `_enter` sees `node.end` or no routes → `_finish()` → `onEnd` → `rpOnEnd` |
| 9 | `rpOnEnd(summary)` | `recordScore(10, summary.passes, summary.turns)` + `markLevelDone(10)` |

The tab is visible for any lesson whose dialogue has ≥2 sentences, i.e. all four Taipei lessons.

**There is only one Level 10 scoring path.** `roleplay/app.js` is a developer sandbox with strategy
and classifier pickers; it never calls `recordScore`, so it is not a second scoring rule.

## 3. Graph schema and source

Authored graphs live at `roleplay/scenarios/lesson/<contentPath with '/'→'-'>.json`. All four Taipei
lessons have one, so the browser fallback builder is never used for them.

```
{ id, lesson, title, you, npc, npc_gender, start, max_turns, nodes: [ … ] }

node  : { id, npc: {text, gender}, learning_objective?: [...], routes?: [...], end?: true,
          fallback?: { partial: {message}, off_topic: {message} } }
route : { intent, meaning, examples: [...], keywords: [...], hint,
          next_nodes: [ {id, weight} ], partial?: true, objective?: {markers: [...]} }
```

Observed across all four Taipei graphs: 7–8 nodes, `start: "arrive"`, `max_turns: 24`, exactly one
terminal node (`bye`, `end: true`, no routes), all weights `100`, and **exactly one `next_node` per
route**. No lesson scenario (of all 57 on disk) uses `partial` or `objective`.

Two consequences, both honest limitations rather than problems:

- **Weighted RNG never actually branches on current content.** With one candidate per route the draw
  is deterministic. The algorithm is ported faithfully so multi-branch graphs work, and parity is
  proven against a synthetic 1/3/96 route.
- **`objectiveMet` is always true** and the data-driven PARTIAL branch never fires for real content.
  Both are ported and covered by synthetic tests.

## 4. Classifier — `RP.classifiers.local`

Fully offline lexical scoring. **No LLM, no embeddings, no external API**, and deterministic: same
text + same node ⇒ same result.

```
tokens(s)        = s.toLowerCase(), every char outside [a-z0-9\s'] → " ", split on whitespace runs
contentWords(t)  = drop STOP words; if ALL are stop-words, keep them
close(a,b)       = equal | prefix (len(a)≥4, len(b)≥3) | edit distance ≤ 1
has(set,arr,w)   = w in set OR any close(s, w)
coverage(u,t)    = |content words of t present in u| / |content words of t|   (duplicates NOT collapsed)

scoreRoute = min(1, max over examples of coverage
                    + (keywords hit ? min(0.35, 0.18 + 0.09*hits) : 0)
                    + coverage(meaning) * 0.1)
```

Decision order, exactly as shipped:

1. no routes → `OFF_TOPIC`
2. `route.partial` **and** score ≥ FLOOR → `PARTIAL`
3. score < FLOOR → `OFF_TOPIC`
4. score ≥ PASS → `PASS` if objective markers met, else `PARTIAL`
5. otherwise (FLOOR ≤ score < PASS) → `PARTIAL`

**Thresholds.** `LocalClassifier` defaults are `pass 0.6 / floor 0.28`, but the lesson caller
overrides them with **`pass 0.5 / floor 0.2`**, so that is what Level 10 scores against. Both pairs
are covered by parity tests. The thresholds are server-owned config; the client cannot set them.

The spec calls the middle band "SOFT"; the shipped code calls it **`PARTIAL`**, and it contributes
**0** to `passes` — there is no fractional credit anywhere.

## 5. Turn and pass semantics

```js
Engine.prototype.submit = function (userText) {
  if (this.done || !this.current) return …;
  this.turns++;                       // EVERY submission, whatever the classification
  …
};
_finish: const passes = this.history.filter(h => h.result === "PASS").length;
```

- `turns` increments for **PASS, PARTIAL and OFF_TOPIC alike**.
- A non-PASS leaves the learner on the same node (`rpNudge` repeats the prompt), so fumbling only
  inflates the denominator.
- `passes` counts PASS results only.
- The denominator is therefore **unbounded and learner-dependent**. Phase 4C preserves this exactly;
  normalising it is a product decision, not a migration detail.

## 6. Termination

The only shipped termination is **reaching a terminal node** (`end: true`, or no routes).
`max_turns` does **not** end the conversation — the engine merely sets `info.maxTurnsReached`, a flag
no UI reads. A learner who never passes can loop forever.

## 7. Retry / restart and storage

- Re-entering the Level 10 tab calls `startRolePlay()` again, which resets and rebuilds: a retry is a
  **whole new conversation**, never a resumption.
- `recordScore` overwrites unconditionally → **latest-wins**. A worse second conversation lowers the
  stored level-10 score. There is no best-of.
- Legacy storage was `localStorage["score:<user>:<file>"]["10"] = {correct: passes, total: turns}`,
  uploaded only inside the opaque `sdata` blob the server does not interpret.
- A conversation that ends with **zero** user turns stores `total: 0`, which `statusFromScores`
  treats as *unscored*.

---

## 8. The new authority model

```
client taps Level 10
      ↓  POST /api/learning/roleplay/start {activityId}
server: registry → scenarioPath → realpath containment → validate_graph → version hash
        creates an opaque session on the graph's start node
      ↓  {sessionId, prompt:{nodeId,text,gender,objective}, turn, passes, completed, you, npc}
client renders the NPC line and collects the learner's words
      ↓  POST /api/learning/roleplay/respond {sessionId, response, seq}
server: owns session → classifies → turns++/passes++ → weighted RNG picks next node
        → detects terminal → persists
      ↓  {result, hint, prompt, turn, passes, completed, score?}
on completion: learning.roleplayProgress[activityId] = {passes, turns, pct, sessionId, updatedAt}
```

The server owns: `sessionId`, account, `activityId`, graph + `graphVersion`, `currentNodeId`,
`visited`, RNG, `turns`, `passes`, thresholds, completion and the final score.
The client owns: rendering, audio, input collection, and submitting the response.

### What the client cannot do (§6, §32)

A client-submitted transcript is **never** accepted as proof of the conversation. Every one of
`currentNodeId`, `nextNodeId`, `graph`, `graphVersion`, `turns`, `passes`, `score`, `pct`,
`completed`, `result`, thresholds (`pass`/`floor`), `rng`, `rewardAmount`, `qualifications` and
`policyVersion` is ignored if sent — proven by unit test and in real Chrome.

### Session identity and lifecycle (§12, §13, §30)

`secrets.token_hex(16)`, stored **inside the owning account's own learning state**, so another
account simply has no such session — ownership is structural, not a check that can be forgotten.

```
learning.roleplaySessions[sessionId] = {activityId, graphVersion, currentNodeId,
                                        turns, passes, visited, createdAt, updatedAt, completed}
```

- `SESSION_TTL` 6 h; an expired session is refused and dropped.
- Starting a session retires any other **open** session for the same activity and prunes expired ones;
  completed sessions are compacted to the most recent 8.
- A completed session can never be replayed to change evidence.
- `graphVersion` (sha256 prefix of the scenario file) is re-checked every turn: if the content changes
  mid-session the turn is refused rather than scored against different rules.
- `roleplaySessions` is **never** exposed by `/api/learning/state` — revealing the current node would
  tell the client where the conversation is going.

### Concurrency (§29)

`seq` is the turn index the client believes it is answering. A mismatch → `stale_turn`, refused with
**no** counter change. This covers double-clicks, duplicate submits, stale responses and two tabs.
Verified in Chrome: three identical concurrent submits, exactly one counted.

### Defensive turn ceiling (§19)

`HARD_TURN_CAP = 200` force-completes a runaway session. This is **defensive infrastructure, not
scoring semantics**: the shipped engine never terminates on turns, and the cap sits far above any
authored graph's `max_turns` (24), so no valid flow is affected.

### Score evidence (§20, §21, §22)

```
learning.roleplayProgress[activityId] = {passes, turns, pct, sessionId, updatedAt}
```

reproducing `recordScore(10, passes, turns)` exactly, with `pct` under JS `Math.round` (half-up)
semantics. **Latest-wins**, matching `recordScore`'s unconditional overwrite. A 0-turn session stores
nothing readable, so it reads as unscored.

Role-play has **no independent pass definition** beyond its numeric score, so it writes **no**
`activityCompletion` and grants nothing.

The central resolver now has four sources, and the lesson policy still knows none of them:

| Level | Source |
|---|---|
| deterministic graders | `activityScores` |
| Read-Along | `sttProgress` |
| Matching | `matchingProgress` |
| **Role-play** | **`roleplayProgress`** → `correct = passes`, `total = turns` |

### Backendless mode (§27, §28)

Backend mode is chosen **before** the session starts: authenticated **and** the registry has a
`roleplay` activity for this content path. Otherwise the legacy local engine runs as pure practice,
clearly marked, and its result can never become authoritative evidence.

On a backend failure mid-session the UI shows a retryable error and **does not** invent a turn,
compute a local score, or silently switch modes.

## 9. Registration

Four activities, all `rewardPolicy: "none"`, `grants: []`:

```
english.prea1.taipei.{zoo,mrt,market,park}.roleplay
  scorerType   : "roleplay_local"
  scenarioPath : "roleplay/scenarios/lesson/Pre-A1-taipei-<slug>"
```

`scorerType` sits beside `read_along_stt` and `matching_first_try`, outside the stateless `GRADERS`
table. A Role-play activity declares no `contentKey` and is **not** reachable through
`POST /api/learning/attempt` (it returns `not_gradable`).

`scenarioPath` is registry data only. The safety chain is: registry allowlist → canonical activityId →
`identity.is_content_path` shape → realpath containment inside `CONTENT_ROOT` → `validate_graph`.

## 10. Graph validation (§10)

Fails closed on: non-object graph, empty/duplicate node ids, missing or unknown `start`, dangling
`next_nodes` targets, malformed weights (0, negative, non-numeric), routes with neither examples nor
keywords, missing `intent`, missing `npc.text`, `end` nodes that still declare routes, unsupported
`strategy`, non-positive `max_turns`, and graphs with no terminal node. A graph that fails validation
cannot start a session at all.

Cycles are permitted (a non-PASS stays on the same node by design); the lifecycle — TTL, `seq`,
and the defensive cap — is what prevents an unbounded session.

## 11. Intentional behaviour changes

1. **Branch selection moved to the server.** No observable difference on current content (one
   candidate per route), and parity-tested on a multi-branch graph.
2. **Thresholds are server-owned.** Previously the caller passed `{pass: 0.5, floor: 0.2}` in the
   browser; the same numbers now live in `learning/roleplay.py` and cannot be overridden by a client.
3. **A defensive 200-turn ceiling exists** where the legacy engine had none (§19).
4. **`seq` is required** to count a turn, so duplicate submits are refused rather than double-counted.
5. **A mid-session scenario edit refuses the turn** (`graph_changed`) instead of scoring against the
   new graph.

Not changed: the classifier, its thresholds' values, the weighted algorithm, turn/pass counting,
termination, retry semantics, the score formula, or what the learner sees.

## 12. Parity evidence

`tests/learning_roleplay_parity_test.py` runs the **real** `classifier.js` and `engine.js` in node
against the Python port:

- **774 classifier cases** — every node of all four real graphs × 20 responses (verbatim examples,
  paraphrases, keyword-only, case/punctuation/whitespace variants, duplicate tokens, apostrophes,
  non-ASCII, empty, all-stop-words, nonsense), plus synthetic `partial`/`objective`/no-route nodes,
  plus the class-default thresholds. Result, intent, `objectiveMet` and every rounded route score
  match exactly. Coverage: 125 PASS / 70 PARTIAL / 579 OFF_TOPIC.
- **Weighted selection** — 4 seeds × 40 draws over a 1/3/96 route, using the same mulberry32 PRNG in
  both languages.
- **5 full-session goldens** — all-strong, mixed, repeated off-topic (never advances, never
  completes), multi-branch weighted, and a real MRT run to terminal. Node sequence, per-turn result,
  `turns`, `passes` and the final `onEnd` summary all match.

## 13. Security audit result

| Attack | Result |
|---|---|
| anonymous start / respond | **401** |
| another account's `sessionId` | `unknown_session` — it does not exist in BOB's state |
| unknown / expired / completed session | refused; expired is dropped; completed is immutable |
| duplicate or stale `seq` | `stale_turn`, counters untouched |
| forged node / graph / version / turns / passes / score / completed / result / thresholds / rng / reward / qualification / policyVersion | all ignored |
| non-Role-play activity started as a session | `not_scorable` |
| Role-play submitted to `/api/learning/attempt` | `not_gradable` |
| graph internals in any response | none — no routes, keywords, next_nodes, weights, intents or fallbacks |

## 14. Rule A readiness — all four Taipei lessons

| Level | Activity suffix | Authoritative source | Evidence | Parity |
|---|---|---|---|---|
| 2 · Read Along | `read_along` | `sttProgress` | `correct = pct`, `total = 100` | Phase 3E1 |
| 3 · Quiz | `quiz3` | `activityScores` | exact `correct`/`total` | Phase 3A/3C |
| 4 · Tricky Quiz | `quiz4` | `activityScores` | exact `correct`/`total` | Phase 3C |
| 5 · Match | `matching` | `matchingProgress` | `firstTry`/`n` | Phase 3E2 |
| 7 · WH | `wh` | `activityScores` | exact `correct`/`total` | Phase 3C |
| 9 · Fill Blank | `cloze` | `activityScores` | exact `correct`/`total` | Phase 3C |
| **10 · Role-play** | **`roleplay`** | **`roleplayProgress`** | **`passes`/`turns`** | **Phase 4C** |

**Can shipped Rule A now be reproduced exactly server-side for each lesson? Yes** — for Zoo, MRT,
Night Market and Park. All seven scored levels have an authoritative source supplying an exact
numerator and denominator, and `rule_a_mean` is already parity-tested against the real
`statusFromScores()` over 40 (lesson, score-vector) pairs.

`tools/validate_content_coverage.py` reports **7/7** for all four lessons.

**Phase 4D activated it.** All four Taipei lessons now carry `average_required_activities` **version
2** requiring exactly these seven activities, passMark 80, `rewardPolicy: "none"`, `grants: []`, so the
production `completionPolicy` count is **4**. Zoo's retired v1 remains recorded and unusable, and a
learner who completed under v1 keeps that record while gaining a separate v2 history entry — see
`docs/lesson-completion.md`.

## 15. Known limitations

- **The denominator is still unbounded.** `passes/turns` penalises exploration: three fumbles before
  a correct answer cost as much as three wrong answers. Preserved deliberately (§18); changing it
  changes Rule A parity and is a product decision.
- **RNG has nothing to choose on current content** — every route has one `next_node`. Server RNG is
  correct and tested, but it is latent capability, not an observable change.
- **`partial` routes and `objective.markers` are unused** by all 57 lesson scenarios. Ported and
  tested synthetically; no production content exercises them.
- **The browser fallback graph builder** (`rpBuildLessonGraph`) has no server equivalent. Any lesson
  without an authored scenario simply gets no Role-play activity, and therefore no authoritative
  level 10. All four Taipei lessons have one.
- **Spoken answers still use the target-less `/api/stt`** to become text; the transcript is client
  input to a server-side classifier. Making that leg authoritative was not in scope.
- **Remote Docker STT gate** is unchanged and unrelated to Role-play: `faster_whisper` import,
  `ffmpeg`, model load, one real transcription, authoritative `sttProgress`, 503 on failure. It
  remains a release task and cannot be certified in this environment.
