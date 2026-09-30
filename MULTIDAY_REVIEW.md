# Short multi-day activity display

Issue: #36. The supplied example covers October 14–16, 2026.

This change is stacked on corrected taxonomy PR #35. The shared renderer, filters and migration fixes were tested together. Merge #35 only after its acceptance gates, then retarget this PR to main and validate the exact final candidate before merging.

## Cause and behavior

The previous calendar cleanup intentionally removed `end` from every FullCalendar event and discarded records that started before the selected month. That stopped long exhibition bars from flooding the grid but also collapsed ordinary multi-day activities to their first day.

- Keep the API's interval-overlap result, including prior-month starts.
- Pass the source start/end interval to FullCalendar. Desktop month view uses a colored span for short multi-day entries; the mobile month agenda lists the entry on each covered date.
- Show the full covered date range and number of calendar dates on event cards and calendar entries, such as `10/14—10/16 · 跨 3 天`.
- Normalize offset-bearing times to Shanghai wall-clock time before passing them to the calendar's UTC display zone. Preserve the exclusive source end; an event ending at midnight does not occupy the next date.
- Do not invent a multi-day duration for missing or zero-length ends. A one-second visual fallback keeps an untimed-end late-night entry on its start date while its source ending remains unknown.
- Retain the original full-time detail and opening-day disclaimer. A source date span does not assert that a venue is continuously open.
- Retain the existing >=14 elapsed-day long/repeated threshold and default-hide toggle. When enabled, those records stay available in the explicit month-overlap panel with their full source range and detail link. They do not flood every day of the grid.
- One canonical record and favorite per event; no database migration, collector changes, source-date rewrite, or AI calls.

## Validation

- Final combined candidate on corrected PR #35 (`d4bd289`): 136 unit/API/pure-JavaScript tests pass after final review corrections. The standalone main-based implementation previously passed 108.
- Actual bundled FullCalendar + actual app scripts: twelve DOM integration scenarios pass (seven multi-day and five taxonomy), including three mobile entries on October 14/15/16, cross-month inclusion, two desktop week segments, midnight exclusion, unknown ends, long-event separation and card range text.
- Python compile, JavaScript syntax and diff whitespace checks pass.
- DOM integration is not a layout or real-browser acceptance pass.

Commands:

```sh
.venv/bin/python -m pytest -q
npm install --prefix /tmp/radar-dom-check jsdom@30.1.1 --ignore-scripts
NODE_PATH=/tmp/radar-dom-check/node_modules node --test tests/multiday_dom.cjs
.venv/bin/python tests/multiday_browser.py
.venv/bin/python tests/calendar_browser.py
.venv/bin/python tests/review_browser.py
.venv/bin/python tests/coverage_browser.py
```

`RADAR_BROWSER` can select an installed browser explicitly; system Chromium/Chrome is supported before the existing server-specific fallback.

## Final review corrections

Independent review after the automated checks identified and resolved:

- Preserve FullCalendar's native focusable agenda link and its Enter/Space handlers; append one date-range label rather than replacing the interactive content. DOM regression verifies exactly one activation per Enter, Space and click and no duplicate label after view changes.
- Keep generic Event/其他 facets available at count zero, retaining saved/past/calendar filters and restored URLs.
- Treat nonpositive all-day date-domain endings as unknown consistently in detail labels, spans and calendar overlap queries. The known all-day date remains queryable without rewriting source dates.

Eight new Python regressions and the keyboard DOM regression failed before these fixes and pass afterward. The corrected code passed an independent re-review with no further confirmed code blockers.

## Hosted browser validation

`.github/workflows/validate-events.yml` runs the exact PR head on a standard GitHub-hosted Ubuntu runner with read-only repository permission. Official actions are SHA-pinned, checkout does not retain credentials, and no secrets, deployments or external test endpoints are configured. The job installs Chromium, runs unit/DOM/browser suites against disposable loopback fixtures, and retains screenshots/logs for seven days. Actual run results are recorded in PR checks; workflow configuration alone is not a browser pass.

## Release gates still open

The isolated real-browser suite was attempted but Chromium could not create its required local socket (`Operation not permitted`). The supported cloud browser also blocked the loopback fixture URL. No screenshots or browser pass are claimed. Run desktop/mobile visual acceptance and interaction regressions in a browser-capable executor, inspect actual screenshots, then perform the repository's production candidate and public HTTPS acceptance before merging/closing. This includes route isolation, authentication, filters, favorites, details, ICS, zero page errors and no horizontal overflow.
