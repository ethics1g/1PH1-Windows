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
# ==== Supplier Accounts (pharmacy → supplier payable + credits) ======
# =====================================================================

async def _pharmacy_supplier_debit(pharmacy_id: str, supplier_id: str) -> float:
    """Sum of `total` from all completed orders between this pharmacy and supplier.
    Falls back to `total_cost` for legacy docs."""
    pipeline = [
        {"$match": {"pharmacy_id": pharmacy_id, "supplier_id": supplier_id,
                    "status": "completed"}},
        {"$group": {"_id": None,
                    "total": {"$sum": {"$ifNull": ["$total", "$total_cost"]}}}},
    ]
    async for r in _db.orders.aggregate(pipeline):
        return float(r.get("total", 0) or 0)
    return 0.0


async def _read_supplier_account(pharmacy_id: str, supplier_id: str) -> Dict[str, Any]:
    """Compute live balance: debit (completed orders) − credit (applied returns)."""
    acct = await _db.supplier_accounts.find_one(
        {"pharmacy_id": pharmacy_id, "supplier_id": supplier_id}, {"_id": 0},
    )
    if not acct:
        acct = {
            "pharmacy_id": pharmacy_id, "supplier_id": supplier_id,
            "credit_applied_total": 0.0, "available_credit": 0.0,
            "applied_return_ids": [], "updated_at": _now_iso(),
        }
        await _db.supplier_accounts.insert_one(acct.copy())
    debit = await _pharmacy_supplier_debit(pharmacy_id, supplier_id)
    credit_applied = float(acct.get("credit_applied_total", 0) or 0)
    outstanding = max(0.0, round(debit - credit_applied, 2))
    return {
        "pharmacy_id": pharmacy_id,
        "supplier_id": supplier_id,
        "total_purchased": round(debit, 2),           # الإجمالي المُشترى (طلبيات مكتملة)
        "credit_applied_total": round(credit_applied, 2),  # قيمة الرواجع المطبَّقة
        "outstanding_balance": outstanding,            # الرصيد الحالي الواجب دفعه
        "available_credit": round(acct.get("available_credit", 0) or 0, 2),  # رصيد دائن جاهز
        "applied_return_ids": acct.get("applied_return_ids", []),
        "updated_at": acct.get("updated_at"),
    }


