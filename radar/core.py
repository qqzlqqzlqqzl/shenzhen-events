"""Event normalization and conservative, source-aware deduplication."""
from __future__ import annotations
import hashlib, json, os, re, sqlite3, unicodedata
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from rapidfuzz.fuzz import ratio
from . import source_identity
ROOT = Path(os.getenv('RADAR_ROOT', Path(__file__).resolve().parents[1]))
TZ = ZoneInfo('Asia/Shanghai')
EVENT_TYPES = {
    'Event':'其他活动',
    'BusinessEvent':'商务活动',
    'ChildrensEvent':'儿童活动',
    'ComedyEvent':'喜剧 / 脱口秀',
    'ConferenceEvent':'会议 / 大会',
    'CourseInstance':'课程 / 培训',
    'DanceEvent':'舞蹈',
    'DeliveryEvent':'交付事件',
    'EducationEvent':'教育活动',
    'ExhibitionEvent':'展览 / 博览',
    'Festival':'节庆',
    'FoodEvent':'美食',
    'Hackathon':'黑客松',
    'LiteraryEvent':'文学 / 读书',
    'MusicEvent':'音乐 / 演唱会',
    'PerformingArtsEvent':'表演艺术',
    'PublicationEvent':'发布活动',
    'SaleEvent':'促销 / 销售',
    'ScreeningEvent':'放映 / 电影',
    'SocialEvent':'社交 / 聚会',
    'SportsEvent':'体育 / 运动',
    'TheaterEvent':'戏剧 / 话剧',
    'VisualArtsEvent':'视觉艺术',
}
TOPICS = {'机器人': ['机器人','机械臂','ros2','robot','具身'], '硬件创客':['创客','maker','硬件','嵌入式','esp32','3d打印','3d 打印','电机','芯片'], 'AI与开源':['ai','人工智能','开源','开发者','linux','rust','python','hackathon','gosim','agent','云计算'], '产品与创业':['创业','产品','出海','电商','增长','一人公司'], '汽车':['汽车','赛车','车展'], '文化艺术':['艺术','博物馆','非遗','文化','美术','设计'], '户外生活':['公园','徒步','户外','运动','马拉松','游园','亲子']}
CATEGORIES = TOPICS
DISTRICTS = ['南山','福田','宝安','龙岗','龙华','罗湖','盐田','光明','坪山','大鹏','深汕']
VERSION = 'radar-v1.1'
LONG_RUNNING_DAYS = 14
def now(): return datetime.now(TZ)
def stamp(): return now().isoformat(timespec='seconds')
def config():
    p=ROOT/'.private/settings.json'
    return json.loads(p.read_text()) if p.exists() else {}
def clean(s): return re.sub(r'\s+', ' ', str(s or '')).strip()
def norm(s): return re.sub(r'[^\w\u3400-\u9fff]', '', unicodedata.normalize('NFKC', clean(s)).casefold())
def canon_url(u):
    try:
        p=urlsplit(clean(u));host=(p.hostname or '').lower()
        if p.scheme not in ('https','http') or not host or p.username or p.password:return ''
        qs=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if not k.startswith('utm_') and k not in ('from','spm','chksm','scene','clicktime','enterid')]
        return urlunsplit(('https' if p.scheme=='https' or host.endswith('bendibao.com') else 'http',p.netloc,p.path,urlencode(qs),''))
    except ValueError:return ''
def iso(v):
    if isinstance(v, datetime): return (v.replace(tzinfo=TZ) if v.tzinfo is None else v.astimezone(TZ)).isoformat(timespec='seconds')
    if isinstance(v,date):return datetime.combine(v,datetime.min.time(),TZ).isoformat(timespec='seconds')
    s=clean(v)
    if not s:return None
    try:return iso(datetime.fromisoformat(s.replace('Z','+00:00')))
    except ValueError:return None

