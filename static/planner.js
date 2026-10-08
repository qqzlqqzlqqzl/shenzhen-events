/* Query-only saved views. No session, token, article detail or credentials persist. */
'use strict';
globalThis.RadarPlanner=(()=>{
 const allowed=new Set(['view','month','q','district','districts','district_none','type','topic','type_none','topic_none','free','show_long','sort','attendance','feedback','feedback_tag','viewed','from','until','saved_only']);
 const cleanQuery=value=>{const raw=new URLSearchParams(String(value||'')),q=new URLSearchParams(String(value||'').slice(0,4096));for(const [k,v] of [...q])if(!allowed.has(k)||v.length>180)q.delete(k);
  // Sanitization must never erase a date constraint and silently widen a saved view.
  for(const key of ['from','until'])if(raw.has(key)){const value=raw.get(key);q.set(key,value.length<=180?value:'invalid')}
  return q.toString()};
 function validDay(value){return /^\d{4}-\d{2}-\d{2}$/.test(value)&&!value.startsWith('0000-')&&Number.isFinite(Date.parse(value+'T00:00:00Z'))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value}
 function range(from,until){
  if(!from&&!until)return null;
  if(!validDay(from)||!validDay(until))throw new Error('请选择完整、有效的开始和结束日期。');
  const span=(Date.parse(until)-Date.parse(from))/86400000+1;
  if(span<1||span>93)throw new Error('结束日期不能早于开始日期，日期范围最多93天。');
  const end=new Date(Date.parse(until)+86400000).toISOString().slice(0,10);
  if(!validDay(end))throw new Error('结束日期超出支持范围，请选择9999-12-30或更早日期。');
  return {start:from,end,days:span};
 }
 function decode(value){
  try{const data=JSON.parse(value||'[]');if(!Array.isArray(data))return [];
   const seen=new Set();return data.filter(x=>{if(!x||typeof x.name!=='string'||typeof x.query!=='string'||!x.name.trim()||x.name.length>40||seen.has(x.name.toLocaleLowerCase()))return false;seen.add(x.name.toLocaleLowerCase());return true}).slice(0,12).map(x=>({name:x.name.trim(),query:cleanQuery(x.query)}));
  }catch{return []}
 }
 let key='radar.saved.v1:owner',profiles=[],undo=null;
 function render(){const select=document.querySelector('#saved-view-choice');if(!select)return;const prev=select.value;select.replaceChildren(new Option('选择常用视图…',''));profiles.forEach((x,i)=>select.add(new Option(x.name,String(i))));if(profiles[Number(prev)]&&prev!=='')select.value=prev;document.querySelector('#saved-view-count').textContent=profiles.length+' / 12 · 仅此浏览器';}
 function write(next){try{localStorage.setItem(key,JSON.stringify(next));profiles=next;render();return true}catch{toast('浏览器未允许保存；当前筛选仍可正常使用。');return false}}
 function storageFailure(){toast('浏览器未允许保存；请恢复存储访问后重试。当前筛选仍可继续使用。')}
 function readProfiles(){const raw=localStorage.getItem(key);if(raw!==null&&!Array.isArray(JSON.parse(raw)))throw new Error('Invalid saved views');return {raw,items:decode(raw)}}
 function expireUndo(){undo=null;document.querySelector('#undo-saved-view').hidden=true}
 // A failed read never authorizes replacement of the existing list.
 function reconcile(){const select=document.querySelector('#saved-view-choice'),previous=profiles[selected()]?.name;try{profiles=readProfiles().items;render();select.value=previous?String(profiles.findIndex(x=>x.name===previous)):'';return true}catch{storageFailure();return false}}
 function user(name){const next='radar.saved.v1:'+String(name||'owner'),changed=next!==key;key=next;
  if(changed){profiles=[];expireUndo();document.querySelector('#saved-view-choice').value='';document.querySelector('#saved-view-name').value=''}
  try{const fresh=readProfiles();profiles=fresh.items;if(undo&&fresh.raw!==undo.current)expireUndo()}catch{profiles=[]}
  render();document.querySelector('#undo-saved-view').hidden=!undo;
 }
 function selected(){const value=document.querySelector('#saved-view-choice').value;return value===''?-1:Number(value)}
 function init(){
  const name=document.querySelector('#saved-view-name');
  document.querySelector('#save-view-form').onsubmit=e=>{e.preventDefault();const label=name.value.trim();if(!reconcile())return;if(!label||label.length>40){toast('视图名称需为1–40个字符。');return}if(profiles.some(x=>x.name.toLocaleLowerCase()===label.toLocaleLowerCase())){toast('已有同名视图，请改名或使用现有视图。');return}if(profiles.length>=12){toast('最多保存12个视图，请先整理旧视图。');return}if(!validateDateInputs())return;const params=draftParams();for(const [param,id] of [['from','date-from'],['until','date-until']]){const value=document.querySelector('#'+id).value;if(value)params.set(param,value);else params.delete(param)}if(write([...profiles,{name:label,query:cleanQuery(params)}])){toast('常用视图已保存到此浏览器。');name.value=''}};
  document.querySelector('#apply-saved-view').onclick=()=>{const i=selected();if(i<0)return;const params=new URLSearchParams(profiles[i].query);try{range(params.get('from')||'',params.get('until')||'')}catch(err){toast(err.message);return}if(filterDraft)finishFilterDraft(false,false);closeDetail(false);history.pushState({radar:true},'',location.pathname+'?'+profiles[i].query);readURL();rememberFilters(true);generatedFilterURL=location.pathname+location.search;load()};
  document.querySelector('#rename-saved-view').onclick=()=>{if(!reconcile())return;const i=selected(),label=name.value.trim();if(i<0||!label||label.length>40){toast('选择视图并输入1–40字新名称。');return}if(profiles.some((x,j)=>j!==i&&x.name.toLocaleLowerCase()===label.toLocaleLowerCase())){toast('名称重复。');return}const next=profiles.map((x,j)=>j===i?{...x,name:label}:x);if(write(next))toast('视图已改名。')};
  document.querySelector('#delete-saved-view').onclick=()=>{if(!reconcile())return;const i=selected();if(i<0)return;const before=profiles.map(x=>({...x}));if(write(profiles.filter((_,j)=>j!==i))){undo={before,current:JSON.stringify(profiles)};document.querySelector('#undo-saved-view').hidden=false;toast('视图已移除，可以撤销。')}};
  document.querySelector('#undo-saved-view').onclick=()=>{if(!undo)return;let current;try{current=localStorage.getItem(key)}catch{storageFailure();return}if(current!==undo.current){toast('视图列表已变化，请重新核对。');return}if(write(undo.before)){undo=null;document.querySelector('#undo-saved-view').hidden=true}};
  document.querySelector('#saved-view-choice').onchange=()=>{const i=selected();if(i>=0)name.value=profiles[i].name};
  addEventListener('storage',e=>{if(e.key===key){profiles=decode(e.newValue);undo=null;document.querySelector('#undo-saved-view').hidden=true;render()}});
 }
 return {cleanQuery,validDay,range,decode,user,init};
})();

