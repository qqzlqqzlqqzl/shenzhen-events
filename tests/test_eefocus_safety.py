"""Durable cases 47–64 (excluding adapter case 59) and real fault/race seams."""
import copy
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar

from radar import api, collectors, core, coverage, eefocus as ee, safety, worker
from radar.calendar import make_calendar
from test_eefocus import DESIGN, PACK, isolated, load, transport, run, counts, report, stored

CASES=[c for c in json.loads((PACK/'cases.json').read_text())['cases'] if 47<=int(c['id'][:2])<=64 and not c['id'].startswith('59')]
ALIAS=ee.ORIGIN+'/event/980002.html'
CANONICAL=ee.ORIGIN+'/live/980102.html'


def client():
    result=TestClient(api.app)
    result.cookies.set(api.COOKIE,api.sign_session({'id':1,'username':'isolated-maintainer'}))
    return result


def seed(monkeypatch, held=False):
    pages={ee.LIST_URL:load('fixtures/redirect-list.html'),ALIAS:{'status':302,'location':CANONICAL},CANONICAL:load('fixtures/redirect-live-detail.html')}
    result,_,_=run(monkeypatch,pages)
    assert result['count']==1
    eid=stored()['id']
    with core.db() as c:
        c.execute('INSERT INTO preferences(event_id,favorite,feedback,feedback_tags,revision,viewed_at) VALUES(?,1,\'interested\',?,7,?)',
                  (eid,json.dumps(['topic_like']),'2026-09-20T11:00:00+08:00'))
        if held:
            details=json.loads(c.execute('SELECT details FROM events WHERE id=?',(eid,)).fetchone()[0])
            details.update(review_hold=True,review_notes='人工保留原文与地址',address_precision='online')
            c.execute('UPDATE events SET details=? WHERE id=?',(json.dumps(details),eid))
        c.execute("UPDATE detail_cache SET next_attempt='2026-09-21'")
    return eid


def seed_second_history(monkeypatch):
    """Materialize a separately verified *historical* edition from exact fixtures.

    Historical migration may contain reused aliases; today's admission correctly
    rejects replacing their owner. Use the real bounded transport/identity parser
    and exact anchoring seam to establish that earlier evidence, never bypass the
    current collector's history check for a newly acquired candidate.
    """
    canonical=ee.ORIGIN+'/live/980999.html'
    transport(monkeypatch,{ee.LIST_URL:load('fixtures/safety-historical-second-list.html'),
        ALIAS:{'status':302,'location':canonical},canonical:load('fixtures/safety-historical-second-detail.html')})
    metrics={'detail_attempted':0};deadline=time.monotonic()+10
    _,soup,final,_=ee.fetch(ee.LIST_URL,DESIGN['source'],deadline,metrics,inventory=True)
    base=ee.parse(soup,final)[0][0]
    _,soup,final,trace=ee.fetch(ALIAS,DESIGN['source'],deadline,metrics)
    patch,proof=ee.detail(base,soup,final,trace)
    item=ee.merge_detail(base,patch);ids=ee.record_bindings(DESIGN['source'],ALIAS,proof)
    item['_identity_binding_ids']=ids;assert core.ingest(DESIGN['source'],item)
    with core.db() as c:
        eid=c.execute('SELECT id FROM events WHERE url=?',(canonical,)).fetchone()[0]
        binding=c.execute('SELECT binding_id FROM eefocus_identity_bindings WHERE alias_url=? AND event_id=?',(ALIAS,eid)).fetchone()[0]
        assert c.execute('SELECT start_at FROM events WHERE id=?',(eid,)).fetchone()[0].startswith('2026-10-30')
    assert counts()==dict(raw_items=2,events=2,event_sources=2)
    return eid,binding


