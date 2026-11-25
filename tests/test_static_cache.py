import hashlib
import json
import re

import pytest
from fastapi.testclient import TestClient

from radar import api, core


@pytest.fixture()
def client(tmp_path, monkeypatch):
    static = tmp_path / 'static'
    (static / 'posters').mkdir(parents=True)
    (static / 'app.js').write_text('console.log(1)')
    (static / 'index.html').write_text(
        '<script defer src="/events/static/app.js?v=old"></script>'
        '<meta name="radar-calendar-script" content="/events/static/missing.js?v=old">')
    (static / 'posters' / ('a' * 64 + '.webp')).write_bytes(b'RIFF')
    (tmp_path / 'sources.json').write_text(json.dumps([]))
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(api, 'ROOT', tmp_path)
    api._ASSET_VERSIONS.clear()
    # The static mount is bound at import time; serve this test's directory instead.
    mount = next(r for r in api.app.routes if getattr(r, 'path', '') == '/events/static')
    monkeypatch.setattr(mount.app, 'directory', static)
    monkeypatch.setattr(mount.app, 'all_directories', [static])
    api.initialize_settings()
    core.init()
    return TestClient(api.app)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def test_index_pins_each_asset_to_its_content(client):
    res = client.get('/events/')
    assert res.status_code == 200 and res.headers['cache-control'] == 'private, no-store'
    assert f'/events/static/app.js?v={digest("console.log(1)")}' in res.text
    # A reference to a missing file is left untouched rather than invented.
    assert '/events/static/missing.js?v=old' in res.text


def test_versioned_assets_are_immutable_and_others_revalidate(client):
    pinned = re.search(r'/events/static/app\.js\?v=\w+', client.get('/events/').text).group(0)
    assert client.get(pinned).headers['cache-control'] == 'public, max-age=31536000, immutable'
    assert client.get('/events/static/app.js?v=stale').headers['cache-control'] == 'no-cache'
    assert client.get('/events/static/app.js').headers['cache-control'] == 'no-cache'
    poster = client.get('/events/static/posters/' + 'a' * 64 + '.webp')
    assert poster.headers['cache-control'] == 'public, max-age=31536000, immutable'


def test_api_and_missing_files_stay_uncached(client):
    assert client.get('/events/api/health').headers['cache-control'] == 'private, no-store'
    assert client.get('/events/static/nope.js?v=x').headers['cache-control'] == 'private, no-store'
