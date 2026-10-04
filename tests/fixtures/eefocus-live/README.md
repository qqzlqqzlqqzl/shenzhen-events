# EEFocus current publisher evidence, 2026-10-02

Source review: https://github.com/qqzlqqzlqqzl/shenzhen-events/pull/86
Exact reviewed commit: 4a7003d6774aa387791b676a1e21dd7aaa7ccfbc

This is a read-only public-publisher evidence package. It is not source activation, positive identity admission, or a passing live integration test. The adapter was inspected, not run against the publisher.

## Original captures versus sanitized fixtures

Only sanitized HTML is included. Each fixture is derived from the corresponding bounded actual HTTP capture. No event text, selector role, identity wrapper, empty-state marker, date, or status was invented. Script/style/noscript/iframe/object/embed contents, link/meta/base elements, comments, network-loading attributes, event handlers, and unrelated dynamic attributes were removed. Remaining tags/attributes were serialized by Python HTMLParser. Retained attributes are class, id, href, data-href, data-post-id, title, alt, role, aria-label, lang, dir, colspan, rowspan, datetime, and charset. Unsafe javascript/data URL attributes are removed. The absence of script bodies means these files are offline structural fixtures; they cannot validate browser execution.

Original byte length/SHA256 and sanitized byte length/SHA256 are separate fields in capture-to-fixture-manifest.json. Never call a sanitized fixture byte-identical to the publisher response. SHA256SUMS.txt covers every payload file except itself. No scripts, credentials, cookie/authorization headers, or session values are included.

## Verified and unverified states

- Inventory is nonempty, 20 cards. Actual root is div.special-list, not main.special-list.
- GMSL event alias 2093134 returned 302 to live 2072182, which returned 200. Main action explicitly says 看回放. This confirms replay evidence, not upcoming-event eligibility. Body has no adapter-style main/article identity wrapper.
- Event 2082468 is a 200 app shell with empty div#app, no h1 or event timing in fetched HTML. Its browser-rendered state was not examined. This is neither a validated empty inventory nor proof of cancellation/registration closure/bot blocking.
- Event 2091127 and older event 2070311 redirect outside the allowed EEFocus origin. Do not widen the allowlist to admit those forms based on this package. Only the first was previously observed as a read-only browser-rendered public form; that foreign body is not packaged.
- Real cancellation, registration-closed, reinstatement, active same-origin dated detail, and recognized-empty state contracts remain unverified. Synthetic fixtures cannot fill those gaps.

## Windows consumption

Materialize this exact Library ZIP into the consuming Windows task via the current Library skill. Confirm ZIP SHA256 supplied by the parent before extraction, then validate every SHA256SUMS.txt entry. Use these as observed, sanitized negative/structural fixtures; do not run a production collector or register the source. Preserve existing identity, replay, cancellation, and external-origin safety boundaries.
