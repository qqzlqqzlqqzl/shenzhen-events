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
TOPICS = {'机器人': ['机器人','机械臂','ros2','robot','具身'], '硬件创客':['创客','maker','硬件','嵌入式','esp32','3d打印','3d 打印','电机','芯片'], 'AI与开源':['ai','人工智能','开源','开发者','linux','rust','python','hackathon','gosim','agent','云计算'], '产品与创业':['创业','产品','出海','电商','增长','一人公司'], '汽车':['汽车','赛车','车展'], '文化艺术':['艺术','博物馆','非遗','文化','美术','设计','音乐','演唱会','音乐会','脱口秀','喜剧','话剧','戏剧','舞蹈','芭蕾','电影','放映','读书','文学'], '户外生活':['公园','徒步','户外','运动','马拉松','游园','亲子']}
TOPICS.update({'社交交流':['交友','相亲','社交','桌游','英语角','聚会','networking'],'学习成长':['培训','课程','演讲','领导力','沟通']})
TOPICS['软件开发'] = []  # Explicit source categories only, not broad title keywords.
CATEGORIES = TOPICS
DISTRICTS = ['南山','福田','宝安','龙岗','龙华','罗湖','盐田','光明','坪山','大鹏','深汕']
FEEDBACK_SIGNALS = {
    'interested':'感兴趣',
    'not_interested':'不感兴趣',
    'attended':'已参加',
}
FEEDBACK_TAGS = {
    'time_conflict':'时间不合适',
    'location_inconvenient':'地点不方便',
    'price_issue':'价格原因',
    'topic_like':'主题喜欢',
    'vibe_like':'氛围喜欢',
    'more_like_this':'以后多推',
    'less_like_this':'以后少推',
}
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
    from .source_fields import obvious_type
    if obvious_type(title):return {'topics':['文化艺术'],'priority':'normal','commercial':'unknown','reason':'演出活动，按文化艺术归类；具体内容以原文为准。'}
    narrative=re.split(r'\s*(?:时间|地点|费用|发起)\s*[：:]',summary,maxsplit=1)[0]
    s=(title+' '+narrative).casefold()
    def matches(word):
        word=word.casefold()
        return bool(re.search(r'(?<![a-z0-9])'+re.escape(word)+r'(?![a-z0-9])',s)) if word.isascii() else word in s
    tags=[k for k,words in TOPICS.items() if any(matches(w) for w in words)]
    commercial='high' if any(w in s for w in ['招生公开课','财富自由','赚钱秘籍','招商加盟','获客','流量变现','引流','成交秘籍']) else 'unknown'
    priority='high' if any(x in tags for x in ['机器人','硬件创客','AI与开源','汽车']) else ('medium' if '产品与创业' in tags else 'normal')
    if commercial=='high':priority='normal'
    return {'topics':tags or ['其他'],'priority':priority,'commercial':commercial,'reason':('涉及'+ '、'.join(tags[:3])+'，可结合原活动说明判断是否参加。') if tags else '保留在全部活动中，供你探索其他兴趣。'}

def canonical_topic(value):
    return '文化艺术' if value=='展览文化' else value

CULTURAL_TYPES={'MusicEvent','ComedyEvent','DanceEvent','TheaterEvent','ScreeningEvent','PerformingArtsEvent','LiteraryEvent','VisualArtsEvent'}
def resolved_topics(values,event_type='Event',title='',summary=''):
    values=list(dict.fromkeys(canonical_topic(x) for x in values if canonical_topic(x) in TOPICS or x=='其他'))
    specific=[x for x in values if x!='其他']
    if specific:return specific
    if event_type in CULTURAL_TYPES:return ['文化艺术']
    if event_type=='SportsEvent':return ['户外生活']
    if event_type=='SocialEvent':return ['社交交流']
    if event_type in ('CourseInstance','EducationEvent'):return ['学习成长']
    return rules(title,summary)['topics'] if title or summary else ['其他']

ATTENDANCE_LABELS={'offline':'线下','online':'线上','hybrid':'线上＋线下','unknown':'参加方式待确认'}
def event_attendance(e):
    d=e.get('details') if isinstance(e.get('details'),dict) else {}
    mode=d.get('attendance')
    if mode in ATTENDANCE_LABELS:return mode
    loc=clean(e.get('location')).casefold()
    if loc in ('线上','线上活动','在线','online','virtual','online event'):return 'online'
    return 'offline' if loc and loc not in ('待确认','地点待确认','地点待定') else 'unknown'

