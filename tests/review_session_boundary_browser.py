"""Session-owned UI regressions with synthetic API/clipboard fixtures at both sizes."""
from review_harness import Harness
from playwright.sync_api import expect

h = Harness('review-session-boundary')
p = h.page
state = {'expired': False, 'version': 'A'}
prompts = []


def api_fixture(route):
    from urllib.parse import urlparse
    path = urlparse(route.request.url).path
    if state['expired']:
        route.fulfill(status=401, json={'detail': 'synthetic expired session'})
        return
    rows = [dict(id=str(i), title=state['version'] + ' synthetic event ' + str(i),
                 start_at='2026-10-05T10:00:00+08:00', end_at='2026-10-05T12:00:00+08:00',
                 status='scheduled', stored_status='scheduled',planning_eligible=True,safety_epoch=0,
                 safety=dict(available=True,guard_count=0,warning=''),favorite=state['version'] == 'A',
                 feedback='interested' if state['version'] == 'A' else 'not_interested',
                 feedback_tags=[], revision=1 if state['version'] == 'A' else 2,
                 event_type='MusicEvent', event_type_label='音乐', topics=['文化艺术'],
                 attendance='offline', district='南山', sources=[], url='https://example.com/' + str(i))
            for i in range(2)]
    data = {}
    if path.endswith(('/session', '/login')):
        data = {'username': 'synthetic-' + state['version']}
    elif path.endswith('/stats'):
        data = dict(recommended=2, upcoming=2, weekend=2, districts=['南山'],
                    event_types=[dict(value='MusicEvent', label='音乐')],
                    topics=[dict(value='文化艺术', label='文化艺术')])
    elif path.endswith('/status'):
        data = dict(sources=[], candidates=[], runs=[], budget=dict(calls=0, tokens=0),
                    limits=dict(daily_calls=1, daily_tokens=1), db_bytes=0, retention_days=45,
                    ics_url='/events/calendar.ics?token=synthetic-calendar-bearer&favorites=true')
    elif path.endswith('/events'):
        data = dict(items=rows, total=2, has_more=False, facets={}, excluded_long=dict(items=[], total=0))
    elif '/event/' in path:
        data = rows[int(path.rsplit('/', 1)[-1])]
    route.fulfill(json=data)


def on_dialog(dialog):
    prompts.append({'message': dialog.message, 'value': dialog.default_value})
    dialog.dismiss()


p.route('**/events/api/**', api_fixture)
p.on('dialog', on_dialog)


def ready(source='public'):
    state.update(expired=False, version='A')
    prompts.clear()
    response = p.goto(h.base + '/events/?view=' + ('status' if source == 'private' else 'all'))
    # Exercise the real response policy; never weaken CSP for the fixture.
    policy = response.headers.get('content-security-policy', '')
    assert "script-src 'self'" in policy and "'unsafe-eval'" not in policy
    expect(p.locator('#workspace')).to_be_visible()
    if source == 'private':
        expect(p.locator('#copy-ics')).to_be_visible()
    else:
        expect(p.locator('.title-button')).to_have_count(2)
    p.evaluate("""() => {
      window.copyWrites=[];
      Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText(value){
        copyWrites.push(value);return new Promise((resolve,reject)=>{window.pendingCopy={resolve,reject}})
      }}});
    }""")


def boundary(kind):
    if kind == '401':
        state['expired'] = True
        p.evaluate("async()=>{try{await api('session')}catch{}}")
    elif kind == 'logout':
        p.evaluate("document.querySelector('#logout').click()")
    else:
        p.evaluate("dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}))")
    expect(p.locator('#login-panel')).to_be_visible()
    expect(p.locator('dialog[open]')).to_have_count(0)
    expect(p.locator('#username')).to_be_focused()
    assert p.evaluate('records.size===0 && listSnapshot===null && calendarSnapshot===null')
    assert p.locator('#compare-body').inner_text() == ''
    assert p.locator('#copy-text').input_value() == ''
    assert p.locator('#status-panel').inner_text() == ''


