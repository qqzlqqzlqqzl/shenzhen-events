import json
from datetime import datetime
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from radar import core, api, worker, collectors, coverage, jobs

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    (tmp_path/'static').mkdir();(tmp_path/'static/index.html').write_text('<html></html>')
    (tmp_path/'sources.json').write_text(json.dumps([source()]))
    for obj in (core,api,worker):monkeypatch.setattr(obj,'ROOT',tmp_path)
    monkeypatch.setattr(core,'now',lambda:datetime(2026,9,30,9,0,tzinfo=core.TZ))
    monkeypatch.setattr(coverage.time,'sleep',lambda _:None)
    api.initialize_settings();core.init();yield tmp_path

def source(**kw):
    s={'id':'a','name':'测试源','kind':'lianpu','url':'https://example.com/city/shenzhen','coverage_mode':'city_pages','city_scope':'深圳','interval_hours':3,'priority':20,'max_pages':10,'max_entries':500,'request_delay':0}
    s.update(kw);return s

def page(title='机器人',slug='1',city='深圳',next_url=''):
    return f'<article><h3><a href="/event/{slug}">{title}</a></h3><p>活动简介</p><p>{city} / 测试会场</p><time datetime="2026-10-17T09:00:00+08:00"></time><time datetime="2026-10-17T12:00:00+08:00"></time></article>'+ (f'<a href="{next_url}">下一页</a>' if next_url else '')

def stub_fetch(monkeypatch,pages):
    seen=[]
    def fetch(url,**kw):
        seen.append((url,kw));value=pages[url]
        if isinstance(value,Exception):raise value
        return value,BeautifulSoup(value,'html.parser'),url
    monkeypatch.setattr(collectors,'fetch',fetch);return seen

def test_lianpu_traverses_all_pages(monkeypatch):
    s=source();u=s['url'];seen=stub_fetch(monkeypatch,{u:page(next_url='?page=2'),u+'?page=2':page('后页工作坊','2')})
    r=coverage.collect_report(s)
    assert r['status']=='ok' and len(r['items'])==2
    assert r['coverage']['pages_visited']==2 and r['coverage']['complete_scope']
    assert r['coverage']['next_cursor'] is None and len(seen)==2

def test_later_page_block_keeps_earlier_results(monkeypatch):
    s=source();u=s['url'];stub_fetch(monkeypatch,{u:page(next_url='?page=2'),u+'?page=2':collectors.Blocked('HTTP 429')})
    r=coverage.collect_report(s)
    assert r['status']=='partial' and len(r['items'])==1
    assert r['coverage']['next_cursor']==u+'?page=2'

def test_page_cap_is_visible_and_resumable(monkeypatch):
    s=source(max_pages=1);u=s['url'];stub_fetch(monkeypatch,{u:page(next_url='?page=2'),u+'?page=2':page('后续','2')})
    r=coverage.collect_report(s);assert r['coverage']['truncated'] and r['status']=='partial'
    r2=coverage.collect_report(s,r['coverage']);assert r2['items'][0]['title']=='后续'
    assert r2['coverage']['next_cursor'] is None

def test_external_next_page_not_followed():
    soup=BeautifulSoup(page(next_url='https://evil.example/'),'html.parser')
    assert coverage.next_page(soup,'https://example.com/city/shenzhen','lianpu')[0] is None

def test_douban_observed_offset_paging():
    soup=BeautifulSoup('<div class="paginator"><a href="?start=10">后页&gt;</a></div>','html.parser')
    assert coverage.next_page(soup,'https://example.com/events','douban')[0]=='https://example.com/events?start=10'

def test_repeated_page_is_partial_not_infinite(monkeypatch):
    s=source();u=s['url'];stub_fetch(monkeypatch,{u:page(next_url='?page=2'),u+'?page=2':page(next_url='?page=3')})
    r=coverage.collect_report(s);assert r['coverage']['pages_visited']==2 and r['coverage']['truncated']