def normalize_event(e):
    e=dict(e);e['title']=clean(e.get('title'))[:220];e['url']=canon_url(e.get('url',''))
    if not e['title'] or not e['url']:return None
    e['start_at']=iso(e.get('start_at'));e['end_at']=iso(e.get('end_at'))
    if e['end_at'] and e['start_at'] and e['end_at']<e['start_at']:e['end_at']=None
    e['location']=clean(e.get('location'))[:250];e['summary']=clean(e.get('summary'))[:3500]
    districts={d for d in DISTRICTS if d in e['location']}
    e['district']=next(iter(districts)) if len(districts)==1 and not any(x in e['location'] for x in ('、','→','↔')) else '待确认'
    e['organizer']=clean(e.get('organizer'))[:200]
    e['details']=e.get('details') if isinstance(e.get('details'),dict) else {}
    e['cost_text']=clean(e.get('cost_text'))[:100] or '费用未注明';e['cost_free']=e['cost_text'] in ('免费','0元','免费参加')
    e['all_day']=bool(e.get('all_day'))
    topics=e.get('topics') or rules(e['title'],e['summary'])['topics']
    e['topics']=[canonical_topic(x) for x in topics if canonical_topic(x) in TOPICS or x=='其他']
    if not e['topics']:e['topics']=['其他']
    raw_type=clean(e.get('event_type'))
    e['event_type']=raw_type if raw_type in EVENT_TYPES else 'Event'
    e['event_type_state']='source' if e['event_type']!='Event' else 'pending'
    e['topics']=resolved_topics(e['topics'],e['event_type'],e['title'],e['summary'])
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
        CREATE TABLE IF NOT EXISTS preferences(event_id TEXT PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,favorite INTEGER DEFAULT 0,hidden INTEGER DEFAULT 0,feedback TEXT NOT NULL DEFAULT '',feedback_tags TEXT NOT NULL DEFAULT '[]',feedback_updated_at TEXT);
        CREATE TABLE IF NOT EXISTS source_health(id TEXT PRIMARY KEY,name TEXT,url TEXT,status TEXT DEFAULT 'pending',message TEXT DEFAULT '',last_attempt TEXT,last_success TEXT,raw_count INTEGER DEFAULT 0,event_count INTEGER DEFAULT 0,failure_count INTEGER DEFAULT 0,next_attempt TEXT);
        CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,kind TEXT,started_at TEXT,finished_at TEXT,status TEXT,details TEXT);
        CREATE TABLE IF NOT EXISTS budget(day TEXT PRIMARY KEY,calls INTEGER DEFAULT 0,tokens INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS candidates(name TEXT PRIMARY KEY,query TEXT,url TEXT,hits INTEGER DEFAULT 1,last_seen TEXT);
        CREATE TABLE IF NOT EXISTS event_redirects(alias_id TEXT PRIMARY KEY,target_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE);
        CREATE INDEX IF NOT EXISTS idx_event_sources_event ON event_sources(event_id);
        CREATE INDEX IF NOT EXISTS idx_events_query_time ON events(start_at,id);
        CREATE INDEX IF NOT EXISTS idx_preferences_favorite_nonzero ON preferences(event_id) WHERE favorite<>0;
        ''')
        if 'coverage' not in {r[1] for r in c.execute('PRAGMA table_info(source_health)')}:
            c.execute("ALTER TABLE source_health ADD COLUMN coverage TEXT NOT NULL DEFAULT '{}'")
        pref_cols={r[1] for r in c.execute('PRAGMA table_info(preferences)')}
        if 'feedback' not in pref_cols:c.execute("ALTER TABLE preferences ADD COLUMN feedback TEXT NOT NULL DEFAULT ''")
        if 'feedback_tags' not in pref_cols:c.execute("ALTER TABLE preferences ADD COLUMN feedback_tags TEXT NOT NULL DEFAULT '[]'")
        if 'feedback_updated_at' not in pref_cols:c.execute("ALTER TABLE preferences ADD COLUMN feedback_updated_at TEXT")
        if 'revision' not in pref_cols:c.execute("ALTER TABLE preferences ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
        if 'viewed_at' not in pref_cols:c.execute("ALTER TABLE preferences ADD COLUMN viewed_at TEXT")
        event_cols={r[1] for r in c.execute('PRAGMA table_info(events)')}
        if 'details' not in event_cols:c.execute("ALTER TABLE events ADD COLUMN details TEXT NOT NULL DEFAULT '{}'")
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

def decode_feedback_tags(value):
    try:values=json.loads(value or '[]')
    except (ValueError,TypeError):return []
    if not isinstance(values,list):return []
    return list(dict.fromkeys(x for x in values if isinstance(x,str) and x in FEEDBACK_TAGS))

def merge_preferences(c,winner,loser):
    loser_pref=c.execute('SELECT * FROM preferences WHERE event_id=?',(loser,)).fetchone()
    if not loser_pref:return
    loser_pref=dict(loser_pref)
    c.execute('INSERT OR IGNORE INTO preferences(event_id) VALUES(?)',(winner,))
    winner_pref=dict(c.execute('SELECT * FROM preferences WHERE event_id=?',(winner,)).fetchone())
    c.execute('UPDATE preferences SET favorite=MAX(favorite,?),hidden=MAX(hidden,?) WHERE event_id=?',
              (int(loser_pref.get('favorite') or 0),int(loser_pref.get('hidden') or 0),winner))
    loser_tags=decode_feedback_tags(loser_pref.get('feedback_tags'))
    winner_tags=decode_feedback_tags(winner_pref.get('feedback_tags'))
    loser_feedback=loser_pref.get('feedback') if loser_pref.get('feedback') in FEEDBACK_SIGNALS else ''
    winner_feedback=winner_pref.get('feedback') if winner_pref.get('feedback') in FEEDBACK_SIGNALS else ''
    loser_has=bool(loser_feedback or loser_tags)
    winner_has=bool(winner_feedback or winner_tags)
    loser_time=loser_pref.get('feedback_updated_at') or ''
    winner_time=winner_pref.get('feedback_updated_at') or ''
    # A timestamp with empty values is an explicit clear, not missing feedback.
    if (loser_time and loser_time>winner_time) or (not winner_time and not loser_time and loser_has and not winner_has):
        c.execute('UPDATE preferences SET feedback=?,feedback_tags=?,feedback_updated_at=? WHERE event_id=?',
                  (loser_feedback,json.dumps(loser_tags,ensure_ascii=False),loser_pref.get('feedback_updated_at'),winner))
    c.execute('UPDATE preferences SET revision=MAX(revision,?)+1,viewed_at=? WHERE event_id=?',
              (int(loser_pref.get('revision') or 0),max(winner_pref.get('viewed_at') or '',loser_pref.get('viewed_at') or '') or None,winner))

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
            preferred=canon_url(a.get('preferred_url',''));preferred_ids={x[0] for x in c.execute('SELECT event_id FROM event_sources WHERE url=?',(preferred,))} if preferred else set()
            rows.sort(key=lambda r:(r['id'] not in preferred_ids,r.get('origin_priority',50),r.get('first_seen',''),r['id']));winner=rows[0]['id']
            for loser in rows[1:]:
                merge_preferences(c,winner,loser['id'])
                c.execute('UPDATE event_sources SET event_id=? WHERE event_id=?',(winner,loser['id']))
                c.execute('UPDATE event_redirects SET target_id=? WHERE target_id=?',(winner,loser['id']))
                c.execute('INSERT OR REPLACE INTO event_redirects(alias_id,target_id) VALUES(?,?)',(loser['id'],winner))
                c.execute('DELETE FROM events WHERE id=?',(loser['id'],));merged.append((winner,loser['id'],a['id']))
    return merged

def resolve_event_id(event_id):
    with db() as c:
        row=c.execute('SELECT target_id FROM event_redirects WHERE alias_id=?',(event_id,)).fetchone()
    return row[0] if row else event_id

def is_duplicate(a,b):
    if not a.get('start_at') or not b.get('start_at') or a['start_at'][:10]!=b['start_at'][:10]:return False
    year=a['start_at'][:4];an,bn=norm(a['title']).replace(year,''),norm(b['title']).replace(year,'');la,lb=norm(a.get('location','')),norm(b.get('location',''))
    def attendance(event):
        details=event.get('details')
        if isinstance(details,str):
            try:details=json.loads(details)
            except (ValueError,TypeError):details={}
        return event_attendance({**event,'details':details})
    am,bm=attendance(a),attendance(b)
    same_url=bool(canon_url(a.get('url','')) and canon_url(a.get('url',''))==canon_url(b.get('url','')))
    if not same_url and am!=bm:
        # A name/date match is not evidence that a broadcast and a venue event
        # are the same activity. Explicit reviewed aliases are resolved before
        # this heuristic, and existing same-source URL links bypass it.
        if 'online' in (am,bm):return False
        if {am,bm}=={'hybrid','offline'}:
            region_names=r'(?:中华人民共和国|中国|广东(?:省)?|深圳(?:市)?|(?:'+ '|'.join(map(re.escape,DISTRICTS))+r')(?:新区|区)?)+'
            remainder=re.sub('^'+region_names,'',la)
            # Remove administrative components, not a named campus/venue.
            # An iterative prefix scan avoids an ambiguous repeated regex over
            # source-controlled address text.
            if not (len(remainder)>2 and remainder.endswith(('校区','园区'))):
                while remainder:
                    part=re.match(r'[\u3400-\u9fff]{1,12}?(?:自治区|自治州|特别行政区|街道|新区|省|市|区|县|镇|乡|村)',remainder)
                    if not part:break
                    remainder=remainder[part.end():]
            same_venue=(la==lb and len(la)>5 and bool(remainder)
                        and not re.search(r'待确认|待定|通知|未知',clean(a.get('location'))))
            same_organizer=bool(norm(a.get('organizer','')) and norm(a.get('organizer',''))==norm(b.get('organizer','')))
            same_clock=(not a.get('all_day') and not b.get('all_day') and a['start_at']==b['start_at'])
            if not same_venue or not (same_organizer or same_clock):return False
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
        held=json.loads(prev['details'] or '{}') if prev else {}
        if held.get('review_hold'):
            e['status']='needs_review';e['details']={**e['details'],**held}
        if not prev or (changed and rank<=prev['origin_priority']):
            data={'id':eid,'title':e['title'],'title_norm':norm(e['title']),'start_at':e['start_at'],'end_at':e['end_at'],'all_day':int(e['all_day']),'location':e['location'],'district':e['district'],'organizer':e['organizer'],'details':json.dumps(e['details'],ensure_ascii=False),'summary':e['summary'],'topics':json.dumps(e['topics'],ensure_ascii=False),'event_type':e['event_type'],'event_type_state':e['event_type_state'],'priority':r['priority'],'reason':r['reason'],'commercial':r['commercial'],'cost_text':e['cost_text'],'cost_free':int(e['cost_free']),'url':e['url'],'status':e['status'],'origin_priority':rank,'first_seen':prev['first_seen'] if prev else ts,'last_seen':ts,'ai_state':'review' if held.get('review_hold') else 'pending'}
            keys=list(data);c.execute(f"INSERT INTO events ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)}) ON CONFLICT(id) DO UPDATE SET "+','.join(f'{k}=excluded.{k}' for k in keys if k not in ('id','first_seen')),tuple(data.values()))
        elif e['event_type_state']=='source' and rank<=prev['origin_priority']:
            # Newly extracted source typing must not reset an unchanged event's
            # AI-established dates, location, summary, or analysis state.
            c.execute('UPDATE events SET event_type=?,event_type_state=?,last_seen=? WHERE id=?',(e['event_type'],'source',ts,eid))
        else:c.execute('UPDATE events SET last_seen=? WHERE id=?',(ts,eid))
        # A lower-priority linked source may fill genuinely missing detail fields,
        # but cannot replace established event dates, venue or a manual review hold.
        if prev:
            unknown={'','费用未注明','未注明','未知','待确认'}
            if clean(prev['cost_text']) in unknown and e['cost_text'] not in unknown:
                c.execute('UPDATE events SET cost_text=?,cost_free=? WHERE id=?',(e['cost_text'],int(e['cost_free']),eid))
            if not clean(prev['organizer']) and e['organizer']:
                c.execute('UPDATE events SET organizer=? WHERE id=?',(e['organizer'],eid))
            if e['details'] and (not held or (rank<=prev['origin_priority'] and not held.get('review_hold'))):
                c.execute('UPDATE events SET details=? WHERE id=?',(json.dumps(e['details'],ensure_ascii=False),eid))
        c.execute('INSERT INTO event_sources VALUES(?,?,?,?,?) ON CONFLICT(source_id,url) DO UPDATE SET event_id=excluded.event_id,raw_id=excluded.raw_id,seen_at=excluded.seen_at',(eid,source['id'],e['url'],rid,ts))
    return changed

def span_days(e):
    if not e.get('start_at') or not e.get('end_at'):return 0.0
    try:return max(0.0,(_query_datetime(e['end_at'])-_query_datetime(e['start_at'])).total_seconds()/86400)
    except ValueError:return 0.0


def period_bounds(period, current):
    """An exclusive upper boundary, in the existing Shanghai period semantics."""
    current=_query_datetime(current)
    day=current.date();begin=current;finish=None
    if period=='week':
        finish=datetime.combine(day+timedelta(days=7-day.weekday()),datetime.min.time(),TZ)
    elif period=='weekend':
        saturday=day+timedelta(days=(5-day.weekday())%7) if day.weekday()<5 else day-timedelta(days=day.weekday()-5)
        begin=max(current,datetime.combine(saturday,datetime.min.time(),TZ))
        finish=datetime.combine(saturday+timedelta(days=2),datetime.min.time(),TZ)
    return begin,finish


def _query_datetime(value):
    result=value if isinstance(value,datetime) else datetime.fromisoformat(value)
    return result.replace(tzinfo=TZ) if result.tzinfo is None else result.astimezone(TZ)


def all_day_end(e):
    """Query-only end: one full Shanghai date when no usable exclusive end exists."""
    start=_query_datetime(e['start_at'])
    value=e.get('end_at')
    if value:
        try:
            end=_query_datetime(value)
            if end>start and end.date()>start.date():
                return end.isoformat()
        except ValueError:
            pass
    return iso(datetime.combine(start.date()+timedelta(days=1),datetime.min.time(),TZ))


def upcoming_end(e):
    # Timed unknown ends retain the established three-hour upcoming window.
    return all_day_end(e) if e['all_day'] else e.get('end_at') or (_query_datetime(e['start_at'])+timedelta(hours=3)).isoformat()


def overlaps_range(e, range_start=None, range_end=None):
    """Half-open date intersection, independent of a view's status/personal policy."""
    if not e.get('start_at'):return False
    start=_query_datetime(e['start_at'])
    end=_query_datetime(all_day_end(e)) if e['all_day'] else _query_datetime(e['end_at']) if e.get('end_at') else None
    if end is None or end<=start:end=start+timedelta(seconds=1)
    return (not range_start or end>_query_datetime(range_start)) and (not range_end or start<_query_datetime(range_end))


def _source_links(c, event_ids):
    marks=','.join('?' for _ in event_ids)
    links={}
    for row in c.execute(f'SELECT es.event_id,es.url,sh.name,es.source_id FROM event_sources es JOIN source_health sh ON sh.id=es.source_id WHERE es.event_id IN ({marks}) ORDER BY es.rowid',event_ids):
        links.setdefault(row['event_id'],[]).append(dict(row))
    return links

def events(query='',period='upcoming',district='',tag='',free=False,recommended=False,favorites=False,include_hidden=False,range_start=None,range_end=None,event_id=None,hide_long=False,sort='asc',event_types=None,topics_filter=None,attendance='all',feedback='',feedback_tag='',viewed='all',districts=None):
    if event_id:event_id=resolve_event_id(event_id)
    aliases=dedupe_aliases()
    topics_filter=[canonical_topic(x) for x in topics_filter or []]
    if tag:topics_filter.append(canonical_topic(tag))
    current=_query_datetime(now());from_dt,to_dt=period_bounds(period,current)
    range_start=_query_datetime(range_start).isoformat() if range_start else None
    range_end=_query_datetime(range_end).isoformat() if range_end else None
    if sort not in ('asc','desc'):raise ValueError('invalid sort')
    # Push only predicates that cannot be changed by alias/topic normalization.
    # Python still owns Unicode search, canonical topics, attendance and facets.
    clauses=[];params=[]
    def add(sql,*values):
        clauses.append(sql);params.extend(values)
    if event_id:add('e.id=?',event_id)
    if not include_hidden:add('COALESCE(p.hidden,0)=0')
    # Seek the marked IDs instead of scanning every event to probe preferences.
    # A subquery adds no per-favorite parameters and stays in this read snapshot.
    if favorites:
        add('COALESCE(p.favorite,0)<>0')
        # A resolved point lookup already seeks one event; do not scan all marks.
        if not event_id:add('e.id IN (SELECT event_id FROM preferences WHERE favorite<>0)')
    if free:add('COALESCE(e.cost_free,0)<>0')
    if recommended:add("e.priority IN ('high','medium') AND COALESCE(e.commercial,'')<>'high'")
    if viewed=='seen':add("COALESCE(p.viewed_at,'')<>''")
    elif viewed=='unseen':add("COALESCE(p.viewed_at,'')=''")
    if feedback in FEEDBACK_SIGNALS:add('p.feedback=?',feedback)
    if districts is not None:
        if districts:add('e.district IN ('+','.join('?' for _ in districts)+')',*districts)
        else:add('0')
    elif district:add('e.district=?',district)
    if event_types:
        add("COALESCE(e.event_type_state,'')<>'pending' AND COALESCE(NULLIF(e.event_type,''),'Event') IN ("+','.join('?' for _ in event_types)+')',*event_types)
    # Only the canonical Shanghai representation is safe for text comparisons.
    # Every other valid legacy representation reaches the datetime predicates.
    canonical_time="????-??-??T??:??:??+08:00"
    legacy_start=f"e.start_at NOT GLOB '{canonical_time}'"
    legacy_end=f"(COALESCE(e.end_at,'')<>'' AND e.end_at NOT GLOB '{canonical_time}')"
    legacy_time=f"({legacy_start} OR {legacy_end})"
    if period=='review':
        add("e.status='needs_review'")
    elif period in ('calendar','range'):
        add("e.start_at IS NOT NULL AND e.start_at<>'' AND e.status='scheduled'")
    elif period=='past':
        add("e.start_at IS NOT NULL AND e.start_at<>''")
        add(f'(e.start_at<=? OR e.end_at<=? OR {legacy_time})',current.isoformat(),current.isoformat())
    elif period not in ('saved','record','feedback','history'):
        add("e.start_at IS NOT NULL AND e.start_at<>'' AND COALESCE(e.status,'') NOT IN ('cancelled','needs_review','not_event')")
        add(f"(e.end_at>? OR e.start_at>? OR (COALESCE(e.all_day,0)<>0 AND substr(e.start_at,1,10)>=?) OR {legacy_time})",
            from_dt.isoformat(),iso(from_dt-timedelta(hours=3)),from_dt.date().isoformat())
        if to_dt:add(f'(e.start_at<? OR {legacy_start})',to_dt.isoformat())
    # Explicit date bounds intersect every view; they never replace its policy.
    if range_start or range_end:
        add("e.start_at IS NOT NULL AND e.start_at<>''")
        # Prune conservatively; non-Shanghai/legacy offsets are checked in Python.
        if range_end:add(f'(e.start_at<? OR {legacy_start})',range_end)
        if range_start:
            add(f'(e.end_at>? OR substr(e.start_at,1,10)>=? OR {legacy_time})',
                range_start,datetime.fromisoformat(range_start).date().isoformat())
    where=' AND '.join(clauses) or '1'
    out=[]
    with db() as c:
        # One read snapshot binds event rows and their source attribution.
        c.execute('BEGIN')
        cursor=c.execute("SELECT e.*,COALESCE(p.favorite,0) favorite,COALESCE(p.hidden,0) hidden,COALESCE(p.feedback,'') feedback,COALESCE(p.feedback_tags,'[]') feedback_tags,p.feedback_updated_at feedback_updated_at,COALESCE(p.revision,0) revision,p.viewed_at viewed_at FROM events e LEFT JOIN preferences p ON e.id=p.event_id WHERE "+where+" ORDER BY e.start_at,e.id",params)
        # Bound intermediate hydration, not the matching set used for totals/facets.
        while batch:=cursor.fetchmany(256):
            rows=[dict(row) for row in batch]
            links=_source_links(c,[e['id'] for e in rows])
            for e in rows:
                if event_id and e['id']!=event_id:continue
                if not include_hidden and e['hidden']:continue
                e['feedback']=e.get('feedback') if e.get('feedback') in FEEDBACK_SIGNALS else ''
                e['feedback_tags']=decode_feedback_tags(e.get('feedback_tags'))
                if feedback=='any' and not (e['feedback'] or e['feedback_tags']):continue
                if feedback=='none' and (e['feedback'] or e['feedback_tags']):continue
                if feedback in FEEDBACK_SIGNALS and e['feedback']!=feedback:continue
                if feedback_tag and feedback_tag not in e['feedback_tags']:continue
                if viewed=='seen' and not e['viewed_at']:continue
                if viewed=='unseen' and e['viewed_at']:continue
                start_dt=_query_datetime(e['start_at']) if e['start_at'] else None
                days=span_days(e);e['span_days']=round(days,1);e['long_running']=days>=LONG_RUNNING_DAYS;e['display_at']=e.get('start_at');e['period_label']=''
                if hide_long and e['long_running'] and period not in ('record','saved','feedback','history'):continue
                if period=='review':
                    if e['status']!='needs_review':continue
                elif period in ('saved','record','feedback','history'):
                    pass
                elif period in ('calendar','range'):
                    if not e['start_at'] or e['status']!='scheduled':continue
                elif period=='past':
                    if not e['start_at']:continue
                    end=all_day_end(e) if e['all_day'] else e['end_at']
                    if end:
                        if _query_datetime(end)>current:continue
                    elif start_dt>=current:continue
                else:
                    if not e['start_at'] or e['status'] in ('cancelled','needs_review','not_event'):continue
                    end=_query_datetime(upcoming_end(e))
                    if end<=from_dt:continue
                    if to_dt and start_dt>=to_dt:continue
                    if e['long_running'] and start_dt<from_dt:
                        e['display_at']=from_dt.isoformat(timespec='seconds')
                        e['period_label']='本周末仍开放' if period=='weekend' else ('本周仍开放' if period=='week' else '长期/重复活动')
                if (range_start or range_end) and not overlaps_range(e,range_start,range_end):continue
                from .posters import display_details
                e['details']=display_details(json.loads(e.get('details') or '{}'),ROOT)
                for a in aliases:
                    if a.get('date')==(e.get('start_at') or '')[:10] and any(canon_url(x.get('url','')) in a.get('urls',[]) for x in links.get(e['id'],[])):
                        fix=a.get('canonical',{})
                        for field in ('title','location'):
                            if isinstance(fix.get(field),str):e[field]=fix[field]
                        if isinstance(fix.get('topics'),list):e['topics']=json.dumps(fix['topics'],ensure_ascii=False)
                e['attendance']=event_attendance(e);e['attendance_label']=ATTENDANCE_LABELS[e['attendance']]
                if attendance!='all' and e['attendance'] not in ({'online':('online','hybrid'),'offline':('offline','hybrid')}.get(attendance,(attendance,))):continue
                e['topics']=resolved_topics(json.loads(e['topics'] or '[]'),e.get('event_type','Event'),e['title'],e['summary'])
                e['event_type']=e.get('event_type') or 'Event';e['event_type_label']='待分类' if e.get('event_type_state')=='pending' else EVENT_TYPES.get(e['event_type'],'其他活动');e['sources']=links.get(e['id'],[])
                if query and query.casefold() not in (e['title']+' '+e['summary']+' '+e['location']+' '+e['organizer']).casefold():continue
                if districts is not None:
                    if e['district'] not in districts:continue
                elif district and e['district']!=district:continue
                if event_types and (e.get('event_type_state')=='pending' or e['event_type'] not in set(event_types)):continue
                if topics_filter and not set(topics_filter).intersection(e['topics']):continue
                if free and not e['cost_free']:continue
                if recommended and (e['priority'] not in ('high','medium') or e['commercial']=='high'):continue
                if favorites and not e['favorite']:continue
                e['stale']=(current-_query_datetime(e['last_seen'])).days>=7;out.append(e)
    def key(e):
        value=e.get('display_at') or e.get('start_at')
        return (value is None if sort=='asc' else value is not None,_query_datetime(value) if value else datetime.min.replace(tzinfo=TZ),e['id'])
    out.sort(key=key,reverse=sort=='desc')
    if period=='history':out.sort(key=lambda e:e.get('viewed_at') or '',reverse=True)
    if period=='feedback':out.sort(key=lambda e:e.get('feedback_updated_at') or '',reverse=True)
    return out


