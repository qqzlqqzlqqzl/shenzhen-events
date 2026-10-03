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
async function fixture({signedIn=true,query='?view=all'}={}){
 const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM(html,{url:'https://fixture.test/events/'+query,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
 const w=dom.window,$=s=>w.document.querySelector(s);
 w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const state={signedIn,owner:'alice',deferPreference:null,deferEvent:null};
 const rows=new Map(Array.from({length:4},(_,i)=>[String(i),{id:String(i),title:'合成长标题候选 '+i+' / '.repeat(25)+' bounded fixture',start_at:'2026-10-10T10:00:00+08:00',end_at:'2026-10-10T12:00:00+08:00',status:'scheduled',favorite:i===0,feedback:'',feedback_tags:[],revision:0,event_type:'ConferenceEvent',event_type_label:'会议',topics:['科技'],attendance:'offline',location:'合成地点',district:'南山',sources:[],url:'https://example.com/'+i}]));
 const reply=(data,status=200)=>({ok:status>=200&&status<300,status,json:async()=>clone(data)});
 w.fetch=async(url,options={})=>{
  const u=new URL(url,w.location.href),p=u.pathname,body=options.body?JSON.parse(options.body):null;calls.push({path:p,method:options.method||'GET',body});
  if(!state.signedIn)return reply({detail:'synthetic session expired'},401);
  if(p.endsWith('/session')||p.endsWith('/login'))return reply({username:state.owner});
  if(p.endsWith('/logout'))return reply({ok:true});
  if(p.endsWith('/stats'))return reply({recommended:4,upcoming:4,weekend:4,districts:['南山'],event_types:[{value:'ConferenceEvent',label:'会议'}],topics:[{value:'科技',label:'科技'}]});
  if(p.endsWith('/status'))return reply({sources:[{id:'current',name:'Synthetic current source',url:'https://example.com/source',status:'ok',retry:null,coverage:{version:1,visible:1,extracted:1,unique:1,shenzhen_candidates:1,admitted:1,stored_events:1}}],candidates:[],runs:[],budget:{calls:0,tokens:0},limits:{daily_calls:1,daily_tokens:1},db_bytes:0,retention_days:45,ics_url:'/events/calendar.ics'});
  if(p.endsWith('/events'))return reply({items:[...rows.values()],total:4,has_more:false,facets:{},excluded_long:{items:[],total:0}});
  if(p.includes('/event/')){const id=p.split('/').at(-1),data=clone(rows.get(id));if(state.deferEvent){const pending=state.deferEvent({id,data});if(pending)return await pending;}return reply(data);}
  if(p.includes('/viewed/'))return reply({viewed_at:'2026-10-03T10:00:00Z'});
  if(p.includes('/preferences/')){
   const id=p.split('/').at(-1),current=rows.get(id),result={...current,...body,revision:current.revision+1};delete result.expected_revision;
   if(state.deferPreference)return await new Promise(resolve=>state.deferPreference({id,result,resolve:()=>{rows.set(id,result);resolve(reply(result))}}));
   rows.set(id,result);return reply(result);
  }
  throw Error('Unexpected fixture request: '+p);
 };
 w.eval(scripts+'\n;window.probe={api,enter,showLogin,openDetail,closeDetail,restoreNavigation,loadStatus,updateFeedback,setFeedbackSignal,get authenticated(){return authenticated},get busy(){return busy},get undo(){return undoFeedback},get records(){return records},get feedbackSaving(){return feedbackSaving}};');
 try {
  if(signedIn)await until(()=>w.probe.authenticated&&!w.probe.busy&&(query.includes('view=status')?!!$('[data-source="current"]'):w.probe.records.size===4),'signed-in view');
  else await until(()=>!$('#login-panel').hidden,'login form');
 } catch(error) {w.probe.showLogin();await sleep(15);dom.window.close();throw error}
 const choose=(n=2)=>{for(let i=0;i<n;i++)$('[data-compare="'+i+'"]').click()};
 const mutate=async(id='0',signal='interested')=>{await w.probe.openDetail(id);$('[data-feedback-signal="'+signal+'"]').click();await until(()=>!w.probe.feedbackSaving.size&&!!w.probe.undo,'feedback settlement')};
 return {w,$,errors,calls,state,rows,choose,mutate,holdNextEvent(){let release;state.deferEvent=({id,data})=>{state.deferEvent=null;return new Promise(resolve=>release=()=>resolve(reply(data)))};return {get pending(){return !!release},release(){release()}}},async settle(){await until(()=>!w.probe.busy&&!w.probe.feedbackSaving.size,'idle');await sleep(15)},async close(){w.probe.showLogin();await sleep(15);assert.deepEqual(errors,[]);dom.window.close()}};
}
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
