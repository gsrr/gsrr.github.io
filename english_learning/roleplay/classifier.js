/* ==========================================================================
   Semantic Classifier  —  pluggable interface + a local (offline) default.

   Contract (every classifier must implement this):

     classifier.classify(userText, node, opts) -> Promise<{
       result:       "PASS" | "PARTIAL" | "OFF_TOPIC",
       intent:       string | null,     // matched route intent (null if off-topic)
       route:        object | null,      // the matched route object (null if off-topic)
       objectiveMet: boolean,            // learning objective satisfied? (PASS => true)
       scores:       [{ intent, score }],// per-route scores, sorted desc (for Debug)
       reason:       string              // short human explanation (for Debug)
     }>

   The engine only ever calls .classify(); nothing else. So a future
   cross-encoder / embedding / LLM classifier just implements the same shape
   and gets registered in RP.classifiers — zero engine changes.

   IMPORTANT (spec §7): classification only compares the CURRENT node's routes.
   No global search, no vector database.
   ========================================================================== */
(function (global) {
  const RP = (global.RP = global.RP || {});
  RP.classifiers = RP.classifiers || {};

  /* ---------- shared text utilities (reused from the app's rpNorm/rpClose) ---------- */
  const STOP = new Set(
    ("a an the is are am was were be been to of and or but in on at it its i you he she we they " +
     "me him her them my your his our this that these those do does did will would can could should " +
     "have has had not no yes so if then there here as with for").split(" ")
  );

  function tokens(s) {
    return (s || "").toLowerCase().replace(/[^a-z0-9\s']/g, " ").split(/\s+/).filter(Boolean);
  }
  function contentWords(toks) {
    const c = toks.filter((w) => !STOP.has(w));
    return c.length ? c : toks; // if a phrase is all stop-words, keep them
  }
  // short-word fuzzy match: prefix match or edit-distance <= 1 (absorbs STT slips)
  function close(a, b) {
    if (a === b) return true;
    if (a.length >= 4 && b.length >= 3 && (a.indexOf(b) === 0 || b.indexOf(a) === 0)) return true;
    if (Math.abs(a.length - b.length) > 1) return false;
    let i = 0, j = 0, e = 0;
    while (i < a.length && j < b.length) {
      if (a[i] === b[j]) { i++; j++; }
      else { e++; if (e > 1) return false; if (a.length > b.length) i++; else if (b.length > a.length) j++; else { i++; j++; } }
    }
    return e + (a.length - i) + (b.length - j) <= 1;
  }
  function has(saidSet, saidArr, w) {
    return saidSet.has(w) || saidArr.some((s) => close(s, w));
  }
  // fraction of `target` content words that appear in the user's words
  function coverage(userArr, userSet, targetToks) {
    const words = contentWords(targetToks);
    if (!words.length) return 0;
    let hit = 0;
    words.forEach((w) => { if (has(userSet, userArr, w)) hit++; });
    return hit / words.length;
  }

  RP.text = { tokens, contentWords, close, coverage, STOP };

  /* ======================================================================
     LocalClassifier — lexical/semantic scoring, fully offline.

     For each route we take the MAX coverage over its example utterances
     (best-matching example), plus small bonuses from keyword hits and the
     route `meaning`. This is deliberately simple (spec §18.14: no
     over-engineering) but genuinely tolerant of paraphrase and STT noise,
     and it drops in behind the same interface a cross-encoder would use.
     ====================================================================== */
  function LocalClassifier(cfg) {
    cfg = cfg || {};
    this.PASS = cfg.pass != null ? cfg.pass : 0.6;      // >= PASS  -> valid answer
    this.FLOOR = cfg.floor != null ? cfg.floor : 0.28;  // <  FLOOR -> off-topic
    this.name = "local";
  }
  LocalClassifier.prototype.scoreRoute = function (route, userArr, userSet) {
    let best = 0;
    (route.examples || []).forEach((ex) => {
      best = Math.max(best, coverage(userArr, userSet, tokens(ex)));
    });
    // keyword bonus: any explicit keyword present is a strong signal
    let kw = 0;
    const kws = route.keywords || [];
    if (kws.length) {
      let hit = 0;
      kws.forEach((k) => { if (has(userSet, userArr, k.toLowerCase())) hit++; });
      kw = hit ? Math.min(0.35, 0.18 + 0.09 * hit) : 0;
    }
    // meaning gives a small tie-break nudge only
    const mean = coverage(userArr, userSet, tokens(route.meaning)) * 0.1;
    return Math.min(1, best + kw + mean);
  };
  LocalClassifier.prototype.objectiveMet = function (route, userArr, userSet, userText) {
    const obj = route.objective;
    if (!obj || !obj.markers || !obj.markers.length) return true; // no explicit objective => met
    const lc = (userText || "").toLowerCase();
    return obj.markers.some((m) => {
      const mm = m.toLowerCase();
      if (mm.indexOf(" ") >= 0) return lc.indexOf(mm) >= 0;       // phrase marker
      return has(userSet, userArr, mm);                           // single-word marker
    });
  };
  LocalClassifier.prototype.classify = function (userText, node) {
    const userArr = tokens(userText);
    const userSet = new Set(userArr);
    const routes = node.routes || [];

    const scored = routes.map((r) => ({ route: r, intent: r.intent, score: this.scoreRoute(r, userArr, userSet) }));
    scored.sort((a, b) => b.score - a.score);
    const scores = scored.map((s) => ({ intent: s.intent, score: +s.score.toFixed(3) }));

    const result = (res, top, objectiveMet, reason) =>
      Promise.resolve({
        result: res,
        intent: top ? top.intent : null,
        route: top ? top.route : null,
        objectiveMet: !!objectiveMet,
        scores,
        reason,
      });

    if (!scored.length) return result("OFF_TOPIC", null, false, "node has no routes");

    const top = scored[0];

    // (a) data-driven PARTIAL: a route explicitly flagged partial (related but incomplete)
    if (top.route.partial && top.score >= this.FLOOR) {
      return result("PARTIAL", top, false, "matched a 'partial' route (semantically related, objective not met)");
    }

    // (b) clear off-topic: best score below the floor
    if (top.score < this.FLOOR) {
      return result("OFF_TOPIC", null, false, "top score " + top.score.toFixed(2) + " < floor " + this.FLOOR);
    }

    // (c) confident enough to be a real answer
    if (top.score >= this.PASS) {
      const met = this.objectiveMet(top.route, userArr, userSet, userText);
      if (met) return result("PASS", top, true, "top score " + top.score.toFixed(2) + " >= pass " + this.PASS);
      return result("PARTIAL", top, false, "intent matched but learning objective markers absent");
    }

    // (d) middle band: semantically related but not a confident/complete answer
    return result("PARTIAL", top, false, "top score " + top.score.toFixed(2) + " in [" + this.FLOOR + "," + this.PASS + ")");
  };

  /* ======================================================================
     RemoteClassifier — adapter for a future server cross-encoder / LLM.
     OFF by default (no such endpoint exists yet). Documents the contract:

       POST <endpoint>  { text, routes:[{intent,meaning,examples}] }
         -> { scores:[{intent,score}] }   // 0..1 per route

     The adapter reuses LocalClassifier's PASS/PARTIAL/OFF_TOPIC decision
     logic on top of whatever scores the server returns, so swapping the
     scorer never changes the three-way result semantics.
     ====================================================================== */
  function RemoteClassifier(cfg) {
    cfg = cfg || {};
    this.endpoint = cfg.endpoint || "/api/classify";
    this.local = new LocalClassifier(cfg);           // fallback + decision logic
    this.name = "remote";
  }
  RemoteClassifier.prototype.classify = function (userText, node) {
    const self = this;
    const routes = node.routes || [];
    const body = JSON.stringify({
      text: userText,
      routes: routes.map((r) => ({ intent: r.intent, meaning: r.meaning, examples: r.examples || [] })),
    });
    return fetch(this.endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d) => {
        const byIntent = {};
        (d.scores || []).forEach((s) => { byIntent[s.intent] = s.score; });
        const scored = routes
          .map((r) => ({ route: r, intent: r.intent, score: byIntent[r.intent] || 0 }))
          .sort((a, b) => b.score - a.score);
        const scores = scored.map((s) => ({ intent: s.intent, score: +(+s.score).toFixed(3) }));
        // reuse the local decision bands on the remote scores
        const decide = self.local;
        const userArr = tokens(userText), userSet = new Set(userArr);
        const mk = (res, top, met, reason) =>
          ({ result: res, intent: top ? top.intent : null, route: top ? top.route : null, objectiveMet: !!met, scores, reason: "[remote] " + reason });
        if (!scored.length) return mk("OFF_TOPIC", null, false, "no routes");
        const top = scored[0];
        if (top.route.partial && top.score >= decide.FLOOR) return mk("PARTIAL", top, false, "partial route");
        if (top.score < decide.FLOOR) return mk("OFF_TOPIC", null, false, "below floor");
        if (top.score >= decide.PASS) {
          const met = decide.objectiveMet(top.route, userArr, userSet, userText);
          return mk(met ? "PASS" : "PARTIAL", top, met, met ? "pass" : "objective not met");
        }
        return mk("PARTIAL", top, false, "middle band");
      })
      .catch(() => self.local.classify(userText, node)); // graceful fallback to offline
  };

  RP.classifiers.local = LocalClassifier;
  RP.classifiers.remote = RemoteClassifier;
})(window);
