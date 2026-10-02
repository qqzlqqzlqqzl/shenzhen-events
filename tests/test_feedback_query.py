"""Feedback prefilter equivalence, gate, facets and transaction snapshots."""
import itertools
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from radar import core
from radar.filtering import contextual_listing

PREDICATE="(COALESCE(p.feedback,'')<>'' OR COALESCE(p.feedback_tags,'[]') NOT IN ('','[]'))"
MARKER='SELECT e.*,COALESCE(p.favorite,0) favorite'
NOW=datetime(2026,10,3,12,tzinfo=core.TZ)
SIGNALS=[None,'','unknown','interested','attended','not_interested']
TAGS=[None,'','[]','[ ]','{bad','null','{}','["topic_like"]',
      '["unknown"]','["\\u0074opic_like",3,"time_conflict"]']


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(core,'ROOT',tmp_path)
    monkeypatch.setattr(core,'now',lambda:NOW)
    (tmp_path/'sources.json').write_text('[{"id":"a","name":"Synthetic A","url":"https://example.invalid"},{"id":"b","name":"Synthetic B","url":"https://example.invalid"}]')
    # Nullable historical columns are a supported state, not coerced test input.
    (tmp_path/'data').mkdir()
    with sqlite3.connect(tmp_path/'data/events.sqlite3') as c:
        c.execute('CREATE TABLE preferences(event_id TEXT PRIMARY KEY REFERENCES events(id),favorite INTEGER DEFAULT 0,hidden INTEGER DEFAULT 0,feedback TEXT,feedback_tags TEXT,feedback_updated_at TEXT)')
    core.init()
    return tmp_path


def seed(count=360, empty=False):
    values=list(itertools.product(SIGNALS,TAGS))
    with core.db() as c:
        for i in range(count):
            eid=f'row-{i:06d}';start=NOW+timedelta(days=i%13-6)
            begin=start.isoformat() if i%11 else start.replace(tzinfo=None).isoformat()
            end=(start+timedelta(days=20 if i%7==0 else 1)).isoformat()
            signal,tags=('','[]') if empty else values[i%len(values)]
            c.execute("""INSERT INTO events(id,title,start_at,end_at,all_day,status,location,district,
                organizer,summary,topics,last_seen,url,event_type_state,details,priority,commercial,event_type)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'normal','unknown','ConferenceEvent')""",
                (eid,eid,begin,end,i%2,'cancelled' if i%17==0 else 'scheduled','Hall',
                 '南山' if i%2 else '福田','Synthetic Org','Summary','["硬件创客"]',NOW.isoformat(),
                 'https://example.invalid/'+eid,'source',json.dumps({'attendance':['online','offline','hybrid'][i%3]})))
            c.execute('INSERT INTO preferences(event_id,favorite,hidden,feedback,feedback_tags,viewed_at) VALUES(?,?,?,?,?,?)',
                      (eid,int(i%7==0),int(i%19==0),signal,tags,NOW.isoformat() if i%3 else None))
            c.execute("INSERT INTO event_sources(event_id,source_id,url) VALUES(?,'a',?)",(eid,'https://example.invalid/'+eid))


def observed(monkeypatch,legacy=False):
    original=core.db;queries=[];hydrated=[]
    class Connection:
        def __init__(self,c):self.c=c
        def execute(self,sql,params=()):
            if sql.startswith(MARKER):
                assert self.c.in_transaction  # Existing BEGIN remains before SELECT.
                if legacy:sql=sql.replace(' AND '+PREDICATE,'').replace(PREDICATE+' AND ','').replace('WHERE '+PREDICATE+' ORDER BY','WHERE 1 ORDER BY')
                queries.append(sql)
            return self.c.execute(sql,params)
        def __getattr__(self,key):return getattr(self.c,key)
    @contextmanager
    def db():
        with original() as c:yield Connection(c)
    original_links=core._source_links
    def links(c,ids):hydrated.extend(ids);return original_links(c,ids)
    monkeypatch.setattr(core,'db',db);monkeypatch.setattr(core,'_source_links',links)
    return queries,hydrated


