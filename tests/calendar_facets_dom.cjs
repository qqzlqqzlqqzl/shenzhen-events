/* UI state regression. Responses were captured from the real isolated API at 56e2b32.
   This DOM test is not browser/pixel evidence; the same scenarios have API/browser checks. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=process.env.RADAR_SOURCE_ROOT||path.join(__dirname,'..');
const responses=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/calendar-facets-api.json')));
const source=['vendor/fullcalendar.js','ui-state.js','render.js','planner.js','event-workflows.js','status.js','app.js'].map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n;\n');
const pause=()=>new Promise(r=>setTimeout(r,10));
async function until(fn){for(let i=0;i<200;i++){if(fn())return;await pause()}throw new Error('DOM state did not settle')}
async function ready(query='?view=calendar&month=2026-10-01&q=UX',storage={},owner='fixture'){
 const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM(fs.readFileSync(path.join(root,'static/index.html'),'utf8'),{url:'https://fixture.test/events/'+query,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
 const w=dom.window,$=s=>w.document.querySelector(s);w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 for(const [key,value] of Object.entries(storage))w.localStorage.setItem(key,value);
 let holdNext=false,held=null;
 w.fetch=async url=>{const u=new URL(url,w.location.href),p=u.searchParams;let data={};
  if(u.pathname.endsWith('/session'))data={username:owner};
  else if(u.pathname.endsWith('/stats'))data={recommended:5,upcoming:5,weekend:2,districts:['南山'],event_types:[{value:'ExhibitionEvent',label:'展览'},{value:'MusicEvent',label:'音乐'},{value:'ConferenceEvent',label:'会议'}],topics:['文化艺术','机器人','社交交流'].map(value=>({value,label:value}))};
  else if(u.pathname.endsWith('/calendar-summary'))data={total:3,unscheduled:1,long_running:1,safety_epoch:0};
  else if(u.pathname.endsWith('/events')){
   calls.push(new URLSearchParams(p));const topics=p.getAll('topic');
   let key=p.get('topic_none')==='true'||p.get('type_none')==='true'?'全不选主题':p.get('hide_long')==='false'?'显示长期':topics.length===1&&topics[0]==='文化艺术'?(p.get('attendance')==='online'?'文化艺术+可线上':p.get('free')==='true'?'文化艺术+免费':'仅文化艺术'):topics.length===2&&!topics.includes('文化艺术')?'未选文化艺术':'全部';
   data=JSON.parse(JSON.stringify(responses[key]));
   if(holdNext){holdNext=false;await new Promise(resolve=>{held=resolve})}
  }
  return {ok:true,status:200,json:async()=>data};
 };
 w.eval(source+'\n;window.probe={load,loadCalendar,showView,restoreNavigation,query,urlParams,get busy(){return busy}};');
 await until(()=>calls.length&&$('#calendar').getAttribute('aria-busy')==='false');
 return {w,$,calls,holdNext(){holdNext=true},release(){assert.ok(held);held()},async settled(){await until(()=>$('#calendar').getAttribute('aria-busy')==='false')},change(selector,value){$(selector).value=value;$(selector).dispatchEvent(new w.Event('change',{bubbles:true}))},close(){assert.deepEqual(errors,[]);w.close()}};
}
const follows=(r,a,b)=>!!(r.$(a).compareDocumentPosition(r.$(b))&r.w.Node.DOCUMENT_POSITION_FOLLOWING);

test('calendar navigation/grid precedes guide, long disclosures and excluded summaries',async()=>{
 const r=await ready();try{assert.ok(follows(r,'#calendar','.calendar-guide'));assert.ok(follows(r,'#calendar','#calendar-long'));assert.ok(follows(r,'#calendar','#excluded-events'));assert.equal(r.$('#excluded-events').querySelectorAll('[data-open]').length,0)}finally{r.close()}
});
test('long disclosure is independent of filtering and persists across reload for only its owner',async()=>{
 const r=await ready('?view=calendar&month=2026-10-01&q=UX&show_long=true');let stored;try{
  const n=r.calls.length;assert.equal(r.$('[data-calendar-long-toggle]').getAttribute('aria-expanded'),'false');
  r.$('[data-calendar-long-toggle]').click();assert.equal(r.$('[data-calendar-long-toggle]').getAttribute('aria-expanded'),'true');assert.equal(r.calls.length,n);assert.equal(r.$('#hide-long').checked,false);
  stored=r.w.localStorage.getItem('radar.calendar-long.v1:fixture');assert.equal(stored,'expanded');
  r.$('#hide-long').click();await r.settled();assert.equal(r.$('#calendar-long').hidden,true);assert.equal(r.$('#excluded-events').querySelectorAll('[data-open]').length,0);
  r.$('#hide-long').click();await r.settled();assert.equal(r.$('[data-calendar-long-toggle]').getAttribute('aria-expanded'),'true');assert.equal(r.calls.at(-1).get('hide_long'),'false');
 }finally{r.close()}
 for(const owner of ['fixture','other']){const x=await ready('?view=calendar&month=2026-10-01&q=UX&show_long=true',{'radar.calendar-long.v1:fixture':stored},owner);try{assert.equal(x.$('[data-calendar-long-toggle]').getAttribute('aria-expanded'),String(owner==='fixture'))}finally{x.close()}}
});
test('calendar total includes long results while giving short/long breakdown',async()=>{
 const r=await ready('?view=calendar&month=2026-10-01&q=UX&show_long=true');try{assert.match(r.$('#result-count').textContent,/本月符合筛选 7 个活动/);assert.match(r.$('#result-count').textContent,/日历 5 项/);assert.match(r.$('#result-count').textContent,/长期\/重复 2 项/)}finally{r.close()}
});
test('an unselected overlapping topic is never described as a negative exclusion',async()=>{
 const r=await ready();try{r.$('#topic-options input[value="文化艺术"]').click();await r.settled();assert.deepEqual(r.calls.at(-1).getAll('topic'),['机器人','社交交流']);assert.match(r.$('#active-filters').textContent,/未选：文化艺术/);assert.doesNotMatch(r.$('#active-filters').textContent,/排除：文化艺术/);assert.doesNotMatch(r.$('#topic-summary').textContent,/排除/);assert.match(r.$('#calendar').textContent,/UX 音乐交流会/)}finally{r.close()}
});
test('only-culture then online then all participation preserves the selected topic and matches recorded totals',async()=>{
 const r=await ready();try{
  r.$('[data-facet-only="topic"][data-facet-value="文化艺术"]').click();await r.settled();assert.deepEqual(r.calls.at(-1).getAll('topic'),['文化艺术']);assert.equal(r.w.document.querySelectorAll('#topic-options input:checked').length,1);assert.match(r.$('#result-count').textContent,/4 个活动/);
  r.change('#attendance','online');await r.settled();assert.match(r.$('#result-count').textContent,/2 个活动/);
  r.change('#attendance','all');await r.settled();assert.deepEqual(r.calls.at(-1).getAll('topic'),['文化艺术']);assert.equal(r.calls.at(-1).has('attendance'),false);assert.match(r.$('#result-count').textContent,/4 个活动/);
  r.$('[data-facet-kind="topic"][data-facet-action="all"]').click();await r.settled();assert.deepEqual(r.calls.at(-1).getAll('topic'),[]);assert.equal(r.calls.at(-1).has('topic_none'),false);assert.match(r.$('#result-count').textContent,/5 个活动/);
 }finally{r.close()}
});
test('single-option shortcut respects mobile draft cancellation and exact one apply',async()=>{
 const r=await ready();try{let n=r.calls.length;r.$('#open-filters').click();r.$('[data-facet-only="topic"][data-facet-value="文化艺术"]').click();assert.equal(r.calls.length,n);r.$('#cancel-filter-draft').click();assert.equal(r.w.document.querySelectorAll('#topic-options input:checked').length,3);assert.equal(r.calls.length,n);
  r.$('#open-filters').click();r.$('[data-facet-only="topic"][data-facet-value="文化艺术"]').click();r.$('#apply-filter-draft').click();await r.settled();assert.equal(r.calls.length,n+1);assert.deepEqual(r.calls.at(-1).getAll('topic'),['文化艺术']);
 }finally{r.close()}
});
test('late calendar response cannot replace newer total, facets, long disclosure or applied selection',async()=>{
 const r=await ready();try{r.holdNext();r.$('#hide-long').click();await until(()=>r.calls.at(-1).get('hide_long')==='false');r.$('#hide-long').click();r.$('[data-facet-only="topic"][data-facet-value="文化艺术"]').click();await r.settled();r.release();await pause();assert.match(r.$('#result-count').textContent,/4 个活动/);assert.equal(r.$('#calendar-long').hidden,true);assert.deepEqual(r.calls.at(-1).getAll('topic'),['文化艺术']);assert.equal(r.$('#hide-long').checked,true)}finally{r.close()}
});
test('active tab visibility moves only the horizontal tab container',async()=>{
 const r=await ready();try{const tabs=r.$('.tabs'),active=r.$('[data-view="calendar"]');tabs.scrollLeft=0;tabs.getBoundingClientRect=()=>({left:0,right:320});active.getBoundingClientRect=()=>({left:500,right:570});r.w.HTMLElement.prototype.scrollIntoView=()=>{throw new Error('whole-page scrolling is forbidden')};const before=r.w.scrollY;r.w.probe.showView();await pause();assert.ok(tabs.scrollLeft>=250);assert.equal(r.w.scrollY,before)}finally{r.close()}
});
