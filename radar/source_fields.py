"""Conservative repairs from explicit fields in already retained source text."""
import re

def inline_fields(value):
    text=re.sub(r'\s+',' ',str(value or '')).strip();out={}
    for key,label in [('location','地点'),('cost_text','费用'),('publisher','发起')]:
        m=re.search(re.escape(label)+r'\s*[：:]\s*(.*?)(?=\s*(?:时间|地点|费用|发起|主办)\s*[：:]|\s*\d+人(?:参加|感兴趣)|$)',text)
        if m and m[1].strip():out[key]=m[1].strip()[:250 if key=='location' else 100]
    return out

def obvious_type(title):
    for words,typ in [(('脱口秀','单口喜剧'),'ComedyEvent'),(('音乐会','演唱会'),'MusicEvent'),(('舞剧',),'DanceEvent'),(('话剧','舞台剧'),'TheaterEvent')]:
        if any(w in str(title) for w in words):return typ
    return None

def event_patch(row,source_ids):
    import json
    from . import core
    details=json.loads(row.get('details') or '{}') if isinstance(row.get('details'),str) else dict(row.get('details') or {})
    if details.get('review_hold'):return {}
    patch={};before=dict(details)
    if source_ids=={'douban'}:
        values=inline_fields(row.get('summary'))
        if not core.clean(row.get('location')) and values.get('location'):
            patch['location']=values['location'];ds={d for d in core.DISTRICTS if d in patch['location']};patch['district']=next(iter(ds)) if len(ds)==1 else '待确认'
        if core.clean(row.get('cost_text')) in ('','费用未注明','未注明','未知','待确认') and values.get('cost_text'):
            patch['cost_text']=values['cost_text'];patch['cost_free']=int(values['cost_text'] in ('免费','0元','免费参加'))
        if values.get('publisher'):details['publisher']=values['publisher']
        typ=obvious_type(row.get('title'))
        if typ and row.get('event_type_state')=='pending' and row.get('ai_state')=='pending':
            patch.update(event_type=typ,event_type_state='source',topics=json.dumps(['文化艺术'],ensure_ascii=False),priority='normal',reason='演出类活动；不因作品标题或场馆地址中的技术词汇进入技术推荐。')
            details['type_evidence']='活动标题明确演出形式'
    if source_ids=={'dev-events-online'} and row.get('ai_state')=='pending':
        from .source_topics import developer_category
        source_topic,topics=developer_category(row.get('summary'))
        if topics:
            patch['topics']=json.dumps(topics,ensure_ascii=False)
            details['source_topic']=source_topic
            details['topic_evidence']='dev.events 原文分类：'+source_topic
    if source_ids=={'huodongxing'} and row.get('organizer') and not details.get('organizer') and not details.get('organizer_notes'):
        details['publisher']=row['organizer'];details['organizer_role']='publisher'
    if details!=before:patch['details']=json.dumps(details,ensure_ascii=False)
    return {k:v for k,v in patch.items() if row.get(k)!=v}
