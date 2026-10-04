"""Synthetic source evidence; no production access or identity migration."""
import json
import subprocess
from pathlib import Path
from datetime import date,datetime,timedelta
import pytest
from bs4 import BeautifulSoup
from icalendar import Calendar
from fastapi.testclient import TestClient
from radar import core, collectors, coverage, details,api

URL='https://example.com/event'
def soup(html):return BeautifulSoup(html,'html.parser')
def ld(**fields):
    value={'@type':'Event','name':'社区活动','url':URL,**fields}
    return collectors.jsonld(soup('<script type="application/ld+json">'+json.dumps(value)+'</script>'),URL)[0]

@pytest.mark.parametrize('title',['免费礼品工作坊','￥0礼品，门票需购买'])
def test_lianpu_admission_comes_from_badge(title):
    html=f'<article><h3><a href="/event">{title}</a></h3><p>免费咖啡</p><time datetime="2026-10-03"></time><span class="rounded-full">￥199</span><p>深圳</p></article>'
    e=collectors.lianpu(soup(html),'https://lianpu.com/city/shenzhen')[0]
    assert e['cost_text']=='￥199' and not core.normalize_event(e)['cost_free']
    e=collectors.lianpu(soup(html.replace('<span class="rounded-full">￥199</span>','')),'https://lianpu.com/city/shenzhen')[0]
    assert e['cost_text']=='费用未注明'

@pytest.mark.parametrize('label',['费用','活动费用','门票价格'])
@pytest.mark.parametrize('markup',['<p><strong>{label}：</strong><span>{value}</span></p>', '<p><strong>{label}</strong>：<span>{value}</span></p>', '<p>{label}：{value}</p>'])
def test_nested_explicit_labels(label,markup):
    html='<main>'+markup.format(label=label,value='199元')+markup.format(label='主办方',value='实际主办')+'</main>'
    e=details.extract(soup(html),URL)
    assert e['cost_text']=='199元' and e['organizer']=='实际主办'

def test_fragmented_value_and_empty_label_do_not_consume_next_field():
    e=details.extract(soup('<main><p><strong>费用：</strong><span>199</span>元</p><p><strong>主办方：</strong><span>实际</span>主办</p></main>'),URL)
    assert e['cost_text']=='199元' and e['organizer']=='实际主办'
    e=details.extract(soup('<main><p>费用：</p><p>主办方：实际主办</p></main>'),URL)
    assert 'cost_text' not in e and e['organizer']=='实际主办'

def test_explicit_organizer_replaces_publisher_with_attribution():
    base={'organizer':'发布账号','details':{'publisher':'发布账号','organizer_role':'publisher','attendance':'hybrid','review_notes':'保留'}}
    e=details.merge(base,{}, {'organizer':'实际主办','evidence_url':URL})
    assert e['organizer']=='实际主办' and e['details']['organizer_role']=='organizer'
    assert e['details']['publisher']=='发布账号' and e['details']['review_notes']=='保留'
    assert e['details']['field_provenance']['organizer']=={'kind':'label','evidence_url':URL}
    assert base['organizer']=='发布账号'

@pytest.mark.parametrize('mode,expected',[('Online','online'),('Mixed','hybrid'),('Offline','offline')])
def test_jsonld_attendance_and_organizer_arrays(mode,expected):
    e=ld(eventAttendanceMode='https://schema.org/'+mode+'EventAttendanceMode',organizer=[{'@type':'Organization','name':'甲'},'乙',{'name':'甲'}])
    assert e['organizer']=='甲 / 乙' and e['details']['organizer_role']=='organizer'
    assert e['details']['attendance']==expected

@pytest.mark.parametrize('reverse',[False,True])
def test_multiple_offers_keep_paid_option_order_independently(reverse):
    offers=[{'price':'0'},{'price':'199','priceCurrency':'CNY'}]
    if reverse:offers.reverse()
    e=ld(offers=offers,isAccessibleForFree=True)
    assert e['cost_text']=='免费 / CNY 199'
    assert not core.normalize_event(e)['cost_free']

def test_aggregate_offer_and_accessibility():
    e=ld(offers={'@type':'AggregateOffer','lowPrice':0,'highPrice':199})
    assert e['cost_text']=='免费 / CNY 199' and not core.normalize_event(e)['cost_free']
    assert ld(isAccessibleForFree=True)['cost_text']=='免费'
    assert not core.normalize_event(ld(isAccessibleForFree=False))['cost_free']
    assert not core.normalize_event(ld(isAccessibleForFree=False,offers={'price':0}))['cost_free']
    e=ld(offers={'@type':'AggregateOffer','offers':[{'price':199},{'price':0}]})
    assert e['cost_text']=='免费 / CNY 199'

