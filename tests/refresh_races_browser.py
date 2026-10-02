"""Real Chromium on a disposable API fixture; retry POST is intercepted."""
import json
from review_harness import Harness
from playwright.sync_api import expect

h=Harness('refresh-races-review');p=h.page

def hold_read():
    held=[]
    def handle(route):
        if held:route.continue_();return
        response=route.fetch();held.append((route,response))
    p.route('**/events/api/events?*',handle)
    return held,handle

def release(held,handle):
    assert len(held)==1
    route,response=held[0];route.fulfill(response=response)
    p.unroute('**/events/api/events?*',handle)

try:
    h.goto()
    target=p.locator('.event-card').first.get_attribute('data-event')
    held,handle=hold_read();p.evaluate('void load()')
    expect(p.locator('#event-list')).to_have_attribute('aria-busy','true')
    p.locator('[data-save="'+target+'"]').first.click()
    p.wait_for_function('(id)=>records.get(id).favorite&&!saving.has(id)',arg=target)
    release(held,handle)
    expect(p.locator('#event-list')).to_have_attribute('aria-busy','false')
    h.check('late_list_read_keeps_confirmed_favorite',p.evaluate('(id)=>records.get(id).favorite&&records.get(id).revision===1',target))
    expect(p.locator('[data-save="'+target+'"]').first).to_have_attribute('aria-pressed','true')
    h.check('fixture_api_favorite_remains_saved',p.request.get(h.base+'/events/api/event/'+target).json()['favorite'])

    h.goto('?view=favorites')
    expect(p.locator('[data-save="'+target+'"]').first).to_be_visible()
    held,handle=hold_read();p.evaluate('void load()')
    expect(p.locator('#event-list')).to_have_attribute('aria-busy','true')
    p.locator('[data-save="'+target+'"]').first.click()
    p.wait_for_function('(id)=>!saving.has(id)&&!document.querySelector(\'[data-event="\'+id+\'"]\')',arg=target)
    release(held,handle)
    expect(p.locator('#event-list')).to_have_attribute('aria-busy','false')
    h.check('saved_only_stale_read_cannot_resurrect_card',p.locator('[data-event="'+target+'"]').count()==0)
    h.check('saved_only_snapshot_and_total_stay_empty',p.evaluate('listSnapshot.items.length===0&&listSnapshot.total===0'))

    source={'id':'synthetic-source','name':'Synthetic source','url':'https://example.invalid/source','status':'error','retry':None}
    state={'sources':[source],'candidates':[],'runs':[],'budget':{'calls':0,'tokens':0},'limits':{'daily_calls':1,'daily_tokens':1},'db_bytes':0,'retention_days':45,'ics_url':'/events/calendar.ics?token=synthetic-only'}
    p.route('**/events/api/status',lambda route:route.fulfill(json=state))
    retry=[]
    p.route('**/events/api/sources/synthetic-source/retry',lambda route:retry.append(route))
    h.goto('?view=status')
    button=p.locator('[data-retry-source="synthetic-source"]');expect(button).to_be_enabled()
    button.focus();p.keyboard.press('Enter')
    expect(button).to_be_disabled()
    p.wait_for_function('()=>document.activeElement.matches(".source-inspection summary")')
    p.evaluate('void loadStatus()')
    expect(p.locator('#status-panel')).to_have_attribute('aria-busy','false')
    expect(button).to_be_disabled()
    h.check('pending_retry_survives_status_refresh_with_real_focus',p.evaluate('document.activeElement.matches(".source-inspection summary")'))
    p.evaluate('void retrySource("synthetic-source",document.querySelector("[data-retry-source]"))')
    h.check('same_source_cannot_submit_twice',len(retry)==1)
    source['retry']={'state':'queued','message':'Synthetic waiting'}
    retry[0].fulfill(json={'message':'Synthetic queued'})
    p.wait_for_function('()=>!sourceRetries.size')
    expect(button).to_be_disabled()
    h.check('completed_queued_retry_keeps_source_keyboard_position',p.evaluate('document.activeElement.matches(".source-inspection summary")'))
    p.screenshot(path=str(h.out/'source-queued-focus.png'))
    h.report['qualification']='All reads/writes use the disposable fixture; source retry POST/status are intercepted. No provider execution or production/backend deduplication proof.'
except Exception as exc:
    h.report['errors'].append(str(exc));raise
finally:h.close()
