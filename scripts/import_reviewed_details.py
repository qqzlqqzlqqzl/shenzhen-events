"""Root-reviewed bounded updates; backup + lock + compare-and-swap; no network."""
import argparse,contextlib,fcntl,hashlib,json,pathlib,sqlite3

def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def signature(c,t):
 assert t in {'preferences','budget','raw_items','event_sources'}
 return hashlib.sha256(canonical(sorted((dict(r) for r in c.execute('SELECT * FROM '+t)),key=canonical)).encode()).hexdigest()
def run(db,updates,audit,apply=False):
 entries=json.loads(pathlib.Path(updates).read_text())['items'];assert len({x['id'] for x in entries})==len(entries)
 allowed={'topics','status','ai_state','priority','commercial','organizer','reason','details'}
 assert all(set(x['patch'])<=allowed and x['patch'] for x in entries)
 report={'mode':'apply' if apply else 'dry-run','changed':[],'already_applied':[],'stale':[]};out=pathlib.Path(audit);out.mkdir(parents=True,exist_ok=True)
 with contextlib.ExitStack() as stack:
  for name in ('collect.lock','analyze.lock'):
   h=stack.enter_context((pathlib.Path(db).parent/name).open('a'));fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
  c=sqlite3.connect(db);c.row_factory=sqlite3.Row;stack.callback(c.close)
  assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  if apply:
   backup=out/'before.sqlite3';assert not backup.exists()
   bc=sqlite3.connect(backup);c.backup(bc);bc.close()
  c.execute('BEGIN IMMEDIATE')
  try:
   sig={t:signature(c,t) for t in ('preferences','budget','raw_items','event_sources')}
   for item in entries:
    row=c.execute('SELECT * FROM events WHERE id=?',(item['id'],)).fetchone();row=dict(row) if row else None;p=item['patch']
    if row and all(row.get(k)==v for k,v in p.items()):report['already_applied'].append(item['id']);continue
    if not row or any(row.get(k)!=v for k,v in item['guard'].items()):report['stale'].append(item['id']);continue
    fields=list(p);c.execute('UPDATE events SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',[p[k] for k in fields]+[item['id']])
    after=dict(c.execute('SELECT * FROM events WHERE id=?',(item['id'],)).fetchone())
    assert all(after[k]==v for k,v in row.items() if k not in p)
    report['changed'].append(item['id'])
   assert all(signature(c,t)==v for t,v in sig.items())
   assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not c.execute('PRAGMA foreign_key_check').fetchall()
   report['protected_tables_unchanged']=True
   if apply:c.commit()
   else:c.rollback()
  except BaseException:c.rollback();raise
 (out/('apply.json' if apply else 'dry-run.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2));return report
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--db',required=True);a.add_argument('--updates',required=True);a.add_argument('--audit',required=True);a.add_argument('--apply',action='store_true');x=a.parse_args();print(json.dumps(run(x.db,x.updates,x.audit,x.apply),ensure_ascii=False))
