"""
Returns (product return) module for 1PH1.

Independent from purchase orders but linked via `original_order_id` for audit.
Status workflow:
  pending          → supplier approves → approved
  approved         → pharmacy ships    → waiting_for_receipt
  waiting_receipt  → supplier confirms → completed (stock deducted + credit)
  pending          → supplier rejects  → rejected

NOTE: This is a PURCHASE return (pharmacy → supplier). When the supplier
confirms receipt of the returned goods, the pharmacy's inventory is
DEDUCTED (LIFO — newest batches first) because the goods physically
leave the pharmacy. The supplier account is credited for the full return
value regardless of physical stock available at deduction time.
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("returns")

_db = None
_require_role = None
_notif = None
_accounting = None


def init(db, require_role, notif_mod=None, accounting_mod=None):
    global _db, _require_role, _notif, _accounting
    _db = db
    _require_role = require_role
    _notif = notif_mod
    _accounting = accounting_mod


router_returns = APIRouter(prefix="/api")


ReturnStatus = Literal["pending", "approved", "waiting_receipt", "completed", "rejected"]
ReturnReason = Literal["expired", "damaged", "wrong_item", "ordered_by_mistake", "other"]


class ReturnItemIn(BaseModel):
    medicine_id: Optional[str] = None
    name: str = Field(..., max_length=200)
    quantity: int = Field(..., ge=1)
    unit_price: float = Field(..., ge=0)


class CreateReturnIn(BaseModel):
    original_order_id: str
    items: List[ReturnItemIn]
    reason: ReturnReason
    notes: Optional[str] = Field(None, max_length=1000)


class RejectIn(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _notify(user_id: str, title: str, body: str, screen: str, return_id: str):
    if not _notif:
        return
    try:
        await _notif.create_notification(
            user_id, title, body,
            type="order",
            data={"screen": screen, "return_id": return_id},
            dedupe_key=f"return:{return_id}:{title[:20]}",
        )
    except Exception:
        logger.exception("Return notification failed")


def install_routes(require_role):
    router_returns.routes.clear()

    # ---------- CREATE (pharmacy) ----------
    @router_returns.post("/returns", status_code=201)
    async def _create(data: CreateReturnIn, user: dict = Depends(require_role("pharmacy"))):
        if not data.items:
            raise HTTPException(400, "يجب اختيار منتج واحد على الأقل للإرجاع")
        # Validate original order
        order = await _db.orders.find_one(
            {"id": data.original_order_id, "pharmacy_id": user["sub"]}, {"_id": 0},
        )
        if not order:
            raise HTTPException(404, "الطلبية الأصلية غير موجودة")
        if order.get("status") not in ("delivered", "completed"):
            raise HTTPException(400, "يمكن إنشاء طلب إرجاع فقط للطلبيات المُسلَّمة")

        # Validate items don't exceed original quantities
        orig_items = {(it.get("name") or "").lower(): it.get("quantity", 0)
                      for it in order.get("items", [])}
        # Compute how much has already been returned for this order (aggregate)
        prev = {}
        async for r in _db.returns.find(
            {"original_order_id": data.original_order_id,
             "status": {"$ne": "rejected"}},
            {"_id": 0, "items": 1},
        ):
            for it in r.get("items", []):
                k = (it.get("name") or "").lower()
                prev[k] = prev.get(k, 0) + it.get("quantity", 0)

        for it in data.items:
            key = it.name.lower()
            available = orig_items.get(key, 0) - prev.get(key, 0)
            if it.quantity > available:
                raise HTTPException(
                    400,
                    f"الكمية المطلوبة ({it.quantity}) لـ {it.name} أكبر من "
                    f"المتاح للإرجاع ({available})",
                )

        total = sum(it.quantity * it.unit_price for it in data.items)
        now = _now_iso()
        doc = {
            "id": str(uuid.uuid4()),
            "original_order_id": data.original_order_id,
            "pharmacy_id": user["sub"],
            "pharmacy_name": order.get("pharmacy_name"),
            "supplier_id": order.get("supplier_id"),
            "supplier_name": order.get("supplier_name"),
            "items": [it.model_dump() for it in data.items],
            "reason": data.reason,
            "notes": (data.notes or "").strip() or None,
            "total": round(total, 2),
            "status": "pending",
            "timeline": [{"status": "pending", "at": now, "by": user["sub"]}],
            "created_at": now,
            "approved_at": None,
            "shipped_at": None,
            "received_at": None,
            "completed_at": None,
        }
        await _db.returns.insert_one(doc.copy())
        doc.pop("_id", None)

        if doc["supplier_id"]:
            await _notify(
                doc["supplier_id"],
                "طلب إرجاع جديد",
                f"وصلك طلب إرجاع جديد بقيمة {doc['total']} د.ع بانتظار الموافقة.",
                "/supplier-orders",
                doc["id"],
            )
        return doc

    # ---------- LIST ----------
    @router_returns.get("/returns")
    async def _list(status: Optional[str] = None,
                    role_view: str = "auto",
                    skip: int = 0, limit: int = 100,
                    user: dict = Depends(require_role("any"))):
        role = user["role"]
        q: Dict[str, Any] = {}
        if role == "pharmacy":
            q["pharmacy_id"] = user["sub"]
        elif role == "supplier":
            q["supplier_id"] = user["sub"]
        # admin sees all
        if status and status != "all":
            q["status"] = status
        cursor = _db.returns.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
        items = [r async for r in cursor]
        return {"items": items, "count": len(items)}

    @router_returns.get("/returns/{rid}")
    async def _get(rid: str, user: dict = Depends(require_role("any"))):
        r = await _db.returns.find_one({"id": rid}, {"_id": 0})
        if not r:
            raise HTTPException(404, "طلب الإرجاع غير موجود")
        role = user["role"]
        if role == "pharmacy" and r.get("pharmacy_id") != user["sub"]:
            raise HTTPException(403, "ليس طلبك")
        if role == "supplier" and r.get("supplier_id") != user["sub"]:
            raise HTTPException(403, "ليس طلبك")
        return r

    # ---------- SUPPLIER: approve / reject / confirm-receipt ----------
    async def _transition(rid: str, expected_from: List[str], new_status: str,
                          set_fields: Dict[str, Any], actor_id: str) -> Dict[str, Any]:
        r = await _db.returns.find_one({"id": rid}, {"_id": 0})
        if not r:
            raise HTTPException(404, "طلب الإرجاع غير موجود")
        if r.get("status") not in expected_from:
            raise HTTPException(400, f"لا يمكن التحويل من الحالة {r.get('status')}")
        now = _now_iso()
        timeline = r.get("timeline", []) + [{"status": new_status, "at": now, "by": actor_id}]
        set_fields = {**set_fields, "status": new_status, "timeline": timeline}
        await _db.returns.update_one({"id": rid}, {"$set": set_fields})
        r.update(set_fields)
        return r

    @router_returns.patch("/returns/{rid}/approve")
    async def _approve(rid: str, user: dict = Depends(require_role("supplier"))):
        r = await _db.returns.find_one({"id": rid}, {"_id": 0})
        if not r or r.get("supplier_id") != user["sub"]:
            raise HTTPException(404, "غير موجود")
        r = await _transition(rid, ["pending"], "approved",
                              {"approved_at": _now_iso()}, user["sub"])
        await _notify(r["pharmacy_id"], "تمت الموافقة على الإرجاع",
                      "قم بإرسال المنتجات للمذخر لإتمام العملية.",
                      f"/returns/{rid}", rid)
        return r

    @router_returns.patch("/returns/{rid}/reject")
    async def _reject(rid: str, data: RejectIn = None,
                      user: dict = Depends(require_role("supplier"))):
        r = await _db.returns.find_one({"id": rid}, {"_id": 0})
        if not r or r.get("supplier_id") != user["sub"]:
            raise HTTPException(404, "غير موجود")
        reason = (data.reason if data else None) or "لم يُذكر سبب"
        r = await _transition(rid, ["pending"], "rejected",
                              {"rejection_reason": reason[:500]}, user["sub"])
        await _notify(r["pharmacy_id"], "تم رفض طلب الإرجاع",
                      f"السبب: {reason}", f"/returns/{rid}", rid)
        return r

    @router_returns.patch("/returns/{rid}/mark-shipped")
    async def _mark_shipped(rid: str, user: dict = Depends(require_role("pharmacy"))):
        """Pharmacy indicates the goods are on the way back to the supplier."""
        r = await _db.returns.find_one({"id": rid}, {"_id": 0})
        if not r or r.get("pharmacy_id") != user["sub"]:
            raise HTTPException(404, "غير موجود")
        r = await _transition(rid, ["approved"], "waiting_receipt",
                              {"shipped_at": _now_iso()}, user["sub"])
        await _notify(r["supplier_id"], "المرتجع في الطريق",
                      "قامت الصيدلية بإرسال المنتجات المرتجعة.",
                      "/supplier-orders", rid)
        return r

    @router_returns.patch("/returns/{rid}/confirm-receipt")
    async def _confirm(rid: str, user: dict = Depends(require_role("supplier"))):
        """Supplier confirms receipt of returned goods → restore stock + credit."""
        r = await _db.returns.find_one({"id": rid}, {"_id": 0})
        if not r or r.get("supplier_id") != user["sub"]:
            raise HTTPException(404, "غير موجود")
        allowed = ["approved", "waiting_receipt"]  # some may skip shipped step
        r = await _transition(rid, allowed, "completed",
                              {"received_at": _now_iso(),
                               "completed_at": _now_iso()},
                              user["sub"])
        # Deduct stock at pharmacy for tracked medicines: goods physically
        # leave the pharmacy when they are shipped back to the supplier.
        # LIFO deduction is best-effort — if the pharmacy already sold some
        # of these units, we deduct only what's still on hand; the supplier
        # credit is still applied for the full return value.
        import batches as _batches
        deducted = 0
        for it in r.get("items", []):
            mid = it.get("medicine_id")
            qty = int(it.get("quantity", 0) or 0)
            if not mid or qty <= 0:
                continue
            try:
                removed = await _batches.deduct_for_return(r["pharmacy_id"], mid, qty)
                deducted += removed
                # Refresh mirror on medicine doc
                new_total = await _batches.get_total_stock(r["pharmacy_id"], mid)
                await _db.medicines.update_one(
                    {"id": mid, "pharmacy_id": r["pharmacy_id"]},
                    {"$set": {"quantity": new_total, "stock": new_total}},
                )
            except Exception:
                logger.exception("Batch deduct failed for medicine %s", mid)
        # Record credit adjustment (financial memo — pharmacy is owed this amount)
        await _db.return_credits.insert_one({
            "id": str(uuid.uuid4()),
            "return_id": rid,
            "pharmacy_id": r["pharmacy_id"],
            "supplier_id": r["supplier_id"],
            "amount": r.get("total", 0),
            "created_at": _now_iso(),
        })

        # Auto-apply credit to supplier account (atomic + idempotent)
        credit_result = None
        if _accounting and r.get("supplier_id"):
            try:
                credit_result = await _accounting.apply_return_credit(
                    pharmacy_id=r["pharmacy_id"],
                    supplier_id=r["supplier_id"],
                    return_id=rid,
                    amount=float(r.get("total", 0) or 0),
                    description=f"Return credit for order {r.get('original_order_id', '')[:12]}",
                )
            except Exception:
                logger.exception("apply_return_credit failed for return %s", rid)

        await _notify(r["pharmacy_id"], "تم إكمال الإرجاع",
                      f"تم استلام المرتجع. رصيدك الدائن: {r.get('total', 0)} د.ع",
                      f"/returns/{rid}", rid)
        return {"return": r, "deducted_units": deducted, "credit": credit_result}
