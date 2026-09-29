"""Public HTTPS smoke and reviewed UX checks. Only signed short-lived test sessions."""
import importlib.util,json,os,sqlite3,time,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];LIVE=Path(os.getenv('RADAR_LIVE_ROOT','/home/ubuntu/shenzhen-events'));OUT=ROOT/'artifacts/review/public';OUT.mkdir(parents=True,exist_ok=True)
spec=importlib.util.spec_from_file_location('accept',LIVE/'tests/browser_acceptance.py');accept=importlib.util.module_from_spec(spec);spec.loader.exec_module(accept)
accept.ART=OUT;accept.REPORT=OUT/'acceptance.json';accept.run()
from playwright.sync_api import sync_playwright,expect
report={'checks':{},'page_errors':[],'tested_commit':subprocess.check_output(['git','-C',str(LIVE),'rev-parse','HEAD'],text=True).strip()}
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path=accept.browser_path(),headless=True,args=['--no-sandbox','--no-proxy-server','--disable-dev-shm-usage'],env=dict(os.environ))
    ctx=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN',timezone_id='America/Los_Angeles')
    ctx.add_cookies([{'name':'sz_events_session','value':accept.test_session(),'domain':'106.53.40.6','path':'/events','httpOnly':True,'secure':True,'sameSite':'Lax'}]);page=ctx.new_page();page.on('pageerror',lambda e:report['page_errors'].append(str(e)))
    page.goto(accept.BASE+'/events/?view=all&q=机器人',wait_until='domcontentloaded');page.locator('.event-card').first.wait_for();assert page.locator('#search').input_value()=='机器人'
    page.reload(wait_until='domcontentloaded');page.locator('.event-card').first.wait_for();assert page.locator('#search').input_value()=='机器人';report['checks']['public_filter_reload']=True
    page.locator('[data-open]').first.click();page.locator('#detail').wait_for(state='visible');assert 'event=' in page.url;title=page.locator('.detail-title').inner_text()
    page.reload(wait_until='domcontentloaded');page.locator('#detail').wait_for(state='visible');assert page.locator('.detail-title').inner_text()==title;page.keyboard.press('Escape');page.wait_for_timeout(180);assert 'event=' not in page.url;report['checks']['public_deep_link_and_escape']=True
    page.locator('[data-view="calendar"]').click();page.locator('.fc-view-harness').wait_for();expect(page.locator('#calendar')).to_have_attribute('aria-busy','false');report['checks']['public_calendar_range_loaded']=True
    page.locator('[data-view="status"]').click();page.locator('.source-card').first.wait_for();report['checks']['public_source_status_loaded']=True
    report['stats']=ctx.request.get(accept.BASE+'/events/api/stats').json();report['checks']['no_empty_partial_counted_normal']=report['stats']['normal_sources']<report['stats']['sources']
    page.locator('[data-view="all"]').click();page.locator('.event-card').first.wait_for();page.locator('[data-open]').first.click();page.locator('#detail').wait_for(state='visible');ctx.clear_cookies();page.evaluate("api('session').catch(()=>{})");page.locator('#login-panel').wait_for(state='visible')
    assert not page.locator('#detail').evaluate('(e)=>e.open');assert page.locator('#detail-body').inner_html()=='';report['checks']['public_expiry_clears_dialog']=True
    browser.close()
def counts(path):
    c=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
    result={'raw':c.execute('SELECT COUNT(*) FROM raw_items').fetchone()[0],'events':c.execute('SELECT COUNT(*) FROM events').fetchone()[0],'favorites':c.execute('SELECT COUNT(*) FROM preferences WHERE favorite=1').fetchone()[0],'pending':c.execute("SELECT COUNT(*) FROM raw_items WHERE analysis_state='pending'").fetchone()[0]};c.close();return result
report['before_repair']=counts(LIVE/'.private/interaction-review-recovery.sqlite3');report['after_repair']=counts(LIVE/'data/events.sqlite3')
report['checks']['exactly_50_duplicate_raw_rows_removed']=report['before_repair']['raw']-report['after_repair']['raw']==50
report['checks']['favorite_count_preserved']=report['before_repair']['favorites']==report['after_repair']['favorites']
report['services']=subprocess.check_output(['systemctl','is-active','shenzhen-events.service','shenzhen-events-collect.timer','shenzhen-events-analyze.timer'],text=True).splitlines()
report['web_memory_bytes']=int(subprocess.check_output(['systemctl','show','shenzhen-events.service','-p','MemoryCurrent','--value'],text=True))
report['original_application_processes']=subprocess.check_output(['ps','-p','2945287,2267215,2247458','-o','pid,lstart,comm','--no-headers'],text=True).splitlines()
assert not report['page_errors'];assert all(report['checks'].values());assert report['services']==['active']*3
(OUT/'review-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
