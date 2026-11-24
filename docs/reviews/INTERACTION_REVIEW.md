# Interaction review — 2026-09-29

Baseline: `8589ea0` (main). Work is isolated in `fix/interaction-review`.
Issues: #3 navigation, #4 favorites/session, #5 calendar/status, #6 search identity.

## Confirmed regressions fixed

- View, search, district and category survive refresh and browser back/forward through URL state.
- Detail links can be reopened directly; Escape/backdrop/back restore the underlying filter context.
- Expired sessions and logout close dialogs, abort requests and clear private caches/DOM.
- Favorite writes are locked per event and use the authoritative server response; failures preserve prior state.
- Saved past/cancelled/review events remain available with accurate lifecycle labels.
- Pagination is guarded against rapid clicks; retry preserves already-loaded cards.
- Search waits for Chinese IME completion and ignores obsolete responses.
- Calendar requests the visible [start,end) interval and walks all API pages (505-event fixture).
- Calendar month persists; changing viewport switches month/list layouts without changing the selected month.
- Shanghai date formatting correctly handles local-midnight crossings, independent of browser timezone.
- Source counters distinguish normal from partial/empty coverage.
- Rotating Sogou transport URLs no longer create new rows or trigger new AI analysis when evidence is unchanged.
- Exact title+body identity requires compatible publisher/publication evidence; different explicit publication dates stay distinct.

## Verification

`tests/test_radar.py`: 41 unit/API tests, including before-fix failing cases.
`tests/review_browser.py`: isolated real API + Chromium, 18 interaction scenarios, controlled failures/races.
Evidence lives under `artifacts/review/`. Synthetic destructive tests never use the production database.
Original `tests/browser_acceptance.py` remains the public HTTPS regression gate.

No additional package/service dependency; existing strict CSP retained. Main application services are not modified.
