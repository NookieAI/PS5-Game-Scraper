Support my project! :heart: https://ko-fi.com/nookie_65120

<img width="944" height="464" alt="Screenshot 2026-01-01 181528" src="https://github.com/user-attachments/assets/33c9f4e3-3a66-4fd4-8b90-88052ec49a4c" />

# PS5 Game Scraper

A portable desktop application built with Electron that scrapes and displays PS5 game download links from dlpsgame.com. It intelligently classifies links by type (game, update, DLC, backport, fix), identifies 8+ hosting providers, extracts firmware compatibility, and organizes everything into a clean, searchable interface.

## Features

### Scraping & Data
- **Full Category Scraping** — Paginates through all PS5 game pages with batched concurrent requests
- **RSS Feed Fallback** — Supplements category data with RSS for cover images and dates
- **8 Host Providers** — Akira, Viking, 1Fichier, LetsUpload, Mediafire, Gofile, Rootz, Viki
- **Smart Link Classification** — Per-link type detection using inline text analysis (game, update, DLC, backport, fix)
- **Section-Level Fallback** — Falls back to section headers when inline detection isn't available
- **Firmware Extraction** — Pulls firmware versions from context text, URLs, and global page content
- **Backport Firmware Grouping** — Detects and separates multiple backport firmware versions (e.g., 4.xx and 5.xx)
- **Version Extraction** — Extracts game versions from link text, URLs, and surrounding context
- **URL Deduplication** — Prevents duplicate download links
- **Concurrent Scrape Lock** — Prevents multiple scrapes of the same game page simultaneously
- **PPSA Code Detection** — Extracts PPSA identifiers from game pages

### Interface
- **Fluid Grid Layout** — Game cards fill the entire screen width, scales from 1080p to 4K+
- **2-Line Game Titles** — Card titles wrap to 2 lines with ellipsis overflow
- **Responsive Cover Art** — 3:4 aspect ratio covers that scale proportionally with card width
- **Game Detail Modal** — Cover image, info grid, description, guide, screenshots, organized download sections
- **Modal Loading Spinner** — Shows loading state inside modal while scraping game details
- **Modal Error + Retry** — Failed scrapes show error state with retry button inside the modal
- **Screenshot Viewer** — Click screenshots to view full-size in overlay modal
- **Search** — Fuzzy search powered by Fuse.js with inline fallback
- **Sort** — Toggle between date (newest first) and alphabetical sorting
- **Favorites** — Star games as favorites, filter to show only favorites, count badge on button
- **Progress Stats** — Live games found, pages scanned, and error count during scan
- **Desktop Notifications** — System notifications on scan complete/cancel
- **Dark & Light Theme** — Full theme support with comprehensive CSS for both modes
- **No Menu Bar** — Clean app window with no File/Edit/View menus
- **No DevTools** — Production-locked, no access to developer tools

### Settings
- **Max Games Limit** — Cap how many games to fetch (0 = unlimited)
- **Auto-Scan on Launch** — Automatically start scanning when app opens if cache is empty
- **Theme Selection** — Dark or Light theme
- **Default Sort Order** — Choose date or name as default sort
- **Cache Auto-Clear** — Automatically clear cache after X days
- **Host Priority Order** — Reorder download hosts with up/down arrows

### Data & Storage
- **Persistent Cache** — Game data saved locally via electron-store for instant loading
- **Favorites Persistence** — Favorites saved separately and survive cache clears
- **Settings Persistence** — All settings saved and restored on launch
- **Legacy Migration** — Automatically migrates old `backport` data bucket to new `other` format

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Framework | Electron 28+ |
| Scraping | Axios + Cheerio |
| Storage | electron-store |
| Search | Fuse.js |
| Build | electron-builder |

## Project Structure

```
ps5-game-scraper/
├── assets/
│   ├── icon1.ico          # App icon
│   └── logo.jpg           # Header logo
├── main.js                # Electron main process — scraping, IPC, store
├── preload.js             # Context bridge — secure API exposure
├── renderer.js            # UI logic — cards, modals, settings, search
├── index.html             # Layout, CSS (dark+light), all modals
├── package.json           # Dependencies + electron-builder config
├── README.md
└── CHANGELOG.md
```

## Build & Run

### Prerequisites
- [Node.js](https://nodejs.org/) v18+
- npm

### Development
```bash
# Install dependencies
npm install

# Run the app
npm start
```

### Build Portable EXE
```bash
# Build portable Windows executable
npm run build

# Output: dist/PS5-Game-Scraper-1.0.0-Portable.exe
```

### Build Windows Installer
```bash
npm run build:installer
```

## Download Hosts Supported

| Host | Domain |
|------|--------|
| Akira | akirabox.com |
| Viking | vikingfile.com |
| 1Fichier | 1fichier.com |
| LetsUpload | letsupload.* |
| Mediafire | mediafire.com |
| Gofile | gofile.io |
| Rootz | rootz.* |
| Viki | viki.* |

## Link Type Detection

The scraper classifies each download link into one of 5 types:

| Type | Badge Color | Detection |
|------|------------|-----------|
| Game | Cyan | Default — base game download |
| Update | Green | "update" keyword in context |
| DLC | Gold | "dlc" keyword in context |
| Backport | Purple | "backport/backpork" keyword in context |
| Fix | Red | "fix" keyword in context |

**Priority**: Per-link inline text → Section header → Keyword fallback

## Disclaimer

This is a **scraper only**. It does not host, distribute, or store any game files. It searches and displays external links found on publicly accessible web pages. All download links belong to their respective hosting providers.

## Support

For support join Discord: https://discord.gg/wp3WpWXP77