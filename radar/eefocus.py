"""Admission-gated EEFocus adapter. Selectors are synthetic, pending live review.

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
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from . import collectors as c, core, recurring_sources as rs

KIND = 'eefocus_events'
ORIGIN = 'https://www.eefocus.com'
LIST_URL = ORIGIN + '/event/'
SCHEMA = 'eefocus_identity_v1'


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


def date_parts(text):
    return [(int(m), int(d)) for m, d in re.findall(r'(\d{1,2})月(\d{1,2})日', text)]


def calendar_dates(text):
    dates = set()
    for values in re.findall(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', text):
        try:
            dates.add(datetime(*(int(v) for v in values)).date().isoformat())
        except ValueError:
            continue
    return dates


def schedule(text, attendance, location, exact=True):
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
    root = soup.select_one('main.special-list > ul.section-list-item-ul')
    if root is None:
        raise c.SourceError('inventory_structure_drift')
    nodes = root.select(':scope > li.section-special-item')
    if not nodes and not soup.select_one('[data-fixture-empty-state="true"]'):
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
        location = c.text(node.select_one('.event-location'))
        raw = c.text(node.select_one('.event-time'))
        organizer = re.sub(r'^主办(?:方|单位)?[：:]\s*', '', c.text(node.select_one('.event-organizer')))
        online, offline = '线上' in tags, '线下' in tags
        hybrid = bool(re.search(r'同步(?:直播|线上)|线上\+线下|线上线下同步', tags + summary))
        conflict = online and offline and not hybrid
        mode = 'unknown' if conflict else 'hybrid' if hybrid else 'online' if online else 'offline' if offline else 'unknown'
        start, end, all_day, zone = schedule(raw, mode, location, exact=False)
        status = 'cancelled' if cancelled(label) else 'needs_review' if not start or conflict or mode == 'unknown' else 'scheduled'
        promotion = '推广期' in raw
        meta = {'publisher': '与非网', 'identity_adapter': KIND, 'source_event_id': re.search(r'/(\d+)\.html$', link)[1],
                'evidence_url': link, 'attendance': mode, 'source_status': label,
                'date_evidence': raw, 'checked_at': core.stamp(), 'timezone_status': zone,
                'time_evidence': [{'field': 'list_promotion_window' if promotion else 'list_meeting_time', 'text': raw, 'url': url}]}
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
    if len(bodies) != 1:
        raise c.SourceError('main_event_identity_missing')
    body = BeautifulSoup(str(bodies[0]), 'html.parser').find('article')
    for node in body.select('aside,nav,footer,script,style,.related,.recommendations'):
        node.decompose()
    heads = body.select('h1')
    if len(heads) != 1:
        raise c.SourceError('main_event_identity_missing')
    if heading(c.text(heads[0])) != heading(base['title']):
        raise c.SourceError('main_event_title_mismatch')
    lines = [c.text(n) for n in body.select('p,.meeting-time')]
    times = list(dict.fromkeys(v for v in lines if re.match(r'^(?:活动|直播|举办)时间[：:]', v)))
    if not times and not re.search(r'技术交流活动|研讨会|线上活动', c.text(body)):
        raise c.SourceError('main_event_semantics_missing')
    if re.search(r'回放|资料下载|开发板试用', c.text(body)):
        raise c.SourceError('main_event_semantics_missing')
    raw = base['details'].get('date_evidence', '')
    list_dates, body_dates = set(date_parts(raw)), {d for t in times for d in date_parts(t)}
    orgs = rs._labeled(lines, ('主办方', '主办单位', '主办'))
    list_org = base.get('organizer', '')
    if list_org and orgs and any(heading(v) != heading(list_org) for v in orgs):
        raise c.SourceError('event_anchor_conflict')
    # Promotion endpoint can corroborate the actual occurrence, never its duration.
    if list_dates and body_dates and (not list_dates.intersection(body_dates)
                                     or ('推广期' not in raw and list_dates != body_dates)):
        raise c.SourceError('event_anchor_conflict')
    list_years = set(re.findall(r'20\d{2}年', raw))
    body_years = {y for t in times for y in re.findall(r'20\d{2}年', t)}
    if '推广期' not in raw and list_years and body_years and list_years != body_years:
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
    elif any(re.search(r'恢复举办|已恢复|恢复举行', s) for s in statuses):
        meta['source_status'] = '已恢复举办'
        meta['reinstated'] = True
    evidence = {'schema': SCHEMA, 'title': c.text(heads[0]), 'shared_dates': shared,
                'organizer_agenda_match': bool(agenda_match), 'requested_url': base['url'],
                'canonical_url': final, 'trace': trace,
                'occurrence_dates': sorted({v[0][:10] for v in schedules}),
                'organizers': orgs,
                'reschedule_text': [v for v in lines if re.search(r'原定.*(?:改期|延期|调整)|(?:改期|延期|调整)至', v)],
                'body_digest': hashlib.sha256(str(body).encode()).hexdigest()}
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
        if not inventory:
            metrics['detail_attempted'] += 1
        return c.fetch(target, **kw, url_policy=lambda u: safe_url(u, inventory),
                       request_observer=observed, include_trace=True)
    return rs.bounded_fetch(request, url, source, deadline, metrics, max_bytes=1000000)


def enrich(source, items, metrics, deadline):
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
                item = merge_detail(base, payload['item'])
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
            with core.db() as db:
                history = db.execute('SELECT canonical_url,evidence FROM eefocus_identity_bindings WHERE source_id=? AND alias_url=? ORDER BY rowid DESC LIMIT 1',
                                     (source['id'], base['url'])).fetchone()
            if history:
                prior = json.loads(history['evidence'])
                if history['canonical_url'] != final:
                    raise c.SourceError('historical_canonical_conflict')
                old_dates, new_dates = set(prior.get('occurrence_dates', [])), set(evidence['occurrence_dates'])
                if old_dates and new_dates and old_dates != new_dates:
                    notices = ' '.join(evidence['reschedule_text'])
                    if not notices or not (old_dates | new_dates).issubset(calendar_dates(notices)):
                        raise c.SourceError('historical_occurrence_conflict')
                if prior.get('organizers') and evidence['organizers'] and prior['organizers'] != evidence['organizers']:
                    raise c.SourceError('historical_organizer_conflict')
            out.append(item)
            resolved[base['url']] = item['url']
            metrics['detail_resolved'] += 1
            payload = json.dumps({'item': item, 'evidence': evidence}, ensure_ascii=False)
            status = 'ok'
            with core.db() as db:
                binding = hashlib.sha256((source['id'] + base['url'] + json.dumps(evidence, sort_keys=True)).encode()).hexdigest()
                db.execute('INSERT OR IGNORE INTO eefocus_identity_bindings VALUES(?,?,?,?,?,?,NULL)',
                           (binding, source['id'], base['url'], final, json.dumps(evidence), core.stamp()))
                if final != base['url']:
                    # The final response itself proves this direct self-mapping;
                    # no transitive alias graph or guessed numeric-ID relation.
                    direct = {**base, 'url': final, 'details': {**base['details'],
                              'source_event_id': item['details']['source_event_id'], 'evidence_url': final}}
                    direct_evidence = {**evidence, 'requested_url': final, 'trace': [trace[-1]]}
                    db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id,url) DO UPDATE SET fingerprint=excluded.fingerprint,payload=excluded.payload,status=excluded.status,checked_at=excluded.checked_at,next_attempt=excluded.next_attempt',
                               (source['id'], final, rs.detail_fingerprint(direct), json.dumps({'item': item, 'evidence': direct_evidence}), 'ok', core.stamp(), core.iso(core.now()+timedelta(hours=24))))
                    direct_binding = hashlib.sha256((source['id'] + final + json.dumps(direct_evidence, sort_keys=True)).encode()).hexdigest()
                    db.execute('INSERT OR IGNORE INTO eefocus_identity_bindings VALUES(?,?,?,?,?,?,NULL)',
                               (direct_binding, source['id'], final, final, json.dumps(direct_evidence), core.stamp()))
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
            if item.get('status') == 'cancelled' or item['details'].get('time_conflict'):
                dedup[item['url']] = item
            elif prior.get('start_at') != item.get('start_at'):
                prior['status'] = 'needs_review'
                prior['details']['time_conflict'] = True
        else:
            dedup[item['url']] = item
    return list(dedup.values())


def bind_stored(source):
    with core.db() as db:
        db.execute('UPDATE eefocus_identity_bindings SET event_id=(SELECT event_id FROM event_sources WHERE source_id=eefocus_identity_bindings.source_id AND url=eefocus_identity_bindings.canonical_url) WHERE source_id=? AND event_id IS NULL', (source['id'],))
