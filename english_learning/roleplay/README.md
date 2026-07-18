# Role Play Engine (MVP)

A **limited-freedom AI role-play engine** for the English-learning app. NPC lines
are authored ahead of time (one sentence = one **Node**); the learner answers
**freely** (text or voice); the system classifies the **intent/meaning** of the
answer and lets the NPC branch through a **conversation graph**.

> **The learner decides the direction, the NPC decides what happens next.**

This module is **self-contained and independently testable** — it does not modify
`index.html`. It reuses the app's existing STT (`/api/stt`), audio scheme
(`audio/index.json` + `speechSynthesis` fallback), and `edge-tts` batch workflow.

```
roleplay/
  index.html            playable UI + Debug panel
  tests.html            in-browser test suite (open it → 12/12)
  engine.js             RP.Engine — conversation graph, branch selection, history
  classifier.js         RP.classifiers.{local, remote} — swappable semantic classifier
  tts.js                RP.tts — audio/index.json mp3 → speechSynthesis → timer
  stt.js                RP.stt — MediaRecorder → POST /api/stt (faster-whisper)
  app.js                UI wiring only
  scenarios/restaurant.json   the demo graph (19 nodes, 41 edges)
  gen_rp_audio.py       batch-TTS the NPC lines into the shared ../audio/
  test.node.js          run the suite headless: `node roleplay/test.node.js`
```

## Run it

Any static web server works (JSON is fetched, so `file://` will not):

```bash
# from english_learning/
python -m http.server 8000
# then open http://localhost:8000/roleplay/index.html
#            http://localhost:8000/roleplay/tests.html
```

- **Text input** works everywhere.
- **Voice input** needs the real backend (`server.py` behind nginx, or the Docker
  image) because it calls `POST /api/stt`. Under plain `http.server` the mic
  falls back to "type instead".
- **Natural mp3 voices** (optional): `pip install edge-tts && python roleplay/gen_rp_audio.py`.
  Without it, the browser's built-in `speechSynthesis` voices the NPC.

## Run the tests

- Browser: open `roleplay/tests.html` → shows `12 / 12 passed`.
- Headless: `node roleplay/test.node.js` (exit code 0 on success).

Covered (spec §10): normal answer · paraphrases · PARTIAL (thirsty / objective
gate) · OFF_TOPIC · ambiguous → higher score wins · weighted branch distribution ·
event branches · graph loop · retry-stays-on-node · full completion.

---

## Data model (Node JSON)

One NPC sentence = one node. A node lists **routes** (candidate learner intents);
each route lists the **next_nodes** the NPC may jump to.

```jsonc
{
  "id": "restaurant",
  "start": "node_seated",
  "max_turns": 40,
  "you": "Customer", "npc": "Waiter", "npc_gender": "female",
  "nodes": [
    {
      "id": "node_seated",
      "type": "normal",                 // normal | event | clarification | challenge | recovery
      "npc": { "text": "What would you like to order?", "gender": "female" },
      "context": { "scene": "restaurant", "situation": "The waiter is taking the order." },
      "learning_objective": ["Order food", "Practice 'I'd like...'"],
      "routes": [
        {
          "intent": "order_food",
          "meaning": "The customer orders or requests a food item.",   // used by the classifier
          "examples": ["I'd like a hamburger.", "Can I have the pasta?"],
          "keywords": ["hamburger", "pasta", "pizza"],                 // optional signal boost
          "objective": {                                              // optional: separates
            "label": "Use 'I'd like' / 'Can I have'",                 // learning objective from
            "markers": ["i'd like", "can i have", "please"]           // semantic correctness
          },
          "next_nodes": [                                             // NPC picks one (weighted)
            { "id": "node_fries",    "weight": 40 },
            { "id": "node_sold_out", "weight": 20 },                  // an "event" branch
            { "id": "node_combo",    "weight": 20 },
            { "id": "node_clarify",  "weight": 20 }
          ]
        },
        {
          "intent": "express_thirst",   // a PARTIAL route: related but incomplete
          "partial": true,
          "meaning": "The customer talks about being thirsty but does not order.",
          "examples": ["I'm thirsty."],
          "hint": "I understand! Now order a drink: 'Water, please.'"
        }
      ],
      "fallback": {                                                   // spoken, stay on node
        "partial":  { "stay_on_current_node": true, "message": "Try: 'I'd like a hamburger.'" },
        "off_topic":{ "stay_on_current_node": true, "message": "Let's talk about your order." }
      }
    },
    { "id": "node_goodbye", "end": true, "npc": { "text": "Goodbye!", "gender": "female" }, "routes": [] }
  ]
}
```

### PASS / PARTIAL / OFF_TOPIC (spec §8–9)

Semantic correctness and learning-objective completion are **separate**:

| Result | When | NPC behavior |
|---|---|---|
| **PASS** | top route ≥ `pass` **and** objective markers present | branch to a `next_nodes` node |
| **PARTIAL** | matched a `partial` route · **or** objective markers absent · **or** score in `[floor, pass)` | stay, speak a hint |
| **OFF_TOPIC** | top score `< floor` | stay, redirect |

## Architecture — the swappable seams (spec §13)

Everything the engine talks to is behind a small interface, so any single AI
provider can be replaced with **zero engine changes**:

- **Classifier** — `classify(text, node) → Promise<{result,intent,route,objectiveMet,scores,reason}>`.
  MVP default `RP.classifiers.local` scores the learner's text against **only the
  current node's routes** (runtime, no vector DB — spec §7). `RP.classifiers.remote`
  is a ready adapter for a server cross-encoder / LLM:
  `POST /api/classify {text, routes:[{intent,meaning,examples}]} → {scores:[{intent,score}]}`
  (off by default; falls back to local on any error).
- **STT** — `RP.stt` (MediaRecorder → `/api/stt`). Swap for Web Speech API / cloud.
- **TTS** — `RP.tts` (mp3 clip → `speechSynthesis`). Swap for any voice backend.
- **Branch selection** — `RP.strategies.{weighted, random, avoidRecent, deterministic}`.

## Future work (kept open by design)

- Add scenarios by dropping a JSON in `scenarios/` (AI-authorable — spec §14) and
  running `gen_rp_audio.py`.
- Plug a real cross-encoder/LLM into `/api/classify` (embedding pre-filter → cross
  encoder → LLM fallback) behind the existing `remote` adapter.
- Integrate into `index.html` as a new level/screen once the engine is proven.
- Persist `history` (spec §17) to the existing progress/localStorage + Supabase path.
