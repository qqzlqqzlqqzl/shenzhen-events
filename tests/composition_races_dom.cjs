/* Independent PR90 state/ownership checks. DOM fixture only: no layout, pixels,
 * native keyboard, browser Back UI, or 200% visual acceptance is claimed. */
'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(process.env.RADAR_SOURCE_ROOT||path.join(__dirname,'..'));
const html=fs.readFileSync(path.join(root,'static/index.html'),'utf8');
const scripts=['vendor/fullcalendar.js','ui-state.js','render.js','planner.js','event-workflows.js','status.js','app.js'].map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n;\n');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,label){for(let i=0;i<160;i++){if(check())return;await sleep(5)}throw Error('Fixture did not settle: '+label)}
const clone=x=>JSON.parse(JSON.stringify(x));
async function fixture({signedIn=true,query='?view=all',pageSize=0}={}){
 const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM(html,{url:'https://fixture.test/events/'+query,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
 const w=dom.window,$=s=>w.document.querySelector(s);
 w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const state={signedIn,owner:'alice',deferPreference:null,deferEvent:null,deferPage:null};
 const rows=new Map(Array.from({length:pageSize?6:4},(_,i)=>[String(i),{id:String(i),title:'合成长标题候选 '+i+' / '.repeat(25)+' bounded fixture',start_at:'2026-10-10T10:00:00+08:00',end_at:'2026-10-10T12:00:00+08:00',status:'scheduled',favorite:i===0,feedback:'',feedback_tags:[],revision:0,event_type:'ConferenceEvent',event_type_label:'会议',topics:['科技'],attendance:'offline',location:'合成地点',district:'南山',sources:[],url:'https://example.com/'+i}]));
 const reply=(data,status=200)=>({ok:status>=200&&status<300,status,json:async()=>clone(data)});
 w.fetch=async(url,options={})=>{
  const u=new URL(url,w.location.href),p=u.pathname,body=options.body?JSON.parse(options.body):null;calls.push({path:p,search:u.search,method:options.method||'GET',body});
  if(!state.signedIn)return reply({detail:'synthetic session expired'},401);
  if(p.endsWith('/session')||p.endsWith('/login'))return reply({username:state.owner});
  if(p.endsWith('/logout'))return reply({ok:true});
  if(p.endsWith('/stats'))return reply({recommended:rows.size,upcoming:rows.size,weekend:rows.size,districts:['南山'],event_types:[{value:'ConferenceEvent',label:'会议'}],topics:[{value:'科技',label:'科技'}]});
  if(p.endsWith('/status'))return reply({sources:[{id:'current',name:'Synthetic current source',url:'https://example.com/source',status:'ok',retry:null,coverage:{version:1,visible:1,extracted:1,unique:1,shenzhen_candidates:1,admitted:1,stored_events:1}}],candidates:[],runs:[],budget:{calls:0,tokens:0},limits:{daily_calls:1,daily_tokens:1},db_bytes:0,retention_days:45,ics_url:'/events/calendar.ics'});
  if(p.endsWith('/events')){
   const all=[...rows.values()],offset=Number(u.searchParams.get('offset')||0),items=pageSize?all.slice(offset,offset+pageSize):all;
   const data={items,total:all.length,has_more:!!pageSize&&offset+items.length<all.length,facets:{},excluded_long:{items:[],total:0}};
   if(state.deferPage){const pending=state.deferPage({offset,data,signal:options.signal});if(pending)return await pending;}
   return reply(data);
  }
  if(p.includes('/event/')){const id=p.split('/').at(-1),data=clone(rows.get(id));if(state.deferEvent){const pending=state.deferEvent({id,data});if(pending)return await pending;}return reply(data);}
  if(p.includes('/viewed/'))return reply({viewed_at:'2026-10-03T10:00:00Z'});
  if(p.includes('/preferences/')){
   const id=p.split('/').at(-1),current=rows.get(id),result={...current,...body,revision:current.revision+1};delete result.expected_revision;
   if(state.deferPreference)return await new Promise(resolve=>state.deferPreference({id,result,resolve:()=>{rows.set(id,result);resolve(reply(result))}}));
   rows.set(id,result);return reply(result);
  }
  throw Error('Unexpected fixture request: '+p);
 };
 w.eval(scripts+'\n;window.probe={api,enter,load,showLogin,openDetail,closeDetail,restoreNavigation,loadStatus,updateFeedback,setFeedbackSignal,get authenticated(){return authenticated},get busy(){return busy},get undo(){return undoFeedback},get records(){return records},get feedbackSaving(){return feedbackSaving}};');
 try {
  if(signedIn)await until(()=>w.probe.authenticated&&!w.probe.busy&&(query.includes('view=status')?!!$('[data-source="current"]'):w.probe.records.size===(pageSize?Math.min(pageSize,rows.size):rows.size)),'signed-in view');
  else await until(()=>!$('#login-panel').hidden,'login form');
 } catch(error) {w.probe.showLogin();await sleep(15);dom.window.close();throw error}
 const choose=(n=2)=>{for(let i=0;i<n;i++)$('[data-compare="'+i+'"]').click()};
 const mutate=async(id='0',signal='interested')=>{await w.probe.openDetail(id);$('[data-feedback-signal="'+signal+'"]').click();await until(()=>!w.probe.feedbackSaving.size&&!!w.probe.undo,'feedback settlement')};
 return {w,$,errors,calls,state,rows,choose,mutate,holdNextPage(){
  let release,reject,offset,signal;
  state.deferPage=page=>{state.deferPage=null;offset=page.offset;signal=page.signal;return new Promise((resolve,fail)=>{release=()=>resolve(reply(page.data));reject=fail})};
  return {get pending(){return !!release},get offset(){return offset},get aborted(){return signal?.aborted},release(){release()},fail(){reject(new Error('synthetic page failure'))},abort(){reject(new w.DOMException('Aborted obsolete request','AbortError'))}};
 },holdNextEvent(){let release,reject;state.deferEvent=({id,data})=>{state.deferEvent=null;return new Promise((resolve,fail)=>{release=()=>resolve(reply(data));reject=fail})};return {get pending(){return !!release},release(){release()},fail(){reject(new Error('synthetic older point read failed'))}}},async settle(){await until(()=>!w.probe.busy&&!w.probe.feedbackSaving.size,'idle');await sleep(15)},async close(){w.probe.showLogin();await sleep(15);assert.deepEqual(errors,[]);dom.window.close()}};
}
for(const outcome of ['abort','success']){
 test('obsolete restore cannot reopen event details after status navigation: '+outcome,async()=>{
  const r=await fixture();try{
   const held=r.holdNextPage(),before=r.calls.length;
   r.w.history.replaceState({},'','/events/?view=all&q=older&event=0');
   r.w.probe.restoreNavigation();await until(()=>held.pending,'restored list held');
   r.$('#manage-sources').click();await until(()=>!!r.$('[data-source="current"]'),'new status view');
   assert.equal(held.aborted,true,'new navigation actually cancels the old transport');
   if(outcome==='abort')held.abort();else held.release();await r.settle();
   assert.equal(new URL(r.w.location.href).searchParams.get('view'),'status');
   assert.equal(new URL(r.w.location.href).searchParams.has('event'),false);
   assert.equal(r.calls.slice(before).filter(c=>c.path.endsWith('/event/0')).length,0);
   assert.equal(r.$('#detail').open,false);
  }finally{await r.close()}
 });
}
test('current restore opens its event after the matching list settles',async()=>{
 const r=await fixture();try{
  const held=r.holdNextPage();r.w.history.replaceState({},'','/events/?view=all&q=current&event=0');
  r.w.probe.restoreNavigation();await until(()=>held.pending,'current restored list held');
  held.release();await until(()=>r.$('#detail').open,'current restored detail opened');
  assert.equal(new URL(r.w.location.href).searchParams.get('event'),'0');
  assert.equal(r.calls.filter(c=>c.path.endsWith('/event/0')).length,1);
 }finally{await r.close()}
});
test('a newer detail retires a pending history restore even in the same list view',async()=>{
 const r=await fixture();try{
  const held=r.holdNextPage(),before=r.calls.length;
  r.w.history.replaceState({},'','/events/?view=all&q=older&event=0');
  r.w.probe.restoreNavigation();await until(()=>held.pending,'older detail restore held');
  await r.w.probe.openDetail('1');held.release();await r.settle();
  assert.equal(new URL(r.w.location.href).searchParams.get('event'),'1');
  assert.equal(r.calls.slice(before).filter(c=>c.path.endsWith('/event/0')).length,0);
  assert.equal(r.$('#detail-title').textContent,r.rows.get('1').title);
 }finally{await r.close()}
});
test('older async comparison cannot reopen a dialog after a newer comparison was closed',async()=>{
 const r=await fixture();try{
  r.choose();const held=r.holdNextEvent();r.$('#compare-open').click();await until(()=>held.pending,'first comparison read held');
  r.$('#compare-open').click();await until(()=>r.$('#compare-dialog').open,'newer comparison open');r.$('#close-compare').click();assert.equal(r.$('#compare-dialog').open,false);
  held.release();await sleep(60);assert.equal(r.$('#compare-dialog').open,false,'a dismissed comparison must not reopen from an older response');
 }finally{await r.close()}
});
test('clearing candidates retires an in-flight comparison and cannot resurrect ghost selection',async()=>{
 const r=await fixture();try{
  r.choose();const held=r.holdNextEvent();r.$('#compare-open').click();await until(()=>held.pending,'comparison read held');
  r.$('#compare-clear').click();assert.equal(r.$('#compare-chips').children.length,0);assert.equal(r.$('#compare-bar').hidden,true);
  held.release();await sleep(60);assert.equal(r.w.RadarEventWorkflows.has('0'),false,'cleared candidate must not be reinserted');assert.equal(r.$('#compare-dialog').open,false);
 }finally{await r.close()}
});
test('fresh detail read begun before a confirmed favorite write cannot roll back personal revision',async()=>{
 const r=await fixture();try{
  const held=r.holdNextEvent(),opening=r.w.probe.openDetail('0');await until(()=>held.pending,'detail read held');
  r.$('[data-save="0"]').click();await until(()=>r.rows.get('0').favorite===false&&r.w.probe.records.get('0').favorite===false&&r.w.probe.records.get('0').revision===1,'favorite write confirmed in model and rendered client');assert.equal(r.w.probe.records.get('0').favorite,false);
  held.release();await opening;await sleep(20);assert.equal(r.w.probe.records.get('0').favorite,false,'older detail must not restore confirmed removed favorite');assert.equal(r.w.probe.records.get('0').revision,1);assert.equal(r.$('#detail [data-save="0"]').getAttribute('aria-pressed'),'false');
 }finally{await r.close()}
});
for(const action of ['chip-remove','toggle-remove','dialog-close','dialog-cancel','safety-invalidate']){
 test('comparison retires pending point reads after '+action,async()=>{
  const r=await fixture();try{
   r.choose();const held=r.holdNextEvent();r.$('#compare-open').click();await until(()=>held.pending,'comparison point read held');
   if(action==='chip-remove')r.$('#compare-chips button').click();
   if(action==='toggle-remove')r.$('[data-compare="0"]').click();
   if(action==='dialog-close')r.$('#compare-dialog').dispatchEvent(new r.w.Event('close'));
   if(action==='dialog-cancel')r.$('#compare-dialog').dispatchEvent(new r.w.Event('cancel'));
   if(action==='safety-invalidate')r.w.RadarEventWorkflows.invalidateSafety();
   held.release();await sleep(60);assert.equal(r.$('#compare-dialog').open,false);
   if(action.endsWith('remove'))assert.equal(r.w.RadarEventWorkflows.has('0'),false);
  }finally{await r.close()}
 });
}
test('comparison point read preserves confirmed personal revision and the fresh safety veto',async()=>{
 const r=await fixture();try{
  r.choose();r.rows.get('0').planning_eligible=false;r.rows.get('0').safety={warning:'Synthetic current cancellation'};
  const held=r.holdNextEvent();r.$('#compare-open').click();await until(()=>held.pending,'comparison point read held');
  r.$('[data-save="0"]').click();await until(()=>r.rows.get('0').favorite===false&&r.w.probe.records.get('0').favorite===false&&r.w.probe.records.get('0').revision===1,'favorite committed');
  held.release();await until(()=>r.$('#compare-dialog').open,'comparison finished');
  const current=r.w.probe.records.get('0');assert.equal(current.favorite,false);assert.equal(current.revision,1);
  assert.equal(current.planning_eligible,false);assert.equal(current.safety.warning,'Synthetic current cancellation');
 }finally{await r.close()}
});

test('fresh comparison point read cannot roll back a confirmed favorite and revision',async()=>{
 const r=await fixture();try{
  r.choose();const held=r.holdNextEvent();r.$('#compare-open').click();await until(()=>held.pending,'comparison read held');
  r.$('[data-save="0"]').click();await until(()=>r.rows.get('0').favorite===false&&r.w.probe.records.get('0').favorite===false&&r.w.probe.records.get('0').revision===1,'favorite confirmed');
  held.release();await until(()=>r.$('#compare-dialog').open,'comparison completed');assert.equal(r.w.probe.records.get('0').favorite,false,'comparison point read must preserve confirmed personal state');assert.equal(r.w.probe.records.get('0').revision,1);
 }finally{await r.close()}
});
test('older detail failure cannot clear the successful newer detail URL',async()=>{
 const r=await fixture();try{
  const held=r.holdNextEvent(),older=r.w.probe.openDetail('0');await until(()=>held.pending,'old detail read held');
  await r.w.probe.openDetail('1');assert.equal(new URL(r.w.location.href).searchParams.get('event'),'1');assert.equal(r.$('#detail').open,true);
  held.fail();await older;await sleep(20);assert.equal(new URL(r.w.location.href).searchParams.get('event'),'1','obsolete failure must not remove newer detail history');assert.match(r.$('#detail-title').textContent,/候选 1/);
 }finally{await r.close()}
});

test('ten overlapping same-event opens share one GET, history write and viewed write',async()=>{
 const r=await fixture();try{
  const held=r.holdNextEvent(),before=r.calls.length;
  const openings=Array.from({length:10},()=>r.w.probe.openDetail('0'));
  await until(()=>held.pending,'same-event detail held');
  assert.equal(r.calls.slice(before).filter(c=>c.path.endsWith('/event/0')).length,1);
  held.release();await Promise.all(openings);await sleep(20);
  assert.equal(r.$('#detail').open,true);
  assert.equal(r.calls.slice(before).filter(c=>c.path.endsWith('/viewed/0')).length,1);
  assert.equal(new URL(r.w.location.href).searchParams.get('event'),'0');
  r.w.probe.closeDetail(false);await r.w.probe.openDetail('0');
  assert.equal(r.calls.slice(before).filter(c=>c.path.endsWith('/event/0')).length,2,'settled detail is always revalidated');
 }finally{await r.close()}
});
test('closing and reopening the same event starts a fresh operation and retires the old callback',async()=>{
 const r=await fixture();try{
  const held=r.holdNextEvent(),older=r.w.probe.openDetail('0');
  await until(()=>held.pending,'older same-event detail held');
  r.w.probe.closeDetail(false);r.rows.get('0').title='Fresh same-event title';
  await r.w.probe.openDetail('0');assert.equal(r.$('#detail-title').textContent,'Fresh same-event title');
  held.release();await older;assert.equal(r.$('#detail-title').textContent,'Fresh same-event title');
  assert.equal(r.calls.filter(c=>c.path.endsWith('/event/0')).length,2);
 }finally{await r.close()}
});
test('a failed shared detail operation permits an immediate fresh retry',async()=>{
 const r=await fixture();try{
  const held=r.holdNextEvent(),first=r.w.probe.openDetail('0'),second=r.w.probe.openDetail('0');
  await until(()=>held.pending,'failed shared detail held');held.fail();await Promise.all([first,second]);
  assert.equal(r.$('#detail').open,false);
  await r.w.probe.openDetail('0');assert.equal(r.$('#detail').open,true);
  assert.equal(r.calls.filter(c=>c.path.endsWith('/event/0')).length,2);
 }finally{await r.close()}
});
test('a different navigation intent does not reuse a pending same-event history operation',async()=>{
 const r=await fixture();try{
  const held=r.holdNextEvent(),older=r.w.probe.openDetail('0',true);
  await until(()=>held.pending,'push detail held');
  await r.w.probe.openDetail('0',false);held.release();await older;
  assert.equal(r.calls.filter(c=>c.path.endsWith('/event/0')).length,2);
  assert.equal(new URL(r.w.location.href).searchParams.has('event'),false);
  assert.equal(r.$('#detail').open,true);
 }finally{await r.close()}
});

test('append keeps its loading button visible and disabled until pagination settles',async()=>{
 const r=await fixture({pageSize:2});try{
  assert.equal(r.$('#more').hidden,false);
  const held=r.holdNextPage(),before=r.calls.length,pending=r.w.probe.load(true);
  await until(()=>held.pending,'append response held');
  assert.equal(r.$('#more').hidden,false);assert.equal(r.$('#more').disabled,true);assert.equal(r.$('#more').textContent,'正在加载…');
  r.$('#more').click();await r.w.probe.load(true);
  assert.equal(r.calls.slice(before).filter(c=>c.path.endsWith('/events')).length,1,'overlapping append must not request twice');
  assert.equal(r.$('#event-list').querySelectorAll('.event-card').length,2);
  held.release();await pending;await r.settle();
  assert.equal(r.$('#event-list').querySelectorAll('.event-card').length,4);
  assert.equal(r.$('#more').hidden,false);assert.equal(r.$('#more').disabled,false);assert.equal(r.$('#more').textContent,'再看看更多 ↓');
  await r.w.probe.load(true);await r.settle();
  assert.equal(r.$('#event-list').querySelectorAll('.event-card').length,6);
  assert.equal(r.$('#more').hidden,true);assert.equal(r.$('#more').disabled,false);
 }finally{await r.close()}
});
test('failed append keeps its button usable and retry exposes the loading state',async()=>{
 const r=await fixture({pageSize:2});try{
  const failed=r.holdNextPage(),pending=r.w.probe.load(true);await until(()=>failed.pending,'failed append held');failed.fail();await pending;
  assert.equal(r.$('#event-list').querySelectorAll('.event-card').length,2);
  assert.equal(r.$('#more').hidden,false);assert.equal(r.$('#more').disabled,false);assert.equal(r.$('#more').textContent,'再看看更多 ↓');
  assert.equal(r.$('#notice').hidden,false);
  const retried=r.holdNextPage();r.$('[data-action="retry"]').click();await until(()=>retried.pending,'append retry held');
  assert.equal(retried.offset,failed.offset,'retry must request the failed page again');
  assert.equal(r.$('#more').hidden,false);assert.equal(r.$('#more').disabled,true);assert.equal(r.$('#more').textContent,'正在加载…');
  retried.release();await r.settle();
  assert.equal(r.$('#event-list').querySelectorAll('.event-card').length,4);
  assert.equal(r.$('#more').hidden,false);assert.equal(r.$('#more').disabled,false);assert.equal(r.$('#notice').hidden,true);
 }finally{await r.close()}
});
for(const outcome of ['success','failure']){
 test('late append '+outcome+' cannot restore pagination after navigating to status',async()=>{
  const r=await fixture({pageSize:2});try{
   const held=r.holdNextPage(),pending=r.w.probe.load(true);await until(()=>held.pending,'obsolete append held');
   r.$('#manage-sources').click();await until(()=>!!r.$('[data-source="current"]'),'new status view');await r.settle();
   const before={hidden:r.$('#more').hidden,disabled:r.$('#more').disabled,text:r.$('#more').textContent,notice:r.$('#notice').hidden};
   assert.equal(before.hidden,true);assert.equal(r.$('#more').parentElement.hidden,true);assert.equal(r.$('#status-panel').hidden,false);
   if(outcome==='success')held.release();else held.fail();await pending;await r.settle();
   assert.deepEqual({hidden:r.$('#more').hidden,disabled:r.$('#more').disabled,text:r.$('#more').textContent,notice:r.$('#notice').hidden},before);
   assert.equal(r.$('#more').parentElement.hidden,true);assert.equal(r.$('#status-panel').hidden,false);
  }finally{await r.close()}
 });
}