def immutable():
    with core.db() as c:
        return {table:[tuple(row) for row in c.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                for table in ('events','raw_items','event_sources','preferences','eefocus_identity_bindings')}


def cancelled(monkeypatch, listing=None):
    return run(monkeypatch,{ee.LIST_URL:listing or load('fixtures/safety-cancelled-list.html'),ALIAS:collectors.SourceError('ReadTimeout')})


def guards():
    with core.db() as c:return [dict(r) for r in c.execute("SELECT * FROM event_safety_guards WHERE state='active' ORDER BY rowid")]


def receipt():
    with core.db() as c:return json.loads(c.execute('SELECT receipt FROM safety_capture_runs ORDER BY rowid DESC LIMIT 1').fetchone()[0])


def resolve(monkeypatch):
    transport(monkeypatch,{ALIAS:{'status':302,'location':CANONICAL},CANONICAL:load('fixtures/safety-reinstatement-detail.html')})
    return ee.resolve_guard_details(DESIGN['source'],[r['guard_id'] for r in guards()],safety.uid('resolution'))


def planning(eid,eligible):
    c=client()
    assert bool(core.events()) is eligible
    for period in ('upcoming','week','calendar','range'):
        params={'period':period}
        if period in ('calendar','range'):params.update(start='2026-10-01',end='2026-11-01')
        response=c.get('/events/api/events',params=params)
        assert response.status_code==200,response.text
        # Week bounds may legitimately exclude the seeded October 23 date.
        if period!='week':assert (response.json()['total']>0) is eligible
    assert c.get('/events/api/events?period=saved').json()['total']==1
    point=c.get('/events/api/event/'+eid).json()
    assert point['planning_eligible'] is eligible
    assert point['stored_status']=='scheduled'
    feed=Calendar.from_ical(c.get('/events/calendar.ics?favorites=true').content)
    assert bool(feed.walk('VEVENT')) is eligible
    assert c.get('/events/api/event/'+eid+'.ics').status_code==(200 if eligible else 409)
    assert c.get('/events/api/calendar-summary').json()['unscheduled']==(0 if eligible else 1)
    if not eligible:assert point['safety']['warning']==safety.WARNING or json.loads(stored()['details'] if isinstance(stored()['details'],str) else json.dumps(stored()['details'])).get('review_hold')


@pytest.mark.parametrize('case',CASES,ids=[c['id'] for c in CASES])
def test_durable_fixture_case(case,monkeypatch):
    number=int(case['id'][:2]);inputs=case['inputs'];expect=json.loads(load(case['expected']))
    if number in (49,60):
        if number==60:
            with core.db() as c:c.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?)',(DESIGN['source']['id'],ALIAS,'failed','{}','error','2026-10-01','2026-10-03'))
        result,_,_=cancelled(monkeypatch)
        assert result['count']==result['changed']==0 and not guards()
        assert receipt()['unlinked_observations']==1 and counts()==dict(raw_items=0,events=0,event_sources=0)
        return
    eid=seed(monkeypatch,held=number==53);before=immutable()
    if number==57:
        result,_,_=run(monkeypatch,{ee.LIST_URL:load('fixtures/redirect-list.html'),ALIAS:collectors.SourceError('ReadTimeout')})
        assert result['count']==0 and not guards();planning(eid,True);assert immutable()==before;return
    if number in (58,63):
        variants=inputs.get('status_variants',[dict(list_html=inputs.get('list_html','fixtures/safety-sidebar-cancelled-list.html'))])
        for variant in variants:
            listing=load(variant['list_html']);result,_,_=cancelled(monkeypatch,listing)
            assert not guards() and result['count']==result['changed']==0
        assert immutable()==before;return
    if number in (50,56):
        second_eid,second_binding=seed_second_history(monkeypatch)
        before=immutable()
    result,metrics,_=cancelled(monkeypatch)
    assert result['count']==result['changed']==0
    assert len(guards())==(2 if number in (50,56) else 1)
    assert immutable()==before
    if number==47:
        assert receipt()['guards_created']==1;planning(eid,False)
    elif number in (48,61):
        capture_id=receipt()['capture_id']
        if number==61:resolve(monkeypatch);assert not guards()
        with core.db() as c:before_changes=c.execute('SELECT COUNT(*) FROM safety_guard_members').fetchone()[0];guard_rows=[tuple(r) for r in c.execute('SELECT * FROM event_safety_guards')]
        safety.replay_capture(capture_id)
        if number==61:
            # The new process reads and replays the immutable retained receipt.
            code="from radar import safety,core; import json; safety.replay_capture("+repr(capture_id)+");\nwith core.db() as c: print(json.dumps([tuple(r) for r in c.execute('SELECT * FROM event_safety_guards')]))"
            proc=subprocess.run([sys.executable,'-c',code],env={**os.environ,'RADAR_ROOT':str(core.ROOT)},capture_output=True,text=True,timeout=20,check=True)
            assert json.loads(proc.stdout)==[list(r) for r in guard_rows]
        with core.db() as c:
            assert [tuple(r) for r in c.execute('SELECT * FROM event_safety_guards')]==guard_rows
            assert c.execute('SELECT COUNT(*) FROM safety_guard_members').fetchone()[0]==before_changes
        planning(eid,number==61)
    elif number in (51,52):
        if number==51:
            run(monkeypatch,{ee.LIST_URL:load('fixtures/redirect-list.html'),ALIAS:collectors.SourceError('ReadTimeout')})
        else:
            transport(monkeypatch,{ALIAS:{'status':302,'location':CANONICAL},CANONICAL:load('fixtures/identity-43-unrelated-detail.html') if (PACK/'fixtures/identity-43-unrelated-detail.html').exists() else '<main><article class="main-event"><h1>其他活动</h1></article></main>'})
            with pytest.raises((collectors.SourceError,safety.SafetyError)):ee.resolve_guard_details(DESIGN['source'],[r['guard_id'] for r in guards()],'unrelated-resolution')
        planning(eid,False)
    elif number in (53,54):
        resolve(monkeypatch);assert not guards();assert immutable()==before;planning(eid,number==54)
    elif number==55:
        code="from radar import core; import json; point=core.events(event_id="+repr(eid)+",period='record')[0]; print(json.dumps({'up':len(core.events()),'saved':len(core.events(period='saved',favorites=True)),'eligible':point['planning_eligible'],'effective':point['effective_status'],'guards':point['safety']['guard_count']}))"
        env={**os.environ,'RADAR_ROOT':str(core.ROOT)}
        proc=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True,timeout=20,check=True)
        assert json.loads(proc.stdout)==dict(up=0,saved=1,eligible=False,effective='needs_review',guards=1);planning(eid,False)
    elif number==56:
        original=[r for r in guards() if r['event_id']==eid]
        snapshot=safety.guard_snapshot([r['guard_id'] for r in original])
        with core.db() as c:observations=[r[0] for r in c.execute('SELECT observation_id FROM safety_guard_members WHERE guard_id=?',(original[0]['guard_id'],))]
        reason=inputs['adjudication']['reason']
        body=dict(resolution_id='review-disassociate',expectations=snapshot,current_binding_id=second_binding,observation_ids=observations,review_reason=reason,authorized_actor='fixture-reviewer')
        headers={'x-radar-request':'1'}
        assert TestClient(api.app).post('/events/api/safety/disassociation',json=body,headers=headers).status_code==401
        response=client().post('/events/api/safety/disassociation',json=body,headers=headers);assert response.status_code==200,response.text
        result=response.json()
        assert result['resolved_guard_ids']==[original[0]['guard_id']]
        assert len(guards())==1 and guards()[0]['event_id']==second_eid;assert immutable()==before
        assert client().post('/events/api/safety/disassociation',json=body,headers=headers).json()==result
        with core.db() as c:
            audit=c.execute('SELECT kind,actor FROM safety_resolutions').fetchone()
            assert tuple(audit)==('authorized_reviewed_adjudication','maintainer:1')
    elif number==62:
        first=guards()[0];snapshot=safety.guard_snapshot([first['guard_id']])
        again=load('fixtures/safety-cancelled-list.html').replace('已取消','恢复举办后，本次10月23日活动再次取消。')
        cancelled(monkeypatch,again)
        assert len(guards())==2
        # Resolve the immutable first snapshot after cancellation B has committed.
        transport(monkeypatch,{ALIAS:{'status':302,'location':CANONICAL},CANONICAL:load('fixtures/safety-reinstatement-detail.html')})
        original_snapshot=safety.guard_snapshot
        monkeypatch.setattr(safety,'guard_snapshot',lambda ids:snapshot)
        ee.resolve_guard_details(DESIGN['source'],[first['guard_id']],'resolution-after-B')
        monkeypatch.setattr(safety,'guard_snapshot',original_snapshot)
        assert len(guards())==1 and guards()[0]['guard_id']!=first['guard_id'];planning(eid,False)
    elif number==64:
        first_capture=receipt()['capture_id'];resolve(monkeypatch);assert not guards()
        cancelled(monkeypatch)
        assert receipt()['capture_id']!=first_capture and len(guards())==1
        assert guards()[0]['reason']=='cancellation_generation_ambiguous_after_reinstatement';planning(eid,False)
    # The expected synthetic IDs/counters describe semantic scenarios; actual
    # durable UUIDs and transport metrics remain generated by production code.
    assert expect['admitted']==0 and expect['changed']==0


