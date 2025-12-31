# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/SemVer).

## [1.1.0] - 2025-12-31

### Added
- Offline functionality: App now keeps its own cache as a local database file (gamesCache.json) that persists across sessions and works even offline.
- IPC communication: Added Electron IPC handlers for saving and loading cache to/from disk.
- File-based cache: Replaced localStorage with fs-based storage for better persistence and larger data capacity.
- Clear cache functionality: Option to delete the cache file entirely.

### Changed
- UI Layout: Modal windows now show only the cover and game information; clicking a game opens a new modal screen with links and full details.
- Game card size: Reduced to half size for better grid display.
- Game names: "PS5" is now removed from the end of game titles for cleaner display.
- Modal appearance: Title removed from behind the cover; modal is smaller and fits content better (40% width on desktop, 80% on mobile).
- Cover display: Modal covers use `object-fit: contain` for portrait orientation (taller height) and no dropshadow frame.
- Cache handling: Cache is now saved to a JSON file in the user data directory, allowing overwrites when newer links are found.

### Fixed
- Cache persistence: Data now survives app restarts and works offline.
- UI responsiveness: Improved modal sizing and cover display for better user experience.

### Technical
- Added `ipcMain` and `fs` usage in main.js for cache management.
- Modified renderer.js to use IPC for cache operations instead of localStorage.
- Updated index.html CSS for modal and cover styling changes.
- Cache file location: `%APPDATA%\NookieAI\PS5-Game-Scraper\gamesCache.json` (or equivalent on other OS).

## [1.0.0] - 2025-12-31

### Added
- Initial release of PS5 Game Scraper.
- Scrapes PS5 game links from dlpsgame.com.
- Supports Akira and Viking download links.
- Displays game covers, titles, voice, subtitles, notes, and size.
- Search functionality for games.
- Progress bar during scraping.
- Caching of results in localStorage.
- Modal popups for game details and links.
- Discord link in the app.

### Known Issues
- Cache limited to 5MB in localStorage.
- No offline support beyond initial cache load.