/**
 * 1PH1 Pharmacy POS — Electron Main Process
 * =============================================================================
 * Wraps the deployed Expo web build in a native Windows window and adds:
 *   • Global keyboard shortcuts optimised for POS workflow (F2/F3/F4/…)
 *   • A safe IPC bridge to the renderer for receipt printing (thermal + A4)
 *   • Persistent settings via electron-store (backend URL, printer config)
 *   • Auto-focus reset on window activation so USB HID barcode scanners
 *     never need a mouse click before scanning.
 *
 * The FastAPI backend and MongoDB stay on Emergent — this app is purely a
 * desktop shell for the existing web frontend.
 */
const { app, BrowserWindow, Menu, ipcMain, globalShortcut, shell, dialog } = require('electron');
const path = require('path');
const Store = require('electron-store');
const { PosPrinter } = require('electron-pos-printer');

// ---------------- Persistent settings ----------------
const store = new Store({
  name: 'pharma-checkout-settings',
  defaults: {
    // Where the deployed frontend lives. Users configure this once via the
    // in-app settings dialog on first launch.
    frontendUrl: process.env.PHARMA_FRONTEND_URL || 'https://YOUR-APP.emergent.host',
    // Thermal printer name (as it appears in Windows Devices & Printers)
    thermalPrinterName: '',
    // A4 printer name
    a4PrinterName: '',
    // Window geometry
    winBounds: { width: 1400, height: 900 },
  },
});

let mainWindow = null;

// ---------------- Window creation ----------------
function createWindow() {
  const bounds = store.get('winBounds');
  mainWindow = new BrowserWindow({
    width:  bounds.width,
    height: bounds.height,
    minWidth: 1024,
    minHeight: 720,
    title: '1PH1 — Pharmacy POS',
    backgroundColor: '#0f172a',
    icon: path.join(__dirname, 'assets', 'icon.ico'),
    autoHideMenuBar: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      spellcheck: false,
    },
  });

  // Persist window size across sessions.
  mainWindow.on('close', () => {
    try { store.set('winBounds', mainWindow.getBounds()); } catch { /* noop */ }
  });

  const url = store.get('frontendUrl');
  mainWindow.loadURL(url).catch((err) => {
    console.error('Failed to load frontend URL:', err);
    dialog.showErrorBox(
      'تعذّر الاتصال بالخادم',
      `فشل تحميل الرابط:\n${url}\n\nافتح الإعدادات (Ctrl+,) وأدخل عنوان الخادم الصحيح.`,
    );
  });

  // Open external links in the user's default browser instead of a new
  // Electron window (safer + more professional).
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    shell.openExternal(target);
    return { action: 'deny' };
  });

  // Every time the window gains focus, tell the renderer to refocus the
  // barcode input if one exists — critical for continuous USB HID scanning.
  mainWindow.on('focus', () => {
    mainWindow.webContents.executeJavaScript(`
      (function () {
        var el = document.querySelector('[data-barcode-input="1"]');
        if (el && typeof el.focus === 'function') el.focus();
      })();
    `).catch(() => {});
  });

  if (process.env.ELECTRON_DEV === '1') {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }
}

// ---------------- POS-optimised keyboard shortcuts ----------------
// Global accelerators — work regardless of which control has focus (except
// while a text input is being actively edited, thanks to `beforeInput`
// filtering handled inside the renderer).
function registerShortcuts() {
  const go = (route) => {
    if (!mainWindow) return;
    mainWindow.webContents.executeJavaScript(`
      (function () {
        try { history.pushState({}, '', '${route}'); }
        catch (e) {}
        // Expo Router uses the URL — trigger a popstate so it re-renders.
        window.dispatchEvent(new Event('popstate'));
      })();
    `).catch(() => {});
    mainWindow.focus();
  };

  globalShortcut.register('F2', () => go('/sell'));
  globalShortcut.register('F3', () => go('/buy'));
  globalShortcut.register('F4', () => go('/inventory'));
  globalShortcut.register('F5', () => go('/customers'));
  globalShortcut.register('F6', () => go('/accounting'));
  globalShortcut.register('F7', () => go('/pharmacy-orders'));
  globalShortcut.register('F8', () => go('/suppliers'));
  globalShortcut.register('CommandOrControl+H', () => go('/home'));
  globalShortcut.register('CommandOrControl+,', () => go('/settings'));
  // Ctrl+P is handled by the renderer via IPC for receipt printing.
}

