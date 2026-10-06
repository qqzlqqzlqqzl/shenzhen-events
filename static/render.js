const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const views={discover:['为你发现','优先看创客、硬件、AI实践与开源；其他兴趣也保留在全部活动中。'],week:['这一周，去见见新想法','按举办时间整理，本周内仍可参加的线下活动。'],weekend:['把周末留给有趣的事','本周六、周日的活动；长期/重复项目默认隐藏，需要时可手动显示。'],all:['全部活动','深圳线下与可在线参加的活动；可按参加方式筛选。'],favorites:['我的收藏','跨设备保存；已结束、已取消或待确认的收藏也会保留并标注状态。'],calendar:['把好奇心，放进日程','月历按照北京时间显示，短期跨日活动连续呈现；点击查看完整时段。'],status:['来源与状态','看得见采集情况，也看得见暂时没有拿到的信息。'],review:['待确认的活动线索','缺少可核实时间或地点的内容，不进入近期活动与日历。'],past:['过往活动','历史记录不代表当前还能报名。']};
views.feedback=['我的反馈','回顾明确判断；过去和待确认的活动也会保留。'];views.history=['最近浏览','按最近打开排序；看过不等于感兴趣或已参加。'];
function toast(text){$('#toast').textContent=text;$('#toast').hidden=false;clearTimeout(toast.t);toast.t=setTimeout(()=>$('#toast').hidden=true,3200)}
function dateParts(e){const value=e.display_at||e.start_at;if(!value)return {day:'?',sub:'时间\n待确认'};const d=new Date(value);const day=new Intl.DateTimeFormat('en',{timeZone:'Asia/Shanghai',day:'2-digit'}).format(d);const month=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'short'}).format(d);const week=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',weekday:'short'}).format(d);const note=e.period_label||(e.long_running?'长期/重复 · 开放日见原文':e.all_day?(RadarUI.dateSpan(e).days>1?'活动时段以原文为准':'当天时段以原文为准'):new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false}).format(d));return {day,sub:month+' · '+week+'\n'+note}}
function originalLink(value,label,cls='',unavailable=label+'（链接不可用）'){const url=RadarUI.safeUrl(value);return url==='#'?`<span${cls?` class="${esc(cls)}"`:''} aria-disabled="true">${esc(unavailable)}</span>`:`<a${cls?` class="${esc(cls)}"`:''} href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`}
function costText(e){const t=String(e.cost_text||'').trim();return /^(费用未注明|未注明|未知|待确认|费用待确认|N\/A|null)$/i.test(t)?'':t}
function detailPosters(d){return (Array.isArray(d.images)?d.images:[]).filter(x=>typeof x==='string'&&/^https?:\/\//i.test(x)).slice(0,8).map((url,i)=>{if(RadarUI.safeUrl(url)==='#')return originalLink(url,`原文配图 ${i+1}`);const local=d.cached_images?.[url],cached=typeof local==='string'&&/^\/events\/static\/posters\/[a-f0-9]{64}\.(webp|png|jpg)$/.test(local);return `<a href="${esc(RadarUI.safeUrl(url))}" target="_blank" rel="noopener noreferrer">${cached?`<img class="detail-poster" src="${esc(local)}" alt="活动原文配图 ${i+1}" loading="lazy" referrerpolicy="no-referrer">`:`查看原文配图 ${i+1} ↗`}</a>`}).join('')}
function detailExtras(e){const d=e.details||{},roles=[['coorganizers','协办'],['guidance','指导'],['supporters','支持']];return `${d.review_notes?`<p class="detail-review-note">${esc(d.review_notes)}</p>`:''}${roles.filter(([k])=>d[k]).map(([k,label])=>`<p><b>${label}（原文标注）</b>${esc(d[k])}</p>`).join('')}${d.organizer_notes?`<p class="detail-summary">${esc(d.organizer_notes)}</p>`:''}${detailPosters(d)}${d.detail_text?`<details class="detail-original"><summary>展开原文内容摘录</summary><p>${esc(d.detail_text)}</p></details>`:''}${d.evidence_url?`<p class="detail-source">以上来自${originalLink(d.evidence_url,'详情原文')}，主协办标注不等于独立背书核验。</p>`:''}`}
function organizerLabel(e){return e.details?.organizer_role==='publisher'?'发布方':'主办'}
const feedbackSignals={interested:'感兴趣',not_interested:'不感兴趣',attended:'已参加'};
const feedbackTagLabels={time_conflict:'时间不合适',location_inconvenient:'地点不方便',price_issue:'价格原因',topic_like:'主题喜欢',vibe_like:'氛围喜欢',more_like_this:'以后多推',less_like_this:'以后少推'};
function feedbackSummary(e){if(feedbackSignals[e.feedback])return feedbackSignals[e.feedback];const n=Array.isArray(e.feedback_tags)?e.feedback_tags.length:0;return n?'已标记 '+n+' 项':''}
function feedbackBadge(e){const label=feedbackSummary(e);return '<span class="tag user-feedback-tag" data-feedback-for="'+esc(e.id)+'" data-feedback-value="'+esc(e.feedback||'')+'"'+(label?'':' hidden')+'>我的反馈 · '+esc(label)+'</span>'}
function personalPending(id){return (typeof saving!=='undefined'&&saving.has(id))||(typeof feedbackSaving!=='undefined'&&feedbackSaving.has(id))}
function cardSummary(e){const s=String(e.summary||'').trim();return s===e.title?'':s}
function costLabel(e){return e.cost_free?'免费':costText(e)||'费用待确认'}
function cardTags(e){
  const state=RadarUI.lifecycle(e),fee=costText(e),attendance=e.attendance_label||({online:'线上',offline:'线下',hybrid:'线上+线下'}[e.attendance]);
  return `<div class="card-tags"><span class="tag type-tag">${esc(e.event_type_label||'其他活动')}</span>${(e.topics||[]).map(t=>`<span class="tag topic-tag">${esc(t)}</span>`).join('')}${attendance?`<span class="tag secondary-tag">${esc(attendance)}</span>`:''}${e.long_running?'<span class="tag long-tag">长期/重复</span>':''}${state?`<span class="tag ${state==='进行中'?'live':'warn'}">${esc(state)}</span>`:''}${e.stale?'<span class="tag warn">信息可能已变化</span>':''}${fee?`<span class="tag cost-state">${esc(fee)}</span>`:`<span class="cost-state visually-hidden">${esc(costLabel(e))}</span>`}${feedbackBadge(e)}<span class="tag viewed-tag" data-viewed-for="${esc(e.id)}"${e.viewed_at?'':' hidden'}>已看过</span></div>`;
}
function bookmark(e){return `<button class="bookmark ${e.favorite?'saved':''}" data-save="${esc(e.id)}" ${personalPending(e.id)?'disabled':''} aria-label="${e.favorite?'取消收藏':'收藏活动'}" aria-pressed="${!!e.favorite}">${e.favorite?'★':'☆'}</button>`}
function compareToggle(e){return `<button class="compare-toggle" type="button" data-compare="${esc(e.id)}" aria-pressed="${RadarEventWorkflows.has(e.id)}">${RadarEventWorkflows.has(e.id)?'已加入对比':'加入对比'}</button>`}
function card(e){const d=dateParts(e);return `<article class="event-card" data-event="${esc(e.id)}"><div class="card-top"><div class="date-chip"><b>${esc(d.day)}</b><span>${esc(d.sub.split('\n')[0])}</span></div>${bookmark(e)}</div><div class="card-main">${cardTags(e)}<h3><button class="title-button" data-open="${esc(e.id)}">${esc(e.title)}</button></h3><p class="card-time">${esc(fullTime(e))}</p>${cardSummary(e)?`<p class="card-summary">${esc(cardSummary(e))}</p>`:''}<div class="event-meta">${esc(e.location||'地点待确认')}</div></div><div class="card-footer"><span class="source-label">来源 · ${esc(e.sources?.[0]?.name||'公开活动来源')}${e.sources?.length>1?' +'+(e.sources.length-1)+' 个来源':''}</span>${compareToggle(e)}</div></article>`}
function listRow(e){return `<article class="event-card event-row" data-event="${esc(e.id)}"><span class="card-time">${esc(fullTime(e))}</span><div class="list-row-content"><h3><button class="title-button" data-open="${esc(e.id)}">${esc(e.title)}</button></h3><span class="cost-state visually-hidden">${esc(costLabel(e))}</span></div><span class="list-location">${esc(e.district||e.location||'地点待确认')}</span>${compareToggle(e)}${bookmark(e)}</article>`}

const states={ok:'本次读取完成',partial:'部分覆盖',empty:'暂无结果',error:'上次检查失败',blocked:'上次访问受限',pending:'等待采集'};
function timeText(value,withTime=true){return value?RadarUI.format(value,withTime):'未更新'}
function fullTime(e){return RadarUI.fullTime(e)}


function renderEventItems(items,mode='cards'){
  if(mode!=='list')return items.map(card).join('');
  // Keep the API's date/personal order; group only contiguous dates.
  let key=null,html='';
  for(const e of items){
    const next=RadarUI.dayKey(e.display_at||e.start_at)||'unknown';
    if(next!==key){
      if(key!==null)html+='</div></section>';
      const value=e.display_at||e.start_at,label=next==='unknown'?'举办日期待确认':new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'long'}).format(new Date(value));
      html+='<section class="date-group"><h3 class="date-group-title">'+esc(label)+'</h3><div class="date-group-items">';key=next;
    }
    html+=listRow(e);
  }
  return html+(key!==null?'</div></section>':'');
}
