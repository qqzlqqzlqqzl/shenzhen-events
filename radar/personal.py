"""Owner-only review state. Explicit judgements and passive views stay separate."""
import json
from . import core


def serialize(row):
    row = dict(row) if row else {}
    return {'favorite': bool(row.get('favorite')), 'hidden': bool(row.get('hidden')),
            'feedback': row.get('feedback') or '', 'feedback_tags': core.decode_feedback_tags(row.get('feedback_tags')),
            'feedback_updated_at': row.get('feedback_updated_at'), 'revision': int(row.get('revision') or 0),
            'viewed_at': row.get('viewed_at')}


class Conflict(Exception):
    def __init__(self, current):
        self.current = current


def update(event_id, patch, expected_revision=None):
    event_id = core.resolve_event_id(event_id)
    if patch.get('feedback') not in (None, '', *core.FEEDBACK_SIGNALS):
        raise ValueError('无效兴趣反馈')
    tags = patch.get('feedback_tags')
    if tags is not None:
        if len(tags) > len(core.FEEDBACK_TAGS) or any(t not in core.FEEDBACK_TAGS for t in tags):
            raise ValueError('无效反馈标签')
        patch = {**patch, 'feedback_tags': list(dict.fromkeys(tags))}
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM events WHERE id=?', (event_id,)).fetchone():
            raise LookupError('活动不存在')
        current = serialize(c.execute('SELECT * FROM preferences WHERE event_id=?', (event_id,)).fetchone())
        if expected_revision is not None and expected_revision != current['revision']:
            raise Conflict(current)
        changes = {k: v for k, v in patch.items() if k in ('favorite', 'hidden', 'feedback', 'feedback_tags') and v is not None and v != current[k]}
        c.execute('INSERT OR IGNORE INTO preferences(event_id) VALUES(?)', (event_id,))
        if changes:
            next_state = {**current, **changes}
            at = core.now().isoformat(timespec='microseconds') if {'feedback', 'feedback_tags'} & changes.keys() else current['feedback_updated_at']
            c.execute('UPDATE preferences SET favorite=?,hidden=?,feedback=?,feedback_tags=?,feedback_updated_at=?,revision=revision+1 WHERE event_id=?',
                      (int(next_state['favorite']), int(next_state['hidden']), next_state['feedback'], json.dumps(next_state['feedback_tags'], ensure_ascii=False), at, event_id))
        return {'ok': True, 'id': event_id, **serialize(c.execute('SELECT * FROM preferences WHERE event_id=?', (event_id,)).fetchone())}


def viewed(event_id):
    event_id = core.resolve_event_id(event_id)
    with core.db() as c:
        if not c.execute('SELECT 1 FROM events WHERE id=?', (event_id,)).fetchone():
            raise LookupError('活动不存在')
        at = core.now().isoformat(timespec='microseconds')
        c.execute('INSERT INTO preferences(event_id,viewed_at) VALUES(?,?) ON CONFLICT(event_id) DO UPDATE SET viewed_at=excluded.viewed_at', (event_id, at))
    return {'ok': True, 'id': event_id, 'viewed_at': at}
