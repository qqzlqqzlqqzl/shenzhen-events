import json,subprocess
from pathlib import Path
import pytest
from radar import core,api
from fastapi.testclient import TestClient


def js(expr):
    return json.loads(subprocess.check_output(['node','-e',"require('./static/ui-state.js');require('./static/event-workflows.js');console.log(JSON.stringify("+expr+"))"],cwd=Path(__file__).parents[1],text=True))

def test_comparison_respects_unknown_ends_and_end_boundary():
    a={'start_at':'2026-10-03T10:00:00+08:00','end_at':'2026-10-03T12:00:00+08:00'}
    b={'start_at':'2026-10-03T12:00:00+08:00','end_at':'2026-10-03T14:00:00+08:00'}
    assert js('RadarEventWorkflows.overlap('+json.dumps(a)+','+json.dumps(b)+')') is False
    assert js('RadarEventWorkflows.overlap('+json.dumps(a)+','+json.dumps(a)+')') is True
    assert js('RadarEventWorkflows.overlap('+json.dumps(a)+',{})') is None
    assert js('RadarEventWorkflows.overlap('+json.dumps({**a,'all_day':True})+','+json.dumps(b)+')') is None

def test_sharing_rejects_script_urls_and_does_not_use_private_current_url():
    assert js("RadarEventWorkflows.safeOriginal('javascript:alert(1)')") == ''
    assert js("RadarEventWorkflows.safeOriginal('https://user:password@example.com/')") == ''
    text=js("RadarEventWorkflows.shareText({title:'活动',url:'https://example.com/event',start_at:'2026-10-03',all_day:true})")
    assert text.endswith('https://example.com/event') and '/events/calendar.ics' not in text

def test_saved_collection_keeps_long_and_unplanned(tmp_path,monkeypatch):
    (tmp_path/'static').mkdir();(tmp_path/'sources.json').write_text('[]')
    for m in (core,api):monkeypatch.setattr(m,'ROOT',tmp_path)
    api.initialize_settings();core.init()
    for name,start,end in [('long','2026-09-01','2026-12-01'),('unknown',None,None)]:
        core.ingest({'id':'a'},{'title':name,'url':'https://example.com/'+name,'start_at':start,'end_at':end,'location':'深圳'})
    with core.db() as c:
        for e in c.execute('SELECT id FROM events').fetchall():c.execute('INSERT INTO preferences(event_id,favorite) VALUES(?,1)',(e[0],))
    assert len(core.events(period='saved',favorites=True,hide_long=True))==2
    with TestClient(api.app,base_url='https://testserver') as c:
        assert c.get('/events/api/calendar-summary').status_code==401
        c.cookies.set(api.COOKIE,api.sign_session({'id':1,'username':'owner'}),path='/events')
        assert c.get('/events/api/calendar-summary').json()=={'total':2,'long_running':1,'unscheduled':1,'safety_epoch':0}
