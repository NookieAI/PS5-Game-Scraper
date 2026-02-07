const { app, BrowserWindow, ipcMain, shell, Menu, Notification } = require('electron');
const path = require('path');
const axios = require('axios');
const cheerio = require('cheerio');
const Store = require('electron-store');

const store = new Store({
  name: 'ps5-scraper-data',
  defaults: {
    gamesData: {},
    favorites: [],
    settings: {
      maxGames: 0,
      autoScan: false,
      theme: 'dark',
      defaultSort: 'date',
      cacheDays: 0,
      hostOrder: ['akira', 'viking', 'onefichier', 'letsupload', 'mediafire', 'gofile', 'rootz', 'viki']
    }
  }
});

let mainWindow;

const MAX_SCREENSHOTS = 2;

const COMMON_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
  'Accept-Language': 'en-US,en;q=0.5',
};

function createWindow() {
  Menu.setApplicationMenu(null);

  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
      devTools: true
    },
    icon: path.join(__dirname, 'assets', 'icon1.ico'),
    show: false,
    autoHideMenuBar: true,
  });

  mainWindow.loadFile('index.html');
  mainWindow.once('ready-to-show', function () {
    mainWindow.maximize();
    mainWindow.show();
  });

  mainWindow.webContents.on('context-menu', function (e) {
    e.preventDefault();
  });

  mainWindow.on('closed', function () { mainWindow = null; });
}

app.on('ready', createWindow);
app.on('window-all-closed', function () { if (process.platform !== 'darwin') app.quit(); });
app.on('activate', function () { if (mainWindow === null) createWindow(); });

// ===== STORE IPC HANDLERS =====

ipcMain.handle('store:get', function (e, key) {
  try { return store.get(key); }
  catch (err) { console.error('Store read error:', err.message); return null; }
});

ipcMain.handle('store:set', function (e, key, value) {
  try { store.set(key, value); return true; }
  catch (err) { console.error('Store write error:', err.message); return false; }
});

ipcMain.handle('store:delete', function (e, key) {
  try { store.delete(key); return true; }
  catch (err) { console.error('Store delete error:', err.message); return false; }
});

ipcMain.handle('store:clear', function () {
  try { store.clear(); return true; }
  catch (err) { console.error('Store clear error:', err.message); return false; }
});

ipcMain.handle('store:getSettings', function () {
  try { return store.get('settings'); }
  catch (err) {
    console.error('Store settings read error:', err.message);
    return {
      maxGames: 0, autoScan: false, theme: 'dark', defaultSort: 'date',
      cacheDays: 0, hostOrder: ['akira', 'viking', 'onefichier', 'letsupload', 'mediafire', 'gofile', 'rootz', 'viki']
    };
  }
});

ipcMain.handle('store:setSetting', function (e, key, value) {
  try { store.set('settings.' + key, value); return true; }
  catch (err) { console.error('Store setting write error:', err.message); return false; }
});

ipcMain.handle('store:setSettings', function (e, settings) {
  try { store.set('settings', settings); return true; }
  catch (err) { console.error('Store settings write error:', err.message); return false; }
});

// ===== EXTERNAL LINK HANDLER =====

ipcMain.handle('open:external', function (event, url) {
  if (typeof url === 'string' && (url.indexOf('http://') === 0 || url.indexOf('https://') === 0)) {
    shell.openExternal(url);
    return true;
  }
  return false;
});

// ===== DESKTOP NOTIFICATION HANDLER =====

ipcMain.handle('show:notification', function (event, title, body) {
  try {
    if (Notification.isSupported()) {
      var notif = new Notification({ title: title || 'PS5 Game Scraper', body: body || '' });
      notif.show();
      return true;
    }
  } catch (e) {
    console.warn('Notification failed:', e.message);
  }
  return false;
});

// ===== SCRAPING HELPER FUNCTIONS =====

