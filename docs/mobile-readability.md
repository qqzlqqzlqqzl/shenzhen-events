# Mobile readability and keyboard focus

Only the pinned text colors, placeholder color/opacity and focus outlines change in product CSS. Layout, fonts and spacing retain their existing declarations. Shared focus uses a 3px green outline; the dark undo notification uses lime. The later search input outline suppression is removed.

`tests/readability_browser.py` reuses the isolated API/browser harness and changes only a fresh fixture database. It measures computed foreground/background compositing, drives real Tab navigation, and checks cards, detail dialogs, filter dialogs, scrolling and overflow at 320 and 390 pixels. A temporary Chromium extension requests native 200% page zoom with `chrome.tabs.setZoom`, confirms `getZoom`, DPR and CSS viewport changes, and checks the zoomed cards/details. No deviceScaleFactor simulation or production login is used.

Measured text contrast: metadata/source/date/summary 5.33:1; topic tags 5.45:1; secondary tags 4.91:1; warnings 5.70:1; mobile search placeholder 5.36:1. Focus rings exceed 3:1. Native zoom reports 2 with DPR 2 and a 640px CSS viewport inside a 1280px browser window. The exact-head CI browser list includes this new regression.

Refs: separate readability issue pending creation (GitHub access blocked by automatic approval review).
