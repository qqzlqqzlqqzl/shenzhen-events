import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import pytest
from bs4 import BeautifulSoup
from radar import core,details,official_sources,worker

@pytest.mark.parametrize('typ,expected',[('MusicEvent','文化艺术'),('ComedyEvent','文化艺术'),('SportsEvent','户外生活'),('ExhibitionEvent','其他')])
def test_specific_type_resolves_only_missing_theme(typ,expected):
 assert core.resolved_topics(['其他'],typ)==[expected]
 assert core.resolved_topics(['硬件创客','其他'],typ)==['硬件创客']

def test_rules_do_not_match_ai_inside_english_words():
 assert 'AI与开源' not in core.rules('Painting fair')['topics']
 assert 'AI与开源' in core.rules('AI硬件工作坊')['topics']
 assert '文化艺术' in core.rules('音乐演唱会')['topics']

def test_automatic_models_fail_closed():
 with patch.object(worker,'config',return_value={}),patch.object(worker.requests.Session,'post',side_effect=AssertionError('must not call model')):
  assert worker.analyze()==0
  assert worker.backfill_types()==0
  assert worker.ai_batch([]) is None
  assert worker.type_batch([]) is None

def test_detail_metadata_requires_labeled_price():
 s=BeautifulSoup('<main><h1>免费赢奖品</h1><p>主办方：甲公司</p><p>协办单位：乙协会</p><img src="https://img.example.com/a.webp"><img alt="二维码" src="https://img.example.com/qr.png"></main>','html.parser')
 out=details.extract(s,'https://example.com/event')
 assert out['organizer']=='甲公司' and out['coorganizers']=='乙协会'
 assert 'cost_text' not in out
 assert len(out['images'])==1
 assert not details.public_image('javascript:alert(1)','https://example.com')
 assert not details.public_image('http://127.0.0.1/x','https://example.com')

def test_enrichment_does_not_erase_known_fields():
 base={'start_at':'2026-10-03T09:00:00+08:00','location':'深圳','cost_text':'免费','organizer':'甲'}
 out=details.merge(base,{'start_at':None,'location':'','cost_text':'费用未注明'},{'images':[]})
 assert all(out[k]==v for k,v in base.items())

def test_official_schedule_year_and_rollover():
 html='<h1>2026年深圳会展中心展览计划表</h1><table class="zhpq-table"><tr><td>&nbsp;</td><td colspan="8"><a name="yue12"></a>2025年12月</td><td colspan="3">&nbsp;</td></tr><tr><td>1</td><td>购物节</td><td>12月31日 - 01月11日</td><td><p>主办公司</p><p>联系人</p></td></tr><tr><td>2026年10月</td></tr><tr><td>84</td><td>湾区半导体产业生态博览会（深圳）</td><td>10月14日 - 10月16日</td><td><p>芯盟会展</p></td></tr></table>'
 rows=official_sources.szcec(BeautifulSoup(html,'html.parser'),'https://www.szcec.com/schedule')
 assert len(rows)==2 and rows[0]['start_at'].startswith('2025-12-31') and rows[0]['end_at'].startswith('2026-01-12')
 assert rows[1]['end_at'].startswith('2026-10-17') and rows[1]['organizer']=='芯盟会展'
 assert rows[0]['url']!=rows[1]['url']
 assert official_sources.szcec(BeautifulSoup(html.replace('2026年深圳会展中心展览计划表','排期'),'html.parser'),'https://example.com')==[]

def test_cioe_explicit_year_not_current_year():
 html='第二十八届中国国际光电博览会（CIOE中国光博会）将于2027年9月8-10日在深圳国际会展中心举办'
 row=official_sources.cioe(BeautifulSoup(html,'html.parser'),'https://www.cioe.cn/')[0]
 assert row['start_at'].startswith('2027-09-08') and row['end_at'].startswith('2027-09-11')

