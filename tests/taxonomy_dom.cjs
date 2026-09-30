/* DOM integration only; real-browser/layout and production acceptance remain separate.
 * NODE_PATH=/tmp/radar-dom-check/node_modules node --test tests/taxonomy_dom.cjs
 * Requires jsdom@30.1.1 installed outside the checkout.
 */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.join(__dirname,'..');
const typeNames=['Event','BusinessEvent','ChildrensEvent','ComedyEvent','ConferenceEvent','CourseInstance','DanceEvent','DeliveryEvent','EducationEvent','ExhibitionEvent','Festival','FoodEvent','Hackathon','LiteraryEvent','MusicEvent','PerformingArtsEvent','PublicationEvent','SaleEvent','ScreeningEvent','SocialEvent','SportsEvent','TheaterEvent','VisualArtsEvent'];
const fixtures=[['comedy','ComedyEvent',['AI与开源']],['music','MusicEvent',['AI与开源']],['robot','MusicEvent',['机器人']],['museum','ExhibitionEvent',['文化艺术']]].map(([id,event_type,topics])=>({id,title:id,event_type,event_type_state:'source',event_type_label:event_type,topics,start_at:'2026-10-03T12:00:00+08:00',end_at:'2026-10-03T14:00:00+08:00',status:'scheduled',location:'深圳',summary:'fixture',url:'https://example.com/'+id,sources:[],last_seen:'2026-09-30T12:00:00+08:00'}));
const pause=()=>new Promise(r=>setTimeout(r,5));
async function settle(w){for(let i=0;i<100;i++){await pause();if(w.document.querySelector('#event-list').getAttribute('aria-busy')==='false')return;}assert.fail('list did not settle');}
async function ready(query='?view=all',count=1){
 const errors=[],requests=[],console=new VirtualConsole();console.on('jsdomError',e=>errors.push(e));
 const dom=new JSDOM(fs.readFileSync(path.join(root,'static/index.html'),'utf8'),{url:'https://example.test/events/'+query,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:console});
 const w=dom.window;w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};
 w.fetch=async url=>{
  const p=new URL(url,w.location.href);let data={};
  if(p.pathname.endsWith('/stats'))data={event_types:typeNames.map(value=>({value,label:value,count})),topics:['AI与开源','机器人','文化艺术','其他'].map(value=>({value,label:value,count})),districts:[],upcoming:4,recommended:2,weekend:0};
  if(p.pathname.endsWith('/events')){requests.push(p);const types=p.searchParams.getAll('type'),topics=p.searchParams.getAll('topic');const items=fixtures.filter(e=>p.searchParams.get('type_none')!=='true'&&p.searchParams.get('topic_none')!=='true'&&(!types.length||types.includes(e.event_type))&&(!topics.length||topics.some(t=>e.topics.includes(t))));data={items,total:items.length,has_more:false};}
  return {ok:true,status:200,json:async()=>data};
 };
 const scripts=['vendor/fullcalendar.js','ui-state.js','render.js','status.js','app.js'].map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n;\n');
 w.eval(scripts+'\n;window.__test={readURL,urlParams,applyFilters};');await settle(w);
 return {w,errors,requests,close(){dom.window.close();}};
}
const titles=w=>[...w.document.querySelectorAll('.title-button')].map(e=>e.textContent).sort();
async function check(w,kind,value){const input=[...w.document.querySelectorAll('#'+kind+'-options input')].find(x=>x.value===value);assert.ok(input);input.checked=true;input.dispatchEvent(new w.Event('change',{bubbles:true}));await settle(w);}

test('legacy tag and repeated topic URLs retain the culture selection',async()=>{
 for(const key of ['tag','topic']){const r=await ready('?view=all&'+new URLSearchParams({[key]:'展览文化'}));try{
  assert.equal(r.w.document.querySelector('#topic-summary').textContent,'已选 1 / 4');assert.deepEqual(titles(r.w),['museum']);
  assert.deepEqual([...r.w.__test.urlParams().getAll('topic')],['文化艺术']);
  r.w.__test.readURL();await r.w.__test.applyFilters();await settle(r.w);assert.deepEqual(titles(r.w),['museum']);assert.deepEqual(r.errors,[]);
 }finally{r.close();}}
});

