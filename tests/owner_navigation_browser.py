"""Real browser Back with synthetic authorized owner changes on a local fixture."""
import json
from review_harness import Harness
from playwright.sync_api import expect

h=Harness('owner-navigation-review');p=h.page
owner={'username':'alice'}
try:
    p.route('**/events/api/session',lambda route:route.fulfill(json=owner))
    p.route('**/events/api/login',lambda route:route.fulfill(json=owner))
    p.route('**/events/api/logout',lambda route:route.fulfill(json={}))
    p.add_init_script("""localStorage.setItem('radar.filters.v1:alice',JSON.stringify({version:1,query:'q=alice-earlier&attendance=online'}));localStorage.setItem('radar.filters.v1:bob',JSON.stringify({version:1,query:'q=bob-choice&attendance=offline'}));""")

    def apply_later_and_back():
        p.locator('#search').fill('alice-later');p.locator('#search').press('Enter')
        expect(p.locator('#event-list')).to_have_attribute('aria-busy','false')
        p.go_back()
        expect(p.locator('#search')).not_to_have_value('alice-later')
        expect(p.locator('#event-list')).to_have_attribute('aria-busy','false')

    def switch(user):
        p.locator('#logout').click();expect(p.locator('#login-panel')).to_be_visible()
        owner['username']=user;p.locator('#username').fill(user);p.locator('#password').fill('synthetic-only')
        p.locator('#login-submit').click();expect(p.locator('#workspace')).to_be_visible()
        expect(p.locator('#event-list')).to_have_attribute('aria-busy','false')

    h.goto('');expect(p.locator('#search')).to_have_value('alice-earlier')
    apply_later_and_back();expect(p.locator('#search')).to_have_value('alice-earlier')
    switch('bob');expect(p.locator('#search')).to_have_value('bob-choice');expect(p.locator('#attendance')).to_have_value('offline')
    h.check('app_history_back_preserves_bob_preferences',p.evaluate("JSON.parse(localStorage.getItem('radar.filters.v1:bob')).query==='q=bob-choice&attendance=offline'"))

    owner['username']='alice';h.goto('?q=external-link&attendance=online')
    apply_later_and_back();expect(p.locator('#search')).to_have_value('external-link')
    switch('bob');expect(p.locator('#search')).to_have_value('external-link');expect(p.locator('#attendance')).to_have_value('online')
    h.check('external_history_entry_remains_a_usable_deep_link','q=external-link' in p.url)

    owner['username']='alice';h.goto('');apply_later_and_back();switch('alice')
    expect(p.locator('#search')).to_have_value('alice-earlier')
    h.check('same_owner_history_choice_survives_relogin')
    h.report['qualification']='Owner names and storage are synthetic; session/login/logout responses are intercepted. Reads use the disposable local fixture. This tests the conditional same-DOM owner boundary, not a production multi-user incident.'
except Exception as exc:
    h.report['errors'].append(str(exc));raise
finally:h.close()
