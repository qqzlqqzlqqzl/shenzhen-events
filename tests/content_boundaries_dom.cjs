const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.join(__dirname,'..');
async function ready(fixture){
 const errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM(fs.readFileSync(path.join(root,'static/index.html'),'utf8'),{url:'https://fixture.test/events/',runScripts:'outside-only',virtualConsole:vc}),w=dom.window;
 w.fetch=()=>{throw Error('Offline fixture forbids network')};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};w.fixture={...fixture,planning_eligible:true,safety_epoch:0};w.companion={...w.fixture,id:'comparison-control',title:'Synthetic comparison control'};
 const scripts=['ui-state.js','render.js','event-workflows.js','status.js'].map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n;\n');
 const app=fs.readFileSync(path.join(root,'static/app.js'),'utf8'),personal=app.slice(app.indexOf('function personalFields('),app.indexOf('function syncPersonalSnapshots(')),detail=app.slice(app.indexOf('function renderDetail(e){'),app.indexOf('async function openDetail('));
 w.eval(`let authenticated=true,authEpoch=1,detailId='';const records=new Map([[fixture.id,fixture],[companion.id,companion]]);const pointReads=[];async function api(request){const id=request.startsWith('event/')?decodeURIComponent(request.slice(6)):null;if(!records.has(id))throw Error('Unexpected synthetic API request');pointReads.push(id);return JSON.parse(JSON.stringify(records.get(id)))}function mountFeedback(){};${scripts}\n${personal}\n${detail}\nwindow.probe={card,renderDetail,cardSummary,coverageCard,pointReads};`);
 const $=s=>w.document.querySelector(s);$('#event-list').innerHTML=w.probe.card(fixture);w.probe.renderDetail(fixture);
 w.RadarEventWorkflows.toggle(fixture.id);w.RadarEventWorkflows.toggle('comparison-control');w.RadarEventWorkflows.init();assert.equal($('#compare-open').disabled,false);$('#compare-open').click();
 try{for(let i=0;i<100&&!$('#compare-dialog').open;i++)await new Promise(resolve=>setTimeout(resolve,5));assert.equal($('#compare-dialog').open,true);assert.equal(w.document.querySelectorAll('.compare-item').length,2);assert.equal(w.probe.pointReads.length,2)}catch(error){w.close();throw error}
 return {w,$,close(){assert.deepEqual(errors,[]);w.close()}};
}
const fixture={id:'stable',title:'代码 <b data-fixture="yes">课程</b>',summary:'C++ <vector> 与 Rust Vec<T> 实践',url:'https://events.example.test/a?keep=1',start_at:'2026-10-05T10:00:00+08:00',end_at:'2026-10-05T12:00:00+08:00',status:'scheduled',cost_text:'25元',organizer:'机构 <em>原文</em>',details:{organizer_role:'organizer'},sources:[],topics:[]};
for(const summary of ['讨论如何管理时间：用番茄钟完成机器人原型。','预计等候时间：10分钟，之后开始体验。','本次讲题《时间：从哲学到编程》。','如何节约时间: 先建立自动化流程。','时间：一种可编程的资源。','普通摘要 时间：2026年10月5日 地点：深圳','C++ <vector> 与 Rust Vec<T> 实践；比较 a < b & c > d','学习 <b> 标签的文本表示']){
 test('card and detail preserve complete prose: '+summary,async()=>{const r=await ready({...fixture,summary});try{
  assert.equal(r.$('.card-summary').textContent,summary);assert.equal(r.$('.detail-summary').textContent,summary);
  assert.equal(r.$('.title-button').textContent,fixture.title);assert.equal(r.$('#detail-title').textContent,fixture.title);
  assert.equal(r.$('.compare-item h3').textContent,fixture.title);assert.equal(r.w.document.querySelector('[data-fixture]'),null);
  assert.equal(r.$('vector'),null);assert.equal(r.$('#event-list em, #detail em, #compare-dialog em'),null);
 }finally{r.close()}});
}
test('known schedule text is retained because flattened text cannot prove a metadata boundary',async()=>{
 const summary='普通摘要 时间：2026年10月5日 地点：深圳',r=await ready({...fixture,summary,details:{time_label:'2026年10月5日'}});
 try{assert.equal(r.w.probe.cardSummary({...fixture,summary}),summary);assert.equal(r.w.probe.cardSummary({...fixture,summary:fixture.title}),'');assert.match(r.$('.detail-meta').textContent,/2026/)}finally{r.close()}
});
for(const [part,valid] of [['',true],[':0',true],[':1',true],[':443',true],[':65535',true],[':65536',false],[':99999',false],[':bad',false],[':-1',false],[':1.5',false]]){
 test('legacy URL actions agree at port '+(part||'default'),async()=>{
  const url='https://events.example.test'+part+'/a?keep=1',name='来源 <strong data-fixture="yes">原文</strong>',r=await ready({...fixture,url,sources:[{name,url}],details:{evidence_url:url,images:[url]}});
  try{
   const original=r.$('.detail-actions .primary');assert.ok(original);
   assert.equal(original.tagName,valid?'A':'SPAN');assert.equal(original.getAttribute('aria-disabled'),valid?null:'true');
   assert.equal(!!r.$('.compare-item a'),valid);assert.equal(!!r.w.RadarEventWorkflows.safeOriginal(url),valid);
   if(valid)assert.equal(original.href,new URL(url).href);else{assert.equal(original.textContent,'原文链接不可用');assert.equal(r.w.RadarEventWorkflows.shareText({...fixture,url}).includes(url),false)}
   assert.ok(r.$('#detail-body > div.detail-source').textContent.includes(name));
   assert.equal(r.w.document.querySelectorAll('a[href="#"]').length,0);assert.equal(r.w.document.querySelector('[data-fixture]'),null);
   const box=r.w.document.createElement('div');box.innerHTML=r.w.probe.coverageCard({id:'source',name,url,status:'ok',coverage:{}});
   assert.equal(!!box.querySelector('h3 a'),valid);assert.ok(box.textContent.includes(name));
   if(!valid)assert.ok(box.querySelector('h3 [aria-disabled="true"]'));
  }finally{r.close()}
 });
}
test('empty, relative, credentials and non-HTTP links stay unavailable',async()=>{const r=await ready(fixture);try{
 for(const url of ['', '/a', 'javascript:harmless','data:text/plain,harmless','ftp://events.example.test/a','https://user:pass@events.example.test/a'])assert.equal(r.w.RadarUI.safeUrl(url),'#');
}finally{r.close()}});
