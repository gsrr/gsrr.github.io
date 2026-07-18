/* ==========================================================================
   Role Play — automated test suite (spec §10).
   Environment-agnostic: needs RP.classifiers + RP.Engine on the global, and a
   loaded graph object. Exposes RP.runTests(graph) -> Promise<{total,passed,cases[]}>.
   Runs in the browser (tests.html) and under Node (test.node.js shim).
   ========================================================================== */
(function (global) {
  const RP = (global.RP = global.RP || {});

  function makeEngine(graph, strategy, rng, cbs) {
    const eng = new RP.Engine(graph, Object.assign({
      classifier: new RP.classifiers.local({}),
      strategy: strategy || "deterministic",
      rng: rng || (() => 0),
    }, cbs || {}));
    eng.start();
    return eng;
  }

  const localClassifier = () => new RP.classifiers.local({});
  const nodeOf = (graph, id) => graph.nodes.find((n) => n.id === id);
  // classify one utterance against a specific node (returns a Promise)
  const classifyAt = (graph, nodeId, text) => localClassifier().classify(text, nodeOf(graph, nodeId));

  async function runTests(graph) {
    const cases = [];
    const assert = (cond, msg) => { if (!cond) throw new Error(msg || "assertion failed"); };
    async function T(name, fn) {
      try { const detail = await fn(); cases.push({ name, ok: true, detail: detail || "" }); }
      catch (e) { cases.push({ name, ok: false, detail: e && e.message ? e.message : String(e) }); }
    }

    /* 0. scenario integrity */
    await T("graph integrity — all next_nodes resolve & start exists", () => {
      const ids = new Set(graph.nodes.map((n) => n.id));
      assert(ids.has(graph.start), "start node missing: " + graph.start);
      let edges = 0;
      graph.nodes.forEach((n) =>
        (n.routes || []).forEach((r) =>
          (r.next_nodes || []).forEach((c) => { edges++; assert(ids.has(c.id), "dangling edge -> " + c.id + " (from " + n.id + ")"); })
        )
      );
      const ends = graph.nodes.filter((n) => n.end || !(n.routes && n.routes.length));
      assert(ends.length >= 1, "no terminal node");
      return graph.nodes.length + " nodes, " + edges + " edges, " + ends.length + " terminal";
    });

    /* 1. normal answer -> PASS */
    await T("normal answer 'I'd like a hamburger.' -> PASS/order_food", async () => {
      const r = await classifyAt(graph, "node_seated", "I'd like a hamburger.");
      assert(r.result === "PASS", "got " + r.result);
      assert(r.intent === "order_food", "intent=" + r.intent);
      assert(r.objectiveMet === true, "objective should be met");
      return "score=" + r.scores[0].score;
    });

    /* 2. different phrasing, same meaning -> still PASS/order_food */
    await T("paraphrases all map to order_food -> PASS", async () => {
      for (const u of ["Can I have the pasta?", "I'll take a pizza.", "A cheeseburger, please.", "Can I get a salad?"]) {
        const r = await classifyAt(graph, "node_seated", u);
        assert(r.result === "PASS", u + " -> " + r.result);
        assert(r.intent === "order_food", u + " -> " + r.intent);
      }
      return "4 paraphrases OK";
    });

    /* 3. partial answer (semantically related, objective not met) -> PARTIAL */
    await T("'I'm thirsty' at drink node -> PARTIAL (not off-topic, not pass)", async () => {
      const r = await classifyAt(graph, "node_drink", "I'm thirsty.");
      assert(r.result === "PARTIAL", "got " + r.result);
      assert(r.objectiveMet === false, "objective must be false");
      return r.reason;
    });

    /* 3b. objective gate: valid intent but no target pattern -> PARTIAL */
    await T("bare 'hamburger' (no I'd like/please) -> PARTIAL via objective gate", async () => {
      const r = await classifyAt(graph, "node_seated", "hamburger");
      assert(r.result === "PARTIAL", "got " + r.result + " score " + r.scores[0].score);
      assert(r.intent === "order_food", "intent=" + r.intent);
      return r.reason;
    });

    /* 4. completely off-topic -> OFF_TOPIC */
    await T("'My dog is very cute' at drink node -> OFF_TOPIC", async () => {
      const r = await classifyAt(graph, "node_drink", "My dog is very cute.");
      assert(r.result === "OFF_TOPIC", "got " + r.result);
      assert(r.intent === null, "intent should be null");
      return "top=" + r.scores[0].score;
    });

    /* 5. ambiguous answer -> picks the higher-scoring intent */
    await T("ambiguous 'What do you recommend?' -> ask_recommendation beats order_food", async () => {
      const r = await classifyAt(graph, "node_seated", "What do you recommend?");
      assert(r.intent === "ask_recommendation", "intent=" + r.intent);
      assert(r.scores[0].score > r.scores[1].score, "top not strictly higher");
      return r.scores.map((s) => s.intent + ":" + s.score).join("  ");
    });

    /* 6. NPC weighted random branch — distribution roughly follows weights */
    await T("weighted branch selection follows weights (order_food 40/20/20/20)", () => {
      let i = 0; const seq = [0.05, 0.3, 0.5, 0.7, 0.9, 0.1, 0.45, 0.65, 0.85, 0.25];
      const rng = () => seq[i++ % seq.length];
      const route = nodeOf(graph, "node_seated").routes.find((r) => r.intent === "order_food");
      const eng = makeEngine(graph, "weighted", rng);
      const counts = {};
      for (let k = 0; k < 400; k++) { const sel = eng._selectNext(route); counts[sel.id] = (counts[sel.id] || 0) + 1; }
      const top = Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0];
      assert(top === "node_fries", "most frequent was " + top + " counts=" + JSON.stringify(counts));
      assert(Object.keys(counts).length === 4, "should reach all 4 branches");
      return JSON.stringify(counts);
    });

    /* 7. event branch reachable & typed */
    await T("event branches (sold_out / combo / clarify) reachable from order_food", () => {
      const route = nodeOf(graph, "node_seated").routes.find((r) => r.intent === "order_food");
      const ids = route.next_nodes.map((c) => c.id);
      ["node_sold_out", "node_combo", "node_clarify"].forEach((ev) => {
        assert(ids.indexOf(ev) >= 0, "missing event branch " + ev);
        const n = nodeOf(graph, ev);
        assert(n.type === "event" || n.type === "clarification", ev + " type=" + n.type);
      });
      return "3 event branches present & typed";
    });

    /* 8. graph loop — node_more_time can loop to itself */
    await T("graph loop — 'still_not_ready' keeps you on node_more_time", async () => {
      const eng = makeEngine(graph, "deterministic");
      eng._enter("node_more_time");
      const info = await eng.submit("Not yet, a little more time please.");
      assert(info.result === "PASS", "loop turn result " + info.result);
      assert(info.nextNode === "node_more_time", "should loop to self, got " + info.nextNode);
      assert(eng.current.id === "node_more_time", "not on node_more_time");
      return "looped OK";
    });

    /* 9. retry — OFF_TOPIC stays on the same node */
    await T("retry — off-topic answer does not advance the node", async () => {
      const eng = makeEngine(graph, "deterministic");
      const before = eng.current.id; // node_welcome
      const info = await eng.submit("The moon is bright tonight.");
      assert(info.result === "OFF_TOPIC", "expected OFF_TOPIC got " + info.result);
      assert(info.stayed === true, "should have stayed");
      assert(eng.current.id === before, "node changed on off-topic");
      return "stayed on " + before;
    });

    /* 10. conversation completion — scripted happy path reaches the end node */
    await T("full happy path reaches the terminal node & fires onEnd", async () => {
      let ended = null;
      const eng = makeEngine(graph, "deterministic", () => 0, { onEnd: (s) => { ended = s; } });
      const say = [
        "Two, please.",                 // welcome -> seated
        "I'd like a hamburger.",        // seated -> (det) node_fries
        "Yes, please.",                 // fries -> drink
        "Can I have a Coke?",           // drink -> (det) node_drink_ok
        "No, that's all.",              // drink_ok -> dessert_offer
        "No, thanks.",                  // dessert_offer -> anything_else
        "Can I have the bill, please?", // anything_else -> bill
        "Can I pay by card?",           // bill -> pay_card
        "Thank you!",                   // pay_card -> goodbye (end)
      ];
      for (const u of say) await eng.submit(u);
      assert(eng.done === true, "engine not done; stuck at " + (eng.current && eng.current.id));
      assert(ended, "onEnd not fired");
      assert(ended.endNode === "node_goodbye", "end node = " + ended.endNode);
      assert(ended.passes >= 8, "expected >=8 passes, got " + ended.passes);
      return "reached " + ended.endNode + " in " + ended.turns + " turns, " + ended.passes + " passes";
    });

    const passed = cases.filter((c) => c.ok).length;
    return { total: cases.length, passed, cases };
  }

  RP.runTests = runTests;
})(typeof window !== "undefined" ? window : globalThis);