def captured(monkeypatch,listing=None):
    transport(monkeypatch,{ee.LIST_URL:listing or load('fixtures/safety-cancelled-list.html')})
    token=safety.claim(safety.begin_capture(DESIGN['source']))
    html,_,final,trace=ee.fetch(ee.LIST_URL,DESIGN['source'],time.monotonic()+10,{},inventory=True)
    return safety.retain(token,html,final,trace)


@pytest.mark.parametrize('statement',[
    'INSERT INTO safety_observations','INSERT INTO event_safety_guards',
    'INSERT INTO safety_guard_members','INSERT INTO safety_observation_targets',
    'INSERT INTO safety_target_evidence','UPDATE safety_observations',
    'UPDATE safety_meta','UPDATE safety_capture_runs','COMMIT'])
def test_each_receipt_write_failure_rolls_back_without_releasing_fence(monkeypatch,statement):
    eid=seed(monkeypatch);before=immutable();token=captured(monkeypatch)
    actual=core.sqlite3.connect
    class FaultConnection(sqlite3.Connection):
        def execute(self,sql,*args,**kwargs):
            if sql.startswith(statement):raise sqlite3.OperationalError('injected safety write failure')
            return super().execute(sql,*args,**kwargs)
        def commit(self):
            if statement=='COMMIT':raise sqlite3.OperationalError('injected commit failure')
            return super().commit()
    monkeypatch.setattr(core.sqlite3,'connect',lambda *args,**kwargs:actual(*args,**kwargs,factory=FaultConnection))
    with pytest.raises(sqlite3.OperationalError):safety.finalize(token)
    monkeypatch.setattr(core.sqlite3,'connect',actual)
    assert immutable()==before and not guards()
    with core.db() as c:
        assert c.execute('SELECT capture_state FROM safety_capture_runs WHERE capture_id=?',(token.id,)).fetchone()[0]=='captured'
        assert c.execute('SELECT COUNT(*) FROM safety_observations').fetchone()[0]==0
    assert client().get('/events/api/events').status_code==503
    safety.finalize(token);assert len(guards())==1;planning(eid,False)


@pytest.mark.parametrize('stage',['reserved','acquiring','captured','safety_finalized'])
def test_restart_capture_states_never_substitute_a_new_response(monkeypatch,stage):
    eid=seed(monkeypatch)
    token=safety.begin_capture(DESIGN['source'])
    if stage!='reserved':token=safety.claim(token)
    if stage in ('captured','safety_finalized'):
        token=safety.retain(token,load('fixtures/safety-cancelled-list.html'),ee.LIST_URL,[dict(url=ee.LIST_URL,status=200)])
    if stage=='safety_finalized':safety.finalize(token)
    code="from radar import core,safety; import json; c=core.db(); db=c.__enter__(); print(json.dumps({'fenced':safety.fenced(db),'captures':db.execute('SELECT COUNT(*) FROM safety_capture_runs').fetchone()[0]})); c.__exit__(None,None,None)"
    result=subprocess.run([sys.executable,'-c',code],env={**os.environ,'RADAR_ROOT':str(core.ROOT)},capture_output=True,text=True,timeout=20,check=True)
    assert json.loads(result.stdout)['fenced']==(stage!='safety_finalized')
    if stage in ('reserved','acquiring'):
        calls,_=transport(monkeypatch,{ee.LIST_URL:load('fixtures/recognized-empty.html')})
        result=worker.collect_source(DESIGN['source']);assert result['status']=='error' and calls==[]
        assert client().get('/events/api/events').json()['code']=='safety_unavailable'
        assert client().get('/events/api/event/'+eid).json()['planning_eligible'] is False
        if stage=='reserved':
            safety.recover_capture(token.id,token.revision,'prove_not_started','owner-revoked','authenticated:maintainer')
            with pytest.raises(safety.Conflict):safety.claim(token)
            planning(eid,True)
        else:
            for mode in ('prove_not_started','prove_no_accepted_inventory','replay_exact_capture'):
                with pytest.raises(safety.Integrity):safety.recover_capture(token.id,token.revision,mode,mode,'authenticated:maintainer')
            safety.recover_capture(token.id,token.revision,'retain_unresolved','lost-response','authenticated:maintainer')
            assert client().get('/events/api/events').status_code==503
    elif stage=='captured':
        safety.replay_ready();planning(eid,False)
    else:
        original=[dict(r) for r in guards()];safety.replay_capture(token.id);assert guards()==original


def test_safety_finalization_precedes_optional_transport_and_survives_failure(monkeypatch):
    eid=seed(monkeypatch);before=immutable()
    pages={ee.LIST_URL:load('fixtures/safety-cancelled-list.html'),ALIAS:RuntimeError('optional crash')}
    calls,_=transport(monkeypatch,pages)
    original=collectors.requests.Session
    class CheckingSession(original):
        def get(self,url,**kwargs):
            if url==ALIAS:
                assert receipt()['outcome']=='observed_and_applied'
                with core.db() as c:assert not safety.fenced(c)
            return super().get(url,**kwargs)
    monkeypatch.setattr(collectors.requests,'Session',CheckingSession)
    result=worker.collect_source(DESIGN['source'])
    assert result['status']=='error' and result['guards_created']==1 and not result.get('safety_update_failed')
    _,metrics=report()
    assert metrics['counters_available'] is False and metrics['http_requests_attempted'] is None
    assert metrics['detail_resolved'] is None and metrics['last_good']['admitted']==1
    assert immutable()==before;planning(eid,False)


@pytest.mark.parametrize('again',[False,True],ids=['membership_revision_conflict','independent_new_veto'])
def test_two_connection_resolution_uses_original_read_snapshot(monkeypatch,again):
    seed(monkeypatch);cancelled(monkeypatch)
    first=guards()[0];taken=threading.Event();committed=threading.Event();original=safety.guard_snapshot
    def snapshot(ids):
        rows=original(ids)  # BEGIN read snapshot closes before barrier/network.
        taken.set();assert committed.wait(10);return rows
    monkeypatch.setattr(safety,'guard_snapshot',snapshot)
    listing=load('fixtures/safety-cancelled-list.html')
    if again:listing=listing.replace('已取消','恢复举办后，本次10月23日活动再次取消。')
    token=captured(monkeypatch,listing)
    transport(monkeypatch,{ALIAS:{'status':302,'location':CANONICAL},CANONICAL:load('fixtures/safety-reinstatement-detail.html')})
    outcomes=[]
    def cancellation_writer():
        assert taken.wait(10)
        try:
            result=safety.finalize(token)
            assert result['observations_new']==1
        finally:committed.set()
    thread=threading.Thread(target=cancellation_writer);thread.start()
    try:outcomes.append(ee.resolve_guard_details(DESIGN['source'],[first['guard_id']],'concurrent-resolution'))
    except Exception as exc:outcomes.append(exc)
    thread.join(10);assert not thread.is_alive()
    if again:assert isinstance(outcomes[0],dict) and len(guards())==1 and guards()[0]['guard_id']!=first['guard_id']
    else:assert isinstance(outcomes[0],safety.Conflict) and guards()[0]['revision']==2


