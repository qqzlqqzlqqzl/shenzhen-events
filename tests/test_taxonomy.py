from __future__ import annotations
import json
from datetime import timedelta
from bs4 import BeautifulSoup
import pytest
from fastapi.testclient import TestClient
from radar import core, api, worker, collectors

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    (tmp_path/'static').mkdir();(tmp_path/'static/index.html').write_text('<html>test</html>')
    (tmp_path/'sources.json').write_text(json.dumps([{'id':'a','name':'测试源','url':'https://example.com','priority':10,'interval_hours':6}]))
    monkeypatch.setattr(core,'ROOT',tmp_path);monkeypatch.setattr(api,'ROOT',tmp_path);monkeypatch.setattr(worker,'ROOT',tmp_path)
    api.initialize_settings();core.init();api.ATTEMPTS.clear()
    yield tmp_path

def src():return {'id':'a','priority':10}
def event(title,event_type='Event',topics=None,url=None):
    start=core.now()+timedelta(days=3)
    return {'title':title,'url':url or 'https://example.com/'+str(abs(hash(title))),'start_at':start.isoformat(),'end_at':(start+timedelta(hours=2)).isoformat(),'location':'深圳市南山区测试中心','summary':title+' 的活动说明','event_type':event_type,'topics':topics or ['其他'],'cost_text':'免费'}
def auth(c):c.cookies.set(api.COOKIE,api.sign_session({'id':1,'username':'owner'}),path='/events')

def test_schema_org_event_vocabulary_is_canonical():
    required={'ComedyEvent','TheaterEvent','MusicEvent','ExhibitionEvent','Hackathon','ConferenceEvent','SportsEvent','SocialEvent','Event'}
    assert required <= set(core.EVENT_TYPES)
    assert '展览文化' not in core.EVENT_TYPES
    assert core.EVENT_TYPES['ComedyEvent']=='喜剧 / 脱口秀'
    assert core.EVENT_TYPES['TheaterEvent']=='戏剧 / 话剧'

def test_jsonld_preserves_specific_schema_event_type():
    data={'@context':'https://schema.org','@type':'MusicEvent','name':'深圳音乐会','startDate':'2026-10-10T19:30:00+08:00','endDate':'2026-10-10T21:30:00+08:00','location':{'@type':'Place','name':'深圳音乐厅','address':{'addressLocality':'深圳'}}}
    soup=BeautifulSoup('<script type="application/ld+json">'+json.dumps(data,ensure_ascii=False)+'</script>','html.parser')
    result=collectors.jsonld(soup,'https://example.com/music')[0]
    assert result['event_type']=='MusicEvent'
    core.ingest(src(),result)
    row=core.events()[0]
    assert row['event_type']=='MusicEvent' and row['event_type_label']=='音乐 / 演唱会'
    with core.db() as c:assert c.execute('select event_type_state from events').fetchone()[0]=='source'

def test_generic_source_update_cannot_erase_specific_type():
    core.ingest(src(),event('深圳音乐会','MusicEvent',url='https://example.com/music'))
    newer=event('深圳音乐会','Event',url='https://example.com/music');newer['summary']='更新后的活动说明'
    core.ingest(src(),newer)
    row=core.events()[0]
    assert row['event_type']=='MusicEvent'
    with core.db() as c:assert c.execute('select event_type_state from events').fetchone()[0]=='source'

def test_ai_analysis_uses_schema_type_without_overriding_source(monkeypatch):
    core.ingest(src(),event('深圳脱口秀'))
    with core.db() as c:rid=c.execute('select id from raw_items').fetchone()[0]
    monkeypatch.setattr(worker,'ai_batch',lambda rows:[{'id':rid,'is_shenzhen_offline':True,'event_type':'ComedyEvent','topics':['文化艺术'],'priority':'normal','commercial':'low','reason':'现场喜剧演出','summary':'脱口秀专场'}])
    worker.analyze(1)
    row=core.events()[0]
    assert row['event_type']=='ComedyEvent' and row['event_type_state']=='ai'

