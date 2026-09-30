from __future__ import annotations
import json
from datetime import datetime, timedelta, date
from pathlib import Path
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from icalendar import Calendar
from radar import core, api, worker, collectors
from radar.collectors import lianpu, bendibao, jsonld, rss, fetch, SourceError
from radar.calendar import make_calendar

@pytest.fixture(autouse=True)
def isolate(tmp_path,monkeypatch):
    (tmp_path/'static').mkdir();(tmp_path/'static/index.html').write_text('<html>test</html>')
    (tmp_path/'sources.json').write_text(json.dumps([{'id':'a','name':'主办方','url':'https://example.com','priority':10,'interval_hours':6},{'id':'b','name':'聚合站','url':'https://example.org','priority':40,'interval_hours':6}]))
    monkeypatch.setattr(core,'ROOT',tmp_path);monkeypatch.setattr(api,'ROOT',tmp_path);monkeypatch.setattr(worker,'ROOT',tmp_path)
    api.initialize_settings();core.init();api.ATTEMPTS.clear()
    yield tmp_path

def source(id='a'):return {'id':id,'priority':10 if id=='a' else 40}
def ev(**updates):
    start=core.now()+timedelta(days=7)
    e={'title':'深圳开源机器人机械臂实践工作坊','url':'https://example.com/event/1','start_at':start.isoformat(),'end_at':(start+timedelta(hours=3)).isoformat(),'location':'深圳市南山区创客中心','summary':'开源机器人与机械臂现场工作坊。','all_day':False,'cost_text':'免费'};e.update(updates);return e

def test_shanghai_conversion():assert core.iso('2026-10-17T01:30:00Z')=='2026-10-17T09:30:00+08:00'
@pytest.mark.parametrize('s,expected',[('2026.10.14-2026.10.16',('2026-10-14','2026-10-17')),('2026年10月14日 – 16日',('2026-10-14','2026-10-17')),('2026/09/12',('2026-09-12','2026-09-13'))])
def test_explicit_dates(s,expected):assert tuple(x[:10] for x in core.date_range(s))==expected
@pytest.mark.parametrize('s',['9月29日','昨天','2026-02-31','暂无时间','2026年10月16日-2026年10月14日'])
def test_dates_unknown_or_invalid(s):assert core.date_range(s)==(None,None)
def test_url_safety():
    assert core.canon_url('javascript:alert(1)')==''
    assert core.canon_url('https://a:b@example.com/')==''
    assert core.canon_url('https://example.com/x?id=9&utm_source=x#top')=='https://example.com/x?id=9'
def test_cost_unknown_is_not_free():assert core.normalize_event(ev(cost_text=''))['cost_free'] is False

def test_cross_source_dedup():
    e=ev();core.ingest(source(),e);core.ingest(source('b'),{**e,'url':'https://example.org/other'})
    rows=core.events();assert len(rows)==1;assert len(rows[0]['sources'])==2;assert rows[0]['url']==e['url']

def test_same_url_update_keeps_identity_and_preferences():
    e=ev();assert core.ingest(source(),e);assert core.ingest(source(),e) is False
    id=core.events()[0]['id']
    with core.db() as c:c.execute('INSERT INTO preferences(event_id,favorite) VALUES(?,1)',(id,))
    e['start_at']=(core.now()+timedelta(days=8)).isoformat();e['end_at']=(core.now()+timedelta(days=8,hours=2)).isoformat();core.ingest(source(),e)
    assert core.events(favorites=True)[0]['id']==id
    assert core.events()[0]['start_at'][:10]==e['start_at'][:10]
@pytest.mark.parametrize('changes',[{'location':'深圳市龙岗区星河中心'},{'start_at':'2027-01-01T09:00:00+08:00'},{'start_at':'2027-01-02T11:00:00+08:00'}])
def test_no_false_merges(changes):
    a=ev(start_at='2027-01-02T09:00:00+08:00');b={**a,**changes};assert not core.is_duplicate(a,b)

