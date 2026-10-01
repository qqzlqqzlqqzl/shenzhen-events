"""Query correctness and database-access regressions using disposable data."""
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from radar import api, core


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    (tmp_path/'static').mkdir()
    (tmp_path/'static/index.html').write_text('<html>fixture</html>')
    (tmp_path/'sources.json').write_text('[{"id":"a","name":"fixture","url":"https://example.com"}]')
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(api, 'ROOT', tmp_path)
    monkeypatch.setattr(core, 'now', lambda: datetime(2026, 10, 3, 12, tzinfo=core.TZ))
    api.initialize_settings()
    core.init()
    yield tmp_path


def seed(count=0, undated=False):
    with core.db() as c:
        data=[]
        for i in range(count):
            eid=f'row-{i:05}'
            data.append((eid,eid,None if undated else '2026-10-20T10:00:00+08:00',
                         None if undated else '2026-10-20T12:00:00+08:00',
                         'needs_review' if undated else 'scheduled',
                         '2026-10-01T00:00:00+08:00', 'https://example.com/'+eid))
        c.executemany("""INSERT INTO events(id,title,start_at,end_at,status,last_seen,url,
            all_day,location,organizer,summary,topics,priority,commercial,event_type,event_type_state)
            VALUES(?,?,?,?,?,?,?,0,'fixture','','fixture','["其他"]','normal','unknown','ConferenceEvent','source')""",data)
        c.executemany("INSERT INTO event_sources(event_id,source_id,url) VALUES(?,'a',?)",
                      [(x[0],x[6]) for x in data])


def put(eid='target', **updates):
    data=dict(id=eid,title='Target needle',start_at='2026-10-20T00:00:00+08:00',
              end_at='2026-10-21T00:00:00+08:00',all_day=1,status='scheduled',
              location='fixture',organizer='',summary='fixture',topics='["其他"]',
              priority='normal',commercial='unknown',last_seen='2026-10-01T00:00:00+08:00',
              url='https://example.com/'+eid,event_type='ConferenceEvent',event_type_state='source')
    data.update(updates)
    with core.db() as c:
        keys=list(data)
        c.execute(f"INSERT INTO events({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",tuple(data.values()))
        c.execute("INSERT INTO event_sources(event_id,source_id,url) VALUES(?,'a',?)",(eid,data['url']))
    return eid


def client():
    c=TestClient(api.app,base_url='https://testserver')
    c.cookies.set(api.COOKIE,api.sign_session({'id':1,'username':'fixture'}),path='/events')
    return c


def ids(**kwargs):
    return [e['id'] for e in core.events(**kwargs)]


def test_targets_after_ten_thousand_undated_rows_remain_queryable():
    seed(10000,undated=True)
    put()
    with core.db() as c:
        c.execute("INSERT INTO preferences(event_id,favorite) VALUES('target',1)")
        c.execute("INSERT INTO event_redirects VALUES('old-target','target')")
    cases=[
        {}, {'favorites':True}, {'query':'needle'},
        {'period':'calendar','range_start':'2026-10-01T00:00:00+08:00','range_end':'2026-11-01T00:00:00+08:00'},
        {'period':'record','event_id':'target','include_hidden':True},
        {'period':'record','event_id':'old-target','include_hidden':True},
    ]
    for kwargs in cases:
        assert 'target' in ids(**kwargs),kwargs
    assert ids(period='saved',sort='desc')[0]=='target'
    with client() as c:
        assert c.get('/events/api/event/old-target').status_code==200
        r=c.get('/events/api/events?favorites=true').json()
        assert r['total']==1 and r['items'][0]['id']=='target'
        assert c.get('/events/api/calendar-summary').json()['total']==1


@pytest.mark.parametrize('end',[None,'2026-10-02T23:00:00+08:00',
    '2026-10-03T00:00:00+08:00','2026-10-03T10:00:00+08:00'])
@pytest.mark.parametrize('clock,upcoming',[
    ('2026-10-03T12:00:00+08:00',True),
    ('2026-10-03T23:59:59+08:00',True),
    ('2026-10-04T00:00:00+08:00',False),
])
def test_all_day_uses_the_complete_shanghai_day_without_changing_source(end,clock,upcoming,monkeypatch):
    put(start_at='2026-10-03T00:00:00+08:00',end_at=end)
    monkeypatch.setattr(core,'now',lambda:datetime.fromisoformat(clock))
    for period in ['upcoming','week','weekend']:
        assert bool(ids(period=period)) is upcoming,period
    assert bool(ids(period='past')) is not upcoming
    for period in ['calendar','range']:
        assert ids(period=period,range_start='2026-10-03T00:00:00+08:00',range_end='2026-10-04T00:00:00+08:00')==['target']
        assert not ids(period=period,range_start='2026-10-04T00:00:00+08:00',range_end='2026-10-05T00:00:00+08:00')
    with core.db() as c:
        raw=c.execute("SELECT start_at,end_at FROM events WHERE id='target'").fetchone()
        assert tuple(raw)==('2026-10-03T00:00:00+08:00',end)


