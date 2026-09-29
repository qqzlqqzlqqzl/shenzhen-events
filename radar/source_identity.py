"""Conservative identity for search-index links whose transport tokens rotate."""
import hashlib,json
from urllib.parse import urlsplit
SEARCH_SOURCES={'sogou-discovery','wechat-chaihuo'}
def is_search(source,e):
    return source['id'] in SEARCH_SOURCES and urlsplit(e.get('url','')).hostname=='weixin.sogou.com'
def compatible(row,e,body):
    prior=json.loads(row['payload'])
    if row['title']!=e['title'] or row['body']!=body:return False
    for key in ('published_at','organizer'):
        a,b=prior.get(key),e.get(key)
        if a and b and a!=b:return False
    return True

def content_hash(source,e,body):
    payload=dict(e)
    if is_search(source,e):payload.pop('url',None)
    return hashlib.sha256((json.dumps(payload,ensure_ascii=False,sort_keys=True)+'\n'+body).encode()).hexdigest()

def find_existing(c,source,e,body):
    row=c.execute('SELECT * FROM raw_items WHERE source_id=? AND url=?',(source['id'],e['url'])).fetchone()
    if row or not is_search(source,e):return row
    rows=c.execute('SELECT * FROM raw_items WHERE source_id=? AND title=? ORDER BY id',(source['id'],e['title'])).fetchall()
    return next((r for r in rows if compatible(r,e,body)),None)

def refresh_url(c,row,url):
    if row['url']==url:return
    c.execute('UPDATE event_sources SET url=? WHERE raw_id=?',(url,row['id']))
    c.execute('UPDATE events SET url=? WHERE url=? AND id IN (SELECT event_id FROM event_sources WHERE raw_id=?)',(url,row['url'],row['id']))
    c.execute('UPDATE raw_items SET url=? WHERE id=?',(url,row['id']))
