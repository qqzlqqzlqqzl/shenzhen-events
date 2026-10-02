const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
// Source bytes are read from the consumer's checkout; no production access.
const root=path.resolve(process.env.RADAR_SOURCE_ROOT||path.join(__dirname,'..'));
if(!fs.existsSync(path.join(root,'static/app.js')))throw new Error('Provide the Events checkout via RADAR_SOURCE_ROOT or the first argument');
const scripts=['vendor/fullcalendar.js','ui-state.js','render.js','planner.js','event-workflows.js','status.js','app.js'].map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n;\n');
const wait=()=>new Promise(r=>setTimeout(r,25));
async function ready(query='?view=all',initial={}){
 const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM(fs.readFileSync(path.join(root,'static/index.html'),'utf8'),{url:'https://fixture.test/events/'+query,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
 const w=dom.window,$=s=>w.document.querySelector(s);w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const state={expired:false,username:'alice',version:'A',failEvents:false,detailReads:0,safetyEpoch:0,guarded:false,unavailable:false};
 for(const [k,v] of Object.entries(initial))w.localStorage.setItem(k,v);
 const rows=()=>[0,1].map(i=>({id:String(i),title:state.version+' selected event '+i,start_at:'2026-10-05T10:00:00+08:00',end_at:'2026-10-05T12:00:00+08:00',status:(state.guarded&&i===0)||state.unavailable?'needs_review':'scheduled',stored_status:'scheduled',planning_eligible:!(state.guarded&&i===0)&&!state.unavailable,safety_epoch:state.safetyEpoch,safety:{available:!state.unavailable,guard_count:state.guarded&&i===0?1:0,warning:state.unavailable?'来源安全采集尚未完成；当前安排待重新核实':state.guarded&&i===0?'来源显示已取消；当前活动身份待复核':''},favorite:state.version==='A',feedback:state.version==='A'?'interested':'not_interested',feedback_tags:[],revision:state.version==='A'?1:2,event_type:'MusicEvent',event_type_label:'音乐',topics:['文化艺术'],attendance:'offline',district:'南山',sources:[],url:'https://example.com/'+i}));
 w.fetch=async(url,options)=>{const u=new URL(url,w.location.href),p=u.searchParams;calls.push(u.pathname+u.search);let data={};
 if(state.expired)return {ok:false,status:401,json:async()=>({detail:'expired fixture session'})};
 if(u.pathname.endsWith('/session')||u.pathname.endsWith('/login'))data={username:state.username};
 else if(u.pathname.endsWith('/stats'))data={recommended:2,upcoming:2,weekend:2,districts:['南山'],event_types:[{value:'MusicEvent',label:'音乐'}],topics:[{value:'文化艺术',label:'文化艺术'}]};
 else if(u.pathname.endsWith('/status'))data={sources:[],candidates:[],runs:[],budget:{calls:0,tokens:0},limits:{daily_calls:1,daily_tokens:1},db_bytes:0,retention_days:45,ics_url:'/events/calendar.ics?token=synthetic-calendar-bearer&favorites=true'};
 else if(u.pathname.endsWith('/events')){if(state.failEvents)throw new Error('fixture offline');if(state.unavailable)return {ok:false,status:503,json:async()=>({code:'safety_unavailable',detail:'captured response awaits recovery'})};data={safety_epoch:state.safetyEpoch,items:rows(),total:2,has_more:false,facets:{},excluded_long:{items:[],total:0}};}
 else if(u.pathname.includes('/event/')){state.detailReads++;data=rows().find(row=>row.id===u.pathname.split('/').at(-1))||rows()[0]}
 return {ok:true,status:200,json:async()=>data};};
 w.eval(scripts+'\n;window.probe={api,enter,load,openDetail,closeDetail,showLogin,beginFilterDraft,syncPersonal,invalidatePlanning,get authenticated(){return authenticated},get epoch(){return authEpoch},get records(){return records},get listSnapshot(){return listSnapshot},get calendarSnapshot(){return calendarSnapshot}};');
 await wait();await wait();return {w,$,state,calls,async expire(){state.expired=true;await w.probe.api('session').catch(()=>{});await wait()},close(){assert.deepEqual(errors,[]);w.close()}};
}

// Every bearer, account and event below is synthetic and fetch never reaches a server.
async function boundary(r,kind){
 if(kind==='401')await r.expire();
 else if(kind==='logout'){r.$('#logout').click();await wait()}
 else r.w.dispatchEvent(new r.w.PageTransitionEvent('pagehide',{persisted:true}));
 assert.equal(r.w.probe.authenticated,false);
 assert.equal(r.$('#login-panel').hidden,false);
 assert.equal(r.w.document.activeElement,r.$('#username'));
}
async function fresh(r,kind){
 r.state.expired=false;r.state.version='B';r.state.username='bob';
 // An event deep link is unrelated to the stale callback under test.
 r.w.history.replaceState({},'',r.w.location.pathname+'?view=all');
 if(kind==='bfcache')r.w.dispatchEvent(new r.w.PageTransitionEvent('pageshow',{persisted:true}));
 else await r.w.probe.enter({username:'bob'});
 await wait();await wait();
 assert.equal(r.w.probe.authenticated,true);
 assert.equal(r.w.probe.records.get('0').feedback,'not_interested');
}
function unchanged(r,before){
 assert.deepEqual([...r.w.probe.records].map(([id,e])=>[id,{...e}]),before.records);
 assert.equal(r.w.document.activeElement,before.focus);
 assert.equal(r.$('#toast').hidden,before.toastHidden);
 assert.equal(r.$('#toast').textContent,before.toastText);
 assert.equal(r.$('#copy-dialog').open,false);
 assert.equal(r.$('#copy-text').value,'');
 assert.equal(r.$('#compare-dialog').open,false);
 assert.equal(r.$('#compare-body').textContent,'');
 assert.equal(r.$('#detail').open,false);
 assert.deepEqual(r.prompts,[]);
}
function snapshot(r){return {records:[...r.w.probe.records].map(([id,e])=>[id,{...e}]),focus:r.w.document.activeElement,toastHidden:r.$('#toast').hidden,toastText:r.$('#toast').textContent}}
for(const kind of ['401','logout','bfcache']){
 test(`${kind} empties and closes session dialogs and disables detached comparison callbacks`,async()=>{
  const r=await ready();r.prompts=[];try{
   r.w.RadarEventWorkflows.toggle('0');r.w.RadarEventWorkflows.toggle('1');r.$('#compare-open').click();await wait();await wait();
   const stale=r.$('#compare-body button'),retained=stale.onclick;
   assert.equal(r.$('#compare-dialog').open,true);
   r.w.navigator.clipboard={writeText:async()=>{throw new Error('synthetic denial')}};
   await r.w.probe.openDetail('0');r.$('.detail-utilities button').click();await wait();
   assert.equal(r.$('#copy-dialog').open,true);assert.notEqual(r.$('#copy-text').value,'');
   r.$('#shortcut-help').click();r.w.probe.beginFilterDraft();
   await boundary(r,kind);
   for(const dialog of r.w.document.querySelectorAll('dialog'))assert.equal(dialog.open,false);
   assert.equal(r.$('#detail-body').textContent,'');assert.equal(r.$('#status-panel').textContent,'');
   assert.equal(r.w.probe.records.size,0);assert.equal(r.w.probe.listSnapshot,null);assert.equal(r.w.probe.calendarSnapshot,null);
   assert.equal(r.$('#compare-chips').textContent,'');assert.equal(r.$('#compare-bar').hidden,true);
   assert.equal(stale.onclick,null);unchanged(r,snapshot(r));
   await fresh(r,kind);const before=snapshot(r);retained();stale.click();await wait();unchanged(r,before);
   assert.equal(r.state.detailReads,3); // Only the initiating comparison/detail revalidation.
  }finally{r.close()}
 });
 for(const source of ['public','private'])for(const outcome of ['resolve','reject'])for(const relogin of [false,true]){
  test(`${source} clipboard ${outcome} after ${kind}${relogin?' and fresh login':''} has no UI effect`,async()=>{
   const r=await ready(source==='private'?'?view=status':'?view=all');r.prompts=[];try{
    r.w.prompt=(...args)=>r.prompts.push(args);let resolve,reject;const writes=[];
    r.w.navigator.clipboard={writeText:value=>{writes.push(value);return new Promise((a,b)=>{resolve=a;reject=b})}};
    if(source==='public')await r.w.probe.openDetail('0');
    const button=source==='private'?r.$('#copy-ics'):r.$('.detail-utilities button');const retained=button.onclick;button.click();
    assert.equal(writes.length,1);
    if(source==='private')assert.match(writes[0],/token=synthetic-calendar-bearer/);else assert.equal(writes[0].includes('synthetic-calendar-bearer'),false);
    await boundary(r,kind);if(relogin)await fresh(r,kind);
    const before=snapshot(r);if(outcome==='reject')reject(new Error('synthetic denial'));else resolve();await wait();unchanged(r,before);
    // A captured handler itself also belongs to its initiating session.
    retained();button.click();await wait();assert.equal(writes.length,1);unchanged(r,before);
   }finally{r.close()}
  });
 }
}
for(const source of ['public','private'])for(const outcome of ['resolve','reject']){
 test(`same-session ${source} clipboard ${outcome} preserves success/manual fallback`,async()=>{
  const r=await ready(source==='private'?'?view=status':'?view=all');try{
   const writes=[],prompts=[];r.w.prompt=(...args)=>prompts.push(args);
   r.w.navigator.clipboard={writeText:async text=>{writes.push(text);if(outcome==='reject')throw new Error('synthetic denial')}};
   if(source==='public')await r.w.probe.openDetail('0');
   const button=source==='private'?r.$('#copy-ics'):r.$('.detail-utilities button');button.click();await wait();assert.equal(writes.length,1);
   if(outcome==='resolve'){assert.equal(r.$('#toast').hidden,false);assert.match(r.$('#toast').textContent,/已复制/)}
   else if(source==='private'){assert.equal(prompts.length,1);assert.equal(prompts[0][1],writes[0])}
   else{assert.equal(r.$('#copy-dialog').open,true);assert.equal(r.$('#copy-text').value,writes[0]);assert.equal(r.w.document.activeElement,r.$('#copy-text'));r.$('#close-copy').click();assert.equal(r.$('#copy-dialog').open,false)}
  }finally{r.close()}
 });
}
test('same-session comparison uses current record and detail close restores focus',async()=>{
 const r=await ready();try{
  const title=r.$('.title-button');title.focus();await r.w.probe.openDetail('0');r.w.probe.closeDetail(false);assert.equal(r.w.document.activeElement,title);
  r.w.RadarEventWorkflows.toggle('0');r.w.RadarEventWorkflows.toggle('1');r.$('#compare-open').click();await wait();await wait();
  r.state.version='B';r.$('#compare-body button').click();await wait();
  assert.equal(r.$('#compare-dialog').open,false);assert.equal(r.$('#detail').open,true);assert.equal(r.w.probe.records.get('0').feedback,'not_interested');
  r.w.probe.closeDetail(false);r.w.document.body.dispatchEvent(new r.w.KeyboardEvent('keydown',{key:'?',bubbles:true}));assert.equal(r.$('#shortcut-dialog').open,true);
 }finally{r.close()}
});

test('point detail revalidates guarded cached records and personal writes preserve the veto',async()=>{
 const r=await ready();try{
  await r.w.probe.openDetail('0');assert.ok(r.$('#detail a[href$=".ics"]'));r.w.probe.closeDetail(false);
  r.state.guarded=true;r.state.safetyEpoch=1;await r.w.probe.openDetail('0');
  assert.match(r.$('#detail-body').textContent,/来源显示已取消/);assert.equal(r.$('#detail a[href$=".ics"]'),null);
  assert.match(r.w.RadarEventWorkflows.shareText(r.w.probe.records.get('0')),/来源显示已取消/);
  r.w.probe.syncPersonal('0',{favorite:false,planning_eligible:true,status:'scheduled',safety:null});
  assert.equal(r.w.probe.records.get('0').planning_eligible,false);assert.equal(r.w.probe.records.get('0').safety.guard_count,1);
 }finally{r.close()}
});

test('typed safety failure clears snapshots while a saved point remains readable without export',async()=>{
 const r=await ready();try{
  r.state.unavailable=true;r.state.safetyEpoch=1;await r.w.probe.load();
  assert.equal(r.w.probe.listSnapshot,null);assert.equal(r.$('#event-list').querySelectorAll('.event-card').length,0);
  await r.w.probe.openDetail('0');assert.match(r.$('#detail-body').textContent,/安全采集尚未完成/);
  assert.equal(r.$('#detail a[href$=".ics"]'),null);assert.equal(r.w.probe.records.get('0').planning_eligible,false);
 }finally{r.close()}
});

test('ordinary failed refresh and offline transition retain no export authority',async()=>{
 const r=await ready();try{
  await r.w.probe.openDetail('0');r.w.probe.closeDetail(false);r.state.failEvents=true;await r.w.probe.load();
  assert.equal(r.w.probe.records.get('0').planning_eligible,false);assert.equal(r.w.probe.records.get('0')._safety_pending,true);
  r.w.dispatchEvent(new r.w.Event('offline'));
  assert.equal(r.w.probe.listSnapshot,null);assert.equal(r.$('#detail a[href$=".ics"]'),null);
 }finally{r.close()}
});

test('comparison awaits point eligibility and refuses stale conflict claims',async()=>{
 const r=await ready();try{
  r.w.RadarEventWorkflows.toggle('0');r.w.RadarEventWorkflows.toggle('1');r.state.guarded=true;r.state.safetyEpoch=1;
  r.$('#compare-open').click();await wait();await wait();assert.match(r.$('#compare-body').textContent,/来源显示已取消/);
  assert.equal(r.w.RadarEventWorkflows.overlap(r.w.probe.records.get('0'),r.w.probe.records.get('1')),null);
 }finally{r.close()}
});
test('detached comparison chip and sequence handlers cannot change a fresh session',async()=>{
 const r=await ready();try{
  r.w.RadarEventWorkflows.toggle('0');const chip=r.$('#compare-chips button').onclick;
  await r.w.probe.openDetail('0');const next=r.$('[data-detail-step="1"]').onclick;
  await boundary(r,'logout');await fresh(r,'logout');r.w.RadarEventWorkflows.toggle('0');await r.w.probe.openDetail('0');
  await wait();const before=snapshot(r),query=r.w.location.search;chip();next();await wait();
  assert.equal(r.w.RadarEventWorkflows.has('0'),true);assert.equal(r.$('#detail-title').textContent,'B selected event 0');
  assert.deepEqual(snapshot(r),before);assert.equal(r.w.location.search,query);
 }finally{r.close()}
});
test('pending detail step cannot restore focus or rewrite history after a session change',async()=>{
 const r=await ready();try{
  await r.w.probe.openDetail('0');
  r.w.eval('window.originalOpenDetail=openDetail;openDetail=async()=>new Promise(resolve=>window.releaseStep=resolve)');
  r.$('[data-detail-step="1"]').click();
  await boundary(r,'logout');r.w.eval('openDetail=window.originalOpenDetail');await fresh(r,'logout');await r.w.probe.openDetail('1');
  r.w.history.replaceState({radar:true,radarModal:false,marker:'fresh-session'},'',r.w.location.href);r.$('#detail').scrollTop=57;
  await wait();const before=snapshot(r),query=r.w.location.search,historyState={...r.w.history.state};r.w.releaseStep();await wait();assert.deepEqual(snapshot(r),before);assert.equal(r.w.location.search,query);assert.deepEqual({...r.w.history.state},historyState);assert.equal(r.$('#detail').scrollTop,57);
 }finally{r.close()}
});
