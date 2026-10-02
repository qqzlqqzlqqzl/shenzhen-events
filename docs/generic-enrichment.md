# Generic enrichment observations

Admission comes from a standalone Lianpu fee span or explicit JSON-LD offers, never a free-gift title. JSON-LD accepts attendance modes, organizer arrays, accessibility flags, AggregateOffer bounds and nested/multiple offers. Mixed free and paid offers retain paid evidence regardless of order and normalize to `cost_free=false`.

Detail extraction supports labels split by inline markup, including fragmented value text. Merge fills missing fields, retains current inventory fee/location/dates/status, preserves review holds and known attendance modes, and retains sibling structured metadata. Newly accepted dates carry their precision into storage, ICS and calendar output; explicit structured attendance can replace an unknown listing default. An explicit organizer replaces a publisher-valued organizer while retaining the publisher's attribution. Compare uses the existing fee and organizer-label helpers and omits unknown fee rows.

The generic detail-cache payload is `{kind: "detail_observation", version: 1, structured: {...}, metadata: {...}}`. It contains detail observations rather than the merged inventory event. Every hit remerges against the current inventory. Legacy whole-event payloads, unsupported versions and malformed envelopes, nested detail containers or provenance evidence miss safely and are refreshed within the existing queue and budget. This changes no database schema, identity, stored user state or recurring-source cache contract.

Regressions: `tests/test_generic_enrichment.py`, `tests/generic_enrichment_dom.cjs`, and existing source-fields, coverage and recurring-source tests. Full local suite logs are retained separately for the independent review. No source registration, production write, migration, backfill or deployment is part of this change.

Refs: #87. Related scope ownership: #85.
