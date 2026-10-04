"""Synthetic calendar/facet dataset shared by isolated API and browser reviews."""
import json


def seed(core, source_id='ux-fixture'):
    source = {'id': source_id, 'priority': 10}
    fixtures = [
        ('art-offline', 'UX 南山美术展', '2026-10-08T10:00:00+08:00', '2026-10-08T12:00:00+08:00', 'ExhibitionEvent', ['文化艺术'], 'offline', '免费', False),
        ('art-online', 'UX 线上艺术讲堂', '2026-10-09T10:00:00+08:00', '2026-10-09T12:00:00+08:00', 'ExhibitionEvent', ['文化艺术'], 'online', '199元', False),
        ('art-hybrid', 'UX 音乐交流会', '2026-10-10T10:00:00+08:00', '2026-10-10T12:00:00+08:00', 'MusicEvent', ['文化艺术', '社交交流'], 'hybrid', '免费', False),
        ('robot', 'UX 机器人技术论坛', '2026-10-11T10:00:00+08:00', '2026-10-11T12:00:00+08:00', 'ConferenceEvent', ['机器人'], 'offline', '免费', False),
        ('cross', 'UX 跨月摄影节', '2026-09-30', '2026-10-02', 'ExhibitionEvent', ['文化艺术'], 'offline', '免费', True),
        ('long', 'UX 长期文化展', '2026-09-01', '2026-11-01', 'ExhibitionEvent', ['文化艺术'], 'offline', '免费', True),
        ('favorite-long', 'UX 收藏机器人展', '2026-09-02', '2026-11-02', 'ExhibitionEvent', ['机器人'], 'offline', '免费', True),
        ('hidden', 'UX 已隐藏活动', '2026-10-13', '2026-10-15', 'ExhibitionEvent', ['文化艺术'], 'offline', '免费', True),
        ('next', 'UX 下月艺术展', '2026-11-01', '2026-11-02', 'ExhibitionEvent', ['文化艺术'], 'offline', '免费', True),
        ('undated', 'UX 收藏待定活动', None, None, 'ExhibitionEvent', ['文化艺术'], 'unknown', '免费', False),
    ]
    ids = {}
    for key, title, start, end, kind, topics, mode, cost, all_day in fixtures:
        url = 'https://example.com/ux-calendar/' + key
        core.ingest(source, dict(title=title, url=url, start_at=start, end_at=end,
                    all_day=all_day, location='深圳南山合成场馆', summary='仅用于隔离 UX 复核。',
                    event_type=kind, event_type_state='source', topics=topics,
                    cost_text=cost, details={'attendance': mode}))
        with core.db() as c:
            ids[key] = c.execute('SELECT id FROM events WHERE url=?', (url,)).fetchone()[0]
            # Preserve precisely declared fixture dimensions; no inference is under test here.
            c.execute('UPDATE events SET topics=?,event_type=?,event_type_state=?,details=? WHERE id=?',
                      (json.dumps(topics), kind, 'source', json.dumps({'attendance': mode}), ids[key]))
    with core.db() as c:
        for key in ('art-offline', 'favorite-long', 'undated'):
            c.execute('INSERT INTO preferences(event_id,favorite) VALUES(?,1)', (ids[key],))
        c.execute('INSERT INTO preferences(event_id,hidden) VALUES(?,1)', (ids['hidden'],))
    return ids
