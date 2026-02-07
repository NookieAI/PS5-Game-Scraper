const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  store: {
    get: (key) => ipcRenderer.invoke('store:get', key),
    set: (key, value) => ipcRenderer.invoke('store:set', key, value),
    delete: (key) => ipcRenderer.invoke('store:delete', key),
    clear: () => ipcRenderer.invoke('store:clear'),
    getSettings: () => ipcRenderer.invoke('store:getSettings'),
    setSetting: (key, value) => ipcRenderer.invoke('store:setSetting', key, value),
    setSettings: (settings) => ipcRenderer.invoke('store:setSettings', settings),
  },
  fetchGameList: (url, timeout) => ipcRenderer.invoke('fetch:gameList', url, timeout),
  fetchRSS: (url) => ipcRenderer.invoke('fetch:rss', url),
  scrapeGamePage: (url, title) => ipcRenderer.invoke('fetch:gamePage', url, title),
  openExternal: (url) => ipcRenderer.invoke('open:external', url),
  showDesktopNotification: (title, body) => {
    try {
      new window.Notification(title, { body: body });
    } catch (e) {
      console.warn('Desktop notification failed:', e.message);
    }
  },
});