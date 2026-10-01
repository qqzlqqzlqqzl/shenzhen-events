/* Pure display helpers shared by the browser and regression tests. */
'use strict';
globalThis.RadarUI = (() => {
  const valid = value => value && Number.isFinite(new Date(value).getTime());
  function dayKey(value) {
    if (!valid(value)) return '';
    const parts = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(value));
    return ['year','month','day'].map(k => parts.find(p => p.type === k).value).join('-');
  }
  function format(value, withTime=true) {
    if (!valid(value)) return '未注明';
    return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',...(withTime?{hour:'2-digit',minute:'2-digit',hourCycle:'h23'}:{})}).format(new Date(value));
  }
  const hasEnd = e => valid(e.start_at)&&valid(e.end_at)&&new Date(e.end_at)>new Date(e.start_at)&&(!e.all_day||dayKey(e.end_at)>dayKey(e.start_at));
  function fullTime(e) {
    if (!valid(e.start_at)) return '举办时间尚待核实';
    const end=hasEnd(e)?new Date(new Date(e.end_at).getTime()-(e.all_day?86400000:0)):null;
    const start=format(e.start_at,!e.all_day);
    if (!end) return start+(e.all_day?' · 具体时段未注明':' · 结束时间未注明');
    const same=dayKey(end)===dayKey(e.start_at);
    const suffix=same?(e.all_day?'':' — '+new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(end)):' — '+format(end,!e.all_day);
    return start+suffix+(e.all_day?' · 具体时段/开放日以原文为准':'');
  }
  // Source ends are exclusive. Count covered Shanghai dates, not rounded 24h periods.
  function dateSpan(e) {
    if (!valid(e.start_at)) return {start:'',last:'',days:0,label:''};
    const start=dayKey(e.start_at);
    const last=hasEnd(e)?dayKey(new Date(new Date(e.end_at).getTime()-(e.all_day?86400000:1))):start;
    const days=Math.round((Date.parse(last)-Date.parse(start))/86400000)+1;
    const short=day=>day.slice(5).replace('-', '/');
    const range=start.slice(0,4)===last.slice(0,4)?`${short(start)}—${short(last)}`:`${start.replaceAll('-', '/')}—${last.replaceAll('-', '/')}`;
    return {start,last,days,label:days>1?`${range} · 跨 ${days} 天`:''};
  }
  function calendarEvent(e) {
    const span=dateSpan(e);
    // FullCalendar uses UTC as a wall-clock display zone; normalize source offsets first.
    const wall=value=>new Date(new Date(value).getTime()+8*3600000).toISOString().slice(0,19);
    const classNames=[];
    if(span.days>1)classNames.push('multi-day-event');
    if(e.favorite)classNames.push('favorite-event');
    return {id:e.id,title:e.title,start:e.all_day?span.start:wall(e.start_at),
      end:hasEnd(e)?(e.all_day?dayKey(e.end_at):wall(e.end_at)):null,allDay:!!e.all_day,
      display:span.days>1?'block':'list-item',classNames,
      extendedProps:{rangeLabel:span.label,fullTime:fullTime(e),favorite:!!e.favorite,favoriteRank:e.favorite?0:1}};
  }
  function lifecycle(e, current=Date.now()) {
    if(e.status==='cancelled')return '已取消';
    if(e.status==='not_event')return '非线下活动';
    if(!valid(e.start_at)||e.status==='needs_review')return '时间地点待确认';
    if(valid(e.end_at)&&new Date(e.end_at).getTime()<=current)return '已结束';
    if(new Date(e.start_at).getTime()<=current)return valid(e.end_at)?(e.all_day?'活动期内 · 开放日见原文':'进行中'):'已开始 · 结束时间未注明';
    return '';
  }
  function safeUrl(value) {
    try {const u=new URL(value,location.origin);return ['https:','http:'].includes(u.protocol)?u.href:'#';} catch{return '#';}
  }
  return {dayKey,format,fullTime,dateSpan,calendarEvent,lifecycle,safeUrl};
})();
