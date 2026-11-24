from __future__ import annotations
import json
from datetime import timedelta

import pytest

from radar import api, core, worker


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    (tmp_path / 'static').mkdir(); (tmp_path / 'static/index.html').write_text('<html>test</html>')
    (tmp_path / 'sources.json').write_text(json.dumps([{'id': 'a', 'name': '测试源', 'url': 'https://example.com', 'priority': 10, 'interval_hours': 6}]))
    monkeypatch.setattr(core, 'ROOT', tmp_path); monkeypatch.setattr(api, 'ROOT', tmp_path); monkeypatch.setattr(worker, 'ROOT', tmp_path)
    api.initialize_settings(); core.init()
    cfg = core.config(); cfg['analysis_enabled'] = True; (core.ROOT / '.private/settings.json').write_text(json.dumps(cfg))
    monkeypatch.setattr(worker, 'backfill_types', lambda *args: 0); monkeypatch.setattr(worker, 'geocode_pending', lambda *args: 0)
    monkeypatch.setattr(worker.time, 'sleep', lambda *args: None)
    yield tmp_path


def ingest(title):
    start = core.now() + timedelta(days=3)
    core.ingest({'id': 'a', 'priority': 10}, {'title': title, 'url': 'https://example.com/' + title, 'start_at': start.isoformat(),
                                              'end_at': (start + timedelta(hours=2)).isoformat(), 'location': '深圳市南山区测试中心',
                                              'summary': title, 'topics': ['其他'], 'cost_text': '免费'})


def test_parse_model_json_escapes_inner_quotes_and_fences():
    broken = '{\n "items": [\n  {"id": 1, "summary": "论坛机器人专场，主题"智启龙岗·具身领航"。包含演讲", "topics": ["机器人"]}\n ]\n}'
    assert worker.parse_model_json(broken)['items'][0]['summary'] == '论坛机器人专场，主题"智启龙岗·具身领航"。包含演讲'
    assert worker.parse_model_json('```json\n{"items": [{"id": 2, "s": "已 \\"转义\\""}]}\n```')['items'][0]['s'] == '已 "转义"'
    with pytest.raises(ValueError):
        worker.parse_model_json('not json at all')


def test_one_malformed_item_cannot_block_the_queue(monkeypatch):
    for title in ('活动甲', '活动乙', '活动丙'):
        ingest(title)
    with core.db() as c:
        ids = {r['title']: r['id'] for r in c.execute('select id,title from raw_items')}
    bad = ids['活动乙']

    def fake(rows):
        if len(rows) > 1 or rows[0]['id'] == bad:
            raise ValueError('malformed model output')
        return [{'id': rows[0]['id'], 'is_shenzhen_offline': True, 'event_type': 'SocialEvent', 'topics': ['其他'],
                 'priority': 'normal', 'commercial': 'low', 'reason': '交流', 'summary': '说明'}]

    monkeypatch.setattr(worker, 'ai_batch', fake)
    assert worker.analyze(10) is None
    with core.db() as c:
        states = {r['title']: r['analysis_state'] for r in c.execute('select title,analysis_state from raw_items')}
    assert states == {'活动甲': 'done', '活动乙': 'model_error', '活动丙': 'done'}


def test_transport_error_still_stops_the_run(monkeypatch):
    ingest('活动甲')
    monkeypatch.setattr(worker, 'ai_batch', lambda rows: (_ for _ in ()).throw(RuntimeError('模型接口 HTTP 502')))
    worker.analyze(10)
    with core.db() as c:
        assert c.execute('select analysis_state from raw_items').fetchone()[0] == 'pending'