test('type OR, topic OR, cross-group AND and chip removal round-trip through URL state',async()=>{
 const r=await ready();try{const {w}=r;w.document.querySelector('[data-facet-kind="type"][data-facet-action="none"]').click();await settle(w);w.document.querySelector('[data-facet-kind="topic"][data-facet-action="none"]').click();await settle(w);await check(w,'type','ComedyEvent');await check(w,'type','MusicEvent');await check(w,'topic','AI与开源');
 assert.deepEqual(titles(w),['comedy','music']);assert.equal(new URL(w.location.href).searchParams.getAll('type').length,2);
 await check(w,'topic','机器人');assert.deepEqual(titles(w),['comedy','music','robot']);
 const comedy=w.document.querySelector('#type-options input[value="ComedyEvent"]');comedy.checked=false;comedy.dispatchEvent(new w.Event('change',{bubbles:true}));await settle(w);assert.deepEqual(titles(w),['music','robot']);assert.deepEqual(r.errors,[]);
 }finally{r.close();}
});

test('all 23 known types are preserved in requests and selected chips',async()=>{
 const r=await ready();try{for(const type of typeNames)await check(r.w,'type',type);
 assert.equal(r.requests.at(-1).searchParams.getAll('type').length,0);assert.equal(r.w.document.querySelector('#type-summary').textContent,'全部');assert.equal(r.w.document.querySelectorAll('[data-facet-remove="type"]').length,0);assert.deepEqual(titles(r.w),['comedy','museum','music','robot']);assert.deepEqual(r.errors,[]);
 }finally{r.close();}
});

test('inverting an exclusion and history restore checkbox state',async()=>{
 const r=await ready('?view=all&type=MusicEvent');try{const {w}=r;
 w.document.querySelector('[data-facet-kind="type"][data-facet-action="invert"]').click();await settle(w);assert.deepEqual(titles(w),['comedy','museum']);
 w.document.querySelector('[data-facet-remove="type"][data-facet-value="MusicEvent"]').click();await settle(w);assert.deepEqual(titles(w),['comedy','museum','music','robot']);
 await new Promise(resolve=>{w.addEventListener('popstate',resolve,{once:true});w.history.back();});await settle(w);assert.deepEqual(titles(w),['comedy','museum']);assert.deepEqual(r.errors,[]);
 }finally{r.close();}
});



test('zero-count generic filters survive favorites/past deep links and refresh',async()=>{
 for(const view of ['favorites','past']){const r=await ready('?view='+view+'&type=Event&topic='+encodeURIComponent('其他'),0);try{const {w}=r;
  assert.equal(w.document.querySelector('#type-summary').textContent,'已选 1 / 23');assert.equal(w.document.querySelector('#topic-summary').textContent,'已选 1 / 4');
  assert.deepEqual(r.requests.at(-1).searchParams.getAll('type'),['Event']);assert.deepEqual(r.requests.at(-1).searchParams.getAll('topic'),['其他']);
  w.document.querySelector('#refresh-data').click();await settle(w);
  assert.equal(w.document.querySelector('#type-summary').textContent,'已选 1 / 23');assert.equal(w.document.querySelector('#topic-summary').textContent,'已选 1 / 4');
  assert.deepEqual(r.requests.at(-1).searchParams.getAll('type'),['Event']);assert.deepEqual(r.requests.at(-1).searchParams.getAll('topic'),['其他']);
  w.__test.readURL();await w.__test.applyFilters();await settle(w);
  assert.equal(new URL(w.location.href).searchParams.get('type'),'Event');assert.equal(new URL(w.location.href).searchParams.get('topic'),'其他');assert.deepEqual(r.errors,[]);
 }finally{r.close();}}
});

test('all to none inverse means zero results, persists URL and refresh',async()=>{
 const r=await ready();try{const {w}=r;w.document.querySelector('[data-facet-kind="type"][data-facet-action="invert"]').click();await settle(w);assert.deepEqual(titles(w),[]);assert.equal(new URL(w.location.href).searchParams.get('type_none'),'true');w.__test.readURL();await w.__test.applyFilters();await settle(w);assert.deepEqual(titles(w),[]);w.document.querySelector('[data-facet-kind="type"][data-facet-action="all"]').click();await settle(w);assert.equal(titles(w).length,4);assert.deepEqual(r.errors,[])}finally{r.close()}
});
