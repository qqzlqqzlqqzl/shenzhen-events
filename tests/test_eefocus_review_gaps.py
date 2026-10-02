"""Independent PR #91 counterexamples and exact evidence-role controls.

The delayed ingest models an alternate writer, not a bypass of the CLI flock.
Publisher transport is stubbed below Session; parser/report/worker/DB/API run.
"""
import json
import threading

import pytest

from radar import collectors, core, coverage, eefocus as ee, safety
from test_eefocus import DESIGN, card, counts, detail_html, isolated, load, run, stored, transport
from test_eefocus_safety import ALIAS, CANONICAL, captured, client, guards, immutable

MEETING='直播时间：2026年10月23日 14:00–15:00 北京时间'


@pytest.mark.parametrize('raw,publisher,role',[
    ('推广期：2026年10月1日–2026年10月23日',False,'promotion_window'),
    ('报名时间：2026年10月1日–2026年10月23日',False,'registration_window'),
    ('发布时间：2026年10月1日',False,'publication_time'),
    ('举办时间：2026年10月1日–2026年10月23日',False,'unknown'),
    ('直播时间：10月23日',False,'unknown'),
    ('2026/10/01–2026/10/23',True,'discovery_window'),
    ('日期待定',False,'unknown'),
])
@pytest.mark.parametrize('candidate_date',['2026-10-23','2026-10-30'])
def test_unknown_cancellation_date_role_cannot_prove_late_non_applicability(monkeypatch,raw,publisher,role,candidate_date):
    listing=load('fixtures/safety-cancelled-list.html').replace(MEETING,raw)
    if publisher:listing=listing.replace('<main class="special-list">','<div class="special-list">').replace('</main>','</div>')
    first,_,_=run(monkeypatch,{ee.LIST_URL:listing,ALIAS:collectors.SourceError('detail unavailable')})
    assert first['count']==first['changed']==0 and counts()['events']==0
    with core.db() as c:
        observation=dict(c.execute('SELECT * FROM safety_observations').fetchone())
        metadata=json.loads(observation['metadata'])
        assert observation['occurrence']=='[]' and observation['targeting_state']=='unlinked'
        assert metadata['time_evidence']['role']==role and metadata['time_evidence']['texts']==[raw]
        c.execute("UPDATE detail_cache SET next_attempt='2025-01-01'")
    if candidate_date=='2026-10-23':
        positive=load('fixtures/redirect-list.html').replace('举办时间：2026年10月23日 14:00–15:00','推广期：2026年10月1日–2026年10月23日')
        canonical=CANONICAL;body=load('fixtures/redirect-live-detail.html')
    else:
        positive=load('fixtures/safety-historical-second-list.html')
        canonical=ee.ORIGIN+'/live/980999.html';body=load('fixtures/safety-historical-second-detail.html')
    second,metrics,_=run(monkeypatch,{ee.LIST_URL:positive,ALIAS:{'status':302,'location':canonical},canonical:body})
    assert second['status']=='error' and second['count']==second['changed']==0
    assert metrics['reported_admitted']==1 and metrics['admitted']==0
    assert counts()==dict(raw_items=0,events=0,event_sources=0)
    assert client().get('/events/api/events').json()['total']==0
    with core.db() as c:
        assert c.execute('SELECT COUNT(*) FROM safety_target_adjudications').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM eefocus_target_anchors').fetchone()[0]==0
        assert c.execute('SELECT occurrence FROM safety_observations').fetchone()[0]=='[]'


@pytest.mark.parametrize('date',['2026-10-23','2026-10-30'])
def test_explicit_cancellation_occurrence_has_positive_same_and_distinct_controls(monkeypatch,date):
    run(monkeypatch,{ee.LIST_URL:load('fixtures/safety-cancelled-list.html'),ALIAS:collectors.SourceError('unavailable')})
    with core.db() as c:c.execute("UPDATE detail_cache SET next_attempt='2025-01-01'")
    if date=='2026-10-23':positive=load('fixtures/redirect-list.html');canonical=CANONICAL;body=load('fixtures/redirect-live-detail.html')
    else:positive=load('fixtures/safety-historical-second-list.html');canonical=ee.ORIGIN+'/live/980999.html';body=load('fixtures/safety-historical-second-detail.html')
    result,_,_=run(monkeypatch,{ee.LIST_URL:positive,ALIAS:{'status':302,'location':canonical},canonical:body})
    assert result['count']==1 and counts()==dict(raw_items=1,events=1,event_sources=1)
    with core.db() as c:
        assert set(r[0] for r in c.execute('SELECT result FROM safety_target_adjudications'))==({'applicable'} if date=='2026-10-23' else {'not_applicable'})
    point=client().get('/events/api/event/'+stored()['id']).json()
    assert point['planning_eligible'] is (date=='2026-10-30')
    assert point['safety']['guard_count']==(1 if date=='2026-10-23' else 0)
    assert client().get('/events/api/event/'+stored()['id']+'.ics').status_code==(409 if date=='2026-10-23' else 200)


