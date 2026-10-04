"""Static artifact checks only. No application imports, fetching, or adapter tests."""
import json
import hashlib
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class MainCards(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.count = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set(a.get('class', '').split())
        if 'section-special-item' in classes:
            if len(self.stack) >= 2 and 'section-list-item-ul' in self.stack[-1][1] and 'special-list' in self.stack[-2][1]:
                self.count += 1
        if tag not in {'meta', 'link', 'br', 'hr', 'img', 'input'}:
            self.stack.append((tag, classes))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def check_types(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if k in {'start_at', 'end_at'}:
                assert v is None or isinstance(v, str), (k, v)
                if v is not None:
                    dt = datetime.fromisoformat(v)
                    assert dt.tzinfo is not None and v.endswith('+08:00'), v
            if k in {'all_day', 'truncated', 'complete_scope', 'time_conflict'}:
                assert isinstance(v, bool), (k, v)
            if k == 'source_total':
                assert v is None, 'This design never establishes a source total'
            if k in {'source_event_id', 'review_notes', 'date_evidence', 'source_status'}:
                assert isinstance(v, str), (k, v)
            if k == 'attendance':
                assert v in {'offline', 'online', 'hybrid', 'unknown'}, v
            if k in {'pages_visited', 'visible', 'extracted', 'unique', 'admitted', 'duplicates',
                     'parser_unaccounted', 'requests_attempted', 'detail_attempted',
                     'detail_resolved', 'detail_failed', 'detail_deferred', 'detail_cached'}:
                assert type(v) is int and v >= 0, (k, v)
            check_types(v)
    elif isinstance(value, list):
        for x in value:
            check_types(x)


def main():
    manifest = json.loads((ROOT / 'cases.json').read_text())
    cases = manifest['cases']
    assert len(cases) == manifest['case_count'] == 64
    assert len({c['id'] for c in cases}) == len(cases)
    json_count = 0
    for path in ROOT.rglob('*.json'):
        if path.name == 'validation.json':
            continue
        check_types(json.loads(path.read_text()))
        json_count += 1
    def check_references(value):
        if isinstance(value, dict):
            for v in value.values():
                check_references(v)
        elif isinstance(value, list):
            for v in value:
                check_references(v)
        elif isinstance(value, str) and value.startswith(('fixtures/', 'expected/')):
            assert (ROOT / value).is_file(), value
    check_references(manifest)
    expected = {}
    for c in cases:
        expected[c['id']] = json.loads((ROOT / c['expected']).read_text())
        for k, v in c['inputs'].items():
            if isinstance(v, str) and v.startswith('fixtures/'):
                assert (ROOT / v).is_file(), (c['id'], k, v)
    parser = MainCards()
    parser.feed((ROOT / 'fixtures/inventory-20-main-cards.html').read_text())
    assert parser.count == 20
    p = expected['01-main-inventory']['parse']
    assert p['visible'] == p['extracted'] + sum(p['excluded'].values()) == 20
    assert len(p['extracted_post_ids']) == p['extracted'] == 12
    e = expected['03-explicit-meeting-time']['item_subset']
    assert (datetime.fromisoformat(e['end_at']) - datetime.fromisoformat(e['start_at'])).total_seconds() == 510 * 60
    cache = json.loads((ROOT / 'fixtures/cache-cancelled.json').read_text())
    assert isinstance(cache['payload'], str)
    assert isinstance(json.loads(cache['payload'])['patch'], dict)
    d = expected['24-detail-timeout-in-flight']['report']['coverage_subset']
    assert d['detail_attempted'] + d['detail_deferred'] == 3
    assert d['requests_attempted'] == 1 + d['detail_attempted'] == 2
    runs = expected['28-repeat-ingest-alias']['counts_after_each_run']
    assert [x['raw_items'] for x in runs] == [0, 1, 1, 1]
    assert all(x['raw_items'] == x['events'] == x['event_sources'] for x in runs)
    assert [x['admitted'] for x in runs] == [0, 1, 1, 1]
    assert [x['changed'] for x in runs] == [0, 1, 0, 0]
    transcript = json.loads((ROOT / 'fixtures/repeat-ingest-transcript.json').read_text())
    seed = transcript['steps'][2]
    assert seed['preferences']['favorite'] == 1
    assert seed['event_patch']['status'] == 'needs_review'
    assert seed['event_patch']['details']['review_hold'] is True
    assert expected['28-repeat-ingest-alias']['expected_event_after_runs_3_and_4']['details']['review_notes'] == seed['event_patch']['details']['review_notes']
    assert expected['01-main-inventory']['report']['coverage_subset']['admitted'] == 0
    for case_id, count in [('24-detail-timeout-in-flight', 0), ('25-detail-budget-expired-before-request', 0), ('26-detail-http-failure', 1), ('27-detail-challenge-stop', 0)]:
        assert expected[case_id]['report']['coverage_subset']['admitted'] == count
    for name, n in [('all-excluded-inventory.html', 5), ('both-aliases-one-inventory.html', 2)]:
        h = MainCards()
        h.feed((ROOT / ('fixtures/' + name)).read_text())
        assert h.count == n
    excluded = expected['36-nonempty-all-excluded']['parse']
    assert excluded['visible'] == excluded['extracted'] + sum(excluded['excluded'].values()) == 5
    assert expected['36-nonempty-all-excluded']['report']['coverage_subset']['recognized_empty'] is False
    both = expected['32-both-aliases-one-inventory']['report']['coverage_subset']
    assert both['visible'] == both['extracted'] == 2
    assert both['unique'] == both['admitted'] == both['duplicates'] == 1
    cache_state = json.loads((ROOT / 'fixtures/cache-timestamp-concrete.json').read_text())
    def fingerprint(e):
        stable = {k: v for k, v in e.items() if k not in ('details', 'published_at')}
        stable['details'] = {k: v for k, v in e['details'].items() if k != 'checked_at'}
        return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    assert fingerprint(cache_state['old_listing_item']) == fingerprint(cache_state['new_listing_item']) == cache_state['cache_row']['fingerprint']
    assert expected['30-cache-timestamp-only-repeat']['fingerprint'] == cache_state['cache_row']['fingerprint']
    assert len(next(c for c in cases if c['id'] == '37-short-summary-undated-lead')['inputs']['summary']) < 40
    assert e['details']['date_evidence'].startswith('活动时间：2026年10月22日')
    assert '等待' not in e['details']['review_notes']
    assert any(t['field'] == 'list_promotion_window' for t in e['details']['time_evidence'])
    assert expected['04-same-origin-event-to-live']['item_subset']['city'] == '线上'
    assert expected['04-same-origin-event-to-live']['item_subset']['details']['attendance'] == 'online'
    # V3: structural checks and evidence/oracle consistency, never adapter execution.
    def read_json(rel):
        return json.loads((ROOT / rel).read_text())
    def canonical_digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                        separators=(',', ':')).encode()).hexdigest()
    by_number = {int(c['id'][:2]): c for c in cases}
    def oracle(n):
        return expected[by_number[n]['id']]
    def inp(n):
        return by_number[n]['inputs']
    baseline = read_json('baseline-v2.json')
    assert baseline['file_count'] == len(baseline['files_sha256']) == 83
    original = ROOT.with_name('eefocus-fixtures-20261002-v2')
    if original.exists():
        actual_paths = {str(p.relative_to(original)) for p in original.rglob('*') if p.is_file()}
        assert actual_paths == set(baseline['files_sha256'])
        for rel, digest in baseline['files_sha256'].items():
            assert hashlib.sha256((original / rel).read_bytes()).hexdigest() == digest, rel
        baseline_cases = json.loads((original / 'cases.json').read_text())['cases']
        for c in baseline_cases:
            if c['id'].startswith('37-'):
                continue
            assert c == next(x for x in cases if x['id'] == c['id']), c['id']
            assert (ROOT / c['expected']).read_bytes() == (original / c['expected']).read_bytes()
    # Validate every local input/expected reference, not just cases.json.
    for path in ROOT.rglob('*.json'):
        if path.name != 'validation.json':
            check_references(json.loads(path.read_text()))
    assert 'detail_response' not in inp(37)
    assert 'identity_verified' not in inp(37)
    detail37 = (ROOT / inp(37)['detail_transport']['responses'][-1]['body_file']).read_text()
    assert '<h1>合成年份待定线上讨论</h1>' in detail37
    assert '举办时间：10月28日，年份待确认' in detail37
    assert oracle(37)['admitted'] == 1 and not oracle(37)['upcoming_included']
    for n in range(41, 47):
        entry = inp(n)
        h = MainCards(); h.feed((ROOT / entry['list_html']).read_text())
        assert h.count == 1
        tr = entry['detail_transport']; res = tr['responses']
        assert res[-1]['status'] == 200 and res[-1]['url'] == tr['final_url']
        assert all(r['url'].startswith('https://www.eefocus.com/') for r in res)
        assert str(980000 + n) in tr['requested_url']
        ok = n == 46
        e = oracle(n); cov = e['report']['coverage_subset']
        assert e['admitted'] == cov['admitted'] == int(ok)
        assert e['identity_verdict'] == ('verified' if ok else 'unverified')
        assert cov['detail_attempted'] == cov['detail_resolved'] + cov['detail_failed'] == 1
        assert cov['requests_attempted'] == 2
        assert cov['detail_resolved'] == int(ok)
        assert set(e['database_counts'].values()) == {int(ok)}
        assert e['identity_success_cache_written'] is ok
        assert e['detail_success_patch_cached'] is ok
    assert '合成汽车营销论坛' in (ROOT / inp(41)['detail_transport']['responses'][-1]['body_file']).read_text()
    assert '<aside>' in (ROOT / inp(42)['detail_transport']['responses'][-1]['body_file']).read_text()
    assert '<aside>' in (ROOT / inp(46)['detail_transport']['responses'][-1]['body_file']).read_text()
    assert oracle(59)['admitted'] == 0 and not oracle(59)['positive_cache_reuse_allowed']
    assert inp(59)['identity_cache']['expires_at'] > manifest['fixed_now']
    for n in list(range(47, 59)) + [60, 61, 62, 63, 64]:
        e = oracle(n); state = read_json(inp(n)['stored_state'])
        assert canonical_digest(state) == e['immutable_stored_state_sha256'], n
        assert e['expected_stored_event'] == state['event'], n
        assert e['expected_preference'] == state['preference'], n
        assert e['expected_alias_history'] == state['alias_history'], n
        assert e['database_counts'] == state['row_counts'], n
        assert e['admitted'] == e['changed'] == 0 and e['items'] == [], n
        assert e['fixture_only_safety_counters']['event_content_updates'] == 0
        assert e['fixture_only_safety_counters']['alias_success_writes'] == 0
        assert e['authoritative_cancelled_status_written'] is False
        if 'query_expectations' in e:
            assert e['query_expectations']['saved_record_included'] is True
            assert e['query_expectations']['point_record_included'] is True
            q = e['query_expectations']
            for key in ['upcoming_api_included', 'planning_feed_included', 'calendar_export_included', 'pending_notification_dispatch_allowed']:
                assert q[key] is q['upcoming_included'], (n, key)
            assert q['eligible_counts_facets_use_safety_state'] is True
            assert q['cached_scheduled_result_may_bypass_guard'] is False
    for n in [47, 48, 50, 51, 52, 53, 55, 62, 64]:
        q = oracle(n)['query_expectations']
        assert q['upcoming_included'] is q['calendar_included'] is q['range_included'] is False, n
    for n in [49, 54, 56, 57, 58, 60, 61]:
        assert oracle(n)['query_expectations']['upcoming_included'] is True, n
    assert read_json(inp(47)['stored_state'])['event']['status'] == 'scheduled'
    assert oracle(47)['expected_stored_event']['status'] == 'scheduled'
    assert oracle(47)['query_expectations']['effective_status'] == 'needs_review'
    assert oracle(47)['fixture_only_safety_counters']['guard_writes'] == 1
    assert oracle(48)['fixture_only_safety_counters']['guard_writes'] == 0
    assert oracle(53)['expected_stored_event']['details']['review_hold'] is True
    assert oracle(53)['fixture_only_safety_counters']['active_guards'] == 0
    assert oracle(54)['fixture_only_safety_counters']['active_guards'] == 0
    assert oracle(55)['expected_guard']['state'] == 'active'
    assert oracle(60)['fixture_only_safety_counters']['active_guards'] == 0
    assert oracle(61)['guard_reopened'] is False
    assert oracle(62)['active_guard_ids'] == ['guard-cancel-002']
    assert oracle(62)['resolved_guard_ids'] == ['guard-cancel-001']
    assert not oracle(62)['unseen_guard_cleared']
    for n in [53, 54]:
        assert 'report' not in oracle(n)
        assert oracle(n)['operation_metrics']['inventory_requests'] == 0
        assert oracle(n)['operation_metrics']['requests_attempted'] == 1
    assert oracle(62)['fixture_only_safety_counters']['guard_writes'] == 2
    assert sum(oracle(62)['fixture_only_safety_counters']['by_actor'].values()) == 2
    assert inp(56)['adjudication']['expected_guard_revision'] == 1
    assert oracle(56)['resolved_guard_revision'] == 2
    assert oracle(63)['cancellation_guard_creations_per_variant'] == [0, 0, 0, 0]
    obs = read_json('fixtures/safety-cancellation-observation.json')
    assert hashlib.sha256((ROOT / obs['body_file']).read_bytes()).hexdigest() == obs['content_digest']
    assert '<span class="event-status">已取消</span>' in (ROOT / obs['body_file']).read_text()
    assert inp(61)['new_network_observation'] is False
    assert inp(64)['publisher_generation_proven_same'] is False
    assert oracle(64)['expected_guard']['state'] == 'active'
    for name in ['fixtures/safety-historical-verification.json', 'fixtures/safety-historical-second-verification.json']:
        proof = read_json(name)
        for file, digest in proof['body_sha256'].items():
            assert hashlib.sha256((ROOT / file).read_bytes()).hexdigest() == digest
        for file in [proof['list_body_file'], proof['responses'][-1]['body_file']]:
            body = (ROOT / file).read_text()
            assert proof['shared_main_heading'] in body
            assert proof['shared_meeting_date'] in body
            assert proof['shared_meeting_clock'] in body
    for state_file in ['fixtures/safety-stored-scheduled.json', 'fixtures/safety-stored-manual-hold.json', 'fixtures/safety-ambiguous-history.json']:
        for binding in read_json(state_file)['alias_history']:
            assert hashlib.sha256((ROOT / binding['evidence_file']).read_bytes()).hexdigest() == binding['evidence_sha256']
            proof = read_json(binding['evidence_file'])
            assert proof['event_id'] == binding['event_id']
            assert proof['requested_url'] == binding['alias_url']
            assert proof['responses'][-1]['url'] == binding['canonical_url']
    provenance = read_json('provenance.json')
    local_source = ROOT.parent / 'events-favorite-independent-review/source'
    if local_source.exists():
        for f in provenance['files']:
            data = (local_source / f['path']).read_bytes()
            blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            assert blob == f['git_blob'], f['path']
    report = {
        'static_artifact_validation': 'passed',
        'revision': 'v3', 'cases': len(cases), 'json_files_checked': json_count,
        'main_list_cards': parser.count,
        'application_code_imported': False,
        'adapter_tests_run': False, 'network_requests_to_publisher': 0,
        'repository_edits': False,
        'scope': 'JSON/types/references/evidence text/fixture arithmetic/immutable-state oracles only; no adapter or integration pass claimed',
        'inherited_cases_unchanged': 39, 'strengthened_cases': 1, 'added_cases': 24,
        'v2_preservation_file_count': 83,
        'production_database_mutations': False, 'query_restart_concurrency_tests_run': False
    }
    (ROOT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
