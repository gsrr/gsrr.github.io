# Level 2 · Read Along / STT — authority (Phase 3E1)

Inventory of the **existing** Level 2 flow at commit `88b6d45`, then the Phase 3E1 design that makes
it server-authoritative. Everything in §1–§3 was read out of `index.html` / `server.py`, not inferred.

---

## 1. Legacy flow (before Phase 3E1)

```
script[idx].text  (client-parsed from the article text file)
      ↓  POST /api/stt?text=<target>   body = audio blob
transcribe(audio, hint=target)         # faster-whisper, language="en", beam_size=1,
      ↓                                # initial_prompt = target (soft guidance)
{ "transcript": "...", "target": "..." }
      ↓  showPron(target, transcript)  ← SCORING HAPPENS IN THE BROWSER
pronScores[idx] = max(pronScores[idx] || 0, pct)
      ↓  (on finishing the level)
recordScore(2, avg, 100)  →  localStorage only
```

### Sentence representation

`script = parseDialogue(await fetch(article.file).text())`:

```js
text.split(/\r?\n/).map(s => s.trim()).filter(Boolean).map(line => {
  const m = line.match(/^([^:：]+)[:：]\s*(.*)$/);      // "Tom: Hi, Anna." -> who / text
  if (!m) return null;
  return { who: m[1].trim(), gender: …, text: m[2].trim() };
}).filter(Boolean);
```

The article text file is the lesson's `contentPath` **without** an extension (e.g.
`Pre-A1/taipei/zoo`), a sibling of the `…​.json` the deterministic graders read. Every sentence is
scorable; the number of sentences is `script.length` (8 for Zoo, 10 for A1/001).

### Exact scoring formula

```js
function pronWords(s) {
  return (s || "").toLowerCase().replace(/[’ʼ]/g, "'")     // curly apostrophes -> ASCII
    .replace(/[^a-z' ]/g, " ")                             // drop everything except a-z, ' and space
    .split(/\s+/).filter(Boolean)
    .reduce((out, w) => out.concat((CONTRACTIONS[w] || w).split(" ")), []);   // "i'm" -> ["i","am"]
}

function showPron(target, said) {
  const sCount = {};                                       // multiset of transcript words
  pronWords(said).forEach(w => { sCount[w] = (sCount[w] || 0) + 1; });
  let total = 0, matched = 0;
  target.split(/\s+/).forEach(tok => {                     // tokens of the TARGET, whitespace-split
    const subs = pronWords(tok);
    if (!subs.length) return;                              // a token with no letters is not counted
    total++;
    if (subs.every(x => sCount[x] > 0)) { subs.forEach(x => sCount[x]--); matched++; }
  });
  const pct = total ? Math.round(matched / total * 100) : 0;
  pronScores[idx] = Math.max(pronScores[idx] || 0, pct);
}
```

Properties that matter for an exact port:

