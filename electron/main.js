/**
 * 1PH1 Pharmacy POS — Electron Main Process (v1.2.0 — offline shell)
 * =============================================================================
 *
 * ARCHITECTURE (v1.2.0):
 *   • The full Expo web bundle is exported at build time with
 *     `EXPO_PUBLIC_BACKEND_URL=https://pharma-checkout-8.emergent.host` and
 *     shipped inside `electron/webapp/`.
 *   • Electron serves those files locally via a custom `app://` protocol.
 *     No preview URL is ever hit at runtime.
 *   • All API calls made by the bundled frontend go DIRECTLY to the
 *     production backend (baked-in at export time), so Windows and
 *     Android use exactly the same MongoDB database — always.
 *   • No boot-up "wake the preview" splash, no 6000 ms timeout error.
 *
 * The `app://` scheme is treated by Chromium as a first-class HTTPS-like
 * origin, which:
 *   - resolves absolute paths (`/_expo/static/js/...`) correctly,
 *   - satisfies expo-router history routing without a real HTTP server,
 *   - is a "standard, secure, CORS-enabled" scheme so fetch() to
 *     `https://pharma-checkout-8.emergent.host/api/*` works with CORS
 *     headers the backend already returns.
 */
const {
  app, BrowserWindow, Menu, ipcMain, shell, dialog,
  session, protocol, net,
} = require('electron');
const path = require('path');
const fs = require('fs');
const url = require('url');
const Store = require('electron-store');
const { PosPrinter } = require('electron-pos-printer');

// ---------------- Register the app:// scheme as privileged BEFORE app.ready.
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'app',
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
      allowServiceWorkers: true,
      stream: true,
    },
  },
]);

// ---------------- Logging (file + console) ----------------
const LOG_DIR = path.join(app.getPath('userData'), 'logs');
try { fs.mkdirSync(LOG_DIR, { recursive: true }); } catch { /* noop */ }
const LOG_FILE = path.join(LOG_DIR, 'main.log');
function log(...args) {
  const line = `[${new Date().toISOString()}] ${args
    .map(a => (typeof a === 'string' ? a : JSON.stringify(a))).join(' ')}\n`;
  try { fs.appendFileSync(LOG_FILE, line); } catch { /* noop */ }
  // eslint-disable-next-line no-console
  console.log(line.trim());
}
process.on('uncaughtException', (e) => log('uncaughtException', e && e.stack || e));
process.on('unhandledRejection', (e) => log('unhandledRejection', e && e.stack || e));

// ---------------- Bundled web-app directory ----------------
// When packaged by electron-builder with `asar: true`, this points inside
// the .asar archive (Electron transparently reads from asar via `fs`).
const WEBAPP_DIR = path.join(__dirname, 'webapp');
const INDEX_FILE = path.join(WEBAPP_DIR, 'index.html');
const PRODUCTION_API_URL = 'https://pharma-checkout-8.emergent.host';

// ---------------- Persistent settings ----------------
const store = new Store({
  name: 'pharma-checkout-settings',
  defaults: {
    thermalPrinterName: '',
    thermalPageSize: '80mm',
    a4PrinterName: '',
    kickCashDrawer: false,
    winBounds: { width: 1400, height: 900 },
    zoomFactor: 1.0,
    schemaVersion: 2,   // v2 = offline shell (no preview URL)
  },
});
// v1.x → v2 migration: drop any leftover URL settings.
try {
  if ((store.get('schemaVersion') || 0) < 2) {
    store.delete('frontendUrl');
    store.delete('productionApiUrl');
    store.set('schemaVersion', 2);
  }
} catch { /* noop */ }

let mainWindow = null;

