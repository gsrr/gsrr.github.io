// ---- Phase 3 ----
async function startPhase3(){
  updatePhaseIndicator();
  const res=await fetch(`/api/questions/${story}`);
  const data=await res.json();
  questions=data.questions.map(q=>({ img:q.phase1.img, answer:q.phase1.answer }));
  renderPhase3();
}

function renderPhase3(){
  if(current>=questions.length){
    let result=wrongCount===0?"pass":"fail";
    setPhaseResult(story,"phase3",result);
    updatePhaseIndicator();
    document.getElementById("phaseContent").innerHTML=`<div class="text-center py-5"><h2>Phase 3 結束！</h2></div>`;
    document.getElementById("statusBar").innerHTML="";
    speechSynthesis.cancel();
    setTimeout(()=>exitToList(),2000);
    return;
  }
  const q=questions[current]; renderStatusBar(q,false,true);

  // 選 3 個干擾詞（仍然送去比對，但不朗讀）
  const distractors = allWords.filter(w => w !== q.answer).sort(()=>0.5-Math.random()).slice(0,3);
  const words = [q.answer, ...distractors].sort(()=>0.5-Math.random());

  document.getElementById("phaseContent").innerHTML=`
    <div class="row">
      <!-- 左邊：操作區 -->
      <div class="col-md-4 d-flex flex-column align-items-center">
        <p id="phase3Status" class="mb-3">🔊 Listen carefully...</p>
        <!-- 喇叭 + 錄音 一列 -->
        <div class="d-flex justify-content-center gap-3 mb-3">
          <button id="repeatBtn" class="btn btn-outline-secondary btn-lg" title="Repeat Question">🔊</button>
          <button id="recordBtn" class="btn btn-primary btn-lg" title="Start Recording">🎤</button>
        </div>
        <!-- 錄音回放與確認 -->
        <div id="reviewControls" class="mt-3 d-none w-100 text-center">
          <audio id="playback" controls class="mb-2 w-100"></audio>
          <p id="pretestResult" class="fw-bold text-start"></p>
          <div class="d-flex justify-content-center gap-2">
            <button id="pretestBtn" class="btn btn-secondary" title="Pretest">🔍 Pretest</button>
            <button id="okBtn" class="btn btn-success" title="Submit">✅</button>
          </div>
        </div>
      </div>
      <!-- 右邊：圖片 -->
      <div class="col-md-8">
        <div class="image-frame mb-3"><img src="${q.img}" alt="Phase3"></div>
      </div>
    </div>
    <p id="resultText" class="mt-3 text-center"></p>
  `;

  // ---- 題目發音（只朗讀正確答案）----
  const u = new SpeechSynthesisUtterance(q.answer.replace(/_/g," "));
  u.lang = "en-US"; 
  u.rate = 0.9; 
  u.pitch = 1.1;
  u.onend = () => {
    document.getElementById("phase3Status").textContent = "Now, say the word for this picture!";
  };
  speechSynthesis.speak(u);

  // ---- 重聽題目 ----
  document.getElementById("repeatBtn").onclick=()=>{
    speechSynthesis.cancel();
    const u=new SpeechSynthesisUtterance(q.answer.replace(/_/g," "));
    u.lang="en-US"; u.rate=0.9; u.pitch=1.1;
    speechSynthesis.speak(u);
  };

  // ---- 錄音流程 ----
  const recordBtn=document.getElementById("recordBtn");
  const reviewDiv=document.getElementById("reviewControls");
  const playback=document.getElementById("playback");
  let mediaRecorder,audioChunks=[],audioBlob=null;

  recordBtn.onclick=async()=>{
    if(!mediaRecorder||mediaRecorder.state==="inactive"){
      const stream=await navigator.mediaDevices.getUserMedia({audio:true});
      mediaRecorder=new MediaRecorder(stream);
      audioChunks=[];
      mediaRecorder.ondataavailable=e=>audioChunks.push(e.data);
      mediaRecorder.onstop=()=>{
        audioBlob=new Blob(audioChunks,{type:"audio/webm"});
        playback.src=URL.createObjectURL(audioBlob);
        reviewDiv.classList.remove("d-none");
        document.getElementById("pretestResult").innerHTML="";
      };
      mediaRecorder.start();
      recordBtn.textContent="⏹";
    } else {
      mediaRecorder.stop();
      recordBtn.textContent="🎤";
    }
  };

  // ---- Pretest ----
  document.getElementById("pretestBtn").onclick=async()=>{
    if(!audioBlob) return;
    const formData=new FormData();
    formData.append("audio",audioBlob,"voice.webm");
    formData.append("words",JSON.stringify(words));
    const resp=await fetch(`/api/speech-match/${story}`,{method:"POST",body:formData});
    const result=await resp.json();

    const best = result.best_match || "未知";
    const scores = result.scores || {};

    let html = `<div>🔍 Pretest Result (best: <span style="color:green;font-weight:bold">${best}</span>):</div><ul>`;
    Object.entries(scores)
      .sort((a,b)=>a[1]-b[1])  // 小分數排前
      .forEach(([w, s])=>{
        if(s!==null){
          if(w===best){
            html += `<li style="color:green;font-weight:bold">${w}: ${s.toFixed(3)}</li>`;
          } else {
            html += `<li style="color:gray">${w}: ${s.toFixed(3)}</li>`;
          }
        } else {
          html += `<li style="color:gray">${w}: (no data)</li>`;
        }
      });
    html += `</ul>`;

    document.getElementById("pretestResult").innerHTML = html;
  };

  // ---- OK (Submit) ----
  document.getElementById("okBtn").onclick=async()=>{
    if(!audioBlob) return;
    const formData=new FormData();
    formData.append("audio",audioBlob,"voice.webm");
    formData.append("words",JSON.stringify(words));
    const resp=await fetch(`/api/speech-match/${story}`,{method:"POST",body:formData});
    const result=await resp.json();
    const best=result.best_match;
    const isCorrect=(best===q.answer);
    document.getElementById("resultText").textContent=isCorrect?`✅ Correct! (${best})`:`❌ Wrong! You said: ${best}`;
    if(isCorrect){correctCount++; playCorrectSound();} else {wrongCount++; playWrongSound();}
    current++; setTimeout(()=>renderPhase3(),2000);
  };
}


