# Calendar / weekend UX review

Scope: Issues #10–#13.

## Root cause

The event model stores a source-provided start/end interval. Some Shenzhen listings use that interval for a long exhibition/opening period or a repeated series. The old weekend query correctly detected interval overlap, but the card still displayed the original start date; FullCalendar also rendered the whole interval as a multi-week bar. This made May/July starts look like current-weekend events and flooded every calendar day.

## Behavior after this change

- An explicit span of 14 days or more is classified at read time as `long_running` (no DB migration or AI rerun).
- Long/repeated entries are hidden by default and can be restored with one checkbox.
- If restored in Week/Weekend, their card uses the effective current window date and says “本周仍开放 / 本周末仍开放”; detail view retains the authoritative source date range.
- List ordering is server-side and supports near→far / far→near before pagination.
- Month view is start-based: normal events are shown on their start date only. Long/repeated entries, when enabled, live in a separate compact panel rather than spanning every day.
- The filter, long-running toggle and sort choice survive URL reload/back/forward.

## Production read-only impact check

At 2026-09-29, the previous weekend query returned 39 records. The new default returns 17; the removed 22 are all >=14-day range/repeat records. No records are deleted. They remain available by unchecking “隐藏长期/重复”.

## Verification

- 46 unit/API tests pass.
- Focused browser checks: 6/6 pass.
- Existing interaction regression: 18/18 pass.
- Browser page errors: zero.
- Desktop and mobile calendar screenshots are under `artifacts/calendar-review/`.

## Public HTTPS release-candidate acceptance

Candidate `a409285` was temporarily deployed only to `shenzhen-events.service` and tested at the real HTTPS endpoint.

- Weekend default: 17 records vs 39 with long/repeated items enabled.
- The previously reported May/July-start records are absent by default.
- When long/repeated items are enabled, an old-start exhibition is labeled “本周末仍开放” and uses the current weekend date on its card.
- Server-side ascending/descending time order and URL reload were verified.
- Default month grid contains no spanning long bars; enabling long items shows them in a separate panel and leaves the grid clean.
- Mobile calendar has no horizontal overflow.
- Routes remain: `/` 200, `/inbox/` 200, `/newapi` 302, `/blog` 302, `/events/` 200.
- Browser console/page errors: zero.
- Existing Inbox/NewAPI/RSSHub processes were not restarted.

Evidence: `artifacts/calendar-review/public/` and `public-run.log`.
