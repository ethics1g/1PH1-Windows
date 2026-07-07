"""
FIFO inventory batch management for 1PH1.

Each purchase creates a new batch (row) tracking:
- purchase_price (cost per unit)
- initial quantity + remaining_quantity
- purchased_at + expiry_date

Sales consume batches oldest-first. Profit per line = revenue - Σ(batch_cost × qty_taken).

Also exposes:
- profit-report endpoint (daily/monthly/yearly aggregation from sale records)
- migration helper for legacy medicines with no batch history
"""
from __future__ import annotations
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger("batches")
_db = None
_require_role = None


def init(db, require_role):
    global _db, _require_role
    _db = db; _require_role = require_role


router_batches = APIRouter(prefix="/api")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_batch(pharmacy_id: str, medicine_id: str,
                       purchase_price: float, quantity: int,
                       expiry_date: Optional[str] = None,
                       notes: Optional[str] = None) -> Dict[str, Any]:
    """Create a new inventory batch for a medicine."""
    doc = {
        "id": str(uuid.uuid4()),
        "pharmacy_id": pharmacy_id,
        "medicine_id": medicine_id,
        "purchase_price": round(float(purchase_price), 2),
        "quantity": int(quantity),
        "remaining_quantity": int(quantity),
        "purchased_at": _now_iso(),
        "expiry_date": expiry_date,
        "notes": (notes or "").strip() or None,
    }
    await _db.medicine_batches.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


async def consume_fifo(pharmacy_id: str, medicine_id: str, quantity: int
                       ) -> List[Dict[str, Any]]:
    """Deduct `quantity` from the oldest batches first. Returns per-batch
    consumption list [{batch_id, taken, purchase_price}]. Atomic per-batch
    via `remaining_quantity` decrement with condition."""
    if quantity <= 0:
        return []
    used = []
    remaining_to_take = quantity
    # Iterate through non-empty batches oldest-first
    async for batch in _db.medicine_batches.find(
        {"pharmacy_id": pharmacy_id, "medicine_id": medicine_id,
         "remaining_quantity": {"$gt": 0}}, {"_id": 0},
    ).sort("purchased_at", 1):
        if remaining_to_take <= 0:
            break
        take = min(int(batch["remaining_quantity"]), remaining_to_take)
        # Atomic decrement guarded by current remaining_quantity
        res = await _db.medicine_batches.update_one(
            {"id": batch["id"], "remaining_quantity": {"$gte": take}},
            {"$inc": {"remaining_quantity": -take}},
        )
        if res.matched_count == 0:
            # Race — someone else took stock. Skip; reload will occur next iter.
            continue
        used.append({
            "batch_id": batch["id"],
            "taken": take,
            "purchase_price": float(batch["purchase_price"]),
        })
        remaining_to_take -= take
    if remaining_to_take > 0:
        # Partial fill only — rollback everything we've taken
        for u in used:
            await _db.medicine_batches.update_one(
                {"id": u["batch_id"]}, {"$inc": {"remaining_quantity": u["taken"]}},
            )
        raise HTTPException(400, f"الكمية غير كافية — طُلب {quantity} لكن المتوفر أقل")
    return used


async def restore_batches(pharmacy_id: str, medicine_id: str, quantity: int) -> int:
    """Restore returned stock. Adds back to the most-recently-emptied batches
    (LIFO for restoration) — cheap approximation good enough for returns.
    Returns actual units restored."""
    if quantity <= 0:
        return 0
    restored = 0
    remaining_to_add = quantity
    async for batch in _db.medicine_batches.find(
        {"pharmacy_id": pharmacy_id, "medicine_id": medicine_id},
        {"_id": 0},
    ).sort("purchased_at", -1):
        if remaining_to_add <= 0:
            break
        headroom = int(batch["quantity"]) - int(batch["remaining_quantity"])
        if headroom <= 0:
            continue
        add = min(headroom, remaining_to_add)
        await _db.medicine_batches.update_one(
            {"id": batch["id"]}, {"$inc": {"remaining_quantity": add}},
        )
        restored += add
        remaining_to_add -= add
    return restored


async def get_total_stock(pharmacy_id: str, medicine_id: str) -> int:
    pipeline = [
        {"$match": {"pharmacy_id": pharmacy_id, "medicine_id": medicine_id}},
        {"$group": {"_id": None, "total": {"$sum": "$remaining_quantity"}}},
    ]
    async for r in _db.medicine_batches.aggregate(pipeline):
        return int(r.get("total", 0) or 0)
    return 0


