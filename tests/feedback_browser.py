import atexit,json,os,shutil,subprocess,sys,tempfile,time
from pathlib import Path
from datetime import timedelta
ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts/feedback-review';ART.mkdir(parents=True,exist_ok=True)
FIX=Path(tempfile.mkdtemp(prefix='radar-feedback-'));os.environ['RADAR_ROOT']=str(FIX)
(FIX/'static').symlink_to(ROOT/'static',target_is_directory=True)
(FIX/'sources.json').write_text(json.dumps([{'id':'a','name':'测试源','url':'https://example.com','priority':10}]))
sys.path.insert(0,str(ROOT))
from radar import core,api
api.initialize_settings();core.init()
start=core.now()+timedelta(days=5)
core.ingest({'id':'a','priority':10},{'title':'反馈测试活动','url':'https://example.com/feedback','start_at':start.isoformat(),'end_at':(start+timedelta(hours=2)).isoformat(),'location':'深圳市南山区测试中心','summary':'用于个人反馈交互的隔离活动。','cost_text':'免费'})
with core.db() as db:
    eid=db.execute("SELECT id FROM events WHERE url='https://example.com/feedback'").fetchone()[0]
    db.execute('INSERT INTO preferences(event_id,favorite) VALUES(?,1)',(eid,))
sys.path.append('/home/ubuntu/ai-news/runtime/venv/lib/python3.12/site-packages')
from playwright.sync_api import sync_playwright,expect
import importlib.util,requests
spec=importlib.util.spec_from_file_location('accept',ROOT/'tests/browser_acceptance.py')
accept=importlib.util.module_from_spec(spec);spec.loader.exec_module(accept)
BASE='http://127.0.0.1:18097'
server=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','uvicorn','radar.api:app','--host','127.0.0.1','--port','18097','--no-access-log'],cwd=ROOT,env=dict(os.environ),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
@atexit.register
def cleanup():
    server.terminate()
    try:server.wait(timeout=5)
    except subprocess.TimeoutExpired:server.kill()
    shutil.rmtree(FIX,ignore_errors=True)
for _ in range(50):
    try:
        if requests.get(BASE+'/events/api/health',timeout=.2).status_code==200:break
    except requests.RequestException:pass
    time.sleep(.1)
report={'checks':{},'errors':[]}
pw=sync_playwright().start();br=pw.chromium.launch(executable_path=accept.browser_path(),headless=True,args=['--no-sandbox','--no-proxy-server','--disable-dev-shm-usage'],env=dict(os.environ))
ctx=br.new_context(viewport={'width':1440,'height':1000},locale='zh-CN',timezone_id='Asia/Shanghai')
ctx.add_cookies([{'name':'sz_events_session','value':api.sign_session({'id':1,'username':'feedback-review'}),'domain':'127.0.0.1','path':'/events','httpOnly':True,'secure':False,'sameSite':'Lax'}])
page=ctx.new_page();page.set_default_timeout(8000);page.on('pageerror',lambda e:report['errors'].append(str(e)))
def ok(name,value,detail=''):
    report['checks'][name]=bool(value)
    if not value:raise AssertionError(name+': '+str(detail))
def ready():
    page.goto(BASE+'/events/?view=all',wait_until='domcontentloaded')
    page.locator('#workspace').wait_for(state='visible')
    expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
try:
    ready();card=page.locator('.event-card',has_text='反馈测试活动').first
    card.wait_for();ok('initial_feedback_badge_hidden',card.locator('[data-feedback-for]').is_hidden())
    card.locator('.title-button').click();page.locator('#detail').wait_for(state='visible')
    favorite=page.locator('#detail [data-save]');ok('favorite_independent_initially',favorite.get_attribute('aria-pressed')=='true')
    interested=page.get_by_role('button',name='感兴趣',exact=True);interested.click()
    expect(interested).to_have_attribute('aria-pressed','true')
    topic=page.get_by_role('button',name='主题喜欢',exact=True);topic.click();expect(topic).to_have_attribute('aria-pressed','true')
    more=page.get_by_role('button',name='以后多推',exact=True);more.click();expect(more).to_have_attribute('aria-pressed','true')
    page.locator('#close-detail').click()
    badge=card.locator('[data-feedback-for]');expect(badge).to_be_visible();ok('card_remembers_interest','感兴趣' in badge.inner_text())
    page.reload(wait_until='domcontentloaded');expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    card=page.locator('.event-card',has_text='反馈测试活动').first;card.locator('.title-button').click()
    expect(page.get_by_role('button',name='感兴趣',exact=True)).to_have_attribute('aria-pressed','true')
    expect(page.get_by_role('button',name='主题喜欢',exact=True)).to_have_attribute('aria-pressed','true')
    expect(page.get_by_role('button',name='以后多推',exact=True)).to_have_attribute('aria-pressed','true')
    ok('reload_persists_and_favorite_remains',page.locator('#detail [data-save]').get_attribute('aria-pressed')=='true')
    dislike=page.get_by_role('button',name='不感兴趣',exact=True);dislike.click();expect(dislike).to_have_attribute('aria-pressed','true')
    conflict=page.get_by_role('button',name='时间不合适',exact=True);conflict.click();expect(conflict).to_have_attribute('aria-pressed','true')
    page.locator('#close-detail').click()
    card=page.locator('.event-card',has_text='反馈测试活动').first
    ok('dislike_does_not_hide_event',card.count()==1);ok('card_shows_dislike','不感兴趣' in card.locator('[data-feedback-for]').inner_text())
    card.locator('.title-button').click();clear=page.get_by_role('button',name='清除反馈',exact=True);clear.click()
    expect(page.get_by_role('button',name='不感兴趣',exact=True)).to_have_attribute('aria-pressed','false')
    expect(page.get_by_role('button',name='时间不合适',exact=True)).to_have_attribute('aria-pressed','false')
    ok('clear_does_not_clear_favorite',page.locator('#detail [data-save]').get_attribute('aria-pressed')=='true')
    page.locator('#close-detail').click();ok('clear_hides_card_feedback',page.locator('.event-card',has_text='反馈测试活动').first.locator('[data-feedback-for]').is_hidden())
    page.set_viewport_size({'width':390,'height':844});page.locator('.title-button').first.click()
    button=page.get_by_role('button',name='感兴趣',exact=True)
    box=button.bounding_box();ok('mobile_feedback_touch_target',box and box['height']>=44,box)
    ok('mobile_no_horizontal_overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.screenshot(path=str(ART/'mobile-feedback.png'),full_page=True)
finally:
    with core.db() as db:state=dict(db.execute('SELECT * FROM preferences WHERE event_id=?',(eid,)).fetchone())
    ok('database_favorite_preserved',state['favorite']==1)
    ok('database_feedback_cleared',state['feedback']=='' and json.loads(state['feedback_tags'])==[])
    report['page_errors_empty']=not report['errors']
    (ART/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    br.close();pw.stop()
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if all(report['checks'].values()) and not report['errors'] else 1)
