"""Three bounded public recurring inventories. Source text is data, never code."""
from __future__ import annotations

import hashlib
import json
import re
import signal
import threading
import time
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit

from . import aggregates, collectors as c, core

KINDS = frozenset(('elecfans_webinar', 'xuanwu_activity', 'shenzhenware_events'))
HOSTS = {'elecfans_webinar': 'webinar.elecfans.com',
         'xuanwu_activity': 'xuanwu.openatom.org',
         'shenzhenware_events': 'www.shenzhenware.com'}
PATHS = {'elecfans_webinar': r'/\d+\.html',
         'xuanwu_activity': r'/articles/activity/[a-zA-Z0-9_-]+\.html',
         'shenzhenware_events': r'/events/\d+'}


class Deadline(c.SourceError):
    pass


def bounded_fetch(fetch, url, source, deadline, metrics, max_bytes=1600000):
    """Reuse public/redirect checks with a hard deadline in the Linux worker.

    Fail closed outside the main thread or if another alarm is already in use.
    Only this process's temporary timer is changed; no background fetch survives.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Deadline('到达本轮时间上限')
    if (threading.current_thread() is not threading.main_thread()
            or not hasattr(signal, 'setitimer')):
        raise c.SourceError('来源需要支持限时请求的采集线程')
    if signal.getitimer(signal.ITIMER_REAL)[0]:
        raise c.SourceError('来源限时请求不能覆盖已有计时器')
    old_handler = signal.getsignal(signal.SIGALRM)

    def expired(*_):
        raise Deadline('到达本轮时间上限')

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    metrics['requests_attempted'] = metrics.get('requests_attempted', 0) + 1
    try:
        return fetch(url, max_bytes=max_bytes, proxy=source.get('proxy'))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def pause(source, deadline):
    delay = max(0, min(5, float(source.get('request_delay', 1))))
    if time.monotonic() + delay >= deadline:
        raise Deadline('到达本轮时间上限')
    time.sleep(delay)


def same_origin(url, kind):
    try:
        p = urlsplit(url)
        return (p.scheme == 'https' and p.hostname == HOSTS[kind]
                and not p.username and not p.password and p.port in (None, 443))
    except ValueError:
        return False


def event_url(href, base, kind):
    url = urljoin(base, str(href or ''))
    if not same_origin(url, kind) or not re.fullmatch(PATHS[kind], urlsplit(url).path):
        return ''
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, '', ''))


def _notes(details, value):
    if value:
        old = details.get('review_notes', '')
        details['review_notes'] = '; '.join(dict.fromkeys(x for x in (old, value) if x))


def _dates(value):
    value = re.sub(r'\s*([年月日./-])\s*', r'\1', core.clean(value))
    return aggregates.explicit_range(value)


def _local_clock(value):
    m = re.fullmatch(r'(20\d{2})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?',
                     core.clean(value))
    if not m:
        return None
    try:
        y, month, day, hour, minute, second = (int(x or 0) for x in m.groups())
        return datetime(y, month, day, hour, minute, second, tzinfo=core.TZ)
    except ValueError:
        return None


def _mode(text, location):
    live = bool(re.search(r'线上直播|在线(?:上)?观看.{0,12}直播|(?:同步|同时).{0,12}直播', text))
    return 'hybrid' if location and live else 'offline' if location else 'unknown'


def _status(label):
    return 'cancelled' if re.search(r'取消|取消举办|已取消', label) else 'scheduled'


def elecfans_webinars(soup, url):
    if not same_origin(url, 'elecfans_webinar'):
        raise c.SourceError('研讨会列表来源不匹配')
    nodes = soup.select('li.bd-wrap')
    if not nodes:
        if soup.select_one('.webinar-empty,.bd-empty') and re.search(r'暂无|没有', c.text(soup)):
            return [], 0, {}
        raise c.SourceError('研讨会列表结构发生变化')
    out, rejected, seen = [], Counter(), set()
    for node in nodes:
        a = node.select_one('.activity-info h3 a[href]')
        link = event_url(a.get('href') if a else '', url, 'elecfans_webinar')
        if not a or not link or not c.text(a):
            rejected['非研讨会详情链接'] += 1
            continue
        if link in seen:
            rejected['重复活动链接'] += 1
            continue
        seen.add(link)
        raw = c.text(node.select_one('.activity-info p span'))
        start, end = _dates(raw)
        meta = {'publisher': '电子发烧友', 'evidence_url': link, 'date_evidence': raw,
                'time_evidence': [{'field': 'list_time', 'text': raw, 'url': url}],
                'attendance': 'online', 'source_event_id': urlsplit(link).path,
                'timezone_status': 'unconfirmed', 'checked_at': core.stamp()}
        _notes(meta, f'原文时间：{raw or "未注明"}；未注明时区，暂按来源日期展示，'
                    '不表示全天直播；开播时间请核对原文。')
        label = c.text(node.select_one('.status'))
        if re.search(r'回放|已结束|重播', label):
            rejected['已结束或回放'] += 1
            continue
        meta['source_status'] = label
        out.append(c.skeleton(c.text(a), link, c.text(node.select_one('.bd-wrap-txt')),
                              '线上', city='线上', start_at=start, end_at=end,
                              all_day=bool(start), status=_status(label),
                              organizer='', cost_text='', event_type='ConferenceEvent',
                              details=meta))
    return out, len(nodes), dict(rejected)


def discover_module(soup, url):
    if not same_origin(url, 'xuanwu_activity'):
        raise c.SourceError('旋武活动目录来源不匹配')
    candidates = set()
    for node in soup.select('link[rel=modulepreload][href]'):
        href = urljoin(url, node['href'])
        if re.fullmatch(r'/assets/activity_index\.md\.[A-Za-z0-9_-]+\.lean\.js',
                        urlsplit(href).path):
            if not same_origin(href, 'xuanwu_activity') or urlsplit(href).query:
                raise c.SourceError('旋武活动模块必须同源')
            candidates.add(href)
    if len(candidates) != 1:
        raise c.SourceError('未找到唯一的旋武活动库存模块')
    return candidates.pop()


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key')
        value[key] = item
    return value


def module_inventory(module, module_url):
    if (not same_origin(module_url, 'xuanwu_activity')
            or not re.fullmatch(r'/assets/activity_index\.md\.[A-Za-z0-9_-]+\.lean\.js',
                                urlsplit(module_url).path)
            or len(module) > 1000000):
        raise c.SourceError('旋武活动模块来源或长度无效')
    match = re.search(r'\bJSON\.parse\s*\(\s*', module)
    if not match or module[match.end():match.end()+1] != chr(96):
        raise c.SourceError('旋武活动模块不是受支持的纯JSON字面量')
    begin = match.end() + 1
    end = module.find(chr(96), begin)
    literal = module[begin:end] if end >= 0 else ''
    if (end < 0 or '\\' in literal or ('$' + '{') in literal
            or not re.match(r'\s*\)', module[end+1:])):
        raise c.SourceError('旋武活动模块包含不支持的转义、插值或表达式')
    try:
        inventory = json.loads(literal, object_pairs_hook=_unique_object,
                               parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, TypeError, RecursionError) as exc:
        raise c.SourceError('旋武活动库存JSON无效') from exc
    if not isinstance(inventory, list) or len(inventory) > 300:
        raise c.SourceError('旋武活动库存形状无效')
    for row in inventory:
        if (not isinstance(row, dict) or not isinstance(row.get('frontmatter'), dict)
                or row['frontmatter'].get('type') != 'activity'
                or not isinstance(row.get('url'), str)):
            raise c.SourceError('旋武活动库存记录类型发生变化')
        fm = row['frontmatter']
        for key in ('title', 'startTime', 'endTime', 'location', 'address', 'addressName',
                    'desc', 'sponsor', 'createTime', 'reviewUrl', 'signUpLink'):
            if key in fm and not isinstance(fm[key], str):
                raise c.SourceError('旋武活动字段类型发生变化')
    return inventory


def xuanwu_events(module, module_url):
    inventory = module_inventory(module, module_url)
    out, rejected, originals = [], Counter(), {}
    for row in inventory:
        link = event_url(row['url'], module_url, 'xuanwu_activity')
        if link and not link.endswith('-review.html'):
            originals[link] = row
    recaps = {}
    for row in inventory:
        fm = row['frontmatter']
        link = event_url(row['url'], module_url, 'xuanwu_activity')
        if not link.endswith('-review.html'):
            continue
        original = link[:-len('-review.html')] + '.html'
        other = originals.get(original)
        if (other and _local_clock(fm.get('startTime')) is not None
                and _local_clock(fm.get('startTime')) == _local_clock(other['frontmatter'].get('startTime'))
                and core.norm(fm.get('address') or fm.get('addressName'))
                and core.norm(fm.get('address') or fm.get('addressName'))
                    == core.norm(other['frontmatter'].get('address') or other['frontmatter'].get('addressName'))):
            recaps.setdefault(original, []).append(row)
    seen = set()
    for row in inventory:
        fm = row['frontmatter']
        link = event_url(row['url'], module_url, 'xuanwu_activity')
        location = core.clean(' '.join(fm.get(k, '') for k in ('location', 'addressName', 'address')))
        if '深圳' not in location and 'shenzhen' not in location.casefold():
            rejected['其他城市或城市未确认'] += 1
            continue
        if not link or not core.clean(fm.get('title')):
            rejected['无有效活动标题或链接'] += 1
            continue
        if link.endswith('-review.html'):
            rejected['回顾作为原活动证据' if any(row in rs for rs in recaps.values())
                     else '无可核验预告的独立回顾'] += 1
            continue
        if link in seen:
            rejected['重复活动链接'] += 1
            continue
        seen.add(link)
        start, end = _local_clock(fm.get('startTime')), _local_clock(fm.get('endTime'))
        invalid = start is None or (fm.get('endTime') and (end is None or end < start))
        meta = {'publisher': '开放原子旋武社区', 'evidence_url': link,
                'source_event_id': urlsplit(link).path,
                'date_evidence': fm.get('startTime', ''),
                'time_evidence': [{'field': k, 'text': fm.get(k, ''), 'url': link}
                                  for k in ('startTime', 'endTime')],
                'timezone_status': 'venue_local', 'timezone_evidence': '深圳现场场馆的本地时间解释',
                'attendance': _mode(fm.get('desc', ''), location), 'checked_at': core.stamp(),
                'venue_name': fm.get('addressName', ''), 'registration_url': core.canon_url(fm.get('signUpLink', '')),
                'organizer_notes': '原站将sponsor字段渲染为主办方；保留来源陈述，不作独立背书。'}
        if invalid:
            start = end = None
            _notes(meta, '来源活动起止时间无效或顺序冲突，需核对原文；未用发布日期补活动日期。')
        status = 'needs_review' if invalid else 'scheduled'
        related = recaps.get(link, [])
        if related:
            meta['recap_urls'] = [event_url(r['url'], module_url, 'xuanwu_activity') for r in related]
            for recap in related:
                rm = recap['frontmatter']
                meta['time_evidence'].extend({'field': 'recap_'+k, 'text': rm.get(k, ''),
                                             'url': event_url(recap['url'], module_url, 'xuanwu_activity')}
                                            for k in ('startTime', 'endTime'))
                if _local_clock(rm.get('endTime')) != end:
                    status = 'needs_review'
                    meta['time_conflict'] = True
                    _notes(meta, '预告与回顾结束时间冲突，保留预告计划，不用回顾覆盖。')
        if fm.get('reviewUrl') or re.search(r'成功举办|圆满落幕', fm.get('desc', '')):
            meta['source_status'] = '历史活动/回顾内容'
        out.append(c.skeleton(core.clean(fm['title']), link, core.clean(fm.get('desc', '')),
                              fm.get('address') or fm.get('addressName') or fm.get('location', ''),
                              city='深圳', organizer=core.clean(fm.get('sponsor', '')), cost_text='',
                              start_at=core.iso(start), end_at=core.iso(end), all_day=False,
                              published_at=fm.get('createTime', ''), status=status,
                              event_type='ConferenceEvent', details=meta))
    return out, len(inventory), dict(rejected)


def regular_urls(soup, url):
    return tuple(event_url(a['href'], url, 'shenzhenware_events')
                 for a in soup.select('.regular-events-list .event-item .card-meta a.initial[href]')
                 if event_url(a['href'], url, 'shenzhenware_events'))


def shenzhenware_events(soup, url):
    if not same_origin(url, 'shenzhenware_events'):
        raise c.SourceError('深圳湾活动列表来源不匹配')
    root = soup.select_one('.regular-events-list')
    nodes = soup.select('.hot .activity,.regular-events-list .event-item')
    if root is None or (not nodes and c.text(root) and not re.search(r'暂无|没有|无活动', c.text(root))):
        raise c.SourceError('深圳湾活动列表结构发生变化')
    out, rejected, seen = [], Counter(), set()
    for node in nodes:
        a = node.select_one('.card-meta a.initial[href]')
        link = event_url(a.get('href') if a else '', url, 'shenzhenware_events')
        if not a or not link or not c.text(a):
            rejected['非正式活动详情链接'] += 1
            continue
        if link in seen:
            rejected['重复活动链接'] += 1
            continue
        seen.add(link)
        raw, location = c.text(node.select_one('.card-times')), c.text(node.select_one('.card-map'))
        start, end = _dates(raw)
        label = c.text(node.select_one('.status'))
        tags = [c.text(n) for n in node.select('.tag')]
        meta = {'publisher': '深圳湾', 'evidence_url': link, 'source_event_id': urlsplit(link).path,
                'date_evidence': raw, 'time_evidence': [{'field': 'list_date', 'text': raw, 'url': url}],
                'attendance': _mode(' '.join(tags), location), 'source_status': label,
                'checked_at': core.stamp()}
        if not start:
            _notes(meta, '来源未提供可确定年份的活动日期，未用抓取或发布日期补年。')
        if re.search(r'审核.*通知|另行通知|地址.*待', location):
            meta['address_precision'] = 'undisclosed'
            _notes(meta, '具体地址需审核后通知；未推断场馆或坐标。')
        out.append(c.skeleton(c.text(a), link, ' '.join(tags), location, city='深圳' if '深圳' in location or 'shenzhen' in location.casefold() else '',
                              start_at=start, end_at=end, all_day=bool(start),
                              organizer='', cost_text='', status=_status(label),
                              details=meta))
    return out, len(nodes), dict(rejected)


def parse(kind, html, soup, url):
    if kind == 'elecfans_webinar':
        return elecfans_webinars(soup, url)
    if kind == 'xuanwu_activity':
        return xuanwu_events(html, url)
    if kind == 'shenzhenware_events':
        return shenzhenware_events(soup, url)
    raise c.SourceError('来源类型尚未适配')


def _lines(body):
    if body is None:
        raise c.SourceError('活动详情主体结构发生变化')
    lines = [core.clean(s) for s in body.get_text('\n', strip=True).splitlines() if core.clean(s)]
    for i, line in enumerate(lines):
        if re.match(r'^(?:往届活动和嘉宾|往期活动专题)', line):
            return lines[:i]
    return lines


def _labeled(lines, labels):
    return aggregates.labeled('\n'.join(lines), labels)


def _clock_range(label):
    start, _ = _dates(label)
    clocks = re.search(r'(\d{1,2}):(\d{2})\s*[—–~至-]\s*(\d{1,2}):(\d{2})', label)
    if not start or not clocks:
        return None
    try:
        a, b = (datetime.fromisoformat(start).replace(hour=int(clocks[1]), minute=int(clocks[2])),
                datetime.fromisoformat(start).replace(hour=int(clocks[3]), minute=int(clocks[4])))
        return (core.iso(a), core.iso(b)) if b > a else None
    except ValueError:
        return None


def detail(kind, base, soup, url):
    if event_url(url, url, kind) != base['url']:
        raise c.SourceError('活动详情跳转不匹配')
    if kind == 'shenzhenware_events':
        body = soup.select_one('.correlation-center.medium-editor-content')
    elif kind == 'xuanwu_activity':
        body = soup.select_one('.vp-doc')
    else:
        body = soup.select_one('.bd-wrap-txt,.webinar-content,.bd-content')
    lines = _lines(body)
    metadata = {'evidence_url': url, 'checked_at': core.stamp(),
                'detail_text': '\n'.join(lines)[:10000]}
    patch = {'details': metadata}
    for key, labels in [('organizer', ('主办方', '主办单位', '主办')),
                        ('cost_text', ('活动费用', '门票价格', '参会费用'))]:
        values = _labeled(lines, labels)
        if len(values) == 1:
            patch[key] = values[0][:200]
            metadata[key+'_evidence'] = values[0]
    if kind == 'xuanwu_activity':
        metadata['attendance'] = _mode(' '.join(lines), base.get('location', ''))
    if kind == 'shenzhenware_events':
        raw_times = _labeled(lines, ('时间', '活动时间'))
        header = soup.select_one('.event-brief-info')
        if header:
            raw_times = [c.text(n) for n in header.select('.card-items')
                         if _clock_range(c.text(n))] + raw_times
        metadata['time_evidence'] = [{'field': 'detail_time', 'text': v, 'url': url}
                                     for v in dict.fromkeys(raw_times)]
        ranges = list(dict.fromkeys(r for v in raw_times if (r := _clock_range(v))))
        if len(ranges) > 1:
            patch['status'] = 'needs_review'
            metadata['time_conflict'] = True
            _notes(metadata, '活动顶部与正文起止时钟冲突：' + '；'.join(dict.fromkeys(raw_times))
                   + '。保留日期粒度，精确时间请核对原文。')
        elif len(ranges) == 1:
            patch.update(start_at=ranges[0][0], end_at=ranges[0][1], all_day=False)
            metadata['timezone_status'] = 'venue_local'
            metadata['timezone_evidence'] = '明确深圳现场场馆的本地时间解释'
        locations = _labeled(lines, ('地点', '活动地点'))
        if len(locations) == 1:
            patch['location'] = locations[0]
    return patch


def merge_detail(base, patch):
    """Fresh listing schedule, cancellation, city and holds outrank old detail patches."""
    out = {**base, 'details': dict(base.get('details') or {})}
    meta = dict(patch.get('details') or {})
    for key in ('attendance', 'date_evidence', 'source_status', 'review_hold'):
        if out['details'].get(key):
            meta[key] = out['details'][key]
    if out['details'].get('time_conflict'):
        meta['time_conflict'] = True
    if (out['details'].get('attendance') in ('offline', 'unknown')
            and (patch.get('details') or {}).get('attendance') == 'hybrid'):
        meta['attendance'] = 'hybrid'
    for key in ('review_notes', 'time_evidence'):
        if key in out['details'] and key in meta:
            if key == 'review_notes':
                meta[key] = '; '.join(dict.fromkeys((out['details'][key], meta[key])))
            else:
                meta[key] = out['details'][key] + [x for x in meta[key] if x not in out['details'][key]]
    out['details'].update(meta)
    for key in ('organizer', 'cost_text'):
        if not out.get(key) and patch.get(key):
            out[key] = patch[key]
    if not out.get('location') and patch.get('location'):
        out['location'] = patch['location']
    if patch.get('start_at'):
        same_date = (base.get('start_at') and patch['start_at'][:10] == base['start_at'][:10])
        single_day = (base.get('start_at') and base.get('end_at')
                      and datetime.fromisoformat(base['end_at']) - datetime.fromisoformat(base['start_at']) == timedelta(days=1))
        if same_date and single_day and base.get('all_day') and base.get('city') == '深圳':
            out.update({k: patch[k] for k in ('start_at', 'end_at', 'all_day')})
        elif (same_date and base.get('all_day') and not single_day) or not same_date or (not base.get('all_day') and any(
                patch.get(k) != base.get(k) for k in ('start_at', 'end_at') if k in patch)):
            out['status'] = 'needs_review'
            out['details']['time_conflict'] = True
            _notes(out['details'], '新列表与详情活动时间不一致，保留新列表，需核对原文。')
    if patch.get('status') == 'needs_review' or out['details'].get('review_hold') or out['details'].get('time_conflict'):
        out['status'] = 'needs_review'
    if base.get('status') == 'cancelled':
        out['status'] = 'cancelled'
    return out


def detail_fingerprint(event):
    stable = {k: v for k, v in event.items() if k not in ('details', 'published_at')}
    stable['details'] = {k: v for k, v in (event.get('details') or {}).items() if k != 'checked_at'}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def enrich_details(source, items, metrics, fetch):
    limit = max(0, min(12, int(source.get('detail_budget', 8))))
    deadline = source['_deadline']
    cutoff = core.iso(core.now() - timedelta(days=45))
    with core.db() as db:
        cache = {r['url']: dict(r) for r in db.execute('SELECT * FROM detail_cache WHERE source_id=?',
                                                     (source['id'],))}
    out, pending = [], []
    for base in items:
        idx = len(out)
        out.append(base)
        if (base.get('end_at') or base.get('start_at') or '9999') < cutoff:
            continue
        fp = detail_fingerprint(base)
        old = cache.get(base['url'])
        if old and old['fingerprint'] == fp and old['next_attempt'] > core.stamp():
            payload = json.loads(old['payload']) if old['payload'] else {}
            if isinstance(payload.get('patch'), dict):
                out[idx] = merge_detail(base, payload['patch'])
                metrics['detail_cached'] += 1
                continue
            if not old['payload']:
                metrics['detail_deferred'] += 1
                continue
        pending.append((old['checked_at'] if old else '', idx, base, fp))
    pending.sort(key=lambda item: item[0])
    attempted = 0
    for _, idx, base, fp in pending[:limit]:
        if time.monotonic() >= deadline:
            break
        payload, status = '', 'error'
        try:
            pause(source, deadline)
            metrics['detail_attempted'] += 1
            attempted += 1
            _, soup, final = bounded_fetch(fetch, base['url'], source, deadline, metrics, max_bytes=1000000)
            patch = detail(source['kind'], base, soup, final)
            out[idx] = merge_detail(base, patch)
            payload = json.dumps({'patch': patch}, ensure_ascii=False)
            status = 'ok'
            metrics['detail_resolved'] += 1
        except Deadline as exc:
            metrics['reasons'].append(str(exc))
            metrics['truncated'] = True
            break
        except c.SourceError as exc:
            status = 'blocked' if isinstance(exc, c.Blocked) else 'error'
            metrics['detail_failed'] += 1
            metrics['reasons'].append(str(exc))
            metrics['detail_blocked'] = status == 'blocked'
        retry = core.iso(core.now() + timedelta(hours=24 if payload else 6))
        with core.db() as db:
            db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id,url) '
                       'DO UPDATE SET fingerprint=excluded.fingerprint,payload=excluded.payload,'
                       'status=excluded.status,checked_at=excluded.checked_at,next_attempt=excluded.next_attempt',
                       (source['id'], base['url'], fp, payload, status, core.stamp(), retry))
        if status == 'blocked':
            break
    metrics['detail_deferred'] += max(0, len(pending) - attempted)
    return out
