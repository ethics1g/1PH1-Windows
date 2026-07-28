/**
 * 1PH1 Pharmacy POS — Electron Main Process
 * =============================================================================
 * Wraps the deployed Expo web build in a native Windows window and adds:
 *   • Keyboard shortcuts optimised for POS workflow (F2/F3/F4/…)
 *     Scoped to the window via `before-input-event` — does NOT hijack the
 *     key globally across the OS.
 *   • A safe IPC bridge to the renderer for receipt printing (thermal + A4)
 *     with cash-drawer kick and printer test-pages.
 *   • Persistent settings via electron-store (backend URL, printer config,
 *     zoom level, window bounds).
 *   • First-run URL setup dialog + automatic reload on transient network
 *     failures so a barcode-only cashier is never stuck on a blank window.
 *   • Rotating log file at %APPDATA%/1PH1 POS/logs/main.log.
 *
 * The FastAPI backend + MongoDB continue to run on Emergent — this app is
 * purely a desktop shell for the existing Expo web frontend.
 */
const {
  app, BrowserWindow, Menu, ipcMain, shell, dialog,
  session,
} = require('electron');
const path = require('path');
const fs = require('fs');
const Store = require('electron-store');
const { PosPrinter } = require('electron-pos-printer');

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

// ---------------- Persistent settings ----------------
const store = new Store({
  name: 'pharma-checkout-settings',
  defaults: {
    // Deployed frontend URL. Users configure this once via the first-run
    // dialog OR the in-app settings screen.
    frontendUrl: process.env.PHARMA_FRONTEND_URL || '',
    // Thermal printer name (exactly as it appears in Windows Devices & Printers)
    thermalPrinterName: '',
    // Thermal paper size: '58mm' or '80mm'
    thermalPageSize: '80mm',
    // A4 printer name (empty = system default)
    a4PrinterName: '',
    // Kick cash drawer after each successful thermal print
    kickCashDrawer: false,
    // Window geometry
    winBounds: { width: 1400, height: 900 },
    // UI zoom (1.0 = 100%)
    zoomFactor: 1.0,
  },
});

const PLACEHOLDER_URLS = [
  '', 'https://YOUR-APP.emergent.host',
  'https://your-app.emergent.host', 'about:blank',
];

let mainWindow = null;

