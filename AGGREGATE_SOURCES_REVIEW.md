# Reusable discovery and user-flow review

User priority: multi-event aggregator / public-account coverage, not one-event sources or poster presentation. Work performed by the primary assistant; server I/O only delegated.

## Verified public contracts (2026-09-30 UTC)
- Shenzhen Activities: https://www.szhuodong.com/ explicitly identifies its public account as `szhdw888`. Its public WordPress index advertises `/wp/v2/posts` and `/wp/v2/categories`. Public GETs succeeded without credentials. Selected categories cover charity, performance, family, lectures, exhibitions, outdoors, food and other activities; avoid repeatedly collecting the classified optician/discount advertising sections. Full public post content, publication time and source link are returned, enabling extraction beyond 50-character search excerpts. Follow advertised total-page headers, cap work and resume. Publication dates never substitute for activity dates.
- Shenzhen exhibition public-service platform: https://www.szhzfw.cn/zhanhui_9/ is a regularly updated multi-venue monthly index operated by Shenzhen's exhibition association. Latest October article https://www.szhzfw.cn/zhanhui_122/7509.html contains 36 named records across 3 venues and 19 listed organizer groupings. Parser follows newly linked month articles instead of hardcoding a single exhibition. English aliases remain attached; clear Chinese co-located events are separate. This is evidence of extracted records, not 36 net-new or independently confirmed events.
- Existing techevent-cn publicly labels online, offline and hybrid events. Its online records were previously dropped by Shenzhen city filtering. Preserve explicit mode; do not infer online attendance from an online registration link.
- 展大人 and 聚展 public listing attempts returned HTTP405 in this environment. They are investigated candidates, not claimed working sources; no CAPTCHA or restriction bypass.
- Datawhale calendar landing page was readable but the dynamic event list was not established as a reliable collector contract. It is not counted as connected.

## Interaction and location
- Root used the user's signed-in dot cloud browser and reproduced topic loss when returning via the home link.
- Remember filters in account-scoped browser storage; explicit filter/deep-link URLs take precedence; clear/reset persists; storage failure does not block use. No credentials are stored.
- Cards adapt 1/2/3/4 columns, with four only when wide enough; sort labels preserve actual event-date semantics.
- Existing server AMap key presence and prior successful usage were verified via read-only I/O; no new key or authorization created. Existing district enrichment is reused. Online and multi-venue/routing descriptions are not geocoded as one physical location. No exact address is overwritten with an inferred location.

## Acceptance required
Run unit/API/DOM and exact-commit desktop/mobile CI. Then deploy via existing SSH, collect each newly integrated source once within its normal public access bounds, verify observed counts and root-test live buttons. Do not close follow-up issues merely because a source URL or test suite exists. Separate later data-quality issue #43 and Inbox UI review.
