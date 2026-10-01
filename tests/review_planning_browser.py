from review_harness import Harness
from playwright.sync_api import expect
h=Harness('review-planning');p=h.page
try:
    h.goto();p.locator('#saved-views summary').click()
    p.locator('#search').fill('审阅活动 1');p.locator('#search').press('Enter');expect(p.locator('.event-card')).to_have_count(1)
    p.locator('#saved-view-name').fill('一个候选');p.get_by_role('button',name='保存当前视图',exact=True).click()
    expect(p.locator('#saved-view-count')).to_contain_text('1 / 12');h.check('E02_save_named_view')
    p.locator('#clear-filters').click();expect(p.locator('.event-card')).to_have_count(5)
    p.locator('#saved-view-choice').select_option('0');p.locator('#apply-saved-view').click();expect(p.locator('.event-card')).to_have_count(1);h.check('E02_restore_query')
    p.locator('#saved-view-name').fill('改名候选');p.locator('#rename-saved-view').click();expect(p.locator('#saved-view-choice option').nth(1)).to_have_text('改名候选')
    p.locator('#saved-view-choice').select_option('0');p.locator('#delete-saved-view').click();expect(p.locator('#saved-view-count')).to_contain_text('0 / 12')
    p.locator('#undo-saved-view').click();expect(p.locator('#saved-view-count')).to_contain_text('1 / 12');h.check('E02_rename_remove_undo')
    p.locator('#clear-filters').click();expect(p.locator('.event-card')).to_have_count(5)
    day=h.core.now().date();from datetime import timedelta
    start=(day+timedelta(days=2)).isoformat();end=(day+timedelta(days=3)).isoformat()
    p.locator('#date-from').fill(start);p.locator('#date-until').fill(end);p.locator('#apply-dates').click();expect(p.locator('.event-card')).to_have_count(2);h.check('E03_end_day_included')
    p.reload();expect(p.locator('#event-list')).to_have_attribute('aria-busy','false');expect(p.locator('.event-card')).to_have_count(2);h.check('E03_date_url_roundtrip')
    p.locator('#clear-dates').click();expect(p.locator('.event-card')).to_have_count(5)
    p.set_viewport_size({'width':390,'height':844});p.locator('#open-filters').click();expect(p.locator('#filter-dialog')).to_be_visible()
    count=[];p.on('request',lambda r:count.append(r.url) if '/events/api/events?' in r.url else None)
    p.locator('#search').fill('审阅活动 2');p.locator('#viewed-filter').select_option('unseen');p.wait_for_timeout(400)
    h.check('E12_draft_causes_zero_queries',not count)
    p.locator('#cancel-filter-draft').click();expect(p.locator('.event-card')).to_have_count(5);h.check('E12_cancel_preserves_results',not count)
    p.locator('#open-filters').click();expect(p.locator('#search')).to_have_value('');p.locator('#search').fill('审阅活动 2');p.locator('#apply-filter-draft').click();expect(p.locator('.event-card')).to_have_count(1)
    h.check('E12_apply_one_query',len(count)==1);h.check('E12_mobile_no_overflow',p.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    p.screenshot(path=str(h.out/'mobile-results.png'),full_page=True)
except Exception as exc:h.report['errors'].append(str(exc));raise
finally:h.close()
