"""Real isolated UI/API sequences for #94/#95, retained within the existing suite."""
import json
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import expect
from ux_calendar_fixture import seed


def run(h):
    p=h.page;ids=seed(h.core, 'a');requests=[];observations=[];captures={}
    h.report.update(ux_calendar_observations=observations,ux_calendar_requests=requests,ux_calendar_captures=captures)
    def request_seen(request):
        url=urlsplit(request.url)
        if url.path=='/events/api/events':requests.append(parse_qs(url.query))
    p.on('request',request_seen)
    base='?view=calendar&month=2026-10-01&q=UX'
    def settled(total):
        expect(p.locator('#calendar')).to_have_attribute('aria-busy','false')
        expect(p.locator('#result-count')).to_contain_text(f'符合筛选 {total} 个活动')
    def open_topics():
        if p.locator('#topic-filter').get_attribute('open') is None:p.locator('#topic-filter summary').click()
    def record(label):
        observations.append({'step':label,'url':p.url,'request':requests[-1] if requests else None,
          'ui':p.evaluate('''()=>({count:document.querySelector('#result-count').textContent,hideLong:document.querySelector('#hide-long').checked,attendance:document.querySelector('#attendance').value,topics:[...document.querySelectorAll('#topic-options input:checked')].map(x=>x.value),chips:document.querySelector('#active-filters').textContent,longExpanded:document.querySelector('[data-calendar-long-toggle]')?.getAttribute('aria-expanded')})''')})
    state='''()=>{const rect=s=>{const r=document.querySelector(s).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}};return {scrollY,innerWidth,innerHeight,dpr:devicePixelRatio,fonts:document.fonts.status,visualViewport:{width:visualViewport.width,height:visualViewport.height,pageTop:visualViewport.pageTop,offsetTop:visualViewport.offsetTop},calendar:rect('#calendar'),tabs:rect('.tabs'),active:rect('.tabs [aria-current="page"]'),long:rect('#calendar-long')}}'''
    def capture(name):
        frames=p.evaluate('''async()=>{await document.fonts.ready;const read='''+state+''';return new Promise((resolve,reject)=>{let prior='',since=performance.now(),start=since,frames=[];function sample(){const current=read(),key=JSON.stringify(current),time=performance.now();frames.push({time:time-start,state:current});if(key!==prior){prior=key;since=time}if(time-since>=300)return resolve(frames);if(time-start>4000)return reject(Error('calendar viewport did not settle'));requestAnimationFrame(sample)}requestAnimationFrame(sample)})}''')
        before=p.evaluate(state);p.screenshot(path=str(h.out/name));after=p.evaluate(state)
        captures[name]={'frames':frames,'before':before,'after':after}
        h.check('ux_calendar_stable_'+name,before==after)
    p.set_viewport_size({'width':1440,'height':900});h.goto(base);settled(5);record('all')
    open_topics();p.locator('#topic-options input[value="文化艺术"]').uncheck();settled(2)
    expect(p.locator('#active-filters')).to_contain_text('未选：文化艺术')
    expect(p.locator('#calendar')).to_contain_text('UX 音乐交流会');record('culture unchecked: overlapping social tag still matches')
    # Full topic catalog includes other values; select only via the explicit action.
    open_topics();p.locator('[data-facet-only="topic"][data-facet-value="文化艺术"]').click();settled(4);record('only culture')
    p.locator('#attendance').select_option('online');settled(2);record('culture and online')
    p.locator('#attendance').select_option('all');settled(4);record('culture and all participation')
    h.check('ux_all_participation_keeps_culture',requests[-1].get('topic')==['文化艺术'] and 'attendance' not in requests[-1])
    expect(p.locator('#type-options label').filter(has=p.locator('input[value="ExhibitionEvent"]')).locator('small')).to_have_text('3')
    expect(p.locator('#type-options label').filter(has=p.locator('input[value="MusicEvent"]')).locator('small')).to_have_text('1')
    h.check('ux_culture_facet_counts_match_current_context')
    open_topics();p.locator('[data-facet-kind="topic"][data-facet-action="all"]').click();settled(5)
    p.locator('#hide-long').uncheck();settled(7)
    expect(p.locator('#result-count')).to_contain_text('日历 5 项 · 长期/重复 2 项')
    toggle=p.locator('[data-calendar-long-toggle]');expect(toggle).to_have_attribute('aria-expanded','false')
    request_count=len(requests);toggle.click();expect(toggle).to_have_attribute('aria-expanded','true')
    expect(p.locator('#calendar-long-items')).to_be_visible();toggle.click();expect(p.locator('#calendar-long-items')).to_be_hidden()
    h.check('ux_fold_never_changes_query_or_hide',len(requests)==request_count and not p.locator('#hide-long').is_checked())
    p.locator('#hide-long').check();settled(5);expect(p.locator('#calendar-long')).to_be_hidden()
    expect(p.locator('#excluded-events [data-open]')).to_have_count(0)
    p.locator('#calendar-month-jump').fill('2026-11');settled(1);record('next month hidden long')
    p.locator('#calendar-month-jump').fill('2026-10');settled(5)
    # Browser Back/Forward must restore query state; disclosure remains presentation state.
    p.locator('#hide-long').uncheck();settled(7);p.go_back();settled(5);p.go_forward();settled(7)
    p.reload();settled(7);expect(p.locator('[data-calendar-long-toggle]')).to_have_attribute('aria-expanded','false')
    h.check('ux_month_history_reload_keep_long_filter_and_fold')
    for width,height in ((320,640),(360,800),(390,844),(430,932),(1440,900)):
        p.set_viewport_size({'width':width,'height':height});h.goto(base);settled(5)
        h.check('ux_calendar_before_aux_'+str(width),p.evaluate('''()=>{const grid=document.querySelector('#calendar'),following=n=>!!(grid.compareDocumentPosition(document.querySelector(n))&Node.DOCUMENT_POSITION_FOLLOWING);return ['.calendar-guide','#calendar-long','#excluded-events'].every(following)}'''))
        h.check('ux_active_calendar_tab_visible_'+str(width),p.locator('.tabs').evaluate('''e=>{const r=e.getBoundingClientRect(),a=e.querySelector('[aria-current="page"]').getBoundingClientRect();return a.left>=r.left-.5&&a.right<=r.right+.5}'''))
        h.check('ux_calendar_no_overflow_'+str(width),p.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        capture(f'ux-calendar-first-{width}.png')
        if width<620:
            p.locator('#open-filters').click();p.locator('#topic-filter summary').click();p.locator('[data-facet-only="topic"][data-facet-value="文化艺术"]').click()
            p.get_by_role('button',name='应用筛选',exact=True).click();settled(4)
            h.check('ux_mobile_only_culture_'+str(width),requests[-1].get('topic')==['文化艺术'])
            p.locator('#open-filters').click();p.locator('#free').check();p.get_by_role('button',name='取消筛选',exact=True).click();settled(4)
            h.check('ux_mobile_cancel_keeps_free_'+str(width),not p.locator('#free').is_checked())
    p.set_viewport_size({'width':390,'height':844});h.goto(base);settled(5)
    # Real keyboard activation traverses every existing tab; labels/font sizes stay intact.
    views=p.locator('.tabs button').evaluate_all('(buttons)=>buttons.map(b=>b.dataset.view)')
    first=p.locator('.tabs button').first;first.focus();first.press('Enter')
    for view in views[1:]:
        p.keyboard.press('Tab');p.keyboard.press('Enter')
        target=p.locator('.tabs button[data-view="'+view+'"]');expect(target).to_be_focused();expect(target).to_have_attribute('aria-current','page')
        h.check('ux_keyboard_tab_visible_'+view,target.evaluate('''e=>{const a=e.getBoundingClientRect(),r=e.parentElement.getBoundingClientRect();return a.left>=r.left-.5&&a.right<=r.right+.5}'''))
    h.goto(base);settled(5)
    for scheme in ('light','dark'):
        p.emulate_media(color_scheme=scheme)
        capture('ux-calendar-os-'+scheme+'-390.png')
    p.emulate_media(color_scheme='light')
    h.report['ux_navigation_theme_scope']='OS light/dark preference tested; application retains its explicit palette. Physical devices are not exercised.'
    touch=h.browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,locale='zh-CN',timezone_id='Asia/Shanghai')
    try:
        touch.add_cookies(h.ctx.cookies());tp=touch.new_page();tp.set_default_timeout(10000);tp.goto(h.base+'/events/'+base)
        expect(tp.locator('#calendar')).to_have_attribute('aria-busy','false')
        target=tp.locator('.tabs button[data-view="all"]');target.tap();expect(target).to_have_attribute('aria-current','page')
        target=tp.locator('.tabs button[data-view="calendar"]');target.tap();expect(target).to_have_attribute('aria-current','page')
        h.check('ux_emulated_touch_navigation_visible',target.evaluate('''e=>{const a=e.getBoundingClientRect(),r=e.parentElement.getBoundingClientRect();return a.left>=r.left-.5&&a.right<=r.right+.5}'''))
    finally:touch.close()
    h.report['ux_calendar_observations']=observations;h.report['ux_calendar_requests']=requests;h.report['ux_calendar_captures']=captures
    (h.out/'ux-calendar-observations.json').write_text(json.dumps({'observations':observations,'requests':requests},ensure_ascii=False,indent=2))
