"""Measured, resumable public-source collection. Counters describe observed scope, not the entire web."""
from __future__ import annotations
import hashlib, json, math, re, time
from collections import Counter
from datetime import date, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
import feedparser
from bs4 import BeautifulSoup
from . import core, collectors as c, details, official_sources, aggregates, source_fields, recurring_sources


OBSERVATION_FIELDS=('pages_visited','visible','extracted','unique','shenzhen_candidates','admitted',
    'duplicates','parser_unaccounted','detail_attempted','detail_resolved','detail_failed','detail_deferred','detail_cached')


def fresh_coverage(source, attempt_started_at=None, available=False):
    """Create current-attempt evidence, never reuse previous sample counters."""
    return dict(version=1,mode=source.get('coverage_mode','single_page'),
        counters_available=available,attempt_started_at=attempt_started_at or core.stamp(),sampled_at=None,
        page_urls=[],source_total=None,rejected={} if available else None,
        truncated=not available,next_cursor=None,reasons=[],complete_scope=False,
        traversal_from_root=True,structure_recognized=False,
        **{key:0 if available else None for key in OBSERVATION_FIELDS})


def finalize(metrics, status, error=''):
    """Completion describes the final status and all measured pending work."""
    error=error or metrics.get('error','')
    blockers=[]
    if not metrics.get('counters_available') or not metrics.get('pages_visited'):blockers.append('本轮观测计数不可用')
    if not metrics.get('structure_recognized'):blockers.append('未确认来源列表结构')
    if not metrics.get('traversal_from_root',False):blockers.append('本轮仅检查续页，不能确认来源全量')
    if metrics.get('mode') not in ('city_pages','page_inventory'):blockers.append('当前采集模式不声明全量覆盖')
    if error:blockers.append(error)
    if metrics.get('truncated') or metrics.get('next_cursor'):blockers.append('仍有未完成的列表工作')
    if metrics.get('parser_unaccounted'):blockers.append('可见条目与解析量不符，需检查适配器')
    if metrics.get('detail_failed'):blockers.append('详情读取失败，待后续重试')
    if metrics.get('detail_deferred'):blockers.append('详情工作仍待处理或处于退避期')
    if metrics.get('source_total') is not None and not metrics.get('source_total_reconciled'):
        blockers.append('声明总量尚未与来源条目核对')
    if status=='ok' and blockers:status='partial'
    metrics['complete_scope']=status=='ok' and not blockers
    for reason in blockers:
        if reason not in metrics['reasons']:metrics['reasons'].append(reason)
    return status


def sample_projection(metrics, status):
    fields=(*OBSERVATION_FIELDS,'page_urls','source_total','rejected','mode','sampled_at','attempt_started_at',
        'counters_available','complete_scope','source_total_basis','source_total_observed','source_total_gap',
        'source_total_comparable','source_total_reconciled','truncated','next_cursor')
    return {**{key:metrics.get(key) for key in fields},'status':status}


def previous_sample(previous, health):
    """Keep a dated readable sample; legacy provenance is explicitly limited."""
    prior=previous.get('last_good')
    candidate=prior if isinstance(prior,dict) else previous
    if candidate.get('counters_available') is False:return None
    if candidate.get('visible') is None and candidate.get('admitted') is None:return None
    sampled_at=candidate.get('sampled_at') or health.get('last_success')
    if not sampled_at:return None
    status=candidate.get('status') or (health.get('status') if candidate is previous else 'unknown')
    legacy=bool(candidate.get('legacy') or not candidate.get('sampled_at') or candidate.get('counters_available') is not True)
    sample=sample_projection(candidate,status)
    if legacy:
        sample.update(sampled_at=sampled_at,legacy=True,counters_available=True,complete_scope=False)
        if status in ('error','blocked'):sample['status']='unknown'
    elif status not in ('ok','partial','empty'):sample['complete_scope']=False
    return sample


def set_query(url, **values):
    p=urlsplit(url);q=dict(parse_qsl(p.query));q.update({k:str(v) for k,v in values.items()})
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),''))


def canonical(url):
    p=urlsplit(core.canon_url(url));q=[(k,v) for k,v in parse_qsl(p.query) if k not in ('qd','fr','icn')]
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(q),''))


