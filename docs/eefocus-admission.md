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
a cancelled stored record; explicit same-event reinstatement is required.

The existing detail cache stores only adapter-derived evidence and canonical
payloads as successful entries. Timestamp-only changes do not invalidate the
fingerprint. Expired, failed, legacy boolean-only or contradicted mappings
cannot admit candidates. `refresh_identity=true` requests a fresh bounded
verification rather than cache reuse. Contradictory canonical bodies invalidate
positive cache reuse while append-only `eefocus_identity_bindings` retains
direct alias/canonical evidence and its stored event ID. Equal titles do not
merge separate EEFocus routes. Changed historical occurrences, organizers and
canonical routes require disambiguation rather than silent overwrites.

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

This is functional synthetic acceptance, **not live publisher DOM validation**.
Semantic detail and empty selectors are reviewed fixture roles, not observed
publisher selectors. No EEFocus publisher request or production source
registration occurs in this PR. `sources.json` stays unchanged.

## Required separate follow-up before registration

Durable safety-only cancellation observations and eligibility guards from
cases 47–64 (apart from case 59's identity contradiction) are not implemented
or claimed tested. In particular, an unverified cancelled listing cannot yet
suppress an existing historical target through a durable independent channel.
The follow-up must cover restart, query/count/calendar consistency, unresolved
and ambiguous targets, persistence failure, evidence-scoped resolution, replay
and concurrency, while retaining favorites, holds and alias history.

Keep this PR in draft and leave the source unregistered until that follow-up and
publisher selector validation are complete. No deployment, production DB/auth
access, paid model call, merge or issue closure is part of this implementation.
