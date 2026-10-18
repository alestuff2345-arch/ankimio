const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const repo=path.resolve(__dirname,'..');
(async()=>{
 const data=fs.mkdtempSync('/tmp/ankimio-resume-browser-');
 const env={...process.env,ANKIMIO_DATA:data};for(const k of ['DATABASE_URL','RENDER','ANKIMIO_REQUIRE_DATABASE','ANKIMIO_PASSWORD'])delete env[k];
 let server,port=0,base;
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1280,height:1000},timezoneId:'America/Lima'});
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 async function stop(){if(server && server.exitCode===null){const exit=new Promise(resolve=>server.once('exit',resolve));server.kill('SIGTERM');await exit;}}
 async function start(){
  server=spawn(path.join(repo,'.venv/bin/python'),['-u','-c',`from app import app; app.run(host="127.0.0.1",port=${port},debug=False)`],{cwd:repo,env,stdio:['ignore','ignore','pipe']});
  let log='';server.stderr.on('data',x=>log+=x.toString());
  for(let i=0;i<100;i++){
   if(server.exitCode!==null)throw Error(log);
   const ready=/Running on http:\/\/127\.0\.0\.1:(\d+)/.exec(log);
   if(ready){port=Number(ready[1]);base='http://127.0.0.1:'+port;try{if((await context.request.get(base+'/healthz',{timeout:100})).ok())return;}catch{}}
   await new Promise(r=>setTimeout(r,50));
  }throw Error('Server did not start: '+log);
 }
 try{
 await start();await page.route('https://fonts.googleapis.com/**',r=>r.abort());
 const api=async(path,body)=>{const r=body===undefined?await context.request.get(base+path):await context.request.post(base+path,{data:body});assert.ok(r.ok(),await r.text());return r.json();};
 const key=(await api('/api/decks',{name:'Ronda persistente'})).id;
 for(const name of ['A','B','C','D'])await api(`/api/decks/${key}/cards`,{front:name,back:'Respuesta '+name});
 const settle=()=>page.waitForFunction(()=>!reviewBusy);
 const hist=n=>page.waitForFunction(n=>!reviewBusy && reviewHistory.length===n,n);
 async function rate(r,n){if(await page.locator('#reveal').isVisible())await page.locator('#reveal').click();await page.locator(`[data-rating="${r}"]`).click();await hist(n);}
 const snapshot=()=>page.evaluate(()=>({queue:reviewQueue.map(c=>c.id),known:reviewKnown,history:reviewHistory.map(h=>({...h,card:h.card.id})),difficulty:[...reviewDifficulty].map(([c,n])=>[c.id,n]),revealed:!!document.querySelector('#answer') && !document.querySelector('#answer').hidden,mode:reviewMode,tracking:reviewTracking}));
 const open=async()=>{await page.goto(base);await page.locator(`[data-id="${key}"][data-action="resume"]`).waitFor();await page.locator(`[data-id="${key}"][data-action="resume"]`).click();await page.locator('#reveal').waitFor({state:'attached'});await settle();};
 await page.goto(base);await page.locator(`[data-id="${key}"][data-action="review"]`).click();await page.locator('#reveal').waitFor();
 await rate('hard',1);await rate('good',2);await page.locator('#reveal').click();
 const before=await snapshot();assert.equal(before.known,1);assert.equal(before.queue.length,3);
 await page.reload();await page.locator(`[data-id="${key}"][data-action="resume"]`).click();await page.locator('#ratings').waitFor();
 assert.deepEqual(await snapshot(),before);
 await page.keyboard.press('Control+z');await hist(1);assert.equal(await page.evaluate(()=>reviewKnown),0);
 await rate('easy',2);await page.locator('#reveal').click();const restartState=await snapshot();
 // Restart the actual Python process, then reload and recover the precise round.
 await stop();await start();await open();assert.deepEqual(await snapshot(),restartState);
 // Browsing and edits must not overwrite the round. Card text is fetched again.
 await page.locator('#study button[onclick="leave()"]').first().click();
 await page.locator(`[data-id="${key}"][data-action="browse"]`).click();await page.locator('#cardlist').waitFor();
 await page.locator('.browse-card button').first().click();await page.locator('#editform textarea[name="front"]').fill('A editada');await page.locator('#editform textarea[name="back"]').press('Control+Enter');await page.waitForFunction(()=>!document.querySelector('#edit').open);
 await page.locator('#study button[onclick="leave()"]').first().click();
 await page.locator(`[data-id="${key}"][data-action="exam"]`).click();await page.locator('#config button').click();await page.locator('input[name="choice"]').first().check();await page.keyboard.press('Space');
 await page.locator('#study button[onclick="leave()"]').first().click();await page.reload();await page.locator(`[data-id="${key}"][data-action="resume"]`).click();await page.locator('#ratings').waitFor();assert.deepEqual(await snapshot(),restartState);
 // Explicit restarts require confirmation; cancel preserves the saved round.
 await page.locator('#study button[onclick="leave()"]').first().click();page.once('dialog',d=>d.dismiss());await page.locator(`[data-id="${key}"][data-action="restart"]`).click();
 assert.equal(await page.locator('#library').isVisible(),true);
 page.once('dialog',d=>d.accept());await page.locator(`[data-id="${key}"][data-action="restart"]`).click();await page.locator('#reveal').waitFor();assert.equal(await page.evaluate(()=>reviewKnown),0);assert.equal(await page.evaluate(()=>reviewHistory.length),0);
 // Lost rating response: persist the in-flight event across a reload, retry once.
 let dropped=false;let event;
 const drop=async route=>{event=route.request().postDataJSON().event_id;if(!dropped){dropped=true;await route.fetch();await route.abort('failed');}else await route.continue();};
 await page.route(/\/reviews$/,drop);await page.locator('#reveal').click();await page.locator('[data-rating="good"]').click();await page.locator('#retryreview').waitFor();await settle();
 await page.unroute(/\/reviews$/,drop);await open();await hist(1);assert.equal(await page.evaluate(()=>reviewKnown),1);
 assert.equal(await page.evaluate(()=>reviewHistory[0].eventId),event);
 // Finish the round, lose the final undo response, reload, and recover that card.
 await rate('good',2);await rate('good',3);await rate('good',4);await page.locator('#again').waitFor();
 let lostUndo=false;const dropUndo=async route=>{if(!lostUndo){lostUndo=true;await route.fetch();await route.abort('failed');}else await route.continue();};
 await page.route(/\/undo$/,dropUndo);await page.locator('#undoreview').click();await page.locator('#retryreview').waitFor();await settle();
 await page.unroute(/\/undo$/,dropUndo);await open();await hist(3);assert.equal(await page.evaluate(()=>reviewKnown),3);assert.equal(await page.evaluate(()=>reviewQueue.length),1);assert.equal(await page.locator('#answer').isVisible(),true);
 await rate('hard',4);await rate('good',5);await page.locator('#complicated').click();await page.locator('#reveal').waitFor();assert.equal(await page.evaluate(()=>reviewOnlyDifficult),true);
 const difficult=await snapshot();await open();assert.deepEqual(await snapshot(),difficult);assert.equal(await page.evaluate(()=>reviewFullDeck.length),4);
 // The current preference takes effect when resuming an existing round too.
 await page.locator('#study button[onclick="leave()"]').first().click();await page.locator('#spacedtoggle').uncheck();
 await page.locator(`[data-id="${key}"][data-action="resume"]`).click();await page.locator('#reveal').waitFor();
 assert.equal(await page.evaluate(()=>reviewTracking),false);
 await page.locator('#study button[onclick="leave()"]').first().click();await page.locator('#spacedtoggle').check();
 await page.locator(`[data-id="${key}"][data-action="resume"]`).click();await page.locator('#reveal').waitFor();
 assert.equal(await page.evaluate(()=>reviewTracking),true);
 // Tracking off still keeps an unlimited round, with no server review writes.
 await rate('good',1);await page.locator('#study button[onclick="leave()"]').first().click();await page.locator('#spacedtoggle').uncheck();
 await page.locator(`[data-id="${key}"][data-action="review"]`).click();await page.locator('#reveal').waitFor();await rate('easy',1);await rate('hard',2);await page.locator('#reveal').click();const off=await snapshot();assert.equal(off.tracking,false);
 await open();assert.deepEqual(await snapshot(),off);await page.keyboard.press('Control+z');await hist(1);
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 // Deleting decks also clears local rounds and leaves the preference intact.
 await page.locator('#study button[onclick="leave()"]').first().click();await page.locator('#deleteall').click();await page.locator('#deleteform button[type="submit"]').click();await page.waitForFunction(()=>!document.querySelector('#deleteconfirm').open);
 assert.equal(await page.evaluate(()=>Object.keys(localStorage).filter(k=>k.startsWith('ankimio.round.')).length),0);
 assert.equal(await page.evaluate(()=>localStorage.getItem('ankimio.spaced-review')),'off');
 assert.deepEqual(errors,[]);
 console.log('PASS: exact order/reveal/count/history after reload and real server restart; edit/exam isolation; restart confirmation; interrupted grade and final undo recovery; difficult subset; tracking off; mobile; deletion.');
 }finally{await stop();await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
