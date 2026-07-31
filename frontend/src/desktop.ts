/**
 * Desktop bridge — bootstraps the tiny surface of `window.pharmaDesktop`
 * for use inside the RN web app. This is a NO-OP on iOS, Android and the
 * plain-browser PWA. It only comes alive when the app is running inside
 * the Electron shell (Windows / macOS / Linux desktop).
 *
 * Public API:
 *   isDesktop()                     → boolean
 *   getDesktopInfo()                → { version, platform, ... } | null
 *   setupDesktopNavigation(router)  → wires the F2/F3/F4/… menu shortcuts
 *                                     dispatched from Electron's main
 *                                     process to expo-router.
 *   printReceipt(data)              → thermal ESC/POS
 *   printA4Invoice(data)            → A4 HTML print
 *   kickCashDrawer()                → open drawer
 */
import { useEffect } from 'react';

// ---- Type surface --------------------------------------------------------

type PrinterInfo = {
  name: string;
  displayName: string;
  isDefault?: boolean;
  status?: number;
  description?: string;
};

type DesktopAPI = {
  isDesktop: true;
  platform: string;
  versions: { electron: string; chrome: string; node: string };
  print: {
    a4: (html: string, opts?: Record<string, any>) => Promise<boolean>;
    thermal: (data: any[], options?: Record<string, any>) => Promise<boolean>;
    testThermal: () => Promise<boolean>;
    kickCashDrawer: () => Promise<boolean>;
  };
  listPrinters: () => Promise<PrinterInfo[]>;
  settings: {
    get: (key: string) => Promise<any>;
    set: (key: string, value: any) => Promise<true>;
    all: () => Promise<Record<string, any>>;
    reset: () => Promise<true>;
  };
  app: {
    info: () => Promise<{
      version: string; electron: string; platform: string;
      arch: string; userData: string; logFile: string;
    }>;
    openExternal: (url: string) => Promise<void>;
    openLogFile: () => Promise<void>;
    reload: () => Promise<true>;
  };
  diagnostics: {
    redirects: () => Promise<{
      rules: { frontendUrl: string; frontendHost: string; productionOrigin: string; productionApiUrl: string };
      totalRedirected: number;
      recent: Array<{ n: number; at: string; method: string; from: string; to: string }>;
    }>;
  };
};

declare global {
  interface Window { pharmaDesktop?: DesktopAPI; }
}

// ---- Helpers -------------------------------------------------------------

export const isDesktop = (): boolean =>
  typeof window !== 'undefined' && !!(window as any).pharmaDesktop?.isDesktop;

export const desktop = (): DesktopAPI | null =>
  isDesktop() ? ((window as any).pharmaDesktop as DesktopAPI) : null;

export async function getDesktopInfo() {
  const d = desktop();
  if (!d) return null;
  try { return await d.app.info(); } catch { return null; }
}

// ---- Router navigation bridge -------------------------------------------

/**
 * Wire the `desktop-navigate` events dispatched by Electron main process
 * (F2/F3/F4/… menu items) into expo-router.
 *
 * Usage inside app/_layout.tsx:
 *   import { useDesktopNavigation } from '../src/desktop';
 *   useDesktopNavigation();
 */
export function useDesktopNavigation() {
  useEffect(() => {
    if (!isDesktop()) return;
    // Lazy-import so React Native mobile builds never pull expo-router into
    // this bridge at module-load time.
    let router: any = null;
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    try { router = require('expo-router').router; } catch { /* noop */ }
    const handler = (e: Event) => {
      // @ts-ignore
      const route = (e && e.detail) || '/';
      try {
        if (router && typeof router.replace === 'function') {
          router.replace(route);
        } else if (typeof window !== 'undefined') {
          window.location.assign(route);
        }
      } catch { /* noop */ }
    };
    window.addEventListener('desktop-navigate', handler);
    return () => window.removeEventListener('desktop-navigate', handler);
  }, []);
}

// ---- Thermal receipt (58mm/80mm ESC/POS) ---------------------------------

export interface ReceiptItem { name: string; quantity: number; price: number; }
export interface ReceiptData {
  pharmacyName: string;
  address?: string;
  phone?: string;
  invoiceNumber?: string;
  cashier?: string;
  items: ReceiptItem[];
  total: number;
  paid?: number;
  change?: number;
  footer?: string;
}

