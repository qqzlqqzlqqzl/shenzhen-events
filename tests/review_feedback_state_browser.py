from review_harness import Harness
from playwright.sync_api import expect
h=Harness('review-feedback-state');page=h.page
try:
    h.goto('?view=all');card=page.locator('.event-card').first;eid=card.get_attribute('data-event')
    card.locator('[data-save]').click();expect(card.locator('[data-save]')).to_have_attribute('aria-pressed','true')
    h.goto('?view=favorites');expect(page.locator('.event-card')).to_have_count(1)
    page.locator('.event-card [data-save]').click();expect(page.locator('.empty')).to_be_visible();expect(page.locator('#result-count')).to_contain_text('0 个活动')
    h.check('E07_unsave_last_favorite_updates_empty_and_count_without_error')
    h.goto('?view=all');page.locator(f'[data-open="{eid}"]').first.click()
    page.get_by_role('button',name='感兴趣',exact=True).click();expect(page.get_by_role('button',name='感兴趣',exact=True)).to_have_attribute('aria-pressed','true')
    page.locator('#close-detail').click();h.goto('?view=feedback');expect(page.locator('.event-card')).to_have_count(1)
    page.locator('.title-button').first.click();page.get_by_role('button',name='清除反馈',exact=True).click();expect(page.get_by_role('button',name='感兴趣',exact=True)).to_have_attribute('aria-pressed','false')
    page.locator('#close-detail').click();expect(page.locator('.empty')).to_be_visible();expect(page.locator('#result-count')).to_contain_text('0 个活动')
    h.check('E01_E09_clear_updates_feedback_membership_on_close')
    page.locator('#undo-feedback').click();expect(page.locator('.event-card')).to_have_count(1);expect(page.locator('[data-feedback-for]')).to_contain_text('感兴趣')
    h.check('E09_undo_survives_result_cache_eviction')
    page.reload();expect(page.locator('.event-card')).to_have_count(1);expect(page.locator('[data-feedback-for]')).to_contain_text('感兴趣');h.check('E09_undo_membership_persists')
except Exception as exc:h.report['errors'].append(str(exc));raise
finally:h.close()
