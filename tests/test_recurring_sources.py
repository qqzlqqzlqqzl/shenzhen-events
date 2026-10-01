"""Public structural fixtures plus synthetic edge cases, through the worker path."""
import copy
import json
import signal
import time
from datetime import datetime
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from radar import api, core, coverage, collectors, geocode, recurring_sources as rs, worker

FIXTURES = Path(__file__).parent / 'fixtures' / 'recurring'
URLS = {'elecfans_webinar': 'https://webinar.elecfans.com/webinar/forthcoming.html',
        'xuanwu_activity': 'https://xuanwu.openatom.org/activity/',
        'shenzhenware_events': 'https://www.shenzhenware.com/events'}
MODULE = 'https://xuanwu.openatom.org/assets/activity_index.md.test123.lean.js'
REAL_SLEEP = time.sleep


def source(kind='elecfans_webinar', **kw):
    out = {'id': kind, 'name': kind, 'kind': kind, 'url': URLS[kind],
           'interval_hours': 12, 'priority': 15, 'coverage_mode': 'page_inventory',
           'max_pages': 5, 'max_entries': 100, 'max_seconds': 10,
           'request_delay': 0, 'detail_budget': 0, 'allow_online': True}
    out.update(kw)
    return out


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    (tmp_path / 'static').mkdir()
    (tmp_path / 'static' / 'index.html').write_text('<html></html>')
    (tmp_path / 'sources.json').write_text(json.dumps([source(k) for k in URLS]))
    for obj in (core, api, worker):
        monkeypatch.setattr(obj, 'ROOT', tmp_path)
    monkeypatch.setattr(core, 'now', lambda: datetime(2026, 10, 1, 12, tzinfo=core.TZ))
    monkeypatch.setattr(worker, 'now', core.now)
    monkeypatch.setattr(coverage.time, 'sleep', lambda _: None)
    api.initialize_settings()
    core.init()
    return tmp_path


def soup(text):
    return BeautifulSoup(text, 'html.parser')


def fixture(name):
    return (FIXTURES / name).read_text()


def module(rows):
    return 'const activities=JSON.parse(' + chr(96) + json.dumps(rows, ensure_ascii=False) + chr(96) + ');'


def fetch_stub(monkeypatch, pages):
    calls = []
    def fetch(url, **kw):
        calls.append((url, kw))
        value = pages[url]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            text, final = value
        else:
            text, final = value, url
        return text, soup(text), final
    monkeypatch.setattr(collectors, 'fetch', fetch)
    return calls


def xrows():
    return json.loads(fixture('xuanwu-shenzhen.json'))


def xindex(url=MODULE):
    return f'<link rel="modulepreload" href="{url}">'


def card(n, date='2026年9月9日-11日', location='深圳国际会展中心', title=None):
    return (f'<div class="event-item"><div class="card-meta"><a class="initial" href="/events/{n}">'
            f'{title or "硬件工作坊" + str(n)}</a></div><div class="card-times">{date}</div>'
            f'<div class="card-map">{location}</div><span class="status">已结束</span></div>')


def shpage(regular, hot=range(1, 7)):
    hot_html = ''.join(card(n).replace('event-item', 'activity') for n in hot)
    return '<div class="hot">' + hot_html + '</div><div class="regular-events-list">' + ''.join(card(n) for n in regular) + '</div>'


def base_event(**kw):
    row = collectors.skeleton('持续社区工作坊', 'https://www.shenzhenware.com/events/690',
        '公众活动说明保持不变', '深圳南山旧会场', city='深圳',
        start_at='2026-10-17T00:00:00+08:00', end_at='2026-10-18T00:00:00+08:00',
        all_day=True, details={'attendance': 'offline', 'source_status': '报名中'})
    row.update(kw)
    return row


def metrics():
    return {'detail_cached': 0, 'detail_deferred': 0, 'detail_attempted': 0,
            'detail_resolved': 0, 'detail_failed': 0, 'reasons': [], 'truncated': False}


