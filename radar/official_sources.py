"""Venue-owned schedules and publisher-owned single-event pages."""
import hashlib,re
from datetime import date,timedelta
from urllib.parse import urlencode
from .core import clean,iso
from .collectors import skeleton,text

def szcec(soup,url):
    heading=next((text(n) for n in soup.select('h1') if '展览计划表' in text(n)),'')
    match=re.search(r'(20\d{2})年',heading)
    if not match:return []
    year=int(match[1]);section_year=year;out=[]
    for row in soup.select('table.zhpq-table tr'):
        cells=row.find_all('td',recursive=False)
        if len(cells)==1:
            m=re.fullmatch(r'(20\d{2})年\s*\d{1,2}月',text(cells[0]))
            if m:section_year=int(m[1])
            continue
        if len(cells)!=4 or not text(cells[0]).isdigit():continue
        title=text(cells[1]);time_label=text(cells[2]);dates=re.findall(r'(\d{1,2})月\s*(\d{1,2})日',time_label)
        if not title or len(dates)!=2:continue
        try:
            m,d=map(int,dates[0]);em,ed=map(int,dates[1]);start=date(section_year,m,d);end=date(section_year+int((em,ed)<(m,d)),em,ed)+timedelta(days=1)
        except ValueError:continue
        org=next((text(n) for n in cells[3].select('p') if text(n)),text(cells[3]))[:200]
        # Synthetic record discriminator on the same canonical venue page; original
        # evidence URL retained separately. No guessed third-party event endpoint.
        record_url=url+('&' if '?' in url else '?')+urlencode({'radar_event':hashlib.sha256((title+'|'+start.isoformat()).encode()).hexdigest()[:20]})
        typ='ExhibitionEvent' if any(w in title for w in ('展','博览')) else 'PublicationEvent' if '发布会' in title else 'ConferenceEvent' if any(w in title for w in ('大会','峰会')) else 'Festival' if '节' in title else 'Event'
        out.append(skeleton(title,record_url,'官方场馆排期；具体开放时段、票务和入场要求以主办方最新公告为准。','深圳会展中心（福田）',start_at=iso(start),end_at=iso(end),all_day=True,organizer=org,event_type=typ,city='深圳',details={'evidence_url':url,'date_evidence':heading+'；'+time_label,'organizer_notes':'场馆排期联系方式中列出的机构；不是独立信誉评价。'}))
    return out

def cioe(soup,url):
    body=clean(soup.get_text(' ',strip=True))
    m=re.search(r'(第二[十零一二三四五六七八九]+届中国国际光电博览会)[（(]CIOE中国光博会[）)]将于(20\d{2})年(\d{1,2})月(\d{1,2})[-—–至](\d{1,2})日在深圳国际会展中心举办',body)
    if not m:return []
    title,y,mo,day,last=m.groups()
    try:start=date(int(y),int(mo),int(day));end=date(int(y),int(mo),int(last))+timedelta(days=1)
    except ValueError:return []
    return [skeleton(title+'（CIOE '+y+'）',url+('?'+urlencode({'radar_edition':y})),'覆盖光电产业链的展会；参观资格、票务与同期会议安排请查看主办方公告。','深圳国际会展中心（宝安）',start_at=iso(start),end_at=iso(end),all_day=True,event_type='ExhibitionEvent',city='深圳',topics=['硬件创客'],details={'evidence_url':url,'date_evidence':m[0]})]