def test_known_exclusive_end_has_no_upcoming_past_gap(monkeypatch):
    put(start_at='2026-10-03T10:00:00+08:00',end_at='2026-10-03T12:00:00+08:00',all_day=0)
    assert not ids() and ids(period='past')==['target']
    monkeypatch.setattr(core,'now',lambda:datetime(2026,10,3,11,59,59,tzinfo=core.TZ))
    assert ids()==['target'] and not ids(period='past')


def test_timed_unknown_end_keeps_three_hour_upcoming_policy(monkeypatch):
    put(start_at='2026-10-03T10:00:00+08:00',end_at=None,all_day=0)
    assert ids()==['target']
    monkeypatch.setattr(core,'now',lambda:datetime(2026,10,3,13,tzinfo=core.TZ))
    assert not ids()
    assert ids(period='past')==['target']


def test_timed_unknown_end_preserves_its_start_boundary():
    put(start_at='2026-10-03T12:00:00+08:00',end_at=None,all_day=0)
    assert ids()==['target']
    assert not ids(period='past')


def test_confirmed_multiday_end_covers_cross_month_then_excludes_boundary(monkeypatch):
    put(start_at='2026-09-30T00:00:00+08:00',end_at='2026-10-04T00:00:00+08:00')
    assert ids()==['target']
    monkeypatch.setattr(core,'now',lambda:datetime(2026,10,4,tzinfo=core.TZ))
    assert not ids() and ids(period='past')==['target']


def test_api_pagination_has_a_reachable_next_page_beyond_ten_thousand():
    seed(10013)
    with client() as c:
        r=c.get('/events/api/events?offset=9996&limit=12')
        assert r.status_code==200
        first=r.json()
        assert first['total']==10013 and len(first['items'])==12 and first['has_more']
        next_page=c.get('/events/api/events?offset=10008&limit=12')
        assert next_page.status_code==200
        last=next_page.json()
        assert len(last['items'])==5 and not last['has_more'] and last['total']==10013
        assert not set(x['id'] for x in first['items'])&set(x['id'] for x in last['items'])
        assert first['facets']==last['facets']


class ObservedCursor:
    def __init__(self,cursor,counter,kind):
        self.cursor,self.counter,self.kind=cursor,counter,kind
    def count(self,rows):
        if self.kind:self.counter[self.kind]+=len(rows)
        return rows
    def __iter__(self):
        for row in self.cursor:
            self.count([row]);yield row
    def fetchone(self):
        row=self.cursor.fetchone()
        if row is not None:self.count([row])
        return row
    def fetchall(self):return self.count(self.cursor.fetchall())
    def fetchmany(self,*args):return self.count(self.cursor.fetchmany(*args))
    def __getattr__(self,name):return getattr(self.cursor,name)


def observe(monkeypatch):
    original=core.db;counts={'events':0,'links':0,'sql':[],'plans':[]}
    class Connection:
        def __init__(self,c):self.c=c
        def execute(self,sql,*args):
            lower=sql.lower();kind='events' if 'from events e' in lower else 'links' if 'from event_sources es' in lower else None
            if kind:
                counts['sql'].append(sql)
                counts['plans'].append([tuple(x) for x in self.c.execute('EXPLAIN QUERY PLAN '+sql,*args)])
            return ObservedCursor(self.c.execute(sql,*args),counts,kind)
        def __getattr__(self,name):return getattr(self.c,name)
    @contextmanager
    def tracked():
        with original() as c:yield Connection(c)
    monkeypatch.setattr(core,'db',tracked)
    return counts


def test_detail_reads_one_event_and_only_its_source_links(monkeypatch):
    seed(1000)
    count=observe(monkeypatch)
    assert ids(period='record',event_id='row-00999')==['row-00999']
    assert count['events']==1 and count['links']==1,count
    assert any('SEARCH e ' in str(p) for p in count['plans'])
    assert any('idx_event_sources_event' in str(p) for p in count['plans'])


