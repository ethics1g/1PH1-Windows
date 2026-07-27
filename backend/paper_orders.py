"""
Paper-order scanning + archiving (independent from marketplace orders).

Feature scope (per user's explicit brief — DO NOT touch inventory/purchase
systems, ONLY add):
  1. POST /api/orders/scan-image → Gemini 3 flash extracts line items from
     a photo of a paper invoice.
  2. POST /api/orders/paper → commits the reviewed items:
     * Every line goes through the EXISTING /medicines/buy-v2 logic path
       (via a direct `_batches.create_batch` call for the ORM lifting) —
       preserving FIFO, mirroring stock, refreshing expiry alerts, etc.
     * Original image + metadata are archived in `paper_orders`.
     * Outstanding balance (if any) creates a `supplier_ledger` entry so
       the existing "ديون الزبائن" screen's supplier tab picks it up.
  3. GET /api/orders/paper → list of scanned orders.
  4. GET /api/orders/paper/{id} → single order details.
  5. POST /api/orders/paper/{id}/pay → record a payment installment.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Populated by install_routes()
_db = None
router_paper_orders = APIRouter(prefix="/api", tags=["paper_orders"])


def init(db_instance) -> None:
    global _db
    _db = db_instance


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_expiry_safe(v: Optional[str]) -> Optional[str]:
    """Wrapper around server._parse_expiry that returns None on failure
    instead of raising — keeps scan flow tolerant to messy OCR."""
    if not v:
        return None
    try:
        import server as _s
        return _s._parse_expiry(v)
    except Exception:
        return None


EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# ---------- OCR prompts (two passes: strict + lenient fallback) ---------

EXTRACTION_PROMPT = """أنت مساعد خبير في قراءة فواتير الأدوية الصيدلانية (مطبوعة أو خط يد، عربية أو إنجليزية أو مختلطة).
مهمتك: استخراج كل الأصناف الظاهرة في الصورة، حتى لو كانت الصورة مضغوطة أو الخط صغيراً.

قواعد قراءة صارمة:
1. اقرأ كل صف بعناية. الأدوية غالباً في جدول من 4-6 أعمدة: (اسم الدواء، الشركة، الكمية، السعر، الإجمالي، أحياناً التشغيلة والصلاحية).
2. **لا ترفض** لأن الجودة منخفضة أو الخط صغير — خمّن أفضل قراءة ممكنة واستمر.
3. أعد الأسماء **بالضبط كما ظهرت** (عربية أو إنجليزية أو مختلطة). لا تُترجم.
4. **إذا كنت غير متأكد من رقم**: ضع 0 وواصل — لا تحذف الصف.
5. تجاهل الرؤوس والتذييلات (شعار، تاريخ، توقيع، هاتف، إجمالي عام في الأسفل).
6. إذا تكرر نفس الاسم بأرقام تشغيلة مختلفة، أعد صفاً منفصلاً لكل تشغيلة.

أرجع مصفوفة JSON فقط. ابدأ بـ [ وانتهِ بـ ]. لا شرح ولا Markdown.

لكل صف:
{
  "name": "اسم الدواء كاملاً كما ظهر (مطلوب — لا تتركه فارغاً)",
  "quantity": رقم صحيح (0 إذا غير واضح),
  "price": رقم عشري لسعر الوحدة (0 إذا غير واضح),
  "batch_number": "رقم التشغيلة" أو null,
  "expiry_date": "YYYY-MM" أو "YYYY-MM-DD" أو null
}

مثال على المخرجات المتوقعة (لا تنسخ القيم — استخدم الصورة):
[{"name":"Paracetamol 500mg","quantity":30,"price":250,"batch_number":"L2401","expiry_date":"2026-08"},
 {"name":"Amoxicillin 250mg","quantity":10,"price":1500,"batch_number":null,"expiry_date":null}]
