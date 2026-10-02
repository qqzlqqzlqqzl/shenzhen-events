"""Extract attributable public detail fields, without making model calls."""
import json, re
from urllib.parse import urljoin, urlsplit
from .core import clean, canon_url, stamp

UNKNOWN_COST={'','费用未注明','未注明','未知','待确认','费用待确认','N/A'}
def public_image(value,base):
    if not isinstance(value,str):return ''
    url=urljoin(base,value.strip());p=urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:return ''
    # Images are displayed by the client, never fetched by a privileged service.
    import ipaddress
    try:
        if not ipaddress.ip_address(p.hostname).is_global:return ''
    except ValueError:
        if p.hostname in ('localhost',) or '.' not in p.hostname:return ''
    return url

def extract(soup,url):
    body=soup.select_one('#js_content,#event_desc_page,.event-detail,article,main')
    out={'evidence_url':canon_url(url),'checked_at':stamp()}
    if body:
        lines=[clean(x) for x in body.get_text('\n',strip=True).splitlines() if clean(x)]
        out['detail_text']='\n'.join(lines)[:14000]
        # Require an explicit field label; never interpret generic "free" slogans.
        labels={'主办方':'organizer','主办单位':'organizer','协办单位':'coorganizers','指导单位':'guidance','支持单位':'supporters','活动费用':'cost_text','门票价格':'cost_text','费用':'cost_text'}
        # Preserve inline value fragments within a labeled block (e.g. 199 + 元).
        for block in body.select('p,li,dt,dd'):
            if block.select('p,li,dt,dd'):continue
            line=clean(block.get_text('',strip=True))
            for label,key in labels.items():
                match=re.fullmatch(re.escape(label)+r'\s*[：:]\s*(.{1,200})',line)
                if match and not any(re.search(re.escape(other)+r'\s*[：:]',match[1]) for other in labels):out.setdefault(key,match[1])
        for i,line in enumerate(lines):
            for label,key in labels.items():
                m=re.match('^'+label+r'\s*[：:]\s*(.{1,200})$',line)
                # Inline markup can split both the colon and the field value.
                bare=re.fullmatch(re.escape(label)+r'\s*[：:]?',line)
                following=lines[i+1:] if bare else []
                if following and following[0] in ('：',':'):following=following[1:]
                value=m[1] if m else (following[0].lstrip('：:').strip() if following else '')
                if value and value not in labels and not any(re.match('^'+re.escape(other)+r'\s*[：:]',value) for other in labels) and len(value)<=200 and not value.startswith(('http','扫码','分享')):out.setdefault(key,value)
    if urlsplit(url).hostname in ('lianpu.com','www.lianpu.com'):
        for badge in soup.select('main span.rounded-full'):
            fee=clean(badge.get_text())
            if fee=='免费' or re.fullmatch(r'[￥¥]\s*\d[\d.,]*(?:\s*[-–]\s*[￥¥]?\s*[\d.,]+)?',fee):
                out.setdefault('cost_text',fee);break
    images=[]
    for n in soup.select('meta[property="og:image"]'):
        value=public_image(n.get('content',''),url)
        if value and value not in images:images.append(value)
    if body:
        for n in body.select('img[src],img[data-src]'):
            if re.search(r'qr|二维码|公众号|logo|头像',n.get('alt',''),re.I):continue
            value=public_image(n.get('data-src') or n.get('src',''),url)
            if value and value not in images:images.append(value)
    out['images']=images[:8]
    return out

def merge(base,structured,metadata):
    """Fill missing fields from observations; retain current inventory evidence."""
    structured=structured or {};metadata=metadata or {};result=dict(base)
    fresh=base.get('details') or {};observed=structured.get('details') or {}
    result['details']={**observed,**metadata,**fresh}
    provenance={**(observed.get('field_provenance') or {}),**(metadata.get('field_provenance') or {}),**(fresh.get('field_provenance') or {})}
    held=bool(fresh.get('review_hold'))
    modes=('online','hybrid','offline')
    if not held and fresh.get('attendance') not in modes and observed.get('attendance') in modes:
        result['details']['attendance']=observed['attendance']
        provenance['attendance']={'kind':'structured','evidence_url':metadata.get('evidence_url',structured.get('url',''))}
    for key,value in structured.items():
        if key in ('details','cost_free','organizer','all_day') or value in (None,'',[],{}):continue
        if key=='cost_text' and value in UNKNOWN_COST:continue
        if held and key in ('start_at','end_at','all_day','status'):continue
        missing=not result.get(key) or (key=='cost_text' and result.get(key) in UNKNOWN_COST)
        if missing:
            result[key]=value
            provenance[key]={'kind':'structured','evidence_url':metadata.get('evidence_url',structured.get('url',''))}
    # Listing precision is provisional until a start date has been accepted.
    # A False timed flag must travel with that evidence, not lose to True.
    if not held and not base.get('start_at') and structured.get('start_at'):
        result['all_day']=bool(structured.get('all_day',len(str(structured['start_at']))==10))
        provenance['all_day']={'kind':'structured','evidence_url':metadata.get('evidence_url',structured.get('url',''))}
    explicit=metadata.get('organizer') or structured.get('organizer')
    if explicit and (not result.get('organizer') or fresh.get('organizer_role')=='publisher'):
        if fresh.get('organizer_role')=='publisher' and base.get('organizer'):
            result['details'].setdefault('publisher',base['organizer'])
        result['organizer']=explicit;result['details']['organizer_role']='organizer'
        provenance['organizer']={'kind':'label' if metadata.get('organizer') else 'structured','evidence_url':metadata.get('evidence_url',structured.get('url',''))}
    elif explicit==result.get('organizer') and explicit:
        result['details']['organizer_role']='organizer'
    if metadata.get('cost_text') and metadata['cost_text'] not in UNKNOWN_COST and (result.get('cost_text') or '') in UNKNOWN_COST:
        result['cost_text']=metadata['cost_text'];provenance['cost_text']={'kind':'label','evidence_url':metadata.get('evidence_url','')}
    if (base.get('cost_text') or '') in UNKNOWN_COST:
        costs=list(dict.fromkeys(v for v in (structured.get('cost_text'),metadata.get('cost_text')) if v and v not in UNKNOWN_COST))
        if len(costs)>1:
            result['cost_text']=' / '.join(costs)
            provenance['cost_text']={'kind':'structured_and_label','evidence_url':metadata.get('evidence_url','')}
    if not result.get('summary') and metadata.get('detail_text'):result['summary']=clean(metadata['detail_text'])[:3500]
    if provenance:result['details']['field_provenance']=provenance
    if (result.get('cost_text') or '') not in UNKNOWN_COST:
        result['cost_free']=result['cost_text'] in ('免费','0元','免费参加')
    return result
