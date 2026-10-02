# EEFocus durable cancellation guard (draft, unregistered)

Refs #85. This separate slice starts at admission PR #86 head
`fed9109e93bb5c7272f1db6edf672747a7e40033`. It implements the reviewed Library
handoff `libfile_4463785e080881918317494e85a2d477`, version 1,
`Events_Durable_Cancellation_Guard_Handoff_4a7003d.zip`, 122150 bytes, SHA-256
`8ebe2dddbdda108a9969aa42d9129d64400bc4b4556624565d4b2b10bf5a2019`.
The current Library helper materialized the archive locally and its version,
size, hash and safe extraction were verified. The older source copies in that
archive are reference evidence; the implementation retains #86's reviewed fixes.

## Capture and authority

Before inventory I/O, a short `BEGIN IMMEDIATE` transaction commits a capacity
reservation and availability fence. A separate CAS issues start permission to
one owner. Exactly retained response bytes and transport provenance move the
capture to `captured`. Parsing those bytes commits observations, direct targets,
guards, target dispositions and the final receipt in one transaction. Only after
that commit can optional details and ordinary admission execute. Every worker
EEFocus result requires the receipt; an unverified listing creates no event.

Current whole-event cancellation labels are recognized only inside inventory
cards. Negation, quotation, sidebar notices, closed registration, postponement
and session cancellation supply no cancellation authority. A recognized notice
may independently suppress immutable same-source, exact-alias historical targets
even when its detail fails. Title, numeric similarity, failed cache entries and
transitive alias graphs supply no targets. Ambiguous direct historical targets
all receive conservative guards; canonical status, favorites and holds survive.

Lost acquisition outcomes remain `recovery_required`. A fresh empty listing,
timeout retry or caller boolean cannot clear that uncertainty. Caught terminal
acquisition failure without an accepted response records its bounded proof and
actual request count. Failure while retaining or finalizing keeps the last
committed fence; no truncated successful receipt is written. Optional-detail
failure after finalization preserves the finalized receipt and guard writes.
If a run aborts before returning its measurements, current-run counters are
explicitly unavailable (`null`), with bounded last-good measurements separate.
Completed ingests and committed safety counters remain independently reported.

Schema version 1 is additive and transactional. Only consistent existing
non-NULL bindings acquire anchors during migration. Exact admitted binding IDs
anchor atomically with event/raw/source ingestion; pending observation/target
pairs reconcile before the new event can become eligible. Unknown applicability
rolls back admission. Ordinary replay returns the original receipt, discovers no
new targets and cannot reopen resolved dispositions. New captures have new IDs;
identical bytes after resolution conservatively establish a new generation.

Cancellation date evidence retains its role and original text. Only one explicit,
fully dated actual-occurrence field can prove a different occurrence. Promotion,
registration, publication and publisher discovery windows, ambiguous ranges and
legacy untyped date arrays remain unknown and cannot dismiss a pending notice.
The late-anchor transaction reparses retained role evidence and rolls back the
whole admission if applicability cannot be established.

Admission also rereads immutable bindings and current canonical history under
the ingestion writer lock, before changing raw, canonical or source records.
A delayed already-verified older occurrence cannot undo a committed forward
reschedule. This protects alternate/adversarial writers; the normal CLI collector
already serializes ordinary collectors with its process flock.

## Projection and resolution

Planning reads, counts, facets, source hydration and guard projection share one
SQLite snapshot. Responses expose stored status, effective status, eligibility,
guard warnings and a safety epoch. Pagination rejects an epoch change. Planning
reads fail with typed 503 when capture availability is unknown; saved/history and
point reads retain warning-bearing records. Guards, manual holds and conflicting
time/attendance evidence prevent planning. ICS accepts only projected eligible
scheduled records, including single-event exports; canonical UID stays stable.

The browser revalidates detail, comparison and export actions. Cached/copied
records and snapshots become pending after refresh, failure, offline or visibility
changes. Ordinary network failure permits visibly disabled historical content;
typed safety failure discards actionable snapshots. Personal writes update only
personal fields and cannot overwrite safety metadata. API projection remains the
authority even if client state is stale.

Connectivity and visibility transitions advance a lifecycle generation and
abort in-flight work. Responses are checked before dispatch, after headers and
after body decoding, so a pre-offline response cannot restore planning or export
controls after reconnect, even if transport ignores abort. Fresh foreground point
verification can restore them. This is a client presentation/action boundary;
server ICS independently enforces projected eligibility.

Fresh detail-only reinstatement uses bounded same-origin transport and parser
evidence for the exact canonical occurrence, dates and clocks. Network work runs
outside writer transactions. Final `BEGIN IMMEDIATE` rereads source/canonical
authority and CASes only named guard revisions and evidence digests. An independent
new guard remains active; a new member of the named guard invalidates its CAS.
Operation retries return the original audited result without another fetch.
No public `reinstated=true` endpoint exists.

