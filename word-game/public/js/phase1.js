// ---- Phase 1 ----
async function startPhase1(){
  updatePhaseIndicator();
  const res=await fetch(`/api/questions/${story}`);
  const data=await res.json();
  questions=data.questions.map(q=>q.phase1);
  allWords=data.questions.map(q=>q.phase1.answer);
  renderPhase1();
}

function renderPhase1(){
  if(current>=questions.length){
    let result=wrongCount===0?"pass":"fail";
    setPhaseResult(story,"phase1",result);
    updatePhaseIndicator();
    document.getElementById("phaseContent").innerHTML=`<div class="text-center py-5"><h2>Phase 1 結束！</h2></div>`;
    document.getElementById("statusBar").innerHTML="";
    setTimeout(()=>selectPhase(2),2000);
    return;
  }
  const q=questions[current]; renderStatusBar(q,false);
  document.getElementById("phaseContent").innerHTML=`
    <div class="row">
      <div class="col-md-6" id="options"></div>
      <div class="col-md-6 text-center">
        <div class="card shadow-sm"><div class="card-body p-0">
          <div class="image-frame"><img id="questionImage" src="${q.img}" alt="Question"></div>
        </div></div>
      </div>
    </div>`;
  const optionsDiv=document.getElementById("options"); currentAnswerIndex=-1; locked=false;
  q.options.forEach((opt,idx)=>{
    const btn=document.createElement("button");
    btn.className="btn btn-outline-success option-btn mb-3 text-start";
    btn.textContent=`(${idx+1}) ${opt.replace(/_/g," ")}`;
    btn.onclick=()=>checkAnswerPhase1(opt,q.answer,idx,btn);
    optionsDiv.appendChild(btn);
    if(opt===q.answer) currentAnswerIndex=idx;
  });
  speakAllOptions(q);
}

function checkAnswerPhase1(selected,answer,idx,btn){
  if(locked) return; locked=true;
  const optionButtons=document.querySelectorAll(".option-btn");
  if(selected===answer){
    correctCount++; playCorrectSound(); current++; renderPhase1();
  } else {
    wrongCount++; btn.classList.add("wrong-answer");
    optionButtons[currentAnswerIndex].classList.add("correct-answer");
    playWrongSound(); current++;
    setTimeout(()=>renderPhase1(),1500);
  }
}

