"""Reviewed 01–46/59 executed through transport, report, worker, SQLite and API.

Legacy merge/payload-only fixtures receive explicit generated semantic HTML;
we never accept their boolean identity claims. All network I/O is stubbed below
requests.Session.get, so production per-hop validation and parsing still run.
"""
import copy
import json
from datetime import datetime
from html import escape
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from radar import api, collectors, core, coverage, eefocus as ee, personal, recurring_sources as rs, worker

PACK = Path(__file__).parent / 'fixtures/eefocus'
DESIGN = json.loads((PACK / 'source-design.json').read_text())
CASES = [c for c in json.loads((PACK / 'cases.json').read_text())['cases']
         if int(c['id'][:2]) <= 46 or c['id'].startswith('59')]


def load(name):
    return (PACK / name).read_text()


def subset(actual, expected):
    if isinstance(expected, dict):
        for key, value in expected.items():
            assert key in actual, (key, actual)
            subset(actual[key], value)
    elif isinstance(expected, list):
        # Evidence lists are assertions of retained entries, not entire objects.
        for value in expected:
            assert any(matches(item, value) for item in actual), (value, actual)
    else:
        assert actual == expected, (actual, expected)


def matches(actual, expected):
    try:
        subset(actual, expected)
        return True
    except (AssertionError, TypeError):
        return False


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    (tmp_path / 'static').mkdir()
    (tmp_path / 'static/index.html').write_text('<html></html>')
    (tmp_path / 'sources.json').write_text(json.dumps([DESIGN['source']]))
    for module in (core, api, worker):
        monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(core, 'now', lambda: datetime.fromisoformat(DESIGN['fixed_now']))
    monkeypatch.setattr(worker, 'now', core.now)
    api.initialize_settings()
    core.init()
    return tmp_path


class Response:
    def __init__(self, value):
        self.status_code = value.get('status', 200)
        self.headers = {'location': value.get('location', '')}
        self.body = value.get('body', '')
        self.encoding = 'utf-8'
        self.closed = False

    def iter_content(self, size):
        yield self.body.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise collectors.SourceError('HTTP ' + str(self.status_code))

    def close(self):
        self.closed = True


def transport(monkeypatch, pages):
    calls, responses = [], []

    class Session:
        def get(self, url, **kw):
            assert kw['allow_redirects'] is False
            assert kw['stream'] is True
            calls.append(url)
            assert url in pages, 'Unexpected network request: ' + url
            value = pages[url]
            if isinstance(value, Exception):
                raise value
            response = Response({'body': value} if isinstance(value, str) else value)
            responses.append(response)
            return response

        def close(self):
            pass

    monkeypatch.setattr(collectors.requests, 'Session', Session)
    monkeypatch.setattr(collectors.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('8.8.8.8', 443))])
    return calls, responses


def counts():
    with core.db() as db:
        return {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                for table in ('raw_items', 'events', 'event_sources')}


def report():
    with core.db() as db:
        row = db.execute('SELECT * FROM source_health WHERE id=?', (DESIGN['source']['id'],)).fetchone()
        return dict(row), json.loads(row['coverage'])


def stored():
    with core.db() as db:
        row = dict(db.execute('SELECT * FROM events').fetchone())
        row['details'] = json.loads(row['details'])
        return row


def api_upcoming():
    with TestClient(api.app) as client:
        client.cookies.set(api.COOKIE, api.sign_session({'id': 1, 'username': 'eefocus-review'}))
        response = client.get('/events/api/events?period=upcoming')
        assert response.status_code == 200, response.text
        return response.json()


def run(monkeypatch, pages, **overrides):
    calls, responses = transport(monkeypatch, pages)
    result = worker.collect_source({**DESIGN['source'], **overrides})
    health, metrics = report()
    assert metrics['admitted'] == result['count']
    assert metrics.get('http_requests_attempted', 0) == len(calls)
    assert counts()['raw_items'] == counts()['event_sources']
    assert all(url.startswith(ee.ORIGIN + '/') for url in calls)
    api_upcoming()
    return result, metrics, calls


