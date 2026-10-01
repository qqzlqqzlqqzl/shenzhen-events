import json,subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from radar import api, core

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    (tmp_path/'static').mkdir();(tmp_path/'sources.json').write_text('[]')
    monkeypatch.setattr(core,'ROOT',tmp_path);monkeypatch.setattr(api,'ROOT',tmp_path)
    api.initialize_settings();core.init()

def test_custom_date_range_includes_overlaps_not_article_publish_date():
    for slug,start,end in [('inside','2026-12-31T23:00:00+08:00','2027-01-01T01:00:00+08:00'),('boundary','2027-01-02','2027-01-03'),('before','2026-12-30','2026-12-31'),('unknown',None,None)]:
        core.ingest({'id':'a'},{'title':slug,'url':'https://example.com/'+slug,'start_at':start,'end_at':end,'location':'深圳','summary':'test'})
    with TestClient(api.app,base_url='https://testserver') as c:
        c.cookies.set(api.COOKIE,api.sign_session({'id':1,'username':'test'}),path='/events')
        r=c.get('/events/api/events?period=range&start=2027-01-01&end=2027-01-02')
        assert r.status_code==200 and [e['title'] for e in r.json()['items']]==['inside']
        for start,end in [('2027-02-30','2027-03-03'),('2027-01-03','2027-01-01'),('2027-01-01','2028-01-01')]:
            assert c.get('/events/api/events',params={'period':'range','start':start,'end':end}).status_code==400

def planner(expr):
    script="require('./static/planner.js');console.log(JSON.stringify("+expr+"))"
    return json.loads(subprocess.check_output(['node','-e',script],cwd=Path(__file__).parents[1],text=True))

def test_saved_view_query_removes_credentials_and_event_identity():
    value=planner("RadarPlanner.cleanQuery('view=all&topic='+encodeURIComponent('机器人')+'&token=secret&event=private&from=2026-10-01&password=oops')")
    assert 'token' not in value and 'password' not in value and 'event=' not in value and 'from=' in value

def test_saved_view_storage_validation_limits_and_deduplication():
    rows=[{'name':'重复','query':'view=all'},{'name':'重复','query':'view=calendar'},{'name':'x'*50,'query':''},{'name':'good','query':'token=s'}]
    value=planner('RadarPlanner.decode('+json.dumps(json.dumps(rows))+')')
    assert value==[{'name':'重复','query':'view=all'},{'name':'good','query':''}]
    assert planner("RadarPlanner.decode('{broken')")==[]
    assert planner("RadarPlanner.validDay('2026-02-31')") is False

def test_range_includes_end_day_and_year_boundary():
    assert planner("RadarPlanner.range('2026-12-31','2027-01-01')")=={'start':'2026-12-31','end':'2027-01-02','days':2}
    assert planner("RadarPlanner.range('','')") is None
