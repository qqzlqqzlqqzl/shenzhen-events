"""Multi-day display acceptance using an isolated database and localhost only."""
import atexit, importlib.util, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts/multiday-review';ART.mkdir(parents=True,exist_ok=True)
FIX=Path(tempfile.mkdtemp(prefix='radar-multiday-'));os.environ['RADAR_ROOT']=str(FIX)
(FIX/'static').symlink_to(ROOT/'static',target_is_directory=True)
(FIX/'sources.json').write_text(json.dumps([{'id':'a','name':'测试主办方','url':'https://example.com','priority':10}]))
sys.path.insert(0,str(ROOT))
from radar import core,api
api.initialize_settings();core.init()
def put(title,start,end,all_day=True):
    core.ingest({'id':'a','priority':10},{'title':title,'url':'https://example.com/'+str(len(ids)),'start_at':start,'end_at':end,'all_day':all_day,'location':'深圳国际会展中心（宝安）15号馆','summary':'隔离测试，原始日期不得改写。','cost_text':'免费'})
    with core.db() as c:ids[title]=c.execute('SELECT id FROM events WHERE title=?',(title,)).fetchone()[0]
ids={}
LONG_TITLE='超长跨日活动'+'OpenSourceHardwareCommunity'*6
put('华南3D打印展','2026-10-14','2026-10-17')
put('跨月活动','2026-09-30','2026-10-03')
put('跨周活动','2026-10-17','2026-10-20')
put('午夜结束','2026-10-20T22:00:00+08:00','2026-10-21T00:00:00+08:00',False)
put('凌晨结束','2026-10-22T22:00:00+08:00','2026-10-23T01:00:00+08:00',False)
put('单日活动','2026-10-25','2026-10-26')
put('结束未注明','2026-10-27T23:59:00+08:00',None,False)
put('长期展览','2026-09-01','2026-11-30')
put(LONG_TITLE,'2026-10-08','2026-10-11')
spec=importlib.util.spec_from_file_location('accept',ROOT/'tests/browser_acceptance.py');accept=importlib.util.module_from_spec(spec);spec.loader.exec_module(accept)
BASE='http://127.0.0.1:18096'
server=subprocess.Popen([sys.executable,'-m','uvicorn','radar.api:app','--host','127.0.0.1','--port','18096','--no-access-log'],cwd=ROOT,env=dict(os.environ),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
@atexit.register
def cleanup():
    server.terminate()
    try:server.wait(timeout=5)
    except subprocess.TimeoutExpired:server.kill()
    shutil.rmtree(FIX,ignore_errors=True)
from browser_startup import wait_for_api
wait_for_api(server,BASE)
report={'checks':{},'errors':[],'environment':'isolated fixture database; localhost only; America/Los_Angeles browser timezone'}
pw=sync_playwright().start();br=pw.chromium.launch(executable_path=accept.browser_path(),headless=True,args=['--no-sandbox','--no-proxy-server','--disable-dev-shm-usage'])
ctx=br.new_context(viewport={'width':1440,'height':1050},locale='zh-CN',timezone_id='America/Los_Angeles')
ctx.add_cookies([{'name':api.COOKIE,'value':api.sign_session({'id':1,'username':'multi-day-test'}),'domain':'127.0.0.1','path':'/events','httpOnly':True,'secure':False,'sameSite':'Lax'}])
page=ctx.new_page();page.set_default_timeout(8000);page.on('pageerror',lambda e:report['errors'].append(str(e)))
def ready(query='?view=calendar&month=2026-10-01'):
    page.goto(BASE+'/events/'+query,wait_until='domcontentloaded');page.locator('#workspace').wait_for(state='visible')
    expect(page.locator('#calendar' if 'view=calendar' in query else '#event-list')).to_have_attribute('aria-busy','false')
def event(title):return page.locator('[data-event-id="'+ids[title]+'"]')
def ok(value,msg='assertion failed'):
    if not value:raise AssertionError(msg)
def check(name,fn):
    try:fn();report['checks'][name]=True;print('PASS',name,flush=True)
    except Exception as e:
        report['checks'][name]=False;report.setdefault('failures',{})[name]=str(e)[:1500];print('FAIL',name,str(e)[:400],flush=True)
        page.screenshot(timeout=30000,animations='disabled',path=str(ART/(name+'-failed.png')),full_page=True)

def desktop_span():
    ready();expect(event('华南3D打印展')).to_have_count(1)
    box=event('华南3D打印展').bounding_box();ok(box)
    for day in [14,15,16]:
        cell=page.locator(f'.fc-daygrid-day[data-date="2026-10-{day}"]').bounding_box();ok(box['x']<=cell['x']+cell['width']/2<=box['x']+box['width'],str((day,box,cell)))
    cell=page.locator('.fc-daygrid-day[data-date="2026-10-17"]').bounding_box();ok(box['x']+box['width']<cell['x']+cell['width']/2)
    ok('10/14—10/16 · 跨 3 天' in event('华南3D打印展').inner_text())
    ok('2026/10/14 — 2026/10/16' in event('华南3D打印展').get_attribute('aria-label'))
    ok('开始的活动' not in page.locator('#result-count').inner_text())
    page.screenshot(timeout=30000,animations='disabled',path=str(ART/'desktop-october-spans.png'),full_page=True)
check('desktop_three_day_bar_covers_oct_14_15_16_only',desktop_span)

def boundaries():
    ready();expect(event('跨月活动')).to_have_count(1);expect(event('跨周活动')).to_have_count(2)
    dates=page.evaluate('Object.fromEntries(calendar.getEvents().map(e=>[e.title,{start:e.startStr,end:e.endStr}]))')
    ok(dates['跨月活动']['start']=='2026-09-30' and dates['跨月活动']['end']=='2026-10-03')
    page.locator('.fc-next-button').click();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false');expect(event('华南3D打印展')).to_have_count(0)
    page.locator('.fc-prev-button').click();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false');expect(event('华南3D打印展')).to_have_count(1)
    page.reload(wait_until='domcontentloaded');expect(page.locator('#calendar')).to_have_attribute('aria-busy','false');expect(event('跨月活动')).to_have_count(1)
check('cross_month_week_and_reload_preserve_intervals',boundaries)

def detail_favorite():
    ready();event('华南3D打印展').click();page.locator('#detail').wait_for(state='visible')
    ok('2026/10/14 — 2026/10/16' in page.locator('.detail-meta').inner_text())
    ok('具体时段/开放日以原文为准' in page.locator('.detail-meta').inner_text())
    button=page.locator('#detail [data-save]');button.click();expect(button).to_have_attribute('aria-pressed','true')
    page.keyboard.press('Escape');expect(page.locator('#detail')).not_to_be_visible();expect(event('华南3D打印展')).to_have_count(1)
    page.go_back(wait_until='domcontentloaded');page.go_forward(wait_until='domcontentloaded');expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    ready('?view=favorites');card=page.locator('.event-card',has_text='华南3D打印展');expect(card).to_be_visible();ok('10/14—10/16 · 跨 3 天' in card.inner_text())
    page.screenshot(timeout=30000,animations='disabled',path=str(ART/'card-full-range.png'),full_page=True)
check('detail_favorite_history_and_list_range_preserved',detail_favorite)

def long_panel():
    ready();expect(event('长期展览')).to_have_count(0);ok(page.locator('#calendar-long').is_hidden())
    page.locator('#hide-long').uncheck();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    expect(page.locator('#calendar-long')).to_be_visible();page.locator('#calendar-long [data-calendar-long-toggle]').click();ok('长期展览' in page.locator('#calendar-long').inner_text());expect(event('长期展览')).to_have_count(0)
    page.locator('#calendar-long [data-open]').click();expect(page.locator('#detail')).to_be_visible();ok('2026/09/01 — 2026/11/29' in page.locator('.detail-meta').inner_text());page.keyboard.press('Escape')
check('long_running_stays_explicit_separate_panel',long_panel)

def mobile_daily():
    page.set_viewport_size({'width':390,'height':844});ready();page.locator('.fc-list').wait_for()
    expect(event('华南3D打印展')).to_have_count(3)
    dates=event('华南3D打印展').evaluate_all("els=>els.map(e=>{let row=e.previousElementSibling;while(row&&!row.classList.contains('fc-list-day'))row=row.previousElementSibling;return row?.dataset.date})")
    ok(dates==['2026-10-14','2026-10-15','2026-10-16'],str(dates))
    expect(event('跨月活动')).to_have_count(2);expect(event('午夜结束')).to_have_count(1);expect(event('凌晨结束')).to_have_count(2);expect(event('单日活动')).to_have_count(1);expect(event('结束未注明')).to_have_count(1)
    ok(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    event('华南3D打印展').nth(1).click();expect(page.locator('#detail')).to_be_visible();ok('华南3D打印展' in page.locator('#detail').inner_text());page.keyboard.press('Escape')
    page.screenshot(timeout=30000,animations='disabled',path=str(ART/'mobile-scrolled-viewport.png'))
    page.evaluate('window.scrollTo(0,0)')
    page.screenshot(timeout=30000,animations='disabled',path=str(ART/'mobile-daily-spans.png'),full_page=True)
    page.set_viewport_size({'width':320,'height':720});ok(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.set_viewport_size({'width':1440,'height':1050});page.locator('.fc-dayGridMonth-view').wait_for();expect(event('华南3D打印展')).to_have_count(1)
check('mobile_repeats_each_covered_day_and_midnight_is_exclusive',mobile_daily)
def keyboard_agenda_and_long_titles():
    page.set_viewport_size({'width':390,'height':844});ready()
    link=event('华南3D打印展').nth(1).locator('.fc-list-event-title a')
    expect(link).to_have_attribute('tabindex','0')
    for key in ['Enter','Space']:
        link.focus();link.press(key);expect(page.locator('#detail')).to_be_visible()
        ok(page.locator('#detail-title').inner_text()=='华南3D打印展')
        page.keyboard.press('Escape');expect(page.locator('#detail')).not_to_be_visible()
    link.click();expect(page.locator('#detail')).to_be_visible();page.keyboard.press('Escape');expect(page.locator('#detail')).not_to_be_visible()
    for width in [390,320,1440]:
        page.set_viewport_size({'width':width,'height':844})
        if width<620:expect(event(LONG_TITLE)).to_have_count(3)
        else:expect(event(LONG_TITLE)).to_have_count(1)
        ok(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(timeout=30000,animations='disabled',path=str(ART/f'long-title-{width}.png'),full_page=True)
check('native_agenda_keyboard_and_long_title_responsive_layout',keyboard_agenda_and_long_titles)

report['page_errors_empty']=not report['errors'];(ART/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
br.close();pw.stop();print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
raise SystemExit(0 if all(report['checks'].values()) and not report['errors'] else 1)