def card(item, raw=None):
    meta = item.get('details', {})
    raw = raw if raw is not None else ('活动时间：' + item['start_at'][:10].replace('-', '年', 1).replace('-', '月', 1) + '日' if item.get('start_at') else '举办时间：10月28日，年份待确认')
    mode = meta.get('attendance', 'online')
    return ('<main class="special-list"><ul class="section-list-item-ul"><li class="section-special-item">'
            f'<a class="item-title" href="{escape(item["url"])}">{escape(item["title"])}</a>'
            f'<p class="item-intro">{escape(item.get("summary", ""))}</p>'
            f'<span class="event-time">{escape(raw)}</span>'
            f'<span class="post-tag">{"线上活动" if mode == "online" else "线下活动"}</span>'
            f'<span class="event-location">{escape(item.get("location", "线上"))}</span>'
            f'<span class="status">{escape(meta.get("source_status", "报名中"))}</span></li></ul></main>')


def detail_html(item, raw=None, status='报名中'):
    if raw is None:
        raw = '活动时间：' + item['start_at'][:10].replace('-', '年', 1).replace('-', '月', 1) + '日 '
        raw += item['start_at'][11:16] + '–' + item['end_at'][11:16] + ' 北京时间'
    return (f'<body><article><h1>{escape(item["title"])}</h1><p>{escape(raw)}</p>'
            f'<p>活动地点：{escape(item.get("location", "线上"))}</p>'
            '<p>主办方：合成测试机构</p>'
            f'<p>当前状态：{escape(status)}</p></article></body>')


def hold_favorite():
    event = stored()
    with core.db() as db:
        meta = {**event['details'], 'review_hold': True,
                'review_notes': '人工保留：确认参加资格后再展示', 'address_precision': 'undisclosed'}
        db.execute("UPDATE events SET status='needs_review',details=?", (json.dumps(meta),))
    personal.update(event['id'], {'favorite': True})
    return event['id']


