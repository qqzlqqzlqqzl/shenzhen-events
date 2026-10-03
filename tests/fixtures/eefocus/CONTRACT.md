# V3 contract: evidence-derived identity and safety-only cancellation suppression

This is a proposed source contract and synthetic acceptance oracle. It is not an installed adapter, database migration, or tested production behavior. V2 is preserved unchanged. V3 retains cases 01–40, strengthens case 37, and adds cases 41–64. Rules below supersede v2 only where explicitly stated.

## 1. Grounded existing behavior and verification boundary

The six inherited Git blob identities in provenance.json were rechecked against read-only local source bytes, not a newly fetched remote commit. No claim is made that those bytes still represent main. The original provenance was not an atomic commit pin.

- worker.collect_source iterates every collect_report.items entry and calls ingest (worker.py:25–60). A candidate omitted from items currently has no independent status-update channel
- recurring_sources.detail checks final URL equality, then extracts a patch (recurring_sources.py:387–430). HTTP success and a numeric route do not demonstrate an EEFocus event identity
- enrich_details leaves the base item on detail failure and increments detail_resolved after patch parsing (481–542). V3 requires identity validation before treating an EEFocus detail patch as a success
- ingest can refresh raw URLs, insert source links, and apply held details wholesale (core.py:315–378). It must not be used as an unverified cancellation side channel
- events filters upcoming and calendar/range by stored status (core.py:436–546). Adding a warning after filtering is insufficient: selection, totals, calendar, and other consumers must consult safety eligibility before producing results

Line anchors refer to the exact inherited blobs and are supplied as evidence for the implementation gaps, not as an implementation patch. All URLs and HTML in the added cases are original synthetic fixtures, never fetched. Semantic classes such as main-event and event-status are fixture roles, not verified publisher selectors.

## 2. Positive admission remains fail-closed

No new provisional alias enters raw_items, events, or event_sources. All newly returned items need a current evidence-derived canonical identity, either from a bounded verified detail observation or from an unexpired, noncontradicted verified mapping. The admission gate must execute before collect_report returns items to the existing worker.

A successful identity verdict requires all of the following:

1. A complete, bounded response/redirect trace; each redirect origin and numeric event/live route is validated before following it. An unsafe intermediate hop invalidates the trace even when the final origin is acceptable
2. A recognized main-event content region with explicit event semantics, not a navigation page, challenge, generic template, replay/download advertisement, sidebar recommendation, or head metadata alone
3. A main-event heading consistent with the listing title under conservative whitespace/Unicode normalization; no fuzzy title-only merge
4. At least one discriminating non-title event anchor shared with the list or independently retained verified occurrence, such as the actual meeting date fragment or organizer plus a specific agenda/session discriminator. Attendance=online or the numeric route ID alone is not discriminating evidence
5. No unresolved contradictions in event-specific anchors. A changed date or organizer is not proof of a different event: fail positive admission into review until explicit reschedule/edition evidence disambiguates it. Never silently merge same-title editions

A bare boolean identity_verified, canonical tag, equal numeric ID, same-origin URL, HTTP200, or matching title cannot replace the evidence bundle. Cache TTL grants no authority against an observed contradiction: a newly fetched unrelated body or invalid trace invalidates positive reuse for that candidate immediately, while historical evidence remains intact. An ordinary timeout says identity is unavailable, not that an unrelated event was proven.

Case 37 now contains a real response/body and matching main heading and yearless meeting fragment. The fragment can corroborate identity but cannot establish a year or scheduled time. It remains an undated review-only admission with the original short summary and detail_candidate gate sequencing. Inherited positive cases are partial semantic assertions, not exemptions from these evidence obligations.

### Counter semantics

A semantic identity rejection after HTTP200 counts one attempted detail and one failed detail, zero resolved, zero success cache, zero admitted. Ordinary failure, in-flight Deadline, unattempted deferred work, and redirect-hop counting retain v2 semantics. Coverage stays partial/single_page with source_total=null. Pending diagnostics are not event rows. Cases 41–46 and 59 carry explicit row and request counts.

## 3. Positive mapping authority and historical association are different

Maintain immutable last-verified association evidence separately from the latest cache attempt. A cache row overwritten as failed cannot destroy the historical binding, and a failed-only row with no verified history cannot create one.

A historical binding records source_id, precisely normalized alias URL, canonical URL, stored event ID, occurrence/edition when known, validation evidence, and binding ID. Expiration removes positive admission authority; it does not erase this association. Never infer an association from equal numeric IDs, title similarity, another source's URL, or a transitive alias graph. Exact canonical event_sources linkage is also a direct historical association. Do not mutate/rekey canonical rows or add duplicate alias event_sources to preserve history.

## 4. Cancellation when current identity cannot be refreshed

V2's no-admission/no-update rule must not leave a previously scheduled event eligible after a current event-specific cancellation is observed. V3 adds a separate safety-only transition channel; it does not relax positive admission.

Required current cancellation observation:

- Current successful bounded inventory retrieval with recognized event-card structure
- Cancellation text scoped to this exact card and alias, expressly applying to the current whole event/occurrence
- Raw bounded evidence, content digest, source/card/alias identifiers, observation time, and any explicit publisher update/edition evidence
- Negations, historical quotations, a different session's cancellation, sidebar text, and postponement alone do not meet this cancellation predicate. Postponement needs its own date/review policy and must not be mislabeled cancellation

