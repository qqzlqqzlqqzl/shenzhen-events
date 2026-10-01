# Favorite query planning

Refs [Issue 83](https://github.com/qqzlqqzlqqzl/shenzhen-events/issues/83).
Baseline: `33108a0a366ed9bf1eece262f59dfdbf509a9534`.

## Change

Favorite listings without an exact event ID add an event-ID semijoin over
nonzero preferences. Exact and redirected point lookups retain their existing
primary-key seek and favorite predicate without enumerating the favorite set. The existing preference predicate, LEFT JOIN, read transaction,
source hydration, aliases, Python filtering, ordering, totals and facets remain
in place. There is no candidate limit or cache. A partial index on
`preferences(event_id) WHERE favorite<>0` is created idempotently by `init()`.

The baseline scans `idx_events_query_time` and probes preferences for every
event. The new plan searches events by primary key after reading the favorite
ID index. It sorts the matching rows rather than using the full event-time
index for order. NULL/zero preferences stay excluded and negative nonzero
legacy flags retain their existing meaning.

## Reproduce

```sh
python -m pytest -q tests/test_favorite_query.py
python tests/benchmark_favorite_query.py
```

The benchmark is bounded to 10,000 and 100,000 synthetic activities and 3–21
repeats per variant. It creates disposable databases, never uses the configured
application database, and writes measurements to
`artifacts/favorite-query-benchmark.json`. Optional `--out` chooses the report
path. All source URLs are synthetic. No service or remote connection is used.

The old SQL predicate is reconstructed at connection execution, sharing the
unchanged current Python normalization and filtering. Comparisons include the
baseline, direct nonzero predicate, semijoin without index, and indexed
semijoin, with and without `ANALYZE`. The report includes source hashes,
runtime versions, every sample, plans, result digests and equality assertions.
Timing is diagnostic rather than a flaky test threshold.

## Measured result

Seven warm connection-per-call samples per variant, 100 favorites (10 hidden),
mixed dates/status/attendance/topic/details/source rows, on the shared local
runner. The final implementation rerun with SQLite 3.53.1 measured:

| Activities | Preference rows | Prior full core query | Indexed semijoin |
|---:|---:|---:|---:|
| 10,000 | 585 | 6.43 ms | 3.60 ms |
| 10,000 | 10,000 | 10.45 ms | 4.03 ms |
| 100,000 | 5,085 | 46.37 ms | 4.07 ms |
| 100,000 | 100,000 | 219.49 ms | 4.27 ms |

The initial independent audit on SQLite 3.46.1 measured 49.17→4.17 ms and
237.35→4.26 ms for the two 100k cases. Exact timings vary with load; these are
synthetic results, not production measurements or a promised speedup. A reduced
SQLite-only control with 0, 100, 1k, 10k and 100k favorites returned identical
ordered rows and showed no regression in that reduced control. Independent
review of the full core with all 100k activities favorited measured 7.00→7.70 s
(three warm samples on the busy shared runner). The sparse improvement does not
apply universally; high favorite cardinality can cost extra sorting and ID-set
work. No adaptive heuristic is introduced on the basis of these noisy samples.

At 100k preference rows / 100 favorites, the index occupied one 4 KiB page and
built in about 4.1–4.2 ms on SQLite 3.53.1 / 3.46.1. Nine measured transactions
of 100 favorite toggles changed median write time from 0.324→0.340 ms and
0.348→0.388 ms respectively. Nonfavorite insert and viewed-update changes were
small and noisy. The index is not free, and its size grows with favorite count.
At 100k favorites, independent review measured index size 1,683,456 bytes and
build time 23.98 ms. Full initial measurements and a stdlib-only plan reproducer
are in Issue 83.

## Verification boundaries

- Strict baseline red: three planning/migration assertions failed; semantic
  assertions already passed. After the implementation, all 28 focused tests
  pass on both SQLite 3.53.1 and 3.46.1
- Full local Python/API suite: 410 passed; pinned jsdom 30.1.1 DOM suite: 76
  passed; static JavaScript syntax, Python compilation and diff check passed
- Independent review caught an avoidable point-lookup regression (100k events /
  10k marks: 0.86→2.91 ms; 100k marks: 0.94→17.93 ms). The point-ID guard
  removes that extra subquery; two
  new plan/semantic regressions failed before the guard and pass afterward
- Tests cover aliases/redirects, empty marks, legacy orphan preferences,
  multiple source links, NULL/zero/negative flags, hidden privacy, filtered
  counts/exclusions, source order, mixed offsets, full all-day boundaries and
  immediate read-after-write. A concurrent writer cannot tear the read snapshot
- 2,500 marked activities pass with the bound-variable limit set to 300;
  maximum observed parameters remain the existing 256 source-link batch
- Local browser suites were attempted but Chromium launch is blocked by the
  sandbox's `socket()` permission. No local browser assertion or production
  acceptance is claimed; the exact-head CI browser matrix remains required

No production state or deployment target is changed by this work. The eventual
PR requires independent review and exact-head CI before any merge/deployment.
