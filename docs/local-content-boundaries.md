# Local content and feedback repair

This follow-on branch starts at reviewed PR89 `8a8b902` and stays local. It does
not change PR89, publish a new issue/PR, migrate identities or backfill records.

Cards retain the full source summary (except an exact title duplicate). The
upstream whitespace normalization discards paragraph boundaries, so a generic
`时间：` substring cannot prove schedule boilerplate. Even a leading label may
be ordinary prose. Known flattened schedule text stays intact alongside the
structured schedule display.

Unlabelled JSON-LD descriptions are safe literal text, including `<vector>`,
`Vec<T>`, tag lessons and entity-looking strings. A structured description
explicitly declaring `encodingFormat: text/html` is extracted through the
existing BeautifulSoup text path; encoded code, paragraphs, emphasis and lists
retain readable text. `text/plain` and absent/unknown format declarations stay
literal. No tag-name guessing or new innerHTML trust is introduced. A source
that emits unlabelled HTML therefore retains its markup as escaped text until
its representation can be established; this is a deliberate non-lossy fallback.

Canonical URL validation evaluates the parsed port. Malformed, negative,
decimal and above-65535 ports fail new ingestion. Valid parser boundaries 0,
1 and 65535 remain accepted without claims about reachability. Historical bad
URLs retain event facts and source names. Original, source-health, evidence and
image actions show unavailable text rather than a `#` link. Comparison and copy
continue omitting bad destinations. ICS omits the invalid URI property while
retaining the event, dates and source attribution text; ordinary valid path and
query content remains intact. No historical database writes occur.

For requested `feedback='any'` or a nonempty tag only, SQL rejects rows with
empty feedback and empty tag storage before hydration. This parenthesized
predicate is a superset: Python still rejects unknown signals and invalid or
unknown JSON tags. LEFT JOIN, BEGIN, ordering, 256-row batches, facets and other
filters retain their contracts. No new index, migration, semijoin or LIMIT is
added. Snapshot tests cover concurrent clear/add and source changes; ordered
output/facet comparisons cover malformed and nullable legacy feedback.

Run focused Python/DOM regressions, the existing source/coverage/recurring
suites, all Python/JavaScript/DOM tests and supported browser suites. The opt-in
`tests/benchmark_feedback_query.py OUTPUT.json` measures sparse and dense 10k
synthetic feedback on the local SQLite version, including all-feedback overhead,
with output equality and no fixed timing assertions.

The separate refresh-race commit ports the verified deferred-response audit:
13 passing boundaries stay intact and seven defect assertions now require the
repaired behavior. A confirmed personal write advances a read generation.
List/calendar responses begun before that write are reissued before rendering,
preserving the applied query and the corrected snapshot. This also refreshes
membership, totals and facets instead of patching individual stale result rows.
Pending favorite controls remain disabled when replaced; obsolete stats failures
use the same latest-ticket guard as success.

Same-source retry locks live outside replaceable DOM nodes. Keyboard focus moves
to that source's inspection summary while retry is unavailable. A token equality
check prevents an old-session finally handler clearing a new lock. Existing
query/session guards and the PR90 overlay hunk stay untouched. Real Chromium
checks favorite/unsave reads on a disposable API fixture; source retry POST/status
are intercepted, so no collector/provider runs or backend deduplication proof is
claimed. The handoff's backend deduplication finding was inspection only.
