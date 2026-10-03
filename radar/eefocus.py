"""Admission-gated EEFocus adapter with bounded captured-publisher roles.

No live source is registered. Durable cancellation eligibility guards are a
separate release prerequisite. Pending candidates never reach normal ingestion.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from . import collectors as c, core, recurring_sources as rs

KIND = 'eefocus_events'
ORIGIN = 'https://www.eefocus.com'
LIST_URL = ORIGIN + '/event/'
# Earlier positive cache entries used permissive status/history checks.
SCHEMA = 'eefocus_identity_v3'
CANCELLATION_TIME_SCHEMA = 'eefocus_cancellation_time_v1'


def safe_url(url, inventory=False):
    try:
        p = urlsplit(url)
        return (p.scheme == 'https' and p.hostname == 'www.eefocus.com'
                and p.port in (None, 443) and not p.username and not p.password
                and not p.query and not p.fragment
                and (p.path == '/event/' if inventory else
                     bool(re.fullmatch(r'/(?:event|live)/\d+\.html', p.path))))
    except ValueError:
        return False


def event_url(href, base=LIST_URL):
    try:
        url = urljoin(base, str(href or ''))
        p = urlsplit(url)
        url = urlunsplit((p.scheme, p.netloc, p.path, '', ''))
        return url if safe_url(url) else ''
    except ValueError:
        return ''


def heading(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', core.clean(value))).strip()


def cancelled(text):
    # Only explicit whole-event labels. Quoted/negated/session text is insufficient.
    return bool(re.fullmatch(r'(?:本(?:次|场)活动)?(?:已|现已)?取消(?:举办)?[。！!]?|活动已取消', core.clean(text)))


def cancellation_observations(soup, url):
    """Extract card authority independently of optional detail admission."""
    from . import safety
    parse(soup, url)
    root = soup.select('div.special-list > ul.section-list-item-ul,main.special-list > ul.section-list-item-ul')[0]
    nodes = root.select(':scope > li.section-special-item')
    if len(nodes) > safety.limits()['cards']:
        raise safety.Capacity('recognized-card bound exceeded; exact capture remains fenced')
    observations, slices = [], 0
    for index, node in enumerate(nodes):
        a = node.select_one('a.item-title[href]')
        alias = event_url(a.get('href') if a else '')
        if not a or not alias or not c.text(a):
            continue
        labels = [c.text(n) for n in node.select('.event-status,.status')]
        again = [bool(re.fullmatch(r'恢复举办后，本次\d{1,2}月\d{1,2}日活动再次取消[。！!]?', value)) for value in labels]
        if not labels or not all(cancelled(value) or repeated for value, repeated in zip(labels, again)):
            continue
        excerpt = str(node).encode(); slices += len(excerpt)
        if len(excerpt) > safety.limits()['slice_bytes'] or slices > safety.limits()['slices_bytes']:
            raise safety.Capacity('card evidence bound exceeded; no truncated receipt')
        time_evidence = cancellation_time_evidence([c.text(n) for n in node.select('.event-time')],root.parent.name=='div',url)
        key = node.get('data-post-id') or f'{index}:{alias}'
        observations.append(dict(alias_url=alias,card_key=str(key),title=c.text(a),status_text=' / '.join(labels),
                                 occurrence=time_evidence['occurrence'],time_evidence=time_evidence,cancelled_again=any(again),card_index=index,
                                 card_digest=hashlib.sha256(excerpt).hexdigest()))
    return observations


def single_cancellation_occurrence(raw):
    """Consume one whole dated meeting field; unparsed suffixes give no proof.

    This positive grammar permits a full date, optional same-day clocks and
    an explicit local timezone. Compact ranges, alternatives, open ends and
    explanatory prose are outside that grammar and remain unknown.
    """
    clock=r'\d{1,2}:\d{2}'
    match=re.fullmatch(r'(?:活动|直播|举办)时间[：:]\s*'
                      r'(?P<date>20\d{2}年\d{1,2}月\d{1,2}日)'
                      rf'(?:\s*(?P<start>{clock})(?:\s*[–—－~-]\s*(?P<end>{clock}))?)?'
                      r'(?:\s*北京时间)?',date_text(raw))
    if not match:return []
    days=sorted(calendar_dates(match['date']))
    if len(days)!=1:return []
    try:
        clocks=[datetime(2000,1,1,*map(int,match[key].split(':'))) for key in ('start','end') if match[key]]
    except ValueError:return []
    if len(clocks)==2 and clocks[1]<=clocks[0]:return []
    return days


def cancellation_time_evidence(texts, publisher_inventory, url):
    """Only a single explicit meeting field identifies cancellation occurrence.

    Campaign endpoints and discovery/publication/registration dates remain
    retained mentions. They cannot prove a different event occurrence later.
    """
    texts=list(dict.fromkeys(core.clean(text) for text in texts if core.clean(text)))
    raw=texts[0] if len(texts)==1 else ''
    days=single_cancellation_occurrence(raw)
    if re.search(r'推广',raw):role='promotion_window'
    elif re.search(r'报名|征集',raw):role='registration_window'
    elif re.search(r'发布|更新|上架',raw):role='publication_time'
    elif publisher_inventory and len(date_parts(raw))>1:role='discovery_window'
    elif days:role='actual_occurrence'
    else:role='unknown'
    return dict(schema=CANCELLATION_TIME_SCHEMA,role=role,texts=texts,publisher_inventory=publisher_inventory,
                url=url,occurrence=days if role=='actual_occurrence' else [])


def verified_cancellation_occurrence(metadata):
    """Recheck immutable evidence roles; legacy bare date arrays are unknown."""
    proof=metadata.get('time_evidence')
    if (not isinstance(proof,dict) or proof.get('schema')!=CANCELLATION_TIME_SCHEMA
            or not isinstance(proof.get('texts'),list) or not all(isinstance(v,str) for v in proof['texts'])
            or not isinstance(proof.get('publisher_inventory'),bool) or not safe_url(proof.get('url'),inventory=True)):
        return []
    checked=cancellation_time_evidence(proof['texts'],proof['publisher_inventory'],proof['url'])
    return checked['occurrence'] if checked==proof else []


def date_text(text):
    """Normalize full slash dates for parsing; retain the original evidence."""
    return re.sub(r'(?<!\d)(20\d{2})/(\d{1,2})/(\d{1,2})(?!\d)',
                  lambda m: f'{m[1]}年{m[2]}月{m[3]}日', text)


def date_parts(text):
    normalized = date_text(text)
    values = re.findall(r'(\d{1,2})月(\d{1,2})日', normalized)
    values += re.findall(r'(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])', normalized)
    return [(int(m), int(d)) for m, d in values]


def calendar_dates(text):
    dates = set()
    for values in re.findall(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', date_text(text)):
        try:
            dates.add(datetime(*(int(v) for v in values)).date().isoformat())
        except ValueError:
            continue
    return dates


def schedule(text, attendance, location, exact=True):
    text = date_text(text)
    m = re.search(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', text)
    if not m or re.search(r'推广期|报名(?:时间|截止)|征集', text):
        return None, None, False, 'unconfirmed'
    try:
        start = datetime(*(int(v) for v in m.groups()), tzinfo=core.TZ)
    except ValueError:
        return None, None, False, 'unconfirmed'
    zone = 'source_explicit' if '北京时间' in text else 'venue_local' if '深圳' in location and attendance in ('offline', 'hybrid') else 'unconfirmed'
    clocks = re.search(r'(\d{1,2}):(\d{2})\s*[–—－~-]\s*(\d{1,2}):(\d{2})', text)
    if exact and clocks and zone != 'unconfirmed':
        try:
            h1, m1, h2, m2 = map(int, clocks.groups())
            a, b = start.replace(hour=h1, minute=m1), start.replace(hour=h2, minute=m2)
            if b > a:
                return core.iso(a), core.iso(b), False, zone
        except ValueError:
            pass
    return core.iso(start), core.iso(start + timedelta(days=1)), True, zone


def parse(soup, url):
    if not safe_url(url, inventory=True):
        raise c.SourceError('inventory_origin_rejected')
    roots = soup.select('div.special-list > ul.section-list-item-ul,main.special-list > ul.section-list-item-ul')
    if len(roots) != 1:
        raise c.SourceError('inventory_structure_drift')
    root = roots[0]
    publisher = root.parent.name == 'div'
    nodes = root.select(':scope > li.section-special-item')
    if not nodes and (publisher or not soup.select_one('[data-fixture-empty-state="true"]')):
        raise c.SourceError('inventory_empty_unrecognized')
    out, rejected, seen = [], Counter(), set()
    for node in nodes:
        a = node.select_one('a.item-title[href]')
        link = event_url(a.get('href') if a else '')
        if not a or not c.text(a) or not link:
            rejected['无有效标题或链接'] += 1
            continue
        tags = ' '.join(c.text(n) for n in node.select('.post-tag'))
        label = c.text(node.select_one('.event-status,.status'))
        if re.search(r'已结束|回放|重播', label + tags):
            rejected['已结束或回放'] += 1
            continue
        if re.search(r'试用|下载|赠送|抽奖|有奖|福利|领取', tags + c.text(a)):
            rejected['非活动推广'] += 1
            continue
        if link in seen:
            rejected['重复活动链接'] += 1
            continue
        seen.add(link)
        summary = c.text(node.select_one('.item-intro'))
        raw_location = c.text(node.select_one('.event-location'))
        company = bool(re.match(r'^公司[：:]', raw_location))
        location = '' if company else re.sub(r'^地点[：:]\s*', '', raw_location)
        raw = c.text(node.select_one('.event-time'))
        organizer = re.sub(r'^主办(?:方|单位)?[：:]\s*', '', c.text(node.select_one('.event-organizer')))
        online = '线上' in tags or '直播' in tags or location in ('线上', '线上活动')
        offline = '线下' in tags or location == '线下活动'
        hybrid = bool(re.search(r'同步(?:直播|线上)|线上\+线下|线上线下同步', tags + summary))
        conflict = online and offline and not hybrid
        mode = 'unknown' if conflict else 'hybrid' if hybrid else 'online' if online else 'offline' if offline else 'unknown'
        # Observed list date ranges are discovery windows, not meeting spans.
        promotion = '推广期' in raw or (publisher and len(date_parts(raw)) > 1)
        start, end, all_day, zone = ((None, None, False, 'unconfirmed') if promotion
                                     else schedule(raw, mode, location, exact=False))
        status = 'cancelled' if cancelled(label) else 'needs_review' if not start or conflict or mode == 'unknown' else 'scheduled'
        if location in ('线上活动', '线下活动'):
            location = '线上' if location == '线上活动' else ''
        meta = {'publisher': '与非网', 'identity_adapter': KIND, 'source_event_id': re.search(r'/(\d+)\.html$', link)[1],
                'evidence_url': link, 'attendance': mode, 'source_status': label,
                'date_evidence': raw, 'checked_at': core.stamp(), 'timezone_status': zone,
                'time_evidence': [{'field': 'list_promotion_window' if promotion else 'list_meeting_time', 'text': raw, 'url': url}]}
        if publisher:
            meta['location_evidence'] = {'text': raw_location, 'role': 'company' if company else 'venue_or_mode', 'url': url}
        if promotion:
            meta['review_notes'] = '推广期不是实际举办日期；等待明确的活动时间证据。'
        if conflict:
            meta['attendance_conflict'] = True
            meta['review_notes'] = '线上与线下标签冲突，尚无明确同步参与证据。'
        if mode == 'online' and zone == 'unconfirmed' and ':' in raw:
            clocks = re.search(r'\d{1,2}:\d{2}\s*[–—－~-]\s*\d{1,2}:\d{2}', raw)
            meta['review_notes'] = f'原文有{clocks[0] if clocks else "时钟"}但没有时区；日期粒度仅供展示，请核对开播时间。'
        out.append(c.skeleton(c.text(a), link, summary, location,
                              start_at=start, end_at=end, all_day=all_day,
                              city='线上' if mode == 'online' else '深圳' if '深圳' in location else '',
                              organizer=organizer, cost_text='', event_type='Event',
                              status=status, details=meta, detail_candidate=True))
    return out, len(nodes), dict(rejected)


def trace_identity(requested, final, trace):
    if not trace or len(trace) > 5 or not safe_url(requested) or not safe_url(final):
        raise c.SourceError('identity_trace_incomplete')
    expected = requested
    for i, hop in enumerate(trace):
        if hop.get('url') != expected or not safe_url(expected):
            raise c.SourceError('identity_trace_invalid')
        if i == len(trace) - 1:
            if hop.get('status') != 200 or expected != final:
                raise c.SourceError('identity_trace_incomplete')
        else:
            if hop.get('status') not in (301, 302, 303, 307, 308) or not hop.get('location'):
                raise c.SourceError('identity_trace_invalid')
            expected = urljoin(expected, hop['location'])
            if not safe_url(expected):
                raise c.SourceError('redirect_route_rejected')


def detail(base, soup, final, trace):
    trace_identity(base['url'], final, trace)
    bodies = soup.select('main article.main-event,body > article')
    observed = soup.select('div.section-body > div.section-medium') if urlsplit(final).path.startswith('/live/') else []
    publisher = not bodies and len(observed) == 1
    if publisher:
        heads = observed[0].select(':scope > div.details-section-title > h1.title')
        contents = observed[0].select(':scope > div.article-content')
        if len(heads) != 1 or len(contents) != 1:
            raise c.SourceError('main_event_identity_missing')
        # The article content excludes publication/author lines, recommendations
        # and the related-live sidebar; only the direct title is identity text.
        body = BeautifulSoup(str(contents[0]), 'html.parser').find('div')
    elif len(bodies) == 1 and not observed:
        body = BeautifulSoup(str(bodies[0]), 'html.parser').find('article')
        heads = body.select('h1')
    else:
        raise c.SourceError('main_event_identity_missing')
    for node in body.select('aside,nav,footer,script,style,.related,.recommendations'):
        node.decompose()
    if not publisher:
        heads = body.select('h1')
    if len(heads) != 1:
        raise c.SourceError('main_event_identity_missing')
    if heading(c.text(heads[0])) != heading(base['title']):
        raise c.SourceError('main_event_title_mismatch')
    if publisher:
        actions = soup.select('div.video-part.live > div.section-left > div.section-action > div.action-right > a.sign-btn.appt-button-trigger')
        if len(actions) > 1:
            raise c.SourceError('main_event_identity_missing')
        if actions and re.fullmatch(r'看回放|观看回放', c.text(actions[0])):
            raise c.SourceError('main_event_replay')
    lines = [c.text(n) for n in body.select('p,.meeting-time')]
    times = list(dict.fromkeys(v for v in lines if re.match(r'^(?:活动|直播|举办)时间[：:]', v)))
    if not times and not re.search(r'技术交流活动|研讨会|线上活动', c.text(body)):
        raise c.SourceError('main_event_semantics_missing')
    if re.search(r'回放|资料下载|开发板试用', c.text(body)):
        raise c.SourceError('main_event_semantics_missing')
    raw = base['details'].get('date_evidence', '')
    promotion = '推广期' in raw or any(v.get('field') == 'list_promotion_window'
                                      for v in base['details'].get('time_evidence', []))
    list_dates, body_dates = set(date_parts(raw)), {d for t in times for d in date_parts(t)}
    orgs = rs._labeled(lines, ('主办方', '主办单位', '主办'))
    list_org = base.get('organizer', '')
    if list_org and orgs and any(heading(v) != heading(list_org) for v in orgs):
        raise c.SourceError('event_anchor_conflict')
    # Promotion endpoint can corroborate the actual occurrence, never its duration.
    if list_dates and body_dates and (not list_dates.intersection(body_dates)
                                     or (not promotion and list_dates != body_dates)):
        raise c.SourceError('event_anchor_conflict')
    list_years = set(re.findall(r'20\d{2}年', date_text(raw)))
    body_years = {y for t in times for y in re.findall(r'20\d{2}年', date_text(t))}
    if not promotion and list_years and body_years and list_years != body_years:
        raise c.SourceError('event_anchor_conflict')
    shared = sorted(list_dates.intersection(body_dates))
    agenda = re.findall(r'(?:议题|专题|场次)[：:]\s*([^。；]+)', base.get('summary', ''))
    agenda_match = list_org and orgs and any(v in c.text(body) for v in agenda)
    if not shared and not agenda_match:
        raise c.SourceError('event_corroboration_missing')
    locations = rs._labeled(lines, ('活动地点', '地点'))
    location = locations[0] if len(locations) == 1 else base.get('location', '')
    schedules = list(dict.fromkeys(schedule(v, base['details']['attendance'], location) for v in times))
    schedules = [v for v in schedules if v[0]]
    meta = {'source_event_id': re.search(r'/(\d+)\.html$', final)[1], 'evidence_url': final,
            'time_evidence': [{'field': 'detail_meeting_time', 'text': t, 'url': final} for t in times],
            'checked_at': core.stamp()}
    patch = {'url': final, 'details': meta}
    if len(orgs) == 1:
        patch['organizer'] = orgs[0]
        meta['organizer_evidence'] = orgs[0]
    if locations:
        patch['location'] = location
    if len(schedules) > 1:
        patch['status'] = 'needs_review'
        meta['time_conflict'] = True
    elif schedules:
        a, b, all_day, zone = schedules[0]
        patch.update(start_at=a, end_at=b, all_day=all_day)
        meta.update(date_evidence=times[0], timezone_status=zone)
    statuses = rs._labeled(lines, ('当前状态',)) + [c.text(n) for n in body.select('.current-status')]
    if any(cancelled(s) for s in statuses):
        patch['status'] = 'cancelled'
        meta['source_status'] = '已取消'
    elif statuses and all(re.fullmatch(r'(?:本(?:次|场)活动)?(?:已)?恢复(?:举办|举行)[。！!]?',
                                      core.clean(s)) for s in statuses):
        # Only unambiguous whole-event labels confer reinstatement authority.
        # Substrings also match negation, quotes, rumors and session notices.
        meta['source_status'] = '已恢复举办'
        meta['reinstated'] = True
    evidence = {'schema': SCHEMA, 'title': c.text(heads[0]), 'shared_dates': shared,
                'organizer_agenda_match': bool(agenda_match), 'requested_url': base['url'],
                'canonical_url': final, 'trace': trace,
                'occurrence_dates': sorted({v[0][:10] for v in schedules}),
                'organizers': orgs,
                'reschedule_text': [v for v in lines if re.search(r'原定.*(?:改期|延期|调整)|(?:改期|延期|调整)至', v)],
                'body_digest': hashlib.sha256(str(body).encode()).hexdigest(),
                'main_body': str(body), 'current_statuses': statuses}
    return merge_detail(base, patch), evidence


def merge_detail(base, patch):
    out = {**base, 'details': dict(base.get('details') or {})}
    old = out['details']
    meta = patch.get('details') or {}
    for k, v in meta.items():
        if k == 'time_evidence':
            old[k] = old.get(k, []) + [x for x in v if x not in old.get(k, [])]
        elif k not in ('review_hold', 'review_notes', 'attendance', 'attendance_conflict'):
            old[k] = v
    for k in ('url', 'organizer', 'location'):
        if patch.get(k):
            out[k] = patch[k]
    if patch.get('start_at'):
        different = (base.get('start_at') and base['start_at'][:10] != patch['start_at'][:10])
        exact_conflict = (base.get('start_at') and not base.get('all_day')
                          and any(base.get(k) != patch.get(k) for k in ('start_at', 'end_at')))
        if different or exact_conflict or meta.get('time_conflict'):
            old['time_conflict'] = True
        else:
            out.update({k: patch[k] for k in ('start_at', 'end_at', 'all_day')})
            if '推广期不是实际举办日期' in old.get('review_notes', ''):
                old['review_notes'] = '已按详情明确举办时间；推广期未用作活动持续时间。'
    review = (not out.get('start_at') or old.get('attendance') == 'unknown'
              or any(old.get(k) for k in ('review_hold', 'attendance_conflict', 'time_conflict')))
    out['status'] = 'needs_review' if review else 'scheduled'
    if patch.get('status') == 'needs_review':
        out['status'] = 'needs_review'
    if base.get('status') == 'cancelled' or patch.get('status') == 'cancelled':
        out['status'] = 'cancelled'
        old['source_status'] = '已取消'
    return out


def fetch(url, source, deadline, metrics, inventory=False):
    def observed(_):
        metrics['http_requests_attempted'] = metrics.get('http_requests_attempted', 0) + 1
    def request(target, **kw):
        if inventory:
            return c.fetch(target, **kw, url_policy=lambda u: safe_url(u, inventory),request_observer=observed,include_trace=True)
        from . import safety
        with safety.optional_capacity():
            metrics['detail_attempted'] += 1
            return c.fetch(target, **kw, url_policy=lambda u: safe_url(u),request_observer=observed,include_trace=True)
    return rs.bounded_fetch(request, url, source, deadline, metrics, max_bytes=1000000)


def check_history(source, requested, final, evidence, connection=None):
    """Check both direct endpoints and the stored canonical occurrence.

    A newly discovered alias has no requested-URL history. It must still agree
    with the directly verified canonical history before cache reuse, bindings
    or admission. Failed checks never mutate this append-only evidence.
    """
    manager=nullcontext(connection) if connection is not None else core.db()
    with manager as db:
        histories = []
        for alias in dict.fromkeys((requested, final)):
            row = db.execute('SELECT canonical_url,evidence FROM eefocus_identity_bindings WHERE source_id=? AND alias_url=? ORDER BY rowid DESC LIMIT 1',
                             (source['id'], alias)).fetchone()
            if row:
                if row['canonical_url'] != final:
                    raise c.SourceError('historical_canonical_conflict')
                try:
                    prior = json.loads(row['evidence'])
                    if not isinstance(prior, dict):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise c.SourceError('historical_identity_invalid')
                histories.append(prior)
        stored = db.execute('SELECT e.start_at,e.organizer FROM event_sources s JOIN events e ON e.id=s.event_id WHERE s.source_id=? AND s.url=?',
                            (source['id'], final)).fetchone()
        if stored:
            histories.append({'occurrence_dates': [stored['start_at'][:10]] if stored['start_at'] else [],
                              'organizers': [stored['organizer']] if stored['organizer'] else []})
    for prior in histories:
        old_dates, new_dates = set(prior.get('occurrence_dates', [])), set(evidence['occurrence_dates'])
        if old_dates and old_dates != new_dates:
            notices = evidence['reschedule_text']
            # A pair of date mentions is insufficient: every scoped notice must
            # affirm a whole-event move, without quotes, negation or session scope.
            full_date = r'20\d{2}年\d{1,2}月\d{1,2}日'
            explicit_move = (rf'(?:本(?:次|场)活动)?原定(?:于)?(?P<old>{full_date})[，,\s]*'
                             rf'(?:现已|现|已)?(?:改期|延期|调整)至(?P<new>{full_date})[。！!]?')
            moves = [re.fullmatch(explicit_move, date_text(core.clean(v))) for v in notices]
            # Each notice must independently prove stored old -> candidate new.
            # An unordered union admits reversed or contradictory directions.
            unambiguous = moves and all(move and calendar_dates(move['old']) == old_dates
                                       and calendar_dates(move['new']) == new_dates for move in moves)
            if not new_dates or not unambiguous:
                raise c.SourceError('historical_occurrence_conflict')
        if prior.get('organizers') and evidence['organizers'] and prior['organizers'] != evidence['organizers']:
            raise c.SourceError('historical_organizer_conflict')


def revalidate_admission_history(connection,source,item,binding_ids):
    """Recheck current direct history under ingestion's writer lock, before writes.

    Collector CLI runs have a process flock. Alternate writers or delayed
    verified items still cannot roll back a newer occurrence. No fetch occurs.
    """
    from . import safety
    safety.assert_schema(connection)
    if (not isinstance(binding_ids,list) or len(binding_ids)>safety.limits()['bindings']
            or not all(isinstance(value,str) for value in binding_ids)):
        raise safety.Integrity('bounded exact admission binding IDs required')
    for binding_id in binding_ids:
        row=connection.execute('SELECT * FROM eefocus_identity_bindings WHERE binding_id=?',(binding_id,)).fetchone()
        if not row or row['source_id']!=source['id'] or row['canonical_url']!=item['url']:
            raise safety.Integrity('admission history binding/source/canonical mismatch')
        check_history(source,row['alias_url'],item['url'],json.loads(row['evidence']),connection=connection)


def enrich(source, items, metrics, deadline):
    from . import safety
    limit = max(0, min(12, int(source.get('detail_budget', 8))))
    with core.db() as db:
        cache = {r['url']: dict(r) for r in db.execute('SELECT * FROM detail_cache WHERE source_id=?', (source['id'],))}
    out, attempted, cached, resolved = [], 0, 0, {}
    invalidated, cached_aliases = set(), {}
    metrics['identity_pending_urls'] = []
    for base in sorted(items, key=lambda e: cache.get(e['url'], {}).get('checked_at', '')):
        fp = rs.detail_fingerprint(base)
        row = cache.get(base['url'])
        try:
            payload = json.loads(row['payload']) if row and row['status'] == 'ok' else {}
            payload = payload if isinstance(payload, dict) else {}
            evidence = payload.get('evidence', {})
            evidence = evidence if isinstance(evidence, dict) else {}
            valid = (row and row['fingerprint'] == fp and row['next_attempt'] > core.stamp()
                     and evidence.get('schema') == SCHEMA and evidence.get('body_digest')
                     and (evidence.get('shared_dates') or evidence.get('organizer_agenda_match'))
                     and heading(evidence.get('title', '')) == heading(base['title']))
            if valid and evidence.get('canonical_url') in invalidated:
                continue
            if valid and not source.get('refresh_identity'):
                trace_identity(base['url'], evidence['canonical_url'], evidence['trace'])
                check_history(source, base['url'], evidence['canonical_url'], evidence)
                item = merge_detail(base, payload['item'])
                item['_identity_binding_ids'] = record_bindings(source, base['url'], evidence)
                out.append(item)
                resolved[base['url']] = item['url']
                cached_aliases[base['url']] = item['url']
                cached += 1
                metrics['detail_cached'] += 1
                continue
        except (ValueError, TypeError, KeyError, c.SourceError):
            pass
        if attempted >= limit or time.monotonic() >= deadline or metrics.get('detail_blocked'):
            metrics['identity_pending_urls'].append(base['url'])
            continue
        payload, status, final = '', 'error', None
        try:
            rs.pause(source, deadline)
            # The observer inside fetch counts actual requests, including safe hops.
            _, soup, final, trace = fetch(base['url'], source, deadline, metrics)
            attempted = metrics['detail_attempted']
            item, evidence = detail(base, soup, final, trace)
            check_history(source, base['url'], final, evidence)
            item['_identity_binding_ids'] = record_bindings(source, base['url'], evidence)
            out.append(item)
            resolved[base['url']] = item['url']
            metrics['detail_resolved'] += 1
            payload = json.dumps({'item': item, 'evidence': evidence}, ensure_ascii=False)
            status = 'ok'
            with core.db() as db:
                if final != base['url']:
                    # The final response itself proves this direct self-mapping;
                    # no transitive alias graph or guessed numeric-ID relation.
                    direct = {**base, 'url': final, 'details': {**base['details'],
                              'source_event_id': item['details']['source_event_id'], 'evidence_url': final}}
                    direct_evidence = {**evidence, 'requested_url': final, 'trace': [trace[-1]]}
                    db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id,url) DO UPDATE SET fingerprint=excluded.fingerprint,payload=excluded.payload,status=excluded.status,checked_at=excluded.checked_at,next_attempt=excluded.next_attempt',
                               (source['id'], final, rs.detail_fingerprint(direct), json.dumps({'item': item, 'evidence': direct_evidence}), 'ok', core.stamp(), core.iso(core.now()+timedelta(hours=24))))
        except safety.Capacity as exc:
            metrics['reasons'].append(str(exc))
            metrics['identity_pending_urls'].append(base['url'])
            break
        except rs.Deadline as exc:
            attempted = metrics['detail_attempted']
            metrics['truncated'] = bool(attempted)
            metrics['reasons'].append(str(exc))
            metrics['identity_pending_urls'].append(base['url'])
            break
        except c.SourceError as exc:
            attempted = metrics['detail_attempted']
            metrics['detail_failed'] += 1
            metrics['reasons'].append(str(exc))
            metrics['identity_pending_urls'].append(base['url'])
            if final is not None:
                invalidated.add(final)
                if row and row['status'] == 'ok' and row['next_attempt'] > core.stamp():
                    metrics['reasons'].append('current_contradiction_invalidates_positive_cache_authority')
                # A contradictory current canonical body revokes all positive
                # reuse for that body. Historical association evidence survives.
                with core.db() as db:
                    for prior_row in db.execute("SELECT url,payload FROM detail_cache WHERE source_id=? AND status='ok'", (source['id'],)).fetchall():
                        try:
                            prior_evidence = json.loads(prior_row['payload']).get('evidence', {})
                            if prior_evidence.get('canonical_url') == final:
                                db.execute("UPDATE detail_cache SET status='error',payload='' WHERE source_id=? AND url=?", (source['id'], prior_row['url']))
                        except (ValueError, TypeError, AttributeError):
                            continue
            if isinstance(exc, c.Blocked):
                status = 'blocked'
                metrics['detail_blocked'] = True
        with core.db() as db:
            db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id,url) DO UPDATE SET fingerprint=excluded.fingerprint,payload=excluded.payload,status=excluded.status,checked_at=excluded.checked_at,next_attempt=excluded.next_attempt',
                       (source['id'], base['url'], fp, payload, status, core.stamp(), core.iso(core.now() + timedelta(hours=24 if payload else 6))))
    revoked_cached = sum(url in invalidated for url in cached_aliases.values())
    cached -= revoked_cached
    metrics['detail_cached'] -= revoked_cached
    out = [item for item in out if item['url'] not in invalidated]
    resolved = {alias: url for alias, url in resolved.items() if url not in invalidated}
    metrics['detail_deferred'] += len(items) - attempted - cached
    metrics['identity_pending_urls'] = [e['url'] for e in items if e['url'] not in resolved]
    # Keep unresolved candidate counts but reconcile identities proven equal.
    dedup = {}
    for item in out:
        if item['url'] in dedup:
            metrics['duplicates'] += 1
            metrics['unique'] -= 1
            prior = dedup[item['url']]
            binding_ids=list(dict.fromkeys(prior.get('_identity_binding_ids',[])+item.get('_identity_binding_ids',[])))
            if item.get('status') == 'cancelled' or item['details'].get('time_conflict'):
                dedup[item['url']] = item
            elif prior.get('start_at') != item.get('start_at'):
                prior['status'] = 'needs_review'
                prior['details']['time_conflict'] = True
            dedup[item['url']]['_identity_binding_ids']=binding_ids
        else:
            dedup[item['url']] = item
    return list(dedup.values())


def bind_stored(source):
    # Exact immutable anchoring is now part of core.ingest's transaction.
    return None


def record_bindings(source, requested, evidence):
    from . import safety
    if len(evidence.get('main_body','').encode())>safety.limits()['slice_bytes']:
        raise c.SourceError('identity_evidence_slice_bound_exceeded')
    ids = []
    variants = [(requested, evidence)]
    final = evidence['canonical_url']
    if final != requested:
        variants.append((final, {**evidence, 'requested_url': final, 'trace': [evidence['trace'][-1]]}))
    with core.db() as db:
        db.execute('BEGIN IMMEDIATE')
        reservation=safety.uid('identity')
        safety.reserve_capacity(db,2*safety.MIB,reservation,'identity_evidence')
        for alias, proof in variants:
            proof=dict(proof)
            if proof.get('main_body'):
                proof['main_body_digest']=safety.blob(db,proof.pop('main_body'),'identity_main_body')
            if len(safety.encoded(proof).encode())>safety.limits()['row_bytes']:
                raise c.SourceError('identity_metadata_bound_exceeded')
            binding = hashlib.sha256((source['id'] + alias + json.dumps(proof, sort_keys=True)).encode()).hexdigest()
            prior = db.execute('SELECT * FROM eefocus_identity_bindings WHERE binding_id=?', (binding,)).fetchone()
            if prior and (prior['source_id'] != source['id'] or prior['alias_url'] != alias or prior['canonical_url'] != final or safety.encoded(json.loads(prior['evidence'])) != safety.encoded(proof)):
                raise c.SourceError('immutable_binding_collision')
            if not prior:
                db.execute('INSERT INTO eefocus_identity_bindings VALUES(?,?,?,?,?,?,NULL)',
                           (binding, source['id'], alias, final, json.dumps(proof), core.stamp()))
            ids.append(binding)
        db.execute('DELETE FROM safety_capacity WHERE reservation_id=?',(reservation,))
    return ids


def resolve_guard_details(source, guard_ids, resolution_id, metrics=None):
    """Detail-only source resolution; never ingest or write successful caches."""
    from . import safety
    with core.db() as db:
        prior=db.execute('SELECT * FROM safety_resolutions WHERE resolution_id=?',(resolution_id,)).fetchone()
        if prior:
            addressed=[row['guard_id'] for row in json.loads(prior['expectations'])]
            if prior['source_id']!=source['id'] or addressed!=guard_ids or prior['kind']!='explicit_same_occurrence_reinstatement':
                raise safety.Integrity('resolution operation ID reused with different scope')
            return json.loads(prior['result'])
    expectations = safety.guard_snapshot(guard_ids)
    if not expectations or len({entry['event_id'] for entry in expectations}) != 1:
        raise safety.Integrity('resolution must name one exact event target')
    with core.db() as db:
        db.execute('BEGIN')
        row = dict(db.execute('SELECT * FROM events WHERE id=?',(expectations[0]['event_id'],)).fetchone())
        authority=safety.resolution_authority(db,row['id'])
        base = dict(row);base['details'] = json.loads(base['details'] or '{}')
        base['url'] = expectations[0]['alias_url']
        base['details']['date_evidence'] = '直播时间：'+base['start_at'][:10].replace('-', '年', 1).replace('-', '月', 1)+'日'
        base['details']['time_evidence'] = []
        base['status'] = 'scheduled'
    metrics = metrics if metrics is not None else dict(detail_attempted=0)
    deadline = time.monotonic()+min(60, float(source.get('max_seconds',60)))
    html, soup, final, trace = fetch(base['url'],source,deadline,metrics)
    item, evidence = detail(base,soup,final,trace)
    check_history(source,base['url'],final,evidence)
    statuses = evidence['current_statuses']
    explicit = re.compile(r'本次(?P<date>20\d{2}年\d{1,2}月\d{1,2}日)(?P<subject>[\u3400-\u9fffA-Za-z0-9]{1,60})原取消安排现已恢复，按原时间举办[。！!]?')
    notices = [match for text in statuses if (match := explicit.fullmatch(date_text(text)))]
    positive = item['details'].get('reinstated') or (len(notices)==len(statuses) and bool(notices)
               and all(match['subject']=='活动' or heading(row['title']).endswith(match['subject']) for match in notices))
    old_dates = sorted({day for entry in expectations for day in json.loads(entry['occurrence'])})
    if (not positive or not statuses or item.get('status')=='cancelled'
            or evidence['occurrence_dates'] != old_dates
            or final != row['url'] or item.get('start_at') != row['start_at']
            or item.get('end_at') != row['end_at'] or bool(item.get('all_day')) != bool(row['all_day'])
            or any(calendar_dates(match['date']) != set(old_dates) for match in notices)):
        raise safety.Integrity('explicit same-occurrence reinstatement missing')
    verified = safety.VerifiedResolution(source['id'],row['id'],html,json.dumps(evidence),authority)
    return safety.resolve_verified(resolution_id,expectations,verified)
