#!/usr/bin/env python3
"""Synthetic, disposable comparison of current and prior favorite SQL predicates.
No network, production, real user data, API changes, or pre-filter limit.
Run from the repository: python tests/benchmark_favorite_query.py
"""
import argparse, contextlib, hashlib, json, platform, sqlite3, statistics, sys, tempfile, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

P=argparse.ArgumentParser();P.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]);P.add_argument('--out',type=Path,default=Path('artifacts/favorite-query-benchmark.json'));P.add_argument('--sizes',default='10000,100000');P.add_argument('--repeats',type=int,default=7);args=P.parse_args()
if any(int(n) not in (10000,100000) for n in args.sizes.split(',')):P.error('--sizes must contain 10000 and/or 100000')
if not 3<=args.repeats<=21:P.error('--repeats must be between 3 and 21')
args.out.parent.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(args.source));from radar import core
from radar.filtering import contextual_listing
CORE_ROOT=core.ROOT;REAL_DB=core.db;NOW=datetime(2026,10,3,12,tzinfo=core.TZ)
core.now=lambda:NOW
SOURCE={}
for name in ['radar/core.py','radar/filtering.py','radar/api.py']:
 b=(args.source/name).read_bytes();SOURCE[name]={'git_blob_sha1':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),'sha256':hashlib.sha256(b).hexdigest()}
main_marker='SELECT e.*,COALESCE(p.favorite,0) favorite'
base_pred='COALESCE(p.favorite,0)<>0'
semi_pred="COALESCE(p.favorite,0)<>0 AND e.id IN (SELECT event_id FROM preferences WHERE favorite<>0)"
variant='baseline';plan=None;query_sql=None;query_params=None
class Proxy:
 def __init__(self,c):self.c=c
 def execute(self,sql,params=()):
  global plan,query_sql,query_params
  if sql.startswith(main_marker):
   # Reconstruct the prior SQL predicate while sharing all current Python semantics.
   sql=sql.replace(' AND e.id IN (SELECT event_id FROM preferences WHERE favorite<>0)', '')
   if variant=='bare_predicate':sql=sql.replace(base_pred,'p.favorite<>0')
   elif variant.startswith('semijoin'):sql=sql.replace(base_pred,semi_pred)
   if plan is None:
    plan=[list(r) for r in self.c.execute('EXPLAIN QUERY PLAN '+sql,params)]
    query_sql=sql;query_params=list(params)
  return self.c.execute(sql,params)
 def __getattr__(self,k):return getattr(self.c,k)
@contextlib.contextmanager
def proxied_db():
 with REAL_DB() as c:yield Proxy(c)
core.db=proxied_db

def rows(n,density):
 event_rows=[];pref_rows=[];link_rows=[];oracle=set();favorite_ids=[]
 # Exactly 100 marked favorites at either scale; 10% of them are hidden.
 stride=n//100
 favorites_map={k*stride+(k%7):k for k in range(100)}
 for i in range(n):
  eid=f'synthetic-{i:06d}';fav=i in favorites_map;hidden=fav and favorites_map[i]%10==0
  start=NOW+timedelta(days=(i%61)-30,hours=i%12);end=start+timedelta(hours=2)
  all_day=int(i%5==0);status='scheduled'
  if all_day:start=start.replace(hour=0,minute=0);end=start+timedelta(days=1 if i%3 else 20)
  if i%17==0:start=None;end=None;status='needs_review'
  if i%19==0:status='cancelled'
  # Valid noncanonical timezone, minute-only, naive and missing all-day ends.
  start_s=start.isoformat() if start else None;end_s=end.isoformat() if end else None
  if start and i%7==0:start_s=start.astimezone(timezone.utc).isoformat();end_s=end.astimezone(timezone.utc).isoformat()
  if start and i%11==0:start_s=start.replace(tzinfo=None).isoformat(timespec='minutes');end_s=None
  if all_day and i%13==0:end_s=None
  topics='["展览文化"]' if i%3==0 else '["硬件创客"]'
  details=json.dumps({'attendance':['online','offline','hybrid'][i%3],'cached_images':{'https://bad.example/img.png':'/private/secret'},'images':['https://bad.example/img.png']})
  url='https://example.invalid/event/'+eid
  event_rows.append((eid,'Synthetic '+str(i),start_s,end_s,all_day,status,'Synthetic Hall','南山' if i%2 else '福田','Synthetic Org','Synthetic summary',topics,'high' if i%3 else 'normal','unknown',NOW.isoformat(),url,'ConferenceEvent' if i%3 else 'ExhibitionEvent','source',details,int(i%2==0)))
  link_rows.append((eid,'synthetic',url))
  if fav or density=='dense' or i%20==0:
   # NULL and zero are intentionally present alongside both signs of nonzero.
   favorite=(1 if favorites_map[i]%2 else -1) if fav else (None if i%2 else 0)
   pref_rows.append((eid,favorite,int(hidden),'' if i%3 else 'want','[]',NOW.isoformat() if i%4 else None,1))
  if fav:favorite_ids.append(eid)
  if fav and not hidden:oracle.add(eid)
 return event_rows,pref_rows,link_rows,oracle,favorite_ids

