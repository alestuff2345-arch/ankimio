const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
class Storage{
 getItem(key){return this[key]??null;}
 setItem(key,value){this[key]=String(value);}
 removeItem(key){delete this[key];}
}
function setup(storage=new Storage()){
 const context=vm.createContext({localStorage:storage});
 vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../static/rounds.js'),'utf8'),context);
 return {store:vm.runInContext('RoundStore',context),storage};
}
function round(){return {version:1,deck:'deck',full:['a','b','c'],round:['a','b','c'],queue:['c','a'],known:1,tracking:true,mode:'all',onlyDifficult:false,revealed:true,difficulty:[['a',1]],history:[{card:'a',known:0,reinsertAt:1,difficulty:0,eventId:'a'.repeat(32)},{card:'b',known:0,reinsertAt:null,difficulty:0,eventId:'b'.repeat(32)}],pendingRating:null,pendingUndo:null};}
test('round-trip preserves queue order, undo and difficulties without storing card content',()=>{
 const {store,storage}=setup();const s=round();assert.equal(store.save(s),true);
 assert.equal(JSON.stringify(store.read('deck')),JSON.stringify(s));
 assert.equal(Object.keys(storage).length,1);
 assert.equal(store.read('other'),null);
});
test('pending rating and undo survive reload for idempotent recovery',()=>{
 const {store,storage}=setup();const s=round();s.pendingRating={card:'c',body:{rating:'hard',event_id:'c'.repeat(32),expected_revision:null,timezone:'America/Lima'}};
 assert.equal(store.save(s),true);assert.equal(setup(storage).store.read('deck').pendingRating.body.event_id,'c'.repeat(32));
 s.pendingRating=null;s.pendingUndo='b'.repeat(32);assert.equal(store.save(s),true);
 assert.equal(setup(storage).store.read('deck').pendingUndo,'b'.repeat(32));
});
test('malformed snapshots cannot replace a valid round',()=>{
 const {store}=setup();const good=round();assert.equal(store.save(good),true);
 const bad=[{version:2},{known:99},{queue:['a','a']},{queue:['missing','a']},{full:['b','c']},{history:[{card:'missing'}]},{pendingUndo:'c'.repeat(32)},{pendingRating:{card:'b',body:{}}}];
 for(const change of bad){assert.equal(store.save({...good,...change}),false);assert.equal(JSON.stringify(store.read('deck')),JSON.stringify(good));}
});
test('corrupt JSON and mismatched deck keys are ignored',()=>{
 const {store,storage}=setup();storage.setItem('ankimio.round.deck','{');assert.equal(store.read('deck'),null);
 storage.setItem('ankimio.round.deck',JSON.stringify({...round(),deck:'other'}));assert.equal(store.read('deck'),null);
});
test('clearing rounds preserves preferences and other browser data',()=>{
 const {store,storage}=setup();store.save(round());store.save({...round(),deck:'another'});
 storage.setItem('ankimio.spaced-review','off');storage.setItem('unrelated','keep');store.clearAll();
 assert.equal(store.read('deck'),null);assert.equal(store.read('another'),null);
 assert.equal(storage.getItem('ankimio.spaced-review'),'off');assert.equal(storage.getItem('unrelated'),'keep');
});
test('unavailable or full storage fails safely without claiming a save',()=>{
 const {store}=setup({getItem(){throw Error('blocked');},setItem(){throw Error('quota');}});
 assert.equal(store.read('deck'),null);assert.equal(store.save(round()),false);assert.doesNotThrow(()=>store.clearAll());
});
