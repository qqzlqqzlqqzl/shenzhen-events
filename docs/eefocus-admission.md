# EEFocus admission adapter (draft, unregistered)

Refs #85. Base: `986ab1557e3bcd0eb60311d06cfb01950ab75814`.

`eefocus_events` now executes inventory parsing and identity verification before
`collect_report` returns items to the worker. Unresolved candidates appear only
in coverage diagnostics; they create no raw, event or source-link rows. The
generic enrichment path is unchanged for existing sources.

Only the bounded HTTPS `www.eefocus.com/event/` inventory and numeric
`/event/<id>.html` or `/live/<id>.html` details are supported. Redirects are
validated before following each hop, with existing public-address checks,
byte limits and a hard Linux deadline. A complete trace, scoped main heading,
explicit event semantics, a shared non-title anchor and no conflicting anchors
are required. Canonical tags, matching numeric IDs and caller booleans confer
no admission authority. Navigation, sidebar and challenge content is excluded.

Promotion windows never establish event duration. Actual meeting evidence can
resolve missing time; attendance uncertainty, clock conflicts, manual holds
and cancellation still win. Online clocks need an explicit timezone; an
unconfirmed clock remains a display-only date. Cancelled undated EEFocus items
retain cancellation through normalization. Fresh verified cancellation retains
favorites and held notes/address metadata. A generic open notice cannot revive
a cancelled stored record; explicit same-event reinstatement is required. Every
scoped status label must unambiguously state whole-event reinstatement; negated,
quoted, tentative, session-specific or conflicting labels cannot authorize it.
The captured `div.special-list` inventory is supported alongside the reviewed
synthetic `main.special-list` contract. Full slash dates are parsed without
changing their retained text. Captured inventory ranges remain discovery
windows with no scheduled span. `直播` and explicit online location text provide
attendance evidence; conflicting offline tags stay unknown/review. Company
labels are retained as evidence and do not become venues or organizer anchors.

The existing detail cache stores only adapter-derived evidence and canonical
payloads as successful entries. Timestamp-only changes do not invalidate the
fingerprint. Expired, failed, legacy boolean-only or contradicted mappings
cannot admit candidates. `refresh_identity=true` requests a fresh bounded
verification rather than cache reuse. Contradictory canonical bodies invalidate
positive cache reuse while append-only `eefocus_identity_bindings` retains
direct alias/canonical evidence and its stored event ID. Equal titles do not
merge separate EEFocus routes. Changed historical occurrences, organizers and
canonical routes require disambiguation rather than silent overwrites.
Checks cover the requested alias, directly fetched canonical self-binding and
exact persisted canonical occurrence before admission, binding or cache reuse.
A new alias cannot overwrite a known occurrence without a reschedule notice
containing both full old and new dates. Every reschedule notice must affirm the
whole-event move; quoted, negated, session-specific or conflicting notices
confer no authority. Old alias caches cannot roll back an
explicitly verified reschedule. Positive cache schema is now
`eefocus_identity_v2`; previous admission-rule evidence requires fresh fetching.

Deduplication occurs after identity resolution and before ingestion. A verified
event→live redirect also retains the directly fetched canonical self-mapping;
aliases do not create additional `event_sources` rows. The detail queue prefers
previously unattempted/older candidates and is capped at 12 per run.

Counter definitions:

- `visible` counts scoped cards, including explicit exclusions; `extracted`
  counts parser candidates. `unique` retains pending candidate identities and
  reconciles aliases actually proven equal. `admitted` counts returned items.
- `requests_attempted` preserves the existing logical bounded-fetch definition;
  `http_requests_attempted` separately counts actual HTTP hop attempts.
- Semantic rejection counts attempted=1, failed=1, resolved=0. An in-flight
  hard deadline is attempted but neither resolved nor ordinary failed.
  Unstarted work is deferred, and no success cache is written for interruption.
- Empty and all-excluded inventories remain distinct. Coverage is always
  partial/single_page, source_total=null, with no inferred pagination or deletion.

