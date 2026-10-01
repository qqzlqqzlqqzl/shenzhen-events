"""Favorite-query planning and semantic regressions on disposable databases."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from radar import core
from radar.filtering import contextual_listing

INDEX = 'idx_preferences_favorite_nonzero'
SEM_JOIN = ' AND e.id IN (SELECT event_id FROM preferences WHERE favorite<>0)'
NOW = datetime(2026, 10, 3, 12, tzinfo=core.TZ)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    (tmp_path/'sources.json').write_text(json.dumps([
        {'id': 'a', 'name': 'Synthetic A', 'url': 'https://example.invalid'},
        {'id': 'b', 'name': 'Synthetic B', 'url': 'https://example.invalid'},
    ]))
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(core, 'now', lambda: NOW)
    core.init()
    return tmp_path


def seed(count, all_favorite=False):
    data = []
    for i in range(count):
        eid = f'row-{i:06}'
        start = NOW + timedelta(days=i % 13 - 6)
        end = start + timedelta(days=20 if i % 7 == 0 else 1)
        begin, finish = start.isoformat(), end.isoformat()
        if i % 5 == 0:
            begin, finish = start.astimezone(timezone.utc).isoformat(), None
        elif i % 11 == 0:
            begin, finish = None, None
        data.append((eid, eid, begin, finish, i % 2, 'cancelled' if i % 7 == 0 else 'scheduled',
                     'Hall', '南山' if i % 2 else '福田', 'Synthetic Org', 'Synthetic summary',
                     '["展览文化"]' if i % 3 else '["硬件创客"]', NOW.isoformat(),
                     'https://example.invalid/'+eid, 'source',
                     json.dumps({'attendance': ['online', 'offline', 'hybrid'][i % 3]})))
    with core.db() as c:
        c.executemany('''INSERT INTO events(id,title,start_at,end_at,all_day,status,location,district,
            organizer,summary,topics,last_seen,url,event_type_state,details,priority,commercial,event_type)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'normal','unknown','ConferenceEvent')''', data)
        c.executemany('INSERT INTO preferences(event_id,favorite,hidden,feedback,viewed_at) VALUES(?,?,?,?,?)',
                      [(r[0], 1 if all_favorite or i % 9 == 0 or i % 13 == 0 else None if i % 5 == 0 else 0,
                        int(i % 19 == 0), 'interested' if i % 3 == 0 else '', NOW.isoformat() if i % 4 else None)
                       for i, r in enumerate(data)])
        c.executemany("INSERT INTO event_sources(event_id,source_id,url) VALUES(?,'a',?)", [(r[0], r[12]) for r in data])
    return data


def observed(monkeypatch, *, old_predicate=False, variable_limit=None):
    original = core.db
    evidence = {'plans': [], 'max_parameters': 0}
    class Connection:
        def __init__(self, c):
            self.c = c
            if variable_limit is not None:c.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, variable_limit)
        def execute(self, sql, params=()):
            evidence['max_parameters'] = max(evidence['max_parameters'], len(params))
            if sql.startswith('SELECT e.*,COALESCE(p.favorite,0) favorite'):
                if old_predicate:sql = sql.replace(SEM_JOIN, '')
                evidence['plans'].extend(str(row[3]) for row in self.c.execute('EXPLAIN QUERY PLAN '+sql, params))
            return self.c.execute(sql, params)
        def __getattr__(self, key):return getattr(self.c, key)
    @contextmanager
    def db():
        with original() as c:yield Connection(c)
    monkeypatch.setattr(core, 'db', db)
    return evidence


def test_favorites_seek_marked_ids_without_event_scan(monkeypatch):
    seed(10020)
    with core.db() as c:
        c.execute('UPDATE preferences SET favorite=0')
        c.execute("UPDATE preferences SET favorite=1,hidden=0 WHERE event_id='row-010019'")
    evidence = observed(monkeypatch)
    result = core.events(period='saved', favorites=True)
    assert [e['id'] for e in result] == ['row-010019']
    assert any('SEARCH e ' in plan and 'id=?' in plan for plan in evidence['plans'])
    assert not any('SCAN e ' in plan for plan in evidence['plans'])
    assert any(INDEX in plan for plan in evidence['plans'])


def test_partial_index_migrates_idempotently_without_changing_preferences():
    seed(20)
    with core.db() as c:
        # Simulate an existing database from before the new index.
        c.execute('DROP INDEX IF EXISTS '+INDEX)
        before = [tuple(r) for r in c.execute('SELECT * FROM preferences ORDER BY event_id')]
    core.init()
    core.init()
    with core.db() as c:
        indexes = [dict(r) for r in c.execute('PRAGMA index_list(preferences)') if r['name'] == INDEX]
        assert len(indexes) == 1 and indexes[0]['partial'] == 1
        assert [tuple(r) for r in c.execute('SELECT * FROM preferences ORDER BY event_id')] == before
        assert 'WHERE favorite<>0' in c.execute('SELECT sql FROM sqlite_master WHERE name=?', (INDEX,)).fetchone()[0]


def test_no_favorites_returns_empty_without_searching_event_rows(monkeypatch):
    seed(20)
    with core.db() as c:c.execute('DELETE FROM preferences')
    evidence = observed(monkeypatch)
    assert core.events(period='saved', favorites=True) == []
    assert not any('SCAN e ' in plan for plan in evidence['plans'])


@pytest.mark.parametrize('options', [
    {}, {'sort': 'desc'}, {'include_hidden': True}, {'period': 'upcoming'}, {'period': 'past'},
    {'period': 'review'}, {'period': 'week'}, {'period': 'weekend'},
    {'period': 'calendar', 'range_start': '2026-10-01T00:00:00+08:00', 'range_end': '2026-10-10T00:00:00+08:00'},
    {'feedback': 'any'}, {'feedback': 'none'}, {'feedback': 'interested'}, {'viewed': 'seen'}, {'viewed': 'unseen'},
    {'topics_filter': ['文化艺术']}, {'attendance': 'online'}, {'attendance': 'offline'}, {'districts': ['南山']},
    {'hide_long': True}, {'query': 'ROW-'},
])
def test_favorite_results_and_contextual_counts_match_prior_predicate(monkeypatch, options):
    seed(120)
    options = {'period': 'saved', 'favorites': True, **options}
    actual = core.events(**options)
    with monkeypatch.context() as m:
        observed(m, old_predicate=True)
        expected = core.events(**options)
    assert actual == expected
    for filters in [{}, {'event_types': ['ConferenceEvent'], 'topics': ['文化艺术'], 'districts': ['南山'],
                        'hide_long': True, 'offset': 2, 'limit': 3},
                    {'type_none': True}, {'topic_none': True}, {'district_none': True}]:
        assert contextual_listing(actual, **filters) == contextual_listing(expected, **filters)


def test_many_favorites_do_not_expand_sql_parameters_or_duplicate_events(monkeypatch):
    seed(2500, all_favorite=True)
    with core.db() as c:
        c.execute('UPDATE preferences SET hidden=0')
        c.execute("UPDATE preferences SET favorite=NULL WHERE event_id='row-000001'")
        c.execute("UPDATE preferences SET favorite=0 WHERE event_id='row-000002'")
        c.execute("UPDATE preferences SET favorite=-1 WHERE event_id='row-000003'")
        c.execute("INSERT INTO event_sources(event_id,source_id,url) VALUES('row-000003','b','https://example.invalid/other-source')")
    # Seed a legacy orphan explicitly; normal ingestion has foreign keys enabled.
    with sqlite3.connect(core.ROOT/'data/events.sqlite3') as c:
        c.execute("INSERT INTO preferences(event_id,favorite) VALUES('missing-event',1)")
    evidence = observed(monkeypatch, variable_limit=300)
    actual = core.events(period='saved', favorites=True)
    assert len(actual) == len({e['id'] for e in actual}) == 2498
    target = next(e for e in actual if e['id'] == 'row-000003')
    assert target['favorite'] == -1 and len(target['sources']) == 2
    assert evidence['max_parameters'] == 256


def test_alias_redirect_privacy_and_all_day_boundary_survive_favorite_selection(isolated):
    seed(2, all_favorite=True)
    with core.db() as c:
        c.execute("UPDATE events SET start_at='2026-10-02T20:00:00+00:00',end_at=NULL,all_day=1,details=? WHERE id='row-000001'",
                  (json.dumps({'images': ['https://bad.example/image.png'], 'cached_images': {'https://bad.example/image.png': '/private/secret'}}),))
        c.execute("INSERT INTO event_redirects VALUES('old-id','row-000001')")
    (isolated/'dedupe_aliases.json').write_text(json.dumps([{
        'date': '2026-10-02', 'urls': ['https://example.invalid/row-000001'],
        'canonical': {'title': 'Canonical NEEDLE', 'location': '线上', 'topics': ['AI与开源']}}]))
    options = {'period': 'record', 'event_id': 'old-id', 'favorites': True,
               'query': 'canonical needle', 'topics_filter': ['AI与开源'], 'attendance': 'online'}
    actual = core.events(**options, range_start='2026-10-03T23:59:59+08:00', range_end='2026-10-04T00:00:00+08:00')
    assert [e['id'] for e in actual] == ['row-000001'] and actual[0]['details']['cached_images'] == {}
    assert core.events(**options, range_start='2026-10-04T00:00:00+08:00', range_end='2026-10-05T00:00:00+08:00') == []
    with core.db() as c:c.execute("UPDATE preferences SET hidden=1 WHERE event_id='row-000001'")
    assert core.events(**options) == []
    assert [e['id'] for e in core.events(**options, include_hidden=True)] == ['row-000001']


def test_favorite_and_source_links_share_snapshot_and_next_read_is_fresh(monkeypatch):
    seed(2, all_favorite=True)
    original = core._source_links
    changed = False
    def update_during_read(c, ids):
        nonlocal changed
        if not changed:
            changed = True
            with core.db() as writer:
                writer.execute("UPDATE preferences SET favorite=0,hidden=1 WHERE event_id='row-000001'")
                writer.execute("INSERT INTO event_sources(event_id,source_id,url) VALUES('row-000001','b','https://example.invalid/new-link')")
        return original(c, ids)
    monkeypatch.setattr(core, '_source_links', update_during_read)
    before = core.events(period='saved', favorites=True)
    assert [e['id'] for e in before] == ['row-000001'] and len(before[0]['sources']) == 1
    assert core.events(period='saved', favorites=True) == []
    current = core.events(period='record', event_id='row-000001', include_hidden=True)
    assert current[0]['hidden'] == 1 and len(current[0]['sources']) == 2


@pytest.mark.parametrize('event_id', ['row-000001', 'old-id'])
def test_exact_and_redirected_favorite_lookup_do_not_scan_favorite_set(monkeypatch, event_id):
    seed(2500, all_favorite=True)
    with core.db() as c:c.execute("INSERT INTO event_redirects VALUES('old-id','row-000001')")
    evidence = observed(monkeypatch)
    options = {'period': 'record', 'event_id': event_id, 'favorites': True}
    assert [e['id'] for e in core.events(**options)] == ['row-000001']
    assert any('SEARCH e ' in plan and 'id=?' in plan for plan in evidence['plans'])
    assert not any(INDEX in plan or 'LIST SUBQUERY' in plan for plan in evidence['plans'])
    with core.db() as c:c.execute("UPDATE preferences SET favorite=0 WHERE event_id='row-000001'")
    assert core.events(**options) == []
    with core.db() as c:c.execute("UPDATE preferences SET favorite=-1,hidden=1 WHERE event_id='row-000001'")
    assert core.events(**options) == []
    assert [e['id'] for e in core.events(**options, include_hidden=True)] == ['row-000001']
