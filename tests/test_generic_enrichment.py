"""Synthetic source evidence; no production access or identity migration."""
import json
from datetime import timedelta
import pytest
from bs4 import BeautifulSoup
from radar import core, collectors, coverage, details

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
