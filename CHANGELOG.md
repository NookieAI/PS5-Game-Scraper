# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- N/A