async def apply_return_credit(pharmacy_id: str, supplier_id: str,
                              return_id: str, amount: float,
                              description: Optional[str] = None) -> Dict[str, Any]:
    """Atomically apply a return credit to the pharmacy↔supplier account.

    Guarantees:
    - Idempotent via `applied_return_ids` set + MongoDB findOneAndUpdate condition.
      A second call with the same return_id is a no-op (returns existing state).
    - Reduces outstanding first; any excess overflows into available_credit for
      future purchases.
    - Records an immutable ledger entry (supplier_ledger) for audit.
    """
    if amount <= 0:
        return {"status": "skipped", "reason": "amount<=0"}

    # Idempotency guard: only apply if not already in applied_return_ids
    now = _now_iso()
    # Ensure account doc exists first (safe with unique index)
    await _db.supplier_accounts.update_one(
        {"pharmacy_id": pharmacy_id, "supplier_id": supplier_id},
        {"$setOnInsert": {"pharmacy_id": pharmacy_id, "supplier_id": supplier_id,
                          "credit_applied_total": 0.0, "available_credit": 0.0,
                          "applied_return_ids": [], "updated_at": now}},
        upsert=True,
    )
    # Then attempt atomic apply only when return_id not already recorded
    upd_res = await _db.supplier_accounts.find_one_and_update(
        {"pharmacy_id": pharmacy_id, "supplier_id": supplier_id,
         "applied_return_ids": {"$ne": return_id}},
        {"$inc": {"credit_applied_total": round(amount, 2)},
         "$addToSet": {"applied_return_ids": return_id},
         "$set": {"updated_at": now}},
        return_document=True,
    )
    if upd_res is None:
        # Already applied (guard by filter) — no-op
        return {"status": "already_applied", "return_id": return_id}

    # Post-adjust: if new credit_applied > debit → excess flows to available_credit
    debit = await _pharmacy_supplier_debit(pharmacy_id, supplier_id)
    new_credit_applied = float(upd_res.get("credit_applied_total", 0) or 0)
    excess = 0.0
    if new_credit_applied > debit:
        excess = round(new_credit_applied - debit, 2)
        # Cap credit_applied_total at debit and put the rest in available_credit
        await _db.supplier_accounts.update_one(
            {"pharmacy_id": pharmacy_id, "supplier_id": supplier_id},
            {"$set": {"credit_applied_total": round(debit, 2)},
             "$inc": {"available_credit": excess}},
        )

    outstanding_now = max(0.0, round(debit - min(new_credit_applied, debit), 2))

    # Ledger entry
    await _db.supplier_ledger.insert_one({
        "id": str(uuid.uuid4()),
        "pharmacy_id": pharmacy_id,
        "supplier_id": supplier_id,
        "kind": "return_credit",
        "amount": round(amount, 2),
        "outstanding_after": outstanding_now,
        "excess_to_credit": excess,
        "description": description or "Supplier Return Credit Applied — رصيد إرجاع",
        "reference_type": "return",
        "reference_id": return_id,
        "created_at": now,
    })
    return {
        "status": "applied",
        "return_id": return_id,
        "amount_applied": round(amount, 2),
        "outstanding_balance": outstanding_now,
        "excess_to_credit": excess,
    }


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

        # Build sold items and apply stock updates via FIFO batch consumption
        import batches as _batches  # local import to avoid circular deps
        sold_items = []
        for it in data.items:
            med = mmap[it.medicine_id]
            unit_price = float(med.get("price", 0.0))
            # FIFO deduction — returns per-batch [{batch_id, taken, purchase_price}]
            consumed = await _batches.consume_fifo(user["sub"], med["id"], it.quantity)
            # Weighted cost = Σ(batch cost × qty taken)
            weighted_cost = sum(u["purchase_price"] * u["taken"] for u in consumed)
            avg_cost = round(weighted_cost / max(1, it.quantity), 4)
            sold_items.append({
                "medicine_id": med["id"],
                "name": med.get("name"),
                "quantity": it.quantity,
                "selling_price": unit_price,
                "purchase_price": avg_cost,       # weighted-avg for reporting
                "fifo_batches": consumed,         # audit: which batches were hit
                "cost_total": round(weighted_cost, 2),
            })
            # Mirror total stock on legacy medicine doc for backward compat UI
            new_total = await _batches.get_total_stock(user["sub"], med["id"])
            await _db.medicines.update_one(
                {"id": med["id"]}, {"$set": {"quantity": new_total, "stock": new_total}},
            )
            # Refresh next-to-expire mirror in case the batch we just fully
            # consumed WAS the earliest-expiring one → alerts auto-shift.
            await _batches.refresh_medicine_expiry(user["sub"], med["id"])

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
        """Extended buy that creates a NEW inventory batch on every purchase for
        FIFO accounting. If a medicine with the same barcode/name already exists,
        we still reuse the medicine record (updating the visible selling_price)
        but always append a new batch tagged with this purchase's cost + expiry."""
        import server as _s
        import batches as _batches
        expiry_iso = _s._parse_expiry(data.expiry_date)

        query: Dict[str, Any] = {"pharmacy_id": user["sub"]}
        if data.barcode:
            existing = await _db.medicines.find_one({**query, "barcode": data.barcode}, {"_id": 0})
        else:
            existing = await _db.medicines.find_one({**query, "name": data.name}, {"_id": 0})

        if existing:
            med_id = existing["id"]
            # Update visible selling price (latest wins) + image/expiry
            updates: Dict[str, Any] = {"price": data.selling_price,
                                       "purchase_price": data.purchase_price}
            if data.image_base64:
                updates["image_base64"] = data.image_base64
            if expiry_iso:
                prev = existing.get("expiry_date")
                updates["expiry_date"] = expiry_iso if (not prev or expiry_iso < prev) else prev
            await _db.medicines.update_one({"id": med_id}, {"$set": updates})
        else:
            med_id = str(uuid.uuid4())
            await _db.medicines.insert_one({
                "id": med_id, "pharmacy_id": user["sub"],
                "name": data.name.strip(),
                "barcode": (data.barcode or "").strip() or None,
                "quantity": 0, "stock": 0,   # batches govern the real total
                "price": data.selling_price,
                "purchase_price": data.purchase_price,
                "image_base64": data.image_base64,
                "expiry_date": expiry_iso,
                "created_at": _now_iso(),
            })

        # NEW BATCH — every purchase creates its own audit row
        batch = await _batches.create_batch(
            user["sub"], med_id, data.purchase_price, data.quantity,
            expiry_date=expiry_iso,
        )

        # Refresh total stock (sum of all batches remaining)
        new_total = await _batches.get_total_stock(user["sub"], med_id)
        await _db.medicines.update_one(
            {"id": med_id}, {"$set": {"quantity": new_total, "stock": new_total}},
        )
        # Refresh the medicine's "next-to-expire" mirror from ACTIVE batches
        # (any batch whose remaining_quantity > 0). Depleted batches are
        # ignored so their expiry no longer skews the UI or alerts.
        await _batches.refresh_medicine_expiry(user["sub"], med_id)
        med = await _db.medicines.find_one({"id": med_id}, {"_id": 0})
        return {"medicine": med, "batch": batch, "total_stock": new_total}

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
        ).sort("created_at", 1).limit(500):  # ASC: oldest → newest
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
        """FIFO customer debt payment — pays oldest unpaid credit sale first,
        then the next, until amount is exhausted. Records per-invoice
        allocations so the audit trail shows exactly which invoices were
        settled and by how much. Never reorders existing invoices."""
        cust = await _db.customers.find_one({"id": cid, "pharmacy_id": user["sub"]}, {"_id": 0})
        if not cust:
            raise HTTPException(404, "الزبون غير موجود")
        remaining_balance = float(cust.get("remaining_balance", 0.0))
        if remaining_balance <= 0.001:
            raise HTTPException(400, "لا يوجد دين متبقٍ على هذا الزبون")
        if data.amount > remaining_balance + 0.001:
            raise HTTPException(400, f"المبلغ المدخل ({data.amount:.2f}) أكبر من الرصيد المتبقي ({remaining_balance:.2f})")

        # Fetch unpaid credit sales for this customer, OLDEST FIRST (FIFO).
        # Do not include cash sales (outstanding is always 0 there anyway).
        sales_cursor = _db.sales.find(
            {"pharmacy_id": user["sub"], "customer_id": cid,
             "outstanding": {"$gt": 0.001}},
            {"_id": 0, "id": 1, "outstanding": 1, "amount_paid": 1,
             "revenue": 1, "total": 1, "created_at": 1},
        ).sort("created_at", 1)  # ASC → oldest first, order preserved

        unpaid_sales = [s async for s in sales_cursor]
        amount_left = round(float(data.amount), 2)
        allocations: List[Dict[str, Any]] = []
        now_iso = _now_iso()

        for sale in unpaid_sales:
            if amount_left <= 0.001:
                break
            sale_outstanding = float(sale.get("outstanding", 0.0))
            if sale_outstanding <= 0.001:
                continue
            take = round(min(amount_left, sale_outstanding), 2)
            new_sale_outstanding = round(sale_outstanding - take, 2)
            new_sale_paid = round(float(sale.get("amount_paid", 0.0)) + take, 2)
            fully_paid = new_sale_outstanding <= 0.005

            await _db.sales.update_one(
                {"id": sale["id"], "pharmacy_id": user["sub"]},
                {"$set": {"outstanding": new_sale_outstanding,
                          "amount_paid": new_sale_paid,
                          "debt_status": "paid" if fully_paid else "partial",
                          "last_payment_at": now_iso}},
            )
            allocations.append({
                "sale_id": sale["id"],
                "sale_date": sale.get("created_at"),
                "invoice_total": round(float(sale.get("revenue") or sale.get("total") or 0), 2),
                "previous_outstanding": round(sale_outstanding, 2),
                "amount_applied": take,
                "new_outstanding": new_sale_outstanding,
                "fully_paid": fully_paid,
            })
            amount_left = round(amount_left - take, 2)

        applied_total = round(float(data.amount) - amount_left, 2)
        # Defensive fallback: legacy customers may have remaining_balance without
        # matching unpaid sales rows (data drift). In that case apply the payment
        # to the aggregate only so the UI never dead-ends on such records.
        if applied_total < float(data.amount) - 0.01 and not allocations:
            applied_total = round(min(float(data.amount), remaining_balance), 2)
        new_remaining = round(remaining_balance - applied_total, 2)
        new_status = "paid" if new_remaining <= 0.005 else "active"

        payment = {
            "id": str(uuid.uuid4()),
            "pharmacy_id": user["sub"],
            "customer_id": cid,
            "amount": applied_total,
            "kind": "receive",
            "notes": (data.notes or "")[:500] or None,
            "remaining_after": new_remaining,
            "allocations": allocations,               # NEW: FIFO trail
            "invoices_fully_paid": sum(1 for a in allocations if a["fully_paid"]),
            "invoices_partial": sum(1 for a in allocations if not a["fully_paid"]),
            "recorded_by": user.get("sub"),           # NEW: audit
            "recorded_by_name": user.get("name") or user.get("phone"),
            "created_at": now_iso,
        }
        await _db.customer_payments.insert_one(payment.copy())
        await _db.customers.update_one(
            {"id": cid},
            {"$set": {"remaining_balance": new_remaining, "status": new_status,
                      "last_payment_at": now_iso},
             "$inc": {"total_paid": applied_total}},
        )
        payment.pop("_id", None)
        return {"status": "ok", "payment": payment,
                "customer_status": new_status,
                "remaining_balance": new_remaining,
                "amount_applied": applied_total,
                "allocations": allocations}

    # -------------- Supplier Accounts (pharmacy → supplier payable) --------------
    @router_accounting.get("/accounting/supplier-accounts")
    async def _list_supplier_accounts(user: dict = Depends(require_role("pharmacy"))):
        """Overview of pharmacy's balances with all suppliers they've purchased from."""
        # Enumerate suppliers from completed orders
        pipeline = [
            {"$match": {"pharmacy_id": user["sub"], "status": "completed"}},
            {"$group": {"_id": "$supplier_id",
                        "total": {"$sum": {"$ifNull": ["$total", "$total_cost"]}},
                        "supplier_name": {"$last": "$supplier_name"},
                        "order_count": {"$sum": 1}}},
        ]
        items = []
        total_outstanding = 0.0
        total_credit = 0.0
        async for row in _db.orders.aggregate(pipeline):
            sid = row["_id"]
            if not sid:
                continue
            acct = await _read_supplier_account(user["sub"], sid)
            acct["supplier_name"] = row.get("supplier_name")
            acct["order_count"] = row.get("order_count", 0)
            items.append(acct)
            total_outstanding += acct["outstanding_balance"]
            total_credit += acct["available_credit"]
        items.sort(key=lambda x: -x["outstanding_balance"])
        return {
            "items": items,
            "count": len(items),
            "total_outstanding": round(total_outstanding, 2),
            "total_available_credit": round(total_credit, 2),
        }

    @router_accounting.get("/accounting/supplier-accounts/{supplier_id}")
    async def _get_supplier_account(supplier_id: str,
                                    user: dict = Depends(require_role("pharmacy"))):
        """Detailed statement: balance + ledger + related orders + returns."""
        acct = await _read_supplier_account(user["sub"], supplier_id)
        supplier = await _db.suppliers.find_one({"id": supplier_id}, {"_id": 0, "id": 1, "name": 1, "phone": 1})
        acct["supplier"] = supplier
        # Ledger entries
        ledger = []
        async for l in _db.supplier_ledger.find(
            {"pharmacy_id": user["sub"], "supplier_id": supplier_id}, {"_id": 0},
        ).sort("created_at", -1).limit(500):
            ledger.append(l)
        # Related orders
        orders = []
        async for o in _db.orders.find(
            {"pharmacy_id": user["sub"], "supplier_id": supplier_id, "status": "completed"},
            {"_id": 0, "id": 1, "total": 1, "total_cost": 1, "created_at": 1,
             "completed_at": 1, "items": 1, "commit_id": 1},
        ).sort("created_at", -1).limit(200):
            orders.append(o)
        # Related returns
        returns = []
        async for r in _db.returns.find(
            {"pharmacy_id": user["sub"], "supplier_id": supplier_id, "status": "completed"},
            {"_id": 0, "id": 1, "total": 1, "created_at": 1, "completed_at": 1,
             "reason": 1, "items": 1},
        ).sort("created_at", -1).limit(200):
            returns.append(r)
        return {"account": acct, "ledger": ledger, "orders": orders, "returns": returns}
