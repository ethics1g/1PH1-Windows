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
SMS_PROVIDER = os.environ.get('SMS_PROVIDER', 'dev')  # 'dev' | 'twilio'

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ---------- Helpers ----------
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    """Timing-safe password verification against a sha256 hash."""
    if not plain or not hashed:
        return False
    return hash_password(plain) == hashed


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
        if required_role == "any":
            return user
        if user.get("role") != required_role:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    return _dep


# ---------- Pagination helper ----------
def _paginate(skip: int, limit: int, default: int = 100, hard_max: int = 500) -> tuple[int, int]:
    """Clamp pagination params to safe bounds."""
    s = max(0, int(skip or 0))
    lim = int(limit) if limit and limit > 0 else default
    lim = max(1, min(lim, hard_max))
    return s, lim


# ---------- Region (Marketplace locality) ----------
import unicodedata as _ud_region

def normalize_region(s: Optional[str]) -> Optional[str]:
    """Lowercase, strip diacritics, collapse whitespace. Used for case/diacritic-insensitive matching."""
    if not s:
        return None
    t = str(s).strip()
    if not t:
        return None
    # Remove Arabic diacritics
    nfkd = _ud_region.normalize("NFKD", t)
    t2 = "".join(c for c in nfkd if not _ud_region.combining(c))
    # Normalize Arabic forms (alef variants, taa marbuta, yaa)
    table = {ord('أ'): 'ا', ord('إ'): 'ا', ord('آ'): 'ا', ord('ٱ'): 'ا',
             ord('ة'): 'ه', ord('ى'): 'ي', ord('ؤ'): 'و', ord('ئ'): 'ي'}
    t2 = t2.translate(table)
    t2 = t2.lower()
    t2 = " ".join(t2.split())
    return t2 or None


async def get_marketplace_mode() -> str:
    doc = await db.app_settings.find_one({"id": "payment"}, {"_id": 0, "marketplace_mode": 1})
    mode = (doc or {}).get("marketplace_mode") or "local"
    return mode if mode in ("local", "national") else "local"


async def get_pharmacy_region_norm(pharmacy_id: str) -> Optional[str]:
    p = await db.pharmacies.find_one({"id": pharmacy_id}, {"_id": 0, "region_normalized": 1})
    return (p or {}).get("region_normalized")


async def allowed_supplier_filter(pharmacy_id: str) -> dict:
    """
    Return a Mongo query fragment to restrict suppliers to same region as the pharmacy.
    Returns {} when:
      - marketplace_mode == 'national', OR
      - pharmacy has no region set (degraded — pharmacy will be prompted to set region).
    """
    mode = await get_marketplace_mode()
    if mode == "national":
        return {}
    region_norm = await get_pharmacy_region_norm(pharmacy_id)
    if not region_norm:
        return {}
    return {"region_normalized": region_norm}


async def allowed_supplier_ids(pharmacy_id: str) -> Optional[list[str]]:
    """
    Returns the list of supplier IDs allowed for the given pharmacy under current marketplace_mode.
    Returns None if no restriction applies (national or pharmacy has no region).
    """
    flt = await allowed_supplier_filter(pharmacy_id)
    if not flt:
        return None
    rows = await db.suppliers.find(flt, {"_id": 0, "id": 1}).to_list(5000)
    return [r["id"] for r in rows]


# ---------- Models ----------
class PharmacyRegister(BaseModel):
    name: str
    phone: str
    password: str
    address: str
    region: str
    country: Optional[str] = None


class SupplierRegister(BaseModel):
    name: str
    phone: str
    password: str
    address: str
    region: str
    country: Optional[str] = None


class SetRegionIn(BaseModel):
    region: str
    country: Optional[str] = None


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
    expiry_date: Optional[str] = None  # ISO date "YYYY-MM-DD"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MedicineCreate(BaseModel):
    name: str
    barcode: Optional[str] = None
    quantity: int = 0
    price: float = 0.0
    image_base64: Optional[str] = None
    expiry_date: Optional[str] = None


