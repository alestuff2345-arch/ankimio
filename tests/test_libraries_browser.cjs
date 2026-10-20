const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const repo=path.resolve(__dirname,'..');
(async()=>{
 const data=fs.mkdtempSync('/tmp/ankimio-libraries-browser-');
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
 const fixture=spawnSync(path.join(repo,'.venv/bin/python'),['-c',"import sys;sys.path.insert(0,'tests');from test_libraries import package;sys.stdout.buffer.write(package())"],{cwd:repo,env:{...env,ANKIMIO_TEST_DATABASE_URL:''}});
 assert.equal(fixture.status,0,fixture.stderr.toString());const raw=fixture.stdout;
 const main=(await api('/api/decks',{name:'Biología original'})).id;
 for(const front of ['Original A','Original B'])await api(`/api/decks/${main}/cards`,{front,back:front+' respuesta'});
 await page.goto(base);await page.locator(`[data-id="${main}"]`).first().waitFor();
 async function createSection(name){
  await page.locator('#newlibrary').click();await page.locator('#libraryform input[name="name"]').fill(name);await page.locator('#libraryform button[type="submit"]').click();
  await page.waitForFunction(name=>!document.querySelector('#librarydialog').open && document.querySelector('#libraryheading').textContent===name,name);
  await page.waitForFunction(()=>document.querySelectorAll('#decks article').length===0);
  return page.evaluate(()=>activeLibrary);
 }
 async function navigate(id){await page.locator(`[data-library="${id}"]`).click();await page.waitForFunction(id=>activeLibrary===id,id);}
 async function upload(){await page.locator('#file').setInputFiles({name:'biologia.colpkg',mimeType:'application/octet-stream',buffer:raw});await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('tarjetas importadas'));}
 const med=await createSection('Medicina');assert.notEqual(med,'main');assert.equal(await page.locator(`[data-id="${main}"]`).count(),0);
 await upload();await page.waitForFunction(()=>document.querySelectorAll('#decks article').length===2);
 const medImported=await api('/api/decks?library='+med);assert.equal(medImported.length,2);
 await page.getByRole('button',{name:'＋ Crear un mazo',exact:true}).click();await page.locator('#newform input[name="name"]').fill('Anatomía');await page.locator('#newform button.primary').click();
 await page.waitForFunction(()=>document.querySelectorAll('#decks article').length===3);
 const manual=(await api('/api/decks?library='+med)).find(d=>d.name==='Anatomía').id;
 await page.locator(`[data-id="${manual}"][data-action="add"]`).click();
 for(const [front,back] of [['¿Qué célula transmite impulsos?','Neurona'],['¿Qué conecta los hemisferios?','Cuerpo calloso']]){
  await page.locator('#addform textarea[name="front"]').fill(front);await page.locator('#addform textarea[name="back"]').fill(back);await page.locator('#addform textarea[name="back"]').press('Control+Enter');await page.waitForFunction(()=>document.querySelector('#cardstatus').textContent.includes('Tarjeta guardada'));
 }
 await page.locator('#add button[type="button"]').click();
 await page.locator(`[data-id="${manual}"][data-action="review"]`).click();await page.locator('#reveal').waitFor();
 await page.locator('#reveal').click();await page.locator('[data-rating="good"]').click();await page.waitForFunction(()=>!reviewBusy && reviewKnown===1);
 const pending=await page.evaluate(()=>reviewQueue.map(c=>c.id));
 const english=await createSection('Inglés');await upload();await page.waitForFunction(()=>document.querySelectorAll('#decks article').length===2);
 const englishDecks=await api('/api/decks?library='+english);assert.equal(englishDecks.length,2);assert.equal(englishDecks.some(e=>medImported.some(m=>m.id===e.id)),false);
 const englishCard=englishDecks[0].id;
 await page.locator(`[data-id="${englishCard}"][data-action="review"]`).click();await page.locator('#reveal').waitFor();await page.locator('#reveal').click();await page.locator('[data-rating="hard"]').click();await page.waitForFunction(()=>!reviewBusy && reviewHistory.length===1);
 await navigate(med);await page.locator(`[data-id="${manual}"][data-action="resume"]`).click();await page.locator('#reveal').waitFor();assert.deepEqual(await page.evaluate(()=>reviewQueue.map(c=>c.id)),pending);
 await page.keyboard.press('Control+z');await page.waitForFunction(()=>!reviewBusy && reviewKnown===0);
 await navigate(english);await page.reload();await page.locator(`[data-library="${english}"][aria-current="page"]`).waitFor();assert.equal(await page.locator('#libraryheading').textContent(),'Inglés');await page.locator(`[data-id="${englishCard}"][data-action="resume"]`).waitFor();
 // Imported media and editing work in the selected section.
 await page.locator(`[data-id="${englishCard}"][data-action="browse"]`).click();await page.locator('.browse-card img').waitFor();await page.waitForFunction(()=>[...document.querySelectorAll('.browse-card img')].every(i=>i.complete && i.naturalWidth>0));
 await page.locator('.browse-card button').first().click();await page.locator('#editform textarea[name="front"]').fill('Figura editada');await page.locator('#editform textarea[name="back"]').press('Control+Enter');await page.waitForFunction(()=>!document.querySelector('#edit').open);
 await navigate(med);await page.locator(`[data-id="${manual}"][data-action="exam"]`).click();await page.locator('#config button').click();
 for(let i=0;i<2;i++){await page.locator('input[name="choice"]').first().check();await page.keyboard.press('Space');}await page.locator('#score').waitFor();
 await navigate(med);await page.locator(`[data-id="${manual}"][data-action="resume"]`).waitFor();
 fs.mkdirSync(path.join(repo,'artifacts'),{recursive:true});await page.screenshot({path:path.join(repo,'artifacts/secciones-biblioteca.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});assert.equal(await page.locator('#newlibrary').isVisible(),true);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.locator(`[data-library="${english}"]`).click();await page.locator(`[data-id="${englishCard}"][data-action="resume"]`).waitFor();
 await page.screenshot({path:path.join(repo,'artifacts/secciones-movil.png'),fullPage:true});
 // Deleting English must preserve main and Medicine, their images and saved rounds.
 await page.locator('#deleteall').click();assert.match(await page.locator('#deletetitle').innerText(),/Inglés/);await page.locator('#deleteform button[type="submit"]').click();await page.waitForFunction(()=>!document.querySelector('#deleteconfirm').open);
 assert.equal((await api('/api/decks?library='+english)).length,0);assert.equal((await api('/api/decks?library='+med)).length,3);assert.ok((await api('/api/decks')).some(d=>d.id===main));
 assert.notEqual(await page.evaluate(id=>RoundStore.read(id),manual),null);assert.equal(await page.evaluate(id=>RoundStore.read(id),englishCard),null);
 const surviving=await api(`/api/decks/${medImported[0].id}/study`);assert.equal(Object.keys(surviving.images).length,1);
 // A request in flight remains bound to the section in which import began.
 let release,held;const gate=new Promise(r=>release=r),intercepted=new Promise(r=>held=r);
 const hold=async route=>{const response=await route.fetch();held();await gate;await route.fulfill({response});};await page.route('**/api/import',hold);
 await page.locator('#file').setInputFiles({name:'late.colpkg',mimeType:'application/octet-stream',buffer:raw});await intercepted;await navigate(med);release();await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('mazos de «Inglés»'));
 await page.unroute('**/api/import',hold);assert.equal(await page.locator('#libraryheading').textContent(),'Medicina');assert.equal((await api('/api/decks?library='+english)).length,2);
 // User names are text, not executable markup, and survive a reload.
 const escaped=await createSection('<b>Mi sección</b>');assert.equal(await page.locator(`[data-library="${escaped}"] b`).count(),0);assert.match(await page.locator(`[data-library="${escaped}"]`).textContent(),/<b>Mi sección<\/b>/);
 await page.reload();await page.locator(`[data-library="${escaped}"][aria-current="page"]`).waitFor();assert.deepEqual(errors,[]);
 console.log('PASS: named sidebar sections, original data, independent manual decks and Anki images, saved rounds, undo, editing, exam Space, scoped deletion, interrupted import navigation, safe names, selection persistence and mobile.');
 }finally{await stop();await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