"""

LENIENT_RETRY_PROMPT = """المحاولة الأولى فشلت. الصورة تحتوي على قائمة أدوية بالتأكيد.
انظر بعناية أكبر — قد تكون الخطوط صغيرة أو مائلة أو بخط اليد. لا تعيدها فارغة.

اقرأ كل سطر واحدة واحدة من أعلى الجدول إلى أسفله واستخرج أي شيء يشبه اسم دواء + رقم كمية + رقم سعر.
حتى لو استطعت قراءة الاسم فقط (بلا كمية أو سعر) → أعد الصف مع quantity=0 و price=0.

**ممنوع** إعادة مصفوفة فارغة إن كانت الصورة تحتوي على أي نص جدولي. حاول قراءة كل صف بأفضل تخمين لديك.

أرجع فقط: [{"name":"...","quantity":N,"price":N,"batch_number":null,"expiry_date":null}, ...]
لا شرح، ابدأ بـ [ وانتهِ بـ ].
"""

METADATA_PROMPT = """من نفس الصورة استخرج بيانات رأس الفاتورة/الطلبية إن وجدت:
- supplier_name: اسم المذخر/الشركة (نص أو null)
- invoice_number: رقم الفاتورة/الطلبية (نص أو null)
- invoice_date: تاريخ الفاتورة بصيغة YYYY-MM-DD (أو null)
- total: الإجمالي المكتوب (رقم أو 0)

