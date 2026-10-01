from radar.filtering import contextual_listing


def item(id,kind='LiteraryEvent',long=False,area='南山',topics=None,hidden=False,state='source'):
    return {'id':id,'event_type':kind,'event_type_state':state,'long_running':long,'district':area,'topics':topics or ['文化艺术'],'hidden':hidden}


def count(result,kind,value):return next(x['count'] for x in result['facets'][kind] if x['value']==value)


def test_counts_and_exclusions_use_the_same_long_running_rule():
    data=[item('short'),item('long',long=True),item('music','MusicEvent')]
    r=contextual_listing(data,event_types=['LiteraryEvent'],hide_long=True)
    assert [x['id'] for x in r['items']]==['short']
    assert r['total']==1 and count(r,'type','LiteraryEvent')==1
    assert count(r,'type','MusicEvent')==1  # Counts ignore only their own facet selection.
    assert r['excluded_long']['total']==1 and r['excluded_long']['items'][0]['id']=='long'
    r=contextual_listing(data,event_types=['LiteraryEvent'],hide_long=False)
    assert r['total']==2 and count(r,'type','LiteraryEvent')==2 and r['excluded_long']['total']==0


def test_other_selected_dimensions_constrain_each_facet_count():
    data=[item('a'),item('b',area='福田'),item('c','MusicEvent',topics=['机器人']),item('d','MusicEvent')]
    r=contextual_listing(data,event_types=['LiteraryEvent'],districts=['南山'],topics=['文化艺术'])
    assert [x['id'] for x in r['items']]==['a']
    assert count(r,'type','LiteraryEvent')==1 and count(r,'type','MusicEvent')==1
    assert count(r,'district','福田')==1 and count(r,'topic','机器人')==0


def test_hidden_records_never_reappear_in_gray_preview_or_counts():
    r=contextual_listing([item('short'),item('hidden',long=True,hidden=True)],hide_long=True)
    assert r['total']==1 and r['excluded_long']['total']==0 and count(r,'type','LiteraryEvent')==1


def test_empty_selection_remains_empty_but_own_options_can_be_recovered():
    r=contextual_listing([item('a')],type_none=True,hide_long=True)
    assert r['total']==0 and r['excluded_long']['total']==0
    assert count(r,'type','LiteraryEvent')==1 and count(r,'topic','文化艺术')==0


def test_excluded_preview_is_bounded_without_hiding_its_total():
    r=contextual_listing([item(str(i),long=True) for i in range(17)],hide_long=True)
    assert r['total']==0 and r['excluded_long']['total']==17
    assert len(r['excluded_long']['items'])==12 and r['excluded_long']['truncated'] is True


def test_pending_types_aliases_and_pagination_keep_existing_semantics():
    rows=[item('pending',state='pending'),item('a'),item('b')]
    r=contextual_listing(rows,tag='展览文化',offset=1,limit=1)
    assert r['total']==3 and [x['id'] for x in r['items']]==['a'] and r['has_more']
    assert r['facets']['type_pending']==1 and count(r,'type','LiteraryEvent')==2
    assert contextual_listing(rows,event_types=['LiteraryEvent'])['total']==2
