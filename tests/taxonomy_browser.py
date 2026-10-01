"""Browser regression for Schema.org event taxonomy and multi-select filters."""
import os,sys,json,time,tempfile,subprocess,shutil,atexit
from pathlib import Path
from datetime import timedelta
ROOT=Path(__file__).resolve().parents[1]
FIX=Path(tempfile.mkdtemp(prefix='radar-taxonomy-'));os.environ['RADAR_ROOT']=str(FIX)
(FIX/'static').symlink_to(ROOT/'static',target_is_directory=True)
(FIX/'sources.json').write_text(json.dumps([{'id':'a','name':'测试源','url':'https://example.com','priority':10,'interval_hours':6}]))
sys.path.insert(0,str(ROOT))
from radar import core,api
api.initialize_settings();core.init()
start=core.now()+timedelta(days=3)
def put(title,typ,topics,n):
    core.ingest({'id':'a','priority':10},{'title':title,'url':f'https://example.com/{n}','start_at':(start+timedelta(hours=n)).isoformat(),'end_at':(start+timedelta(hours=n+2)).isoformat(),'location':'深圳市南山区测试中心','summary':title+'说明','event_type':typ,'topics':topics,'cost_text':'免费'})
put('AI 脱口秀','ComedyEvent',['AI与开源'],1)
put('AI 音乐会','MusicEvent',['AI与开源'],2)
put('机器人音乐会','MusicEvent',['机器人'],3)
put('博物馆设计展','ExhibitionEvent',['文化艺术'],4)
put('技术黑客松','Hackathon',['AI与开源','硬件创客'],5)
sys.path.append('/home/ubuntu/ai-news/runtime/venv/lib/python3.12/site-packages')
from playwright.sync_api import sync_playwright,expect
import importlib.util
spec=importlib.util.spec_from_file_location('accept',ROOT/'tests/browser_acceptance.py');accept=importlib.util.module_from_spec(spec);spec.loader.exec_module(accept)
BASE='http://127.0.0.1:18095'
server=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','uvicorn','radar.api:app','--host','127.0.0.1','--port','18095','--no-access-log'],cwd=ROOT,env=dict(os.environ),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
@atexit.register
def cleanup():
    server.terminate()
    try:server.wait(timeout=5)
    except subprocess.TimeoutExpired:server.kill()
    shutil.rmtree(FIX,ignore_errors=True)
import requests
for _ in range(50):
    try:
        if requests.get(BASE+'/events/api/health',timeout=.2).status_code==200:break
    except requests.RequestException:pass
    time.sleep(.1)
ART=ROOT/'artifacts/taxonomy-review';ART.mkdir(parents=True,exist_ok=True)
report={'checks':{},'errors':[]}
pw=sync_playwright().start();br=pw.chromium.launch(executable_path=accept.browser_path(),headless=True,args=['--no-sandbox','--no-proxy-server','--disable-dev-shm-usage'],env=dict(os.environ))
ctx=br.new_context(viewport={'width':1440,'height':1000},locale='zh-CN',timezone_id='Asia/Shanghai')
ctx.add_cookies([{'name':'sz_events_session','value':api.sign_session({'id':1,'username':'taxonomy-review'}),'domain':'127.0.0.1','path':'/events','httpOnly':True,'secure':False,'sameSite':'Lax'}])
page=ctx.new_page();page.set_default_timeout(8000);page.on('pageerror',lambda e:report['errors'].append(str(e)))
def ready(url='?view=all'):
    page.goto(BASE+'/events/'+url,wait_until='domcontentloaded');page.locator('#workspace').wait_for(state='visible')
    if page.locator('#event-list').is_visible():expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    if page.locator('#status-panel').is_visible():page.locator('#status-panel').wait_for(state='visible')
def check(name,fn):
    try:fn();report['checks'][name]=True;print('PASS',name,flush=True)
    except Exception as e:
        report['checks'][name]=False;report.setdefault('failures',{})[name]=str(e)[:1200];print('FAIL',name,str(e)[:220],flush=True);page.screenshot(path=str(ART/(name+'-failed.png')),full_page=True)
def ok(x,msg='assertion failed'):
    if not x:raise AssertionError(msg)

def schema_labels_are_distinct():
    ready()
    cards=page.locator('.event-card').all_inner_texts()
    joined='\n'.join(cards)
    for label in ['喜剧 / 脱口秀','音乐 / 演唱会','展览 / 博览','黑客松']:ok(label in joined,label)
    ok('展览文化' not in joined)
check('schema_type_labels_distinguish_entertainment',schema_labels_are_distinct)

def multiselect_semantics_and_url():
    ready()
    page.locator('#type-filter > summary').click()
    page.locator('[data-facet-kind="type"][data-facet-action="none"]').click();expect(page.locator('#event-list')).to_have_attribute('aria-busy','false');page.get_by_label('喜剧 / 脱口秀').check();expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    page.get_by_label('音乐 / 演唱会').check();expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    page.locator('#topic-filter > summary').click();expect(page.locator('#type-filter')).to_have_js_property('open',False);expect(page.locator('#topic-filter')).to_have_js_property('open',True);page.locator('[data-facet-kind="topic"][data-facet-action="none"]').click();expect(page.locator('#event-list')).to_have_attribute('aria-busy','false');page.get_by_label('AI与开源').check();expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    titles=page.locator('.title-button').all_inner_texts();ok(set(titles)=={'AI 脱口秀','AI 音乐会'},str(titles))
    u=page.url;ok(u.count('type=')==2 and 'topic=' in u,u)
    expect(page.locator('#type-summary')).to_have_text('已选 2 类');expect(page.locator('#topic-summary')).to_have_text('已选 1 个主题')
    page.screenshot(path=str(ART/'desktop-multiselect.png'),full_page=True)
    page.reload(wait_until='domcontentloaded');expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    ok(page.get_by_label('喜剧 / 脱口秀').is_checked() and page.get_by_label('音乐 / 演唱会').is_checked() and page.get_by_label('AI与开源').is_checked())
