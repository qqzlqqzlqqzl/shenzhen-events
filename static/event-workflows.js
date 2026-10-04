/* Decision and review helpers: no automatic RSVP, subscription or network writes. */
'use strict';
globalThis.RadarEventWorkflows=(()=>{
 const selected=new Map();let detailOrder=[],returnElement=null,compareGeneration=0,compareIntentGeneration=0;
 function retireComparison(){compareGeneration++;compareIntentGeneration++;}
 function overlap(a,b){
  if(a.planning_eligible===false||b.planning_eligible===false||a._safety_pending||b._safety_pending)return null;
  if(a.all_day||b.all_day||!a.start_at||!b.start_at||!a.end_at||!b.end_at)return null;
  const [as,ae,bs,be]=[a.start_at,a.end_at,b.start_at,b.end_at].map(Date.parse);
  if(![as,ae,bs,be].every(Number.isFinite)||ae<=as||be<=bs)return null;
  return Math.max(as,bs)<Math.min(ae,be);
 }
 function shareText(e){return (e.safety?.warning||e._safety_pending?'【'+(e.safety?.warning||'安全状态待重新核实')+'】\n':'')+e.title+'\n'+RadarUI.fullTime(e)+(e.location?'\n'+e.location:'')+'\n'+safeOriginal(e.url)}
 function safeOriginal(value){try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password?u.href:''}catch{return ''}}
 function node(tag,text,cls){const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n}
 function paint(){
  const epoch=authEpoch;
  const bar=document.querySelector('#compare-bar'),chips=document.querySelector('#compare-chips');bar.hidden=selected.size===0;chips.replaceChildren();
  document.querySelector('#compare-open').textContent='比较 '+selected.size+' / 3 项';document.querySelector('#compare-open').disabled=selected.size<2;
  for(const [id,e] of selected){const b=node('button',e.title+' ×','compare-chip');b.type='button';b.setAttribute('aria-label','移除对比 '+e.title);b.onclick=()=>{if(!authenticated||epoch!==authEpoch)return;retireComparison();selected.delete(id);paint()};chips.append(b)}
  for(const b of document.querySelectorAll('[data-compare]')){const yes=selected.has(b.dataset.compare);b.setAttribute('aria-pressed',String(yes));b.textContent=yes?'已加入对比':'加入对比'}
 }
 function toggle(id){if(!authenticated)return;const e=records.get(id);if(!e)return;retireComparison();if(selected.has(id))selected.delete(id);else if(selected.size>=3){toast('最多比较3项，先移除不需要的候选。');return}else selected.set(id,{...e});paint()}
 async function compare(){
  if(!authenticated||selected.size<2)return;const epoch=authEpoch;invalidateSafety();
  const intent=compareIntentGeneration,ids=[...selected.keys()];let ticket=compareGeneration,restarts=0;
  const currentIntent=()=>authenticated&&epoch===authEpoch&&intent===compareIntentGeneration&&ids.length===selected.size&&ids.every(id=>selected.has(id));
  const currentRequest=()=>currentIntent()&&ticket===compareGeneration;
  for(let index=0;index<ids.length;index++){
   const id=ids[index],prior=selected.get(id);let current,error;
   try{current=await api('event/'+encodeURIComponent(id))}catch(problem){error=problem}
   if(!currentIntent()||error?.name==='AbortError')return;
   if(ticket!==compareGeneration){
    // A newer safety epoch invalidates the whole group. Retain only the
    // still-current explicit intent, then recheck every frozen ID together.
    if(++restarts>2){toast('活动安全状态连续变化，请重新比较。');return;}
    ticket=compareGeneration;index=-1;continue;
   }
   if(error)prior.safety={...prior.safety,warning:'安全状态未重新核实；仅供历史查阅'};
   else{reconcilePersonalRead(current);selected.set(id,current);records.set(id,current);}
  }
  if(!currentRequest())return;
  const box=document.querySelector('#compare-body');box.replaceChildren();const list=[...selected.values()];
  for(const e of list){const article=node('article','','compare-item');article.append(node('h3',e.title));if(e.safety?.warning)article.append(node('p',e.safety.warning,'warn'));for(const [label,value] of [['时间',RadarUI.fullTime(e)],['参加方式',e.attendance_label||'待确认'],['地点',e.location||'未注明'],['费用',costText(e)],[organizerLabel(e),e.organizer]]){if(!value)continue;const p=node('p','');p.append(node('b',label+'：'),node('span',value));article.append(p)}
   const url=safeOriginal(e.url);if(url){const a=node('a','查看原文 ↗');a.href=url;a.target='_blank';a.rel='noopener noreferrer';article.append(a)}const open=node('button','查看完整详情');open.type='button';open.onclick=()=>{if(!currentRequest())return;retireComparison();document.querySelector('#compare-dialog').close();if(!records.has(e.id))records.set(e.id,e);openDetail(e.id)};article.append(open);box.append(article)}
  for(let i=0;i<list.length;i++)for(let j=i+1;j<list.length;j++){const result=overlap(list[i],list[j]);box.append(node('p',`第 ${i+1} 与 ${j+1} 项：`+(result===null?'时间信息不足，无法判定冲突':result?'活动时段重叠，请自行取舍':'明确时段不重叠；未计入通勤时间'),'compare-conflict'))}
  document.querySelector('#compare-dialog').showModal();document.querySelector('#close-compare').focus();
 }
 function beginDetail(id){
  detailOrder=[...new Set([...document.querySelectorAll('.event-card[data-event]')].map(x=>x.dataset.event))];if(!detailOrder.includes(id))detailOrder=[...new Set([...records.keys()])].filter(key=>records.get(key)?.id===key);
  returnElement=document.activeElement;
 }
 function mountDetail(e){
  const epoch=authEpoch;
  const actions=document.querySelector('#detail-body .detail-actions'),title=document.querySelector('#detail-title');if(!actions||!title)return;
  // Act without scrolling past a long full-text excerpt.
  title.after(actions);actions.classList.add('detail-primary-actions');
  const extras=node('div','','detail-utilities');
  const copy=node('button','复制活动摘要');copy.type='button';copy.onclick=()=>copyText(shareText(e),'活动摘要',epoch);extras.append(copy);
  const share=node('button','复制原文链接');share.type='button';share.onclick=()=>copyText(safeOriginal(e.url),'原文链接',epoch);extras.append(share);
  if(e.location&&['offline','hybrid'].includes(e.attendance)){const a=node('a','在地图中搜索地点 ↗');a.href='https://uri.amap.com/search?keyword='+encodeURIComponent(e.location)+'&city='+encodeURIComponent('深圳');a.target='_blank';a.rel='noopener noreferrer';a.title='按地点文字搜索，不代表已核验的精确坐标';extras.append(a)}
  actions.after(extras);
  const index=detailOrder.indexOf(e.id),nav=node('nav','','detail-sequence');nav.setAttribute('aria-label','连续查看活动');
  for(const [delta,label] of [[-1,'上一条'],[1,'下一条']]){const b=node('button',label);b.type='button';b.dataset.detailStep=String(delta);b.disabled=index<0||index+delta<0||index+delta>=detailOrder.length;b.onclick=()=>{if(authenticated&&epoch===authEpoch)step(delta)};nav.append(b);if(delta===-1)nav.append(node('span',index>=0?`${index+1} / ${detailOrder.length} · 当前已加载结果`:'单条活动'))}
  title.before(nav);
 }
 async function step(delta){if(!authenticated)return;const epoch=authEpoch,index=detailOrder.indexOf(detailId),id=detailOrder[index+delta];if(!id)return;const had=history.state?.radarModal;await openDetail(id,false);if(!authenticated||epoch!==authEpoch||detailId!==id)return;writeURL('replace',id);history.replaceState({...history.state,radarModal:!!had},'',location.href);opener=returnElement;document.querySelector('#detail').scrollTop=0;}
 function restoreFocus(){if(authenticated&&returnElement?.isConnected){returnElement.focus({preventScroll:true});returnElement=null}}
 async function copyText(value,label,epoch){if(!authenticated||epoch!==authEpoch)return;if(!value){toast('没有可复制的公开链接。');return}try{await navigator.clipboard.writeText(value);if(!authenticated||epoch!==authEpoch)return;toast(label+'已复制；未包含私人日历订阅链接。')}catch{if(!authenticated||epoch!==authEpoch)return;const box=document.querySelector('#copy-text');box.value=value;document.querySelector('#copy-dialog').showModal();box.focus();box.select()}}
 async function unplanned(){if(!authenticated)return;const epoch=authEpoch;try{const result=await api('calendar-summary');if(!authenticated||epoch!==authEpoch||view!=='calendar')return;const unknown=Number(result.unscheduled)||0,long=Number(result.long_running)||0;const box=document.querySelector('#calendar-unscheduled');box.replaceChildren();box.hidden=!(unknown||long);if(unknown||long){const scope=node('span','全部收藏的补充提示（不随当前筛选变化）：');box.append(scope)}if(unknown){const b=node('button',`${unknown} 项收藏尚不能排入日历 · 查看收藏`);b.onclick=()=>{if(authenticated&&epoch===authEpoch)navigate('favorites',true)};box.append(b)}if(long){const b=node('button',`${long} 项长期收藏 · 显示长期活动`);b.onclick=()=>{if(!authenticated||epoch!==authEpoch)return;document.querySelector('#hide-long').checked=false;applyFilters()};box.append(b)}}catch{if(authenticated&&epoch===authEpoch&&view==='calendar'){const box=document.querySelector('#calendar-unscheduled');box.hidden=false;box.textContent='收藏日程提示暂不可用；仍可打开“我的收藏”。'}}}
 function init(){
  document.querySelector('#compare-open').onclick=compare;document.querySelector('#compare-clear').onclick=()=>{retireComparison();selected.clear();paint()};document.querySelector('#close-compare').onclick=()=>{retireComparison();document.querySelector('#compare-dialog').close()};
  document.querySelector('#compare-dialog').addEventListener('cancel',retireComparison);document.querySelector('#compare-dialog').addEventListener('close',retireComparison);document.querySelector('#close-copy').onclick=()=>document.querySelector('#copy-dialog').close();
  document.querySelector('#calendar-month-jump').onchange=e=>{if(/^\d{4}-\d{2}$/.test(e.target.value)){calendarDate=e.target.value+'-01';writeURL();if(calendar)calendar.gotoDate(calendarDate)}};
  document.querySelector('#calendar-saved-only').onchange=()=>applyFilters();
  document.querySelector('#shortcut-help').onclick=()=>{if(authenticated)document.querySelector('#shortcut-dialog').showModal()};document.querySelector('#close-shortcuts').onclick=()=>document.querySelector('#shortcut-dialog').close();
  document.addEventListener('keydown',e=>{if(!authenticated||e.isComposing||e.ctrlKey||e.metaKey||e.altKey||e.target.closest('input,textarea,select,[contenteditable="true"]')||String(getSelection()))return;
   if(document.querySelector('#detail').open&&['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();step(e.key==='ArrowLeft'?-1:1);return}
   if(document.querySelector('dialog[open]'))return;if(e.key==='/'){e.preventDefault();if(innerWidth<620)beginFilterDraft();document.querySelector('#search').focus()}if(e.key==='?'){e.preventDefault();document.querySelector('#shortcut-dialog').showModal()}
  });
 }
 function invalidateSafety(preserveComparisonIntent=false){if(preserveComparisonIntent)compareGeneration++;else retireComparison();for(const e of selected.values()){e._safety_pending=true;e.planning_eligible=false;e.safety={...e.safety,warning:e.safety?.warning||'安全状态待重新核实；暂不可安排'};}for(const button of document.querySelectorAll('#compare-body button'))button.onclick=null;document.querySelector('#compare-body')?.replaceChildren();}
 function clear(){
  retireComparison();selected.clear();detailOrder=[];returnElement=null;
  // Remove session-owned content and callbacks before another login can use them.
  for(const button of document.querySelectorAll('#compare-body button,#compare-chips button,#detail-body button,#calendar-unscheduled button'))button.onclick=null;
  document.querySelector('#calendar-unscheduled').replaceChildren();document.querySelector('#calendar-unscheduled').hidden=true;
  document.querySelector('#compare-body').replaceChildren();document.querySelector('#copy-text').value='';
  for(const id of ['copy-dialog','compare-dialog','shortcut-dialog']){const dialog=document.getElementById(id);if(dialog.open)dialog.close()}
  paint();
 }
 return {has:id=>selected.has(id),overlap,safeOriginal,shareText,toggle,paint,beginDetail,mountDetail,restoreFocus,unplanned,init,clear,invalidateSafety};
})();
