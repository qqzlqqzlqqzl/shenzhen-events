"""Current-context counts, gray exclusions and inclusive participation modes."""
from datetime import timedelta
import json
from review_harness import Harness
from playwright.sync_api import expect
h=Harness('review-filter-context');p=h.page
try:
    with h.core.db() as c:
        for i,eid in enumerate(h.ids):
            kind='LiteraryEvent' if i<2 else 'MusicEvent'
            mode='hybrid' if i==3 else 'online' if i==4 else 'offline'
            c.execute('UPDATE events SET event_type=?,details=? WHERE id=?',(kind,json.dumps({'attendance':mode}),eid))
        c.execute('UPDATE events SET end_at=? WHERE id=?',(h.core.iso(h.core.now()+timedelta(days=40)),h.ids[1]))
    h.core.ingest({'id':'a','priority':10},{'title':'明确隐藏的长期活动','url':'https://example.com/hidden-long','start_at':h.core.iso(h.core.now()+timedelta(days=2)),'end_at':h.core.iso(h.core.now()+timedelta(days=42)),'location':'深圳南山','event_type':'LiteraryEvent'})
    with h.core.db() as c:
        eid=c.execute("SELECT id FROM events WHERE url='https://example.com/hidden-long'").fetchone()[0]
        c.execute('INSERT INTO preferences(event_id,hidden) VALUES(?,1)',(eid,))
    h.goto('?view=all&type=LiteraryEvent')
    expect(p.locator('.event-card')).to_have_count(1)
    expect(p.locator('#result-count')).to_contain_text('符合当前筛选 1 个活动')
    expect(p.locator('#excluded-events')).to_contain_text('1 项长期/重复')
    expect(p.locator('#excluded-events')).to_contain_text('审阅活动 2')
    expect(p.locator('#excluded-events')).not_to_contain_text('明确隐藏')
    expect(p.locator('#type-options label').filter(has=p.locator('input[value="LiteraryEvent"]')).locator('small')).to_have_text('1')
    h.check('context_count_matches_visible_literary_events')
    h.check('excluded_long_visible_with_reason_without_private_hidden',p.locator('.excluded-event-row').count()==1)
    p.locator('#type-filter summary').click()
    expect(p.locator('#type-options input')).to_have_count(23)
    expect(p.locator('#type-options .facet-extra')).to_have_count(0)
    p.screenshot(path=str(h.out/'desktop-context.png'),full_page=True)
    p.locator('#type-filter summary').click()
    p.get_by_role('button',name='纳入长期/重复活动',exact=True).click()
    expect(p.locator('.event-card')).to_have_count(2);expect(p.locator('#excluded-events')).to_be_hidden()
    expect(p.locator('#type-options label').filter(has=p.locator('input[value="LiteraryEvent"]')).locator('small')).to_have_text('2')
    h.check('include_long_restores_second_event_and_count')
    p.locator('#clear-filters').click();p.locator('#attendance').select_option('online')
    expect(p.locator('.event-card')).to_have_count(2)
    h.check('online_includes_hybrid',set(p.locator('.title-button').all_text_contents())=={'审阅活动 4','审阅活动 5'})
    p.locator('#attendance').select_option('offline');expect(p.locator('.event-card')).to_have_count(3)
    h.check('offline_includes_hybrid',set(p.locator('.title-button').all_text_contents())=={'审阅活动 1','审阅活动 3','审阅活动 4'})
    p.locator('#attendance').select_option('hybrid');expect(p.locator('.event-card')).to_have_count(1)
    h.check('hybrid_only_still_supported',p.locator('.title-button').inner_text()=='审阅活动 4')
    h.goto('?view=all&type=LiteraryEvent');p.set_viewport_size({'width':390,'height':844})
    h.check('gray_exclusions_mobile_no_overflow',p.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    p.screenshot(path=str(h.out/'mobile-context.png'),full_page=True)
    p.locator('#open-filters').click();p.locator('#type-filter summary').click()
    expect(p.locator('#type-options input')).to_have_count(23)
    h.check('all_options_remain_available_on_mobile')
    p.get_by_role('button',name='取消筛选',exact=True).click()
except Exception as exc:h.report['errors'].append(str(exc));raise
finally:h.close()