أرجع كائن JSON واحد فقط."""


async def _call_gemini_json(image_b64: str, prompt: str, session_prefix: str, model: str = "gemini-3-flash-preview") -> str:
    """Low-level Gemini call — returns raw response text or empty on error.
    Errors are logged with FULL detail so silent failures never mask a real
    issue behind a generic 'الصورة غير واضحة' message to the user."""
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"{session_prefix}-{uuid.uuid4()}",
            system_message="أنت مساعد خبير في قراءة فواتير الأدوية بدقة عالية.",
        ).with_model("gemini", model)
        msg = UserMessage(text=prompt, file_contents=[ImageContent(image_base64=image_b64)])
        resp = await chat.send_message(msg)
        text = (resp or "").strip()
        # Log a preview for diagnostics without dumping the full base64
        logger.info("paper-order OCR (%s / %s) raw response preview: %s",
                    session_prefix, model, (text[:200] + '...') if len(text) > 200 else text)
        return text
    except Exception as ex:
        logger.exception("paper-order OCR failed (%s / %s): %s", session_prefix, model, ex)
        return ""


def _parse_items_json(text: str) -> List[Dict[str, Any]]:
    """Robust JSON-array extraction from a Gemini response."""
    if not text:
        return []
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    s = text.find("[")
    e = text.rfind("]")
    if s == -1 or e == -1:
        return []
    try:
        arr = json.loads(text[s: e + 1])
    except json.JSONDecodeError:
        # Try to recover by fixing trailing commas or single quotes
        cleaned = re.sub(r",\s*([\]\}])", r"\1", text[s: e + 1])
        try:
            arr = json.loads(cleaned)
        except Exception:
            return []
    if not isinstance(arr, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or "").strip()
        if not name:
            continue
        def _fnum(x):
            try: return float(x or 0)
            except Exception: return 0.0
        def _inum(x):
            try: return int(float(x or 0))
            except Exception: return 0
        out.append({
            "name": name,
            "quantity": _inum(it.get("quantity")),
            "purchase_price": _fnum(it.get("price")),
            "batch_number": (it.get("batch_number") or None) or None,
            "expiry_date": _parse_expiry_safe(it.get("expiry_date")),
        })
    return out


async def _gemini_extract_items(image_b64: str) -> List[Dict[str, Any]]:
    """Call Gemini 3 Flash on the invoice image and return parsed line items.
    Two-pass strategy: strict extraction, then a lenient retry if empty. This
    saved several real Iraqi handwritten invoices that Gemini refused on the
    first pass with a generic 'unclear image' response."""
    # Pass 1: strict prompt
    text = await _call_gemini_json(image_b64, EXTRACTION_PROMPT, "items-p1")
    items = _parse_items_json(text)
    if items:
        return items

    logger.warning("paper-order OCR: pass 1 returned 0 items — retrying with lenient prompt")

    # Pass 2: lenient retry — nudges the model to try harder before giving up
    text2 = await _call_gemini_json(image_b64, LENIENT_RETRY_PROMPT, "items-p2")
    items = _parse_items_json(text2)
    if items:
        logger.info("paper-order OCR: pass 2 recovered %d items", len(items))
        return items

    logger.warning("paper-order OCR: both passes returned 0 items")
    return []


async def _gemini_extract_metadata(image_b64: str) -> Dict[str, Any]:
    """Extract header metadata (supplier, invoice number, date, total)."""
    text = await _call_gemini_json(image_b64, METADATA_PROMPT, "meta")
    if not text:
        return {}
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    s = text.find("{")
    e = text.rfind("}")
    if s == -1 or e == -1:
        return {}
    try:
        obj = json.loads(text[s: e + 1])
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    return {
        "supplier_name": (obj.get("supplier_name") or None) or None,
        "invoice_number": (obj.get("invoice_number") or None) or None,
        "invoice_date":  _parse_expiry_safe(obj.get("invoice_date")),
        "total": float(obj.get("total") or 0),
    }


# =====================================================================
# ============================= MODELS  ==============================
# =====================================================================

class ScanImageIn(BaseModel):
    image_base64: str = Field(..., description="Raw base64 of the invoice image")


class PaperOrderItemIn(BaseModel):
    name: str
    quantity: int
    purchase_price: float
    selling_price: Optional[float] = None       # if user set one, else purchase_price*1.25
    batch_number: Optional[str] = None
    expiry_date: Optional[str] = None
    barcode: Optional[str] = None


class CommitPaperOrderIn(BaseModel):
    image_base64: str = Field(..., description="Original invoice image, archived as-is")
    supplier_name: Optional[str] = None
    supplier_id: Optional[str] = None           # linked in-app supplier (optional)
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    total: float = 0.0                           # if provided, override sum(item)
    amount_paid: float = 0.0
    items: List[PaperOrderItemIn]
    notes: Optional[str] = None


class PayPaperOrderIn(BaseModel):
    amount: float
    notes: Optional[str] = None


# =====================================================================
# ============================= ROUTES  ==============================
# =====================================================================

def install_routes(require_role):
    router_paper_orders.routes.clear()

    @router_paper_orders.post("/orders/scan-image")
    async def _scan_image(data: ScanImageIn,
                          user: dict = Depends(require_role("pharmacy"))):
        """Runs Gemini 3 Flash on the image with a two-pass strategy
        (strict + lenient retry). Returns extracted items + metadata for
        the frontend review step. Includes a `hint` field on empty results
        so the UI can show a helpful message instead of the generic
        'الصورة غير واضحة'."""
        image_b64 = (data.image_base64 or "").strip()
        if image_b64.startswith("data:") and "," in image_b64:
            image_b64 = image_b64.split(",", 1)[1]
        if len(image_b64) < 100:
            raise HTTPException(400, "الصورة غير صالحة")
        # Size guard: refuse absurdly small images that Gemini can't OCR
        approx_bytes = int(len(image_b64) * 0.75)
        if approx_bytes < 10 * 1024:      # <10 KB → almost certainly unreadable
            return {
                "items": [], "metadata": {}, "count": 0,
                "hint": "الصورة صغيرة جداً. حاول التقاط الصورة بجودة أعلى أو مسافة أقرب.",
            }
        # Guard against oversized payloads (>10 MB decoded)
        if approx_bytes > 10 * 1024 * 1024:
            raise HTTPException(413, "الصورة كبيرة جداً — يُرجى إعادة الالتقاط بحجم أصغر")

        items = await _gemini_extract_items(image_b64)
        meta = await _gemini_extract_metadata(image_b64)

        response = {
            "items": items,
            "metadata": meta,
            "count": len(items),
        }
        if not items:
            # Distinguish between "we understood the image but no items" and
            # a real OCR failure so the UI can give useful guidance.
            if meta and (meta.get("supplier_name") or meta.get("invoice_number")):
                response["hint"] = ("تعرّفنا على رأس الفاتورة لكن لم نستطع قراءة الأصناف بوضوح. "
                                    "جرّب: (1) تصوير الجدول عن قرب (2) إضاءة أفضل (3) إزالة الظلال (4) تصوير أفقي.")
            else:
                response["hint"] = ("لم نتمكن من قراءة الصورة. تأكد من: وضع الفاتورة على سطح مستوٍ، "
                                    "إضاءة كافية بدون انعكاس، والصورة مركّزة على الجدول كاملاً.")
        return response

    @router_paper_orders.post("/orders/paper", status_code=201)
    async def _commit_paper_order(data: CommitPaperOrderIn,
                                  user: dict = Depends(require_role("pharmacy"))):
        """Persist the reviewed paper order:
           1. Every line → new batch via `_batches.create_batch` (matches
              /medicines/buy-v2 semantics: create medicine if missing +
              append batch + refresh stock + refresh expiry mirror).
           2. Archive original image + metadata in `paper_orders`.
           3. If remaining balance > 0 → add supplier_ledger DEBIT so the
              existing supplier accounts screen surfaces it.
        """
        if not data.items:
            raise HTTPException(400, "لا يوجد أصناف للحفظ")
        image_b64 = (data.image_base64 or "").strip()
        if image_b64.startswith("data:") and "," in image_b64:
            image_b64 = image_b64.split(",", 1)[1]
        if len(image_b64) < 100:
            raise HTTPException(400, "صورة الطلبية مطلوبة")

        import batches as _batches

        pharmacy_id = user["sub"]
        added_items: List[Dict[str, Any]] = []
        computed_total = 0.0

        for it in data.items:
            name = (it.name or "").strip()
            if not name or it.quantity <= 0:
                continue
            selling_price = it.selling_price if it.selling_price and it.selling_price > 0 \
                else round(float(it.purchase_price or 0) * 1.25, 2)
            expiry_iso = _parse_expiry_safe(it.expiry_date)

            # Reuse the same lookup logic /medicines/buy-v2 uses so a
            # medicine that already exists in the pharmacy is REUSED,
            # never overwritten.
            query: Dict[str, Any] = {"pharmacy_id": pharmacy_id}
            existing = None
            if it.barcode:
                existing = await _db.medicines.find_one(
                    {**query, "barcode": it.barcode}, {"_id": 0})
            if not existing:
                existing = await _db.medicines.find_one(
                    {**query, "name": name}, {"_id": 0})

            if existing:
                med_id = existing["id"]
                updates: Dict[str, Any] = {
                    "price": selling_price,
                    "purchase_price": it.purchase_price,
                }
                if expiry_iso:
                    prev = existing.get("expiry_date")
                    updates["expiry_date"] = expiry_iso if (not prev or expiry_iso < prev) else prev
                await _db.medicines.update_one({"id": med_id}, {"$set": updates})
            else:
                med_id = str(uuid.uuid4())
                await _db.medicines.insert_one({
                    "id": med_id,
                    "pharmacy_id": pharmacy_id,
                    "name": name,
                    "barcode": (it.barcode or "").strip() or None,
                    "quantity": 0, "stock": 0,
                    "price": selling_price,
                    "purchase_price": it.purchase_price,
                    "expiry_date": expiry_iso,
                    "created_at": _now_iso(),
                })

            batch = await _batches.create_batch(
                pharmacy_id, med_id, it.purchase_price, it.quantity,
                expiry_date=expiry_iso,
            )
            # Attach the OCR-detected batch_number to the batch document
            # (informational — not used in FIFO logic).
            if it.batch_number:
                await _db.medicine_batches.update_one(
                    {"id": batch["id"]},
                    {"$set": {"batch_number": it.batch_number}},
                )
                batch["batch_number"] = it.batch_number

            # Refresh mirror stock + earliest-active expiry
            new_total = await _batches.get_total_stock(pharmacy_id, med_id)
            await _db.medicines.update_one(
                {"id": med_id},
                {"$set": {"quantity": new_total, "stock": new_total}},
            )
            await _batches.refresh_medicine_expiry(pharmacy_id, med_id)

            line_total = round(float(it.purchase_price or 0) * int(it.quantity), 2)
            computed_total += line_total
            added_items.append({
                "medicine_id": med_id,
                "batch_id": batch["id"],
                "name": name,
                "quantity": it.quantity,
                "purchase_price": it.purchase_price,
                "selling_price": selling_price,
                "batch_number": it.batch_number,
                "expiry_date": expiry_iso,
                "line_total": line_total,
            })

        if not added_items:
            raise HTTPException(400, "لا يوجد أصناف صالحة للحفظ")

        # Order total: user-provided if > 0, else sum of line totals
        total = round(float(data.total or 0), 2) if float(data.total or 0) > 0 \
            else round(computed_total, 2)
        amount_paid = round(max(0.0, min(float(data.amount_paid or 0), total)), 2)
        remaining = round(max(0.0, total - amount_paid), 2)
        if remaining <= 0.005:
            pay_status = "paid"
        elif amount_paid > 0:
            pay_status = "partial"
        else:
            pay_status = "unpaid"

        order_id = str(uuid.uuid4())
        order_number = f"PO-{datetime.now(timezone.utc).strftime('%y%m%d')}-{order_id[:6].upper()}"

        # Auto-assign a stable local supplier_id when the paper order is not
        # linked to a real marketplace supplier. This ensures every paper
        # order appears under some supplier in the debts UI and can be paid
        # via the FIFO 'تسديد دين' flow, exactly like marketplace suppliers.
        effective_supplier_id = data.supplier_id
        supplier_name_clean = (data.supplier_name or "").strip() or "مذخر غير محدد"
        if not effective_supplier_id:
            import hashlib
            key = supplier_name_clean.lower()
            h = hashlib.md5(f"{pharmacy_id}|{key}".encode("utf-8")).hexdigest()[:12]
            effective_supplier_id = f"local:{h}"

        order_doc: Dict[str, Any] = {
            "id": order_id,
            "pharmacy_id": pharmacy_id,
            "order_number": order_number,
            "invoice_number": data.invoice_number,
            "invoice_date": _parse_expiry_safe(data.invoice_date) or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "supplier_id": effective_supplier_id,
            "supplier_name": supplier_name_clean,
            "image_base64": image_b64,      # archive
            "items": added_items,
            "total": total,
            "amount_paid": amount_paid,
            "remaining": remaining,
            "payment_status": pay_status,
            "notes": data.notes,
            "created_at": _now_iso(),
            "payments": ([{
                "id": str(uuid.uuid4()),
                "amount": amount_paid,
                "at": _now_iso(),
                "notes": "دفعة أولى عند التسجيل",
            }] if amount_paid > 0 else []),
        }
        await _db.paper_orders.insert_one(order_doc.copy())

        # Mirror the remaining balance into supplier_ledger so it shows in
        # the debts UI (works for both real and local:* supplier IDs).
        if remaining > 0:
            await _db.supplier_ledger.insert_one({
                "id": str(uuid.uuid4()),
                "pharmacy_id": pharmacy_id,
                "supplier_id": effective_supplier_id,
                "kind": "paper_order_debit",
                "amount": remaining,
                "reference_id": order_id,
                "reference_type": "paper_order",
                "notes": f"طلبية مصورة {order_number}",
                "created_at": _now_iso(),
                "ts": _now_iso(),
            })

        order_doc.pop("_id", None)
        return order_doc

    @router_paper_orders.get("/orders/paper")
    async def _list_paper_orders(status: Optional[str] = None,
                                 skip: int = 0, limit: int = 50,
                                 supplier_id: Optional[str] = None,
                                 user: dict = Depends(require_role("pharmacy"))):
        limit = max(1, min(limit, 200))
        skip = max(0, skip)
        q: Dict[str, Any] = {"pharmacy_id": user["sub"]}
        if status in ("paid", "partial", "unpaid"):
            q["payment_status"] = status
        if supplier_id:
            q["supplier_id"] = supplier_id
        items = []
        # Never return the full image in list view — too heavy
        proj = {"_id": 0, "image_base64": 0}
        async for o in _db.paper_orders.find(q, proj).sort("created_at", -1).skip(skip).limit(limit):
            items.append(o)
        total_count = await _db.paper_orders.count_documents(q)
        return {"items": items, "count": len(items), "total": total_count}

    @router_paper_orders.get("/orders/paper/{order_id}")
    async def _get_paper_order(order_id: str,
                                user: dict = Depends(require_role("pharmacy"))):
        o = await _db.paper_orders.find_one(
            {"id": order_id, "pharmacy_id": user["sub"]}, {"_id": 0},
        )
        if not o:
            raise HTTPException(404, "الطلبية غير موجودة")
        return o

    @router_paper_orders.post("/orders/paper/{order_id}/pay")
    async def _pay_paper_order(order_id: str, data: PayPaperOrderIn,
                                user: dict = Depends(require_role("pharmacy"))):
        if data.amount is None or data.amount <= 0:
            raise HTTPException(400, "المبلغ غير صالح")
        o = await _db.paper_orders.find_one(
            {"id": order_id, "pharmacy_id": user["sub"]}, {"_id": 0},
        )
        if not o:
            raise HTTPException(404, "الطلبية غير موجودة")
        remaining_before = float(o.get("remaining", 0) or 0)
        amount = round(min(float(data.amount), remaining_before), 2)
        if amount <= 0:
            raise HTTPException(400, "الطلبية مدفوعة بالكامل")

        new_paid = round(float(o.get("amount_paid", 0) or 0) + amount, 2)
        new_remaining = round(max(0.0, float(o.get("total", 0) or 0) - new_paid), 2)
        new_status = "paid" if new_remaining <= 0.005 else "partial"

        payment_entry = {
            "id": str(uuid.uuid4()),
            "amount": amount,
            "at": _now_iso(),
            "notes": (data.notes or "").strip() or None,
        }
        await _db.paper_orders.update_one(
            {"id": order_id, "pharmacy_id": user["sub"]},
            {"$set": {"amount_paid": new_paid,
                       "remaining": new_remaining,
                       "payment_status": new_status,
                       "last_payment_at": _now_iso()},
             "$push": {"payments": payment_entry}},
        )

        # Mirror into supplier_ledger as a CREDIT so the debts UI stays
        # in sync with the paper-order remaining balance.
        if o.get("supplier_id"):
            await _db.supplier_ledger.insert_one({
                "id": str(uuid.uuid4()),
                "pharmacy_id": user["sub"],
                "supplier_id": o["supplier_id"],
                "kind": "paper_order_payment",
                "amount": amount,
                "reference_id": order_id,
                "reference_type": "paper_order",
                "notes": f"دفعة على طلبية {o.get('order_number','')}",
                "created_at": _now_iso(),
                "ts": _now_iso(),
            })

        return {
            "status": "ok",
            "payment": payment_entry,
            "amount_paid": new_paid,
            "remaining": new_remaining,
            "payment_status": new_status,
        }