## Verification boundary

The reviewed bundle is Library `libfile_6045f94e48b481918c2c58f04fce3c9a`, version 0,
`eefocus-fixtures-20261002-v3.zip`, 148620 bytes, SHA-256
`68ee2472e63d80623b6e23c8f03a8073a577f5da87afe8a61e81de0b10b3f706`.
It was materialized using the current Library helper in Linux, retaining Library
metadata, and verified locally. `tests/fixtures/eefocus` preserves the expanded
reviewed bytes; the test suite verifies its checksum manifest.

`tests/test_eefocus.py` executes cases 01–46 and 59, with network stubs below
`requests.Session.get` so the real per-hop transport, parser, report, worker,
isolated SQLite and authenticated local API execute. Parser-only expectations
are also checked before collection; unverified parser outputs still never reach
the worker. Legacy patch/payload-only cases use explicit generated semantic
HTML to exercise real identity parsing rather than trust their proposed flags.
Stateful cases seed real favorites and holds. Additional regressions cover real
fresh-cache contradiction, retained immutable history, inventory failures,
historical anchor changes, title-only dedup prevention and status authority.
Independent-review regressions cover negated/ambiguous reinstatement, new-alias
year/organizer reuse against canonical and persisted history, valid alias and
reschedule controls, and previous-schema/stale-alias cache rejection. These are
admission fixes; the deferred durable cancellation channel remains separate.

The second evidence bundle is Library
`libfile_adf2ca70a220819196f33d6af41d17af`, version 0,
`eefocus-live-selector-evidence-20261002-sanitized.zip`, 63557 bytes, SHA-256
`acb7c4b94fd3a2ad00024f9a0b7a8adde798ea1a726d2efba9477b8e500d6308`.
It was independently materialized with the current Library helper and verified.
`tests/fixtures/eefocus-live` preserves all twelve checksummed payload files and
six captured-response structural signatures. Original response hashes and
sanitized fixture hashes are separately recorded; sanitized bytes are not
claimed identical to original publisher responses.

Offline tests now replay observed inventory, response status/Location metadata
and sanitized detail captures through the real adapter/report/worker/SQLite/API.
The observed live scope is `div.section-body > div.section-medium`, with direct
`div.details-section-title > h1.title` and `div.article-content`; publication
metadata and related/sidebar content supply no meeting or identity authority.
The main action is scoped separately under `div.video-part.live >
div.section-left > div.section-action > div.action-right >
a.sign-btn.appt-button-trigger`. Explicit `看回放` rejects the captured replay;
the sidebar's replay labels cannot establish that state. The actual app shell
remains unverified, and both observed foreign form redirects are rejected
before fetching the foreign hop. Removing the captured main replay action in an
adversarial test still cannot admit the page without a non-title event anchor.

This verifies bounded captured inventory and negative detail structures,
**not a passing live upcoming-event integration**. Active same-origin dated
detail, actual app rendering, cancellation, registration closure, reinstatement
and recognized-empty contracts remain unverified. An empty observed inventory
is an error even with a synthetic empty marker. Synthetic semantic/empty
roles cannot fill those evidence gaps. Tests use offline replay only; the
executor made no publisher request. `sources.json` stays unchanged.

## Required separate follow-up before registration

Durable safety-only cancellation observations and eligibility guards from
cases 47–64 (apart from case 59's identity contradiction) are not implemented
or claimed tested. In particular, an unverified cancelled listing cannot yet
suppress an existing historical target through a durable independent channel.
The follow-up must cover restart, query/count/calendar consistency, unresolved
and ambiguous targets, persistence failure, evidence-scoped resolution, replay
and concurrency, while retaining favorites, holds and alias history.

Keep this PR in draft and leave the source unregistered until that follow-up and
the remaining publisher state/positive-detail validation are complete. No
deployment, production DB/auth access, paid model call, merge or issue closure
is part of this implementation.