def test_elec_three_public_cards_not_speakers_or_ads(monkeypatch):
    src = source()
    calls = fetch_stub(monkeypatch, {src['url']: fixture('elecfans.html')})
    report = coverage.collect_report(src)
    assert report['status'] == 'ok'
    assert len(report['items']) == 3 and report['coverage']['visible'] == 3
    assert len(calls) == 1
    for event in report['items']:
        assert not event['organizer'] and not event['cost_text']
        assert event['details']['attendance'] == 'online'
        assert event['details']['timezone_status'] == 'unconfirmed'
        assert event['all_day'] and event['start_at'].endswith('00:00:00+08:00')
        assert '时区' in event['details']['review_notes']
        core.ingest(src, event)
    assert len(core.events(attendance='online')) == 3
    assert core.events(free=True) == [] and core.events(attendance='offline') == []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(geocode, 'load_key', lambda: 'unit-test')
        mp.setattr(geocode, 'resolve_location', lambda *a, **k: pytest.fail('online geocoded'))
        assert geocode.enrich_pending()['skipped'] == 3


@pytest.mark.parametrize('kind,html', [('elecfans_webinar', '<div class="webinar-empty">暂无活动</div>'),
                                     ('shenzhenware_events', '<div class="regular-events-list"></div>')])
def test_recognized_empty_and_markup_drift(kind, html, monkeypatch):
    src = source(kind)
    fetch_stub(monkeypatch, {src['url']: html})
    assert coverage.collect_report(src)['coverage']['recognized_empty']
    fetch_stub(monkeypatch, {src['url']: '<form>登录 查看活动</form>'})
    report = coverage.collect_report(src)
    assert report['status'] == 'error' and report['error']


@pytest.mark.parametrize('href', ['https://evil.example/1056.html', 'http://webinar.elecfans.com/1056.html',
                                'https://user@webinar.elecfans.com/1056.html', '/webinar/signup.html'])
def test_detail_url_validation(href):
    assert not rs.event_url(href, URLS['elecfans_webinar'], 'elecfans_webinar')


def test_elec_replay_cancel_and_duplicate():
    html = fixture('elecfans.html')
    first = soup(html).select_one('li.bd-wrap')
    first.append(soup('<span class="status">已取消</span>'))
    second = copy.copy(first)
    third = copy.copy(first)
    third.select_one('a')['href'] = '/9999.html'
    third.select_one('.status').string = '回放'
    rows, visible, rejected = rs.elecfans_webinars(soup(str(first) + str(second) + str(third)), URLS['elecfans_webinar'])
    assert len(rows) == 1 and rows[0]['status'] == 'cancelled'
    assert visible == 3 and sum(rejected.values()) == 2


def test_xuanwu_dynamic_inventory_city_and_recap(monkeypatch):
    rows = xrows()
    assert len(rows) == 6
    foreign = copy.deepcopy(rows[0])
    foreign['frontmatter'].update(location='北京市', address='北京市会场', addressName='北京会场')
    inventory = rows + [{**foreign, 'url': f'/articles/activity/foreign-{n}.html'} for n in range(46)]
    src = source('xuanwu_activity')
    calls = fetch_stub(monkeypatch, {src['url']: xindex(), MODULE: module(inventory)})
    report = coverage.collect_report(src)
    parsed, count, rejected = rs.xuanwu_events(module(inventory), MODULE)
    assert count == report['coverage']['source_total'] == 52
    assert len(parsed) == 5 and rejected['其他城市或城市未确认'] == 46
    assert len(report['items']) == 2  # Future teaching event and September meetup inside retention.
    assert sum(e['start_at'] > core.iso(core.now()) for e in report['items']) == 1
    meetup = next(e for e in parsed if e['url'].endswith('260905-rust-shenzhen-meetup.html'))
    assert meetup['end_at'].endswith('17:30:00+08:00')
    assert meetup['status'] == 'needs_review' and meetup['details']['time_conflict']
    assert len(meetup['details']['recap_urls']) == 1
    assert all('lon' not in e and 'lat' not in e and not e['cost_text'] for e in parsed)
    assert len(calls) == 2 and report['coverage']['parser_unaccounted'] == 0


