# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v2.0.0] - 2026-02-07

### Added

#### Scraping Engine (main.js)
- **Per-link type detection** — `getTextBeforeLink()` analyzes HTML between links to classify each link individually (game, update, DLC, backport, fix)
- **`getTypeFromPrecedingText()`** — Keyword priority: backport > fix > update > dlc > game
- **Section-level fallback** — Falls back to section headers only when per-link detection fails
- **`looksLikeFirmware()` heuristic** — Correctly distinguishes firmware versions (4.xx) from game versions (01.027)
- **Firmware swap for backports** — Moves misclassified version to firmware field when it looks like a firmware number
- **Game firmware cleanup** — Prevents game links from inheriting backport firmware values
- **Viking/Viki host collision fix** — `identifyHost()` checks for `viking` before `viki` to prevent misclassification
- **5 additional hosts** — LetsUpload, Mediafire, Gofile, Rootz, Viki (previously only Akira, Viking, 1Fichier)
- **URL deduplication** — `seenUrls` map prevents duplicate download links
- **Concurrent scrape lock** — `scrapeLocksInProgress` Map prevents simultaneous scrapes of the same game page
- **Double scan guard** — `isScraping` flag prevents running multiple scans at once
- **Store error handling** — All store operations wrapped in try/catch with return values
- **`store:setSettings` IPC handler** — Bulk settings save for the settings modal
- **`store:setSetting` IPC handler** — Individual setting updates
- **PPSA code extraction** — Detects PPSA identifiers from game page body text
- **Password extraction** — Extracts download passwords from game pages
- **Screen languages extraction** — Pulls screen language info from game pages
- **Guide extraction** — Extracts guide/instructions text from game pages
- **Multiple backport firmware support** — Correctly handles games with 2+ backport firmware versions (e.g., NHL 24 with 4.xx and 5.xx)

#### Preload (preload.js) — NEW FILE
- **Context bridge** — Secure API exposure with `contextIsolation: true`
- **Store operations** — get, set, delete, clear, getSettings, setSetting, setSettings
- **Fetch operations** — fetchGameList, fetchRSS, scrapeGamePage
- **External links** — openExternal via IPC
- **Desktop notifications** — Uses browser `window.Notification` API (fixed from broken Electron `Notification` class)

#### UI (renderer.js)
- **Modal loading spinner** — Shows animated spinner inside modal while game details are being scraped
- **Modal error state with retry** — Failed scrapes show error icon with Retry and Close buttons inside the modal
- **Favorites count badge** — Shows `★ 3` when 3 games are favorited
- **Multiple backport sections** — Modal displays separate "Backport 4.xx Downloads" and "Backport 5.xx Downloads" sections
- **Info grid multi-backport** — Shows "Backports: 4.xx, 5.xx" when multiple backport firmwares exist
- **`getAllBackportFirmwares()`** — Returns sorted unique firmware versions for the info grid
- **`getBackportFwGroup()`** — Groups backport links by major firmware number
- **`buildDownloadLink()`** — Extracted helper function for DRY download link rendering
- **Host reordering** — `sortHostNames()` sorts download hosts based on user's preferred order
- **`renderHostOrder()`** — IIFE closure for button indices prevents stale variable bugs
- **Legacy migration** — Automatically migrates old `backport` data bucket to `other` on load
- **`updateFavBtn()`** — Updates favorite button color and count badge
- **Cache auto-clear** — `checkCacheExpiry()` compares newest game date to `cacheDays` setting

#### Settings System
- **Max Games** — Limit how many games to fetch (0 = unlimited)
- **Auto-Scan on Launch** — Automatically start scanning when app opens if no cache exists
- **Theme** — Dark or Light mode with comprehensive CSS for both
- **Default Sort** — Choose date or name as the default sort order
- **Cache Auto-Clear** — Automatically clear cache after X days
- **Preferred Host Order** — Reorder download hosts with up/down arrows in settings modal

#### Layout & Styling (index.html)
- **Full-width fluid layout** — Container stretches to 100% width, no more 1200px cap
- **Fluid game cards** — Cards fill available width using `auto-fill` grid with `minmax(140px, 1fr)`
- **Aspect ratio covers** — `aspect-ratio: 3/4` keeps cover images proportional at any card size
- **2-line game titles** — `-webkit-line-clamp: 2` with `min-height: 2.8em` for consistent card heights
- **Discord badge** — Professional pill badge with Discord SVG icon, label, separator, and username
- **Light theme** — Complete light theme CSS covering all elements: cards, modals, settings, scrollbars, Discord badge
- **Modal loading CSS** — Spinner animation and error icon styles
- **Backport firmware badge** — Purple color in both dark (`#b266ff`) and light (`#8833cc`) themes
- **Settings modal** — Full settings UI with inputs, selects, checkboxes, and host reorder list
- **Large screen breakpoints** — `@media (min-width: 1800px)` and `2400px` for ultrawide/4K displays
- **Mobile breakpoints** — Responsive layout for screens under 900px
- **Custom scrollbars** — Styled for both dark and light themes
- **No menu bar** — `Menu.setApplicationMenu(null)` removes File/Edit/View/Help
- **No DevTools** — `devTools: false` in webPreferences blocks all developer tools access
- **`autoHideMenuBar: true`** — Backup menu bar hiding

