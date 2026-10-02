"""Bounded public-source adapters. Search results are leads, never verified events."""
from __future__ import annotations
import ipaddress, json, re, socket, time, warnings
from urllib.parse import urljoin, urlsplit, urlencode
import requests, feedparser
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from .core import clean, iso, date_range, canon_url, now, db, stamp, EVENT_TYPES
class SourceError(Exception): pass
class Blocked(SourceError): pass

def fetch(url, *, trusted_local=False, max_bytes=1600000, proxy=None, include_pagination=False):
    """No login scraping. Bounded time/size; public-only redirect validation."""
    session=requests.Session();session.trust_env=False
    if proxy:
        if proxy!="http://127.0.0.1:17890":raise SourceError("非允许的出口配置")
        session.proxies={"http":proxy,"https":proxy}
    for _ in range(5):
        p=urlsplit(url)
        if p.scheme not in ('http','https') or p.username or p.password:raise SourceError('不支持的链接')
        local=trusted_local and p.hostname=='127.0.0.1' and p.port==1200
        if not local:
            try:
                addresses={x[4][0] for x in socket.getaddrinfo(p.hostname,p.port or 443,type=socket.SOCK_STREAM)}
                if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):raise SourceError('拒绝非公网地址')
            except socket.gaierror:raise SourceError('DNS 解析失败')
        try:
            r=session.get(url,headers={'User-Agent':'Mozilla/5.0 (compatible; ShenzhenEvents/1.0; personal low-frequency aggregator)','Accept':'text/html,application/rss+xml,application/json;q=0.9'},timeout=(6,18),allow_redirects=False,stream=True)
            if r.status_code in (301,302,303,307,308):url=urljoin(url,r.headers.get('location',''));r.close();continue
            if r.status_code in (403,429):raise Blocked(f'来源限制访问（HTTP {r.status_code}），已退避')
            r.raise_for_status();buf=bytearray()
            for chunk in r.iter_content(16384):
                buf.extend(chunk)
                if len(buf)>max_bytes:raise SourceError('页面超过采集大小限制')
            r.close();html=bytes(buf).decode(r.encoding if r.encoding and r.encoding.lower()!='iso-8859-1' else 'utf-8','replace')
        except requests.RequestException as e:raise SourceError(('HTTP '+str(e.response.status_code)) if getattr(e,'response',None) is not None else type(e).__name__)
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore',category=XMLParsedAsHTMLWarning)
            soup=BeautifulSoup(html,'html.parser')
        title=clean(soup.title.get_text() if soup.title else '')
        if any(x in title.lower() for x in ['captcha','访问验证','安全验证','反爬','请输入验证码']) or '/antispider' in url:raise Blocked('来源要求验证码，未绕过验证')
        if include_pagination:
            return html,soup,url,{'total':r.headers.get('X-WP-Total'),'total_pages':r.headers.get('X-WP-TotalPages')}
        return html,soup,url
    raise SourceError('重定向次数超限')
def text(node):return clean(node.get_text(' ',strip=True)) if node else ''
def skeleton(title,url,summary='',location='',**kw):return {'title':title,'url':url,'summary':summary,'location':location,'start_at':None,'end_at':None,'all_day':False,**kw}

