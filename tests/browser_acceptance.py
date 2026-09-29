"""Run with a Playwright-equipped Python. Uses a short-lived signed test session.
Does not read user passwords. Does not write to existing applications.
"""
import os, json, time, hmac, hashlib, base64, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE=os.getenv('RADAR_TEST_URL','https://106.53.40.6')
REPORT=ROOT/'artifacts/browser-acceptance.json'
ART=ROOT/'artifacts'

def test_session():
    settings=json.loads((ROOT/'.private/settings.json').read_text())
    body=base64.urlsafe_b64encode(json.dumps({'id':1,'name':'deployment-acceptance','exp':int(time.time())+900},separators=(',',':')).encode()).decode().rstrip('=')
    sig=hmac.new(bytes.fromhex(settings['session_secret']),body.encode(),hashlib.sha256).hexdigest()
    return body+'.'+sig

def browser_path():
    os.environ['LD_LIBRARY_PATH']='/home/ubuntu/ai-news/runtime/browser-libs/usr/lib/x86_64-linux-gnu'
    config=ROOT/'.private/browser-fonts.conf'
    config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>/home/ubuntu/ai-news/runtime/browser-libs/usr/share/fonts</dir><dir>/usr/share/fonts</dir><cachedir>'+str(ROOT/'.private/font-cache')+'</cachedir></fontconfig>')
    os.environ['FONTCONFIG_FILE']=str(config)
    candidates=sorted(Path('/home/ubuntu/.claude-server-commander/puppeteer-cache/chrome').glob('*/chrome-linux64/chrome'))
    if not candidates:raise RuntimeError('No local browser installation found')
    return str(candidates[-1])

def run():
    ART.mkdir(exist_ok=True);result={'checks':{},'console_errors':[],'page_errors':[],'tested_base':BASE}
    executable=browser_path()
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=executable,headless=True,args=['--no-sandbox','--no-proxy-server','--disable-dev-shm-usage'],env=dict(os.environ))
        ctx=browser.new_context(viewport={'width':1440,'height':1100},ignore_https_errors=BASE.endswith('127.0.0.1'),locale='zh-CN',timezone_id='Asia/Shanghai')
        page=ctx.new_page();page.on('pageerror',lambda e:result['page_errors'].append(str(e)))
        page.on('console',lambda m:result['console_errors'].append(m.text) if m.type=='error' and '401' not in m.text else None)
        t=time.perf_counter();response=page.goto(BASE+'/events/',wait_until='domcontentloaded',timeout=60000)
        result['checks']['http_ok']=response.ok;result['loopback_tls_verification_skipped']=BASE.endswith('127.0.0.1');page.locator('#login-panel').wait_for(state='visible')
        result['checks']['private_login_visible']=True;page.screenshot(path=str(ART/'desktop-login.png'),full_page=True)
        anon=ctx.request.get(BASE+'/events/api/events');assert anon.status==401;result['checks']['unauthenticated_api_denied']=True
        await_cookie={'name':'sz_events_session','value':test_session(),'domain':BASE.split('://',1)[1].split('/')[0],'path':'/events','httpOnly':True,'secure':True,'sameSite':'Lax'}
        ctx.add_cookies([await_cookie]);page.reload(wait_until='domcontentloaded');page.locator('.event-card').first.wait_for(timeout=20000)
        result['checks']['desktop_cards']=page.locator('.event-card').count();result['load_seconds']=round(time.perf_counter()-t,2)
        result['checks']['desktop_no_overflow']=page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(ART/'desktop-discover.png'),full_page=True)
        # Detail, source links and persisted favorite. Restore the prior state.
        card=page.locator('.event-card').first;event_id=card.get_attribute('data-event');button=card.locator('[data-save]');before=button.get_attribute('aria-pressed')=='true'
        button.click();page.wait_for_timeout(500);page.reload(wait_until='domcontentloaded');saved=ctx.request.get(BASE+'/events/api/events?favorites=true').json()['items']
        assert any(e['id']==event_id for e in saved)!=before;result['checks']['favorite_persists']=True
        ctx.request.post(BASE+'/events/api/preferences/'+event_id,headers={'X-Radar-Request':'1'},data={'favorite':before})
        page.locator('[data-open]').first.click();page.locator('#detail').wait_for(state='visible');assert page.locator('#detail a[target="_blank"]').count()>0;result['checks']['detail_source_links']=True;page.locator('#close-detail').click()
        page.locator('[data-view="all"]').click();page.wait_for_timeout(700)
        page.locator('#search').fill('no-such-radar-event-xyz-2026');page.locator('.empty').wait_for();result['checks']['search_empty_state']=True
        page.locator('#clear-filters').click();page.locator('.event-card').first.wait_for()
        page.locator('#free').check();page.wait_for_timeout(700);cards=page.locator('.event-card');result['checks']['free_filter']=all('免费' in cards.nth(i).inner_text() for i in range(cards.count()))
        page.locator('#clear-filters').click();page.wait_for_timeout(500)
        page.locator('[data-view="weekend"]').click();page.wait_for_timeout(600);result['checks']['weekend_cards']=page.locator('.event-card').count()
        page.locator('[data-view="calendar"]').click();page.locator('.fc-view-harness').wait_for(timeout=10000);result['checks']['fullcalendar_loaded']=True;page.screenshot(path=str(ART/'desktop-calendar.png'),full_page=True)
        page.locator('[data-view="status"]').click();page.locator('.source-card').first.wait_for();result['checks']['source_cards']=page.locator('.source-card').count();page.screenshot(path=str(ART/'desktop-sources.png'),full_page=True)
        # Mobile browser with independent viewport and same private session.
        mobile=browser.new_context(viewport={'width':390,'height':844},ignore_https_errors=BASE.endswith('127.0.0.1'),device_scale_factor=1,locale='zh-CN',timezone_id='Asia/Shanghai',is_mobile=True,has_touch=True)
        mobile.add_cookies([await_cookie]);mp=mobile.new_page();mp.on('pageerror',lambda e:result['page_errors'].append(str(e)));mp.goto(BASE+'/events/',wait_until='domcontentloaded');mp.locator('.event-card').first.wait_for()
        result['checks']['mobile_no_overflow']=mp.evaluate('document.documentElement.scrollWidth<=innerWidth');assert result['checks']['mobile_no_overflow'];mp.screenshot(path=str(ART/'mobile-discover.png'),full_page=True)
        mp.locator('[data-open]').first.click();mp.locator('#detail').wait_for(state='visible');mp.screenshot(path=str(ART/'mobile-detail.png'));mp.locator('#close-detail').click()
        mp.locator('[data-view="calendar"]').click();mp.locator('.fc-list').wait_for();result['checks']['mobile_calendar_list']=True;mp.screenshot(path=str(ART/'mobile-calendar.png'),full_page=True)
        page.goto(BASE+'/',wait_until='domcontentloaded');links={p:page.locator('a[href="'+p+'"]').count() for p in ['/inbox/','/newapi','/blog','/events/']};assert all(links.values());result['checks']['portal_links']=links;page.screenshot(path=str(ART/'portal-four-cards.png'),full_page=True)
        result['baseline_routes']={route:ctx.request.get(BASE+route,max_redirects=0).status for route in ['/','/inbox/','/newapi','/blog','/events/']}
        result['stats']=ctx.request.get(BASE+'/events/api/stats').json()
        browser.close()
    assert not result['page_errors'],result['page_errors']
    assert not result['console_errors'],result['console_errors']
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':run()