def date_range(text):
    """Parse explicitly dated event-time fields, NEVER an article publication date."""
    text=clean(text);matches=list(re.finditer(r'(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?',text))
    if not matches:return None,None
    try:
        y,m,d=map(int,matches[0].groups());start=date(y,m,d);last=start
        if len(matches)>1:last=date(*map(int,matches[1].groups()))
        else:
            r=re.match(r'\s*[—–~至\-]\s*(?:(\d{1,2})月)?(\d{1,2})日',text[matches[0].end():])
            if r:last=date(y,int(r[1] or m),int(r[2]))
        if last<start:return None,None
        return iso(start),iso(last+timedelta(days=1))
    except (ValueError,OverflowError):return None,None

def rules(title,summary=''):
    s=(title+' '+summary).casefold();tags=[k for k,words in TOPICS.items() if any(w.casefold() in s for w in words)]
    commercial='high' if any(w in s for w in ['招生公开课','财富自由','赚钱秘籍','招商加盟','获客','流量变现','引流','成交秘籍']) else 'unknown'
    priority='high' if any(x in tags for x in ['机器人','硬件创客','AI与开源','汽车']) else ('medium' if '产品与创业' in tags else 'normal')
    if commercial=='high':priority='normal'
    return {'topics':tags or ['其他'],'priority':priority,'commercial':commercial,'reason':('涉及'+ '、'.join(tags[:3])+'，可结合原活动说明判断是否参加。') if tags else '保留在全部活动中，供你探索其他兴趣。'}

def canonical_topic(value):
    return '文化艺术' if value=='展览文化' else value

def normalize_event(e):
    e=dict(e);e['title']=clean(e.get('title'))[:220];e['url']=canon_url(e.get('url',''))
    if not e['title'] or not e['url']:return None
    e['start_at']=iso(e.get('start_at'));e['end_at']=iso(e.get('end_at'))
    if e['end_at'] and e['start_at'] and e['end_at']<e['start_at']:e['end_at']=None
    e['location']=clean(e.get('location'))[:250];e['summary']=clean(e.get('summary'))[:3500]
    e['district']=next((d for d in DISTRICTS if d in e['location']),'待确认')
    e['organizer']=clean(e.get('organizer'))[:200]
    e['cost_text']=clean(e.get('cost_text'))[:100] or '费用未注明';e['cost_free']=e['cost_text'] in ('免费','0元','免费参加')
    e['all_day']=bool(e.get('all_day'))
    topics=e.get('topics') or rules(e['title'],e['summary'])['topics']
    e['topics']=[canonical_topic(x) for x in topics if canonical_topic(x) in TOPICS or x=='其他']
    if not e['topics']:e['topics']=['其他']
    raw_type=clean(e.get('event_type'))
    e['event_type']=raw_type if raw_type in EVENT_TYPES else 'Event'
    e['event_type_state']='source' if e['event_type']!='Event' else 'pending'
    e['city']=e.get('city','深圳');e['status']=e.get('status','scheduled')
    if not e['start_at']:e['status']='needs_review'
    return e

@contextmanager
def db():
    (ROOT/'data').mkdir(exist_ok=True)
    con=sqlite3.connect(ROOT/'data/events.sqlite3',timeout=15);con.row_factory=sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON');con.execute('PRAGMA busy_timeout=15000')
    try:yield con;con.commit()
    except Exception:con.rollback();raise
    finally:con.close()