def city_evidence(e, source):
    """Prefer structured venue locality, then location. No title-only national prefilter."""
    loc=core.clean(e.get('location')); explicit=core.clean(e.get('city'))
    combined=(explicit+' '+loc).casefold().replace('shen zhen','shenzhen')
    if '深圳' in combined or 'shenzhen' in combined:return '深圳'
    if explicit and explicit not in ('未知','待确认'):return explicit
    if any(x in combined for x in ('香港','澳门','hong kong','new territories','kowloon')):return '外市'
    if any(x in loc for x in ('北京市','上海市','广州市','东莞市','成都市','贵阳市','杭州市')):return '外市'
    if source.get('city_scope')=='深圳':return '深圳'
    return '待确认'


def hdx(soup,url):
    out=[]
    for node in soup.select('.search-tab-content-item'):
        a=node.select_one('.item-title[href]')
        if not a:continue
        label=c.text(node.select_one('.item-data'));start,end=core.date_range(label)
        loc=c.text(node.select_one('.item-dress'))
        out.append(c.skeleton(c.text(a),urljoin(url,a['href']),c.text(a),loc,
            start_at=start,end_at=end,all_day=True,time_label=label,
            organizer=c.text(node.select_one('.user-name')),details={'publisher':c.text(node.select_one('.user-name')),'organizer_role':'publisher'}))
    return out


def douban_all(soup,url):
    out=[]
    for n in soup.select('li.list-entry,.event-item'):
        title=n.select_one('.title a[href],.event-title a[href],a[itemprop="url"]')
        if not title:continue
        link=urljoin(url,title['href'])
        if not re.match(r'^/event/\d+/?$',urlsplit(link).path):continue
        def when(prop):
            v=n.select_one('[itemprop="'+prop+'"]')
            return core.iso(v.get('content') or v.get('datetime')) if v else None
        start,end=when('startDate'),when('endDate');fields=source_fields.inline_fields(c.text(n))
        typ=source_fields.obvious_type(c.text(title)) or 'Event'
        out.append(c.skeleton(c.text(title),link,c.text(n),c.text(n.select_one('[itemprop="location"],.loc,.address')) or fields.get('location',''),
            start_at=start,end_at=end,city='深圳',cost_text=fields.get('cost_text',''),event_type=typ,
            details={'publisher':fields.get('publisher',''),'type_evidence':'标题明确演出形式' if typ!='Event' else ''},detail_candidate=not start))
    return out

def microdata_detail(soup,url):
    start=soup.select_one('[itemprop="startDate"]')
    if not start:return []
    date=core.iso(start.get('content') or start.get('datetime'))
    if not date:return []
    end=soup.select_one('[itemprop="endDate"]');loc=soup.select_one('[itemprop="location"]')
    title=soup.select_one('h1,[itemprop="name"]')
    if not title:return []
    return [c.skeleton(c.text(title),url,c.text(soup.select_one('#event_desc_page,.related_info,article,main') or soup)[:9000],c.text(loc),
        start_at=date,end_at=core.iso(end.get('content') or end.get('datetime')) if end else None,
        all_day=len(str(start.get('content') or start.get('datetime')))==10)]


def tech_all(soup,url):
    out=[]
    for node in soup.select('a[href^="/event/"]'):
        title=node.select_one('h3');loc=node.select_one('[i-carbon-location]');dt=node.select_one('[i-carbon-calendar]');org=node.select_one('[i-carbon-group]')
        if not title:continue
        city=c.text(loc.parent) if loc else '';start,end=core.date_range(c.text(dt.parent) if dt else '')
        form=c.text(node.select_one('h3 + span'));mode='hybrid' if '线上+线下' in form else 'online' if form=='线上' else 'offline' if form=='线下' else 'unknown'
        out.append(c.skeleton(c.text(title),urljoin(url,node['href']),c.text(node.select_one('p')),city,
            start_at=start,end_at=end,all_day=True,city=city,organizer=c.text(org.parent) if org else '',details={'attendance':mode}))
    return out


