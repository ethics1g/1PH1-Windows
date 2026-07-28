# 1PH1 Pharmacy POS — Windows Desktop (Electron)

هذا المجلد يحتوي على مغلف Electron يحوّل تطبيق الويب (Expo) إلى تطبيق ويندوز أصلي مع دعم:
- ⌨️ اختصارات لوحة المفاتيح الاحترافية (F2 = بيع، F3 = شراء، F4 = مخزن، ...)
- 🖨️ الطابعات الحرارية (58mm / 80mm ESC/POS)
- 📄 طابعات A4 القياسية (طباعة صامتة أو بالمعاينة)
- 💵 فتح درج الكاش (Cash Drawer Kick) عبر أمر ESC/POS
- 🏷️ ماسحات الباركود USB HID (تعمل تلقائياً — يلتقطها `hidGuard.ts` في الواجهة)
- ⚙️ إعدادات محفوظة (electron-store) — الطابعة، حجم النافذة، مستوى التكبير
- 🔄 إعادة اتصال تلقائية بالخادم عند انقطاع الشبكة
- 📝 ملف سجل دوّار لتشخيص المشاكل

---

## 🛠️ متطلبات البناء (على جهاز ويندوز)

- Windows 10 / 11 (x64)
- [Node.js 18+](https://nodejs.org/)
- Yarn: `npm i -g yarn`

## 📦 خطوات البناء

```powershell
cd C:\path\to\app\electron
yarn install
yarn dist        # ينشئ NSIS installer + Portable exe في مجلد dist\
```

الملفات الناتجة في `dist\`:
- `1PH1-POS-Setup-1.0.0-x64.exe` — Installer NSIS (الأفضل للنشر النهائي)
- `1PH1-POS-1.0.0-portable.exe` — نسخة محمولة (بدون تثبيت)

خيارات إضافية:
```powershell
yarn dist:nsis      # NSIS installer فقط
yarn dist:portable  # Portable exe فقط
yarn dist:msi       # MSI installer (للنشر عبر Group Policy)
```

---

## 🚀 التشغيل بدون بناء (Development)

```powershell
yarn install
yarn start          # تشغيل مباشر (يفتح نافذة Electron)
yarn dev            # تشغيل مع DevTools مفتوحة
```

عند التشغيل لأول مرة سيسألك عن رابط الخادم (Frontend URL). أدخل الرابط المنشور — مثلاً:
```
https://pharma-checkout-8.emergent.host
```

---

## ⌨️ اختصارات لوحة المفاتيح

| المفتاح | الوظيفة |
|---------|---------|
| `F2` | شاشة **البيع** |
| `F3` | شاشة **الشراء** |
| `F4` | شاشة **المخزن** |
| `F5` | شاشة **الزبائن** *(Ctrl+F5 = إعادة تحميل)* |
| `F6` | شاشة **المحاسبة** |
| `F7` | **طلباتي** (طلبات الصيدلية من المذاخر) |
| `F8` | شاشة **المذاخر** |
| `Ctrl+H` | الصفحة الرئيسية |
| `Ctrl+,` | الإعدادات |
| `Ctrl++` / `Ctrl+-` | تكبير / تصغير |
| `Ctrl+0` | حجم افتراضي |
| `F11` | ملء الشاشة |
| `Ctrl+Q` | خروج |

الاختصارات تعمل داخل نافذة التطبيق فقط ولا تُصادر مفاتيح النظام.

---

## 🖨️ إعداد الطابعة الحرارية

1. ثبّت الطابعة على ويندوز (Devices & Printers → Add Printer).
2. افتح التطبيق ثم اختر من القائمة: **الطابعة → طباعة صفحة اختبار حرارية**.
3. إذا لم تُطبع فتح ملف الإعدادات وضع اسم الطابعة **حرفياً** كما يظهر في ويندوز:
   `%APPDATA%\1PH1 - Pharmacy POS\pharma-checkout-settings.json`

مثال:
```json
{
  "thermalPrinterName": "XP-80C",
  "thermalPageSize": "80mm",
  "a4PrinterName": "",
  "kickCashDrawer": true
}
```

- `thermalPageSize`: `"58mm"` أو `"80mm"`
- `kickCashDrawer: true` يفتح درج الكاش تلقائياً بعد كل فاتورة (إذا كان الدرج موصولاً بمنفذ RJ11/RJ12 في الطابعة).

---

## 🏷️ ماسحات الباركود USB

الماسحات USB HID تعمل **تلقائياً** — يلتقطها المستمع العالمي `hidGuard.ts` في الواجهة، ولا يهم أي حقل مفتوح. لا حاجة لإعداد إضافي.

---

## 📁 مواقع الملفات على ويندوز

| المسار | المحتوى |
|--------|---------|
| `%APPDATA%\1PH1 - Pharmacy POS\pharma-checkout-settings.json` | إعدادات التطبيق |
| `%APPDATA%\1PH1 - Pharmacy POS\logs\main.log` | سجل الأخطاء والتشخيص |
| `%LOCALAPPDATA%\Programs\1PH1 Pharmacy POS\` | مكان التثبيت |

من داخل التطبيق: **مساعدة → فتح ملف السجل** أو **مساعدة → مجلد الإعدادات**.

---

## 🔧 استكشاف الأخطاء

**النافذة سوداء عند التشغيل**
- الخادم غير متاح — راجع `main.log` أو غيّر `frontendUrl`.

**الطابعة الحرارية لا تعمل**
- تحقق من أن الاسم في `thermalPrinterName` مطابق حرفياً لاسم الطابعة في ويندوز.
- جرّب: **الطابعة → طباعة صفحة اختبار حرارية** (من القائمة).

**الباركود يظهر داخل حقل السعر**
- بعد أول تحديث للتطبيق، تأكد أن `hidGuard.ts` نُشر مع الواجهة الجديدة.

**نسخة x32 مطلوبة؟**
- عدّل `build.win.target[*].arch` في `package.json` إلى `["x64", "ia32"]` قبل `yarn dist`.

---

## 🛡️ الأمان

- `contextIsolation: true` + `nodeIntegration: false` — بيئة Renderer معزولة تماماً.
- الروابط الخارجية تُفتح في المتصفح الافتراضي، لا داخل نافذة Electron.
- يُسمح فقط بالانتقال داخل نطاق `frontendUrl` المُكوّن.
