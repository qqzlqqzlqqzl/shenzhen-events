"""Upgrade regressions for legacy raw hashes and authoritative source typing."""
import json
from datetime import timedelta

import pytest

from radar import core, source_identity, worker


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    (tmp_path / 'sources.json').write_text(json.dumps([
        {'id': 'a', 'name': '测试源', 'url': 'https://example.com', 'priority': 10}
    ]))
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(worker, 'ROOT', tmp_path)
    monkeypatch.setattr(worker.time, 'sleep', lambda _: None)
    core.init()


SOURCE = {'id': 'a', 'priority': 10}


def legacy_record(event):
    """Reproduce the payload persisted before event taxonomy was introduced."""
    core.ingest(SOURCE, event)
    with core.db() as c:
        raw = dict(c.execute('SELECT * FROM raw_items').fetchone())
        payload = json.loads(raw['payload'])
        payload.pop('event_type')
        payload.pop('event_type_state')
        payload['topics'] = ['展览文化']
        c.execute("UPDATE raw_items SET payload=?,content_hash=?,analysis_state='done',ai_result=? WHERE id=?", (
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            source_identity.content_hash(SOURCE, payload, raw['body']),
            '{"existing_analysis":true}', raw['id']))
        c.execute("UPDATE events SET ai_state='done',topics=?", (json.dumps(['展览文化'], ensure_ascii=False),))
        return c.execute('SELECT id FROM events').fetchone()[0]


def snapshot():
    with core.db() as c:
        event = dict(c.execute('SELECT * FROM events').fetchone())
        event.pop('last_seen')
        return event, [tuple(r) for r in c.execute('SELECT * FROM preferences')], [tuple(r)[:4] for r in c.execute('SELECT * FROM event_sources')]


def test_unchanged_legacy_refresh_preserves_ai_dates_location_and_favorite(monkeypatch):
    event = {'title': '深圳音乐分享会', 'url': 'https://example.com/legacy',
             'summary': '活动时间：2026年10月3日，深圳南山区社区中心', 'location': ''}
    eid = legacy_record(event)
    with core.db() as c:
        c.execute("UPDATE events SET start_at=?,end_at=?,all_day=1,location=?,district='南山',status='scheduled',summary=?,reason=? WHERE id=?", (
            '2026-10-03T00:00:00+08:00', '2026-10-04T00:00:00+08:00',
            '深圳南山区社区中心', '已核实的活动资料', '已有参与理由', eid))
        c.execute('INSERT INTO preferences VALUES(?,1,0)', (eid,))
    core.init()
    before = snapshot()

    assert core.ingest(SOURCE, event) is False
    assert snapshot() == before
    with core.db() as c:
        raw = dict(c.execute('SELECT * FROM raw_items').fetchone())
        assert raw['analysis_state'] == 'done'
        assert raw['ai_result'] == '{"existing_analysis":true}'
        assert 'event_type' in json.loads(raw['payload'])
        assert c.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1
        assert c.execute('SELECT COUNT(*) FROM raw_items').fetchone()[0] == 1
    assert core.ingest(SOURCE, event) is False
    assert snapshot() == before

    def unexpected_analysis(rows):
        pytest.fail('An unchanged legacy source must not repeat full AI analysis')
    monkeypatch.setattr(worker, 'ai_batch', unexpected_analysis)
    monkeypatch.setattr(worker, 'type_batch', lambda rows: None)
    monkeypatch.setattr(worker, 'geocode_pending', lambda limit: {})
    worker.analyze(48)
    assert snapshot() == before


def test_legacy_refresh_adopts_new_source_type_without_full_reanalysis():
    start = (core.now() + timedelta(days=3)).isoformat()
    event = {'title': '深圳音乐会', 'url': 'https://example.com/music',
             'summary': '现场音乐会', 'location': '深圳音乐厅', 'start_at': start}
    legacy_record(event)
    core.init()
    before, preferences, links = snapshot()

    assert core.ingest(SOURCE, dict(event, event_type='MusicEvent')) is False
    after, after_preferences, after_links = snapshot()
    assert after['event_type'] == 'MusicEvent'
    assert after['event_type_state'] == 'source'
    for key in ('event_type', 'event_type_state'):
        before.pop(key)
        after.pop(key)
    assert after == before
    assert after_preferences == preferences and after_links == links
    with core.db() as c:
        assert c.execute('SELECT analysis_state FROM raw_items').fetchone()[0] == 'done'
    assert core.ingest(SOURCE, dict(event, event_type='MusicEvent')) is False


def test_real_source_edit_after_upgrade_still_queues_analysis():
    event = {'title': '深圳音乐会', 'url': 'https://example.com/music',
             'summary': '现场音乐会', 'location': '深圳音乐厅',
             'start_at': (core.now() + timedelta(days=3)).isoformat()}
    legacy_record(event)
    core.init()
    changed = dict(event, summary='主办方更新了活动内容与时间说明')
    assert core.ingest(SOURCE, changed) is True
    with core.db() as c:
        assert c.execute('SELECT analysis_state FROM raw_items').fetchone()[0] == 'pending'
        assert c.execute('SELECT ai_state FROM events').fetchone()[0] == 'pending'