// ---------------- Native application menu (Arabic-friendly) ----------------
function buildMenu() {
  const template = [
    {
      label: 'الملف',
      submenu: [
        { label: 'الرئيسية', accelerator: 'Ctrl+H', click: () => mainWindow?.webContents.executeJavaScript(
          "history.pushState({},'','/home');dispatchEvent(new Event('popstate'));"
        ) },
        { type: 'separator' },
        { label: 'الإعدادات', accelerator: 'Ctrl+,', click: () => mainWindow?.webContents.executeJavaScript(
          "history.pushState({},'','/settings');dispatchEvent(new Event('popstate'));"
        ) },
        { type: 'separator' },
        { role: 'quit', label: 'خروج' },
      ],
    },
    {
      label: 'العمليات',
      submenu: [
        { label: 'بيع (F2)',        accelerator: 'F2', click: () => mainWindow?.webContents.executeJavaScript(
          "history.pushState({},'','/sell');dispatchEvent(new Event('popstate'));"
        ) },
        { label: 'شراء (F3)',       accelerator: 'F3', click: () => mainWindow?.webContents.executeJavaScript(
          "history.pushState({},'','/buy');dispatchEvent(new Event('popstate'));"
        ) },
        { label: 'المخزن (F4)',      accelerator: 'F4', click: () => mainWindow?.webContents.executeJavaScript(
          "history.pushState({},'','/inventory');dispatchEvent(new Event('popstate'));"
        ) },
        { label: 'الزبائن (F5)',     accelerator: 'F5', click: () => mainWindow?.webContents.executeJavaScript(
          "history.pushState({},'','/customers');dispatchEvent(new Event('popstate'));"
        ) },
        { label: 'المحاسبة (F6)',    accelerator: 'F6', click: () => mainWindow?.webContents.executeJavaScript(
          "history.pushState({},'','/accounting');dispatchEvent(new Event('popstate'));"
        ) },
      ],
    },
    {
      label: 'عرض',
      submenu: [
        { role: 'reload',           label: 'إعادة تحميل' },
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
      label: 'مساعدة',
      submenu: [
        { label: 'حول 1PH1', click: () => dialog.showMessageBox({
          type: 'info',
          title: 'حول 1PH1',
          message: '1PH1 — Pharmacy POS',
          detail: `الإصدار ${app.getVersion()}\nنظام نقاط بيع للصيدليات مع محاسبة كاملة.`,
        }) },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ---------------- IPC: renderer → main (printing + settings) ----------------

// Standard A4 print — silent (no dialog) if `silent: true` is passed.
ipcMain.handle('print:a4', async (_e, { html, silent = false, printerName = null }) => {
  if (!mainWindow) throw new Error('window unavailable');
  const win = new BrowserWindow({
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  try {
    await win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
    const opts = {
      silent,
      printBackground: true,
      deviceName: printerName || store.get('a4PrinterName') || undefined,
      margins: { marginType: 'default' },
    };
    return await new Promise((resolve, reject) => {
      win.webContents.print(opts, (ok, err) => (ok ? resolve(true) : reject(new Error(err || 'print failed'))));
    });
  } finally {
    win.close();
  }
});

// Thermal ESC/POS print — designed for 58mm/80mm receipt printers.
// `data` is a JSON array following electron-pos-printer's schema.
ipcMain.handle('print:thermal', async (_e, { data, options = {} }) => {
  const printerName = options.printerName || store.get('thermalPrinterName');
  if (!printerName) throw new Error('لم يتم ضبط الطابعة الحرارية بعد. افتح الإعدادات وأدخل اسم الطابعة.');
  await PosPrinter.print(data, {
    preview: false,
    silent: true,
    margin: '0 0 0 0',
    copies: options.copies || 1,
    printerName,
    timeOutPerLine: 400,
    pageSize: options.pageSize || '80mm',   // 58mm or 80mm
    ...options,
  });
  return true;
});

// Settings get/set — used by an in-app settings screen or a native dialog.
ipcMain.handle('settings:get', (_e, key) => store.get(key));
ipcMain.handle('settings:set', (_e, key, value) => { store.set(key, value); return true; });
ipcMain.handle('settings:all', () => store.store);

// List installed printers so the settings UI can offer them as options.
ipcMain.handle('printers:list', async () => {
  if (!mainWindow) return [];
  const printers = await mainWindow.webContents.getPrintersAsync();
  return printers.map(p => ({
    name: p.name,
    displayName: p.displayName,
    description: p.description,
    isDefault: p.isDefault,
    status: p.status,
  }));
});

// ---------------- Lifecycle ----------------
app.setName('1PH1 POS');
app.commandLine.appendSwitch('lang', 'ar');

app.whenReady().then(() => {
  createWindow();
  buildMenu();
  registerShortcuts();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('will-quit', () => globalShortcut.unregisterAll());
