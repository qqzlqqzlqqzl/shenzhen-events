import json
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch
import pytest
from bs4 import BeautifulSoup
from radar import aggregates,core,coverage,api,geocode
from fastapi.testclient import TestClient

@pytest.mark.parametrize('label,year,start,end',[
 ('10月1日—10月3日 19:30-21:00',2026,'2026-10-01','2026-10-04'),
 ('2026年10月31日-11月1日',None,'2026-10-31','2026-11-02'),
 ('12月31日-1月2日',2026,'2026-12-31','2027-01-03'),
 ('2027.1.2',None,'2027-01-02','2027-01-03'),
])
def test_explicit_event_ranges(label,year,start,end):
 a,b=aggregates.explicit_range(label,year);assert a.startswith(start) and b.startswith(end)

@pytest.mark.parametrize('label,year',[('即日至10月31日',2026),('截止10月1日',2026),('每周六',2026),('10月3日-1日',2026),('2月31日',2026),('10月1日',None),('明天',2026)])
def test_no_invented_dates(label,year):assert aggregates.explicit_range(label,year)==(None,None)

def wp(content,date='2026-09-29T12:00:00',title='音乐专场'):
 return json.dumps([{'title':{'rendered':title},'link':'https://example.org/e','date':date,'content':{'rendered':content},'categories':[3]}])

def test_post_date_is_not_event_date_and_publisher_not_organizer():
 rows,_,_=aggregates.wordpress_posts(wp('<p>报道：城市文化介绍</p>'),'https://example.org/api',{'name':'聚合账号'})
 e=rows[0];assert e['start_at'] is None and not e['organizer'];assert e['details']['publisher']=='聚合账号'

def test_nested_labels_and_parent_series_dates():
 body='<p><b>演出时间：</b>10月1日—3日</p><p>活动地点：深圳音乐厅</p><p>活动参与：公益免费，需预约</p><p>活动时间：10月1日</p><p>活动时间：10月3日</p>'
 e=aggregates.wordpress_posts(wp(body),'https://example.org/api',{})[0][0]
 assert e['start_at'].startswith('2026-10-01') and e['end_at'].startswith('2026-10-04');assert e['cost_text']=='免费';assert e['location']=='深圳音乐厅'

def test_multi_event_roundup_is_not_one_schedule():
 e=aggregates.wordpress_posts(wp('<p>活动时间：10月1日</p><p>活动时间：11月2日</p>',title='活动汇总'),'https://example.org/api',{})[0][0]
 assert e['start_at'] is None and '多个活动' in e['details']['review_notes']

def test_old_publication_never_uses_current_year():
 e=aggregates.wordpress_posts(wp('<p>演出时间：10月1日</p>',date='2019-09-29T12:00:00'),'https://example.org/api',{})[0][0]
 assert e['start_at'].startswith('2019-10-01')

def test_monthly_article_splits_events_with_stable_source_identity():
 soup=BeautifulSoup('<title>2026年10月深圳展会预告</title><div><p>01</p><p>机器人博览会</p><p>Robotics Expo 2026</p><p>场馆：深圳国际会展中心</p><p>开展时间：10月14日-16日</p><p>主/承办单位：甲协会</p><p>02</p><p>电子展</p><p>场馆：深圳会展中心</p><p>开展时间：10月21日-23日</p><p>主/承办单位：乙公司</p></div>','html.parser')
 rows=aggregates.monthly_events(soup,'https://example.org/monthly.html');assert len(rows)==2 and rows[0]['organizer']=='甲协会';assert rows[0]['end_at'].startswith('2026-10-17');assert rows[0]['url']!=rows[1]['url'];assert 'Robotics' in rows[0]['title']
 assert aggregates.monthly_events(soup,'https://example.org/monthly.html')==rows

def test_collection_follows_public_api_pagination_without_guessing(tmp_path,monkeypatch):
 monkeypatch.setattr(core,'ROOT',tmp_path);(tmp_path/'sources.json').write_text('[]');core.init()
 pages=[(wp('<p>活动时间：2026年10月1日</p>'),{'total':'2','total_pages':'2'}),(wp('<p>活动时间：2026年10月2日</p>',title='第二场').replace('/e"','/f"'),{'total':'2','total_pages':'2'})]
 def fetch(url,**kwargs):
  assert kwargs['include_pagination'];html,meta=pages.pop(0);return html,BeautifulSoup('', 'html.parser'),url,meta
 src={'id':'w','kind':'wordpress_events','name':'聚合源','url':'https://example.org/api?per_page=1','city_scope':'深圳','max_pages':2,'max_entries':20,'coverage_mode':'city_pages','request_delay':0}
 with patch.object(coverage.c,'fetch',side_effect=fetch),patch.object(core,'now',return_value=datetime(2026,9,30,tzinfo=core.TZ)):
  r=coverage.collect_report(src)
 assert len(r['items'])==2 and r['coverage']['pages_visited']==2 and r['coverage']['source_total']==2 and not r['coverage']['truncated']

@pytest.fixture
def database(tmp_path,monkeypatch):
 (tmp_path/'sources.json').write_text('[]');(tmp_path/'static').mkdir()
 monkeypatch.setattr(core,'ROOT',tmp_path);monkeypatch.setattr(api,'ROOT',tmp_path);api.initialize_settings();core.init()
 return tmp_path

def test_attendance_filter_and_no_online_geocoding(database,monkeypatch):
 start=core.iso(core.now()+timedelta(days=2))
 for n,mode in enumerate(['online','offline','hybrid']):
  core.ingest({'id':'a','priority':10},{'title':mode+'开发者活动','url':'https://example.org/'+str(n),'start_at':start,'location':'待确认' if mode=='online' else '深圳南山测试会场','details':{'attendance':mode}})
 assert len(core.events())==3 and len(core.events(attendance='online'))==1
 assert core.events(attendance='online')[0]['attendance_label']=='线上'
 with patch.object(geocode,'load_key',return_value='unit-test'),patch.object(geocode,'resolve_location',side_effect=AssertionError('online must not geocode')):
  result=geocode.enrich_pending();assert result['skipped']==1
 with TestClient(api.app) as client:
  client.cookies.set(api.COOKIE,api.sign_session({'id':1,'username':'owner'}))
  assert client.get('/events/api/events?attendance=online').json()['total']==1
  assert client.get('/events/api/events?attendance=invalid').status_code==400


def test_multi_venue_does_not_claim_one_amap_position():
 for loc in ['南山区甲馆、福田区乙馆','深圳市民中心→宝安海滨广场','南山区甲馆 福田区乙馆']:
  assert geocode.direct_district(loc)==''
 for loc in ['南山区甲馆、福田区乙馆','深圳市民中心→宝安海滨广场']:
  assert geocode.query_text(loc)==''