def test_xuanwu_hybrid_and_dates_never_replaced_by_post_date():
    rows, _, _ = rs.xuanwu_events(module(xrows()), MODULE)
    old = next(e for e in rows if '250322-' in e['url'])
    assert old['details']['attendance'] == 'hybrid'
    assert old['start_at'].startswith('2025-03-22')
    row = copy.deepcopy(xrows()[0])
    row['frontmatter'].update(startTime='2026-02-31 9:00:00', endTime='', createTime='2026-10-01')
    invalid = rs.xuanwu_events(module([row]), MODULE)[0][0]
    assert invalid['start_at'] is None and invalid['status'] == 'needs_review'
    row['frontmatter']['startTime'] = '2026-10-17'
    assert rs.xuanwu_events(module([row]), MODULE)[0][0]['start_at'] is None


def test_xuanwu_recap_requires_existing_matching_start_and_venue():
    rows = xrows()
    recap = next(r for r in rows if r['url'].endswith('-review.html'))
    recap['frontmatter']['address'] = '深圳另一个会场'
    parsed, _, _ = rs.xuanwu_events(module(rows), MODULE)
    meetup = next(e for e in parsed if e['url'].endswith('260905-rust-shenzhen-meetup.html'))
    assert not meetup['details'].get('recap_urls') and meetup['status'] == 'scheduled'


@pytest.mark.parametrize('literal', ['[]+alert(1)', '[NaN]', '[{"url":"a","url":"b"}]',
                                    '$' + '{process.exit()}', '[{"frontmatter":{"type":"news"},"url":"a"}]'])
def test_module_literals_fail_closed(literal):
    with pytest.raises(collectors.SourceError):
        rs.module_inventory('JSON.parse(' + chr(96) + literal + chr(96) + ')', MODULE)


def test_discovery_rejects_cross_origin_and_ambiguous_modules():
    assert rs.discover_module(soup(xindex()), URLS['xuanwu_activity']) == MODULE
    with pytest.raises(collectors.SourceError):
        rs.discover_module(soup(xindex(MODULE.replace('xuanwu.openatom.org', 'evil.example'))), URLS['xuanwu_activity'])
    with pytest.raises(collectors.SourceError):
        rs.discover_module(soup(xindex() + xindex(MODULE.replace('test123', 'new456'))), URLS['xuanwu_activity'])


def test_module_redirect_failure_keeps_worker_last_good(monkeypatch):
    src = source('xuanwu_activity')
    with core.db() as db:
        db.execute('UPDATE source_health SET raw_count=5,last_success=?,coverage=? WHERE id=?',
                   ('2026-09-30', json.dumps({'visible': 52, 'admitted': 5}), src['id']))
    fetch_stub(monkeypatch, {src['url']: xindex(), MODULE: (module(xrows()), 'https://evil.example/x')})
    assert worker.collect_source(src)['status'] == 'error'
    with core.db() as db:
        h = dict(db.execute('SELECT * FROM source_health WHERE id=?', (src['id'],)).fetchone())
    assert h['raw_count'] == 5 and h['last_success'] == '2026-09-30' and h['failure_count'] == 1


def test_shenzhenware_fixed_hot_rows_do_not_stop_regular_pagination(monkeypatch):
    src = source('shenzhenware_events')
    u = src['url']
    calls = fetch_stub(monkeypatch, {u: shpage(range(7, 13)), u+'?page=2': shpage(range(13, 19)),
                                   u+'?page=3': shpage([])})
    report = coverage.collect_report(src)
    assert len(report['items']) == report['coverage']['unique'] == 18
    assert report['coverage']['visible'] == 30 and report['coverage']['duplicates'] == 12
    assert len(calls) == 3 and report['status'] == 'ok'
    assert sum(e['start_at'] > core.iso(core.now()) for e in report['items']) == 0


