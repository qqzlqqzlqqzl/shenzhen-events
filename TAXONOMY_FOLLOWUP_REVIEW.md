# Taxonomy upgrade follow-up review

Reviewed original PR #35 head `daabcc595c0faa4225aa253684a0640b13031133`.

## Fixed findings

1. **P1: unchanged legacy source refresh erased AI-confirmed event data.** New normalized taxonomy fields and changed rule-derived topics altered legacy raw hashes. An unchanged refresh was treated as new source content, reset completed AI state and replaced AI-confirmed dates/location with the original incomplete source payload. Reproduction also moved an event from `scheduled` to `needs_review`. The fix compares legacy source content without upgrade-derived fields, upgrades only that record's raw payload/hash during its normal refresh, and preserves dates, location, summaries, preferences, source links and completed AI analysis. Newly extracted authoritative source types can update just taxonomy fields. Genuine source edits still queue analysis.
2. **P2: generic Event filter disagreed with its facet count.** Pending records used the `Event` fallback but were excluded from the “其他活动” count. The type filter now excludes pending classifications; those records remain in unfiltered results with “待分类”.
3. **P2: legacy culture-topic selections were lost.** Normalize `展览文化` to `文化艺术` before validation in source topics, API topic/tag filters and restored URL state. OR-within-group semantics remain intact when legacy and new parameters coexist.
4. **P2: selecting all offered event types returned HTTP 400.** Validate against the canonical vocabulary size rather than an arbitrary limit of 20. All 23 offered values can be selected together.

## Verification

- Original head: 100 tests passed but did not cover these upgrade/filter regressions.
- Six new regression assertions fail against the original code and pass with the fixes.
- Corrected code: 111 unit/API tests pass, including no full reanalysis for unchanged legacy records, genuine source changes, source type authority, call/token budget exhaustion and 12-item backfill batches under the per-run limit.
- Four actual-app DOM scenarios pass: legacy URL restoration, OR/AND filtering and chip removal, all 23 types, and browser-history state restoration.
- Python compile and JavaScript syntax pass.
- No production data, credentials or AI API calls were used.

## Gates still open

Real-browser tests were attempted but Chromium could not create its required local socket in this executor. DOM tests do not establish visual layout, keyboard accessibility or mobile touch acceptance. The original PR's browser/screenshots evidence applies to the previous head only. Rerun browser suites and inspect desktop/mobile screenshots for this corrected candidate, then perform production migration/candidate and public HTTPS acceptance before merge or issue closure. No new production acceptance is claimed.