def test_authenticated_recovery_rejects_revision_payload_and_untrusted_actor(monkeypatch):
    seed(monkeypatch);token=safety.begin_capture(DESIGN['source']);c=client();path='/events/api/safety/captures/'+token.id+'/recover'
    body=dict(expected_revision=token.revision,mode='prove_not_started',decision_id='auth-recovery')
    unauth=TestClient(api.app)
    assert unauth.post(path,json={**body,'actor':'fixture-admin'},headers={'x-radar-request':'1'}).status_code==401
    assert c.post(path,json={**body,'expected_revision':999},headers={'x-radar-request':'1'}).status_code==409
    assert c.post(path,json=body,headers={'x-radar-request':'1'}).status_code==200
    assert c.post(path,json=body,headers={'x-radar-request':'1'}).status_code==200
    assert c.post(path,json={**body,'mode':'retain_unresolved'},headers={'x-radar-request':'1'}).status_code==503
    with core.db() as db:assert db.execute('SELECT actor FROM safety_recovery_decisions').fetchone()[0]=='maintainer:1'


@pytest.mark.parametrize('change',['guard','hold','source_cancel','raw','link','undated_cancel'])
def test_ai_commit_rereads_after_begin_immediate_and_discards_stale_result(monkeypatch,change):
    eid=seed(monkeypatch);cfg=core.config();cfg['analysis_enabled']=True
    (core.ROOT/'.private/settings.json').write_text(json.dumps(cfg))
    before=stored();dispatch=[]
    def fake_model(rows):
        dispatch.extend(rows)
        # Another connection acquires a writer lock while the model is running.
        if change=='guard':cancelled(monkeypatch)
        else:
            with core.db() as c:
                c.execute('BEGIN IMMEDIATE')
                if change=='hold':
                    details=json.loads(c.execute('SELECT details FROM events WHERE id=?',(eid,)).fetchone()[0]);details['review_hold']=True
                    c.execute('UPDATE events SET details=? WHERE id=?',(json.dumps(details),eid))
                elif change=='source_cancel':c.execute("UPDATE events SET status='cancelled' WHERE id=?",(eid,))
                elif change=='undated_cancel':c.execute("UPDATE events SET status='cancelled',start_at=NULL,end_at=NULL WHERE id=?",(eid,))
                elif change=='raw':c.execute("UPDATE raw_items SET content_hash='new-version',payload='{}'")
                elif change=='link':c.execute("UPDATE event_sources SET source_id='other-source'")
        with core.db() as c:dispatch.append(('expected_after',immutable()))
        return [dict(id=rows[0]['id'],is_shenzhen_offline=True,event_date='2026-12-01',date_evidence='2026年12月1日',location='深圳伪造地点',summary='AI stale result',topics=['AI与开源'])]
    monkeypatch.setattr(worker,'ai_batch',fake_model);monkeypatch.setattr(worker,'backfill_types',lambda *args:0);monkeypatch.setattr(worker,'geocode_pending',lambda *args:None)
    worker.analyze(1)
    assert dispatch and immutable()==dispatch[-1][1]
    # Existing independent holds/cancellation also skip paid dispatch entirely.
    monkeypatch.setattr(worker,'ai_batch',lambda rows:pytest.fail('unsafe AI dispatch'))
    if change in ('guard','hold','source_cancel','undated_cancel'):worker.analyze(1)


def test_backfill_types_ignores_guard_arriving_during_model_call(monkeypatch):
    eid=seed(monkeypatch);cfg=core.config();cfg['analysis_enabled']=True;(core.ROOT/'.private/settings.json').write_text(json.dumps(cfg))
    with core.db() as c:c.execute("UPDATE events SET ai_state='done'")
    def model(rows):cancelled(monkeypatch);return [dict(id=eid,event_type='ConferenceEvent')]
    monkeypatch.setattr(worker,'type_batch',model)
    assert worker.backfill_types(1)==0
    assert stored()['event_type_state']=='pending'


def test_serializer_cannot_bypass_missing_or_false_safety_projection(monkeypatch):
    eid=seed(monkeypatch)
    with core.db() as c:raw=dict(c.execute('SELECT * FROM events').fetchone())
    assert not Calendar.from_ical(make_calendar([raw])).walk('VEVENT')
    projected=core.events(period='record')[0];uid=Calendar.from_ical(make_calendar([projected])).walk('VEVENT')[0]['uid']
    cancelled(monkeypatch);guarded=core.events(period='record')[0]
    assert not Calendar.from_ical(make_calendar([guarded,{**projected,'status':'needs_review'}])).walk('VEVENT')
    resolve(monkeypatch)
    assert Calendar.from_ical(make_calendar(core.events())).walk('VEVENT')[0]['uid']==uid


@pytest.mark.parametrize('notice',[
    '尚未恢复举办，活动仍已取消。','引用：“活动已恢复举办”。','去年活动已恢复举办。',
    '另一个环节已恢复举办。','活动即将举行','本次2027年10月23日电路研讨会原取消安排现已恢复，按原时间举办。'])
def test_resolution_negative_language_never_resolves_guard(monkeypatch,notice):
    seed(monkeypatch);cancelled(monkeypatch);original=guards()
    body=load('fixtures/safety-reinstatement-detail.html')
    import re
    body=re.sub(r'(<p class="current-status">).*?(</p>)',lambda m:m[1]+notice+m[2],body)
    transport(monkeypatch,{ALIAS:{'status':302,'location':CANONICAL},CANONICAL:body})
    with pytest.raises((safety.SafetyError,collectors.SourceError)):ee.resolve_guard_details(DESIGN['source'],[original[0]['guard_id']],'negative-resolution')
    assert guards()==original