check('multiselect_or_within_and_across_groups_url_roundtrip',multiselect_semantics_and_url)

def removable_chip_and_history():
    ready('?view=all&type=ComedyEvent&type=MusicEvent&topic=AI%E4%B8%8E%E5%BC%80%E6%BA%90')
    page.locator('#type-filter > summary').click();page.get_by_label('喜剧 / 脱口秀').uncheck();expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    ok(page.locator('.title-button').all_inner_texts()==['AI 音乐会'])
    page.go_back(wait_until='domcontentloaded');expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    ok(set(page.locator('.title-button').all_inner_texts())=={'AI 脱口秀','AI 音乐会'})
check('selected_chip_removal_and_back_restore',removable_chip_and_history)

def mobile_checkbox_filter():
    page.set_viewport_size({'width':390,'height':844});ready()
    page.locator('#open-filters').click();expect(page.locator('#filter-dialog')).to_be_visible()
    page.locator('#type-filter > summary').focus();page.keyboard.press('Enter');page.locator('#type-options').wait_for(state='visible')
    box=page.locator('#type-filter .filter-popover').bounding_box();ok(box and box['x']>=0 and box['x']+box['width']<=390,box)
    ok(page.get_by_label('喜剧 / 脱口秀').is_visible());ok(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.screenshot(path=str(ART/'mobile-type-filter.png'),full_page=True);page.keyboard.press('Escape');ok(not page.locator('#type-filter').evaluate('(e)=>e.open'))
check('mobile_multiselect_touch_layout',mobile_checkbox_filter)

def status_reports_type_backfill():
    page.set_viewport_size({'width':1440,'height':1000});ready('?view=status');page.locator('#status-panel').wait_for()
    ok('外部模型自动分析已停用' in page.locator('#status-panel').inner_text())
check('status_discloses_type_backfill_progress',status_reports_type_backfill)

def legacy_topic_url_aliases():
    from urllib.parse import urlencode
    for key in ('tag', 'topic'):
        ready('?' + urlencode({'view': 'all', key: '展览文化'}))
        ok(page.get_by_label('文化艺术').is_checked())
        ok(page.locator('.title-button').all_inner_texts() == ['博物馆设计展'])
        page.reload(wait_until='domcontentloaded')
        expect(page.locator('#event-list')).to_have_attribute('aria-busy', 'false')
        ok(page.get_by_label('文化艺术').is_checked())
        ok(page.locator('.title-button').all_inner_texts() == ['博物馆设计展'])
check('legacy_topic_urls_keep_the_culture_filter', legacy_topic_url_aliases)

def all_type_facets_can_be_selected():
    ready()
    page.locator('#type-filter > summary').click()
    if page.locator('#type-options .facet-extra > summary').count():page.locator('#type-options .facet-extra > summary').click()
    for checkbox in page.locator('#type-options input[type="checkbox"]').all():
        checkbox.check()
        expect(page.locator('#event-list')).to_have_attribute('aria-busy', 'false')
    ok(page.locator('#type-options input:checked').count() > 20)
    ok(page.locator('#notice').is_hidden())
    ok(page.locator('.event-card').count() == 5)
check('all_offered_type_facets_are_valid_together', all_type_facets_can_be_selected)

def remembered_filters_after_fresh_entry():
    ready('?view=all&topic='+__import__('urllib.parse',fromlist=['quote']).quote('机器人'))
    ok(page.locator('#topic-options input:checked').count()==1)
    page.goto(BASE+'/events/',wait_until='domcontentloaded')
    expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    ok(page.get_by_label('机器人',exact=True).is_checked())
    ok(page.locator('#topic-options input:checked').count()==1)
    ready('?view=all')
    ok(page.locator('#topic-summary').inner_text()=='全部')
    page.locator('#clear-filters').click();expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
check('remember_filters_fresh_entry_explicit_url_reset',remembered_filters_after_fresh_entry)

def responsive_card_columns():
    for width,columns in [(390,1),(900,2),(1196,3),(1440,4),(1920,4)]:
        page.set_viewport_size({'width':width,'height':1000});ready('?view=all')
        actual=page.locator('#event-list').evaluate('(e)=>getComputedStyle(e).gridTemplateColumns.split(" ").length')
        ok(actual==columns,f'{width}: {actual} columns')
        ok(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.screenshot(path=str(ART/'responsive-four-columns.png'),full_page=True)
check('responsive_one_two_three_four_columns',responsive_card_columns)

report['page_errors_empty']=not report['errors'];(ART/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
br.close();pw.stop();print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
raise SystemExit(0 if all(report['checks'].values()) and not report['errors'] else 1)

