from bs4 import BeautifulSoup

from radar import coverage, posters

POSTER = 'https://img3.doubanio.com/pview/event_poster/{}/public/b734641f995e278.jpg'


def test_douban_list_cards_keep_their_poster_as_the_large_cover():
    html = ('<li class="list-entry"><div class="pic"><a href="https://www.douban.com/event/1/">'
            '<img src="https://img3.doubanio.com/f/shire/x/pics/blank.gif" data-lazy="' + POSTER.format('median') + '"></a></div>'
            '<div class="title"><a href="https://www.douban.com/event/1/">深圳技术沙龙</a></div>'
            '<meta itemprop="startDate" content="2026-12-05T14:00:00"></li>'
            '<li class="list-entry"><div class="title"><a href="https://www.douban.com/event/2/">没有海报的活动</a></div></li>')
    items = coverage.douban_all(BeautifulSoup(html, 'html.parser'), 'https://www.douban.com/location/shenzhen/events/future-all')
    assert items[0]['details']['cover'] == POSTER.format('large')
    assert 'cover' not in items[1]['details']


def test_cover_comes_first_and_douban_sizes_collapse():
    details = {'cover': POSTER.format('large'),
               'images': [POSTER.format('small'), POSTER.format('large'), 'https://img3.doubanio.com/view/page_note/large/public/p1.jpg']}
    assert posters.image_list(details) == [POSTER.format('large'), 'https://img3.doubanio.com/view/page_note/large/public/p1.jpg']


def test_listed_pictures_win_over_a_discovered_cover_and_others_pass_through():
    assert posters.image_list({'images': ['https://a.test/1.png']}, 'https://a.test/og.png') == ['https://a.test/1.png', 'https://a.test/og.png']
    assert posters.image_list({}, 'https://a.test/og.png') == ['https://a.test/og.png']
    odd = ['https://a.test/1.png', {}, 'http://plain.test/x.png']
    assert posters.image_list({'images': odd}) is odd
