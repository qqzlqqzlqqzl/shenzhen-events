"""Whole-field occurrence authority through real capture/worker/SQLite/API.

Publisher transport is synthetic. These tests make no live source request.
"""
import json

import pytest

from radar import collectors, core, eefocus as ee
from test_eefocus import isolated, load, run, counts, stored
from test_eefocus_safety import ALIAS, CANONICAL, client

MEETING='直播时间：2026年10月23日 14:00–15:00 北京时间'
RESIDUAL=[
    '活动时间：2026年10月1日–23日',
    '活动时间：2026年10月1日至23日',
    '活动时间：2026年10月1日或23日',
    '活动时间：2026年10月1日起，结束时间待通知',
]


def unlinked(monkeypatch,raw):
    listing=load('fixtures/safety-cancelled-list.html').replace(MEETING,raw)
    result,_,_=run(monkeypatch,{ee.LIST_URL:listing,ALIAS:collectors.SourceError('detail unavailable')})
    assert result['count']==0 and counts()['events']==0
    with core.db() as c:
        row=dict(c.execute('SELECT * FROM safety_observations').fetchone())
        assert row['targeting_state']=='unlinked'
        c.execute("UPDATE detail_cache SET next_attempt='2025-01-01'")
    return row


def positive(monkeypatch):
    return run(monkeypatch,{ee.LIST_URL:load('fixtures/redirect-list.html'),ALIAS:{'status':302,'location':CANONICAL},CANONICAL:load('fixtures/redirect-live-detail.html')})


@pytest.mark.parametrize('raw',RESIDUAL+[
    '活动时间：2026年10月1日、23日',
    '活动时间：2026年10月1日/23日',
    '活动时间：2026年10月1日 14:00–15:00，另场23日',
    '活动时间：2026年10月1日 14:00–15:00 未确认',
    '活动时间：2026年10月1日 25:00–26:00',
    '活动时间：2026年10月1日 23:00–01:00',
])
def test_unconsumed_or_invalid_occurrence_field_rolls_back_late_admission(monkeypatch,raw):
    prior=unlinked(monkeypatch,raw)
    proof=json.loads(prior['metadata'])['time_evidence']
    assert proof['role']=='unknown' and proof['texts']==[raw] and proof['occurrence']==[]
    assert prior['occurrence']=='[]'
    result,metrics,_=positive(monkeypatch)
    assert result['status']=='error' and result['count']==result['changed']==0
    assert metrics['reported_admitted']==1 and metrics['admitted']==0
    assert counts()==dict(events=0,raw_items=0,event_sources=0)
    assert client().get('/events/api/events').json()['total']==0
    with core.db() as c:
        assert c.execute('SELECT COUNT(*) FROM safety_target_adjudications').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM eefocus_target_anchors').fetchone()[0]==0
        assert dict(c.execute('SELECT * FROM safety_observations').fetchone())==prior


@pytest.mark.parametrize('day',['1','23'])
@pytest.mark.parametrize('tail',['',' 14:00–15:00 北京时间','14:00-15:00',' 14:00 北京时间'])
def test_complete_single_date_same_and_different_controls_keep_real_ics_gate(monkeypatch,day,tail):
    prior=unlinked(monkeypatch,f'活动时间：2026年10月{day}日{tail}')
    proof=json.loads(prior['metadata'])['time_evidence']
    assert proof['role']=='actual_occurrence' and proof['occurrence']==[f'2026-10-{int(day):02d}']
    result,_,_=positive(monkeypatch)
    assert result['count']==1 and counts()==dict(events=1,raw_items=1,event_sources=1)
    point=client().get('/events/api/event/'+stored()['id']).json()
    different=day=='1'
    assert point['planning_eligible'] is different and point['safety']['guard_count']==(0 if different else 1)
    assert client().get('/events/api/event/'+stored()['id']+'.ics').status_code==(200 if different else 409)
    with core.db() as c:
        assert [row[0] for row in c.execute('SELECT result FROM safety_target_adjudications')]==(['not_applicable'] if different else ['applicable'])


@pytest.mark.parametrize('raw',RESIDUAL)
def test_previously_misclassified_typed_evidence_is_immutable_and_fails_closed(monkeypatch,raw):
    actual=ee.cancellation_time_evidence
    def previous_parser(*args):
        proof=actual(*args)
        assert proof['texts']==[raw]
        return {**proof,'role':'actual_occurrence','occurrence':['2026-10-01']}
    with monkeypatch.context() as context:
        context.setattr(ee,'cancellation_time_evidence',previous_parser)
        prior=unlinked(context,raw)
    assert prior['occurrence']=='["2026-10-01"]'
    result,_,_=positive(monkeypatch)
    assert result['count']==0 and not core.events() and counts()['events']==0
    with core.db() as c:
        assert dict(c.execute('SELECT * FROM safety_observations').fetchone())==prior
        assert c.execute('SELECT COUNT(*) FROM safety_target_adjudications').fetchone()[0]==0