def test_missing_or_past_dates_not_upcoming():
    core.ingest(source(),ev(start_at=None,end_at=None));core.ingest(source(),ev(url='https://example.com/old',start_at='2020-01-01',end_at='2020-01-02'))
    assert not core.events();assert len(core.events(period='review'))==1

def test_sunday_weekend_includes_sunday(monkeypatch):
    monkeypatch.setattr(core,'now',lambda:datetime(2026,10,4,9,0,tzinfo=core.TZ))
    core.ingest(source(),ev(start_at='2026-10-04T14:00:00+08:00',end_at='2026-10-04T17:00:00+08:00'))
    assert len(core.events(period='weekend'))==1

def test_ics_exclusive_end_and_stable_uid():
    e=ev(start_at='2026-10-14',end_at='2026-10-17',all_day=True);core.ingest(source(),e)
    with core.db() as c:row=dict(c.execute('SELECT * FROM events').fetchone())
    row['sources']=[]
    a=Calendar.from_ical(make_calendar([row])).walk('VEVENT')[0]
    b=Calendar.from_ical(make_calendar([row])).walk('VEVENT')[0]
    assert a.decoded('dtstart')==date(2026,10,14);assert a.decoded('dtend')==date(2026,10,17);assert a['uid']==b['uid']

def test_lianpu_uses_machine_dates():
    s=BeautifulSoup('<article><h3><a href="/event/e">机器人活动</a></h3><p>实践</p><time datetime="2026-10-17T01:00:00Z">今天</time><time datetime="2026-10-17T09:00:00Z">晚上</time><p>深圳 / 南山区</p><span>免费</span></article>','html.parser')
    e=lianpu(s,'https://example.com')[0];assert e['start_at']=='2026-10-17T09:00:00+08:00';assert e['cost_text']=='免费'

def test_bendibao_event_date_label():
    s=BeautifulSoup('<div class="main-single-block" data-url="https://example.com/e"><div class="main-single-block-title">科技展</div><div><span class="main-single-block-des">活动时间</span><span>2026.10.01-2026.10.07</span></div><div><span class="main-single-block-des">活动地址</span><span>深圳南山</span></div></div>','html.parser')
    e=bendibao(s,'https://example.com')[0];assert e['start_at'].startswith('2026-10-01');assert e['end_at'].startswith('2026-10-08')

def test_jsonld_not_article_date():
    s=BeautifulSoup('<script type="application/ld+json">{"@type":"Article","headline":"深圳活动","datePublished":"2026-10-01"}</script>','html.parser');assert jsonld(s,'https://example.com')==[]

def test_rss_publication_not_event_date():
    xml='<rss version="2.0"><channel><title>example</title><item><title>示例文章</title><link>https://example.com/a</link><description>这里是文章内容而不是活动时间</description><pubDate>Tue, 29 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>'
    assert rss({'id':'a'},xml)[0]['start_at'] is None

def test_ssrf_localhost_rejected():
    with pytest.raises(SourceError):fetch('http://127.0.0.1:8092/')

def auth(client):client.cookies.set(api.COOKIE,api.sign_session({'id':1,'username':'test-owner'}),path='/events')

def test_private_api_and_csrf():
    with TestClient(api.app,base_url='https://testserver') as c:
        assert c.get('/events/api/health').status_code==200
        assert c.get('/events/api/events').status_code==401
        assert c.post('/events/api/login',json={'username':'a','password':'b'}).status_code==403
        assert c.get('/events/calendar.ics').status_code==401
        auth(c);assert c.get('/events/api/events').status_code==200
        s=c.get('/events/api/status').json();assert 'session_secret' not in json.dumps(s);assert 'model_base' not in json.dumps(s)

def test_miniflux_auth_endpoint_respects_base_path():
    assert api.AUTH_URL=='http://127.0.0.1:8091/mf/v1/me'