Use the observation to locate directly recorded historical targets, even if their mapping TTL has expired. Create an idempotent durable eligibility guard for each exact historical target requiring review. This is an uncertain cancellation-related veto, not verified identity or authoritative cancelled status. No normal ingest call occurs, items=[], admitted=0, changed=0 for event content. Record guard writes/eligibility changes separately. Persisted event status can remain scheduled while effective eligibility is needs_review.

The guard preserves canonical event/raw/source IDs and URLs, row counts, dates/content, favorite/hidden/feedback/viewed state/revision, manual review_hold/review_notes/address fields, and all alias history. A guard must not set favorite=0, hidden=1, delete anything, rewrite aliases, or manufacture a successful identity cache.

### Target ambiguity

- One direct target: suppress its planning eligibility pending identity/status adjudication
- Multiple explicitly recorded direct targets from alias reuse: suppress only that finite historical candidate set as uncertain. Never merge them or mark all authoritatively cancelled. Surface ambiguity and retain independent per-target guards
- No historical target or failed-only cache: retain an unlinked pending observation and diagnostic; admit no new item, assign no target, and do not suppress unrelated records. This cannot guarantee the unknown cancellation was matched; report that limit
- Expiry/timeout alone, without qualifying cancellation and without an existing guard, preserves previously stored event eligibility. It does not invent cancellation

## 5. Durable visibility and access behavior

Add a safety write path separate from returned admitted items. It must persist observations and guards transactionally and idempotently before declaring the cancellation handled. A suppression-write failure must be reported as a failed safety update, never as handled; serving paths must fail closed for affected unresolved records rather than quietly reuse a known-unsafe scheduled result. Persistence/query failure behavior needs integration/fault-injection validation before release; this pack does not test it.

Effective planning eligibility is: existing normal criteria AND no unresolved applicable guard AND no manual hold/conflict/authoritative cancellation. Apply this before filtering, counting, pagination, facets, calendar/range, upcoming API/feed/export/planning surfaces, and any existing upcoming notification consumer. Invalidate their cached eligible result and recheck immediately before dispatch. A UI-only warning or an in-memory guard is insufficient. This contract does not create a notification feature.

Saved/history/point-record access remains available under normal access rules, displaying the warning “来源显示已取消，当前活动身份待核验” when applicable. A favorite is retained and inspectable; it does not override the eligibility veto. The same read snapshot must bind event data, historical alias targeting, and active guards so one surface cannot leak a stale scheduled view. Case 55 requires persistence across restart. These are requirements, not tested implementation facts.

## 6. Resolution, replay and concurrency

Guards do not auto-expire and are not cleared by cache TTL, absent cards, empty inventory, timeouts, a generic 报名中 listing, a newly observed timestamp alone, or unrelated detail content.

A guard can be resolved through either:

- Current bounded, identity-verified explicit reinstatement/retraction for the same occurrence that demonstrably addresses its cancellation evidence; or
- Verified disassociation or reviewed authorized adjudication that the cancellation does not concern that stored target. This recovery is necessary for reused aliases/false historical matches; an unrelated old event cannot be expected to publish a reinstatement

Retain the observation, association, guard and resolution audit. Resolution is scoped to named evidence/guard/target IDs using compare-and-set/version semantics. It cannot clear independent holds, conflicts, other-source cancellations or an unseen concurrently added guard. Effective status is recomputed after all remaining reasons; case 53 retains an independent manual hold, case 54 can regain eligibility.

Observation time is not publisher chronology. Reprocessing the same immutable captured observation ID after it was resolved is an idempotent replay, not a new veto. A new network capture with identical bytes is different: the publisher may have cancelled again using the same words. After reinstatement, treat that new capture as ambiguous and retain review-only suppression unless publisher revision/generation evidence establishes it is the already-resolved notice. Stable content hashes alone cannot establish that generation. Deduplicate processing of the same captured observation and retain an active per-target guard without duplicating it for repeated unresolved evidence. Materially distinct or chronology-ambiguous contradictory evidence must not be silently discarded. Cases 61–62 and 64 cover captured-observation replay, concurrent resolution, and identical-new-fetch ambiguity. A synthetic manual-adjudication input is not a real executed decision or authorization.

## 7. Required implementation changes

R1–R6 from v2 remain requirements: verified admission, explicit identity/cache/deduplication, evidence-aware time refinement, status authority/manual-hold preservation, empty versus excluded inventory, per-hop redirect validation. They are not implemented here.

- R2 is strengthened: derive identity verdict from scoped body evidence, invalidate positive cache reuse on current contradiction, retain immutable historical bindings separately
- R7: add durable observation/guard processing independent of ingestion; use exact direct historical targets, support no-target/ambiguous-target diagnostics, idempotence and failure reporting
- R8: join/project effective safety state consistently across planning reads, counts/caches/dispatch and retained saved-record access; implement evidence-scoped reinstatement/disassociation with replay and concurrency protection

The pack validates JSON/types/references, evidence text/counters/immutable snapshots, source blob provenance, and checksums offline. It imports no application code and executes no adapter, worker, database, query, restart, concurrency, redirect, or live DOM tests. No publisher requests, repository changes, production actions, credentials, remote commands, or GUI work were performed.