def jsonld(soup,url):
    out=[]
    def description(value):
        # Unlabelled descriptions are text: tag lessons and C++/Rust code use <>.
        # Extract HTML only when the structured value declares its representation.
        if isinstance(value,dict):
            content=value.get('text',value.get('value',''))
            if not isinstance(content,str):return ''
            if clean(value.get('encodingFormat')).split(';',1)[0].lower()=='text/html':
                return text(BeautifulSoup(content,'html.parser'))
            return clean(content)
        return clean(value) if isinstance(value,str) else ''
    def names(value):
        if isinstance(value,list):return ' / '.join(dict.fromkeys(n for v in value if (n:=names(v))))
        if isinstance(value,dict):return clean(value.get('name'))
        return clean(value) if isinstance(value,str) else ''
    def prices(value):
        from decimal import Decimal, InvalidOperation
        values=[]
        for offer in value if isinstance(value,list) else [value]:
            if not isinstance(offer,dict):continue
            currency=str(offer.get('priceCurrency') or 'CNY')
            for field in ('price','lowPrice','highPrice'):
                raw=offer.get(field)
                if raw is None or isinstance(raw,bool):continue
                try:amount=Decimal(str(raw))
                except InvalidOperation:continue
                if amount.is_finite() and amount>=0:values.append((currency,amount))
            values.extend(prices(offer.get('offers',[])))
        return values
    def walk(x):
        if isinstance(x,list):
            for a in x:walk(a)
        elif isinstance(x,dict):
            typ=x.get('@type','');types=typ if isinstance(typ,list) else [typ]
            normalized_types=[str(t).rsplit('/',1)[-1] for t in types]
            if any(t=='Event' or t in EVENT_TYPES for t in normalized_types) and x.get('name'):
                loc=x.get('location',{});loc=loc[0] if isinstance(loc,list) and loc else loc
                locality=''
                if isinstance(loc,dict) and isinstance(loc.get('address'),dict):locality=loc['address'].get('addressLocality','')
                if isinstance(loc,dict):
                    addr=loc.get('address',{});addr=' '.join(str(v) for k,v in addr.items() if k!='@type' and isinstance(v,str)) if isinstance(addr,dict) else str(addr)
                    loc=clean(str(loc.get('name',''))+' '+addr)
                org=names(x.get('organizer',{}));offer_prices=sorted(set(prices(x.get('offers',[]))))
                cost=' / '.join('免费' if amount==0 else currency+' '+format(amount.normalize(),'f') for currency,amount in offer_prices)
                if not cost:cost='免费' if x.get('isAccessibleForFree') is True else '收费（价格未注明）' if x.get('isAccessibleForFree') is False else '费用未注明'
                if x.get('isAccessibleForFree') is False and cost=='免费':cost='收费（含免费选项，价格未注明）'
                mode=str(x.get('eventAttendanceMode','')).rsplit('/',1)[-1]
                attendance={'OnlineEventAttendanceMode':'online','MixedEventAttendanceMode':'hybrid','OfflineEventAttendanceMode':'offline'}.get(mode)
                detail={'attendance':attendance} if attendance else {}
                if org:detail['organizer_role']='organizer'
                event_type=next((t for t in normalized_types if t in EVENT_TYPES and t!='Event'),'Event')
                out.append(skeleton(x['name'],x.get('url') or url,description(x.get('description','')),str(loc),start_at=iso(x.get('startDate')),end_at=iso(x.get('endDate')),organizer=org,city=locality,cost_text=cost,all_day=len(str(x.get('startDate','')))==10,status='cancelled' if 'Cancelled' in str(x.get('eventStatus','')) else 'scheduled',event_type=event_type,details=detail))
            for v in x.values():
                if isinstance(v,(dict,list)):walk(v)
    for script in soup.select('script[type="application/ld+json"]'):
        try:walk(json.loads(script.string or script.get_text()))
        except (ValueError,TypeError):pass
    return out

def lianpu(soup,url):
    out=[]
    for a in soup.select('article'):
        title=a.select_one('h3 a[href]');times=a.select('time[datetime]')
        if not title or not times:continue
        ps=a.select('p');loc=text(ps[-1]) if ps else ''
        # Admission is a standalone fee badge, never a title or gift slogan.
        fees=[text(n) for n in a.select('span') if not n.find_parent(['h3','p']) and not n.select('span') and re.fullmatch(r'(?:[￥¥]\s*\d[\d.,]*(?:\s*[-–]\s*[￥¥]?\s*[\d.,]+)?|免费)',text(n))]
        money=' / '.join(sorted(set(fees)))
        out.append(skeleton(text(title),urljoin(url,title['href']),text(ps[0]) if len(ps)>1 else '',loc,start_at=iso(times[0]['datetime']),end_at=iso(times[1]['datetime']) if len(times)>1 else None,organizer=' / '.join(text(x) for x in a.select('a[href^="/org/"]')),cost_text=money or '费用未注明'))
    return out

def bendibao(soup,url):
    out=[]
    for a in soup.select('.main-single-block[data-url]'):
        fields={text(label):text(label.parent).removeprefix(text(label)).strip() for label in a.select('.main-single-block-des')}
        title=text(a.select_one('.main-single-block-title'));start,end=date_range(fields.get('活动时间',''))
        if title:out.append(skeleton(title,urljoin(url,a['data-url']),fields.get('活动亮点',''),fields.get('活动地址',''),start_at=start,end_at=end,all_day=True,time_label=fields.get('活动时间','')))
    return out

def tech(soup,url):
    out=[]
    for a in soup.select('a[href^="/event/"]'):
        title=a.select_one('h3');loc=a.select_one('[i-carbon-location]');dt=a.select_one('[i-carbon-calendar]');org=a.select_one('[i-carbon-group]')
        if not title or not loc or '深圳' not in text(loc.parent):continue
        start,end=date_range(text(dt.parent) if dt else '')
        out.append(skeleton(text(title),urljoin(url,a['href']),text(a.select_one('p')),text(loc.parent),start_at=start,end_at=end,all_day=True,organizer=text(org.parent) if org else ''))
    return out