@pytest.mark.parametrize('feedback,tag',list(itertools.product(['','any','none','interested','unknown'],['','topic_like','unknown'])))
def test_only_requested_any_or_tag_enables_gate(monkeypatch,feedback,tag):
    seed(2)
    queries,_=observed(monkeypatch)
    core.events(period='feedback',feedback=feedback,feedback_tag=tag)
    assert (PREDICATE in queries[0])==(feedback=='any' or bool(tag))
    assert ' LEFT JOIN preferences ' in queries[0]
    assert queries[0].endswith(' ORDER BY e.start_at,e.id')
    assert ' LIMIT ' not in queries[0] and 'SELECT event_id FROM preferences' not in queries[0]


@pytest.mark.parametrize('feedback,tag,extras',list(itertools.product(
    ['any','none','interested',''],['','topic_like','time_conflict'],
    [{},{'sort':'desc','include_hidden':True},{'attendance':'online','viewed':'seen'},
     {'favorites':True},{'districts':['南山'],'topics_filter':['硬件创客']},
     {'period':'calendar','range_start':'2026-10-01T00:00:00+08:00','range_end':'2026-10-10T00:00:00+08:00'}])))
def test_complete_ordered_output_and_contextual_facets_equal_legacy(monkeypatch,feedback,tag,extras):
    seed()
    options={'period':'history','feedback':feedback,'feedback_tag':tag,**extras}
    actual=core.events(**options)
    with monkeypatch.context() as m:
        observed(m,legacy=True);expected=core.events(**options)
    assert actual==expected
    for context in [{},{'districts':['南山'],'event_types':['ConferenceEvent'],'topics':['硬件创客'],'offset':2,'limit':3},
                    {'district_none':True},{'topic_none':True},{'type_none':True}]:
        assert contextual_listing(actual,**context)==contextual_listing(expected,**context)


def test_hydrates_only_candidate_superset_and_preserves_preferences(monkeypatch):
    seed(1500,empty=True)
    with core.db() as c:
        c.execute("UPDATE preferences SET feedback_tags='[\"topic_like\"]',hidden=0 WHERE event_id='row-001499'")
        c.execute("UPDATE preferences SET feedback='unknown',hidden=0 WHERE event_id='row-001498'")
        before=[tuple(r) for r in c.execute('SELECT * FROM preferences ORDER BY event_id')]
    _,hydrated=observed(monkeypatch)
    assert [e['id'] for e in core.events(period='feedback',feedback='any')]==['row-001499']
    assert set(hydrated)=={'row-001498','row-001499'}
    with core.db() as c:assert [tuple(r) for r in c.execute('SELECT * FROM preferences ORDER BY event_id')]==before


@pytest.mark.parametrize('action',['clear','add'])
def test_feedback_and_sources_share_snapshot_and_next_read_is_fresh(monkeypatch,action):
    seed(2,empty=True)
    with core.db() as c:
        c.execute("UPDATE preferences SET feedback='interested',hidden=0 WHERE event_id='row-000001'")
        c.execute("UPDATE preferences SET hidden=0 WHERE event_id='row-000000'")
    original=core._source_links;changed=False
    def update_during_read(c,ids):
        nonlocal changed
        if not changed:
            changed=True
            with core.db() as writer:
                if action=='clear':writer.execute("UPDATE preferences SET feedback='',feedback_tags='[]' WHERE event_id='row-000001'")
                else:writer.execute("UPDATE preferences SET feedback='attended' WHERE event_id='row-000000'")
                writer.execute("INSERT INTO event_sources(event_id,source_id,url) VALUES('row-000001','b','https://example.invalid/new')")
        return original(c,ids)
    monkeypatch.setattr(core,'_source_links',update_during_read)
    current=core.events(period='feedback',feedback='any')
    assert [e['id'] for e in current]==['row-000001'] and len(current[0]['sources'])==1
    next_rows=core.events(period='feedback',feedback='any')
    assert {e['id'] for e in next_rows}==(set() if action=='clear' else {'row-000000','row-000001'})
    target=core.events(period='record',event_id='row-000001')[0]
    assert len(target['sources'])==2 and target['feedback']==('' if action=='clear' else 'interested')
