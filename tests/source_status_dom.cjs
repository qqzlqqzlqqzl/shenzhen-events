const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {JSDOM} = require('jsdom');

function card(coverage){
  const context=vm.createContext({esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;'),RadarUI:{safeUrl:x=>x},states:{ok:'读取完成'},timeText:x=>x??''});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/render.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/status.js'),'utf8'),context);
  return new JSDOM(context.coverageCard({id:'example',name:'示例',url:'https://example.org',status:'ok',coverage})).window.document;
}
test('online inventory explains why zero Shenzhen candidates can still admit events',()=>{
  const doc=card({version:1,visible:170,extracted:170,unique:170,shenzhen_candidates:0,online_candidates:170,admitted:170,stored_events:164});
  assert.deepEqual([...doc.querySelectorAll('dd')].map(x=>x.textContent),['170','170','170','0','170','170','164']);
  assert.match(doc.body.textContent,/线上\/混合候选/);
  assert.match(doc.body.textContent,/不要求在深圳举办/);
  assert.match(doc.body.textContent,/合并为同一活动/);
});
test('legacy offline coverage does not invent an online candidate count',()=>{
  const doc=card({version:1,visible:22,extracted:22,unique:22,shenzhen_candidates:6,admitted:6,stored_events:6});
  assert.equal(doc.querySelectorAll('dd').length,6);
  assert.doesNotMatch(doc.body.textContent,/线上\/混合候选/);
});