def seed(n,density,folder):
 core.ROOT=folder;(folder/'sources.json').write_text('[{"id":"synthetic","name":"Synthetic source","url":"https://example.invalid"}]')
 (folder/'dedupe_aliases.json').write_text('[]');core.init()
 ev,pr,li,oracle,fids=rows(n,density)
 with REAL_DB() as c:
  c.executemany('INSERT INTO events(id,title,start_at,end_at,all_day,status,location,district,organizer,summary,topics,priority,commercial,last_seen,url,event_type,event_type_state,details,cost_free) VALUES('+','.join('?'*19)+')',ev)
  c.executemany('INSERT INTO preferences(event_id,favorite,hidden,feedback,feedback_tags,viewed_at,revision) VALUES(?,?,?,?,?,?,?)',pr)
  c.executemany('INSERT INTO event_sources(event_id,source_id,url) VALUES(?,?,?)',li)
 return oracle,fids,len(pr)

def timed(fn,repeats):
 fn();samples=[]
 for _ in range(repeats):
  t=time.perf_counter();value=fn();samples.append((time.perf_counter()-t)*1000)
 return {'median_ms':statistics.median(samples),'min_ms':min(samples),'max_ms':max(samples),'samples_ms':samples}

def query_raw():
 with REAL_DB() as c:return c.execute(query_sql,query_params).fetchall()

def digest(rows):return hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

report={'source':SOURCE,'runtime':{'python':sys.version,'sqlite':sqlite3.sqlite_version,'platform':platform.platform()},'method':str(args.repeats)+' repeated warm connection-per-call reads; no ANALYZE by default, exact repository schema; disposable synthetic data; same full query result and same contextual facets required; each configuration first warmed once','cases':[]}
for n in map(int,args.sizes.split(',')):
 for density in ['sparse','dense']:
  with tempfile.TemporaryDirectory(prefix='events-favorites-audit-') as td:
   folder=Path(td);oracle,fids,prefs=seed(n,density,folder)
   expected=None;case={'n_events':n,'n_preferences':prefs,'density':density,'favorite_count':100,'visible_favorites':len(oracle),'variants':{},'correctness':[]}
   for variant in ['baseline','bare_predicate','semijoin_no_index','semijoin_partial_index']:
    with REAL_DB() as c:
     c.execute('DROP INDEX IF EXISTS idx_preferences_favorite_nonzero')
     if variant=='semijoin_partial_index':c.execute('CREATE INDEX idx_preferences_favorite_nonzero ON preferences(event_id) WHERE favorite<>0')
    plan=None;actual=core.events(period='saved',favorites=True)
    assert {e['id'] for e in actual}==oracle
    assert all(e['details']['cached_images']=={} for e in actual)
    if expected is None:expected=actual
    else:assert actual==expected
    raw_time=timed(query_raw,args.repeats)
    total_time=timed(lambda:core.events(period='saved',favorites=True),args.repeats)
    case['variants'][variant]={'query_plan':plan,'raw_sql':raw_time,'full_core_events':total_time,'result_digest':digest(actual)}
   # Include full metadata, ranking, aliases/topic normalization, sources and facets.
   # The existing correct implementation is the semantic oracle for these cases.
   cases=[{}, {'sort':'desc'},{'include_hidden':True},{'period':'upcoming'}, {'period':'past'}, {'period':'review'},
          {'period':'week'},{'period':'weekend'},
          {'period':'calendar','range_start':'2026-10-01T00:00:00+08:00','range_end':'2026-10-31T00:00:00+08:00'},
          {'attendance':'online'}, {'attendance':'offline'}, {'free':True}, {'feedback':'any'}, {'feedback':'none'},
          {'viewed':'seen'}, {'viewed':'unseen'}, {'query':'SYNTHETIC'}, {'districts':['南山']}, {'topics_filter':['文化艺术']}]
   for opts in cases:
    opts={'period':'saved','favorites':True,**opts}
    variant='baseline';before=core.events(**opts)
    variant='semijoin_partial_index';after=core.events(**opts)
    assert before==after,opts
    for facet_opts in [{},{'event_types':['ConferenceEvent'],'topics':['硬件创客'],'districts':['南山'],'hide_long':True,'limit':7,'offset':7},{'type_none':True},{'topic_none':True},{'district_none':True}]:
     assert contextual_listing(before,**facet_opts)==contextual_listing(after,**facet_opts)
    case['correctness'].append({'options':opts,'count':len(before),'result_digest':digest(before)})
   # A post-query favorite change is visible immediately; no cached totals.
   new_id='synthetic-000001'
   with REAL_DB() as c:c.execute('INSERT INTO preferences(event_id,favorite) VALUES(?,1) ON CONFLICT(event_id) DO UPDATE SET favorite=1',(new_id,))
   variant='baseline';before=core.events(period='saved',favorites=True)
   variant='semijoin_partial_index';after=core.events(period='saved',favorites=True)
   assert before==after and new_id in {e['id'] for e in after}
   case['post_mutation_count']=len(after)
   # Plan+speed after standard SQLite statistics collection, on same data.
   with REAL_DB() as c:c.execute('ANALYZE')
   case['analyzed_variants']={}
   for variant in ['baseline','bare_predicate','semijoin_partial_index']:
    plan=None;actual=core.events(period='saved',favorites=True)
    assert actual==after
    case['analyzed_variants'][variant]={'query_plan':plan,'full_core_events':timed(lambda:core.events(period='saved',favorites=True),args.repeats)}
   report['cases'].append(case)
   print(json.dumps({'n':n,'density':density,'core_ms':{k:round(v['full_core_events']['median_ms'],3) for k,v in case['variants'].items()},'raw_ms':{k:round(v['raw_sql']['median_ms'],3) for k,v in case['variants'].items()},'equivalence_cases':len(cases)},ensure_ascii=False),flush=True)
   args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
core.ROOT=CORE_ROOT;core.db=REAL_DB
print('All assertions passed; report:',args.out)