def next_page(soup,url,kind):
    """Follow observed paging metadata only; never guess endless page numbers."""
    if kind=='shenzhenware_events':
        # Verified source pagination contract; only regular rows advance the cursor.
        if not recurring_sources.regular_urls(soup,url):return None,None
        try:page=int(dict(parse_qsl(urlsplit(url).query)).get('page',1))
        except ValueError:raise c.SourceError('深圳湾分页游标无效')
        return (set_query(url,page=page+1) if 0<page<100 else None),None
    if kind=='devevents':
        button=soup.select_one('button.moreButton[hx-vals]');total_match=re.search(r'showing\s+\d+\s+out of\s+(\d+)',c.text(soup),re.I)
        total=int(total_match[1]) if total_match else None
        if button:
            try:
                page=int(json.loads(button['hx-vals'])['page']);nxt=set_query(url,page=page)
                if 1<page<=500:return nxt,total
            except (ValueError,TypeError,KeyError):pass
        return None,total
    if kind=='hdx':
        script=' '.join(x.get_text() for x in soup.select('script:not([src])'))
        m=re.search(r"elem:\s*['\"]pagination['\"].*?count:\s*(\d+).*?limit:\s*(\d+).*?curr:\s*(\d+)",script,re.S)
        if not m:return None,None
        total,size,page=map(int,m.groups())
        return (set_query(url,page=page+1) if size and page*size<total else None),total
    selector='.paginator a[href]' if kind=='douban' else 'a[href]'
    names=('下一页','下页','后页>','next','下一頁')
    for a in soup.select(selector):
        label=c.text(a).casefold()
        if label not in names and 'next' not in (a.get('rel') or []):continue
        nxt=urljoin(url,a['href']);old,new=urlsplit(url),urlsplit(nxt)
        if old.netloc==new.netloc and old.path.rstrip('/')==new.path.rstrip('/'):return nxt,None
    return None,None


def _douban_card(node, url):
    a=node.select_one('.title a[href],.event-title a[href],a[itemprop="url"]')
    if not a:return None
    link=urlsplit(urljoin(url,a['href']))
    if re.match(r'^/event/\d+/?$',link.path):return 'event'
    if link.hostname=='site.douban.com' and re.fullmatch(r'/\d+/?',link.path):return 'organizer'
    return None


def _developer_inventory(soup):
    rows=soup.select('.row:not(.featured)')
    excluded=Counter();comparable=True;recognized=False
    for row in rows:
        scripts=row.select('script[type="application/ld+json"]')
        if len(scripts)!=1:comparable=False;continue
        try:data=json.loads(scripts[0].get_text())
        except ValueError:continue
        if not isinstance(data,dict) or data.get('@type')!='Event':continue
        recognized=True
        mode=data.get('eventAttendanceMode')
        if mode not in ('https://schema.org/OnlineEventAttendanceMode','https://schema.org/MixedEventAttendanceMode'):
            excluded['不支持的活动形式']+=1;continue
        try:
            start=date.fromisoformat(str(data.get('startDate',''))[:10])
            end=date.fromisoformat(str(data.get('endDate') or data.get('startDate'))[:10])
            valid=end>=start and core.clean(data.get('name')) and core.canon_url(data.get('url',''))
        except ValueError:valid=False
        if not valid:excluded['日期或链接信息不足']+=1
    return len(rows),dict(excluded),recognized,comparable


def _recognized_page(source, soup, url, items):
    kind=source['kind']
    if kind=='douban':return any(_douban_card(n,url) for n in soup.select('li.list-entry,.event-item'))
    if kind=='devevents':return _developer_inventory(soup)[2]
    return bool(items) or kind in ('rss','wordpress_events',*recurring_sources.KINDS)


def parse_page(source,html,soup,url):
    kind=source['kind']
    if kind in recurring_sources.KINDS:return recurring_sources.parse(kind,html,soup,url)
    if kind=='wordpress_events':return aggregates.wordpress_posts(html,url,source)
    if kind=='szhzfw':
        items=aggregates.monthly_events(soup,url);return items,len(items),{}
    fn={'devevents':aggregates.developer_events,'szcec':official_sources.szcec,'cioe':official_sources.cioe,'lianpu':c.lianpu,'douban':douban_all,'bendibao':c.bendibao,'chaihuo':c.chaihuo,'jsonld':c.jsonld,'tech':tech_all,'hdx':hdx}.get(kind)
    if not fn:raise c.SourceError('来源类型尚未适配')
    items=fn(soup,url)
    selectors={'lianpu':'article','douban':'li.list-entry','bendibao':'.main-single-block[data-url]','chaihuo':'a[href*="/activity/poster"]','tech':'a[href^="/event/"]','hdx':'.search-tab-content-item'}
    visible=len(soup.select(selectors[kind])) if kind in selectors else len(items)
    excluded={}
    if kind=='devevents':visible,excluded,_,_=_developer_inventory(soup)
    if kind=='chaihuo':
        excluded['其他城市']=sum(any(w in c.text(n) for w in ('成都柴火','贵阳','河北柴火')) for n in soup.select(selectors[kind]))
    # Some markup contains JSON-LD/sidebars as well as main list rows. Never invent a denominator.
    if kind=='douban':
        visible=len(soup.select('li.list-entry,.event-item'))
        excluded['非活动主办方卡片']=sum(_douban_card(n,url)=='organizer' for n in soup.select('li.list-entry,.event-item'))
    return items,visible,excluded


