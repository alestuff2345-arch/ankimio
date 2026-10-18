// Save identifiers only: card text, edits and images are fetched afresh.
const RoundStore=(()=>{
    const prefix='ankimio.round.';
    const id=value=>typeof value==='string' && /^[a-zA-Z0-9-]{1,160}$/.test(value);
    const token=value=>typeof value==='string' && /^[a-f0-9]{32}$/.test(value);
    const integer=value=>Number.isSafeInteger(value) && value>=0;
    const ids=value=>Array.isArray(value) && value.every(id) && new Set(value).size===value.length;
    function valid(s){
        if(!s || s.version!==1 || !id(s.deck) || !ids(s.full) || !ids(s.round) || !ids(s.queue) || !s.round.length)return false;
        const full=new Set(s.full),round=new Set(s.round);
        if(!s.round.every(c=>full.has(c)) || !s.queue.every(c=>round.has(c)) || s.known!==s.round.length-s.queue.length)return false;
        if(typeof s.tracking!=='boolean' || typeof s.onlyDifficult!=='boolean' || typeof s.revealed!=='boolean' || !['all','recommended'].includes(s.mode))return false;
        if(!Array.isArray(s.difficulty) || !s.difficulty.every(d=>Array.isArray(d) && round.has(d[0]) && integer(d[1])))return false;
        if(!Array.isArray(s.history) || !s.history.every(h=>h && round.has(h.card) && integer(h.known) && h.known<=s.round.length && integer(h.difficulty) && (h.reinsertAt===null || integer(h.reinsertAt) && h.reinsertAt<s.round.length) && (h.eventId===null || token(h.eventId))))return false;
        if(s.pendingRating){
            const p=s.pendingRating,b=p.body;
            if(!b || p.card!==s.queue[0] || !token(b.event_id) || !['again','hard','good','easy'].includes(b.rating) || !(b.expected_revision===null || token(b.expected_revision)) || typeof b.timezone!=='string')return false;
        }
        if(s.pendingUndo && (!token(s.pendingUndo) || s.history.at(-1)?.eventId!==s.pendingUndo))return false;
        return true;
    }
    return {
        read(deck){try{const s=JSON.parse(localStorage.getItem(prefix+deck));return valid(s) && s.deck===deck?s:null;}catch{return null;}},
        save(snapshot){try{if(!valid(snapshot))return false;localStorage.setItem(prefix+snapshot.deck,JSON.stringify(snapshot));return true;}catch{return false;}},
        clearAll(){try{Object.keys(localStorage).filter(k=>k.startsWith(prefix)).forEach(k=>localStorage.removeItem(k));}catch{}}
    };
})();
