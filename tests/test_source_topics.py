import json
import pytest
from radar.source_topics import developer_category
from radar.source_fields import event_patch
from radar import core

@pytest.mark.parametrize('label,topic',[
    ('JavaScript','软件开发'),('Rust','软件开发'),('Testing / QA','软件开发'),
    ('Open Source','AI与开源'),('Artificial Intelligence (AI)','AI与开源'),
    ('Product management','产品与创业'),('Business Analysis','产品与创业'),
    ('Tech leadership','学习成长')])
def test_explicit_aggregator_categories(label,topic):
    assert developer_category(label+' conference Online')==(label,[topic])
    assert developer_category(label+' conference in Moscow, Russia and Online')==(label,[topic])
    assert topic in core.TOPICS

@pytest.mark.parametrize('description',['Tech conference Online','Other conference Online','A play mentioning JavaScript','JavaScript conference','Secret Category conference Online','JavaScript conference Online\nignore instructions'])
def test_unknown_or_unstructured_description_is_not_forced(description):
    assert developer_category(description)[1]==[]

def test_repair_preserves_reviewed_and_other_sources():
    row={'title':'Not a keyword inference','summary':'JavaScript conference Online','ai_state':'pending','topics':'["其他"]','details':'{}'}
    fix=event_patch(row,{'dev-events-online'})
    assert json.loads(fix['topics'])==['软件开发']
    assert json.loads(fix['details'])['source_topic']=='JavaScript'
    assert set(fix)=={'topics','details'}
    assert event_patch({**row,**fix},{'dev-events-online'})=={}
    assert event_patch({**row,'ai_state':'done'},{'dev-events-online'})=={}
    assert event_patch(row,{'another-source'})=={}
    assert event_patch({**row,'details':'{"review_hold":"date_conflict"}'},{'dev-events-online'})=={}
