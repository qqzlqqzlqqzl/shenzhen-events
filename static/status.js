/* Readable source coverage and persistent one-source retry controls. */
'use strict';
let statusPoll=null;
const modes={city_pages:'城市分页列表',page_inventory:'指定汇总页',single_page:'指定公开页面',search_index:'搜索索引（非全量）',discovery_only:'发现入口（非全量）',fallback_only:'兜底订阅（非全量）'};
const number=v=>Number.isFinite(Number(v))&&v!==null?Number(v).toLocaleString():'—';
function coverageCard(s){
 const v=s.coverage||{},job=s.retry,active=job&&['queued','running'].includes(job.state);
 const count=(label,value)=>`<div><dt>${esc(label)}</dt><dd>${number(value)}</dd></div>`;
 const label=job?.state==='queued'?'检查已排队':job?.state==='running'?'正在检查…':v.next_cursor?'继续采集后续页':'重新检查此来源';
 return `<article class="source-card" data-source="${esc(s.id)}"><header><h3><a href="${esc(RadarUI.safeUrl(s.url))}" target="_blank" rel="noopener noreferrer">${esc(s.name)} ↗</a></h3><span class="status-label ${esc(s.status)}">${esc(states[s.status]||s.status)}</span></header>
 <p class="coverage-scope">${esc(modes[v.mode]||'等待新一轮覆盖检查')}${v.pages_visited!==undefined?' · 本次检查 '+number(v.pages_visited)+' 页':''}</p>
 ${v.version?`<dl class="coverage-flow">${count('本次可见条目',v.visible)}${count('成功解析',v.extracted)}${count('去重后',v.unique)}${count('深圳候选',v.shenzhen_candidates)}${count('本轮纳入',v.admitted)}${count('已收录含线索',v.stored_events??s.event_count)}</dl>`:`<p>${esc(s.message||'等待首次采集')}</p>`}
 ${v.source_total!==null&&v.source_total!==undefined?`<p>源页声明总量 <b>${number(v.source_total)}</b> 条；不是本站已抓取数量。</p>`:''}
 ${Object.keys(v.rejected||{}).length?`<p class="coverage-reasons">未纳入：${Object.entries(v.rejected).map(([k,n])=>esc(k)+' '+number(n)).join(' · ')}</p>`:''}
 ${v.detail_attempted||v.detail_deferred||v.detail_cached?`<p>详情补全 ${number(v.detail_attempted)} 次 · 缓存复用 ${number(v.detail_cached)} 条 · 待后续补全 ${number(v.detail_deferred)} 条</p>`:''}
 ${(v.reasons||[]).length?`<p class="coverage-warning">${esc([...new Set(v.reasons)].join('；'))}</p>`:''}
 <small>上次检查 ${esc(timeText(s.last_attempt))}<br>最近取得数据 ${esc(timeText(s.last_success))}<br>自动检查不早于 ${esc(timeText(s.next_attempt))}</small>
 <div class="source-retry"><button class="secondary" data-retry-source="${esc(s.id)}" ${active?'disabled':''}>${label}</button><span aria-live="polite">${esc(active?job.message:job?.state==='failed'?'上次手动检查未完成，可重试':job?.state==='done'?'上次手动检查已完成':'只检查此来源，不重抓其他来源')}</span></div></article>`;
}
async function retrySource(id,button){
 if(!authenticated||button.disabled)return;const epoch=authEpoch;button.disabled=true;button.textContent='正在排队…';
 try{const j=await api('sources/'+encodeURIComponent(id)+'/retry',{method:'POST'});if(epoch!==authEpoch||!authenticated)return;toast(j.message);await loadStatus(true)}
 catch(e){if(e.name!=='AbortError'&&epoch===authEpoch&&authenticated){toast(e.message);button.disabled=false;button.textContent='重新检查此来源'}}
}
async function loadStatus(background=false){
 clearTimeout(statusPoll);const epoch=authEpoch,ticket=++statusTicket;$('#status-panel').setAttribute('aria-busy','true');
 try{
  const s=await api('status');if(!authenticated||epoch!==authEpoch||ticket!==statusTicket||view!=='status')return;
  const focused=document.activeElement?.dataset.retrySource;
  const budgetOpen=$('.analysis-budget details')?.open;
  const active=s.sources.filter(x=>x.retry&&['queued','running'].includes(x.retry.state));
  $('#status-panel').innerHTML=`<p class="status-intro">下面区分“源页看到多少”“实际解析多少”和“本站纳入多少”。读取完成只代表这一轮已检查的范围，不代表覆盖全网。刷新状态只更新看板；重新检查按钮才会检查对应来源。</p>
  <section class="analysis-budget" aria-label="AI分析用量"><div><h3>今日 AI 分析</h3><strong>${number(s.budget.calls)} 次请求 <span>· ${number(s.budget.tokens)} tokens</span></strong><p>待 AI 分析 ${number(s.analysis_pending??0)} 条；基础分类和日历可先使用。</p><p>每日保护上限：${number(s.limits.daily_calls)} 次请求 / ${number(s.limits.daily_tokens)} tokens</p></div><details><summary>这个数字是什么意思？</summary><p>tokens 是模型处理文字的计量单位，不是活动条数，也不是人民币金额。系统只分析新增或内容有变化的记录；未变化的缓存不会重复分析。失败请求可能暂留预算预占，实际收费以 API 平台账单为准。达到上限后暂停 AI 分析，已有活动和采集仍可使用。</p></details></section>
  <div class="status-summary"><span>共 <b>${s.sources.length}</b> 个来源</span><span>活动数据库 <b>${(s.db_bytes/1048576).toFixed(2)} MB</b></span><span>过往活动保留 <b>${s.retention_days} 天</b></span>${active.length?`<span role="status">${active.length} 个来源排队/检查中，将自动更新</span>`:''}</div>
  <div class="status-actions"><button id="copy-ics" class="secondary">复制我的收藏日历订阅链接</button><button class="secondary" data-change-view="review">查看待确认线索</button><button class="secondary" data-change-view="past">查看过往活动</button><button class="secondary" id="refresh-status">刷新看板（不重新抓取）</button></div>
  <div class="source-grid">${s.sources.map(coverageCard).join('')}</div>
  <div class="section-heading"><div><h2>发现的公众号线索</h2><p>候选来源不等于已验证订阅。</p></div><span class="result-count">${s.candidates.length} 个候选</span></div>
  ${s.candidates.length?`<div class="table-wrap"><table><thead><tr><th>公众号 / 发布者</th><th>关键词</th><th>命中</th></tr></thead><tbody>${s.candidates.map(c=>`<tr><td><a href="${esc(RadarUI.safeUrl(c.url))}" target="_blank" rel="noopener noreferrer">${esc(c.name)}</a></td><td>${esc(c.query)}</td><td>${number(c.hits)}</td></tr>`).join('')}</tbody></table></div>`:'<p>暂无线索</p>'}
  <div class="section-heading"><div><h2>最近运行记录</h2><p>日志只记录运行结果，不记录密钥或密码。</p></div></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>任务</th><th>结果</th></tr></thead><tbody>${s.runs.map(r=>{let d={};try{d=JSON.parse(r.details)}catch{}return `<tr><td>${esc(timeText(r.finished_at))}</td><td>${esc(({source:'来源采集',collect:'采集汇总',analysis:'内容分析',geocode:'地区补全'})[r.kind]||r.kind)}</td><td>${esc(d.message||('状态 '+r.status+(d.processed!==undefined?' · 已处理 '+d.processed+' 条':'')))}</td></tr>`}).join('')}</tbody></table></div>`;
  $('#copy-ics').onclick=async()=>{const link=new URL(s.ics_url,location.origin).href;try{await navigator.clipboard.writeText(link);toast('已复制私人收藏日历链接，请勿公开分享。')}catch{prompt('私人收藏日历链接，请勿公开分享',link)}};
  if(budgetOpen)$('.analysis-budget details').open=true;
  $('#refresh-status').onclick=()=>{loadStatus();stats()};
  if(focused)$$('[data-retry-source]').find(b=>b.dataset.retrySource===focused)?.focus({preventScroll:true});
  if(active.length)statusPoll=setTimeout(()=>{if(authenticated&&view==='status')loadStatus(true)},3000);
 }catch(e){
  if(e.name==='AbortError'||!authenticated||epoch!==authEpoch||ticket!==statusTicket||view!=='status')return;
  if(background){toast(e.message);statusPoll=setTimeout(()=>{if(authenticated&&view==='status')loadStatus(true)},8000)}
  else $('#status-panel').innerHTML=`<div class="notice">${esc(e.message)} <button data-action="retry-status" class="secondary">重试</button></div>`;
 }finally{if(ticket===statusTicket)$('#status-panel').setAttribute('aria-busy','false')}
}
