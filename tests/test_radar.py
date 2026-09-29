from __future__ import annotations
import json
from datetime import datetime, timedelta, date
from pathlib import Path
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from icalendar import Calendar
from radar import core, api, worker
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