def fresh(kind):
    state.update(expired=False, version='B')
    p.evaluate("history.replaceState({},'',location.pathname+'?view=all')")
    if kind == 'bfcache':
        p.evaluate("dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
    else:
        p.evaluate("async()=>await enter({username:'synthetic-B'})")
    expect(p.locator('#workspace')).to_be_visible()
    # Locator assertions wait for the fresh render without CSP-blocked string eval.
    expect(p.locator('.title-button').first).to_have_text('B synthetic event 0')
    assert p.evaluate("records.get('0')?.feedback==='not_interested'")


def snapshot():
    return p.evaluate("""() => ({records:[...records], focus:document.activeElement.id,
      toastHidden:document.querySelector('#toast').hidden, toastText:document.querySelector('#toast').textContent,
      query:location.search})""")


def unchanged(before):
    assert snapshot() == before
    expect(p.locator('dialog[open]')).to_have_count(0)
    assert p.locator('#copy-text').input_value() == ''
    assert p.locator('#compare-body').inner_text() == ''
    assert not prompts


try:
    for width in [1440, 390]:
        p.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
        for kind in ['401', 'logout', 'bfcache']:
            ready()
            for i in range(2):
                p.locator('[data-compare]').nth(i).click()
            p.locator('#compare-open').click()
            p.locator('#compare-body button').first.wait_for()
            p.evaluate("window.staleCompare=document.querySelector('#compare-body button');window.staleAction=staleCompare.onclick")
            boundary(kind)
            fresh(kind)
            before = snapshot()
            p.evaluate('staleAction();staleCompare.click()')
            unchanged(before)
            h.check(f'{width}_{kind}_comparison_removed_and_stale_action_inert')
            for source in ['public', 'private']:
                for outcome in ['resolve', 'reject']:
                    for relogin in [False, True]:
                        ready(source)
                        if source == 'public':
                            p.locator('.title-button').first.click()
                        selector = '#copy-ics' if source == 'private' else '.detail-utilities button'
                        # Point details mount after their fresh API revalidation.
                        p.locator(selector).first.wait_for(state='visible')
                        p.evaluate("selector=>{window.staleCopy=document.querySelector(selector);window.staleCopyAction=staleCopy.onclick}", selector)
                        p.locator(selector).first.click()
                        assert p.evaluate('copyWrites.length') == 1
                        boundary(kind)
                        if relogin:
                            fresh(kind)
                        before = snapshot()
                        p.evaluate("""async outcome=>{
                          if(outcome==='reject')pendingCopy.reject(new Error('synthetic clipboard denial'));else pendingCopy.resolve();
                          await new Promise(resolve=>setTimeout(resolve,0));
                          await staleCopyAction();staleCopy.click();
                          await new Promise(resolve=>setTimeout(resolve,0));
                        }""", outcome)
                        assert p.evaluate('copyWrites.length') == 1
                        unchanged(before)
                        h.check(f'{width}_{kind}_{source}_{outcome}_fresh_{relogin}_no_late_ui')
        # An already-open manual-copy overlay, filter sheet, and help overlay are all torn down.
        ready()
        p.locator('.title-button').first.click()
        p.locator('.detail-utilities button').first.click()
        p.evaluate("pendingCopy.reject(new Error('synthetic denial'))")
        expect(p.locator('#copy-dialog')).to_be_visible()
        expect(p.locator('#copy-text')).to_be_focused()
        p.evaluate("document.querySelector('#shortcut-help').click();beginFilterDraft()")
        boundary('401')
        h.check(f'{width}_all_auxiliary_dialogs_closed')
        p.screenshot(path=str(h.out / f'login-clean-{width}.png'), full_page=True)
        for source in ['public', 'private']:
            for outcome in ['resolve', 'reject']:
                ready(source)
                if source == 'public':
                    p.locator('.title-button').first.click()
                p.locator('#copy-ics' if source == 'private' else '.detail-utilities button').first.click()
                if source == 'private' and outcome == 'reject':
                    # Register before rejection, then wait for the actual fallback prompt.
                    with p.expect_event('dialog') as opened_prompt:
                        p.evaluate("pendingCopy.reject(new Error('synthetic denial'))")
                    assert opened_prompt.value.type == 'prompt'
                else:
                    p.evaluate("outcome=>outcome==='resolve'?pendingCopy.resolve():pendingCopy.reject(new Error('synthetic denial'))", outcome)
                if outcome == 'resolve':
                    expect(p.locator('#toast')).to_be_visible()
                    expect(p.locator('#toast')).to_contain_text('已复制')
                elif source == 'private':
                    assert p.evaluate('copyWrites.length') == 1
                    assert len(prompts) == 1
                    assert 'token=synthetic-calendar-bearer' in prompts[0]['value']
                else:
                    expect(p.locator('#copy-dialog')).to_be_visible()
                    expect(p.locator('#copy-text')).to_be_focused()
                    p.keyboard.press('Escape')
                    expect(p.locator('#copy-dialog')).not_to_be_visible()
                    expect(p.locator('.detail-utilities button').first).to_be_focused()
                    p.locator('#close-detail').click()
                    expect(p.locator('.title-button').first).to_be_focused()
                h.check(f'{width}_{source}_{outcome}_same_session_behavior')
        ready()
        for i in range(2):
            p.locator('[data-compare]').nth(i).click()
        p.locator('#compare-open').click()
        expect(p.locator('#close-compare')).to_be_focused()
        h.check(f'{width}_no_horizontal_overflow', p.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        p.screenshot(path=str(h.out / f'comparison-{width}.png'), full_page=True)
        p.keyboard.press('Escape')
        expect(p.locator('#compare-open')).to_be_focused()
        p.locator('.title-button').first.click()
        first = p.locator('#detail-title').inner_text()
        p.keyboard.press('ArrowRight')
        expect(p.locator('#detail-title')).not_to_have_text(first)
        p.keyboard.press('ArrowLeft')
        expect(p.locator('#detail-title')).to_have_text(first)
        p.locator('#close-detail').click()
        expect(p.locator('.title-button').first).to_be_focused()
        p.keyboard.press('?')
        expect(p.locator('#shortcut-dialog')).to_be_visible()
        p.keyboard.press('Escape')
        h.check(f'{width}_normal_comparison_keyboard_focus')
except Exception as exc:
    h.report['errors'].append(str(exc))
    raise
finally:
    h.close()