def test_upcoming_prunes_undated_candidates_before_hydration(monkeypatch):
    seed(10000,undated=True);put()
    count=observe(monkeypatch)
    assert ids()==['target']
    assert count['events']==1 and count['links']==1,count


def test_stats_reuses_one_candidate_hydration(monkeypatch):
    seed(1000)
    count=observe(monkeypatch)
    with client() as c:assert c.get('/events/api/stats').json()['upcoming']==1000
    assert count['events']==1000 and count['links']==1000,count


def test_alias_overrides_precede_search_topics_and_attendance(isolated):
    put(title='Raw title',location='Raw venue')
    (isolated/'dedupe_aliases.json').write_text(json.dumps([{
        'date':'2026-10-20','urls':['https://example.com/target'],
        'canonical':{'title':'Canonical needle','location':'线上','topics':['AI与开源']}}]))
    assert ids(query='canonical',topics_filter=['AI与开源'],attendance='online')==['target']
    assert not ids(query='raw title')
    with core.db() as c:c.execute("INSERT INTO preferences(event_id,hidden) VALUES('target',1)")
    assert not ids(query='canonical')
    assert ids(query='canonical',include_hidden=True)==['target']


@pytest.mark.parametrize('period',['saved','feedback','history','review','past','record'])
def test_explicit_date_bounds_intersect_personal_view_without_replacing_its_policy(period):
    put('inside',start_at='2026-09-30T00:00:00+08:00',end_at='2026-10-02T00:00:00+08:00',
        status='needs_review' if period=='review' else 'cancelled')
    put('outside',start_at='2026-09-28T00:00:00+08:00',end_at='2026-09-30T00:00:00+08:00',
        status='needs_review' if period=='review' else 'not_event')
    put('undated',start_at=None,end_at=None,status='needs_review')
    for eid in ['inside','outside','undated']:
        with core.db() as c:
            c.execute("INSERT INTO preferences(event_id,favorite,feedback,feedback_updated_at,viewed_at) VALUES(?,1,'interested',?,?)",
                (eid,{'inside':'2026-10-02','outside':'2026-10-01','undated':'2026-09-30'}[eid],
                 {'inside':'2026-10-01','outside':'2026-10-02','undated':'2026-09-30'}[eid]))
    options=dict(period=period,sort='desc',favorites=period=='saved',feedback='any' if period=='feedback' else '',viewed='seen' if period=='history' else 'all')
    original=ids(**options)
    assert 'inside' in original and 'outside' in original
    assert ('undated' in original) is (period!='past')
    bounds=dict(range_start='2026-10-01T00:00:00+08:00',range_end='2026-10-02T00:00:00+08:00')
    assert ids(**options,**bounds)==[eid for eid in original if eid=='inside']
    assert ids(**options)==original
    with core.db() as c:
        assert c.execute("SELECT status,start_at,end_at FROM events WHERE id='inside'").fetchone()['status']==('needs_review' if period=='review' else 'cancelled')


@pytest.mark.parametrize('end',[None,'2026-10-03T00:00:00+08:00','2026-10-02T23:00:00+08:00','2026-10-03T10:00:00+08:00'])
def test_explicit_personal_range_uses_full_all_day_and_exclusive_boundary(end):
    put(end_at=end,start_at='2026-10-03T00:00:00+08:00',status='cancelled')
    assert ids(period='saved',range_start='2026-10-03T23:59:59+08:00',range_end='2026-10-04T00:00:00+08:00')==['target']
    assert not ids(period='saved',range_start='2026-10-04T00:00:00+08:00',range_end='2026-10-05T00:00:00+08:00')
    assert ids(period='saved')==['target']
    with core.db() as c:assert c.execute("SELECT end_at FROM events WHERE id='target'").fetchone()[0]==end


def test_explicit_personal_range_preserves_sort_long_running_hidden_and_one_sided_bounds():
    put('long',start_at='2026-09-01T00:00:00+08:00',end_at='2026-11-01T00:00:00+08:00',status='cancelled')
    put('next',start_at='2026-10-05T00:00:00+08:00',end_at='2026-10-06T00:00:00+08:00',status='cancelled')
    put('undated',start_at=None,end_at=None,status='needs_review')
    put('hidden',status='cancelled')
    with core.db() as c:c.execute("INSERT INTO preferences(event_id,hidden) VALUES('hidden',1)")
    options=dict(period='saved',hide_long=True,sort='desc')
    assert ids(**options)==['next','long','undated']
    assert ids(**options,range_start='2026-10-04T00:00:00+08:00')==['next','long']
    assert ids(**options,range_end='2026-10-05T00:00:00+08:00')==['long']
    assert ids(**options,range_start='2026-10-05T00:00:00+08:00',range_end='2026-10-06T00:00:00+08:00')==['next','long']


