# Discovery, details and filter review — 2026-09-30

Scope: issue #38. Root authored the functional changes and reviewed the public-source evidence. Server operations are separately executed over the existing authorized SSH route.

## Changes
- All/none/invert checkbox semantics with URL and back-navigation persistence; none returns zero results.
- Unknown price labels hidden, never treated as free; known costs remain visible.
- Attributed organizer/co-organizer/poster/detail text, no independent endorsement implied.
- Dated entries enter the bounded rotating detail queue; cached observations do not continuously requeue unchanged content.
- Broader WeChat discovery: sixteen query groups, four per source run. This is search coverage, not sixteen newly verified publishers or a full WeChat feed.
- Two new first-party adapters: Shenzhen Convention & Exhibition Center schedule and CIOE edition page. Source-side HTTP accessibility still must be validated on the deployment host. Failed/blocked fetches must remain visible, never counted as successful coverage.
- Derived culture/social/learning themes replace avoidable generic labels. Literal ASCII word boundaries reduce AI false positives inside unrelated English words.
- External-model calls fail closed unless analysis_enabled is exactly true; existing timer explicitly disabled. Collector/retry remain separate and checks rotate oldest-first.
- Manual date-conflict hold survives future ingestion. WorkBuddy page states October 3 while its attached poster states September 23; retain review status rather than inventing a resolved date.

## Validation at preparation
- 149 Python unit/API tests passed, including disabled model network guards, explicit empty facets, metadata safety, stable raw identity, year rollover and review-hold persistence.
- 15 Node DOM tests passed: filtering, inversion, zero selection, refresh, history and previous multi-day calendar checks.
- Python and JavaScript syntax checks passed.
- Guarded 175-record review import fixture: dry-run, apply, idempotent replay and protected-field/table invariants passed.
- Headless Chromium could not launch in the root execution sandbox (socket operation not permitted). This is not a browser-test pass. Run full browser suites against the candidate on the supported deployment executor/CI before production acceptance.

## Boundaries
- No automatic image OCR or continuous dot review daemon added; source images are available for direct review.
- No registration, contact, CAPTCHA bypass, login scraping or external-model request performed.
- Primary dates and venue fields are not changed by the reviewed data patch. WorkBuddy is withheld from upcoming results, not silently moved to an assumed date.
- Current-source reachability and production authenticated UI remain deployment gates.

## Product-flow pass
Signed-in users go straight to activities instead of a large marketing hero. Source diagnostics move to a secondary header entry. Filter chips describe the smaller selected/excluded set instead of listing every hidden alternative; card action opens details without implying external navigation. Readability and touch target sizes improved. None-selection, default-all and legacy URLs remain explicit.
