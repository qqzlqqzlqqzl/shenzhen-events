"""Repair only explicit retained source fields; no network or external model."""
import argparse,contextlib,fcntl,json,pathlib,sqlite3,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from radar.source_fields import event_patch
from import_reviewed_details import signature

def run(db,audit,apply=False):
 out=pathlib.Path(audit);out.mkdir(parents=True,exist_ok=True);report={'apply':apply,'changed':[],'fields':{}}
 with contextlib.ExitStack() as stack:
  for name in ('collect.lock','analyze.lock'):
   h=stack.enter_context((pathlib.Path(db).parent/name).open('a'));fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
  c=sqlite3.connect(db);c.row_factory=sqlite3.Row;stack.callback(c.close)
  if apply:
   backup=out/'before.sqlite3';assert not backup.exists();bc=sqlite3.connect(backup);c.backup(bc);bc.close()
  c.execute('BEGIN IMMEDIATE')
  try:
   protected={t:signature(c,t) for t in ('raw_items','event_sources','preferences','budget')}
   for row in c.execute("SELECT * FROM events WHERE status!='not_event'").fetchall():
    row=dict(row);sources={x[0] for x in c.execute('SELECT source_id FROM event_sources WHERE event_id=?',(row['id'],))};patch=event_patch(row,sources)
    if not patch:continue
    cols=list(patch);c.execute('UPDATE events SET '+','.join(k+'=?' for k in cols)+' WHERE id=?',[patch[k] for k in cols]+[row['id']]);after=dict(c.execute('SELECT * FROM events WHERE id=?',(row['id'],)).fetchone());assert all(after[k]==v for k,v in row.items() if k not in patch)
    report['changed'].append(row['id'])
    for k in cols:report['fields'][k]=report['fields'].get(k,0)+1
   assert all(signature(c,t)==v for t,v in protected.items());assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok';assert not c.execute('PRAGMA foreign_key_check').fetchall()
   report['protected_unchanged']=True
   if apply:c.commit()
   else:c.rollback()
  except BaseException:c.rollback();raise
 (out/('apply.json' if apply else 'dry-run.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2));return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--audit',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args();print(json.dumps(run(a.db,a.audit,a.apply),ensure_ascii=False))
