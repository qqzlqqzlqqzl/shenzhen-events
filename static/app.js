'use strict';
let view='discover',offset=0,total=0,sequence=0,calendar=null,controller=null;
let authenticated=false,authEpoch=0,statusTicket=0,statsTicket=0,detailTicket=0,busy=false;
let calendarDate='',calendarRange=null,detailId=null,debounce=null,composing=false,opener=null;
let listSnapshot=null,calendarSnapshot=null;
let filterDraft=null;
// Date inputs are a draft until explicitly applied; detail/refresh URLs use this pair.
let appliedDates={from:'',until:''},appliedFilterQuery=null,dateLoadError='',dateLoadValues=null;
let undoFeedback=null,personalQueryDirty=false;
const records=new Map(),inflight=new Set(),saving=new Set(),feedbackSaving=new Set();
const facetCatalog={type:new Map(),topic:new Map(),district:new Map()};
function checkedFacet(kind){return $$(`#${kind}-options input[type="checkbox"]:checked`).map(x=>x.value)}
function updateFacetSummary(kind){const n=checkedFacet(kind).length,total=$$(`#${kind}-options input[type="checkbox"]`).length,unit={type:'类',topic:'个主题',district:'区'}[kind];$(`#${kind}-summary`).textContent=n===total?'全部':!n?'未选择':n>total/2?`已排除 ${total-n} ${unit}`:`已选 ${n} ${unit}`}
function renderFacetOptions(kind,items,pending=0){
  const box=$(`#${kind}-options`),hadOptions=!!box.querySelector('input'),selected=new Set(checkedFacet(kind)),wasAll=hadOptions&&selected.size===box.querySelectorAll('input').length;facetCatalog[kind]=new Map((items||[]).map(x=>[x.value,x.label]));box.replaceChildren();
  if(kind==='type'&&pending){const note=document.createElement('p');note.className='facet-progress';note.textContent='类型未明确的活动，在选择“全部”时仍会显示。';box.append(note)}
  for(const item of items||[]){const label=document.createElement('label');label.className='facet-option';const input=document.createElement('input');input.type='checkbox';input.value=item.value;input.checked=!hadOptions||wasAll||selected.has(item.value);input.setAttribute('aria-label',item.label);const text=document.createElement('span');text.textContent=item.label;label.append(input,text);if(kind!=='district'){const count=document.createElement('small');count.dataset.facetCount='';count.textContent='—';count.title='数量按其他已应用筛选条件统计；—表示当前统计尚未取得。';label.append(count)}box.append(label)}
  if(!(items||[]).length){const empty=document.createElement('p');empty.className='facet-empty';empty.textContent='暂无可用选项。';box.append(empty)}
  updateFacetSummary(kind);
}
function updateFacetCounts(facets){
  for(const kind of ['type','topic','district']){const counts=new Map((facets?.[kind]||[]).map(x=>[x.value,x.count]));for(const input of $$(`#${kind}-options input`)){const label=input.closest('label'),count=counts.get(input.value),small=label.querySelector('[data-facet-count]');label.classList.toggle('is-empty',count===0);if(small)small.textContent=Number.isFinite(count)?String(count):'—'}}
}
function resultCountText(count,excluded){return `符合当前筛选 ${count} 个活动${excluded?.total?` · 另 ${excluded.total} 项长期/重复未计入（下方灰色列出）`:''}`}
function renderExcluded(excluded){
  const box=$('#excluded-events');box.replaceChildren();box.hidden=!excluded?.total||view==='status';if(box.hidden)return;
  const heading=document.createElement('h3');heading.textContent=`未计入结果：${excluded.total} 项长期/重复活动`;
  const hint=document.createElement('p');hint.textContent=`以下活动仍满足其他条件，只因开放或重复区间达到 ${excluded.threshold_days||14} 天，被当前“隐藏长期/重复”规则排除。`;
  const include=document.createElement('button');include.type='button';include.className='secondary';include.dataset.action='include-long';include.textContent='纳入长期/重复活动';
  const list=document.createElement('div');list.className='excluded-list';for(const e of excluded.items||[]){const row=document.createElement('div');row.className='excluded-event-row';const title=document.createElement('button');title.type='button';title.dataset.open=e.id;title.textContent=e.title;title.setAttribute('aria-label','查看未计入结果的活动：'+e.title);const meta=document.createElement('span');meta.textContent=RadarUI.fullTime(e)+' · 未计入：长期/重复';row.append(title,meta);list.append(row)}
  box.append(heading,hint,include,list);if(excluded.truncated){const more=document.createElement('p');more.textContent=`已显示 ${excluded.items.length} 项，共 ${excluded.total} 项；点击“纳入长期/重复活动”后可查看全部。`;box.append(more)}
}
function renderActiveFilters(){
  const box=$('#active-filters'),p=urlParams();box.replaceChildren();
  const addChip=(kind,value,exclude)=>{const b=document.createElement('button');b.type='button';b.className='filter-chip'+(exclude?' excluded-filter-chip':'');b.dataset.facetRemove=kind;b.dataset.facetValue=value;b.dataset.facetExcluded=String(exclude);b.textContent=(exclude?'排除：':'')+(facetCatalog[kind].get(value)||value)+' ×';box.append(b)};
  for(const kind of ['type','topic','district']){const all=$$(`#${kind}-options input`),values=p.getAll(kind==='district'?'districts':kind),selected=p.get(kind+'_none')==='true'?[]:values.length?values:all.map(x=>x.value);if(selected.length===all.length||(kind==='district'&&p.get('attendance')==='online'))continue;if(!selected.length){const note=document.createElement('span');note.textContent=({type:'活动类型',topic:'主题',district:'地区'}[kind])+'：未选择';box.append(note)}else{const exclude=selected.length>all.length/2;for(const x of all.filter(x=>exclude?!selected.includes(x.value):selected.includes(x.value)))addChip(kind,x.value,exclude)}}
  const rest=[p.get('q')?'关键词：'+p.get('q'):'',p.get('free')==='true'?'只看免费':'',['favorites','feedback','history'].includes(view)?'此视图包含长期/重复':p.get('show_long')!=='true'?'排除：长期/重复（≥14天）':'包含长期/重复',p.get('sort')==='desc'?'举办日期：从新到旧':'',p.get('attendance')?$('#attendance').querySelector(`option[value="${p.get('attendance')}"]`)?.textContent:''].filter(Boolean);
  if(view!=='calendar'&&!dateLoadError&&appliedDates.from&&appliedDates.until)rest.push(appliedDates.from+' 至 '+appliedDates.until);
  for(const [key,id] of [['feedback','feedback-filter'],['feedback_tag','feedback-tag-filter'],['viewed','viewed-filter']]){const value=p.get(key);if(value&&value!=='all')rest.push($('#'+id).querySelector(`option[value="${value}"]`)?.textContent||'')}
  if(rest.length){const span=document.createElement('span');span.className='filter-text';span.textContent=rest.join(' · ');box.append(span)}
}
async function api(path,options={}) {
  const epoch=authEpoch,c=new AbortController(),abort=()=>c.abort();
  if(options.signal?.aborted)c.abort();else options.signal?.addEventListener('abort',abort,{once:true});
  inflight.add(c);let timedOut=false;
  const timer=setTimeout(()=>{timedOut=true;c.abort()},20000);
  try {
    const r=await fetch('/events/api/'+path,{credentials:'same-origin',...options,signal:c.signal,headers:{'Content-Type':'application/json','X-Radar-Request':'1',...(options.headers||{})}});
    if(epoch!==authEpoch)throw new DOMException('Stale session','AbortError');
    if(r.status===401&&path!=='login'){showLogin('登录已过期，请重新登录。');throw new DOMException('Expired session','AbortError')}
    let data;try{data=await r.json()}catch{throw new Error('服务器返回异常，请重试。')}
    if(epoch!==authEpoch)throw new DOMException('Stale session','AbortError');
    if(!r.ok){const err=new Error(typeof data.detail==='string'?data.detail:'请求失败，请重试。');err.status=r.status;err.current=data.current;throw err}
    return data;
  } catch(e) {if(timedOut)throw new Error('请求超时，已有数据未更改，请重试。');throw e}
  finally {clearTimeout(timer);inflight.delete(c);options.signal?.removeEventListener('abort',abort)}
}
function showLogin(message='') {
  // Invalidate session callbacks before closing dialogs or restoring any focus.
  authenticated=false;authEpoch++;
  resetStatusRecovery();personalQueryDirty=false;listSnapshot=null;calendarSnapshot=null;renderExcluded(null);updateFacetCounts(null);$('#network-banner').hidden=true;if(filterDraft)finishFilterDraft(false);RadarEventWorkflows.clear();undoFeedback=null;$('#undo-bar').hidden=true;sequence++;detailTicket++;statusTicket++;busy=false;
  clearTimeout(debounce);for(const c of inflight)c.abort();inflight.clear();controller?.abort();
  closeDetail(false);records.clear();saving.clear();feedbackSaving.clear();calendar?.destroy();calendar=null;calendarRange=null;
  for(const s of ['#event-list','#status-panel','#calendar','#calendar-long','#detail-body'])$(s).replaceChildren();
  $('.hero').hidden=false;$('#manage-sources').hidden=true;$('#workspace').hidden=true;$('#login-panel').hidden=false;$('#logout').hidden=true;clearTimeout(toast.t);$('#toast').hidden=true;$('#toast').textContent='';
  $('#login-error').textContent=message;$('#password').value='';$('#username').focus();
}
async function stats() {
  const epoch=authEpoch,ticket=++statsTicket;
  try {const s=await api('stats');if(!authenticated||epoch!==authEpoch||ticket!==statsTicket)return;
    $('#count-recommended').textContent=s.recommended;$('#count-upcoming').textContent=s.upcoming;$('#count-weekend').textContent=s.weekend;
    $('#update-note').textContent=s.last_updated?'全站统计 · 最近更新：'+timeText(s.last_updated):'活动正在整理中';
    if(!$('#district-options input'))renderFacetOptions('district',[...(s.districts||[]).map(v=>({value:v,label:v})),{value:'待确认',label:'地区待确认'}]);
    if(!$('#type-options input'))renderFacetOptions('type',s.event_types||[],s.type_pending||0);if(!$('#topic-options input'))renderFacetOptions('topic',s.topics||[]);
  }catch(e){if(e.name!=='AbortError'&&authenticated&&epoch===authEpoch)$('#update-note').textContent=e.message}
}
let filterStorageKey='radar.filters.v1:owner';
const filterKeys=new Set(['q','district','districts','district_none','type','topic','type_none','topic_none','tag','free','show_long','sort','attendance','feedback','feedback_tag','viewed','from','until','saved_only']);
function rememberFilters(){
  try{const p=urlParams();RadarPlanner.range(p.get('from')||'',p.get('until')||'');for(const k of [...p.keys()])if(!filterKeys.has(k))p.delete(k);localStorage.setItem(filterStorageKey,JSON.stringify({version:1,query:p.toString()}))}catch{}
}
function restoreSavedFilters(){
  const explicit=new URLSearchParams(location.search);
  if([...explicit.keys()].some(k=>filterKeys.has(k)||['view','month','event'].includes(k)))return;
  try{const saved=JSON.parse(localStorage.getItem(filterStorageKey)||'null');if(saved?.version!==1||typeof saved.query!=='string'||saved.query.length>4096)return;
    const p=new URLSearchParams(saved.query);for(const k of [...p.keys()])if(!filterKeys.has(k))p.delete(k);
    for(const [k,v] of p)explicit.append(k,v);
    if(p.size)history.replaceState({radar:true},'',location.pathname+'?'+explicit.toString());
  }catch{}
}
function readURL() {
  const p=new URLSearchParams(location.search);view=Object.hasOwn(views,p.get('view'))?p.get('view'):'discover';
  $('#attendance').value=['online','offline','hybrid','unknown'].includes(p.get('attendance'))?p.get('attendance'):'all';
  $('#search').value=(p.get('q')||'').slice(0,160);$('#free').checked=p.get('free')==='true';$('#hide-long').checked=p.get('show_long')!=='true';$('#sort').value=p.get('sort')==='desc'?'desc':'asc';
  $('#feedback-filter').value=p.get('feedback')||'';$('#feedback-tag-filter').value=p.get('feedback_tag')||'';$('#viewed-filter').value=p.get('viewed')||'all';
  appliedDates={from:p.get('from')||'',until:p.get('until')||''};
  $('#date-from').value=appliedDates.from;$('#date-until').value=appliedDates.until;
  dateLoadError='';try{RadarPlanner.range(appliedDates.from,appliedDates.until)}catch(e){dateLoadError=e.message}
  dateLoadValues={from:$('#date-from').value,until:$('#date-until').value};$('#date-error').textContent=dateLoadError;
  const topicAlias=x=>x==='展览文化'?'文化艺术':x;
  const selectedTypes=new Set(p.getAll('type')),selectedTopics=new Set(p.getAll('topic').map(topicAlias));const legacy=p.get('tag');if(legacy)selectedTopics.add(topicAlias(legacy));
  $$('#type-options input[type="checkbox"]').forEach(x=>x.checked=p.get('type_none')!=='true'&&(!selectedTypes.size||selectedTypes.has(x.value)));$$('#topic-options input[type="checkbox"]').forEach(x=>x.checked=p.get('topic_none')!=='true'&&(!selectedTopics.size||selectedTopics.has(x.value)));updateFacetSummary('type');updateFacetSummary('topic');
  const districts=new Set([...p.getAll('districts'),...p.getAll('district')].filter(Boolean));
  $$('#district-options input[type="checkbox"]').forEach(x=>x.checked=p.get('district_none')!=='true'&&(!districts.size||districts.has(x.value)));updateFacetSummary('district');
  $('#calendar-saved-only').checked=p.get('saved_only')==='true';
  const month=p.get('month')||'';calendarDate=/^\d{4}-\d{2}-\d{2}$/.test(month)&&Number.isFinite(Date.parse(month))?month:RadarUI.dayKey(new Date());
  appliedFilterQuery=draftParams().toString();
}
function draftParams() {
  const p=new URLSearchParams();if(view!=='discover')p.set('view',view);
  for(const [k,id] of [['q','search']]){const v=$('#'+id).value.trim();if(v)p.set(k,v)}
  for(const kind of ['type','topic','district']){const selected=checkedFacet(kind),total=$$(`#${kind}-options input`).length;if(total&&!selected.length)p.set(kind+'_none','true');else if(selected.length<total)for(const v of selected)p.append(kind==='district'?'districts':kind,v)}
  for(const [key,id] of [['feedback','feedback-filter'],['feedback_tag','feedback-tag-filter'],['viewed','viewed-filter']]){const v=$('#'+id).value;if(v&&v!=='all')p.set(key,v)}
  if($('#calendar-saved-only').checked)p.set('saved_only','true');
  if(appliedDates.from)p.set('from',appliedDates.from);if(appliedDates.until)p.set('until',appliedDates.until);
  if($('#attendance').value!=='all')p.set('attendance',$('#attendance').value);
  if($('#free').checked)p.set('free','true');if(!$('#hide-long').checked)p.set('show_long','true');if($('#sort').value==='desc')p.set('sort','desc');if(view==='calendar'&&calendarDate)p.set('month',calendarDate);return p;
}
// Requests, detail URLs, persistence, and result summaries only consume this snapshot.
// Controls may still contain an unapplied date/search/filter draft.
function urlParams() {
  const p=new URLSearchParams(appliedFilterQuery??draftParams());
  p.delete('view');if(view!=='discover')p.set('view',view);
  p.delete('month');if(view==='calendar'&&calendarDate)p.set('month',calendarDate);
  return p;
}
function writeURL(mode='push',event=null) {
  // Invalid legacy URLs remain editable, but are never newly persisted.
  try{RadarPlanner.range(appliedDates.from,appliedDates.until)}catch{
    const p=new URLSearchParams(location.search);if(event)p.set('event',event);else p.delete('event');
    const u=location.pathname+(p.size?'?'+p:'');if(u!==location.pathname+location.search)history[mode==='replace'?'replaceState':'pushState']({radar:true,radarModal:!!event&&mode==='push'},'',u);return;
  }
  rememberFilters();
  const p=urlParams();if(event)p.set('event',event);const u=location.pathname+(p.size?'?'+p:'');
  if(u!==location.pathname+location.search)history[mode==='replace'?'replaceState':'pushState']({radar:true,radarModal:!!event&&mode==='push'},'',u);
}
function clearFilters(){clearTimeout(debounce);dateLoadError='';$('#calendar-saved-only').checked=false;$('#date-from').value='';$('#date-until').value='';$('#date-error').textContent='';$('#feedback-filter').value='';$('#feedback-tag-filter').value='';$('#viewed-filter').value='all';$('#attendance').value='all';$('#search').value='';$$('#type-options input,#topic-options input,#district-options input').forEach(x=>x.checked=true);updateFacetSummary('type');updateFacetSummary('topic');updateFacetSummary('district');$('#free').checked=false;$('#hide-long').checked=true;$('#sort').value='asc';syncFilterControls()}
async function enter(user={}) {
  filterStorageKey='radar.filters.v1:'+String(user.username||'owner');RadarPlanner.user(user.username);
  authenticated=true;authEpoch++;$('.hero').hidden=true;$('#manage-sources').hidden=false;$('#login-panel').hidden=true;$('#workspace').hidden=false;$('#logout').hidden=false;
  await stats();if(!authenticated)return;restoreSavedFilters();readURL();rememberFilters();await load();const id=new URLSearchParams(location.search).get('event');if(id&&authenticated)await openDetail(id,false);
}
function query(period) {const p=urlParams();const r=RadarPlanner.range(p.get('from')||'',p.get('until')||'');p.delete('from');p.delete('until');if(r&&!period&&!['calendar','status'].includes(view)){if(!['favorites','feedback','history','review','past'].includes(view))period='range';p.set('start',r.start);p.set('end',r.end)}if(p.get('attendance')==='online'){p.delete('district');p.delete('districts');p.delete('district_none')}const showLong=p.get('show_long')==='true';p.delete('view');p.delete('month');p.delete('show_long');p.set('hide_long',showLong?'false':'true');if(p.get('saved_only')==='true'&&view==='calendar')p.set('favorites','true');p.delete('saved_only');p.set('period',period||({feedback:'feedback',history:'history',favorites:'saved',calendar:'calendar',week:'week',weekend:'weekend',review:'review',past:'past'}[view]||'upcoming'));if(view==='discover')p.set('recommended','true');if(view==='favorites')p.set('favorites','true');if(['favorites','feedback','history'].includes(view))p.set('hide_long','false');return p}
let failedAppend=false;
function showError(error,append=false){failedAppend=append;$('#notice').hidden=false;$('#notice').replaceChildren();const t=document.createElement('span');t.textContent=error.message||'网络连接失败，请重试。';const b=document.createElement('button');b.className='secondary';b.dataset.action=dateLoadError?'clear-invalid-dates':'retry';b.textContent=dateLoadError?'清除无效日期并查询':'重试';if(dateLoadError)t.textContent+=' 请修改日期，或清除日期后重新查询；其他筛选会保留。';$('#notice').append(t,b)}
function syncFilterControls(){
  const online=$('#attendance').value==='online';$('#district-filter').hidden=online;$$('#district-options input').forEach(x=>x.disabled=online);
  const monthly=view==='calendar';for(const id of ['date-from','date-until','apply-dates'])$('#'+id).disabled=monthly;
  const personal=['favorites','feedback','history'].includes(view);
  $('#date-scope-note').hidden=!monthly&&!personal;$('#date-scope-note').textContent=monthly?'月历按当前月份显示，不应用此处的日期；日期偏好仍保留，切回列表后生效。':personal?'按活动举办日期筛选，非收藏、反馈或浏览日期；包含跨日重叠，未确认举办日期的活动仅在设置日期后排除。':'';
  $('#hide-long').disabled=['favorites','feedback','history'].includes(view);
}
function showView(){
  syncFilterControls();$('#excluded-events').hidden=true;
  $('#personal-actions').hidden=view!=='feedback';$('#saved-views').hidden=view==='status';$('#open-filters').hidden=view==='status';
  $('#result-count').hidden=view==='status';$('#active-filters').hidden=view==='status';if(view==='status')$('#result-count').textContent='';
  $('#notice').hidden=true;$('#more').hidden=true;$('#status-panel').hidden=view!=='status';$('#calendar-panel').hidden=view!=='calendar';$('#event-list').hidden=['status','calendar'].includes(view);$('#filter-panel').hidden=view==='status';
  $('#view-title').textContent=views[view][0];$('#view-subtitle').textContent=views[view][1];
  $$('.tabs button').forEach(b=>{b.classList.toggle('active',b.dataset.view===view);if(b.dataset.view===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
  renderActiveFilters();
}
function emptyState(){const p=urlParams(),filtered=['feedback','feedback_tag','viewed','from','q','attendance','free','type','topic','districts','type_none','topic_none','district_none'].some(key=>p.has(key));return `<div class="empty"><b>${filtered?'当前筛选条件下没有活动':view==='favorites'?'还没有收藏活动':'这里暂时没有活动'}</b><p>${filtered?'试试重置筛选；其他收藏或活动不会被删除。':view==='favorites'?'点击活动卡片的星号即可收藏，过期后仍会保留。':'可以查看其他日期，或去全部活动探索。'}</p><button class="secondary" data-action="${filtered?'reset':'browse-all'}">${filtered?'重置筛选':'查看全部活动 →'}</button></div>`}
async function load(append=false){
  if(!authenticated||filterDraft||(append&&busy))return;personalQueryDirty=false;const seq=++sequence;controller?.abort();controller=new AbortController();busy=true;showView();
  let requestKey,keep=false;
  try{
  // Validate raw restored values before input[type=date] can normalize them away.
  requestKey=query().toString();
  if(view!=='calendar'&&calendar){calendar.destroy();calendar=null;calendarRange=null}
  if(view==='status'){busy=false;await loadStatus();return}
  if(view==='calendar'){busy=false;renderCalendar();return}
  keep=!append&&listSnapshot?.key===requestKey;
  $('#event-list').dataset.hasSnapshot=String(keep||append);
  if(keep){updateFacetCounts(listSnapshot.facets);renderExcluded(listSnapshot.excluded);records.clear();for(const e of listSnapshot.items)records.set(e.id,e);$('#event-list').innerHTML=listSnapshot.items.map(card).join('')||emptyState();total=listSnapshot.total;offset=listSnapshot.offset;$('#more').hidden=!listSnapshot.hasMore;$('#result-count').textContent=`${total} 个活动 · 刷新中，保留上次结果`}
  $('#event-list').setAttribute('aria-busy','true');$('#more').disabled=true;$('#more').textContent='正在加载…';
  if(!append&&!keep){updateFacetCounts(null);renderExcluded(null);offset=0;$('#result-count').textContent='正在加载';records.clear();$('#event-list').innerHTML=Array(3).fill('<div class="loading-card" aria-hidden="true"></div>').join('')}
  const p=new URLSearchParams(requestKey);p.set('offset',append?offset:0);p.set('limit',36);const res=await api('events?'+p,{signal:controller.signal});if(seq!==sequence||!authenticated)return;
    updateFacetCounts(res.facets);renderExcluded(res.excluded_long);total=res.total;if(!append)$('#event-list').replaceChildren();
    const fresh=append?res.items.filter(e=>!records.has(e.id)):res.items;if(!append)records.clear();for(const e of res.items)records.set(e.id,e);
    if(!res.items.length&&!append)$('#event-list').innerHTML=emptyState();else $('#event-list').insertAdjacentHTML('beforeend',fresh.map(card).join(''));
    offset=append?offset+res.items.length:res.items.length;listSnapshot={key:requestKey,items:$$('.event-card[data-event]').map(n=>records.get(n.dataset.event)).filter(Boolean),total,offset,hasMore:!!res.has_more,facets:res.facets||null,excluded:res.excluded_long||null,at:Date.now()};$('#event-list').dataset.hasSnapshot='true';$('#result-count').textContent=resultCountText(total,res.excluded_long);$('#more').hidden=!res.has_more;
  }catch(e){if(e.name==='AbortError'||seq!==sequence||!authenticated)return;if(dateLoadError)$('#date-error').textContent=dateLoadError;if(!append&&!keep){$('#event-list').replaceChildren();$('#result-count').textContent='加载失败';if(dateLoadError){records.clear();updateFacetCounts(null);renderExcluded(null);calendar?.removeAllEvents();renderLongCalendar([])}}if(keep){$('#result-count').textContent=`${total} 个活动 · 上次成功结果`;showError(new Error(e.message+' 正在保留此查询的上次结果，请手动重试。'),append)}else showError(e,append);if(append)$('#more').hidden=false}
  finally{if(seq===sequence){busy=false;$('#event-list').setAttribute('aria-busy','false');$('#more').disabled=false;$('#more').textContent='再看看更多 ↓'}}
}
function renderCalendar(){
  if(!window.FullCalendar){showError(new Error('日历组件未加载，请刷新页面；活动列表仍可使用。'));return}
  if(calendar){if(RadarUI.dayKey(calendar.getDate())!==calendarDate)calendar.gotoDate(calendarDate);else if(calendarRange)loadCalendar(calendarRange);return}
  calendar=new FullCalendar.Calendar($('#calendar'),{
    initialDate:calendarDate,initialView:innerWidth<620?'listMonth':'dayGridMonth',locale:'zh-cn',timeZone:'UTC',now:RadarUI.dayKey(new Date()),firstDay:1,height:'auto',
    buttonText:{today:'今天',month:'月',week:'周',list:'列表'},headerToolbar:{left:'prev,next today',center:'title',right:'dayGridMonth,listMonth'},
    showNonCurrentDates:false,fixedWeekCount:false,dayMaxEvents:false,dayMaxEventRows:false,eventOrder:'favoriteRank,start,title',eventOrderStrict:true,nextDayThreshold:'00:00:00',defaultTimedEventDuration:'00:00:01',allDayText:'活动期',noEventsContent:'这个月暂无已确认活动。',
    datesSet:info=>{calendarDate=info.view.currentStart.toISOString().slice(0,10);$('#calendar-month-jump').value=calendarDate.slice(0,7);writeURL('replace',detailId);loadCalendar({startStr:calendarDate,endStr:info.view.currentEnd.toISOString().slice(0,10)})},
    eventClick:i=>{i.jsEvent.preventDefault();openDetail(i.event.id)},
    eventContent:i=>{if(i.view.type.startsWith('list'))return true;const label=i.event.extendedProps.rangeLabel;const box=document.createElement('span');box.className='calendar-event-content';const title=document.createElement('span');title.className='calendar-event-title';title.textContent=(i.event.extendedProps.favorite?'★ ':'')+(i.timeText&&!i.view.type.startsWith('list')?i.timeText+' ':'')+i.event.title;box.append(title);if(label){const range=document.createElement('small');range.className='calendar-event-range';range.textContent=label;box.append(range)}return {domNodes:[box]}},
    eventDidMount:i=>{const favorite=!!i.event.extendedProps.favorite;const label=(favorite?'已收藏 · ':'')+i.event.title+' · '+i.event.extendedProps.fullTime;i.el.title=label;i.el.setAttribute('aria-label',label);i.el.dataset.eventId=i.event.id;i.el.classList.toggle('favorite-event',favorite);
      const link=i.el.querySelector('.fc-list-event-title a');if(link){link.setAttribute('aria-label',label);link.classList.add('calendar-event-content');if(favorite&&!link.querySelector('.calendar-favorite-star')){const star=document.createElement('span');star.className='calendar-favorite-star';star.setAttribute('aria-hidden','true');star.textContent='★ ';link.prepend(star)}const rangeLabel=i.event.extendedProps.rangeLabel;if(rangeLabel&&!link.querySelector('.calendar-event-range')){const range=document.createElement('small');range.className='calendar-event-range';range.textContent=rangeLabel;link.append(range)}}}
  });calendar.render();
}
function renderLongCalendar(items){
  const box=$('#calendar-long');box.replaceChildren();
  if(!items.length||urlParams().get('show_long')!=='true'){box.hidden=true;return}
  box.hidden=false;
  const head=document.createElement('div');head.className='calendar-long-head';
  head.innerHTML=`<div><b>这个月仍在开放 / 重复进行</b><span>${items.length} 项 · 不再铺成整月长条</span></div>`;
  const list=document.createElement('div');list.className='calendar-long-list';
  const visible=[...items].sort((a,b)=>Number(b.favorite)-Number(a.favorite));
  for(const e of visible.slice(0,Math.max(8,visible.filter(x=>x.favorite).length))){
    const b=document.createElement('button');b.className='calendar-long-item';b.classList.toggle('favorite',!!e.favorite);b.dataset.open=e.id;
    const title=document.createElement('strong');title.textContent=(e.favorite?'★ ':'')+e.title;
    const meta=document.createElement('span');meta.textContent=`${RadarUI.fullTime(e)}${e.location?' · '+e.location:''}`;
    b.append(title,meta);list.append(b);
  }
  if(items.length>Math.max(8,visible.filter(x=>x.favorite).length)){const more=document.createElement('span');more.className='calendar-long-more';more.textContent=`另有 ${items.length-Math.max(8,visible.filter(x=>x.favorite).length)} 项，可用“全部活动”查看`;list.append(more)}
  box.append(head,list);
}
async function loadCalendar(info){
  if(!authenticated||view!=='calendar')return;calendarRange=info;const seq=++sequence;controller?.abort();controller=new AbortController();busy=true;
  let keep=false;
  try{const requestKey=query('calendar').toString()+'|'+info.startStr+'|'+info.endStr;keep=calendarSnapshot?.key===requestKey;
  $('#notice').hidden=true;$('#calendar').dataset.hasSnapshot=String(keep);$('#calendar').setAttribute('aria-busy','true');$('#result-count').textContent=keep?'正在刷新 · 保留该月份上次结果':'正在加载当前月份';if(!keep){updateFacetCounts(null);renderExcluded(null);calendar.removeAllEvents();records.clear();$('#calendar-long').replaceChildren();$('#calendar-long').hidden=true}else{updateFacetCounts(calendarSnapshot.facets);renderExcluded(calendarSnapshot.excluded);calendar.removeAllEvents();records.clear();for(const e of calendarSnapshot.items)records.set(e.id,e);renderLongCalendar(calendarSnapshot.items.filter(e=>e.long_running));calendar.addEventSource(calendarSnapshot.items.filter(e=>!e.long_running).map(RadarUI.calendarEvent))}
  let cursor=0,metadata=null;const data=[];
    while(true){const p=query('calendar');p.set('start',info.startStr.slice(0,10));p.set('end',info.endStr.slice(0,10));p.set('offset',cursor);p.set('limit',500);
      const res=await api('events?'+p,{signal:controller.signal});if(seq!==sequence||!authenticated||view!=='calendar')return;
      if(!metadata)metadata=res;data.push(...res.items);cursor+=res.items.length;if(!res.has_more)break;if(!res.items.length)throw new Error('该范围活动过多，请用地区或兴趣缩小筛选。');
    }
    calendar.removeAllEvents();records.clear();for(const e of data)records.set(e.id,e);calendarSnapshot={key:requestKey,items:data,facets:metadata?.facets||null,excluded:metadata?.excluded_long||null,at:Date.now()};updateFacetCounts(metadata?.facets);renderExcluded(metadata?.excluded_long);$('#calendar').dataset.hasSnapshot='true';
    const long=data.filter(e=>e.long_running);
    const normal=data.filter(e=>!e.long_running); // API already selects interval overlap, including prior-month starts.
    renderLongCalendar(long);RadarEventWorkflows.unplanned();
    calendar.addEventSource(normal.map(RadarUI.calendarEvent));
    const hiddenText=metadata?.excluded_long?.total?` · ${metadata.excluded_long.total} 项长期/重复未计入（上方灰色列出）`:urlParams().get('show_long')!=='true'?' · 已应用长期/重复排除规则':long.length?` · ${long.length} 项长期/重复单列`:'';
    $('#result-count').textContent=`本月 ${normal.length} 个活动 · 跨日活动按覆盖日期显示${hiddenText}`;calendar.updateSize();
  }catch(e){if(seq!==sequence||!authenticated||view!=='calendar'||!calendar)return;if(!keep){calendar.removeAllEvents();records.clear();renderLongCalendar([])}if(e.name!=='AbortError'&&seq===sequence&&authenticated){$('#result-count').textContent=keep?'上次成功结果 · 当前月份刷新失败':'日历加载失败';showError(keep?new Error(e.message+' 保留该月份上次结果，其他月份不会混入。'):e)}}
  finally{if(seq===sequence){busy=false;$('#calendar').setAttribute('aria-busy','false')}}
}
function mountFeedback(e){
  const actions=$('#detail-body .detail-actions');if(!actions)return;
  const panel=document.createElement('section');panel.className='personal-feedback';panel.dataset.feedbackPanel=e.id;
  const head=document.createElement('div');head.className='feedback-heading';const intro=document.createElement('div');const title=document.createElement('b');title.textContent='我的反馈';const hint=document.createElement('span');hint.textContent='收藏是留着以后看；这里记录你看完后的判断，方便以后推荐学习。';intro.append(title,hint);
  const clear=document.createElement('button');clear.type='button';clear.className='quiet feedback-clear';clear.dataset.feedbackClear=e.id;clear.textContent='清除反馈';head.append(intro,clear);panel.append(head);
  const signals=document.createElement('div');signals.className='feedback-signals';signals.setAttribute('role','group');signals.setAttribute('aria-label','兴趣反馈');
  for(const [value,label] of Object.entries(feedbackSignals)){const b=document.createElement('button');b.type='button';b.className='feedback-choice';b.dataset.feedbackSignal=value;b.dataset.feedbackEvent=e.id;b.textContent=label;signals.append(b)}panel.append(signals);
  const sub=document.createElement('div');sub.className='feedback-tag-heading';sub.textContent='补充标签 ';const small=document.createElement('span');small.textContent='可多选';sub.append(small);panel.append(sub);
  const tags=document.createElement('div');tags.className='feedback-reasons';tags.setAttribute('role','group');tags.setAttribute('aria-label','反馈标签');
  for(const [value,label] of Object.entries(feedbackTagLabels)){const b=document.createElement('button');b.type='button';b.className='feedback-reason';b.dataset.feedbackTag=value;b.dataset.feedbackEvent=e.id;b.textContent=label;tags.append(b)}panel.append(tags);
  actions.before(panel);paintFeedback(e.id)
}
function paintFeedback(id){const e=records.get(id);if(!e)return;const summary=feedbackSummary(e);
  for(const tag of $$('[data-feedback-for]'))if(tag.dataset.feedbackFor===id){tag.hidden=!summary;tag.textContent=summary?'我的反馈 · '+summary:'';tag.dataset.feedbackValue=e.feedback||''}
  if(detailId===id){for(const b of $$('[data-feedback-signal]'))if(b.dataset.feedbackEvent===id){const on=b.dataset.feedbackSignal===e.feedback;b.setAttribute('aria-pressed',String(on));b.classList.toggle('selected',on);b.disabled=feedbackSaving.has(id)||saving.has(id)}
    const selected=new Set(e.feedback_tags||[]);for(const b of $$('[data-feedback-tag]'))if(b.dataset.feedbackEvent===id){const on=selected.has(b.dataset.feedbackTag);b.setAttribute('aria-pressed',String(on));b.classList.toggle('selected',on);b.disabled=feedbackSaving.has(id)||saving.has(id)}
    const clear=$$('[data-feedback-clear]').find(b=>b.dataset.feedbackClear===id);if(clear){clear.hidden=!(e.feedback||selected.size);clear.disabled=feedbackSaving.has(id)}
  }
}
function syncPersonalSnapshots(id,result){
  if(listSnapshot)listSnapshot.facets=null;if(calendarSnapshot)calendarSnapshot.facets=null;updateFacetCounts(null);
  for(const snapshot of [listSnapshot,calendarSnapshot]){
    if(!snapshot)continue;
    for(const item of snapshot.items)if(item.id===id)Object.assign(item,result);
    for(const item of snapshot.excluded?.items||[])if(item.id===id)Object.assign(item,result);
    // A confirmed un-save must not reappear from an older saved-only snapshot.
    if(result.favorite===false&&new URLSearchParams(snapshot.key.split('|')[0]).get('favorites')==='true'){
      const before=snapshot.items.length;snapshot.items=snapshot.items.filter(item=>item.id!==id);
      const removed=before-snapshot.items.length;
      if(Number.isFinite(snapshot.total))snapshot.total=Math.max(0,snapshot.total-removed);
      if(Number.isFinite(snapshot.offset))snapshot.offset=Math.max(0,snapshot.offset-removed);
      if(snapshot.excluded){const previous=snapshot.excluded.items.length;snapshot.excluded.items=snapshot.excluded.items.filter(item=>item.id!==id);if(snapshot.excluded.items.length<previous)snapshot.excluded.total=Math.max(0,snapshot.excluded.total-1);else snapshot.excluded=null}
    }
  }
}
function syncPersonal(id,result){const current=records.get(id);if(current)Object.assign(current,result);syncPersonalSnapshots(id,result);paintFeedback(id);paintFavorite(id)}
function positionFeedbackUndo(){
  const bar=$('#undo-bar'),dialog=$('#detail'),inside=dialog.open;
  const host=inside?dialog:document.body;
  if(bar.parentElement!==host)host.appendChild(bar);
  bar.classList.toggle('in-detail',inside);
}
async function updateFeedback(id,patch,message,undo=false){const e=records.get(id);if(!e||feedbackSaving.has(id)||saving.has(id)||!authenticated)return;
  const before={feedback:e.feedback||'',feedback_tags:[...(e.feedback_tags||[])]},epoch=authEpoch;feedbackSaving.add(id);paintFeedback(id);paintFavorite(id);
  try{const result=await api('preferences/'+encodeURIComponent(id),{method:'POST',body:JSON.stringify({...patch,expected_revision:e.revision||0})});if(!authenticated||epoch!==authEpoch)return;
    syncPersonal(id,result);toast(message);undoFeedback=undo?null:{id,before,record:{...e,feedback_tags:[...(e.feedback_tags||[])]},revision:result.revision,expires:Date.now()+30000};$('#undo-bar').hidden=!undoFeedback;positionFeedbackUndo();personalQueryDirty=true;if(!detailId)load();
  }catch(err){if(err.name!=='AbortError'&&authenticated&&epoch===authEpoch){if(err.current)syncPersonal(id,err.current);toast(err.message)}}
  finally{feedbackSaving.delete(id);if(authenticated&&epoch===authEpoch){paintFeedback(id);paintFavorite(id)}}
}
async function recordView(id){const epoch=authEpoch;try{const result=await api('viewed/'+encodeURIComponent(id),{method:'POST'});if(!authenticated||epoch!==authEpoch)return;const current=records.get(id);if(current)current.viewed_at=result.viewed_at;syncPersonalSnapshots(id,{viewed_at:result.viewed_at});for(const tag of $$('[data-viewed-for]'))if(tag.dataset.viewedFor===id){tag.hidden=false;tag.textContent='已看过'}}catch(e){if(e.name!=='AbortError'&&authenticated&&epoch===authEpoch)toast('浏览记录未同步；活动仍可阅读。')}}
function setFeedbackSignal(id,value){const e=records.get(id);if(!e)return;const target=e.feedback===value?'':value;updateFeedback(id,{feedback:target},target?'已记录“'+feedbackSignals[target]+'”。':'已清除主反馈。')}
function toggleFeedbackTag(id,value){const e=records.get(id);if(!e)return;const tags=new Set(e.feedback_tags||[]);if(tags.has(value))tags.delete(value);else tags.add(value);updateFeedback(id,{feedback_tags:[...tags]},'反馈标签已更新。')}
function clearFeedback(id){updateFeedback(id,{feedback:'',feedback_tags:[]},'已清除这条活动反馈。')}
function renderDetail(e){
  const state=RadarUI.lifecycle(e);const ended=state==='已结束'||e.status==='cancelled'||e.status==='not_event';
  $('#detail-body').innerHTML=`<div class="card-tags"><span class="tag type-tag">${esc(e.event_type_label||'其他活动')}</span>${(e.topics||[]).map(t=>`<span class="tag topic-tag">${esc(t)}</span>`).join('')}${e.long_running?'<span class="tag long-tag">长期/重复</span>':''}${state?`<span class="tag warn">${esc(state)}</span>`:''}</div><h2 class="detail-title" id="detail-title">${esc(e.title)}</h2><div class="detail-meta"><p><b>时间</b>${esc(fullTime(e))}</p><p><b>地点</b>${esc(e.location||'原文未明确地点')}</p>${costText(e)?`<p><b>费用</b>${esc(costText(e))}</p>`:''}${e.organizer?`<p><b>${esc(organizerLabel(e))}</b>${esc(e.organizer)}</p>`:''}</div><p class="detail-summary">${esc(e.summary||'请查看原始活动页。')}</p>${e.reason&&e.ai_state==='done'?`<p class="detail-summary">${esc(e.reason)}</p>`:''}${detailExtras(e)}<div class="detail-actions"><a class="primary" href="${esc(RadarUI.safeUrl(e.url))}" target="_blank" rel="noopener noreferrer">${ended?'查看历史原文':'查看原文 / 报名'} ↗</a>${e.start_at&&e.status==='scheduled'?`<a class="secondary" href="/events/api/event/${esc(e.id)}.ics">导出日历 ↓</a>`:''}<button class="secondary" data-save="${esc(e.id)}" aria-pressed="${!!e.favorite}">${e.favorite?'取消收藏':'☆ 收藏活动'}</button></div><div class="detail-source">${(e.sources||[]).map(s=>`<div>来源：<a href="${esc(RadarUI.safeUrl(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.name)} ↗</a></div>`).join('')}<div>最近采集：${esc(timeText(e.last_seen))}。报名状态与变更请以主办方为准。</div></div>`;
  mountFeedback(e);RadarEventWorkflows.mountDetail(e);
}
async function openDetail(id,push=true){
  if(!authenticated)return;if(push||!detailId)RadarEventWorkflows.beginDetail(id);const epoch=authEpoch,ticket=++detailTicket;opener=document.activeElement;
  try{const e=records.get(id)||await api('event/'+encodeURIComponent(id));if(!authenticated||epoch!==authEpoch||ticket!==detailTicket)return;
    records.set(id,e);records.set(e.id,e);detailId=e.id;renderDetail(e);paintFavorite(e.id);paintFeedback(e.id);if(push)writeURL('push',e.id);else if(id!==e.id)writeURL('replace',e.id);
    if(!$('#detail').open)$('#detail').showModal();positionFeedbackUndo();document.body.classList.add('modal-open');$('#close-detail').focus();recordView(e.id);
  }catch(e){if(e.name!=='AbortError'&&authenticated&&epoch===authEpoch){toast(e.message);writeURL('replace');detailId=null}}
}
function closeDetail(updateHistory=true){
  detailTicket++;const had=detailId;detailId=null;if($('#detail').open)$('#detail').close();positionFeedbackUndo();document.body.classList.remove('modal-open');
  if(updateHistory&&had){if(history.state?.radarModal)history.back();else writeURL('replace')}
  if(authenticated&&opener?.isConnected)opener.focus({preventScroll:true});if(authenticated)RadarEventWorkflows.restoreFocus();opener=null;if(updateHistory&&authenticated&&personalQueryDirty)load();
}
function paintFavorite(id){const e=records.get(id);if(!e)return;for(const b of $$('[data-save]'))if(b.dataset.save===id){b.disabled=saving.has(id)||feedbackSaving.has(id);b.setAttribute('aria-pressed',String(!!e.favorite));if(b.classList.contains('bookmark')){b.classList.toggle('saved',!!e.favorite);b.textContent=e.favorite?'★':'☆';b.setAttribute('aria-label',e.favorite?'取消收藏':'收藏活动')}else b.textContent=e.favorite?'取消收藏':'☆ 收藏活动'}
  if(view==='calendar'&&calendar){const ce=calendar.getEventById(id);if(ce){const payload=RadarUI.calendarEvent(e);ce.setExtendedProp('favorite',!!e.favorite);ce.setExtendedProp('favoriteRank',e.favorite?0:1);ce.setProp('classNames',payload.classNames)}if(e.long_running)renderLongCalendar([...records.values()].filter(x=>x.long_running))}
}
async function save(id){
  const e=records.get(id);if(!e||saving.has(id)||feedbackSaving.has(id)||!authenticated)return;const epoch=authEpoch,target=!e.favorite;saving.add(id);paintFavorite(id);
  try{const result=await api('preferences/'+encodeURIComponent(id),{method:'POST',body:JSON.stringify({favorite:target,expected_revision:e.revision||0})});if(!authenticated||epoch!==authEpoch)return;
    Object.assign(e,result);syncPersonal(id,result);
    toast(result.favorite?'已收藏，其他设备登录后也能看到。':'已取消收藏。');
    if(view==='favorites'&&!result.favorite){const card=$$('[data-event]').find(c=>c.dataset.event===id);if(card){card.remove();offset=Math.max(0,offset-1);total=Math.max(0,total-1);$('#result-count').textContent=resultCountText(total,listSnapshot?.excluded);if(!$('#event-list').children.length){if(total)await load();else $('#event-list').innerHTML=emptyState()}}}
  }catch(err){if(err.name!=='AbortError'&&authenticated&&epoch===authEpoch){if(err.current)syncPersonal(id,err.current);toast(err.message)}}finally{saving.delete(id);if(authenticated&&epoch===authEpoch){paintFavorite(id);paintFeedback(id)}}
}
function validateDateInputs(){
  try{const from=$('#date-from').value,until=$('#date-until').value;
    if(dateLoadError&&from===dateLoadValues?.from&&until===dateLoadValues?.until)throw new Error(dateLoadError);
    RadarPlanner.range(from,until);$('#date-error').textContent='';return true;
  }catch(e){$('#date-error').textContent=e.message;toast(e.message);return false}
}
function commitDateInputs(){appliedDates={from:$('#date-from').value,until:$('#date-until').value};dateLoadError='';dateLoadValues=null;appliedFilterQuery=draftParams().toString()}
function navigate(next,reset=false){if(filterDraft)finishFilterDraft(false);clearTimeout(debounce);if(reset){clearFilters();dateLoadError=''}if(!validateDateInputs())return;commitDateInputs();closeDetail(false);view=Object.hasOwn(views,next)?next:'discover';writeURL();load()}
function applyFilters(mode='push'){clearTimeout(debounce);syncFilterControls();if(filterDraft)return;if(!validateDateInputs())return;commitDateInputs();closeDetail(false);writeURL(mode);load()}
function restoreNavigation(){if(!authenticated)return;if(filterDraft)finishFilterDraft(false);const before=urlParams().toString();closeDetail(false);readURL();rememberFilters();const after=urlParams().toString();const id=new URLSearchParams(location.search).get('event');if(before!==after||personalQueryDirty)load().then(()=>{if(id)openDetail(id,false)});else if(id)openDetail(id,false)}
addEventListener('popstate',restoreNavigation);
$('#login-form').onsubmit=async e=>{e.preventDefault();const b=$('#login-submit');if(b.disabled)return;b.disabled=true;b.textContent='正在验证…';$('#login-error').textContent='';try{const user=await api('login',{method:'POST',body:JSON.stringify({username:$('#username').value,password:$('#password').value})});$('#password').value='';await enter(user)}catch(err){if(err.name!=='AbortError')$('#login-error').textContent=err.message}finally{b.disabled=false;b.textContent='打开我的雷达 →'}};
$('#logout').onclick=async()=>{const b=$('#logout');b.disabled=true;try{await api('logout',{method:'POST'});showLogin()}catch(e){if(e.name!=='AbortError')toast(e.message)}finally{b.disabled=false}};
document.addEventListener('click',e=>{
  const b=e.target.closest('button,[data-open]');if(!b||b.disabled)return;
  if(b.dataset.facetAction){const kind=b.dataset.facetKind;$$(`#${kind}-options input`).forEach(x=>x.checked=b.dataset.facetAction==='all'?true:b.dataset.facetAction==='none'?false:!x.checked);updateFacetSummary(kind);applyFilters();return}
  if(b.dataset.facetRemove){const kind=b.dataset.facetRemove,value=b.dataset.facetValue;$$(`#${kind}-options input[type="checkbox"]`).forEach(x=>{if(x.value===value)x.checked=b.dataset.facetExcluded==='true'});updateFacetSummary(kind);applyFilters();return}
  if(b.dataset.compare){RadarEventWorkflows.toggle(b.dataset.compare);return}
  if(b.dataset.retrySource){retrySource(b.dataset.retrySource,b);return}
  if(b.dataset.feedbackSignal){setFeedbackSignal(b.dataset.feedbackEvent,b.dataset.feedbackSignal);return}
  if(b.dataset.feedbackTag){toggleFeedbackTag(b.dataset.feedbackEvent,b.dataset.feedbackTag);return}
  if(b.dataset.feedbackClear){clearFeedback(b.dataset.feedbackClear);return}
  if(b.dataset.save){save(b.dataset.save);return}if(b.dataset.open){openDetail(b.dataset.open);return}
  if(b.dataset.view||b.dataset.changeView){navigate(b.dataset.view||b.dataset.changeView);return}
  const action=b.dataset.action;
  if(action==='include-long'){$('#hide-long').checked=false;applyFilters();return}
  if(action==='browse-all'){navigate('all',true);return}
  if(action==='reset'){clearFilters();dateLoadError='';applyFilters();return}
  if(action==='clear-invalid-dates'){$('#clear-dates').click();return}
  if(action==='retry-status'){loadStatus();return}
  if(action==='retry'){view==='calendar'&&calendarRange?loadCalendar(calendarRange):load(failedAppend)}
});
$('#close-detail').onclick=()=>closeDetail();$('#detail').addEventListener('cancel',e=>{e.preventDefault();closeDetail()});
$('#detail').addEventListener('click',e=>{if(e.target===$('#detail')){const r=$('#detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeDetail()}});
$('#search').addEventListener('compositionstart',()=>{composing=true;clearTimeout(debounce)});
$('#search').addEventListener('compositionend',()=>{composing=false;clearTimeout(debounce);if(!filterDraft)debounce=setTimeout(()=>applyFilters(),250)});
$('#search').oninput=e=>{clearTimeout(debounce);if(!filterDraft&&!composing&&!e.isComposing)debounce=setTimeout(()=>applyFilters(),250)};
$('#search').onkeydown=e=>{if(e.key==='Enter'&&!composing&&!e.isComposing){e.preventDefault();applyFilters()}};
for(const s of ['#free','#hide-long','#sort','#attendance','#feedback-filter','#feedback-tag-filter','#viewed-filter'])$(s).onchange=()=>applyFilters();
for(const kind of ['type','topic','district']){
  $(`#${kind}-options`).addEventListener('change',e=>{if(e.target.matches('input[type="checkbox"]')){updateFacetSummary(kind);applyFilters()}});
  $(`#${kind}-filter`).addEventListener('toggle',e=>{if(e.target.open){for(const other of ['type','topic','district'])if(other!==kind)$(`#${other}-filter`).open=false}});
}
document.addEventListener('click',e=>{if(!e.target.closest('.multi-filter'))$$('.multi-filter[open]').forEach(x=>x.open=false)});
document.addEventListener('keydown',e=>{if(e.key==='Escape')$$('.multi-filter[open]').forEach(x=>x.open=false)});
$('#clear-filters').onclick=()=>{clearFilters();if(!filterDraft)dateLoadError='';applyFilters()};$('#more').onclick=()=>load(true);
$('#refresh-data').onclick=()=>{stats();load()};
matchMedia('(max-width:619px)').addEventListener('change',e=>{if(calendar&&view==='calendar')calendar.changeView(e.matches?'listMonth':'dayGridMonth')});
addEventListener('pageshow',e=>{if(e.persisted)(async()=>{try{const user=await api('session');await enter(user)}catch{showLogin()}})()});
addEventListener('pagehide',e=>{if(e.persisted)showLogin()});
(async()=>{try{const user=await api('session');await enter(user)}catch(e){if(!authenticated)showLogin()}})();


$('#dismiss-undo').onclick=()=>{undoFeedback=null;$('#undo-bar').hidden=true};
$('#undo-feedback').onclick=()=>{const u=undoFeedback;if(!u||Date.now()>u.expires){toast('撤销已过期，请在详情修改。');$('#dismiss-undo').click();return}const e=records.get(u.id)||u.record;if(!e||e.revision!==u.revision){toast('活动已更新，请重新核对。');$('#dismiss-undo').click();return}if(!records.has(u.id))records.set(u.id,e);updateFeedback(u.id,u.before,'已撤销上次反馈。',true)};

function beginFilterDraft(){if(!authenticated||filterDraft)return;clearTimeout(debounce);filterDraft=$$('#filter-panel input,#filter-panel select,#calendar-saved-only').map(el=>({el,value:el.value,checked:el.checked}));filterDraft.dateLoadError=dateLoadError;syncFilterControls();$('#filter-draft-body').append($('#filter-panel'));$('#filter-dialog').showModal();$('#cancel-filter-draft').focus()}
function finishFilterDraft(apply){if(!filterDraft)return;clearTimeout(debounce);if(apply){if(!validateDateInputs())return}else{for(const s of filterDraft){s.el.value=s.value;if(s.checked!==undefined)s.el.checked=s.checked}dateLoadError=filterDraft.dateLoadError}
  filterDraft=null;$('#filter-dialog').close();$('#filter-home').after($('#filter-panel'));updateFacetSummary('type');updateFacetSummary('topic');updateFacetSummary('district');if(authenticated)$('#open-filters').focus();syncFilterControls();if(apply)applyFilters();else{$('#date-error').textContent=dateLoadError;renderActiveFilters();}}
$('#open-filters').onclick=beginFilterDraft;$('#cancel-filter-draft').onclick=()=>finishFilterDraft(false);$('#apply-filter-draft').onclick=()=>finishFilterDraft(true);$('#reset-filter-draft').onclick=()=>clearFilters();$('#filter-dialog').addEventListener('cancel',e=>{e.preventDefault();finishFilterDraft(false)});
$('#apply-dates').onclick=()=>applyFilters();$('#clear-dates').onclick=()=>{$('#date-from').value='';$('#date-until').value='';dateLoadError='';applyFilters()};RadarPlanner.init();

RadarEventWorkflows.init();

function updateConnectivity(){if(!authenticated)return;const offline=!navigator.onLine;$('#network-banner').hidden=false;$('#network-message').textContent=offline?'网络已断开，已加载内容仍可阅读；保存操作不会自动重试。':'网络已恢复，可手动刷新当前页面。';$('#network-retry').disabled=offline;}
addEventListener('offline',updateConnectivity);addEventListener('online',updateConnectivity);$('#network-retry').onclick=()=>{if(navigator.onLine){$('#network-banner').hidden=true;load()}};

initStatusRecovery();