@pytest.mark.parametrize('structured,label',[('免费','199元'),('199元','免费')])
def test_conflicting_detail_prices_preserve_paid_evidence(structured,label):
    e=details.merge({'title':'活动','url':URL},{'cost_text':structured},{'cost_text':label})
    assert '199元' in e['cost_text'] and not core.normalize_event(e)['cost_free']

@pytest.mark.parametrize('unknown',[None,'','费用未注明'])
def test_label_fills_unknown_fee_and_preserves_sibling_provenance(unknown):
    e=details.merge({'cost_text':unknown},{'details':{'field_provenance':{'attendance':{'kind':'source'}}}},{'cost_text':'199元'})
    assert e['cost_text']=='199元' and not e['cost_free']
    assert e['details']['field_provenance']['attendance']=={'kind':'source'}

def test_merge_preserves_current_fields_holds_and_structured_siblings():
    base={'title':'当前标题','url':URL,'location':'深圳新场馆','cost_text':'199元','start_at':'2026-10-04','end_at':'2026-10-05','all_day':True,'status':'cancelled','details':{'attendance':'hybrid','review_hold':'date_conflict','publisher':'发布者'}}
    stale={'title':'旧标题','location':'旧场馆','cost_text':'免费','start_at':'2026-10-01','end_at':'2026-10-02','all_day':False,'status':'scheduled','details':{'attendance':'online','schedule_evidence':'JSON-LD','other':'保留'}}
    e=details.merge(base,stale,{'images':['https://example.com/poster.png']})
    assert all(e[k]==v for k,v in base.items() if k!='details')
    assert not e['cost_free'] and e['details']['attendance']=='hybrid'
    assert e['details']['review_hold']=='date_conflict' and e['details']['schedule_evidence']=='JSON-LD' and e['details']['other']=='保留'
    assert e['details']['images']==['https://example.com/poster.png']
    held=details.merge({'url':URL,'details':{'review_hold':'date_conflict'}},stale,{})
    assert not held.get('start_at') and not held.get('end_at')

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(core,'ROOT',tmp_path);(tmp_path/'static').mkdir();(tmp_path/'sources.json').write_text('[]');core.init()
    monkeypatch.setattr(coverage.time,'sleep',lambda _:None)

def metrics():return dict.fromkeys(['detail_cached','detail_deferred','detail_attempted','detail_resolved','detail_failed'],0)

@pytest.mark.parametrize('start,end,all_day',[
    ('2026-10-10T14:00:00+08:00','2026-10-10T16:00:00+08:00',False),
    ('2026-10-10','2026-10-11',True),
])
def test_undated_hdx_accepts_detail_date_precision_on_fetch_and_cache(isolated,monkeypatch,start,end,all_day):
    listing='<div class="search-tab-content-item"><a class="item-title" href="'+URL+'">社区活动</a><p class="item-data">日期待确认</p><p class="item-dress">深圳测试场馆</p></div>'
    base=coverage.hdx(soup(listing),URL)[0]
    assert base['start_at'] is None and base['all_day'] is True
    html='<script type="application/ld+json">'+json.dumps({'@type':'Event','name':'社区活动','url':URL,'startDate':start,'endDate':end})+'</script>'
    calls=[];monkeypatch.setattr(collectors,'fetch',lambda url,**kw:(calls.append(url) or html,soup(html),url))
    source={'id':'hdx-fixture','kind':'hdx','enrich_dated':True,'request_delay':0}
    fresh=coverage.enrich_details(source,[dict(base)],metrics())[0]
    assert fresh['all_day'] is all_day
    m=metrics();cached=coverage.enrich_details(source,[dict(base)],m)[0]
    assert m['detail_cached']==1 and len(calls)==1 and cached['all_day'] is all_day
    assert cached['start_at']==core.iso(start) and cached['end_at']==core.iso(end)
    core.ingest(source,cached)
    with core.db() as db:event_id=db.execute('SELECT id FROM events WHERE url=?',(URL,)).fetchone()[0]
    monkeypatch.setattr(api,'ROOT',core.ROOT);api.initialize_settings()
    with TestClient(api.app) as client:
        client.cookies.set(api.COOKIE,api.sign_session({'id':1,'username':'precision-fixture'}))
        response=client.get('/events/api/event/'+event_id+'.ics');assert response.status_code==200
        public=client.get('/events/api/event/'+event_id).json()
    event=Calendar.from_ical(response.content).walk('VEVENT')[0]
    assert str(event['uid'])==event_id+'@shenzhen-events'
    if all_day:
        assert type(event.decoded('dtstart')) is date and event.decoded('dtstart')==date(2026,10,10)
        assert event.decoded('dtend')==date(2026,10,11)
    else:
        assert isinstance(event.decoded('dtstart'),datetime) and event.decoded('dtstart').hour==14
        assert event.decoded('dtend').hour==16 and event.decoded('dtend')-event.decoded('dtstart')==timedelta(hours=2)
    script="require('./static/ui-state.js');console.log(JSON.stringify(RadarUI.calendarEvent("+json.dumps(public)+")));"
    frontend=json.loads(subprocess.check_output(['node','-e',script],cwd=Path(__file__).resolve().parents[1],text=True))
    assert frontend['allDay'] is all_day
    assert frontend['start']==('2026-10-10' if all_day else '2026-10-10T14:00:00')
    assert frontend['end']==('2026-10-11' if all_day else '2026-10-10T16:00:00')