// ---------------- Custom `app://` protocol handler ----------------
// Every request to `app://index.html/...` is served from `webapp/`.
// Unknown paths (e.g. deep expo-router routes on cold start) fall back to
// index.html so the SPA can hydrate and route client-side.
function registerAppProtocol() {
  session.defaultSession.protocol.handle('app', async (request) => {
    try {
      const parsed = new URL(request.url);
      // Ignore host component — we always serve from WEBAPP_DIR.
      let pathname = decodeURIComponent(parsed.pathname || '/');
      // Prevent path traversal.
      pathname = path.posix.normalize(pathname).replace(/^\/+/, '');
      let filePath = path.join(WEBAPP_DIR, pathname);
      // If the request has no extension or the file doesn't exist, try:
      //   1. `path/index.html`     (folder routes)
      //   2. `path.html`           (expo-router file-based routes)
      //   3. fallback to /index.html (SPA hydration entry)
      if (!pathname || pathname === '/' || pathname === '') {
        filePath = INDEX_FILE;
      } else if (!fs.existsSync(filePath)) {
        const asIndex = path.join(WEBAPP_DIR, pathname, 'index.html');
        const asHtml  = path.join(WEBAPP_DIR, `${pathname.replace(/\/$/, '')}.html`);
        if      (fs.existsSync(asIndex)) filePath = asIndex;
        else if (fs.existsSync(asHtml))  filePath = asHtml;
        else                             filePath = INDEX_FILE;
      }
      // Guarantee we stay inside WEBAPP_DIR (defence in depth).
      const resolved = path.resolve(filePath);
      if (!resolved.startsWith(path.resolve(WEBAPP_DIR))) {
        return new Response('403 forbidden', { status: 403 });
      }
      return net.fetch(url.pathToFileURL(resolved).toString());
    } catch (e) {
      log('app:// handler error:', e && e.message);
      return new Response(`internal error: ${e && e.message}`, { status: 500 });
    }
  });
  log('Registered app:// protocol handler, WEBAPP_DIR =', WEBAPP_DIR);
}

// ---------------- Window creation ----------------
async function createWindow() {
  const bounds = store.get('winBounds');
  mainWindow = new BrowserWindow({
    width:  bounds.width  || 1400,
    height: bounds.height || 900,
    x: Number.isInteger(bounds.x) ? bounds.x : undefined,
    y: Number.isInteger(bounds.y) ? bounds.y : undefined,
    minWidth: 1024,
    minHeight: 720,
    title: '1PH1 — Pharmacy POS',
    backgroundColor: '#0f172a',
    icon: fs.existsSync(path.join(__dirname, 'assets', 'icon.ico'))
      ? path.join(__dirname, 'assets', 'icon.ico') : undefined,
    autoHideMenuBar: false,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      spellcheck: false,
      webSecurity: true,
    },
  });

  const persistBounds = () => {
    try { store.set('winBounds', mainWindow.getBounds()); } catch { /* noop */ }
  };
  mainWindow.on('close', persistBounds);
  mainWindow.on('resized', persistBounds);
  mainWindow.on('moved', persistBounds);

  mainWindow.webContents.on('did-finish-load', () => {
    const z = store.get('zoomFactor') || 1.0;
    try { mainWindow.webContents.setZoomFactor(z); } catch { /* noop */ }
  });
  mainWindow.webContents.on('zoom-changed', (_e, dir) => {
    const curr = mainWindow.webContents.getZoomFactor();
    const next = Math.max(0.5, Math.min(2.5, curr + (dir === 'in' ? 0.1 : -0.1)));
    mainWindow.webContents.setZoomFactor(next);
    store.set('zoomFactor', next);
  });

  // Load the LOCAL bundled index page — no network, no preview URL.
  try {
    await mainWindow.loadURL('app://local/index.html');
    mainWindow.show();
  } catch (e) {
    log('loadURL app:// failed:', e && e.message);
    dialog.showErrorBox(
      'خطأ في تحميل التطبيق',
      `فشل تحميل الواجهة المحلية.\n\n${e && e.message}\n\n`
      + 'أعد تثبيت التطبيق. ملف السجل: ' + LOG_FILE,
    );
    mainWindow.show();
    return;
  }

  // External links open in default browser.
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    shell.openExternal(target);
    return { action: 'deny' };
  });

  // Prevent navigation away from the app:// origin (except to the
  // production API, which is fetched — not navigated to).
  mainWindow.webContents.on('will-navigate', (e, target) => {
    try {
      const t = new URL(target);
      if (t.protocol !== 'app:') {
        e.preventDefault();
        shell.openExternal(target);
      }
    } catch { /* noop */ }
  });

  mainWindow.on('focus', () => {
    try { mainWindow.webContents.focus(); } catch { /* noop */ }
  });

  // POS-friendly key shortcuts — scoped to this window.
  mainWindow.webContents.on('before-input-event', (e, input) => {
    if (input.type !== 'keyDown') return;
    const goto = (route) => { e.preventDefault(); navigate(route); };
    switch (input.key) {
      case 'F2': return goto('/sell');
      case 'F3': return goto('/buy');
      case 'F4': return goto('/inventory');
      case 'F5': {
        if (input.control || input.meta) return; // Ctrl+F5 = reload
        return goto('/customers');
      }
      case 'F6': return goto('/accounting');
      case 'F7': return goto('/pharmacy-orders');
      case 'F8': return goto('/suppliers');
    }
    if ((input.control || input.meta) && !input.shift && !input.alt) {
      if (input.key.toLowerCase() === 'h') return goto('/home');
      if (input.key === ',')               return goto('/settings/desktop');
    }
  });

  if (process.env.ELECTRON_DEV === '1') {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }
}

