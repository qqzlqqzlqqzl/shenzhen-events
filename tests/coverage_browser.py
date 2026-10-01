"""Isolated real API + browser regression, with controlled network faults. No production writes."""
import os,sys,json,time,tempfile,subprocess,hashlib,base64,hmac,importlib.util,threading
from pathlib import Path
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parents[1];ART=ROOT/'artifacts/coverage-review/browser';ART.mkdir(parents=True,exist_ok=True)
FIX=Path(tempfile.mkdtemp(prefix='radar-ux-'));os.environ['RADAR_ROOT']=str(FIX)
(FIX/'static').symlink_to(ROOT/'static',target_is_directory=True)
(FIX/'sources.json').write_text(json.dumps([{'id':'a','name':'测试活动主办方','url':'https://example.com','priority':10}]))
sys.path.insert(0,str(ROOT))
from radar import core,api
api.initialize_settings();core.init()
base=(core.now()+timedelta(days=1)).replace(hour=14,minute=0,second=0,microsecond=0)
for i in range(48):
    e={'title':f'机器人{i}' if i%2==0 else f'文化{i}','url':f'https://example.com/e/{i}','start_at':base.isoformat(),'end_at':(base+timedelta(hours=3)).isoformat(),'location':'深圳市南山区测试中心' if i%2==0 else '深圳市福田区测试场馆','summary':'测试活动介绍，仅在隔离测试库。','cost_text':'免费' if i%2==0 else '50元'}
    core.ingest({'id':'a','priority':10},e)
for name,status,start in [('过去收藏','scheduled',base-timedelta(days=8)),('取消收藏','cancelled',base),('缺少日期','needs_review',None)]:
    core.ingest({'id':'a','priority':10},{'title':name,'url':'https://example.com/'+name,'start_at':start.isoformat() if start else None,'end_at':(start+timedelta(hours=2)).isoformat() if start else None,'location':'深圳市南山区测试中心','status':status,'summary':'测试收藏保留。'})
with core.db() as c:
    for r in c.execute("SELECT id FROM events WHERE title IN ('过去收藏','取消收藏')").fetchall():c.execute('INSERT INTO preferences(event_id,favorite) VALUES(?,1)',(r['id'],))
    c.execute("UPDATE source_health SET status='ok',raw_count=48")
# Reuse an installed Playwright/browser, without adding a browser service.
sys.path.append('/home/ubuntu/ai-news/runtime/venv/lib/python3.12/site-packages')
from playwright.sync_api import sync_playwright, expect
spec=importlib.util.spec_from_file_location('accept',ROOT/'tests/browser_acceptance.py');accept=importlib.util.module_from_spec(spec);spec.loader.exec_module(accept)
BASE='http://127.0.0.1:18095';server=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','uvicorn','radar.api:app','--host','127.0.0.1','--port','18095','--no-access-log'],cwd=ROOT,env=dict(os.environ),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
import atexit,shutil,requests
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
report={'checks':{},'errors':[],'environment':'isolated fixture database, localhost only'}
pw=sync_playwright().start();br=pw.chromium.launch(executable_path=accept.browser_path(),headless=True,args=['--no-sandbox','--no-proxy-server','--disable-dev-shm-usage'],env=dict(os.environ))
ctx=br.new_context(viewport={'width':1440,'height':1000},locale='zh-CN',timezone_id='America/Los_Angeles')
def login_cookie():ctx.add_cookies([{'name':'sz_events_session','value':api.sign_session({'id':1,'username':'synthetic-review'}),'domain':'127.0.0.1','path':'/events','httpOnly':True,'secure':False,'sameSite':'Lax'}])
login_cookie();page=ctx.new_page();page.set_default_timeout(7000);page.on('pageerror',lambda e:report['errors'].append(str(e)))
def ready(url='?view=all'):
    page.goto(BASE+'/events/'+url,wait_until='domcontentloaded');page.locator('#workspace').wait_for(state='visible');expect(page.locator("#event-list")).to_have_attribute("aria-busy","false")
def check(name,fn):
    try:fn();report['checks'][name]=True;print('PASS',name,flush=True)
    except Exception as e:
        report['checks'][name]=False;report.setdefault('failures',{})[name]=str(e)[:1200];print('FAIL',name,str(e)[:220],flush=True)
        page.screenshot(path=str(ART/(name+'-failed.png')),full_page=True)
