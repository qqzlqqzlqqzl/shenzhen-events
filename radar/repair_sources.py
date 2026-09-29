"""Bounded, idempotent repair of confirmed duplicate search records. Dry-run by default."""
import argparse,json,sqlite3
from . import core,source_identity as identity

def repair(apply=False):
    with core.db() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM raw_items WHERE source_id IN ('sogou-discovery','wechat-chaihuo') ORDER BY id")]
        groups=[]
        for row in rows:
            e=json.loads(row['payload'])
            if not identity.is_search({'id':row['source_id']},e):continue
            group=next((g for g in groups if g[0]['source_id']==row['source_id'] and all(identity.compatible(r,e,row['body']) for r in g)),None)
            if group is None:groups.append([row])
            else:group.append(row)
        groups=[g for g in groups if len(g)>1];report={'groups':len(groups),'duplicate_raw_rows':sum(len(g)-1 for g in groups),'applied':apply}
        if not apply or not groups:return report
        for group in groups:
            keep=max(group,key=lambda r:(r['analysis_state']=='done',r['collected_at'],r['id']))
            links=[dict(x) for r in group for x in c.execute('SELECT event_id FROM event_sources WHERE raw_id=?',(r['id'],))]
            ids=sorted({r['event_id'] for r in links})
            if not ids:continue
            events=[dict(c.execute('SELECT * FROM events WHERE id=?',(eid,)).fetchone()) for eid in ids]
            winner=min(events,key=lambda e:(e['origin_priority'],e['first_seen'],e['id']))['id']
            for eid in ids:
                if eid==winner:continue
                pref=c.execute('SELECT favorite,hidden FROM preferences WHERE event_id=?',(eid,)).fetchone()
                if pref:c.execute('INSERT INTO preferences(event_id,favorite,hidden) VALUES(?,?,?) ON CONFLICT(event_id) DO UPDATE SET favorite=MAX(favorite,excluded.favorite),hidden=MAX(hidden,excluded.hidden)',(winner,pref['favorite'],pref['hidden']))
                c.execute('UPDATE event_sources SET event_id=? WHERE event_id=?',(winner,eid));c.execute('DELETE FROM events WHERE id=?',(eid,))
            for row in group:
                if row['id']==keep['id']:continue
                c.execute('DELETE FROM event_sources WHERE raw_id=?',(row['id'],));c.execute('DELETE FROM raw_items WHERE id=?',(row['id'],))
            urls={r['url'] for r in group}
            current=c.execute('SELECT url FROM events WHERE id=?',(winner,)).fetchone()['url']
            if current in urls:c.execute('UPDATE events SET url=? WHERE id=?',(keep['url'],winner))
            e=json.loads(keep['payload']);h=identity.content_hash({'id':keep['source_id']},e,keep['body'])
            c.execute('UPDATE raw_items SET content_hash=? WHERE id=?',(h,keep['id']))
        return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if args.apply:
        # One snapshot retained for this review, not an unbounded backup set.
        path=core.ROOT/'.private/interaction-review-recovery.sqlite3'
        if not path.exists():
            with core.db() as source:
                target=sqlite3.connect(path);source.backup(target);target.close();path.chmod(0o600)
    print(json.dumps(repair(args.apply),ensure_ascii=False))
