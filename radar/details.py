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
        for i,line in enumerate(lines):
            for label,key in labels.items():
                m=re.match('^'+label+r'\s*[：:]\s*(.{1,200})$',line)
                value=m[1] if m else (lines[i+1] if line==label and i+1<len(lines) else '')
                if value and value not in labels and len(value)<=200 and not value.startswith(('http','扫码','分享')):out.setdefault(key,value)
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
    """Enrichment cannot erase established dates/location or an already known price."""
    result=dict(base)
    for key,value in (structured or {}).items():
        if value not in (None,'',[],{}) and not (key=='cost_text' and value in UNKNOWN_COST):result[key]=value
    for key in ('organizer','cost_text'):
        if metadata.get(key) and (not result.get(key) or result.get(key) in UNKNOWN_COST):result[key]=metadata[key]
    # Keep all source fields as attributed observations, not verified endorsements.
    result['details']={**(base.get('details') or {}),**metadata}
    if metadata.get('organizer') or (structured or {}).get('organizer'):result['details']['organizer_role']='organizer'
    return result