def test_shenzhenware_cap_repeat_and_later_page_block(monkeypatch):
    src = source('shenzhenware_events', max_pages=1)
    u = src['url']
    fetch_stub(monkeypatch, {u: shpage(range(7, 13))})
    capped = coverage.collect_report(src)
    assert capped['status'] == 'partial' and capped['coverage']['next_cursor'] == u+'?page=2'
    src['max_pages'] = 5
    fetch_stub(monkeypatch, {u: shpage(range(7, 13)), u+'?page=2': shpage(range(7, 13))})
    repeated = coverage.collect_report(src)
    assert repeated['coverage']['pages_visited'] == 2 and repeated['status'] == 'partial'
    fetch_stub(monkeypatch, {u: shpage(range(7, 13)), u+'?page=2': collectors.Blocked('HTTP 429')})
    partial = worker.collect_source(src)
    assert partial['status'] == 'partial' and partial['count'] == 12
    with core.db() as db:
        assert db.execute('SELECT failure_count FROM source_health WHERE id=?', (src['id'],)).fetchone()[0] == 1


@pytest.mark.parametrize('date,start,end', [('2026 年 12 月 31 日-1 月 2 日', '2026-12-31', '2027-01-03'),
                                         ('2026.10.17', '2026-10-17', '2026-10-18')])
def test_shenzhenware_exclusive_all_day_range(date, start, end):
    rows, _, _ = rs.shenzhenware_events(soup('<div class="regular-events-list">'+card(9, date)+'</div>'), URLS['shenzhenware_events'])
    assert rows[0]['start_at'].startswith(start) and rows[0]['end_at'].startswith(end)
    assert rows[0]['all_day']


def test_shenzhenware_unknown_city_not_title_inferred_and_year_not_guessed(monkeypatch):
    src = source('shenzhenware_events')
    html = '<div class="regular-events-list">'+card(9, '10月17日', '地址待通知', '深圳创新工作坊')+'</div>'
    fetch_stub(monkeypatch, {src['url']: html, src['url']+'?page=2': '<div class="regular-events-list"></div>'})
    parsed = rs.shenzhenware_events(soup(html), src['url'])[0][0]
    assert parsed['start_at'] is None and not parsed['city']
    assert coverage.collect_report(src)['items'] == []


def test_shenzhenware_detail_conflict_scoped_organizer_and_modal_fee():
    event = base_event(start_at='2026-05-16T00:00:00+08:00', end_at='2026-05-17T00:00:00+08:00')
    patch = rs.detail('shenzhenware_events', event, soup(fixture('shenzhenware-conflict.html')), event['url'])
    merged = rs.merge_detail(event, patch)
    assert merged['status'] == 'needs_review' and merged['details']['time_conflict']
    assert merged['all_day'] and merged['start_at'] == event['start_at']
    assert merged['organizer'] == '声网 x 深圳湾' and not merged.get('cost_text')
    assert '历史主办方' not in merged['details']['detail_text']
    assert len(merged['details']['time_evidence']) == 2


@pytest.mark.parametrize('field,new', [('start_at', '2026-10-20T00:00:00+08:00'),
                                     ('end_at', '2026-10-21T00:00:00+08:00'),
                                     ('location', '深圳福田新会场'), ('all_day', False), ('status', 'cancelled')])
def test_detail_cache_fingerprint_includes_schedule_and_venue(field, new):
    old = base_event()
    fresh = {**old, field: new}
    assert rs.detail_fingerprint(old) != rs.detail_fingerprint(fresh)


def test_patch_cache_never_overwrites_fresh_hold_conflict_cancel_or_schedule():
    fresh = base_event(status='cancelled', details={'attendance': 'hybrid', 'review_hold': True,
        'source_status': '已取消', 'time_conflict': True, 'review_notes': '新列表冲突'})
    patch = {'status': 'scheduled', 'location': '深圳旧会场',
             'details': {'attendance': 'offline', 'review_hold': False, 'time_conflict': False,
                         'source_status': '报名中', 'review_notes': '旧详情'}}
    merged = rs.merge_detail(fresh, patch)
    assert merged['status'] == 'cancelled' and merged['location'] == fresh['location']
    assert merged['details']['time_conflict'] and merged['details']['review_hold']
    assert merged['details']['source_status'] == '已取消' and merged['details']['attendance'] == 'hybrid'


