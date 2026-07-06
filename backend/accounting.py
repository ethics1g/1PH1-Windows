"""
Simple Accounting module for 1PH1.

Adds cost tracking + credit sales + customer debts + payment history + inventory
valuation on top of the existing POS. Fully additive — the current sell/buy
flows keep working unchanged. Old medicines with no purchase_price are treated
as cost=0 (profit == full selling price) until re-stocked with a proper cost.

Exposes:
- `router_accounting` (already /api-prefixed)
- `init(db, require_role)` — wire deps
- `install_routes(require_role)` — mount all endpoints
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("accounting")

_db = None
_require_role = None


def init(db, require_role):
    global _db, _require_role
    _db = db
    _require_role = require_role


router_accounting = APIRouter(prefix="/api")


# =====================================================================
# ============================  MODELS  ===============================
# =====================================================================

class SellItemIn(BaseModel):
    medicine_id: str
    quantity: int = Field(..., ge=1)


class SellIn(BaseModel):
    items: List[SellItemIn]
    payment_type: str = Field(default="cash", pattern="^(cash|credit)$")
    # Only used when payment_type == "credit":
    customer_name: Optional[str] = Field(None, max_length=140)
    customer_phone: Optional[str] = Field(None, max_length=32)
    customer_notes: Optional[str] = Field(None, max_length=500)
    amount_paid: Optional[float] = None  # allow partial payment on credit sales


class CustomerPaymentIn(BaseModel):
    amount: float = Field(..., gt=0)
    notes: Optional[str] = Field(None, max_length=500)


class BuyExtendedIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    barcode: Optional[str] = Field(None, max_length=64)
    quantity: int = Field(..., ge=1)
    purchase_price: float = Field(..., ge=0)  # NEW: cost/unit
    selling_price: float = Field(..., gt=0)    # NEW: selling/unit
    image_base64: Optional[str] = None
    expiry_date: Optional[str] = None


# =====================================================================
# =========================  HELPERS  =================================
# =====================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_utc() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _upsert_customer(pharmacy_id: str, name: str, phone: Optional[str],
                           notes: Optional[str]) -> Dict[str, Any]:
    """Find-or-create a customer by (pharmacy_id, phone) if phone provided,
    else by (pharmacy_id, normalized name). Returns the customer document."""
    q: Dict[str, Any] = {"pharmacy_id": pharmacy_id}
    if phone:
        q["phone"] = phone.strip()
        existing = await _db.customers.find_one(q, {"_id": 0})
    else:
        # Match by trimmed name only when no phone (case-insensitive)
        q_name = name.strip()
        existing = await _db.customers.find_one(
            {"pharmacy_id": pharmacy_id, "phone": {"$in": [None, ""]},
             "name_lc": q_name.lower()},
            {"_id": 0},
        )
    if existing:
        # Refresh optional notes without overwriting existing
        upd = {}
        if notes and not existing.get("notes"):
            upd["notes"] = notes[:500]
        if upd:
            await _db.customers.update_one({"id": existing["id"]}, {"$set": upd})
            existing.update(upd)
        return existing

    doc = {
        "id": str(uuid.uuid4()),
        "pharmacy_id": pharmacy_id,
        "name": name.strip()[:140],
        "name_lc": name.strip().lower(),
        "phone": (phone or "").strip() or None,
        "notes": (notes or "")[:500] or None,
        "total_debt": 0.0,
        "total_paid": 0.0,
        "remaining_balance": 0.0,
        "last_payment_at": None,
        "created_at": _now_iso(),
        "status": "active",   # active | paid
    }
    await _db.customers.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


def _sale_totals(items: List[Dict[str, Any]]) -> Dict[str, float]:
    revenue = sum((it.get("selling_price", 0.0) * it.get("quantity", 0)) for it in items)
    cost = sum((it.get("purchase_price", 0.0) * it.get("quantity", 0)) for it in items)
    return {"revenue": round(revenue, 2), "cost": round(cost, 2), "profit": round(revenue - cost, 2)}


# =====================================================================
# =========================  ROUTES  ==================================
# =====================================================================

def install_routes(require_role):
    router_accounting.routes.clear()

    # ---------------- SEARCH: autocomplete ----------------
    @router_accounting.get("/medicines/search")
    async def _search_medicines(q: str = Query("", max_length=100),
                                limit: int = Query(15, ge=1, le=50),
                                user: dict = Depends(require_role("pharmacy"))):
        """Fast prefix + substring search on the pharmacy's inventory.
        Returns lightweight records for autocomplete."""
        query: Dict[str, Any] = {"pharmacy_id": user["sub"]}
        q = (q or "").strip()
        if q:
            # Escape regex metachars
            import re
            esc = re.escape(q)
            query["$or"] = [
                {"name": {"$regex": esc, "$options": "i"}},
                {"barcode": {"$regex": f"^{esc}"}},
            ]
        cursor = _db.medicines.find(
            query,
            {"_id": 0, "id": 1, "name": 1, "barcode": 1, "quantity": 1,
             "price": 1, "purchase_price": 1, "expiry_date": 1, "image_base64": 1},
        ).sort("name", 1).limit(limit)
        items = []
        async for m in cursor:
            items.append({
                "id": m["id"],
                "name": m.get("name"),
                "barcode": m.get("barcode"),
                "quantity": m.get("quantity", 0),
                "price": m.get("price", 0),
                "purchase_price": m.get("purchase_price", 0),
                "expiry_date": m.get("expiry_date"),
                "has_image": bool(m.get("image_base64")),
            })
        return {"items": items, "count": len(items)}

    # ---------------- SELL v2 (payment_type + customer) ----------------
    @router_accounting.post("/sales")
    async def _create_sale(data: SellIn, user: dict = Depends(require_role("pharmacy"))):
        if not data.items:
            raise HTTPException(400, "الطلب فارغ")
        if data.payment_type == "credit" and not (data.customer_name and data.customer_name.strip()):
            raise HTTPException(400, "اسم الزبون مطلوب للبيع الآجل")

        # Fetch all medicines in one query
        med_ids = [it.medicine_id for it in data.items]
        mmap = {}
        async for m in _db.medicines.find(
            {"id": {"$in": med_ids}, "pharmacy_id": user["sub"]}, {"_id": 0},
        ):
            mmap[m["id"]] = m
        for it in data.items:
            if it.medicine_id not in mmap:
                raise HTTPException(404, "الدواء غير موجود")
            med = mmap[it.medicine_id]
            if med.get("quantity", 0) < it.quantity:
                raise HTTPException(400, f"الكمية غير كافية: {med.get('name')}")

        # Build sold items and apply stock updates
        sold_items = []
        for it in data.items:
            med = mmap[it.medicine_id]
            unit_price = float(med.get("price", 0.0))
            unit_cost = float(med.get("purchase_price", 0.0) or 0.0)
            sold_items.append({
                "medicine_id": med["id"],
                "name": med.get("name"),
                "quantity": it.quantity,
                "selling_price": unit_price,
                "purchase_price": unit_cost,
            })
            await _db.medicines.update_one(
                {"id": med["id"]}, {"$inc": {"quantity": -it.quantity, "stock": -it.quantity}},
            )

        totals = _sale_totals(sold_items)

        # Optional customer & credit tracking
        customer_id: Optional[str] = None
        amount_paid = float(data.amount_paid or 0.0) if data.payment_type == "credit" else totals["revenue"]
        outstanding = round(max(0.0, totals["revenue"] - amount_paid), 2)

        if data.payment_type == "credit":
            cust = await _upsert_customer(user["sub"], data.customer_name or "",
                                          data.customer_phone, data.customer_notes)
            customer_id = cust["id"]
            await _db.customers.update_one(
                {"id": customer_id},
                {"$inc": {"total_debt": totals["revenue"],
                          "total_paid": amount_paid,
                          "remaining_balance": outstanding},
                 "$set": {"status": "active" if outstanding > 0 else "paid"}},
            )
            # Record any initial partial payment as a payment entry
            if amount_paid > 0:
                await _db.customer_payments.insert_one({
                    "id": str(uuid.uuid4()),
                    "pharmacy_id": user["sub"],
                    "customer_id": customer_id,
                    "amount": round(amount_paid, 2),
                    "kind": "initial",
                    "created_at": _now_iso(),
                    "notes": "دفعة أولية عند البيع",
                    "remaining_after": outstanding,
                })

        # Build sale record
        sale_doc = {
            "id": str(uuid.uuid4()),
            "pharmacy_id": user["sub"],
            "items": sold_items,
            "revenue": totals["revenue"],
            "cost": totals["cost"],
            "profit": totals["profit"],
            "total": totals["revenue"],  # for backward compat with old /sales list clients
            "payment_type": data.payment_type,
            "customer_id": customer_id,
            "customer_name": data.customer_name if data.payment_type == "credit" else None,
            "amount_paid": round(amount_paid, 2),
            "outstanding": outstanding,
            "created_at": _now_iso(),
        }
        await _db.sales.insert_one(sale_doc.copy())
        sale_doc.pop("_id", None)

        return sale_doc

    # ---------------- BUY v2 with cost/selling separation ---------------
    @router_accounting.post("/medicines/buy-v2")
    async def _buy_v2(data: BuyExtendedIn, user: dict = Depends(require_role("pharmacy"))):
        """Extended buy that stores BOTH purchase_price and selling_price on the
        medicine. Keeps backward compat with /medicines/buy (which stored only price)."""
        # Import _parse_expiry lazily to avoid circular import
        import server as _s
        expiry_iso = _s._parse_expiry(data.expiry_date)

        query: Dict[str, Any] = {"pharmacy_id": user["sub"]}
        if data.barcode:
            existing = await _db.medicines.find_one({**query, "barcode": data.barcode}, {"_id": 0})
        else:
            existing = await _db.medicines.find_one({**query, "name": data.name}, {"_id": 0})

        if existing:
            new_qty = existing.get("quantity", 0) + data.quantity
            updates: Dict[str, Any] = {
                "quantity": new_qty,
                "stock": new_qty,  # keep in sync
                "price": data.selling_price,
                "purchase_price": data.purchase_price,
            }
            if data.image_base64:
                updates["image_base64"] = data.image_base64
            if expiry_iso:
                prev = existing.get("expiry_date")
                updates["expiry_date"] = expiry_iso if (not prev or expiry_iso < prev) else prev
            await _db.medicines.update_one({"id": existing["id"]}, {"$set": updates})
            existing.update(updates)
            existing.pop("_id", None)
            return existing

        doc = {
            "id": str(uuid.uuid4()),
            "pharmacy_id": user["sub"],
            "name": data.name.strip(),
            "barcode": (data.barcode or "").strip() or None,
            "quantity": data.quantity,
            "stock": data.quantity,
            "price": data.selling_price,
            "purchase_price": data.purchase_price,
            "image_base64": data.image_base64,
            "expiry_date": expiry_iso,
            "created_at": _now_iso(),
        }
        await _db.medicines.insert_one(doc.copy())
        doc.pop("_id", None)
        return doc

    # ---------------- ACCOUNTING SUMMARY ---------------------------------
    @router_accounting.get("/accounting/summary")
    async def _summary(user: dict = Depends(require_role("pharmacy"))):
        today = _today_utc().isoformat()
        month_start = _month_start_utc().isoformat()
        pipeline_today = [
            {"$match": {"pharmacy_id": user["sub"], "created_at": {"$gte": today}}},
            {"$group": {"_id": None,
                        "revenue": {"$sum": {"$ifNull": ["$revenue", "$total"]}},
                        "profit": {"$sum": {"$ifNull": ["$profit", 0]}},
                        "count": {"$sum": 1}}},
        ]
        pipeline_month = [
            {"$match": {"pharmacy_id": user["sub"], "created_at": {"$gte": month_start}}},
            {"$group": {"_id": None,
                        "revenue": {"$sum": {"$ifNull": ["$revenue", "$total"]}},
                        "profit": {"$sum": {"$ifNull": ["$profit", 0]}},
                        "count": {"$sum": 1}}},
        ]
        t = m = None
        async for r in _db.sales.aggregate(pipeline_today):
            t = r
        async for r in _db.sales.aggregate(pipeline_month):
            m = r
        # Outstanding debts total
        debts_pipeline = [
            {"$match": {"pharmacy_id": user["sub"]}},
            {"$group": {"_id": None, "outstanding": {"$sum": "$remaining_balance"}}},
        ]
        d = None
        async for r in _db.customers.aggregate(debts_pipeline):
            d = r
        return {
            "today":  {"revenue": round((t or {}).get("revenue", 0), 2),
                       "profit":  round((t or {}).get("profit", 0), 2),
                       "sales_count": (t or {}).get("count", 0)},
            "month":  {"revenue": round((m or {}).get("revenue", 0), 2),
                       "profit":  round((m or {}).get("profit", 0), 2),
                       "sales_count": (m or {}).get("count", 0)},
            "outstanding_debts": round((d or {}).get("outstanding", 0), 2),
        }

    @router_accounting.get("/accounting/inventory-value")
    async def _inv_value(user: dict = Depends(require_role("pharmacy"))):
        pipeline = [
            {"$match": {"pharmacy_id": user["sub"], "quantity": {"$gt": 0}}},
            {"$group": {"_id": None,
                        "purchase_value": {"$sum": {"$multiply": [
                            {"$ifNull": ["$purchase_price", 0]}, "$quantity"]}},
                        "selling_value": {"$sum": {"$multiply": [
                            {"$ifNull": ["$price", 0]}, "$quantity"]}},
                        "units": {"$sum": "$quantity"},
                        "sku_count": {"$sum": 1}}},
        ]
        r = None
        async for row in _db.medicines.aggregate(pipeline):
            r = row
        purchase = round((r or {}).get("purchase_value", 0), 2)
        selling = round((r or {}).get("selling_value", 0), 2)
        return {
            "purchase_value": purchase,
            "selling_value": selling,
            "expected_profit": round(selling - purchase, 2),
            "units": (r or {}).get("units", 0),
            "sku_count": (r or {}).get("sku_count", 0),
        }

    # ---------------- CUSTOMERS ---------------------------------
    @router_accounting.get("/customers")
    async def _list_customers(q: str = Query("", max_length=100),
                              status: str = Query("all", pattern="^(all|active|paid)$"),
                              skip: int = 0, limit: int = 100,
                              user: dict = Depends(require_role("pharmacy"))):
        query: Dict[str, Any] = {"pharmacy_id": user["sub"]}
        if status != "all":
            query["status"] = status
        q = (q or "").strip()
        if q:
            import re
            esc = re.escape(q)
            query["$or"] = [
                {"name": {"$regex": esc, "$options": "i"}},
                {"phone": {"$regex": esc}},
            ]
        cursor = _db.customers.find(query, {"_id": 0}).sort("remaining_balance", -1).skip(skip).limit(limit)
        items = [c async for c in cursor]
        return {"items": items, "count": len(items)}

    @router_accounting.get("/customers/{cid}")
    async def _get_customer(cid: str, user: dict = Depends(require_role("pharmacy"))):
        cust = await _db.customers.find_one({"id": cid, "pharmacy_id": user["sub"]}, {"_id": 0})
        if not cust:
            raise HTTPException(404, "الزبون غير موجود")
        payments = []
        async for p in _db.customer_payments.find(
            {"customer_id": cid, "pharmacy_id": user["sub"]}, {"_id": 0},
        ).sort("created_at", -1).limit(500):
            payments.append(p)
        sales = []
        async for s in _db.sales.find(
            {"customer_id": cid, "pharmacy_id": user["sub"]},
            {"_id": 0, "id": 1, "items": 1, "revenue": 1, "total": 1, "amount_paid": 1,
             "outstanding": 1, "created_at": 1},
        ).sort("created_at", -1).limit(200):
            sales.append(s)
        return {"customer": cust, "payments": payments, "sales": sales}

    @router_accounting.post("/customers/{cid}/payment")
    async def _record_payment(cid: str, data: CustomerPaymentIn,
                              user: dict = Depends(require_role("pharmacy"))):
        cust = await _db.customers.find_one({"id": cid, "pharmacy_id": user["sub"]}, {"_id": 0})
        if not cust:
            raise HTTPException(404, "الزبون غير موجود")
        remaining = float(cust.get("remaining_balance", 0.0))
        if data.amount > remaining + 0.001:
            raise HTTPException(400, f"المبلغ المدخل ({data.amount}) أكبر من الرصيد المتبقي ({remaining:.2f})")
        new_remaining = round(remaining - data.amount, 2)
        new_status = "paid" if new_remaining <= 0.001 else "active"
        now_iso = _now_iso()
        payment = {
            "id": str(uuid.uuid4()),
            "pharmacy_id": user["sub"],
            "customer_id": cid,
            "amount": round(data.amount, 2),
            "kind": "receive",
            "notes": (data.notes or "")[:500] or None,
            "remaining_after": new_remaining,
            "created_at": now_iso,
        }
        await _db.customer_payments.insert_one(payment.copy())
        await _db.customers.update_one(
            {"id": cid},
            {"$set": {"remaining_balance": new_remaining, "status": new_status,
                      "last_payment_at": now_iso},
             "$inc": {"total_paid": round(data.amount, 2)}},
        )
        payment.pop("_id", None)
        return {"status": "ok", "payment": payment,
                "customer_status": new_status,
                "remaining_balance": new_remaining}
