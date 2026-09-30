import json,importlib.util,sys
from pathlib import Path
from datetime import timedelta
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from radar import core,api,coverage,aggregates,source_fields,details

def test_explicit_douban_fields_not_address_keywords():
 raw='黄西脱口秀专场《DeepChat AI咋咋地》 时间：10月11日 周日 19:30-20:30 地点：南山区 风华大剧院 公园路49号 费用：50.0元起 发起：猫眼演出 0人参加 0人感兴趣'
 f=source_fields.inline_fields(raw);assert f=={'location':'南山区 风华大剧院 公园路49号','cost_text':'50.0元起','publisher':'猫眼演出'}
 assert core.rules('黄西脱口秀专场《DeepChat AI咋咋地》',raw)['topics']==['文化艺术'];assert core.rules('黄西脱口秀专场《DeepChat AI咋咋地》',raw)['priority']=='normal'
 row={'title':'黄西脱口秀专场《DeepChat AI咋咋地》','summary':raw,'location':'','cost_text':'费用未注明','details':'{}','event_type_state':'pending','ai_state':'pending'}
 p=source_fields.event_patch(row,{'douban'});assert p['event_type']=='ComedyEvent' and p['district']=='南山' and p['cost_free']==0
 assert not source_fields.event_patch({**row,**p},{'douban'})
 assert source_fields.event_patch({**row,'details':'{"review_hold":"date_conflict"}'},{'douban'})=={}
 assert 'event_type' not in source_fields.event_patch({**row,'ai_state':'done'},{'douban'})

def test_enrichment_preserves_modality_and_publisher_roles():
 e=details.merge({'details':{'attendance':'hybrid','publisher':'发布号','organizer_role':'publisher'}},{},{'images':[]})
 assert e['details']['attendance']=='hybrid' and e['details']['organizer_role']=='publisher'
 e=details.merge(e,{'organizer':'原文明示的主办'},{'organizer':'原文明示的主办'})
 assert e['details']['organizer_role']=='organizer'

def test_developer_online_dates_are_not_fabricated_eight_am():
 value={'@type':'EducationEvent','name':'Test Online Conference','eventAttendanceMode':'https://schema.org/OnlineEventAttendanceMode','startDate':'2026-10-01T00:00:00.000+00:00','endDate':'2026-10-02T00:00:00.000+00:00','url':'https://dev.events/conferences/test','description':'AI conference Online'}
 html='<div class="row"><script type="application/ld+json">'+json.dumps(value)+'</script><time>Oct 1-2 26</time></div><button class="moreButton" hx-vals=\'{"page":"2"}\'>Show more</button><p>showing 30 out of 170 conferences</p>'
 soup=BeautifulSoup(html,'html.parser');e=aggregates.developer_events(soup,'https://dev.events/ON')[0]
 assert e['all_day'] and e['start_at']=='2026-10-01T00:00:00+08:00' and e['end_at']=='2026-10-03T00:00:00+08:00'
 assert e['details']['attendance']=='online' and e['location']=='线上'
 assert coverage.next_page(soup,'https://dev.events/ON','devevents')==('https://dev.events/ON?page=2',170)

@pytest.fixture
def isolated(tmp_path,monkeypatch):
 monkeypatch.setattr(core,'ROOT',tmp_path);monkeypatch.setattr(api,'ROOT',tmp_path);(tmp_path/'static').mkdir();(tmp_path/'sources.json').write_text('[]');api.initialize_settings();core.init();return tmp_path