def test_raw_fees_unknown_and_holds_persist(tmp_path,monkeypatch):
 monkeypatch.setattr(core,'ROOT',tmp_path);(tmp_path/'sources.json').write_text('[]');core.init()
 src={'id':'sample','priority':10}
 event={'title':'音乐演唱会','url':'https://example.com/e','start_at':'2026-10-03','location':'深圳','event_type':'MusicEvent'}
 core.ingest(src,event)
 with core.db() as c:
  old=dict(c.execute('select * from events').fetchone());eid=old['id']
  c.execute('update events set details=?,status=?,ai_state=? where id=?',(json.dumps({'review_hold':'date_conflict','review_notes':'海报日期冲突'}),'needs_review','review',eid))
 core.ingest(src,{**event,'summary':'changed','details':{'images':['https://example.com/x.png']}})
 with core.db() as c:
  r=dict(c.execute('select * from events').fetchone())
 assert r['status']=='needs_review' and r['ai_state']=='review'
 assert json.loads(r['details'])['review_hold']=='date_conflict'


def test_derived_details_do_not_requeue_unchanged_source(tmp_path,monkeypatch):
 monkeypatch.setattr(core,'ROOT',tmp_path);(tmp_path/'sources.json').write_text('[]');core.init()
 src={'id':'sample','priority':10};e={'title':'音乐会','url':'https://example.com/a','start_at':'2026-10-03','location':'深圳','event_type':'MusicEvent'}
 core.ingest(src,e)
 with core.db() as c:c.execute("update raw_items set analysis_state='done'");c.execute("update events set ai_state='done'")
 assert not core.ingest(src,{**e,'details':{'images':['https://example.com/p.webp'],'checked_at':'later'}})
 with core.db() as c:
  assert c.execute('select analysis_state from raw_items').fetchone()[0]=='done'
  assert c.execute('select ai_state from events').fetchone()[0]=='done'
  assert json.loads(c.execute('select details from events').fetchone()[0])['images']


def test_official_schedule_never_guesses_section_year():
 html='<h1>2026年深圳会展中心展览计划表</h1><table class="zhpq-table"><tr><td>1</td><td>新年购物节</td><td>12月31日 - 01月11日</td><td>甲公司</td></tr></table>'
 assert official_sources.szcec(BeautifulSoup(html,'html.parser'),'https://example.com')==[]


def test_reviewed_posters_are_local_and_untrusted_cache_paths_are_ignored(tmp_path):
 from radar import posters
 folder=tmp_path/'static/posters';folder.mkdir(parents=True)
 name='a'*64+'.webp';(folder/name).write_bytes(b'fixture')
 url='https://example.com/poster.webp'
 (folder/'manifest.json').write_text(json.dumps({url:name,'https://bad.test/a':'../../secret','https://bad.test/b':'b'*64+'.png'}))
 d={'images':[url,'https://unknown.test/a',{}],'cached_images':{'https://unknown.test/a':'https://tracker.test/a'}}
 out=posters.display_details(d,tmp_path)
 assert out['cached_images']=={url:'/events/static/posters/'+name}
 assert out['images']==d['images']
 assert d['cached_images']!=out['cached_images']
 assert posters.display_details({'images':'invalid'},tmp_path)['cached_images']=={}


def test_packaged_workbuddy_poster_hash_and_manifest():
 import hashlib
 root=Path(__file__).resolve().parents[1]
 mapping=json.loads((root/'static/posters/manifest.json').read_text())
 assert len(mapping)==1
 for url,name in mapping.items():
  content=(root/'static/posters'/name).read_bytes()
  assert hashlib.sha256(content).hexdigest()==name.split('.')[0]
  assert content[:4]==b'RIFF' and content[8:12]==b'WEBP'


def test_wechat_queries_use_current_year_and_publisher_is_not_organizer():
 from radar import collectors
 from urllib.parse import urlsplit,parse_qs
 soup=BeautifulSoup('<ul class="news-list"><li><h3><a href="https://example.com/post">活动</a></h3><p class="txt-info">报名</p></li></ul>','html.parser')
 source={'url':'https://weixin.sogou.com/weixin','queries':['深圳 工作坊','深圳 展会 2027'],'queries_per_run':2}
 with patch.object(collectors,'now',return_value=datetime(2026,9,30,tzinfo=core.TZ)),patch.object(collectors,'fetch',return_value=('',soup,'')) as f,patch.object(collectors.time,'sleep'):
  rows=collectors.sogou(source)
  queries=[parse_qs(urlsplit(c.args[0]).query)['query'][0] for c in f.call_args_list]
  assert set(queries)=={'深圳 工作坊 2026','深圳 展会 2027'}
  assert all(not r.get('organizer') for r in rows)
  assert all(not r.get('start_at') for r in rows)
