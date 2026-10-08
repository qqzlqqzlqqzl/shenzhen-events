/* Deferred-response regression ported from the verified offline audit. All 13 passing boundaries remain; seven defect assertions now require repaired behavior. No real network or server dedup execution. */
'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(process.env.RADAR_SOURCE_ROOT||path.join(__dirname,'..'));
const files=['vendor/fullcalendar.js','ui-state.js','render.js','planner.js','event-workflows.js','status.js','app.js'];
const source=files.map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n;\n');
const tick=()=>new Promise(r=>setTimeout(r,20));
const clone=x=>JSON.parse(JSON.stringify(x));
const row=(title='initial',extra={})=>({id:'one',title,start_at:'2026-10-05T10:00:00+08:00',end_at:'2026-10-05T12:00:00+08:00',status:'scheduled',favorite:false,feedback:'',feedback_tags:[],revision:0,event_type:'MusicEvent',event_type_label:'音乐',topics:['文化艺术'],attendance:'offline',district:'南山',sources:[],url:'https://fixture.test/event/one',...extra});
const events=(items=[row()])=>({items:clone(items),total:items.length,has_more:false,facets:{},excluded_long:{total:0,items:[]}});
const stat=(n=2)=>({recommended:n,upcoming:n,weekend:n,last_updated:'2026-10-02T12:00:00Z',districts:['南山','福田'],event_types:[{value:'MusicEvent',label:'音乐'},{value:'ConferenceEvent',label:'会议'}],topics:[{value:'文化艺术',label:'文化艺术'}]});
const status=(name='source initial',retry=null)=>({sources:[{id:'source-a',name,url:'https://fixture.test/source',status:'error',message:'fixture source',retry}],candidates:[],runs:[],budget:{calls:0,tokens:0},limits:{daily_calls:1,daily_tokens:1},db_bytes:0,retention_days:45,ics_url:'/events/calendar.ics?token=synthetic-only'});
async function ready(query='?view=all'){
 const errors=[],calls=[],rules=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM(fs.readFileSync(path.join(root,'static/index.html'),'utf8'),{url:'https://fixture.test/events/'+query,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
 const w=dom.window,$=s=>w.document.querySelector(s);
 w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const model={username:'alice',rows:[row()],status:status()};
 w.fetch=async (url,options={})=>{
  const u=new URL(url,w.location.href);assert.equal(u.origin,'https://fixture.test');assert.ok(u.pathname.startsWith('/events/api/'));const rec={path:u.pathname.split('/events/api/')[1],url:u,options};calls.push(rec);
  const rule=rules.find(r=>!r.used&&r.matches(rec));if(rule){rule.used=true;rule.request=rec;return rule.promise;}
  let data={};if(['login','session'].includes(rec.path))data={username:model.username};
  else if(rec.path==='stats')data=stat();else if(rec.path==='events')data=events(model.rows.filter(e=>u.searchParams.get('favorites')!=='true'||e.favorite));
  else if(rec.path==='status')data=clone(model.status);else if(rec.path.startsWith('event/'))data=clone(model.rows[0]);
  else if(rec.path.startsWith('preferences/')){Object.assign(model.rows[0],JSON.parse(options.body));model.rows[0].revision++;data=clone(model.rows[0]);}
  else if(rec.path.startsWith('viewed/'))data={viewed_at:'2026-10-02T12:00:00Z'};
  return {ok:true,status:200,json:async()=>clone(data)};
 };
 w.eval(source+'\n;window.probe={api,load,loadCalendar,loadStatus,stats,enter,showLogin,navigate,save,updateFeedback,openDetail,closeDetail,retrySource,get records(){return records},get calendar(){return calendar},get saving(){return saving},get feedbackSaving(){return feedbackSaving},get authenticated(){return authenticated},get listSnapshot(){return listSnapshot},get calendarSnapshot(){return calendarSnapshot},get busy(){return busy},get view(){return view}};');
 await tick();await tick();
 return {w,$,calls,model,errors,
  defer(matches){let resolve,reject;const r={matches:typeof matches==='string'?c=>c.path===matches:matches,promise:new Promise((a,b)=>{resolve=a;reject=b}),used:false};r.ok=data=>resolve({ok:true,status:200,json:async()=>clone(data)});r.http=(code,data)=>resolve({ok:false,status:code,json:async()=>clone(data)});r.fail=message=>reject(new Error(message));rules.push(r);return r;},
  change(s,v){$(s).value=v;$(s).dispatchEvent(new w.Event('change',{bubbles:true}));},
  search(v){$('#search').value=v;$('#search').dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));},
  async login(name='bob'){model.username=name;$('#username').value=name;$('#password').value='synthetic-only';$('#login-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await tick();await tick();},
  close(){assert.deepEqual(errors,[]);w.close();}
 };
}

test('PASS: three quick queries, responses newest first, older success/failure cannot relabel current rows',async()=>{
 const r=await ready();try{
  const a=r.defer('events');r.search('alpha');const b=r.defer('events');r.search('beta');const c=r.defer('events');r.search('gamma');
  assert.equal(a.request.options.signal.aborted,true);assert.equal(b.request.options.signal.aborted,true);
  c.ok(events([row('gamma result')]));await tick();b.fail('old beta failure');a.ok(events([row('alpha result')]));await tick();
  assert.equal(r.$('.title-button').textContent,'gamma result');assert.equal(new URL(r.w.location.href).searchParams.get('q'),'gamma');assert.equal(r.$('#notice').hidden,true);assert.equal(r.$('#more').disabled,false);
 }finally{r.close()}
});

test('PASS: out-of-order month jumps discard old payload without fetching obsolete next page',async()=>{
 const r=await ready('?view=calendar&month=2026-10-01&q=preserve');try{
  const nov=r.defer('events');r.change('#calendar-month-jump','2026-11');const dec=r.defer('events');r.change('#calendar-month-jump','2026-12');
  dec.ok(events([row('December result',{start_at:'2026-12-05T10:00:00+08:00',end_at:'2026-12-05T12:00:00+08:00'})]));await tick();nov.ok({...events([row('November stale')]),has_more:true});await tick();
  assert.deepEqual(Array.from(r.w.probe.calendar.getEvents(),x=>x.title),['December result']);assert.equal(r.$('#calendar-month-jump').value,'2026-12');assert.equal(r.$('#search').value,'preserve');assert.equal(r.$('#calendar').getAttribute('aria-busy'),'false');
  assert.equal(r.calls.filter(c=>c.path==='events'&&c.url.searchParams.get('offset')==='1').length,0);
 }finally{r.close()}
});

for(const kind of ['events','status'])for(const outcome of ['success','401','failure'])test(`PASS: old ${kind} ${outcome} after logout and new login cannot mutate new session`,async()=>{
 const r=await ready(kind==='status'?'?view=status':'?view=all');try{
  const a=r.defer(kind),old=kind==='status'?r.w.probe.loadStatus():r.w.probe.load();r.$('#logout').click();await tick();assert.equal(r.w.probe.authenticated,false);
  r.model.rows=[row('Bob current')];r.model.status=status('Bob source');await r.login();
  if(outcome==='success')a.ok(kind==='events'?events([row('Alice old')]):status('Alice source'));else if(outcome==='401')a.http(401,{detail:'old expired response'});else a.fail('old-session transport failure');await old;await tick();
  assert.equal(r.w.probe.authenticated,true);assert.equal(r.$('#login-panel').hidden,true);
  if(kind==='events')assert.equal(r.$('.title-button').textContent,'Bob current');else assert.match(r.$('.source-card h3').textContent,/Bob source/);
 }finally{r.close()}
});

test('PASS: reverse status responses preserve latest data and current search/filter/selection/expanded state',async()=>{
 const r=await ready('?view=status');try{
  const a=r.defer('status'),pa=r.w.probe.loadStatus();const b=r.defer('status'),pb=r.w.probe.loadStatus();
  r.$('#source-search').value='source';r.$('#source-search').dispatchEvent(new r.w.Event('input'));r.change('#source-state','attention');r.$('.source-inspection').open=true;r.$('#source-search').focus();r.$('#source-search').setSelectionRange(1,4);
  b.ok(status('source latest'));await pb;a.ok(status('source obsolete'));await pa;
  assert.match(r.$('.source-card h3').textContent,/source latest/);assert.equal(r.$('#source-state').value,'attention');assert.equal(r.$('#source-search').value,'source');assert.equal(r.w.document.activeElement.id,'source-search');assert.equal(r.$('#source-search').selectionStart,1);assert.equal(r.$('.source-inspection').open,true);
 }finally{r.close()}
});

test('successful status refresh with retry:null renders fresh contents while retaining the pending retry lock and focus',async()=>{
 const r=await ready('?view=status');try{
  const pending=r.defer(c=>c.path==='sources/source-a/retry');r.$('[data-retry-source]').focus();r.$('[data-retry-source]').click();assert.equal(r.$('[data-retry-source]').disabled,true);
  r.model.status=status('source refreshed with no retry job');r.model.status.sources[0].message='Fresh successful inventory details';
  await r.w.probe.loadStatus();
  assert.match(r.$('.source-card h3').textContent,/source refreshed with no retry job/);assert.match(r.$('.source-card').textContent,/Fresh successful inventory details/);
  assert.doesNotMatch(r.$('#source-snapshot').textContent,/刷新失败/);assert.doesNotMatch(r.$('#toast').textContent,/Cannot read|reading 'message'/);
  assert.equal(r.$('[data-retry-source]').disabled,true);assert.equal(r.$('.source-retry span').textContent,r.$('[data-retry-source]').textContent);assert.equal(r.w.document.activeElement,r.$('.source-inspection summary'));
  const duplicate=r.defer(c=>c.path==='sources/source-a/retry');r.$('[data-retry-source]').click();assert.equal(r.calls.filter(c=>c.path==='sources/source-a/retry').length,1);
  pending.ok({message:'queued first'});duplicate.ok({message:'queued second'});await tick();await tick();assert.equal(r.$('[data-retry-source]').disabled,false);
 }finally{r.close()}
});

test('queued retry status replacement keeps keyboard focus in its source',async()=>{
 const r=await ready('?view=status');try{
  const pending=r.defer(c=>c.path==='sources/source-a/retry');r.$('[data-retry-source]').focus();r.$('[data-retry-source]').click();r.model.status=status('source queued',{state:'queued',message:'waiting'});pending.ok({message:'queued'});await tick();await tick();
  assert.equal(r.$('[data-retry-source]').disabled,true);assert.equal(r.w.document.activeElement,r.$('.source-inspection summary'));
 }finally{r.close()}
});

test('late list refresh keeps the confirmed favorite and revision',async()=>{
 const r=await ready();try{
  const pending=r.defer('events'),refresh=r.w.probe.load();r.$('[data-save]').click();await tick();assert.equal(r.w.probe.records.get('one').favorite,true);assert.equal(r.w.probe.records.get('one').revision,1);
  pending.ok(events([row('stale refresh')]));await refresh;
  assert.equal(r.w.probe.records.get('one').favorite,true);assert.equal(r.w.probe.records.get('one').revision,1);assert.equal(r.$('[data-save]').getAttribute('aria-pressed'),'true');assert.match(r.$('#toast').textContent,/已收藏/);assert.equal(r.model.rows[0].favorite,true);
 }finally{r.close()}
});

test('same-query refresh keeps favorite controls disabled while save remains pending',async()=>{
 const r=await ready();try{
  const pending=r.defer(c=>c.path==='preferences/one');r.$('[data-save]').click();assert.equal(r.$('[data-save]').disabled,true);await r.w.probe.load();assert.equal(r.w.probe.saving.has('one'),true);assert.equal(r.$('[data-save]').disabled,true);
  r.$('[data-save]').click();assert.equal(r.calls.filter(c=>c.path==='preferences/one').length,1);pending.ok({...row(),favorite:true,revision:1});await tick();
 }finally{r.close()}
});

test('older stats failure preserves the successful newer stats note',async()=>{
 const r=await ready();try{
  const a=r.defer('stats'),pa=r.w.probe.stats();const b=r.defer('stats'),pb=r.w.probe.stats();b.ok(stat(7));await pb;const latestNote=r.$('#update-note').textContent;assert.match(latestNote,/2026/);a.fail('old stats failed');await pa;assert.equal(r.$('#count-upcoming').textContent,'7');assert.equal(r.$('#update-note').textContent,latestNote);assert.doesNotMatch(r.$('#update-note').textContent,/old stats failed/);
 }finally{r.close()}
});


test('late pre-unsave refresh keeps saved-only list, count and snapshot empty',async()=>{
 const r=await ready('?view=favorites&q=preserve&districts=南山');try{
  r.model.rows=[row('saved event',{favorite:true,revision:1})];await r.w.probe.load();const before=r.w.location.href;
  const pending=r.defer('events'),refresh=r.w.probe.load();r.$('[data-save]').click();await tick();assert.equal(r.$('.event-card'),null);assert.equal(r.w.probe.listSnapshot.items.length,0);
  pending.ok(events([row('saved event',{favorite:true,revision:1})]));await refresh;
  assert.equal(r.$('.event-card'),null);assert.equal(r.w.probe.listSnapshot.items.length,0);assert.equal(r.model.rows[0].favorite,false);assert.equal(r.w.location.href,before);assert.match(r.$('#result-count').textContent,/0 个活动/);
 }finally{r.close()}
});

test('late calendar refresh agrees with the confirmed favorite in detail',async()=>{
 const r=await ready('?view=calendar&month=2026-10-01&q=preserve');try{
  const pending=r.defer('events'),refresh=r.w.probe.loadCalendar({startStr:'2026-10-01',endStr:'2026-11-01'});
  await r.w.probe.openDetail('one');r.$('#detail [data-save]').click();await tick();assert.equal(r.w.probe.records.get('one').favorite,true);assert.equal(r.$('#detail [data-save]').getAttribute('aria-pressed'),'true');
  pending.ok(events([row()]));await refresh;
  assert.equal(r.w.probe.records.get('one').favorite,true);assert.equal(r.w.probe.calendar.getEventById('one').extendedProps.favorite,true);assert.equal(r.$('#detail [data-save]').getAttribute('aria-pressed'),'true');assert.equal(r.model.rows[0].favorite,true);
 }finally{r.close()}
});

test('PASS: calendar/list switching ignores both old view payloads and keeps applied query',async()=>{
 const r=await ready('?view=all&q=preserve&districts=南山');try{
  const oldList=r.defer('events'),pl=r.w.probe.load();const oldMonth=r.defer('events');r.w.probe.navigate('calendar');const current=r.defer('events');r.w.probe.navigate('all');
  current.ok(events([row('current list')]));await tick();oldMonth.ok(events([row('old month')]));oldList.ok(events([row('old list')]));await pl;await tick();
  assert.equal(r.w.probe.view,'all');assert.equal(r.$('.title-button').textContent,'current list');assert.equal(r.w.probe.calendar,null);assert.equal(r.$('#search').value,'preserve');assert.equal(new URL(r.w.location.href).searchParams.get('districts'),'南山');
 }finally{r.close()}
});


for(const outcome of ['success','failure'])test(`PASS: old retry POST ${outcome} after logout/login cannot toast or refresh Bob status`,async()=>{
 const r=await ready('?view=status');try{
  const pending=r.defer(c=>c.path==='sources/source-a/retry');r.$('[data-retry-source]').click();r.$('#logout').click();await tick();r.model.status=status('Bob source');await r.login();const count=r.calls.filter(c=>c.path==='status').length;const toast=r.$('#toast').textContent;
  if(outcome==='success')pending.ok({message:'Alice old retry queued'});else pending.fail('Alice old retry failed');await tick();await tick();
  assert.equal(r.w.probe.authenticated,true);assert.match(r.$('.source-card h3').textContent,/Bob source/);assert.equal(r.calls.filter(c=>c.path==='status').length,count);assert.equal(r.$('#toast').textContent,toast);assert.equal(r.$('[data-retry-source]').disabled,false);
 }finally{r.close()}
});

test('old retry finally cannot clear a new-session same-source pending lock',async()=>{
 const r=await ready('?view=status');try{
  const old=r.defer(c=>c.path==='sources/source-a/retry');r.$('[data-retry-source]').click();r.$('#logout').click();await tick();await r.login();
  const current=r.defer(c=>c.path==='sources/source-a/retry');r.$('[data-retry-source]').click();
  old.ok({message:'old session queued'});await tick();await r.w.probe.loadStatus();
  assert.equal(r.$('[data-retry-source]').disabled,true);r.$('[data-retry-source]').click();
  assert.equal(r.calls.filter(c=>c.path==='sources/source-a/retry').length,2);
  current.ok({message:'current queued'});await tick();
 }finally{r.close()}
});

test('failed replacement read keeps the confirmed saved-only removal and filters',async()=>{
 const r=await ready('?view=favorites&q=preserve&districts=南山');try{
  r.model.rows=[row('saved',{favorite:true,revision:1})];await r.w.probe.load();const url=r.w.location.href;
  const old=r.defer('events'),refresh=r.w.probe.load();r.$('[data-save]').click();await tick();
  const replacement=r.defer('events');old.ok(events([row('saved',{favorite:true,revision:1})]));await tick();replacement.fail('replacement offline');await refresh;
  assert.equal(r.$('.event-card'),null);assert.equal(r.w.probe.listSnapshot.items.length,0);assert.equal(r.w.probe.listSnapshot.total,0);assert.equal(r.w.location.href,url);assert.equal(r.model.rows[0].favorite,false);
 }finally{r.close()}
});

test('failed favorite POST leaves a concurrent valid read eligible',async()=>{
 const r=await ready();try{
  const read=r.defer('events'),refresh=r.w.probe.load(),write=r.defer(c=>c.path==='preferences/one');r.$('[data-save]').click();write.fail('write offline');await tick();
  const before=r.calls.filter(c=>c.path==='events').length;read.ok(events([row('fresh title')]));await refresh;
  assert.equal(r.calls.filter(c=>c.path==='events').length,before);assert.equal(r.$('.title-button').textContent,'fresh title');assert.equal(r.w.probe.records.get('one').favorite,false);
 }finally{r.close()}
});

test('saved-only calendar cannot resurrect a confirmed unsaved event from a late read',async()=>{
 const r=await ready('?view=calendar&month=2026-10-01&saved_only=true');try{
  r.model.rows=[row('saved',{favorite:true,revision:1})];await r.w.probe.loadCalendar({startStr:'2026-10-01',endStr:'2026-11-01'});
  const old=r.defer('events'),refresh=r.w.probe.loadCalendar({startStr:'2026-10-01',endStr:'2026-11-01'});
  await r.w.probe.openDetail('one');r.$('#detail [data-save]').click();await tick();old.ok(events([row('saved',{favorite:true,revision:1})]));await refresh;
  assert.equal(r.w.probe.calendar.getEvents().length,0);assert.equal(r.w.probe.calendarSnapshot.items.length,0);assert.equal(r.$('#detail [data-save]').getAttribute('aria-pressed'),'false');assert.equal(r.model.rows[0].favorite,false);
 }finally{r.close()}
});


test('PASS: already-inflight old month page two cannot append into a later month',async()=>{
 const r=await ready('?view=calendar&month=2026-10-01');try{
  const first=r.defer('events');r.change('#calendar-month-jump','2026-11');const second=r.defer('events');first.ok({...events([row('November page one')]),has_more:true});await tick();assert.equal(second.request.url.searchParams.get('offset'),'1');
  const dec=r.defer('events');r.change('#calendar-month-jump','2026-12');dec.ok(events([row('December final',{start_at:'2026-12-05T10:00:00+08:00',end_at:'2026-12-05T12:00:00+08:00'})]));await tick();second.ok(events([row('November page two',{id:'two'})]));await tick();
  assert.deepEqual(Array.from(r.w.probe.calendar.getEvents(),x=>x.title),['December final']);assert.equal(r.w.probe.calendarSnapshot.items.length,1);assert.equal(r.$('#calendar-month-jump').value,'2026-12');
 }finally{r.close()}
});

for(const late of [false,true]){
 test('saved-only calendar removes an unsaved event after detail closes: '+(late?'late POST':'completed POST'),async()=>{
  const r=await ready('?view=calendar&month=2026-10-01&saved_only=true&q=preserve');try{
   r.model.rows=[row('saved calendar event',{favorite:true,revision:1})];
   await r.w.probe.loadCalendar({startStr:'2026-10-01',endStr:'2026-11-01'});await tick();
   assert.equal(r.w.probe.calendar.getEvents().length,1);
   await r.w.probe.openDetail('one',false);await tick();
   const pending=late?r.defer(c=>c.path==='preferences/one'):null;
   const before=r.calls.length,saving=r.w.probe.save('one');
   if(!late)await saving;
   r.w.probe.closeDetail();
   if(late){
    assert.equal(r.w.probe.calendar.getEvents().length,1,'pending save retains current event');
    r.model.rows[0].favorite=false;r.model.rows[0].revision=2;
    pending.ok(row('saved calendar event',{favorite:false,revision:2}));await saving;
   }
   await tick();await tick();
   assert.equal(r.w.probe.calendarSnapshot.items.length,0);
   assert.equal(r.w.probe.calendar.getEvents().length,0,'calendar must agree with saved-only snapshot');
   assert.match(r.$('#result-count').textContent,/0 个活动/);
   assert.equal(r.calls.slice(before).filter(c=>c.path==='events').length,1);
   assert.equal(new URL(r.w.location.href).searchParams.get('saved_only'),'true');
   assert.equal(new URL(r.w.location.href).searchParams.get('q'),'preserve');
  }finally{r.close()}
 });
}
test('ordinary calendar retains an unsaved event without a membership reload',async()=>{
 const r=await ready('?view=calendar&month=2026-10-01');try{
  r.model.rows=[row('ordinary event',{favorite:true,revision:1})];
  await r.w.probe.loadCalendar({startStr:'2026-10-01',endStr:'2026-11-01'});await tick();
  await r.w.probe.openDetail('one',false);await tick();const before=r.calls.length;
  await r.w.probe.save('one');r.w.probe.closeDetail();await tick();await tick();
  assert.equal(r.w.probe.calendar.getEvents().length,1);
  assert.equal(r.w.probe.calendar.getEventById('one').extendedProps.favorite,false);
  assert.equal(r.calls.slice(before).filter(c=>c.path==='events').length,0);
 }finally{r.close()}
});


test('removing the last saved list row clears its empty date group',async()=>{
 const r=await ready('?view=favorites');try{
  r.model.rows=[row('only saved row',{favorite:true,revision:1})];await r.w.probe.load();
  r.$('[data-display-mode="list"]').click();assert.equal(r.w.document.querySelectorAll('.date-group').length,1);
  r.$('[data-save]').click();await tick();await tick();
  assert.equal(r.w.document.querySelectorAll('.date-group').length,0);
  assert.equal(r.$('.event-card'),null);assert.ok(r.$('#event-list .empty'));
  assert.match(r.$('#result-count').textContent,/0/);assert.equal(r.model.rows[0].favorite,false);
 }finally{r.close()}
});
