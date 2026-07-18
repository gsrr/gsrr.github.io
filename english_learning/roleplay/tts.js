/* ==========================================================================
   TTS module (pluggable). Reuses the app's existing audio scheme:
     audio/index.json  maps  "<gender>|<text>"  ->  "<sha1>.mp3"
   Priority:  pre-generated mp3  ->  browser speechSynthesis  ->  timer only.
   Interface:  RP.tts.speak(text, gender, onend)  ->  triggers onend when done.
               RP.tts.cancel()
   Swap this object to change the voice backend; the engine only calls speak().
   ========================================================================== */
(function (global) {
  const RP = (global.RP = global.RP || {});

  let audioMap = {};
  let current = null;
  let maleVoice = null, femaleVoice = null;
  const synth = global.speechSynthesis;

  // load the shared clip index (best-effort; falls back to speechSynthesis)
  fetch("../audio/index.json", { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : {}))
    .then((m) => { audioMap = m || {}; })
    .catch(() => {});

  function pickVoices() {
    if (!synth) return;
    const vs = synth.getVoices() || [];
    const en = vs.filter((v) => /en[-_]/i.test(v.lang));
    const pool = en.length ? en : vs;
    femaleVoice = pool.find((v) => /female|jenny|aria|zira|samantha|woman/i.test(v.name)) || pool[0] || null;
    maleVoice = pool.find((v) => /male|guy|david|mark|man/i.test(v.name)) || pool[0] || null;
  }
  if (synth) { pickVoices(); synth.onvoiceschanged = pickVoices; }

  function clipFile(text, gender) { return audioMap[(gender || "female") + "|" + text]; }

  function cancel() {
    if (current) { try { current.pause(); } catch (e) {} current = null; }
    try { if (synth) synth.cancel(); } catch (e) {}
  }

  function speak(text, gender, onend) {
    cancel();
    let done = false;
    const fire = () => { if (done) return; done = true; if (onend) onend(); };
    const words = (text || "").split(/\s+/).filter(Boolean).length;
    const guard = setTimeout(fire, 2500 + words * 450); // safety net if onended never fires
    const cb = () => { clearTimeout(guard); fire(); };

    // 1) pre-generated mp3
    const f = clipFile(text, gender);
    if (f) {
      try {
        current = new Audio("../audio/" + f);
        current.onended = cb;
        current.onerror = null;
        current.play().catch(() => {}); // if autoplay blocked, guard timer advances
        return true;
      } catch (e) { current = null; }
    }
    // 2) browser speechSynthesis
    try {
      if (typeof SpeechSynthesisUtterance !== "undefined" && synth) {
        const u = new SpeechSynthesisUtterance(text);
        u.lang = "en-US"; u.rate = 0.9;
        const v = gender === "male" ? maleVoice : femaleVoice;
        if (v) u.voice = v;
        u.onend = cb;
        synth.speak(u);
        return true;
      }
    } catch (e) {}
    // 3) nothing available -> guard timer will advance
    return false;
  }

  RP.tts = { speak, cancel, clipFile, hasClip: (t, g) => !!clipFile(t, g) };
})(window);
