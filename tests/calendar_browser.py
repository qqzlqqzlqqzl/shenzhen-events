"""Focused browser regression for issues #10-#13. Uses disposable DB only."""
import os,sys,json,time,tempfile,subprocess,importlib.util,shutil,atexit
from pathlib import Path
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1];ART=ROOT/'artifacts/calendar-review';ART.mkdir(parents=True,exist_ok=True)
FIX=Path(tempfile.mkdtemp(prefix='radar-calendar-'));os.environ['RADAR_ROOT']=str(FIX)
(FIX/'static').symlink_to(ROOT/'static',target_is_directory=True)
(FIX/'sources.json').write_text(json.dumps([{'id':'a','name':'测试主办方','url':'https://example.com','priority':10}]))
sys.path.insert(0,str(ROOT))
from radar import core,api
api.initialize_settings();core.init()
now=core.now();day=now.date()
# Match the server's current/upcoming weekend, including Sunday. Keep sorting
# fixtures on weekdays so the expected weekend count is independent of CI's day.
sat=day+timedelta(days=5-day.weekday()) if day.weekday()<5 else day-timedelta(days=day.weekday()-5)
early=now+timedelta(days=2)
while early.weekday()>=5:early+=timedelta(days=1)
late=early+timedelta(days=7)
CALENDAR_QUERY='?view=calendar&month='+early.replace(day=1).date().isoformat()
def put(title,url,start,end,all_day=False):
    core.ingest({'id':'a','priority':10},{'title':title,'url':url,'start_at':start,'end_at':end,'all_day':all_day,'location':'深圳市南山区测试中心','summary':'隔离浏览器测试。','cost_text':'免费'})
put('长期博物馆展','https://example.com/long',(now-timedelta(days=100)).date().isoformat(),(now+timedelta(days=100)).date().isoformat(),True)
put('周末工作坊','https://example.com/weekend',sat.isoformat(),(sat+timedelta(days=2)).isoformat(),True)
put('排序较早','https://example.com/early',early.replace(hour=9).isoformat(),early.replace(hour=11).isoformat())
put('排序较晚','https://example.com/late',late.replace(hour=9).isoformat(),late.replace(hour=11).isoformat())
# A dense date must show every event directly, not hide any behind +N.
for i in range(12):
    put(f'同日普通活动{i+1}',f'https://example.com/same-day-{i+1}',early.replace(hour=8+i).isoformat(),early.replace(hour=9+i).isoformat())
with core.db() as c:
    favorite_id=c.execute("SELECT id FROM events WHERE url='https://example.com/early'").fetchone()[0]
    c.execute('INSERT INTO preferences(event_id,favorite) VALUES(?,1)',(favorite_id,))
sys.path.append('/home/ubuntu/ai-news/runtime/venv/lib/python3.12/site-packages')
from playwright.sync_api import sync_playwright,expect
spec=importlib.util.spec_from_file_location('accept',ROOT/'tests/browser_acceptance.py');accept=importlib.util.module_from_spec(spec);spec.loader.exec_module(accept)
BASE='http://127.0.0.1:18094'
server=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','uvicorn','radar.api:app','--host','127.0.0.1','--port','18094','--no-access-log'],cwd=ROOT,env=dict(os.environ),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
@atexit.register
def cleanup():
    server.terminate()
    try:server.wait(timeout=5)
    except subprocess.TimeoutExpired:server.kill()
    shutil.rmtree(FIX,ignore_errors=True)
from browser_startup import wait_for_api
wait_for_api(server,BASE)
report={'checks':{},'errors':[]}
pw=sync_playwright().start();br=pw.chromium.launch(executable_path=accept.browser_path(),headless=True,args=['--no-sandbox','--no-proxy-server','--disable-dev-shm-usage'],env=dict(os.environ))
ctx=br.new_context(viewport={'width':1440,'height':1050},locale='zh-CN',timezone_id='Asia/Shanghai')
ctx.add_cookies([{'name':'sz_events_session','value':api.sign_session({'id':1,'username':'calendar-review'}),'domain':'127.0.0.1','path':'/events','httpOnly':True,'secure':False,'sameSite':'Lax'}])
page=ctx.new_page();page.set_default_timeout(8000);page.on('pageerror',lambda e:report['errors'].append(str(e)))
def ready(url):
    page.goto(BASE+'/events/'+url,wait_until='domcontentloaded');page.locator('#workspace').wait_for(state='visible')
    if page.locator('#event-list').is_visible():expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
def check(name,fn):
    try:fn();report['checks'][name]=True;print('PASS',name,flush=True)
    except Exception as e:
        report['checks'][name]=False;report.setdefault('failures',{})[name]=str(e)[:1000];print('FAIL',name,str(e)[:220],flush=True)
        page.screenshot(path=str(ART/(name+'-failed.png')),full_page=True)
def ok(v,msg='assertion failed'):
    if not v:raise AssertionError(msg)
def weekend_default():
    ready('?view=weekend')
    text=page.locator('#event-list').inner_text()
    ok('周末工作坊' in text);ok('长期博物馆展' not in text)
    ok(page.locator('#hide-long').is_checked())
    ok(page.locator('#count-weekend').inner_text()=='1',page.locator('#count-weekend').inner_text())
check('weekend_defaults_hide_long_running',weekend_default)

