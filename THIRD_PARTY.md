# Third-party components and attribution

This project is Apache-2.0 licensed. Upstream services and bundled third-party assets retain their own licenses.

## Community Calendar — Apache-2.0
- Repository: https://github.com/judell/community-calendar
- Inspected file: `scrapers/lib/base.py`, Git blob `48fe7c1f826404ff50ca10f32337042973f255f6`.
- `radar/calendar.py` adapts the `BaseScraper.create_calendar` / `create_event` export pattern and documents the modifications in its module header.
- Changes: Asia/Shanghai timezone, stable canonical event IDs, DTSTAMP/LAST-MODIFIED, exclusive all-day end, merged source attribution, and no invented end time for an event without one.
- Source-priority and cross-source duplicate handling informed the design. The Chinese normalization, district conflict guard, SQLite schema and event-candidate verification are original implementation; this is not a deployment of Community Calendar's Supabase stack.
- Apache-2.0 license text is included as `LICENSE`. Upstream source remains available at the link above.

## FullCalendar Standard 6.1.19 — MIT
- Repository: https://github.com/fullcalendar/fullcalendar
- Installed using `npm pack fullcalendar@6.1.19 --ignore-scripts`.
- Local browser bundle: `static/vendor/fullcalendar.js`.
- Original MIT license: `static/vendor/FullCalendar-LICENSE.md`.
- Checksums and asset sizes: `artifacts/frontend-assets.json`.
- Standard month/list components only; no Premium/Scheduler code.
- Calendar receives Shanghai wall-clock values using a UTC coordinate display. This deliberately keeps the displayed Chinese event clock fixed even when the browser is in another timezone. It does not convert the underlying event instant: API and exported ICS retain +08:00 / Asia/Shanghai correctly.

## RSSHub — existing external service
- Repository: https://github.com/DIYgod/RSSHub
- Existing local service is reused on port 1200, without copying or modifying its source or service configuration.
- Routes used: `/huodongxing/explore` and `/wechat/sogou/ChaiHuoMakerSpace`.
- The activity route is a national latest-list route, not complete Shenzhen coverage. Search-index-based WeChat results are explicitly marked partial.

## Python libraries
Pinned installed versions are in `requirements.lock.txt`: FastAPI, Uvicorn, Requests, BeautifulSoup, Feedparser, RapidFuzz, icalendar, recurring-ical-events, and their dependencies. Test tooling includes pytest and httpx.

`recurring-ical-events` is retained as an optional extension dependency; the shipped public-source adapters currently normalize explicit date spans, not a complete recurrence import pipeline. A long date span must not be interpreted as proof that an activity occurs every day.

## Source content
Activity titles, event facts and concise descriptions are attributed to their original source links. This private aggregation installation does not grant redistribution rights over source articles, images or third-party site databases. No original full-article snapshots or user credentials are committed.
