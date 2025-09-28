let phase = 1;
let questions = [];
let current = 0, correctCount = 0, wrongCount = 0;
let currentAnswerIndex = -1, locked = false;
let allWords = [];

const synth = new Tone.Synth().toDestination();

function playCorrectSound(){ 
  synth.triggerAttackRelease("C6","8n"); 
}
function playWrongSound(){ 
  synth.triggerAttackRelease("C3","8n"); 
  setTimeout(()=>synth.triggerAttackRelease("C2","8n"),150); 
}

function speak(text){
  speechSynthesis.cancel(); // 確保不疊音
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-US"; 
  u.rate = 0.9; 
  u.pitch = 1.1;
  speechSynthesis.speak(u);
}

function speakAllOptions(q){
  speechSynthesis.cancel();
  q.options.forEach((opt,idx)=>{
    const u = new SpeechSynthesisUtterance(opt.replace(/_/g," "));
    u.lang = "en-US"; 
    u.rate = 0.9; 
    u.pitch = 1.1;
    setTimeout(()=>speechSynthesis.speak(u), idx*1200);
  });
}

function getStoryResults(){
  return JSON.parse(localStorage.getItem("storyPhases")||"{}");
}

function setPhaseResult(story, phaseKey, status){
  const data = getStoryResults();
  if(!data[story]) data[story]={phase1:"notest",phase2:"notest",phase3:"notest"};
  data[story][phaseKey]=status;
  localStorage.setItem("storyPhases", JSON.stringify(data));
}

function exitToList(){ 
  window.location.href="index.html"; 
}

function updatePhaseIndicator(){
  const results = getStoryResults()[story] || {phase1:"notest",phase2:"notest",phase3:"notest"};
  ["phase1","phase2","phase3"].forEach(p=>{
    const el=document.getElementById(p);
    el.className="phase-light"; // reset
    switch(results[p]){
      case "pass": el.classList.add("light-pass"); break;
      case "fail": el.classList.add("light-fail"); break;
      case "done": el.classList.add("light-done"); break;
      default: el.classList.add("light-default");
    }

    // 🔵 高亮目前的 phase
    if(phase === parseInt(p.replace("phase",""))){
      el.style.border="3px solid #3b82f6";   // 藍色粗框
      el.style.transform="scale(1.3)";       // 放大
    } else {
      el.style.border="1px solid #ccc";      // 恢復預設細框
      el.style.transform="scale(1)";
    }
  });
}

function selectPhase(p){
  // 顯示 Processing 畫面
  document.getElementById("phaseContent").innerHTML = `
    <div class="text-center py-5">
      <div class="spinner-border text-primary mb-3" role="status"></div>
      <h4>Processing…</h4>
    </div>
  `;

  // 延遲停止語音，避免切換時 UI 停頓
  setTimeout(()=>speechSynthesis.cancel(), 10);

  // 用 requestAnimationFrame 確保 UI 更新後再進入新 phase
  requestAnimationFrame(()=>{
    phase=p; 
    current=0; 
    correctCount=0; 
    wrongCount=0; 
    locked=false;

    if(phase===1) startPhase1();
    else if(phase===2) startPhase2();
    else startPhase3();
  });
}

function renderStatusBar(q,isPhase2=false,isPhase3=false){
  const progressColor="bg-success";
  document.getElementById("statusBar").innerHTML=`
    <div class="progress mb-2 mx-auto" style="height:20px; max-width:600px;">
      <div class="progress-bar ${progressColor}" role="progressbar" style="width:${((current+1)/questions.length)*100}%"></div>
    </div>
    ${isPhase2?`<p class="fs-4 fw-bold mb-1">${q.word.replace(/_/g," ")}</p>`:""}
    ${isPhase3?`<p class="fs-4 fw-bold mb-1">Say the word for this picture</p>`:""}
    <div class="d-flex justify-content-center align-items-center">
      <span class="me-2">✅ ${correctCount} / ❌ ${wrongCount}</span>
    </div>`;
}