def test_hdx_city_parser_uses_location_not_title(monkeypatch):
    s=source(kind='hdx',proxy='http://127.0.0.1:17890');u=s['url']
    html='<div class="search-tab-content-item"><a class="item-title" href="/event/123">芯片创新论坛</a><p class="item-data">2026.10.27-2026.10.27</p><p class="item-dress">广东深圳宝安国际会展中心</p></div><script>laypage.render({elem: "pagination", count: 1, limit: 10, curr: 1})</script>'
    seen=stub_fetch(monkeypatch,{u:html});r=coverage.collect_report(s)
    assert r['coverage']['source_total']==1 and len(r['items'])==1
    assert r['items'][0]['title']=='芯片创新论坛' and r['items'][0]['all_day']
    assert seen[0][1]['proxy']=='http://127.0.0.1:17890'

def test_hdx_pagination_uses_declared_total():
    html='<script>laypage.render({elem:"pagination",count:23,limit:10,curr:2})</script>'
    nxt,total=coverage.next_page(BeautifulSoup(html,'html.parser'),'https://example.com/eventlist?city=shenzhen&page=2','hdx')
    assert total==23 and 'page=3' in nxt

def feed(n):
    return '<rss version="2.0"><channel>'+''.join(f'<item><title>工作坊{i}</title><link>https://example.com/event/{i}</link><description>'+('深圳线下社区活动报名介绍'*6)+f'</description><pubDate>Wed, 30 Sep 2026 00:00:00 GMT</pubDate></item>' for i in range(n))+'</channel></rss>'

def test_rss_keeps_entries_beyond_30_and_explains_cap(monkeypatch):
    s=source(kind='rss',coverage_mode='search_index',detail_budget=0);stub_fetch(monkeypatch,{s['url']:feed(50)})
    r=coverage.collect_report(s);assert len(r['items'])==50 and r['coverage']['feed_total']==50
    assert r['coverage']['detail_deferred']==50 and r['status']=='partial'
    s['max_entries']=35;r=coverage.collect_report(s);assert len(r['items'])==35 and r['coverage']['truncated']

def test_detail_budget_rotates_past_first_entries(monkeypatch):
    s=source(kind='rss',coverage_mode='search_index',detail_budget=2);u=s['url']
    pages={u:feed(6)}
    for i in range(6):pages[f'https://example.com/event/{i}']='<script type="application/ld+json">'+json.dumps({'@type':'Event','name':f'深圳活动{i}','startDate':'2026-10-18','location':{'name':'深圳会场'}})+'</script>'
    stub_fetch(monkeypatch,pages)
    r=coverage.collect_report(s);assert r['coverage']['detail_attempted']==2
    r=coverage.collect_report(s);assert r['coverage']['detail_cached']==2 and r['coverage']['detail_attempted']==2
    assert sum(bool(e['start_at']) for e in r['items'])==4

def test_tech_total_and_shenzhen_count_are_distinct(monkeypatch):
    def card(city,n):return f'<a href="/event/{n}"><h3>{city}活动</h3><p>活动介绍</p><div><i i-carbon-location></i>{city}</div><div><i i-carbon-calendar></i>2026年10月17日</div></a>'
    s=source(kind='tech',city_scope='',coverage_mode='page_inventory');stub_fetch(monkeypatch,{s['url']:card('深圳',1)+card('上海',2)})
    r=coverage.collect_report(s);m=r['coverage']
    assert m['visible']==2 and m['extracted']==2 and m['shenzhen_candidates']==1 and m['rejected']['其他城市']==1

def test_stale_history_rejected_before_ai(monkeypatch):
    s=source();stub_fetch(monkeypatch,{s['url']:page().replace('2026-10-17','2026-01-01')})
    r=coverage.collect_report(s);assert not r['items'] and r['coverage']['rejected']['超出历史保留期']==1

def test_jsonld_city_structure_preserved_without_type_noise():
    data={'@type':'Event','name':'活动','startDate':'2026-10-17','location':{'name':'场馆','address':{'@type':'PostalAddress','addressLocality':'Shen Zhen Shi','streetAddress':'某路1号'}}}
    r=collectors.jsonld(BeautifulSoup('<script type="application/ld+json">'+json.dumps(data)+'</script>','html.parser'),'https://example.com')[0]
    assert 'PostalAddress' not in r['location'] and coverage.city_evidence(r,{})=='深圳'

