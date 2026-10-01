"""Issue #77 real-browser scenarios; invoked by review_filter_context_browser."""
from datetime import timedelta
from urllib.parse import parse_qs, urlparse
import json
from playwright.sync_api import expect


def run(h):
    p = h.page
    p.set_viewport_size({'width': 1440, 'height': 1000})
    requests = []
    p.on('request', lambda r: requests.append(parse_qs(urlparse(r.url).query)) if '/events/api/events?' in r.url else None)
    key = 'radar.filters.v1:review-owner'
    day = h.core.now().date() + timedelta(days=2)
    start, until = day.isoformat(), day.isoformat()
    query = f'?view=all&from={start}&until={until}'
    h.goto(query)
    expect(p.locator('.event-card')).to_have_count(1)
    original_url = p.url
    original_saved = p.evaluate('(key)=>localStorage.getItem(key)', key)
    count = len(requests)
    p.locator('#date-until').fill('')
    p.locator('[data-view="favorites"]').click()
    expect(p.locator('#date-error')).to_contain_text('日期')
    expect(p.locator('#view-title')).to_have_text('全部活动')
    assert p.url == original_url and len(requests) == count
    assert p.evaluate('(key)=>localStorage.getItem(key)', key) == original_saved
    p.locator('#attendance').select_option('online')
    assert len(requests) == count and p.url == original_url
    p.locator('.title-button').press('Enter')
    expect(p.locator('#detail')).to_be_visible()
    assert parse_qs(urlparse(p.url).query)['until'] == [until]
    assert 'attendance' not in parse_qs(urlparse(p.url).query)
    assert p.evaluate('(key)=>localStorage.getItem(key)', key) == original_saved
    p.locator('#close-detail').click()
    expect(p.locator('#detail')).to_be_hidden()
    assert len(requests) == count
    p.locator('#refresh-data').click()
    expect(p.locator('#event-list')).to_have_attribute('aria-busy', 'false')
    assert requests[-1]['start'] == [start]
    assert 'attendance' not in requests[-1]
    h.check('F77_invalid_navigation_and_detail_keep_applied_date_pair')

    # Real DOM input normalization cannot turn an invalid stored pair into an unrestricted query.
    raw = json.dumps({'version': 1, 'query': 'from=garbage&until=garbage&attendance=online'})
    p.evaluate('([key,value])=>localStorage.setItem(key,value)', [key, raw])
    count = len(requests)
    h.goto('')
    expect(p.locator('#notice')).to_contain_text('日期')
    expect(p.locator('#event-list')).to_have_attribute('aria-busy', 'false')
    assert len(requests) == count
    p.locator('[data-action="clear-invalid-dates"]').click()
    expect(p.locator('#notice')).to_be_hidden()
    expect(p.locator('#event-list')).to_have_attribute('aria-busy', 'false')
    assert len(requests) == count + 1 and requests[-1]['attendance'] == ['online']
    assert 'from' not in json.loads(p.evaluate('(key)=>localStorage.getItem(key)', key))['query']
    h.check('F77_invalid_persisted_dates_require_explicit_recovery')

    # Date filtering stays inside each personal view, including its long/unknown default scope.
    with h.core.db() as c:
        for i, eid in enumerate(h.ids):
            c.execute('INSERT INTO preferences(event_id,favorite,feedback,viewed_at,feedback_updated_at) VALUES(?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET favorite=1,feedback=excluded.feedback,viewed_at=excluded.viewed_at,feedback_updated_at=excluded.feedback_updated_at',
                      (eid, 1, 'interested', h.core.stamp(), h.core.stamp()))
    for view, period in [('favorites', 'saved'), ('feedback', 'feedback'), ('history', 'history')]:
        h.goto('?view=' + view)
        expect(p.locator('.event-card')).to_have_count(5)
        p.locator('#date-from').fill(start)
        p.locator('#date-until').fill(until)
        p.locator('#apply-dates').click()
        expect(p.locator('.event-card')).to_have_count(1)
        assert requests[-1]['period'] == [period]
        assert requests[-1]['start'] == [start]
        assert requests[-1]['end'] == [(day + timedelta(days=1)).isoformat()]
        assert requests[-1]['hide_long'] == ['false']
        assert parse_qs(urlparse(p.url).query)['view'] == [view]
        expect(p.locator('#active-filters')).to_contain_text(start + ' 至 ' + until)
        expect(p.locator('#date-scope-note')).to_contain_text('非收藏、反馈或浏览日期')
    p.screenshot(path=str(h.out/'date-personal-desktop.png'), full_page=True)
    h.check('F77_real_api_personal_date_controls_results_and_period_agree')

    # Back and Forward restore a fully applied date pair, with no stale validation message.
    p.locator('#clear-dates').click()
    expect(p.locator('.event-card')).to_have_count(5)
    p.go_back()
    expect(p.locator('.event-card')).to_have_count(1)
    expect(p.locator('#date-until')).to_have_value(until)
    p.go_forward()
    expect(p.locator('.event-card')).to_have_count(5)
    expect(p.locator('#date-error')).to_have_text('')
    h.check('F77_browser_back_forward_preserves_valid_filters')

    h.goto('?view=all&attendance=online&districts=南山')
    p.set_viewport_size({'width': 390, 'height': 844})
    count, original_url = len(requests), p.url
    p.locator('#open-filters').click()
    p.locator('#search').fill('取消尾请求')
    p.locator('#cancel-filter-draft').click()
    p.wait_for_timeout(350)
    assert len(requests) == count and p.url == original_url
    h.check('F77_fast_search_cancel_has_no_delayed_query')
    p.locator('#open-filters').click()
    p.locator('#attendance').select_option('offline')
    expect(p.locator('#district-filter')).to_be_visible()
    p.locator('#district-filter summary').click()
    p.locator('#district-options input[value="南山"]').uncheck()
    p.locator('#district-options input[value="福田"]').check()
    p.locator('#attendance').select_option('online')
    expect(p.locator('#district-filter')).to_be_hidden()
    p.locator('#attendance').select_option('hybrid')
    expect(p.locator('#district-filter')).to_be_visible()
    p.locator('#reset-filter-draft').click()
    expect(p.locator('#district-filter')).to_be_visible()
    p.locator('#cancel-filter-draft').click()
    assert len(requests) == count and p.url == original_url
    p.locator('#open-filters').click()
    expect(p.locator('#attendance')).to_have_value('online')
    p.locator('#attendance').select_option('offline')
    p.locator('#district-filter summary').click()
    expect(p.locator('#district-options input[value="南山"]')).to_be_checked()
    expect(p.locator('#district-options input[value="福田"]')).not_to_be_checked()
    p.locator('#district-options input[value="南山"]').uncheck()
    p.locator('#district-options input[value="福田"]').check()
    p.screenshot(path=str(h.out/'date-mobile-draft.png'), full_page=True)
    p.locator('#apply-filter-draft').click()
    expect(p.locator('#filter-dialog')).to_be_hidden()
    expect(p.locator('#event-list')).to_have_attribute('aria-busy', 'false')
    p.wait_for_timeout(350)
    assert len(requests) == count + 1
    assert requests[-1]['attendance'] == ['offline'] and requests[-1]['districts'] == ['福田']
    assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
    h.check('F77_mobile_dependency_cancel_reset_apply_exact_request_count')

    p.goto(h.base + f'/events/?view=calendar&month={start[:7]}-01&saved_only=true&from={start}&until={until}', wait_until='domcontentloaded')
    expect(p.locator('#calendar-panel')).to_be_visible()
    expect(p.locator('#calendar')).to_have_attribute('aria-busy', 'false')
    p.locator('#open-filters').click()
    expect(p.locator('#date-from')).to_be_disabled()
    expect(p.locator('#date-scope-note')).to_contain_text('不应用')
    p.locator('#reset-filter-draft').click()
    p.locator('#cancel-filter-draft').click()
    expect(p.locator('#calendar-saved-only')).to_be_checked()
    p.locator('[data-view="calendar"]').click()
    expect(p.locator('#calendar')).to_have_attribute('aria-busy', 'false')
    assert requests[-1]['period'] == ['calendar'] and requests[-1]['favorites'] == ['true']
    h.check('F77_calendar_uses_month_and_cancel_preserves_saved_only')

    for invalid in ['from=0000-01-01&until=0000-01-02', 'from=9999-12-30&until=9999-12-31']:
        count = len(requests)
        h.goto('?view=all&' + invalid)
        expect(p.locator('#notice')).to_contain_text('日期')
        expect(p.locator('#event-list')).to_have_attribute('aria-busy', 'false')
        assert len(requests) == count
    h.check('F77_unsupported_years_fail_before_query')