def test_cache_hit_and_legacy_payload_rejection_then_real_ingest_updates(monkeypatch):
    src = source('shenzhenware_events', detail_budget=1, _deadline=time.monotonic()+10)
    old = base_event()
    patch = {'organizer': '真实主办', 'details': {'review_notes': '详情补充'}}
    with core.db() as db:
        db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?)',
                   (src['id'], old['url'], rs.detail_fingerprint(old), json.dumps({'patch': patch}),
                    'ok', core.stamp(), '2026-10-02T12:00:00+08:00'))
    m = metrics()
    cached = rs.enrich_details(src, [old], m, lambda *a, **k: pytest.fail('cache should hit'))[0]
    assert m['detail_cached'] == 1 and cached['organizer'] == '真实主办'
    assert core.ingest(src, cached)
    fresh = base_event(start_at='2026-10-20T00:00:00+08:00', end_at='2026-10-21T00:00:00+08:00',
                       location='深圳福田新会场', status='cancelled')
    calls = []
    def fetch(url, **kw):
        calls.append(url)
        text = '<div class="correlation-center medium-editor-content"><p>主办：真实主办</p></div>'
        return text, soup(text), url
    changed = rs.enrich_details(src, [fresh], metrics(), fetch)[0]
    assert calls and changed['start_at'] == fresh['start_at'] and changed['location'] == fresh['location']
    assert changed['status'] == 'cancelled' and core.ingest(src, changed)
    assert core.events() == []
    with core.db() as db:
        row = dict(db.execute('SELECT * FROM events').fetchone())
        assert row['start_at'] == fresh['start_at'] and row['status'] == 'cancelled'
        db.execute('UPDATE detail_cache SET fingerprint=?,payload=?',
                   (rs.detail_fingerprint(fresh), json.dumps(old)))
    calls.clear()
    assert rs.enrich_details(src, [fresh], metrics(), fetch)[0]['status'] == 'cancelled'
    assert calls  # A legacy full-event cache never wins over the new listing.


def test_manual_review_hold_survives_real_ingest_and_api_calendar():
    src, event = source('shenzhenware_events'), base_event()
    core.ingest(src, event)
    with core.db() as db:
        db.execute('UPDATE events SET details=?,status=?', (json.dumps({'review_hold': True}), 'needs_review'))
    updated = base_event(start_at='2026-10-22T00:00:00+08:00', end_at='2026-10-23T00:00:00+08:00')
    assert core.ingest(src, updated)
    with core.db() as db:
        row = dict(db.execute('SELECT * FROM events').fetchone())
        assert row['status'] == 'needs_review' and json.loads(row['details'])['review_hold']
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert core.events() == []
    with TestClient(api.app) as client:
        client.cookies.set(api.COOKIE, api.sign_session({'id': 1, 'username': 'test'}))
        assert client.get('/events/api/events').json()['total'] == 0
        calendar = client.get('/events/calendar.ics')
        assert calendar.status_code == 200 and 'BEGIN:VEVENT' not in calendar.text


def test_distinct_colocated_events_and_hybrid_both_filters():
    src = source('xuanwu_activity')
    a = base_event(title='Rust语言教学研讨会', details={'attendance': 'hybrid'})
    b = base_event(title='机器人电机调试交流', url='https://www.shenzhenware.com/events/691', details={'attendance': 'offline'})
    core.ingest(src, a)
    core.ingest(src, b)
    assert len(core.events()) == 2
    assert len(core.events(attendance='online')) == 1 and len(core.events(attendance='offline')) == 2