def assert_true(x,message='assertion failed'):
    if not x:raise AssertionError(message)
ready();print('INITIAL_CARDS',page.locator('.event-card').count(),flush=True)
def navigation():
    ready('?view=all');page.locator('#search').fill('机器人');page.wait_for_timeout(400);page.locator('#district-filter summary').click();page.locator('[data-facet-kind="district"][data-facet-action="none"]').click();page.locator('#district-options input[value="南山"]').check();page.locator('#district-filter summary').click();page.wait_for_timeout(250)
    assert_true('q=' in page.url and 'districts=' in page.url);page.reload(wait_until='domcontentloaded');page.locator('.event-card').first.wait_for()
    assert_true(page.locator('#search').input_value()=='机器人');assert_true(page.locator('#district-options input[value="南山"]').is_checked() and page.locator('#district-options input:checked').count()==1)
    page.locator('[data-view="favorites"]').click();page.wait_for_timeout(200);page.go_back(wait_until='domcontentloaded');page.wait_for_timeout(250)
    assert_true(page.locator('.tabs [aria-current="page"]').inner_text()=='全部活动');assert_true(page.locator('#search').input_value()=='机器人')
    page.go_forward(wait_until='domcontentloaded');page.wait_for_timeout(200);assert_true(page.locator('.tabs .active').inner_text()=='我的收藏')
check('url_reload_back_forward_filters',navigation)
def retained_favorites():
    ready('?view=favorites');text=page.locator('#event-list').inner_text();assert_true('过去收藏' in text and '取消收藏' in text)
    assert_true('已结束' in text and '已取消' in text);assert_true('进行中' not in text)
check('retained_past_cancelled_favorites',retained_favorites)
def detail_navigation():
    ready('?view=all&q=机器人');page.locator('[data-open]').first.click();page.locator('#detail').wait_for(state='visible');assert_true('event=' in page.url)
    title=page.locator('.detail-title').inner_text();page.reload(wait_until='domcontentloaded');page.locator('#detail').wait_for(state='visible');assert_true(page.locator('.detail-title').inner_text()==title)
    page.keyboard.press('Escape');page.wait_for_timeout(200);assert_true(not page.locator('#detail').evaluate('(e)=>e.open'));assert_true('event=' not in page.url);assert_true(page.locator('#search').input_value()=='机器人')
    page.locator('[data-open]').first.click();page.locator('#detail').wait_for(state='visible');page.go_back();page.wait_for_timeout(250);assert_true(not page.locator('#detail').evaluate('(e)=>e.open'))
check('detail_deep_link_escape_and_back',detail_navigation)
def favorite_race():
    ready('?view=all');eid=page.locator('.event-card').first.get_attribute('data-event');calls=[]
    def delayed(route):
        calls.append(route.request.post_data_json);response=route.fetch();time.sleep(.2);route.fulfill(response=response)
    page.route('**/events/api/preferences/*',delayed)
    page.evaluate("()=>{const b=document.querySelector('[data-save]');b.click();b.click();b.click()}");page.wait_for_timeout(600);page.unroute('**/events/api/preferences/*',delayed)
    assert_true(len(calls)==1,'rapid click issued multiple writes');saved=ctx.request.get(BASE+'/events/api/event/'+eid).json()['favorite'];assert_true(bool(saved),"server did not persist favorite")
    assert_true(page.locator('[data-save]').first.get_attribute('aria-pressed')=='true')
check('favorite_rapid_click_consistency',favorite_race)
def favorite_failure():
    ready('?view=all');before=page.locator('[data-save]').first.get_attribute('aria-pressed')
    def fail(route):route.fulfill(status=503,json={'detail':'临时故障，请重试'})
    page.route('**/events/api/preferences/*',fail);page.locator('[data-save]').first.click();page.wait_for_timeout(250);page.unroute('**/events/api/preferences/*',fail)
    assert_true(page.locator('[data-save]').first.get_attribute('aria-pressed')==before);assert_true(page.locator('[data-save]').first.is_enabled());assert_true('临时故障' in page.locator('#toast').inner_text())
