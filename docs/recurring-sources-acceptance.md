# Three recurring hardware/community sources

Tracks [Issue 76](https://github.com/qqzlqqzlqqzl/shenzhen-events/issues/76).
The candidate adds recurring inventories through `worker.collect_source → coverage.collect_report → parse_page`, with registration in `sources.json`. No production collection or deployment is part of this candidate's verification.

## Source contracts

- **Elecfans**: upcoming webinar cards only; speakers, survey links and recommendations are excluded. Explicit dates use date granularity and exclusive end boundaries. Raw clocks and unconfirmed timezone remain visible in review notes; no precise +08 webinar clock is asserted. Attendance is online, organizer/fee remain unknown, and online items are not geocoded. Detail enrichment remains disabled until the detail-body contract is verified.
- **Xuanwu**: discover the current same-origin hashed activity module, then parse its first strictly validated JSON literal without executing JavaScript. Escapes, interpolation, expressions and wrong shapes fail closed; unrelated news/video arrays are excluded. Shenzhen venue evidence determines inclusion; publication dates do not replace event clocks. Recaps relate only to an existing announcement with the same start and address. The September 5 announcement keeps its planned 17:30 end and is marked needs_review against the recap's 17:40 evidence. Organizer is attributed to the source's rendered statement, fees remain unknown, and reused coordinates are omitted.
- **Shenzhenware**: hot and regular card sections, same-origin numeric event URLs only. Its verified page query contract is bounded to five pages; regular rows determine progress, so fixed hot rows do not stop traversal. Date-only ranges retain exclusive ends. Conflicting header/body clocks become needs_review with visible evidence. Historical sections, related events and the generic ¥0 modal do not supply organizer, clock or fee evidence. Undisclosed addresses stay undisclosed.

Requests reuse public-address/redirect guards, byte limits and a Linux main-thread hard deadline. Unsupported timer contexts fail closed. Delays consume the same source budget; 403/429 retain existing inventory and use worker backoff. These sources use supplement-only detail patches and fingerprints including fresh schedule, venue, all_day, cancellation and conflict metadata. Legacy full-event cache payloads cannot replace fresh listings. Manual review holds keep existing ingestion behavior.

## Narrow identity protection

The reproduced same-name/day online/offline collision is fixed in `core.is_duplicate`, with strict passing assertions. Different attendance modes containing pure online do not merge by title/date alone. Hybrid/offline heuristic matching additionally requires the same specific venue and either the same stated organizer or confirmed start clock. Serialized SQLite details preserve attendance in this check. Exact canonical event URLs remain valid; reviewed aliases and existing same-source URL links are resolved before this heuristic. No other core query function is changed.

## Public probe results

Anonymous public GETs used a temporary database in the independent worktree, with planning cutoff Beijing 2026-10-01. Counts describe inspected source scope, not production net-new events.

| Source | Visible records | Unique activities | Admitted within existing retention | Future | Scope |
|---|---:|---:|---:|---:|---|
| Elecfans | 3 | 3 online | 3 | 3 | Current forthcoming page: ok |
| Xuanwu | 52 national; 6 Shenzhen | 5 Shenzhen after recap relation | 2 | 1 | Current activity inventory: ok |
| Shenzhenware | 60 appearances over 5 pages | 36 | 1 historical | 0 | Partial; next cursor page=6 |

Requests: Elecfans 1; Xuanwu 4 including module and two details; Shenzhenware 6 including one retained detail. All parser-unaccounted counts were zero. Separately inspected Shenzhenware page 1 had 12 unique URLs, and pages 1–2 had 18.

## Verification

Combined base: verified query [PR 78](https://github.com/qqzlqqzlqqzl/shenzhen-events/pull/78) candidate `d8ef4ac49a97b1c736f32dda6fcb1d6c6570c23d`; isolated branch `codex/recurring-hardware-sources-20261001`.

- Full combined Python/API suite: **311 passed**, no xfail, including a detail clock that cannot collapse a confirmed multi-day source range.
- All combined workflow DOM tests: **23 passed**.
- All six static JavaScript syntax checks, `compileall -q radar tests`, and `git diff --check`: passed.
- All 13 workflow browser suites passed: taxonomy, multiday, calendar, review_district, review_filter_context, review_personal, review_feedback_state, review_planning, review_decisions, review_recovery, feedback, review, coverage. These used temporary fixture databases and localhost API servers, covering desktop and mobile layouts, keyboard/focus, private state, pagination, recovery and source coverage.
- The static project has no separate package build command. Workflow checks above are its required validation.

Test-only Playwright/jsdom dependencies and logs stay under ignored worktree paths. Full public pages, private databases, keys and user data are not committed. Production net-new counts and production UI acceptance belong to the deployment owner.

This source commit is stacked on the verified query candidate rather than reimplementing its query changes. Both changes passed the complete matrix together. If PR 78 changes code before merging, repeat the combined matrix on its replacement head. Verify GitHub CI on the resulting exact source commit. Root review, merge and deployment remain outside this executor's scope.