function extractVersion(text, href, contextText) {
  var m = (href || '').match(/[Vv_](\d{1,2}[._]\d{2,3})(?!\s*[GMKgmk][Bb])/);
  if (m) return m[1].replace('_', '.');
  m = (text || '').match(/[Vv][\s.:]*(\d{1,2}[._]\d{2,3})(?!\s*[GMKgmk][Bb])/);
  if (m) return m[1].replace('_', '.');
  m = (href || '').match(/(\d{1,2}\.\d{3})(?!\s*[GMKgmk][Bb])/);
  if (m) return m[1];
  if (contextText) {
    m = contextText.match(/[Vv][\s.:]*(\d{1,2}[._]\d{2,3})(?!\s*[GMKgmk][Bb])/);
    if (m) return m[1].replace('_', '.');
  }
  return '';
}

function extractFirmwareFromContext(text) {
  if (!text) return '';
  var m = text.match(/(?:fw|firmware)\s*[:.]?\s*(\d+(?:\.[xX\d]+)?)/i);
  if (m) return m[1];
  m = text.match(/fix\s*(?:for\s*)?(?:fw\s*)?(\d+(?:\.[xX\d]+)?)/i);
  if (m) return m[1];
  m = text.match(/backpor[tk]\s*(?:for\s*)?(?:fw\s*)?(\d+(?:\.[xX\d]+)?)/i);
  if (m) return m[1];
  return '';
}

function extractFirmwareFromUrl(href) {
  if (!href) return '';
  var m = href.match(/[_\/-](\d)[._](?:xx|\d{2})/i);
  if (m) return m[1];
  m = href.match(/(?:bp|fw|backport)[\s_-]?(\d)/i);
  if (m) return m[1];
  return '';
}

function looksLikeFirmware(ver) {
  if (!ver) return false;
  if (ver.match(/^\d\.[xX]+$/i)) return true;
  if (ver.match(/^\d$/)) return true;
  var num = parseFloat(ver);
  if (!isNaN(num) && num < 10 && !ver.match(/^0\d/)) return true;
  return false;
}

function identifyHost(href) {
  if (href.indexOf('akirabox.com') !== -1 || href.indexOf('akirabox') !== -1) return 'akira';
  if (href.indexOf('vikingfile.com') !== -1 || href.indexOf('vikingfile') !== -1) return 'viking';
  if (href.indexOf('1fichier.com') !== -1) return 'onefichier';
  if (href.indexOf('letsupload') !== -1) return 'letsupload';
  if (href.indexOf('mediafire') !== -1) return 'mediafire';
  if (href.indexOf('gofile') !== -1) return 'gofile';
  if (href.indexOf('rootz') !== -1) return 'rootz';
  if (href.indexOf('viki') !== -1 && href.indexOf('viking') === -1) return 'viki';
  return '';
}

function getTextBeforeLink($, el) {
  var parent = $(el).parent();
  if (!parent.length) return '';
  var html = parent.html();
  if (!html) return '';
  var outerHtml = $.html(el);
  var idx = html.indexOf(outerHtml);
  if (idx <= 0) return '';
  var before = html.substring(0, idx);
  var text = before.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  var lastClosingA = before.lastIndexOf('</a>');
  if (lastClosingA !== -1) {
    text = before.substring(lastClosingA + 4).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  }
  return text;
}

function getTypeFromPrecedingText(text) {
  if (!text) return '';
  var lower = text.toLowerCase();
  if (lower.match(/backpor[tk]/)) return 'backport';
  if (lower.match(/\bfix\b/)) return 'fix';
  if (lower.match(/\bupdate\b/)) return 'update';
  if (lower.match(/\bdlc\b/)) return 'dlc';
  if (lower.match(/\bgame\b/)) return 'game';
  return '';
}

// ===== GAME LIST FETCH =====

