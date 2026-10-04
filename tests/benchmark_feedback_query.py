"""Opt-in local SQLite measurements; synthetic data and no timing assertions."""
import hashlib,json,sqlite3,statistics,sys,tempfile,time
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from radar import core
from test_feedback_query import NOW, seed, observed

report={'sqlite':sqlite3.sqlite_version,'python':sys.version,'source_head':None,
        'method':'Warm connection-per-call full core.events; five samples; disposable 10k synthetic rows. Legacy reference removes only the candidate predicate. No index, LIMIT or facet changes; no production latency guarantee.', 'scenarios':[]}
import subprocess
report['source_head']=sys.argv[2] if len(sys.argv)>2 else subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
assert len(report['source_head'])==40 and all(c in '0123456789abcdef' for c in report['source_head'])
for density,all_feedback in [('sparse',False),('dense',False),('dense',True)]:
    with tempfile.TemporaryDirectory(prefix='events-feedback-measure-') as temporary,pytest.MonkeyPatch.context() as m:
        folder=Path(temporary);m.setattr(core,'ROOT',folder);m.setattr(core,'now',lambda:NOW)
        (folder/'sources.json').write_text('[{"id":"a","name":"Synthetic A","url":"https://example.invalid"}]')
        core.init();seed(10000,empty=True)
        with core.db() as c:
            c.execute('UPDATE preferences SET hidden=0')
            c.execute("UPDATE preferences SET feedback='interested'"+(" WHERE CAST(substr(event_id,5) AS INTEGER)%100=0" if not all_feedback else ''))
            if density=='sparse':c.execute("DELETE FROM preferences WHERE COALESCE(feedback,'')='' AND CAST(substr(event_id,5) AS INTEGER)%10<>0")
            indexes=[tuple(r) for r in c.execute('SELECT name,sql FROM sqlite_master WHERE type=\'index\' ORDER BY name')]
            counts={table:c.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ['events','preferences','event_sources']}
        case={'density':density,'all_feedback':all_feedback,'counts':counts,'variants':{}}
        reference=None
        for name,legacy in [('legacy',True),('candidate',False)]:
            with pytest.MonkeyPatch.context() as observer:
                queries,hydrated=observed(observer,legacy=legacy)
                result=core.events(period='feedback',feedback='any');warm_ids=len(hydrated);samples=[]
                if reference is None:reference=result
                else:assert result==reference
                for _ in range(5):
                    started=time.perf_counter();assert core.events(period='feedback',feedback='any')==reference;samples.append((time.perf_counter()-started)*1000)
                with core.db() as c:plan=[tuple(r) for r in c.execute('EXPLAIN QUERY PLAN '+queries[0])]
                case['variants'][name]={'median_ms':statistics.median(samples),'samples_ms':samples,'source_ids_hydrated_per_call':warm_ids,'output_count':len(result),'output_sha256':hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest(),'query_plan':plan}
        with core.db() as c:assert indexes==[tuple(r) for r in c.execute('SELECT name,sql FROM sqlite_master WHERE type=\'index\' ORDER BY name')]
        report['scenarios'].append(case)
        print(json.dumps({'density':density,'all_feedback':all_feedback,'variants':case['variants']}),flush=True)
Path(sys.argv[1]).write_text(json.dumps(report,indent=2))