def test_multiselect_or_within_group_and_and_across_groups():
    core.ingest(src(),event('AI脱口秀','ComedyEvent',['AI与开源']))
    core.ingest(src(),event('AI音乐会','MusicEvent',['AI与开源']))
    core.ingest(src(),event('机器人音乐会','MusicEvent',['机器人']))
    core.ingest(src(),event('博物馆展览','ExhibitionEvent',['文化艺术']))
    rows=core.events(event_types=['ComedyEvent','MusicEvent'],topics_filter=['AI与开源'])
    assert {x['title'] for x in rows}=={'AI脱口秀','AI音乐会'}
    rows=core.events(event_types=['MusicEvent'],topics_filter=['AI与开源','机器人'])
    assert {x['title'] for x in rows}=={'AI音乐会','机器人音乐会'}

def test_api_repeated_type_and_topic_params_and_facets():
    core.ingest(src(),event('脱口秀','ComedyEvent',['文化艺术']))
    core.ingest(src(),event('话剧','TheaterEvent',['文化艺术']))
    core.ingest(src(),event('机器人黑客松','Hackathon',['机器人','AI与开源']))
    with TestClient(api.app,base_url='https://testserver') as c:
        auth(c)
        r=c.get('/events/api/events?type=ComedyEvent&type=TheaterEvent')
        assert r.status_code==200 and {x['event_type'] for x in r.json()['items']}=={'ComedyEvent','TheaterEvent'}
        r=c.get('/events/api/events?type=Hackathon&topic=机器人')
        assert r.status_code==200 and r.json()['total']==1
        assert c.get('/events/api/events?type=MadeUpEvent').status_code==400
        stats=c.get('/events/api/stats').json()
        values={x['value']:x for x in stats['event_types']}
        assert values['ComedyEvent']['label']=='喜剧 / 脱口秀' and values['ComedyEvent']['count']==1
        assert any(x['value']=='机器人' and x['count']==1 for x in stats['topics'])

def test_legacy_topic_name_migrates_to_subject_tag():
    core.ingest(src(),event('旧文化活动','ExhibitionEvent',['文化艺术']))
    with core.db() as c:c.execute("update events set topics=?",(json.dumps(['展览文化'],ensure_ascii=False),))
    core.init()
    assert core.events()[0]['topics']==['文化艺术']

def test_type_backfill_uses_existing_budget_path(monkeypatch):
    core.ingest(src(),event('一场音乐会'))
    with core.db() as c:c.execute("update events set ai_state='done',event_type='Event',event_type_state='pending'")
    monkeypatch.setattr(worker,'type_batch',lambda rows:[{'id':rows[0]['id'],'event_type':'MusicEvent'}])
    assert worker.backfill_types(10)==1
    row=core.events()[0]
    assert row['event_type']=='MusicEvent'
    with core.db() as c:assert c.execute('select event_type_state from events').fetchone()[0]=='ai'

def test_generic_ai_classification_is_not_reset_by_source_refresh():
    core.ingest(src(),event('难以细分的社区活动','Event',url='https://example.com/generic'))
    with core.db() as c:c.execute("update events set event_type='Event',event_type_state='ai',ai_state='done'")
    refreshed=event('难以细分的社区活动','Event',url='https://example.com/generic');refreshed['summary']='来源更新后的说明'
    core.ingest(src(),refreshed)
    with core.db() as c:
        row=c.execute('select event_type,event_type_state from events').fetchone()
        assert tuple(row)==('Event','ai')

def test_legacy_topic_normalizes_before_validation():
    assert core.normalize_event(event('旧文化记录', topics=['展览文化']))['topics'] == ['文化艺术']


def test_legacy_topic_filters_work_in_core_and_api():
    core.ingest(src(), event('文化展览', 'ExhibitionEvent', ['文化艺术']))
    core.ingest(src(), event('机器人活动', 'Hackathon', ['机器人']))
    assert [x['title'] for x in core.events(tag='展览文化')] == ['文化展览']
    assert [x['title'] for x in core.events(topics_filter=['展览文化'])] == ['文化展览']
    assert len(core.events(tag='展览文化', topics_filter=['机器人'])) == 2
    with TestClient(api.app, base_url='https://testserver') as c:
        auth(c)
        for params in ({'tag': '展览文化'}, {'topic': '展览文化'}):
            response = c.get('/events/api/events', params=params)
            assert response.status_code == 200
            assert [x['title'] for x in response.json()['items']] == ['文化展览']
        response = c.get('/events/api/events', params=[('topic', '展览文化'), ('topic', '文化艺术'), ('topic', '机器人')])
        assert response.status_code == 200 and response.json()['total'] == 2
        response = c.get('/events/api/events', params=[('tag', '展览文化'), ('topic', '机器人')])
        assert response.status_code == 200 and response.json()['total'] == 2


