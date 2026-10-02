"""Current-attempt observations, bounded inventory and completion invariants."""
import copy
import json
from datetime import datetime
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from radar import core, api, coverage, worker, collectors, aggregates
from test_coverage import isolated, source, page, stub_fetch, auth


def report(monkeypatch, s, pages, previous=None):
    calls=stub_fetch(monkeypatch,pages)
    result=coverage.collect_report(s,previous)
    return result,calls


@pytest.mark.parametrize('failure',[collectors.SourceError('unavailable'),collectors.Blocked('HTTP 429')])
def test_dated_failed_detail_backoff_is_deferred(monkeypatch,failure):
    s=source(enrich_dated=True,detail_budget=1);u=s['url'];detail='https://example.com/event/1'
    pages={u:page(),detail:failure};calls=stub_fetch(monkeypatch,pages)
    first=coverage.collect_report(s)
    with core.db() as db:before=dict(db.execute('SELECT * FROM detail_cache').fetchone())
    calls.clear();second=coverage.collect_report(s);m=second['coverage']
    assert calls==[(u,{'trusted_local':False,'proxy':None})]
    assert (m['detail_attempted'],m['detail_failed'],m['detail_deferred'])==(0,0,1)
    assert first['status']==second['status']=='partial' and not m['complete_scope']
    with core.db() as db:assert dict(db.execute('SELECT * FROM detail_cache').fetchone())==before
    worker.collect_source(s)
    with TestClient(api.app,base_url='https://testserver') as client:
        auth(client);assert client.get('/events/api/stats').json()['normal_sources']==0


def test_dated_detail_opt_out_and_changed_fingerprint(monkeypatch):
    s=source(enrich_dated=True,detail_budget=1);u=s['url'];detail='https://example.com/event/1'
    pages={u:page(),detail:collectors.SourceError('failed')};calls=stub_fetch(monkeypatch,pages)
    coverage.collect_report(s);calls.clear()
    opted=coverage.collect_report({**s,'enrich_dated':False})
    assert opted['status']=='ok' and opted['coverage']['detail_deferred']==0 and len(calls)==1
    pages[u]=page('changed title');calls.clear();changed=coverage.collect_report(s)
    assert changed['coverage']['detail_attempted']==1 and len(calls)==2


def test_successful_typed_detail_cache_still_resolves(monkeypatch):
    s=source(enrich_dated=True,detail_budget=1);u=s['url'];detail='https://example.com/event/1'
    data={'@type':'Event','name':'技术分享','startDate':'2026-10-17','location':{'name':'深圳会场'}}
    calls=stub_fetch(monkeypatch,{u:page(),detail:'<script type="application/ld+json">'+json.dumps(data)+'</script>'})
    coverage.collect_report(s);calls.clear();r=coverage.collect_report(s)
    assert r['coverage']['detail_cached']==1 and r['coverage']['detail_deferred']==0 and len(calls)==1


def monthly_index(n=5):
    return ''.join(f'<a href="/zhanhui_1/{i}.html">2026年{10+i}月深圳展会</a>' for i in range(n))


@pytest.mark.parametrize('n,max_pages,selected,visited,deferred,status',[(5,5,4,4,1,'partial'),(4,5,4,4,0,'ok'),(5,3,4,2,3,'partial')])
def test_monthly_inventory_explicit_cap(monkeypatch,n,max_pages,selected,visited,deferred,status):
    # September's accepted window contains October through February.
    index=''.join(f'<a href="/zhanhui_1/{i}.html">{2026+(9+i)//12}年{(9+i)%12+1}月深圳展会</a>' for i in range(n))
    s=source(kind='szhzfw',url='https://example.com/index',max_pages=max_pages);u=s['url']
    pages={u:index}
    for i in range(n):
        year=2026+(9+i)//12;month=(9+i)%12+1
        pages[f'https://example.com/zhanhui_1/{i}.html']=f'<title>{year}年{month}月深圳展会</title><div><p>1</p><p>技术展览{i}</p><p>场馆：深圳会场</p><p>开展时间：{year}年{month}月17日</p></div>'
    r,calls=report(monkeypatch,s,pages);m=r['coverage']
    assert r['status']==status
    assert (m['monthly_eligible'],m['monthly_selected'],m['monthly_visited'],m['monthly_deferred'])==(n,selected,visited,deferred)
    assert len(m['monthly_deferred_urls'])==deferred and len(calls)==visited+1
    assert m['complete_scope']==(status=='ok') and m['next_cursor'] is None
    if deferred:assert m['truncated'] and any('月' in reason and str(deferred) in reason for reason in m['reasons'])