def init():
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS raw_items(id INTEGER PRIMARY KEY,source_id TEXT NOT NULL,url TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,content_hash TEXT NOT NULL,payload TEXT NOT NULL,collected_at TEXT NOT NULL,analysis_state TEXT NOT NULL DEFAULT 'pending',analysis_version TEXT,ai_result TEXT,UNIQUE(source_id,url));
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,title TEXT,title_norm TEXT,start_at TEXT,end_at TEXT,all_day INTEGER,location TEXT,district TEXT,organizer TEXT,summary TEXT,topics TEXT,priority TEXT,reason TEXT,commercial TEXT,cost_text TEXT,cost_free INTEGER,url TEXT,status TEXT,origin_priority INTEGER DEFAULT 50,first_seen TEXT,last_seen TEXT,ai_state TEXT DEFAULT 'pending');
        CREATE INDEX IF NOT EXISTS idx_events_time ON events(start_at);
        CREATE INDEX IF NOT EXISTS idx_raw_source_title ON raw_items(source_id,title);
        CREATE TABLE IF NOT EXISTS event_sources(event_id TEXT REFERENCES events(id) ON DELETE CASCADE,source_id TEXT,url TEXT,raw_id INTEGER,seen_at TEXT,PRIMARY KEY(source_id,url));
        CREATE TABLE IF NOT EXISTS preferences(event_id TEXT PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,favorite INTEGER DEFAULT 0,hidden INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS source_health(id TEXT PRIMARY KEY,name TEXT,url TEXT,status TEXT DEFAULT 'pending',message TEXT DEFAULT '',last_attempt TEXT,last_success TEXT,raw_count INTEGER DEFAULT 0,event_count INTEGER DEFAULT 0,failure_count INTEGER DEFAULT 0,next_attempt TEXT);
        CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,kind TEXT,started_at TEXT,finished_at TEXT,status TEXT,details TEXT);
        CREATE TABLE IF NOT EXISTS budget(day TEXT PRIMARY KEY,calls INTEGER DEFAULT 0,tokens INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS candidates(name TEXT PRIMARY KEY,query TEXT,url TEXT,hits INTEGER DEFAULT 1,last_seen TEXT);
        ''')
        if 'coverage' not in {r[1] for r in c.execute('PRAGMA table_info(source_health)')}:
            c.execute("ALTER TABLE source_health ADD COLUMN coverage TEXT NOT NULL DEFAULT '{}'")
        event_cols={r[1] for r in c.execute('PRAGMA table_info(events)')}
        if 'event_type' not in event_cols:c.execute("ALTER TABLE events ADD COLUMN event_type TEXT NOT NULL DEFAULT 'Event'")
        if 'event_type_state' not in event_cols:c.execute("ALTER TABLE events ADD COLUMN event_type_state TEXT NOT NULL DEFAULT 'pending'")
        c.execute('CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)')
        for row in c.execute('SELECT id,topics FROM events'):
            try:vals=json.loads(row['topics'] or '[]')
            except ValueError:vals=[]
            mapped=['文化艺术' if x=='展览文化' else x for x in vals]
            if mapped!=vals:c.execute('UPDATE events SET topics=? WHERE id=?',(json.dumps(mapped,ensure_ascii=False),row['id']))
        c.executescript("""
        CREATE TABLE IF NOT EXISTS detail_cache(source_id TEXT,url TEXT,fingerprint TEXT,payload TEXT,status TEXT,checked_at TEXT,next_attempt TEXT,PRIMARY KEY(source_id,url));
        CREATE TABLE IF NOT EXISTS source_jobs(id TEXT PRIMARY KEY,source_id TEXT,state TEXT,requested_at TEXT,updated_at TEXT,message TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_source_active_job ON source_jobs(source_id) WHERE state IN ('queued','running');
        """)
        for s in json.loads((ROOT/'sources.json').read_text()):c.execute('INSERT INTO source_health(id,name,url) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,url=excluded.url',(s['id'],s['name'],s.get('public_url',s['url'])))

def dedupe_aliases():
    p=ROOT/'dedupe_aliases.json'
    if not p.exists():return []
    try:return json.loads(p.read_text())
    except (ValueError,OSError):return []

def alias_for(e):
    if not e.get('start_at'):return None
    url=canon_url(e.get('url',''));day=e['start_at'][:10]
    for a in dedupe_aliases():
        if a.get('date')==day and url in {canon_url(x) for x in a.get('urls',[])}:return a
    return None

def reconcile_aliases():
    merged=[]
    with db() as c:
        for a in dedupe_aliases():
            urls=[canon_url(x) for x in a.get('urls',[]) if canon_url(x)]
            if not urls:continue
            qs=','.join('?' for _ in urls)
            ids=[r['event_id'] for r in c.execute(f'SELECT DISTINCT event_id FROM event_sources WHERE url IN ({qs})',urls)]
            if len(ids)<2:continue
            rows=[dict(c.execute('SELECT * FROM events WHERE id=?',(eid,)).fetchone()) for eid in ids]
            rows=[r for r in rows if r and (not a.get('date') or (r.get('start_at') or '')[:10]==a['date'])]
            if len(rows)<2:continue
            rows.sort(key=lambda r:(r.get('origin_priority',50),r.get('first_seen',''),r['id']));winner=rows[0]['id']
            for loser in rows[1:]:
                pref=c.execute('SELECT favorite,hidden FROM preferences WHERE event_id=?',(loser['id'],)).fetchone()
                if pref:c.execute('INSERT INTO preferences(event_id,favorite,hidden) VALUES(?,?,?) ON CONFLICT(event_id) DO UPDATE SET favorite=MAX(favorite,excluded.favorite),hidden=MAX(hidden,excluded.hidden)',(winner,pref['favorite'],pref['hidden']))
                c.execute('UPDATE event_sources SET event_id=? WHERE event_id=?',(winner,loser['id']))
                c.execute('DELETE FROM events WHERE id=?',(loser['id'],));merged.append((winner,loser['id'],a['id']))
    return merged

def is_duplicate(a,b):
    if not a.get('start_at') or not b.get('start_at') or a['start_at'][:10]!=b['start_at'][:10]:return False
    year=a['start_at'][:4];an,bn=norm(a['title']).replace(year,''),norm(b['title']).replace(year,'');la,lb=norm(a.get('location','')),norm(b.get('location',''))
    da=next((d for d in DISTRICTS if d in la),None);db_=next((d for d in DISTRICTS if d in lb),None)
    if da and db_ and da!=db_:return False
    if min(len(la),len(lb))>5 and la not in lb and lb not in la and ratio(la,lb)<80:return False
    if not a.get('all_day') and not b.get('all_day') and a['start_at'][11:16]!=b['start_at'][11:16]:return False
    return an==bn or (min(len(an),len(bn))>=10 and ratio(an,bn)>=93)

def ingest(source,e,body=None):
    e=normalize_event(e)
    if not e:return False
    body=clean(body or e['summary'])[:14000];payload=json.dumps(e,ensure_ascii=False,sort_keys=True)
    h=source_identity.content_hash(source,e,body);ts=stamp()
    with db() as c:
        old=source_identity.find_existing(c,source,e,body);changed=not old
        if old:
            prior=json.loads(old['payload'])
            if 'event_type' not in prior and 'event_type_state' not in prior:
                # Taxonomy and rule-derived topics were added/renamed by this upgrade,
                # not by the source. Upgrade its raw payload without repeating AI work.
                derived={'event_type','event_type_state','topics'}
                previous={k:v for k,v in prior.items() if k not in derived}
                incoming={k:v for k,v in e.items() if k not in derived}
                changed=source_identity.content_hash(source,previous,old['body'])!=source_identity.content_hash(source,incoming,body)
            else:changed=source_identity.content_hash(source,prior,old['body'])!=h
        if old:source_identity.refresh_url(c,old,e['url'])
        if old:
            c.execute('UPDATE raw_items SET title=?,body=?,payload=?,collected_at=?,content_hash=?,analysis_state=CASE WHEN ? THEN \'pending\' ELSE analysis_state END WHERE id=?',(e['title'],body,payload,ts,h,int(changed),old['id']));rid=old['id']
        else:rid=c.execute('INSERT INTO raw_items(source_id,url,title,body,content_hash,payload,collected_at) VALUES(?,?,?,?,?,?,?)',(source['id'],e['url'],e['title'],body,h,payload,ts)).lastrowid
        link=c.execute('SELECT event_id FROM event_sources WHERE source_id=? AND url=?',(source['id'],e['url'])).fetchone()
        if link:eid=link['event_id']
        else:
            eid=None;alias=alias_for(e)
            if alias:
                urls=[canon_url(x) for x in alias.get('urls',[]) if canon_url(x)]
                if urls:
                    qs=','.join('?' for _ in urls);row=c.execute(f'SELECT event_id FROM event_sources WHERE url IN ({qs}) LIMIT 1',urls).fetchone()
                    eid=row['event_id'] if row else hashlib.sha256(('alias|'+alias['id']).encode()).hexdigest()[:20]
            if not eid and e['start_at']:
                for row in c.execute('SELECT * FROM events WHERE substr(start_at,1,10)=?',(e['start_at'][:10],)):
                    if is_duplicate(e,dict(row)):eid=row['id'];break
            eid=eid or hashlib.sha256((source['id']+'|'+e['url']).encode()).hexdigest()[:20]
        prev=c.execute('SELECT * FROM events WHERE id=?',(eid,)).fetchone();rank=source.get('priority',50);r=rules(e['title'],e['summary'])
        if prev and prev['location']==e['location'] and e['district']=='待确认':e['district']=prev['district']
        if prev and e['event_type']=='Event' and prev['event_type_state'] in ('source','ai'):
            e['event_type']=prev['event_type'];e['event_type_state']=prev['event_type_state']
        if not prev or (changed and rank<=prev['origin_priority']):
            data={'id':eid,'title':e['title'],'title_norm':norm(e['title']),'start_at':e['start_at'],'end_at':e['end_at'],'all_day':int(e['all_day']),'location':e['location'],'district':e['district'],'organizer':e['organizer'],'summary':e['summary'],'topics':json.dumps(e['topics'],ensure_ascii=False),'event_type':e['event_type'],'event_type_state':e['event_type_state'],'priority':r['priority'],'reason':r['reason'],'commercial':r['commercial'],'cost_text':e['cost_text'],'cost_free':int(e['cost_free']),'url':e['url'],'status':e['status'],'origin_priority':rank,'first_seen':prev['first_seen'] if prev else ts,'last_seen':ts,'ai_state':'pending'}
            keys=list(data);c.execute(f"INSERT INTO events ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)}) ON CONFLICT(id) DO UPDATE SET "+','.join(f'{k}=excluded.{k}' for k in keys if k not in ('id','first_seen')),tuple(data.values()))
        elif e['event_type_state']=='source' and rank<=prev['origin_priority']:
            # Newly extracted source typing must not reset an unchanged event's
            # AI-established dates, location, summary, or analysis state.
            c.execute('UPDATE events SET event_type=?,event_type_state=?,last_seen=? WHERE id=?',(e['event_type'],'source',ts,eid))
        else:c.execute('UPDATE events SET last_seen=? WHERE id=?',(ts,eid))
        c.execute('INSERT INTO event_sources VALUES(?,?,?,?,?) ON CONFLICT(source_id,url) DO UPDATE SET event_id=excluded.event_id,raw_id=excluded.raw_id,seen_at=excluded.seen_at',(eid,source['id'],e['url'],rid,ts))
    return changed

def span_days(e):
    if not e.get('start_at') or not e.get('end_at'):return 0.0
    try:return max(0.0,(datetime.fromisoformat(e['end_at'])-datetime.fromisoformat(e['start_at'])).total_seconds()/86400)
    except ValueError:return 0.0

def events(query='',period='upcoming',district='',tag='',free=False,recommended=False,favorites=False,include_hidden=False,range_start=None,range_end=None,event_id=None,hide_long=False,sort='asc',event_types=None,topics_filter=None):
    topics_filter=[canonical_topic(x) for x in topics_filter or []]
    if tag:topics_filter.append(canonical_topic(tag))
    current=now();day=current.date();from_dt=current;to_dt=None
    if sort not in ('asc','desc'):raise ValueError('invalid sort')
    if period=='week':to_dt=datetime.combine(day+timedelta(days=7-day.weekday()),datetime.min.time(),TZ)
    if period=='weekend':
        saturday=day+timedelta(days=(5-day.weekday())%7) if day.weekday()<5 else day-timedelta(days=day.weekday()-5)
        from_dt=max(current,datetime.combine(saturday,datetime.min.time(),TZ));to_dt=datetime.combine(saturday+timedelta(days=2),datetime.min.time(),TZ)
    with db() as c:
        rows=[dict(r) for r in c.execute('SELECT e.*,COALESCE(p.favorite,0) favorite,COALESCE(p.hidden,0) hidden FROM events e LEFT JOIN preferences p ON e.id=p.event_id ORDER BY e.start_at,e.id LIMIT 10000')];links={}
        for r in c.execute('SELECT es.event_id,es.url,sh.name,es.source_id FROM event_sources es JOIN source_health sh ON sh.id=es.source_id'):links.setdefault(r['event_id'],[]).append(dict(r))
    out=[]
    for e in rows:
        if event_id and e['id']!=event_id:continue
        if not include_hidden and e['hidden']:continue
        days=span_days(e);e['span_days']=round(days,1);e['long_running']=days>=LONG_RUNNING_DAYS;e['display_at']=e.get('start_at');e['period_label']=''
        if hide_long and e['long_running'] and period!='record':continue
        if period=='review':
            if e['status']!='needs_review':continue
        elif period in ('saved','record'):
            pass
        elif period=='calendar':
            if not e['start_at'] or e['status']!='scheduled':continue
            end=e['end_at']
            if not end or end<=e['start_at'] or (e['all_day'] and end[:10]<=e['start_at'][:10]):
                start=datetime.fromisoformat(e['start_at'])
                # A known all-day date with no usable end occupies that date only.
                end=iso(datetime.combine(start.date()+timedelta(days=1),datetime.min.time(),TZ) if e['all_day'] else start+timedelta(seconds=1))
            if end<=range_start or e['start_at']>=range_end:continue
        elif period=='past':
            if not e['start_at'] or (e['end_at'] or e['start_at'])>=current.isoformat():continue
        else:
            if not e['start_at'] or e['status'] in ('cancelled','needs_review','not_event'):continue
            end=e['end_at'] or iso(datetime.fromisoformat(e['start_at'])+timedelta(hours=3))
            if end<=from_dt.isoformat():continue
            if to_dt and e['start_at']>=to_dt.isoformat():continue
            if e['long_running'] and e['start_at']<from_dt.isoformat():
                e['display_at']=from_dt.isoformat(timespec='seconds')
                e['period_label']='本周末仍开放' if period=='weekend' else ('本周仍开放' if period=='week' else '长期/重复活动')
        e['topics']=['文化艺术' if x=='展览文化' else x for x in json.loads(e['topics'] or '[]')]
        e['event_type']=e.get('event_type') or 'Event';e['event_type_label']='待分类' if e.get('event_type_state')=='pending' else EVENT_TYPES.get(e['event_type'],'其他活动');e['sources']=links.get(e['id'],[])
        if query and query.casefold() not in (e['title']+' '+e['summary']+' '+e['location']+' '+e['organizer']).casefold():continue
        if district and e['district']!=district:continue
        if event_types and (e.get('event_type_state')=='pending' or e['event_type'] not in set(event_types)):continue
        if topics_filter and not set(topics_filter).intersection(e['topics']):continue
        if free and not e['cost_free']:continue
        if recommended and (e['priority'] not in ('high','medium') or e['commercial']=='high'):continue
        if favorites and not e['favorite']:continue
        e['stale']=(current-datetime.fromisoformat(e['last_seen'])).days>=7;out.append(e)
    def key(e):
        value=e.get('display_at') or e.get('start_at')
        return (value is None,value or '',e['id'])
    if sort=='asc':out.sort(key=key)
    else:out.sort(key=lambda e:((e.get('display_at') or e.get('start_at')) is not None,e.get('display_at') or e.get('start_at') or '',e['id']),reverse=True)
    return out
