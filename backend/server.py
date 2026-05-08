from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, BackgroundTasks
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import logging
import uuid
import hashlib
import jwt
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone, timedelta

import catalog_import

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret')
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ---------- Helpers ----------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def create_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.replace("Bearer ", "")
    payload = decode_token(token)
    return payload  # {sub, role}


def require_role(required_role: str):
    async def _dep(user: dict = Depends(get_current_user)) -> dict:
        if user.get("role") != required_role:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return _dep


# ---------- Models ----------
class PharmacyRegister(BaseModel):
    name: str
    phone: str
    password: str
    address: str


class SupplierRegister(BaseModel):
    name: str
    phone: str
    password: str
    address: str


class LoginInput(BaseModel):
    phone: str
    password: str


class Medicine(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pharmacy_id: str
    name: str
    barcode: Optional[str] = None
    quantity: int = 0
    price: float = 0.0
    image_base64: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MedicineCreate(BaseModel):
    name: str
    barcode: Optional[str] = None
    quantity: int = 0
    price: float = 0.0
    image_base64: Optional[str] = None


class MedicineUpdate(BaseModel):
    name: Optional[str] = None
    barcode: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[float] = None


class SellItem(BaseModel):
    medicine_id: str
    quantity: int = 1


class SellRequest(BaseModel):
    items: List[SellItem]


class BuyRequest(BaseModel):
    name: str
    barcode: Optional[str] = None
    quantity: int
    price: float
    image_base64: Optional[str] = None


class IdentifyImage(BaseModel):
    image_base64: str


class OrderItem(BaseModel):
    name: str
    quantity: int


class OrderCreate(BaseModel):
    items: List[OrderItem]


class SupplierProduct(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    supplier_id: str
    supplier_name: str
    supplier_phone: Optional[str] = None
    name: str
    price: float
    quantity: int = 0
    delivery_time: Optional[str] = None
    image_base64: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SupplierProductCreate(BaseModel):
    name: str
    price: float
    quantity: int = 0
    delivery_time: Optional[str] = None
    image_base64: Optional[str] = None
    description: Optional[str] = None


class OptimizeRequest(BaseModel):
    items: List[OrderItem]


# ---------- Auth - Pharmacy ----------
@api_router.post("/pharmacy/register")
async def pharmacy_register(data: PharmacyRegister):
    existing = await db.pharmacies.find_one({"phone": data.phone})
    if existing:
        raise HTTPException(status_code=400, detail="رقم الهاتف مسجل مسبقاً")
    pharmacy_id = str(uuid.uuid4())
    doc = {
        "id": pharmacy_id,
        "name": data.name,
        "phone": data.phone,
        "password": hash_password(data.password),
        "address": data.address,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.pharmacies.insert_one(doc)
    token = create_token(pharmacy_id, "pharmacy")
    return {"token": token, "pharmacy": {"id": pharmacy_id, "name": data.name, "phone": data.phone, "address": data.address}}


@api_router.post("/pharmacy/login")
async def pharmacy_login(data: LoginInput):
    doc = await db.pharmacies.find_one({"phone": data.phone}, {"_id": 0})
    if not doc or doc["password"] != hash_password(data.password):
        raise HTTPException(status_code=401, detail="رقم الهاتف أو الرمز السري غير صحيح")
    token = create_token(doc["id"], "pharmacy")
    return {"token": token, "pharmacy": {"id": doc["id"], "name": doc["name"], "phone": doc["phone"], "address": doc["address"]}}


# ---------- Auth - Supplier ----------
@api_router.post("/supplier/register")
async def supplier_register(data: SupplierRegister):
    existing = await db.suppliers.find_one({"phone": data.phone})
    if existing:
        raise HTTPException(status_code=400, detail="رقم الهاتف مسجل مسبقاً")
    supplier_id = str(uuid.uuid4())
    doc = {
        "id": supplier_id,
        "name": data.name,
        "phone": data.phone,
        "password": hash_password(data.password),
        "address": data.address,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.suppliers.insert_one(doc)
    token = create_token(supplier_id, "supplier")
    return {"token": token, "supplier": {"id": supplier_id, "name": data.name, "phone": data.phone, "address": data.address}}


@api_router.post("/supplier/login")
async def supplier_login(data: LoginInput):
    doc = await db.suppliers.find_one({"phone": data.phone}, {"_id": 0})
    if not doc or doc["password"] != hash_password(data.password):
        raise HTTPException(status_code=401, detail="رقم الهاتف أو الرمز السري غير صحيح")
    token = create_token(doc["id"], "supplier")
    return {"token": token, "supplier": {"id": doc["id"], "name": doc["name"], "phone": doc["phone"], "address": doc["address"]}}


@api_router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    if user["role"] == "pharmacy":
        doc = await db.pharmacies.find_one({"id": user["sub"]}, {"_id": 0, "password": 0})
    else:
        doc = await db.suppliers.find_one({"id": user["sub"]}, {"_id": 0, "password": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return {"role": user["role"], "user": doc}


# ---------- Medicines (Pharmacy) ----------
@api_router.get("/medicines")
async def list_medicines(user: dict = Depends(require_role("pharmacy"))):
    docs = await db.medicines.find({"pharmacy_id": user["sub"]}, {"_id": 0}).to_list(5000)
    return docs


@api_router.post("/medicines")
async def create_medicine(data: MedicineCreate, user: dict = Depends(require_role("pharmacy"))):
    med = Medicine(pharmacy_id=user["sub"], **data.dict())
    doc = med.dict()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.medicines.insert_one(doc.copy())
    return doc


@api_router.patch("/medicines/{medicine_id}")
async def update_medicine(medicine_id: str, data: MedicineUpdate, user: dict = Depends(require_role("pharmacy"))):
    updates = {k: v for k, v in data.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No updates")
    result = await db.medicines.update_one({"id": medicine_id, "pharmacy_id": user["sub"]}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    doc = await db.medicines.find_one({"id": medicine_id}, {"_id": 0})
    return doc


@api_router.delete("/medicines/{medicine_id}")
async def delete_medicine(medicine_id: str, user: dict = Depends(require_role("pharmacy"))):
    result = await db.medicines.delete_one({"id": medicine_id, "pharmacy_id": user["sub"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@api_router.get("/medicines/barcode/{barcode}")
async def get_by_barcode(barcode: str, user: dict = Depends(require_role("pharmacy"))):
    doc = await db.medicines.find_one({"pharmacy_id": user["sub"], "barcode": barcode}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="لم يتم العثور على الدواء")
    return doc


@api_router.post("/medicines/sell")
async def sell_medicines(data: SellRequest, user: dict = Depends(require_role("pharmacy"))):
    total = 0.0
    sold_items = []
    for item in data.items:
        med = await db.medicines.find_one({"id": item.medicine_id, "pharmacy_id": user["sub"]}, {"_id": 0})
        if not med:
            raise HTTPException(status_code=404, detail=f"الدواء غير موجود")
        if med["quantity"] < item.quantity:
            raise HTTPException(status_code=400, detail=f"الكمية غير كافية لـ {med['name']}")
        new_qty = med["quantity"] - item.quantity
        await db.medicines.update_one({"id": item.medicine_id}, {"$set": {"quantity": new_qty}})
        total += med["price"] * item.quantity
        sold_items.append({"name": med["name"], "quantity": item.quantity, "price": med["price"]})

    sale_doc = {
        "id": str(uuid.uuid4()),
        "pharmacy_id": user["sub"],
        "items": sold_items,
        "total": total,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.sales.insert_one(sale_doc.copy())
    sale_doc.pop("_id", None)
    return {"total": total, "sale_id": sale_doc["id"], "items": sold_items}


@api_router.post("/medicines/buy")
async def buy_medicine(data: BuyRequest, user: dict = Depends(require_role("pharmacy"))):
    # Find existing by barcode or name to increment quantity
    query = {"pharmacy_id": user["sub"]}
    if data.barcode:
        existing = await db.medicines.find_one({**query, "barcode": data.barcode}, {"_id": 0})
    else:
        existing = await db.medicines.find_one({**query, "name": data.name}, {"_id": 0})

    if existing:
        new_qty = existing["quantity"] + data.quantity
        updates = {"quantity": new_qty, "price": data.price}
        if data.image_base64:
            updates["image_base64"] = data.image_base64
        await db.medicines.update_one({"id": existing["id"]}, {"$set": updates})
        existing.update(updates)
        return existing

    med = Medicine(
        pharmacy_id=user["sub"],
        name=data.name,
        barcode=data.barcode,
        quantity=data.quantity,
        price=data.price,
        image_base64=data.image_base64,
    )
    doc = med.dict()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.medicines.insert_one(doc.copy())
    return doc


# ---------- AI Identify ----------
@api_router.post("/medicines/identify")
async def identify_medicine(data: IdentifyImage, user: dict = Depends(get_current_user)):
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"identify-{uuid.uuid4()}",
            system_message="أنت خبير صيدلة. مهمتك تحديد اسم الدواء من الصورة. أجب فقط باسم الدواء بالعربية أو الإنجليزية كما هو مكتوب على العبوة. إذا لم تستطع التعرف، أجب بكلمة واحدة: UNKNOWN"
        ).with_model("gemini", "gemini-3-flash-preview")

        img = ImageContent(image_base64=data.image_base64)
        msg = UserMessage(text="ما اسم هذا الدواء؟ أعطني الاسم فقط بدون أي شرح.", file_contents=[img])
        response = await chat.send_message(msg)
        name = (response or "").strip().split("\n")[0][:100]
        return {"name": name}
    except Exception as e:
        logger.exception("identify failed")
        raise HTTPException(status_code=500, detail=f"فشل التعرف: {str(e)}")


# ---------- Orders ----------
@api_router.post("/orders")
async def create_order(data: OrderCreate, user: dict = Depends(require_role("pharmacy"))):
    order = {
        "id": str(uuid.uuid4()),
        "pharmacy_id": user["sub"],
        "items": [item.dict() for item in data.items],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.orders.insert_one(order.copy())
    order.pop("_id", None)
    return order


@api_router.get("/orders")
async def list_orders(user: dict = Depends(require_role("pharmacy"))):
    docs = await db.orders.find({"pharmacy_id": user["sub"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return docs


# ---------- Supplier Products ----------
@api_router.get("/supplier/products")
async def list_my_products(user: dict = Depends(require_role("supplier"))):
    docs = await db.supplier_products.find({"supplier_id": user["sub"]}, {"_id": 0}).to_list(5000)
    return docs


@api_router.post("/supplier/products")
async def add_supplier_product(data: SupplierProductCreate, user: dict = Depends(require_role("supplier"))):
    supplier = await db.suppliers.find_one({"id": user["sub"]}, {"_id": 0})
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    prod = SupplierProduct(
        supplier_id=user["sub"],
        supplier_name=supplier["name"],
        supplier_phone=supplier.get("phone"),
        **data.dict(),
    )
    doc = prod.dict()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.supplier_products.insert_one(doc.copy())
    return doc


@api_router.post("/orders/optimize")
async def optimize_order(data: OptimizeRequest, user: dict = Depends(require_role("pharmacy"))):
    """
    Compute price-optimal supplier plans for a basket.
    Returns:
      - per_item: cheapest supplier per item (greedy global optimum without fixed costs)
      - single_supplier: ranked list of suppliers that can fully fulfill the basket
      - smart_split: greedy per-item, supports splitting one item across suppliers
                     when single-supplier qty is insufficient
      - unavailable: items no supplier has
      - savings: vs the most expensive option
    """
    products = await db.supplier_products.find({}, {"_id": 0}).to_list(5000)

    # ---- Arabic-aware word-boundary matcher ----
    _DIACRITICS = re.compile(r'[\u064B-\u0652\u0670\u0640]')

    def _normalize(s: str) -> str:
        s = (s or "").strip().lower()
        s = _DIACRITICS.sub('', s)
        s = s.replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا')
        s = s.replace('ى', 'ي').replace('ئ', 'ي').replace('ؤ', 'و')
        s = s.replace('ة', 'ه')
        return s

    def _tokens(s: str) -> set[str]:
        return {t for t in re.findall(r'\w+', s, flags=re.UNICODE) if len(t) >= 2}

    def matches(query: str, name: str) -> bool:
        q = _normalize(query)
        n = _normalize(name)
        if not q or not n:
            return False
        if q == n:
            return True
        # Token overlap of length >= 3 prevents short false positives (e.g. "أدول" vs "بنادول")
        shared = _tokens(q) & _tokens(n)
        if any(len(t) >= 3 for t in shared):
            return True
        # Substring fallback only for long queries (>= 6 chars) — supports concatenated names
        if len(q) >= 6 and (q in n or n in q):
            return True
        return False

    # ---- For each requested item, gather supplier offers (sorted by price asc) ----
    per_item_options: list[dict] = []
    unavailable: list[str] = []
    for it in data.items:
        offers = []
        for p in products:
            if matches(it.name, p["name"]):
                offers.append({
                    "product_id": p["id"],
                    "supplier_id": p["supplier_id"],
                    "supplier_name": p["supplier_name"],
                    "supplier_phone": p.get("supplier_phone"),
                    "matched_name": p["name"],
                    "price": float(p.get("price") or 0),
                    "available_qty": int(p.get("quantity") or 0),
                    "delivery_time": p.get("delivery_time"),
                })
        offers.sort(key=lambda x: x["price"])
        if not offers:
            unavailable.append(it.name)
        per_item_options.append({"name": it.name, "quantity": it.quantity, "offers": offers})

    # ---- Plan 1: Per-item cheapest (ignore qty constraints) ----
    per_item_plan = []
    per_item_total = 0.0
    for opt in per_item_options:
        if not opt["offers"]:
            continue
        best = opt["offers"][0]
        line_total = best["price"] * opt["quantity"]
        per_item_total += line_total
        per_item_plan.append({
            "name": opt["name"],
            "quantity": opt["quantity"],
            "supplier_id": best["supplier_id"],
            "supplier_name": best["supplier_name"],
            "supplier_phone": best.get("supplier_phone"),
            "unit_price": best["price"],
            "line_total": line_total,
        })

    # ---- Plan 2: Single supplier (each must have ALL items, ignore qty) ----
    single_supplier = []
    suppliers_by_id: dict[str, dict] = {}
    for p in products:
        suppliers_by_id.setdefault(p["supplier_id"], {
            "supplier_id": p["supplier_id"],
            "supplier_name": p["supplier_name"],
            "supplier_phone": p.get("supplier_phone"),
        })
    for sid, sinfo in suppliers_by_id.items():
        items_for_supplier = []
        ok = True
        total = 0.0
        for opt in per_item_options:
            match = next((o for o in opt["offers"] if o["supplier_id"] == sid), None)
            if not match:
                ok = False
                break
            line = match["price"] * opt["quantity"]
            total += line
            items_for_supplier.append({
                "name": opt["name"],
                "quantity": opt["quantity"],
                "unit_price": match["price"],
                "line_total": line,
            })
        if ok and items_for_supplier:
            single_supplier.append({
                **sinfo,
                "items": items_for_supplier,
                "total": total,
            })
    single_supplier.sort(key=lambda x: x["total"])

    # ---- Plan 3: Smart split (greedy per item, may split one item across suppliers if qty insufficient) ----
    # Group fulfillment per supplier so we can send one WhatsApp per supplier
    split_by_supplier: dict[str, dict] = {}
    smart_total = 0.0
    smart_items_summary = []
    for opt in per_item_options:
        remaining = opt["quantity"]
        item_breakdown = []
        for offer in opt["offers"]:
            if remaining <= 0:
                break
            avail = offer["available_qty"] if offer["available_qty"] > 0 else remaining
            take = min(avail, remaining)
            if take <= 0:
                continue
            line = offer["price"] * take
            smart_total += line
            remaining -= take
            sid = offer["supplier_id"]
            grp = split_by_supplier.setdefault(sid, {
                "supplier_id": sid,
                "supplier_name": offer["supplier_name"],
                "supplier_phone": offer.get("supplier_phone"),
                "items": [],
                "total": 0.0,
            })
            grp["items"].append({
                "name": opt["name"],
                "quantity": take,
                "unit_price": offer["price"],
                "line_total": line,
            })
            grp["total"] += line
            item_breakdown.append({
                "supplier_id": sid,
                "supplier_name": offer["supplier_name"],
                "quantity": take,
                "unit_price": offer["price"],
            })
        smart_items_summary.append({
            "name": opt["name"],
            "requested_quantity": opt["quantity"],
            "fulfilled_quantity": opt["quantity"] - remaining,
            "missing_quantity": remaining,
            "breakdown": item_breakdown,
        })

    smart_split_groups = sorted(split_by_supplier.values(), key=lambda x: -x["total"])

    # ---- Savings ----
    candidates = []
    if per_item_plan:
        candidates.append(per_item_total)
    if single_supplier:
        candidates.append(single_supplier[0]["total"])
    if smart_split_groups:
        candidates.append(smart_total)

    most_expensive = max(candidates) if candidates else 0
    cheapest = min(candidates) if candidates else 0

    return {
        "unavailable": unavailable,
        "per_item": {
            "plan": per_item_plan,
            "total": per_item_total,
            "savings_vs_max": round(most_expensive - per_item_total, 2),
        },
        "single_supplier": {
            "options": single_supplier,
            "best": single_supplier[0] if single_supplier else None,
            "savings_vs_max": round(most_expensive - single_supplier[0]["total"], 2) if single_supplier else 0,
        },
        "smart_split": {
            "groups": smart_split_groups,
            "items_summary": smart_items_summary,
            "total": round(smart_total, 2),
            "savings_vs_max": round(most_expensive - smart_total, 2) if smart_split_groups else 0,
        },
        "summary": {
            "cheapest_total": cheapest,
            "most_expensive_total": most_expensive,
            "max_savings": round(most_expensive - cheapest, 2),
        },
    }


@api_router.delete("/supplier/products/{product_id}")
async def delete_supplier_product(product_id: str, user: dict = Depends(require_role("supplier"))):
    result = await db.supplier_products.delete_one({"id": product_id, "supplier_id": user["sub"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@api_router.get("/marketplace")
async def marketplace(user: dict = Depends(get_current_user)):
    docs = await db.supplier_products.find({}, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return docs


@api_router.get("/")
async def root():
    return {"message": "Pharmacy Cashier API"}


# ---------- Catalog Import (AI) ----------
class CatalogUploadIn(BaseModel):
    file_b64: str
    file_type: str  # "pdf" | "image/jpeg" | "image/png" etc.
    filename: Optional[str] = None


class CatalogItemPatch(BaseModel):
    extracted_name: Optional[str] = None
    strength: Optional[str] = None
    dosage_form: Optional[str] = None
    manufacturer: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    approved_name: Optional[str] = None
    match_status: Optional[str] = None  # "approved" | "rejected"


@api_router.post("/supplier/catalog/upload")
async def catalog_upload(
    data: CatalogUploadIn,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_role("supplier")),
):
    if not data.file_b64:
        raise HTTPException(status_code=400, detail="ملف فارغ")
    file_size = (len(data.file_b64) * 3) // 4
    if file_size > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="حجم الملف يتجاوز 12MB")
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "supplier_id": user["sub"],
        "status": "pending",
        "progress": 0,
        "file_type": data.file_type,
        "filename": data.filename,
        "file_size": file_size,
        "file_b64": data.file_b64,
        "total_items": 0,
        "items_to_review": 0,
        "page_count": 0,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }
    await db.import_jobs.insert_one(job.copy())
    background_tasks.add_task(catalog_import.process_import_job, db, job_id)
    return {"job_id": job_id, "status": "pending"}


@api_router.get("/supplier/catalog/jobs")
async def list_jobs(user: dict = Depends(require_role("supplier"))):
    docs = await db.import_jobs.find(
        {"supplier_id": user["sub"]},
        {"_id": 0, "file_b64": 0},
    ).sort("created_at", -1).to_list(100)
    return docs


@api_router.get("/supplier/catalog/jobs/{job_id}")
async def get_job(job_id: str, user: dict = Depends(require_role("supplier"))):
    job = await db.import_jobs.find_one(
        {"id": job_id, "supplier_id": user["sub"]},
        {"_id": 0, "file_b64": 0},
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    items = await db.import_items.find({"job_id": job_id}, {"_id": 0}).to_list(5000)
    grouped = {"auto": [], "needs_review": [], "approved": [], "rejected": []}
    for it in items:
        grouped.setdefault(it.get("match_status", "needs_review"), []).append(it)
    return {"job": job, "items": items, "grouped": grouped}


@api_router.patch("/supplier/catalog/items/{item_id}")
async def patch_item(
    item_id: str,
    data: CatalogItemPatch,
    user: dict = Depends(require_role("supplier")),
):
    item = await db.import_items.find_one({"id": item_id}, {"_id": 0})
    if not item or item.get("supplier_id") != user["sub"]:
        raise HTTPException(status_code=404, detail="Item not found")

    updates: dict = {}
    extracted = item.get("extracted", {}).copy()
    if data.extracted_name is not None:
        extracted["name"] = data.extracted_name
    if data.strength is not None:
        extracted["strength"] = data.strength
    if data.dosage_form is not None:
        extracted["dosage_form"] = data.dosage_form
    if data.manufacturer is not None:
        extracted["manufacturer"] = data.manufacturer
    if data.price is not None:
        extracted["price"] = float(data.price)
    if data.quantity is not None:
        extracted["quantity"] = int(data.quantity)
    if extracted != item.get("extracted", {}):
        updates["extracted"] = extracted

    if data.approved_name is not None:
        updates["approved_name"] = data.approved_name
        # Learn the correction so future imports auto-resolve
        if item.get("canonical_key") and data.approved_name != item.get("suggested_canonical_name"):
            await db.catalog_corrections.update_one(
                {"supplier_id": user["sub"], "original_key": item["canonical_key"]},
                {"$set": {"corrected_name": data.approved_name},
                 "$inc": {"count": 1}},
                upsert=True,
            )

    if data.match_status is not None:
        if data.match_status not in ("approved", "rejected", "needs_review"):
            raise HTTPException(status_code=400, detail="Invalid match_status")
        updates["match_status"] = data.match_status

    if updates:
        await db.import_items.update_one({"id": item_id}, {"$set": updates})

    fresh = await db.import_items.find_one({"id": item_id}, {"_id": 0})
    return fresh


@api_router.post("/supplier/catalog/jobs/{job_id}/publish")
async def publish_job(job_id: str, user: dict = Depends(require_role("supplier"))):
    job = await db.import_jobs.find_one({"id": job_id, "supplier_id": user["sub"]}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in ("review", "published"):
        raise HTTPException(status_code=400, detail="Job not ready to publish")

    supplier = await db.suppliers.find_one({"id": user["sub"]}, {"_id": 0})
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    # Pick all items that are auto-confident OR explicitly approved by user
    items = await db.import_items.find(
        {"job_id": job_id, "match_status": {"$in": ["auto", "approved"]}},
        {"_id": 0},
    ).to_list(5000)

    created = 0
    updated = 0
    for it in items:
        ext = it.get("extracted", {})
        name = (it.get("approved_name") or ext.get("name") or "").strip()
        if not name:
            continue
        # If a product with the same name already exists for this supplier, update it
        existing = await db.supplier_products.find_one(
            {"supplier_id": user["sub"], "name": name}, {"_id": 0}
        )
        if existing:
            await db.supplier_products.update_one(
                {"id": existing["id"]},
                {"$set": {
                    "price": float(ext.get("price") or existing.get("price", 0)),
                    "quantity": int(ext.get("quantity") or existing.get("quantity", 0)),
                }},
            )
            updated += 1
        else:
            doc = {
                "id": str(uuid.uuid4()),
                "supplier_id": user["sub"],
                "supplier_name": supplier["name"],
                "supplier_phone": supplier.get("phone"),
                "name": name,
                "price": float(ext.get("price") or 0),
                "quantity": int(ext.get("quantity") or 0),
                "delivery_time": None,
                "image_base64": None,
                "description": " | ".join(filter(None, [
                    ext.get("strength"), ext.get("dosage_form"), ext.get("manufacturer"),
                ])) or None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await db.supplier_products.insert_one(doc.copy())
            created += 1

    await db.import_jobs.update_one(
        {"id": job_id},
        {"$set": {"status": "published",
                  "published_at": datetime.now(timezone.utc).isoformat(),
                  "published_count": created + updated}},
    )
    return {"created": created, "updated": updated, "total": created + updated}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