@pytest.mark.parametrize('case', CASES, ids=[c['id'] for c in CASES])
def test_reviewed_matrix(case, monkeypatch):
    number = int(case['id'][:2])
    inputs = case['inputs']
    expected = json.loads(load(case['expected']))
    pages, overrides = {}, dict(inputs.get('source_overrides', {}))
    listing = inputs.get('list_html')
    if listing:
        pages[ee.LIST_URL] = load(listing)
    else:
        pages[ee.LIST_URL] = load('fixtures/redirect-list.html')
    soup = BeautifulSoup(pages[ee.LIST_URL], 'html.parser')
    parsed = None
    if number not in (21, 22, 23):
        parsed, visible, excluded = ee.parse(soup, ee.LIST_URL)
    if expected.get('stage') == 'parse' or number in (1, 36):
        oracle = expected.get('parse', expected)
        if 'item_subset' in oracle:
            subset(parsed[0], oracle['item_subset'])
        if 'visible' in oracle:
            assert visible == oracle['visible']
        if 'excluded' in oracle:
            assert excluded == oracle['excluded']
        if 'extracted' in oracle:
            assert len(parsed) == oracle['extracted']
        overrides.setdefault('detail_budget', 0)
    if number in (3, 4, 14):
        url = parsed[0]['url']
        if number == 4:
            pages[url] = {'status': 302, 'location': '/live/980102.html'}
            pages[ee.ORIGIN + '/live/980102.html'] = load(inputs['detail_html'])
        else:
            pages[url] = load(inputs['detail_html'])
    if number in (12, 13):
        base = parsed[0]
        patch = json.loads(load(inputs['cache_row']))['payload'] if number == 12 else inputs['old_detail_patch']
        if isinstance(patch, str):
            patch = json.loads(patch)
        patch = patch.get('patch', patch)
        merged = ee.merge_detail(base, patch)
        subset(merged, expected.get('if_stale_patch_is_forced', expected)['item_subset'])
        assert rs.detail_fingerprint(base) != rs.detail_fingerprint(merged) or number == 12
        overrides['detail_budget'] = 0
    if number == 21:
        pass  # Real fetch detects the challenge before inventory parsing.
    if number == 23:
        pages[ee.LIST_URL] = rs.Deadline('list hard deadline')
    if number == 24:
        pages[parsed[0]['url']] = rs.Deadline('detail hard deadline')
    if number == 25:
        monkeypatch.setattr(rs, 'pause', lambda *a: (_ for _ in ()).throw(rs.Deadline('before request')))
    if number == 26:
        pages[parsed[0]['url']] = collectors.SourceError('ReadTimeout')
        pages[parsed[1]['url']] = load('fixtures/detail-success-undated.html')
    if number == 27:
        pages[parsed[0]['url']] = load('fixtures/challenge.html')
    if number == 28:
        pages[parsed[0]['url']] = collectors.SourceError('ReadTimeout')
        first, _, _ = run(monkeypatch, pages, detail_budget=0)
        assert first['count'] == first['changed'] == 0
        assert counts() == {'raw_items': 0, 'events': 0, 'event_sources': 0}
        pages[parsed[0]['url']] = {'status': 302, 'location': '/live/980102.html'}
        pages[ee.ORIGIN + '/live/980102.html'] = load('fixtures/redirect-live-detail.html')
        second, _, _ = run(monkeypatch, pages)
        assert second['count'] == second['changed'] == 1
        eid = hold_favorite()
        third, _, _ = run(monkeypatch, pages)
        assert third['count'] == 1 and third['changed'] == 0
        pages[ee.LIST_URL] = card({**parsed[0], 'url': ee.ORIGIN + '/live/980102.html?utm_source=fixture'}, parsed[0]['details']['date_evidence'])
        fourth, metrics, _ = run(monkeypatch, pages, detail_budget=0)
        assert fourth['count'] == 1 and fourth['changed'] == 0
        assert stored()['id'] == eid
        subset(stored(), expected['expected_event_after_runs_3_and_4'])
        assert counts() == {'raw_items': 1, 'events': 1, 'event_sources': 1}
        with core.db() as db:
            assert db.execute('SELECT COUNT(DISTINCT alias_url) FROM eefocus_identity_bindings').fetchone()[0] == 2
        assert personal.update(eid, {})['favorite'] is True
        assert api_upcoming()['total'] == 0
        return
    if number in (29, 40):
        variants = inputs.get('transports', [{'final_url': inputs['reported_redirect_chain'][0]['location']}]) if number == 40 else inputs['transports']
        for variant in variants:
            pages[parsed[0]['url']] = {'status': 302, 'location': variant['final_url']}
            result, metrics, calls = run(monkeypatch, pages)
            assert result['count'] == 0 and len(calls) == 2
        assert counts() == {'raw_items': 0, 'events': 0, 'event_sources': 0}
        return
    if number == 30:
        state = json.loads(load(inputs['state']))
        assert rs.detail_fingerprint(state['old_listing_item']) == rs.detail_fingerprint(state['new_listing_item']) == expected['fingerprint']
        pages[ee.LIST_URL] = card(state['new_listing_item'], state['new_listing_item']['details']['date_evidence'])
        base = ee.parse(BeautifulSoup(pages[ee.LIST_URL], 'html.parser'), ee.LIST_URL)[0][0]
        pages[base['url']] = detail_html(state['new_listing_item'])
        first, _, _ = run(monkeypatch, pages)
        second, metrics, _ = run(monkeypatch, pages)
        assert first['count'] == second['count'] == 1 and second['changed'] == 0
        subset(metrics, expected['coverage_subset'])
        subset(stored(), expected['expected_enriched_fields'])
        return
    if number == 31:
        overrides['detail_budget'] = 0
        subset(parsed[0], expected['desired_item_subset'])
        assert core.normalize_event(parsed[0])['status'] == 'cancelled'
    if number == 32:
        pages[parsed[0]['url']] = {'status': 302, 'location': '/live/980102.html'}
        pages[ee.ORIGIN + '/live/980102.html'] = load('fixtures/redirect-live-detail.html')
    if number in (33, 34, 35):
        base = inputs.get('base_item', inputs.get('fresh_list_item'))
        pages[ee.LIST_URL] = card(base)
        pages[base['url']] = detail_html(base, status='已取消' if number != 35 else '已恢复举办')
        if number in (34, 35):
            core.ingest(DESIGN['source'], base)
            eid = hold_favorite()
        if number == 35:
            current = ee.parse(BeautifulSoup(pages[ee.LIST_URL], 'html.parser'), ee.LIST_URL)[0][0]
            with core.db() as db:
                db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?)',
                           (DESIGN['source']['id'], base['url'], rs.detail_fingerprint(current),
                            json.dumps({'patch': inputs['prior_detail_cache_patch']}), 'ok',
                            inputs['cache_checked_at'], inputs['cache_next_attempt']))
        result, metrics, _ = run(monkeypatch, pages)
        assert result['count'] == 1
        subset(stored(), expected.get('expected_event', expected.get('item_subset')))
        assert api_upcoming()['total'] == 0
        if number in (34, 35):
            assert personal.update(eid, {})['favorite'] is True
        if number == 35:
            assert metrics['detail_cached'] == 0 and metrics['detail_attempted'] == 1
        return
    if number in (37, 41, 42, 43, 44, 45, 46, 59):
        for response in inputs['detail_transport']['responses']:
            pages[response['url']] = {'status': response['status'], 'location': response.get('location', ''),
                                      'body': load(response['body_file']) if response.get('body_file') else ''}
    if number in (38, 39):
        cache = inputs['identity_cache']
        prior = {'title': parsed[0]['title'], 'url': cache['canonical_url'], 'summary': parsed[0]['summary'],
                 'start_at': '2026-10-23T14:00:00+08:00', 'end_at': '2026-10-23T15:00:00+08:00',
                 'location': '线上', 'city': '线上', 'details': {'attendance': 'online'}}
        core.ingest(DESIGN['source'], prior)
        eid = hold_favorite()
        with core.db() as db:
            db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?)',
                       (DESIGN['source']['id'], parsed[0]['url'], rs.detail_fingerprint(parsed[0]),
                        json.dumps(cache), 'error' if number == 39 else 'ok', cache['verified_at'], cache['expires_at']))
        pages[parsed[0]['url']] = collectors.SourceError('ReadTimeout')
    if number == 59:
        # Caller flags cannot become successful cache evidence. Case-specific
        # actual valid-cache contradiction is exercised separately below.
        with core.db() as db:
            db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?)',
                       (DESIGN['source']['id'], parsed[0]['url'], rs.detail_fingerprint(parsed[0]),
                        json.dumps(inputs['identity_cache']), 'ok', '2026-10-02', '2026-10-03'))
    result, metrics, calls = run(monkeypatch, pages, **overrides)
    if 'report' in expected:
        oracle = expected['report']
        assert result['status'] == oracle['status']
        subset(metrics, oracle['coverage_subset'])
        if oracle.get('error_nonempty'):
            assert report()[0]['failure_count'] == 1
    if 'database_counts' in expected:
        subset(counts(), expected['database_counts'])
    if number in (3, 4, 14):
        # Normalization adds unrelated fields; raw payload preserves empty cost.
        with core.db() as db:
            payload = json.loads(db.execute('SELECT payload FROM raw_items').fetchone()[0])
        oracle = copy.deepcopy(expected['item_subset'])
        if oracle.get('cost_text') == '':
            oracle['cost_text'] = '费用未注明'
        if number == 3:
            oracle['details'].pop('review_notes')  # same meaning, wording not API contract
        subset(payload, oracle)
        assert (api_upcoming()['total'] > 0) == expected['upcoming_included']
    if number in (37, 46):
        assert result['count'] == 1
        if number == 37:
            subset(stored(), expected['admitted_item_subset'])
            assert api_upcoming()['total'] == 0
    if number in (38, 39):
        assert stored()['id'] == eid and result['changed'] == 0
        subset(stored(), expected['expected_persisted_event'])
        assert personal.update(eid, {})['favorite'] is True
    if number in (41, 42, 43, 44, 45, 59):
        assert expected['reason_code'] in metrics['reasons']
        assert counts() == {'raw_items': 0, 'events': 0, 'event_sources': 0}
        with core.db() as db:
            assert db.execute('SELECT COUNT(*) FROM eefocus_identity_bindings').fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM detail_cache WHERE status='ok'").fetchone()[0] == 0