- **Token granularity is the target's whitespace token**, not the expanded word. `I'm` is ONE token
  that requires BOTH `i` and `am` to be present — all-or-nothing per token.
- **Multiset consumption, greedy left-to-right.** Each transcript word can satisfy only one target
  token; a target saying "the … the" needs two `the`s in the transcript.
- Word order in the transcript is **irrelevant**.
- Extra words in the transcript are ignored (they only ever help by being available to match).
- A target token that reduces to no letters (e.g. `—`, `123`) is skipped entirely — it lowers neither
  `matched` nor `total`.
- `CONTRACTIONS` is a fixed 40-entry English table applied to **both** sides.
- `pct = Math.round(matched / total * 100)` — half-up.
- Empty transcript ⇒ `matched = 0` ⇒ `pct = 0`.

### Retry semantics — **best-per-sentence** (not latest-wins)

`pronScores[idx] = Math.max(existing, pct)`. A worse retry never lowers a sentence's score. This is
deliberately different from the whole-lesson rule (`recordScore` latest-wins at the *level* level, see
[lesson-completion.md](lesson-completion.md) §2) — the two must not be conflated.

### Level 2 aggregation

```js
const scoredCount = Object.keys(pronScores).length;
if (scoredCount > 0) {
  let sum = 0;
  for (let i = 0; i < script.length; i++) sum += (pronScores[i] || 0);   // unscored sentence = 0
  recordScore(2, Math.round(sum / script.length), 100);                  // correct=avg, total=100
} else {
  recordScore(2, script.length, script.length);                          // FULL MARKS fallback
}
```

- The mean is over **every** sentence in the script; sentences never recorded count as 0.
- Stored as `correct = avg, total = 100`, so the generic `levelPassed("2")` rule
  (`round(correct/total*100) >= 80`) means **avg ≥ 80** — Level 2 does have a real pass threshold.

### The backend-unavailable fallback

When *no* sentence was ever scored, the level records **full marks**. Its stated purpose is fairness on
deployments with no backend at all (GitHub Pages serves the same `index.html` with no `/api`). Without
it, Level 2 would score 0 and the level-lock would trap the learner before Level 3.

### Other findings

- No minimum-confidence or threshold logic anywhere; the transcript is used as-is.
- Language assumption: `pronWords` keeps only `[a-z']`, and `transcribe(..., language="en")` — the
  rule is **English-specific**, which Phase 3E1 declares as scorer config rather than hardcoding.
- There is exactly **one** pronunciation scorer (`showPron`). Roleplay also calls `/api/stt`, but with
  **no** `text` param and is graded by `roleplay/classifier.js` — a different, untouched path.
- `/api/stt` accepted **arbitrary** `?text=` from the client and returned only a transcript. It
  created no server state at all.

---

## 2. §4 / §36 STOP determination — **no stop**

| # | Condition | Verdict | Evidence |
|---|---|---|---|
| 1 | Score not reproducible from server-visible inputs | FALSE | pure text function of (target, transcript) |
| 2 | Client uses data the server never receives | FALSE | target is derivable from lesson content; transcript is server-produced |
| 3 | STT nondeterminism breaks the semantics | FALSE | the server scores the transcript **it generated**; parity is (target, transcript) → pct |
| 4 | Browser-only audio analysis | FALSE | no audio analysis exists — scoring is text comparison only |
| 5 | Multiple materially different implementations | FALSE | one scorer (`showPron`); roleplay is a separate untouched path |
| 6 | Requires a new STT model/provider | FALSE | same `transcribe()`, same model, same params |
| 7 | Retry semantics ambiguous | FALSE | `Math.max` per sentence, unambiguous |
| 8 | Offline fallback is a product requirement | **FLAGGED** | see below |

**§4.8 — flagged, not blocking.** The full-marks fallback *is* load-bearing for the GitHub Pages
deployment, which has no `/api` at all. §14 already prescribes the resolution and §15 explicitly
permits keeping it as "legacy UI convenience": it stays as a **local, non-authoritative** progression
convenience and never becomes server evidence. On a backend deployment it can no longer mask an
outage as success. No new product rule was invented here — flagging it explicitly per §4.

---

## 3. Phase 3E1 design (as built)

### Authority split

| Concern | Before | After |
|---|---|---|
| Target sentence | client sends `?text=` | **server** resolves from lesson content by `sentenceIndex` |
| Transcript | server | server (unchanged) |
| Per-sentence score | **browser** | **server** (`learning/stt_scoring.py`, exact port) |
| Best-per-sentence | browser memory | **server** state, per account |
| Level pct | browser | **server** (`activityPct`) |
| Persistence | `localStorage` | `learning.sttProgress` in the per-account progress file |
| Outage | full marks | **no evidence at all** |

### Scorer boundary (§8)

STT is deliberately **not** in the deterministic `GRADERS` table — it has different inputs (audio →
transcript) and different retry semantics (best-per-sentence). An activity declares **exactly one** of
`graderType` (deterministic) or `scorerType` (`read_along_stt`).

```
score_sentence(target, transcript) -> {pct, matchedTokens, totalTokens}
```

### Registry

```jsonc
"english.prea1.taipei.zoo.read_along": {
  "lessonId": "english.prea1.taipei.zoo",
  "scorerType": "read_along_stt",       // no contentKey: the content IS the lesson's dialogue file
  "title": "Taipei · At the Zoo — Read Along",
  "grants": [],                          // §20: no new qualification
  "rewardPolicy": "none"                 // §20/§21: no new gold
}
```

### Persistence (§9, §11)

```jsonc
"learning": {
  "sttProgress": {
    "<activityId>": {
      "sentences": { "<index>": { "score": 0-100, "updatedAt": … } },   // BEST per sentence
      "totalSentences": 8,
      "pct": 0-100                                                      // round(sum / totalSentences)
    }
  }
}
```

Per-account (room-independent, survives territory loss, refresh and re-login), additive, atomic save.
No audio and no raw STT payload is stored.

### Activity completion (§12)

Level 2 has a real 80% threshold, so it **is** represented as an activity completion: when
`activityPct >= PASS_MARK` the normal `activityCompletions[activityId]` record is written through the
existing machinery, with the existing reward/qualification policy (both "none" here). Below the
threshold, `sttProgress` still records the evidence — the score is real, the pass is not yet.

### `/api/stt` contract (§16)

Authoritative mode (client sends `activityId` + `sentenceIndex` + token):

```jsonc
{ "transcript": …, "target": …, "score": 0-100, "activityId": …, "sentenceIndex": 3,
  "activityPct": 0-100, "activityPassed": false, "totalSentences": 8, "authoritative": true }
```

`?text=` is **ignored** in this mode. Legacy mode (no `activityId`) still returns
`{transcript, target, authoritative: false}` and creates **no** state — this is what roleplay uses.

### Outage (§14, §27)

If transcription fails, the endpoint returns an error, writes nothing, and creates no score, no
completion, no qualification and no reward. The client shows a retry message. On a backendless
deployment the local full-marks convenience remains, clearly marked non-authoritative.

---

## 4. What this does NOT unblock

Production lesson `completionPolicy` count remains **0**. The remaining blocker is
**Level 5 · Matching** (Phase 3C category B). See [lesson-completion.md](lesson-completion.md) §9.