def test_month_discovery_deduplicates_and_keeps_window():
    html=monthly_index(3)+monthly_index(3)+'<a href="/zhanhui_1/old.html">2025年1月深圳展会</a>'
    assert len(aggregates.monthly_links(BeautifulSoup(html,'html.parser'),'https://example.com/index'))==3


def test_month_failure_lists_every_unread_eligible_url(monkeypatch):
    s=source(kind='szhzfw',url='https://example.com/index');u=s['url']
    r,calls=report(monkeypatch,s,{u:monthly_index(3),'https://example.com/zhanhui_1/0.html':collectors.Blocked('HTTP 429')})
    m=r['coverage'];assert r['status']=='partial' and m['monthly_deferred']==3 and m['monthly_visited']==0
    assert m['monthly_deferred_urls']==m['monthly_eligible_urls'] and m['next_cursor'] is None and len(calls)==2


def test_month_time_budget_exposes_unread_inventory(monkeypatch):
    s=source(kind='szhzfw',url='https://example.com/index',max_seconds=5)
    clock=iter([0,0,6,6]);monkeypatch.setattr(coverage.time,'monotonic',lambda:next(clock,6))
    r,calls=report(monkeypatch,s,{s['url']:monthly_index(3)})
    m=r['coverage'];assert len(calls)==1 and m['monthly_visited']==0 and m['monthly_deferred']==3
    assert m['monthly_deferred_urls']==m['monthly_eligible_urls'] and r['status']=='partial' and m['next_cursor'] is None


HOST='<li class="list-entry"><p class="title"><a href="https://site.douban.com/123/">主办方卡片</a></p></li>'
EVENT='<li class="list-entry"><p class="title"><a href="/event/456/">深圳技术活动</a></p><meta itemprop="startDate" content="2026-10-17"><p class="loc">深圳会场</p></li>'


def test_organizer_only_page_continues_allowed_pagination(monkeypatch):
    s=source(kind='douban',detail_budget=0);u=s['url'];nxt=u+'?start=10'
    r,calls=report(monkeypatch,s,{u:HOST+'<div class="paginator"><a href="?start=10">后页&gt;</a></div>',nxt:EVENT})
    m=r['coverage'];assert len(calls)==2 and r['status']=='ok'
    assert (m['pages_visited'],m['visible'],m['extracted'],m['admitted'],m['parser_unaccounted'])==(2,2,1,1,0)
    assert m['rejected']['非活动主办方卡片']==1 and m['complete_scope']


@pytest.mark.parametrize('html,expected,visible',[(HOST,'empty',1),('<p>arbitrary</p>','error',None),('<li class="list-entry"><p class="title"><a href="https://evil.test/123">arbitrary</a></p></li>','error',None)])
def test_recognized_empty_and_unrecognized_markup(monkeypatch,html,expected,visible):
    s=source(kind='douban',detail_budget=0);r,_=report(monkeypatch,s,{s['url']:html})
    m=r['coverage'];assert r['status']==expected and m['visible']==visible and not m['complete_scope']
    assert m['counters_available']==(visible is not None)


def developer_row(i=1,mode='Online',date='2026-10-17',featured=False):
    data={'@type':'Event','name':f'Engineering workshop {i}','url':f'https://example.com/event/{i}','startDate':date,'eventAttendanceMode':f'https://schema.org/{mode}EventAttendanceMode','description':'Technical community event'}
    return '<div class="row'+(' featured' if featured else '')+'"><script type="application/ld+json">'+json.dumps(data)+'</script></div>'


@pytest.mark.parametrize('more',['','<button class="moreButton" hx-vals="invalid">More</button>','<button class="moreButton" hx-vals="null">More</button>'])
def test_declared_total_gap_without_actionable_more(monkeypatch,more):
    s=source(kind='devevents',coverage_mode='page_inventory',allow_online=True)
    r,calls=report(monkeypatch,s,{s['url']:developer_row()+'<p>Showing 1 out of 100</p>'+more});m=r['coverage']
    assert r['status']=='partial' and not m['complete_scope'] and len(calls)==1 and m['next_cursor'] is None
    assert m['source_total']==100 and m['source_total_observed']==1 and m['source_total_gap']==99
    assert m['source_total_basis']=='ordinary_nonfeatured_inventory_rows' and not m['source_total_reconciled']
    assert any('99' in reason for reason in m['reasons']) and any('后续' in reason for reason in m['reasons'])


def test_total_uses_inventory_before_filters(monkeypatch):
    s=source(kind='devevents',coverage_mode='page_inventory',allow_online=True)
    html=developer_row()+developer_row(2,'Offline')+developer_row(3,date='invalid')+developer_row(4,featured=True)+'<p>Showing 3 out of 3</p>'
    r,_=report(monkeypatch,s,{s['url']:html});m=r['coverage']
    assert r['status']=='ok' and m['complete_scope'] and m['source_total_reconciled']
    assert m['source_total_observed']==m['visible']==3 and m['admitted']==1 and m['parser_unaccounted']==0
    assert sum(m['rejected'].values())==2