ipcMain.handle('fetch:gameList', async function (event, pageUrl, timeout) {
  try {
    var response = await axios.get(pageUrl, { timeout: timeout || 10000, headers: COMMON_HEADERS });
    var $ = cheerio.load(response.data);
    var games = [];
    var strategies = [
      { container: '.post', title: 'h2 a', date: '.publish-date, time, .entry-date, .post-date', cover: 'img' },
      { container: 'article', title: 'h2 a, h3 a, .entry-title a', date: 'time, .entry-date, .published, .post-date', cover: 'img, .post-thumbnail img' },
      { container: '.hentry, .entry, .type-post', title: 'h2 a, h3 a, .entry-title a', date: 'time, .entry-date, .published', cover: 'img' },
    ];
    for (var s = 0; s < strategies.length; s++) {
      var strat = strategies[s];
      var elements = $(strat.container);
      if (elements.length === 0) continue;
      elements.each(function (i, el) {
        var $p = $(el);
        var $l = $p.find(strat.title).first();
        var title = $l.text().trim() || $l.attr('title') || '';
        var url = $l.attr('href') || '';
        var $d = $p.find(strat.date).first();
        var date = $d.attr('datetime') || $d.text().trim() || '';
        var cover = $p.find(strat.cover).first().attr('src') || $p.find(strat.cover).first().attr('data-src') || '';
        if (title && url) games.push({ title: title.replace(/\s+/g, ' ').trim(), url: url, date: date, cover: cover });
      });
      if (games.length > 0) break;
    }
    return { success: true, games: games, error: null, endOfList: false };
  } catch (error) {
    var status = error.response ? error.response.status : null;
    if (status === 404) return { success: true, games: [], error: null, endOfList: true };
    return { success: false, games: [], endOfList: false, error: { url: pageUrl, message: error.message, code: error.code || null, status: status } };
  }
});

// ===== RSS FETCH =====

ipcMain.handle('fetch:rss', async function (event, rssUrl) {
  try {
    var response = await axios.get(rssUrl, { timeout: 30000, headers: COMMON_HEADERS });
    var $ = cheerio.load(response.data, { xmlMode: true });
    var rssData = {};
    $('item').each(function (i, el) {
      var title = $(el).find('title').text().trim();
      var link = $(el).find('link').text().trim();
      var pubDate = $(el).find('pubDate').text().trim();
      var cover = $(el).find('enclosure').attr('url') || '';
      var date = pubDate ? new Date(pubDate).toISOString().split('T')[0] : '';
      if (title && link) rssData[title] = { cover: cover, date: date, url: link };
    });
    return { success: true, data: rssData, error: null };
  } catch (error) {
    return { success: false, data: {}, error: { url: rssUrl, message: error.message, code: error.code || null, status: error.response ? error.response.status : null } };
  }
});

// ===== GAME PAGE SCRAPE =====

var scrapeLocksInProgress = new Map();

