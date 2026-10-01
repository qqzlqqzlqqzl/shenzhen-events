/* Query-only saved views. No session, token, article detail or credentials persist. */
'use strict';
globalThis.RadarPlanner=(()=>{
 const allowed=new Set(['view','month','q','district','type','topic','type_none','topic_none','free','show_long','sort','attendance','feedback','feedback_tag','viewed','from','until','saved_only']);
 const cleanQuery=value=>{const q=new URLSearchParams(String(value||'').slice(0,4096));for(const [k,v] of [...q])if(!allowed.has(k)||v.length>180)q.delete(k);return q.toString()};
 function validDay(value){return /^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value+'T00:00:00Z'))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value}
 function range(from,until){
  if(!from&&!until)return null;
  if(!validDay(from)||!validDay(until))throw new Error('请选择完整、有效的开始和结束日期。');
  const span=(Date.parse(until)-Date.parse(from))/86400000+1;
  if(span<1||span>93)throw new Error('结束日期不能早于开始日期，日期范围最多93天。');
  return {start:from,end:new Date(Date.parse(until)+86400000).toISOString().slice(0,10),days:span};
 }
 function decode(value){
  try{const data=JSON.parse(value||'[]');if(!Array.isArray(data))return [];
   const seen=new Set();return data.filter(x=>{if(!x||typeof x.name!=='string'||typeof x.query!=='string'||!x.name.trim()||x.name.length>40||seen.has(x.name.toLocaleLowerCase()))return false;seen.add(x.name.toLocaleLowerCase());return true}).slice(0,12).map(x=>({name:x.name.trim(),query:cleanQuery(x.query)}));
  }catch{return []}
 }
 let key='radar.saved.v1:owner',profiles=[],undo=null;
 function render(){const select=document.querySelector('#saved-view-choice');if(!select)return;const prev=select.value;select.replaceChildren(new Option('选择常用视图…',''));profiles.forEach((x,i)=>select.add(new Option(x.name,String(i))));if(profiles[Number(prev)]&&prev!=='')select.value=prev;document.querySelector('#saved-view-count').textContent=profiles.length+' / 12 · 仅此浏览器';}
 function write(next){try{localStorage.setItem(key,JSON.stringify(next));profiles=next;render();return true}catch{toast('浏览器未允许保存；当前筛选仍可正常使用。');return false}}
 function user(name){key='radar.saved.v1:'+String(name||'owner');try{profiles=decode(localStorage.getItem(key))}catch{profiles=[]}undo=null;render()}
 function selected(){const value=document.querySelector('#saved-view-choice').value;return value===''?-1:Number(value)}
 function init(){
  const name=document.querySelector('#saved-view-name');
  document.querySelector('#save-view-form').onsubmit=e=>{e.preventDefault();const label=name.value.trim();if(!label||label.length>40){toast('视图名称需为1–40个字符。');return}if(profiles.some(x=>x.name.toLocaleLowerCase()===label.toLocaleLowerCase())){toast('已有同名视图，请改名或使用现有视图。');return}if(profiles.length>=12){toast('最多保存12个视图，请先整理旧视图。');return}try{range(document.querySelector('#date-from').value,document.querySelector('#date-until').value)}catch(err){toast(err.message);return}if(write([...profiles,{name:label,query:cleanQuery(urlParams())}])){toast('常用视图已保存到此浏览器。');name.value=''}};
  document.querySelector('#apply-saved-view').onclick=()=>{const i=selected();if(i<0)return;closeDetail(false);history.pushState({radar:true},'',location.pathname+'?'+profiles[i].query);readURL();rememberFilters();load()};
  document.querySelector('#rename-saved-view').onclick=()=>{const i=selected(),label=name.value.trim();if(i<0||!label||label.length>40){toast('选择视图并输入1–40字新名称。');return}if(profiles.some((x,j)=>j!==i&&x.name.toLocaleLowerCase()===label.toLocaleLowerCase())){toast('名称重复。');return}const next=profiles.map((x,j)=>j===i?{...x,name:label}:x);if(write(next))toast('视图已改名。')};
  document.querySelector('#delete-saved-view').onclick=()=>{const i=selected();if(i<0)return;const before=profiles.map(x=>({...x}));if(write(profiles.filter((_,j)=>j!==i))){undo={before,current:JSON.stringify(profiles)};document.querySelector('#undo-saved-view').hidden=false;toast('视图已移除，可以撤销。')}};
  document.querySelector('#undo-saved-view').onclick=()=>{if(!undo)return;let current;try{current=localStorage.getItem(key)}catch{return}if(current!==undo.current){toast('视图列表已变化，请重新核对。');return}if(write(undo.before)){undo=null;document.querySelector('#undo-saved-view').hidden=true}};
  document.querySelector('#saved-view-choice').onchange=()=>{const i=selected();if(i>=0)name.value=profiles[i].name};
  addEventListener('storage',e=>{if(e.key===key){profiles=decode(e.newValue);undo=null;document.querySelector('#undo-saved-view').hidden=true;render()}});
 }
 return {cleanQuery,validDay,range,decode,user,init};
})();
