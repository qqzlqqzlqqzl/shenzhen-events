"""Private activity UI. Identity verification is delegated, never password storage."""
from __future__ import annotations
import base64, hashlib, hmac, json, os, secrets, threading, time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from collections import defaultdict, deque, Counter
import requests
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field
from .core import ROOT, TZ, config, db, events, init, reconcile_aliases, now, stamp, VERSION, CATEGORIES, TOPICS, EVENT_TYPES, DISTRICTS, FEEDBACK_SIGNALS, FEEDBACK_TAGS, decode_feedback_tags, iso, canonical_topic
from .calendar import make_calendar
from . import jobs
COOKIE='sz_events_session'
AUTH_URL='http://127.0.0.1:8091/mf/v1/me'
ATTEMPTS=defaultdict(deque);ATTEMPT_LOCK=threading.Lock()

def initialize_settings():
    private=ROOT/'.private';private.mkdir(exist_ok=True);private.chmod(0o700);p=private/'settings.json'
    if not p.exists():
        cfg={'analysis_enabled':False,'session_secret':secrets.token_hex(32),'feed_token':secrets.token_urlsafe(32),'daily_tokens':200000,'daily_calls':60,'model_base':'https://ark.cn-beijing.volces.com/api/v3','model':'deepseek-v4-flash-ga-260731'}
        fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(cfg,f)
    return config()

def sign_session(user):
    body=base64.urlsafe_b64encode(json.dumps({'id':user['id'],'name':user['username'],'exp':int(time.time())+14*86400},separators=(',',':')).encode()).decode().rstrip('=')
    sig=hmac.new(bytes.fromhex(config()['session_secret']),body.encode(),hashlib.sha256).hexdigest()
    return body+'.'+sig

def read_session(token):
    try:
        body,sig=token.split('.',1);expected=hmac.new(bytes.fromhex(config()['session_secret']),body.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig,expected):return None
        obj=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        return obj if obj['exp']>time.time() else None
    except (ValueError,KeyError,TypeError):return None

def require(request):
    user=read_session(request.cookies.get(COOKIE,''))
    if not user:raise HTTPException(401,'请使用现有阅读器账号登录')
    return user

@asynccontextmanager
async def lifespan(app):
    initialize_settings();init();reconcile_aliases();yield