def test_explicit_range_normalizes_offset_and_timed_unknown_end_is_not_invented():
    put('offset',start_at='2026-10-02T23:00:00+00:00',end_at=None,all_day=1,status='cancelled')
    put('timed',start_at='2026-10-03T10:00:00+08:00',end_at=None,all_day=0,status='cancelled')
    assert ids(period='saved',range_start='2026-10-03T12:00:00+08:00',range_end='2026-10-04T00:00:00+08:00')==['offset']
    assert ids(period='saved',range_start='2026-10-03T10:00:00+08:00',range_end='2026-10-03T10:00:01+08:00')==['offset','timed']


def test_explicit_range_pruning_normalizes_both_boundary_offsets():
    put('span',start_at='2026-10-02T00:00:00+08:00',end_at='2026-10-03T20:00:00+08:00',status='cancelled')
    assert ids(period='saved',range_start='2026-10-04T00:00:00+14:00',range_end='2026-10-04T02:00:00+14:00')==['span']
    put('early',start_at='2026-10-03T02:00:00+08:00',end_at='2026-10-03T03:00:00+08:00',all_day=0,status='cancelled')
    assert ids(period='saved',range_start='2026-10-02T15:00:00+00:00',range_end='2026-10-02T20:00:00+00:00')==['span','early']


def test_all_day_invalid_legacy_end_uses_its_known_date_without_rewriting_it():
    put(start_at='2026-10-03T00:00:00+08:00',end_at='invalid')
    assert ids()==['target'] and not ids(period='past')
    assert ids(period='saved',range_start='2026-10-03T23:00:00+08:00',range_end='2026-10-04T00:00:00+08:00')==['target']
    with core.db() as c:assert c.execute("SELECT end_at FROM events WHERE id='target'").fetchone()[0]=='invalid'


@pytest.mark.parametrize('all_day',[0,1])
def test_range_pruning_keeps_non_shanghai_end_after_canonical_start(all_day):
    start='2026-09-30T23:30:00+08:00';end='2026-09-30T23:30:00+00:00'
    put(start_at=start,end_at=end,all_day=all_day)
    bounds=dict(range_start='2026-10-01T00:00:00+08:00',range_end='2026-10-02T00:00:00+08:00')
    assert core.overlaps_range({'start_at':start,'end_at':end,'all_day':all_day},**bounds)
    for period in ['calendar','range','saved']:
        assert ids(period=period,**bounds)==['target']
    with core.db() as c:assert tuple(c.execute("SELECT start_at,end_at FROM events WHERE id='target'").fetchone())==(start,end)


@pytest.mark.parametrize('clock',['2026-10-03T01:00:00+08:00','2026-10-02T17:00:00+00:00','2026-10-03T01:00:00'])
def test_utc_activity_spanning_shanghai_midnight_has_consistent_periods_and_stats(clock,monkeypatch):
    start='2026-10-02T16:00:00+00:00';end='2026-10-02T20:00:00+00:00'
    put(start_at=start,end_at=end,all_day=0)
    monkeypatch.setattr(core,'now',lambda:datetime.fromisoformat(clock))
    for period in ['upcoming','week','weekend']:assert ids(period=period)==['target']
    assert not ids(period='past')
    with client() as c:
        result=c.get('/events/api/stats').json()
        assert result['upcoming']==1 and result['weekend']==1
    monkeypatch.setattr(core,'now',lambda:datetime.fromisoformat('2026-10-03T04:00:00+08:00'))
    for period in ['upcoming','week','weekend']:assert not ids(period=period)
    assert ids(period='past')==['target']


@pytest.mark.parametrize('start,end',[
    ('2026-10-03T10:00:00','2026-10-03T06:00:00+00:00'),
    ('2026-10-03T02:00:00+00:00','2026-10-03T14:00:00'),
    ('2026-10-03T10:00:00+08:00','2026-10-03T14:00:00'),
    ('2026-10-03 10:00:00+08:00','2026-10-03 14:00:00+08:00'),
])
def test_mixed_legacy_start_end_have_valid_span_and_do_not_crash_views(start,end):
    put(start_at=start,end_at=end,all_day=0)
    event={'start_at':start,'end_at':end}
    assert core.span_days(event)==pytest.approx(4/24)
    for period in ['upcoming','week','weekend']:assert ids(period=period)==['target']
    assert not ids(period='past')
    assert ids(period='calendar',range_start='2026-10-03T12:00:00+08:00',range_end='2026-10-03T13:00:00+08:00')==['target']
    with core.db() as c:assert tuple(c.execute("SELECT start_at,end_at FROM events WHERE id='target'").fetchone())==(start,end)


