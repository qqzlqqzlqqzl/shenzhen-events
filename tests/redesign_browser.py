"""Focused #100 template/desktop interactions against the isolated real API."""
from datetime import timedelta
import json
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
    # Diverse disposable records keep facet counts and combinations real.
    with h.core.db() as db:
        for index, event_id in enumerate(h.ids):
            district = ("南山", "南山", "福田", "福田", "宝安")[index]
            event_type = ("ConferenceEvent", "ConferenceEvent", "ConferenceEvent", "CourseInstance", "MusicEvent")[index]
            topics = ["AI与开源"] if index < 3 else ["硬件创客"]
            free = index in (1, 2)
            db.execute("UPDATE events SET district=?,location=?,event_type=?,topics=?,cost_free=?,cost_text=?,details=? WHERE id=?",
                       (district, district + "测试地点", event_type, json.dumps(topics), int(free),
                        "免费" if free else "费用未注明", json.dumps({"attendance": "offline"}), event_id))
        db.execute("UPDATE events SET summary=? WHERE id=?",
                   ("隔离环境的可重复审阅活动。" * 80, h.ids[0]))

    def card_ids():
        return p.locator(".event-card").evaluate_all("els => els.map(e => e.dataset.event)")

    def open_group(kind):
        group = p.locator("#" + kind + "-filter")
        if not group.evaluate("e => e.open"):
            group.locator("summary").click()

    def only(kind, value):
        open_group(kind)
        p.locator(f'[data-facet-only="{kind}"][data-facet-value="{value}"]').click()
        p.locator("#" + kind + "-filter summary").click()

    queries = []
    p.on("request", lambda r: queries.append(r.url)
         if "/events/api/events?" in r.url else None)
    h.goto()
    expect(p.locator(".event-card")).to_have_count(5)
    expect(p.locator("#filter-panel")).to_be_hidden()
    expect(p.locator("#search")).to_be_visible()
    stats_response = h.ctx.request.get(h.base + "/events/api/stats")
    h.check("collapsed_filters_and_real_summary", stats_response.ok and
            p.locator("#count-upcoming").inner_text() == str(stats_response.json()["upcoming"]))
    h.check("sticky_search_toolbar",
            p.locator(".explore-toolbar").evaluate(
                "e => getComputedStyle(e).position === 'sticky'"))

    h.report["layout"] = []
    for width, columns in ((1200, 3), (1440, 3), (1920, 3), (2560, 3), (900, 2), (560, 1)):
        p.set_viewport_size({"width": width, "height": 1000})
        geometry = p.locator("#event-list").evaluate(r"""e => {
            const cards = [...e.querySelectorAll('.event-card')].map(c => c.getBoundingClientRect());
            return {viewport: innerWidth, columns: getComputedStyle(e).gridTemplateColumns.split(/\s+/).length,
                    lefts: [...new Set(cards.map(r => Math.round(r.left)))].length,
                    overflow: document.documentElement.scrollWidth > innerWidth};
        }""")
        h.report["layout"].append(geometry)
        h.check("card_columns_" + str(width), geometry["columns"] == columns and
                geometry["lefts"] == columns and not geometry["overflow"])
    p.set_viewport_size({"width": 1440, "height": 1000})
    h.check("template_card_hierarchy", p.locator(".event-card").first.evaluate("""e => {
        const card = getComputedStyle(e), title = getComputedStyle(e.querySelector('h3'));
        const summary = getComputedStyle(e.querySelector('.card-summary'));
        return card.borderRadius === '22px' && card.paddingTop === '20px' &&
               title.fontSize === '18px' && summary.webkitLineClamp === '2';
    }"""))
    p.screenshot(path=str(h.out / "desktop-cards-light.png"), full_page=True)
    p.emulate_media(reduced_motion="reduce")
    h.check("card_respects_reduced_motion", p.locator(".event-card").first.evaluate(
        "e => getComputedStyle(e).transitionDuration.split(',').every(v => parseFloat(v) === 0)"))
    p.emulate_media(reduced_motion="no-preference")

    p.locator("#search").fill("审阅活动 1")
    p.locator("#search").press("Enter")
    expect(p.locator(".event-card")).to_have_count(1)
    p.locator('[data-filter-remove="search"]').click()
    expect(p.locator(".event-card")).to_have_count(5)
    h.check("individual_search_chip_removes_only_search",
            not parse_qs(urlsplit(p.url).query).get("q"))
    initial_badge = int(p.locator("#filter-count").inner_text() or "0")
    h.check("filter_badge_counts_applied_conditions", initial_badge == p.locator("#active-filters button").count())
    before, applied_url = len(queries), p.url
    p.locator("#open-filters").click()
    expect(p.locator("#filter-dialog")).to_be_visible()
    expect(p.locator("#open-filters")).to_have_attribute("aria-expanded", "true")
    h.check("filters_expand_below_toolbar_without_modal", p.locator("#filter-dialog").evaluate("""e => {
        const tools = document.querySelector('.explore-tools').getBoundingClientRect();
        return e.tagName !== 'DIALOG' && !document.querySelector(':modal') &&
               getComputedStyle(e).position !== 'fixed' && e.getBoundingClientRect().top >= tools.bottom - 1 &&
               !document.body.classList.contains('modal-open');
    }"""))
    p.screenshot(path=str(h.out / "desktop-filters-expanded.png"), full_page=True)
    p.locator("#search").fill("取消的草稿")
    p.locator("#attendance").select_option("offline")
    p.locator("#open-filters").click()
    expect(p.locator("#filter-dialog")).to_be_hidden()
    expect(p.locator("#open-filters")).to_have_attribute("aria-expanded", "false")
    p.locator("#open-filters").click()
    expect(p.locator("#search")).to_have_value("取消的草稿")
    expect(p.locator("#attendance")).to_have_value("offline")
    h.check("collapse_reopen_preserves_unapplied_draft", p.url == applied_url and len(queries) == before and
            int(p.locator("#filter-count").inner_text() or "0") == initial_badge)
    p.locator("#search").focus()
    p.keyboard.press("Escape")
    expect(p.locator("#filter-dialog")).to_be_hidden()
    expect(p.locator("#search")).to_have_value("")
    expect(p.locator("#attendance")).to_have_value("all")
    expect(p.locator("#open-filters")).to_be_focused()
    p.wait_for_timeout(350)  # A cancelled debounced search must not fire later.
    h.check("cancel_preserves_query_and_search_home",
            len(queries) == before and p.url == applied_url and
            p.locator("#search").evaluate("e => !!e.closest('.toolbar-search')"))

    # Multi-select is OR within a group, AND across groups, and stays a draft.
    for action in ("cancel", "apply"):
        before = len(queries)
        p.locator("#open-filters").click()
        only("district", "南山")
        open_group("district")
        p.locator('#district-options input[value="福田"]').check()
        expect(p.locator('#district-options input:checked')).to_have_count(2)
        p.locator('#district-options input[value="福田"]').uncheck()
        p.locator("#district-filter summary").click()
        only("type", "ConferenceEvent")
        only("topic", "AI与开源")
        p.locator("#attendance").select_option("offline")
        p.locator("#free").check()
        expect(p.locator(".event-card")).to_have_count(5)
        h.check("combined_" + action + "_remains_unapplied", len(queries) == before)
        p.locator("#" + ("cancel" if action == "cancel" else "apply") + "-filter-draft").click()
        expect(p.locator("#filter-dialog")).to_be_hidden()
        if action == "cancel":
            expect(p.locator("#free")).not_to_be_checked()
            h.check("explicit_cancel_restores_all_groups", len(queries) == before and p.url == applied_url)
        else:
            expect(p.locator(".event-card")).to_have_count(1)
            params = parse_qs(urlsplit(queries[-1]).query)
            h.check("combined_real_filter_applies_once", len(queries) == before + 1 and card_ids() == [h.ids[1]] and
                    params.get("districts") == ["南山"] and params.get("type") == ["ConferenceEvent"] and
                    params.get("topic") == ["AI与开源"] and params.get("attendance") == ["offline"] and params.get("free") == ["true"])
            actual = h.ctx.request.get(queries[-1]).json()
            h.check("result_count_uses_api", actual["total"] == 1 and "1 个活动" in p.locator("#result-count").inner_text())
            for kind in ("type", "topic"):
                for row in actual["facets"][kind]:
                    item = p.locator(f'#{kind}-options input[value="{row["value"]}"]')
                    if item.count():
                        expect(item.locator("xpath=..").locator("[data-facet-count]")).to_have_text(str(row["count"]))
            h.check("facet_counts_use_applied_api_scope")
            applied_badge = int(p.locator("#filter-count").inner_text())
            h.check("filter_badge_tracks_only_applied_conditions", applied_badge > initial_badge and
                    applied_badge == p.locator("#active-filters button").count())
            expect(p.locator("#active-filters")).to_contain_text("南山")
            p.screenshot(path=str(h.out / "desktop-applied-filters.png"), full_page=True)
    p.locator('[data-filter-remove="free"]').click()
    expect(p.locator(".event-card")).to_have_count(2)
    h.check("removing_one_chip_preserves_other_groups", card_ids() == h.ids[:2] and
            parse_qs(urlsplit(p.url).query).get("districts") == ["南山"] and
            int(p.locator("#filter-count").inner_text()) == applied_badge - 1)
    p.locator("#open-filters").click()
    open_group("district")
    p.locator('[data-facet-kind="district"][data-facet-action="all"]').click()
    expect(p.locator('#district-options input:not(:checked)')).to_have_count(0)
    p.locator("#reset-filter-draft").click()
    p.locator("#apply-filter-draft").click()
    expect(p.locator(".event-card")).to_have_count(5)
    h.check("all_select_and_reset_restore_real_results", card_ids() == h.ids)

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
    for close_action in ("escape", "button", "backdrop"):
        title.click()
        expect(p.locator("#detail")).to_be_visible()
        h.check("centered_detail_" + close_action, p.locator("#detail").evaluate("""e => {
            const r = e.getBoundingClientRect();
            return Math.abs((r.left + r.right) / 2 - innerWidth / 2) < 2 &&
                   Math.abs((r.top + r.bottom) / 2 - innerHeight / 2) < 2 &&
                   r.left > 20 && r.right < innerWidth - 20 && r.top >= 0 && r.bottom <= innerHeight;
        }"""))
        h.check("detail_background_locked_" + close_action,
                p.evaluate("getComputedStyle(document.body).overflowY === 'hidden'"))
        if close_action == "escape":
            p.keyboard.press("ArrowRight")
            expect(p.locator("#detail-title")).to_have_text("审阅活动 2")
            p.keyboard.press("ArrowLeft")
            expect(p.locator("#detail-title")).to_have_text("审阅活动 1")
            h.check("existing_detail_sequence_navigation")
            scroll_container = p.locator("#detail").evaluate("""e => {
                const scroller = [e, ...e.querySelectorAll('*')].find(n =>
                    /auto|scroll/.test(getComputedStyle(n).overflowY) && n.scrollHeight > n.clientHeight);
                if (!scroller) return false;
                scroller.scrollTop = 100;
                return scroller.scrollTop > 0;
            }""")
            h.check("long_detail_scrolls_inside", scroll_container)
            p.mouse.move(4, 4)
            p.mouse.wheel(0, 300)
            p.wait_for_timeout(100)
            h.check("detail_wheel_cannot_scroll_background", abs(p.evaluate("scrollY") - scroll_y) < 2)
            p.screenshot(path=str(h.out / "desktop-detail-centered.png"))
            p.keyboard.press("Escape")
        elif close_action == "button":
            p.locator('#detail [data-save]').click()
            expect(p.locator('#detail [data-save]')).to_have_attribute("aria-pressed", "true")
            p.get_by_role("button", name="感兴趣", exact=True).click()
            expect(p.get_by_role("button", name="感兴趣", exact=True)).to_have_attribute("aria-pressed", "true")
            expect(p.locator('#detail a[href="https://example.com/e0"]').first).to_have_attribute("target", "_blank")
            p.locator("#close-detail").click()
        else:
            p.mouse.click(4, 4)
        expect(p.locator("#detail")).to_be_hidden()
        expect(title).to_be_focused()
        h.check("detail_" + close_action + "_restores_list_scroll_focus",
                p.locator(".date-group").count() == 5 and
                p.locator('[data-display-mode="list"]').get_attribute("aria-pressed") == "true" and
                abs(p.evaluate("scrollY") - scroll_y) < 2 and
                not p.evaluate("document.body.classList.contains('modal-open')"))
    expect(p.locator(f'.event-card[data-event="{h.ids[0]}"] [data-save]')).to_have_attribute("aria-pressed", "true")
    h.check("detail_favorite_feedback_persist_to_real_api",
            h.ctx.request.get(h.base + "/events/api/event/" + h.ids[0]).json()["favorite"] and
            h.ctx.request.get(h.base + "/events/api/event/" + h.ids[0]).json()["feedback"] == "interested")

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