export async function printReceipt(r: ReceiptData): Promise<boolean> {
  const d = desktop();
  if (!d) return false;
  const now = new Date().toLocaleString('ar-EG');
  const rtl = { textAlign: 'right' as const, direction: 'rtl' as const };
  const rows = r.items.map((it) => ({
    type: 'text',
    value: `${it.name}   ${it.quantity} × ${it.price.toLocaleString()}  =  ${(it.quantity * it.price).toLocaleString()}`,
    style: { fontSize: '11px', ...rtl },
  }));
  const data: any[] = [
    { type: 'text', value: r.pharmacyName, style: { fontSize: '16px', fontWeight: '900', textAlign: 'center' } },
    ...(r.address ? [{ type: 'text', value: r.address, style: { fontSize: '10px', textAlign: 'center' } }] : []),
    ...(r.phone   ? [{ type: 'text', value: r.phone,   style: { fontSize: '10px', textAlign: 'center' } }] : []),
    { type: 'text', value: now, style: { fontSize: '10px', textAlign: 'center', marginBottom: '4px' } },
    ...(r.invoiceNumber ? [{ type: 'text', value: `فاتورة #${r.invoiceNumber}`, style: { fontSize: '10px', textAlign: 'center' } }] : []),
    { type: 'divider' },
    ...rows,
    { type: 'divider' },
    { type: 'text', value: `الإجمالي: ${r.total.toLocaleString()} د.ع`,
      style: { fontSize: '14px', fontWeight: '900', ...rtl } },
    ...(r.paid !== undefined ? [{ type: 'text', value: `المدفوع: ${r.paid!.toLocaleString()} د.ع`,
      style: { fontSize: '12px', ...rtl } }] : []),
    ...(r.change !== undefined ? [{ type: 'text', value: `الباقي: ${r.change!.toLocaleString()} د.ع`,
      style: { fontSize: '12px', ...rtl } }] : []),
    ...(r.cashier ? [{ type: 'text', value: `الكاشير: ${r.cashier}`,
      style: { fontSize: '10px', marginTop: '6px', ...rtl } }] : []),
    { type: 'text', value: r.footer || 'شكراً لتعاملكم معنا',
      style: { fontSize: '11px', textAlign: 'center', marginTop: '6px' } },
  ];
  try {
    const size = await d.settings.get('thermalPageSize');
    return await d.print.thermal(data, { pageSize: size || '80mm', copies: 1 });
  } catch (e: any) {
    // Non-fatal: log for the caller to show a toast, but never crash Sell.
    console.warn('printReceipt failed', e && e.message);
    return false;
  }
}

// ---- A4 invoice (professional look) --------------------------------------

export async function printA4Invoice(r: ReceiptData): Promise<boolean> {
  const d = desktop();
  if (!d) return false;
  const rows = r.items.map((it) => `
    <tr>
      <td style="text-align:right">${it.name}</td>
      <td style="text-align:center">${it.quantity}</td>
      <td style="text-align:center">${it.price.toLocaleString()}</td>
      <td style="text-align:center">${(it.quantity * it.price).toLocaleString()}</td>
    </tr>`).join('');
  const html = `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
    <style>
      * { font-family: Tahoma, Arial; }
      body { margin: 24px; }
      h1 { text-align: center; font-size: 22px; margin: 0 0 4px; }
      .meta { display: flex; justify-content: space-between; font-size: 12px; margin: 12px 0; }
      table { width: 100%; border-collapse: collapse; margin-top: 12px; }
      th, td { border: 1px solid #333; padding: 8px; font-size: 12px; }
      th { background: #f3f4f6; }
      .total { text-align: left; margin-top: 20px; font-size: 16px; font-weight: 900; }
      .footer { margin-top: 16px; font-size: 11px; color: #444; }
    </style></head><body>
    <h1>${escapeHtml(r.pharmacyName)}</h1>
    <div class="meta">
      <div>فاتورة #${escapeHtml(r.invoiceNumber || '-')}</div>
      <div>${new Date().toLocaleString('ar-EG')}</div>
    </div>
    <table>
      <thead><tr><th>الصنف</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="total">الإجمالي الكلي: ${r.total.toLocaleString()} د.ع</div>
    ${r.cashier ? `<div class="footer">الكاشير: ${escapeHtml(r.cashier)}</div>` : ''}
    </body></html>`;
  try {
    return await d.print.a4(html, { silent: false });
  } catch (e: any) {
    console.warn('printA4Invoice failed', e && e.message);
    return false;
  }
}

export async function kickCashDrawer(): Promise<boolean> {
  const d = desktop();
  if (!d) return false;
  try { return await d.print.kickCashDrawer(); }
  catch (e: any) { console.warn('kickCashDrawer failed', e && e.message); return false; }
}

function escapeHtml(s: string): string {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
