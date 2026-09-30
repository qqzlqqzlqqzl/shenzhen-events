"""Public HTTPS acceptance for issues #10-#13. Read-only except temporary favorite-free signed session."""
import os,json,time,hmac,hashlib,base64,importlib.util
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts/calendar-review/public';ART.mkdir(parents=True,exist_ok=True)
BASE='https://106.53.40.6'
PROD=Path('/home/ubuntu/shenzhen-events')
def session_token():
    cfg=json.loads((PROD/'.private/settings.json').read_text())
    body=base64.urlsafe_b64encode(json.dumps({'id':1,'name':'public-calendar-review','exp':int(time.time())+900},separators=(',',':')).encode()).decode().rstrip('=')
    sig=hmac.new(bytes.fromhex(cfg['session_secret']),body.encode(),hashlib.sha256).hexdigest()
    return body+'.'+sig
spec=importlib.util.spec_from_file_location('accept',ROOT/'tests/browser_acceptance.py')
accept=importlib.util.module_from_spec(spec);spec.loader.exec_module(accept)
report={'checks':{},'errors':[],'tested_base':BASE,'candidate':'a409285aff8039997d81ceb52ffc699c53d18e3c'}
pw=sync_playwright().start()
browser=pw.chromium.launch(executable_path=accept.browser_path(),headless=True,args=['--no-sandbox','--no-proxy-server','--disable-dev-shm-usage'],env=dict(os.environ))
ctx=browser.new_context(viewport={'width':1440,'height':1050},locale='zh-CN',timezone_id='Asia/Shanghai')
ctx.add_cookies([{'name':'sz_events_session','value':session_token(),'domain':'106.53.40.6','path':'/events','httpOnly':True,'secure':True,'sameSite':'Lax'}])
page=ctx.new_page();page.set_default_timeout(10000);page.on('pageerror',lambda e:report['errors'].append(str(e)))
page.on('console',lambda m:report['errors'].append('console:'+m.text) if m.type=='error' and '401' not in m.text else None)
def check(name,fn):
    try:fn();report['checks'][name]=True;print('PASS',name,flush=True)
    except Exception as e:
        report['checks'][name]=False;report.setdefault('failures',{})[name]=str(e)[:1200];print('FAIL',name,str(e)[:240],flush=True)
        page.screenshot(path=str(ART/(name+'-failed.png')),full_page=True)
def ok(value,message='assertion failed'):
    if not value:raise AssertionError(message)
def ready(query='?view=weekend'):
    page.goto(BASE+'/events/'+query,wait_until='domcontentloaded')
    page.locator('#workspace').wait_for(state='visible')
    if page.locator('#event-list').is_visible():expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
def weekend_default():
    ready('?view=weekend')
    text=page.locator('#event-list').inner_text()
    for old in ['深圳博物馆新展《宠爱--猫猫狗狗的世界》','深圳自然博物馆参观攻略+实拍','《在一起，再出发——2026珠宝首饰设计展·深圳》']:
        ok(old not in text,'long-running item leaked into default weekend: '+old)
    ok(page.locator('#hide-long').is_checked())
    count=int(page.locator('#result-count').inner_text().split()[0])
    all_count=ctx.request.get(BASE+'/events/api/events?period=weekend&hide_long=false&limit=500').json()['total']
    ok(0<count<all_count,f'clean={count} all={all_count}')
    report['weekend_default']=count;report['weekend_with_long']=all_count
    page.screenshot(path=str(ART/'weekend-default.png'),full_page=True)
check('weekend_default_removes_old_long_ranges',weekend_default)
def weekend_show_long():
    ready('?view=weekend');page.locator('#hide-long').uncheck();expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    card=page.locator('.event-card',has_text='深圳博物馆新展《宠爱--猫猫狗狗的世界》')
    card.wait_for();text=card.inner_text()
    ok('本周末仍开放' in text,text);ok('5月' not in text,text);ok('show_long=true' in page.url)
    page.reload(wait_until='domcontentloaded');expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    ok(not page.locator('#hide-long').is_checked())
check('weekend_long_item_uses_effective_weekend_date',weekend_show_long)
def time_sort():
    ready('?view=all')
    asc=ctx.request.get(BASE+'/events/api/events?period=upcoming&hide_long=true&sort=asc&limit=500').json()['items']
    desc=ctx.request.get(BASE+'/events/api/events?period=upcoming&hide_long=true&sort=desc&limit=500').json()['items']
    av=[x.get('display_at') or x.get('start_at') for x in asc if x.get('display_at') or x.get('start_at')]
    dv=[x.get('display_at') or x.get('start_at') for x in desc if x.get('display_at') or x.get('start_at')]
    ok(av==sorted(av),str(av[:5]));ok(dv==sorted(dv,reverse=True),str(dv[:5]))
    page.locator('#sort').select_option('desc');expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    ok('sort=desc' in page.url);page.reload(wait_until='domcontentloaded');expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    ok(page.locator('#sort').input_value()=='desc')
check('server_side_time_sort_and_url_roundtrip',time_sort)
def calendar_default():
    ready('?view=calendar')
    page.locator('.fc-view-harness').wait_for();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    ok(page.locator('#calendar-long').is_hidden())
    grid=page.locator('#calendar').inner_text()
    ok('深圳博物馆新展《宠爱--猫猫狗狗的世界》' not in grid)
    ends=page.evaluate("calendar.getEvents().map(e=>e.end)")
    ok(page.evaluate('calendar.getEvents().every(e=>!e.end||e.end-e.start<14*86400000)'),str(ends[:8]))
    ok('短期跨日活动连续显示' in page.locator('.calendar-guide').inner_text())
    page.screenshot(path=str(ART/'calendar-default.png'),full_page=True)
check('month_calendar_has_no_spanning_long_bars',calendar_default)
def calendar_show_long():
    ready('?view=calendar');page.locator('#hide-long').uncheck();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    page.locator('#calendar-long').wait_for(state='visible')
    panel=page.locator('#calendar-long').inner_text();grid=page.locator('#calendar').inner_text()
    ok('深圳博物馆新展《宠爱--猫猫狗狗的世界》' in panel)
    ok('深圳博物馆新展《宠爱--猫猫狗狗的世界》' not in grid)
    ok('不再铺成整月长条' in panel)
    page.screenshot(path=str(ART/'calendar-with-long-panel.png'),full_page=True)
check('month_calendar_separates_long_running_panel',calendar_show_long)
def mobile():
    page.set_viewport_size({'width':390,'height':844});ready('?view=calendar')
    page.locator('.fc-list').wait_for();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    ok(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.screenshot(path=str(ART/'calendar-mobile.png'),full_page=True)
check('mobile_calendar_no_overflow',mobile)
def routes_and_stats():
    routes={p:ctx.request.get(BASE+p,max_redirects=0).status for p in ['/','/inbox/','/newapi','/blog','/events/']}
    ok(routes=={'/':200,'/inbox/':200,'/newapi':302,'/blog':302,'/events/':200},str(routes))
    stats=ctx.request.get(BASE+'/events/api/stats').json()
    ok(stats['weekend']==report['weekend_default'],str(stats))
    ok(stats.get('long_running',0)>0,str(stats))
    report['routes']=routes;report['stats']=stats
check('baseline_routes_and_weekend_counter',routes_and_stats)
report['page_errors_empty']=not report['errors']
(ART/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
browser.close();pw.stop()
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
raise SystemExit(0 if all(report['checks'].values()) and not report['errors'] else 1)

