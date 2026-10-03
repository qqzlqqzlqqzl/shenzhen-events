"""Explicit date ranges intersect personal/lifecycle scopes without replacing them."""
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from radar import api, core


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path/'static').mkdir()
    (tmp_path/'sources.json').write_text('[]')
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(api, 'ROOT', tmp_path)
    monkeypatch.setattr(core, 'now', lambda: datetime(2026, 12, 1, tzinfo=core.TZ))
    api.initialize_settings()
    core.init()
    with TestClient(api.app, base_url='https://testserver') as c:
        c.cookies.set(api.COOKIE, api.sign_session({'id': 1, 'username': 'fixture'}), path='/events')
        yield c


@pytest.mark.parametrize('period', ['saved', 'feedback', 'history', 'review', 'past', 'upcoming'])
def test_explicit_range_is_validated_and_forwarded_in_every_scope(client, monkeypatch, period):
    calls = []
    snapshot=core.EventRows();snapshot.safety_epoch=0
    monkeypatch.setattr(api, 'events', lambda **kw: calls.append(kw) or snapshot)
    for start, end in [('', '2026-10-02'), ('2026-10-01', ''), ('bad', '2026-10-02'),
                       ('2026-02-30', '2026-03-03'), ('2026-10-02', '2026-10-01'),
                       ('2026-10-01', '2026-10-01'), ('2026-01-01', '2026-04-05')]:
        r = client.get('/events/api/events', params={'period': period, 'start': start, 'end': end})
        assert r.status_code == 400
    assert calls == []
    r = client.get('/events/api/events', params={'period': period, 'start': '2026-10-01', 'end': '2026-11-01'})
    assert r.status_code == 200
    assert calls[-1]['period'] == period
    assert calls[-1]['range_start'] == '2026-10-01T00:00:00+08:00'
    assert calls[-1]['range_end'] == '2026-11-01T00:00:00+08:00'
    assert calls[-1]['favorites'] == (period == 'saved')
    assert calls[-1]['feedback'] == ('any' if period == 'feedback' else '')
    assert calls[-1]['viewed'] == ('seen' if period == 'history' else 'all')
    assert client.get('/events/api/events', params={'period': period, 'start': '2026-01-01', 'end': '2026-04-04'}).status_code == 200


def seed():
    fixtures = [
        ('inside', '2026-10-05', '2026-10-06', 'scheduled'),
        ('outside', '2026-11-05', '2026-11-06', 'scheduled'),
        ('long', '2026-09-01', '2026-10-10', 'scheduled'),
        ('unknown', None, None, 'needs_review'),
        ('cancelled', '2026-10-08', '2026-10-09', 'cancelled'),
        ('review', '2026-10-09', '2026-10-10', 'needs_review'),
        ('boundary', '2026-09-30', '2026-10-01', 'scheduled'),
        ('hidden', '2026-10-05', '2026-10-06', 'scheduled'),
    ]
    with core.db() as c:
        for i, (title, start, end, status) in enumerate(fixtures):
            c.execute("INSERT INTO events(id,title,start_at,end_at,status,last_seen,summary,location,organizer,details,topics,event_type,event_type_state) VALUES(?,?,?,?,?,?,'','','','{}','[]','MusicEvent','source')",
                      (title, title, core.iso(start), core.iso(end), status, core.stamp()))
            c.execute('INSERT INTO preferences(event_id,favorite,hidden,feedback,viewed_at,feedback_updated_at) VALUES(?,?,?,?,?,?)',
                      (title, 1, int(title == 'hidden'), 'interested', f'2026-11-0{(i % 7)+1}T12:00:00+08:00', f'2026-11-0{(i % 7)+1}T12:00:00+08:00'))


@pytest.mark.parametrize('period', ['saved', 'feedback', 'history', 'review', 'past'])
def test_range_intersects_scope_status_order_counts_and_preserves_unfiltered_records(client, period):
    seed()
    params = {'period': period, 'hide_long': 'true'}
    unfiltered = client.get('/events/api/events', params=params).json()
    params.update(start='2026-10-01', end='2026-11-01')
    result = client.get('/events/api/events', params=params).json()
    expected = {'review'} if period == 'review' else {'inside', 'long', 'cancelled', 'review'}
    # Personal views include long intervals even when the general hide-long preference is set.
    if period in ('review', 'past'):
        expected.discard('long')
    assert {x['id'] for x in result['items']} == expected
    assert result['total'] == len(expected)
    assert sum(x['count'] for x in result['facets']['type']) == len(expected)
    assert all(x['favorite'] and x['feedback'] == 'interested' and x['viewed_at'] for x in result['items'])
    assert 'hidden' not in {x['id'] for x in unfiltered['items']}
    if period in ('saved', 'feedback', 'history'):
        assert {'unknown', 'outside', 'long'} <= {x['id'] for x in unfiltered['items']}
        assert result['excluded_long']['total'] == 0
    if period in ('feedback', 'history'):
        field = 'viewed_at' if period == 'history' else 'feedback_updated_at'
        values = [x[field] for x in result['items']]
        assert values == sorted(values, reverse=True)