def install_routes(require_role):
    router_batches.routes.clear()

    @router_batches.get("/medicines/{mid}/batches")
    async def _list_batches(mid: str, user: dict = Depends(require_role("pharmacy"))):
        items = []
        async for b in _db.medicine_batches.find(
            {"pharmacy_id": user["sub"], "medicine_id": mid}, {"_id": 0},
        ).sort("purchased_at", 1):
            items.append(b)
        med = await _db.medicines.find_one({"id": mid, "pharmacy_id": user["sub"]},
                                           {"_id": 0, "id": 1, "name": 1, "price": 1})
        total = sum(b["remaining_quantity"] for b in items)
        return {"medicine": med, "batches": items, "total_stock": total}

    @router_batches.get("/accounting/profit-report")
    async def _profit_report(
        period: str = Query("month", pattern="^(day|month|year)$"),
        year: Optional[int] = None,
        month: Optional[int] = None,
        user: dict = Depends(require_role("pharmacy")),
    ):
        """Aggregate profit by period.
        - period='day'   → last 30 days grouped by day
        - period='month' → current-year months (optionally specify year)
        - period='year'  → all years
        """
        now = datetime.now(timezone.utc)
        match: Dict[str, Any] = {"pharmacy_id": user["sub"]}
        if period == "day":
            start = (now - timedelta(days=30)).isoformat()
            match["created_at"] = {"$gte": start}
            group_id = {"$substr": ["$created_at", 0, 10]}  # YYYY-MM-DD
        elif period == "month":
            y = year or now.year
            start = f"{y}-01-01T00:00:00+00:00"
            end = f"{y + 1}-01-01T00:00:00+00:00"
            match["created_at"] = {"$gte": start, "$lt": end}
            group_id = {"$substr": ["$created_at", 0, 7]}  # YYYY-MM
        else:  # year
            group_id = {"$substr": ["$created_at", 0, 4]}  # YYYY

        pipeline = [
            {"$match": match},
            {"$group": {"_id": group_id,
                        "revenue": {"$sum": {"$ifNull": ["$revenue", "$total"]}},
                        "cost":    {"$sum": {"$ifNull": ["$cost", 0]}},
                        "profit":  {"$sum": {"$ifNull": ["$profit", 0]}},
                        "sales_count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        rows: List[Dict[str, Any]] = []
        totals = {"revenue": 0.0, "cost": 0.0, "profit": 0.0, "sales_count": 0}
        async for r in _db.sales.aggregate(pipeline):
            row = {
                "period": r["_id"],
                "revenue": round(r.get("revenue", 0), 2),
                "cost":    round(r.get("cost", 0), 2),
                "profit":  round(r.get("profit", 0), 2),
                "sales_count": r.get("sales_count", 0),
            }
            rows.append(row)
            totals["revenue"] += row["revenue"]
            totals["cost"] += row["cost"]
            totals["profit"] += row["profit"]
            totals["sales_count"] += row["sales_count"]
        for k in ("revenue", "cost", "profit"):
            totals[k] = round(totals[k], 2)
        return {"period": period, "rows": rows, "totals": totals}


# =====================================================================
# ======================  MIGRATION  ==================================
# =====================================================================

async def migrate_legacy_medicines(db) -> Dict[str, int]:
    """One-shot migration: for every medicine that has no batch yet, create
    one 'legacy' batch representing the current stock with the medicine's
    stored purchase_price (or 0)."""
    created = 0
    async for m in db.medicines.find({}, {"_id": 0}):
        already = await db.medicine_batches.count_documents(
            {"medicine_id": m["id"], "pharmacy_id": m.get("pharmacy_id")},
        )
        if already > 0:
            continue
        qty = int(m.get("quantity", 0) or 0)
        if qty <= 0:
            continue
        await db.medicine_batches.insert_one({
            "id": str(uuid.uuid4()),
            "pharmacy_id": m.get("pharmacy_id"),
            "medicine_id": m["id"],
            "purchase_price": round(float(m.get("purchase_price", 0) or 0), 2),
            "quantity": qty,
            "remaining_quantity": qty,
            "purchased_at": m.get("created_at") or _now_iso(),
            "expiry_date": m.get("expiry_date"),
            "notes": "legacy migration",
        })
        created += 1
    logger.info("Legacy migration created %d batches", created)
    return {"migrated": created}
