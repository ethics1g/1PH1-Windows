/**
 * Preload — safe IPC bridge between renderer (web app) and main process.
 * Exposes `window.pharmaDesktop` in the renderer without leaking Node.
 *
 * The API is intentionally small and typed via /app/electron/src/print-helpers.ts
 * which is copied into the frontend as `src/desktop.ts`.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pharmaDesktop', {
  isDesktop: true,
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
  },

  /* Printing --------------------------------------------------------- */
  print: {
    /** Print raw HTML on A4 (or default paper). `silent` skips the dialog. */
    a4: (html, opts = {}) => ipcRenderer.invoke('print:a4', { html, ...opts }),

    /** Print a thermal receipt via ESC/POS.
     * @param {Array} data electron-pos-printer schema — an array of
     *   { type: 'text'|'image'|'qrCode'|'barCode'|'divider'|'table',
     *     value, style, css }
     * @param {Object} options { printerName?, copies?, pageSize? } */
    thermal: (data, options = {}) =>
      ipcRenderer.invoke('print:thermal', { data, options }),

    /** Test-page for the currently configured thermal printer. */
    testThermal: () => ipcRenderer.invoke('print:testThermal'),

    /** Kick the cash drawer via the receipt printer's ESC p command. */
    kickCashDrawer: () => ipcRenderer.invoke('print:kickCashDrawer'),
  },

  /* Printers --------------------------------------------------------- */
  listPrinters: () => ipcRenderer.invoke('printers:list'),

  /* Settings --------------------------------------------------------- */
  settings: {
    get: (key) => ipcRenderer.invoke('settings:get', key),
    set: (key, value) => ipcRenderer.invoke('settings:set', key, value),
    all: () => ipcRenderer.invoke('settings:all'),
    reset: () => ipcRenderer.invoke('settings:reset'),
  },

  /* App info / utilities --------------------------------------------- */
  app: {
    info: () => ipcRenderer.invoke('app:info'),
    openExternal: (url) => ipcRenderer.invoke('app:openExternal', url),
    openLogFile: () => ipcRenderer.invoke('app:openLogFile'),
    reload: () => ipcRenderer.invoke('app:reload'),
  },

  /* Diagnostics (live proof that /api/* is being redirected) ---------- */
  diagnostics: {
    redirects: () => ipcRenderer.invoke('diagnostics:redirects'),
  },
});
