"""Real isolated API/SQLite contracts for #94/#95; no publisher requests."""
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from radar import api, core
from ux_calendar_fixture import seed


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    (tmp_path/'static').mkdir()
    (tmp_path/'sources.json').write_text('[{"id":"ux-fixture","name":"合成样本","url":"https://example.com","priority":10}]')
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(api, 'ROOT', tmp_path)
    monkeypatch.setattr(core, 'now', lambda: datetime(2026, 10, 4, tzinfo=core.TZ))
    api.initialize_settings(); core.init(); ids = seed(core)
    with TestClient(api.app, base_url='https://testserver') as client:
        client.cookies.set(api.COOKIE, api.sign_session({'id': 1, 'username': 'ux-fixture'}), path='/events')
        yield client, ids


def query(client, **extra):
    params={'q':'UX', 'period':'calendar', 'start':'2026-10-01', 'end':'2026-11-01', 'hide_long':'true', 'limit':500}
    params.update(extra)
    response=client.get('/events/api/events', params=params)
    assert response.status_code == 200
    return response.json()


def facet(result, kind, value):
    return next(x['count'] for x in result['facets'][kind] if x['value']==value)


def test_culture_then_all_participation_keeps_other_dimensions(fixture):
    client, ids=fixture
    assert query(client)['total']==5
    culture=query(client, topic='文化艺术')
    assert culture['total']==4 and culture['excluded_long']['total']==1
    online=query(client, topic='文化艺术', attendance='online')
    assert {e['id'] for e in online['items']}=={ids['art-online'],ids['art-hybrid']}
    again=query(client, topic='文化艺术', attendance='all')
    assert [e['id'] for e in again['items']]==[e['id'] for e in culture['items']]
    assert again['facets']==culture['facets']


def test_unselected_overlapping_topic_is_not_a_negative_filter(fixture):
    client, ids=fixture
    result=query(client, topic=['机器人','社交交流'])
    assert {e['id'] for e in result['items']}=={ids['robot'],ids['art-hybrid']}
    assert '文化艺术' in next(e['topics'] for e in result['items'] if e['id']==ids['art-hybrid'])
    # Facet counts omit only their own selection, so they are not additive totals.
    assert facet(result,'topic','文化艺术')==4
    assert result['facets']['scope']=='other_applied_filters'


def test_same_dimension_or_other_dimension_and_and_empty_recovery(fixture):
    client, ids=fixture
    result=query(client, type=['ExhibitionEvent','MusicEvent'], topic=['文化艺术','机器人'])
    assert result['total']==4
    music=query(client, type='MusicEvent', topic='文化艺术')
    assert [e['id'] for e in music['items']]==[ids['art-hybrid']]
    assert facet(music,'type','ExhibitionEvent')==3 and facet(music,'type','MusicEvent')==1
    none=query(client, topic_none='true')
    assert none['total']==0 and none['excluded_long']['total']==0
    assert facet(none,'topic','文化艺术')==4
    assert query(client)['total']==5


def test_long_and_free_counts_match_current_filters_without_hidden_records(fixture):
    client, ids=fixture
    shown=query(client, hide_long='false')
    assert shown['total']==7
    assert sum(e['long_running'] for e in shown['items'])==2
    assert shown['excluded_long']['total']==0
    free=query(client, topic='文化艺术', free='true')
    assert free['total']==3 and free['excluded_long']['total']==1
    assert query(client, topic='文化艺术', free='true', hide_long='false')['total']==4
    assert ids['hidden'] not in {e['id'] for e in shown['items']}


def test_month_boundary_favorites_and_all_day_ics_survive(fixture):
    client, ids=fixture
    october=query(client)
    assert ids['cross'] in {e['id'] for e in october['items']}
    assert ids['next'] not in {e['id'] for e in october['items']}
    november=query(client, start='2026-11-01',end='2026-12-01',hide_long='false')
    assert {e['id'] for e in november['items']}=={ids['next'],ids['favorite-long']}
    assert query(client, favorites='true')['total']==1
    assert query(client, favorites='true',hide_long='false')['total']==2
    saved=query(client, period='saved',start='',end='')
    assert {e['id'] for e in saved['items']}=={ids['art-offline'],ids['favorite-long'],ids['undated']}
    ics=client.get('/events/api/event/'+ids['cross']+'.ics')
    assert ics.status_code==200
    assert 'DTSTART;VALUE=DATE:20260930' in ics.text and 'DTEND;VALUE=DATE:20261002' in ics.text


def test_reading_filter_sequences_preserves_all_personal_rows(fixture):
    client, ids=fixture
    with core.db() as c: before=[tuple(row) for row in c.execute('SELECT * FROM preferences ORDER BY event_id')]
    for changes in ({},{'topic':'文化艺术'},{'type_none':'true'},{'hide_long':'false'},{'attendance':'online'},{'attendance':'all'},{'favorites':'true'}):
        query(client, **changes)
    with core.db() as c: after=[tuple(row) for row in c.execute('SELECT * FROM preferences ORDER BY event_id')]
    assert before==after