@pytest.mark.parametrize('base_all_day',[True,False])
def test_existing_date_precision_is_preserved(base_all_day):
    base={'start_at':'2026-10-04T00:00:00+08:00','end_at':'2026-10-05T00:00:00+08:00','all_day':base_all_day}
    e=details.merge(base,{'start_at':'2026-10-03T14:00:00+08:00','end_at':'2026-10-03T16:00:00+08:00','all_day':not base_all_day},{})
    assert all(e[k]==v for k,v in base.items())

@pytest.mark.parametrize('cached',[False,True],ids=['fetch','cache'])
@pytest.mark.parametrize('detail_start,detail_end,matching',[
    ('2026-10-11T14:00:00+08:00','2026-10-11T16:00:00+08:00',False),
    ('2026-10-10T14:00:00+08:00','2026-10-10T16:00:00+08:00',True),
    ('2026-10-10T06:00:00Z','2026-10-10T08:00:00Z',True),
],ids=['conflicting-start','matching-start','matching-instant'])
def test_douban_missing_end_requires_matching_detail_schedule(isolated,monkeypatch,cached,detail_start,detail_end,matching):
    url='https://www.douban.com/event/12345/'
    def listing(start):
        html='<li class="list-entry"><div class="title"><a href="'+url+'">深圳社区活动</a></div><meta itemprop="startDate" content="'+start+'"><span itemprop="location">深圳测试场馆</span></li>'
        return coverage.douban_all(soup(html),url)[0]
    base=listing('2026-10-10T14:00:00+08:00')
    assert base['start_at']=='2026-10-10T14:00:00+08:00' and base['end_at'] is None and not base['all_day']
    html='<script type="application/ld+json">'+json.dumps({'@type':'Event','name':base['title'],'url':url,'startDate':detail_start,'endDate':detail_end})+'</script>'
    calls=[];monkeypatch.setattr(collectors,'fetch',lambda url,**kw:(calls.append(url) or html,soup(html),url))
    source={'id':'douban-fixture','kind':'douban','enrich_dated':True,'request_delay':0}
    if cached:
        old=listing(detail_start)
        assert coverage._detail_fingerprint(old)==coverage._detail_fingerprint(base)
        coverage.enrich_details(source,[old],metrics())
    m=metrics();event=coverage.enrich_details(source,[base],m)[0]
    assert len(calls)==1 and m['detail_cached']==int(cached) and m['detail_attempted']==int(not cached)
    assert event['start_at']==base['start_at'] and event['all_day'] is False
    assert event['end_at']==(core.iso(detail_end) if matching else None)
    provenance=event['details'].get('field_provenance',{})
    assert ('end_at' in provenance) is matching
    assert 'start_at' not in provenance
    core.ingest(source,event)
    with core.db() as db:event_id=db.execute('SELECT id FROM events WHERE url=?',(url,)).fetchone()[0]
    monkeypatch.setattr(api,'ROOT',core.ROOT);api.initialize_settings()
    with TestClient(api.app) as client:
        client.cookies.set(api.COOKIE,api.sign_session({'id':1,'username':'schedule-fixture'}))
        response=client.get('/events/api/event/'+event_id+'.ics');assert response.status_code==200
        public=client.get('/events/api/event/'+event_id).json()
    exported=Calendar.from_ical(response.content).walk('VEVENT')[0]
    assert exported.decoded('dtstart')==datetime(2026,10,10,14,tzinfo=core.TZ)
    assert public['end_at']==(core.iso(detail_end) if matching else None)
    if matching:assert exported.decoded('dtend')-exported.decoded('dtstart')==timedelta(hours=2)
    else:assert 'dtend' not in exported