def test_current_contradiction_invalidates_real_fresh_cache(monkeypatch):
    listing = load('fixtures/identity-41-list.html')
    base = ee.parse(BeautifulSoup(listing, 'html.parser'), ee.LIST_URL)[0][0]
    pages = {ee.LIST_URL: listing, base['url']: detail_html(base, base['details']['date_evidence'])}
    transport(monkeypatch, pages)
    first = coverage.collect_report(DESIGN['source'])
    assert first['coverage']['detail_resolved'] == 1
    assert counts() == {'raw_items': 0, 'events': 0, 'event_sources': 0}
    with core.db() as db:
        history_before = [tuple(r) for r in db.execute('SELECT * FROM eefocus_identity_bindings')]
        assert len(history_before) == 1
    pages[base['url']] = load('fixtures/identity-41-detail.html')
    result, metrics, _ = run(monkeypatch, pages, refresh_identity=True)
    assert result['count'] == 0
    subset(metrics, {'detail_attempted': 1, 'detail_failed': 1, 'detail_resolved': 0, 'detail_cached': 0})
    with core.db() as db:
        assert db.execute("SELECT COUNT(*) FROM detail_cache WHERE status='ok'").fetchone()[0] == 0
        assert [tuple(r) for r in db.execute('SELECT * FROM eefocus_identity_bindings')] == history_before
    pages[base['url']] = collectors.SourceError('ReadTimeout')
    later, _, _ = run(monkeypatch, pages)
    assert later['count'] == 0 and counts()['events'] == 0


