"""Optional AMap district enrichment. Never logs or exposes the private key."""
from __future__ import annotations
import argparse, json, re, time, threading
from datetime import datetime, timedelta
import requests
from rapidfuzz.fuzz import ratio
from . import core

GEOCODE_URL='https://restapi.amap.com/v3/geocode/geo'
PLACE_URL='https://restapi.amap.com/v5/place/text'
CACHE_DAYS=30
MIN_REQUEST_INTERVAL=0.8
_RATE_LOCK=threading.Lock()
_LAST_REQUEST=0.0
GENERIC_PHRASES=('具体地址报名后通知','具体地址将在报名','具体地址以原文为准','报名后可知详细地址','报名后可知看详细地址','报名后通知','报名后可查看详细地址','地址待定','地点待定')
FOREIGN_HINTS=('香港','澳门','广州','东莞','惠州','珠海','佛山','成都','重庆','北京','上海','Hong Kong','New Territories','Kowloon')
DISTRICT_ALIASES={'南山区':'南山','福田区':'福田','宝安区':'宝安','龙岗区':'龙岗','龙华区':'龙华','罗湖区':'罗湖','盐田区':'盐田','光明区':'光明','坪山区':'坪山','大鹏新区':'大鹏','深汕特别合作区':'深汕'}
ENGLISH_DISTRICTS={'nanshan':'南山','futian':'福田','baoan':'宝安',"bao'an":'宝安','longgang':'龙岗','longhua':'龙华','luohu':'罗湖','yantian':'盐田','guangming':'光明','pingshan':'坪山','dapeng':'大鹏'}

def key_path():return core.ROOT/'.private/amap.key'
def load_key():
    p=key_path()
    try:return p.read_text().strip()
    except OSError:return ''