def test_one_of_one_total_and_continuation_only(monkeypatch):
    s=source(kind='devevents',coverage_mode='page_inventory',allow_online=True);u=s['url']
    pages={u:developer_row()+'<p>Showing 1 out of 1</p>',u+'?page=2':developer_row()+'<p>Showing 1 out of 1</p>'}
    r,_=report(monkeypatch,s,pages);assert r['status']=='ok' and r['coverage']['complete_scope']
    r=coverage.collect_report(s,{'next_cursor':u+'?page=2'})
    assert r['status']=='partial' and not r['coverage']['complete_scope'] and not r['coverage']['traversal_from_root']


def test_incomparable_inventory_total_fails_closed(monkeypatch):
    s=source(kind='devevents',coverage_mode='page_inventory',allow_online=True)
    html='<div class="row">'+developer_row()+developer_row(2)+'</div><p>Showing 2 out of 2</p>'
    r,_=report(monkeypatch,s,{s['url']:html});m=r['coverage']
    assert r['status']=='partial' and not m['complete_scope'] and m['source_total_gap'] is None
    assert not m['source_total_comparable'] and any('比较' in x for x in m['reasons'])


def health():
    with core.db() as db:
        h=dict(db.execute('SELECT * FROM source_health').fetchone());h['coverage']=json.loads(h['coverage']);return h


@pytest.mark.parametrize('failure',[ValueError('crash'),collectors.Blocked('HTTP 429'),collectors.SourceError('down')])
def test_failure_never_relabels_last_good_as_current(monkeypatch,failure):
    s=source();u=s['url'];pages={u:''.join(page(slug=str(i)) for i in range(12))};stub_fetch(monkeypatch,pages)
    worker.collect_source(s);before=health();prior=copy.deepcopy(before['coverage']['last_good'])
    pages[u]=failure
    monkeypatch.setattr(core,'now',lambda:datetime(2026,10,2,12,tzinfo=core.TZ));monkeypatch.setattr(worker,'now',core.now)
    for count in (1,2):
        worker.collect_source(s);after=health();m=after['coverage']
        assert not m['counters_available'] and m['sampled_at'] is None and not m['complete_scope'] and m['truncated']
        assert all(m[key] is None for key in ('pages_visited','visible','extracted','unique','admitted','parser_unaccounted','detail_attempted'))
        assert m['source_total'] is None and m['page_urls']==[] and m['last_good']==prior
        assert after['raw_count']==12 and after['last_success']==before['last_success'] and after['failure_count']==count
        assert 'None' not in after['message']
        assert m['attempt_started_at']==after['last_attempt']!=prior['attempt_started_at']
        with TestClient(api.app,base_url='https://testserver') as client:
            auth(client);assert client.get('/events/api/stats').json()['normal_sources']==0
            emitted=client.get('/events/api/status').json()['sources'][0]['coverage']
            assert emitted['admitted'] is None and emitted['last_good']['admitted']==12
    pages[u]=page();worker.collect_source(s);assert health()['failure_count']==0 and health()['coverage']['counters_available']


def test_first_failure_and_legacy_nullable_previous(monkeypatch):
    s=source();stub_fetch(monkeypatch,{s['url']:ValueError('crash')});worker.collect_source(s)
    assert health()['coverage']['last_good'] is None
    with core.db() as db:
        db.execute('UPDATE source_health SET raw_count=8,last_success=?,status=?,coverage=?',('2026-09-29T10:00:00+08:00','ok',json.dumps({'visible':8,'admitted':8,'pages_visited':1,'complete_scope':True})))
    worker.collect_source(s);m=health()['coverage'];assert m['last_good']['legacy'] and m['last_good']['sampled_at']=='2026-09-29T10:00:00+08:00'
    assert not m['last_good']['complete_scope'] and health()['raw_count']==8
    with core.db() as db:db.execute('UPDATE source_health SET coverage=?',(json.dumps({'visible':None,'pages_visited':None,'counters_available':False}),))
    stub_fetch(monkeypatch,{s['url']:page()});worker.collect_source(s);assert health()['status']=='ok'


def test_inventory_drop_invalidates_completion(monkeypatch):
    s=source();pages={s['url']:''.join(page(slug=str(i)) for i in range(12))};stub_fetch(monkeypatch,pages)
    worker.collect_source(s);pages[s['url']]=page();worker.collect_source(s)
    h=health();assert h['status']=='partial' and not h['coverage']['complete_scope']
    assert h['coverage']['last_good']['status']=='partial' and any('50%' in reason for reason in h['coverage']['reasons'])


