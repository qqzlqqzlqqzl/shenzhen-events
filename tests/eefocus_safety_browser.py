"""Real adapter → isolated DB/API → browser cache and personal-state acceptance."""
import json
import pytest
from playwright.sync_api import expect
from review_harness import Harness

h=Harness('eefocus-safety-browser');p=h.page;patch=pytest.MonkeyPatch()
try:
    from test_eefocus import DESIGN, load, transport
    from radar import collectors, core, eefocus as ee, worker
    # Extend only the ephemeral harness source registry; production sources.json
    # remains untouched. All publisher requests are below-Session stubs.
    sources=json.loads((h.tmp/'sources.json').read_text());sources.append(DESIGN['source'])
    (h.tmp/'sources.json').write_text(json.dumps(sources));core.init()
    alias=ee.ORIGIN+'/event/980002.html';canonical=ee.ORIGIN+'/live/980102.html'
    transport(patch,{ee.LIST_URL:load('fixtures/redirect-list.html'),alias:{'status':302,'location':canonical},canonical:load('fixtures/redirect-live-detail.html')})
    result=worker.collect_source(DESIGN['source']);assert result['count']==1
    with core.db() as c:
        eid=c.execute('SELECT event_id FROM event_sources WHERE source_id=?',(DESIGN['source']['id'],)).fetchone()[0]
        c.execute('INSERT INTO preferences(event_id,favorite,revision) VALUES(?,1,7)',(eid,))
        c.execute("UPDATE detail_cache SET next_attempt='2026-01-01'")
    h.goto();expect(p.locator(f'.event-card[data-event="{eid}"]')).to_have_count(1)
    p.locator(f'.event-card[data-event="{eid}"] .title-button').click()
    expect(p.locator('#detail a[href$=".ics"]')).to_have_count(1)
    p.locator('#close-detail').click()
    p.evaluate('(id)=>{RadarEventWorkflows.toggle(id);RadarEventWorkflows.toggle([...records.keys()].find(key=>key!==id));}',eid)
    # The source observation persists before a timed-out optional detail request.
    transport(patch,{ee.LIST_URL:load('fixtures/safety-cancelled-list.html'),alias:collectors.SourceError('ReadTimeout')})
    result=worker.collect_source(DESIGN['source']);assert result['count']==result['changed']==0 and result['guards_created']==1
    p.locator(f'.event-card[data-event="{eid}"] .title-button').click()
    expect(p.locator('#detail')).to_contain_text('来源显示已取消；当前活动身份待复核')
    expect(p.locator('#detail a[href$=".ics"]')).to_have_count(0)
    h.check('point_cache_revalidated_and_export_revoked')
    assert '来源显示已取消' in p.evaluate('(id)=>RadarEventWorkflows.shareText(records.get(id))',eid)
    h.check('copied_summary_carries_source_warning')
    p.locator('#detail [data-save]').click();expect(p.locator('#detail [data-save]')).to_have_attribute('aria-pressed','false')
    h.check('favorite_write_preserves_safety_metadata',p.evaluate('(id)=>records.get(id).planning_eligible===false && records.get(id).safety.guard_count===1',eid))
    p.locator('#close-detail').click();p.locator('#compare-open').click()
    expect(p.locator('#compare-dialog')).to_contain_text('来源显示已取消')
    h.check('comparison_revalidated_before_display');p.locator('#close-compare').click()
    p.locator('#refresh-data').click();expect(p.locator('#event-list')).to_have_attribute('aria-busy','false')
    expect(p.locator(f'.event-card[data-event="{eid}"]')).to_have_count(0)
    h.check('guarded_event_removed_from_current_planning_list')
    # An ordinary point-read failure cannot authorize a retained planning record.
    remaining=p.locator('.event-card').first.get_attribute('data-event')
    p.locator('.title-button').first.click();expect(p.locator('#detail a[href$=".ics"]')).to_have_count(1)
    p.locator('#close-detail').click()
    def fail_point(route):route.abort('failed')
    p.route('**/events/api/event/*',fail_point)
    p.locator('.title-button').first.click();expect(p.locator('#toast')).to_be_visible()
    h.check('ordinary_revalidation_failure_disables_cached_export',p.evaluate('(id)=>records.get(id)._safety_pending && records.get(id).planning_eligible===false',remaining))
    p.unroute('**/events/api/event/*',fail_point)
    # Typed availability failures invalidate append/calendar/comparison snapshots.
    def unavailable(route):route.fulfill(status=503,json={'code':'safety_unavailable','detail':'安全采集尚未完成'})
    p.route('**/events/api/events?*',unavailable);p.locator('#refresh-data').click()
    expect(p.locator('#event-list')).to_have_attribute('aria-busy','false')
    h.check('typed_failure_clears_actionable_snapshots',p.evaluate('listSnapshot===null && calendarSnapshot===null') and p.locator('a[href*=".ics"]').count()==0)
    p.unroute('**/events/api/events?*',unavailable);p.locator('#refresh-data').click();expect(p.locator('#event-list')).to_have_attribute('aria-busy','false')
    h.ctx.set_offline(True);expect(p.locator('#network-banner')).to_be_visible()
    h.check('offline_records_remain_unverified',p.evaluate('[...records.values()].every(row=>row._safety_pending && row.planning_eligible===false)'))
    h.ctx.set_offline(False)
    p.set_viewport_size({'width':390,'height':844});h.check('mobile_no_horizontal_overflow',p.evaluate('document.documentElement.scrollWidth<=innerWidth'))
    p.screenshot(path=str(h.out/'mobile-safety.png'),full_page=True)
except Exception as exc:h.report['errors'].append(str(exc));raise
finally:patch.undo();h.close()