def _detail_fingerprint(e):
    return hashlib.sha256((e.get('title','')+'|'+e.get('summary','')).encode()).hexdigest()


def _detail_fields_valid(fields):
    """Check the nested containers and scalars consumed by detail merging."""
    if not isinstance(fields,dict):return False
    scalar=('cost_text','organizer','location','start_at','end_at','attendance','organizer_role','publisher','evidence_url','detail_text','checked_at')
    if any(fields.get(key) is not None and not isinstance(fields[key],str) for key in scalar):return False
    if 'all_day' in fields and type(fields['all_day']) is not bool:return False
    if 'details' in fields and not _detail_fields_valid(fields['details']):return False
    if 'field_provenance' in fields:
        provenance=fields['field_provenance']
        if not isinstance(provenance,dict):return False
        for evidence in provenance.values():
            if not isinstance(evidence,dict) or not isinstance(evidence.get('kind'),str) or not evidence['kind']:return False
            if 'evidence_url' in evidence and not isinstance(evidence['evidence_url'],str):return False
    return True


def _detail_observation(payload):
    """Legacy whole-event payloads and malformed envelopes are safe misses."""
    try:value=json.loads(payload)
    except (ValueError,TypeError):return None
    if not isinstance(value,dict) or value.get('kind')!='detail_observation' or type(value.get('version')) is not int or value.get('version')!=1:return None
    if not all(_detail_fields_valid(value.get(key)) for key in ('structured','metadata')):return None
    return value


def enrich_details(source, items, metrics):
    """A persistent rotating queue, not the first eight entries on every run."""
    if not items:return items
    if source.get('kind') in recurring_sources.KINDS:
        return recurring_sources.enrich_details(source,items,metrics,c.fetch)
    limit=max(0,min(100,int(source.get('detail_budget',12))))
    pending=[];out=[]
    with core.db() as db:
        cache={r['url']:dict(r) for r in db.execute('SELECT * FROM detail_cache WHERE source_id=?',(source['id'],))}
    for e in items:
        key=canonical(e['url']);e['url']=key;old=cache.get(key);fp=_detail_fingerprint(e)
        if e.get('start_at') and not source.get('enrich_dated',False):
            out.append(e);continue
        observation=_detail_observation(old['payload']) if old and old['payload'] else None
        if old and old['fingerprint']==fp and old['next_attempt']>core.stamp() and (not old['payload'] or observation):
            if old['payload']:
                e=details.merge(e,observation['structured'],observation['metadata'])
                metrics['detail_cached']+=1
            else:metrics['detail_deferred']+=1
            out.append(e);continue
        pending.append((old['checked_at'] if old else '',len(out),e,fp));out.append(e)
    pending.sort(key=lambda x:x[0])
    for _,idx,e,fp in pending[:limit]:
        if time.monotonic()>source.get('_deadline',float('inf')):break
        metrics['detail_attempted']+=1;status='no_date';payload=''
        try:
            html,soup,url=c.fetch(e['url'],max_bytes=1000000,proxy=source.get('proxy'))
            meta=details.extract(soup,url)
            values=c.jsonld(soup,url) or microdata_detail(soup,url)
            chosen=None
            if values:
                chosen=next((v for v in values if canonical(v['url'])==e['url']),values[0] if len(values)==1 else None)
            out[idx]=details.merge(e,chosen or {},meta)
            payload=json.dumps({'kind':'detail_observation','version':1,'structured':chosen or {},'metadata':meta},ensure_ascii=False)
            if out[idx].get('start_at'):metrics['detail_resolved']+=1;status='ok'
        except c.SourceError as exc:
            status='blocked' if isinstance(exc,c.Blocked) else 'error';metrics['detail_failed']+=1
        retry=core.now()+timedelta(hours=24 if payload else 6)
        with core.db() as db:
            db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id,url) DO UPDATE SET fingerprint=excluded.fingerprint,payload=excluded.payload,status=excluded.status,checked_at=excluded.checked_at,next_attempt=excluded.next_attempt',
                (source['id'],e['url'],fp,payload,status,core.stamp(),core.iso(retry)))
        if status=='blocked':break
        time.sleep(float(source.get('request_delay',.5)))
    metrics['detail_deferred']+=max(0,len(pending)-metrics['detail_attempted'])
    return out