def test_hard_deadline_interrupts_fetch_and_restores_alarm(monkeypatch):
    monkeypatch.setattr(time, 'sleep', REAL_SLEEP)
    old_handler = signal.getsignal(signal.SIGALRM)
    def slow(*a, **kw):
        time.sleep(.2)
        pytest.fail('deadline did not interrupt')
    with pytest.raises(rs.Deadline):
        rs.bounded_fetch(slow, URLS['elecfans_webinar'], source(), time.monotonic()+.03, {})
    assert signal.getsignal(signal.SIGALRM) == old_handler
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


@pytest.mark.parametrize('code', [403, 429])
def test_blocked_source_retains_inventory_and_worker_backoff(monkeypatch, code):
    src = source()
    with core.db() as db:
        db.execute('UPDATE source_health SET raw_count=3,last_success=? WHERE id=?', ('2026-09-30', src['id']))
    fetch_stub(monkeypatch, {src['url']: collectors.Blocked(f'HTTP {code}')})
    result = worker.collect_source(src)
    assert result['status'] == 'blocked'
    with core.db() as db:
        h = dict(db.execute('SELECT * FROM source_health WHERE id=?', (src['id'],)).fetchone())
    assert h['raw_count'] == 3 and h['last_success'] == '2026-09-30'
    assert h['failure_count'] == 1 and h['next_attempt'].startswith('2026-10-02')


def test_real_worker_registers_and_ingests_three_elec_items(monkeypatch):
    src = source()
    fetch_stub(monkeypatch, {src['url']: fixture('elecfans.html')})
    result = worker.collect_source(src)
    assert result['count'] == result['changed'] == 3
    with core.db() as db:
        assert db.execute('SELECT COUNT(*) FROM source_health').fetchone()[0] == 3
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 3
        assert db.execute('SELECT COUNT(*) FROM event_sources').fetchone()[0] == 3
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    assert worker.collect_source(src)['changed'] == 0


def test_unknown_end_is_not_invented_and_module_arrays_are_separate():
    row = copy.deepcopy(xrows()[0])
    row['frontmatter']['endTime'] = ''
    text = module([row]) + ';const news=JSON.parse(' + chr(96) + '[{"type":"news"}]' + chr(96) + ');'
    event = rs.xuanwu_events(text, MODULE)[0][0]
    assert event['end_at'] is None and not event['all_day']
    assert event['start_at'].endswith('09:30:00+08:00')


def test_new_same_key_conflict_changes_ingest_and_blocks_single_ics():
    src, old = source('shenzhenware_events'), base_event()
    core.ingest(src, old)
    fresh = base_event(details={'attendance': 'offline', 'time_conflict': True,
                               'review_notes': '新列表出现时钟冲突'})
    merged = rs.merge_detail(fresh, {'details': {'time_conflict': False}})
    assert merged['status'] == 'needs_review' and core.ingest(src, merged)
    with core.db() as db:
        eid = db.execute('SELECT id FROM events').fetchone()[0]
    with TestClient(api.app) as client:
        client.cookies.set(api.COOKIE, api.sign_session({'id': 1, 'username': 'test'}))
        assert client.get(f'/events/api/event/{eid}.ics').status_code == 409
        assert 'BEGIN:VEVENT' not in client.get('/events/calendar.ics').text


def test_timed_detail_end_conflict_keeps_fresh_range():
    fresh = base_event(start_at='2026-10-17T14:00:00+08:00', end_at='2026-10-17T17:30:00+08:00', all_day=False)
    merged = rs.merge_detail(fresh, {'start_at': fresh['start_at'], 'end_at': '2026-10-17T17:15:00+08:00', 'all_day': False})
    assert merged['end_at'] == fresh['end_at'] and merged['status'] == 'needs_review'


def test_single_session_clock_cannot_collapse_multiday_source_range():
    fresh = base_event(end_at='2026-10-20T00:00:00+08:00')
    patch = {'start_at': '2026-10-17T14:00:00+08:00', 'end_at': '2026-10-17T17:30:00+08:00', 'all_day': False}
    merged = rs.merge_detail(fresh, patch)
    assert merged['start_at'] == fresh['start_at'] and merged['end_at'] == fresh['end_at']
    assert merged['all_day'] and merged['status'] == 'needs_review'