// ---------------- Renderer navigation helper ----------------
function navigate(route) {
  if (!mainWindow) return;
  mainWindow.webContents.executeJavaScript(`
    (function () {
      try {
        var ev = new CustomEvent('desktop-navigate', { detail: ${JSON.stringify(route)} });
        window.dispatchEvent(ev);
      } catch (e) {}
      try {
        history.pushState({}, '', ${JSON.stringify(route)});
        window.dispatchEvent(new PopStateEvent('popstate'));
      } catch (e) {}
    })();
  `).catch(() => {});
  mainWindow.focus();
}

// ---------------- Native application menu (Arabic RTL) ----------------
function buildMenu() {
  const nav = (route) => () => navigate(route);
  const template = [
    {
      label: 'الملف',
      submenu: [
        { label: 'الرئيسية',   accelerator: 'Ctrl+H', click: nav('/home') },
        { type: 'separator' },
        { label: 'الإعدادات',   accelerator: 'Ctrl+,', click: nav('/settings/desktop') },
        { type: 'separator' },
        { role: 'quit', label: 'خروج' },
      ],
    },
    {
      label: 'العمليات',
      submenu: [
        { label: 'بيع (F2)',        accelerator: 'F2', click: nav('/sell') },
        { label: 'شراء (F3)',       accelerator: 'F3', click: nav('/buy') },
        { label: 'المخزن (F4)',      accelerator: 'F4', click: nav('/inventory') },
        { label: 'الزبائن (F5)',     accelerator: 'F5', click: nav('/customers') },
        { label: 'المحاسبة (F6)',    accelerator: 'F6', click: nav('/accounting') },
        { label: 'طلباتي (F7)',      accelerator: 'F7', click: nav('/pharmacy-orders') },
        { label: 'المذاخر (F8)',     accelerator: 'F8', click: nav('/suppliers') },
      ],
    },
    {
      label: 'عرض',
      submenu: [
        { role: 'reload',           label: 'إعادة تحميل' },
        { role: 'forceReload',      label: 'إعادة تحميل قسرية' },
        { role: 'toggleDevTools',   label: 'أدوات المطوّر' },
        { type: 'separator' },
        { role: 'resetZoom',        label: 'حجم افتراضي' },
        { role: 'zoomIn',           label: 'تكبير' },
        { role: 'zoomOut',          label: 'تصغير' },
        { type: 'separator' },
        { role: 'togglefullscreen', label: 'ملء الشاشة' },
      ],
    },
    {
      label: 'الطابعة',
      submenu: [
        { label: 'طباعة صفحة اختبار حرارية', click: async () => {
          try { await printTestReceipt(); dialog.showMessageBox({ type: 'info', message: 'تمّت الطباعة بنجاح.' }); }
          catch (e) { dialog.showErrorBox('فشل الطباعة', e.message || String(e)); }
        } },
        { label: 'فتح درج الكاش', click: async () => {
          try { await kickCashDrawer(); dialog.showMessageBox({ type: 'info', message: 'تم إرسال أمر فتح الدرج.' }); }
          catch (e) { dialog.showErrorBox('فشل فتح الدرج', e.message || String(e)); }
        } },
      ],
    },
    {
      label: 'مساعدة',
      submenu: [
        { label: 'فتح ملف السجل', click: () => shell.openPath(LOG_FILE) },
        { label: 'مجلد الإعدادات', click: () => shell.openPath(app.getPath('userData')) },
        { type: 'separator' },
        { label: 'حول 1PH1', click: () => dialog.showMessageBox({
          type: 'info',
          title: 'حول 1PH1',
          message: '1PH1 — Pharmacy POS',
          detail: `الإصدار ${app.getVersion()}\nElectron ${process.versions.electron}\n`
                + `خادم الإنتاج: ${PRODUCTION_API_URL}\n`
                + 'نظام نقاط بيع للصيدليات مع محاسبة كاملة.',
        }) },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ---------------- Printing helpers ----------------
async function printTestReceipt() {
  const printerName = store.get('thermalPrinterName');
  if (!printerName) throw new Error('لم يتم ضبط الطابعة الحرارية. افتح الإعدادات.');
  const pageSize = store.get('thermalPageSize') || '80mm';
  const now = new Date().toLocaleString('ar-EG');
  await PosPrinter.print([
    { type: 'text', value: '1PH1 — صفحة اختبار', style: { fontSize: '14px', fontWeight: '900', textAlign: 'center' } },
    { type: 'text', value: now, style: { fontSize: '10px', textAlign: 'center' } },
    { type: 'divider' },
    { type: 'text', value: 'إذا ظهرت هذه الرسالة فالطابعة تعمل بشكل صحيح.', style: { fontSize: '11px', textAlign: 'right', direction: 'rtl' } },
    { type: 'text', value: `الطابعة: ${printerName}`, style: { fontSize: '10px', textAlign: 'right', direction: 'rtl' } },
    { type: 'text', value: `مقاس الورق: ${pageSize}`, style: { fontSize: '10px', textAlign: 'right', direction: 'rtl' } },
    { type: 'divider' },
    { type: 'text', value: 'شكراً — 1PH1', style: { fontSize: '11px', textAlign: 'center', marginTop: '4px' } },
  ], {
    preview: false, silent: true, printerName,
    margin: '0 0 0 0', copies: 1, timeOutPerLine: 400, pageSize,
  });
}

async function kickCashDrawer() {
  const printerName = store.get('thermalPrinterName');
  if (!printerName) throw new Error('لم يتم ضبط الطابعة الحرارية.');
  const pageSize = store.get('thermalPageSize') || '80mm';
  await PosPrinter.print([
    { type: 'text', value: '\x1B\x70\x00\x19\xFA', style: {} },
  ], {
    preview: false, silent: true, printerName,
    margin: '0 0 0 0', copies: 1, timeOutPerLine: 200, pageSize,
  });
}

// ---------------- IPC: renderer → main ----------------
ipcMain.handle('print:a4', async (_e, { html, silent = false, printerName = null }) => {
  const win = new BrowserWindow({
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  try {
    await win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
    const opts = {
      silent: !!silent, printBackground: true,
      deviceName: printerName || store.get('a4PrinterName') || undefined,
      margins: { marginType: 'default' },
    };
    return await new Promise((resolve, reject) => {
      win.webContents.print(opts, (ok, err) => (ok ? resolve(true) : reject(new Error(err || 'print failed'))));
    });
  } finally { try { win.close(); } catch { /* noop */ } }
});

ipcMain.handle('print:thermal', async (_e, { data, options = {} }) => {
  const printerName = options.printerName || store.get('thermalPrinterName');
  if (!printerName) throw new Error('لم يتم ضبط الطابعة الحرارية بعد. افتح الإعدادات.');
  const pageSize = options.pageSize || store.get('thermalPageSize') || '80mm';
  await PosPrinter.print(data, {
    preview: false, silent: true, margin: '0 0 0 0',
    copies: options.copies || 1, printerName, timeOutPerLine: 400, pageSize, ...options,
  });
  if (store.get('kickCashDrawer')) {
    try { await kickCashDrawer(); } catch (e) { log('cash drawer failed', e.message); }
  }
  return true;
});

ipcMain.handle('print:kickCashDrawer', () => kickCashDrawer());
ipcMain.handle('print:testThermal', () => printTestReceipt());

ipcMain.handle('settings:get', (_e, key) => store.get(key));
ipcMain.handle('settings:set', (_e, key, value) => { store.set(key, value); return true; });
ipcMain.handle('settings:all', () => store.store);
ipcMain.handle('settings:reset', () => { store.clear(); return true; });

ipcMain.handle('printers:list', async () => {
  if (!mainWindow) return [];
  try {
    const printers = await mainWindow.webContents.getPrintersAsync();
    return printers.map(p => ({
      name: p.name, displayName: p.displayName, description: p.description,
      isDefault: p.isDefault, status: p.status,
    }));
  } catch (e) { log('printers:list failed', e.message); return []; }
});

ipcMain.handle('app:info', () => ({
  version: app.getVersion(),
  electron: process.versions.electron,
  platform: process.platform,
  arch: process.arch,
  userData: app.getPath('userData'),
  logFile: LOG_FILE,
  productionApiUrl: PRODUCTION_API_URL,
  webappDir: WEBAPP_DIR,
}));
ipcMain.handle('app:openExternal', (_e, url) => shell.openExternal(url));
ipcMain.handle('app:openLogFile', () => shell.openPath(LOG_FILE));
ipcMain.handle('app:reload', () => { mainWindow && mainWindow.reload(); return true; });

// Live diagnostics: prove /api/* calls are hitting production and nothing else.
const API_REQUEST_LOG = [];
const MAX_API_LOG = 25;
let apiRequestCount = 0;
ipcMain.handle('diagnostics:redirects', () => ({
  rules: {
    frontendUrl: 'app://local/',
    productionOrigin: PRODUCTION_API_URL,
    productionApiUrl: PRODUCTION_API_URL,
    mode: 'offline-shell',   // v1.2.0
  },
  totalRedirected: apiRequestCount,
  recent: API_REQUEST_LOG.slice(-15),
}));

// ---------------- Lifecycle ----------------
app.setName('1PH1 POS');
app.commandLine.appendSwitch('lang', 'ar');

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    registerAppProtocol();

    // Passive observer of production API calls — used ONLY for the
    // in-app diagnostics panel. No rewriting happens; the bundle already
    // points at production.
    session.defaultSession.webRequest.onBeforeRequest(
      { urls: [`${PRODUCTION_API_URL}/api/*`] },
      (details, cb) => {
        try {
          const u = new URL(details.url);
          apiRequestCount++;
          if (API_REQUEST_LOG.length >= MAX_API_LOG) API_REQUEST_LOG.shift();
          API_REQUEST_LOG.push({
            n: apiRequestCount,
            at: new Date().toISOString(),
            method: details.method,
            from: details.url,
            to: details.url,   // same — for compatibility with old UI shape
          });
        } catch { /* noop */ }
        cb({});
      },
    );

    createWindow().catch((e) => log('createWindow failed', e));
    buildMenu();

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });
}
