# 1PH1 Pharmacy POS — النسخة المكتبية لـ Windows

هذا مجلد Electron جاهز لتحويل تطبيق **1PH1** إلى تطبيق سطح مكتب Windows احترافي (`.exe` installer + Portable).

يعتمد على النسخة الويب من التطبيق (المنشورة على Emergent). لا حاجة لأي تغيير في الباك-إند (FastAPI + MongoDB يبقيان على Emergent).

---

## 🎯 الميزات المضمّنة

- ✅ **نافذة سطح مكتب أصلية** — تبدو كتطبيق Windows حقيقي، لا محاكي Android
- ✅ **قارئ الباركود USB HID** — يعمل مباشرة (نفس كود React الحالي)
- ✅ **الطباعة الحرارية ESC/POS** (58mm و 80mm) عبر `electron-pos-printer`
- ✅ **الطباعة العادية A4** — للفواتير الرسمية
- ✅ **اختصارات لوحة المفاتيح** المخصّصة لعمل POS:
  - `F2` بيع  ·  `F3` شراء  ·  `F4` المخزن  ·  `F5` الزبائن  ·  `F6` المحاسبة  ·  `F7` طلباتي  ·  `F8` المذاخر
  - `Ctrl+H` الرئيسية  ·  `Ctrl+,` الإعدادات
- ✅ **إعادة التركيز التلقائي** على حقل الباركود عند تفعيل النافذة (مسح متتابع بدون لمس)
- ✅ **إعدادات محلية دائمة** (اسم الطابعة، رابط الخادم) عبر `electron-store`
- ✅ **قائمة عربية RTL** كاملة
- ✅ **مُثبِّت NSIS** بواجهة عربية + إنجليزية + نسخة **Portable** بدون تثبيت

---

## 🏗️ خطوات بناء الـ `.exe` على جهاز Windows

### المتطلبات
- **Windows 10/11** (64-bit)
- **Node.js 18+** — من [nodejs.org](https://nodejs.org/)
- **Git** — من [git-scm.com](https://git-scm.com/)
- **~2 GB** مساحة فارغة للبناء

### الخطوات
```bash
# 1) استنسخ المستودع من GitHub (بعد رفعه من Emergent)
git clone https://github.com/<اسمك>/pharma-checkout-8.git
cd pharma-checkout-8/electron

# 2) ثبّت الاعتماديات
npm install

# 3) عدّل رابط الخادم قبل البناء (اختياري — يمكن ضبطه لاحقاً من الإعدادات)
# افتح main.js وابحث عن PHARMA_FRONTEND_URL أو دع المستخدم يضبطه من التطبيق

# 4) اختبر محلياً قبل البناء
npm run dev

# 5) ابنِ المُثبِّت (NSIS installer + Portable)
npm run dist

# 6) ستجد المخرجات في:
#    electron/dist/1PH1 Pharmacy POS Setup 1.0.0.exe   ← المُثبِّت
#    electron/dist/1PH1-POS-1.0.0-portable.exe          ← نسخة محمولة
```

بناء نسخة MSI فقط:
```bash
npm run dist:msi
```

بناء نسخة Portable فقط (بدون تثبيت):
```bash
npm run dist:portable
```

---

## 🖨️ ضبط الطابعات (بعد التثبيت)

عند أول تشغيل، أدخل الإعدادات (`Ctrl+,`) وأدخل:
- **رابط الخادم**: مثلاً `https://pharma-checkout-8.emergent.host`
- **الطابعة الحرارية**: اسمها بالضبط كما يظهر في **Devices and Printers** بـ Windows (مثال: `XP-58C`, `POS-80`)
- **طابعة A4**: للفواتير الرسمية

القيم تُحفظ في:
```
%APPDATA%/pharma-checkout-desktop-settings/config.json
```

---

## 🧩 كيف تستدعي الطباعة من داخل React Native code؟

انسخ الملف `electron/src/print-helpers.ts` إلى `frontend/src/desktop.ts` واستعمله في `sell.tsx`:

```typescript
import { isDesktop, printReceipt } from '../src/desktop';

// بعد إتمام عملية بيع
if (isDesktop()) {
  await printReceipt({
    pharmacyName: 'صيدلية 1PH1',
    invoiceNumber: '00123',
    items: cart,
    total,
    paid: amountPaid,
    change: amountPaid - total,
    cashier: user.name,
  });
}
```

الدالة تعمل فقط داخل تطبيق Windows — على الموبايل والويب العادي تُرجع `false` بلا خطأ.

---

## 🔐 التوقيع الرقمي (لتجنّب تحذير SmartScreen)

Windows يعرض تحذير "Unknown publisher" حتى توقّع الملف. للتوقيع:

1. اشترِ **Code Signing Certificate** من DigiCert / Sectigo / SSL.com (~$100-300/سنة)
2. أضف إلى `package.json` في قسم `build.win`:
   ```json
   "certificateFile": "path/to/cert.pfx",
   "certificatePassword": "your-password",
   "signingHashAlgorithms": ["sha256"]
   ```
3. أعد تشغيل `npm run dist`

بديل مجاني للاختبار الداخلي: بدون توقيع، سيظهر تحذير عند أول تشغيل — اضغط "More info" → "Run anyway".

---

## 🚨 استكشاف الأخطاء

| المشكلة | الحل |
|--------|------|
| نافذة فارغة | تأكد من `frontendUrl` في الإعدادات — يجب أن يكون HTTPS |
| قارئ الباركود لا يعمل | افتح `Ctrl+Shift+I` وتحقق من الـ Console — قد يحتاج تركيز حقل الباركود يدوياً أول مرة |
| الطابعة الحرارية لا تطبع | تأكد من اسم الطابعة يطابق ما في Windows تماماً (case-sensitive) |
| ملف .exe كبير جداً | مضغوط بالفعل بأقصى ضغط — طبيعي ~150MB لـ Electron |
| SmartScreen يمنع التشغيل | وقّع الملف رقمياً أو استخدم "Run anyway" مؤقتاً |

---

## 📁 هيكل المجلد

```
electron/
├── package.json          ← إعدادات الحزمة + electron-builder
├── main.js               ← Main process (نافذة + IPC + طباعة + اختصارات)
├── preload.js            ← جسر آمن للـ renderer
├── config/
│   └── defaults.json     ← إعدادات افتراضية
├── src/
│   └── print-helpers.ts  ← دوال جاهزة للاستخدام من React Native
├── assets/
│   └── icon.ico          ← أيقونة التطبيق (استبدلها بأيقونتك)
└── README.md             ← هذا الملف
```

---

## 💡 التالي (اختياري لتحسينات لاحقة)

- **Auto-update**: أضف `electron-updater` مع Emergent-hosted release feed
- **Offline mode**: مزامنة IndexedDB مع FastAPI عند الاتصال
- **Cash drawer**: مكتبة `escpos` تدعم فتح الدرج بأمر ESC
- **Multi-monitor**: نافذة عرض السعر للزبون على شاشة ثانية
- **App icon**: استبدل `assets/icon.ico` بأيقونة مخصّصة (256×256 على الأقل)

---

## 📞 دعم

- **مشاكل في الكود**: `support@1ph1.local`
- **مشاكل النشر على Emergent**: `support@emergent.sh`

**البناء يتم على جهاز Windows فقط — لا يمكن بناء .exe داخل بيئة Linux/Emergent.**