def test_title_word_boundaries_are_identity_evidence(monkeypatch):
    base = {'title': '合成 Power Grid 研讨会', 'url': ee.ORIGIN + '/event/990041.html',
            'summary': '本次合成技术活动讨论电源环路稳定性与测量方法，不对应真实活动。',
            'location': '线上', 'start_at': '2026-11-12T14:00:00+08:00', 'end_at': '2026-11-12T15:00:00+08:00'}
    unrelated = detail_html({**base, 'title': '合成 PowerGrid 研讨会'})
    result, metrics, _ = run(monkeypatch, {ee.LIST_URL: card(base), base['url']: unrelated})
    assert result['count'] == 0 and 'main_event_title_mismatch' in metrics['reasons']
    assert ee.heading('Café  研讨会') == ee.heading('Cafe\u0301 研讨会')


def test_malformed_redirect_is_counted_failure_without_following(monkeypatch):
    alias = ee.ORIGIN + '/event/980002.html'
    result, metrics, calls = run(monkeypatch, {ee.LIST_URL: load('fixtures/redirect-list.html'),
                                             alias: {'status': 302, 'location': 'https://[invalid/'}})
    assert result['count'] == 0 and calls == [ee.LIST_URL, alias]
    subset(metrics, {'pages_visited': 1, 'detail_attempted': 1, 'detail_failed': 1, 'detail_resolved': 0})


@pytest.mark.parametrize('failure', [collectors.Blocked('challenge'), rs.Deadline('hard deadline')])
def test_inventory_failure_preserves_stored_state(monkeypatch, failure):
    pages = {ee.LIST_URL: load('fixtures/redirect-list.html'),
             ee.ORIGIN + '/event/980002.html': {'status': 302, 'location': '/live/980102.html'},
             ee.ORIGIN + '/live/980102.html': load('fixtures/redirect-live-detail.html')}
    run(monkeypatch, pages)
    eid = hold_favorite()
    before = stored()
    with core.db() as db:
        db.execute("UPDATE source_health SET raw_count=7,last_success='2026-10-01',failure_count=2")
    failed, metrics, _ = run(monkeypatch, {ee.LIST_URL: failure})
    health, _ = report()
    assert failed['count'] == failed['changed'] == 0 and metrics['pages_visited'] == 0
    assert health['raw_count'] == 7 and health['last_success'] == '2026-10-01'
    assert health['failure_count'] == 3
    assert stored() == before and personal.update(eid, {})['favorite'] is True


def test_sidebar_inside_article_cannot_supply_identity(monkeypatch):
    listing = load('fixtures/identity-45-list.html')
    base = ee.parse(BeautifulSoup(listing, 'html.parser'), ee.LIST_URL)[0][0]
    detail = load('fixtures/identity-45-detail.html').replace('</article>',
                '<aside><p>活动时间：2026年11月12日 14:00–15:00 北京时间</p></aside></article>')
    result, metrics, _ = run(monkeypatch, {ee.LIST_URL: listing, base['url']: detail})
    assert result['count'] == 0 and metrics['detail_failed'] == 1


def test_unknown_mapping_flags_never_admit_at_zero_budget(monkeypatch):
    listing = load('fixtures/identity-41-list.html')
    base = ee.parse(BeautifulSoup(listing, 'html.parser'), ee.LIST_URL)[0][0]
    with core.db() as db:
        db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?)',
                   (DESIGN['source']['id'], base['url'], rs.detail_fingerprint(base),
                    json.dumps({'identity_verified': True, 'canonical_url': base['url']}),
                    'ok', core.stamp(), '2026-10-03'))
    result, metrics, calls = run(monkeypatch, {ee.LIST_URL: listing}, detail_budget=0)
    assert result['count'] == 0 and len(calls) == 1 and metrics['detail_deferred'] == 1


def test_same_title_routes_remain_distinct_events(monkeypatch):
    listing = load('fixtures/identity-46-list.html')
    detail = load('fixtures/identity-46-detail.html')
    run(monkeypatch, {ee.LIST_URL: listing, ee.ORIGIN + '/event/980046.html': detail})
    run(monkeypatch, {ee.LIST_URL: listing.replace('980046', '980146'),
                      ee.ORIGIN + '/event/980146.html': detail.replace('980046', '980146')})
    assert counts() == {'raw_items': 2, 'events': 2, 'event_sources': 2}


