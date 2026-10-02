"""Residual sample-provenance and observed-continuation review controls."""
import json
from radar import core, coverage, worker, collectors
from test_coverage import isolated, source, page, stub_fetch
from test_coverage_accounting import health, developer_row


def failed_first_report(monkeypatch,s,pages):
    original=worker.ingest;calls=[]
    def ingest(src,event):
        calls.append(event)
        if len(calls)==2:raise ValueError('synthetic partial ingest failure')
        return original(src,event)
    with monkeypatch.context() as local:
        local.setattr(worker,'ingest',ingest)
        worker.collect_source(s)
    h=health()
    assert h['status']=='error' and h['raw_count']==0 and h['last_success'] is None
    assert h['coverage']['visible']==h['coverage']['reported_admitted']==12
    assert h['coverage']['admitted']==1 and h['coverage']['last_good'] is None
    return h


def test_explicit_null_sample_stays_null_after_later_blocked_fetch(monkeypatch):
    s=source();pages={s['url']:''.join(page(slug=str(i)) for i in range(12))};stub_fetch(monkeypatch,pages)
    failed_first_report(monkeypatch,s,pages)
    pages[s['url']]=collectors.Blocked('HTTP 429');worker.collect_source(s);h=health()
    assert h['status']=='blocked' and h['coverage']['last_good'] is None
    assert h['raw_count']==0 and h['last_success'] is None and not h['coverage']['counters_available']


def test_one_row_recovery_does_not_compare_against_failed_report(monkeypatch):
    s=source();pages={s['url']:''.join(page(slug=str(i)) for i in range(12))};stub_fetch(monkeypatch,pages)
    failed_first_report(monkeypatch,s,pages)
    pages[s['url']]=page();worker.collect_source(s);h=health()
    assert h['status']=='ok' and h['coverage']['complete_scope']
    assert h['raw_count']==1 and h['last_success'] is not None and h['coverage']['last_good']['visible']==1
    assert not any('50%' in reason for reason in h['coverage']['reasons'])


def test_malformed_more_without_total_is_unresolved_not_terminal(monkeypatch):
    s=source(kind='devevents',coverage_mode='page_inventory',allow_online=True)
    calls=stub_fetch(monkeypatch,{s['url']:developer_row()+'<button class="moreButton" hx-vals="invalid-json">More</button>'})
    r=coverage.collect_report(s);m=r['coverage']
    assert r['status']=='partial' and not m['complete_scope']
    assert m['continuation_unavailable'] and m['truncated'] and m['next_cursor'] is None and m['source_total'] is None
    assert len(calls)==1 and any('后续分页' in reason for reason in m['reasons'])


def test_missing_legacy_sample_key_retains_dated_history(monkeypatch):
    s=source();stub_fetch(monkeypatch,{s['url']:collectors.Blocked('HTTP 429')})
    old={'visible':12,'admitted':12,'pages_visited':1,'complete_scope':True}
    with core.db() as db:db.execute('UPDATE source_health SET status=?,raw_count=12,last_success=?,coverage=?',('ok','2026-09-29T10:00:00+08:00',json.dumps(old)))
    worker.collect_source(s);h=health();prior=h['coverage']['last_good']
    assert prior['legacy'] and prior['visible']==12 and prior['sampled_at']=='2026-09-29T10:00:00+08:00'
    assert not prior['complete_scope'] and h['raw_count']==12


def test_existing_normally_persisted_sample_survives_failure(monkeypatch):
    s=source();pages={s['url']:''.join(page(slug=str(i)) for i in range(12))};stub_fetch(monkeypatch,pages)
    worker.collect_source(s);before=health();prior=before['coverage']['last_good']
    assert prior['complete_scope'] and prior['visible']==12
    pages[s['url']]=collectors.Blocked('HTTP 429');worker.collect_source(s);h=health()
    assert h['coverage']['last_good']==prior and h['last_success']==before['last_success'] and h['raw_count']==12


def test_valid_more_then_terminal_page_without_total_is_complete(monkeypatch):
    s=source(kind='devevents',coverage_mode='page_inventory',allow_online=True);u=s['url']
    more='<button class="moreButton" hx-vals=\'{"page":2}\'>More</button>'
    calls=stub_fetch(monkeypatch,{u:developer_row()+more,u+'?page=2':developer_row(2)})
    r=coverage.collect_report(s);m=r['coverage']
    assert r['status']=='ok' and m['complete_scope'] and m['pages_visited']==2 and m['source_total'] is None
    assert len(calls)==2 and not m.get('continuation_unavailable')
