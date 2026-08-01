/**
 * 1PH1 Pharmacy POS — Electron Main Process (v1.3.0 — loopback-http shell)
 * =============================================================================
 *
 * ARCHITECTURE (v1.3.0):
 *   • The full Expo web bundle is exported at build time with
 *     `EXPO_PUBLIC_BACKEND_URL=https://pharma-checkout-8.emergent.host` and
 *     shipped inside `electron/webapp/`.
 *   • On startup Electron boots a tiny loopback-only HTTP server on
 *     `127.0.0.1:<random-free-port>` that streams those files. The renderer
 *     loads `http://127.0.0.1:<port>/` — a first-class HTTP origin, so
 *     `@font-face`-based icon fonts (Ionicons, Feather, MaterialCommunity…)
 *     work reliably. Custom `app://` protocols silently blocked font
 *     loading, causing every icon to render as a ☐ box.
 *   • All API calls made by the bundled frontend go DIRECTLY to the
 *     production backend (baked-in at export time), so Windows and
 *     Android use exactly the same MongoDB database — always.
 *   • The HTTP server is bound to `127.0.0.1` only and is never exposed
 *     on the LAN. No boot-up "wake the preview" splash, no timeout error.
 */
const {
  app, BrowserWindow, Menu, ipcMain, shell, dialog,
  session,
} = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const Store = require('electron-store');
const { PosPrinter } = require('electron-pos-printer');

// Note: we intentionally do NOT use a custom `app://` protocol any more.
// Chromium blocks `@font-face` loading from non-standard schemes even with
// CORS headers set — this caused the pharmacy icons (Ionicons, Feather, …)
// to render as ☐ boxes on Windows. Instead we boot a tiny loopback-only
// HTTP server on 127.0.0.1:<random-free-port> and load the SPA from
// there. This gives us a fully-featured HTTP origin that Chromium treats
// as first-class, so fonts, service workers, and everything else "just
// work" without any special headers.

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

// ---------------- MIME-type map (file ext → Content-Type) ----------------
// Set the right Content-Type for every asset Expo emits — especially
// .ttf fonts, which browsers otherwise refuse to apply → icons ☐.
const MIME_TYPES = {
  '.html':  'text/html; charset=utf-8',
  '.htm':   'text/html; charset=utf-8',
  '.js':    'application/javascript; charset=utf-8',
  '.mjs':   'application/javascript; charset=utf-8',
  '.css':   'text/css; charset=utf-8',
  '.json':  'application/json; charset=utf-8',
  '.map':   'application/json; charset=utf-8',
  '.svg':   'image/svg+xml',
  '.png':   'image/png',
  '.jpg':   'image/jpeg',
  '.jpeg':  'image/jpeg',
  '.gif':   'image/gif',
  '.webp':  'image/webp',
  '.ico':   'image/x-icon',
  '.ttf':   'font/ttf',
  '.otf':   'font/otf',
  '.woff':  'font/woff',
  '.woff2': 'font/woff2',
  '.eot':   'application/vnd.ms-fontobject',
  '.wasm':  'application/wasm',
  '.txt':   'text/plain; charset=utf-8',
};
function mimeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  return MIME_TYPES[ext] || 'application/octet-stream';
}

// ---------------- Local HTTP server (loopback only) ----------------
// Serves the exported Expo web bundle over http://127.0.0.1:<port>/ so
// the renderer runs from a first-class HTTP origin. Bound to 127.0.0.1
// only — never exposed on the LAN.
//
// IMPORTANT — port MUST be stable across launches. Chromium binds
// `localStorage` (and therefore AsyncStorage / auth session) to the
// full origin, including the port. If we picked a random free port
// every launch, the origin would change → localStorage would be empty →
// the user would have to log in again on every app restart. We use a
// fixed high port (41871). If it is somehow already in use we try a
// deterministic small ladder so the origin still stays stable per
// machine (the OS almost never gives out this range to other apps).
let localServer = null;
let localServerPort = 0;
const WEBAPP_ROOT = path.resolve(WEBAPP_DIR);
const PREFERRED_PORTS = [41871, 41872, 41873, 41874, 41875];