def test_login_delegation_and_cookie(monkeypatch):
    class Result:
        status_code=200
        def json(self):return {'id':1,'username':'test-owner','is_admin':True}
    calls=[]
    def get(self,url,**kwargs):calls.append((url,kwargs));return Result()
    monkeypatch.setattr(requests_session:=api.requests.Session,'get',get)
    with TestClient(api.app,base_url='https://testserver') as c:
        r=c.post('/events/api/login',headers={'X-Radar-Request':'1'},json={'username':'test-owner','password':'synthetic-test-value'})
        assert r.status_code==200;cookie=r.headers['set-cookie'];assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=lax' in cookie;assert calls[0][0]==api.AUTH_URL
        assert c.get('/events/api/session').status_code==200

def test_favorite_roundtrip():
    core.ingest(source(),ev());id=core.events()[0]['id']
    with TestClient(api.app,base_url='https://testserver') as c:
        auth(c);r=c.post('/events/api/preferences/'+id,headers={'X-Radar-Request':'1'},json={'favorite':True});assert r.status_code==200
        assert c.get('/events/api/events?favorites=true').json()['total']==1
        assert c.post('/events/api/preferences/'+id,headers={'X-Radar-Request':'1','Origin':'https://evil.example'},json={'favorite':False}).status_code==403

def test_budget_hard_cap(monkeypatch):
    monkeypatch.setattr(worker,'config',lambda:{'daily_calls':2,'daily_tokens':100})
    assert worker.reserve(50);assert worker.reserve(50);assert not worker.reserve(1)

def test_unproved_ai_date_stays_review(monkeypatch):
    core.ingest(source(),ev(start_at=None,end_at=None))
    with core.db() as c:id=c.execute('SELECT id FROM raw_items').fetchone()[0]
    monkeypatch.setattr(worker,'ai_batch',lambda rows:[{'id':id,'is_shenzhen_offline':True,'event_date':'2026-10-10','date_evidence':'2026年10月10日','location':'深圳市南山区','topics':['机器人'],'priority':'high'}])
    worker.analyze(1);assert len(core.events(period='review'))==1;assert not core.events()

def test_exact_alias_dedup_survives_title_drift(tmp_path):
    (tmp_path/'dedupe_aliases.json').write_text(json.dumps([{'id':'aws-day','date':'2027-01-09','urls':['https://example.com/event/1','https://example.org/other']}]))
    a=ev(title='Bridge with Signal 深圳技术社区日',start_at='2027-01-09T09:00:00+08:00',end_at='2027-01-09T17:00:00+08:00')
    b=ev(title='AWS Community Day Shenzhen 2027',url='https://example.org/other',start_at='2027-01-09T09:00:00+08:00',end_at='2027-01-09T17:00:00+08:00')
    assert not core.is_duplicate(a,b)
    core.ingest(source(),a);core.ingest(source('b'),b)
    rows=core.events();assert len(rows)==1;assert len(rows[0]['sources'])==2

def test_reconcile_aliases_merges_existing_rows(tmp_path):
    a=ev(title='Bridge with Signal 深圳技术社区日',start_at='2027-01-09T09:00:00+08:00',end_at='2027-01-09T17:00:00+08:00')
    b=ev(title='AWS Community Day Shenzhen 2027',url='https://example.org/other',start_at='2027-01-09T00:00:00+08:00',end_at='2027-01-10T00:00:00+08:00',all_day=True)
    core.ingest(source(),a);core.ingest(source('b'),b);assert len(core.events())==2
    (tmp_path/'dedupe_aliases.json').write_text(json.dumps([{'id':'aws-day','date':'2027-01-09','urls':['https://example.com/event/1','https://example.org/other']}]))
    with core.db() as c:
        ids=[x['id'] for x in c.execute('select id from events order by origin_priority')]
        c.execute('insert into preferences(event_id,favorite,hidden) values(?,?,?)',(ids[-1],1,1))
    merged=core.reconcile_aliases();assert len(merged)==1
    rows=core.events(include_hidden=True);assert len(rows)==1;assert len(rows[0]['sources'])==2;assert rows[0]['favorite']==1;assert rows[0]['hidden']==1