### Changed
- **Architecture** — Split from monolithic `main.js` + `renderer.js` into 4-file architecture with dedicated `preload.js`
- **Host bucket structure** — Changed from `akira/viking/onefichier/backport` to `akira/viking/onefichier/other` to support all host types
- **Link type detection** — Changed from section-only detection to per-link inline analysis with section fallback
- **Firmware extraction** — Now uses 3-tier extraction: context text → URL patterns → global page content
- **Progress display** — Replaced progress bar with compact inline stats (games · pages · errors)
- **Container width** — Changed from `max-width: 1200px` to `width: 100%; max-width: 100%`
- **Card sizing** — Removed fixed `max-width: 125px` on game cards, now fluid width
- **Cover images** — Changed from fixed `height: 150px` to `aspect-ratio: 3/4` for proportional scaling
- **Body margin** — Changed from `margin: 20px` to `margin: 0; padding: 20px` to prevent collapse
- **Discord link** — Upgraded from plain text link to professional badge with SVG icon
- **Notification import** — Changed from Electron `Notification` (main process only, crashed in preload) to browser `window.Notification` API
- **Settings storage** — Changed from individual `setSetting` calls to bulk `setSettings` for the settings modal

### Fixed
- **Preload Notification crash** — `Notification` class from Electron main process was undefined in preload context, causing app crash on scan complete. Fixed by using browser `window.Notification` API
- **Viking/Viki host collision** — Links containing "viki" in the URL were incorrectly identified as Viki when they were actually Viking. Fixed with explicit `viking` check before `viki`
- **Backport links mixed with game links** — All links on inline-format pages (e.g., NFS Unbound) were classified as one type. Fixed with `getTextBeforeLink()` per-link analysis
- **Firmware misclassification** — Game versions like `01.027` were treated as firmware. Fixed with `looksLikeFirmware()` heuristic
- **Game links inheriting backport firmware** — Game-type links incorrectly showed backport firmware versions. Fixed with type-aware firmware assignment
- **Cover images not scaling** — Fixed `padding-bottom: 133%` trick (broken on `img` elements) by using `aspect-ratio: 3/4`
- **Cards not filling screen** — Fixed by removing `max-width: 125px` cap and `1200px` container limit
- **Buttons not working** — CSP meta tag `connect-src https:` blocked Electron IPC calls. Fixed by removing restrictive CSP

### Removed
- **CSP meta tag** — Removed `Content-Security-Policy` meta tag that was blocking Electron IPC
- **Progress bar** — Replaced with compact inline progress stats
- **Fixed card widths** — Removed `max-width: 125px` constraint
- **Container width cap** — Removed `max-width: 1200px`
- **Default Electron menu** — Removed File, Edit, View, Help menu bar
- **DevTools access** — Disabled `Ctrl+Shift+I`, `F12`, and all DevTools access

---

## [v1.2.0] - 2026-01-01

### Added
- Pagination support for scraping all PS5 games from `dlpsgame.com/category/ps5/` (previously only fetched from a single page).
- Release date scraping from game pages and sorting games by release date (newest first by default).
- Sort toggle button ("Sort: Date" / "Sort: Name") to switch between date-based and alphabetical sorting.
- Percentage display in scraping progress status (e.g., "Scraping... 50/300 (17%)").
- Total games found display in status messages (e.g., "Loaded 300 games from cache", "Scan completed! Found 300 games in 120 seconds").
- Favorites system: Star games as favorites, toggle to show only favorites.
- Grid view toggle removed (kept only grid for simplicity).
- Desktop notifications for scan completion, cancellation, and errors.
- Progress bar: Thin, electric-style progress bar that auto-hides after scan.
- Game modal enhancements: Display game description and screenshots from the game page.
- Lazy loading: Full link/details scraped on-demand when opening modal.

### Changed
- Scraping source changed to category pages for a comprehensive game list (fetches all ~300+ games via pagination).
- Button layout: Cancel button moved to the left of Start Scraping.
- Button states: Only Cancel button is enabled during scanning; all others (Start Scraping, Clear Cache, Sort, Search input) are disabled to prevent interference.
- UI spacing: Reduced margin between title and buttons.
- Performance optimizations: Increased batch size to 40 (from 20), reduced delays (page fetch to 500ms, inter-batch to 100ms) for ~2-4x faster scraping without breaking functionality.
- Progress bar: Now thin and electric-styled, auto-hides after completion, with game count on the same row.
- Progress updates: Smoother bar with percentage info and avoids jumping back and forth.

### Fixed
- Game name cleaning and display for consistency (removes extra suffixes, trims whitespace).
- Progress bar jumping issues during batch processing.
- Button positioning and states to avoid user errors during scans.
- Modal display: Now includes description and screenshots from game pages.

### Removed
- List view toggle (kept only grid view for simplicity).