ipcMain.handle('fetch:gamePage', async function (event, gameUrl, gameTitle) {
  var key = gameTitle || gameUrl;
  while (scrapeLocksInProgress.has(key)) await scrapeLocksInProgress.get(key);
  var releaseLock;
  var lockPromise = new Promise(function (resolve) { releaseLock = resolve; });
  scrapeLocksInProgress.set(key, lockPromise);

  try {
    var response = await axios.get(gameUrl, { timeout: 30000, headers: COMMON_HEADERS });
    var $ = cheerio.load(response.data);
    var seenUrls = {};

    var pageText = $('.entry-content').text() || '';
    var globalVersionMatch = pageText.match(/[Vv][\s.:]*(\d{1,2}[._]\d{2,3})(?!\s*[GMKgmk][Bb])/);
    var globalVersion = globalVersionMatch ? globalVersionMatch[1].replace('_', '.') : '';

    var globalFirmware = '';
    var globalFwMatch = pageText.match(/(?:Working|Works)\s*(?:on)?\s*[:.]?\s*([\d]+(?:\.[\dxX]+)?)/i);
    if (globalFwMatch) {
      globalFirmware = globalFwMatch[1].trim();
      var gfwNum = globalFirmware.match(/(\d+)(?=\.[\dxX])/);
      if (gfwNum) globalFirmware = gfwNum[1] + '.xx';
    }

    var linkTypeMap = {};
    var linkFwMap = {};

    $('.entry-content').find('a[href]').each(function (i, el) {
      var href = $(el).attr('href');
      if (!href) return;
      if (!identifyHost(href)) return;
      var precedingText = getTextBeforeLink($, el);
      var detectedType = getTypeFromPrecedingText(precedingText);
      var detectedFw = extractFirmwareFromContext(precedingText);
      if (detectedType) linkTypeMap[href] = detectedType;
      if (detectedFw) linkFwMap[href] = detectedFw;
    });

    var sectionType = '';
    var sectionFw = '';
    $('.entry-content').children().each(function (i, el) {
      var txt = $(el).text().trim();
      var lower = txt.toLowerCase();
      var linksInEl = $(el).find('a[href]').length;
      var isHeader = (linksInEl === 0 && txt.length < 200) || lower.match(/^(game|update|fix|backpor[tk]|dlc)\b/i);
      if (isHeader) {
        if (lower.match(/backpor[tk]/i)) { sectionType = 'backport'; sectionFw = extractFirmwareFromContext(txt) || ''; }
        else if (lower.match(/\bfix\b/i)) { sectionType = 'fix'; sectionFw = extractFirmwareFromContext(txt) || ''; }
        else if (lower.match(/\bupdate\b/i)) { sectionType = 'update'; sectionFw = extractFirmwareFromContext(txt) || ''; }
        else if (lower.match(/\bdlc\b/i)) { sectionType = 'dlc'; sectionFw = ''; }
        else if (lower.match(/\bgame\b/i)) { sectionType = 'game'; sectionFw = ''; }
      }
      $(el).find('a[href]').each(function (j, aEl) {
        var h = $(aEl).attr('href');
        if (!h) return;
        if (!linkTypeMap[h] && sectionType) linkTypeMap[h] = sectionType;
        if (!linkFwMap[h] && sectionFw) linkFwMap[h] = sectionFw;
      });
    });

    var akiraLinks = [];
    var vikingLinks = [];
    var onefichierLinks = [];
    var otherLinks = [];

    $('a[href]').each(function (i, el) {
      var href = $(el).attr('href');
      if (!href) return;
      if (seenUrls[href]) return;
      seenUrls[href] = true;
      var host = identifyHost(href);
      if (!host) return;

      var linkText = $(el).text().trim() || '';
      var parentP = $(el).closest('p');
      var parentDiv = $(el).closest('div');
      var contextText = parentP.length ? parentP.text().trim().replace(/\s+/g, ' ') : '';
      if (!contextText && parentDiv.length) contextText = parentDiv.text().trim().replace(/\s+/g, ' ');
      var vt = contextText || linkText || 'Download Link';

      var sectionText = '';
      var prev = parentP.length ? parentP : $(el);
      for (var walk = 0; walk < 10; walk++) {
        prev = prev.prev();
        if (!prev.length) break;
        var prevText = prev.text().trim();
        if (prevText.match(/[Vv][\s.:]*\d{1,2}[._]\d{2,3}/) ||
            prevText.match(/fix\s*(?:for\s*)?(?:fw\s*)?\d+/i) ||
            prevText.match(/backpor[tk]/i) ||
            prevText.match(/(?:fw|firmware)\s*\d+/i)) {
          sectionText = prevText;
          break;
        }
      }

      var ver = extractVersion(vt, href, sectionText);
      if (!ver && globalVersion) ver = globalVersion;

      var fwVer = linkFwMap[href] || extractFirmwareFromContext(linkText) || extractFirmwareFromUrl(href);
      if (!fwVer && globalFirmware) fwVer = globalFirmware;

      var type = linkTypeMap[href] || '';
      if (!type) {
        var allText = (vt + ' ' + sectionText + ' ' + linkText).toLowerCase();
        if (allText.indexOf('dlc') !== -1) type = 'dlc';
        else if (allText.indexOf('update') !== -1) type = 'update';
        else if (allText.indexOf('backport') !== -1 || allText.indexOf('backpork') !== -1) type = 'backport';
        else if (allText.indexOf('fix') !== -1) type = 'fix';
        else type = 'game';
      }

      if ((type === 'backport' || type === 'fix') && ver && !fwVer && looksLikeFirmware(ver)) {
        fwVer = ver;
        ver = '';
      }
      if (type === 'game' && fwVer && looksLikeFirmware(fwVer)) {
        if (globalFirmware && fwVer !== globalFirmware.replace('.xx', '')) {
          fwVer = globalFirmware;
        }
      }

      var ld = { link: href, host: host, version: vt, extractedVersion: ver, extractedFirmware: fwVer, type: type };
      if (host === 'akira') akiraLinks.push(ld);
      else if (host === 'viking') vikingLinks.push(ld);
      else if (host === 'onefichier') onefichierLinks.push(ld);
      else otherLinks.push(ld);
    });

    var title = $('title').text() || '';
    var metaDesc = $('meta[name="description"]').attr('content') || '';
    var cover = $('meta[property="og:image"]').attr('content') || '';
    var voice = (title.match(/Voice\s*:\s*([^|]+)/) || [null, ''])[1] || '';
    voice = voice.trim();
    var subtitles = (title.match(/Subtitles?\s*:\s*([^|]+)/) || [null, ''])[1] || '';
    subtitles = subtitles.trim();
    var notes = (title.match(/Note\s*:\s*([^|]+)/) || [null, ''])[1] || '';
    notes = notes.trim();
    var size = (title.match(/Size\s*:\s*([^|]+)/) || [null, ''])[1] || '';
    size = size.trim();
    var fullContent = $('.entry-content').text();

    var firmware = '';
    var fwMatch = fullContent.match(/(?:Working|Works)\s*(?:on)?\s*[:.]?\s*([\d]+(?:\.[\dxX]+)?(?:\s*[-\u2013]\s*[\d]+(?:\.[\dxX]+)?)?)/i);
    if (fwMatch) {
      firmware = fwMatch[1].trim();
      var fwNumbers = firmware.match(/(\d+)(?=\.[\dxX])/g);
      if (fwNumbers && fwNumbers.length > 0) {
        var nums = fwNumbers.map(function (n) { return parseInt(n, 10); });
        var maxFw = Math.max.apply(null, nums);
        firmware = maxFw + '.xx';
      }
    }

    var description = metaDesc || '';
    var password = '';
    var pwMatch = fullContent.match(/password\s*[:=]\s*(\S+)/i);
    if (pwMatch) password = pwMatch[1];

    var screenLanguages = '';
    var langMatch = fullContent.match(/(?:screen\s*)?languages?\s*:\s*([^\n]+)/i);
    if (langMatch) screenLanguages = langMatch[1].trim();

    var guide = '';
    var guideMatch = fullContent.match(/(?:installation|install)\s*(?:guide|instructions?)\s*[:.]?\s*([\s\S]*?)(?=\n\s*\n|\bpassword\b|$)/i);
    if (guideMatch) guide = guideMatch[1].trim().substring(0, 500);

    var ppsa = '';
    var ppsaMatch = (title + ' ' + fullContent).match(/(PPSA\d+)/);
    if (ppsaMatch) ppsa = ppsaMatch[1];

    var date = '';
    var dateEl = $('time.entry-date, time.published, .post-date').first();
    if (dateEl.length) {
      date = dateEl.attr('datetime') || dateEl.text().trim() || '';
      try { date = new Date(date).toISOString().split('T')[0]; } catch (e) {}
    }

    // Collect screenshots — limit to MAX_SCREENSHOTS
    var screenshots = [];
    var seenScreenshots = {};
    $('.entry-content img').each(function (i, el) {
      if (screenshots.length >= MAX_SCREENSHOTS) return false; // break out of .each()
      var src = $(el).attr('src') || $(el).attr('data-src') || '';
      if (!src) return;
      if (seenScreenshots[src]) return;
      if (src === cover) return;
      if (src.match(/icon|logo|banner|avatar|badge|button|ad[_-]|sponsor/i)) return;
      var w = parseInt($(el).attr('width'), 10);
      var h = parseInt($(el).attr('height'), 10);
      if (w && w < 100) return;
      if (h && h < 100) return;
      seenScreenshots[src] = true;
      screenshots.push(src);
    });

    return {
      success: true,
      data: {
        akira: akiraLinks,
        viking: vikingLinks,
        onefichier: onefichierLinks,
        other: otherLinks,
        cover: cover,
        voice: voice,
        subtitles: subtitles,
        notes: notes,
        size: size,
        firmware: firmware,
        date: date,
        description: description,
        screenshots: screenshots,
        password: password,
        screenLanguages: screenLanguages,
        guide: guide,
        ppsa: ppsa
      }
    };
  } catch (error) {
    return {
      success: false,
      data: null,
      error: { url: gameUrl, message: error.message, code: error.code || null, status: error.response ? error.response.status : null }
    };
  } finally {
    scrapeLocksInProgress.delete(key);
    if (releaseLock) releaseLock();
  }
});