function resolveWebappFile(rawPathname) {
  let pathname = decodeURIComponent(rawPathname || '/');
  pathname = pathname.split('?')[0].split('#')[0];
  pathname = path.posix.normalize(pathname).replace(/^\/+/, '');
  // Normalise `index.html` → root so expo-router matches the index route.
  if (pathname === 'index.html') pathname = '';
  if (!pathname) return INDEX_FILE;

  const direct   = path.join(WEBAPP_DIR, pathname);
  const asIndex  = path.join(WEBAPP_DIR, pathname, 'index.html');
  const asHtml   = path.join(WEBAPP_DIR, `${pathname.replace(/\/$/, '')}.html`);
  if (fs.existsSync(direct)  && fs.statSync(direct).isFile()) return direct;
  if (fs.existsSync(asIndex))                                 return asIndex;
  if (fs.existsSync(asHtml))                                  return asHtml;
  return INDEX_FILE;                                          // SPA fallback
}

function startLocalServer() {
  const tryListen = (port) => new Promise((resolve, reject) => {
    localServer = http.createServer((req, res) => {
      try {
        const parsed = new URL(req.url, 'http://127.0.0.1');
        const filePath = resolveWebappFile(parsed.pathname);
        // Defence in depth — never leak files outside WEBAPP_DIR.
        const resolved = path.resolve(filePath);
        if (!resolved.startsWith(WEBAPP_ROOT)) {
          res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
          res.end('403 forbidden');
          return;
        }
        const data = fs.readFileSync(resolved); // asar-transparent
        res.writeHead(200, {
          'Content-Type':   mimeFor(resolved),
          'Content-Length': data.length,
          'Cache-Control':  'no-cache',
          // Fonts are same-origin here (both page and .ttf are on
          // 127.0.0.1:<port>) so CORS is not strictly needed, but this
          // header is harmless and future-proofs cross-origin fetches.
          'Access-Control-Allow-Origin': '*',
        });
        res.end(data);
      } catch (e) {
        log('local-server error:', e && e.message, 'for', req.url);
        res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end('500 internal error');
      }
    });
    localServer.once('error', (err) => reject(err));
    // Bind to loopback only — never accept connections from the LAN.
    localServer.listen(port, '127.0.0.1', () => {
      localServerPort = localServer.address().port;
      log(`Local HTTP server listening on http://127.0.0.1:${localServerPort} (requested ${port})`);
      resolve(localServerPort);
    });
  });

  // Walk the preferred-port ladder so the origin stays stable across
  // launches → localStorage / auth session survives app restarts.
  return (async () => {
    for (const p of PREFERRED_PORTS) {
      try {
        return await tryListen(p);
      } catch (err) {
        log(`port ${p} unavailable: ${err && err.message}. Trying next…`);
      }
    }
    // Ladder exhausted — fall back to any free port (session will reset
    // on this rare unlucky launch, but the app still works).
    log('All preferred ports busy, falling back to OS-assigned port.');
    return await tryListen(0);
  })();
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

  // Load the LOCAL bundled SPA entry over a real HTTP loopback origin —
  // this is what makes @font-face-based vector icons work on Windows.
  // Custom protocols like app:// silently blocked font loading, showing
  // every icon as a ☐ box.
  try {
    if (!localServerPort) await startLocalServer();
    await mainWindow.loadURL(`http://127.0.0.1:${localServerPort}/`);
    mainWindow.show();
  } catch (e) {
    log('loadURL local server failed:', e && e.message);
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

  // Prevent navigation away from the local server origin (except to the
  // production API, which is fetched — not navigated to).
  mainWindow.webContents.on('will-navigate', (e, target) => {
    try {
      const t = new URL(target);
      const isLocal =
        t.protocol === 'http:' && t.hostname === '127.0.0.1'
        && t.port === String(localServerPort);
      if (!isLocal) {
        e.preventDefault();
        shell.openExternal(target);
      }
    } catch { /* noop */ }
  });

  mainWindow.on('focus', () => {
    try { mainWindow.webContents.focus(); } catch { /* noop */ }
  });

  // POS-friendly key shortcuts — scoped to this window.
  //
  // IMPORTANT: HID barcode scanners (very common in pharmacy POS setups)
  // emit their scans as a rapid burst of synthetic key events, and many
  // industrial scanners are pre-configured to send an F-key (typically
  // F8) as a prefix or suffix marker. That was silently triggering
  // "F8 → /suppliers" navigation mid-scan and stranding the user on the
  // suppliers screen with a broken back stack.
  //
  // Fix: disable F-key global shortcuts on the small set of routes where
  // barcodes are actually scanned. Users on those screens still navigate
  // via the top menu bar (الملف / العمليات …) or Ctrl+H → Home. On
  // every other screen (dashboards, accounting, settings…) F2–F8 keep
  // working exactly as before.
  const SCANNER_ROUTES = ['/sell', '/buy', '/inventory', '/orders', '/returns'];
  const isOnScannerRoute = () => {
    try {
      const u = new URL(mainWindow.webContents.getURL());
      const p = u.pathname || '/';
      return SCANNER_ROUTES.some((r) => p === r || p.startsWith(r + '/'));
    } catch { return false; }
  };

  mainWindow.webContents.on('before-input-event', (e, input) => {
    if (input.type !== 'keyDown') return;

    // Never hijack F-keys while the user is on a scanner-heavy screen —
    // this is the fix for the "scanner → Suppliers screen" bug.
    const isFKey = /^F([1-9]|1[0-2])$/.test(input.key || '');
    if (isFKey && isOnScannerRoute()) return;

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
      if ((input.key || '').toLowerCase() === 'h') return goto('/home');
      if (input.key === ',')                        return goto('/settings/desktop');
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
  //
  // IMPORTANT — DO NOT set `accelerator: 'F2'..'F8'` on any of the
  // navigation menu items. Native menu accelerators fire at the OS level
  // BEFORE any renderer-side handler, which means the URL-based scanner-
  // route guard in `before-input-event` was being completely bypassed
  // whenever the barcode scanner emitted an F-key (many HID scanners
  // send F8 as a burst prefix/suffix). Result: mid-scan navigation to
  // /suppliers with a broken back stack.
  //
  // We instead keep the F-key labels for user discoverability, but the
  // actual shortcut handling lives entirely in `before-input-event`,
  // where the guard on /sell, /buy, /inventory, /orders, /returns can
  // suppress F-keys during scanning. F-keys still work on every OTHER
  // screen (home, dashboards, accounting, …) because that same handler
  // does forward them there.
  //
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
        // NB: `accelerator:` deliberately omitted — see comment above.
        { label: 'بيع (F2)',        click: nav('/sell') },
        { label: 'شراء (F3)',       click: nav('/buy') },
        { label: 'المخزن (F4)',      click: nav('/inventory') },
        { label: 'الزبائن (F5)',     click: nav('/customers') },
        { label: 'المحاسبة (F6)',    click: nav('/accounting') },
        { label: 'طلباتي (F7)',      click: nav('/pharmacy-orders') },
        { label: 'المذاخر (F8)',     click: nav('/suppliers') },
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
    frontendUrl: localServerPort ? `http://127.0.0.1:${localServerPort}/` : '(not started)',
    productionOrigin: PRODUCTION_API_URL,
    productionApiUrl: PRODUCTION_API_URL,
    mode: 'loopback-http-shell',   // v1.3.0 (font-safe)
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

  app.whenReady().then(async () => {
    // Boot the loopback HTTP server that hosts the exported Expo bundle.
    // Must complete BEFORE we open the window, so loadURL has a live port.
    try {
      await startLocalServer();
    } catch (e) {
      log('startLocalServer failed:', e && e.message);
      dialog.showErrorBox(
        'خطأ في تشغيل التطبيق',
        `فشل تشغيل خادم الواجهة المحلية.\n\n${e && e.message}\n\n`
        + 'أعد تثبيت التطبيق. ملف السجل: ' + LOG_FILE,
      );
      app.quit();
      return;
    }

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
    try { if (localServer) localServer.close(); } catch { /* noop */ }
    if (process.platform !== 'darwin') app.quit();
  });
}
