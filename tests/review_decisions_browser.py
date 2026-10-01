from review_harness import Harness
from playwright.sync_api import expect
h=Harness('review-decisions');p=h.page
try:
    h.goto()
    for i in range(3):p.locator('.event-card [data-compare]').nth(i).click()
    expect(p.locator('#compare-open')).to_have_text('比较 3 / 3 项');p.locator('.event-card [data-compare]').nth(3).click();expect(p.locator('#compare-chips button')).to_have_count(3);h.check('E04_maximum_three_candidates')
    p.locator('#compare-open').click();expect(p.locator('#compare-dialog')).to_be_visible();expect(p.locator('.compare-item')).to_have_count(3);expect(p.locator('.compare-conflict')).to_have_count(3);h.check('E04_full_comparison_and_conflicts')
    p.set_viewport_size({'width':390,'height':844});h.check('E04_mobile_compare_no_overflow',p.evaluate('document.documentElement.scrollWidth<=innerWidth'));p.locator('#close-compare').click();p.locator('#compare-clear').click()
    p.set_viewport_size({'width':1440,'height':1000});p.locator('.title-button').first.click();first=p.locator('#detail-title').inner_text()
    p.get_by_role('button',name='下一条',exact=True).click();expect(p.locator('#detail-title')).not_to_have_text(first);h.check('E06_next_detail')
    p.keyboard.press('ArrowLeft');expect(p.locator('#detail-title')).to_have_text(first);h.check('E06_keyboard_previous')
    expect(p.locator('.detail-utilities')).to_be_visible();expect(p.get_by_role('link',name='在地图中搜索地点 ↗')).to_be_visible();h.check('E08_reachable_actions_and_map')
    p.locator('#close-detail').click();h.check('E06_returns_focus',p.locator('.title-button').first.evaluate('(e)=>e===document.activeElement'))
    p.keyboard.press('?');expect(p.locator('#shortcut-dialog')).to_be_visible();p.keyboard.press('Escape');h.check('E06_help_keyboard')
    p.locator('.event-card [data-save]').first.click();expect(p.locator('.event-card [data-save]').first).to_have_attribute('aria-pressed','true')
    from datetime import timedelta
    month=(h.core.now()+timedelta(days=2)).strftime('%Y-%m-01')
    h.goto('?view=calendar&month='+month);expect(p.locator('#calendar')).to_have_attribute('aria-busy','false')
    p.locator('#calendar-saved-only').check();expect(p.locator('#calendar')).to_have_attribute('aria-busy','false');p.wait_for_function('calendar.getEvents().length===1');h.check('E07_calendar_saved_only')
    p.reload();expect(p.locator('#calendar')).to_have_attribute('aria-busy','false');expect(p.locator('#calendar-saved-only')).to_be_checked();h.check('E07_saved_filter_roundtrip')
    p.set_viewport_size({'width':390,'height':844});p.screenshot(path=str(h.out/'mobile-calendar.png'),full_page=True)
except Exception as exc:h.report['errors'].append(str(exc));raise
finally:h.close()
