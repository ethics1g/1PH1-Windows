from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import uuid
import hashlib
import jwt
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone, timedelta

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
    name: str
    price: float
    image_base64: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SupplierProductCreate(BaseModel):
    name: str
    price: float
    image_base64: Optional[str] = None
    description: Optional[str] = None


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
    prod = SupplierProduct(supplier_id=user["sub"], supplier_name=supplier["name"], **data.dict())
    doc = prod.dict()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.supplier_products.insert_one(doc.copy())
    return doc


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