def pending_admission(monkeypatch):
    transport(monkeypatch,{ee.LIST_URL:load('fixtures/redirect-list.html'),ALIAS:{'status':302,'location':CANONICAL},CANONICAL:load('fixtures/redirect-live-detail.html')})
    report=coverage.collect_report(DESIGN['source'])
    assert report['coverage']['admitted']==1
    return report['items'][0]


@pytest.mark.parametrize('order',['cancellation_first','anchor_first'])
def test_null_anchor_two_writer_orders_never_expose_eligible_target(monkeypatch,order):
    item=pending_admission(monkeypatch);token=captured(monkeypatch)
    done=threading.Event();errors=[]
    def writer():
        try:
            if order=='cancellation_first':safety.finalize(token)
            else:core.ingest(DESIGN['source'],item)
        except Exception as exc:errors.append(exc)
        finally:done.set()
    thread=threading.Thread(target=writer);thread.start();assert done.wait(10);thread.join(10);assert not errors
    if order=='cancellation_first':
        assert receipt()['unlinked_observations']==1 and not guards()
        core.ingest(DESIGN['source'],item)
    else:
        assert client().get('/events/api/events').status_code==503
        safety.finalize(token)
    assert len(guards())==1 and len(core.events())==0 and counts()['events']==1
    with core.db() as c:
        assert c.execute('SELECT COUNT(*) FROM eefocus_target_anchors').fetchone()[0]==2
        assert c.execute('PRAGMA foreign_key_check').fetchall()==[]


@pytest.mark.parametrize('failure',['insert_guard','capacity','unknown_occurrence'])
def test_late_anchor_failure_rolls_back_entire_positive_ingest(monkeypatch,failure):
    listing=load('fixtures/safety-cancelled-list.html')
    if failure=='unknown_occurrence':listing=listing.replace('2026年10月23日','日期待定')
    cancelled(monkeypatch,listing);assert receipt()['unlinked_observations']==1
    item=pending_admission(monkeypatch);before=immutable()
    if failure=='capacity':
        cfg=core.config();cfg['safety_limits']={'anchor_bytes':1};(core.ROOT/'.private/settings.json').write_text(json.dumps(cfg))
        expected=safety.Capacity
    elif failure=='insert_guard':
        actual=core.sqlite3.connect
        class Failing(sqlite3.Connection):
            def execute(self,sql,*args,**kwargs):
                if sql.startswith('INSERT INTO event_safety_guards'):raise sqlite3.OperationalError('failure after exact anchor insertion')
                return super().execute(sql,*args,**kwargs)
        monkeypatch.setattr(core.sqlite3,'connect',lambda *a,**kw:actual(*a,**kw,factory=Failing));expected=sqlite3.OperationalError
    else:expected=safety.SafetyError
    with pytest.raises(expected):core.ingest(DESIGN['source'],item)
    assert immutable()==before and not guards() and counts()['events']==0
    with core.db() as c:assert c.execute('SELECT COUNT(*) FROM eefocus_target_anchors').fetchone()[0]==0


def test_new_exact_target_reconciliation_preserves_already_resolved_disposition(monkeypatch):
    eid=seed(monkeypatch);cancelled(monkeypatch);resolve(monkeypatch)
    with core.db() as c:
        observation=dict(c.execute('SELECT * FROM safety_observations').fetchone())
        original=[tuple(r) for r in c.execute('SELECT * FROM event_safety_guards')]
        first=c.execute('SELECT * FROM eefocus_identity_bindings WHERE alias_url=? LIMIT 1',(ALIAS,)).fetchone()
        proof=json.loads(first['evidence'])
    # A previously verified historical NULL binding is anchored by the exact
    # success seam; URL equality alone is not used to invent applicability.
    second=ee.ORIGIN+'/live/980202.html';proof.update(canonical_url=second,trace=[dict(url=ALIAS,status=302,location=second),dict(url=second,status=200)])
    ids=ee.record_bindings(DESIGN['source'],ALIAS,proof)
    base=json.loads(immutable()['raw_items'][0][6]);base['url']=second;base['_identity_binding_ids']=ids
    core.ingest(DESIGN['source'],base)
    assert len(guards())==1 and guards()[0]['event_id']!=eid
    with core.db() as c:
        assert [tuple(r) for r in c.execute("SELECT * FROM event_safety_guards WHERE state='resolved'")]==original
        assert c.execute('SELECT targeting_state FROM safety_observations').fetchone()[0]=='linked_ambiguous'
        assert c.execute('SELECT COUNT(*) FROM safety_observation_targets').fetchone()[0]==2
        target_count=c.total_changes
    safety.replay_capture(observation['capture_id'])
    assert len(guards())==1


def test_guard_projection_and_source_links_share_one_read_snapshot(monkeypatch):
    eid=seed(monkeypatch);token=captured(monkeypatch)
    # Finalize a recognized open result first to release the availability fence;
    # cancellation B is a retained capture without a source-wide fence only after
    # its later atomic finalization. Use actual observation transaction at hook.
    safety.finalize(token)
    resolve(monkeypatch)
    original=core._source_links;changed=False
    def links(c,ids):
        nonlocal changed
        if not changed:
            changed=True
            cancelled(monkeypatch)
        return original(c,ids)
    monkeypatch.setattr(core,'_source_links',links)
    first=core.events(period='record');second=core.events(period='record')
    assert first[0]['planning_eligible'] is True and first[0]['safety']['guard_count']==0
    assert second[0]['planning_eligible'] is False and second.safety_epoch>first.safety_epoch


