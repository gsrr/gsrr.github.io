/* ==========================================================================
   Role Play UI — wires the engine + classifier + tts + stt to the DOM.
   Standalone; does not depend on the main app's index.html.
   ========================================================================== */
(function (global) {
  const RP = global.RP;
  let eng = null, graph = null, classifier = null;
  let awaitingUser = false;   // is it the user's turn to answer?

  const $ = (id) => document.getElementById(id);
  const convo = () => $("rpConvo");

  function bubble(who, text, cls) {
    const div = document.createElement("div");
    div.className = "rp-bubble " + (cls || "");
    div.innerHTML = '<span class="rp-who">' + who + "</span><span class='rp-text'>" + escapeHtml(text) + "</span>";
    convo().appendChild(div);
    convo().scrollTop = convo().scrollHeight;
    return div;
  }
  function escapeHtml(s) { return (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

  function setFeedback(html, kind) {
    const fb = $("rpFeedback");
    fb.className = "rp-fb " + (kind || "");
    fb.innerHTML = html;
  }

  function setStatus(t) { $("rpStatus").textContent = t; }

  /* ---------- Debug panel (spec §16) ---------- */
  function renderDebug(info) {
    if (!$("rpDebug").classList.contains("open")) return;
    const cls = info.classification;
    const rows = (cls.scores || [])
      .map((s) => {
        const on = s.intent === cls.intent && cls.result !== "OFF_TOPIC";
        return '<tr class="' + (on ? "sel" : "") + '"><td>' + s.intent + "</td><td>" + s.score.toFixed(2) + "</td></tr>";
      })
      .join("");
    const sel = info.selection;
    $("rpDebugBody").innerHTML =
      '<div class="dbg-row"><b>Current node</b><span>' + info.node + "</span></div>" +
      '<div class="dbg-row"><b>User</b><span>“' + escapeHtml(info.user) + "”</span></div>" +
      '<div class="dbg-grp">Candidate intents<table class="dbg-tbl"><tr><th>intent</th><th>score</th></tr>' + rows + "</table></div>" +
      '<div class="dbg-row"><b>Result</b><span class="pill ' + cls.result + '">' + cls.result + "</span></div>" +
      '<div class="dbg-row"><b>Selected intent</b><span>' + (cls.intent || "—") + "</span></div>" +
      '<div class="dbg-row"><b>Objective met</b><span>' + (cls.objectiveMet ? "yes" : "no") + "</span></div>" +
      '<div class="dbg-row"><b>Available next</b><span>' + (sel ? sel.pool.join(", ") : "—") + "</span></div>" +
      '<div class="dbg-row"><b>Selected next</b><span>' + (info.nextNode || "(stay)") + "</span></div>" +
      '<div class="dbg-row"><b>Reason</b><span>' + escapeHtml(cls.reason) + (sel ? " · " + sel.strategy : "") + "</span></div>";
  }

  /* ---------- engine callbacks ---------- */
  function onNode(node) {
    awaitingUser = false;
    RP.tts.cancel();
    setStatus("🔊 " + graph.npc + " is speaking…");
    disableInput(true);
    const b = bubble("🧑‍🍳 " + graph.npc, node.npc.text, "npc active");
    RP.tts.speak(node.npc.text, node.npc.gender, function () {
      b.classList.remove("active");
      if (!eng.done) {
        awaitingUser = true;
        disableInput(false);
        setStatus("🎭 Your turn — you are the " + graph.you);
        $("rpText").focus();
      }
    });
  }

  function onResult(info) {
    const cls = info.classification;
    renderDebug(info);
    if (cls.result === "PASS") {
      setFeedback("✅ <b>PASS</b> · " + (cls.intent || ""), "pass");
    } else if (cls.result === "PARTIAL") {
      const hint = (cls.route && cls.route.hint) || partialMsg(info) || "Close! Try to complete your answer.";
      setFeedback("🟡 <b>PARTIAL</b> — " + escapeHtml(hint), "partial");
      // NPC nudges but stays on the same node
      nudge(hint);
    } else {
      const msg = offTopicMsg(info) || "Let's stay on topic.";
      setFeedback("🔴 <b>OFF-TOPIC</b> — " + escapeHtml(msg), "off");
      nudge(msg);
    }
  }

  function partialMsg(info) {
    const n = eng.node(info.node);
    return n && n.fallback && n.fallback.partial && n.fallback.partial.message;
  }
  function offTopicMsg(info) {
    const n = eng.node(info.node);
    return n && n.fallback && n.fallback.off_topic && n.fallback.off_topic.message;
  }

  // NPC repeats/redirects without advancing (stay_on_current_node)
  function nudge(msg) {
    awaitingUser = false;
    disableInput(true);
    RP.tts.cancel();
    const b = bubble("🧑‍🍳 " + graph.npc, msg, "npc hint");
    RP.tts.speak(msg, graph.npc_gender, function () {
      b.classList.remove("active");
      if (!eng.done) { awaitingUser = true; disableInput(false); $("rpText").focus(); }
    });
  }

  function onEnd(summary) {
    awaitingUser = false;
    disableInput(true);
    setStatus("🎉 Conversation complete!");
    const pct = Math.round((summary.passes / Math.max(1, summary.turns)) * 100);
    setFeedback("🎉 <b>Done!</b> " + summary.passes + " good replies over " + summary.turns + " turns (" + pct + "%). Nodes visited: " + summary.visited.length, "pass");
  }

  /* ---------- input handling (text + voice) ---------- */
  function disableInput(dis) {
    $("rpText").disabled = dis;
    $("rpSend").disabled = dis;
    $("rpMic").disabled = dis || !RP.stt.available();
  }

  function submitText() {
    const t = $("rpText").value.trim();
    if (!t || !awaitingUser) return;
    bubble("🧑 " + graph.you, t, "user");
    $("rpText").value = "";
    awaitingUser = false;
    disableInput(true);
    setFeedback("🎯 Checking…", "");
    eng.submit(t);
  }

  let micOn = false;
  function toggleMic() {
    if (!awaitingUser) return;
    if (micOn) { // stop -> transcribe
      micOn = false;
      $("rpMic").textContent = "🎤 Speak";
      $("rpMic").classList.remove("rec");
      setFeedback("🎯 Transcribing…", "");
      const hint = ""; // spec: don't bias STT toward a single expected answer here
      RP.stt.stop(hint)
        .then((d) => {
          const t = (d.transcript || "").trim();
          if (!t) { setFeedback("🔇 Didn't catch that. Try again or type.", "off"); awaitingUser = true; disableInput(false); return; }
          bubble("🧑 " + graph.you, t + "  🎤", "user");
          awaitingUser = false; disableInput(true);
          setFeedback("🎯 Checking…", "");
          eng.submit(t);
        })
        .catch(() => { setFeedback("⚠️ Speech needs the server (/api/stt). Type your answer instead.", "off"); awaitingUser = true; disableInput(false); });
    } else {
      RP.stt.start().then(() => {
        micOn = true;
        $("rpMic").textContent = "⏹ Stop";
        $("rpMic").classList.add("rec");
        setFeedback("🎙️ Listening… speak, then press Stop.", "");
      }).catch(() => setFeedback("⚠️ No microphone available. Type your answer instead.", "off"));
    }
  }

  /* ---------- boot ---------- */
  function classifierFromUI() {
    const kind = $("rpClassifier").value;
    const Ctor = RP.classifiers[kind] || RP.classifiers.local;
    return new Ctor({});
  }

  function restart() {
    convo().innerHTML = "";
    setFeedback("", "");
    classifier = classifierFromUI();
    eng = new RP.Engine(graph, {
      classifier,
      strategy: $("rpStrategy").value,
      onNode, onResult, onEnd,
    });
    global.rpEngine = eng; // expose for console debugging
    eng.start();
  }

  let manifest = null;

  function loadScenario(url) {
    setStatus("Loading…");
    fetch(url, { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then((g) => {
        graph = g;
        $("rpTitle").textContent = g.title;
        $("rpRoleLine").innerHTML = "You are the <b>" + g.you + "</b> 🧑 · the computer is the <b>" + g.npc + "</b> 🧑‍🍳";
        restart();
      })
      .catch((e) => setStatus("⚠️ Could not load scenario (" + e.message + "). Run via a web server, not file://."));
  }

  // resolve which scenario id to open, from ?scenario= / ?lesson= / manifest default
  function pickScenarioId() {
    const p = new URLSearchParams(location.search);
    const wanted = p.get("scenario");
    if (wanted && scenarioById(wanted)) return wanted;
    const lesson = p.get("lesson");
    if (lesson && manifest && manifest.lesson_map && manifest.lesson_map[lesson]) {
      return manifest.lesson_map[lesson];
    }
    return (manifest && manifest.default) || "restaurant";
  }

  function scenarioById(id) {
    return manifest && (manifest.scenarios || []).find((s) => s.id === id);
  }

  function loadScenarioById(id) {
    const s = scenarioById(id);
    if (!s) { setStatus("⚠️ Unknown scenario: " + id); return; }
    const sel = $("rpScenario");
    if (sel) sel.value = id;
    loadScenario("scenarios/" + s.file);
  }

  function buildPicker() {
    const sel = $("rpScenario");
    if (!sel || !manifest) return;
    sel.innerHTML = (manifest.scenarios || [])
      .map((s) => '<option value="' + s.id + '">' + escapeHtml(s.title) + "</option>")
      .join("");
    sel.addEventListener("change", () => loadScenarioById(sel.value));
  }

  function boot() {
    // Load the catalog; fall back to restaurant-only if it isn't reachable.
    fetch("scenarios/index.json", { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then((m) => {
        manifest = m;
        buildPicker();
        loadScenarioById(pickScenarioId());
      })
      .catch(() => {
        manifest = { scenarios: [{ id: "restaurant", file: "restaurant.json", title: "At the Restaurant 🍔" }], default: "restaurant" };
        buildPicker();
        loadScenarioById("restaurant");
      });
  }

  function init() {
    if (!RP.stt.available()) { $("rpMic").disabled = true; $("rpMic").title = "Microphone/STT not available here — type instead"; }
    $("rpSend").addEventListener("click", submitText);
    $("rpText").addEventListener("keydown", (e) => { if (e.key === "Enter") submitText(); });
    $("rpMic").addEventListener("click", toggleMic);
    $("rpRestart").addEventListener("click", restart);
    $("rpClassifier").addEventListener("change", restart);
    $("rpStrategy").addEventListener("change", restart);
    $("rpDebugToggle").addEventListener("click", () => {
      $("rpDebug").classList.toggle("open");
      $("rpDebugToggle").textContent = $("rpDebug").classList.contains("open") ? "🐞 Hide debug" : "🐞 Debug";
    });
    boot();
  }

  document.addEventListener("DOMContentLoaded", init);
})(window);
