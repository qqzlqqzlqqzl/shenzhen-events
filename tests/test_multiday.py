"""Date-span rendering regressions; no live data or model calls."""
import json
import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

def display(event):
    script = "require('./static/ui-state.js');const e=" + json.dumps(event) + ";console.log(JSON.stringify({span:RadarUI.dateSpan(e),calendar:RadarUI.calendarEvent(e),full:RadarUI.fullTime(e)}));"
    return json.loads(subprocess.check_output(['node', '-e', script], cwd=ROOT, text=True))

@pytest.mark.parametrize('start,end,all_day,days,last', [
    ('2026-10-14T00:00:00+08:00','2026-10-17T00:00:00+08:00',True,3,'2026-10-16'),
    ('2026-09-30T10:00:00+08:00','2026-10-02T18:00:00+08:00',False,3,'2026-10-02'),
    ('2026-10-14T22:00:00+08:00','2026-10-15T00:00:00+08:00',False,1,'2026-10-14'),
    ('2026-10-14T22:00:00+08:00','2026-10-15T01:00:00+08:00',False,2,'2026-10-15'),
    ('2026-10-14T23:59:00+08:00',None,False,1,'2026-10-14'),
    ('2026-10-14T00:00:00+08:00',None,True,1,'2026-10-14'),
    ('2026-10-14T10:00:00+08:00','2026-10-14T10:00:00+08:00',False,1,'2026-10-14'),
    ('2026-10-13T16:00:00Z','2026-10-16T16:00:00Z',True,3,'2026-10-16'),
    ('2026-12-31T00:00:00+08:00','2027-01-03T00:00:00+08:00',True,3,'2027-01-02'),
])
def test_span_uses_shanghai_calendar_days_and_exclusive_end(start,end,all_day,days,last):
    result=display(dict(id='span',title='活动',start_at=start,end_at=end,all_day=all_day))
    assert result['span']['days']==days
    assert result['span']['last']==last
    assert result['calendar']['display']==('block' if days>1 else 'list-item')
    assert bool(result['span']['label'])==(days>1)
    if days>1:assert f'跨 {days} 天' in result['span']['label']


def test_calendar_keeps_exact_timed_interval_and_normalizes_offsets():
    result=display(dict(id='timed',title='活动',start_at='2026-10-14T14:00:00Z',end_at='2026-10-14T17:00:00Z',all_day=False))
    assert result['calendar']['start']=='2026-10-14T22:00:00'
    assert result['calendar']['end']=='2026-10-15T01:00:00'
    assert result['calendar']['allDay'] is False
    assert '2026/10/15 01:00' in result['full']


def test_all_day_range_disclaims_unknown_opening_hours():
    result=display(dict(id='three',title='展览',start_at='2026-10-14',end_at='2026-10-17',all_day=True))
    assert result['span']['label']=='10/14—10/16 · 跨 3 天'
    assert result['calendar']['end']=='2026-10-17'
    assert '具体时段/开放日以原文为准' in result['full']

@pytest.mark.parametrize('end', ['2026-10-14T00:00:00+08:00','2026-10-14T10:00:00+08:00'])
def test_nonpositive_all_day_date_range_is_unknown_not_inverted(end):
    result=display(dict(id='invalid-end',title='活动',start_at='2026-10-14T00:00:00+08:00',end_at=end,all_day=True))
    assert result['span']['days']==1 and result['span']['last']=='2026-10-14'
    assert result['calendar']['end'] is None
    assert result['full']=='2026/10/14 · 具体时段未注明'
    assert result['calendar']['extendedProps']['fullTime']==result['full']


def test_calendar_favorite_is_semantic_not_color_only():
    result=display(dict(id='fav',title='收藏活动',start_at='2026-10-14T19:00:00+08:00',end_at='2026-10-14T21:00:00+08:00',all_day=False,favorite=1))
    assert 'favorite-event' in result['calendar']['classNames']
    assert result['calendar']['extendedProps']['favorite'] is True
    assert result['calendar']['extendedProps']['favoriteRank'] == 0
    plain=display(dict(id='plain',title='普通活动',start_at='2026-10-14T19:00:00+08:00',end_at='2026-10-14T21:00:00+08:00',all_day=False,favorite=0))
    assert 'favorite-event' not in plain['calendar']['classNames']
    assert plain['calendar']['extendedProps']['favorite'] is False
    assert plain['calendar']['extendedProps']['favoriteRank'] == 1
