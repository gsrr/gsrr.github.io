/* ==========================================================================
   Conversation Graph Engine  (RP.Engine)

   Core loop (spec §1):
     NPC node -> user answer -> classifier -> route -> pick next node -> repeat

   The engine is UI-agnostic and AI-provider-agnostic. It is given a graph, a
   classifier (any object with .classify), and callbacks. It owns: current
   node, branch selection, history, visited set, loop / max_turns guard, and
   the completion state. It does NOT touch the DOM, audio, or the mic.

   Usage:
     const eng = new RP.Engine(graph, {
       classifier,                    // required: {classify(text,node)->Promise<result>}
       strategy: "weighted",          // branch selection strategy name
       onNode:  (node) => {},         // an NPC node became current (play its audio here)
       onResult:(info) => {},         // a user turn was classified (info = {classification, entry, ...})
       onEnd:   (summary) => {},      // conversation finished
       rng: Math.random,              // injectable for deterministic tests
     });
     eng.start();
     await eng.submit("I'd like a hamburger.");   // text OR STT transcript
   ========================================================================== */
(function (global) {
  const RP = (global.RP = global.RP || {});

  /* ---------- branch-selection strategies (spec §13) ---------- */
  const strategies = {
    // weighted random over next_nodes[].weight  (MVP default)
    weighted(candidates, ctx) {
      const total = candidates.reduce((s, c) => s + (c.weight || 1), 0);
      let r = (ctx.rng() * total);
      for (const c of candidates) { r -= (c.weight || 1); if (r <= 0) return c; }
      return candidates[candidates.length - 1];
    },
    random(candidates, ctx) {
      return candidates[Math.floor(ctx.rng() * candidates.length)];
    },
    // deterministic: always the first candidate (used by the test suite)
    deterministic(candidates) {
      return candidates[0];
    },
    // prefer a node not visited recently; fall back to weighted
    avoidRecent(candidates, ctx) {
      const fresh = candidates.filter((c) => !ctx.visited.has(c.id));
      return strategies.weighted(fresh.length ? fresh : candidates, ctx);
    },
  };
  RP.strategies = strategies;

  function Engine(graph, opts) {
    opts = opts || {};
    this.graph = graph;
    this.nodesById = {};
    (graph.nodes || []).forEach((n) => { this.nodesById[n.id] = n; });
    this.classifier = opts.classifier;
    this.strategyName = opts.strategy || "weighted";
    this.rng = opts.rng || Math.random;
    this.maxTurns = opts.maxTurns || graph.max_turns || 40;
    this.cb = {
      onNode: opts.onNode || function () {},
      onResult: opts.onResult || function () {},
      onEnd: opts.onEnd || function () {},
    };
    this.reset();
  }

  Engine.prototype.reset = function () {
    this.current = null;
    this.turns = 0;            // counts user turns
    this.visited = new Set();
    this.history = [];         // spec §17 conversation log
    this.done = false;
  };

  Engine.prototype.node = function (id) { return this.nodesById[id]; };

  Engine.prototype.start = function () {
    this.reset();
    this._enter(this.graph.start);
    return this.current;
  };

  Engine.prototype._enter = function (id) {
    const node = this.nodesById[id];
    if (!node) { console.warn("RP.Engine: missing node", id); this._finish(); return; }
    this.current = node;
    this.visited.add(id);
    this.cb.onNode(node);
    if (node.end || !(node.routes && node.routes.length)) {
      // terminal node: play its line, then finish
      this._finish();
    }
  };

  Engine.prototype._finish = function () {
    if (this.done) return;
    this.done = true;
    const passes = this.history.filter((h) => h.result === "PASS").length;
    this.cb.onEnd({
      turns: this.turns,
      passes: passes,
      visited: Array.from(this.visited),
      history: this.history.slice(),
      endNode: this.current ? this.current.id : null,
    });
  };

  // pick the next node id from a matched route's next_nodes
  Engine.prototype._selectNext = function (route) {
    const cands = (route.next_nodes || []).filter((c) => this.nodesById[c.id]);
    if (!cands.length) return null;
    const strat = strategies[this.strategyName] || strategies.weighted;
    const ctx = { rng: this.rng, visited: this.visited };
    const chosen = strat(cands, ctx);
    return { id: chosen.id, weight: chosen.weight, pool: cands.map((c) => c.id), strategy: this.strategyName };
  };

  // Handle one user turn. Returns a Promise of the turn info.
  Engine.prototype.submit = function (userText) {
    if (this.done || !this.current) return Promise.resolve(null);
    const node = this.current;
    this.turns++;
    const self = this;

    return Promise.resolve(this.classifier.classify(userText, node)).then(function (cls) {
      const info = { node: node.id, user: userText, classification: cls, selection: null, nextNode: null, result: cls.result, stayed: true };

      if (cls.result === "PASS") {
        const sel = self._selectNext(cls.route);
        info.selection = sel;
        info.nextNode = sel ? sel.id : null;
        info.stayed = !sel;
      }

      // spec §17 history entry
      const entry = {
        node: node.id,
        npc: node.npc ? node.npc.text : "",
        user: userText,
        intent: cls.intent,
        score: (cls.scores && cls.scores[0] && cls.scores[0].score) || 0,
        result: cls.result,
        objectiveMet: cls.objectiveMet,
        next_node: info.nextNode,
      };
      self.history.push(entry);
      info.entry = entry;

      self.cb.onResult(info);

      // loop / runaway guard (spec §12)
      if (self.turns >= self.maxTurns && cls.result !== "PASS") {
        info.maxTurnsReached = true;
      }

      // advance only on PASS with a valid next node; otherwise stay on current
      if (cls.result === "PASS" && info.nextNode) {
        self._enter(info.nextNode);
      }
      return info;
    });
  };

  RP.Engine = Engine;
})(window);