def test_detail_budget_rotates_and_delay_respects_deadline():
    src = source('xuanwu_activity', detail_budget=1, _deadline=time.monotonic()+10)
    rows = [base_event(url=f'https://xuanwu.openatom.org/articles/activity/test-{n}.html') for n in range(3)]
    def fetch(url, **kw):
        text = '<div class="vp-doc"><p>主办方：开源社区</p></div>'
        return text, soup(text), url
    first, second = metrics(), metrics()
    rs.enrich_details(src, rows, first, fetch)
    rs.enrich_details(src, rows, second, fetch)
    assert first['detail_attempted'] == 1 and first['detail_deferred'] == 2
    assert second['detail_cached'] == second['detail_attempted'] == 1
    with pytest.raises(rs.Deadline):
        rs.pause(source(request_delay=1), time.monotonic()+.01)


def test_explicit_fee_and_timed_all_day_ics_boundary():
    src, event = source('shenzhenware_events'), base_event()
    text = '<div class="correlation-center medium-editor-content"><p>活动费用：免费</p></div>'
    patch = rs.detail(src['kind'], event, soup(text), event['url'])
    event = rs.merge_detail(event, patch)
    core.ingest(src, event)
    assert len(core.events(free=True)) == 1
    with TestClient(api.app) as client:
        client.cookies.set(api.COOKIE, api.sign_session({'id': 1, 'username': 'test'}))
        calendar = client.get('/events/calendar.ics').text
        assert 'DTSTART;VALUE=DATE:20261017' in calendar
        assert 'DTEND;VALUE=DATE:20261018' in calendar


def test_online_and_onsite_same_name_same_day_remain_distinct():
    src = source()
    online = base_event(location='线上', city='线上', details={'attendance': 'online'})
    onsite = base_event(url='https://www.shenzhenware.com/events/692', details={'attendance': 'offline'})
    core.ingest(src, online)
    core.ingest(source('shenzhenware_events'), onsite)
    assert len(core.events()) == 2


@pytest.mark.parametrize('mode', ['offline', 'hybrid', 'unknown'])
@pytest.mark.parametrize('reverse', [False, True])
def test_online_identity_guard_handles_serialized_database_details(mode, reverse):
    online = base_event(details={'attendance': 'online'}, location='线上')
    other = base_event(url='https://www.shenzhenware.com/events/692', details=json.dumps({'attendance': mode}))
    assert not core.is_duplicate(*( (other, online) if reverse else (online, other) ))


def test_hybrid_joins_onsite_only_with_specific_same_venue_and_organizer_or_clock():
    hybrid = base_event(details={'attendance': 'hybrid'})
    onsite = base_event(url='https://www.shenzhenware.com/events/693', details={'attendance': 'offline'})
    assert not core.is_duplicate(hybrid, onsite)
    hybrid['organizer'] = onsite['organizer'] = '开源社区'
    assert core.is_duplicate(hybrid, onsite)
    onsite['location'] = hybrid['location'] = '深圳（具体地址另行通知）'
    assert not core.is_duplicate(hybrid, onsite)
    hybrid = base_event(details={'attendance': 'hybrid'}, start_at='2026-10-17T14:00:00+08:00', all_day=False)
    onsite = base_event(url='https://www.shenzhenware.com/events/693', details=json.dumps({'attendance': 'offline'}), start_at=hybrid['start_at'], all_day=False)
    assert core.is_duplicate(hybrid, onsite)
    onsite['start_at'] = '2026-10-17T15:00:00+08:00'
    assert not core.is_duplicate(hybrid, onsite)


def test_exact_event_url_can_match_attendance_refinement():
    online = base_event(details={'attendance': 'online'}, location='线上')
    hybrid = base_event(details=json.dumps({'attendance': 'hybrid'}))
    assert core.is_duplicate(online, hybrid)


