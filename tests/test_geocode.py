from __future__ import annotations
import json
from pathlib import Path
import pytest
from radar import core, geocode

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    (tmp_path/'static').mkdir()
    (tmp_path/'sources.json').write_text(json.dumps([{'id':'a','name':'测试源','url':'https://example.com','priority':10,'interval_hours':6}]))
    (tmp_path/'.private').mkdir()
    (tmp_path/'.private'/'amap.key').write_text('test-web-key')
    monkeypatch.setattr(core,'ROOT',tmp_path)
    core.init()
    yield tmp_path

def event(location,url='https://example.com/e'):
    return {'title':'深圳线下测试活动','url':url,'start_at':'2026-10-10T10:00:00+08:00','end_at':'2026-10-10T12:00:00+08:00','location':location,'summary':'测试活动','cost_text':'免费'}

def test_direct_district_never_calls_network(monkeypatch):
    monkeypatch.setattr(geocode,'_request_json',lambda *a,**k:pytest.fail('network should not be called'))
    r=geocode.resolve_location('深圳市南山区科技园')
    assert r['district']=='南山' and r['method']=='text'

def test_geocode_resolves_landmark_and_caches(monkeypatch):
    calls=[]
    def fake(url,params,session=None):
        calls.append((url,dict(params)))
        return {'status':'1','infocode':'10000','geocodes':[{'district':'福田区','adcode':'440304','location':'114.059,22.543','formatted_address':'广东省深圳市福田区深圳博物馆'}]},''
    monkeypatch.setattr(geocode,'_request_json',fake)
    a=geocode.resolve_location('深圳博物馆历史民俗馆')
    b=geocode.resolve_location('深圳博物馆历史民俗馆')
    assert a['district']=='福田' and a['method']=='geocode'
    assert b['district']=='福田' and len(calls)==1
    with core.db() as c:assert c.execute('select count(*) from geocode_cache').fetchone()[0]==1

def test_poi_fallback_is_strictly_shenzhen(monkeypatch):
    responses=[
        ({'status':'1','infocode':'10000','geocodes':[]},''),
        ({'status':'1','infocode':'10000','pois':[{'name':'深圳湾万丽酒店','cityname':'深圳市','adname':'南山区','adcode':'440305','location':'113.95,22.53','address':'深圳湾科技生态园'}]},'')
    ]
    def fake(url,params,session=None):
        if geocode.PLACE_URL==url:
            assert params['region']=='深圳市' and params['city_limit']=='true'
        return responses.pop(0)
    monkeypatch.setattr(geocode,'_request_json',fake)
    r=geocode.resolve_location('深圳 / 深圳湾万丽酒店')
    assert r['district']=='南山' and r['method']=='poi'

def test_foreign_and_generic_locations_are_skipped(monkeypatch):
    monkeypatch.setattr(geocode,'_request_json',lambda *a,**k:pytest.fail('network should not be called'))
    assert geocode.resolve_location('香港故宫文化博物馆')['status']=='skipped'
    assert geocode.resolve_location('深圳 / 具体地址报名后通知')['status']=='skipped'
    assert geocode.resolve_location('深圳')['status']=='skipped'

def test_non_shenzhen_adcode_is_rejected(monkeypatch):
    responses=[
        ({'status':'1','infocode':'10000','geocodes':[{'district':'天河区','adcode':'440106','location':'113.3,23.1'}]},''),
        ({'status':'1','infocode':'10000','pois':[{'name':'测试中心','cityname':'广州市','adname':'天河区','adcode':'440106','location':'113.3,23.1'}]},'')
    ]
    monkeypatch.setattr(geocode,'_request_json',lambda *a,**k:responses.pop(0))
    r=geocode.resolve_location('测试中心')
    assert r['status']=='not_found' and not r.get('district')

def test_api_failure_does_not_cache_or_update(monkeypatch):
    core.ingest({'id':'a','priority':10},event('深圳湾某测试场馆'))
    monkeypatch.setattr(geocode,'_request_json',lambda *a,**k:(None,'network_Timeout'))
    r=geocode.enrich_pending(limit=10,apply=True,sleep_seconds=0)
    assert r['errors']==1 and r['updated']==0
    with core.db() as c:
        assert c.execute('select district from events').fetchone()[0]=='待确认'
        assert c.execute('select count(*) from geocode_cache').fetchone()[0]==0

def test_apply_updates_only_district_and_keeps_location(monkeypatch):
    original='深圳自然博物馆'
    core.ingest({'id':'a','priority':10},event(original))
    def fake(url,params,session=None):
        return {'status':'1','infocode':'10000','geocodes':[{'district':'坪山区','adcode':'440310','location':'114.35,22.69','formatted_address':'深圳自然博物馆'}]},''
    monkeypatch.setattr(geocode,'_request_json',fake)
    r=geocode.enrich_pending(limit=10,apply=True,sleep_seconds=0)
    assert r['resolved']==1 and r['updated']==1
    with core.db() as c:
        row=c.execute('select district,location,title from events').fetchone()
        assert row['district']=='坪山' and row['location']==original and row['title']=='深圳线下测试活动'

