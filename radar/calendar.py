"""ICS export adapted from Community Calendar's BaseScraper.create_calendar/create_event.
Upstream: judell/community-calendar, scrapers/lib/base.py
Upstream blob: 48fe7c1f826404ff50ca10f32337042973f255f6
License: Apache-2.0. See THIRD_PARTY.md and LICENSE.
Modifications: Asia/Shanghai; canonical UID; DTSTAMP/LAST-MODIFIED; all-day end
is exclusive; no zero-duration invented ending; merged source attribution.
"""
from datetime import datetime, timedelta
from icalendar import Calendar, Event
from .core import TZ, now, canon_url, clean

def make_calendar(rows):
    cal=Calendar();cal.add('prodid','-//Shenzhen Events Radar//ZH-CN//');cal.add('version','2.0');cal.add('x-wr-calname','深圳活动雷达');cal.add('x-wr-timezone','Asia/Shanghai')
    for row in rows:
        if not row.get('start_at') or row.get('planning_eligible') is not True or row.get('status')!='scheduled' or 'safety_epoch' not in row:continue
        start=datetime.fromisoformat(row['start_at']);end=datetime.fromisoformat(row['end_at']) if row.get('end_at') else None
        event=Event();event.add('uid',row['id']+'@shenzhen-events');event.add('summary',row['title']);event.add('dtstamp',datetime.fromisoformat(row.get('last_seen') or now().isoformat()));event.add('last-modified',datetime.fromisoformat(row.get('last_seen') or now().isoformat()))
        if row.get('all_day'):
            event.add('dtstart',start.date());event.add('dtend',end.date() if end else start.date()+timedelta(days=1))
        else:
            event.add('dtstart',start.astimezone(TZ))
            if end:event.add('dtend',end.astimezone(TZ))
        # Legacy records can predate URL validation. Keep the event/attribution,
        # but never advertise a malformed destination as a calendar URI.
        url=clean(row.get('url',''))
        if canon_url(url):event.add('url',url)
        event.add('location',row.get('location',''))
        sources='\n'.join(s['name']+': '+s['url'] for s in row.get('sources',[]))
        event.add('description',(row.get('summary','')+'\n\n费用：'+row.get('cost_text','费用未注明')+'\n以主办方最新说明为准。\n'+sources).strip());event.add('x-source','深圳活动雷达');event.add('status','CANCELLED' if row.get('status')=='cancelled' else 'CONFIRMED');cal.add_component(event)
    return cal.to_ical()