def test_week_and_weekend_upper_bounds_compare_instants_before_pruning(monkeypatch):
    monkeypatch.setattr(core,'now',lambda:datetime.fromisoformat('2026-10-02T12:00:00+08:00'))
    # The raw date is Monday but the actual Shanghai start is Sunday 18:00.
    put('inside',start_at='2026-10-05T00:00:00+14:00',end_at='2026-10-05T01:00:00+14:00',all_day=0)
    # The raw UTC date is Sunday but its Shanghai start is the exclusive Monday boundary.
    put('boundary',start_at='2026-10-04T16:00:00+00:00',end_at='2026-10-04T17:00:00+00:00',all_day=0)
    for period in ['week','weekend']:assert ids(period=period)==['inside']
    with client() as c:assert c.get('/events/api/stats').json()['weekend']==1
    assert ids(period='calendar',range_start='2026-10-04T00:00:00+08:00',range_end='2026-10-05T00:00:00+08:00')==['inside']


def test_past_pruning_accepts_legacy_raw_dates_after_the_shanghai_clock(monkeypatch):
    monkeypatch.setattr(core,'now',lambda:datetime.fromisoformat('2026-10-01T20:00:00+08:00'))
    put(start_at='2026-10-02T00:00:00+14:00',end_at='2026-10-02T01:00:00+14:00',all_day=0)
    assert ids(period='past')==['target'] and not ids()


def test_mixed_legacy_long_running_span_is_not_silently_discarded():
    start='2026-10-01T00:00:00';end='2026-10-14T16:00:00+00:00'
    put(start_at=start,end_at=end,all_day=0)
    assert core.span_days({'start_at':start,'end_at':end})==14
    result=core.events()
    assert len(result)==1 and result[0]['long_running'] and result[0]['display_at']=='2026-10-03T12:00:00+08:00'
    assert (result[0]['start_at'],result[0]['end_at'])==(start,end)
    assert not ids(hide_long=True)
    with client() as c:
        stats=c.get('/events/api/stats').json()
        assert stats['upcoming']==1 and stats['long_running']==1 and stats['weekend']==0


@pytest.mark.parametrize('start',['2026-10-03T10:00:00','2026-10-03T02:00:00Z','2026-10-03T16:00:00+14:00'])
def test_timed_unknown_legacy_end_keeps_its_three_hour_and_past_start_policies(start,monkeypatch):
    put(start_at=start,end_at=None,all_day=0)
    assert ids()==['target'] and ids(period='past')==['target']
    monkeypatch.setattr(core,'now',lambda:datetime.fromisoformat('2026-10-03T13:00:00+08:00'))
    assert not ids() and ids(period='past')==['target']


def test_legacy_time_order_compares_instants_without_changing_output_format():
    put('early',start_at='2026-10-03T10:00:00',end_at='2026-10-03T12:00:00+08:00',all_day=0)
    put('late',start_at='2026-10-03T03:00:00+00:00',end_at='2026-10-03T13:00:00+08:00',all_day=0)
    assert ids(period='saved')==['early','late']
    assert ids(period='saved',sort='desc')==['late','early']
    assert core.events(period='saved')[0]['start_at']=='2026-10-03T10:00:00'


@pytest.mark.parametrize('all_day,end',[ (0,None),(1,'2026-10-04T00:00:00.500000+08:00') ])
def test_legacy_subsecond_query_ends_keep_their_actual_exclusive_boundary(all_day,end,monkeypatch):
    start='2026-10-03T10:00:00.500000+08:00' if not all_day else '2026-10-03T00:00:00+08:00'
    put(start_at=start,end_at=end,all_day=all_day)
    before='2026-10-03T13:00:00.250000+08:00' if not all_day else '2026-10-04T00:00:00.250000+08:00'
    boundary='2026-10-03T13:00:00.500000+08:00' if not all_day else end
    monkeypatch.setattr(core,'now',lambda:datetime.fromisoformat(before))
    assert ids()==['target']
    monkeypatch.setattr(core,'now',lambda:datetime.fromisoformat(boundary))
    assert not ids() and ids(period='past')==['target']