def test_dry_run_resolves_but_does_not_mutate(monkeypatch):
    core.ingest({'id':'a','priority':10},event('深圳珠宝博物馆'))
    monkeypatch.setattr(geocode,'_request_json',lambda *a,**k:({'status':'1','infocode':'10000','geocodes':[{'district':'罗湖区','adcode':'440303','location':'114.1,22.55'}]},''))
    r=geocode.enrich_pending(limit=10,apply=False,sleep_seconds=0)
    assert r['resolved']==1 and r['updated']==0
    with core.db() as c:assert c.execute('select district from events').fetchone()[0]=='待确认'

def test_amap_service_error_is_transient(monkeypatch):
    core.ingest({'id':'a','priority':10},event('深圳某场馆'))
    monkeypatch.setattr(geocode,'_request_json',lambda *a,**k:(None,'amap_10003'))
    r=geocode.enrich_pending(limit=10,apply=True,sleep_seconds=0)
    assert r['errors']==1 and r['updated']==0
    with core.db() as c:assert c.execute('select count(*) from geocode_cache').fetchone()[0]==0

def test_geocode_engine_error_falls_back_to_poi(monkeypatch):
    responses=[
        (None,'amap_30001'),
        ({'status':'1','infocode':'10000','pois':[{'name':'深圳欢乐谷','cityname':'深圳市','adname':'南山区','adcode':'440305','location':'113.98,22.54','address':'侨城西街'}]},'')
    ]
    monkeypatch.setattr(geocode,'_request_json',lambda *a,**k:responses.pop(0))
    r=geocode.resolve_location('欢乐谷')
    assert r['status']=='ok' and r['district']=='南山' and r['method']=='poi'

def test_postaladdress_location_is_reduced_to_place_name():
    assert geocode.query_text('Hilton Shenzhen Futian PostalAddress Shenzhen cn Tower B, Great China International')=='Hilton Shenzhen Futian'
    assert geocode.query_text('Shenzhen Lowu PostalAddress New Territories cn')==''

def test_english_poi_uses_consensus_and_skips_geocode(monkeypatch):
    calls=[]
    pois=[
        {'name':'深圳北站','cityname':'深圳市','adname':'龙华区','adcode':'440309','location':'114.03,22.61'},
        {'name':'深圳北站西广场','cityname':'深圳市','adname':'龙华区','adcode':'440309','location':'114.02,22.61'},
        {'name':'深圳北站店','cityname':'深圳市','adname':'龙华区','adcode':'440309','location':'114.03,22.61'}
    ]
    def fake(url,params,session=None):
        calls.append(url);return {'status':'1','infocode':'10000','pois':pois},''
    monkeypatch.setattr(geocode,'_request_json',fake)
    r=geocode.resolve_location('Shenzhen North Railway Station')
    assert r['district']=='龙华' and r['method']=='poi'
    assert calls==[geocode.PLACE_URL]

def test_english_poi_refuses_cross_district_ambiguity(monkeypatch):
    pois=[
        {'name':'Alpha Center','cityname':'深圳市','adname':'南山区','adcode':'440305','location':'113.9,22.5'},
        {'name':'Alpha Club','cityname':'深圳市','adname':'福田区','adcode':'440304','location':'114.0,22.5'}
    ]
    monkeypatch.setattr(geocode,'_request_json',lambda *a,**k:({'status':'1','infocode':'10000','pois':pois},''))
    r=geocode.resolve_location('Some English Place Name')
    assert r['status']=='not_found'

def test_english_district_text_beats_network(monkeypatch):
    monkeypatch.setattr(geocode,'_request_json',lambda *a,**k:pytest.fail('network should not be called'))
    r=geocode.resolve_location('Le Select (Chegongmiao Exit C in Futian District)')
    assert r['district']=='福田' and r['method']=='text'

def test_signup_success_and_generic_city_are_skipped():
    assert geocode.query_text('深圳市（报名成功后由主办方告知具体地点）')==''
    assert geocode.query_text('广东·深圳')==''

def test_api_district_without_shenzhen_adcode_is_rejected():
    data={'status':'1','geocodes':[{'district':'南山区','adcode':'','location':'113.9,22.5'}]}
    assert geocode._from_geocode(data) is None

def test_service_wide_error_stops_batch(monkeypatch):
    for i in range(3):
        core.ingest({'id':'a','priority':10},event(f'深圳测试场馆{i}',url=f'https://example.com/{i}'))
    calls=[]
    def fail(*args,**kwargs):
        calls.append(1);return None,'amap_10001'
    monkeypatch.setattr(geocode,'_request_json',fail)
    r=geocode.enrich_pending(limit=10,apply=True,sleep_seconds=0)
    assert r['errors']==1 and r['examined']==1 and r['stopped']=='amap_10001'
    assert len(calls)==1
