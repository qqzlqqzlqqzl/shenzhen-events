"""Private activity UI. Identity verification is delegated, never password storage."""
from __future__ import annotations
import base64, hashlib, hmac, json, os, secrets, threading, time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from collections import defaultdict, deque
import requests
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field
from .core import ROOT, TZ, config, db, events, init, reconcile_aliases, now, stamp, VERSION, CATEGORIES, DISTRICTS
from .calendar import make_calendar
COOKIE='sz_events_session'
AUTH_URL='http://127.0.0.1:8091/v1/me'
ATTEMPTS=defaultdict(deque);ATTEMPT_LOCK=threading.Lock()

def initialize_settings():
    private=ROOT/'.private';private.mkdir(exist_ok=True);private.chmod(0o700);p=private/'settings.json'
    if not p.exists():
        cfg={'session_secret':secrets.token_hex(32),'feed_token':secrets.token_urlsafe(32),'daily_tokens':200000,'daily_calls':60,'model_base':'https://ark.cn-beijing.volces.com/api/v3','model':'deepseek-v4-flash-ga-260731'}
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
def listing(request:Request,q:str=Query('',max_length=160),period:str='upcoming',district:str='',tag:str='',free:bool=False,recommended:bool=False,favorites:bool=False,offset:int=Query(0,ge=0,le=10000),limit:int=Query(36,ge=1,le=500)):
    require(request)
    if period not in ('upcoming','week','weekend','review','past'):raise HTTPException(400,'无效日期筛选')
    rows=events(query=q,period=period,district=district,tag=tag,free=free,recommended=recommended,favorites=favorites)
    return {'items':rows[offset:offset+limit],'total':len(rows),'offset':offset,'has_more':len(rows)>offset+limit}
@app.get('/events/api/stats')
def stats(request:Request):
    require(request);up=events();rec=[e for e in up if e['priority'] in ('high','medium') and e['commercial']!='high']
    with db() as c:
        health=[dict(x) for x in c.execute('SELECT * FROM source_health')];raw=c.execute('SELECT COUNT(*) FROM raw_items').fetchone()[0];pending=c.execute("SELECT COUNT(*) FROM raw_items WHERE analysis_state='pending'").fetchone()[0]
    return {'upcoming':len(up),'recommended':len(rec),'weekend':len(events(period='weekend')),'sources':len(health),'working_sources':sum(s['status'] in ('ok','partial') for s in health),'raw':raw,'pending':pending,'last_updated':max((s['last_success'] or '' for s in health),default=''),'categories':list(CATEGORIES),'districts':DISTRICTS,'timezone':'Asia/Shanghai'}
@app.get('/events/api/status')
def status(request:Request):
    require(request);cfg=config()
    with db() as c:
        sources=[dict(x) for x in c.execute('SELECT * FROM source_health')];runs=[dict(x) for x in c.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 20')];candidates=[dict(x) for x in c.execute('SELECT * FROM candidates ORDER BY hits DESC,last_seen DESC LIMIT 50')];b=c.execute('SELECT * FROM budget WHERE day=?',(now().date().isoformat(),)).fetchone()
    return {'sources':sources,'runs':runs,'candidates':candidates,'budget':dict(b) if b else {'calls':0,'tokens':0},'limits':{'daily_tokens':cfg.get('daily_tokens',200000),'daily_calls':cfg.get('daily_calls',60)},'db_bytes':(ROOT/'data/events.sqlite3').stat().st_size,'ics_url':'/events/calendar.ics?token='+cfg['feed_token']+'&favorites=true','retention_days':45}
class Preference(BaseModel):
    favorite:bool|None=None
    hidden:bool|None=None
@app.post('/events/api/preferences/{event_id}')
def preference(event_id:str,body:Preference,request:Request):
    require(request)
    with db() as c:
        if not c.execute('SELECT 1 FROM events WHERE id=?',(event_id,)).fetchone():raise HTTPException(404,'活动不存在')
        c.execute('INSERT OR IGNORE INTO preferences(event_id) VALUES(?)',(event_id,))
        if body.favorite is not None:c.execute('UPDATE preferences SET favorite=? WHERE event_id=?',(int(body.favorite),event_id))
        if body.hidden is not None:c.execute('UPDATE preferences SET hidden=? WHERE event_id=?',(int(body.hidden),event_id))
    return {'ok':True}
@app.get('/events/calendar.ics')
def calendar(request:Request,token:str='',favorites:bool=False,recommended:bool=False):
    if not read_session(request.cookies.get(COOKIE,'')) and not hmac.compare_digest(token,config().get('feed_token','__invalid__')):raise HTTPException(401,'日历订阅需要私人链接')
    return Response(make_calendar(events(favorites=favorites,recommended=recommended)),media_type='text/calendar; charset=utf-8',headers={'Content-Disposition':'attachment; filename="shenzhen-events.ics"'})
@app.get('/events/api/event/{event_id}.ics')
def one_event(event_id:str,request:Request):
    require(request);rows=[e for e in events() if e['id']==event_id]
    if not rows:raise HTTPException(404,'活动不存在或已经结束')
    return Response(make_calendar(rows),media_type='text/calendar; charset=utf-8',headers={'Content-Disposition':'attachment; filename="event.ics"'})
@app.get('/events')
def redirect():return RedirectResponse('/events/',status_code=308)
@app.get('/events/')
def index():return FileResponse(ROOT/'static/index.html')
app.mount('/events/static',StaticFiles(directory=ROOT/'static'),name='static')
