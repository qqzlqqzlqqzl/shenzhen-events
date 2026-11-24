import pytest

from radar import core

CASES = [
    # Sub-area names without the district.
    ('广东深圳前海青年梦工场北区二期L栋愈欣空间', '南山'),
    ('坂田天安云谷', '龙岗'),
    ('华强北赛格广场', '福田'),
    # An explicit district is no longer hidden by 、 inside one address.
    ('南山区 万象天地剧场 粤海街道科发路19号万象天地西侧一、二层', '南山'),
    ('宝安区 海雅大剧院 建安一路99号海雅缤纷城F3层L399、F4层', '宝安'),
    # Longer venue names win over names they contain.
    ('深圳国际会展中心 1号馆', '宝安'),
    ('深圳会展中心 9号馆', '福田'),
    ('东部华侨城茶溪谷', '盐田'),
    ('华侨城创意文化园', '南山'),
    ('沙头角中英街', '盐田'),
    # The explicit district wins; a generic word like 东门 (east gate) is not a place.
    ('南山区深圳湾公园东门', '南山'),
    # Ambiguous or unknown stays unknown.
    ('深圳市民中心→宝安海滨广场（参考线路）', ''),
    ('南山、福田多场', ''),
    ('深圳 / 具体地点报名后可知', ''),
    ('线上', ''),
    ('Frankfurt, Germany', ''),
]


@pytest.mark.parametrize('location,district', CASES)
def test_infer_district(location, district):
    assert core.infer_district(location) == district


def test_normalized_event_uses_inferred_district():
    event = core.normalize_event({'title': 'x', 'url': 'https://example.com/x', 'location': '前海嘉里中心'})
    assert event['district'] == '南山'
    event = core.normalize_event({'title': 'y', 'url': 'https://example.com/y', 'location': '深圳'})
    assert event['district'] == '待确认'
