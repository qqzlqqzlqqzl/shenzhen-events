/* Pure helpers behind list/card grouping; NOT a substitute for browser acceptance.
 * NODE_PATH=/tmp/radar-dom-check/node_modules node --test tests/list_grouping_dom.cjs
 */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
require(path.join(__dirname,'..','static','ui-state.js'));
const U=globalThis.RadarUI;
const at=(start,end=null,all_day=0)=>({start_at:start,end_at:end,all_day});
// Tuesday 2026-11-24 10:00 Asia/Shanghai.
const now=Date.parse('2026-11-24T10:00:00+08:00');

test('relative day buckets follow the Shanghai calendar week', () => {
  const cases=[
    ['2026-11-24T09:00:00+08:00','进行中'],
    ['2026-11-24T19:30:00+08:00','今天'],
    ['2026-11-25T14:00:00+08:00','明天'],
    ['2026-11-27T19:00:00+08:00','本周'],
    ['2026-11-28T10:00:00+08:00','本周末'],
    ['2026-11-29T23:30:00+08:00','本周末'],
    ['2026-11-30T10:00:00+08:00','下周'],
    ['2026-12-06T10:00:00+08:00','下周'],
    ['2026-12-07T00:30:00+08:00','更晚'],
  ];
  for (const [start,label] of cases) assert.equal(U.dayBucket(at(start),now),label,start);
  assert.equal(U.dayBucket({start_at:null},now),'日期待确认');
});

test('weekend bucket on a Saturday keeps Sunday as 明天 and next days as 下周', () => {
  const saturday=Date.parse('2026-11-28T09:00:00+08:00');
  assert.equal(U.dayBucket(at('2026-11-28T20:00:00+08:00'),saturday),'今天');
  assert.equal(U.dayBucket(at('2026-11-29T10:00:00+08:00'),saturday),'明天');
  assert.equal(U.dayBucket(at('2026-11-30T10:00:00+08:00'),saturday),'下周');
});

test('row time is compact under a date heading and keeps multi-day ends', () => {
  assert.equal(U.rowTime(at('2026-11-24T14:30:00+08:00','2026-11-24T18:06:00+08:00')),'14:30–18:06');
  assert.equal(U.rowTime(at('2026-11-25T14:00:00+08:00')),'14:00');
  assert.equal(U.rowTime(at('2026-11-30T10:00:00+08:00','2026-12-02T18:00:00+08:00')),'10:00 至 12/02');
  assert.equal(U.rowTime(at('2026-11-29T00:00:00+08:00','2026-11-30T00:00:00+08:00',1)),'全天');
  // Source ends are exclusive for all-day events.
  assert.equal(U.rowTime(at('2026-12-07T00:00:00+08:00','2026-12-10T00:00:00+08:00',1)),'至 12/09');
  assert.equal(U.rowTime({start_at:''}),'时间待确认');
});