def test_sogou_discovers_current_account_markup(monkeypatch):
    html='<ul class="news-list"><li><h3><a href="/link?url=x">深圳机器人工作坊</a></h3><p class="txt-info">深圳南山线下活动</p><div class="s-p"><span class="all-time-y2">深圳创客社区</span></div></li></ul>'
    soup=BeautifulSoup(html,'html.parser')
    monkeypatch.setattr(collectors,'fetch',lambda url:('',soup,url));monkeypatch.setattr(collectors.time,'sleep',lambda _:None)
    out=collectors.sogou({'url':'https://weixin.sogou.com/weixin'})
    assert len(out)==2 and all(x['organizer']=='深圳创客社区' for x in out)
    with core.db() as c:
        row=c.execute('select name,hits from candidates where name=?',('深圳创客社区',)).fetchone()
        assert row['hits']==2

# Regression cases from interaction review, issues #3/#4/#5.
def test_saved_past_and_cancelled_remain_visible():
    core.ingest(source(),ev(start_at='2026-01-01',end_at='2026-01-02'))
    core.ingest(source(),ev(url='https://example.com/cancel',status='cancelled'))
    with core.db() as c:
        for r in c.execute('SELECT id FROM events').fetchall():
            c.execute('INSERT INTO preferences(event_id,favorite) VALUES(?,1)',(r['id'],))
    with TestClient(api.app,base_url='https://testserver') as client:
        auth(client)
        r=client.get('/events/api/events?period=saved&favorites=true')
        assert r.status_code==200 and r.json()['total']==2

def test_calendar_range_includes_past_excludes_end_boundary():
    core.ingest(source(),ev(start_at='2026-01-09T23:00:00+08:00',end_at='2026-01-10T01:00:00+08:00'))
    core.ingest(source(),ev(url='https://example.com/out',start_at='2026-01-11',end_at='2026-01-12'))
    with TestClient(api.app,base_url='https://testserver') as client:
        auth(client)
        r=client.get('/events/api/events',params={'period':'calendar','start':'2026-01-10','end':'2026-01-11'})
        assert r.status_code==200 and r.json()['total']==1
        for a,b in [('invalid','2026-01-02'),('2026-02-01','2026-01-01'),('2026-01-01','2028-01-01')]:
            assert client.get('/events/api/events',params={'period':'calendar','start':a,'end':b}).status_code==400

def test_preference_response_is_authoritative():
    core.ingest(source(),ev());eid=core.events()[0]['id']
    with TestClient(api.app,base_url='https://testserver') as client:
        auth(client);r=client.post('/events/api/preferences/'+eid,headers={'X-Radar-Request':'1'},json={'favorite':True})
        assert r.json()['favorite'] is True and r.json()['hidden'] is False

def test_detail_endpoint_can_open_past_record():
    core.ingest(source(),ev(start_at='2026-01-01',end_at='2026-01-02'))
    with core.db() as c:eid=c.execute('SELECT id FROM events').fetchone()['id']
    with TestClient(api.app,base_url='https://testserver') as client:
        assert client.get('/events/api/event/'+eid).status_code==401
        auth(client);r=client.get('/events/api/event/'+eid)
        assert r.status_code==200 and r.json()['id']==eid
        assert client.get('/events/api/event/not-existing').status_code==404
        assert client.get('/events/api/event/'+eid+'.ics').status_code==200

def test_health_count_does_not_claim_empty_partial_is_working():
    with core.db() as c:
        c.execute("UPDATE source_health SET status='ok',raw_count=3 WHERE id='a'")
        c.execute("UPDATE source_health SET status='partial',raw_count=0 WHERE id='b'")
    with TestClient(api.app,base_url='https://testserver') as client:
        auth(client);s=client.get('/events/api/stats').json()
        assert s['working_sources']==1 and s['partial_sources']==1

def test_cross_midnight_ics_never_invents_event_duration():
    core.ingest(source(),ev(start_at='2027-01-09T23:00:00+08:00',end_at='2027-01-10T01:00:00+08:00'))
    with TestClient(api.app,base_url='https://testserver') as client:
        auth(client);eid=core.events()[0]['id'];r=client.get('/events/api/event/'+eid+'.ics')
        parsed=Calendar.from_ical(r.content).walk('VEVENT')[0]
        assert parsed.decoded('dtend')-parsed.decoded('dtstart')==timedelta(hours=2)

