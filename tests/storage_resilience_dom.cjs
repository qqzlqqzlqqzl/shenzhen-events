/* Exact-source, offline DOM storage audit. All account names/storage/API data are synthetic. */
'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(process.env.RADAR_STORAGE_ROOT||path.join(__dirname,'../static'));
const files=['vendor/fullcalendar.js','ui-state.js','render.js','planner.js','event-workflows.js','status.js','app.js'];
const source=files.map(f=>fs.readFileSync(path.join(root,f),'utf8')).join('\n;\n');
const tick=()=>new Promise(r=>setTimeout(r,10));
const fk=user=>'radar.filters.v1:'+user,sk=user=>'radar.saved.v1:'+user;
const pref=query=>JSON.stringify({version:1,query});
const named=(name,query)=>({name,query});
const clone=x=>JSON.parse(JSON.stringify(x));


async function ready(options={}) {
 const errors=[],calls=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM(fs.readFileSync(path.join(root,'index.html'),'utf8'),{url:'https://fixture.test/events/'+(options.query??''),runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc});
 const w=dom.window,$=s=>w.document.querySelector(s),data=new Map(Object.entries(options.initial||{})),ops=[];
 const mode={getter:false,get:false,set:false,...options.mode};
 const storage={getItem(k){ops.push({op:'get',key:k});if(mode.get)throw new w.DOMException('Synthetic read blocked','SecurityError');return data.get(k)??null},setItem(k,v){ops.push({op:'set',key:k,value:String(v)});if(mode.set)throw new w.DOMException('Synthetic quota exceeded','QuotaExceededError');data.set(k,String(v))},removeItem(){throw new Error('No removeItem permitted in audit')},clear(){throw new Error('No clear permitted in audit')}};
 Object.defineProperty(w,'localStorage',{configurable:true,get(){if(mode.getter)throw new w.DOMException('Synthetic localStorage unavailable','SecurityError');return storage}});
 Object.defineProperty(w,'sessionStorage',{configurable:true,get(){throw new w.DOMException('Synthetic sessionStorage unavailable','SecurityError')}});
 w.matchMedia=()=>({matches:true,addEventListener(){}});w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const model={username:options.username||'alice',rows:[{id:'one',title:'Synthetic visible row',start_at:'2026-10-05T10:00:00+08:00',end_at:'2026-10-05T12:00:00+08:00',status:'scheduled',favorite:false,feedback:'',feedback_tags:[],revision:0,event_type:'MusicEvent',topics:['文化艺术'],attendance:'offline',district:'南山',sources:[],url:'https://fixture.test/public'}]};
 w.fetch=async(url,opts={})=>{const u=new URL(url,w.location.href);assert.equal(u.origin,'https://fixture.test');assert.ok(u.pathname.startsWith('/events/api/'));const route=u.pathname.split('/events/api/')[1];calls.push({route,url:u,opts});let payload={};
  if(['session','login'].includes(route))payload={username:model.username};
  else if(route==='stats')payload={recommended:1,upcoming:1,weekend:1,last_updated:'2026-10-02T00:00:00Z',districts:['南山','福田'],event_types:[{value:'MusicEvent',label:'音乐'},{value:'ConferenceEvent',label:'会议'}],topics:[{value:'文化艺术',label:'文化艺术'},{value:'硬件创客',label:'硬件创客'}]};
  else if(route==='events')payload={items:model.rows,total:1,has_more:false,facets:{},excluded_long:{total:0,items:[]}};
  else if(route.startsWith('event/'))payload=model.rows[0];else if(route.startsWith('viewed/'))payload={viewed_at:'2026-10-02T00:00:00Z'};
  return {ok:true,status:200,json:async()=>clone(payload)};
 };
 w.eval(source+'\n;window.probe={enter,showLogin,rememberFilters,restoreSavedFilters,readURL,load,get authenticated(){return authenticated},get appliedFilterQuery(){return appliedFilterQuery}};');
 await tick();await tick();
 return {w,$,data,ops,mode,model,calls,errors,events(){return calls.filter(x=>x.route==='events')},change(s,v){const el=$(s);if(el.type==='checkbox')el.checked=v;else el.value=v;el.dispatchEvent(new w.Event('change',{bubbles:true}))},search(value){$('#search').value=value;$('#search').dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}))},save(label){$('#saved-view-name').value=label;$('#save-view-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}))},async logout(){ $('#logout').click();await tick()},async login(user){model.username=user;$('#username').value=user;$('#password').value='synthetic-only';$('#login-form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await tick();await tick()},close(){w.close();assert.deepEqual(errors,[])}};
}
function live(r){assert.equal(r.w.probe.authenticated,true);assert.equal(r.$('#workspace').hidden,false);assert.equal(r.$('.title-button').textContent,'Synthetic visible row');assert.equal(r.$('#event-list').getAttribute('aria-busy'),'false');}

for(const mode of [{getter:true},{get:true,set:true},{set:true}])test('PASS: unavailable storage or quota does not blank UI, lose active mobile choice, or claim named-save success '+JSON.stringify(mode),async()=>{
 const old=pref('q=previous'),saved=JSON.stringify([named('Preserved','q=previous')]);const r=await ready({query:'?q=current',mode,initial:{[fk('alice')]:old,[sk('alice')]:saved}});try{live(r);const baseline=r.events().length,url=r.w.location.href,ops=r.ops.length;
  r.$('#open-filters').click();r.change('#attendance','online');r.$('#search').value='cancelled draft';r.$('#search').dispatchEvent(new r.w.Event('input',{bubbles:true}));r.$('#cancel-filter-draft').click();await tick();assert.equal(r.events().length,baseline);assert.equal(r.w.location.href,url);assert.equal(r.$('#search').value,'current');assert.equal(r.$('#attendance').value,'all');assert.equal(r.ops.length,ops);
  r.$('#open-filters').click();r.change('#attendance','online');r.$('#apply-filter-draft').click();await tick();live(r);assert.equal(r.events().at(-1).url.searchParams.get('attendance'),'online');assert.equal(r.$('#attendance').value,'online');assert.equal(new URL(r.w.location.href).searchParams.get('attendance'),'online');
  r.save('Attempt');assert.match(r.$('#toast').textContent,/未允许保存/);assert.equal(r.$('#saved-view-name').value,'Attempt');assert.equal(r.data.get(sk('alice')),saved);assert.equal(r.data.get(fk('alice')),old);

 }finally{r.close()}
});

test('PASS: quota failure preserves named-view rename/delete/undo model and retry works',async()=>{
 const original=JSON.stringify([named('First','q=first'),named('Second','q=second')]);const r=await ready({initial:{[sk('alice')]:original}});try{r.$('#saved-view-choice').value='0';r.mode.set=true;r.$('#saved-view-name').value='Renamed';r.$('#rename-saved-view').click();assert.equal(r.data.get(sk('alice')),original);assert.equal(r.$('#saved-view-choice option[value="0"]').textContent,'First');r.$('#delete-saved-view').click();assert.equal(r.data.get(sk('alice')),original);assert.equal(r.$('#undo-saved-view').hidden,true);
  r.mode.set=false;r.$('#delete-saved-view').click();const deleted=r.data.get(sk('alice'));assert.equal(JSON.parse(deleted).length,1);r.mode.set=true;r.$('#undo-saved-view').click();assert.equal(r.data.get(sk('alice')),deleted);assert.equal(r.$('#undo-saved-view').hidden,false);assert.match(r.$('#toast').textContent,/未允许保存/);r.mode.set=false;r.$('#undo-saved-view').click();assert.equal(r.data.get(sk('alice')),original);assert.equal(r.$('#undo-saved-view').hidden,true);
 }finally{r.close()}
});

for(const raw of ['{broken', '{"items":[{"name":"old","query":"q=old"}]}','[null,5,{"name":"","query":"q=old"},{"name":"valid","query":"q=keep"}]'])test('PASS: corrupt/wrong-shaped named JSON never blanks page and is left untouched merely by loading '+raw.slice(0,16),async()=>{
 const r=await ready({initial:{[sk('alice')]:raw}});try{live(r);assert.equal(r.data.get(sk('alice')),raw);assert.equal(r.$('#saved-view-choice').options.length,raw.startsWith('[null')?2:1);if(raw.startsWith('[null')){r.$('#saved-view-choice').value='0';r.$('#apply-saved-view').click();await tick();assert.equal(r.$('#search').value,'keep');live(r)}}finally{r.close()}
});

for(const raw of ['{broken',JSON.stringify({version:2,query:'q=future-owner-choice'}),JSON.stringify({version:1,query:['q=wrong-shape']})])test('FIX: rejected remembered-filter bytes survive entry until explicit choice '+raw.slice(0,25),async()=>{
 const r=await ready({initial:{[fk('alice')]:raw}});try{live(r);assert.equal(r.$('#search').value,'');assert.equal(r.data.get(fk('alice')),raw);}finally{r.close()}
});

test('PASS: invalid dates in valid filter JSON remain raw and fail closed until explicit recovery',async()=>{
 const raw=pref('q=keep&attendance=online&from=garbage&until=garbage');const r=await ready({initial:{[fk('alice')]:raw}});try{assert.equal(r.w.probe.authenticated,true);assert.equal(r.events().length,0);assert.match(r.$('#notice').textContent,/日期/);assert.equal(r.data.get(fk('alice')),raw);r.$('[data-action="clear-invalid-dates"]').click();await tick();live(r);assert.equal(r.$('#search').value,'keep');assert.equal(r.events().at(-1).url.searchParams.get('attendance'),'online');assert.equal(new URLSearchParams(JSON.parse(r.data.get(fk('alice'))).query).has('from'),false)}finally{r.close()}
});

test('FIX: initial transient filter read failure preserves valid bytes when writes still work',async()=>{
 const old=pref('q=keep&attendance=online');const r=await ready({initial:{[fk('alice')]:old},mode:{get:true}});try{live(r);assert.equal(r.data.get(fk('alice')),old);r.mode.get=false;r.w.probe.restoreSavedFilters();assert.equal(r.$('#search').value,'');}finally{r.close()}
});

test('FIX: unreadable named views become empty in memory and later new save reconciles old list',async()=>{
 const old=JSON.stringify([named('Preserve existing','q=keep')]);const r=await ready({initial:{[sk('alice')]:old},mode:{getter:true}});try{live(r);assert.match(r.$('#saved-view-count').textContent,/0 \/ 12/);assert.equal(r.data.get(sk('alice')),old);r.mode.getter=false;r.save('New');assert.deepEqual(JSON.parse(r.data.get(sk('alice'))),[named('Preserve existing','q=keep'),named('New','')]);}finally{r.close()}
});

test('FIX: switching owner restores the verified new owner preferences',async()=>{
 const alice=pref('q=alice-choice&attendance=online'),bob=pref('q=bob-choice&attendance=offline');const r=await ready({initial:{[fk('alice')]:alice,[fk('bob')]:bob}});try{live(r);assert.equal(r.$('#search').value,'alice-choice');await r.logout();await r.login('bob');live(r);assert.equal(r.$('#search').value,'bob-choice');assert.equal(r.data.get(fk('bob')),bob);assert.equal(r.data.get(fk('alice')),alice);}finally{r.close()}
});

test('FIX: owner switch clears stale saved-view editor and Undo',async()=>{
 const a=JSON.stringify([named('Alice first','q=a1'),named('Alice second','q=a2')]),b=JSON.stringify([named('Bob first','q=b1')]);const r=await ready({initial:{[sk('alice')]:a,[sk('bob')]:b}});try{r.$('#saved-view-choice').value='0';r.$('#saved-view-choice').dispatchEvent(new r.w.Event('change'));r.$('#delete-saved-view').click();assert.equal(r.$('#undo-saved-view').hidden,false);await r.logout();await r.login('bob');assert.equal(r.$('#saved-view-name').value,'');assert.equal(r.$('#saved-view-choice').value,'');assert.equal(r.$('#saved-view-choice option[value="0"]').textContent,'Bob first');assert.equal(r.$('#undo-saved-view').hidden,true);r.$('#undo-saved-view').click();assert.equal(r.data.get(sk('bob')),b);}finally{r.close()}
});

test('PASS: blocked storage during mobile draft, session expiry, same-owner login cancels draft without persisting it',async()=>{
 const old=pref('q=before&attendance=offline');const r=await ready({initial:{[fk('alice')]:old}});try{r.$('#open-filters').click();r.$('#search').value='cancel me';r.change('#attendance','online');r.mode.getter=true;r.w.probe.showLogin('Synthetic expired session');assert.equal(r.$('#filter-dialog').hidden,true);assert.equal(r.$('#search').value,'before');assert.equal(r.data.get(fk('alice')),old);await r.login('alice');live(r);assert.equal(r.$('#search').value,'before');assert.equal(r.$('#attendance').value,'offline');assert.equal(r.data.get(fk('alice')),old)}finally{r.close()}
});

test('PASS: same-owner successful login keeps valid saved bytes and discarded draft out of filters',async()=>{
 const old=pref('q=keep&attendance=offline'),namedRaw=JSON.stringify([named('Kept','q=keep')]);const r=await ready({initial:{[fk('alice')]:old,[sk('alice')]:namedRaw}});try{r.$('#open-filters').click();r.change('#attendance','online');await r.logout();await r.login('alice');live(r);assert.equal(r.data.get(fk('alice')),old);assert.equal(r.data.get(sk('alice')),namedRaw);assert.equal(r.$('#attendance').value,'offline')}finally{r.close()}
});

test('FIX: named Undo storage read failure reports failure and retains retry',async()=>{
 const old=JSON.stringify([named('First','q=first')]);const r=await ready({initial:{[sk('alice')]:old}});try{r.$('#saved-view-choice').value='0';r.$('#delete-saved-view').click();const removed=r.data.get(sk('alice')),before=r.$('#toast').textContent;r.mode.get=true;r.$('#undo-saved-view').click();assert.equal(r.data.get(sk('alice')),removed);assert.notEqual(r.$('#toast').textContent,before);assert.match(r.$('#toast').textContent,/未允许保存/);assert.equal(r.$('#undo-saved-view').hidden,false);r.mode.get=false;r.$('#undo-saved-view').click();assert.equal(r.data.get(sk('alice')),old);}finally{r.close()}
});

test('FIX: mobile back-forward cache restoration preserves a valid same-owner saved-view Undo',async()=>{
 const old=JSON.stringify([named('First','q=first')]);const r=await ready({initial:{[sk('alice')]:old}});try{r.$('#saved-view-choice').value='0';r.$('#delete-saved-view').click();assert.equal(r.$('#undo-saved-view').hidden,false);const removed=r.data.get(sk('alice'));r.w.dispatchEvent(new r.w.PageTransitionEvent('pagehide',{persisted:true}));assert.equal(r.w.probe.authenticated,false);r.w.dispatchEvent(new r.w.PageTransitionEvent('pageshow',{persisted:true}));await tick();await tick();live(r);assert.equal(r.$('#undo-saved-view').hidden,false);r.$('#undo-saved-view').click();assert.equal(r.data.get(sk('alice')),old);assert.equal(r.$('#undo-saved-view').hidden,true);}finally{r.close()}
});

test('PASS: storage-event update from a different owner does not replace current owner named views',async()=>{
 const a=JSON.stringify([named('Alice first','q=a')]),b=JSON.stringify([named('Bob first','q=b')]);const r=await ready({initial:{[sk('alice')]:a,[sk('bob')]:b}});try{r.w.dispatchEvent(new r.w.StorageEvent('storage',{key:sk('bob'),newValue:'[]'}));assert.equal(r.$('#saved-view-choice option[value="0"]').textContent,'Alice first');assert.equal(r.data.get(sk('alice')),a);assert.equal(r.data.get(sk('bob')),b)}finally{r.close()}
});

test('PASS: same-owner storage event invalidates deleted-view Undo and corrupt event payload cannot blank page',async()=>{
 const a=JSON.stringify([named('First','q=a')]);const r=await ready({initial:{[sk('alice')]:a}});try{r.$('#saved-view-choice').value='0';r.$('#delete-saved-view').click();assert.equal(r.$('#undo-saved-view').hidden,false);r.w.dispatchEvent(new r.w.StorageEvent('storage',{key:sk('alice'),newValue:'{broken'}));assert.equal(r.$('#undo-saved-view').hidden,true);assert.equal(r.$('#saved-view-choice').options.length,1);live(r)}finally{r.close()}
});

test('explicit apply can replace readable rejected filters; automatic navigation cannot',async()=>{
 const raw=JSON.stringify({version:2,query:'q=future'}),r=await ready({initial:{[fk('alice')]:raw}});try{
  r.$('[data-view="all"]').click();await tick();assert.equal(r.data.get(fk('alice')),raw);
  r.search('chosen');await tick();assert.equal(JSON.parse(r.data.get(fk('alice'))).version,1);assert.equal(new URLSearchParams(JSON.parse(r.data.get(fk('alice'))).query).get('q'),'chosen');
 }finally{r.close()}
});

test('one transient restore failure stays protected after reads recover until an explicit choice',async()=>{
 const old=pref('q=keep'),r=await ready({mode:{get:true},initial:{[fk('alice')]:old}});try{
  r.mode.get=false;r.w.probe.rememberFilters();assert.equal(r.data.get(fk('alice')),old);
  r.$('[data-view="all"]').click();await tick();assert.equal(r.data.get(fk('alice')),old);
  r.search('chosen');await tick();assert.equal(new URLSearchParams(JSON.parse(r.data.get(fk('alice'))).query).get('q'),'chosen');
 }finally{r.close()}
});

test('an explicit choice cannot overwrite still unreadable filter bytes',async()=>{
 const old=pref('q=keep'),r=await ready({mode:{get:true},initial:{[fk('alice')]:old}});try{r.search('chosen');await tick();live(r);assert.equal(r.$('#search').value,'chosen');assert.equal(r.data.get(fk('alice')),old)}finally{r.close()}
});

test('recovery checks duplicates and the twelve-view limit against the existing list',async()=>{
 for(const entries of [[named('Existing','q=keep')],Array.from({length:12},(_,i)=>named('View '+i,'q='+i))]){
  const raw=JSON.stringify(entries),r=await ready({mode:{get:true},initial:{[sk('alice')]:raw}});try{
   r.mode.get=false;r.save(entries.length===1?'existing':'Extra');assert.equal(r.data.get(sk('alice')),raw);assert.match(r.$('#toast').textContent,entries.length===1?/同名/:/最多保存12/);assert.notEqual(r.$('#saved-view-name').value,'');
  }finally{r.close()}
 }
});

test('corrupt named bytes remain unchanged when a new save is attempted',async()=>{
 const raw='{broken',r=await ready({initial:{[sk('alice')]:raw}});try{r.save('New');assert.equal(r.data.get(sk('alice')),raw);assert.match(r.$('#toast').textContent,/未允许保存/)}finally{r.close()}
});

test('supplied deep links survive a conditional same-DOM verified owner change',async()=>{
 const bob=pref('q=bob'),r=await ready({query:'?q=supplied',initial:{[fk('bob')]:bob}});try{await r.logout();await r.login('bob');live(r);assert.equal(r.$('#search').value,'supplied');assert.equal(new URL(r.w.location.href).searchParams.get('q'),'supplied')}finally{r.close()}
});

test('a separately supplied URL after restoration survives owner change',async()=>{
 const r=await ready({initial:{[fk('alice')]:pref('q=alice'),[fk('bob')]:pref('q=bob')}});try{
  r.w.history.replaceState({},'','/events/?q=supplied-later');await r.logout();await r.login('bob');assert.equal(r.$('#search').value,'supplied-later');
 }finally{r.close()}
});

test('same-owner re-entry visibly expires Undo when the stored list has changed',async()=>{
 const r=await ready({initial:{[sk('alice')]:JSON.stringify([named('First','q=first')])}});try{
  r.$('#saved-view-choice').value='0';r.$('#delete-saved-view').click();r.data.set(sk('alice'),JSON.stringify([named('Changed','q=changed')]));await r.w.probe.enter({username:'alice'});assert.equal(r.$('#undo-saved-view').hidden,true);assert.equal(r.$('#saved-view-choice option[value="0"]').textContent,'Changed');
 }finally{r.close()}
});

test('Back to an earlier app-generated query cannot overwrite a verified new owner preference',async()=>{
 const alice=pref('q=alice-earlier&attendance=online'),bob=pref('q=bob-choice&attendance=offline');
 const r=await ready({initial:{[fk('alice')]:alice,[fk('bob')]:bob}});try{
  r.search('alice-later');await tick();r.w.history.back();await tick();await tick();assert.equal(r.$('#search').value,'alice-earlier');
  await r.logout();await r.login('bob');live(r);assert.equal(r.$('#search').value,'bob-choice');assert.equal(r.$('#attendance').value,'offline');assert.equal(r.data.get(fk('bob')),bob);
 }finally{r.close()}
});

test('Back while signed out also retains app-generated query provenance for a verified owner change',async()=>{
 const bob=pref('q=bob-choice'),r=await ready({initial:{[fk('alice')]:pref('q=alice-earlier'),[fk('bob')]:bob}});try{
  r.search('alice-later');await tick();await r.logout();r.w.history.back();await tick();await r.login('bob');assert.equal(r.$('#search').value,'bob-choice');assert.equal(r.data.get(fk('bob')),bob);
 }finally{r.close()}
});

test('Back to an external deep link keeps that supplied query through a verified owner change',async()=>{
 const r=await ready({query:'?q=external-link&attendance=online',initial:{[fk('bob')]:pref('q=bob-choice&attendance=offline')}});try{
  r.search('alice-owned');await tick();r.w.history.back();await tick();await tick();assert.equal(r.$('#search').value,'external-link');
  await r.logout();await r.login('bob');live(r);assert.equal(r.$('#search').value,'external-link');assert.equal(r.$('#attendance').value,'online');assert.equal(new URL(r.w.location.href).searchParams.get('q'),'external-link');
 }finally{r.close()}
});

test('same-owner Back navigation preserves the earlier app-generated query',async()=>{
 const r=await ready({initial:{[fk('alice')]:pref('q=alice-earlier')}});try{
  r.search('alice-later');await tick();r.w.history.back();await tick();await tick();await r.logout();await r.login('alice');live(r);assert.equal(r.$('#search').value,'alice-earlier');
 }finally{r.close()}
});
