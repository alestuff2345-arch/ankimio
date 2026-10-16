const $=s=>document.querySelector(s);let selected,session,index,exam,answers,examPool,reviewDeck,reviewQueue,reviewKnown;
function esc(s){const e=document.createElement('div');e.textContent=s;return e.innerHTML}
function plain(s){const d=new DOMParser().parseFromString(s,'text/html');d.querySelectorAll('script,style').forEach(x=>x.remove());return d.body.textContent||''}
async function api(url,options){const r=await fetch(url,options);const d=await r.json();if(!r.ok)throw Error(d.error||'No se pudo completar la operación.');return d}
function notice(s){$('#notice').textContent=s}
async function load(){try{const decks=await api('/api/decks');$('#total').textContent=`(${decks.length})`;$('#decks').innerHTML=decks.length?decks.map((d,i)=>`<article><div class="deck-icon">${['⚓','☠','☀','♜'][i%4]}</div><h3>${esc(d.name)}</h3><p>${d.count} tarjetas · Sin límite diario</p><div class="deck-actions"><button data-id="${d.id}" data-action="review">Repasar ↗</button><button data-id="${d.id}" data-action="exam">Simulacro</button><button data-id="${d.id}" data-action="add" aria-label="Añadir tarjeta">＋</button></div></article>`).join(''):'<div class="empty"><span>✧</span><h3>¡Tu aventura empieza aquí, nakama!</h3><p>Tu primer tesoro: crea un mazo o importa tus tarjetas de Anki.</p></div>'}catch(e){notice(e.message)}}
$('#newform').onsubmit=async e=>{e.preventDefault();try{await api('/api/decks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});$('#new').close();e.target.reset();load()}catch(e){notice(e.message)}};
let savingCard=false;
$('#addform').addEventListener('keydown',e=>{
    if(e.ctrlKey && e.key==='Enter' && !e.isComposing){
        e.preventDefault();
        if(!e.repeat && !savingCard) e.currentTarget.requestSubmit();
    }
});
$('#addform').onsubmit=async e=>{
    e.preventDefault();
    if(savingCard) return;
    const form=e.currentTarget, button=form.querySelector('button[type="submit"]');
    const front=form.elements.front.value.trim(), back=form.elements.back.value.trim();
    if(!front || !back){
        const field=!front?form.elements.front:form.elements.back;
        field.setCustomValidity('Completa este campo.');field.reportValidity();return;
    }
    savingCard=true;button.disabled=true;
    $('#cardstatus').textContent='Guardando…';
    try{
        await api(`/api/decks/${selected}/cards`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({front,back})});
        form.reset();
        $('#cardstatus').textContent='Tarjeta guardada. Puedes añadir otra.';
        form.elements.front.focus();
        await load();
    }catch(error){$('#cardstatus').textContent=error.message;}
    finally{savingCard=false;button.disabled=false;}
};
$('#addform').addEventListener('input',e=>{
    if(e.target.matches('textarea')) e.target.setCustomValidity('');
    $('#cardstatus').textContent='';
});
$('#add').addEventListener('close',()=>{$('#cardstatus').textContent='';});
$('#file').onchange=async e=>{if(!e.target.files[0])return;const form=new FormData();form.append('file',e.target.files[0]);notice('Importando…');try{const r=await api('/api/import',{method:'POST',body:form});notice(`${r.count} tarjetas importadas en ${r.decks} mazos. ${r.warning}`);load()}catch(e){notice(e.message)}e.target.value=''};
function shuffled(items){
    const result=[...items];
    for(let i=result.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[result[i],result[j]]=[result[j],result[i]];}
    return result;
}
function answerText(card){return plain(card.back).trim();}
function answerKey(text){return text.replace(/\s+/g,' ').trim().toLocaleLowerCase('es');}
function choicesFor(card){
    const correct=answerText(card), key=answerKey(correct);
    const distractors=shuffled(examPool.filter(text=>answerKey(text)!==key)).slice(0,3);
    return shuffled([correct,...distractors]);
}
$('#decks').onclick=async e=>{
    const b=e.target.closest('button');if(!b)return;
    selected=b.dataset.id;if(b.dataset.action==='add')return $('#add').showModal();
    try{
        session=await api(`/api/decks/${selected}/cards`);
        if(!session.length)return notice('Añade tarjetas a este mazo para empezar.');
        exam=b.dataset.action==='exam';index=0;answers=[];
        if(exam){
            session=session.filter(c=>plain(c.front).trim() && answerText(c));
            const unique=new Map();
            session.forEach(c=>unique.set(answerKey(answerText(c)),answerText(c)));
            examPool=[...unique.values()];
            if(examPool.length<2)return notice('Para un simulacro con alternativas necesitas al menos dos respuestas distintas en el mazo.');
            session=shuffled(session);
        }
        $('#library').hidden=true;$('#study').hidden=false;notice('');
        if(exam){
            $('#study').innerHTML=`<button onclick="leave()">← Mis mazos</button><h1>Tu prueba en el Grand Line.</h1><p>Marca una alternativa por pregunta. Recibirás tu nota y las claves al terminar, sin límite de tiempo.</p><p class="hint">Hasta 4 alternativas, usando respuestas de otras tarjetas del mazo. Revisa que tus preguntas tengan una única respuesta válida.</p><form id="config"><label>Número de preguntas<input id="amount" type="number" min="1" max="${session.length}" value="${Math.min(20,session.length)}" required></label><button class="primary">Comenzar simulacro</button></form>`;
            $('#config').onsubmit=e=>{
                e.preventDefault();
                session=session.slice(0,Number($('#amount').value)).map(c=>({...c,choices:choicesFor(c)}));show();
            };
        }else startReview(session);
    }catch(e){notice(e.message)}
};
function leave(){$('#study').hidden=true;$('#library').hidden=false;notice('');load()}
function startReview(cards){
    reviewDeck=[...cards];reviewQueue=shuffled(cards);reviewKnown=0;showReview();
}
function showReview(){
    if(!reviewQueue.length){
        $('#study').innerHTML=`<div class="empty"><span>✳</span><h1>¡Ya te las sabes todas!</h1><p>Has marcado las ${reviewDeck.length} tarjetas como Bien o Fácil. Puedes repasar el mazo completo otra vez, sin esperar.</p><button class="primary" id="again">Repasar todo de nuevo</button> <button onclick="leave()">Mis mazos</button></div>`;
        $('#again').onclick=()=>startReview(reviewDeck);
        return;
    }
    const c=reviewQueue[0];
    $('#study').innerHTML=`<button onclick="leave()">← Mis mazos</button><div class="section-title"><h2>Repaso libre</h2><span>${reviewKnown} / ${reviewDeck.length} aprendidas · ${reviewQueue.length} pendientes</span></div><progress value="${reviewKnown}" max="${reviewDeck.length}"></progress><div class="flashcard"><span class="eyebrow">PIENSA EN LA RESPUESTA</span><h2>${esc(plain(c.front))}</h2><div id="answer" hidden><hr><p>${esc(plain(c.back))}</p></div></div><div class="actions"><button class="primary" id="reveal" aria-keyshortcuts="Space">Mostrar respuesta</button><div id="ratings" class="rating-actions" hidden><button data-rating="again" aria-keyshortcuts="1" class="rating-again"><span>1 · Otra vez</span><small>No me la sé</small></button><button data-rating="hard" aria-keyshortcuts="2" class="rating-hard"><span>2 · Difícil</span><small>Seguir practicando</small></button><button data-rating="good" aria-keyshortcuts="3 Space" class="rating-good"><span>3 · Bien</span><small>Me la sé</small></button><button data-rating="easy" aria-keyshortcuts="4" class="rating-easy"><span>4 · Fácil</span><small>Dominada</small></button></div></div><p class="hint" id="reviewhint">Espacio: mostrar respuesta. Las tarjetas pendientes se repiten sin esperas.</p>`;
    $('#reveal').onclick=()=>{
        $('#answer').hidden=false;$('#ratings').hidden=false;$('#reveal').hidden=true;
        $('#reviewhint').textContent='1: Otra vez · 2: Difícil · 3: Bien · 4: Fácil · Espacio: Bien.';
    };
    $('#ratings').onclick=e=>{
        const button=e.target.closest('button[data-rating]');if(!button || $('#answer').hidden)return;
        const card=reviewQueue.shift(), rating=button.dataset.rating;
        if(rating==='again' || rating==='hard'){
            // Repeat within this session: sooner for Again, later for Hard.
            reviewQueue.splice(Math.min(rating==='again'?1:3,reviewQueue.length),0,card);
        }else reviewKnown++;
        showReview();
    };
}
function show(){
    const c=session[index];
    $('#study').innerHTML=`<button onclick="leave()">← Mis mazos</button><div class="section-title"><h2>Simulacro</h2><span>${index+1} / ${session.length}</span></div><progress value="${index}" max="${session.length}"></progress><div class="flashcard"><span class="eyebrow">MARCA UNA ALTERNATIVA</span><h2>${esc(plain(c.front))}</h2><fieldset class="choices"><legend>Elige tu respuesta</legend>${c.choices.map((text,i)=>`<label class="choice"><input type="radio" name="choice" value="${i}"><span class="choice-letter">${'ABCD'[i]}</span><span>${esc(text)}</span></label>`).join('')}</fieldset></div><div class="actions"><button class="primary" id="next" disabled>${index===session.length-1?'Terminar y ver resultados':'Siguiente pregunta →'}</button></div>`;
    document.querySelectorAll('input[name="choice"]').forEach(r=>r.onchange=()=>{$('#next').disabled=false;});
    $('#next').onclick=()=>{
        const marked=$('input[name="choice"]:checked');if(!marked)return;
        answers.push(Number(marked.value));index++;
        if(index<session.length)show();else results();
    };
}
document.addEventListener('keydown',e=>{
    const space=e.code==='Space' || e.key===' ';
    if(!space && !['1','2','3','4'].includes(e.key)) return;
    if(e.ctrlKey || e.altKey || e.metaKey || e.shiftKey || e.isComposing) return;
    if(exam || $('#study').hidden || document.querySelector('dialog[open]')) return;
    const target=e.target;
    if(target instanceof Element && (target.closest('input,textarea,select,a,[role="textbox"]') || target.isContentEditable)) return;
    const reveal=$('#reveal'), ratings=$('#ratings');
    if(!reveal || !ratings)return;
    const revealed=!ratings.hidden;
    let action;
    if(space) action=revealed ? $('[data-rating="good"]') : reveal;
    else if(revealed) action=ratings.querySelector(`[data-rating="${['again','hard','good','easy'][Number(e.key)-1]}"]`);
    if(!action || action.disabled)return;
    const focusedButton=target instanceof Element ? target.closest('button') : null;
    if(space && focusedButton && focusedButton!==reveal){
        // Preserve native Space activation on a focused difficulty button.
        if(focusedButton.closest('#ratings')){
            e.preventDefault();if(!e.repeat)focusedButton.click();return;
        }
        return;
    }
    e.preventDefault();if(!e.repeat)action.click();
});
function results(){
    const correct=session.filter((c,i)=>answerKey(c.choices[answers[i]])===answerKey(answerText(c))).length;
    $('#study').innerHTML=`<button onclick="leave()">← Mis mazos</button><h1>El botín de tu aventura.</h1><p>Simulacro corregido. Estas son tus respuestas y las claves correctas.</p><h2 id="score">${correct} / ${session.length} correctas · ${Math.round(correct/session.length*100)}%</h2>${session.map((c,i)=>{
        const marked=answers[i],right=c.choices.findIndex(text=>answerKey(text)===answerKey(answerText(c))),ok=marked===right;
        return `<article class="result ${ok?'result-correct':'result-wrong'}"><span class="result-verdict">${ok?'✓ Correcta':'✕ Incorrecta'}</span><h3>${i+1}. ${esc(plain(c.front))}</h3><p><strong>Tu respuesta (${'ABCD'[marked]}):</strong> ${esc(c.choices[marked])}</p><p><strong>Clave correcta (${'ABCD'[right]}):</strong> ${esc(c.choices[right])}</p></article>`;
    }).join('')}<button onclick="leave()">Volver a mis mazos</button>`;
}
load();