def test_unaccepted_dates_cannot_replace_listing_precision():
    base={'all_day':True,'details':{'review_hold':'date_conflict'}}
    e=details.merge(base,{'start_at':'2026-10-03T14:00:00+08:00','all_day':False},{})
    assert e['all_day'] is True and not e.get('start_at')
    assert details.merge({'all_day':True},{'all_day':False},{})['all_day'] is True

@pytest.mark.parametrize('observation',[
    {'end_at':'2026-10-10T16:00:00+08:00'},
    {'start_at':'invalid','end_at':'2026-10-10T16:00:00+08:00'},
    {'start_at':'2026-10-10T14:00:00+08:00','end_at':'2026-10-10T16:00:00+08:00','all_day':True},
])
def test_detail_end_requires_valid_start_and_matching_precision(observation):
    event=details.merge({'start_at':'2026-10-10T14:00:00+08:00','end_at':None,'all_day':False},observation,{})
    assert event['end_at'] is None

@pytest.mark.parametrize('matching',[False,True])
def test_missing_start_requires_matching_current_end(matching):
    base={'end_at':'2026-10-10T16:00:00+08:00','all_day':True}
    observation={'start_at':'2026-10-10T14:00:00+08:00','end_at':'2026-10-10T16:00:00+08:00' if matching else '2026-10-11T16:00:00+08:00','all_day':False}
    event=details.merge(base,observation,{})
    assert event.get('start_at')==(observation['start_at'] if matching else None)
    assert event['end_at']==base['end_at'] and event['all_day'] is (not matching)

def test_rejected_schedule_does_not_claim_observation_provenance():
    fresh={'start_at':{'kind':'source','evidence_url':URL}}
    observed={'start_at':{'kind':'structured'},'end_at':{'kind':'structured'},'all_day':{'kind':'structured'},'attendance':{'kind':'structured'}}
    event=details.merge({'start_at':'2026-10-10T14:00:00+08:00','end_at':None,'all_day':False,'details':{'field_provenance':fresh}},
        {'start_at':'2026-10-11T14:00:00+08:00','end_at':'2026-10-11T16:00:00+08:00','all_day':False,'details':{'field_provenance':observed}},
        {'field_provenance':{'end_at':{'kind':'label'}}})
    assert event['end_at'] is None
    assert event['details']['field_provenance']=={**fresh,'attendance':observed['attendance']}

def test_rejected_schedule_only_provenance_is_removed():
    event=details.merge({'start_at':'2026-10-10T14:00:00+08:00','end_at':None,'all_day':False},
        {'start_at':'2026-10-11T14:00:00+08:00','end_at':'2026-10-11T16:00:00+08:00','details':{'field_provenance':{'start_at':{'kind':'structured'}}}},
        {'field_provenance':{'end_at':{'kind':'label'}}})
    assert event['end_at'] is None and 'field_provenance' not in event['details']

def test_unknown_tech_listing_attendance_uses_explicit_jsonld(isolated,monkeypatch):
    listing='<a href="/event/fixture"><h3>社区活动</h3><span>参加方式待确认</span><p>简介</p><div><i i-carbon-location></i>深圳测试场馆</div></a>'
    base=coverage.tech_all(soup(listing),URL)[0]
    assert base['details']['attendance']=='unknown'
    html='<script type="application/ld+json">'+json.dumps({'@type':'Event','name':'社区活动','url':URL,'eventAttendanceMode':'https://schema.org/OnlineEventAttendanceMode','startDate':'2026-10-10T14:00:00+08:00','endDate':'2026-10-10T16:00:00+08:00'})+'</script>'
    calls=[];monkeypatch.setattr(collectors,'fetch',lambda url,**kw:(calls.append(url) or html,soup(html),url))
    source={'id':'tech-fixture','kind':'tech','enrich_dated':True,'request_delay':0}
    fresh=coverage.enrich_details(source,[dict(base)],metrics())[0]
    assert fresh['details']['attendance']=='online' and core.event_attendance(fresh)=='online'
    m=metrics();cached=coverage.enrich_details(source,[dict(base)],m)[0]
    assert m['detail_cached']==1 and len(calls)==1 and cached['details']['attendance']=='online'

@pytest.mark.parametrize('mode',['online','hybrid','offline'])
def test_explicit_fresh_attendance_remains_authoritative(mode):
    e=details.merge({'details':{'attendance':mode}},{'details':{'attendance':'online'}},{})
    assert e['details']['attendance']==mode

