# AMap district enrichment review

Issue: #15

## Purpose

Some event sources provide a venue/building name but omit a Shenzhen district. The optional AMap Web Service integration enriches only `district`; it never replaces the source-provided `location`.

## Resolution policy

1. Parse an explicit Chinese/English Shenzhen district locally.
2. If still unknown and the location is usable, use AMap geocoding.
3. If geocoding has no district or returns a 3xxxx engine error, fall back to AMap POI text search with `region=深圳市` and `city_limit=true`.
4. English-heavy POI names use POI search first. Low text similarity is accepted only when at least two valid Shenzhen results agree on the same district.
5. Accept only known Shenzhen districts and `4403xx` adcodes from API results.
6. Hong Kong/Macau/other-city hints, generic “深圳”, and “报名后通知” locations remain unresolved.
7. Successful and negative results are cached for 30 days. Service/network errors are never cached as “not found”.
8. Requests are globally rate-limited. Any external failure leaves the existing event untouched.

The private key lives at `.private/amap.key` on the server and is excluded from Git.

## Production snapshot review

A clean snapshot of production data was used. No production row was changed during dry-run.

- Events with `district=待确认`: 127
- Of those with non-empty location: 76
- Reliably resolved: 47
- Explicitly skipped as vague/non-Shenzhen: 25
- No reliable result: 4
- API/service errors: 0
- Methods: geocode 35, POI 9, direct text 3

Resolved district distribution:

- 南山 23
- 福田 8
- 罗湖 4
- 龙华 4
- 龙岗 3
- 宝安 2
- 盐田 2
- 坪山 1

A snapshot apply changed only those 47 districts. Event count, favorite count and AI pending count remained unchanged. `district=待确认` fell from 127 to 80.

Safe review data is committed under `artifacts/amap-review/`. Database snapshots and the private key are not committed.
