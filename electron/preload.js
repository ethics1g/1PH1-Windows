/**
 * Preload — safe IPC bridge between renderer (web app) and main process.
 * Exposes `window.pharmaDesktop` in the renderer without leaking Node.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pharmaDesktop', {
  isDesktop: true,
  platform: process.platform,

  /* Printing --------------------------------------------------------- */
  print: {
    /** Print raw HTML on A4 (or default paper). `silent` skips the dialog. */
    a4: (html, opts = {}) => ipcRenderer.invoke('print:a4', { html, ...opts }),

    /** Print a thermal receipt via ESC/POS.
     * @param {Array} data electron-pos-printer schema — an array of
     *   { type: 'text'|'image'|'qrCode'|'barCode'|'divider'|'table',
     *     value, style, css }
     * @param {Object} options { printerName?, copies?, pageSize? } */
    thermal: (data, options = {}) => ipcRenderer.invoke('print:thermal', { data, options }),
  },

  /* Printers --------------------------------------------------------- */
  listPrinters: () => ipcRenderer.invoke('printers:list'),

  /* Settings --------------------------------------------------------- */
  settings: {
    get: (key) => ipcRenderer.invoke('settings:get', key),
    set: (key, value) => ipcRenderer.invoke('settings:set', key, value),
    all: () => ipcRenderer.invoke('settings:all'),
  },
});
