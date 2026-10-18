const $=s=>document.querySelector(s);let selected,session,index,exam,answers,examPool,reviewDeck,reviewQueue,reviewKnown,reviewHistory=[],reviewDifficulty=new Map(),reviewFullDeck=[],reviewOnlyDifficult=false;
function esc(s){const e=document.createElement('div');e.textContent=s;return e.innerHTML}
function plain(s){const t=document.createElement('template');t.innerHTML=s;t.content.querySelectorAll('script,style').forEach(x=>x.remove());return t.content.textContent||''}
const sessionImages=new Map();
function clearSessionImages(){
    for(const url of sessionImages.values())URL.revokeObjectURL(url);
    sessionImages.clear();
}
// Rebuild a small HTML allowlist; imported scripts, styles and external URLs
// never enter the live document.
function cardHtml(markup,useSessionImages=true){
    const template=document.createElement('template');template.innerHTML=markup;
    const parsed=template.content.ownerDocument;
    const allowed=new Set(['DIV','P','SPAN','BR','HR','B','STRONG','I','EM','U','S','SUB','SUP','UL','OL','LI','TABLE','THEAD','TBODY','TR','TD','TH','H1','H2','H3','H4','BLOCKQUOTE','PRE','CODE']);
    function clean(node){
        if(node.nodeType===Node.TEXT_NODE)return parsed.createTextNode(node.textContent);
        const fragment=parsed.createDocumentFragment();
        if(node.nodeType!==Node.ELEMENT_NODE)return fragment;
        if(['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','SVG','MATH','TEMPLATE','LINK','META'].includes(node.tagName))return fragment;
        if(node.tagName==='IMG'){
            const src=node.getAttribute('src')||'';
            const saved=node.getAttribute('data-media-src');
            const ref=/^\/media\/[a-f0-9]{32}$/.test(src)?src:(saved && sessionImages.get(saved)===src?saved:'');
            if(!/^\/media\/[a-f0-9]{32}$/.test(ref))return parsed.createTextNode('[Imagen no disponible: vuelve a importar el mazo con sus archivos multimedia]');
            const img=parsed.createElement('img');
            const cached=useSessionImages && sessionImages.get(ref);
            img.setAttribute('src',cached || ref);if(cached)img.setAttribute('data-media-src',ref);
            img.alt=node.getAttribute('alt')||'Imagen de la tarjeta';img.loading='lazy';return img;
        }
        const result=allowed.has(node.tagName)?parsed.createElement(node.tagName.toLowerCase()):fragment;
        if(node.classList.contains('cloze') && result.nodeType===Node.ELEMENT_NODE)result.className='cloze';
        for(const child of node.childNodes)result.append(clean(child));
        return result;
    }
    const output=parsed.createElement('div');for(const child of template.content.childNodes)output.append(clean(child));return output.innerHTML;
}
// A transient image request should not leave only a broken-image label.
// Retry once, then offer an explicit retry without altering card content.
document.addEventListener('load',e=>{
    if(e.target instanceof HTMLImageElement)delete e.target.dataset.retried;
},true);
document.addEventListener('error',e=>{
    const img=e.target;
    if(!(img instanceof HTMLImageElement) || !img.closest('.flashcard,.browse-card,.result,.edit-images'))return;
    const path=img.getAttribute('data-media-src') || new URL(img.src,location.href).pathname;
    if(!/^\/media\/[a-f0-9]{32}$/.test(path))return;
    if(!img.dataset.retried){
        img.dataset.retried='1';
        setTimeout(()=>{if(img.isConnected)img.src=path+'?retry=1';},350);
        return;
    }
    if(img.nextElementSibling?.classList.contains('image-error'))return;
    img.hidden=true;
    const message=document.createElement('span');message.className='image-error';message.setAttribute('role','status');
    message.append(document.createTextNode('No se pudo cargar esta imagen. '));
    const retry=document.createElement('button');retry.type='button';retry.textContent='Reintentar imagen';
    retry.onclick=()=>{
        message.remove();img.hidden=false;delete img.dataset.retried;
        img.src=path+'?retry='+Date.now();
    };
    message.append(retry);img.after(message);
    img.addEventListener('load',()=>{message.remove();img.hidden=false;},{once:true});
},true);
function cardImages(markup){
    const container=document.createElement('template');container.innerHTML=cardHtml(markup,false);
    return [...container.content.querySelectorAll('img')].map(img=>img.outerHTML).join('');
}
function hasCardContent(markup){return Boolean(plain(markup).trim() || cardImages(markup));}
function editedCardSide(original,text){
    if(text===plain(original))return original;
    return esc(text.trim()).replace(/\n/g,'<br>')+cardImages(original);
}
async function api(url,options={},timeoutMs=30000){
    const controller=new AbortController();let timedOut=false;
    const cancel=()=>controller.abort();
    if(options.signal?.aborted)controller.abort();
    else options.signal?.addEventListener('abort',cancel,{once:true});
    const timer=setTimeout(()=>{timedOut=true;controller.abort();},timeoutMs);
    try{
        const response=await fetch(url,{...options,signal:controller.signal});
        const text=await response.text();let data;
        try{data=JSON.parse(text);}catch{
            throw Error(`El servidor no respondió correctamente (HTTP ${response.status}). Inténtalo de nuevo.`);
        }
        if(!response.ok){const error=Error(data.error||'No se pudo completar la operación.');error.status=response.status;throw error;}
        return data;
    }catch(error){
        if(timedOut){const timeout=Error('El servidor está tardando demasiado. Inténtalo de nuevo.');timeout.code='TIMEOUT';throw timeout;}
        if(controller.signal.aborted){const cancelled=Error('Se canceló la espera de la respuesta.');cancelled.code='CANCELLED';throw cancelled;}
        throw error;
    }finally{
        clearTimeout(timer);options.signal?.removeEventListener('abort',cancel);
    }
}
async function deckCards(key){
    const bundle=await api(`/api/decks/${key}/study`,{},120000);
    const images=new Map();
    try{
        for(const [path,value] of Object.entries(bundle.images || {})){
            if(!/^\/media\/[a-f0-9]{32}$/.test(path))continue;
            const match=/^data:(image\/(?:png|jpeg|gif|webp|bmp|avif));base64,([A-Za-z0-9+/=]+)$/.exec(value);
            if(!match)continue;
            const bytes=Uint8Array.from(atob(match[2]),c=>c.charCodeAt(0));
            images.set(path,URL.createObjectURL(new Blob([bytes],{type:match[1]})));
        }
    }catch(error){for(const url of images.values())URL.revokeObjectURL(url);throw error;}
    clearSessionImages();for(const [path,url] of images)sessionImages.set(path,url);
    return bundle.cards;
}
function notice(s){$('#notice').textContent=s}
async function load(){try{const decks=await api('/api/decks');$('#total').textContent=`(${decks.length})`;$('#deleteall').disabled=decks.length===0;$('#decks').innerHTML=decks.length?decks.map((d,i)=>`<article><div class="deck-icon">${['⚓','☠','☀','♜'][i%4]}</div><h3>${esc(d.name)}</h3><p>${d.count} tarjetas · Sin límite diario</p><div class="deck-actions"><button data-id="${d.id}" data-action="review">Repasar ↗</button><button data-id="${d.id}" data-action="exam">Simulacro</button><button data-id="${d.id}" data-action="browse">Explorar</button><button data-id="${d.id}" data-action="add" aria-label="Añadir tarjeta">＋</button></div></article>`).join(''):'<div class="empty"><span>✧</span><h3>¡Tu aventura empieza aquí, nakama!</h3><p>Tu primer tesoro: crea un mazo o importa tus tarjetas de Anki.</p></div>'}catch(e){notice(e.message)}}
$('#deleteall').onclick=()=>{
    $('#deletestatus').textContent='';$('#deleteconfirm').showModal();
};
$('#canceldelete').onclick=()=>$('#deleteconfirm').close();
let deletingDecks=false;
$('#deleteconfirm').addEventListener('cancel',e=>{if(deletingDecks)e.preventDefault();});
$('#deleteform').onsubmit=async e=>{
    e.preventDefault();if(deletingDecks)return;
    deletingDecks=true;
    const buttons=[...e.currentTarget.querySelectorAll('button')];
    buttons.forEach(b=>b.disabled=true);$('#deletestatus').textContent='Eliminando…';
    try{
        const result=await api('/api/decks',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:true})});
        clearSessionImages();selected=null;session=[];answers=[];examPool=[];reviewDeck=[];reviewQueue=[];reviewKnown=0;reviewHistory=[];reviewDifficulty.clear();reviewFullDeck=[];reviewOnlyDifficult=false;
        $('#study').hidden=true;$('#study').innerHTML='';$('#library').hidden=false;
        $('#deleteconfirm').close();
        await load();notice(`Se eliminaron ${result.decks} mazos y ${result.cards} tarjetas.`);
    }catch(error){$('#deletestatus').textContent=error.message;}
    finally{deletingDecks=false;buttons.forEach(b=>b.disabled=false);}
};
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
$('#file').onchange=async e=>{if(!e.target.files[0])return;const form=new FormData();form.append('file',e.target.files[0]);notice('Importando…');try{const r=await api('/api/import',{method:'POST',body:form},120000);notice(`${r.count} tarjetas importadas en ${r.decks} mazos. ${r.warning}`);load()}catch(e){notice(e.message)}e.target.value=''};
let browseCards=[],browseDeck=null,browsePage=0,editingCard=null,savingEdit=false,editingDeck=null,afterCardEdit=null,editRequest=null;
const pageSize=25;
async function openBrowser(deck,name){
    try{
        const cards=await deckCards(deck);
        browseDeck=deck;browseCards=cards.sort((a,b)=>plain(a.front).localeCompare(plain(b.front),'es'));browsePage=0;
        $('#library').hidden=true;$('#study').hidden=false;notice('');
        $('#study').innerHTML=`<button onclick="leave()">← Mis mazos</button><h1>Explorar mazo</h1><h2>${esc(name)}</h2><label>Buscar tarjetas<input type="search" id="cardsearch" placeholder="Buscar en preguntas y respuestas…"></label><p id="browsecount" role="status"></p><div id="cardlist"></div><div class="actions"><button id="browseprev">← Anterior</button><span id="browsepage"></span><button id="browsenext">Siguiente →</button></div>`;
        $('#cardsearch').oninput=()=>{browsePage=0;renderBrowser();};
        $('#browseprev').onclick=()=>{browsePage--;renderBrowser();};
        $('#browsenext').onclick=()=>{browsePage++;renderBrowser();};
        $('#cardlist').onclick=e=>{
            const b=e.target.closest('button[data-edit]');if(!b)return;
            const card=browseCards.find(c=>c.id===b.dataset.edit);if(!card)return;
            openCardEditor(card,browseDeck,renderBrowser);
        };
        renderBrowser();
    }catch(error){notice(error.message);}
}
function renderBrowser(){
    const search=$('#cardsearch').value.toLocaleLowerCase('es');
    const filtered=browseCards.filter(c=>plain(c.front).toLocaleLowerCase('es').includes(search) || plain(c.back).toLocaleLowerCase('es').includes(search));
    const pages=Math.max(1,Math.ceil(filtered.length/pageSize));browsePage=Math.min(Math.max(0,browsePage),pages-1);
    $('#browsecount').textContent=`${filtered.length} de ${browseCards.length} tarjetas`;
    $('#cardlist').innerHTML=filtered.slice(browsePage*pageSize,(browsePage+1)*pageSize).map(c=>`<article class="browse-card"><div><div class="browse-front">${cardHtml(c.front)}</div><div class="browse-back"><strong>Respuesta:</strong> ${cardHtml(c.back)}</div></div><button data-edit="${esc(c.id)}">Editar</button></article>`).join('') || '<p class="empty">No hay tarjetas que mostrar.</p>';
    $('#browsepage').textContent=`Página ${browsePage+1} de ${pages}`;
    $('#browseprev').disabled=browsePage===0;$('#browsenext').disabled=browsePage>=pages-1;
}
function openCardEditor(card,deck,onSaved){
    editingCard=card;editingDeck=deck;afterCardEdit=onSaved;
    const form=$('#editform');form.elements.front.value=plain(card.front);form.elements.back.value=plain(card.back);
    for(const name of ['front','back']){
        form.elements[name].required=!cardImages(card[name]);form.elements[name].setCustomValidity('');
    }
    $('#editimages').innerHTML=cardHtml(cardImages(card.front)+cardImages(card.back));
    $('#editimages').hidden=!$('#editimages').innerHTML;
    $('#editstatus').textContent='';$('#edit').showModal();
}
$('#canceledit').onclick=()=>{
    if(savingEdit){editRequest?.abort();return;}
    $('#edit').close();
};
$('#edit').addEventListener('cancel',e=>{
    if(savingEdit){e.preventDefault();editRequest?.abort();}
});
$('#editform').oninput=e=>{if(e.target.matches('textarea'))e.target.setCustomValidity('');};
$('#editform').onkeydown=e=>{
    if(e.ctrlKey && e.key==='Enter' && !e.isComposing){e.preventDefault();if(!e.repeat && !savingEdit)e.currentTarget.requestSubmit();}
};
$('#editform').onsubmit=async e=>{
    e.preventDefault();if(savingEdit || !editingCard)return;
    const form=e.currentTarget, card=editingCard;
    for(const name of ['front','back']){
        if(!form.elements[name].value.trim() && !cardImages(card[name])){form.elements[name].setCustomValidity('Completa este campo.');form.elements[name].reportValidity();return;}
    }
    const body={};
    for(const name of ['front','back'])body[name]=editedCardSide(card[name],form.elements[name].value);
    savingEdit=true;editRequest=new AbortController();
    const saveButton=form.querySelector('button[type="submit"]'),cancelButton=$('#canceledit');
    saveButton.disabled=true;cancelButton.textContent='Dejar de esperar';
    form.querySelectorAll('textarea').forEach(field=>field.readOnly=true);
    $('#editstatus').textContent='Guardando…';
    try{
        await api(`/api/decks/${editingDeck}/cards/${card.id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:editRequest.signal},20000);
        Object.assign(card,body);$('#edit').close();if(afterCardEdit)afterCardEdit();notice('Cambios guardados.');
    }catch(error){
        const uncertain=['TIMEOUT','CANCELLED'].includes(error.code) || error instanceof TypeError;
        $('#editstatus').textContent=uncertain
            ? 'No se pudo confirmar el guardado. Tu texto se conserva aquí; puedes pulsar Guardar cambios para reintentar.'
            : error.message;
    }finally{
        savingEdit=false;editRequest=null;saveButton.disabled=false;cancelButton.textContent='Cancelar';
        form.querySelectorAll('textarea').forEach(field=>field.readOnly=false);
    }
};
function shuffled(items){
    const result=[...items];
    for(let i=result.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[result[i],result[j]]=[result[j],result[i]];}
    return result;
}
function answerText(card){return cardHtml(card.back).trim();}
function answerKey(text){
    const holder=document.createElement('template');holder.innerHTML=cardImages(text);
    return plain(text).replace(/\s+/g,' ').trim().toLocaleLowerCase('es')+'|'+[...holder.content.querySelectorAll('img')].map(img=>img.getAttribute('src')).join('|');
}
function choicesFor(card){
    const correct=answerText(card), key=answerKey(correct);
    const distractors=shuffled(examPool.filter(text=>answerKey(text)!==key)).slice(0,3);
    return shuffled([correct,...distractors]);
}
$('#decks').onclick=async e=>{
    const b=e.target.closest('button');if(!b)return;
    selected=b.dataset.id;if(b.dataset.action==='add')return $('#add').showModal();
    if(b.dataset.action==='browse')return openBrowser(selected,b.closest('article').querySelector('h3').textContent);
    try{
        session=await deckCards(selected);
        if(!session.length)return notice('Añade tarjetas a este mazo para empezar.');
        exam=b.dataset.action==='exam';index=0;answers=[];
        if(exam){
            session=session.filter(c=>hasCardContent(c.front) && hasCardContent(c.back));
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
function leave(){reviewHistory=[];reviewDifficulty.clear();$('#study').hidden=true;$('#library').hidden=false;notice('');load()}
function startReview(cards,fullDeck=cards,onlyDifficult=false){
    reviewFullDeck=[...fullDeck];reviewOnlyDifficult=onlyDifficult;
    reviewDeck=[...cards];reviewQueue=shuffled(cards);reviewKnown=0;reviewHistory=[];reviewDifficulty.clear();showReview();
}
function undoReview(){
    if(exam || $('#study').hidden || !reviewHistory.length)return;
    const previous=reviewHistory.pop();
    if(previous.reinsertAt!==null)reviewQueue.splice(previous.reinsertAt,1);
    reviewQueue.unshift(previous.card);reviewKnown=previous.known;
    if(previous.difficulty)reviewDifficulty.set(previous.card,previous.difficulty);
    else reviewDifficulty.delete(previous.card);
    showReview();$('#reveal').click();
    const flashcard=$('#study .flashcard');flashcard.tabIndex=-1;flashcard.focus({preventScroll:true});
    notice('Última calificación deshecha. Puedes volver a calificar esta tarjeta.');
}
function undoReviewButton(){
    return `<button id="undoreview" type="button" aria-keyshortcuts="Control+z Meta+z" ${reviewHistory.length?'':'disabled'}>↶ Deshacer calificación · Ctrl + Z</button>`;
}
function showReview(){
    if(!reviewQueue.length){
        const difficult=reviewDeck.filter(card=>reviewDifficulty.has(card));
        $('#study').innerHTML=`<div class="empty"><span>✳</span><h1>${reviewOnlyDifficult?'¡Refuerzo completado!':'¡Ya te las sabes todas!'}</h1><p>Has marcado las ${reviewDeck.length} tarjetas de esta ronda como Bien o Fácil.</p><p>${difficult.length?`${difficult.length} tarjetas te costaron más: las marcaste como Otra vez o Difícil. Puedes repasar solo esas.`:'No marcaste ninguna tarjeta como Otra vez o Difícil en esta ronda.'}</p><div class="actions"><button class="primary" id="complicated" ${difficult.length?'':'disabled'}>Repasar las complicadas (${difficult.length})</button><button id="again">Repasar todo de nuevo</button><button onclick="leave()">Mis mazos</button>${undoReviewButton()}</div></div>`;
        $('#undoreview').onclick=undoReview;
        $('#complicated').onclick=()=>{if(difficult.length)startReview(difficult,reviewFullDeck,true);};
        $('#again').onclick=()=>startReview(reviewFullDeck);
        return;
    }
    const c=reviewQueue[0];
    $('#study').innerHTML=`<button onclick="leave()">← Mis mazos</button> ${undoReviewButton()}<div class="section-title"><h2>${reviewOnlyDifficult?'Repaso de complicadas':'Repaso libre'}</h2><span>${reviewKnown} / ${reviewDeck.length} aprendidas · ${reviewQueue.length} pendientes</span></div><progress value="${reviewKnown}" max="${reviewDeck.length}"></progress><div class="flashcard"><div class="card-toolbar"><span class="eyebrow">PIENSA EN LA RESPUESTA</span><button id="editcurrent" type="button">Editar tarjeta</button></div><div class="card-front">${cardHtml(c.front)}</div><div id="answer" hidden><hr><div class="card-back">${cardHtml(c.back)}</div></div></div><div class="actions"><button class="primary" id="reveal" aria-keyshortcuts="Space">Mostrar respuesta</button><div id="ratings" class="rating-actions" hidden><button data-rating="again" aria-keyshortcuts="1" class="rating-again"><span>1 · Otra vez</span><small>No me la sé</small></button><button data-rating="hard" aria-keyshortcuts="2" class="rating-hard"><span>2 · Difícil</span><small>Seguir practicando</small></button><button data-rating="good" aria-keyshortcuts="3 Space" class="rating-good"><span>3 · Bien</span><small>Me la sé</small></button><button data-rating="easy" aria-keyshortcuts="4" class="rating-easy"><span>4 · Fácil</span><small>Dominada</small></button></div></div><p class="hint" id="reviewhint">Espacio: mostrar respuesta. Las tarjetas pendientes se repiten sin esperas.</p>`;
    $('#undoreview').onclick=undoReview;
    $('#editcurrent').onclick=()=>{
        const wasRevealed=!$('#answer').hidden;
        openCardEditor(c,selected,()=>{showReview();if(wasRevealed)$('#reveal').click();});
    };
    $('#reveal').onclick=()=>{
        $('#answer').hidden=false;$('#ratings').hidden=false;$('#reveal').hidden=true;
        $('#reviewhint').textContent='1: Otra vez · 2: Difícil · 3: Bien · 4: Fácil · Espacio: Bien.';
    };
    $('#ratings').onclick=e=>{
        const button=e.target.closest('button[data-rating]');if(!button || $('#answer').hidden)return;
        const card=reviewQueue.shift(), rating=button.dataset.rating;
        const previous={card,known:reviewKnown,reinsertAt:null,difficulty:reviewDifficulty.get(card)||0};
        if(rating==='again' || rating==='hard'){
            reviewDifficulty.set(card,previous.difficulty+1);
            // Repeat within this session: sooner for Again, later for Hard.
            previous.reinsertAt=Math.min(rating==='again'?1:3,reviewQueue.length);
            reviewQueue.splice(previous.reinsertAt,0,card);
        }else reviewKnown++;
        reviewHistory.push(previous);
        showReview();
    };
}
function show(){
    const c=session[index];
    $('#study').innerHTML=`<button onclick="leave()">← Mis mazos</button><div class="section-title"><h2>Simulacro</h2><span>${index+1} / ${session.length}</span></div><progress value="${index}" max="${session.length}"></progress><div class="flashcard"><span class="eyebrow">MARCA UNA ALTERNATIVA</span><div class="card-front">${cardHtml(c.front)}</div><fieldset class="choices"><legend>Elige tu respuesta</legend>${c.choices.map((text,i)=>`<label class="choice"><input type="radio" name="choice" value="${i}"><span class="choice-letter">${'ABCD'[i]}</span><span class="choice-content">${cardHtml(text)}</span></label>`).join('')}</fieldset></div><div class="actions"><button class="primary" id="next" aria-keyshortcuts="Space" disabled>${index===session.length-1?'Terminar y ver resultados':'Siguiente pregunta →'}</button></div><p class="hint">Marca una alternativa y pulsa Espacio para continuar.</p>`;
    document.querySelectorAll('input[name="choice"]').forEach(r=>r.onchange=()=>{$('#next').disabled=false;});
    $('#next').onclick=()=>{
        const marked=$('input[name="choice"]:checked');if(!marked)return;
        answers.push(Number(marked.value));index++;
        if(index<session.length)show();else results();
    };
}
document.addEventListener('keydown',e=>{
    if(!(e.ctrlKey || e.metaKey) || e.key.toLowerCase()!=='z' || e.shiftKey || e.altKey || e.isComposing)return;
    if(exam || $('#study').hidden || document.querySelector('dialog[open]'))return;
    const target=e.target;
    if(target instanceof Element && (target.closest('input,textarea,select,[role="textbox"]') || target.isContentEditable))return;
    const button=$('#undoreview');if(!button || button.disabled)return;
    e.preventDefault();if(!e.repeat)undoReview();
});
document.addEventListener('keydown',e=>{
    const space=e.code==='Space' || e.key===' ';
    if(!space && !['1','2','3','4'].includes(e.key)) return;
    if(e.ctrlKey || e.altKey || e.metaKey || e.shiftKey || e.isComposing) return;
    if($('#study').hidden || document.querySelector('dialog[open]')) return;
    const target=e.target;
    if(exam){
        if(!space)return;
        const next=$('#next');
        if(!next || next.disabled || !$('input[name="choice"]:checked'))return;
        if(target instanceof Element){
            if(target.isContentEditable || target.closest('textarea,select,a,[role="textbox"]'))return;
            const input=target.closest('input');
            if(input && !input.matches('input[type="radio"][name="choice"]'))return;
            const button=target.closest('button');if(button && button!==next)return;
        }
        e.preventDefault();if(!e.repeat)next.click();return;
    }
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
        return `<article class="result ${ok?'result-correct':'result-wrong'}"><span class="result-verdict">${ok?'✓ Correcta':'✕ Incorrecta'}</span><div class="result-question"><strong>${i+1}.</strong> ${cardHtml(c.front)}</div><div><strong>Tu respuesta (${'ABCD'[marked]}):</strong> ${cardHtml(c.choices[marked])}</div><div><strong>Clave correcta (${'ABCD'[right]}):</strong> ${cardHtml(c.choices[right])}</div></article>`;
    }).join('')}<button onclick="leave()">Volver a mis mazos</button>`;
}
load();
