"""One candidate snapshot, contextual OR-within/AND-between facets and exclusions."""
from collections import Counter
from .core import EVENT_TYPES, TOPICS, DISTRICTS, LONG_RUNNING_DAYS, canonical_topic


def contextual_listing(candidates, *, event_types=None, topics=None, tag='', district='', districts=None,
                       type_none=False, topic_none=False, district_none=False, hide_long=False, offset=0, limit=36):
    types=set(event_types or [])
    selected_topics={canonical_topic(x) for x in topics or []}
    if tag:selected_topics.add(canonical_topic(tag))
    selected_districts=set(districts) if districts is not None else ({district} if district else None)
    def type_match(e):return not type_none and (not types or e.get('event_type_state')!='pending' and e.get('event_type','Event') in types)
    def topic_match(e):return not topic_none and (not selected_topics or bool(selected_topics.intersection(e.get('topics',[]))))
    def district_match(e):return not district_none and (selected_districts is None or e.get('district') in selected_districts)
    # Explicitly hidden records are never exposed by the explanatory preview.
    base=[e for e in candidates if not e.get('hidden')]
    visible=[e for e in base if not hide_long or not e.get('long_running')]
    matched=[e for e in visible if type_match(e) and topic_match(e) and district_match(e)]
    excluded=[e for e in base if hide_long and e.get('long_running') and type_match(e) and topic_match(e) and district_match(e)]
    type_context=[e for e in visible if topic_match(e) and district_match(e)]
    topic_context=[e for e in visible if type_match(e) and district_match(e)]
    district_context=[e for e in visible if type_match(e) and topic_match(e)]
    tc=Counter(e.get('event_type','Event') for e in type_context if e.get('event_type_state')!='pending')
    pc=Counter(t for e in topic_context for t in set(e.get('topics',[])))
    dc=Counter(e.get('district','待确认') for e in district_context)
    return {'items':matched[offset:offset+limit],'total':len(matched),'offset':offset,'has_more':len(matched)>offset+limit,
            'facets':{'type':[{'value':v,'count':tc[v]} for v in EVENT_TYPES],
                      'topic':[{'value':v,'count':pc[v]} for v in [*TOPICS,'其他']],
                      'district':[{'value':v,'count':dc[v]} for v in [*DISTRICTS,'待确认']],
                      'type_pending':sum(e.get('event_type_state')=='pending' for e in type_context),
                      'scope':'other_applied_filters'},
            'excluded_long':{'items':excluded[:12],'total':len(excluded),'truncated':len(excluded)>12,
                             'threshold_days':LONG_RUNNING_DAYS,'applied':hide_long}}