def test_transient_sogou_link_does_not_duplicate_or_reanalyze():
    s={'id':'sogou-discovery','priority':30};e=ev(url='https://weixin.sogou.com/link?url=A&token=one',published_at='2026-09-29',organizer='测试主办方')
    assert core.ingest(s,e)
    with core.db() as c:c.execute("UPDATE raw_items SET analysis_state='done'")
    assert not core.ingest(s,{**e,'url':'https://weixin.sogou.com/link?url=B&token=two'})
    with core.db() as c:
        assert c.execute('SELECT COUNT(*) FROM raw_items').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM events').fetchone()[0]==1
        assert c.execute('SELECT analysis_state FROM raw_items').fetchone()[0]=='done'
        assert 'token=two' in c.execute('SELECT url FROM event_sources').fetchone()[0]

def test_distinct_explicit_publication_dates_are_not_collapsed():
    s={'id':'sogou-discovery','priority':30};e=ev(start_at=None,end_at=None,url='https://weixin.sogou.com/link?url=A',published_at='2026-09-29')
    core.ingest(s,e);core.ingest(s,{**e,'url':'https://weixin.sogou.com/link?url=B','published_at':'2026-09-30'})
    with core.db() as c:assert c.execute('SELECT COUNT(*) FROM raw_items').fetchone()[0]==2

def test_search_duplicate_repair_is_conservative_idempotent_and_preserves_favorite(monkeypatch):
    from radar import source_identity,repair_sources
    source_data={'id':'sogou-discovery','priority':30}
    e=ev(start_at=None,end_at=None,url='https://weixin.sogou.com/link?url=A',published_at='2026-09-29')
    with monkeypatch.context() as m:
        m.setattr(source_identity,'is_search',lambda *args:False)
        core.ingest(source_data,e);core.ingest(source_data,{**e,'url':'https://weixin.sogou.com/link?url=B'})
    with core.db() as c:
        ids=[r['id'] for r in c.execute('SELECT id FROM events')]
        assert len(ids)==2
        c.execute('INSERT INTO preferences(event_id,favorite,hidden) VALUES(?,1,1)',(ids[-1],))
    assert repair_sources.repair()['duplicate_raw_rows']==1
    assert repair_sources.repair(True)['duplicate_raw_rows']==1
    assert repair_sources.repair()['duplicate_raw_rows']==0
    with core.db() as c:
        assert c.execute('SELECT COUNT(*) FROM raw_items').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM event_sources').fetchone()[0]==1
        assert tuple(c.execute('SELECT favorite,hidden FROM preferences').fetchone())==(1,1)

def test_weekend_long_running_uses_window_date_and_can_be_hidden(monkeypatch):
    monkeypatch.setattr(core,'now',lambda:datetime(2026,9,29,12,0,tzinfo=core.TZ))
    core.ingest(source(),ev(title='长期展览',start_at='2026-05-30',end_at='2026-10-10',all_day=True))
    rows=core.events(period='weekend',hide_long=False)
    assert len(rows)==1 and rows[0]['long_running'] is True
    assert rows[0]['display_at'].startswith('2026-10-03')
    assert rows[0]['period_label']=='本周末仍开放'
    assert core.events(period='weekend',hide_long=True)==[]

def test_short_multiday_event_is_not_long_running(monkeypatch):
    monkeypatch.setattr(core,'now',lambda:datetime(2026,9,29,12,0,tzinfo=core.TZ))
    core.ingest(source(),ev(title='三日创客大会',start_at='2026-10-02',end_at='2026-10-05',all_day=True))
    rows=core.events(period='weekend',hide_long=True)
    assert len(rows)==1 and rows[0]['long_running'] is False

