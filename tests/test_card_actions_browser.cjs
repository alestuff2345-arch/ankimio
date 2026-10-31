const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const repo=path.resolve(__dirname,'..');
(async()=>{
 const data=fs.mkdtempSync('/tmp/ankimio-card-actions-');
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
 const api=async(path,body,method='post')=>{const r=body===undefined?await context.request.get(base+path):await context.request[method](base+path,{data:body});assert.ok(r.ok(),await r.text());return r.json();};
 const fixture=spawnSync(path.join(repo,'.venv/bin/python'),['-c',"import sys;sys.path.insert(0,'tests');from test_libraries import package;sys.stdout.buffer.write(package())"],{cwd:repo,env:{...env,ANKIMIO_TEST_DATABASE_URL:''}});assert.equal(fixture.status,0,fixture.stderr.toString());
 const imported=await context.request.post(base+'/api/import',{multipart:{file:{name:'sample.colpkg',mimeType:'application/octet-stream',buffer:fixture.stdout}}});assert.ok(imported.ok(),await imported.text());
 const decks=await api('/api/decks'),key=decks[0].id,other=decks[1].id;
 const bundle=await api(`/api/decks/${key}/study`),original=bundle.cards[0],image=Object.keys(bundle.images)[0];
 const markup='<style>.card { font-size: 20px; }</style>\n\n\n\n<strong>hacen proteínas con actividad catalítica</strong>\r\namilasa, lipasa\n<img src="'+image+'">\n\n';
 await api(`/api/decks/${key}/cards/${original.id}`,{front:'Enzimas',back:markup},'patch');
 const stored=(await api(`/api/decks/${key}/cards`))[0].back;
 for(const front of ['A','B'])await api(`/api/decks/${key}/cards`,{front,back:'Respuesta '+front});
 await page.goto(base);await page.locator(`[data-id="${key}"][data-action="browse"]`).click();await page.locator('#cardsearch').fill('Enzimas');await page.locator('.browse-card button[data-edit]').click();
 assert.equal(await page.locator('#editform textarea[name="back"]').inputValue(),'hacen proteínas con actividad catalítica\namilasa, lipasa');
 fs.mkdirSync(path.join(repo,'artifacts'),{recursive:true});await page.locator('#edit').screenshot({path:path.join(repo,'artifacts/editor-sin-espacio.png')});
 await page.locator('#editform button[type="submit"]').click();await page.waitForFunction(()=>!document.querySelector('#edit').open);
 assert.equal((await api(`/api/decks/${key}/cards`)).find(c=>c.id===original.id).back,stored.trim());
 await page.locator('.browse-card button[data-edit]').click();await page.locator('#editform textarea[name="back"]').fill('Respuesta actualizada\nSegunda línea');await page.locator('#editform textarea[name="back"]').press('Control+Enter');await page.waitForFunction(()=>!document.querySelector('#edit').open);
 const changed=(await api(`/api/decks/${key}/cards`)).find(c=>c.id===original.id).back;assert.ok(changed.startsWith('Respuesta actualizada<br>Segunda línea'));assert.ok(changed.includes(image));
 await page.locator('#study button[onclick="leave()"]').first().click();await page.locator(`[data-id="${key}"][data-action="review"]`).click();await page.locator('#reveal').waitFor();
 await page.locator('#reveal').click();await page.locator('[data-rating="good"]').click();await page.waitForFunction(()=>!reviewBusy && reviewKnown===1);
 const learned=await page.evaluate(()=>reviewHistory[0].card.id),target=await page.evaluate(()=>reviewQueue[0].id);
 await page.locator('#study').screenshot({path:path.join(repo,'artifacts/tarjeta-eliminar.png')});
 page.once('dialog',d=>d.dismiss());await page.locator('#deletecurrent').click();assert.equal(await page.evaluate(()=>reviewQueue[0].id),target);assert.equal((await api(`/api/decks/${key}/cards`)).length,3);
 page.once('dialog',d=>d.accept());await page.locator('#deletecurrent').click();await page.waitForFunction(()=>!reviewBusy && document.querySelector('#notice').textContent.includes('Tarjeta eliminada'));
 assert.equal((await api(`/api/decks/${key}/cards`)).length,2);assert.equal(await page.evaluate(()=>reviewKnown),1);assert.equal(await page.evaluate(()=>reviewQueue.length),1);assert.equal(await page.locator('#undoreview').isDisabled(),true);
 await page.reload();await page.locator(`[data-id="${key}"][data-action="resume"]`).click();await page.locator('#reveal').waitFor();assert.equal(await page.evaluate(()=>reviewKnown),1);assert.equal(await page.evaluate(()=>reviewQueue.length),1);assert.equal(await page.evaluate(id=>reviewFullDeck.some(c=>c.id===id),target),false);
 await page.locator('#study button[onclick="leave()"]').first().click();await page.locator(`[data-id="${key}"][data-action="browse"]`).click();await page.locator('#cardlist').waitFor();
 page.once('dialog',d=>d.accept());await page.locator(`[data-delete="${learned}"]`).click();await page.waitForFunction(()=>!reviewBusy && browseCards.length===1);
 await page.locator('#study button[onclick="leave()"]').first().click();await page.locator(`[data-id="${key}"][data-action="resume"]`).click();await page.locator('#reveal').waitFor();assert.equal(await page.evaluate(()=>reviewKnown),0);assert.equal(await page.evaluate(()=>reviewQueue.length),1);
 // Server commits deletion but its response is lost. Repeating safely removes the stale UI.
 let lost=false;const drop=async route=>{if(route.request().method()!=='DELETE')return route.continue();if(!lost){lost=true;await route.fetch();await route.abort('failed');}else await route.continue();};
 await page.route(/\/api\/decks\/[^/]+\/cards\/[^/]+$/,drop);page.once('dialog',d=>d.accept());await page.locator('#deletecurrent').click();await page.waitForFunction(()=>!reviewBusy && document.querySelector('#notice').textContent.includes('No se pudo confirmar la eliminación'));
 assert.equal(await page.locator('#deletecurrent').count(),1);page.once('dialog',d=>d.accept());await page.locator('#deletecurrent').click();await page.waitForFunction(()=>!reviewBusy && document.querySelector('#study h1')?.textContent==='Este mazo ya no tiene tarjetas.');
 assert.equal(await page.evaluate(id=>RoundStore.read(id),key),null);await page.unroute(/\/api\/decks\/[^/]+\/cards\/[^/]+$/,drop);
 assert.equal((await context.request.get(base+image)).status(),200);assert.equal((await api(`/api/decks/${other}/cards`)).length,1);
 // A card removed from another tab must not invalidate the remaining saved round.
 for(const front of ['C','D','E'])await api(`/api/decks/${key}/cards`,{front,back:'Respuesta '+front});
 await page.locator('#study button[onclick="leave()"]').first().click();await page.locator(`[data-id="${key}"][data-action="review"]`).click();await page.locator('#reveal').waitFor();
 await page.locator('#reveal').click();await page.locator('[data-rating="good"]').click();await page.waitForFunction(()=>!reviewBusy && reviewKnown===1);
 const external=await page.evaluate(()=>reviewQueue[0].id);await page.locator('#reveal').click();await api(`/api/decks/${key}/cards/${external}`,{confirm:true},'delete');
 await page.reload();await page.locator(`[data-id="${key}"][data-action="resume"]`).click();await page.locator('#reveal').waitFor();assert.equal(await page.evaluate(()=>reviewQueue.length),1);assert.equal(await page.evaluate(()=>reviewKnown),1);assert.equal(await page.locator('#answer').isVisible(),false);
 assert.equal(await page.locator('#undoreview').isDisabled(),true);
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);assert.equal(await page.locator('#deletecurrent').isVisible(),true);
 assert.deepEqual(errors,[]);
 console.log('PASS: editor trims blank edges, preserves internal newlines/unchanged markup/images; delete confirmation/cancel, scoped persistence, queue/known/history repair, saved round, explorer, last card, lost response retry, external deletions, shared image safety and mobile.');
 }finally{await stop();await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
