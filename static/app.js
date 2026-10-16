const $=s=>document.querySelector(s);let selected,session,index,exam,answers;
function esc(s){const e=document.createElement('div');e.textContent=s;return e.innerHTML}
function plain(s){const d=new DOMParser().parseFromString(s,'text/html');d.querySelectorAll('script,style').forEach(x=>x.remove());return d.body.textContent||''}
async function api(url,options){const r=await fetch(url,options);const d=await r.json();if(!r.ok)throw Error(d.error||'No se pudo completar la operación.');return d}
function notice(s){$('#notice').textContent=s}
async function load(){try{const decks=await api('/api/decks');$('#total').textContent=`(${decks.length})`;$('#decks').innerHTML=decks.length?decks.map((d,i)=>`<article><div class="deck-icon">${['⚓','☠','☀','♜'][i%4]}</div><h3>${esc(d.name)}</h3><p>${d.count} tarjetas · Sin límite diario</p><div class="deck-actions"><button data-id="${d.id}" data-action="review">Repasar ↗</button><button data-id="${d.id}" data-action="exam">Simulacro</button><button data-id="${d.id}" data-action="add" aria-label="Añadir tarjeta">＋</button></div></article>`).join(''):'<div class="empty"><span>✧</span><h3>¡Tu aventura empieza aquí, nakama!</h3><p>Tu primer tesoro: crea un mazo o importa tus tarjetas de Anki.</p></div>'}catch(e){notice(e.message)}}
let savingDeck=false;
$('#newform').addEventListener('keydown',e=>{
    if(e.ctrlKey && e.key==='Enter' && !e.isComposing){
        e.preventDefault();
        if(!e.repeat && !savingDeck) e.currentTarget.requestSubmit();
    }
});
$('#newform').onsubmit=async e=>{
    e.preventDefault();
    if(savingDeck) return;
    const form=e.currentTarget, input=form.elements.name, button=form.querySelector('button[type="submit"]');
    const name=input.value.trim();
    if(!name){input.setCustomValidity('Escribe un nombre para el mazo.');input.reportValidity();return;}
    savingDeck=true;button.disabled=true;
    $('#newstatus').textContent='Guardando…';
    try{
        await api('/api/decks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
        form.reset();
        $('#newstatus').textContent=`Mazo «${name}» guardado. Puedes añadir otro.`;
        input.focus();
        await load();
    }catch(error){
        $('#newstatus').textContent=error.message;
    }finally{savingDeck=false;button.disabled=false;}
};
$('#newform input').addEventListener('input',e=>e.target.setCustomValidity(''));
$('#addform').onsubmit=async e=>{e.preventDefault();try{await api(`/api/decks/${selected}/cards`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});$('#add').close();e.target.reset();load()}catch(e){notice(e.message)}};
$('#file').onchange=async e=>{if(!e.target.files[0])return;const form=new FormData();form.append('file',e.target.files[0]);notice('Importando…');try{const r=await api('/api/import',{method:'POST',body:form});notice(`${r.count} tarjetas importadas en ${r.decks} mazos. ${r.warning}`);load()}catch(e){notice(e.message)}e.target.value=''};
$('#decks').onclick=async e=>{const b=e.target.closest('button');if(!b)return;selected=b.dataset.id;if(b.dataset.action==='add')return $('#add').showModal();try{session=await api(`/api/decks/${selected}/cards`);if(!session.length)return notice('Añade tarjetas a este mazo para empezar.');exam=b.dataset.action==='exam';index=0;answers=[];$('#library').hidden=true;$('#study').hidden=false;notice('');if(exam){$('#study').innerHTML='<button onclick="leave()">← Mis mazos</button><h1>Tu prueba en el Grand Line.</h1><p>Responde sin mirar las soluciones y corrige al terminar. Sin límite de tiempo.</p><form id="config"><label>Número de preguntas<input id="amount" type="number" min="1" max="'+session.length+'" value="'+Math.min(20,session.length)+'" required></label><button class="primary">Comenzar simulacro</button></form>';$('#config').onsubmit=e=>{e.preventDefault();session=session.slice(0,Number($('#amount').value));show()}}else show()}catch(e){notice(e.message)}};
function leave(){$('#study').hidden=true;$('#library').hidden=false;notice('');load()}
function show(){const c=session[index];$('#study').innerHTML=`<button onclick="leave()">← Mis mazos</button><div class="section-title"><h2>${exam?'Simulacro':'Repaso libre'}</h2><span>${index+1} / ${session.length}</span></div><progress value="${index}" max="${session.length}"></progress><div class="flashcard"><span class="eyebrow">${exam?'PREGUNTA':'PIENSA EN LA RESPUESTA'}</span><h2>${esc(plain(c.front))}</h2>${exam?'<label>Tu respuesta<textarea id="response" placeholder="Escribe lo que recuerdas…"></textarea></label>':`<div id="answer" hidden><hr><p>${esc(plain(c.back))}</p></div>`}</div><div class="actions">${exam?'<button class="primary" id="next">'+(index===session.length-1?'Terminar y corregir':'Siguiente pregunta →')+'</button>':'<button class="primary" id="reveal">Mostrar respuesta</button><button id="next" hidden>Siguiente tarjeta →</button>'}</div>`;if(!exam)$('#reveal').onclick=()=>{$('#answer').hidden=false;$('#next').hidden=false;$('#reveal').hidden=true};$('#next').onclick=()=>{if(exam)answers.push($('#response').value);index++;if(index<session.length)show();else if(exam)results();else{$('#study').innerHTML='<div class="empty"><span>✳</span><h1>¡Otra isla conquistada!</h1><p>Has repasado todas las tarjetas. Puedes volver a empezar ahora mismo.</p><button class="primary" id="again">Volver a repasar</button> <button onclick="leave()">Mis mazos</button></div>';$('#again').onclick=()=>{index=0;session.sort(()=>Math.random()-.5);show()}}}}
function results(){$('#study').innerHTML=`<button onclick="leave()">← Mis mazos</button><h1>El botín de tu aventura.</h1><p>Compara tus respuestas con las soluciones y marca las que acertaste.</p><h2 id="score">0 / ${session.length} correctas</h2>${session.map((c,i)=>`<article class="result"><h3>${i+1}. ${esc(plain(c.front))}</h3><p><strong>Tu respuesta:</strong> ${esc(answers[i]||'Sin respuesta')}</p><p><strong>Solución:</strong> ${esc(plain(c.back))}</p><label class="check"><input type="checkbox" class="grade"> La respondí correctamente</label></article>`).join('')}<button onclick="leave()">Volver a mis mazos</button>`;document.querySelectorAll('.grade').forEach(x=>x.onchange=()=>{$('#score').textContent=`${document.querySelectorAll('.grade:checked').length} / ${session.length} correctas`})}
load();
