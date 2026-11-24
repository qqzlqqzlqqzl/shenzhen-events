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

## Final production acceptance

Runtime candidate: 025b53193ce004fb438b8bc3768facab1812719c.

- 91 unit/API tests pass; all 23 isolated browser regressions pass again on final code.
- 6 real HTTPS acceptance checks pass, including the actual installed one-minute retry timer. Only the requested TechEvent source changed its check timestamp; all other source timestamps remained unchanged.
- September 2026 uses five rows and contains no October event. Next-month navigation and mobile list view work.
- The source-status view clears old list counts, exposes measured coverage, and explains tokens / requests / budgets / pending analysis.
- AMap is live: natural museum resolves to 坪山. New segmented English locality cases (Fu Tian Qu) and duplicate-failure starvation are fixed; a subsequent production enrichment batch updated eight records with zero errors.
- Acceptance snapshot: 812 upcoming records, 69 weekend records under the default long-running filter, 988 raw records, 573 pending AI analyses. AI budgets were not raised to drain the new backlog; basic source-derived dates and filters remain available.
- Huodongxing's latest pass: six readable anonymous pages, 64 unique records; source total 1,882 includes inaccessible inventory. The seventh page requests login, explicitly recorded as partial. The initial pass found 65; promoted cards can change between reads.
- Original routes: / 200, /inbox/ 200, /newapi 302, /blog 302, /events/ 200.
- Browser console/page errors: zero. Web service memory approximately 48 MiB; original application services were not modified by this release.

Public evidence is in artifacts/coverage-review/public/; no private session token or feed-token URL is saved there. A private pre-coverage SQLite recovery snapshot remains on the server.