@pytest.mark.parametrize('location', [
    '广东省深圳市南山区', '中国广东省深圳市', '中华人民共和国广东省深圳市南山区',
    '中国广东深圳南山', '广东省深圳市南山区粤海街道', '上海市黄浦区',
    '深圳市南山区', '广西壮族自治区南宁市武鸣区',
])
@pytest.mark.parametrize('reverse', [False, True])
def test_administrative_locality_is_not_specific_hybrid_venue(location, reverse):
    a = base_event(location=location, organizer='同一主办方', details={'attendance': 'hybrid'})
    b = base_event(location=location, organizer=a['organizer'], url='https://www.shenzhenware.com/events/694',
                   details=json.dumps({'attendance': 'offline'}))
    assert not core.is_duplicate(*( (b, a) if reverse else (a, b) ))


@pytest.mark.parametrize('location', [
    '广东省深圳市南山区伊敦酒店海汉厅', '深圳龙岗工业软件园',
    '深圳市南山区深圳大学粤海校区', '深圳市南山区某路100号2楼会议室',
])
def test_specific_hybrid_venue_still_matches_in_both_directions(location):
    a = base_event(location=location, organizer='同一主办方', details={'attendance': 'hybrid'})
    b = base_event(location=location, organizer=a['organizer'], url='https://www.shenzhenware.com/events/695',
                   details=json.dumps({'attendance': 'offline'}))
    assert core.is_duplicate(a, b) and core.is_duplicate(b, a)


def test_exact_event_evidence_still_matches_with_administrative_address():
    a = base_event(location='广东省深圳市南山区', details={'attendance': 'hybrid'})
    b = base_event(location=a['location'], details=json.dumps({'attendance': 'offline'}))
    assert core.is_duplicate(a, b) and core.is_duplicate(b, a)


@pytest.mark.parametrize('desc', [
    '本次活动不提供线上直播，仅限线下参加', '活动没有线上直播', '本次不会同步直播',
    '不安排同步线上直播', '本次不设线上直播', '线上直播已取消', '线上直播：已取消',
    '本次线上直播不会开放', '仅线下参加，并非线上直播', '本次未提供在线上观看的直播',
    '本次暂无线上直播', '活动不做线上直播',
])
def test_negated_live_broadcast_stays_offline_in_inventory_and_detail(desc):
    row = copy.deepcopy(xrows()[0])
    row['frontmatter']['desc'] = desc
    event = rs.xuanwu_events(module([row]), MODULE)[0][0]
    assert event['details']['attendance'] == 'offline'
    patch = rs.detail('xuanwu_activity', event, soup('<div class="vp-doc"><p>'+desc+'</p></div>'), event['url'])
    assert patch['details']['attendance'] == 'offline'
    enriched = rs.merge_detail(event, patch)
    core.ingest(source('xuanwu_activity'), enriched)
    assert core.events(attendance='online') == []
    assert len(core.events(attendance='offline')) == 1


@pytest.mark.parametrize('desc', [
    '现场活动将同步直播', '现场活动同时进行线上直播', '大家可在线上观看了直播',
    '不仅有线下活动，也有线上直播', '不仅支持线上直播，也可现场参加',
    '无需报名即可观看线上直播', '线上直播不需要报名', '线上直播不免费',
    '上次没有提供线上直播，但本次将同步直播',
])
def test_positive_live_broadcast_still_enriches_and_enters_both_filters(desc):
    row = copy.deepcopy(xrows()[0])
    row['frontmatter']['desc'] = '现场教学研讨'
    event = rs.xuanwu_events(module([row]), MODULE)[0][0]
    assert event['details']['attendance'] == 'offline'
    patch = rs.detail('xuanwu_activity', event, soup('<div class="vp-doc"><p>'+desc+'</p></div>'), event['url'])
    assert patch['details']['attendance'] == 'hybrid'
    assert rs._mode(desc, event['location']) == 'hybrid'
    core.ingest(source('xuanwu_activity'), rs.merge_detail(event, patch))
    assert len(core.events(attendance='online')) == len(core.events(attendance='offline')) == 1
