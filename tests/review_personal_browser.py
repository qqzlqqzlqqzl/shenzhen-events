from review_harness import Harness
from playwright.sync_api import expect
h=Harness('review-personal');page=h.page
try:
    h.goto();card=page.locator('.event-card').first;eid=card.get_attribute('data-event')
    card.locator('.title-button').click()
    expect(page.locator('#detail')).to_be_visible()
    page.get_by_role('button',name='不感兴趣',exact=True).click()
    expect(page.get_by_role('button',name='不感兴趣',exact=True)).to_have_attribute('aria-pressed','true')
    page.get_by_role('button',name='时间不合适',exact=True).click()
    expect(page.get_by_role('button',name='时间不合适',exact=True)).to_have_attribute('aria-pressed','true')
    page.locator('#close-detail').click();h.goto('?view=feedback')
    expect(page.locator('.event-card')).to_have_count(1);h.check('E01_feedback_review')
    page.locator('#feedback-filter').select_option('interested');expect(page.locator('.empty')).to_be_visible();h.check('E01_no_matching_reason_resettable')
    h.goto('?view=history');expect(page.locator('.event-card')).to_have_count(1);h.check('E05_recent_views_not_interest')
    h.goto('?view=all&viewed=unseen');expect(page.locator('.event-card')).to_have_count(4);h.check('E05_unseen_filter')
    h.goto('?view=feedback');page.locator('.title-button').first.click()
    page.get_by_role('button',name='感兴趣',exact=True).click();expect(page.get_by_role('button',name='感兴趣',exact=True)).to_have_attribute('aria-pressed','true')
    # Undo is available outside the modal after returning to the result list.
    page.locator('#close-detail').click();page.locator('#undo-feedback').click()
    expect(page.locator('[data-feedback-for]').first).to_contain_text('不感兴趣');h.check('E09_feedback_undo')
    page.reload();expect(page.locator('#event-list')).to_have_attribute('aria-busy','false')
    expect(page.locator('[data-feedback-for]').first).to_contain_text('不感兴趣');h.check('E09_undo_persisted')
    page.set_viewport_size({'width':390,'height':844});h.check('E01_E05_mobile_no_overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    page.screenshot(path=str(h.out/'mobile.png'),full_page=True)
except Exception as exc:
    h.report['errors'].append(str(exc));raise
finally:h.close()