def test_generic_type_filter_excludes_pending_and_matches_facet_count():
    core.ingest(src(), event('已经分析的其他活动'))
    with core.db() as c:
        c.execute("UPDATE events SET event_type_state='ai',ai_state='done'")
    core.ingest(src(), event('待分类活动一'))
    core.ingest(src(), event('待分类活动二'))
    with TestClient(api.app, base_url='https://testserver') as c:
        auth(c)
        stats = c.get('/events/api/stats').json()
        facet = next(x for x in stats['event_types'] if x['value'] == 'Event')
        result = c.get('/events/api/events', params={'type': 'Event'}).json()
        assert facet['count'] == result['total'] == 1
        assert {x['event_type_state'] for x in result['items']} == {'ai'}
        assert stats['type_pending'] == 2
        assert c.get('/events/api/events').json()['total'] == 3


def test_all_valid_type_facets_can_be_selected_together():
    core.ingest(src(), event('深圳音乐会', 'MusicEvent'))
    with TestClient(api.app, base_url='https://testserver') as c:
        auth(c)
        response = c.get('/events/api/events', params=[('type', value) for value in core.EVENT_TYPES])
        assert response.status_code == 200
        assert response.json()['total'] == 1

@pytest.mark.parametrize('limit_key', ['daily_calls', 'daily_tokens'])
def test_type_backfill_pauses_before_network_when_budget_is_exhausted(monkeypatch, limit_key):
    core.ingest(src(), event('等待补全类型的活动'))
    with core.db() as c:
        c.execute("UPDATE events SET ai_state='done'")
    cfg = core.config()
    cfg[limit_key] = 0
    (core.ROOT / '.private/settings.json').write_text(json.dumps(cfg))
    monkeypatch.delenv('ARK_API_KEY', raising=False)
    monkeypatch.setenv('RADAR_API_KEY', 'local-test-placeholder')
    def unexpected_session():
        pytest.fail('Budget exhaustion must stop before creating a network session')
    monkeypatch.setattr(worker.requests, 'Session', unexpected_session)
    assert worker.backfill_types(12) == 0
    with core.db() as c:
        assert c.execute('SELECT event_type_state FROM events').fetchone()[0] == 'pending'
        assert c.execute('SELECT status FROM runs ORDER BY id DESC LIMIT 1').fetchone()[0] == 'budget_paused'
        assert c.execute('SELECT calls FROM budget').fetchone()[0] == 0


def test_type_backfill_respects_per_run_limit_and_batch_size(monkeypatch):
    for index in range(30):
        core.ingest(src(), event('条目' + str(index)))
    with core.db() as c:
        c.execute("UPDATE events SET ai_state='done'")
    batches = []
    def classify(rows):
        batches.append(len(rows))
        return [{'id':row['id'], 'event_type':'SocialEvent'} for row in rows]
    monkeypatch.setattr(worker, 'type_batch', classify)
    monkeypatch.setattr(worker.time, 'sleep', lambda _: None)
    assert worker.backfill_types(25) == 25
    assert batches == [12, 12, 1]
    with core.db() as c:
        assert c.execute("SELECT COUNT(*) FROM events WHERE event_type_state='pending'").fetchone()[0] == 5
    assert worker.backfill_types(25) == 5


def test_ai_cannot_replace_a_specific_source_type(monkeypatch):
    core.ingest(src(), event('来源明确的音乐会', 'MusicEvent'))
    with core.db() as c:
        rid = c.execute('SELECT id FROM raw_items').fetchone()[0]
    monkeypatch.setattr(worker, 'ai_batch', lambda rows: [{'id':rid, 'event_type':'ComedyEvent', 'is_shenzhen_offline':True}])
    monkeypatch.setattr(worker.time, 'sleep', lambda _: None)
    monkeypatch.setattr(worker, 'geocode_pending', lambda limit: {})
    worker.analyze(1)
    row = core.events()[0]
    assert row['event_type'] == 'MusicEvent' and row['event_type_state'] == 'source'
