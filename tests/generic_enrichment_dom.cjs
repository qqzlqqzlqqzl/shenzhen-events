const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
test('compare hides unknown fees and labels publisher without HTML injection',()=>{
 const root=path.join(__dirname,'..'),dom=new JSDOM(fs.readFileSync(path.join(root,'static/index.html'),'utf8'),{url:'https://fixture.test/events/',runScripts:'outside-only'}),w=dom.window;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
 w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const scripts=['render.js','event-workflows.js'].map(f=>fs.readFileSync(path.join(root,'static',f),'utf8')).join('\n;\n');
 w.eval(`let authenticated=true,authEpoch=1;const records=new Map([['a',{id:'a',title:'未知费用',cost_text:'费用未注明',organizer:'发布账号',details:{organizer_role:'publisher'}}],['b',{id:'b',title:'付费活动',cost_text:'199元',organizer:'<主办>',details:{organizer_role:'organizer'}}]]);const RadarUI={fullTime:()=> '时间待确认'};function toast(){};${scripts}\n;RadarEventWorkflows.toggle('a');RadarEventWorkflows.toggle('b');RadarEventWorkflows.init();`);
 w.document.querySelector('#compare-open').click();
 const rows=w.document.querySelectorAll('.compare-item');
 assert.equal(rows.length,2);assert.match(rows[0].textContent,/发布方：发布账号/);
 assert.doesNotMatch(rows[0].textContent,/费用：|主办：/);
 assert.match(rows[1].textContent,/费用：199元/);assert.match(rows[1].textContent,/主办：<主办>/);
 assert.equal(rows[1].querySelector('主办'),null);dom.window.close();
});
