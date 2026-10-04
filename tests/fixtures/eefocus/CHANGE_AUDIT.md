# V2 → V3 change audit

## Findings addressed

- Case 37 assumed identity with a caller boolean: replaced it with an original detail HTML response, main heading and matching yearless actual-meeting fragment. The original short summary and undated review-only outcome remain
- HTTP200 and route shape were unchallenged: added six concrete list/detail body pairs, plus a fresh-cache contradiction case. Unrelated title, absent main identity, inconsistent same-title anchors and missing corroboration fail positive admission. Sidebar identity/status cannot override consistent main-event evidence
- Expired-cache cancellation never seeded a scheduled record: new lifecycle fixtures seed complete canonical/raw/source identities, scheduled status, favorite/feedback/viewed state, and immutable verified alias history. A current cancelled card plus ReadTimeout produces zero normal admissions/content updates and a durable uncertain eligibility veto
- “Preserve everything” could preserve unsafe upcoming: split unchanged canonical/user state from effective planning eligibility. Proposed guard state is processed independently of collect_report.items and consulted before planning filters/counts/caches/dispatch
- Failed cache could lose provenance: separate immutable last-verified bindings from latest cache attempts; failed-only rows cannot target suppression
- Alias reuse could permanently hide unrelated records: finite direct historical target sets get uncertain guards, with explicit disassociation/adjudication recovery and retained audit
- Fresh open and failed refresh could resurrect a cancellation: forbid generic open/absence/TTL/timeout from clearing guards; require explicit verified same-occurrence evidence. Independent manual holds remain
- Resolution could be undone by stale replay or clear a concurrent veto: add evidence identity, scoped compare-and-set resolution, idempotent captured-observation replay and concurrent-guard cases; a new fetch with identical bytes is not a proven replay without publisher-generation evidence
- Keyword-only cancellation could overreach: scoped current whole-event predicate excludes negations, historical quotes, unrelated sessions, sidebars and postponement. Postponement needs a separate review policy and is not claimed safe/upcoming by this pack

## Evidence-based rationale

Read-only local source bytes match all six inherited Git blob identities. worker.py:32 calls ingest only for returned items; therefore omission cannot by itself suppress an already stored scheduled event. recurring_sources.py:387–430 validates final URL equality and extracts a patch, which cannot prove body identity. core.py:436–546 filters planning results by stored status, so post-query warnings alone cannot implement safety suppression. core.py:315–378 can rekey/source-link/overlay held data through ingest, so unverified negative observations require their own non-ingest path. provenance.json records precise anchors and the absence of a new remote revision check.

These are implementation gaps supported by source inspection, not claims that the proposed guard schema or behavior already exists. The guard shape, reason strings, counters and state snapshots are fixture-side design oracles.

Independent read-only artifact review additionally caught and corrected detail-only inventory counter overstatements in cases 53–54, whole-scenario guard mutation accounting in case 62, and missing compare-and-set guard/revision inputs in case 56. These corrections were revalidated offline.

## Preservation and validation

baseline-v2.json captures all input v2 files. Validation checks the input directory remains byte-identical when locally present. V3 preserves 39 inherited cases unchanged and changes only case 37 among cases 01–40. It appends 24 cases (41–64).

The offline validator checks JSON and field types, referenced files, exact card/evidence content, counts, source blob hashes, preservation snapshots and selected invariants. SHA256SUMS.txt covers all pack files except itself. There are no application imports, network requests, real database mutations or executable adapter tests. Crash, concurrency and query outputs remain acceptance oracles awaiting an actual integration harness.