def test_failed_attempt_preserves_partial_sample_timestamp(monkeypatch):
    s=source(max_pages=1);u=s['url'];pages={u:page(next_url='?page=2')};stub_fetch(monkeypatch,pages)
    worker.collect_source(s);before=health()['coverage']['last_good']
    assert before['status']=='partial' and not before['complete_scope']
    pages[u]=ValueError('crash');worker.collect_source(s)
    assert health()['coverage']['last_good']==before


def test_unknown_legacy_provenance_does_not_create_sample(monkeypatch):
    s=source();stub_fetch(monkeypatch,{s['url']:ValueError('crash')})
    with core.db() as db:db.execute('UPDATE source_health SET coverage=?',(json.dumps({'visible':12,'complete_scope':True}),))
    worker.collect_source(s);assert health()['coverage']['last_good'] is None


def test_legacy_nested_sample_is_preserved_without_trusting_completion(monkeypatch):
    s=source();stub_fetch(monkeypatch,{s['url']:collectors.Blocked('HTTP 429')})
    old={'counters_available':False,'visible':None,'last_good':{'visible':8,'admitted':8,'pages_visited':1,'complete_scope':True}}
    with core.db() as db:db.execute('UPDATE source_health SET status=?,raw_count=8,last_success=?,coverage=?',('error','2026-09-29T10:00:00+08:00',json.dumps(old)))
    worker.collect_source(s);m=health()['coverage']['last_good']
    assert m['legacy'] and m['visible']==8 and m['sampled_at']=='2026-09-29T10:00:00+08:00' and not m['complete_scope']
    assert m['status']=='unknown' and 'last_good' not in m


def test_exception_after_report_preserves_measured_not_ingested_admission(monkeypatch):
    s=source();pages={s['url']:''.join(page(slug=str(i)) for i in range(3))};stub_fetch(monkeypatch,pages)
    original=worker.ingest;calls=[]
    def ingest(src,event):
        calls.append(event)
        if len(calls)==2:raise ValueError('storage failed')
        return original(src,event)
    monkeypatch.setattr(worker,'ingest',ingest);worker.collect_source(s);h=health();m=h['coverage']
    assert h['status']=='error' and m['counters_available'] and m['visible']==3 and not m['complete_scope']
    assert m['reported_admitted']==3 and m['admitted']==1 and m['stored_events']==1 and h['raw_count']==0
    assert m['last_good'] is None and h['last_success'] is None


def test_partial_ingest_failure_retains_prior_readable_sample(monkeypatch):
    s=source();pages={s['url']:''.join(page(slug=str(i)) for i in range(12))};stub_fetch(monkeypatch,pages)
    worker.collect_source(s);before=health()
    # Same title/date/venue across URLs is one logical event, twelve observed rows.
    assert before['event_count']==1
    pages[s['url']]=''.join(page(slug=str(20+i)) for i in range(3))
    original=worker.ingest;attempts=[]
    def ingest(src,event):
        attempts.append(event)
        if len(attempts)==2:raise ValueError('partial storage failure')
        return original(src,event)
    monkeypatch.setattr(worker,'ingest',ingest);worker.collect_source(s);h=health();m=h['coverage']
    assert m['last_good']==before['coverage']['last_good'] and h['last_success']==before['last_success'] and h['raw_count']==12
    assert m['visible']==m['reported_admitted']==3 and m['admitted']==1 and m['stored_events']==1 and not m['complete_scope']


@pytest.mark.parametrize('status',['partial','error','blocked','empty'])
def test_finalizer_invalidates_every_non_ok_status(status):
    m=coverage.fresh_coverage(source(),available=True);m.update(pages_visited=1,structure_recognized=True,complete_scope=True)
    assert coverage.finalize(m,status)==status and not m['complete_scope']


@pytest.mark.parametrize('blocker,value',[('truncated',True),('next_cursor','https://example.com/?page=2'),('parser_unaccounted',1),('detail_failed',1),('detail_deferred',1),('counters_available',False),('structure_recognized',False),('traversal_from_root',False),('source_total',100),('pages_visited',0),('error','unexpected')])
def test_each_pending_work_blocker_prevents_completion(blocker,value):
    m=coverage.fresh_coverage(source(),available=True);m.update(pages_visited=1,structure_recognized=True,complete_scope=True);m[blocker]=value
    assert coverage.finalize(m,'ok')=='partial' and not m['complete_scope']


def test_clean_full_scope_finalizer_control():
    m=coverage.fresh_coverage(source(),available=True);m.update(pages_visited=1,structure_recognized=True)
    assert coverage.finalize(m,'ok')=='ok' and m['complete_scope']