def test_source_error_keeps_last_good_inventory(monkeypatch):
    s=source();stub_fetch(monkeypatch,{s['url']:collectors.Blocked('来源限制访问（HTTP 429）')})
    with core.db() as db:db.execute("UPDATE source_health SET raw_count=8,last_success='2026-09-29T10:00:00+08:00',coverage=?",(json.dumps({'visible':8,'admitted':8}),))
    r=worker.collect_source(s);assert r['status']=='blocked'
    with core.db() as db:
        row=dict(db.execute('SELECT * FROM source_health').fetchone())
        assert row['raw_count']==8 and row['last_success'].startswith('2026-09-29') and row['failure_count']==1

def auth(client):client.cookies.set(api.COOKIE,api.sign_session({'id':1,'username':'test'}),path='/events')

def test_retry_endpoint_private_idempotent_and_rate_limited(monkeypatch):
    with TestClient(api.app,base_url='https://testserver') as client:
        headers={'X-Radar-Request':'1'}
        assert client.post('/events/api/sources/a/retry',headers=headers).status_code==401
        auth(client);assert client.post('/events/api/sources/a/retry').status_code==403
        a=client.post('/events/api/sources/a/retry',headers=headers);b=client.post('/events/api/sources/a/retry',headers=headers)
        assert a.status_code==202 and a.json()['id']==b.json()['id']
        assert client.post('/events/api/sources/not-a-source/retry',headers=headers).status_code==404
        with core.db() as db:db.execute("UPDATE source_jobs SET state='done'")
        assert client.post('/events/api/sources/a/retry',headers=headers).status_code==429

def test_failed_source_recovers_via_queued_retry(monkeypatch):
    s=source();stub_fetch(monkeypatch,{s['url']:page()});monkeypatch.setattr(worker,'geocode_pending',lambda *a:{'enabled':False})
    with core.db() as db:db.execute("UPDATE source_health SET status='error',failure_count=4")
    jobs.enqueue('a');worker.retry_one()
    with core.db() as db:
        h=dict(db.execute('SELECT * FROM source_health').fetchone());j=dict(db.execute('SELECT * FROM source_jobs').fetchone())
        assert h['failure_count']==0 and h['status']=='ok' and j['state']=='done'
        assert json.loads(h['coverage'])['pages_visited']==1

def test_status_exposes_structured_coverage_and_job():
    jobs.enqueue('a')
    with TestClient(api.app,base_url='https://testserver') as client:
        auth(client);r=client.get('/events/api/status').json()
        assert isinstance(r['sources'][0]['coverage'],dict)
        assert r['sources'][0]['retry']['state']=='queued'
        assert 'session_secret' not in json.dumps(r)

def test_douban_ticket_cards_included_hosts_rejected(monkeypatch):
    html='<li class="list-entry"><p class="event-title"><a href="https://www.douban.com/event/123/?icn=list-shopitem">票务推荐</a></p><p>10月17日</p></li><li class="list-entry"><p class="title"><a href="https://site.douban.com/123/">主办方</a></p></li>'
    source_data=source(kind='douban',detail_budget=0);stub_fetch(monkeypatch,{source_data['url']:html})
    r=coverage.collect_report(source_data)
    assert r['coverage']['visible']==2 and r['coverage']['extracted']==1
    assert r['coverage']['rejected']['非活动主办方卡片']==1 and r['coverage']['parser_unaccounted']==0
    assert r['items'][0]['start_at'] is None and len(r['items'])==1
    assert r['items'][0]['url']=='https://www.douban.com/event/123/'

def test_microdata_detail_date_is_explicit_only():
    html='<h1>票务活动</h1><meta itemprop="startDate" content="2026-10-01T15:00:00+08:00"><span itemprop="location">深圳南山剧院</span>'
    out=coverage.microdata_detail(BeautifulSoup(html,'html.parser'),'https://www.douban.com/event/123/')
    assert out[0]['start_at']=='2026-10-01T15:00:00+08:00'
    assert coverage.microdata_detail(BeautifulSoup('<p>10月1日</p>','html.parser'),'https://example.com')==[]


def test_enriched_district_survives_non_location_source_change():
    event={'title':'深圳机器人','url':'https://example.com/event/1','location':'深圳博物馆历史民俗馆','summary':'活动一','start_at':'2026-10-17'}
    core.ingest(source(),event)
    with core.db() as db:db.execute("UPDATE events SET district='福田'")
    core.ingest(source(),{**event,'summary':'活动介绍更新'})
    with core.db() as db:assert db.execute('SELECT district FROM events').fetchone()[0]=='福田'
