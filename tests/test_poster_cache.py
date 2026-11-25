import io
import json
from datetime import timedelta

import pytest
from PIL import Image

from radar import core, poster_cache, posters


def picture(size=(1600, 900), fmt='PNG'):
    buf = io.BytesIO()
    Image.new('RGB', size, (200, 120, 40)).save(buf, fmt)
    return buf.getvalue()


class Response:
    def __init__(self, status=200, body=b'', kind='image/png'):
        self.status_code, self.body, self.headers = status, body, {'content-type': kind}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, size):
        yield self.body


class Session:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def get(self, url, headers=None, **kwargs):
        self.calls.append((url, headers.get('Referer')))
        return self.answers[url]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    (tmp_path / 'static/posters').mkdir(parents=True)
    (tmp_path / 'static/posters/manifest.json').write_text('{}')
    (tmp_path / 'sources.json').write_text('[]')
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(poster_cache.time, 'sleep', lambda *a: None)
    core.init()
    yield tmp_path


def add_event(eid, images, days=3, status='scheduled', url='https://example.com/e'):
    start = core.now() + timedelta(days=days)
    with core.db() as c:
        c.execute("INSERT INTO events(id,title,start_at,end_at,status,url,priority,details) VALUES(?,?,?,?,?,?,?,?)",
                  (eid, eid, start.isoformat(timespec='seconds'), (start + timedelta(hours=2)).isoformat(timespec='seconds'),
                   status, url, 'high', json.dumps({'images': images})))


def test_images_become_small_local_webp_and_reach_display_details(isolated):
    add_event('a', ['https://img.test/1.png', 'https://img.test/icon.png'])
    session = Session({'https://img.test/1.png': Response(body=picture()),
                       'https://img.test/icon.png': Response(body=picture((40, 40)))})
    stats = poster_cache.run(session=session)
    assert stats['fetched'] == 1 and stats['icons'] == 1 and stats['failed'] == 0
    assert session.calls[0][1] == 'https://example.com/e'     # the event page is the referer
    state = json.loads((isolated / 'data/poster-cache.json').read_text())
    name = state['images']['https://img.test/1.png']
    with Image.open(isolated / 'static/posters' / name) as im:
        assert im.format == 'WEBP' and im.size[0] <= 960
    assert state['icons'] == {'https://img.test/icon.png': {'why': 'icon 40x40'}} and state['failures'] == {}
    shown = posters.display_details({'images': ['https://img.test/1.png', 'https://img.test/icon.png']}, isolated)
    assert shown['cached_images'] == {'https://img.test/1.png': '/events/static/posters/' + name}


def test_failures_back_off_and_cached_images_are_not_refetched(isolated):
    add_event('a', ['https://img.test/1.png', 'https://img.test/broken'])
    first = Session({'https://img.test/1.png': Response(body=picture()),
                     'https://img.test/broken': Response(status=403)})
    poster_cache.run(session=first)
    second = Session({})
    stats = poster_cache.run(session=second)
    assert second.calls == [] and stats['cached'] == 1 and stats['skipped'] == 1


def test_non_images_are_rejected_and_old_files_are_removed(isolated):
    add_event('a', ['https://img.test/page'])
    stats = poster_cache.run(session=Session({'https://img.test/page': Response(body=b'<html>', kind='text/html')}))
    assert stats['failed'] == 1
    reviewed = 'b' * 64 + '.webp'
    (isolated / 'static/posters' / reviewed).write_bytes(b'RIFF')
    (isolated / 'static/posters/manifest.json').write_text(json.dumps({'https://reviewed.test/p': reviewed}))
    stale = 'c' * 64 + '.webp'
    (isolated / 'static/posters' / stale).write_bytes(b'RIFF')
    stats = poster_cache.run(session=Session({}))
    assert stats['removed'] == 1
    assert (isolated / 'static/posters' / reviewed).exists() and not (isolated / 'static/posters' / stale).exists()


def test_events_that_ended_long_ago_are_ignored(isolated):
    add_event('old', ['https://img.test/old.png'], days=-60)
    session = Session({})
    assert poster_cache.run(session=session)['events'] == 0 and session.calls == []


def test_icons_are_never_downloaded_again_and_old_records_migrate(isolated):
    add_event('a', ['https://img.test/thin.png', 'https://img.test/old-icon.png'])
    (isolated / 'data').mkdir(exist_ok=True)
    (isolated / 'data/poster-cache.json').write_text(json.dumps(
        {'failures': {'https://img.test/old-icon.png': {'n': 1, 'next': 0, 'why': 'too small'}}}))
    first = Session({'https://img.test/thin.png': Response(body=picture((1200, 60)))})
    stats = poster_cache.run(session=first)
    assert stats['icons'] == 1 and stats['failed'] == 0
    assert [url for url, _ in first.calls] == ['https://img.test/thin.png']   # the migrated icon is not fetched
    state = json.loads((isolated / 'data/poster-cache.json').read_text())
    assert set(state['icons']) == {'https://img.test/thin.png', 'https://img.test/old-icon.png'} and state['failures'] == {}
    second = Session({})
    poster_cache.run(session=second)
    assert second.calls == []
