from review_harness import Harness
from playwright.sync_api import expect
h=Harness('review-recovery');p=h.page
try:
    # Keep one healthy and one problematic source in an isolated status snapshot.
    with h.core.db() as c:
        c.execute("UPDATE source_health SET status='ok',raw_count=5,name='正常来源' WHERE id='a'")
        c.execute("INSERT INTO source_health(id,name,url,status,message) VALUES('broken','失败来源','https://example.com/broken','error','上次读取失败')")
    h.goto();before=p.locator('.title-button').all_inner_texts()
    def fail(route):route.fulfill(status=503,json={'detail':'隔离故障'})
    p.route('**/events/api/events?*',fail)
    p.locator('#refresh-data').click();expect(p.locator('#notice')).to_contain_text('上次结果')
    expect(p.locator('.event-card')).to_have_count(5);h.check('E11_same_query_keeps_cards',p.locator('.title-button').all_inner_texts()==before)
    p.locator('#search').fill('新查询');p.locator('#search').press('Enter');expect(p.locator('#result-count')).to_have_text('加载失败')
    expect(p.locator('.event-card')).to_have_count(0);h.check('E11_different_query_never_mislabeled')
    p.unroute('**/events/api/events?*',fail);p.locator('#clear-filters').click();expect(p.locator('.event-card')).to_have_count(5)
    h.check('E11_manual_retry_recovers')
    from datetime import timedelta
    month=(h.core.now()+timedelta(days=2)).strftime('%Y-%m-01')
    h.goto('?view=calendar&month='+month);expect(p.locator('#calendar')).to_have_attribute('aria-busy','false');count=p.evaluate('calendar.getEvents().length')
    p.route('**/events/api/events?*',fail);p.locator('#refresh-data').click();expect(p.locator('#result-count')).to_contain_text('刷新失败');h.check('E11_same_month_preserved',p.evaluate('calendar.getEvents().length')==count)
    # The next month must not display the retained previous month's data as its own.
    p.locator('.fc-next-button').click();expect(p.locator('#result-count')).to_have_text('日历加载失败');h.check('E11_other_month_not_reused',p.evaluate('calendar.getEvents().length')==0)
    p.unroute('**/events/api/events?*',fail)
    h.goto('?view=status');expect(p.locator('.source-card')).to_have_count(2)
    p.locator('#source-state').select_option('attention');expect(p.locator('.source-card:visible')).to_have_count(1);expect(p.locator('#source-match-count')).to_contain_text('1 / 2');h.check('E10_problem_only_filter')
    p.locator('.source-card:visible .source-inspection summary').click();p.locator('#source-search').fill('失败');p.locator('#refresh-status').click();expect(p.locator('#status-panel')).to_have_attribute('aria-busy','false')
    expect(p.locator('#source-search')).to_have_value('失败');expect(p.locator('#source-state')).to_have_value('attention');expect(p.locator('.source-card:visible .source-inspection')).to_have_js_property('open',True);h.check('E10_context_survives_refresh')
    p.route('**/events/api/status',fail);p.locator('#refresh-status').click();expect(p.locator('#source-snapshot')).to_contain_text('刷新失败');expect(p.locator('.source-card:visible')).to_have_count(1);h.check('E10_failed_refresh_retains_evidence')
    p.unroute('**/events/api/status',fail);p.locator('#reset-source-search').click();expect(p.locator('.source-card:visible')).to_have_count(2)
    p.locator('#source-search').fill('不存在');expect(p.locator('#source-empty')).to_be_visible();h.check('E10_empty_filter_is_explained')
    h.goto();writes=[];p.on('request',lambda r:writes.append(r.url) if r.method=='POST' else None)
    h.ctx.set_offline(True);expect(p.locator('#network-banner')).to_be_visible();expect(p.locator('#network-message')).to_contain_text('断开');h.check('E11_offline_banner_keeps_content',p.locator('.event-card').count()==5)
    h.ctx.set_offline(False);expect(p.locator('#network-message')).to_contain_text('恢复');h.check('E11_network_restore_never_replays_writes',not writes)
    p.locator('#network-retry').click();expect(p.locator('#event-list')).to_have_attribute('aria-busy','false')
    p.set_viewport_size({'width':390,'height':844});h.check('E10_E11_mobile_no_overflow',p.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    p.screenshot(path=str(h.out/'mobile.png'),full_page=True)
except Exception as exc:h.report['errors'].append(str(exc));raise
finally:h.close()