def chaihuo(soup,url):
    out=[]
    for a in soup.select('a[href*="/activity/poster"]'):
        t=text(a)
        if any(x in t for x in ['成都柴火','贵阳','河北柴火']):continue
        match=re.search(r'20\d\d/\d{2}/\d{2}',t)
        if not match:continue
        start,end=date_range(match[0]);h=a.select_one('h3,h2,h4,.title');img=a.select_one('img[alt]');title=text(h) or (img.get('alt','') if img else '') or t[:110]
        out.append(skeleton(title,urljoin(url,a['href']),t,'深圳 · 柴火创客（具体地址以原文为准）',start_at=start,end_at=end,all_day=True,organizer='柴火创客'))
    return out

def douban(soup,url):
    out=jsonld(soup,url)
    if out:return out
    for a in soup.select('li.list-entry,.event-item'):
        title=a.select_one('.title a[href],a[itemprop="url"]');start=a.select_one('[itemprop="startDate"]');end=a.select_one('[itemprop="endDate"]')
        if not title:continue
        def dt(n):return iso(n.get('content') or n.get('datetime')) if n else None
        out.append(skeleton(text(title),urljoin(url,title['href']),text(a),text(a.select_one('[itemprop="location"],.loc,.address')),start_at=dt(start),end_at=dt(end)))
    return out

def rss(source,html):
    parsed=feedparser.parse(html);out=[]
    for item in parsed.entries[:30]:
        title=clean(item.get('title'));summary=text(BeautifulSoup(item.get('summary',''),'html.parser'));u=canon_url(item.get('link',''))
        if not u:continue
        if source.get('scope')=='national' and '深圳' not in title+summary:continue
        e=skeleton(title,u,summary,organizer=item.get('author',''))
        if any(w in title for w in ['活动','工作坊','Meetup','Day','黑客松','报名','沙龙','大会','峰会']) and len(out)<8:
            try:
                _,s,final=fetch(u,max_bytes=1000000);ld=jsonld(s,final)
                if ld:e=ld[0]
                else:e['summary']=text(s.select_one('#js_content,#event_desc_page,article,main') or s)[:9000]
            except SourceError:pass
        e['published_at']=item.get('published','');out.append(e)
    return out

def sogou(source):
    keywords=source.get('queries') or ['深圳 创客 工作坊','深圳 机器人 活动','南山 开源 沙龙','深圳 AI 黑客松','深圳 嵌入式 技术交流','深圳 开发者 Meetup','深圳 硬件 开放日','深圳 汽车 科技 展览']
    keywords=[clean(x)[:100] for x in keywords if isinstance(x,str) and clean(x)][:40]
    if not keywords:return []
    # Discovery should favor the current season, not decade-old high-ranked posts.
    if source.get('current_year',True):
        keywords=[q if re.search(r'\b20\d{2}\b',q) else f'{q} {now().year}' for q in keywords]
    count=max(1,min(4,int(source.get('queries_per_run',2))))
    slot=(now().timetuple().tm_yday*4+now().hour//6)*count;out=[]
    for q in [keywords[(slot+i)%len(keywords)] for i in range(min(count,len(keywords)))]:
        url=source['url']+'?'+urlencode({'type':2,'query':q,'ie':'utf8'});_,s,_=fetch(url)
        if s.select_one('#seccodeImage,#seccodeInput'):raise Blocked('搜狗要求验证码，已停止此轮发现')
        for li in s.select('.news-list li')[:max(1,min(20,int(source.get('results_per_query',8))))]:
            a=li.select_one('h3 a[href]');author=li.select_one('.account,.s-p .all-time-y2,.s-p a');desc=li.select_one('.txt-info');name=text(author)
            if not a:continue
            link=urljoin(url,a['href']);out.append(skeleton(text(a),link,text(desc),'',details={'publisher':name}))
            if name:
                with db() as c:c.execute('INSERT INTO candidates(name,query,url,last_seen) VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET hits=hits+1,last_seen=excluded.last_seen,query=excluded.query,url=excluded.url',(name,q,link,stamp()))
        time.sleep(3)
    return out

def collect(source):
    if source['kind']=='sogou':return sogou(source)
    html,soup,url=fetch(source['url'],trusted_local=source['url'].startswith('http://127.0.0.1:1200/'))
    if source['kind']=='rss':return rss(source,html)
    fn={'lianpu':lianpu,'bendibao':bendibao,'tech':tech,'chaihuo':chaihuo,'douban':douban,'jsonld':jsonld}.get(source['kind']);items=fn(soup,url) if fn else []
    if not items:raise SourceError('网页可访问，但未提取到有效活动；保留上次数据')
    if source['kind']=='jsonld':items=[e for e in items if '深圳' in e['location'] or 'shenzhen' in e['location'].lower()]
    return items