def test_alias_merge_retains_old_deep_links_calendar_and_favorite_writes(isolated):
 start=core.iso(core.now()+timedelta(days=2))
 for n,title in enumerate(['全称甲活动','同场简称乙活动']):core.ingest({'id':str(n),'priority':10+n},{'title':title,'url':'https://example.com/'+str(n),'start_at':start,'location':'深圳南山测试中心'})
 rows=core.events();ids={e['url']:e['id'] for e in rows};old=ids['https://example.com/0'];winner=ids['https://example.com/1']
 (isolated/'dedupe_aliases.json').write_text(json.dumps([{'id':'checked','date':start[:10],'urls':list(ids),'preferred_url':'https://example.com/1'}]))
 with core.db() as c:c.execute('INSERT INTO preferences(event_id,favorite) VALUES(?,1)',(old,))
 assert len(core.reconcile_aliases())==1
 assert core.resolve_event_id(old)==winner and len(core.events())==1 and core.events()[0]['favorite']
 with TestClient(api.app) as client:
  client.cookies.set(api.COOKIE,api.sign_session({'id':1,'username':'owner'}))
  assert client.get('/events/api/event/'+old).json()['id']==winner
  assert client.get('/events/api/event/'+old+'.ics').status_code==200
  r=client.post('/events/api/preferences/'+old,headers={'X-Radar-Request':'1'},json={'favorite':False});assert r.status_code==200 and not r.json()['favorite']
 with core.db() as c:assert not c.execute('PRAGMA foreign_key_check').fetchall()

def test_source_field_import_is_idempotent_and_preserves_raw(isolated,monkeypatch):
 start=core.iso(core.now()+timedelta(days=2));core.ingest({'id':'douban','priority':35},{'title':'黄西脱口秀专场','url':'https://example.com/c','start_at':start,'summary':'时间：10月11日 地点：南山区风华大剧院 费用：50元 发起：公开账号 0人参加'})
 scripts=Path(__file__).resolve().parents[1]/'scripts';monkeypatch.syspath_prepend(str(scripts));spec=importlib.util.spec_from_file_location('repair_source',scripts/'repair_source_fields.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 db=isolated/'data/events.sqlite3'
 assert len(module.run(db,isolated/'dry')['changed'])==1
 assert len(module.run(db,isolated/'apply',True)['changed'])==1
 assert module.run(db,isolated/'again')['changed']==[]
 assert core.events()[0]['location']=='南山区风华大剧院'


def test_global_hybrid_and_online_admission_is_not_shenzhen_venue(isolated,monkeypatch):
 now=core.now()+timedelta(days=10);date=now.strftime('%Y-%m-%d')
 rows=[]
 for mode in ['Online','Mixed']:
  item={'name':mode+' developer summit','eventAttendanceMode':'https://schema.org/'+mode+'EventAttendanceMode','startDate':date+'T00:00:00Z','endDate':date+'T00:00:00Z','url':'https://dev.events/conferences/'+mode,'location':{'name':'Berlin, Germany'}}
  rows.append('<div class="row"><script type="application/ld+json">'+json.dumps(item)+'</script><time>'+date+'</time></div>')
 html=''.join(rows);soup=BeautifulSoup(html,'html.parser')
 monkeypatch.setattr(coverage.c,'fetch',lambda url,**kw:(html,soup,url))
 r=coverage.collect_report({'id':'dev','kind':'devevents','url':'https://dev.events/ON','allow_online':True,'coverage_mode':'page_inventory'})
 assert len(r['items'])==2
 assert {e['details']['attendance'] for e in r['items']}=={'online','hybrid'}
 assert all(e['city']!='深圳' for e in r['items'])


def test_cached_detail_cannot_erase_fresh_attendance(isolated):
 e={'title':'混合活动','url':'https://example.com/hybrid','start_at':core.iso(core.now()+timedelta(days=5)),'details':{'attendance':'hybrid','organizer_role':'publisher'}}
 payload={**e,'details':{'organizer':'真实主办','organizer_role':'organizer'}}
 fp=coverage._detail_fingerprint(e)
 with core.db() as c:c.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?)',('a',e['url'],fp,json.dumps(payload),'ok',core.stamp(),core.iso(core.now()+timedelta(hours=4))))
 metrics={k:0 for k in ['detail_cached','detail_deferred','detail_attempted','detail_resolved','detail_failed']}
 out=coverage.enrich_details({'id':'a','enrich_dated':True},[e],metrics)
 assert out[0]['details']['attendance']=='hybrid' and out[0]['details']['organizer_role']=='organizer' and metrics['detail_cached']==1
