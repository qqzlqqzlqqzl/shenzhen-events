/* DOM integration, NOT a substitute for browser/layout acceptance.
 * npm install --prefix /tmp/radar-dom-check jsdom@30.1.1 --ignore-scripts
 * NODE_PATH=/tmp/radar-dom-check/node_modules node --test tests/multiday_dom.cjs
 */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.join(__dirname,'..');
function event(id,start,end,all_day=true,long_running=false){return {id,title:id,start_at:start,end_at:end,all_day,long_running,status:'scheduled',topics:[],summary:'isolated fixture',location:'深圳',url:'https://example.com/'+id,sources:[],last_seen:'2026-09-30T10:00:00+08:00'};}
const fixtures=[
 event('three','2026-10-14T00:00:00+08:00','2026-10-17T00:00:00+08:00'),
 event('month','2026-09-30T00:00:00+08:00','2026-10-03T00:00:00+08:00'),
 event('week','2026-10-17T00:00:00+08:00','2026-10-20T00:00:00+08:00'),
 event('midnight','2026-10-20T22:00:00+08:00','2026-10-21T00:00:00+08:00',false),
 event('overnight','2026-10-22T22:00:00+08:00','2026-10-23T01:00:00+08:00',false),
 event('single','2026-10-25T00:00:00+08:00','2026-10-26T00:00:00+08:00'),
 event('unknown','2026-10-27T23:59:00+08:00',null,false),
 event('long','2026-09-01T00:00:00+08:00','2026-11-30T00:00:00+08:00',true,true),
];
async function ready(width=1440){
 const errors=[];const console=new VirtualConsole();console.on('jsdomError',e=>errors.push(e));
 const dom=new JSDOM(fs.readFileSync(path.join(root,'static/index.html'),'utf8'),{url:'https://example.test/events/?view=calendar&month=2026-10-01',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:console});
 const w=dom.window;w.innerWidth=width;w.matchMedia=()=>({matches:width<620,addEventListener(){}});w.scrollTo=()=>{};
 w.fetch=async url=>{
   let data={};const p=new URL(url,w.location.href);
   if(p.pathname.endsWith('/stats'))data={categories:[],districts:[],recommended:0,upcoming:fixtures.length,weekend:0};
   if(p.pathname.endsWith('/events')){const items=fixtures.filter(e=>p.searchParams.get('hide_long')!=='true'||!e.long_running);data={items,total:items.length,has_more:false};}
   return {ok:true,status:200,json:async()=>data};
 };
 const scripts=['vendor/fullcalendar.js','ui-state.js','render.js','planner.js','event-workflows.js','status.js','app.js'].map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n;\n');
 w.eval(scripts+'\n;window.__test={getCalendar:()=>calendar,loadCalendar,renderLongCalendar,card};');
 for(let i=0;i<100;i++){if(w.__test.getCalendar()&&w.document.querySelector('#calendar').getAttribute('aria-busy')==='false')break;await new Promise(r=>setTimeout(r,5));}
 assert.ok(w.__test.getCalendar(),'calendar initialized');assert.equal(w.document.querySelector('#calendar').getAttribute('aria-busy'),'false');
 return {w,dom,errors,close(){w.__test.getCalendar()?.destroy();dom.window.close();}};
}
const entries=(w,id)=>[...w.document.querySelectorAll(`[data-event-id="${id}"]`)];
test('desktop passes source interval, range labels and accessible date text to FullCalendar',async()=>{
 const r=await ready();try{const {w}=r,cal=w.__test.getCalendar(),three=cal.getEventById('three');
 assert.equal(three.startStr,'2026-10-14');assert.equal(three.endStr,'2026-10-17');
 assert.equal(three.display,'block');assert.equal(three.extendedProps.rangeLabel,'10/14—10/16 · 跨 3 天');
 assert.equal(entries(w,'three').length,1);assert.match(entries(w,'three')[0].getAttribute('aria-label'),/2026\/10\/14 — 2026\/10\/16/);
 assert.ok(entries(w,'three')[0].classList.contains('multi-day-event'));
 assert.match(w.document.querySelector('#result-count').textContent,/7 个活动/);assert.deepEqual(r.errors,[]);
 }finally{r.close();}
});
test('cross-month source starts remain in the month; cross-week spans split into two segments',async()=>{
 const r=await ready();try{assert.equal(r.w.__test.getCalendar().getEventById('month').startStr,'2026-09-30');assert.equal(entries(r.w,'month').length,1);assert.equal(entries(r.w,'week').length,2);assert.deepEqual(r.errors,[]);}finally{r.close();}
});
test('mobile agenda lists Oct 14, 15 and 16 exactly once each',async()=>{
 const r=await ready(390);try{const {w}=r;assert.equal(w.__test.getCalendar().view.type,'listMonth');
 const dates=entries(w,'three').map(e=>{let p=e.previousElementSibling;while(p&&!p.classList.contains('fc-list-day'))p=p.previousElementSibling;return p?.dataset.date;});
 assert.deepEqual(dates,['2026-10-14','2026-10-15','2026-10-16']);assert.equal(entries(w,'month').length,2);assert.equal(entries(w,'week').length,3);assert.deepEqual(r.errors,[]);
 }finally{r.close();}
});
test('exclusive midnight and unknown end never invent an extra covered date',async()=>{
 const r=await ready(390);try{const {w}=r;assert.equal(entries(w,'midnight').length,1);assert.equal(entries(w,'overnight').length,2);assert.equal(entries(w,'single').length,1);assert.equal(entries(w,'unknown').length,1);assert.equal(w.__test.getCalendar().getEventById('unknown').end,null);assert.deepEqual(r.errors,[]);}finally{r.close();}
});
test('long-running items remain separate and their full source date range is available',async()=>{
 const r=await ready();try{const {w}=r;assert.equal(entries(w,'long').length,0);assert.equal(w.document.querySelector('#calendar-long').hidden,true);w.document.querySelector('#hide-long').checked=false;await w.__test.loadCalendar({startStr:'2026-10-01',endStr:'2026-11-01'});assert.equal(entries(w,'long').length,0);assert.equal(w.document.querySelector('#calendar-long').hidden,false);assert.match(w.document.querySelector('#calendar-long').textContent,/2026\/09\/01 — 2026\/11\/29/);assert.deepEqual(r.errors,[]);}finally{r.close();}
});
test('cards show full short-event date range and preserve unknown opening-day disclaimer',async()=>{
 const r=await ready();try{const html=r.w.__test.card(fixtures[0]);assert.match(html,/10\/14—10\/16 · 跨 3 天/);assert.match(html,/具体时段\/开放日以原文为准/);assert.match(html,/data-event="three"/);assert.deepEqual(r.errors,[]);}finally{r.close();}
});

test('mobile agenda keeps native focus, single keyboard/pointer activation and one range label',async()=>{
 const r=await ready(390);try{const {w}=r,cal=w.__test.getCalendar();let activations=0;
 cal.setOption('eventClick',()=>{activations++;});
 const link=entries(w,'three')[0].querySelector('.fc-list-event-title a');
 assert.ok(link,'native link retained');assert.equal(link.tabIndex,0);link.focus();assert.equal(w.document.activeElement,link);
 assert.match(link.getAttribute('aria-label'),/2026\/10\/14 — 2026\/10\/16/);
 for(const key of ['Enter',' ']){const before=activations;link.dispatchEvent(new w.KeyboardEvent('keydown',{key,bubbles:true,cancelable:true}));assert.equal(activations,before+1);}
 link.click();assert.equal(activations,3);
 for(const row of entries(w,'three'))assert.equal(row.querySelectorAll('.calendar-event-range').length,1);
 cal.changeView('dayGridMonth');cal.changeView('listMonth');
 for(const row of entries(w,'three')){assert.equal(row.querySelectorAll('.calendar-event-range').length,1);assert.equal(row.querySelector('.fc-list-event-title a').tabIndex,0);}
 assert.deepEqual(r.errors,[]);
 }finally{r.close();}
});