// ---------------- First-run URL prompt ----------------
async function ensureFrontendUrl() {
  let url = (store.get('frontendUrl') || '').trim();
  while (PLACEHOLDER_URLS.includes(url) || !/^https?:\/\//i.test(url)) {
    const r = await dialog.showMessageBox({
      type: 'question',
      title: 'إعداد أول مرة — 1PH1 POS',
      message: 'أدخل رابط الخادم (Frontend URL)',
      detail: [
        'مثال:  https://pharma-checkout-8.emergent.host',
        '',
        'يمكنك تغييره لاحقاً من: الملف ← الإعدادات',
      ].join('\n'),
      buttons: ['فتح ملف الإعدادات يدوياً', 'خروج'],
      defaultId: 0, cancelId: 1,
      noLink: true,
    });
    if (r.response === 1) { app.quit(); return null; }
    // Open the settings JSON in the default editor so the user can paste
    // the URL. Windows-friendly: `shell.openPath` uses ShellExecute.
    const configPath = path.join(app.getPath('userData'), 'pharma-checkout-settings.json');
    try {
      if (!fs.existsSync(configPath)) {
        fs.writeFileSync(configPath, JSON.stringify(store.store, null, 2));
      }
      await shell.openPath(configPath);
    } catch (e) { log('openPath failed', e.message); }
    // Wait for the user to close the dialog & re-check.
    await dialog.showMessageBox({
      type: 'info',
      title: '1PH1 POS',
      message: 'اضغط "استمرار" بعد حفظ رابط الخادم في ملف الإعدادات.',
      buttons: ['استمرار'],
    });
    // Re-read from disk in case user edited it externally
    url = (store.get('frontendUrl') || '').trim();
  }
  return url;
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
    show: false,   // show after content is ready to avoid white flash
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,       // needed for electron-pos-printer sub-window
      spellcheck: false,
      // Disable navigation to file:// URLs after load
      webSecurity: true,
    },
  });

  // Persist window geometry across sessions.
  const persistBounds = () => {
    try { store.set('winBounds', mainWindow.getBounds()); } catch { /* noop */ }
  };
  mainWindow.on('close', persistBounds);
  mainWindow.on('resized', persistBounds);
  mainWindow.on('moved', persistBounds);

  // Restore persisted zoom.
  mainWindow.webContents.on('did-finish-load', () => {
    const z = store.get('zoomFactor') || 1.0;
    try { mainWindow.webContents.setZoomFactor(z); } catch { /* noop */ }
  });
  // Ctrl+scroll → adjust zoom & persist.
  mainWindow.webContents.on('zoom-changed', (_e, dir) => {
    const curr = mainWindow.webContents.getZoomFactor();
    const next = Math.max(0.5, Math.min(2.5, curr + (dir === 'in' ? 0.1 : -0.1)));
    mainWindow.webContents.setZoomFactor(next);
    store.set('zoomFactor', next);
  });

  const url = await ensureFrontendUrl();
  if (!url) return;

  const loadWithRetry = async (attempt = 1) => {
    try {
      await mainWindow.loadURL(url);
      mainWindow.show();
    } catch (err) {
      log(`Load attempt ${attempt} failed:`, err && err.message);
      if (attempt >= 5) {
        dialog.showErrorBox(
          'تعذّر الاتصال بالخادم',
          `فشل تحميل الرابط:\n${url}\n\n${err && err.message || ''}\n\n` +
          'افتح الإعدادات (Ctrl+,) وتحقق من عنوان الخادم وحالة الشبكة.',
        );
        mainWindow.show();
        return;
      }
      // Exponential backoff: 1s, 2s, 4s, 8s, 16s
      await new Promise((r) => setTimeout(r, 1000 * Math.pow(2, attempt - 1)));
      await loadWithRetry(attempt + 1);
    }
  };
  await loadWithRetry();

  // Open external links in the user's default browser instead of a new
  // Electron window (safer + more professional).
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    shell.openExternal(target);
    return { action: 'deny' };
  });

  // Prevent navigation away from the configured frontend URL.
  mainWindow.webContents.on('will-navigate', (e, target) => {
    try {
      const currentHost = new URL(url).host;
      const targetHost = new URL(target).host;
      if (currentHost !== targetHost) {
        e.preventDefault();
        shell.openExternal(target);
      }
    } catch { /* noop */ }
  });

  // On focus, make sure the webContents receives keyboard events. The
  // frontend already ships a document-level `useExternalScanner` listener
  // (see /app/frontend/src/externalScanner.tsx) that captures HID scanner
  // bursts globally, so nothing else is required for barcode input.
  mainWindow.on('focus', () => {
    try { mainWindow.webContents.focus(); } catch { /* noop */ }
  });

  // POS-friendly key shortcuts (scoped to this window — never hijack keys OS-wide).
  mainWindow.webContents.on('before-input-event', (e, input) => {
    if (input.type !== 'keyDown') return;
    const goto = (route) => {
      e.preventDefault();
      navigate(route);
    };
    // F-keys are typically not typed into inputs, safe to intercept always.
    switch (input.key) {
      case 'F2': return goto('/sell');
      case 'F3': return goto('/buy');
      case 'F4': return goto('/inventory');
      case 'F5': {
        // If pure F5 without modifiers → treat as "customers" screen, but
        // Ctrl+F5 keeps its native "reload" meaning.
        if (input.control || input.meta) return; // reload
        return goto('/customers');
      }
      case 'F6': return goto('/accounting');
      case 'F7': return goto('/pharmacy-orders');
      case 'F8': return goto('/suppliers');
    }
    // Ctrl+H → home,  Ctrl+, → desktop settings (matches Menu accelerators)
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
// The frontend hooks a `desktop-navigate` custom event that maps to
// `router.replace(route)` inside app/_layout.tsx (see /app/frontend/src/desktop.ts).
// Falling back to history.pushState + popstate keeps the wrapper working
// even if the frontend hasn't wired the custom event yet.
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
          try {
            await printTestReceipt();
            dialog.showMessageBox({ type: 'info', message: 'تمّت الطباعة بنجاح.' });
          } catch (e) {
            dialog.showErrorBox('فشل الطباعة', e.message || String(e));
          }
        } },
        { label: 'فتح درج الكاش', click: async () => {
          try {
            await kickCashDrawer();
            dialog.showMessageBox({ type: 'info', message: 'تم إرسال أمر فتح الدرج.' });
          } catch (e) {
            dialog.showErrorBox('فشل فتح الدرج', e.message || String(e));
          }
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
          detail: `الإصدار ${app.getVersion()}\nElectron ${process.versions.electron}\nنظام نقاط بيع للصيدليات مع محاسبة كاملة.`,
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

// ESC/POS cash-drawer kick — command is `ESC p 0 25 250`. Sent by writing
// raw bytes to a dedicated tiny thermal print job (works with most drawers
// wired via RJ11/RJ12 to a receipt printer).
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

// ---------------- IPC: renderer → main (printing + settings) ----------------

// Standard A4 print — silent (no dialog) if `silent: true` is passed.
ipcMain.handle('print:a4', async (_e, { html, silent = false, printerName = null }) => {
  const win = new BrowserWindow({
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  try {
    await win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
    const opts = {
      silent: !!silent,
      printBackground: true,
      deviceName: printerName || store.get('a4PrinterName') || undefined,
      margins: { marginType: 'default' },
    };
    return await new Promise((resolve, reject) => {
      win.webContents.print(opts, (ok, err) => (ok ? resolve(true) : reject(new Error(err || 'print failed'))));
    });
  } finally {
    try { win.close(); } catch { /* noop */ }
  }
});

// Thermal ESC/POS print — designed for 58mm/80mm receipt printers.
ipcMain.handle('print:thermal', async (_e, { data, options = {} }) => {
  const printerName = options.printerName || store.get('thermalPrinterName');
  if (!printerName) throw new Error('لم يتم ضبط الطابعة الحرارية بعد. افتح الإعدادات.');
  const pageSize = options.pageSize || store.get('thermalPageSize') || '80mm';
  await PosPrinter.print(data, {
    preview: false,
    silent: true,
    margin: '0 0 0 0',
    copies: options.copies || 1,
    printerName,
    timeOutPerLine: 400,
    pageSize,
    ...options,
  });
  if (store.get('kickCashDrawer')) {
    try { await kickCashDrawer(); } catch (e) { log('cash drawer failed', e.message); }
  }
  return true;
});

// Explicit cash drawer kick (from renderer buttons)
ipcMain.handle('print:kickCashDrawer', () => kickCashDrawer());

// Explicit thermal test print
ipcMain.handle('print:testThermal', () => printTestReceipt());

// Settings get/set — used by an in-app settings screen or a native dialog.
ipcMain.handle('settings:get', (_e, key) => store.get(key));
ipcMain.handle('settings:set', (_e, key, value) => { store.set(key, value); return true; });
ipcMain.handle('settings:all', () => store.store);
ipcMain.handle('settings:reset', () => { store.clear(); return true; });

// List installed printers so the settings UI can offer them as options.
ipcMain.handle('printers:list', async () => {
  if (!mainWindow) return [];
  try {
    const printers = await mainWindow.webContents.getPrintersAsync();
    return printers.map(p => ({
      name: p.name,
      displayName: p.displayName,
      description: p.description,
      isDefault: p.isDefault,
      status: p.status,
    }));
  } catch (e) {
    log('printers:list failed', e.message);
    return [];
  }
});

// App info + control (used by the About / settings screens)
ipcMain.handle('app:info', () => ({
  version: app.getVersion(),
  electron: process.versions.electron,
  platform: process.platform,
  arch: process.arch,
  userData: app.getPath('userData'),
  logFile: LOG_FILE,
}));
ipcMain.handle('app:openExternal', (_e, url) => shell.openExternal(url));
ipcMain.handle('app:openLogFile', () => shell.openPath(LOG_FILE));
ipcMain.handle('app:reload', () => { mainWindow && mainWindow.reload(); return true; });

// ---------------- Lifecycle ----------------
app.setName('1PH1 POS');
app.commandLine.appendSwitch('lang', 'ar');

// Single-instance lock so a second launch just focuses the existing window
// instead of starting a duplicate cash-drawer client.
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
    // Content Security Policy — allow the frontend URL host, common HTTPS
    // resources, and inline styles/scripts (Expo web bundle needs them).
    session.defaultSession.webRequest.onHeadersReceived((details, cb) => {
      cb({ responseHeaders: { ...details.responseHeaders } });
    });

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