app=FastAPI(title='深圳活动雷达',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
app.add_middleware(GZipMiddleware,minimum_size=700)

@app.middleware('http')
async def security(request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        if request.headers.get('x-radar-request')!='1' or request.headers.get('sec-fetch-site')=='cross-site':return JSONResponse({'detail':'拒绝跨站写入'},status_code=403)
        origin=request.headers.get('origin')
        if origin and origin!=str(request.base_url).rstrip('/'):return JSONResponse({'detail':'来源不匹配'},status_code=403)
        try:
            if int(request.headers.get('content-length','0'))>16384:return JSONResponse({'detail':'请求过大'},status_code=413)
        except ValueError:return JSONResponse({'detail':'无效长度'},status_code=400)
    response=await call_next(request)
    response.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Cache-Control':'private, no-store'})
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    return response

@app.get('/events/api/health')
def health():
    with db() as c:c.execute('SELECT 1').fetchone()
    return {'ok':True,'service':'shenzhen-events','version':VERSION}
class Credentials(BaseModel):
    username:str=Field(min_length=1,max_length=128)
    password:str=Field(min_length=1,max_length=256)
@app.post('/events/api/login')
def login(body:Credentials,request:Request):
    ip=request.headers.get('x-real-ip') or request.client.host
    with ATTEMPT_LOCK:
        t=time.monotonic();q=ATTEMPTS[ip]
        while q and q[0]<t-300:q.popleft()
        if len(q)>=8:raise HTTPException(429,'尝试次数过多，请稍后再试')
        q.append(t)
        if len(ATTEMPTS)>1000:
            for k in list(ATTEMPTS):
                if not ATTEMPTS[k] or ATTEMPTS[k][-1]<t-300:ATTEMPTS.pop(k,None)
    try:
        s=requests.Session();s.trust_env=False;r=s.get(AUTH_URL,auth=(body.username,body.password),timeout=(3,8))
    except requests.RequestException:raise HTTPException(503,'账号验证服务暂不可用')
    if r.status_code!=200:raise HTTPException(401,'账号或密码不正确')
    user=r.json()
    if not user.get('is_admin'):raise HTTPException(403,'此私人站点仅允许所有者账号')
    response=JSONResponse({'ok':True,'username':user['username']})
    response.set_cookie(COOKIE,sign_session(user),max_age=14*86400,httponly=True,secure=True,samesite='lax',path='/events')
    return response
@app.post('/events/api/logout')
def logout(request:Request):
    require(request);r=JSONResponse({'ok':True});r.delete_cookie(COOKIE,path='/events',secure=True,httponly=True,samesite='lax');return r
@app.get('/events/api/session')
def session(request:Request):return {'username':require(request)['name']}
@app.get('/events/api/events')
def listing(request:Request,q:str=Query('',max_length=160),period:str='upcoming',district:str='',districts:list[str]|None=Query(None),district_none:bool=False,tag:str='',event_types:list[str]|None=Query(None,alias='type'),topics:list[str]|None=Query(None,alias='topic'),type_none:bool=False,topic_none:bool=False,attendance:str='all',feedback:str='',feedback_tag:str='',viewed:str='all',free:bool=False,recommended:bool=False,favorites:bool=False,hide_long:bool=False,sort:str='asc',offset:int=Query(0,ge=0),limit:int=Query(36,ge=1,le=500),start:str='',end:str=''):
    require(request)
    if period not in ('upcoming','week','weekend','review','past','saved','calendar','feedback','history','range'):raise HTTPException(400,'无效日期筛选')
    if attendance not in ('all','online','offline','hybrid','unknown'):raise HTTPException(400,'无效参加方式')
    if feedback not in ('','any','none',*FEEDBACK_SIGNALS) or feedback_tag not in ('',*FEEDBACK_TAGS) or viewed not in ('all','seen','unseen'):raise HTTPException(400,'无效个人状态筛选')
    if districts is not None:
        districts=list(dict.fromkeys(districts))
        if len(districts)>len(DISTRICTS)+1 or any(x not in (*DISTRICTS,'待确认') for x in districts):raise HTTPException(400,'无效地区筛选')
    if attendance=='online':district='';districts=None;district_none=False
    if sort not in ('asc','desc'):raise HTTPException(400,'无效排序方式')
    event_types=list(dict.fromkeys(event_types or []));topics=list(dict.fromkeys(canonical_topic(x) for x in topics or []))
    if len(event_types)>len(EVENT_TYPES) or any(x not in EVENT_TYPES for x in event_types):raise HTTPException(400,'无效活动类型筛选')
    if len(topics)>20 or any(x not in TOPICS and x!='其他' for x in topics):raise HTTPException(400,'无效主题筛选')
    begin,finish=None,None
    if period in ('calendar','range'):
        begin,finish=iso(start),iso(end)
        if not begin or not finish:raise HTTPException(400,'日历起止日期无效')
        span=datetime.fromisoformat(finish)-datetime.fromisoformat(begin)
        if span.total_seconds()<=0 or span>timedelta(days=93):raise HTTPException(400,'日历范围需在93天内')
    if period=='saved':favorites=True
    if period=='feedback' and not feedback:feedback='any'
    if period=='history':viewed='seen'
    from .filtering import contextual_listing
    candidates=events(query=q,period=period,free=free,recommended=recommended,favorites=favorites,range_start=begin,range_end=finish,hide_long=False,sort=sort,attendance=attendance,feedback=feedback,feedback_tag=feedback_tag,viewed=viewed)
    return contextual_listing(candidates,event_types=event_types,topics=topics,tag=tag,district=district,districts=districts,type_none=type_none,topic_none=topic_none,district_none=district_none,hide_long=hide_long and period not in ('saved','feedback','history'),offset=offset,limit=limit)
@app.get('/events/api/calendar-summary')
def calendar_summary(request:Request):
    require(request)
    rows=events(period='saved',favorites=True)
    return {'total':len(rows),'unscheduled':sum(not e['start_at'] or e['status']!='scheduled' for e in rows),'long_running':sum(e['long_running'] for e in rows)}

@app.get('/events/api/stats')
def stats(request:Request):
    from .core import period_bounds, upcoming_end, now as query_now
    require(request);up=events();rec=[e for e in up if e['priority'] in ('high','medium') and e['commercial']!='high']
    begin,finish=period_bounds('weekend',query_now())
    weekend=sum(not e['long_running'] and upcoming_end(e)>begin.isoformat() and e['start_at']<finish.isoformat() for e in up)
    long_running=sum(e['long_running'] for e in up)
    with db() as c:
        health=[dict(x) for x in c.execute('SELECT * FROM source_health')];raw=c.execute('SELECT COUNT(*) FROM raw_items').fetchone()[0];pending=c.execute("SELECT COUNT(*) FROM raw_items WHERE analysis_state='pending'").fetchone()[0];type_pending=c.execute("SELECT COUNT(*) FROM events WHERE event_type_state='pending' AND status='scheduled'").fetchone()[0]
    type_counts=Counter(e.get('event_type') or 'Event' for e in up if e.get('event_type_state')!='pending');topic_counts=Counter(t for e in up for t in e.get('topics',[]))
    type_facets=[{'value':v,'label':label,'count':type_counts.get(v,0)} for v,label in EVENT_TYPES.items() if v!='Event']
    type_facets.append({'value':'Event','label':'其他活动','count':type_counts.get('Event',0)})
    topic_facets=[{'value':v,'label':v,'count':topic_counts.get(v,0)} for v in TOPICS]
    topic_facets.append({'value':'其他','label':'主题待归类','count':topic_counts.get('其他',0)})
    return {'upcoming':len(up),'recommended':len(rec),'weekend':weekend,'sources':len(health),'working_sources':sum(s['status'] in ('ok','partial') and s['raw_count']>0 for s in health),'normal_sources':sum(s['status']=='ok' and s['raw_count']>0 for s in health),'partial_sources':sum(s['status']=='partial' for s in health),'raw':raw,'pending':pending,'type_pending':type_pending,'long_running':long_running,'last_updated':max((s['last_success'] or '' for s in health),default=''),'categories':list(TOPICS),'event_types':type_facets,'topics':topic_facets,'districts':DISTRICTS,'timezone':'Asia/Shanghai'}
@app.get('/events/api/status')
def status(request:Request):
    require(request);cfg=config()
    with db() as c:
        sources=[dict(x) for x in c.execute('SELECT * FROM source_health')];runs=[dict(x) for x in c.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 20')];candidates=[dict(x) for x in c.execute('SELECT * FROM candidates ORDER BY hits DESC,last_seen DESC LIMIT 50')];b=c.execute('SELECT * FROM budget WHERE day=?',(now().date().isoformat(),)).fetchone()
    with db() as c:
        analysis_pending=c.execute("SELECT COUNT(*) FROM raw_items WHERE analysis_state='pending'").fetchone()[0]
        type_pending=c.execute("SELECT COUNT(*) FROM events WHERE event_type_state='pending' AND status='scheduled'").fetchone()[0]
    pending_jobs=jobs.latest_jobs()
    for source in sources:
        source['coverage']=json.loads(source.get('coverage') or '{}')
        source['retry']=pending_jobs.get(source['id'])
    return {'analysis_enabled':cfg.get('analysis_enabled') is True,'analysis_pending':analysis_pending,'type_pending':type_pending,'sources':sources,'runs':runs,'candidates':candidates,'budget':dict(b) if b else {'calls':0,'tokens':0},'limits':{'daily_tokens':cfg.get('daily_tokens',200000),'daily_calls':cfg.get('daily_calls',60)},'db_bytes':(ROOT/'data/events.sqlite3').stat().st_size,'ics_url':'/events/calendar.ics?token='+cfg['feed_token']+'&favorites=true','retention_days':45}
@app.post('/events/api/sources/{source_id}/retry',status_code=202)
def retry_source(source_id:str,request:Request):
    require(request)
    try:return jobs.enqueue(source_id)
    except jobs.QueueError as exc:raise HTTPException(exc.status,str(exc))

class Preference(BaseModel):
    expected_revision:int|None=Field(default=None,ge=0)
    favorite:bool|None=None
    hidden:bool|None=None
    feedback:str|None=Field(default=None,max_length=32)
    feedback_tags:list[str]|None=Field(default=None,max_length=len(FEEDBACK_TAGS))
@app.post('/events/api/preferences/{event_id}')
def preference(event_id:str,body:Preference,request:Request):
    require(request)
    from . import personal
    try:return personal.update(event_id, body.model_dump(exclude={'expected_revision'}), body.expected_revision)
    except personal.Conflict as exc:return JSONResponse({'detail':'活动状态已在其他页面更新，请核对后重试。','current':exc.current},status_code=409)
    except ValueError as exc:raise HTTPException(400,str(exc))
    except LookupError as exc:raise HTTPException(404,str(exc))

@app.post('/events/api/viewed/{event_id}')
def mark_viewed(event_id:str,request:Request):
    require(request)
    from . import personal
    try:return personal.viewed(event_id)
    except LookupError as exc:raise HTTPException(404,str(exc))

@app.get('/events/api/feedback-export')
def feedback_export(request:Request):
    require(request)
    rows=events(period='feedback',include_hidden=True,feedback='any')
    fields=('id','title','url','start_at','end_at','feedback','feedback_tags','feedback_updated_at','favorite','revision')
    return JSONResponse({'version':1,'exported_at':stamp(),'count':len(rows),'items':[{k:e.get(k) for k in fields} for e in rows]},headers={'Content-Disposition':'attachment; filename="event-feedback.json"'})

@app.get('/events/calendar.ics')
def calendar(request:Request,token:str='',favorites:bool=False,recommended:bool=False):
    if not read_session(request.cookies.get(COOKIE,'')) and not hmac.compare_digest(token,config().get('feed_token','__invalid__')):raise HTTPException(401,'日历订阅需要私人链接')
    return Response(make_calendar(events(favorites=favorites,recommended=recommended)),media_type='text/calendar; charset=utf-8',headers={'Content-Disposition':'attachment; filename="shenzhen-events.ics"'})
@app.get('/events/api/event/{event_id}.ics')
def one_event(event_id:str,request:Request):
    require(request);rows=events(period='record',event_id=event_id,include_hidden=True)
    if not rows:raise HTTPException(404,'活动不存在')
    if not rows[0]['start_at'] or rows[0]['status']!='scheduled':raise HTTPException(409,'此活动没有可导出的已确认日程')
    return Response(make_calendar(rows),media_type='text/calendar; charset=utf-8',headers={'Content-Disposition':'attachment; filename="event.ics"'})
@app.get('/events/api/event/{event_id}')
def event_detail(event_id:str,request:Request):
    require(request)
    rows=events(period='record',event_id=event_id,include_hidden=True)
    if not rows:raise HTTPException(404,'活动已不存在或已清理')
    return rows[0]
@app.get('/events')
def redirect():return RedirectResponse('/events/',status_code=308)
@app.get('/events/')
def index():return FileResponse(ROOT/'static/index.html')
app.mount('/events/static',StaticFiles(directory=ROOT/'static'),name='static')


