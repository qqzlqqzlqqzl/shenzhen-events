"""Public HTTPS acceptance for issues #10-#13. Read-only except temporary favorite-free signed session."""
import os,json,time,hmac,hashlib,base64,importlib.util
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts/coverage-review/public';ART.mkdir(parents=True,exist_ok=True)
BASE='https://106.53.40.6'
PROD=Path('/home/ubuntu/shenzhen-events')
def session_token():
    cfg=json.loads((PROD/'.private/settings.json').read_text())
    body=base64.urlsafe_b64encode(json.dumps({'id':1,'name':'public-calendar-review','exp':int(time.time())+900},separators=(',',':')).encode()).decode().rstrip('=')
    sig=hmac.new(bytes.fromhex(cfg['session_secret']),body.encode(),hashlib.sha256).hexdigest()
    return body+'.'+sig
spec=importlib.util.spec_from_file_location('accept',ROOT/'tests/browser_acceptance.py')
accept=importlib.util.module_from_spec(spec);spec.loader.exec_module(accept)
report={'checks':{},'errors':[],'tested_base':BASE,'candidate':__import__('subprocess').check_output(['git','-C',str(PROD),'rev-parse','HEAD'],text=True).strip()}
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

def exact_month():
    ready('?view=calendar&month=2026-09-01');page.locator('.fc-dayGridMonth-view').wait_for()
    expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    evs=page.evaluate("calendar.getEvents().map(e=>({id:e.id,start:e.start.toISOString(),end:e.end?.toISOString()}))")
    ok(len(evs)>0 and all(e['start']<'2026-10-01' and (e['end']>'2026-09-01T00:00:00.000Z' if e['end'] else e['start']>='2026-09-01T00:00:00.000Z') for e in evs),str(evs[:4]))
    ok(page.locator('.fc-daygrid-body table tbody tr').count()==5)
    ok(page.locator('.fc-day-other .fc-event').count()==0)
    report['september_event_count']=len(evs)
    page.screenshot(path=str(ART/'september-only.png'),full_page=True)
    page.locator('.fc-next-button').click();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    ok(page.evaluate("calendar.getEvents().every(e=>e.start<new Date('2026-11-01')&&(e.end?e.end>new Date('2026-10-01'):e.start>=new Date('2026-10-01')))"))
check('real_month_queries_exclude_padding_dates',exact_month)

def source_coverage():
    ready('?view=weekend');page.locator('[data-view="status"]').click();page.locator('.coverage-flow').first.wait_for()
    ok(page.locator('#result-count').is_hidden() and page.locator('#result-count').inner_text()=='')
    ok(page.locator('#active-filters').is_hidden())
    status=ctx.request.get(BASE+'/events/api/status').json();sources={s['id']:s for s in status['sources']}
    for name in ['lianpu','douban','huodongxing']:
        cov=sources[name]['coverage'];ok(cov['pages_visited']>1,name+str(cov));ok(cov['unique']>30,name+str(cov))
    ok(sources['lianpu']['coverage']['unique']>=200)
    ok(sources['douban']['coverage']['unique']>=500)
    ok(sources['techevent']['coverage']['visible']>sources['techevent']['coverage']['shenzhen_candidates'])
    ok(sources['huodongxing']['status']=='partial')
    ok(any('登录' in r for r in sources['huodongxing']['coverage']['reasons']))
    for name in ['bendibao','meetup','wechat-chaihuo','sogou-discovery']:ok(sources[name]['status']!='ok',name)
    page.locator('.analysis-budget summary').click();ok('不是人民币金额' in page.locator('.analysis-budget').inner_text())
    ok('待 AI 分析' in page.locator('.analysis-budget').inner_text())
    report['sources']=[{k:s.get(k) for k in ['id','status','message','last_attempt','last_success','coverage']} for s in status['sources']]
    report['analysis_pending']=status.get('analysis_pending')
    page.screenshot(path=str(ART/'source-coverage.png'),full_page=True)
check('real_source_coverage_counts_and_budget_explanation',source_coverage)

def tech_events_available():
    r=ctx.request.get(BASE+'/events/api/events?period=upcoming&hide_long=false&q=TCT').json()
    ok(r['total']>=1);ok(any('TCT' in e['title'] for e in r['items']))
    report['tct_titles']=[e['title'] for e in r['items']]
check('reported_techevent_item_remains_available',tech_events_available)

def district_resolution():
    r=ctx.request.get(BASE+'/events/api/events?period=upcoming&hide_long=false&q='+__import__('urllib.parse',fromlist=['quote']).quote('深圳自然博物馆')).json()
    ok(any(e['district']=='坪山' for e in r['items']),str([(e['title'],e['district']) for e in r['items']]))
    report['amap_example']=[{'title':e['title'],'district':e['district'],'location':e['location']} for e in r['items']]
check('amap_district_enrichment_is_live',district_resolution)

def retry_only_tech():
    before=ctx.request.get(BASE+'/events/api/status').json()
    before_times={s['id']:s['last_attempt'] for s in before['sources']}
    page.locator('[data-retry-source="techevent"]').click()
    expect(page.locator('[data-retry-source="techevent"]')).to_have_text('检查已排队')
    expect(page.locator('[data-retry-source="techevent"]')).to_be_disabled()
    # Let the installed timer consume the actual persisted job; no fixture worker.
    deadline=time.time()+100
    while time.time()<deadline:
        page.wait_for_timeout(2000)
        state=ctx.request.get(BASE+'/events/api/status').json()
        current=next(s for s in state['sources'] if s['id']=='techevent')
        if current.get('retry') and current['retry']['state'] in ('done','failed'):break
    ok(current['retry']['state']=='done',str(current.get('retry')))
    expect(page.locator('[data-retry-source="techevent"]')).to_be_enabled(timeout=8000)
    for s in state['sources']:
        if s['id']!='techevent':ok(before_times[s['id']]==s['last_attempt'],'unrequested source fetched '+s['id'])
    report['actual_single_source_retry']=current['retry']
check('installed_timer_processes_only_requested_source',retry_only_tech)

def mobile_and_routes():
    page.set_viewport_size({'width':390,'height':844});ready('?view=status');page.locator('.coverage-flow').first.wait_for()
    ok(page.evaluate('document.documentElement.scrollWidth<=innerWidth'));page.screenshot(path=str(ART/'mobile-status.png'),full_page=True)
    ready('?view=calendar&month=2026-09-01');page.locator('.fc-list').wait_for();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false')
    ok(page.evaluate('document.documentElement.scrollWidth<=innerWidth'));page.screenshot(path=str(ART/'mobile-calendar.png'),full_page=True)
    routes={p:ctx.request.get(BASE+p,max_redirects=0).status for p in ['/','/inbox/','/newapi','/blog','/events/']}
    ok(routes=={'/':200,'/inbox/':200,'/newapi':302,'/blog':302,'/events/':200},str(routes))
    report['routes']=routes;report['stats']=ctx.request.get(BASE+'/events/api/stats').json()
check('mobile_layout_and_original_routes',mobile_and_routes)
report['page_errors_empty']=not report['errors']
(ART/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
browser.close();pw.stop();print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
raise SystemExit(0 if all(report['checks'].values()) and not report['errors'] else 1)

