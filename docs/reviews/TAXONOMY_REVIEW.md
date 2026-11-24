# Schema.org Event taxonomy review

Issue: #34

## Why this change

The original filter mixed subject interests (AI, robotics, hardware, automotive) with event forms (exhibition, culture, music). That made the first-level category semantically unstable: a comedy show or concert could be placed in the same bucket as a museum exhibition.

The canonical event-type vocabulary now comes from Schema.org Event subtypes:
https://schema.org/Event

Google's event structured-data documentation also uses Schema.org Event as the event classification model:
https://developers.google.com/search/docs/appearance/structured-data/event

No platform-specific category list is used as the canonical taxonomy.

## Canonical model

Each event has:

- `event_type`: one canonical Schema.org Event type.
- `event_type_state`: `source`, `ai`, or `pending`.
- `topics`: independent subject-interest tags.

User-facing examples:

- ComedyEvent → 喜剧 / 脱口秀
- TheaterEvent → 戏剧 / 话剧
- MusicEvent → 音乐 / 演唱会
- ExhibitionEvent → 展览 / 博览
- Hackathon → 黑客松
- ConferenceEvent → 会议 / 大会
- SportsEvent → 体育 / 运动
- SocialEvent → 社交 / 聚会

A source-provided specific Schema.org type is authoritative and is not overwritten by AI. Generic or missing types remain pending until incremental classification. Unknown records are shown as “待分类”, not falsely labeled “其他活动”.

## Filter semantics

The UI has two independent checkbox groups:

1. 活动类型 — Schema.org types.
2. 主题 — AI/开源、机器人、硬件创客、产品创业、汽车、文化艺术、户外生活等 subject tags.

Within one group, selections are OR. Across groups, they are AND.

Example:

`(ComedyEvent OR MusicEvent) AND (AI与开源)`

Repeated URL parameters preserve the state:

`?type=ComedyEvent&type=MusicEvent&topic=AI与开源`

The filters survive reload and browser back/forward. Selected type/topic chips can be removed individually.

## Migration and budget

The migration adds columns only; it does not rewrite dates, locations, favorites, source links, or AI summaries.

Existing records start as `Event + pending`. New/changed records receive `event_type` in the existing AI analysis call. Previously analyzed records are backfilled in bounded batches under the same daily model budget. No separate unlimited budget is introduced.

Specific Schema.org `@type` values found in source JSON-LD are stored immediately with state `source`.

## Verification

- Production database snapshot migration preserves event/raw/favorite counts.
- Unit/API regressions cover specific source types, source authority, AI typing, multi-select OR/AND semantics, repeated URL params, facets, legacy topic migration, and bounded backfill.
- Browser regression covers distinct entertainment type labels, desktop multi-select, removable chips, history restoration, mobile checkbox UI and type-backfill status.
- Original interaction/coverage browser suites are rerun before release.