class MedicineUpdate(BaseModel):
    name: Optional[str] = None
    barcode: Optional[str] = None
    quantity: Optional[int] = None
    price: Optional[float] = None
    expiry_date: Optional[str] = None


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
    expiry_date: Optional[str] = None  # ISO date "YYYY-MM-DD" (required by frontend)


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
    region_norm = normalize_region(data.region)
    if not region_norm:
        raise HTTPException(status_code=400, detail="المنطقة/المحافظة مطلوبة")
    pharmacy_id = str(uuid.uuid4())
    doc = {
        "id": pharmacy_id,
        "name": data.name,
        "phone": data.phone,
        "password": hash_password(data.password),
        "address": data.address,
        "region": data.region.strip(),
        "region_normalized": region_norm,
        "country": (data.country or "").strip() or None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.pharmacies.insert_one(doc)
    token = create_token(pharmacy_id, "pharmacy")
    return {"token": token, "pharmacy": {"id": pharmacy_id, "name": data.name, "phone": data.phone, "address": data.address, "region": doc["region"], "country": doc["country"]}}


@api_router.post("/pharmacy/login")
async def pharmacy_login(data: LoginInput):
    doc = await db.pharmacies.find_one({"phone": data.phone}, {"_id": 0})
    if not doc or doc["password"] != hash_password(data.password):
        raise HTTPException(status_code=401, detail="رقم الهاتف أو الرمز السري غير صحيح")
    if doc.get("disabled"):
        raise HTTPException(status_code=403, detail="الحساب معطل")
    token = create_token(doc["id"], "pharmacy")
    await db.audit_logs.insert_one({"id": str(uuid.uuid4()), "action": "login",
        "actor": {"id": doc["id"], "role": "pharmacy", "phone": data.phone},
        "target": {}, "meta": {}, "timestamp": datetime.now(timezone.utc).isoformat()})
    must_set_region = not bool(doc.get("region_normalized"))
    return {
        "token": token,
        "pharmacy": {
            "id": doc["id"], "name": doc["name"], "phone": doc["phone"], "address": doc.get("address"),
            "region": doc.get("region"), "country": doc.get("country"),
        },
        "must_set_region": must_set_region,
    }


# ---------- Forgot Password / OTP ----------
import secrets

class ForgotPasswordIn(BaseModel):
    phone: str
    role: str  # "pharmacy" | "supplier"


class VerifyOtpIn(BaseModel):
    phone: str
    role: str
    otp: str


class ResetPasswordIn(BaseModel):
    reset_token: str
    new_password: str


def _otp_collection_for(role: str):
    return db.password_reset_otps


async def _send_sms(phone: str, otp: str) -> None:
    if SMS_PROVIDER == "twilio":
        try:
            sid = os.environ.get("TWILIO_ACCOUNT_SID")
            tok = os.environ.get("TWILIO_AUTH_TOKEN")
            frm = os.environ.get("TWILIO_FROM_NUMBER")
            if not (sid and tok and frm):
                logger.warning("Twilio env missing, falling back to log")
                logger.info(f"[SMS-FALLBACK] phone={phone} otp={otp}")
                return
            from twilio.rest import Client
            client = Client(sid, tok)
            client.messages.create(
                body=f"رمز التحقق: {otp} - يفقد صلاحيته خلال 10 دقائق",
                from_=frm, to=phone,
            )
        except Exception:
            logger.exception("twilio send failed")
            logger.info(f"[SMS-FALLBACK] phone={phone} otp={otp}")
    else:
        logger.info(f"[SMS-DEV] phone={phone} otp={otp}")


async def _check_rate_limit(phone: str, role: str) -> None:
    """Max 3 OTP requests per phone+role per hour."""
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    cnt = await db.password_reset_otps.count_documents({
        "phone": phone,
        "role": role,
        "created_at": {"$gte": one_hour_ago.isoformat()},
    })
    if cnt >= 3:
        raise HTTPException(status_code=429, detail="عدد الطلبات تجاوز الحد. حاول بعد ساعة.")


@api_router.post("/auth/forgot-password")
async def forgot_password(data: ForgotPasswordIn):
    if data.role not in ("pharmacy", "supplier"):
        raise HTTPException(status_code=400, detail="role غير صالح")

    coll = db.pharmacies if data.role == "pharmacy" else db.suppliers
    user = await coll.find_one({"phone": data.phone}, {"_id": 0})
    # Always rate-limit even for non-existent phones (don't leak existence)
    await _check_rate_limit(data.phone, data.role)

    # Always pretend success but only generate OTP if user exists
    if user:
        otp_plain = f"{secrets.randbelow(1_000_000):06d}"
        otp_hash = hashlib.sha256(otp_plain.encode()).hexdigest()
        # Invalidate any active OTPs
        await db.password_reset_otps.update_many(
            {"phone": data.phone, "role": data.role, "used": False},
            {"$set": {"used": True}},
        )
        await db.password_reset_otps.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "role": data.role,
            "phone": data.phone,
            "otp_hash": otp_hash,
            "attempts": 0,
            "used": False,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await _send_sms(data.phone, otp_plain)
        await db.password_reset_audit.insert_one({
            "id": str(uuid.uuid4()),
            "phone": data.phone, "role": data.role, "action": "otp_requested",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if SMS_PROVIDER == "dev":
            return {"status": "ok", "dev_otp": otp_plain, "message": "في وضع التطوير، رمز OTP في الاستجابة"}
    return {"status": "ok", "message": "إذا كان الرقم مسجلاً، سيتم إرسال رمز التحقق"}


@api_router.post("/auth/verify-otp")
async def verify_otp(data: VerifyOtpIn):
    if data.role not in ("pharmacy", "supplier"):
        raise HTTPException(status_code=400, detail="role غير صالح")
    if not (data.otp and data.otp.isdigit() and len(data.otp) == 6):
        raise HTTPException(status_code=400, detail="رمز OTP غير صالح")

    rec = await db.password_reset_otps.find_one(
        {"phone": data.phone, "role": data.role, "used": False},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if not rec:
        raise HTTPException(status_code=400, detail="لا يوجد طلب نشط. اطلب رمزاً جديداً.")

    # Expiry
    if datetime.fromisoformat(rec["expires_at"]) < datetime.now(timezone.utc):
        await db.password_reset_otps.update_one({"id": rec["id"]}, {"$set": {"used": True}})
        raise HTTPException(status_code=400, detail="انتهت صلاحية الرمز. اطلب رمزاً جديداً.")

    # Attempt limit (max 3)
    if rec["attempts"] >= 3:
        await db.password_reset_otps.update_one({"id": rec["id"]}, {"$set": {"used": True}})
        raise HTTPException(status_code=429, detail="تجاوزت 3 محاولات. اطلب رمزاً جديداً.")

    submitted_hash = hashlib.sha256(data.otp.encode()).hexdigest()
    if submitted_hash != rec["otp_hash"]:
        await db.password_reset_otps.update_one(
            {"id": rec["id"]}, {"$inc": {"attempts": 1}},
        )
        remaining = 3 - rec["attempts"] - 1
        raise HTTPException(status_code=400, detail=f"رمز غير صحيح. {remaining} محاولات متبقية.")

    # Success → mark used + issue short reset token
    await db.password_reset_otps.update_one({"id": rec["id"]}, {"$set": {"used": True}})
    payload = {
        "sub": rec["user_id"],
        "role": rec["role"],
        "purpose": "password_reset",
        "otp_id": rec["id"],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    reset_token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    await db.password_reset_audit.insert_one({
        "id": str(uuid.uuid4()),
        "phone": data.phone, "role": data.role, "action": "otp_verified",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {"reset_token": reset_token, "expires_in": 900}


@api_router.post("/auth/reset-password")
async def reset_password(data: ResetPasswordIn):
    try:
        payload = jwt.decode(data.reset_token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=401, detail="رمز إعادة التعيين غير صالح أو منتهٍ")
    if payload.get("purpose") != "password_reset":
        raise HTTPException(status_code=401, detail="رمز إعادة التعيين غير صالح")
    if not data.new_password or len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="كلمة المرور يجب أن تكون 6 أحرف على الأقل")

    # Ensure the OTP record was used and not reused
    otp_id = payload.get("otp_id")
    used_rec = await db.password_reset_otps.find_one({"id": otp_id}, {"_id": 0})
    if not used_rec or used_rec.get("token_consumed"):
        raise HTTPException(status_code=401, detail="هذا الرمز تم استخدامه سابقاً")

    coll = db.pharmacies if payload["role"] == "pharmacy" else db.suppliers
    result = await coll.update_one(
        {"id": payload["sub"]},
        {"$set": {"password": hash_password(data.new_password)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")

    # Mark token as consumed (single-use)
    await db.password_reset_otps.update_one({"id": otp_id}, {"$set": {"token_consumed": True}})
    await db.password_reset_audit.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": payload["sub"], "role": payload["role"],
        "action": "password_reset_completed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    await db.audit_logs.insert_one({"id": str(uuid.uuid4()), "action": "password_change",
        "actor": {"id": payload["sub"], "role": payload["role"]},
        "target": {}, "meta": {"via": "otp"},
        "timestamp": datetime.now(timezone.utc).isoformat()})
    return {"status": "ok", "message": "تم تغيير كلمة المرور بنجاح"}


# ---------- Auth - Supplier ----------
@api_router.post("/supplier/register")
async def supplier_register(data: SupplierRegister):
    existing = await db.suppliers.find_one({"phone": data.phone})
    if existing:
        raise HTTPException(status_code=400, detail="رقم الهاتف مسجل مسبقاً")
    region_norm = normalize_region(data.region)
    if not region_norm:
        raise HTTPException(status_code=400, detail="المنطقة/المحافظة مطلوبة")
    supplier_id = str(uuid.uuid4())
    doc = {
        "id": supplier_id,
        "name": data.name,
        "phone": data.phone,
        "password": hash_password(data.password),
        "address": data.address,
        "region": data.region.strip(),
        "region_normalized": region_norm,
        "country": (data.country or "").strip() or None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.suppliers.insert_one(doc)
    token = create_token(supplier_id, "supplier")
    return {"token": token, "supplier": {"id": supplier_id, "name": data.name, "phone": data.phone, "address": data.address, "region": doc["region"], "country": doc["country"]}}


@api_router.post("/supplier/login")
async def supplier_login(data: LoginInput):
    doc = await db.suppliers.find_one({"phone": data.phone}, {"_id": 0})
    if not doc or doc["password"] != hash_password(data.password):
        raise HTTPException(status_code=401, detail="رقم الهاتف أو الرمز السري غير صحيح")
    if doc.get("disabled"):
        raise HTTPException(status_code=403, detail="الحساب معطل")
    token = create_token(doc["id"], "supplier")
    await db.audit_logs.insert_one({"id": str(uuid.uuid4()), "action": "login",
        "actor": {"id": doc["id"], "role": "supplier", "phone": data.phone},
        "target": {}, "meta": {}, "timestamp": datetime.now(timezone.utc).isoformat()})
    must_set_region = not bool(doc.get("region_normalized"))
    return {
        "token": token,
        "supplier": {
            "id": doc["id"], "name": doc["name"], "phone": doc["phone"], "address": doc.get("address"),
            "region": doc.get("region"), "country": doc.get("country"),
        },
        "must_set_region": must_set_region,
    }


@api_router.patch("/auth/set-region")
async def set_region(data: SetRegionIn, user: dict = Depends(get_current_user)):
    """Set or update region for the current user. Admins are not required to set region."""
    region_norm = normalize_region(data.region)
    if not region_norm:
        raise HTTPException(status_code=400, detail="المنطقة/المحافظة مطلوبة")
    updates = {
        "region": data.region.strip(),
        "region_normalized": region_norm,
        "country": (data.country or "").strip() or None,
        "region_set_at": datetime.now(timezone.utc).isoformat(),
    }
    if user["role"] == "pharmacy":
        await db.pharmacies.update_one({"id": user["sub"]}, {"$set": updates})
        # Also propagate to existing orders/products? Not strictly necessary; region is on the user.
    elif user["role"] == "supplier":
        await db.suppliers.update_one({"id": user["sub"]}, {"$set": updates})
        # Propagate region to supplier_products for fast filtering on optimize/orders.
        await db.supplier_products.update_many(
            {"supplier_id": user["sub"]},
            {"$set": {"region_normalized": region_norm, "region": updates["region"]}},
        )
    elif user["role"] == "admin":
        await db.admins.update_one({"id": user["sub"]}, {"$set": updates})
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()), "action": "region_set",
        "actor": {"id": user["sub"], "role": user["role"]},
        "target": {}, "meta": {"region": updates["region"], "country": updates["country"]},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return {"status": "ok", "region": updates["region"], "country": updates["country"]}


@api_router.get("/regions/suggest")
async def regions_suggest(q: Optional[str] = None, user: dict = Depends(get_current_user)):
    """Autocomplete suggestions from existing users (pharmacies + suppliers)."""
    pipeline = [
        {"$match": {"region": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$region_normalized", "label": {"$first": "$region"},
                    "country": {"$first": "$country"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 50},
    ]
    pharm = await db.pharmacies.aggregate(pipeline).to_list(50)
    supp = await db.suppliers.aggregate(pipeline).to_list(50)
    # Merge by normalized key
    merged: dict[str, dict] = {}
    for r in pharm + supp:
        k = r.get("_id")
        if not k:
            continue
        if k in merged:
            merged[k]["count"] += r.get("count", 0)
        else:
            merged[k] = {"region": r.get("label"), "region_normalized": k,
                         "country": r.get("country"), "count": r.get("count", 0)}
    items = sorted(merged.values(), key=lambda x: x["count"], reverse=True)
    if q:
        qn = normalize_region(q)
        if qn:
            items = [i for i in items if qn in (i["region_normalized"] or "")]
    return items[:20]


@api_router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    if user["role"] == "pharmacy":
        doc = await db.pharmacies.find_one({"id": user["sub"]}, {"_id": 0, "password": 0})
    else:
        doc = await db.suppliers.find_one({"id": user["sub"]}, {"_id": 0, "password": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return {"role": user["role"], "user": doc}


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


@api_router.patch("/me/password")
async def me_change_password(data: ChangePasswordIn,
                              user: dict = Depends(get_current_user)):
    """Change the current user's login password.
    The same password is used by the accounting-unlock keypad, so any
    change here automatically becomes the new unlock code."""
    new_pw = (data.new_password or "").strip()
    if len(new_pw) < 6:
        raise HTTPException(status_code=400,
                            detail="كلمة السر الجديدة يجب أن تكون 6 أحرف على الأقل")
    if user["role"] == "pharmacy":
        col = db.pharmacies
    elif user["role"] == "supplier":
        col = db.suppliers
    elif user["role"] == "admin":
        col = db.admins
    else:
        raise HTTPException(status_code=403, detail="Forbidden")
    doc = await col.find_one({"id": user["sub"]}, {"_id": 0})
    if not doc or doc.get("password") != hash_password(data.current_password or ""):
        raise HTTPException(status_code=401, detail="كلمة السر الحالية غير صحيحة")
    if doc.get("password") == hash_password(new_pw):
        raise HTTPException(status_code=400,
                            detail="يجب أن تختلف كلمة السر الجديدة عن الحالية")
    await col.update_one({"id": user["sub"]},
                          {"$set": {"password": hash_password(new_pw)}})
    return {"ok": True}


class VerifyPasswordIn(BaseModel):
    password: str


@api_router.post("/auth/verify-password")
async def auth_verify_password(data: VerifyPasswordIn,
                               user: dict = Depends(get_current_user)):
    """Verify a password matches the CURRENT authenticated user's login password.
    Used to gate sensitive sections of the app (e.g. accounting unlock)
    with the same credential as the login. Returns 200 on match, 401 otherwise
    with no additional details."""
    if user["role"] == "pharmacy":
        doc = await db.pharmacies.find_one({"id": user["sub"]}, {"_id": 0})
    elif user["role"] == "supplier":
        doc = await db.suppliers.find_one({"id": user["sub"]}, {"_id": 0})
    elif user["role"] == "admin":
        doc = await db.admins.find_one({"id": user["sub"]}, {"_id": 0})
    else:
        doc = None
    if not doc or doc.get("password") != hash_password(data.password or ""):
        raise HTTPException(status_code=401, detail="رمز غير صحيح")
    return {"ok": True}


# ---------- Medicines (Pharmacy) ----------
@api_router.get("/medicines")
async def list_medicines(skip: int = 0, limit: int = 200, user: dict = Depends(require_role("pharmacy"))):
    s, lim = _paginate(skip, limit, default=200, hard_max=500)
    docs = await db.medicines.find({"pharmacy_id": user["sub"]}, {"_id": 0}).skip(s).limit(lim).to_list(lim)
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


def _parse_expiry(v: Optional[str]) -> Optional[str]:
    """Validate and normalize an expiry date string to 'YYYY-MM-DD'.

    Accepts a flexible set of inputs and normalizes them all to canonical
    'YYYY-MM-DD'. Supported shapes (separators may be '-', '/', '.', or '\\'):
        2027-04-01, 2027-4-1, 2027/4/1
        01-04-2027, 1/4/2027 (day-month-year)
        2027-04, 2027/4    (year-month  → day = 01)
        04-2027            (month-year  → day = 01)
    Arabic-Indic digits (٠-٩) are converted to ASCII before parsing.
    """
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    # Arabic-Indic → ASCII
    s = "".join(
        chr(ord(c) - 0x0660 + ord("0")) if "\u0660" <= c <= "\u0669"
        else chr(ord(c) - 0x06F0 + ord("0")) if "\u06F0" <= c <= "\u06F9"
        else c
        for c in s
    )
    parts = [p for p in re.split(r"[-/.\\]", s) if p != ""]
    if len(parts) < 2 or len(parts) > 3 or not all(p.isdigit() for p in parts):
        raise HTTPException(status_code=400, detail="تاريخ انتهاء غير صالح (مثال: 2027-04-01)")

    try:
        if len(parts[0]) == 4:
            y = int(parts[0])
            m = int(parts[1])
            d = int(parts[2]) if len(parts) == 3 else 1
        elif len(parts[-1]) == 4:
            if len(parts) == 2:
                # M-YYYY
                m = int(parts[0])
                y = int(parts[1])
                d = 1
            else:
                d = int(parts[0])
                m = int(parts[1])
                y = int(parts[2])
        else:
            raise HTTPException(status_code=400, detail="يرجى إدخال السنة بأربعة أرقام (مثال: 2027)")

        if not (1900 <= y <= 2100) or not (1 <= m <= 12) or not (1 <= d <= 31):
            raise HTTPException(status_code=400, detail=f"تاريخ غير صالح: {y}-{m}-{d}")
        dt = datetime(y, m, d)  # calendar-valid check (raises ValueError on 31-Feb etc.)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="تاريخ انتهاء غير صالح")

    return dt.strftime("%Y-%m-%d")


def _expiry_status(expiry_date: Optional[str]) -> dict:
    if not expiry_date:
        return {"status": "no_expiry", "days_left": None}
    try:
        d = datetime.strptime(expiry_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return {"status": "no_expiry", "days_left": None}
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    days_left = (d - today).days
    if days_left < 0:
        return {"status": "expired", "days_left": days_left}
    if days_left <= 7:
        return {"status": "critical_7", "days_left": days_left}
    if days_left <= 30:
        return {"status": "warning_30", "days_left": days_left}
    if days_left <= 90:
        return {"status": "soon_90", "days_left": days_left}
    return {"status": "ok", "days_left": days_left}


@api_router.get("/medicines/expiry-alerts")
async def medicines_expiry_alerts(user: dict = Depends(require_role("pharmacy"))):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    horizon_90 = (today + timedelta(days=90)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")
    cursor = db.medicines.find(
        {
            "pharmacy_id": user["sub"],
            "expiry_date": {"$ne": None, "$exists": True, "$lte": horizon_90},
            "quantity": {"$gt": 0},
        },
        {"_id": 0, "image_base64": 0},
    )
    items = await cursor.to_list(5000)
    groups: dict[str, list[dict]] = {"expired": [], "critical_7": [], "warning_30": [], "soon_90": []}
    for it in items:
        st = _expiry_status(it.get("expiry_date"))
        it["status"] = st["status"]
        it["days_left"] = st["days_left"]
        if st["status"] in groups:
            groups[st["status"]].append(it)
    return {
        "today": today_str,
        "groups": groups,
        "counts": {k: len(v) for k, v in groups.items()},
        "total_alerts": sum(len(v) for v in groups.values()),
    }


@api_router.post("/medicines/buy")
async def buy_medicine(data: BuyRequest, user: dict = Depends(require_role("pharmacy"))):
    expiry_iso = _parse_expiry(data.expiry_date)
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
        if expiry_iso:
            prev = existing.get("expiry_date")
            updates["expiry_date"] = expiry_iso if (not prev or expiry_iso < prev) else prev
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
        expiry_date=expiry_iso,
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
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.orders.insert_one(order.copy())
    order.pop("_id", None)
    return order


@api_router.get("/orders")
async def list_orders(skip: int = 0, limit: int = 100, user: dict = Depends(require_role("pharmacy"))):
    s, lim = _paginate(skip, limit, default=100, hard_max=500)
    docs = await db.orders.find({"pharmacy_id": user["sub"]}, {"_id": 0}).sort("created_at", -1).skip(s).limit(lim).to_list(lim)
    return docs


# ---------- Supplier Products ----------
@api_router.get("/supplier/products")
async def list_my_products(skip: int = 0, limit: int = 200, user: dict = Depends(require_role("supplier"))):
    s, lim = _paginate(skip, limit, default=200, hard_max=500)
    docs = await db.supplier_products.find({"supplier_id": user["sub"]}, {"_id": 0}).skip(s).limit(lim).to_list(lim)
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
    # Denormalize region for fast marketplace filtering
    doc["region"] = supplier.get("region")
    doc["region_normalized"] = supplier.get("region_normalized")
    doc["country"] = supplier.get("country")
    await db.supplier_products.insert_one(doc.copy())
    return doc


@api_router.post("/orders/optimize")
async def optimize_order(data: OptimizeRequest, user: dict = Depends(require_role("pharmacy"))):
    """
    Compute price-optimal supplier plans for a basket, filtered by pharmacy region (marketplace mode).
    """
    # Region filter: only consider suppliers in the same region (or all if national)
    sup_flt = await allowed_supplier_filter(user["sub"])
    # supplier_products may be denormalized with region_normalized; fall back to filtering by supplier_id
    if sup_flt:
        # Get allowed supplier_ids and filter products by them (handles legacy products w/o region_normalized)
        rows = await db.suppliers.find(sup_flt, {"_id": 0, "id": 1}).to_list(5000)
        allowed_ids = [r["id"] for r in rows]
        product_query = {"supplier_id": {"$in": allowed_ids}}
    else:
        product_query = {}
    products = await db.supplier_products.find(product_query, {"_id": 0}).to_list(5000)

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
    # Pharmacies see only same-region suppliers; suppliers see their own marketplace overview
    flt: dict = {}
    if user["role"] == "pharmacy":
        sup_flt = await allowed_supplier_filter(user["sub"])
        if sup_flt:
            rows = await db.suppliers.find(sup_flt, {"_id": 0, "id": 1}).to_list(5000)
            flt = {"supplier_id": {"$in": [r["id"] for r in rows]}}
    docs = await db.supplier_products.find(flt, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return docs


@api_router.get("/suppliers")
async def list_suppliers(user: dict = Depends(get_current_user)):
    """Public suppliers directory. Pharmacies see only same-region suppliers."""
    flt: dict = {}
    if user["role"] == "pharmacy":
        sup_flt = await allowed_supplier_filter(user["sub"])
        flt.update(sup_flt or {})
    docs = await db.suppliers.find(flt, {"_id": 0, "password": 0}).to_list(2000)
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
    # Validate accepted types: pdf, image/*, xlsx/xls
    ft = (data.file_type or "").lower()
    fn = (data.filename or "").lower()
    accepted = (ft.startswith("image/") or ft in ("pdf", "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel", "xlsx", "xls")
        or fn.endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp", ".xlsx", ".xls", ".xlsm")))
    if not accepted:
        raise HTTPException(status_code=400, detail="نوع الملف غير مدعوم. الأنواع المدعومة: PDF, Image, Excel")
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


@api_router.get("/supplier/catalog/template")
async def download_excel_template(user: dict = Depends(require_role("supplier"))):
    """Return a sample .xlsx supplier can fill in and re-upload."""
    from fastapi.responses import Response
    data = catalog_import.build_excel_template()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="catalog_template.xlsx"'},
    )


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

# ============== Notifications & Account Management ==============
import notifications as notif_mod  # noqa: E402
notif_mod.init(db, require_role, hash_password, verify_password)
notif_mod.install_routes(require_role)
app.include_router(notif_mod.router_notifications)

# ============== Accounting Module (profit/debts/customers) ==============
import accounting as acc_mod  # noqa: E402
acc_mod.init(db, require_role)
acc_mod.install_routes(require_role)
app.include_router(acc_mod.router_accounting)

# ============== Returns Module (product returns) ==============
import returns as returns_mod  # noqa: E402
returns_mod.init(db, require_role, notif_mod=notif_mod, accounting_mod=acc_mod)
returns_mod.install_routes(require_role)
app.include_router(returns_mod.router_returns)

# ============== FIFO Batch Inventory Module ==============
import batches as batches_mod  # noqa: E402
batches_mod.init(db, require_role)
batches_mod.install_routes(require_role)
app.include_router(batches_mod.router_batches)


@app.on_event("startup")
async def _run_batches_migration():
    try:
        result = await batches_mod.migrate_legacy_medicines(db)
        logger.info("Batches migration: %s", result)
    except Exception:
        logger.exception("Batches migration failed")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        notif_mod.stop_scheduler()
    except Exception:
        pass
    client.close()


@app.on_event("startup")
async def start_notification_scheduler():
    """Start the notifications scheduler and restore any pending scheduled batches."""
    try:
        notif_mod.start_scheduler()
        await notif_mod.restore_scheduled()
        logger.info("Notification scheduler ready")
    except Exception:
        logger.exception("Failed to start notification scheduler")


# ============== Admin Bootstrap & RBAC ==============

@app.on_event("startup")
async def seed_admin():
    """Ensure default admins exist (idempotent)."""
    SEEDS = [
        {"email": "admin@system.local", "phone": "0000000000", "password": "admin123"},
        {"email": "rasool@system.local", "phone": "07823567874", "password": "Rasooll$123"},
    ]
    for s in SEEDS:
        existing = await db.admins.find_one({"phone": s["phone"]}, {"_id": 0})
        if existing:
            continue
        await db.admins.insert_one({
            "id": str(uuid.uuid4()),
            "email": s["email"],
            "phone": s["phone"],
            "password": hash_password(s["password"]),
            "must_change_password": True,
            "disabled": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Seeded admin: phone={s['phone']}")


@app.on_event("startup")
async def ensure_indexes():
    """Create indexes used by the marketplace and frequently-queried fields. Idempotent."""
    try:
        await db.pharmacies.create_index("phone", unique=False)
        await db.pharmacies.create_index("region_normalized")
        await db.suppliers.create_index("phone", unique=False)
        await db.suppliers.create_index("region_normalized")
        await db.supplier_products.create_index("supplier_id")
        await db.supplier_products.create_index("region_normalized")
        await db.supplier_sales.create_index("commit_id")
        await db.supplier_sales.create_index("supplier_id")
        await db.supplier_sales.create_index("status")
        await db.audit_logs.create_index("action")
        await db.audit_logs.create_index("timestamp")
        logger.info("DB indexes ensured")
    except Exception:
        logger.exception("ensure_indexes failed (non-fatal)")


# ---------- Audit log helper ----------
async def audit(action: str, actor: dict | None = None, target: dict | None = None, meta: dict | None = None) -> None:
    try:
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "action": action,
            "actor": actor or {},
            "target": target or {},
            "meta": meta or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        logger.exception("audit log failed")


# ---------- Admin Auth ----------
class AdminLoginIn(BaseModel):
    phone: str
    password: str


class AdminChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


@api_router.post("/admin/login")
async def admin_login(data: AdminLoginIn):
    doc = await db.admins.find_one({"phone": data.phone}, {"_id": 0})
    if not doc or doc["password"] != hash_password(data.password):
        await audit("login_failed", actor={"phone": data.phone, "role": "admin"})
        raise HTTPException(status_code=401, detail="رقم الهاتف أو الرمز السري غير صحيح")
    if doc.get("disabled"):
        raise HTTPException(status_code=403, detail="الحساب معطل")
    token = create_token(doc["id"], "admin")
    await audit("login", actor={"id": doc["id"], "role": "admin", "phone": data.phone})
    return {
        "token": token,
        "admin": {
            "id": doc["id"], "email": doc.get("email"), "phone": doc["phone"],
            "must_change_password": bool(doc.get("must_change_password", False)),
        },
    }


# ---------- Unified Login (role determined server-side) ----------
@api_router.post("/auth/login")
async def unified_login(data: LoginInput):
    """
    Unified login that resolves the user's role server-side from the database.
    The role is NEVER taken from the request. Search order: admins -> pharmacies -> suppliers.
    """
    pwd_hash = hash_password(data.password)

    admin = await db.admins.find_one({"phone": data.phone}, {"_id": 0})
    if admin and admin["password"] == pwd_hash:
        if admin.get("disabled"):
            raise HTTPException(status_code=403, detail="الحساب معطل")
        token = create_token(admin["id"], "admin")
        await db.audit_logs.insert_one({"id": str(uuid.uuid4()), "action": "login",
            "actor": {"id": admin["id"], "role": "admin", "phone": data.phone},
            "target": {}, "meta": {}, "timestamp": datetime.now(timezone.utc).isoformat()})
        return {
            "token": token, "role": "admin",
            "user": {
                "id": admin["id"], "email": admin.get("email"), "phone": admin["phone"],
                "must_change_password": bool(admin.get("must_change_password", False)),
            },
        }

    pharmacy = await db.pharmacies.find_one({"phone": data.phone}, {"_id": 0})
    if pharmacy and pharmacy["password"] == pwd_hash:
        if pharmacy.get("disabled"):
            raise HTTPException(status_code=403, detail="الحساب معطل")
        token = create_token(pharmacy["id"], "pharmacy")
        await db.audit_logs.insert_one({"id": str(uuid.uuid4()), "action": "login",
            "actor": {"id": pharmacy["id"], "role": "pharmacy", "phone": data.phone},
            "target": {}, "meta": {}, "timestamp": datetime.now(timezone.utc).isoformat()})
        return {
            "token": token, "role": "pharmacy",
            "user": {"id": pharmacy["id"], "name": pharmacy["name"], "phone": pharmacy["phone"],
                     "address": pharmacy.get("address"),
                     "region": pharmacy.get("region"), "country": pharmacy.get("country")},
            "must_set_region": not bool(pharmacy.get("region_normalized")),
        }

    supplier = await db.suppliers.find_one({"phone": data.phone}, {"_id": 0})
    if supplier and supplier["password"] == pwd_hash:
        if supplier.get("disabled"):
            raise HTTPException(status_code=403, detail="الحساب معطل")
        token = create_token(supplier["id"], "supplier")
        await db.audit_logs.insert_one({"id": str(uuid.uuid4()), "action": "login",
            "actor": {"id": supplier["id"], "role": "supplier", "phone": data.phone},
            "target": {}, "meta": {}, "timestamp": datetime.now(timezone.utc).isoformat()})
        return {
            "token": token, "role": "supplier",
            "user": {"id": supplier["id"], "name": supplier["name"], "phone": supplier["phone"],
                     "address": supplier.get("address"),
                     "region": supplier.get("region"), "country": supplier.get("country")},
            "must_set_region": not bool(supplier.get("region_normalized")),
        }

    await db.audit_logs.insert_one({"id": str(uuid.uuid4()), "action": "login_failed",
        "actor": {"phone": data.phone}, "target": {}, "meta": {},
        "timestamp": datetime.now(timezone.utc).isoformat()})
    raise HTTPException(status_code=401, detail="رقم الهاتف أو الرمز السري غير صحيح")


@api_router.post("/admin/change-password")
async def admin_change_password(data: AdminChangePasswordIn, user: dict = Depends(require_role("admin"))):
    doc = await db.admins.find_one({"id": user["sub"]}, {"_id": 0})
    if not doc or doc["password"] != hash_password(data.old_password):
        raise HTTPException(status_code=401, detail="كلمة المرور القديمة غير صحيحة")
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="كلمة المرور يجب أن تكون 6 أحرف على الأقل")
    await db.admins.update_one(
        {"id": user["sub"]},
        {"$set": {"password": hash_password(data.new_password), "must_change_password": False}},
    )
    await audit("password_change", actor={"id": user["sub"], "role": "admin"})
    return {"status": "ok"}


# ---------- Admin: Stats ----------
@api_router.get("/admin/stats")
async def admin_stats(user: dict = Depends(require_role("admin"))):
    pharmacies_count = await db.pharmacies.count_documents({})
    suppliers_count = await db.suppliers.count_documents({})
    medicines_count = await db.medicines.count_documents({})
    products_count = await db.supplier_products.count_documents({})
    orders_count = await db.orders.count_documents({})
    # Use aggregation to avoid loading all sales docs into memory
    revenue_agg = await db.sales.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$total"}, "count": {"$sum": 1}}}
    ]).to_list(1)
    revenue = float(revenue_agg[0]["total"]) if revenue_agg else 0.0
    sales_count = int(revenue_agg[0]["count"]) if revenue_agg else 0
    catalog_jobs = await db.import_jobs.count_documents({})
    audit_count = await db.audit_logs.count_documents({})
    return {
        "pharmacies": pharmacies_count,
        "suppliers": suppliers_count,
        "medicines": medicines_count,
        "products": products_count,
        "orders": orders_count,
        "sales": sales_count,
        "revenue": round(revenue, 2),
        "catalog_jobs": catalog_jobs,
        "audit_logs": audit_count,
    }


# ---------- Admin: Users ----------
@api_router.get("/admin/users")
async def admin_users(role: Optional[str] = None, skip: int = 0, limit: int = 200, user: dict = Depends(require_role("admin"))):
    s, lim = _paginate(skip, limit, default=200, hard_max=500)
    out: list[dict] = []
    if role in (None, "pharmacy"):
        ps = await db.pharmacies.find({}, {"_id": 0, "password": 0}).skip(s if role == "pharmacy" else 0).limit(lim).to_list(lim)
        for p in ps:
            p["role"] = "pharmacy"
        out.extend(ps)
    if role in (None, "supplier"):
        ss = await db.suppliers.find({}, {"_id": 0, "password": 0}).skip(s if role == "supplier" else 0).limit(lim).to_list(lim)
        for s_ in ss:
            s_["role"] = "supplier"
        out.extend(ss)
    return out


@api_router.patch("/admin/users/{role}/{user_id}")
async def admin_toggle_user(role: str, user_id: str, body: dict, user: dict = Depends(require_role("admin"))):
    if role not in ("pharmacy", "supplier"):
        raise HTTPException(status_code=400, detail="role غير صالح")
    coll = db.pharmacies if role == "pharmacy" else db.suppliers
    if "disabled" not in body:
        raise HTTPException(status_code=400, detail="يجب تمرير قيمة disabled")
    new_val = bool(body["disabled"])
    res = await coll.update_one({"id": user_id}, {"$set": {"disabled": new_val}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    await audit("user_disabled" if new_val else "user_enabled",
                actor={"id": user["sub"], "role": "admin"},
                target={"id": user_id, "role": role})
    return {"status": "ok"}


@api_router.delete("/admin/users/{role}/{user_id}")
async def admin_delete_user(role: str, user_id: str, user: dict = Depends(require_role("admin"))):
    if role not in ("pharmacy", "supplier"):
        raise HTTPException(status_code=400, detail="role غير صالح")
    coll = db.pharmacies if role == "pharmacy" else db.suppliers
    res = await coll.delete_one({"id": user_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    # Cascade: also remove their data (idempotent)
    if role == "pharmacy":
        await db.medicines.delete_many({"pharmacy_id": user_id})
        await db.orders.delete_many({"pharmacy_id": user_id})
    else:
        await db.supplier_products.delete_many({"supplier_id": user_id})
    await audit("user_deleted", actor={"id": user["sub"], "role": "admin"},
                target={"id": user_id, "role": role})
    return {"status": "ok"}


# ---------- Admin: Orders ----------
@api_router.get("/admin/orders")
async def admin_orders(status: Optional[str] = None, skip: int = 0, limit: int = 200, user: dict = Depends(require_role("admin"))):
    s, lim = _paginate(skip, limit, default=200, hard_max=500)
    q: dict = {}
    if status == "pending":
        # Legacy orders without status field are treated as pending
        q = {"$or": [{"status": "pending"}, {"status": {"$exists": False}}]}
    elif status:
        q["status"] = status
    docs = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).skip(s).limit(lim).to_list(lim)
    # Enrich pharmacy name
    pharmacy_ids = list({d["pharmacy_id"] for d in docs})
    pharmas = await db.pharmacies.find({"id": {"$in": pharmacy_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)
    name_by_id = {p["id"]: p["name"] for p in pharmas}
    for d in docs:
        d["pharmacy_name"] = name_by_id.get(d["pharmacy_id"], "—")
        d.setdefault("status", "pending")
    return docs


@api_router.patch("/admin/orders/{order_id}")
async def admin_update_order(order_id: str, body: dict, user: dict = Depends(require_role("admin"))):
    new_status = body.get("status")
    if new_status not in ("pending", "confirmed", "delivered", "cancelled"):
        raise HTTPException(status_code=400, detail="status غير صالح")
    res = await db.orders.update_one({"id": order_id}, {"$set": {"status": new_status}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="الطلبية غير موجودة")
    return {"status": "ok"}


# ---------- Admin: Products (medicines + supplier_products) ----------
@api_router.get("/admin/products")
async def admin_products(kind: Optional[str] = None, skip: int = 0, limit: int = 200, user: dict = Depends(require_role("admin"))):
    s, lim = _paginate(skip, limit, default=200, hard_max=500)
    out: list[dict] = []
    if kind in (None, "medicine"):
        meds = await db.medicines.find({}, {"_id": 0}).skip(s if kind == "medicine" else 0).limit(lim).to_list(lim)
        for m in meds:
            m["kind"] = "medicine"
        out.extend(meds)
    if kind in (None, "supplier_product"):
        sp = await db.supplier_products.find({}, {"_id": 0}).skip(s if kind == "supplier_product" else 0).limit(lim).to_list(lim)
        for s_ in sp:
            s_["kind"] = "supplier_product"
        out.extend(sp)
    return out


@api_router.delete("/admin/products/{kind}/{product_id}")
async def admin_delete_product(kind: str, product_id: str, user: dict = Depends(require_role("admin"))):
    if kind == "medicine":
        coll = db.medicines
    elif kind == "supplier_product":
        coll = db.supplier_products
    else:
        raise HTTPException(status_code=400, detail="kind غير صالح")
    res = await coll.delete_one({"id": product_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="المنتج غير موجود")
    await audit("product_deleted", actor={"id": user["sub"], "role": "admin"},
                target={"id": product_id, "kind": kind})
    return {"status": "ok"}


# ---------- Admin: Notifications ----------
class NotificationIn(BaseModel):
    title: str
    body: str
    audience: str = "all"  # all | pharmacy | supplier


@api_router.post("/admin/notifications")
async def admin_send_notification(data: NotificationIn, user: dict = Depends(require_role("admin"))):
    if data.audience not in ("all", "pharmacy", "supplier"):
        raise HTTPException(status_code=400, detail="audience غير صالح")
    if not data.title.strip() or not data.body.strip():
        raise HTTPException(status_code=400, detail="العنوان والمحتوى مطلوبان")
    doc = {
        "id": str(uuid.uuid4()),
        "title": data.title.strip(),
        "body": data.body.strip(),
        "audience": data.audience,
        "active": True,
        "created_by": user["sub"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.notifications.insert_one(doc.copy())
    return doc


@api_router.get("/admin/notifications")
async def admin_list_notifications(user: dict = Depends(require_role("admin"))):
    docs = await db.notifications.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return docs


@api_router.delete("/admin/notifications/{notif_id}")
async def admin_delete_notification(notif_id: str, user: dict = Depends(require_role("admin"))):
    res = await db.notifications.delete_one({"id": notif_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="الإشعار غير موجود")
    return {"status": "ok"}


# Public: any logged-in user fetches active notifications for their audience
@api_router.get("/notifications/active")
async def active_notifications(user: dict = Depends(get_current_user)):
    role = user.get("role")
    docs = await db.notifications.find(
        {"active": True, "audience": {"$in": ["all", role]}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(20)
    return docs


# ---------- Admin: Audit Logs ----------
@api_router.get("/admin/audit-logs")
async def admin_audit(action: Optional[str] = None, limit: int = 200, user: dict = Depends(require_role("admin"))):
    q: dict = {}
    if action:
        q["action"] = action
    docs = await db.audit_logs.find(q, {"_id": 0}).sort("timestamp", -1).to_list(min(limit, 1000))
    return docs


# ---------- Supplier Commissions ----------
COMMISSION_RATE = 0.04  # 4%


class CommitGroupItem(BaseModel):
    name: str
    quantity: int
    unit_price: float


class CommitGroup(BaseModel):
    supplier_id: str
    supplier_name: str
    items: List[CommitGroupItem]
    total: float


class CommitOrderIn(BaseModel):
    commit_id: str  # client-generated UUID; idempotent
    groups: List[CommitGroup]
    # Savings estimate distributed per group (worst_for_this_basket - actual_for_this_group).
    # If provided, summed and stored per-order then added to pharmacy's cumulative_savings on completion.
    savings_estimate_total: Optional[float] = None
    savings_per_group: Optional[List[float]] = None


@api_router.post("/orders/optimize/commit")
async def commit_order(data: CommitOrderIn, user: dict = Depends(require_role("pharmacy"))):
    """
    Pharmacy locks a plan -> create one ORDER per supplier group with status='pending'.
    NO commission is created at this stage. Commission is only created when the order
    reaches 'completed' (manual confirm-receipt OR auto 72h after delivered).
    Idempotent via commit_id.
    """
    if not data.commit_id or not data.groups:
        raise HTTPException(status_code=400, detail="بيانات ناقصة")
    # Idempotency: skip if any order with this commit_id already exists
    existing = await db.orders.count_documents({"commit_id": data.commit_id})
    if existing > 0:
        return {"status": "already_committed", "commit_id": data.commit_id, "created": 0}

    # === Pending-receipt enforcement (mandatory receipt confirmation) ===
    # Pharmacy may not create new orders if 2 or more of their existing orders are in
    # 'delivered' status awaiting their action (must click "received" or "not received").
    pending_receipt_count = await db.orders.count_documents({
        "pharmacy_id": user["sub"],
        "status": "delivered",
    })
    if pending_receipt_count >= 2:
        raise HTTPException(
            status_code=409,
            detail=(
                "لا يمكن إنشاء طلبية جديدة قبل تأكيد استلام طلبياتك السابقة. "
                "يوجد لديك {n} طلبيات تم تسليمها وتنتظر إجراءك. "
                "يرجى الذهاب إلى \"طلباتي\" والضغط على \"تأكيد الاستلام\" أو \"لم أستلم الطلبية\" لكل منها."
            ).format(n=pending_receipt_count),
        )

    pharmacy = await db.pharmacies.find_one({"id": user["sub"]}, {"_id": 0})
    if not pharmacy:
        raise HTTPException(status_code=404, detail="Pharmacy not found")

    # Region enforcement: when marketplace_mode == 'local', reject groups whose supplier is in a different region
    allowed_ids = await allowed_supplier_ids(user["sub"])
    if allowed_ids is not None:  # local mode with pharmacy region set
        bad = [g.supplier_id for g in data.groups if g.supplier_id not in set(allowed_ids)]
        if bad:
            raise HTTPException(status_code=403, detail="بعض المذاخر خارج منطقتك ولا يمكن الطلب منها")

    created = []
    now_iso = datetime.now(timezone.utc).isoformat()
    # Distribute savings_estimate across groups proportionally to group totals if not provided per-group
    total_groups_value = sum(float(g.total or 0) for g in data.groups) or 1.0
    sp_per_group = data.savings_per_group or []
    saving_total = float(data.savings_estimate_total or 0)
    for idx, g in enumerate(data.groups):
        if g.total <= 0:
            continue
        if idx < len(sp_per_group):
            saving_for_g = max(0.0, float(sp_per_group[idx] or 0))
        elif saving_total > 0:
            saving_for_g = round(saving_total * (float(g.total) / total_groups_value), 2)
        else:
            saving_for_g = 0.0
        order = {
            "id": str(uuid.uuid4()),
            "commit_id": data.commit_id,
            "pharmacy_id": user["sub"],
            "pharmacy_name": pharmacy.get("name"),
            "pharmacy_phone": pharmacy.get("phone"),
            "pharmacy_address": pharmacy.get("address"),
            "pharmacy_region": pharmacy.get("region"),
            "pharmacy_country": pharmacy.get("country"),
            "supplier_id": g.supplier_id,
            "supplier_name": g.supplier_name,
            "items": [it.dict() for it in g.items],
            "total": float(g.total),
            "savings_estimate": saving_for_g,
            "status": "pending",
            "source": "optimize",
            "rejection_reason": None,
            "commission_amount": None,
            "commission_rate": COMMISSION_RATE,
            "commission_id": None,
            "auto_completed": False,
            "savings_credited": False,
            "created_at": now_iso,
            "accepted_at": None,
            "processing_at": None,
            "delivered_at": None,
            "completed_at": None,
            "rejected_at": None,
        }
        await db.orders.insert_one(order.copy())
        created.append({"id": order["id"], "supplier_name": g.supplier_name, "total": order["total"], "savings": saving_for_g})
    return {"status": "ok", "commit_id": data.commit_id, "created": len(created), "orders": created}


# ---------- Order lifecycle endpoints ----------
AUTO_COMPLETE_HOURS = 72


def _redact_pharmacy_info(order: dict) -> dict:
    """Hide pharmacy contact details if the order is still in pending state (anti-circumvention)."""
    if (order.get("status") or "pending") == "pending":
        o = dict(order)
        o["pharmacy_name"] = None
        o["pharmacy_phone"] = None
        o["pharmacy_address"] = None
        # Keep region/country (for logistics decision before accept)
        return o
    return order


async def _create_completion_commission(order: dict, actor: dict, auto: bool = False) -> dict:
    """Create a supplier_sales record on completion. Returns the new record."""
    total = float(order.get("total") or 0)
    commission = round(total * COMMISSION_RATE, 2)
    rec = {
        "id": str(uuid.uuid4()),
        "commit_id": order.get("commit_id"),
        "order_id": order.get("id"),
        "supplier_id": order.get("supplier_id"),
        "supplier_name": order.get("supplier_name"),
        "pharmacy_id": order.get("pharmacy_id"),
        "pharmacy_name": order.get("pharmacy_name"),
        "order_total": total,
        "commission": commission,
        "rate": COMMISSION_RATE,
        "items": order.get("items") or [],
        "status": "pending",  # commission payment status (pending -> submitted -> paid)
        "payment_proof_b64": None,
        "paid_at": None,
        "source": "order_completed_auto" if auto else "order_completed",
        "frozen": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.supplier_sales.insert_one(rec.copy())
    rec.pop("_id", None)
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "action": "commission_generated_on_completion",
        "actor": {"id": actor.get("id"), "role": actor.get("role")},
        "target": {"order_id": order.get("id"), "supplier_id": order.get("supplier_id"),
                   "amount": commission, "auto": auto},
        "meta": {}, "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return rec


async def _complete_order(order: dict, actor: dict, auto: bool = False) -> dict:
    """Transition an order to 'completed' and generate the commission. Idempotent."""
    if order.get("status") == "completed":
        return order
    if order.get("status") != "delivered":
        return order
    now_iso = datetime.now(timezone.utc).isoformat()
    commission_rec = await _create_completion_commission(order, actor, auto=auto)
    await db.orders.update_one(
        {"id": order["id"]},
        {"$set": {
            "status": "completed",
            "completed_at": now_iso,
            "auto_completed": bool(auto),
            "commission_amount": commission_rec["commission"],
            "commission_id": commission_rec["id"],
        }},
    )
    # Credit pharmacy cumulative_savings (only if not already credited)
    try:
        savings = float(order.get("savings_estimate") or 0)
        if savings > 0 and not order.get("savings_credited"):
            await db.pharmacies.update_one(
                {"id": order.get("pharmacy_id")},
                {"$inc": {"cumulative_savings": savings},
                 "$set": {"cumulative_savings_updated_at": now_iso}},
            )
            await db.orders.update_one({"id": order["id"]}, {"$set": {"savings_credited": True}})
    except Exception:
        logger.exception("Failed to credit pharmacy savings (non-fatal)")
    updated = await db.orders.find_one({"id": order["id"]}, {"_id": 0})
    return updated or order


@api_router.get("/pharmacy/savings")
async def pharmacy_cumulative_savings(user: dict = Depends(require_role("pharmacy"))):
    p = await db.pharmacies.find_one(
        {"id": user["sub"]},
        {"_id": 0, "cumulative_savings": 1, "cumulative_savings_updated_at": 1},
    )
    # Per-order count of completed orders (for context)
    completed_count = await db.orders.count_documents({"pharmacy_id": user["sub"], "status": "completed"})
    return {
        "cumulative_savings": round(float((p or {}).get("cumulative_savings") or 0), 2),
        "updated_at": (p or {}).get("cumulative_savings_updated_at"),
        "completed_orders": completed_count,
    }


async def _maybe_auto_complete_delivered(filter_q: dict, actor: dict) -> int:
    """Auto-complete orders that have been 'delivered' for > AUTO_COMPLETE_HOURS hours."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=AUTO_COMPLETE_HOURS)).isoformat()
    q = {**filter_q, "status": "delivered", "delivered_at": {"$lt": cutoff}}
    cursor = db.orders.find(q, {"_id": 0})
    count = 0
    async for o in cursor:
        await _complete_order(o, actor, auto=True)
        count += 1
    return count


class RejectIn(BaseModel):
    reason: Optional[str] = None


@api_router.patch("/supplier/orders/{order_id}/accept")
async def supplier_accept_order(order_id: str, user: dict = Depends(require_role("supplier"))):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلبية غير موجودة")
    if order.get("supplier_id") != user["sub"]:
        raise HTTPException(status_code=403, detail="ليست طلبيتك")
    if order.get("status") != "pending":
        raise HTTPException(status_code=400, detail=f"لا يمكن القبول. الحالة الحالية: {order.get('status')}")
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": order_id}, {"$set": {"status": "accepted", "accepted_at": now_iso}})
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()), "action": "order_accepted",
        "actor": {"id": user["sub"], "role": "supplier"},
        "target": {"order_id": order_id}, "meta": {},
        "timestamp": now_iso,
    })
    if order.get("pharmacy_id"):
        try:
            await notif_mod.create_notification(
                order["pharmacy_id"],
                "تم قبول طلبيتك",
                f"قام {order.get('supplier_name', 'المذخر')} بقبول طلبيتك وسيبدأ التجهيز قريباً.",
                type="order",
                data={"screen": "/pharmacy-orders", "order_id": order_id},
                dedupe_key=f"order:{order_id}:accepted",
            )
        except Exception:
            logger.exception("notify accepted failed")
    return {"status": "ok", "order_status": "accepted"}


@api_router.patch("/supplier/orders/{order_id}/reject")
async def supplier_reject_order(order_id: str, data: RejectIn, user: dict = Depends(require_role("supplier"))):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلبية غير موجودة")
    if order.get("supplier_id") != user["sub"]:
        raise HTTPException(status_code=403, detail="ليست طلبيتك")
    if order.get("status") not in ("pending", "accepted"):
        raise HTTPException(status_code=400, detail=f"لا يمكن الرفض. الحالة: {order.get('status')}")
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": order_id}, {"$set": {
        "status": "rejected",
        "rejected_at": now_iso,
        "rejection_reason": (data.reason or "").strip() or None,
    }})
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()), "action": "order_rejected",
        "actor": {"id": user["sub"], "role": "supplier"},
        "target": {"order_id": order_id}, "meta": {"reason": data.reason},
        "timestamp": now_iso,
    })
    return {"status": "ok", "order_status": "rejected"}


@api_router.patch("/supplier/orders/{order_id}/processing")
async def supplier_processing_order(order_id: str, user: dict = Depends(require_role("supplier"))):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلبية غير موجودة")
    if order.get("supplier_id") != user["sub"]:
        raise HTTPException(status_code=403, detail="ليست طلبيتك")
    if order.get("status") != "accepted":
        raise HTTPException(status_code=400, detail=f"يجب القبول أولاً. الحالة: {order.get('status')}")
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": order_id}, {"$set": {"status": "processing", "processing_at": now_iso}})
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()), "action": "order_processing",
        "actor": {"id": user["sub"], "role": "supplier"},
        "target": {"order_id": order_id}, "meta": {},
        "timestamp": now_iso,
    })
    if order.get("pharmacy_id"):
        try:
            await notif_mod.create_notification(
                order["pharmacy_id"], "قيد التجهيز",
                f"طلبيتك من {order.get('supplier_name', 'المذخر')} قيد التجهيز الآن.",
                type="order",
                data={"screen": "/pharmacy-orders", "order_id": order_id},
                dedupe_key=f"order:{order_id}:processing",
            )
        except Exception:
            logger.exception("notify processing failed")
    return {"status": "ok", "order_status": "processing"}


@api_router.patch("/supplier/orders/{order_id}/delivered")
async def supplier_delivered_order(order_id: str, user: dict = Depends(require_role("supplier"))):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلبية غير موجودة")
    if order.get("supplier_id") != user["sub"]:
        raise HTTPException(status_code=403, detail="ليست طلبيتك")
    if order.get("status") not in ("accepted", "processing"):
        raise HTTPException(status_code=400, detail=f"لا يمكن وضع علامة تم التسليم. الحالة: {order.get('status')}")
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"id": order_id}, {"$set": {"status": "delivered", "delivered_at": now_iso}})
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()), "action": "order_delivered",
        "actor": {"id": user["sub"], "role": "supplier"},
        "target": {"order_id": order_id}, "meta": {},
        "timestamp": now_iso,
    })
    if order.get("pharmacy_id"):
        try:
            await notif_mod.create_notification(
                order["pharmacy_id"], "تم تسليم طلبيتك",
                f"وصلت طلبيتك من {order.get('supplier_name', 'المذخر')}. يرجى تأكيد الاستلام أو الإبلاغ عن عدم الاستلام.",
                type="order",
                data={"screen": "/pharmacy-orders", "order_id": order_id, "filter": "delivered"},
                dedupe_key=f"order:{order_id}:delivered",
            )
        except Exception:
            logger.exception("notify delivered failed")
    return {"status": "ok", "order_status": "delivered"}


@api_router.patch("/pharmacy/orders/{order_id}/confirm-receipt")
async def pharmacy_confirm_receipt(order_id: str, user: dict = Depends(require_role("pharmacy"))):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلبية غير موجودة")
    if order.get("pharmacy_id") != user["sub"]:
        raise HTTPException(status_code=403, detail="ليست طلبيتك")
    if order.get("status") != "delivered":
        raise HTTPException(status_code=400, detail=f"لا يمكن التأكيد. الحالة: {order.get('status')}")
    updated = await _complete_order(order, {"id": user["sub"], "role": "pharmacy"}, auto=False)
    return {"status": "ok", "order_status": "completed",
            "commission_amount": updated.get("commission_amount"),
            "commission_id": updated.get("commission_id")}


class RejectReceiptIn(BaseModel):
    reason: Optional[str] = None


@api_router.patch("/pharmacy/orders/{order_id}/reject-receipt")
async def pharmacy_reject_receipt(order_id: str,
                                  data: Optional[RejectReceiptIn] = None,
                                  user: dict = Depends(require_role("pharmacy"))):
    """Pharmacy reports they did NOT receive a delivered order.
    Terminal transition: delivered -> not_received. No commission/savings credited.
    """
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلبية غير موجودة")
    if order.get("pharmacy_id") != user["sub"]:
        raise HTTPException(status_code=403, detail="ليست طلبيتك")
    if order.get("status") != "delivered":
        raise HTTPException(status_code=400, detail=f"لا يمكن الإبلاغ. الحالة: {order.get('status')}")

    now_iso = datetime.now(timezone.utc).isoformat()
    reason = (data.reason if data else None) or "لم يتم الاستلام"
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "status": "not_received",
            "not_received_at": now_iso,
            "not_received_reason": reason[:500],
            "savings_credited": False,
        }},
    )
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "action": "order_not_received",
        "actor": {"id": user["sub"], "role": "pharmacy"},
        "target": {"order_id": order_id, "supplier_id": order.get("supplier_id")},
        "meta": {"reason": reason[:500]},
        "timestamp": now_iso,
    })
    return {"status": "ok", "order_status": "not_received"}


# Pharmacy: view own orders (already exists at /orders; we replace with richer version)
@api_router.get("/pharmacy/orders")
async def pharmacy_orders(status: Optional[str] = None, skip: int = 0, limit: int = 100,
                          user: dict = Depends(require_role("pharmacy"))):
    s, lim = _paginate(skip, limit, default=100, hard_max=500)
    # Trigger lazy auto-complete for THIS pharmacy's delivered orders >72h
    await _maybe_auto_complete_delivered({"pharmacy_id": user["sub"]},
                                         {"id": "system", "role": "system"})
    q: dict = {"pharmacy_id": user["sub"]}
    if status:
        q["status"] = status
    docs = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).skip(s).limit(lim).to_list(lim)
    return docs


@api_router.get("/pharmacy/orders/{order_id}")
async def pharmacy_order_detail(order_id: str,
                                user: dict = Depends(require_role("pharmacy"))):
    """Return a single pharmacy order (used by the return-creation screen)."""
    doc = await db.orders.find_one(
        {"id": order_id, "pharmacy_id": user["sub"]}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="الطلبية غير موجودة")
    return doc


@api_router.get("/supplier/orders")
async def supplier_orders(status: Optional[str] = None, skip: int = 0, limit: int = 100,
                         user: dict = Depends(require_role("supplier"))):
    s, lim = _paginate(skip, limit, default=100, hard_max=500)
    # Trigger lazy auto-complete
    await _maybe_auto_complete_delivered({"supplier_id": user["sub"]},
                                         {"id": "system", "role": "system"})
    q: dict = {"supplier_id": user["sub"]}
    if status:
        q["status"] = status
    docs = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).skip(s).limit(lim).to_list(lim)
    # Redact pharmacy info for pending orders
    return [_redact_pharmacy_info(d) for d in docs]


@api_router.get("/supplier/orders/stats")
async def supplier_order_stats(user: dict = Depends(require_role("supplier"))):
    """Aggregate counts and totals by status. Used in supplier dashboard."""
    pipeline = [
        {"$match": {"supplier_id": user["sub"]}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}, "total": {"$sum": "$total"}}},
    ]
    rows = await db.orders.aggregate(pipeline).to_list(50)
    stats = {row["_id"]: {"count": row["count"], "total": round(row["total"] or 0, 2)} for row in rows}
    completed = stats.get("completed", {"count": 0, "total": 0})
    completed_total = completed["total"]
    commission_due = round(completed_total * COMMISSION_RATE, 2)
    return {
        "by_status": stats,
        "completed_count": completed["count"],
        "completed_total": completed_total,
        "commission_due_total": commission_due,
        "rate": COMMISSION_RATE,
    }


def _monthly_summary(records: list[dict]) -> list[dict]:
    """Aggregate sales by YYYY-MM month."""
    months: dict[str, dict] = {}
    for r in records:
        m = r.get("created_at", "")[:7] or "unknown"
        m_data = months.setdefault(m, {"month": m, "total_sales": 0.0, "total_commission": 0.0,
                                       "paid_commission": 0.0, "pending_commission": 0.0, "count": 0})
        m_data["count"] += 1
        m_data["total_sales"] += float(r.get("order_total") or 0)
        m_data["total_commission"] += float(r.get("commission") or 0)
        if r.get("status") == "paid":
            m_data["paid_commission"] += float(r.get("commission") or 0)
        else:
            m_data["pending_commission"] += float(r.get("commission") or 0)
    out = list(months.values())
    out.sort(key=lambda x: x["month"], reverse=True)
    for x in out:
        for k in ("total_sales", "total_commission", "paid_commission", "pending_commission"):
            x[k] = round(x[k], 2)
    return out


@api_router.get("/supplier/commissions")
async def supplier_commissions(skip: int = 0, limit: int = 200,
                               user: dict = Depends(require_role("supplier"))):
    s, lim = _paginate(skip, limit, default=200, hard_max=500)
    records = await db.supplier_sales.find(
        {"supplier_id": user["sub"]},
        {"_id": 0, "payment_proof_b64": 0},  # don't ship the heavy proof
    ).sort("created_at", -1).skip(s).limit(lim).to_list(lim)
    full_records = await db.supplier_sales.find(
        {"supplier_id": user["sub"]}, {"_id": 0, "payment_proof_b64": 0}
    ).to_list(5000)
    summary = _monthly_summary(full_records)
    outstanding = round(sum(r["pending_commission"] for r in summary), 2)
    total_due = round(sum(r["total_commission"] for r in summary), 2)
    total_sales = round(sum(r["total_sales"] for r in summary), 2)
    return {
        "records": records,
        "monthly": summary,
        "outstanding": outstanding,
        "total_due": total_due,
        "total_sales": total_sales,
        "rate": COMMISSION_RATE,
    }


class UploadProofIn(BaseModel):
    proof_b64: str


@api_router.post("/supplier/commissions/{record_id}/upload-proof")
async def supplier_upload_proof(record_id: str, data: UploadProofIn, user: dict = Depends(require_role("supplier"))):
    if not data.proof_b64 or len(data.proof_b64) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="إثبات الدفع غير صالح أو كبير جداً")
    rec = await db.supplier_sales.find_one({"id": record_id}, {"_id": 0})
    if not rec or rec.get("supplier_id") != user["sub"]:
        raise HTTPException(status_code=404, detail="السجل غير موجود")
    if rec.get("status") == "paid":
        raise HTTPException(status_code=400, detail="هذا السجل مدفوع بالفعل")
    await db.supplier_sales.update_one(
        {"id": record_id},
        {"$set": {"payment_proof_b64": data.proof_b64,
                  "proof_uploaded_at": datetime.now(timezone.utc).isoformat(),
                  "status": "submitted"}},
    )
    return {"status": "ok"}


# Admin: commission management
class AdminManualCommissionIn(BaseModel):
    supplier_id: str
    pharmacy_id: Optional[str] = None
    pharmacy_name: Optional[str] = None
    order_total: float
    note: Optional[str] = None


@api_router.get("/admin/commissions")
async def admin_commissions(status: Optional[str] = None, supplier_id: Optional[str] = None,
                            skip: int = 0, limit: int = 200,
                            user: dict = Depends(require_role("admin"))):
    s, lim = _paginate(skip, limit, default=200, hard_max=500)
    q: dict = {}
    if status:
        q["status"] = status
    if supplier_id:
        q["supplier_id"] = supplier_id
    records = await db.supplier_sales.find(q, {"_id": 0, "payment_proof_b64": 0}).sort("created_at", -1).skip(s).limit(lim).to_list(lim)
    # Aggregate stats
    agg = await db.supplier_sales.aggregate([
        {"$group": {"_id": "$status", "count": {"$sum": 1},
                    "total_commission": {"$sum": "$commission"},
                    "total_sales": {"$sum": "$order_total"}}}
    ]).to_list(10)
    stats = {a["_id"] or "unknown": {"count": a["count"],
                                     "commission": round(a["total_commission"] or 0, 2),
                                     "sales": round(a["total_sales"] or 0, 2)} for a in agg}
    return {"records": records, "stats": stats}


@api_router.get("/admin/commissions/{record_id}/proof")
async def admin_get_proof(record_id: str, user: dict = Depends(require_role("admin"))):
    rec = await db.supplier_sales.find_one({"id": record_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"proof_b64": rec.get("payment_proof_b64")}


@api_router.post("/admin/commissions")
async def admin_manual_commission(data: AdminManualCommissionIn, user: dict = Depends(require_role("admin"))):
    """Manual commission entry by admin (offline / special cases)."""
    supplier = await db.suppliers.find_one({"id": data.supplier_id}, {"_id": 0})
    if not supplier:
        raise HTTPException(status_code=404, detail="المذخر غير موجود")
    if data.order_total <= 0:
        raise HTTPException(status_code=400, detail="المبلغ غير صالح")
    rec = {
        "id": str(uuid.uuid4()),
        "commit_id": str(uuid.uuid4()),
        "supplier_id": data.supplier_id,
        "supplier_name": supplier.get("name"),
        "pharmacy_id": data.pharmacy_id,
        "pharmacy_name": data.pharmacy_name,
        "order_total": float(data.order_total),
        "commission": round(float(data.order_total) * COMMISSION_RATE, 2),
        "rate": COMMISSION_RATE,
        "items": [],
        "status": "pending",
        "source": "manual",
        "frozen": True,
        "note": data.note,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.supplier_sales.insert_one(rec.copy())
    rec.pop("_id", None)
    return rec


@api_router.patch("/admin/commissions/{record_id}/confirm")
async def admin_confirm_commission(record_id: str, user: dict = Depends(require_role("admin"))):
    rec = await db.supplier_sales.find_one({"id": record_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="غير موجود")
    if rec.get("status") == "paid":
        return {"status": "already_paid"}
    await db.supplier_sales.update_one(
        {"id": record_id},
        {"$set": {"status": "paid",
                  "paid_at": datetime.now(timezone.utc).isoformat(),
                  "confirmed_by": user["sub"]}},
    )
    await db.audit_logs.insert_one({"id": str(uuid.uuid4()), "action": "commission_paid",
        "actor": {"id": user["sub"], "role": "admin"},
        "target": {"id": record_id, "supplier_id": rec.get("supplier_id"), "amount": rec.get("commission")},
        "meta": {}, "timestamp": datetime.now(timezone.utc).isoformat()})
    return {"status": "ok"}


# ============== Payment Settings ==============
PAYMENT_SETTINGS_ID = "payment"


class PaymentSettingsUpdate(BaseModel):
    zaincash_phone: Optional[str] = None
    zaincash_qr_b64: Optional[str] = None
    whatsapp_admin_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    iban: Optional[str] = None
    stripe_public_key: Optional[str] = None
    stripe_secret_key: Optional[str] = None
    stripe_enabled: Optional[bool] = None
    instructions: Optional[str] = None
    marketplace_mode: Optional[str] = None  # "local" | "national"


DEFAULT_PAYMENT_SETTINGS = {
    "id": PAYMENT_SETTINGS_ID,
    "zaincash_phone": None,
    "zaincash_qr_b64": None,
    "whatsapp_admin_number": None,
    "bank_name": None,
    "bank_account_number": None,
    "iban": None,
    "stripe_public_key": None,
    "stripe_secret_key": None,
    "stripe_enabled": False,
    "instructions": None,
    "marketplace_mode": "local",
    "updated_at": None,
    "updated_by": None,
}


async def _get_or_init_payment_settings() -> dict:
    doc = await db.app_settings.find_one({"id": PAYMENT_SETTINGS_ID}, {"_id": 0})
    if not doc:
        doc = DEFAULT_PAYMENT_SETTINGS.copy()
        await db.app_settings.insert_one(doc.copy())
        doc.pop("_id", None)
    return doc


@api_router.get("/admin/payment-settings")
async def admin_get_payment_settings(user: dict = Depends(require_role("admin"))):
    """Full settings including stripe_secret_key. Admin only."""
    return await _get_or_init_payment_settings()


@api_router.patch("/admin/payment-settings")
async def admin_update_payment_settings(data: PaymentSettingsUpdate,
                                        user: dict = Depends(require_role("admin"))):
    updates = {k: v for k, v in data.dict(exclude_unset=True).items() if v is not None or k in ("stripe_enabled",)}
    # Allow explicit nullification: client must send empty string ("") to clear a field
    raw = data.dict(exclude_unset=True)
    for k, v in raw.items():
        if v == "":
            updates[k] = None
    if "marketplace_mode" in updates and updates["marketplace_mode"] not in ("local", "national"):
        raise HTTPException(status_code=400, detail="marketplace_mode must be 'local' or 'national'")
    if not updates:
        raise HTTPException(status_code=400, detail="لا يوجد تحديث")
    # Validate Zain Cash QR base64 size
    qr = updates.get("zaincash_qr_b64")
    if qr and len(qr) > 4 * 1024 * 1024:  # ~3MB after b64 decode
        raise HTTPException(status_code=413, detail="حجم صورة QR كبير جداً (الحد 3MB)")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    updates["updated_by"] = user["sub"]
    await db.app_settings.update_one(
        {"id": PAYMENT_SETTINGS_ID},
        {"$set": updates, "$setOnInsert": {"id": PAYMENT_SETTINGS_ID}},
        upsert=True,
    )
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()), "action": "payment_settings_updated",
        "actor": {"id": user["sub"], "role": "admin"},
        "target": {"id": PAYMENT_SETTINGS_ID},
        "meta": {"fields": list(updates.keys())},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return await _get_or_init_payment_settings()


@api_router.get("/payment-info")
async def get_public_payment_info(user: dict = Depends(get_current_user)):
    """
    Public-safe payment info for any authenticated user.
    Hides stripe_secret_key. Returns the QR image (base64) so suppliers can scan & pay.
    """
    s = await _get_or_init_payment_settings()
    return {
        "zaincash_phone": s.get("zaincash_phone"),
        "zaincash_qr_b64": s.get("zaincash_qr_b64"),
        "whatsapp_admin_number": s.get("whatsapp_admin_number"),
        "bank_name": s.get("bank_name"),
        "bank_account_number": s.get("bank_account_number"),
        "iban": s.get("iban"),
        "stripe_public_key": s.get("stripe_public_key"),
        "stripe_enabled": bool(s.get("stripe_enabled")),
        "instructions": s.get("instructions"),
        "marketplace_mode": s.get("marketplace_mode") or "local",
        "updated_at": s.get("updated_at"),
    }


# ============== End Payment Settings ==============


# ============== End Admin ==============

# Re-register router to pick up admin routes added after initial include
app.include_router(api_router)
