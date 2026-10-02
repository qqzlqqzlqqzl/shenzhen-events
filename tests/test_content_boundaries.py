"""Offline content/URL boundaries, including malformed historical records."""
import json
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup
from icalendar import Calendar
from radar import api, core
from radar.calendar import make_calendar
from radar.collectors import jsonld

PORTS = [('', True), (':0', True), (':1', True), (':443', True),
         (':65535', True), (':65536', False), (':99999', False),
         (':bad', False), (':-1', False), (':1.5', False)]
PLAIN = ['C++ <vector> 与 Rust Vec<T> 实践', '学习 <b> 标签的文本表示',
         '比较 a < b & c > d', 'literal &#60; & "quoted"',
         '<p>没有格式声明，保留原文</p>']


def event(url='https://events.example.test/a?literal=%26&keep=1', **updates):
    return dict(title='内容 <b data-fixture="yes">原文</b>', url=url,
                start_at='2026-10-05T10:00:00+08:00',
                end_at='2026-10-05T12:00:00+08:00', summary=PLAIN[0],
                cost_text='25元', organizer='原文 <em>机构</em>', **updates)


def collect(description):
    raw={'@type': 'Event', 'name': '代码课程', 'description': description,
         'url': 'https://events.example.test/a', 'startDate': '2026-10-05'}
    soup=BeautifulSoup('<script type="application/ld+json">'+json.dumps(raw).replace('<','\\u003c')+'</script>', 'html.parser')
    return jsonld(soup, raw['url'])[0]


@pytest.mark.parametrize('description', PLAIN)
def test_unlabelled_jsonld_description_remains_literal(description):
    parsed=collect(description)
    assert parsed['summary']==description
    assert core.normalize_event(parsed)['summary']==description


@pytest.mark.parametrize('markup,want', [
    ('<p>欢迎 <strong>创客</strong> &amp; 开发者</p><p>体验 <code>&lt;vector&gt;</code></p>',
     '欢迎 创客 & 开发者 体验 <vector>'),
    ('<ul><li>机器人</li><li>Rust &amp; C++</li></ul>', '机器人 Rust & C++'),
    ('<p>正常 <script>synthetic</script><style>.synthetic{}</style>内容</p>', '正常 内容'),
])
def test_declared_html_has_readable_text_and_encoded_code(markup, want):
    assert collect({'@type':'TextObject','encodingFormat':'text/html; charset=utf-8','text':markup})['summary']==want


def test_explicit_plain_text_does_not_guess_html():
    assert collect({'@type':'TextObject','encodingFormat':'text/plain','text':'学习 <b> 标签'})['summary']=='学习 <b> 标签'
    assert collect({'@type':'TextObject','text':'Vec<T>'})['summary']=='Vec<T>'


@pytest.mark.parametrize('port,valid', PORTS)
def test_port_validation_at_normalization_and_ics(port, valid):
    url='https://events.example.test'+port+'/a?keep=1'
    assert bool(core.canon_url(url))==valid
    normalized=core.normalize_event(event(url))
    assert (normalized is not None)==valid
    # A historical row bypasses new ingestion validation; keep its dates/text.
    legacy={**event(url),'id':'same-id','last_seen':'2026-10-02T20:00:00+08:00',
            'sources':[{'name':'来源 <strong>原文</strong>','url':url}]}
    result=Calendar.from_ical(make_calendar([legacy])).walk('VEVENT')
    assert len(result)==1
    row=result[0]
    assert ('URL' in row)==valid
    if valid:assert str(row['URL'])==url
    assert str(row['UID'])=='same-id@shenzhen-events'
    assert row['DTSTART'].dt.isoformat()=='2026-10-05T10:00:00+08:00'
    assert legacy['summary'] in str(row['DESCRIPTION'])
    assert legacy['sources'][0]['name']+': '+url in str(row['DESCRIPTION'])


@pytest.mark.parametrize('url', ['javascript:harmless','data:text/plain,harmless',
    'ftp://events.example.test/a','https://user:pass@events.example.test/a'])
def test_existing_protocol_and_credentials_rejections_remain(url):
    assert core.canon_url(url)=='' and core.normalize_event(event(url)) is None


def test_rejected_new_ports_write_no_events_or_raw_items(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    (tmp_path/'sources.json').write_text('[]')
    core.init()
    for url in ['https://events.example.test:bad/a','https://events.example.test:99999/a']:
        core.ingest({'id':'synthetic','name':'Synthetic','kind':'jsonld'}, event(url))
    with core.db() as c:
        for table in ['events','raw_items','event_sources','preferences']:
            assert c.execute('SELECT count(*) FROM '+table).fetchone()[0]==0


def test_literal_api_and_export_roundtrip_preserves_attribution_and_escaping():
    normalized=core.normalize_event({**event(),'summary':PLAIN[0]+'\r\nX-FIXTURE:second'})
    normalized.update(id='stable-id',last_seen='2026-10-02T20:00:00+08:00',
                      sources=[{'name':'来源 <strong>原文</strong>', 'url':normalized['url']}])
    with patch.object(api,'require',lambda _:{}), patch.object(api,'events',lambda **_: [normalized]):
        wire=json.loads(json.dumps(api.event_detail('stable-id', None)))
        assert wire==normalized
        items=Calendar.from_ical(api.one_event('stable-id',None).body).walk('VEVENT')
    assert len(items)==1 and 'X-FIXTURE' not in items[0]
    assert normalized['summary'] in str(items[0]['DESCRIPTION'])
    assert normalized['organizer']==wire['organizer']
    assert normalized['sources'][0]['name'] in str(items[0]['DESCRIPTION'])