def init_cache():
    with core.db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS geocode_cache(
            query TEXT PRIMARY KEY,district TEXT,adcode TEXT,lon TEXT,lat TEXT,
            method TEXT,status TEXT,resolved_name TEXT,checked_at TEXT
        )''')

def normalize_district(name,adcode=''):
    name=core.clean(name)
    if not str(adcode).startswith('4403'):return ''
    if name in DISTRICT_ALIASES:return DISTRICT_ALIASES[name]
    bare=name.removesuffix('区')
    return bare if bare in core.DISTRICTS else ''

def direct_district(text):
    text=core.clean(text)
    for alias,district in DISTRICT_ALIASES.items():
        if alias in text:return district
    for district in core.DISTRICTS:
        if district+'区' in text:return district
    low=text.casefold()
    for token,district in ENGLISH_DISTRICTS.items():
        if re.search(r'(?<![a-z])'+re.escape(token)+r'(?:\s+district)?(?![a-z])',low):return district
    return ''

def query_text(location):
    value=core.clean(location)
    if not value:return ''
    if any(x.casefold() in value.casefold() for x in FOREIGN_HINTS):return ''
    value=re.sub(r'^(?:广东省?)?[·\s/|,-]*深圳市?[·\s/|,-]+','',value,flags=re.I)
    if 'PostalAddress' in value:value=value.split('PostalAddress',1)[0]
    value=re.sub(r'[（(][^）)]*(?:报名(?:成功)?后|具体地址|以原文为准|待通知)[^）)]*[）)]','',value)
    value=core.clean(value.strip(' /·|-，,'))
    if not value or value in ('深圳','深圳市','广东深圳','广东·深圳','广东省深圳市'):return ''
    if any(value==x or (x in value and len(value)<=len(x)+4) for x in GENERIC_PHRASES):return ''
    if len(value)<3:return ''
    return value[:80]

def _request_json(url,params,session=None):
    global _LAST_REQUEST
    s=session or requests.Session();s.trust_env=False
    with _RATE_LOCK:
        wait=MIN_REQUEST_INTERVAL-(time.monotonic()-_LAST_REQUEST)
        if wait>0:time.sleep(wait)
        _LAST_REQUEST=time.monotonic()
    try:r=s.get(url,params=params,timeout=(3,8))
    except requests.RequestException as exc:return None,'network_'+type(exc).__name__
    if r.status_code!=200:return None,'http_'+str(r.status_code)
    try:data=r.json()
    except ValueError:return None,'invalid_json'
    if data.get('status')!='1':return None,'amap_'+str(data.get('infocode') or 'error')
    return data,''

def _cache_get(query):
    init_cache()
    with core.db() as c:row=c.execute('SELECT * FROM geocode_cache WHERE query=?',(query,)).fetchone()
    if not row:return None
    row=dict(row)
    try:fresh=core.now()-datetime.fromisoformat(row['checked_at'])<timedelta(days=CACHE_DAYS)
    except (TypeError,ValueError):fresh=False
    return row if fresh else None

def _cache_put(query,result):
    init_cache()
    with core.db() as c:
        c.execute('''INSERT INTO geocode_cache(query,district,adcode,lon,lat,method,status,resolved_name,checked_at)
        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(query) DO UPDATE SET
        district=excluded.district,adcode=excluded.adcode,lon=excluded.lon,lat=excluded.lat,
        method=excluded.method,status=excluded.status,resolved_name=excluded.resolved_name,checked_at=excluded.checked_at''',
        (query,result.get('district',''),result.get('adcode',''),result.get('lon',''),result.get('lat',''),result.get('method',''),result.get('status',''),result.get('resolved_name',''),core.stamp()))

def _coords(value):
    try:
        lon,lat=(value or '').split(',',1)
        float(lon);float(lat);return lon,lat
    except (ValueError,AttributeError):return '',''

def _from_geocode(data):
    geocodes=data.get('geocodes') or []
    districts={normalize_district(g.get('district',''),g.get('adcode','')) for g in geocodes}
    districts.discard('')
    if len(districts)>1:return None
    for g in geocodes:
        district=normalize_district(g.get('district',''),g.get('adcode',''))
        if district:
            lon,lat=_coords(g.get('location'))
            return {'status':'ok','district':district,'adcode':str(g.get('adcode','')),'lon':lon,'lat':lat,'method':'geocode','resolved_name':core.clean(g.get('formatted_address'))[:200]}
    return None

def english_heavy(query):
    letters=sum(1 for ch in query if ch.isascii() and ch.isalpha())
    han=len(re.findall(r'[㐀-鿿]',query))
    return letters>=6 and letters>han*2

def _poi_score(query,poi):
    q=core.norm(query);name=core.norm(poi.get('name',''));address=core.norm(poi.get('address',''))
    if not q or not name:return 0
    if q==name:return 100
    if q in name or name in q:return 92
    score=ratio(q,name)
    if address and (q in address or address in q):score=max(score,85)
    return score

def _from_poi(query,data):
    ranked=[]
    for poi in data.get('pois') or []:
        district=normalize_district(poi.get('adname',''),poi.get('adcode',''))
        if not district:continue
        city=core.clean(poi.get('cityname'))
        if city and '深圳' not in city:continue
        ranked.append((_poi_score(query,poi),poi,district))
    if not ranked:return None
    ranked.sort(key=lambda x:x[0],reverse=True);score,poi,district=ranked[0]
    if score<58:
        same={x[2] for x in ranked}
        if not (english_heavy(query) and len(ranked)>=2 and len(same)==1):return None
    if len(ranked)>1 and ranked[1][0]>=score-3 and ranked[1][2]!=district:return None
    lon,lat=_coords(poi.get('location'))
    return {'status':'ok','district':district,'adcode':str(poi.get('adcode','')),'lon':lon,'lat':lat,'method':'poi','resolved_name':core.clean(poi.get('name'))[:200]}

def resolve_location(location,session=None,use_cache=True):
    if any(x.casefold() in core.clean(location).casefold() for x in FOREIGN_HINTS):return {'status':'skipped','district':'','method':'skip'}
    direct=direct_district(location)
    if direct:return {'status':'ok','district':direct,'adcode':'','lon':'','lat':'','method':'text','resolved_name':''}
    query=query_text(location)
    if not query:return {'status':'skipped','district':'','method':'skip'}
    if use_cache:
        cached=_cache_get(query)
        if cached:return cached
    key=load_key()
    if not key:return {'status':'disabled','district':'','method':'no_key'}
    if not english_heavy(query):
        params={'key':key,'address':query,'city':'深圳'}
        data,error=_request_json(GEOCODE_URL,params,session)
        if data:
            result=_from_geocode(data)
            if result:_cache_put(query,result);return result
        elif error and not error.startswith('amap_3'):
            return {'status':'error','district':'','method':'geocode','error':error}
    params={'key':key,'keywords':query,'region':'深圳市','city_limit':'true','page_size':3}
    data,error=_request_json(PLACE_URL,params,session)
    if data:
        result=_from_poi(query,data)
        if result:_cache_put(query,result);return result
        result={'status':'not_found','district':'','method':'poi'}
        _cache_put(query,result);return result
    if error:return {'status':'error','district':'','method':'poi','error':error}
    result={'status':'not_found','district':'','method':'poi'}
    _cache_put(query,result);return result

def enrich_pending(limit=30,apply=True,sleep_seconds=0):
    init_cache();stats={'enabled':bool(load_key()),'examined':0,'resolved':0,'updated':0,'skipped':0,'not_found':0,'errors':0,'methods':{},'error_types':{}}
    if not stats['enabled']:return stats
    with core.db() as c:
        cutoff=(core.now()-timedelta(days=90)).isoformat(timespec='seconds')
        c.execute('DELETE FROM geocode_cache WHERE checked_at<?',(cutoff,))
        rows=[dict(x) for x in c.execute("SELECT id,title,location,district FROM events WHERE district=? AND trim(location)<>'' ORDER BY COALESCE(start_at,'9999'),id LIMIT ?",('待确认',10000))]
    session=requests.Session();session.trust_env=False;consecutive_errors=0
    attempts=0
    for row in rows:
        query=query_text(row['location'])
        if not query:stats['skipped']+=1;continue
        cached=_cache_get(query)
        if cached and cached.get('status')=='not_found':stats['not_found']+=1;continue
        if attempts>=max(1,int(limit)):stats['remaining']=True;break
        attempts+=1
        stats['examined']+=1
        result=resolve_location(row['location'],session=session)
        status=result.get('status')
        if status=='ok':
            stats['resolved']+=1;method=result.get('method','');stats['methods'][method]=stats['methods'].get(method,0)+1
            if apply and result.get('district'):
                with core.db() as c:
                    cur=c.execute("UPDATE events SET district=? WHERE id=? AND district=? AND location=?",(result['district'],row['id'],'待确认',row['location']))
                    stats['updated']+=cur.rowcount
        elif status=='skipped':stats['skipped']+=1
        elif status=='not_found':stats['not_found']+=1
        elif status=='error':
            stats['errors']+=1;consecutive_errors+=1;code=result.get('error','unknown');stats['error_types'][code]=stats['error_types'].get(code,0)+1
            if code.startswith(('network_','http_','amap_100','amap_400')) or consecutive_errors>=3:
                stats['stopped']=code;break
        else:consecutive_errors=0
        if status!='error':consecutive_errors=0
        if result.get('method') in ('geocode','poi') and sleep_seconds:time.sleep(sleep_seconds)
    return stats

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=100);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    core.init();result=enrich_pending(args.limit,args.apply)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
