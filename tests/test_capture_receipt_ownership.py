"""Independent synthetic interleavings, no production or real network."""
import json
import pytest
from radar import collectors,core,coverage,eefocus as ee,safety,worker
from test_eefocus import DESIGN,isolated,load,report,transport
from test_eefocus_safety import seed,guards,planning,receipt,ALIAS


def test_optional_failure_receipt_stays_bound_to_its_own_capture(monkeypatch):
    eid=seed(monkeypatch)
    transport(monkeypatch,{ee.LIST_URL:load('fixtures/safety-cancelled-list.html')})
    identities={}
    def overlap_then_fail(*args,**kwargs):
        identities['own']=receipt()['capture_id']
        assert guards() and not core.events()
        # The first capture has already finalized, so the real safety seam
        # admits another owner while its optional details remain in flight.
        other=safety.claim(safety.begin_capture(DESIGN['source']))
        other=safety.retain(other,load('fixtures/redirect-list.html'),ee.LIST_URL,
                            [{'url':ee.LIST_URL,'status':200,'location':''}])
        identities['other']=safety.finalize(other)['capture_id']
        raise RuntimeError('synthetic optional transport failure')
    monkeypatch.setattr(ee,'enrich',overlap_then_fail)
    result=worker.collect_source(DESIGN['source'])
    _,metrics=report()
    assert result['status']=='error' and identities['own']!=identities['other']
    # Authority/eligibility must remain safe even if the health receipt is wrong.
    assert guards() and not core.events()
    planning(eid,False)
    print(json.dumps({'own_capture':identities['own'],'other_capture':identities['other'],
                      'reported_capture':metrics['safety']['capture_id'],
                      'reported_guards_created':result.get('guards_created'),
                      'actual_active_guards':len(guards()),'planning_blocked':True}))
    assert metrics['safety']['capture_id']==identities['own'], 'failure reporting borrowed a different capture receipt'


def test_optional_failure_has_explicit_unknown_request_counters(monkeypatch):
    seed(monkeypatch)
    transport(monkeypatch,{ee.LIST_URL:load('fixtures/safety-cancelled-list.html'),
                           ALIAS:RuntimeError('synthetic optional failure')})
    result=worker.collect_source(DESIGN['source']);_,metrics=report()
    assert result['status']=='error' and metrics['safety']['outcome']=='observed_and_applied'
    for key in ('requests_attempted','http_requests_attempted'):
        assert key in metrics and metrics[key] is None, key
    assert metrics['counters_available'] is False