def test_time_sort_uses_effective_display_date(monkeypatch):
    monkeypatch.setattr(core,'now',lambda:datetime(2026,9,29,12,0,tzinfo=core.TZ))
    core.ingest(source(),ev(title='长期展览',start_at='2026-05-30',end_at='2026-10-10',all_day=True))
    core.ingest(source(),ev(title='周六工作坊',url='https://example.com/workshop',start_at='2026-10-03T10:00:00+08:00',end_at='2026-10-03T12:00:00+08:00'))
    asc=core.events(period='weekend',hide_long=False,sort='asc')
    desc=core.events(period='weekend',hide_long=False,sort='desc')
    assert [x['title'] for x in asc]==['长期展览','周六工作坊']
    assert [x['title'] for x in desc]==['周六工作坊','长期展览']

def test_listing_supports_long_filter_and_time_sort(monkeypatch):
    monkeypatch.setattr(core,'now',lambda:datetime(2026,9,29,12,0,tzinfo=core.TZ))
    core.ingest(source(),ev(title='长期展览',start_at='2026-05-30',end_at='2026-10-10',all_day=True))
    core.ingest(source(),ev(title='周六工作坊',url='https://example.com/workshop',start_at='2026-10-03T10:00:00+08:00',end_at='2026-10-03T12:00:00+08:00'))
    with TestClient(api.app,base_url='https://testserver') as client:
        auth(client)
        r=client.get('/events/api/events?period=weekend&hide_long=true&sort=asc')
        assert r.status_code==200 and [x['title'] for x in r.json()['items']]==['周六工作坊']
        assert client.get('/events/api/events?sort=wrong').status_code==400


@pytest.mark.parametrize('day,expected',[(13,0),(14,1),(15,1),(16,1),(17,0)])
def test_three_day_event_in_each_covered_day(day,expected):
    core.ingest(source(),ev(title='2026华南3D打印展',start_at='2026-10-14',end_at='2026-10-17',all_day=True))
    with TestClient(api.app,base_url='https://testserver') as client:
        auth(client)
        r=client.get('/events/api/events',params={'period':'calendar','start':f'2026-10-{day:02}','end':f'2026-10-{day+1:02}'})
        assert r.status_code==200 and r.json()['total']==expected


def test_month_overlap_returns_one_record_and_preserves_favorites():
    core.ingest(source(),ev(title='跨月展览',start_at='2026-09-30',end_at='2026-10-03',all_day=True))
    with core.db() as c:
        before=dict(c.execute('SELECT * FROM events').fetchone())
        c.execute('INSERT INTO preferences(event_id,favorite) VALUES(?,1)',(before['id'],))
    with TestClient(api.app,base_url='https://testserver') as client:
        auth(client)
        for start,end in [('2026-09-01','2026-10-01'),('2026-10-01','2026-11-01')]:
            data=client.get('/events/api/events',params={'period':'calendar','start':start,'end':end,'hide_long':'true'}).json()
            assert data['total']==1
            assert data['items'][0]['favorite']==1
            assert data['items'][0]['start_at']==before['start_at']
            assert data['items'][0]['end_at']==before['end_at']
            assert data['items'][0]['location']==before['location']
    with core.db() as c:assert dict(c.execute('SELECT * FROM events').fetchone())==before

@pytest.mark.parametrize('end', [None,'2026-10-01T00:00:00+08:00','2026-10-01T10:00:00+08:00'])
def test_calendar_all_day_unknown_or_nonpositive_end_covers_its_known_day(end):
    core.ingest(source(),ev(title='结束未注明的活动',start_at='2026-10-01',end_at=end,all_day=True))
    with TestClient(api.app,base_url='https://testserver') as client:
        auth(client)
        for start,finish in [('2026-10-01','2026-11-01'),('2026-10-01T12:00:00+08:00','2026-10-02')]:
            response=client.get('/events/api/events',params={'period':'calendar','start':start,'end':finish})
            assert response.status_code==200 and response.json()['total']==1
        assert client.get('/events/api/events',params={'period':'calendar','start':'2026-10-02','end':'2026-10-03'}).json()['total']==0
    with core.db() as c:assert c.execute('SELECT end_at FROM events').fetchone()[0]==core.iso(end)
