/**
 * Utility helpers you can import inside the RN web app to invoke printing.
 * Copy this file into `/app/frontend/src/desktop.ts` (or similar) and use
 * the `printReceipt` / `printA4Invoice` helpers from Sell / Buy screens.
 *
 *   import { isDesktop, printReceipt, printA4Invoice } from '../src/desktop';
 *
 *   if (isDesktop()) {
 *     await printReceipt({
 *       pharmacyName: 'صيدلية 1PH1',
 *       items: cart,
 *       total,
 *       cashier: user.name,
 *     });
 *   }
 */

// The `pharmaDesktop` global is injected by the Electron preload script.
// It exists ONLY when the app runs inside the Windows shell — never in
// mobile builds or the plain web PWA.
declare global {
  interface Window {
    pharmaDesktop?: {
      isDesktop: true;
      platform: string;
      print: {
        a4: (html: string, opts?: any) => Promise<boolean>;
        thermal: (data: any[], options?: any) => Promise<boolean>;
      };
      listPrinters: () => Promise<Array<{ name: string; displayName: string; isDefault: boolean }>>;
      settings: {
        get: (key: string) => Promise<any>;
        set: (key: string, value: any) => Promise<true>;
        all: () => Promise<Record<string, any>>;
      };
    };
  }
}

export const isDesktop = (): boolean =>
  typeof window !== 'undefined' && !!window.pharmaDesktop?.isDesktop;

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
}

export async function printReceipt(r: ReceiptData): Promise<boolean> {
  if (!isDesktop()) return false;
  const now = new Date().toLocaleString('ar-EG');
  const rows = r.items.map((it) => ({
    type: 'text',
    value: `${it.name}   ${it.quantity} × ${it.price.toLocaleString()}  =  ${(it.quantity * it.price).toLocaleString()}`,
    style: { fontSize: '11px', textAlign: 'right', direction: 'rtl' },
  }));
  const data = [
    { type: 'text', value: r.pharmacyName, style: { fontSize: '16px', fontWeight: '900', textAlign: 'center' } },
    ...(r.address ? [{ type: 'text', value: r.address, style: { fontSize: '10px', textAlign: 'center' } }] : []),
    ...(r.phone   ? [{ type: 'text', value: r.phone,   style: { fontSize: '10px', textAlign: 'center' } }] : []),
    { type: 'text', value: now, style: { fontSize: '10px', textAlign: 'center', marginBottom: '4px' } },
    { type: 'text', value: r.invoiceNumber ? `فاتورة #${r.invoiceNumber}` : '', style: { fontSize: '10px', textAlign: 'center' } },
    { type: 'divider' },
    ...rows,
    { type: 'divider' },
    { type: 'text', value: `الإجمالي: ${r.total.toLocaleString()} د.ع`,
      style: { fontSize: '14px', fontWeight: '900', textAlign: 'right', direction: 'rtl' } },
    ...(r.paid !== undefined ? [{ type: 'text', value: `المدفوع: ${r.paid!.toLocaleString()} د.ع`,
      style: { fontSize: '12px', textAlign: 'right', direction: 'rtl' } }] : []),
    ...(r.change !== undefined ? [{ type: 'text', value: `الباقي: ${r.change!.toLocaleString()} د.ع`,
      style: { fontSize: '12px', textAlign: 'right', direction: 'rtl' } }] : []),
    ...(r.cashier ? [{ type: 'text', value: `الكاشير: ${r.cashier}`,
      style: { fontSize: '10px', textAlign: 'right', direction: 'rtl', marginTop: '6px' } }] : []),
    { type: 'text', value: 'شكراً لتعاملكم معنا', style: { fontSize: '11px', textAlign: 'center', marginTop: '6px' } },
  ];
  return window.pharmaDesktop!.print.thermal(data, { pageSize: '80mm', copies: 1 });
}

// ---- A4 invoice (professional look) --------------------------------------

export async function printA4Invoice(r: ReceiptData): Promise<boolean> {
  if (!isDesktop()) return false;
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
    </style></head><body>
    <h1>${r.pharmacyName}</h1>
    <div class="meta">
      <div>فاتورة #${r.invoiceNumber || '-'}</div>
      <div>${new Date().toLocaleString('ar-EG')}</div>
    </div>
    <table>
      <thead><tr><th>الصنف</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="total">الإجمالي الكلي: ${r.total.toLocaleString()} د.ع</div>
    ${r.cashier ? `<div style="margin-top:16px;font-size:11px">الكاشير: ${r.cashier}</div>` : ''}
    </body></html>`;
  return window.pharmaDesktop!.print.a4(html, { silent: false });
}