check('favorite_failed_write_rolls_back',favorite_failure)
def pagination_retry():
    ready('?view=all');initial=page.locator('.event-card').count();failures=[]
    def once(route):
        if 'offset=36' in route.request.url and not failures:failures.append(1);route.fulfill(status=503,json={'detail':'分页暂时失败'})
        else:route.continue_()
    page.route('**/events/api/events?*',once);page.locator('#more').click();page.locator('[data-action="retry"]').wait_for();assert_true(page.locator('.event-card').count()==initial)
    page.locator('[data-action="retry"]').click();page.wait_for_timeout(400);page.unroute('**/events/api/events?*',once)
    ids=page.locator('.event-card').evaluate_all('(xs)=>xs.map(x=>x.dataset.event)');assert_true(len(ids)==48 and len(set(ids))==48)
check('pagination_error_retry_preserves_cards',pagination_retry)
def rapid_pagination():
    ready('?view=all');page.evaluate("()=>{const b=document.querySelector('#more');b.click();b.click()}");page.wait_for_timeout(400)
    ids=page.locator('.event-card').evaluate_all('(xs)=>xs.map(x=>x.dataset.event)');assert_true(len(ids)==48 and len(set(ids))==48)
check('pagination_double_click_no_duplicates',rapid_pagination)
def ime():
    ready('?view=all');calls=[];handler=lambda req:calls.append(req.url) if '/events/api/events?' in req.url else None;page.on('request',handler)
    page.locator('#search').dispatch_event('compositionstart');page.locator('#search').fill('ji');page.wait_for_timeout(400);assert_true(len(calls)==0)
    page.locator('#search').fill('机器人');page.locator('#search').dispatch_event('compositionend');page.wait_for_timeout(400);page.remove_listener('request',handler)
    assert_true(len(calls)==1);assert_true(page.locator('#search').input_value()=='机器人')
check('chinese_ime_waits_for_composition',ime)
def stale_search():
    ready('?view=all')
    page.evaluate("""()=>{const original=window.fetch;window.fetch=(u,o)=>original(u,o).then(r=>String(u).includes('q='+encodeURIComponent('机器人'))?new Promise(resolve=>setTimeout(()=>resolve(r),700)):r);const s=document.querySelector('#search');s.value='机器人';applyFilters();setTimeout(()=>{s.value='文化';applyFilters()},80)}""")
    page.wait_for_timeout(1100);assert_true('文化' in page.locator('#event-list').inner_text());assert_true('机器人' not in page.locator('#event-list').inner_text())
check('slow_search_cannot_overwrite_new_filters',stale_search)
def calendar_ranges():
    ready('?view=all');calls=[];handler=lambda req:calls.append(req.url) if '/events/api/events?' in req.url and 'period=calendar' in req.url else None;page.on('request',handler)
    page.locator('[data-view="calendar"]').click();expect(page.locator("#calendar")).to_have_attribute("aria-busy","false")
    assert_true(any('start=' in u and 'end=' in u for u in calls));page.locator('.fc-prev-button').click();page.wait_for_timeout(350);assert_true(len(calls)>=2)
    month=page.evaluate('calendarDate');page.reload(wait_until='domcontentloaded');page.locator('.fc-view-harness').wait_for();page.wait_for_timeout(350);assert_true(page.evaluate('calendarDate')==month)
    page.remove_listener('request',handler)
check('calendar_fetches_visible_range_and_keeps_month',calendar_ranges)
def calendar_more_than_500():
    far=(base+timedelta(days=65)).replace(day=5)
    for i in range(505):core.ingest({'id':'a','priority':10},{'title':f'E{i}','url':f'https://example.com/bulk/{i}','start_at':far.isoformat(),'end_at':(far+timedelta(hours=2)).isoformat(),'location':'深圳南山','summary':'隔离批量测试'})
    page.goto(BASE+'/events/?view=calendar&month='+far.date().isoformat(),wait_until='domcontentloaded');page.locator('.fc-view-harness').wait_for();expect(page.locator("#calendar")).to_have_attribute("aria-busy","false")
    assert_true(page.evaluate('calendar.getEvents().length')==505,'calendar silently truncated after first API page')
check('calendar_paginates_beyond_500_events',calendar_more_than_500)
def cross_midnight_display():
    value=page.evaluate("RadarUI.fullTime({start_at:'2026-10-09T23:00:00+08:00',end_at:'2026-10-10T01:00:00+08:00',all_day:false})")
    assert_true('10/09' in value and '10/10' in value,value)
    assert_true(page.evaluate("RadarUI.lifecycle({start_at:'2020-01-01',end_at:'2020-01-02',status:'scheduled'})")=='已结束')
