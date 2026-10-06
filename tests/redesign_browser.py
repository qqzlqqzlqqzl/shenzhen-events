"""Focused desktop UI regression for #98; existing isolated real API harness."""
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import expect
from review_harness import Harness

h = Harness("redesign")
p = h.page
try:
    now = h.core.now()
    h.core.ingest({"id": "a", "priority": 10}, {
        "title": "长期展览对照", "url": "https://example.com/ui-long",
        "start_at": (now - timedelta(days=30)).date().isoformat(),
        "end_at": (now + timedelta(days=30)).date().isoformat(),
        "all_day": True, "location": "深圳测试展厅",
        "summary": "只用于隔离环境验证长期活动后置。",
        "event_type": "ExhibitionEvent", "event_type_state": "done",
    })
    queries = []
    p.on("request", lambda r: queries.append(r.url)
         if "/events/api/events?" in r.url else None)
    h.goto()
    expect(p.locator(".event-card")).to_have_count(5)
    expect(p.locator("#filter-panel")).to_be_hidden()
    expect(p.locator("#search")).to_be_visible()
    h.check("collapsed_filters_and_real_summary",
            p.locator("#count-upcoming").inner_text().isdigit())
    h.check("sticky_search_toolbar",
            p.locator(".explore-toolbar").evaluate(
                "e => getComputedStyle(e).position === 'sticky'"))

    p.locator("#search").fill("审阅活动 1")
    p.locator("#search").press("Enter")
    expect(p.locator(".event-card")).to_have_count(1)
    p.locator('[data-filter-remove="search"]').click()
    expect(p.locator(".event-card")).to_have_count(5)
    h.check("individual_search_chip_removes_only_search",
            not parse_qs(urlsplit(p.url).query).get("q"))
    before = len(queries)
    p.locator("#open-filters").click()
    p.locator("#search").fill("取消的草稿")
    p.keyboard.press("Escape")
    expect(p.locator("#search")).to_have_value("")
    expect(p.locator("#open-filters")).to_be_focused()
    # The explicit opener receives focus; the search is returned to its toolbar.
    h.check("cancel_preserves_query_and_search_home",
            len(queries) == before and
            p.locator("#search").evaluate("e => !!e.closest('.toolbar-search')"))

    p.locator("#open-filters").click()
    p.locator("#date-from").fill((now.date() + timedelta(days=2)).isoformat())
    p.locator("#date-until").fill((now.date() + timedelta(days=3)).isoformat())
    p.locator("#apply-filter-draft").click()
    expect(p.locator(".event-card")).to_have_count(2)
    p.locator('[data-filter-remove="dates"]').click()
    expect(p.locator(".event-card")).to_have_count(5)
    h.check("date_chip_restores_full_applied_results")

    before = len(queries)
    ids = p.locator(".event-card").evaluate_all("els => els.map(e => e.dataset.event)")
    p.locator('[data-display-mode="list"]').click()
    expect(p.locator(".date-group")).to_have_count(5)
    h.check("date_grouping_preserves_order_without_fetch",
            len(queries) == before and
            ids == p.locator(".event-card").evaluate_all("els => els.map(e => e.dataset.event)"))
    expect(p.locator(".cost-state").first).to_have_text("费用待确认")
    expect(p.locator(".card-time").first).not_to_be_empty()
    p.screenshot(path=str(h.out / "desktop-list.png"), full_page=True)

    title = p.locator(".title-button").first
    p.evaluate("window.scrollTo(0, 300)")
    title.scroll_into_view_if_needed()
    scroll_y = p.evaluate("scrollY")
    title.click()
    expect(p.locator("#detail")).to_be_visible()
    h.check("native_right_drawer",
            p.locator("#detail").evaluate(
                "e => Math.abs(e.getBoundingClientRect().right-innerWidth)<2 && e.getBoundingClientRect().width<650"))
    p.screenshot(path=str(h.out / "desktop-detail.png"))
    p.keyboard.press("Escape")
    expect(p.locator("#detail")).to_be_hidden()
    expect(title).to_be_focused()
    h.check("detail_escape_keeps_filter_list_and_focus",
            p.locator(".date-group").count() == 5 and
            p.locator('[data-display-mode="list"]').get_attribute("aria-pressed") == "true" and
            abs(p.evaluate("scrollY") - scroll_y) < 2)

    p.locator(".compare-toggle").nth(0).click()
    p.locator(".compare-toggle").nth(1).click()
    p.locator("#compare-open").click()
    expect(p.locator("#compare-dialog")).to_be_visible()
    expect(p.locator("#compare-body")).to_contain_text("审阅活动 1")
    p.locator("#close-compare").click()
    h.check("existing_comparison_still_works")
    p.locator("#theme-toggle").click()
    expect(p.locator("html")).to_have_attribute("data-theme", "dark")
    p.reload()
    expect(p.locator("#event-list")).to_have_attribute("aria-busy", "false")
    expect(p.locator("html")).to_have_attribute("data-theme", "dark")
    expect(p.locator(".date-group")).to_have_count(5)
    h.check("theme_and_display_preference_persist")
    p.screenshot(path=str(h.out / "desktop-dark.png"), full_page=True)

    p.locator("#search").fill("没有这个活动的空状态对照")
    p.locator("#search").press("Enter")
    expect(p.locator(".event-card")).to_have_count(0)
    p.locator('.empty [data-action="reset"]').click()
    expect(p.locator(".event-card")).to_have_count(5)
    h.check("empty_state_reset_preserves_data")
    p.locator('.display-modes [data-view="calendar"]').click()
    expect(p.locator("#calendar")).to_have_attribute("aria-busy", "false")
    p.locator("#open-filters").click()
    p.locator("#hide-long").uncheck()
    p.locator("#apply-filter-draft").click()
    expect(p.locator("#calendar-long")).to_be_visible()
    expect(p.locator("#calendar-long-items")).to_be_hidden()
    h.check("calendar_first_long_after_and_collapsed",
            p.evaluate("!!(document.querySelector('#calendar').compareDocumentPosition(document.querySelector('#calendar-long')) & Node.DOCUMENT_POSITION_FOLLOWING)"))
    before = len(queries)
    p.locator("[data-calendar-long-toggle]").click()
    expect(p.locator("#calendar-long-items")).to_be_visible()
    h.check("long_disclosure_does_not_change_hide_long_or_fetch",
            len(queries) == before and not p.locator("#hide-long").is_checked())
    h.check("desktop_no_horizontal_overflow",
            p.evaluate("document.documentElement.scrollWidth <= innerWidth"))
except Exception as exc:
    h.report["errors"].append(str(exc))
    raise
finally:
    h.close()