def test_query_parity_crosses_hydration_and_calendar_pagination_boundaries(monkeypatch):
    eid=seed(monkeypatch)
    with core.db() as c:
        original=dict(c.execute('SELECT * FROM events WHERE id=?',(eid,)).fetchone())
        c.execute("INSERT INTO source_health(id,name,url) VALUES('other','other','https://example.test/')")
        for index in range(501):
            row={**original,'id':f'ordinary-{index:04}','url':f'https://example.test/event/{index}',
                 'title':f'Ordinary {index}','event_type':'ConferenceEvent','event_type_state':'source','priority':'high'}
            keys=list(row);c.execute('INSERT INTO events('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',tuple(row.values()))
            c.execute('INSERT INTO preferences(event_id,favorite) VALUES(?,1)',(row['id'],))
            c.execute('INSERT INTO event_sources VALUES(?,?,?,?,?)',(row['id'],'other',row['url'],None,core.stamp()))
    c=client();params=dict(period='calendar',start='2026-10-01',end='2026-11-01',limit=500,favorites=True)
    first=c.get('/events/api/events',params=params).json();assert first['total']==502 and first['has_more']
    transport(monkeypatch,{ee.LIST_URL:load('fixtures/safety-cancelled-list.html'),ALIAS:collectors.SourceError('ReadTimeout')})
    result=worker.collect_source(DESIGN['source']);assert result['guards_created']==1
    stale=c.get('/events/api/events',params={**params,'offset':500,'safety_epoch':first['safety_epoch']})
    assert stale.status_code==409 and stale.json()['code']=='safety_snapshot_changed'
    fresh=c.get('/events/api/events',params=params).json();assert fresh['total']==501 and len(fresh['items'])==500
    for query in ('','&favorites=true','&recommended=true','&attendance=online','&hide_long=true','&type=ConferenceEvent','&feedback=none'):
        response=c.get('/events/api/events?period=upcoming'+query).json()
        assert eid not in {row['id'] for row in response['items']}
        assert eid not in {row['id'] for row in response.get('excluded_long',{}).get('items',[])}
    assert len(core.events(period='saved',favorites=True))==502
    assert c.get('/events/api/stats').json()['upcoming']==501
    assert c.get('/events/api/calendar-summary').json()['unscheduled']==1


def test_retention_and_alias_merge_preserve_active_and_resolved_audit(monkeypatch):
    eid=seed(monkeypatch);cancelled(monkeypatch);resolve(monkeypatch);cancelled(monkeypatch)
    with core.db() as c:
        c.execute('DELETE FROM preferences');c.execute("UPDATE events SET start_at='2025-01-01',end_at='2025-01-02'")
        c.execute("UPDATE raw_items SET collected_at='2025-01-01'")
        c.execute("UPDATE detail_cache SET checked_at='2025-01-01'")
        for index in range(410):c.execute("INSERT INTO runs(kind,status) VALUES('old','ok')")
    worker.retention()
    assert counts()==dict(raw_items=1,events=1,event_sources=1)
    with core.db() as c:
        assert c.execute('SELECT COUNT(*) FROM detail_cache').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==400
        assert c.execute('SELECT COUNT(*) FROM safety_resolutions').fetchone()[0]==1
        observation=c.execute('SELECT capture_id FROM safety_observations ORDER BY rowid LIMIT 1').fetchone()[0]
    safety.replay_capture(observation);assert len(guards())==1
    # A reviewed merge touching a safety-linked ID defers without changing IDs.
    with core.db() as c:
        row=dict(c.execute('SELECT * FROM events').fetchone());row.update(id='other-canonical',url='https://example.test/old')
        keys=list(row);c.execute('INSERT INTO events('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',tuple(row.values()))
        c.execute('INSERT INTO event_sources VALUES(?,?,?,?,?)',('other-canonical','other-source',row['url'],None,core.stamp()))
    (core.ROOT/'dedupe_aliases.json').write_text(json.dumps([dict(id='reviewed',date='2025-01-01',urls=[CANONICAL,'https://example.test/old'])]))
    assert core.reconcile_aliases()==[] and counts()['events']==2 and len(guards())==1
    with core.db() as c:
        assert c.execute("SELECT code FROM safety_diagnostics WHERE id='safety_merge_deferred'").fetchone()[0]=='safety_merge_deferred'


@pytest.mark.parametrize('change',['hold','source'])
def test_fresh_resolution_revalidates_canonical_and_source_authority(monkeypatch,change):
    eid=seed(monkeypatch);cancelled(monkeypatch);snapshot=guards()
    transport(monkeypatch,{ALIAS:{'status':302,'location':CANONICAL},CANONICAL:load('fixtures/safety-reinstatement-detail.html')})
    actual=ee.fetch
    def after_network(*args,**kwargs):
        response=actual(*args,**kwargs)
        with core.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if change=='hold':
                detail=json.loads(c.execute('SELECT details FROM events WHERE id=?',(eid,)).fetchone()[0]);detail['review_hold']=True
                c.execute('UPDATE events SET details=? WHERE id=?',(json.dumps(detail),eid))
            else:c.execute('UPDATE event_sources SET url=? WHERE event_id=?',(ee.ORIGIN+'/live/989999.html',eid))
        return response
    monkeypatch.setattr(ee,'fetch',after_network)
    with pytest.raises(safety.Conflict):ee.resolve_guard_details(DESIGN['source'],[snapshot[0]['guard_id']],'authority-race')
    assert guards()==snapshot
    with core.db() as c:assert c.execute('SELECT COUNT(*) FROM safety_resolutions').fetchone()[0]==0


def test_resolution_operation_retry_returns_original_without_new_network(monkeypatch):
    seed(monkeypatch);cancelled(monkeypatch);ids=[r['guard_id'] for r in guards()]
    calls,_=transport(monkeypatch,{ALIAS:{'status':302,'location':CANONICAL},CANONICAL:load('fixtures/safety-reinstatement-detail.html')})
    result=ee.resolve_guard_details(DESIGN['source'],ids,'exact-operation');attempts=len(calls)
    assert ee.resolve_guard_details(DESIGN['source'],ids,'exact-operation')==result and len(calls)==attempts
    with pytest.raises(safety.Integrity):ee.resolve_guard_details(DESIGN['source'],['different-guard'],'exact-operation')
    assert len(calls)==attempts


def test_scheduled_manual_hold_enters_review_projection(monkeypatch):
    eid=seed(monkeypatch,held=True)
    row=core.events(period='review')[0]
    assert row['id']==eid and row['stored_status']=='scheduled' and row['effective_status']=='needs_review' and row['planning_eligible'] is False


@pytest.mark.parametrize('overrun',['cards','metadata','edges'])
def test_declared_bound_overrun_keeps_complete_capture_fenced(monkeypatch,overrun):
    seed(monkeypatch)
    listing=load('fixtures/safety-cancelled-list.html')
    if overrun=='cards':
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(listing,'html.parser');node=str(soup.select_one('li'));listing=str(soup).replace(node,node*257)
    token=captured(monkeypatch,listing)
    cfg=core.config();cfg['safety_limits']={'metadata_bytes':8} if overrun=='metadata' else {'target_edges':0} if overrun=='edges' else {}
    (core.ROOT/'.private/settings.json').write_text(json.dumps(cfg))
    with pytest.raises(safety.Capacity):safety.finalize(token)
    with core.db() as c:
        assert safety.fenced(c) and c.execute('SELECT COUNT(*) FROM safety_observations').fetchone()[0]==0
        assert c.execute('SELECT response_digest FROM safety_capture_runs WHERE capture_id=?',(token.id,)).fetchone()[0]
    assert client().get('/events/api/events').status_code==503 and not guards()


def test_capacity_reservation_rejection_happens_before_fence_or_network(monkeypatch):
    eid=seed(monkeypatch);before=immutable();cfg=core.config();cfg['safety_limits']={'account_bytes':safety.CAPTURE_RESERVE+safety.LIMITS['headroom_bytes']}
    (core.ROOT/'.private/settings.json').write_text(json.dumps(cfg))
    calls,_=transport(monkeypatch,{})
    result=worker.collect_source(DESIGN['source'])
    assert result['status']=='error' and calls==[] and immutable()==before
    with core.db() as c:
        assert not safety.fenced(c) and c.execute('SELECT COUNT(*) FROM safety_capacity').fetchone()[0]==0
        assert c.execute("SELECT code FROM safety_diagnostics WHERE id='safety_capacity_paused'").fetchone()[0]=='safety_capacity_paused'
    planning(eid,True)


def test_simultaneous_acquisition_reservations_cannot_double_spend_headroom(monkeypatch):
    barrier=threading.Barrier(2);out=[]
    def reserve(source):
        barrier.wait(timeout=10)
        try:out.append(safety.begin_capture(source))
        except safety.SafetyError as exc:out.append(exc)
    threads=[threading.Thread(target=reserve,args=({**DESIGN['source'],'id':f'source-{i}'},)) for i in range(2)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(10);assert not thread.is_alive()
    assert sum(isinstance(value,safety.Capture) for value in out)==1
    with core.db() as c:
        assert c.execute('SELECT COUNT(*) FROM safety_capacity').fetchone()[0]==1
        assert c.execute('SELECT SUM(bytes) FROM safety_capacity').fetchone()[0]==safety.CAPTURE_RESERVE


def legacy_database(monkeypatch,path):
    seed(monkeypatch)
    legacy=sqlite3.connect(path);legacy.row_factory=sqlite3.Row;legacy.execute('PRAGMA foreign_keys=ON')
    with core.db() as c:
        tables=c.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        for table in tables:
            name=table['name']
            if name.startswith('safety_') or name in ('event_safety_guards','eefocus_target_anchors'):continue
            legacy.execute(table['sql'])
            rows=c.execute('SELECT * FROM '+name).fetchall()
            for row in rows:
                values=list(row)
                if name=='eefocus_identity_bindings':
                    evidence=json.loads(values[4]);evidence.pop('main_body_digest',None);values[4]=json.dumps(evidence)
                legacy.execute('INSERT INTO '+name+' VALUES('+','.join('?' for _ in row)+')',values)
    legacy.commit()
    return legacy


def test_additive_migration_preserves_legacy_rows_and_does_not_guess_null_or_conflicting_anchors(monkeypatch,tmp_path):
    c=legacy_database(monkeypatch,tmp_path/'legacy.sqlite')
    original=c.execute('SELECT * FROM eefocus_identity_bindings LIMIT 1').fetchone()
    c.execute('INSERT INTO eefocus_identity_bindings VALUES(?,?,?,?,?,?,NULL)',('null-binding',original['source_id'],original['alias_url'],original['canonical_url'],original['evidence'],core.stamp()))
    proof=json.loads(original['evidence']);proof['occurrence_dates']=['2027-10-23']
    c.execute('INSERT INTO eefocus_identity_bindings VALUES(?,?,?,?,?,?,?)',('inconsistent-binding',original['source_id'],original['alias_url'],original['canonical_url'],json.dumps(proof),core.stamp(),original['event_id']))
    c.commit()
    baseline={table:[tuple(r) for r in c.execute('SELECT * FROM '+table)] for table in ('events','raw_items','event_sources','preferences','eefocus_identity_bindings')}
    safety.migrate(c);safety.migrate(c)
    assert {table:[tuple(r) for r in c.execute('SELECT * FROM '+table)] for table in baseline}==baseline
    assert {r[0] for r in c.execute('SELECT binding_id FROM eefocus_target_anchors')}=={r[0] for r in baseline['eefocus_identity_bindings'] if r[0] not in ('null-binding','inconsistent-binding')}
    assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
    c.execute('UPDATE safety_meta SET schema_version=999');c.commit()
    with pytest.raises(safety.SafetyError):safety.migrate(c)
    c.close()


def test_interrupted_migration_rolls_back_all_new_schema(monkeypatch,tmp_path):
    path=tmp_path/'legacy-interrupted.sqlite';legacy_database(monkeypatch,path).close()
    class Failing(sqlite3.Connection):
        def execute(self,sql,*args,**kwargs):
            if sql.startswith('CREATE TABLE safety_observations'):raise sqlite3.OperationalError('migration interrupted')
            return super().execute(sql,*args,**kwargs)
    c=sqlite3.connect(path,factory=Failing);c.row_factory=sqlite3.Row
    with pytest.raises(sqlite3.OperationalError):safety.migrate(c)
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'safety_%'").fetchone()[0]==0
    c.close();c=sqlite3.connect(path);c.row_factory=sqlite3.Row;safety.migrate(c)
    assert safety.assert_schema(c)==0;c.close()


def test_unknown_future_or_missing_schema_fails_closed_without_content_mutation(monkeypatch):
    seed(monkeypatch);before=immutable()
    with core.db() as c:c.execute('UPDATE safety_meta SET schema_version=999')
    with pytest.raises(safety.SafetyError):core.init()
    assert immutable()==before and client().get('/events/api/events').status_code==503
    with core.db() as c:c.execute('UPDATE safety_meta SET schema_version=1');c.execute('ALTER TABLE event_safety_guards RENAME TO broken_guard_schema')
    assert client().get('/events/api/events').status_code==503


def test_immutable_evidence_target_and_receipt_cannot_be_deleted_or_retargeted(monkeypatch):
    eid=seed(monkeypatch);cancelled(monkeypatch)
    attempts=["DELETE FROM safety_observations","DELETE FROM safety_evidence_blobs","DELETE FROM safety_guard_members",
              "DELETE FROM eefocus_target_anchors","DELETE FROM safety_capture_runs",
              "UPDATE eefocus_identity_bindings SET canonical_url='https://www.eefocus.com/live/999.html'",
              "UPDATE safety_observation_targets SET event_id='other'","UPDATE safety_capture_runs SET capture_state='reserved' WHERE capture_state='safety_finalized'"]
    for sql in attempts:
        with pytest.raises(sqlite3.IntegrityError):
            with core.db() as c:c.execute(sql)
    assert len(guards())==1 and counts()['events']==1


def test_measured_maximum_inventory_and_target_ledger_fits_declared_reservation(monkeypatch):
    """256 cards × eight direct historical targets: full 2,048-edge workload."""
    from bs4 import BeautifulSoup
    original=load('fixtures/safety-cancelled-list.html');soup=BeautifulSoup(original,'html.parser');node=soup.select_one('li');cards=[]
    # This is trusted historical DB fixture setup. Actual observation parsing,
    # targeting, guard/membership writes and receipt use the production service.
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        template=dict(title='合成线上电路研讨会',url=CANONICAL,start_at='2026-10-23T14:00:00+08:00',end_at='2026-10-23T15:00:00+08:00',location='线上',summary='maximum-bound historical target',details={'attendance':'online'})
        normalized=core.normalize_event(template);payload=json.dumps(normalized)
        for index in range(256):
            card=BeautifulSoup(str(node),'html.parser').find('li');alias=ee.ORIGIN+f'/event/{900000+index}.html';card['data-post-id']=str(index)+'x'*2500;card.select_one('a')['href']=alias;cards.append(str(card))
            for edition in range(8):
                canonical=ee.ORIGIN+f'/live/{900000+index*8+edition}.html';eid=f'bound-{index}-{edition}'
                rid=c.execute('INSERT INTO raw_items(source_id,url,title,body,content_hash,payload,collected_at) VALUES(?,?,?,?,?,?,?)',(DESIGN['source']['id'],canonical,template['title'],'historical source body','hash',payload,core.stamp())).lastrowid
                c.execute("INSERT INTO events(id,title,start_at,end_at,url,status,details,last_seen,topics) VALUES(?,?,?,?,?,'scheduled',?,?,?)",(eid,template['title'],template['start_at'],template['end_at'],canonical,json.dumps(template['details']),core.stamp(),'[]'))
                c.execute('INSERT INTO event_sources VALUES(?,?,?,?,?)',(eid,DESIGN['source']['id'],canonical,rid,core.stamp()))
                binding=f'bound-binding-{index}-{edition}';proof=json.dumps({'canonical_url':canonical,'occurrence_dates':['2026-10-23']})
                c.execute('INSERT INTO eefocus_identity_bindings VALUES(?,?,?,?,?,?,?)',(binding,DESIGN['source']['id'],alias,canonical,proof,core.stamp(),eid))
                c.execute('INSERT INTO eefocus_target_anchors VALUES(?,?,?,?,?,?)',(binding,eid,rid,'["2026-10-23"]',proof,core.stamp()))
    listing='<main class="special-list"><ul class="section-list-item-ul">'+''.join(cards)+'</ul></main>'
    assert len(listing.encode())<=safety.LIMITS['inventory_bytes']
    before=sum(p.stat().st_size for p in (core.ROOT/'data').glob('*') if p.is_file())
    token=captured(monkeypatch,listing);result=safety.finalize(token)
    after=sum(p.stat().st_size for p in (core.ROOT/'data').glob('*') if p.is_file())
    assert result['observations_new']==256 and result['guards_created']==2048 and result['ambiguous_targets']==256
    with core.db() as c:
        assert c.execute('SELECT COUNT(*) FROM safety_guard_members').fetchone()[0]==2048
        assert c.execute('SELECT COUNT(*) FROM safety_target_evidence').fetchone()[0]==2048
        assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
    measurement=dict(inventory_bytes=len(listing.encode()),cards=256,edges=2048,before_bytes=before,after_bytes=after,
                     committed_growth_bytes=after-before,reservation_bytes=safety.CAPTURE_RESERVE,headroom_bytes=safety.LIMITS['headroom_bytes'])
    out=PACK.parents[2]/'artifacts/safety-capacity';out.mkdir(parents=True,exist_ok=True);(out/'measurement.json').write_text(json.dumps(measurement,indent=2))
    assert after-before<safety.CAPTURE_RESERVE


@pytest.mark.parametrize('fault',['full','readonly','locked'])
def test_actual_sqlite_storage_failures_preserve_durable_last_state(monkeypatch,fault):
    seed(monkeypatch);token=safety.claim(safety.begin_capture(DESIGN['source']))
    actual=core.sqlite3.connect;locker=None
    if fault=='readonly':
        def connect(path,**kwargs):return actual('file:'+str(path)+'?mode=ro',uri=True,**kwargs)
    elif fault=='full':
        def connect(path,**kwargs):
            c=actual(path,**kwargs);pages=c.execute('PRAGMA page_count').fetchone()[0];c.execute('PRAGMA max_page_count='+str(pages));return c
    else:
        locker=actual(core.ROOT/'data/events.sqlite3');locker.execute('BEGIN IMMEDIATE')
        class FastBusy(sqlite3.Connection):
            def execute(self,sql,*args,**kwargs):
                if sql.startswith('PRAGMA busy_timeout='):sql='PRAGMA busy_timeout=50'
                return super().execute(sql,*args,**kwargs)
        def connect(path,**kwargs):return actual(path,**kwargs,factory=FastBusy)
    monkeypatch.setattr(core.sqlite3,'connect',connect)
    body=load('fixtures/safety-cancelled-list.html')+'<!--'+'x'*900_000+'-->'
    with pytest.raises(sqlite3.OperationalError):safety.retain(token,body,ee.LIST_URL,[dict(url=ee.LIST_URL,status=200)])
    monkeypatch.setattr(core.sqlite3,'connect',actual)
    if locker:locker.rollback();locker.close()
    with core.db() as c:
        run=c.execute('SELECT * FROM safety_capture_runs WHERE capture_id=?',(token.id,)).fetchone()
        assert run['capture_state']=='acquiring' and run['response_digest'] is None and run['receipt'] is None
    safety.mark_unknown(token,'accepted_response_not_retained')
    assert client().get('/events/api/events').status_code==503
    with pytest.raises(safety.Conflict):safety.retain(safety.Capture(token.id,token.owner,token.revision+1),body,ee.LIST_URL,[dict(url=ee.LIST_URL,status=200)])


def test_precise_live_transport_failure_receipt_releases_only_its_fence(monkeypatch):
    eid=seed(monkeypatch)
    import requests
    calls,_=transport(monkeypatch,{ee.LIST_URL:requests.exceptions.ConnectTimeout('no accepted response')})
    result=worker.collect_source(DESIGN['source'])
    assert result['status']=='error' and result['count']==0
    proof=receipt();assert proof['outcome']=='known_acquisition_failure' and proof['requests_attempted']==len(calls)
    assert proof['transport_message'] and not guards();planning(eid,True)