def weekend_show_long():
    ready('?view=weekend');page.locator('#hide-long').uncheck();page.wait_for_timeout(350)
    text=page.locator('#event-list').inner_text();ok('长期博物馆展' in text);ok('本周末仍开放' in text)
    ok('show_long=true' in page.url)
    oldmonth=(now-timedelta(days=100)).strftime('%-m月')
    longcard=page.locator('.event-card',has_text='长期博物馆展')
    ok(oldmonth not in longcard.inner_text(),longcard.inner_text())
    page.reload(wait_until='domcontentloaded');expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    ok(not page.locator('#hide-long').is_checked());ok('长期博物馆展' in page.locator('#event-list').inner_text())
check('weekend_show_long_uses_effective_weekend_date',weekend_show_long)

def sort_control():
    ready('?view=all&q=排序');titles=page.locator('.title-button').all_inner_texts();ok(titles==['排序较早','排序较晚'],str(titles))
    page.locator('#sort').select_option('desc');page.wait_for_timeout(300)
    titles=page.locator('.title-button').all_inner_texts();ok(titles==['排序较晚','排序较早'],str(titles));ok('sort=desc' in page.url)
    page.reload(wait_until='domcontentloaded');expect(page.locator('#event-list')).to_have_attribute('aria-busy','false');ok(page.locator('#sort').input_value()=='desc')
check('time_sort_roundtrip',sort_control)
def calendar_clean():
    ready(CALENDAR_QUERY)
    page.locator('.fc-view-harness').wait_for();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    ok(page.locator('#calendar-long').is_hidden())
    ok('长期博物馆展' not in page.locator('#calendar').inner_text())
    ok(page.locator('.fc-daygrid-event').count()>=1)
    # Only ordinary short events enter the grid; retain their actual ends.
    ends=page.evaluate("calendar.getEvents().map(e=>e.end)")
    ok(all(x is not None for x in ends),str(ends))
    ok(page.evaluate('calendar.getEvents().every(e=>e.end-e.start<14*86400000)'))
    fav=page.locator('.fc-event.favorite-event',has_text='排序较早').first
    fav.wait_for();ok('★' in fav.inner_text(),fav.inner_text());ok('已收藏' in (fav.get_attribute('aria-label') or ''))
    ok(page.locator('.calendar-legend span',has_text='我的收藏').is_visible())
    ok(page.locator('.fc-daygrid-more-link').count()==0, 'Dense dates must not hide events behind +N')
    boxes=[]
    for i in range(12):
        item=page.locator('.fc-daygrid-event').filter(has_text=f'同日普通活动{i+1}').filter(has=page.locator('.calendar-event-title')).all()
        exact=[node for node in item if node.locator('.calendar-event-title').inner_text().endswith(f'同日普通活动{i+1}')]
        ok(len(exact)==1, f'Dense event {i+1} must appear once')
        ok(exact[0].is_visible(), f'Dense event {i+1} hidden')
        box=exact[0].bounding_box();ok(box and box['height']>=18, 'Readable event row required');boxes.append(box)
    boxes.sort(key=lambda b:b['y'])
    ok(all(a['y']+a['height']<=b['y']+1 for a,b in zip(boxes,boxes[1:])), 'Dense rows overlap')
    ok(page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Desktop overflow')
    page.screenshot(path=str(ART/'desktop-month-clean.png'),full_page=True)
check('month_calendar_preserves_short_intervals',calendar_clean)

def calendar_favorite_updates_without_reload():
    ready(CALENDAR_QUERY);expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    fav=page.locator('.fc-event.favorite-event',has_text='排序较早').first;fav.click()
    page.locator('#detail').wait_for(state='visible')
    b=page.locator('#detail [data-save]')
    ok(b.get_attribute('aria-pressed')=='true')
    b.click();expect(b).to_have_attribute('aria-pressed','false')
    expect(page.locator('.fc-event.favorite-event',has_text='排序较早')).to_have_count(0)
    b.click();expect(b).to_have_attribute('aria-pressed','true')
    page.locator('#close-detail').click()
    page.locator('.fc-event.favorite-event',has_text='排序较早').first.wait_for()
check('calendar_favorite_updates_without_reload',calendar_favorite_updates_without_reload)

def calendar_show_long():
    ready(CALENDAR_QUERY);page.locator('#hide-long').uncheck();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    page.locator('#calendar-long').wait_for(state='visible')
    expect(page.locator('#calendar-long [data-calendar-long-toggle]')).to_have_attribute('aria-expanded','false')
    page.locator('#calendar-long [data-calendar-long-toggle]').click()
    ok('长期博物馆展' in page.locator('#calendar-long').inner_text())
    ok('长期博物馆展' not in page.locator('#calendar').inner_text())
    ok('不再铺成整月长条' in page.locator('#calendar-long').inner_text())
check('month_calendar_separates_long_running',calendar_show_long)

def mobile_calendar():
    page.set_viewport_size({'width':390,'height':844});ready(CALENDAR_QUERY)
    page.locator('.fc-list').wait_for();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    ok(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    fav=page.locator('.fc-list-event.favorite-event',has_text='排序较早').first
    fav.wait_for();ok('★' in fav.inner_text(),fav.inner_text());ok('已收藏' in (fav.get_attribute('aria-label') or ''))
    for i in range(12):
        expect(page.locator('.fc-list-event',has_text=f'同日普通活动{i+1}').first).to_be_visible()
    ok(page.locator('.fc-daygrid-more-link').count()==0)
    page.screenshot(path=str(ART/'mobile-month-list.png'),full_page=True)
check('calendar_mobile_no_overflow',mobile_calendar)

report['page_errors_empty']=not report['errors']
(ART/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
br.close();pw.stop();print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
raise SystemExit(0 if all(report['checks'].values()) and not report['errors'] else 1)
