# PS5 Game Scraper v1.0

<img width="1887" height="904" alt="image" src="https://github.com/user-attachments/assets/cc1979c6-93d3-4131-b826-6c31a9dc360f" />

A desktop application built with Electron that scrapes PS5 game data from dlpsgame.com, extracting Akira and Viking download links for easy access to game updates and patches.

## Features

### Core Functionality
- **Web Scraping**: Automatically fetches PS5 game lists from dlpsgame.com and scrapes individual game pages for download links.
- **Link Extraction**: Identifies and organizes Akira (akirabox.com) and Viking (vikingfile.com) download links, formatted with PPSA codes, regions, and versions.
- **Game Cards**: Displays games in visually appealing cards with covers, titles, and categorized links.
- **Cache System**: Saves scraped data locally for offline viewing and quick reloads on startup.
- **Progress Tracking**: Real-time progress bar and status updates during scraping.

### User Interface
- **Search Functionality**: Real-time search to filter games by title.
- **Dark Theme**: Sleek black and dark grey color scheme with glowing text effects.
- **Responsive Design**: Adapts to different screen sizes, with mobile-friendly layouts.
- **Notifications**: Toast-style notifications for success, errors, and updates.
- **External Links**: All links (game downloads and Discord) open in the user's default browser.

### Controls and Utilities
- **Start Scraping**: Initiates the scraping process.
- **Cancel Scan**: Stops the ongoing scraping operation.
- **Clear Cache**: Removes cached data and resets the UI.
- **Retry**: Appears on errors to retry the scraping process.
- **Discord Link**: Small, cute link in the top-right corner for joining the community (https://discord.gg/nj45kDSBEd).

### Advanced Features
- **Error Handling**: Robust error detection with user-friendly messages and retry options.
- **Concurrency**: Processes games in batches (10 at a time) for efficient scraping.
- **Button Management**: Disables irrelevant buttons during scanning to prevent conflicts.
- **Startup Behavior**: Launches maximized/fullscreen for optimal viewing.
- **Data Parsing**: Extracts additional details like voice, subtitles, notes, and file sizes where available.

## Installation

### Prerequisites
- Node.js (v14 or higher)
- npm or yarn

### Steps
1. Clone or download the project files.
2. Navigate to the project directory.
3. Install dependencies:
