/* Synthetic, deterministic regressions for Issue #77. No production calls. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.join(__dirname,'..');
const scripts=['vendor/fullcalendar.js','ui-state.js','render.js','planner.js','event-workflows.js','status.js','app.js'].map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n;\n');
const key='radar.filters.v1:fixture';
const wait=()=>new Promise(resolve=>setTimeout(resolve,15));
const rows=['2026-10-05','2026-11-05'].map((day,i)=>({id:String(i),title:'收藏 '+day,start_at:day+'T10:00:00+08:00',end_at:day+'T12:00:00+08:00',status:'scheduled',favorite:true,event_type:'MusicEvent',event_type_label:'音乐',topics:['文化艺术'],attendance:'offline',district:i?'福田':'南山',sources:[],url:'https://example.com/'+i}));
async function ready(query='?view=all',saved=null,profiles=null,preferences={}){
 const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM(fs.readFileSync(path.join(root,'static/index.html'),'utf8'),{url:'https://fixture.test/events/'+query,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
 const w=dom.window,$=s=>w.document.querySelector(s);w.matchMedia=()=>({matches:false,addEventListener(){}});w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 if(saved!==null)w.localStorage.setItem(key,saved);if(profiles)w.localStorage.setItem('radar.saved.v1:fixture',JSON.stringify(profiles));
 for(const [name,value] of Object.entries(preferences))w.localStorage.setItem(name,value);
 w.fetch=async url=>{const u=new URL(url,w.location.href),p=u.searchParams;let data={};
  if(u.pathname.endsWith('/session'))data={username:'fixture'};
  else if(u.pathname.endsWith('/stats'))data={recommended:2,upcoming:2,weekend:2,districts:['南山','福田'],event_types:[{value:'MusicEvent',label:'音乐'},{value:'ConferenceEvent',label:'会议'}],topics:[{value:'文化艺术',label:'文化艺术'}]};
  else if(u.pathname.endsWith('/events')){calls.push(p);let items=rows;if(p.has('start'))items=items.filter(x=>x.start_at.slice(0,10)>=p.get('start')&&x.start_at.slice(0,10)<p.get('end'));data={items,total:items.length,has_more:false,facets:{type:[{value:'MusicEvent',count:items.length},{value:'ConferenceEvent',count:0}]},excluded_long:{items:[],total:0}}}
  else if(u.pathname.includes('/event/'))data=rows[0];
  return {ok:true,status:200,json:async()=>data};
 };
 w.eval(scripts+'\n;window.probe={load,navigate,readURL,restoreNavigation,query,urlParams,openDetail,closeDetail,get busy(){return busy}};');
 await wait();await wait();
 return {w,$,calls,errors,change(s,value){$(s).value=value;$(s).dispatchEvent(new w.Event('change',{bubbles:true}))},close(){assert.deepEqual(errors,[]);w.close()}};
}
const saved=r=>r.w.localStorage.getItem(key);
const applied='from=2026-10-01&until=2026-10-31';

test('display grouping and theme preferences change presentation without another query',async()=>{
 const r=await ready();try{
  const n=r.calls.length,ids=[...r.w.document.querySelectorAll('.event-card')].map(e=>e.dataset.event);
  r.$('[data-display-mode="list"]').click();
  assert.equal(r.calls.length,n);assert.equal(r.w.document.querySelectorAll('.date-group').length,2);
  assert.deepEqual([...r.w.document.querySelectorAll('.event-card')].map(e=>e.dataset.event),ids);
  assert.equal(r.w.localStorage.getItem('radar.display.v1'),'list');
  r.$('#theme-toggle').click();assert.equal(r.w.document.documentElement.dataset.theme,'dark');
  assert.equal(r.w.localStorage.getItem('radar.theme.v1'),'dark');assert.equal(r.calls.length,n);
 }finally{r.close()}
 const r2=await ready('?view=all',null,null,{'radar.display.v1':'list','radar.theme.v1':'dark'});
 try{assert.equal(r2.w.document.documentElement.dataset.theme,'dark');assert.equal(r2.w.document.querySelectorAll('.date-group').length,2)}finally{r2.close()}
});

test('individual applied chips remove their own condition while retaining other filters',async()=>{
 const r=await ready('?view=all&'+applied+'&q=关键词&free=true&attendance=online');
 try{
  const n=r.calls.length;r.$('[data-filter-remove="search"]').click();await wait();
  assert.equal(r.calls.length,n+1);assert.equal(r.calls.at(-1).has('q'),false);
  assert.equal(r.calls.at(-1).get('free'),'true');assert.equal(r.calls.at(-1).get('attendance'),'online');assert.equal(r.calls.at(-1).get('start'),'2026-10-01');
  r.$('[data-filter-remove="dates"]').click();await wait();
  assert.equal(r.calls.at(-1).has('start'),false);assert.equal(r.calls.at(-1).get('free'),'true');assert.equal(r.calls.at(-1).get('attendance'),'online');
 }finally{r.close()}
});

test('inline filter panel retains the toolbar search and cancels without a request',async()=>{
 for(const action of ['button','escape']){const r=await ready();try{
  const input=r.$('#search'),n=r.calls.length;assert.ok(input.closest('.toolbar-search'));
  r.$('#open-filters').click();assert.ok(input.closest('.toolbar-search'));assert.notEqual(r.$('#filter-dialog').tagName,'DIALOG');assert.equal(r.$('#filter-dialog').hidden,false);assert.equal(r.$('#open-filters').getAttribute('aria-expanded'),'true');
  input.value='未应用的搜索';input.dispatchEvent(new r.w.Event('input',{bubbles:true}));
  if(action==='escape'){
   const ime=new r.w.KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true,cancelable:true});
   input.dispatchEvent(ime);assert.equal(ime.defaultPrevented,false);assert.equal(r.$('#filter-dialog').hidden,false);
   const escape=new r.w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true});
   input.dispatchEvent(escape);assert.equal(escape.defaultPrevented,true);
  }else r.$('#cancel-filter-draft').click();
  await wait();assert.equal(r.$('#search'),input);assert.ok(input.closest('.toolbar-search'));
  assert.equal(input.value,'');assert.equal(r.calls.length,n);assert.equal(r.$('#filter-dialog').hidden,true);
  assert.equal(r.$('#open-filters').getAttribute('aria-expanded'),'false');assert.equal(r.w.document.activeElement,r.$('#open-filters'));
 }finally{r.close()}}
});

test('filter toggle preserves unapplied selections without querying or changing applied chips',async()=>{
 const r=await ready('?view=all&free=true');try{
  const n=r.calls.length,url=r.w.location.href,stored=saved(r),chips=r.$('#active-filters').textContent;
  r.$('#open-filters').click();r.change('#attendance','online');
  r.$('#search').value='保留的草稿';r.$('#search').dispatchEvent(new r.w.Event('input',{bubbles:true}));
  r.$('#open-filters').click();assert.equal(r.$('#filter-dialog').hidden,true);
  assert.equal(r.$('#open-filters').getAttribute('aria-expanded'),'false');
  r.$('#open-filters').click();assert.equal(r.$('#filter-dialog').hidden,false);
  assert.equal(r.$('#attendance').value,'online');assert.equal(r.$('#search').value,'保留的草稿');assert.equal(r.$('#free').checked,true);
  await wait();assert.equal(r.calls.length,n);assert.equal(r.w.location.href,url);assert.equal(saved(r),stored);assert.equal(r.$('#active-filters').textContent,chips);
  r.$('#cancel-filter-draft').click();assert.equal(r.$('#attendance').value,'all');assert.equal(r.$('#search').value,'');assert.equal(r.$('#free').checked,true);
  assert.equal(r.$('#filter-dialog').hidden,true);assert.equal(r.calls.length,n);assert.equal(r.w.location.href,url);
 }finally{r.close()}
});

test('invalid date edits cannot navigate, poison storage, or leak into detail URLs',async()=>{
 for(const [from,until] of [['2026-10-02',''],['','2026-10-02'],['2026-10-31','2026-10-01'],['2026-01-01','2026-10-31']]){
  const r=await ready('?view=all&'+applied);try{const oldURL=r.w.location.href,oldSaved=saved(r),n=r.calls.length;
   r.$('#date-from').value=from;r.$('#date-until').value=until;r.$('[data-view="favorites"]').click();await wait();
   assert.equal(r.w.location.href,oldURL);assert.equal(saved(r),oldSaved);assert.equal(r.calls.length,n);assert.equal(r.w.probe.busy,false);assert.ok(r.$('#date-error').textContent);assert.equal(r.$('#view-title').textContent,'全部活动');
   await r.w.probe.openDetail('0');assert.equal(new URL(r.w.location.href).searchParams.get('from'),'2026-10-01');assert.equal(new URL(r.w.location.href).searchParams.get('until'),'2026-10-31');assert.equal(saved(r),oldSaved);
   await r.w.probe.load();assert.equal(r.calls.at(-1).get('start'),'2026-10-01');assert.equal(r.calls.at(-1).get('end'),'2026-11-01');assert.equal(r.w.probe.busy,false);
  }finally{r.close()}
 }
});

test('invalid legacy storage and explicit URLs fail visibly and recover without dropping other preferences',async()=>{
 for(const dates of ['from=2026-10-01','until=2026-10-31','from=2026-10-31&until=2026-10-01','from=2026-01-01&until=2026-10-31','from=2026-02-30&until=2026-02-31','from=garbage&until=garbage']){
  for(const stored of [true,false]){const q='attendance=online&districts='+encodeURIComponent('南山')+'&'+dates,raw=JSON.stringify({version:1,query:q});const r=await ready(stored?'':'?view=all&'+q,stored?raw:null);try{
   assert.equal(r.calls.length,0);assert.equal(r.w.probe.busy,false);assert.ok(r.$('#date-error').textContent);assert.equal(r.$('#notice').hidden,false);assert.ok(r.$('#notice').textContent.includes('日期'));assert.equal(r.$('#event-list').getAttribute('aria-busy'),'false');
   if(stored)assert.equal(saved(r),raw);else assert.equal(saved(r),null);
   r.$('#clear-dates').click();await wait();assert.equal(r.calls.length,1);assert.equal(r.w.probe.busy,false);assert.equal(r.$('#notice').hidden,true);assert.equal(r.$('#date-error').textContent,'');
   const p=new URLSearchParams(JSON.parse(saved(r)).query);assert.equal(p.has('from'),false);assert.equal(p.has('until'),false);assert.equal(p.get('attendance'),'online');assert.deepEqual(p.getAll('districts'),['南山']);
  }finally{r.close()}}
 }
});

test('URL priority and valid persisted dates survive bare entry, malformed JSON, and history recovery',async()=>{
 const raw=JSON.stringify({version:1,query:applied+'&q=stored'});
 for(const [query,storage,start] of [['',raw,'2026-10-01'],['?view=all',raw,null],['','broken',null]]){const r=await ready(query,storage);try{assert.equal(r.calls.at(-1).get('start'),start);assert.equal(r.w.probe.busy,false)}finally{r.close()}}
 const r=await ready('?view=all&'+applied);try{const previous=saved(r);r.w.history.pushState({},'','?view=all&from=2026-10-01');r.w.probe.restoreNavigation();await wait();assert.equal(saved(r),previous);assert.equal(r.w.probe.busy,false);assert.equal(r.$('#notice').hidden,false);
  const back=new Promise(resolve=>r.w.addEventListener('popstate',resolve,{once:true}));r.w.history.back();await back;await wait();assert.equal(r.calls.at(-1).get('start'),'2026-10-01');assert.equal(r.$('#date-error').textContent,'');assert.equal(r.$('#notice').hidden,true);
 }finally{r.close()}
});

test('personal and lifecycle views apply dates while preserving their own period and URL',async()=>{
 for(const [view,period] of [['favorites','saved'],['feedback','feedback'],['history','history'],['review','review'],['past','past']]){const r=await ready('?view='+view+'&'+applied);try{
  assert.equal(r.$('#date-from').disabled,false);assert.equal(r.$('#date-until').disabled,false);assert.equal(r.$('#apply-dates').disabled,false);assert.equal(r.calls.at(-1).get('period'),period);assert.equal(r.calls.at(-1).get('start'),'2026-10-01');assert.equal(r.calls.at(-1).get('end'),'2026-11-01');assert.ok(r.$('#active-filters').textContent.includes('2026-10-01 至 2026-10-31'));assert.equal(r.$('.title-button').textContent,'收藏 2026-10-05');
  if(['favorites','feedback','history'].includes(view)){assert.equal(r.calls.at(-1).get('hide_long'),'false');assert.ok(r.$('#date-scope-note').textContent.includes('非收藏、反馈或浏览日期'))}if(view==='favorites')assert.equal(r.calls.at(-1).get('favorites'),'true');
  assert.equal(new URL(r.w.location.href).searchParams.get('view'),view);r.$('#date-until').value='2026-10-20';r.$('#apply-dates').click();await wait();assert.equal(r.calls.at(-1).get('period'),period);assert.equal(r.calls.at(-1).get('end'),'2026-10-21');assert.equal(new URL(r.w.location.href).searchParams.get('view'),view);
 }finally{r.close()}}
});

test('calendar explains month scope and retains custom dates for return to a list',async()=>{
 const r=await ready('?view=calendar&month=2026-11-01&'+applied);try{
  assert.equal(r.$('#date-from').disabled,true);assert.equal(r.$('#date-until').disabled,true);assert.equal(r.$('#apply-dates').disabled,true);assert.equal(r.$('#date-scope-note').hidden,false);assert.ok(r.$('#date-scope-note').textContent.includes('不应用'));assert.equal(r.$('#active-filters').textContent.includes('2026-10-01 至 2026-10-31'),false);assert.equal(r.calls.at(-1).get('period'),'calendar');assert.equal(r.calls.at(-1).get('start'),'2026-11-01');assert.equal(r.calls.at(-1).get('end'),'2026-12-01');
  assert.equal(new URL(r.w.location.href).searchParams.get('from'),'2026-10-01');r.w.probe.navigate('all');await wait();assert.equal(r.$('#date-from').disabled,false);assert.equal(r.$('#date-scope-note').hidden,true);assert.equal(r.calls.at(-1).get('start'),'2026-10-01');assert.equal(r.calls.at(-1).get('end'),'2026-11-01');assert.ok(r.$('#active-filters').textContent.includes('2026-10-01 至 2026-10-31'));assert.equal(r.$('.title-button').textContent,'收藏 2026-10-05');
 }finally{r.close()}
});

test('mobile dependencies follow the draft; cancel/reset query zero times and apply queries once',async()=>{
 const r=await ready('?view=all&attendance=online&districts='+encodeURIComponent('南山'));try{const n=r.calls.length,oldURL=r.w.location.href,oldSaved=saved(r);
  r.$('#open-filters').click();for(const mode of ['offline','online','hybrid','online']){r.change('#attendance',mode);assert.equal(r.$('#district-filter').hidden,mode==='online');assert.equal(r.$('#district-options input').disabled,mode==='online');assert.equal(r.calls.length,n);assert.equal(r.w.location.href,oldURL);assert.equal(saved(r),oldSaved)}
  r.$('#reset-filter-draft').click();assert.equal(r.$('#district-filter').hidden,false);assert.equal(r.$('#district-options input').disabled,false);assert.equal(r.calls.length,n);r.$('#cancel-filter-draft').click();assert.equal(r.$('#district-filter').hidden,true);assert.equal(r.$('#district-options input').disabled,true);assert.equal(r.$('#district-options input[value="南山"]').checked,true);assert.equal(r.$('#district-options input[value="福田"]').checked,false);assert.equal(r.calls.length,n);
  r.$('#open-filters').click();r.change('#attendance','offline');r.$('#district-options input[value="南山"]').checked=false;r.$('#district-options input[value="福田"]').checked=true;r.$('#apply-filter-draft').click();await wait();assert.equal(r.calls.length,n+1);assert.equal(r.calls.at(-1).get('attendance'),'offline');assert.deepEqual(r.calls.at(-1).getAll('districts'),['福田']);assert.equal(r.$('#district-filter').hidden,false);
 }finally{r.close()}
});

test('invalid named views are rejected before changing history or persisting filters',async()=>{
 const profiles=[{name:'旧坏日期',query:'view=all&from=2026-10-01'},{name:'有效日期',query:'view=all&'+applied}];const r=await ready('?view=all',null,profiles);try{const oldURL=r.w.location.href,oldSaved=saved(r),n=r.calls.length;r.$('#saved-view-choice').value='0';r.$('#apply-saved-view').click();await wait();assert.equal(r.w.location.href,oldURL);assert.equal(saved(r),oldSaved);assert.equal(r.calls.length,n);assert.ok(r.$('#toast').textContent.includes('日期'));assert.equal(r.w.probe.busy,false);
  r.$('#saved-view-choice').value='1';r.$('#apply-saved-view').click();await wait();assert.equal(r.calls.length,n+1);assert.equal(r.calls.at(-1).get('start'),'2026-10-01');assert.equal(r.calls.at(-1).get('end'),'2026-11-01');
 }finally{r.close()}
});

test('calendar draft reset then cancel preserves saved-only URL and next request',async()=>{
 const r=await ready('?view=calendar&month=2026-10-01&saved_only=true');try{const n=r.calls.length,oldURL=r.w.location.href;r.$('#open-filters').click();r.$('#reset-filter-draft').click();r.$('#cancel-filter-draft').click();assert.equal(r.$('#calendar-saved-only').checked,true);assert.equal(r.w.location.href,oldURL);assert.equal(r.calls.length,n);await r.w.probe.load();await wait();assert.equal(r.calls.at(-1).get('favorites'),'true');
 }finally{r.close()}
});

test('saved-query sanitization cannot discard oversized invalid dates or late valid dates',async()=>{
 const profiles=[{name:'坏日期',query:'view=all&from='+'a'.repeat(181)+'&until='+'b'.repeat(181)},{name:'晚出现的日期',query:'q='+'x'.repeat(4100)+'&view=all&'+applied}];const r=await ready('?view=all&'+applied,null,profiles);try{const url=r.w.location.href,n=r.calls.length;r.$('#saved-view-choice').value='0';r.$('#apply-saved-view').click();await wait();assert.equal(r.w.location.href,url);assert.equal(r.calls.length,n);assert.ok(r.$('#toast').textContent.includes('日期'));r.$('#saved-view-choice').value='1';r.$('#apply-saved-view').click();await wait();assert.equal(r.calls.at(-1).get('start'),'2026-10-01');assert.equal(r.calls.at(-1).get('end'),'2026-11-01');
 }finally{r.close()}
});

test('mobile malformed-date reset can be cancelled or deliberately applied',async()=>{
 const r=await ready('?view=all&from=garbage&until=garbage&attendance=online');try{const url=r.w.location.href;r.$('#open-filters').click();r.$('#reset-filter-draft').click();r.$('#cancel-filter-draft').click();assert.equal(r.calls.length,0);assert.equal(r.w.location.href,url);assert.ok(r.$('#date-error').textContent);r.$('#open-filters').click();r.$('#reset-filter-draft').click();r.$('#apply-filter-draft').click();await wait();assert.equal(r.calls.length,1);assert.equal(r.$('#date-error').textContent,'');assert.equal(r.w.probe.busy,false);
 }finally{r.close()}
});

test('saving a valid pending date pair retains that pair without applying or issuing a query',async()=>{
 const r=await ready();try{const n=r.calls.length,url=r.w.location.href;r.$('#date-from').value='2026-10-01';r.$('#date-until').value='2026-10-31';r.$('#saved-view-name').value='十月';r.$('#save-view-form').dispatchEvent(new r.w.Event('submit',{bubbles:true,cancelable:true}));await wait();assert.equal(r.calls.length,n);assert.equal(r.w.location.href,url);const profiles=JSON.parse(r.w.localStorage.getItem('radar.saved.v1:fixture'));assert.equal(new URLSearchParams(profiles[0].query).get('until'),'2026-10-31');r.$('#saved-view-choice').value='0';r.$('#apply-saved-view').click();await wait();assert.equal(r.calls.length,n+1);assert.equal(r.calls.at(-1).get('start'),'2026-10-01');
 }finally{r.close()}
});

test('closing a deep-linked detail removes only the event even when legacy dates are invalid',async()=>{
 const r=await ready('?view=all&from=garbage&until=garbage&event=0');try{assert.equal(r.$('#detail').open,true);r.w.probe.closeDetail();await wait();const p=new URL(r.w.location.href).searchParams;assert.equal(p.has('event'),false);assert.equal(p.get('from'),'garbage');assert.equal(p.get('until'),'garbage');assert.equal(saved(r),null);assert.equal(r.$('#detail').open,false);r.w.probe.restoreNavigation();await wait();assert.equal(r.$('#detail').open,false);assert.equal(r.calls.length,0);assert.ok(r.$('#date-error').textContent);
 }finally{r.close()}
});


test('blocked invalid-date edit cannot persist non-date controls via detail',async()=>{
 const r=await ready('?view=all&'+applied);try{const oldSaved=saved(r),n=r.calls.length;
 r.$('#date-until').value='';r.change('#attendance','online');await wait();
 assert.equal(r.calls.length,n);assert.equal(saved(r),oldSaved);assert.ok(r.$('#date-error').textContent);
 await r.w.probe.openDetail('0');assert.equal(saved(r),oldSaved);assert.equal(new URL(r.w.location.href).searchParams.has('attendance'),false);
 }finally{r.close()}
});
test('blocked invalid-date edit cannot alter refresh query',async()=>{
 const r=await ready('?view=all&'+applied);try{const oldQuery=r.calls.at(-1).toString();
 r.$('#date-until').value='';r.change('#attendance','online');await wait();await r.w.probe.load();
 assert.equal(r.calls.at(-1).toString(),oldQuery);
 }finally{r.close()}
});
test('cancelling a fast mobile search draft must make zero listing requests',async()=>{
 const r=await ready('?view=all&'+applied);try{const n=r.calls.length;
 r.$('#open-filters').click();r.$('#search').value='pending';r.$('#search').dispatchEvent(new r.w.Event('input',{bubbles:true}));r.$('#cancel-filter-draft').click();
 await new Promise(res=>setTimeout(res,350));assert.equal(r.calls.length,n);
 }finally{r.close()}
});
test('cancelling mobile search draft cannot commit preexisting pending dates',async()=>{
 const r=await ready('?view=all');try{const oldSaved=saved(r),oldURL=r.w.location.href;
 r.$('#date-from').value='2026-10-01';r.$('#date-until').value='2026-10-31';
 r.$('#open-filters').click();r.$('#search').value='pending';r.$('#search').dispatchEvent(new r.w.Event('input',{bubbles:true}));r.$('#cancel-filter-draft').click();
 await new Promise(res=>setTimeout(res,350));assert.equal(r.w.location.href,oldURL);assert.equal(saved(r),oldSaved);
 }finally{r.close()}
});


test('all non-date controls remain a draft after validation fails; result summaries and recovery stay applied',async()=>{
 const r=await ready('?view=all&'+applied);try{const oldSaved=saved(r),oldQuery=r.calls.at(-1).toString(),oldSummary=r.$('#active-filters').textContent;
  r.$('#date-until').value='';r.change('#attendance','online');r.change('#search','pending text');r.change('#sort','desc');r.$('#free').checked=true;r.$('#free').dispatchEvent(new r.w.Event('change',{bubbles:true}));r.$('[data-facet-kind="type"][data-facet-action="none"]').click();
  await r.w.probe.openDetail('0');assert.equal(saved(r),oldSaved);await r.w.probe.load();assert.equal(r.calls.at(-1).toString(),oldQuery);assert.equal(r.$('#active-filters').textContent,oldSummary);assert.equal(r.$('#attendance').value,'online');assert.equal(r.$('#search').value,'pending text');
  r.$('#date-until').value='2026-10-31';const n=r.calls.length;r.$('#apply-dates').click();await wait();assert.equal(r.calls.length,n+1);const p=r.calls.at(-1);assert.equal(p.get('attendance'),'online');assert.equal(p.get('q'),'pending text');assert.equal(p.get('sort'),'desc');assert.equal(p.get('free'),'true');assert.equal(p.get('type_none'),'true');assert.ok(r.$('#active-filters').textContent.includes('pending text'));
 }finally{r.close()}
});

test('draft search and IME cancel never query; applying a draft queries exactly once after debounce time',async()=>{
 for(const action of ['cancel','apply']){const r=await ready('?view=all&'+applied);try{const n=r.calls.length,oldURL=r.w.location.href;r.$('#open-filters').click();r.$('#search').dispatchEvent(new r.w.Event('compositionstart',{bubbles:true}));r.$('#search').value='中文';r.$('#search').dispatchEvent(new r.w.Event('input',{bubbles:true}));r.$('#search').dispatchEvent(new r.w.Event('compositionend',{bubbles:true}));r.$('#'+action+'-filter-draft').click();await new Promise(resolve=>setTimeout(resolve,350));assert.equal(r.calls.length,n+(action==='apply'?1:0));if(action==='cancel'){assert.equal(r.w.location.href,oldURL);assert.equal(r.$('#search').value,'')}else assert.equal(r.calls.at(-1).get('q'),'中文');
 }finally{r.close()}}
});

test('unsupported Gregorian and exclusive-end years fail before persistence and require explicit correction',async()=>{
 for(const dates of ['from=0000-01-01&until=0000-01-02','from=9999-12-30&until=9999-12-31']){const raw=JSON.stringify({version:1,query:dates}),r=await ready('',raw);try{assert.equal(r.calls.length,0);assert.equal(saved(r),raw);assert.ok(r.$('#date-error').textContent);r.change('#attendance','online');assert.equal(saved(r),raw);assert.equal(r.calls.length,0);r.$('#clear-dates').click();await wait();assert.equal(r.calls.length,1);assert.equal(r.calls.at(-1).get('attendance'),'online');assert.equal(r.calls.at(-1).has('start'),false);
 }finally{r.close()}}
 const r=await ready('?view=all&from=9999-12-30&until=9999-12-30');try{assert.equal(r.calls.at(-1).get('start'),'9999-12-30');assert.equal(r.calls.at(-1).get('end'),'9999-12-31')}finally{r.close()}
});


// A valid named view is intentional navigation even if a draft is folded.
test('valid saved view retires visible or folded unapplied drafts and renders its results',async()=>{
 for(const folded of [false,true]){
  const profiles=[{name:'十一月',query:'view=all&from=2026-11-01&until=2026-11-30'}];
  const r=await ready('?view=all&'+applied,null,profiles);
  try{
   const n=r.calls.length;
   r.$('#open-filters').click();r.$('#search').value='未应用草稿';
   r.$('#search').dispatchEvent(new r.w.Event('input',{bubbles:true}));
   if(folded)r.$('#open-filters').click();
   assert.equal(r.calls.length,n);
   r.$('#saved-view-choice').value='0';r.$('#apply-saved-view').click();await wait();await wait();
   assert.equal(r.calls.length,n+1,'saved view must issue its November request');
   assert.equal(r.calls.at(-1).get('start'),'2026-11-01');
   assert.equal(r.calls.at(-1).get('end'),'2026-12-01');
   assert.equal(r.calls.at(-1).has('q'),false);
   assert.equal(r.$('.title-button').textContent,'收藏 2026-11-05');
   assert.equal(r.$('#filter-dialog').hidden,true);
   assert.equal(r.$('#open-filters').classList.contains('has-draft'),false);
   await r.w.probe.load();await wait();
   assert.equal(r.calls.length,n+2,'retired draft cannot block later reloads');
  }finally{r.close()}
 }
});
test('invalid saved view retains visible or folded draft without query or history changes',async()=>{
 for(const folded of [false,true]){
  const profiles=[{name:'坏日期',query:'view=all&from=2026-11-01'}];
  const r=await ready('?view=all&'+applied,null,profiles);
  try{
   const url=r.w.location.href,n=r.calls.length,stored=saved(r);
   r.$('#open-filters').click();r.$('#search').value='保留草稿';
   r.$('#search').dispatchEvent(new r.w.Event('input',{bubbles:true}));
   if(folded)r.$('#open-filters').click();
   r.$('#saved-view-choice').value='0';r.$('#apply-saved-view').click();await wait();
   assert.equal(r.w.location.href,url);assert.equal(r.calls.length,n);assert.equal(saved(r),stored);
   assert.equal(r.$('#search').value,'保留草稿');
   assert.equal(r.$('#filter-dialog').hidden,folded);
   assert.equal(r.$('#open-filters').classList.contains('has-draft'),true);
   assert.ok(r.$('#toast').textContent.includes('日期'));
   r.$('#apply-filter-draft').click();await wait();
   assert.equal(r.calls.length,n+1);assert.equal(r.calls.at(-1).get('q'),'保留草稿');
  }finally{r.close()}
 }
});