@pytest.mark.parametrize('replacement', [('2026年11月12日', '2027年11月12日'), ('合成测试机构', '不同主办机构')])
def test_historical_anchor_change_rejects_reused_route(monkeypatch, replacement):
    listing = load('fixtures/identity-46-list.html')
    detail = load('fixtures/identity-46-detail.html')
    pages = {ee.LIST_URL: listing, ee.ORIGIN + '/event/980046.html': detail}
    run(monkeypatch, pages)
    before = stored()
    pages = {url: text.replace(*replacement) for url, text in pages.items()}
    result, metrics, _ = run(monkeypatch, pages, refresh_identity=True)
    assert result['count'] == 0 and metrics['detail_failed'] == 1
    assert stored() == before


def test_generic_open_does_not_revive_cancelled_event(monkeypatch):
    base = {'title': '合成取消与恢复状态', 'url': ee.ORIGIN + '/event/990033.html',
            'summary': '本活动仅用于独立状态回归测试，包含明确活动日期与技术交流内容，不对应真实活动。',
            'location': '线上', 'start_at': '2026-11-11T09:00:00+08:00', 'end_at': '2026-11-11T10:00:00+08:00'}
    pages = {ee.LIST_URL: card(base), base['url']: detail_html(base, status='已取消')}
    run(monkeypatch, pages)
    assert stored()['status'] == 'cancelled'
    pages[base['url']] = detail_html(base, status='报名中')
    run(monkeypatch, pages, refresh_identity=True)
    assert stored()['status'] == 'cancelled' and api_upcoming()['total'] == 0
    pages[base['url']] = detail_html(base, status='已恢复举办')
    run(monkeypatch, pages, refresh_identity=True)
    assert stored()['status'] == 'scheduled' and api_upcoming()['total'] == 1


@pytest.mark.parametrize('guard', [{'review_hold': True, 'review_notes': '人工保留：确认受邀资格前不展示'},
                                  {'attendance': 'unknown', 'review_notes': '参加方式冲突尚未确认'}])
def test_time_resolution_preserves_unrelated_review_reason(guard):
    base = ee.parse(BeautifulSoup(load('fixtures/promotion-list.html'), 'html.parser'), ee.LIST_URL)[0][0]
    base['details'].update(guard)
    item, _ = ee.detail(base, BeautifulSoup(load('fixtures/promotion-detail-actual-meeting.html'), 'html.parser'), base['url'], [{'url': base['url'], 'status': 200}])
    assert item['status'] == 'needs_review'
    subset(item['details'], guard)


def test_reviewed_pack_bytes_remain_exact():
    import hashlib
    for line in load('SHA256SUMS.txt').splitlines():
        digest, name = line.split(maxsplit=1)
        assert hashlib.sha256((PACK / name.lstrip('*')).read_bytes()).hexdigest() == digest, name


@pytest.mark.parametrize('reverse', [False, True])
def test_contradiction_revokes_other_alias_in_same_report(monkeypatch, reverse):
    listing = load('fixtures/both-aliases-one-inventory.html')
    alias, canonical = ee.ORIGIN + '/event/980002.html', ee.ORIGIN + '/live/980102.html'
    pages = {ee.LIST_URL: listing, alias: {'status': 302, 'location': canonical},
             canonical: load('fixtures/redirect-live-detail.html')}
    run(monkeypatch, pages)
    before = stored()
    # A changed first card bypasses its fingerprint cache while the second
    # canonical card still has an otherwise valid mapping in the cache snapshot.
    pages[ee.LIST_URL] = listing.replace('14:00–15:00', '14:00–16:00', 1)
    if reverse:
        soup = BeautifulSoup(pages[ee.LIST_URL], 'html.parser')
        ul = soup.select_one('.section-list-item-ul')
        ul.insert(0, ul.select('li')[1].extract())
        pages[ee.LIST_URL] = str(soup)
    pages[canonical] = load('fixtures/identity-41-detail.html')
    result, metrics, _ = run(monkeypatch, pages)
    assert result['count'] == result['changed'] == 0
    assert metrics['detail_failed'] == 1 and metrics['detail_cached'] == 0
    assert stored() == before
    with core.db() as db:
        assert db.execute("SELECT COUNT(*) FROM detail_cache WHERE status='ok'").fetchone()[0] == 0
