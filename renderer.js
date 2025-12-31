const { shell } = require('electron');

document.addEventListener('DOMContentLoaded', () => {
  const cheerio = require('cheerio');
  const axios = require('axios');

  const scrapeBtn = document.getElementById('scrapeBtn');
  const cancelBtn = document.getElementById('cancelBtn');
  const clearCacheBtn = document.getElementById('clearCacheBtn');
  const retryBtn = document.getElementById('retryBtn');
  const statusDiv = document.getElementById('status');
  const progressContainer = document.getElementById('progressContainer');
  const progressBar = document.getElementById('progressBar');
  const progressText = document.getElementById('progressText');
  const resultsDiv = document.getElementById('results');
  const searchInput = document.getElementById('searchInput');
  const notificationDiv = document.getElementById('notification');
  const discordLink = document.getElementById('discord-link');
  const modal = document.getElementById('modal');
  const modalBody = document.getElementById('modal-body');
  const closeBtn = document.querySelector('.close');

  const BASE_URL = 'https://dlpsgame.com';
  let isCancelled = false;
  let gamesData = {};

  console.log('Renderer loaded');
  console.log('scrapeBtn:', scrapeBtn); // Debug: Check if button is found

  if (!scrapeBtn) {
    console.error('Scrape button not found. Check HTML for id="scrapeBtn".');
    return;
  }

  // Function to show notifications (only for errors now)
  function showNotification(message, type = 'info') {
    notificationDiv.textContent = message;
    notificationDiv.style.background = type === 'error' ? '#e74c3c' : type === 'success' ? '#27ae60' : '#3498db';
    notificationDiv.style.display = 'block';
    setTimeout(() => {
      notificationDiv.style.display = 'none';
    }, 5000);
  }

  // Function to show status with auto-hide
  function showStatus(message) {
    statusDiv.textContent = message;
    statusDiv.classList.add('show');
    setTimeout(() => {
      statusDiv.classList.remove('show');
    }, 5000);
  }

  // Function to disable/enable buttons during scan
  function setButtonsDuringScan(scanning) {
    scrapeBtn.disabled = scanning;
    searchInput.disabled = scanning;
    clearCacheBtn.disabled = scanning;
    cancelBtn.disabled = !scanning;
    cancelBtn.style.display = scanning ? 'inline-block' : 'none';
    retryBtn.style.display = 'none'; // Hide retry unless error
  }

  // Function to get all game URLs from the PS5 list page
  async function getGameUrls() {
    try {
      const response = await axios.get(`${BASE_URL}/list-game-ps5/`, { timeout: 30000 });
      const $ = cheerio.load(response.data);
      const links = [];
      $('a.title').each((i, el) => {
        const href = $(el).attr('href');
        if (href && href.startsWith('https://dlpsgame.com/')) {
          links.push(href);
        }
      });
      console.log('Game URLs found:', links.length);
      return [...new Set(links)]; // Remove duplicates
    } catch (error) {
      console.error('Error fetching game URLs:', error);
      showNotification('Failed to fetch game list. Check your internet connection.', 'error');
      return [];
    }
  }

  // Function to scrape a game page for Akira and Viking download links
  async function scrapeGamePage(gameUrl) {
    try {
      const response = await axios.get(gameUrl, { timeout: 30000 });
      const $ = cheerio.load(response.data);
      const akiraLinks = [];
      const vikingLinks = [];
      $('a[href]').each((i, el) => {
        const href = $(el).attr('href');
        if (href) {
          const versionText = $(el).closest('div').text().trim().replace(/\s+/g, ' ') || $(el).closest('p').text().trim().replace(/\s+/g, ' ') || $(el).text().trim() || 'Download Link';
          const linkData = { link: href, version: versionText };
          if (href.includes('akirabox.com')) {
            akiraLinks.push(linkData);
          } else if (href.includes('vikingfile.com')) {
            vikingLinks.push(linkData);
          }
        }
      });
      const title = $('title').text() || '';
      const metaDesc = $('meta[name="description"]').attr('content') || '';
      const cover = $('meta[property="og:image"]').attr('content') || '';
      const voice = title.match(/Voice\s*:\s*([^N]+)/)?.[1]?.trim() || '';
      const subtitles = title.match(/Subtitles?\s*:\s*([^N]+)/)?.[1]?.trim() || '';
      const notes = title.match(/Note\s*:\s*(.+?)(?:\(|$)/)?.[1]?.trim() || '';
      const size = title.match(/Size\s*:\s*([^N]+)/)?.[1]?.trim() || '';
      return { akira: akiraLinks, viking: vikingLinks, title, metaDesc, cover, voice, subtitles, notes, size };
    } catch (error) {
      console.error('Error scraping game page:', error);
      showNotification('Failed to scrape a game page. Retrying or skipping.', 'error');
      return { akira: [], viking: [], title: '', metaDesc: '', cover: '', voice: '', subtitles: '', notes: '', size: '' };
    }
  }

  // Function to create a game card in the UI
  function createGameCard(gameTitle, cover, voice, subtitles, notes, size) {
    const card = document.createElement('div');
    card.className = 'game-card';
    card.dataset.title = gameTitle; // Store title for modal
    
    if (cover) {
      const img = document.createElement('img');
      img.src = cover.startsWith('http') ? cover : `${BASE_URL}${cover}`;
      img.alt = gameTitle;
      img.className = 'game-cover';
      card.appendChild(img);
    }
    
    const title = document.createElement('div');
    title.className = 'game-title';
    title.textContent = gameTitle;
    card.appendChild(title);
    
    const details = document.createElement('div');
    details.className = 'game-details';
    let detailsText = '';
    if (voice) detailsText += `Voice: ${voice} | `;
    if (subtitles) detailsText += `Subtitles: ${subtitles} | `;
    if (notes) detailsText += `Notes: ${notes} | `;
    if (size) detailsText += `Size: ${size}`;
    details.textContent = detailsText.replace(/ \| $/, '');
    if (detailsText) card.appendChild(details);
    
    card.addEventListener('click', () => showModal(gameTitle));
    
    return card;
  }

  // Function to show modal with game details and links
  function showModal(gameTitle) {
    const data = gamesData[gameTitle];
    if (!data) return;
    
    modalBody.innerHTML = '';
    
    // Cover
    if (data.cover) {
      const img = document.createElement('img');
      img.src = data.cover.startsWith('http') ? data.cover : `${BASE_URL}${data.cover}`;
      img.alt = gameTitle;
      img.className = 'game-cover';
      modalBody.appendChild(img);
    }
    
    // Details
    const details = document.createElement('div');
    details.className = 'game-details';
    let detailsText = '';
    if (data.voice) detailsText += `Voice: ${data.voice} | `;
    if (data.subtitles) detailsText += `Subtitles: ${data.subtitles} | `;
    if (data.notes) detailsText += `Notes: ${data.notes} | `;
    if (data.size) detailsText += `Size: ${data.size}`;
    details.textContent = detailsText.replace(/ \| $/, '');
    if (detailsText) modalBody.appendChild(details);
    
    // Akira Links
    if (data.akira && data.akira.length > 0) {
      const akiraSection = document.createElement('div');
      akiraSection.className = 'links-section';
      akiraSection.innerHTML = '<h3>Akira Links:</h3>';
      const akiraList = document.createElement('ul');
      akiraList.className = 'link-list';
      data.akira.forEach(item => {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = item.link;
        let displayText = '';
        const ppsaMatch = item.version.match(/PPSA\d+ – [A-Z]{3}/g);
        if (ppsaMatch) {
          const ppsaStr = ppsaMatch.join(' ').replace(/ – /g, ' (') + ')';
          displayText += ppsaStr + ' - ';
        }
        const versionMatch = item.version.match(/\( ?v[\d.]+\)/);
        if (versionMatch) displayText += versionMatch[0].replace(' ', '');
        a.textContent = displayText || item.link;
        a.addEventListener('click', (e) => {
          e.preventDefault();
          shell.openExternal(item.link);
        });
        li.appendChild(a);
        akiraList.appendChild(li);
      });
      akiraSection.appendChild(akiraList);
      modalBody.appendChild(akiraSection);
    }
    
    // Viking Links
    if (data.viking && data.viking.length > 0) {
      const vikingSection = document.createElement('div');
      vikingSection.className = 'links-section';
      vikingSection.innerHTML = '<h3>Viking Links:</h3>';
      const vikingList = document.createElement('ul');
      vikingList.className = 'link-list';
      data.viking.forEach(item => {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = item.link;
        let displayText = '';
        const ppsaMatch = item.version.match(/PPSA\d+ – [A-Z]{3}/g);
        if (ppsaMatch) {
          const ppsaStr = ppsaMatch.join(' ').replace(/ – /g, ' (') + ')';
          displayText += ppsaStr + ' - ';
        }
        const versionMatch = item.version.match(/\( ?v[\d.]+\)/);
        if (versionMatch) displayText += versionMatch[0].replace(' ', '');
        a.textContent = displayText || item.link;
        a.addEventListener('click', (e) => {
          e.preventDefault();
          shell.openExternal(item.link);
        });
        li.appendChild(a);
        vikingList.appendChild(li);
      });
      vikingSection.appendChild(vikingList);
      modalBody.appendChild(vikingSection);
    }
    
    modal.style.display = 'block';
  }

  // Function to display results
  function displayResults(data = gamesData) {
    resultsDiv.innerHTML = '';
    const sorted = Object.entries(data).sort(([a], [b]) => a.localeCompare(b));
    for (const [gameTitle, links] of sorted) {
      const card = createGameCard(gameTitle, links.cover, links.voice, links.subtitles, links.notes, links.size);
      resultsDiv.appendChild(card);
    }
  }

  // Function to display cached results
  function displayCachedResults() {
    const cachedData = localStorage.getItem('gamesData');
    if (cachedData) {
      gamesData = JSON.parse(cachedData);
      displayResults();
      if (statusDiv) statusDiv.textContent = 'Loaded from cache. Click "Start Scraping" to begin.';
      console.log('Displayed cached results');
    } else {
      if (statusDiv) statusDiv.textContent = 'No cached results. Click "Start Scraping" to begin.';
    }
  }

  // Main scraping function
  async function runScraper() {
    console.log('Starting scraper');
    const startTime = Date.now(); // Track start time
    isCancelled = false;
    setButtonsDuringScan(true);
    retryBtn.style.display = 'none';
    if (statusDiv) statusDiv.textContent = 'Fetching game list...';
    if (progressContainer) progressContainer.style.display = 'none';
    if (resultsDiv) resultsDiv.innerHTML = '';
    
    const gameUrls = await getGameUrls();
    if (gameUrls.length === 0) {
      showNotification('No games found. Please check the website.', 'error');
      setButtonsDuringScan(false);
      retryBtn.style.display = 'inline-block';
      return;
    }
    if (isCancelled) {
      setButtonsDuringScan(false);
      return;
    }
    if (progressBar) progressBar.max = gameUrls.length;
    if (progressBar) progressBar.value = 0;
    if (progressText) progressText.textContent = `0/${gameUrls.length}`;
    if (progressContainer) progressContainer.style.display = 'block';
    if (statusDiv) statusDiv.textContent = `Found ${gameUrls.length} games. Scraping details...`;
    
    gamesData = {}; // Reset
    let completed = 0;
    let hasErrors = false;
    const batchSize = 10; // Process in batches of 10 for concurrency
    
    for (let i = 0; i < gameUrls.length; i += batchSize) {
      if (isCancelled) break;
      const batch = gameUrls.slice(i, i + batchSize);
      const promises = batch.map(async (url, idx) => {
        const globalIdx = i + idx;
        const gameTitle = url.split('/').slice(-2)[0].replace(/-/g, ' ').replace(/-ps5$/, '').toUpperCase() || url;
        console.log(`Processing: ${globalIdx + 1}/${gameUrls.length} - ${gameTitle}`);
        const data = await scrapeGamePage(url);
        const rawTitle = data.metaDesc || data.title || gameTitle;
        const cleanedTitle = rawTitle.split(' Download')[0].split(' ISO')[0].split(' Torrent')[0].trim().replace(/\s+PS5$/i, '');
        const finalTitle = cleanedTitle || rawTitle;
        return { finalTitle, data };
      });
      
      const results = await Promise.allSettled(promises);
      results.forEach(result => {
        if (result.status === 'fulfilled' && result.value) {
          const { finalTitle, data } = result.value;
          if (data.akira.length > 0 || data.viking.length > 0) {
            if (!gamesData[finalTitle]) {
              gamesData[finalTitle] = { akira: [], viking: [], cover: data.cover, voice: data.voice, subtitles: data.subtitles, notes: data.notes, size: data.size };
            }
            gamesData[finalTitle].akira.push(...data.akira);
            gamesData[finalTitle].viking.push(...data.viking);
          }
        } else {
          hasErrors = true;
        }
        completed++;
        if (progressBar) progressBar.value = completed;
        if (progressText) progressText.textContent = `${completed}/${gameUrls.length}`;
        if (statusDiv) statusDiv.textContent = `Scraping... ${completed}/${gameUrls.length}`;
      });
      
      // Add random delay between batches to avoid rate limiting
      await new Promise(resolve => setTimeout(resolve, Math.random() * 1000));
    }
    
    if (progressBar) progressBar.value = gameUrls.length;
    if (progressText) progressText.textContent = `${gameUrls.length}/${gameUrls.length}`;
    if (progressContainer) progressContainer.style.display = 'none';
    
    if (hasErrors && !isCancelled) {
      showNotification('Some games failed to scrape. Check console for details.', 'error');
      retryBtn.style.display = 'inline-block';
    }
    
    // Display results if not cancelled
    if (!isCancelled) {
      displayResults();
      if (Object.keys(gamesData).length === 0) {
        if (resultsDiv) resultsDiv.textContent = 'No matching games found.';
      } else {
        // Check data size before saving to localStorage
        const dataString = JSON.stringify(gamesData);
        if (dataString.length > 5e6) { // 5MB limit
          showNotification('Data too large for cache. Results not saved.', 'error');
        } else {
          localStorage.setItem('gamesData', dataString);
          console.log('Saved results to cache');
        }
      }
    }
    
    // Show status message
    if (isCancelled) {
      if (statusDiv) statusDiv.textContent = 'Scan cancelled.';
    } else {
      const duration = Math.round((Date.now() - startTime) / 1000);
      if (statusDiv) showStatus(`Scan completed successfully in ${duration} seconds!`);
    }
    
    setButtonsDuringScan(false);
  }

  function cancelScan() {
    isCancelled = true;
    setButtonsDuringScan(false);
    if (statusDiv) statusDiv.textContent = 'Cancelling...';
  }

  function clearCache() {
    localStorage.removeItem('gamesData');
    gamesData = {};
    resultsDiv.innerHTML = '';
    if (statusDiv) statusDiv.textContent = 'Cache cleared. Click "Start Scraping" to begin.';
    console.log('Cache cleared');
  }

  function retryScraper() {
    retryBtn.style.display = 'none';
    runScraper();
  }

  // Load cached results on start
  displayCachedResults();
  setButtonsDuringScan(false); // Ensure buttons are enabled initially

  // Discord link
  discordLink.addEventListener('click', () => {
    shell.openExternal('https://discord.gg/nj45kDSBEd');
  });

  // Search functionality
  searchInput.addEventListener('input', () => {
    const query = searchInput.value.toLowerCase();
    const cards = document.querySelectorAll('.game-card');
    cards.forEach(card => {
      const title = card.querySelector('.game-title').textContent.toLowerCase();
      card.style.display = title.includes(query) ? 'block' : 'none';
    });
  });

  // Modal close
  closeBtn.addEventListener('click', () => {
    modal.style.display = 'none';
  });

  window.addEventListener('click', (event) => {
    if (event.target === modal) {
      modal.style.display = 'none';
    }
  });

  scrapeBtn.addEventListener('click', () => {
    console.log('Button clicked');
    runScraper();
  });
  if (cancelBtn) cancelBtn.addEventListener('click', cancelScan);
  if (clearCacheBtn) clearCacheBtn.addEventListener('click', clearCache);
  if (retryBtn) retryBtn.addEventListener('click', retryScraper);
});