Support my project! :heart: https://ko-fi.com/nookie_65120

# PS5 Game Scraper

<img width="1891" height="931" alt="image" src="https://github.com/user-attachments/assets/640fd289-a3c1-451f-93eb-caee3b941b8e" />

An Electron-based desktop app that scrapes PS5 game download links from dlpsgame.com, displaying them with covers, details, and direct download links to Akira and Viking hosts. Now with offline support via persistent local cache!

## Features

- **Game Scraping**: Automatically fetches the latest PS5 game list and extracts download links from Akira and Viking.
- **Offline Support**: Keeps a persistent cache as a local JSON database file, allowing the app to work without an internet connection after the initial scrape.
- **User-Friendly UI**: Clean, dark-themed interface with game covers, search, and modal details.
- **Modal Details**: Click on any game to view full cover, info, and download links in a popup modal.
- **Search & Filter**: Real-time search through game titles.
- **Progress Tracking**: Visual progress bar and status updates during scraping.
- **Cache Management**: Clear cache or let it auto-update with newer links.
- **Cross-Platform**: Built with Electron for Windows, macOS, and Linux.
### Prerequisites
- Node.js (v14 or higher)
- npm

### Steps
1. Clone the repository:
   ```
   git clone https://github.com/NookieAI/PS5-Game-Scraper.git
   cd PS5-Game-Scraper
   ```

2. Install dependencies:
   ```
   npm install
   ```

3. Run the app:
   ```
   npm start
   ```

### Building for Distribution
To build executables for your platform:
```
npm run build
```

This uses Electron Builder to create distributable packages.

## Usage

1. Launch the app.
2. Click "Start Scraping" to fetch the latest PS5 games and links.
3. Use the search bar to filter games.
4. Click on a game card to open the modal with cover, details, and download links.
5. Click download links to open in your default browser.
6. The app caches results locally for offline use—scrape again to update with new links.

### Offline Mode
- After the first scrape, results are saved to a local file (`gamesCache.json` in your user data directory).
- Reopen the app anytime to view cached games without internet.
- Clear cache if needed to free space or force a fresh scrape.

## Configuration

- **Cache Location**: `%APPDATA%\NookieAI\PS5-Game-Scraper\gamesCache.json` (Windows), or equivalent on macOS/Linux.
- No additional config files needed.

## Dependencies

- **Electron**: For the desktop app framework.
- **Cheerio**: For HTML parsing during scraping.
- **Axios**: For HTTP requests.
- **Shell**: For opening external links.

## Development

- Main process: `main.js`
- Renderer process: `renderer.js`
- UI: `index.html` with inline CSS.

To modify:
- Edit `index.html` for UI changes.
- Update `renderer.js` for logic.
- Modify `main.js` for Electron setup or IPC.

## Contributing

1. Fork the repo.
2. Create a feature branch.
3. Make changes and test.
4. Submit a pull request.

## License

This project is open-source under the MIT License. See LICENSE for details.

## Disclaimer

This app scrapes public websites for educational purposes. Respect copyright laws and terms of service. Use at your own risk.

## Support

- Issues: [GitHub Issues](https://github.com/NookieAI/PS5-Game-Scraper/issues)
- Discord: Join [Nookie_65120's Server](https://discord.gg/nj45kDSBEd)
