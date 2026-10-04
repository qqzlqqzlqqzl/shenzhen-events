"""Public multi-organizer listings; keep event dates separate from publication dates."""
import hashlib,json,re
from datetime import date,datetime,timedelta
from urllib.parse import urljoin,urlsplit,urlencode
from bs4 import BeautifulSoup
from . import core
from .collectors import skeleton,text,SourceError


def explicit_range(value,year_hint=None):
    """Parse a labelled event date, retaining all-day precision and inclusive last day."""
    v=core.clean(value)
    if re.match(r'^(?:即日|即日起|截至|截止|至|每周|每天)',v):return None,None
    m=re.search(r'(?:(20\d{2})[年./-])?(\d{1,2})[月./-](\d{1,2})日?',v)
    if not m or not (m[1] or year_hint):return None,None
    try:
        y=int(m[1] or year_hint);mo=int(m[2]);day=int(m[3]);start=date(y,mo,day);end=start
        tail=v[m.end():]
        n=re.match(r'\s*[—–~至\-]\s*(?:(20\d{2})[年./-])?(?:(\d{1,2})[月./-])?(\d{1,2})日?',tail)
        if n:
            ey=int(n[1] or y);em=int(n[2] or mo);ed=int(n[3])
            if not n[1] and (em,ed)<(mo,day):
                if mo==12 and em==1:ey+=1
                else:return None,None
            end=date(ey,em,ed)
        if end<start or (end-start).days>366:return None,None
        return core.iso(start),core.iso(end+timedelta(days=1))
    except (ValueError,OverflowError):return None,None


def labeled(lines,labels):
    vals=[]
    for m in re.finditer(r'(?:^|\n)(?:'+ '|'.join(map(re.escape,labels))+r')\s*[：:]\s*([^\n]+)',lines):
        v=core.clean(m[1])
        if v and v not in vals:vals.append(v)
    return vals


def wordpress_posts(html,url,source):
    try:posts=json.loads(html)
    except ValueError:raise SourceError('公开文章接口返回无效JSON')
    if not isinstance(posts,list):raise SourceError('公开文章接口未返回文章列表')
    out=[];excluded={}
    category_types={'3':'PerformingArtsEvent','4':'ChildrensEvent','5':'LiteraryEvent','6':'ExhibitionEvent','7':'SportsEvent','8':'FoodEvent'}
    for p in posts:
        if not isinstance(p,dict):continue
        if p.get('content',{}).get('protected'):
            excluded['需授权文章']=excluded.get('需授权文章',0)+1;continue
        title=text(BeautifulSoup(p.get('title',{}).get('rendered',''),'html.parser'));link=core.canon_url(p.get('link',''))
        if not title or not link:excluded['无有效标题链接']=excluded.get('无有效标题链接',0)+1;continue
        soup=BeautifulSoup(p.get('content',{}).get('rendered',''),'html.parser')
        for n in soup.select('script,style,iframe'):n.decompose()
        lines=soup.get_text('\n',strip=True);published=core.iso(p.get('date'));times=labeled(lines,['活动时间','演出时间','展览时间','比赛时间','赛事时间','开展时间'])
        locs=labeled(lines,['活动地点','演出地点','展览地点','比赛地点','赛事地点','场馆地址','活动地址','上课地点','观赛地点','活动区域','比赛路程','演出地址'])
        orgs=labeled(lines,['主办单位','主办方']);fees=labeled(lines,['活动费用','培训费用','票价','门票价格','活动参与','参与方式'])
        # An old post never becomes a current event just because it was recollected.
        hint=int(published[:4]) if published else None
        ranges=[explicit_range(t,hint) for t in times]
        start,end=ranges[0] if ranges else (None,None)
        contained=start and all(a and start<=a and b<=end for a,b in ranges)
        if len(times)>1 and (not contained or re.search(r'汇总|盘点|合集|大全|一览',title)):start,end=None,None

        if start and published and not re.search(r'20\d{2}',times[0]):
            delta=(datetime.fromisoformat(start)-datetime.fromisoformat(published)).days
            if not -45<=delta<=120:start,end=None,None
        typ=next((category_types[str(c)] for c in p.get('categories',[]) if str(c) in category_types),'Event')
        # Source categories describe broad sections, not necessarily a specific format.
        if typ=='SportsEvent' and not any(w in title for w in ('赛','徒步','跑','登山','骑行')):typ='Event'
        if any(w in title for w in ('脱口秀','喜剧')):typ='ComedyEvent'
        elif any(w in title for w in ('音乐会','演唱会','打击乐')):typ='MusicEvent'
        cost=''
        if len(fees)==1 and re.search(r'^(?:公益)?免费(?:[，,。！!\s]|$)',fees[0]):cost='免费'
        elif len(fees)==1 and re.search(r'\d\s*元|[￥¥]\s*\d',fees[0]):cost=fees[0][:100]
        evidence={'evidence_url':link,'detail_text':lines[:14000],'publisher':source.get('name',''),'date_evidence':times[0] if len(times)==1 else '；'.join(times),'year_context':published or '','source_category_ids':p.get('categories',[]),'attendance':'offline' if locs else 'unknown'}
        if len(times)>1 and not start:evidence['review_notes']='推文包含多个活动时间，需分别核实；未把整篇当作一个确定日程。'
        if not start:evidence['review_notes']=evidence.get('review_notes','活动时间信息不足，保留原文待核实。')
        out.append(skeleton(title,link,text(soup)[:3500],locs[0] if locs and all(core.norm(v) in core.norm(locs[0]) or core.norm(locs[0]) in core.norm(v) for v in locs) else '',start_at=start,end_at=end,all_day=True,city='深圳',organizer=orgs[0] if len(orgs)==1 else '',cost_text=cost,event_type=typ,published_at=published,details=evidence,detail_candidate=True))
    return out,len(posts),excluded


def monthly_links(soup,url):
    out=[];current=core.now().year*12+core.now().month
    for a in soup.select('a[href]'):
        link=urljoin(url,a['href']);title=text(a);m=re.search(r'(20\d{2})年(\d{1,2})月.*展会',title)
        if not m or not re.search(r'/zhanhui_\d+/\d+\.html$',urlsplit(link).path):continue
        if not -1<=int(m[1])*12+int(m[2])-current<=6:continue
        if link not in out:out.append(link)
    return out


def monthly_events(soup,url):
    title=text(soup.select_one('title'));m=re.search(r'(20\d{2})年(\d{1,2})月',title)
    if not m:return []
    year=int(m[1]);needle=soup.find(string=lambda s:s and '开展时间' in s)
    if not needle:return []
    body=needle.find_parent('div')
    if not body:return []
    # Paragraph boundaries survive nested WeChat spans; text-node boundaries do not.
    lines=[core.clean(p.get_text('',strip=True)) for p in body.find_all('p')]
    blocks=[];block=[]
    for line in lines:
        if re.fullmatch(r'\d{1,2}',line):
            if block:blocks.append(block)
            block=[]
        elif line:block.append(line)
    if block:blocks.append(block)
    out=[]
    for lines in blocks:
        field_at=next((i for i,x in enumerate(lines) if re.match(r'场\s*馆\s*[：:]',x)),None)
        if field_at is None:continue
        names=[x for x in lines[:field_at] if not x.startswith('—') and not x.startswith('*')]
        venue=re.sub(r'^场\s*馆\s*[：:]\s*','',lines[field_at]);time_label=next((re.sub(r'^开展时间\s*[：:]\s*','',x) for x in lines if x.startswith('开展时间')),'')
        start,end=explicit_range(time_label,year)
        if not names or not start:continue
        org=next((re.sub(r'^主/承办单位\s*[：:]\s*','',x) for x in lines if x.startswith('主/承办单位')),'')
        if not org:
            i=next((i for i,x in enumerate(lines) if x.startswith('主/承办单位')),None)
            if i is not None and i+1<len(lines):org=lines[i+1]
        # English aliases are joined to their Chinese event title, not counted twice.
        titles=[]
        for name in names:
            if not re.search(r'[\u3400-\u9fff]',name) and titles:titles[-1]+=' / '+name
            else:titles.append(name)
        for name in titles:
            if len(name)<2:continue
            key=hashlib.sha256((name+'|'+start+'|'+venue).encode()).hexdigest()[:20]
            record=url+('?'+urlencode({'radar_event':key}))
            typ='ConferenceEvent' if any(w in name for w in ('大会','峰会')) and not any(w in name for w in ('展览','博览')) else 'ExhibitionEvent'
            out.append(skeleton(name,record,'月度聚合排期；具体时段、入场和票务以主办方最新信息为准。',venue,start_at=start,end_at=end,all_day=True,city='深圳',organizer=org,event_type=typ,details={'evidence_url':url,'date_evidence':title+'；'+time_label,'attendance':'offline','organizer_notes':'聚合排期原文列为“主/承办单位”，不等于独立信誉核验。'}))
    return out


def developer_events(soup,url):
    """Date-only online/hybrid conference inventory with explicit Schema.org mode."""
    from .source_topics import developer_category,developer_event_type
    out=[]
    for node in soup.select('.row:not(.featured) script[type="application/ld+json"]'):
        try:d=json.loads(node.get_text())
        except ValueError:continue
        mode={'https://schema.org/OnlineEventAttendanceMode':'online','https://schema.org/MixedEventAttendanceMode':'hybrid'}.get(d.get('eventAttendanceMode'))
        if not mode:continue
        title=core.clean(d.get('name'));link=core.canon_url(d.get('url',''))
        if not title or not link:continue
        try:
            start=date.fromisoformat(str(d.get('startDate',''))[:10]);last=date.fromisoformat(str(d.get('endDate') or d.get('startDate'))[:10])
            if last<start:continue
        except ValueError:continue
        loc=d.get('location') or {};venue=core.clean(loc.get('name')) if isinstance(loc,dict) else ''
        label=text(node.parent.select_one('time'));description=core.clean(d.get('description'))
        source_topic,topics=developer_category(description)
        out.append(skeleton(title,link,description,'线上' if mode=='online' else venue,
            start_at=core.iso(start),end_at=core.iso(last+timedelta(days=1)),all_day=True,
            event_type=developer_event_type(description),city='线上' if mode=='online' else venue,topics=topics,
            details={'attendance':mode,'source_topic':source_topic,'evidence_url':link,'date_evidence':label,'review_notes':'聚合来源仅提供举办日期；具体时区、开播时间、费用及参与条件请核对原文。','publisher':'dev.events'}))
    return out