check('shanghai_midnight_date_and_ended_label',cross_midnight_display)
def mobile_and_keyboard():
    page.set_viewport_size({'width':390,'height':844});ready('?view=all');assert_true(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.locator('[data-open]').first.click();page.locator('#detail').wait_for(state='visible');assert_true(page.locator('#close-detail').evaluate('(e)=>e===document.activeElement'))
    assert_true(page.evaluate("document.body.classList.contains('modal-open')"));page.screenshot(path=str(ART/'mobile-detail.png'))
    page.keyboard.press('Escape');page.wait_for_timeout(150);assert_true(not page.evaluate("document.body.classList.contains('modal-open')"))
    page.locator('[data-view="calendar"]').click();page.locator('.fc-list').wait_for();expect(page.locator("#calendar")).to_have_attribute("aria-busy","false")
    page.set_viewport_size({'width':1440,'height':1000});page.locator('.fc-dayGridMonth-view').wait_for();assert_true(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.screenshot(path=str(ART/'desktop-calendar.png'));page.set_viewport_size({'width':320,'height':740});ready('?view=all');assert_true(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.screenshot(path=str(ART/'mobile-320.png'))
check('mobile_width_keyboard_modal_and_resize',mobile_and_keyboard)
def empty_filter_and_reset():
    ready('?view=favorites&q=absolutely-no-matches');assert_true('筛选' in page.locator('.empty').inner_text());page.locator('[data-action="reset"]').click();page.wait_for_timeout(300)
    assert_true(page.locator('.tabs .active').inner_text()=='我的收藏');assert_true(page.locator('.event-card').count()>=2)
check('empty_filter_reset_keeps_current_scope',empty_filter_and_reset)
def session_expiry():
    ready('?view=all');page.locator('[data-open]').first.click();page.locator('#detail').wait_for(state='visible');ctx.clear_cookies();page.evaluate("api('session').catch(()=>{})");page.locator('#login-panel').wait_for(state='visible')
    assert_true(not page.locator('#detail').evaluate('(e)=>e.open'));assert_true(page.locator('#detail-body').inner_html()=='');assert_true(page.evaluate('records.size')==0);login_cookie()
check('expired_session_closes_and_clears_private_ui',session_expiry)
def late_status_after_logout():
    ready('?view=all');page.evaluate("""()=>{const original=window.fetch;window.fetch=(u,o)=>original(u,o).then(r=>String(u).endsWith('/status')?new Promise(resolve=>setTimeout(()=>resolve(r),600)):r);navigate('status');setTimeout(()=>document.querySelector('#logout').click(),60)}""");page.wait_for_timeout(1000)
    assert_true(page.locator('#login-panel').is_visible());assert_true(page.locator('#status-panel').inner_html()=='');assert_true(not page.locator('#detail').evaluate('(e)=>e.open'))
check('late_status_cannot_repopulate_after_logout',late_status_after_logout)
def calendar_failure_retry():
    login_cookie();page.set_viewport_size({'width':1440,'height':1000});ready('?view=all');attempts=[]
    def once(route):
        if 'period=calendar' in route.request.url and not attempts:attempts.append(1);route.fulfill(status=503,json={'detail':'日历暂时失败'})
        else:route.continue_()
    page.route('**/events/api/events?*',once);page.locator('[data-view="calendar"]').click();page.locator('[data-action="retry"]').wait_for()
    assert_true(page.evaluate('calendar.getEvents().length')==0);page.locator('[data-action="retry"]').click();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false');assert_true(not page.locator('#notice').is_visible());page.unroute('**/events/api/events?*',once)
check('calendar_failure_clears_stale_events_and_retries',calendar_failure_retry)
def status_failure_retry():
    ready('?view=all');attempts=[]
    def once(route):
        if not attempts:attempts.append(1);route.fulfill(status=503,json={'detail':'状态暂时失败'})
        else:route.continue_()
    page.route('**/events/api/status',once);page.locator('[data-view="status"]').click();page.locator('[data-action="retry-status"]').wait_for();page.locator('[data-action="retry-status"]').click();page.locator('.source-card').wait_for();assert_true(page.locator('.source-card').count()==1);page.unroute('**/events/api/status',once)
check('status_failure_retries_without_stuck_loading',status_failure_retry)

def exact_month_boundary():
    login_cookie();page.set_viewport_size({'width':1440,'height':1000})
    for title,start in [('九月专属','2026-09-29T14:00:00+08:00'),('十月不得混入','2026-10-05T14:00:00+08:00')]:
        core.ingest({'id':'a','priority':10},{'title':title,'url':'https://example.com/boundary/'+title,'start_at':start,'end_at':None,'location':'深圳南山','summary':'月份边界回归'})
    page.goto(BASE+'/events/?view=calendar&month=2026-09-01',wait_until='domcontentloaded')
    page.locator('.fc-dayGridMonth-view').wait_for();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    assert_true('九月专属' in page.locator('#calendar').inner_text())
    assert_true('十月不得混入' not in page.locator('#calendar').inner_text())
    assert_true(page.evaluate("calendar.getEvents().every(e=>e.start.toISOString().startsWith('2026-09'))"))
    assert_true(page.locator('.fc-daygrid-body table tbody tr').count()==5)
    page.screenshot(path=str(ART/'september-only.png'),full_page=True)
    page.locator('.fc-next-button').click();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    assert_true('十月不得混入' in page.locator('#calendar').inner_text())
check('calendar_exact_month_without_next_month_events',exact_month_boundary)

def status_metrics_and_budget():
    with core.db() as c:
        c.execute('UPDATE source_health SET coverage=?',(json.dumps({'version':1,'mode':'page_inventory','visible':22,'extracted':22,'unique':22,'shenzhen_candidates':6,'admitted':6,'stored_events':6,'pages_visited':1,'rejected':{'其他城市':16}}),))
    ready('?view=all');assert_true('活动' in page.locator('#result-count').inner_text())
    page.locator('[data-view="status"]').click();page.locator('.coverage-flow').wait_for()
    assert_true(page.locator('#result-count').is_hidden() and page.locator('#result-count').inner_text()=='')
    assert_true(page.locator('#active-filters').is_hidden())
    assert_true(page.locator('.coverage-flow dd').all_inner_texts()==['22','22','22','6','6','6'])
    assert_true('外部模型自动分析已停用' in page.locator('.analysis-budget').inner_text())
    assert_true('自动采集继续运行' in page.locator('.analysis-budget').inner_text())
    assert_true(page.locator('.analysis-budget summary').count()==0)
    page.screenshot(path=str(ART/'source-coverage-budget.png'),full_page=True)
check('status_clears_list_count_and_explains_coverage_budget',status_metrics_and_budget)

def retry_queue_ui():
    page.locator('[data-retry-source="a"]').click()
    expect(page.locator('[data-retry-source="a"]')).to_have_text('检查已排队')
    expect(page.locator('[data-retry-source="a"]')).to_be_disabled()
    with core.db() as c:
        row=c.execute('SELECT * FROM source_jobs ORDER BY requested_at DESC LIMIT 1').fetchone()
        assert_true(row is not None and row['source_id']=='a' and row['state']=='queued', 'Queued UI must reflect a persisted job: '+str(dict(row) if row else None))
        c.execute("UPDATE source_jobs SET state='done',message='测试完成',updated_at=?",(core.stamp(),))
    expect(page.locator('[data-retry-source="a"]')).to_be_enabled(timeout=7000)
    assert_true('上次手动检查已完成' in page.locator('.source-retry').inner_text())
check('single_source_retry_queue_feedback_and_polling',retry_queue_ui)

def mobile_status_readable():
    page.set_viewport_size({'width':320,'height':740});page.evaluate("navigate('status')");page.locator('.coverage-flow').wait_for()
    assert_true(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.screenshot(path=str(ART/'mobile-status.png'),full_page=True)
check('mobile_status_metrics_and_touch_actions',mobile_status_readable)

def late_calendar_response_safe():
    page.set_viewport_size({'width':1440,'height':1000});ready('?view=all')
    page.evaluate("""()=>{const original=window.fetch;window.fetch=(u,o)=>original(u,o).then(r=>String(u).includes('period=calendar')?new Promise(resolve=>setTimeout(()=>resolve(r),600)):r);navigate('calendar');setTimeout(()=>navigate('status'),60)}""")
    page.wait_for_timeout(1000);assert_true(page.locator('#status-panel').is_visible());assert_true(page.locator('#result-count').is_hidden())
check('late_calendar_response_cannot_clear_new_status_view',late_calendar_response_safe)

report['page_errors_empty']=not report['errors'];br.close();pw.stop();(ART/'browser-regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
raise SystemExit(0 if all(report['checks'].values()) and not report['errors'] else 1)