def test_legacy_bare_promotion_dates_remain_unknown_without_rewriting_observation(monkeypatch):
    raw='推广期：2026年10月1日–2026年10月23日';listing=load('fixtures/safety-cancelled-list.html').replace(MEETING,raw)
    actual=ee.cancellation_observations
    def legacy_shape(*args):
        rows=actual(*args)
        for row in rows:row.pop('time_evidence');row['occurrence']=sorted(ee.calendar_dates(raw))
        return rows
    with monkeypatch.context() as context:
        context.setattr(ee,'cancellation_observations',legacy_shape)
        run(context,{ee.LIST_URL:listing,ALIAS:collectors.SourceError('unavailable')})
    with core.db() as c:
        prior=tuple(c.execute('SELECT * FROM safety_observations').fetchone())
        c.execute("UPDATE detail_cache SET next_attempt='2025-01-01'")
    result,_,_=run(monkeypatch,{ee.LIST_URL:load('fixtures/redirect-list.html'),ALIAS:{'status':302,'location':CANONICAL},CANONICAL:load('fixtures/redirect-live-detail.html')})
    assert result['count']==0 and not core.events() and counts()['events']==0
    with core.db() as c:assert tuple(c.execute('SELECT * FROM safety_observations').fetchone())==prior


@pytest.mark.parametrize('guarded',[False,True])
def test_delayed_verified_admission_cannot_undo_reschedule_under_alternate_writer(monkeypatch,guarded):
    alias,new_alias,canonical=(ee.ORIGIN+p for p in ('/event/990002.html','/event/990003.html','/live/990102.html'))
    base=dict(title='合成同名年度研讨会',url=alias,location='深圳',start_at='2026-10-23T14:00:00+08:00',end_at='2026-10-23T15:00:00+08:00')
    original=card(base)
    run(monkeypatch,{ee.LIST_URL:original,alias:{'status':302,'location':canonical},canonical:detail_html(base)})
    transport(monkeypatch,{ee.LIST_URL:original})
    delayed=coverage.collect_report({**DESIGN['source'],'detail_budget':0})['items'][0]
    if guarded:safety.finalize(captured(monkeypatch,card({**base,'details':{'source_status':'已取消'}})))
    listing=card({**base,'url':new_alias}).replace('2026年10月23日','2027年10月23日')
    body=detail_html(base).replace('2026年10月23日','2027年10月23日').replace('</article>','<p>原定2026年10月23日，改期至2027年10月23日。</p></article>')
    result,_,_=run(monkeypatch,{ee.LIST_URL:listing,new_alias:{'status':302,'location':canonical},canonical:body})
    assert result['count']==1 and stored()['start_at'].startswith('2027')
    before=immutable();prior_guards=guards();checks=[];outcome=[];actual=ee.revalidate_admission_history
    def inspect_writer(connection,*args):
        checks.append((connection.in_transaction,connection.execute('SELECT start_at FROM events').fetchone()[0]))
        return actual(connection,*args)
    monkeypatch.setattr(ee,'revalidate_admission_history',inspect_writer)
    def writer():
        try:outcome.append(core.ingest(DESIGN['source'],delayed))
        except Exception as exc:outcome.append(exc)
    thread=threading.Thread(target=writer);thread.start();thread.join(10)
    assert not thread.is_alive() and len(outcome)==1
    assert isinstance(outcome[0],collectors.SourceError) and 'historical_occurrence_conflict' in str(outcome[0])
    assert checks==[(True,stored()['start_at'])] and checks[0][1].startswith('2027')
    assert immutable()==before and guards()==prior_guards
    assert bool(guards()) is guarded
