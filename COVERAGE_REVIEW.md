# Source coverage and interaction release review

Issues #21–#31; complements AMap PR #16 (#15, #17–#20).

## Source contracts

| Source | Contract |
|---|---|
| Lianpu | Observed city next-page links; bounded and resumable. |
| Douban | Observed offset paging; include main/ticket cards, exclude host cards; event-ID dedupe. |
| Huodongxing | Shenzhen public city pages via the existing RSSHub network; declared page totals; bounded paging and continuation. |
| TechEvent | All visible cards then explicit Shenzhen/other-city counts. |
| Chaihuo | Reconcile visible poster cards and other-city exclusions on this listing. |
| Bendibao | Specified public aggregate page only; partial. |
| Meetup | Public discovery inventory only; partial; structured locality and JSON-LD dedupe. |
| WeChat/Sogou | Search-index/discovery only; partial, never whole-WeChat coverage. |

HTTP 200 is not coverage. Each run stores page count, visible/extracted/unique/Shenzhen/admitted counts, exclusion reasons, truncation and continuation cursor. Parse discrepancies and large count drops trigger a partial warning.

## Details and date evidence
RSS no longer silently stops at 30 entries or repeatedly enriches only the first eight. Persistent detail caching prioritizes never-attempted records. Caps and deferred work are visible. Douban ticket cards missing a year remain leads until explicit detail metadata resolves the date. Historical entries outside the retention window are excluded before AI work; existing AI classifications are not bulk reset.

## Interaction behavior
- Month queries use currentStart/currentEnd, hide other-month cells and omit the forced sixth week.
- Status view clears prior activity counts and list filters.
- AI usage explains tokens, requests, daily caps and upstream billing; it is not an activity count or a RMB invoice.
- Single-source retry is authenticated, CSRF-protected, rate-limited and persistent. Duplicate clicks reuse the active job. A separate one-minute oneshot timer processes only that source under the shared collection lock.
- Retry UI shows queued/running/completed/failed states and updates automatically. Expanded budget help stays open during polling.
- Old calendar requests cannot clear a newly opened status view. Session expiry clears long-calendar content too.

## Deployment
From the production checkout, `sudo python3 deploy/install.py retry` installs only the new retry service/timer. Original Inbox/NewAPI/Blog and shared RSSHub services remain untouched. Database migration is additive. Collection stays within the existing eight-minute / 224 MiB limits; bounded runs resume where they stopped.

## Evidence
Unit/API: artifacts/coverage-review/unit.xml.
Browser: artifacts/coverage-review/browser/ (23 cases including network failures, races, queue endpoints, strict CSP, 320px mobile and month boundaries).
Source probes: artifacts/coverage-review/source-probe.json; these are deliberately bounded probes, not a full-source coverage claim.
Production evidence is appended after candidate deployment.

## Production collection and access boundary
The candidate checked all nine sources in 169 seconds. Lianpu: 6 pages / 260 unique / 87 within retained scope. Douban: 71 pages / 708 unique admitted (host cards excluded, repeated ticket cards deduplicated). Huodongxing: six anonymous city pages / 65 unique; page seven serves a login form. This provider restriction is explicit partial coverage, not a parser-success or full-inventory claim. No login challenge was bypassed. All other source contracts/counters were persisted.