def test_attendance_review_hold_preserves_unknown_mode():
    e=details.merge({'details':{'attendance':'unknown','review_hold':'attendance_conflict'}},{'details':{'attendance':'online'}},{})
    assert e['details']['attendance']=='unknown' and e['details']['review_hold']=='attendance_conflict'

@pytest.mark.parametrize('part',['structured_details','metadata','metadata_details'])
@pytest.mark.parametrize('provenance',['malformed',[],None,{'start_at':'malformed'},{'start_at':{'kind':[]}},{'start_at':{'kind':'structured','evidence_url':[]}}])
def test_malformed_nested_cache_provenance_is_safe_miss(isolated,monkeypatch,part,provenance):
    observation={'kind':'detail_observation','version':1,'structured':{'details':{}},'metadata':{}}
    fields=observation['structured']['details'] if part=='structured_details' else observation['metadata'] if part=='metadata' else observation['metadata'].setdefault('details',{})
    fields['field_provenance']=provenance
    base={'title':'活动','url':URL,'cost_text':'199元','location':'深圳新场馆'}
    payload=json.dumps(observation)
    with core.db() as db:db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?)',('a',URL,coverage._detail_fingerprint(base),payload,'ok',core.stamp(),core.iso(core.now()+timedelta(hours=24))))
    calls=[];html='<main><p>主办方：实际主办</p></main>'
    monkeypatch.setattr(collectors,'fetch',lambda url,**kw:(calls.append(url) or html,soup(html),url))
    m=metrics();e=coverage.enrich_details({'id':'a','request_delay':0},[base],m)[0]
    assert coverage._detail_observation(payload) is None
    assert len(calls)==1 and m['detail_cached']==0 and m['detail_attempted']==1
    assert e['cost_text']=='199元' and e['location']=='深圳新场馆' and e['organizer']=='实际主办'

def test_observation_cache_remerges_fresh_fee_location_dates_status(isolated,monkeypatch):
    html='<main><p>费用：50元</p></main><script type="application/ld+json">'+json.dumps({'@type':'Event','name':'活动','startDate':'2026-10-03','location':{'name':'旧场馆'},'offers':{'price':0}})+'</script>'
    calls=[]
    monkeypatch.setattr(collectors,'fetch',lambda url,**kw:(calls.append(url) or html,soup(html),url))
    source={'id':'fixture','enrich_dated':True,'request_delay':0}
    base={'title':'活动','summary':'简介','url':URL,'start_at':'2026-10-03','details':{'publisher':'发布账号'}}
    first=coverage.enrich_details(source,[base],metrics())[0]
    with core.db() as db:payload=json.loads(db.execute('SELECT payload FROM detail_cache').fetchone()[0])
    assert payload['kind']=='detail_observation' and payload['version']==1
    assert 'publisher' not in payload['structured']['details']
    fresh={**base,'cost_text':'199元','location':'深圳新场馆','start_at':'2026-10-08','end_at':'2026-10-09','status':'cancelled','all_day':False,'details':{'attendance':'hybrid','review_hold':'date_conflict'}}
    m=metrics();e=coverage.enrich_details(source,[fresh],m)[0]
    assert len(calls)==1 and m['detail_cached']==1
    assert all(e[k]==v for k,v in fresh.items() if k!='details') and not e['cost_free']
    assert e['details']['attendance']=='hybrid' and e['details']['review_hold']=='date_conflict'

@pytest.mark.parametrize('payload',['{broken','[]','{"kind":"detail_observation","version":1,"structured":[],"metadata":{}}','{"kind":"detail_observation","version":true,"structured":{},"metadata":{}}','{"kind":"detail_observation","version":1,"structured":{"cost_text":[]},"metadata":{}}',json.dumps({'cost_text':'免费','location':'旧场馆'})])
def test_legacy_and_malformed_cache_are_safe_misses(isolated,monkeypatch,payload):
    base={'title':'活动','url':URL,'cost_text':'199元','location':'深圳新场馆'}
    with core.db() as db:db.execute('INSERT INTO detail_cache VALUES(?,?,?,?,?,?,?)',('a',URL,coverage._detail_fingerprint(base),payload,'ok',core.stamp(),core.iso(core.now()+timedelta(hours=24))))
    calls=[];html='<main><p>费用：免费</p></main>'
    monkeypatch.setattr(collectors,'fetch',lambda url,**kw:(calls.append(url) or html,soup(html),url))
    m=metrics();e=coverage.enrich_details({'id':'a','request_delay':0},[base],m)[0]
    assert len(calls)==1 and m['detail_cached']==0 and e['cost_text']=='199元' and e['location']=='深圳新场馆'
