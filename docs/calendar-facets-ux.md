# Calendar and facet UX: #94, #95, #96

This change starts at merged main `56e2b32bbe215c82024c1aa919477377faf1e2f6`
(tree `1c2ef5dbfea9f1f1d53cc929950ae7d10a337b81`). Product changes are limited
to the four existing frontend files. Backend query, safety, source admission,
identity, personal-write and calendar/ICS rules retain their existing code.

## Behavior

- Month controls and the calendar precede the guide, long-event region and
  excluded-long summary. The empty list-pagination spacer is hidden in calendar.
- Long events start collapsed. The explicit expand/collapse button changes only
  presentation; it does not change the hide-long checkbox, URL or API query.
  The choice survives reload per authenticated owner. Storage failure leaves
  the current screen usable. Hiding long events removes their calendar preview;
  a compact count explains the filter after the calendar. The existing list-view
  explanation remains available.
- The calendar headline states the total matching activities, including long
  activities when included, with a separate grid/long breakdown. Multiple visual
  occurrences of a short multiday event do not inflate that activity count.
- Facets continue to mean OR within a dimension and AND across dimensions.
  Counts are measured under the other applied dimensions, ignoring their own
  selection. Topic counts overlap and must not be added. An unchecked topic is
  now called “未选”, not “排除”: an event can still match another selected topic.
  “仅选” provides an explicit one-option shortcut while checkbox toggles,
  all/invert/none and mobile apply/cancel keep their existing behavior.
- “全部方式” changes participation mode only; it keeps a selected culture topic.
  The supplemental favorite notice explicitly says it describes all favorites,
  independent of current filters.
- View changes reveal the active tab by adjusting the navigation container's
  horizontal scroll only. Labels, type sizes, core entries and page scroll are
  retained.

## Evidence and unfinished gates

The unchanged baseline's real isolated SQLite/API responses establish the sequence
all (5), culture (4), culture+online (2), culture+all participation (4), and long
included (7 = 5 short + 2 long). These are synthetic fixture counts, not a claim
about the user's current data or the screenshot's historical 252 activities.
An overlapping culture/social event correctly survives selecting social and
robotics while leaving culture unchecked. The old “排除文化艺术” description was
therefore misleading; the API algorithm itself is unchanged.

`tests/test_calendar_facets.py` covers actual query semantics, all/none, free and
long intersections, month boundaries, favorites, ICS and unchanged preference
rows. `tests/calendar_facets_dom.cjs` uses recorded synthetic API responses for
state/URL/query, disclosure, old-response rejection and horizontal navigation.
The eight new DOM contracts were run against the old product first and failed;
this includes missing new controls, and is not a claim of eight old race defects.

The existing browser union is retained. `calendar_facets_browser_cases.py` extends
the existing filter-context suite with real API/UI controls, back/forward/reload,
320/360/390/430/1440 CSS viewports, keyboard and emulated touch navigation, OS
light/dark preference, and normal-motion paired screenshots after a 300ms stable
frame interval. Original multiday/calendar assertions are preserved with the
new explicit expand action. This is not physical Android/iOS acceptance.

Cloud UI execution for this candidate is NOT RUN. The coordinator reported an
ERR_BLOCKED_BY_CLIENT boundary for cloud CDP loopback and directed no alternate
host/port/tunnel; this slot did not retry it. Local API/DOM checks do not substitute
for that browser work. Hosted execution, independent review, production deployment
and real user-flow verification remain required before closing the issues or
counting the whole three-round UX effort complete. No EEFocus activation or
production operation is part of this branch.

Frontend delivery uses the repository's existing FastAPI-served `static/` files;
there is no extra frontend bundler. Use the unchanged locked requirements and
existing `validate-events.yml` workflow for the full candidate checks.
