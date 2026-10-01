import json
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from radar import api, core, personal, worker


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    (tmp_path/'static').mkdir(); (tmp_path/'sources.json').write_text('[{"id":"a","name":"test","url":"https://example.com"}]')
    for module in (core, api, worker):monkeypatch.setattr(module,'ROOT',tmp_path)
    api.initialize_settings();core.init()
    yield tmp_path


def event(slug='a', old=False):
    day=core.now()+timedelta(days=-100 if old else 2)
    core.ingest({'id':'a','priority':10},{'title':'活动 '+slug,'url':'https://example.com/'+slug,'start_at':day.isoformat(),'end_at':(day+timedelta(hours=2)).isoformat(),'location':'深圳南山','summary':'测试活动'})
    with core.db() as c:return c.execute('SELECT id FROM events WHERE url=?',('https://example.com/'+slug,)).fetchone()[0]


def client():
    c=TestClient(api.app,base_url='https://testserver')
    c.cookies.set(api.COOKIE,api.sign_session({'id':1,'username':'owner'}),path='/events')
    return c


def test_review_filter_export_is_private_and_includes_past():
    eid=event(old=True);personal.update(eid,{'feedback':'not_interested','feedback_tags':['time_conflict']})
    with client() as c:
        r=c.get('/events/api/events?period=feedback&feedback_tag=time_conflict').json()
        assert r['total']==1 and r['items'][0]['id']==eid
        assert c.get('/events/api/events?period=feedback&feedback=interested').json()['total']==0
        assert c.get('/events/api/events?feedback=typo').status_code==400
        data=c.get('/events/api/feedback-export');assert data.json()['count']==1
        assert data.json()['items'][0]['feedback_tags']==['time_conflict']
        assert 'session_secret' not in data.text and 'token' not in data.text
        c.cookies.clear();assert c.get('/events/api/feedback-export').status_code==401


def test_viewed_is_explicit_and_never_changes_judgement():
    eid=event();personal.update(eid,{'favorite':True,'feedback':'interested'})
    with client() as c:
        before=c.get('/events/api/event/'+eid).json();assert not before['viewed_at']
        assert c.get('/events/api/events?viewed=unseen').json()['total']==1
        assert c.post('/events/api/viewed/'+eid).status_code==403
        r=c.post('/events/api/viewed/'+eid,headers={'X-Radar-Request':'1'});assert r.status_code==200
        after=c.get('/events/api/event/'+eid).json()
        for key in ('favorite','feedback','feedback_tags','revision'):assert after[key]==before[key]
        assert after['viewed_at'] and c.get('/events/api/events?period=history').json()['total']==1
        assert c.get('/events/api/events?viewed=unseen').json()['total']==0


def test_revision_conflict_no_partial_write_and_clear_is_a_revision():
    eid=event();r=personal.update(eid,{'favorite':True},0);assert r['revision']==1
    with client() as c:
        r=c.post('/events/api/preferences/'+eid,json={'feedback':'interested','favorite':False,'expected_revision':0},headers={'X-Radar-Request':'1'})
        assert r.status_code==409 and r.json()['current']['favorite']
    r=personal.update(eid,{'feedback':'interested'},1)
    r=personal.update(eid,{'feedback':''},r['revision'])
    assert r['feedback']=='' and r['favorite'] and r['feedback_updated_at'] and r['revision']==3
    assert personal.update(eid,{'feedback':''},3)['revision']==3


def test_latest_clear_survives_alias_merge():
    a=event('a');b=event('b')
    # Fixtures may be naturally deduplicated, use distinct dates to exercise helper independently.
    if a==b:
        with core.db() as c:
            c.execute('INSERT INTO events(id,title) VALUES(?,?)',('explicit-other','Other'))
        b='explicit-other'
    personal.update(a,{'feedback':'interested'})
    personal.update(b,{'feedback':'not_interested'})
    personal.update(b,{'feedback':''})
    with core.db() as c:
        core.merge_preferences(c,a,b)
        r=personal.serialize(c.execute('SELECT * FROM preferences WHERE event_id=?',(a,)).fetchone())
    assert r['feedback']=='' and r['feedback_updated_at']


def test_retention_keeps_unstarred_training_labels():
    eid=event('labelled',old=True)
    personal.update(eid,{'feedback_tags':['topic_like']})
    worker.retention()
    with core.db() as c:
        assert c.execute('SELECT 1 FROM events WHERE id=?',(eid,)).fetchone()
        assert c.execute('SELECT favorite FROM preferences WHERE event_id=?',(eid,)).fetchone()[0]==0


def test_invalid_combined_patch_rolls_back_every_field():
    eid=event()
    with pytest.raises(ValueError):personal.update(eid,{'favorite':True,'feedback_tags':['unknown']})
    with core.db() as c:assert c.execute('SELECT * FROM preferences WHERE event_id=?',(eid,)).fetchone() is None


def test_migrations_repeat_without_changing_user_state():
    eid=event();before=personal.update(eid,{'feedback':'attended','favorite':True})
    core.init();core.init()
    with core.db() as c:after=personal.serialize(c.execute('SELECT * FROM preferences WHERE event_id=?',(eid,)).fetchone())
    assert all(after[k]==before[k] for k in after)
