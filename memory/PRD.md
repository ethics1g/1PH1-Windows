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
- `GET/POST/PATCH/DELETE /api/medicines`, `GET /api/medicines/barcode/{code}`
- `POST /api/medicines/sell` (deducts qty, returns total)
- `POST /api/medicines/buy` (adds/updates inventory)
- `POST /api/medicines/identify` (image base64 → name)
- `POST/GET /api/orders`
- `GET/POST/DELETE /api/supplier/products`, `GET /api/marketplace`
