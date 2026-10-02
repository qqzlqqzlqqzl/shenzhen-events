# EEFocus publisher selector validation

Target: qqzlqqzlqqzl/shenzhen-events PR #86, commit 4a7003d6774aa387791b676a1e21dd7aaa7ccfbc.

Result: FAIL the live-publisher validation gate. Keep the source unregistered. The adapter cannot parse the current inventory root, and its detail identity container does not exist on the checked same-origin final page. These are observed raw-HTML mismatches, not merely browser rendering differences. No repository changes, source activation, production collection, login, registration, or form submission were performed.

## Capture scope and method

Read the exact-commit adapter through the GitHub connector. Inspected three public navigation outcomes in dot's cloud browser before ending browser inspection. Separately made six bounded raw-HTTP GETs (12-second timeout, 1,000,000-byte ceiling plus one overflow-detection byte, automatic redirects disabled except the initial inventory request whose final URL was unchanged). Raw same-origin detail hops were explicitly requested only after their Location header was observed. Foreign raw redirect destinations were not followed. No adapter/production collector execution.

The web tool's inventory was labeled crawled two weeks earlier and differed from the current browser/raw inventory; it was not used as current structural evidence.

## Evidence matrix

| Check | Result | Evidence / impact |
|---|---|---|
| Inventory host/route | PASS | https://www.eefocus.com/event/ returned HTTP 200, 147,231 bytes; raw request started 2026-10-02T10:14:41.243974Z |
| Inventory root selector | FAIL | Raw HTML and rendered DOM contain `div.special-list > ul.section-list-item-ul`, 20 direct `li.section-special-item`; zero `main` tags. Adapter requires `main.special-list > ul.section-list-item-ul`, so it would raise `inventory_structure_drift` |
| Card-local title/summary/tag/time roles | PASS, partial | `a.item-title`, `.item-intro`, `.post-tag`, `.event-time` exist in scoped cards. Raw inventory: 20 time nodes, 20 tags, 15 `.event-location`, zero `.event-organizer`, `.event-status`, or `.status` |
| List meeting date format | FAIL | Actual strings use `时间：2026/09/20~10/22` and `时间：2026/09/23 14:00~16:30`; adapter date parsing/corroboration requires Chinese 年/月/日. The first range begins before the actual October 22 meeting and must not become event duration |
| Attendance/location interpretation | FAIL/needs explicit policy | GMSL card's tag is `直播`, location `地点：线上活动`; current adapter derives attendance only from 线上/线下 in tags. Arduino card has `线下活动` tag but `地点：线上活动`, an actual contradiction. `.event-location` also contains company names on some cards; it is not uniformly a venue |
| Dated Shenzhen card | PASS for rejecting unsupported redirect; not admitted | https://www.eefocus.com/event/2091127.html returned 302 to https://jsj.top/f/mKLfr9?x_field_1=HD at 10:16:44.099480Z. Prior browser navigation verified that final URL; visible form described October 22 09:00–17:30 and Shenzhen venue. This is foreign-origin content, outside the adapter allowlist; no form interaction |
| Event-to-live transport alias | PASS for observed chain only | https://www.eefocus.com/event/2093134.html returned 302 to https://www.eefocus.com/live/2072182.html at 10:16:49.984835Z; the explicit final GET returned 200 at 10:17:31.818963Z. Browser independently landed on the same final URL. Equal numeric IDs are not required, and this chain alone is not admission authority |
| Final live identity/body selector | FAIL | Final raw HTML and rendered DOM have zero `main` and zero `article`; the adapter's `main article.main-event,body > article` matches nothing. Actual heading is `div.section-medium > div.details-section-title > h1.title`, matching the list title. Body is `div.article-content` with `.live-template-box` sections |
| Final live non-title anchors | UNVERIFIABLE for positive admission | No `活动时间:`, `直播时间:`, or `举办时间:` labeled paragraph was present. Sponsor material is a `div.live-template-title` labeled 主办方 plus `.live-template-sponsor-v` blocks, not adapter-style labeled paragraphs. Publication time is not event time. Do not replace non-title corroboration with title/redirect equality |
| Replay status | FAIL current selector contract, positive replay evidence observed | Final main action is `div.video-part.live ... div.section-action > div.action-right > a.sign-btn.appt-button-trigger`, text `看回放`, data-href ending `/live/2072182/watch`. Related-live sidebar also contains replay labels, so status must stay scoped to this main action. The listing itself had no status node |
| Clocked dated event | FAIL for raw-detail identity; rendered state unverified | https://www.eefocus.com/event/2082468.html returned 200 at 10:16:55.723597Z, 12,819 bytes, generic site title, empty `<div id="app"></div>` and `<div id="modal-form-container"></div>`, no h1/main/article/event time. Browser rendering was not inspected after browser inspection ended. This shell is not proof of cancellation, registration closure, or a bot block |
| Older dated listing | PASS for rejecting unsupported redirect; not admitted | https://www.eefocus.com/event/2070311.html returned 302 to https://jsj.top/f/Rj4Nv3?x_field_1=HD at 10:17:00.982803Z. Foreign target not followed in raw validation. Listing still says 查看详情; a past date does not establish registration closure |
| Cancelled / registration-closed / reinstated states | UNVERIFIABLE | No authoritative current example in the bounded inventory/detail sample. A focused public search returned no result. Do not claim these synthetic roles have live validation |
| Recognized empty state | UNVERIFIABLE | Inventory is nonempty; no `[data-fixture-empty-state="true"]`. No current empty publisher contract established |