def rss_page(source, html, metrics):
    feed=feedparser.parse(html);entries=list(feed.entries);metrics['feed_total']=len(entries)
    cap=max(1,min(5000,int(source.get('max_entries',500))))
    if len(entries)>cap:metrics['truncated']=True;metrics['reasons'].append('订阅条目达到本轮上限')
    out=[]
    for item in entries[:cap]:
        url=canonical(item.get('link',''))
        if not url:continue
        e=c.skeleton(core.clean(item.get('title')),url,c.text(BeautifulSoup(item.get('summary',''),'html.parser')),organizer=item.get('author',''))
        e['published_at']=item.get('published','');out.append(e)
    return out,len(entries),{}


def collect_report(source, previous=None):
    started=time.monotonic();previous=previous or {};kind=source['kind']
    metrics=fresh_coverage(source,available=True);metrics['counters_available']=False
    rows={};rejects=Counter();seen_pages=set();signatures=set()
    max_pages=max(1,min(300,int(source.get('max_pages',1))));max_entries=max(1,min(5000,int(source.get('max_entries',5000))))
    max_seconds=max(5,min(360,float(source.get('max_seconds',180))))
    if kind in recurring_sources.KINDS:max_pages=min(max_pages,5)
    deadline=started+max_seconds
    url=source['url'];cursor=previous.get('next_cursor');monthly_queue=[];monthly_eligible=[];monthly_visited=[]
    if kind=='wordpress_events':url=set_query(url,after=(core.now()-timedelta(days=120)).strftime('%Y-%m-%dT00:00:00'))
    if cursor:
        a,b=urlsplit(url),urlsplit(cursor)
        if a.netloc==b.netloc and a.path==b.path:
            url=cursor;metrics['traversal_from_root']=False;metrics['reasons'].append('接续上轮分页')
    error='';blocked=False
    for page in range(max_pages):
        if time.monotonic()-started>=max_seconds:
            metrics['truncated']=True;metrics['next_cursor']=url;metrics['reasons'].append('到达本轮时间上限');break
        if url in seen_pages:
            metrics['truncated']=True;metrics['reasons'].append('检测到重复分页链接');break
        seen_pages.add(url)
        try:
            if kind=='sogou':
                items=c.sogou(source);visible=len(items);excluded={};nxt=None;total=None
                recognized=bool(items)
            else:
                if kind=='wordpress_events':
                    html,soup,final,pagination=c.fetch(url,proxy=source.get('proxy'),include_pagination=True)
                elif kind in recurring_sources.KINDS:
                    html,soup,final=recurring_sources.bounded_fetch(c.fetch,url,source,deadline,metrics)
                else:html,soup,final=c.fetch(url,trusted_local=url.startswith('http://127.0.0.1:1200/'),proxy=source.get('proxy'))
                if kind=='szhzfw' and urlsplit(url).path==urlsplit(source['url']).path:
                    monthly_eligible=aggregates.monthly_links(soup,final)
                    monthly_queue=monthly_eligible[:4];items=[];visible=0;excluded={}
                    metrics.update(monthly_eligible_urls=monthly_eligible,monthly_selected_urls=monthly_queue.copy())
                    recognized=bool(monthly_eligible)
                elif kind=='xuanwu_activity':
                    module_url=recurring_sources.discover_module(soup,final)
                    recurring_sources.pause(source,deadline)
                    module,module_soup,module_final=recurring_sources.bounded_fetch(c.fetch,module_url,source,deadline,metrics,max_bytes=1000000)
                    if module_final!=module_url:raise c.SourceError('旋武活动模块跳转不匹配')
                    metrics['inventory_module_url']=module_url
                    items,visible,excluded=parse_page(source,module,module_soup,module_final)
                    metrics['source_total']=visible
                    recognized=True
                else:items,visible,excluded=rss_page(source,html,metrics) if kind=='rss' else parse_page(source,html,soup,final)
                if not (kind=='szhzfw' and urlsplit(url).path==urlsplit(source['url']).path) and kind!='xuanwu_activity':
                    recognized=_recognized_page(source,soup,final,items)
                if kind=='devevents':
                    metrics['source_total_comparable']=metrics.get('source_total_comparable',True) and _developer_inventory(soup)[3]
                nxt,total=next_page(soup,final,kind) if kind in ('lianpu','douban','hdx','devevents','elecfans_webinar','shenzhenware_events') else (None,None)
                if kind=='szhzfw':nxt=monthly_queue.pop(0) if monthly_queue else None
                if kind=='wordpress_events':
                    try:
                        total=int(pagination.get('total'));pages=int(pagination.get('total_pages'));current=int(dict(parse_qsl(urlsplit(url).query)).get('page',1))
                        nxt=set_query(url,page=current+1) if current<pages else None
                    except (ValueError,TypeError):
                        metrics['truncated']=True;metrics['reasons'].append('公开接口未提供可靠分页总数，未猜测后续页')

                if not items and kind=='hdx' and ('login' in final.lower() or ('登录' in c.text(soup) and not soup.select_one('.search-tab-content-list'))):
                    metrics['access_boundary']=url
                    raise c.Blocked('后续分页要求登录；已保留公开可读页，未绕过访问限制')
                if not items and kind in recurring_sources.KINDS:
                    # The source-specific parser has already validated the inventory shape.
                    metrics['recognized_empty']=True
                elif not items and not recognized:
                    raise c.SourceError('页面可访问但解析为空')
            metrics['pages_visited']+=1;metrics['page_urls'].append(url);metrics['visible']+=visible;metrics['extracted']+=len(items)
            metrics['counters_available']=True;metrics['sampled_at']=core.stamp()
            metrics['structure_recognized']=recognized and (metrics['structure_recognized'] or metrics['pages_visited']==1)
            if kind=='szhzfw' and url in monthly_eligible:monthly_visited.append(url)
            if total is not None:
                if metrics['source_total'] is not None and metrics['source_total']!=total:
                    metrics['source_total_comparable']=False
                metrics['source_total']=total
            rejects.update(excluded)
            metrics['parser_unaccounted']+=max(0,visible-len(items)-sum(excluded.values()))
            signature=(tuple(sorted(recurring_sources.regular_urls(soup,final))) if kind=='shenzhenware_events'
                       else tuple(sorted(canonical(e['url']) for e in items)))
            if signature and signature in signatures:
                metrics['truncated']=True;metrics['reasons'].append('分页返回重复内容');break
            signatures.add(signature)
            for e in items:
                key=canonical(e['url']);e['url']=key
                if key in rows:
                    metrics['duplicates']+=1
                    if e.get('start_at') and not rows[key].get('start_at'):rows[key]=e
                else:rows[key]=e
            if len(rows)>=max_entries:
                metrics['truncated']=True;metrics['reasons'].append('到达本轮条目上限');metrics['next_cursor']=nxt;break
            if not nxt:break
            metrics['next_cursor']=nxt;url=nxt
            if page+1==max_pages:metrics['truncated']=True;metrics['reasons'].append('到达本轮分页上限');break
            if kind in recurring_sources.KINDS:recurring_sources.pause(source,deadline)
            else:time.sleep(float(source.get('request_delay',.5)))
        except c.SourceError as exc:
            error=str(exc);blocked=isinstance(exc,c.Blocked)
            metrics['reasons'].append(error);metrics['truncated']=True;metrics['next_cursor']=url if metrics['pages_visited'] else None;break
    else:metrics['truncated']=True
    if metrics.get('access_boundary'):
        metrics['next_cursor']=None
        metrics['reasons'].append('下轮更新公开页；登录后内容不计为已覆盖')
    if monthly_eligible:
        deferred=[link for link in monthly_eligible if link not in monthly_visited]
        metrics.update(monthly_eligible=len(monthly_eligible),monthly_selected=len(metrics['monthly_selected_urls']),
            monthly_visited=len(monthly_visited),monthly_deferred=len(deferred),
            monthly_visited_urls=monthly_visited,monthly_deferred_urls=deferred)
        if deferred:
            metrics['truncated']=True
            metrics['reasons'].append(f'发现 {len(monthly_eligible)} 个月，已检查 {len(monthly_visited)} 个，{len(deferred)} 个因四月上限或本轮预算待处理')
        # The existing resume guard cannot honor a monthly URL with a different path.
        metrics['next_cursor']=None
    if not metrics['truncated']:metrics['next_cursor']=None
    items=list(rows.values())[:max_entries];metrics['unique']=len(items)
    if kind in ('rss','douban','sogou') or source.get('enrich_dated',False):items=enrich_details({**source,'_deadline':deadline},items,metrics)
    if kind in recurring_sources.KINDS and metrics.get('detail_blocked'):
        error='来源详情限制访问，已退避并保留已读取的列表'
        blocked=True
    admitted=[]
    for e in items:
        mode=core.event_attendance(e);online=mode in ('online','hybrid') and source.get('allow_online',False)
        city='深圳' if online else city_evidence(e,source)
        if kind in recurring_sources.KINDS and not online and city!='深圳':
            rejects['城市尚未确认' if city=='待确认' else '其他城市']+=1;continue
        if city not in ('深圳','待确认'):rejects['其他城市']+=1;continue
        if city=='待确认' and source.get('scope')=='national':
            if '深圳' not in (e.get('title','')+e.get('summary','')) and 'shenzhen' not in (e.get('title','')+e.get('summary','')).casefold():rejects['城市尚未确认']+=1;continue
            e['status']='needs_review';e['start_at']=None;e['end_at']=None
        if city=='待确认' and kind=='jsonld':rejects['城市尚未确认']+=1;continue
        e['city']=(e.get('city') or '线上') if online else '深圳';metrics['shenzhen_candidates']+=int(not online)
        if online:metrics['online_candidates']=metrics.get('online_candidates',0)+1
        end=e.get('end_at') or e.get('start_at')
        if end and end<core.iso(core.now()-timedelta(days=45)):rejects['超出历史保留期']+=1;continue
        if not e.get('start_at') and len(e.get('summary',''))<40 and not e.get('detail_candidate'):rejects['线索信息不足']+=1;continue
        e.pop("detail_candidate",None)
        if not core.normalize_event(e):rejects['无有效标题或链接']+=1;continue
        admitted.append(e)
    metrics['admitted']=len(admitted);metrics['rejected']=dict(rejects)
    if metrics['source_total'] is not None:
        bases={'devevents':'ordinary_nonfeatured_inventory_rows','hdx':'source_list_rows',
            'wordpress_events':'source_post_rows','xuanwu_activity':'validated_module_rows'}
        metrics['source_total_basis']=bases.get(kind,'unknown')
        comparable=kind in bases and metrics.get('source_total_comparable',True)
        metrics.update(source_total_comparable=comparable,source_total_observed=metrics['visible'],
            source_total_gap=max(0,metrics['source_total']-metrics['visible']) if comparable else None,
            source_total_reconciled=comparable and metrics['source_total']==metrics['visible'])
        if not metrics['source_total_reconciled']:
            metrics['truncated']=True
            if comparable:
                metrics['reasons'].append(f"声明总量 {metrics['source_total']}，本轮观察 {metrics['visible']}，缺口 {metrics['source_total_gap']}；来源条目尚未核对一致")
            else:metrics['reasons'].append('声明总量与条目单位或范围无法可靠比较')
            if not metrics['next_cursor']:metrics['reasons'].append('未提供可用的后续分页；未猜测链接')
    partial=metrics['truncated'] or metrics['parser_unaccounted'] or metrics['detail_deferred'] or metrics['detail_failed']
    if metrics['mode'] in ('search_index','discovery_only','fallback_only','single_page'):
        metrics['reasons'].append({'search_index':'搜索索引非全量实时','discovery_only':'仅发现入口中的公开线索','fallback_only':'全国订阅仅作兜底','single_page':'仅覆盖这个公开汇总页'}[metrics['mode']])
        partial=True
    metrics['elapsed_seconds']=round(time.monotonic()-started,2)
    status=('blocked' if blocked else 'error') if error and not metrics['pages_visited'] else ('partial' if partial else ('ok' if items else 'empty'))
    if not metrics['counters_available']:
        metrics.update({key:None for key in OBSERVATION_FIELDS})
        metrics.update(source_total=None,rejected=None,page_urls=[],sampled_at=None,truncated=True)
    status=finalize(metrics,status,error)
    return {'items':admitted,'coverage':metrics,'status':status,'error':error}