Human disassociation is separately recorded as `authorized_reviewed_adjudication`,
not inferred automatically from a reused alias's other occurrence. The existing
authenticated maintainer session supplies the actor. The request must address
exact retained observation IDs, named guard expectations, an immutable direct
same-alias different-occurrence evidence anchor and a substantive review reason.
Fixture actor strings confer no authority. The audit retains those references,
the reason and actor; CAS resolves only the named target and retains other guards.
This API is an explicit human decision facility, not a publisher truth oracle.

Recovery supports reserved-owner revocation before start permission, exact retained
capture replay and explicit unresolved hold. A lost response with no durable
terminal proof has no waiver route. Recovery IDs are idempotent and revision-bound.
Replay stays routable when new collection is capacity-paused. Referenced records,
evidence and audit are retained past ordinary cache/run retention. Alias merges
touching safety history defer with a bounded diagnostic until an audited merge
contract exists. No automatic TTL or evidence deletion frees space.

AI takes an authority snapshot before paid dispatch and skips guarded/held records.
After model work, the writer lock precedes rereading raw hash, canonical fields,
source links, immutable anchor proofs and epoch. Stale proposals cannot apply any
part of the update. Type backfill uses the same check. Tests stub models; no paid
model calls were made.

## Declared bounds and measured evidence

`safety_limits` configuration can tighten the supported work/account bounds or
increase recovery headroom. It cannot expand beyond the calibrated maximum:

| Bound | Value |
| --- | ---: |
| Retained inventory | 1,000,000 bytes |
| Recognized cards / observations | 256 |
| Each card/body excerpt | 65,536 bytes |
| Total card excerpts | 1,000,000 bytes |
| Observation metadata / ledger row metadata | 4,096 bytes |
| Direct evidence edges and each target ledger | 2,048 per capture |
| Newly anchored bindings | 24 per admission |
| Retained target payload | 1,000,000 bytes |
| Late-anchor reservation ceiling | 192 MiB |
| Outstanding captures | 1 globally (therefore at most 1 per source) |
| Operational account / recovery headroom | 256 MiB / 16 MiB |
| Resolution proof / named guards | 2,000,000 bytes / 16 |

The capture reservation is **182,063,616 bytes**:
`4 * (2,000,000 + 256*4096 + 5*2048*4096) + 2 MiB`. The factor covers encoded
ledgers, indexes/pages, WAL/checkpoint and staging. Accounting includes operational
data files, allocated SQLite pages, WAL peak and outstanding reservations; available
filesystem space is checked too. Late anchoring calculates its prospective missing
pair cost under the writer lock. Optional detail and resolution evidence have
separate bounded reservations. Overruns retain captured bytes and the fence;
pre-acquisition capacity pause makes no HTTP request and emits a bounded diagnostic
when storage permits. Guard resolution metadata must also fit the row bound.

The maximum-bound harness exercises 256 cards and 2,048 targets with a 784,090-byte
inventory. Measured committed database growth is approximately **6.54 MB**, well
inside the 182.06 MB reservation; exact before/after sizes are regenerated in
`artifacts/safety-capacity/measurement.json`. This is measured application admission
headroom, not a physical ENOSPC guarantee. Real SQLite FULL, read-only, locked and
commit failures are tested and retain the last durable state. External writers or
storage loss can still exhaust physical space and require intervention.

## Acceptance and operational boundary

`tests/test_eefocus_safety.py` executes the remaining 17 reviewed cases 47–64,
excluding admission case 59, through real collection/persistence/API seams. It
also covers migration, restart, write/commit fault injection, exact replay,
late anchoring, two-connection races, AI authority, retention, capacity and ICS.
The original cases 01–46 and 59 continue through the real adapter and worker.
`tests/eefocus_safety_browser.py` covers actual isolated worker/API/browser flows;
the full existing Python, DOM, syntax and desktop/mobile browser checks are required.

The independent three-gap review bundle was materialized with the current Library
helper and verified as `libfile_c2de94af93448191aa7e40091fd6715b`, version 0,
455345 bytes, SHA-256
`57acc82700899cd0e01a4444b611ab7781a13b31b960749c085c653169834f11`.
`tests/test_eefocus_review_gaps.py` exercises typed unknown and explicit-occurrence
controls through collection, ingestion and API, legacy retained evidence, and
delayed alternate writers with and without a guard. DOM checks cover delayed
detail/list/calendar/comparison/export responses and fresh reconnect recovery;
the isolated real API/browser flow also delays a response across an offline event.

Independent implementation acceptance is still required; design approval is not
implementation approval. Publisher evidence still lacks a passing upcoming-event
detail, app rendering and cancellation/reinstatement/recognized-empty integration.
Synthetic contracts cannot satisfy that gate. `sources.json` remains unchanged.

Before any eventual operational rollout, stop and retire older writers/readers
that do not enforce this schema and eligibility contract, then migrate and verify
the new reader/worker pair together. New readers fail closed on absent or future
safety schema; old binaries cannot be made safe by additive tables alone. That
operational rollout has not been performed. This work uses isolated temporary
databases and test servers only; no production DB/auth, deployment, merge, source
registration or issue closure is authorized or performed.