## Required corrections before a fresh validation

1. Replace the synthetic root with an observed narrowly scoped inventory structure; capture exact publisher snapshots with provenance. This is an inventory failure now, so changing only details is insufficient.
2. Treat list date ranges as promotion/discovery evidence unless an independently established meeting field says otherwise. Add actual slash-format dates without converting every range into event duration. Do not infer timezone or exact meeting time from publication metadata.
3. Establish actual scoped live heading/body/status roles, excluding related-live/sidebar content. Preserve the strong requirement for a non-title identity anchor; the checked replay cannot establish a positive upcoming-event contract.
4. Explicitly handle `直播`, conflicting tag/location evidence, and company-vs-location labels. Do not treat `查看详情` as closed/cancelled or `立即参与` as evidence that a meeting is scheduled.
5. Keep external form destinations outside the current allowlist and retain unresolved JS-shell details as unverified. Do not turn shell HTML into a successful empty page.
6. Obtain real cancelled, registration-closed, empty, and active same-origin dated samples before claiming those selectors validated. Durable cancellation guards remain a separate gate handled by the other reviewer.

## Raw artifact integrity

- inventory.html: SHA256 7723f5ff44c0a0c0a64be0096d5f28ee69aa14884781a7eb13741df81992a801
- dated.html (302 body): 1b4d9950b88002c735aaa8fdfa37edaf70a918b2a3fd181692d191a71b226aec
- alias.html (302 body): 890bee5adcde9746105ba3803a7f425c43646e99d296a36a615aa9717622bfd5
- live_final.html: d09dfab77c0f3ece5c29ceed026eb1a4142f3619fd54fbf5082dee51946ec551
- clocked.html: bfc1ff475dffdc29d04ef0e89de324af111dd498421576286e8e9c4c00b38270
- old_dated.html (302 body): 31b5ea135a7cd80d1bf32864bafe3013ea02a76370141263cefc12679c016816

This package contains sanitized fixtures, not original response bytes. `response-metadata.json` contains selected observed status/header fields; `structural-evidence.json` contains parsed structure; `capture-to-fixture-manifest.json` separately identifies original capture and sanitized fixture hashes. `sanitization-validation.json` confirms the critical structural/text signatures are unchanged. No original publisher scripts, credentials, or raw session fields are included.
