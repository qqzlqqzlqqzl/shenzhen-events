'use strict';
let view='discover',offset=0,total=0,sequence=0,calendar=null,controller=null;
let authenticated=false,authEpoch=0,statusTicket=0,statsTicket=0,detailTicket=0,busy=false;
let calendarDate='',calendarRange=null,detailId=null,debounce=null,composing=false,opener=null;
const records=new Map(),inflight=new Set(),saving=new Set();
const facetCatalog={type:new Map(),topic:new Map()};
function checkedFacet(kind){return $$(`#${kind}-options input[type="checkbox"]:checked`).map(x=>x.value)}
function updateFacetSummary(kind){const n=checkedFacet(kind).length,total=$$(`#${kind}-options input[type="checkbox"]`).length;$(`#${kind}-summary`).textContent=n===total?'全部':n?`已选 ${n} / ${total}`:'未选择'}
function renderFacetOptions(kind,items,pending=0){
  const box=$(`#${kind}-options`),hadOptions=!!box.querySelector('input'),selected=new Set(checkedFacet(kind)),wasAll=hadOptions&&selected.size===box.querySelectorAll('input').length;facetCatalog[kind]=new Map((items||[]).map(x=>[x.value,x.label]));box.replaceChildren();
  if(kind==='type'&&pending){const note=document.createElement('p');note.className='facet-progress';note.textContent=`还有 ${Number(pending).toLocaleString()} 条待标准分类；已分类结果可先筛选。`;box.append(note)}
  for(const item of items||[]){const label=document.createElement('label');label.className='facet-option';const input=document.createElement('input');input.type='checkbox';input.value=item.value;input.checked=!hadOptions||wasAll||selected.has(item.value);input.setAttribute('aria-label',item.label);const text=document.createElement('span');text.textContent=item.label;const count=document.createElement('small');count.textContent=Number(item.count||0).toLocaleString();label.append(input,text,count);box.append(label)}
  if(!(items||[]).length){const empty=document.createElement('p');empty.className='facet-empty';empty.textContent=kind==='type'?'活动类型正在按 Schema.org 标准逐批补齐。':'暂无可用主题标签。';box.append(empty)}
  updateFacetSummary(kind);
}
function renderActiveFilters(){
  const box=$('#active-filters');box.replaceChildren();
  const addChip=(kind,value)=>{const b=document.createElement('button');b.type='button';b.className='filter-chip';b.dataset.facetRemove=kind;b.dataset.facetValue=value;b.textContent=(facetCatalog[kind].get(value)||value)+' ×';box.append(b)};
  for(const kind of ['type','topic']){const all=$$(`#${kind}-options input`),selected=checkedFacet(kind);if(selected.length===all.length)continue;if(!selected.length){const note=document.createElement('span');note.textContent=(kind==='type'?'活动类型':'主题')+'：未选择';box.append(note)}else for(const x of all.filter(x=>!x.checked)){addChip(kind,x.value);box.lastChild.textContent='排除：'+(facetCatalog[kind].get(x.value)||x.value)+' ×'}}
  const rest=[$('#search').value?'关键词：'+$('#search').value:'',$('#district').value,$('#free').checked?'只看免费':'',$('#hide-long').checked?'长期/重复已隐藏':'包含长期/重复',$('#sort').value==='desc'?'时间远→近':''].filter(Boolean);
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
    if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'请求失败，请重试。');
    return data;
  } catch(e) {if(timedOut)throw new Error('请求超时，已有数据未更改，请重试。');throw e}
  finally {clearTimeout(timer);inflight.delete(c);options.signal?.removeEventListener('abort',abort)}
}
function showLogin(message='') {
  authenticated=false;authEpoch++;sequence++;detailTicket++;statusTicket++;busy=false;
  clearTimeout(debounce);for(const c of inflight)c.abort();inflight.clear();controller?.abort();
  closeDetail(false);records.clear();saving.clear();calendar?.destroy();calendar=null;calendarRange=null;
  for(const s of ['#event-list','#status-panel','#calendar','#calendar-long','#detail-body'])$(s).replaceChildren();
  $('#workspace').hidden=true;$('#login-panel').hidden=false;$('#logout').hidden=true;$('#toast').hidden=true;
  $('#login-error').textContent=message;$('#password').value='';$('#username').focus();
}
async function stats() {
  const epoch=authEpoch,ticket=++statsTicket;
  try {const s=await api('stats');if(!authenticated||epoch!==authEpoch||ticket!==statsTicket)return;
    $('#count-recommended').textContent=s.recommended;$('#count-upcoming').textContent=s.upcoming;$('#count-weekend').textContent=s.weekend;
    $('#update-note').textContent=`${s.normal_sources??0} 个来源本次读取完成 · ${s.partial_sources??0} 个部分覆盖 · ${s.last_updated?timeText(s.last_updated)+' 更新':'尚未采集'}`;
    if($('#district').options.length===1){for(const v of s.districts)$('#district').add(new Option(v,v));$('#district').add(new Option('地区待确认','待确认'))}
    renderFacetOptions('type',s.event_types||[],s.type_pending||0);renderFacetOptions('topic',s.topics||[]);
  }catch(e){if(e.name!=='AbortError'&&authenticated&&epoch===authEpoch)$('#update-note').textContent=e.message}
}
function readURL() {
  const p=new URLSearchParams(location.search);view=Object.hasOwn(views,p.get('view'))?p.get('view'):'discover';
  $('#search').value=(p.get('q')||'').slice(0,160);$('#district').value=p.get('district')||'';$('#free').checked=p.get('free')==='true';$('#hide-long').checked=p.get('show_long')!=='true';$('#sort').value=p.get('sort')==='desc'?'desc':'asc';
  const topicAlias=x=>x==='展览文化'?'文化艺术':x;
  const selectedTypes=new Set(p.getAll('type')),selectedTopics=new Set(p.getAll('topic').map(topicAlias));const legacy=p.get('tag');if(legacy)selectedTopics.add(topicAlias(legacy));
  $$('#type-options input[type="checkbox"]').forEach(x=>x.checked=p.get('type_none')!=='true'&&(!selectedTypes.size||selectedTypes.has(x.value)));$$('#topic-options input[type="checkbox"]').forEach(x=>x.checked=p.get('topic_none')!=='true'&&(!selectedTopics.size||selectedTopics.has(x.value)));updateFacetSummary('type');updateFacetSummary('topic');
  const month=p.get('month')||'';calendarDate=/^\d{4}-\d{2}-\d{2}$/.test(month)&&Number.isFinite(Date.parse(month))?month:RadarUI.dayKey(new Date());
}
function urlParams() {
  const p=new URLSearchParams();if(view!=='discover')p.set('view',view);
  for(const [k,id] of [['q','search'],['district','district']]){const v=$('#'+id).value.trim();if(v)p.set(k,v)}
  for(const kind of ['type','topic']){const selected=checkedFacet(kind),total=$$(`#${kind}-options input`).length;if(total&&!selected.length)p.set(kind+'_none','true');else if(selected.length<total)for(const v of selected)p.append(kind,v)}
  if($('#free').checked)p.set('free','true');if(!$('#hide-long').checked)p.set('show_long','true');if($('#sort').value==='desc')p.set('sort','desc');if(view==='calendar'&&calendarDate)p.set('month',calendarDate);return p;
}
function writeURL(mode='push',event=null) {
  const p=urlParams();if(event)p.set('event',event);const u=location.pathname+(p.size?'?'+p:'');
  if(u!==location.pathname+location.search)history[mode==='replace'?'replaceState':'pushState']({radar:true,radarModal:!!event&&mode==='push'},'',u);
}
function clearFilters(){clearTimeout(debounce);$('#search').value='';$('#district').value='';$$('#type-options input,#topic-options input').forEach(x=>x.checked=true);updateFacetSummary('type');updateFacetSummary('topic');$('#free').checked=false;$('#hide-long').checked=true;$('#sort').value='asc'}
async function enter() {
  authenticated=true;authEpoch++;$('#login-panel').hidden=true;$('#workspace').hidden=false;$('#logout').hidden=false;
  await stats();if(!authenticated)return;readURL();await load();const id=new URLSearchParams(location.search).get('event');if(id&&authenticated)await openDetail(id,false);
}
function query(period) {const p=urlParams();const showLong=p.get('show_long')==='true';p.delete('view');p.delete('month');p.delete('show_long');p.set('hide_long',showLong?'false':'true');p.set('period',period||({favorites:'saved',calendar:'calendar',week:'week',weekend:'weekend',review:'review',past:'past'}[view]||'upcoming'));if(view==='discover')p.set('recommended','true');if(view==='favorites')p.set('favorites','true');return p}
let failedAppend=false;
function showError(error,append=false){failedAppend=append;$('#notice').hidden=false;$('#notice').replaceChildren();const t=document.createElement('span');t.textContent=error.message||'网络连接失败，请重试。';const b=document.createElement('button');b.className='secondary';b.dataset.action='retry';b.textContent='重试';$('#notice').append(t,b)}
function showView(){
  $('#result-count').hidden=view==='status';$('#active-filters').hidden=view==='status';if(view==='status')$('#result-count').textContent='';
  $('#notice').hidden=true;$('#more').hidden=true;$('#status-panel').hidden=view!=='status';$('#calendar-panel').hidden=view!=='calendar';$('#event-list').hidden=['status','calendar'].includes(view);$('#filter-panel').hidden=view==='status';
  $('#view-title').textContent=views[view][0];$('#view-subtitle').textContent=views[view][1];
  $$('.tabs button').forEach(b=>{b.classList.toggle('active',b.dataset.view===view);if(b.dataset.view===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
  renderActiveFilters();
}
function emptyState(){const filtered=!!$('#active-filters').textContent;return `<div class="empty"><b>${filtered?'当前筛选条件下没有活动':view==='favorites'?'还没有收藏活动':'这里暂时没有活动'}</b><p>${filtered?'试试重置筛选；其他收藏或活动不会被删除。':view==='favorites'?'点击活动卡片的星号即可收藏，过期后仍会保留。':'可以查看其他日期，或去全部活动探索。'}</p><button class="secondary" data-action="${filtered?'reset':'browse-all'}">${filtered?'重置筛选':'查看全部活动 →'}</button></div>`}
async function load(append=false){
  if(!authenticated||(append&&busy))return;const seq=++sequence;controller?.abort();controller=new AbortController();busy=true;showView();
  if(view!=='calendar'&&calendar){calendar.destroy();calendar=null;calendarRange=null}
  if(view==='status'){busy=false;await loadStatus();return}
  if(view==='calendar'){busy=false;renderCalendar();return}
  $('#event-list').setAttribute('aria-busy','true');$('#more').disabled=true;$('#more').textContent='正在加载…';
  if(!append){offset=0;$('#result-count').textContent='正在加载';records.clear();$('#event-list').innerHTML=Array(3).fill('<div class="loading-card" aria-hidden="true"></div>').join('')}
  try{const p=query();p.set('offset',offset);p.set('limit',36);const res=await api('events?'+p,{signal:controller.signal});if(seq!==sequence||!authenticated)return;
    total=res.total;if(!append)$('#event-list').replaceChildren();
    const fresh=res.items.filter(e=>!records.has(e.id));for(const e of res.items)records.set(e.id,e);
    if(!res.items.length&&!append)$('#event-list').innerHTML=emptyState();else $('#event-list').insertAdjacentHTML('beforeend',fresh.map(card).join(''));
    offset+=res.items.length;$('#result-count').textContent=`${total} 个活动`;$('#more').hidden=!res.has_more;
  }catch(e){if(e.name==='AbortError'||seq!==sequence||!authenticated)return;if(!append){$('#event-list').replaceChildren();$('#result-count').textContent='加载失败'}showError(e,append);if(append)$('#more').hidden=false}
  finally{if(seq===sequence){busy=false;$('#event-list').setAttribute('aria-busy','false');$('#more').disabled=false;$('#more').textContent='再看看更多 ↓'}}
}
function renderCalendar(){
  if(!window.FullCalendar){showError(new Error('日历组件未加载，请刷新页面；活动列表仍可使用。'));return}
  if(calendar){if(RadarUI.dayKey(calendar.getDate())!==calendarDate)calendar.gotoDate(calendarDate);else if(calendarRange)loadCalendar(calendarRange);return}
  calendar=new FullCalendar.Calendar($('#calendar'),{
    initialDate:calendarDate,initialView:innerWidth<620?'listMonth':'dayGridMonth',locale:'zh-cn',timeZone:'UTC',now:RadarUI.dayKey(new Date()),firstDay:1,height:'auto',
    buttonText:{today:'今天',month:'月',week:'周',list:'列表'},headerToolbar:{left:'prev,next today',center:'title',right:'dayGridMonth,listMonth'},
    showNonCurrentDates:false,fixedWeekCount:false,dayMaxEvents:4,nextDayThreshold:'00:00:00',defaultTimedEventDuration:'00:00:01',allDayText:'活动期',moreLinkText:n=>`+${n} 个`,noEventsContent:'这个月暂无已确认活动。',
    datesSet:info=>{calendarDate=info.view.currentStart.toISOString().slice(0,10);writeURL('replace',detailId);loadCalendar({startStr:calendarDate,endStr:info.view.currentEnd.toISOString().slice(0,10)})},
    eventClick:i=>{i.jsEvent.preventDefault();openDetail(i.event.id)},
    eventContent:i=>{if(i.view.type.startsWith('list'))return true;const label=i.event.extendedProps.rangeLabel;const box=document.createElement('span');box.className='calendar-event-content';const title=document.createElement('span');title.className='calendar-event-title';title.textContent=(i.timeText&&!i.view.type.startsWith('list')?i.timeText+' ':'')+i.event.title;box.append(title);if(label){const range=document.createElement('small');range.className='calendar-event-range';range.textContent=label;box.append(range)}return {domNodes:[box]}},
    eventDidMount:i=>{const label=i.event.title+' · '+i.event.extendedProps.fullTime;i.el.title=label;i.el.setAttribute('aria-label',label);i.el.dataset.eventId=i.event.id;
      const link=i.el.querySelector('.fc-list-event-title a');if(link){link.setAttribute('aria-label',label);link.classList.add('calendar-event-content');const rangeLabel=i.event.extendedProps.rangeLabel;if(rangeLabel&&!link.querySelector('.calendar-event-range')){const range=document.createElement('small');range.className='calendar-event-range';range.textContent=rangeLabel;link.append(range)}}}
  });calendar.render();
}
function renderLongCalendar(items){
  const box=$('#calendar-long');box.replaceChildren();
  if(!items.length||$('#hide-long').checked){box.hidden=true;return}
  box.hidden=false;
  const head=document.createElement('div');head.className='calendar-long-head';
  head.innerHTML=`<div><b>这个月仍在开放 / 重复进行</b><span>${items.length} 项 · 不再铺成整月长条</span></div>`;
  const list=document.createElement('div');list.className='calendar-long-list';
  for(const e of items.slice(0,8)){
    const b=document.createElement('button');b.className='calendar-long-item';b.dataset.open=e.id;
    const title=document.createElement('strong');title.textContent=e.title;
    const meta=document.createElement('span');meta.textContent=`${RadarUI.fullTime(e)}${e.location?' · '+e.location:''}`;
    b.append(title,meta);list.append(b);
  }
  if(items.length>8){const more=document.createElement('span');more.className='calendar-long-more';more.textContent=`另有 ${items.length-8} 项，可用“全部活动”查看`;list.append(more)}
  box.append(head,list);
}
async function loadCalendar(info){
  if(!authenticated||view!=='calendar')return;calendarRange=info;const seq=++sequence;controller?.abort();controller=new AbortController();busy=true;
  $('#notice').hidden=true;$('#calendar').setAttribute('aria-busy','true');$('#result-count').textContent='正在加载当前月份';calendar.removeAllEvents();records.clear();$('#calendar-long').replaceChildren();$('#calendar-long').hidden=true;
  try{let cursor=0;const data=[];
    while(true){const p=query('calendar');p.set('start',info.startStr.slice(0,10));p.set('end',info.endStr.slice(0,10));p.set('offset',cursor);p.set('limit',500);
      const res=await api('events?'+p,{signal:controller.signal});if(seq!==sequence||!authenticated||view!=='calendar')return;
      data.push(...res.items);cursor+=res.items.length;if(!res.has_more)break;if(!res.items.length||cursor>=10000)throw new Error('该范围活动过多，请用地区或兴趣缩小筛选。');
    }
    for(const e of data)records.set(e.id,e);
    const long=data.filter(e=>e.long_running);
    const normal=data.filter(e=>!e.long_running); // API already selects interval overlap, including prior-month starts.
    renderLongCalendar(long);
    calendar.addEventSource(normal.map(RadarUI.calendarEvent));
    const hiddenText=$('#hide-long').checked?' · 长期/重复已隐藏':long.length?` · ${long.length} 项长期/重复单列`:'';
    $('#result-count').textContent=`本月 ${normal.length} 个活动 · 跨日活动按覆盖日期显示${hiddenText}`;calendar.updateSize();
  }catch(e){if(seq!==sequence||!authenticated||view!=='calendar'||!calendar)return;calendar.removeAllEvents();records.clear();renderLongCalendar([]);if(e.name!=='AbortError'&&seq===sequence&&authenticated){$('#result-count').textContent='日历加载失败';showError(e)}}
  finally{if(seq===sequence){busy=false;$('#calendar').setAttribute('aria-busy','false')}}
}
function renderDetail(e){
  const state=RadarUI.lifecycle(e);const ended=state==='已结束'||e.status==='cancelled'||e.status==='not_event';
  $('#detail-body').innerHTML=`<div class="card-tags"><span class="tag type-tag">${esc(e.event_type_label||'其他活动')}</span>${(e.topics||[]).map(t=>`<span class="tag topic-tag">${esc(t)}</span>`).join('')}${e.long_running?'<span class="tag long-tag">长期/重复</span>':''}${state?`<span class="tag warn">${esc(state)}</span>`:''}</div><h2 class="detail-title" id="detail-title">${esc(e.title)}</h2><div class="detail-meta"><p><b>时间</b>${esc(fullTime(e))}</p><p><b>地点</b>${esc(e.location||'原文未明确地点')}</p>${costText(e)?`<p><b>费用</b>${esc(costText(e))}</p>`:''}${e.organizer?`<p><b>主办</b>${esc(e.organizer)}</p>`:''}</div><p class="detail-summary">${esc(e.summary||'请查看原始活动页。')}</p>${e.reason&&e.ai_state==='done'?`<p class="detail-summary">${esc(e.reason)}</p>`:''}${detailExtras(e)}<div class="detail-actions"><a class="primary" href="${esc(RadarUI.safeUrl(e.url))}" target="_blank" rel="noopener noreferrer">${ended?'查看历史原文':'查看原文 / 报名'} ↗</a>${e.start_at&&e.status==='scheduled'?`<a class="secondary" href="/events/api/event/${esc(e.id)}.ics">导出日历 ↓</a>`:''}<button class="secondary" data-save="${esc(e.id)}" aria-pressed="${!!e.favorite}">${e.favorite?'取消收藏':'☆ 收藏活动'}</button></div><div class="detail-source">${(e.sources||[]).map(s=>`<div>来源：<a href="${esc(RadarUI.safeUrl(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.name)} ↗</a></div>`).join('')}<div>最近采集：${esc(timeText(e.last_seen))}。报名状态与变更请以主办方为准。</div></div>`;
}
async function openDetail(id,push=true){
  if(!authenticated)return;const epoch=authEpoch,ticket=++detailTicket;opener=document.activeElement;
  try{const e=records.get(id)||await api('event/'+encodeURIComponent(id));if(!authenticated||epoch!==authEpoch||ticket!==detailTicket)return;
    records.set(id,e);detailId=id;renderDetail(e);paintFavorite(id);if(push)writeURL('push',id);
    if(!$('#detail').open)$('#detail').showModal();document.body.classList.add('modal-open');$('#close-detail').focus();
  }catch(e){if(e.name!=='AbortError'&&authenticated&&epoch===authEpoch){toast(e.message);writeURL('replace');detailId=null}}
}
function closeDetail(updateHistory=true){
  detailTicket++;const had=detailId;detailId=null;if($('#detail').open)$('#detail').close();document.body.classList.remove('modal-open');
  if(updateHistory&&had){if(history.state?.radarModal)history.back();else writeURL('replace')}
  if(authenticated&&opener?.isConnected)opener.focus();opener=null;
}
function paintFavorite(id){const e=records.get(id);if(!e)return;for(const b of $$('[data-save]'))if(b.dataset.save===id){b.disabled=saving.has(id);b.setAttribute('aria-pressed',String(!!e.favorite));if(b.classList.contains('bookmark')){b.classList.toggle('saved',!!e.favorite);b.textContent=e.favorite?'★':'☆';b.setAttribute('aria-label',e.favorite?'取消收藏':'收藏活动')}else b.textContent=e.favorite?'取消收藏':'☆ 收藏活动'}}
async function save(id){
  const e=records.get(id);if(!e||saving.has(id)||!authenticated)return;const epoch=authEpoch,target=!e.favorite;saving.add(id);paintFavorite(id);
  try{const result=await api('preferences/'+encodeURIComponent(id),{method:'POST',body:JSON.stringify({favorite:target})});if(!authenticated||epoch!==authEpoch)return;
    e.favorite=result.favorite;const current=records.get(id);if(current)current.favorite=result.favorite;
    toast(result.favorite?'已收藏，其他设备登录后也能看到。':'已取消收藏。');
    if(view==='favorites'&&!result.favorite){const card=$$('[data-event]').find(c=>c.dataset.event===id);if(card){card.remove();offset=Math.max(0,offset-1);total=Math.max(0,total-1);$('#result-count').textContent=`${total} 个活动`;if(!$('#event-list').children.length){if(total)await load();else $('#event-list').innerHTML=emptyState()}}}
  }catch(err){if(err.name!=='AbortError'&&authenticated&&epoch===authEpoch)toast(err.message)}finally{saving.delete(id);if(authenticated&&epoch===authEpoch)paintFavorite(id)}
}
function navigate(next,reset=false){clearTimeout(debounce);closeDetail(false);view=Object.hasOwn(views,next)?next:'discover';if(reset)clearFilters();writeURL();load()}
function applyFilters(mode='push'){clearTimeout(debounce);closeDetail(false);writeURL(mode);load()}
function restoreNavigation(){if(!authenticated)return;const before=urlParams().toString();closeDetail(false);readURL();const after=urlParams().toString();const id=new URLSearchParams(location.search).get('event');if(before!==after)load().then(()=>{if(id)openDetail(id,false)});else if(id)openDetail(id,false)}
addEventListener('popstate',restoreNavigation);
$('#login-form').onsubmit=async e=>{e.preventDefault();const b=$('#login-submit');if(b.disabled)return;b.disabled=true;b.textContent='正在验证…';$('#login-error').textContent='';try{await api('login',{method:'POST',body:JSON.stringify({username:$('#username').value,password:$('#password').value})});$('#password').value='';await enter()}catch(err){if(err.name!=='AbortError')$('#login-error').textContent=err.message}finally{b.disabled=false;b.textContent='打开我的雷达 →'}};
$('#logout').onclick=async()=>{const b=$('#logout');b.disabled=true;try{await api('logout',{method:'POST'});showLogin()}catch(e){if(e.name!=='AbortError')toast(e.message)}finally{b.disabled=false}};
document.addEventListener('click',e=>{
  const b=e.target.closest('button,[data-open]');if(!b||b.disabled)return;
  if(b.dataset.facetAction){const kind=b.dataset.facetKind;$$(`#${kind}-options input`).forEach(x=>x.checked=b.dataset.facetAction==='all'?true:b.dataset.facetAction==='none'?false:!x.checked);updateFacetSummary(kind);applyFilters();return}
  if(b.dataset.facetRemove){const kind=b.dataset.facetRemove,value=b.dataset.facetValue;$$(`#${kind}-options input[type="checkbox"]`).forEach(x=>{if(x.value===value)x.checked=true});updateFacetSummary(kind);applyFilters();return}
  if(b.dataset.retrySource){retrySource(b.dataset.retrySource,b);return}if(b.dataset.save){save(b.dataset.save);return}if(b.dataset.open){openDetail(b.dataset.open);return}
  if(b.dataset.view||b.dataset.changeView){navigate(b.dataset.view||b.dataset.changeView);return}
  const action=b.dataset.action;
  if(action==='browse-all'){navigate('all',true);return}
  if(action==='reset'){clearFilters();applyFilters();return}
  if(action==='retry-status'){loadStatus();return}
  if(action==='retry'){view==='calendar'&&calendarRange?loadCalendar(calendarRange):load(failedAppend)}
});
$('#close-detail').onclick=()=>closeDetail();$('#detail').addEventListener('cancel',e=>{e.preventDefault();closeDetail()});
$('#detail').addEventListener('click',e=>{if(e.target===$('#detail')){const r=$('#detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeDetail()}});
$('#search').addEventListener('compositionstart',()=>{composing=true;clearTimeout(debounce)});
$('#search').addEventListener('compositionend',()=>{composing=false;clearTimeout(debounce);debounce=setTimeout(()=>applyFilters(),250)});
$('#search').oninput=e=>{clearTimeout(debounce);if(!composing&&!e.isComposing)debounce=setTimeout(()=>applyFilters(),250)};
$('#search').onkeydown=e=>{if(e.key==='Enter'&&!composing&&!e.isComposing){e.preventDefault();applyFilters()}};
for(const s of ['#district','#free','#hide-long','#sort'])$(s).onchange=()=>applyFilters();
for(const kind of ['type','topic']){
  $(`#${kind}-options`).addEventListener('change',e=>{if(e.target.matches('input[type="checkbox"]')){updateFacetSummary(kind);applyFilters()}});
  $(`#${kind}-filter`).addEventListener('toggle',e=>{if(e.target.open){for(const other of ['type','topic'])if(other!==kind)$(`#${other}-filter`).open=false}});
}
document.addEventListener('click',e=>{if(!e.target.closest('.multi-filter'))$$('.multi-filter[open]').forEach(x=>x.open=false)});
document.addEventListener('keydown',e=>{if(e.key==='Escape')$$('.multi-filter[open]').forEach(x=>x.open=false)});
$('#clear-filters').onclick=()=>{clearFilters();applyFilters()};$('#more').onclick=()=>load(true);
$('#refresh-data').onclick=()=>{stats();load()};
matchMedia('(max-width:619px)').addEventListener('change',e=>{if(calendar&&view==='calendar')calendar.changeView(e.matches?'listMonth':'dayGridMonth')});
addEventListener('pageshow',e=>{if(e.persisted)(async()=>{try{await api('session');await enter()}catch{showLogin()}})()});
addEventListener('pagehide',e=>{if(e.persisted)showLogin()});
(async()=>{try{await api('session');await enter()}catch(e){if(!authenticated)showLogin()}})();

