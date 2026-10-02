# Mobile readability and keyboard focus

The pinned text colors, placeholder color/opacity and focus outlines improve readability. Shared focus uses a 3px green outline; the dark undo notification uses lime. The later search input outline suppression is removed. Card, page and dialog fonts/layout remain unchanged.

Page-level comparison and feedback undo share a bottom action stack. Its layout follows the bars' actual heights, including wrapped comparison chips, so both remain reachable after closing detail. Undo remains inside an open detail dialog and returns to the stack on close; feedback data, comparison selection and undo behavior retain their existing contracts. The markup adds the shared host, the existing reparent helper targets it, and CSS coordinates placement without a measured pixel offset.

`tests/readability_browser.py` reuses the isolated API/browser harness and changes only a fresh fixture database. It measures computed foreground/background compositing, drives real Tab navigation, and checks cards, detail dialogs, filter dialogs, scrolling and overflow at 320 and 390 pixels. A temporary Chromium extension requests native 200% page zoom with `chrome.tabs.setZoom`, confirms `getZoom`, DPR and CSS viewport changes, and checks the zoomed cards/details. No deviceScaleFactor simulation or production login is used.

Measured text contrast: metadata/source/date/summary 5.33:1; topic tags 5.45:1; secondary tags 4.91:1; warnings 5.70:1; mobile search placeholder 5.36:1. Focus rings exceed 3:1. Native zoom reports 2 with DPR 2 and a 640px CSS viewport inside a 1280px browser window; this establishes DOM geometry only, with no 320/390px-at-200% visual claim. Headless native-zoom captures remain blank. Mobile captures are inspected at 100% zoom.

`tests/mobile_overlays_browser.py` uses the same isolated real Chromium/API harness. It keeps comparison selected during detail feedback and button/Escape/Back close, checks rendered intersection/hit targets and real Tab focus, opens comparison, adds/removes long-title candidates, performs undo and clears/dismisses independently at 320x640, 390x844 and desktop. The exact-head CI browser list includes both regressions. The prior head's real mobile captures show 109px overlap and blocked comparison controls.

Refs #88. Additional interaction repair requires independent review before release.
