// ---- Phase 2 ----
async function startPhase2(){
  updatePhaseIndicator();
  const res=await fetch(`/api/questions/${story}`);
  const data=await res.json();
  questions=data.questions.map(q=>q.phase2);
  renderPhase2();
}

function renderPhase2(){
  if(current>=questions.length){
    let result=wrongCount===0?"pass":"fail";
    setPhaseResult(story,"phase2",result);
    updatePhaseIndicator();
    document.getElementById("phaseContent").innerHTML=`<div class="text-center py-5"><h2>Phase 2 結束！</h2></div>`;
    document.getElementById("statusBar").innerHTML="";
    setTimeout(()=>selectPhase(3),2000);
    return;
  }
  const q=questions[current]; renderStatusBar(q,true); locked=false;
  document.getElementById("phaseContent").innerHTML=`<div class="row" id="phase2Options"></div>`;
  speak(q.word.replace(/_/g," "));
  const optionsDiv=document.getElementById("phase2Options");
  q.options.forEach((opt,idx)=>{
    const col=document.createElement("div"); col.className="col-md-3 col-6 mb-4 text-center";
    const btn=document.createElement("button"); btn.className="btn p-0 border-0 bg-transparent";
    btn.onclick=()=>checkAnswerPhase2(opt,q.answer,btn);
    btn.innerHTML=`<div class="card shadow-sm"><div class="image-frame"><img src="${opt}" alt="Option ${idx+1}"></div></div>`;
    col.appendChild(btn); optionsDiv.appendChild(col);
  });
}

function checkAnswerPhase2(selected,answer,btn){
  if(locked) return; locked=true;
  if(selected===answer){
    correctCount++; playCorrectSound();
    btn.querySelector(".card").classList.add("correct");
    current++; setTimeout(()=>renderPhase2(),1000);
  } else {
    wrongCount++; btn.querySelector(".card").classList.add("wrong");
    const allCards=document.querySelectorAll("#phase2Options .card");
    allCards.forEach(card=>{
      const img=card.querySelector("img");
      if(img && img.src===answer) card.classList.add("correct");
    });
    playWrongSound(); current++; setTimeout(()=>renderPhase2(),1500);
  }
}

