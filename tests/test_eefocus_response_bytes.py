"""Independent exact-response-byte contract probes; synthetic transport only."""
import hashlib
import json

import pytest

from radar import collectors, core, coverage, eefocus as ee, safety
from test_eefocus import DESIGN, isolated, load


@pytest.mark.parametrize('encoding', ['utf-8', 'gb18030'])
def test_capture_digest_and_blob_cover_original_response_entity_bytes(monkeypatch, encoding):
    html = load('fixtures/safety-cancelled-list.html')
    raw = html.encode(encoding)
    if encoding == 'utf-8':
        # A non-UTF8 byte in an irrelevant comment must still remain in the
        # immutable response record; the original contract promises exact bytes.
        raw += b'<!-- original byte: \xff -->'

    class Response:
        status_code = 200
        headers = {'Content-Type': 'text/html; charset=' + encoding}

        def iter_content(self, size):
            yield raw

        def raise_for_status(self):
            pass

        def close(self):
            pass

    Response.encoding = encoding

    class Session:
        def get(self, url, **kwargs):
            assert url == ee.LIST_URL
            assert kwargs['stream'] and kwargs['allow_redirects'] is False
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(collectors.requests, 'Session', Session)
    monkeypatch.setattr(collectors.socket, 'getaddrinfo', lambda *args, **kwargs: [(2, 1, 6, '', ('8.8.8.8', 443))])
    coverage.collect_report({**DESIGN['source'], 'detail_budget': 0})
    with core.db() as connection:
        captured = dict(connection.execute('SELECT sc.*, sb.body, sb.original_bytes FROM safety_capture_runs sc JOIN safety_evidence_blobs sb ON sb.digest = sc.response_digest').fetchone())
        assert captured['capture_state'] == 'safety_finalized'
        assert connection.execute('SELECT COUNT(*) FROM safety_observations').fetchone()[0] == 1
    assert bytes(captured['body']) == raw, {
        'encoding': encoding,
        'response_sha256': hashlib.sha256(raw).hexdigest(),
        'recorded_sha256': captured['response_digest'],
        'response_bytes': len(raw),
        'recorded_original_bytes': captured['original_bytes'],
    }
    assert captured['response_digest'] == hashlib.sha256(raw).hexdigest()
    assert captured['original_bytes'] == len(raw)
    metadata = json.loads(captured['provenance'])['response_entity']
    assert metadata == {'version': 1, 'encoding': encoding, 'errors': 'replace'}
    receipt = safety.replay_capture(captured['capture_id'])
    assert receipt == json.loads(captured['receipt'])
    with core.db() as connection:
        assert bytes(connection.execute('SELECT body FROM safety_evidence_blobs WHERE digest=?', (captured['response_digest'],)).fetchone()[0]) == raw
        assert connection.execute('SELECT COUNT(*) FROM safety_observations').fetchone()[0] == 1


def test_unfinalized_non_utf8_capture_replays_original_bytes(monkeypatch):
    raw = load('fixtures/safety-cancelled-list.html').encode('gb18030')
    capture = safety.claim(safety.begin_capture(DESIGN['source']))
    captured = safety.retain(capture, collectors.ResponseText(raw, 'gb18030'), ee.LIST_URL,
                             [{'url': ee.LIST_URL, 'status': 200, 'location': ''}])
    # Resume solely from durable state, without fetching or using the text object.
    result = safety.replay_capture(captured.id)
    assert result['observations_new'] == 1
    with core.db() as connection:
        run = dict(connection.execute('SELECT * FROM safety_capture_runs').fetchone())
        assert run['capture_state'] == 'safety_finalized'
        assert run['response_digest'] == hashlib.sha256(raw).hexdigest()


def test_legacy_utf8_capture_remains_unchanged_and_replayable(monkeypatch):
    html = load('fixtures/safety-cancelled-list.html')
    capture = safety.claim(safety.begin_capture(DESIGN['source']))
    captured = safety.retain(capture, html, ee.LIST_URL,
                             [{'url': ee.LIST_URL, 'status': 200, 'location': ''}])
    assert safety.replay_capture(captured.id)['observations_new'] == 1
    with core.db() as connection:
        run = dict(connection.execute('SELECT * FROM safety_capture_runs').fetchone())
        assert run['response_digest'] == hashlib.sha256(html.encode()).hexdigest()
        assert 'response_entity' not in json.loads(run['provenance'])


def test_mismatched_decoded_capture_keeps_acquisition_fenced(monkeypatch):
    html = collectors.ResponseText(load('fixtures/safety-cancelled-list.html').encode(), 'utf-8')
    html.response_bytes += b'changed'
    capture = safety.claim(safety.begin_capture(DESIGN['source']))
    with pytest.raises(safety.Integrity):
        safety.retain(capture, html, ee.LIST_URL, [{'url': ee.LIST_URL, 'status': 200}])
    with core.db() as connection:
        assert connection.execute('SELECT capture_state FROM safety_capture_runs').fetchone()[0] == 'acquiring'
        assert connection.execute('SELECT COUNT(*) FROM safety_capacity').fetchone()[0] == 1
        assert connection.execute('SELECT COUNT(*) FROM safety_evidence_blobs').fetchone()[0] == 0
