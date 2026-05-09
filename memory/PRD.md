# Pharmacy Cashier App - PRD

## Overview
Arabic (RTL) mobile app for pharmacies and wholesale suppliers ("مذاخر"). Green + blue + white modern medical theme. Cheerful UI, thumb-friendly, large touch targets.

## Users
1. **Pharmacy** – scans/sells medicines, manages inventory, creates supplier orders
2. **Supplier (مذخر)** – lists medicines with prices visible to pharmacies

## Features
### Auth (custom JWT)
- Pharmacy register/login: name, phone, password, address
- Supplier register/login: same fields, separate collection & role

### Home (Pharmacy) - 4 tiles
1. **البيع (Sell)** – scan barcode OR capture image → Gemini 3 Flash AI identifies → adds to cart; auto deducts inventory on checkout; shows total
2. **الشراء (Buy)** – scan/image + manual form (name, barcode, qty, price) → adds to inventory
3. **المخزن (Inventory)** – list of all medicines with stock & price; search; tap to add to order; **إنشاء طلبية** sends via WhatsApp or copies text
4. **المذاخر (Suppliers)** – marketplace grid of all supplier products

### Supplier Dashboard
- Add products (name, price, description)
- View / delete own products

## Tech Stack
- **Frontend**: Expo Router, React Native, expo-camera (barcode + image), AsyncStorage, @expo/vector-icons
- **Backend**: FastAPI + Motor + MongoDB, JWT auth (HS256)
- **AI**: Gemini 3 Flash via emergentintegrations library + Emergent LLM Key

## Endpoints
- `POST /api/pharmacy/register|login`, `POST /api/supplier/register|login`, `GET /api/me`
- `POST /api/auth/forgot-password`, `POST /api/auth/verify-otp`, `POST /api/auth/reset-password` ⭐ NEW
- `GET/POST/PATCH/DELETE /api/medicines`, `GET /api/medicines/barcode/{code}`
- `POST /api/medicines/sell` (deducts qty, returns total)
- `POST /api/medicines/buy` (adds/updates inventory)
- `POST /api/medicines/identify` (image base64 → name)
- `POST/GET /api/orders`
- `POST /api/orders/optimize` — Smart Multi-Pharmacy Price Optimization
- `GET/POST/DELETE /api/supplier/products`, `GET /api/marketplace`
- `POST /api/supplier/catalog/upload` ⭐ NEW — AI Catalog Import (PDF/Image)
- `GET /api/supplier/catalog/jobs`, `GET /api/supplier/catalog/jobs/{id}`
- `PATCH /api/supplier/catalog/items/{id}` (edit/approve/reject + saves correction)
- `POST /api/supplier/catalog/jobs/{id}/publish` (publishes auto+approved items)

## AI Supplier Catalog Import (new)
Suppliers upload a PDF/image price-list. Backend pipeline (async via FastAPI BackgroundTasks):
1. PDF → page-images via `pypdfium2` (max 12 pages); image → JPEG normalize
2. Each page → Gemini 3 Flash with JSON schema → list of {name, strength, dosage_form, manufacturer, price, quantity}
3. Arabic-aware normalization + dedupe within batch
4. Smart matching: corrections lookup → RapidFuzz token_set → if ambiguous (55-90% conf) call Gemini "are these same drug?" (the "switching" layer)
5. Items with conf ≥ 0.90 auto-approved; else flagged `needs_review`
6. Frontend review screen lets supplier edit/approve/reject; corrections are saved to `catalog_corrections` for self-improving matching
7. Publish pushes auto+approved to `supplier_products` (existing names → update, new → insert)
Collections: `import_jobs`, `import_items`, `catalog_corrections`

## Smart Split Optimization (new)
Pharmacy can tap **"اقتراح أفضل سعر"** in inventory after building an order. Backend computes 3 plans:
- **per_item**: cheapest supplier per item (ignores qty)
- **single_supplier**: ranked list of suppliers that have ALL items
- **smart_split**: greedy per-item that splits one item across multiple suppliers when stock is insufficient (honors `quantity`; `0` = unlimited)
Frontend `/optimize` screen shows tabs (تقسيم ذكي / مذخر واحد) + per-supplier WhatsApp send button (`wa.me/<phone>`) + "نسخ الكل" for screenshot. Items not offered by any supplier are flagged.
