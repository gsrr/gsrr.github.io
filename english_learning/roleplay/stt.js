/* ==========================================================================
   Speech-to-Text module (pluggable). Wraps MediaRecorder + POST /api/stt
   (faster-whisper on the server). Decoupled from the engine: it only turns
   microphone audio into a transcript string. Swap this object to change the
   STT backend (e.g. Web Speech API, a different server, a cloud provider).

   Interface:
     RP.stt.available()                      -> boolean (mic + recorder + not in-app browser)
     RP.stt.start()                          -> begins recording (throws if unavailable)
     RP.stt.stop(hintText)                   -> Promise<{transcript}>  (uploads + transcribes)
     RP.stt.cancel()
   ========================================================================== */
(function (global) {
  const RP = (global.RP = global.RP || {});

  let rec = null, chunks = [], stream = null, endpoint = "/api/stt";

  function available() {
    const ua = navigator.userAgent || "";
    if (/FBAN|FBAV|FB_IAB|Instagram/i.test(ua)) return false; // in-app browsers block mic
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && global.MediaRecorder);
  }

  function start() {
    if (!available()) return Promise.reject(new Error("no-mic"));
    return navigator.mediaDevices.getUserMedia({ audio: true }).then((s) => {
      stream = s; chunks = [];
      rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => { if (e.data && e.data.size > 0) chunks.push(e.data); };
      rec.start();
      return true;
    });
  }

  function cleanupStream() {
    if (stream) { try { stream.getTracks().forEach((t) => t.stop()); } catch (e) {} stream = null; }
  }

  // Stop recording, upload the blob, resolve with the transcript.
  function stop(hintText) {
    return new Promise((resolve, reject) => {
      if (!rec) return reject(new Error("not-recording"));
      rec.onstop = () => {
        const blob = new Blob(chunks, { type: (rec && rec.mimeType) || "audio/webm" });
        cleanupStream();
        fetch(endpoint + "?text=" + encodeURIComponent(hintText || ""), { method: "POST", body: blob })
          .then((r) => (r.ok ? r.json() : Promise.reject(new Error("stt-http"))))
          .then((d) => resolve({ transcript: (d && d.transcript) || "" }))
          .catch(reject);
      };
      try { if (rec.state === "recording") rec.stop(); } catch (e) { reject(e); }
    });
  }

  function cancel() {
    try { if (rec && rec.state === "recording") rec.stop(); } catch (e) {}
    cleanupStream();
    rec = null; chunks = [];
  }

  function recording() { return !!(rec && rec.state === "recording"); }

  RP.stt = { available, start, stop, cancel, recording, setEndpoint: (e) => { endpoint = e; } };
})(window);
