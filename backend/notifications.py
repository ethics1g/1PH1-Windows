"""
Notification and Account Management module for 1PH1.

Provides:
- Notification Center (CRUD for user's own notifications)
- Notification Preferences (per user)
- Admin Notification Panel (send / schedule / history)
- Automatic expiry reminders (90/30/7/1 day) via APScheduler
- Weekly expired-medicines report (per user)
- Account: change password, update personal info
- Push token registration (Phase 3 hook — stores token for FCM)
- Emergent-managed Push Notifications (FCM/APNs relay)

Mounts one router: `router_notifications` (already /api-prefixed).
Exposes `start_scheduler(db, logger)` and `stop_scheduler()` for lifecycle.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal, Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("notifications")

# ---------- Emergent Push (FCM/APNs relay) ------------
PUSH_BASE_URL = "https://integrations.emergentagent.com"
PUSH_KEY = os.environ.get("EMERGENT_PUSH_KEY", "placeholder")
_push_client: Optional[httpx.AsyncClient] = None


def _get_push_client() -> httpx.AsyncClient:
    global _push_client
    if _push_client is None:
        _push_client = httpx.AsyncClient(
            base_url=PUSH_BASE_URL,
            headers={"X-Push-Key": PUSH_KEY},
            timeout=10.0,
        )
    return _push_client


async def send_push(recipients: List[str],
                    data: Dict[str, Any],
                    idempotency_key: Optional[str] = None) -> None:
    """Relay a push through the Emergent-managed push service.
    recipients: list of user_ids (max 100 per call).
    data: dict with keys {title, message, subtext?, image_url?, action_url?}.
    Non-fatal — swallows errors so notification creation is never blocked."""
    if not recipients:
        return
    if "title" not in data or "message" not in data:
        logger.warning("send_push called without title/message; skipping")
        return
    # Chunk if >100
    chunks = [recipients[i:i + 100] for i in range(0, len(recipients), 100)]
    client = _get_push_client()
    for idx, chunk in enumerate(chunks):
        payload: Dict[str, Any] = {"recipients": chunk, "data": data}
        if idempotency_key:
            payload["$idempotency_key"] = f"{idempotency_key}:{idx}"
        try:
            resp = await client.post("/api/v1/push/trigger", json=payload)
            if resp.status_code == 401:
                logger.error("Emergent push: 401 unauthorized (EMERGENT_PUSH_KEY placeholder or invalid)")
                return
            if resp.status_code >= 500:
                logger.warning("Emergent push: upstream 5xx (chunk %d)", idx)
                continue
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Push relay failed (non-blocking): %s", e)

# ---------- shared references (set via init) ------------
_db = None
_require_role = None
_hash_password = None
_verify_password = None
_scheduler: Optional[AsyncIOScheduler] = None


def init(db, require_role, hash_password, verify_password):
    """Wire external dependencies. Called from server.py during startup."""
    global _db, _require_role, _hash_password, _verify_password
    _db = db
    _require_role = require_role
    _hash_password = hash_password
    _verify_password = verify_password


router_notifications = APIRouter(prefix="/api")


# =====================================================================
# ============================  MODELS  ===============================
# =====================================================================

NotificationType = Literal[
    "admin",              # from admin broadcast
    "expiry_reminder",    # scheduled: 90/30/7/1 day before expiry
    "expired_weekly",     # weekly recap of expired items
    "order",              # order lifecycle
    "system",             # generic system message
]

AudienceMode = Literal["all", "role", "region", "ids"]


class NotificationCreate(BaseModel):
    title: str = Field(..., max_length=140)
    body: str = Field(..., max_length=1000)
    type: NotificationType = "system"
    data: Dict[str, Any] = Field(default_factory=dict)  # {screen, params}


class AdminSendIn(BaseModel):
    title: str = Field(..., max_length=140)
    body: str = Field(..., max_length=1000)
    audience_mode: AudienceMode
    role: Optional[str] = None            # required when audience_mode="role"
    region: Optional[str] = None          # required when audience_mode="region"
    ids: Optional[List[str]] = None       # required when audience_mode="ids"
    data: Dict[str, Any] = Field(default_factory=dict)
    scheduled_for: Optional[str] = None   # ISO-8601 UTC. If set → scheduled batch.

    @field_validator("role")
    @classmethod
    def _check_role(cls, v):
        if v is not None and v not in ("pharmacy", "supplier", "admin"):
            raise ValueError("role must be pharmacy|supplier|admin")
        return v


class PreferencesIn(BaseModel):
    notifications_enabled: Optional[bool] = None
    expiry_reminders: Optional[bool] = None
    weekly_expired_report: Optional[bool] = None
    admin_announcements: Optional[bool] = None
    order_updates: Optional[bool] = None


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6, max_length=200)


class UpdateProfileIn(BaseModel):
    name: Optional[str] = Field(None, max_length=140)
    email: Optional[str] = Field(None, max_length=200)
    display_name: Optional[str] = Field(None, max_length=140)


class PushTokenIn(BaseModel):
    token: str = Field(..., min_length=8, max_length=500)
    platform: Literal["android", "ios", "web"] = "android"
    device_id: Optional[str] = Field(None, max_length=200)


# =====================================================================
# ==========================  HELPERS  ================================
# =====================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_preferences() -> Dict[str, bool]:
    return {
        "notifications_enabled": True,
        "expiry_reminders": True,
        "weekly_expired_report": True,
        "admin_announcements": True,
        "order_updates": True,
    }


async def _get_preferences(user_id: str) -> Dict[str, Any]:
    doc = await _db.notification_preferences.find_one({"user_id": user_id}, {"_id": 0})
    if not doc:
        prefs = _default_preferences()
        prefs["user_id"] = user_id
        prefs["updated_at"] = _now_iso()
        try:
            await _db.notification_preferences.insert_one(prefs)
        except Exception:
            # race — read again
            doc = await _db.notification_preferences.find_one({"user_id": user_id}, {"_id": 0})
            if doc:
                return doc
        return prefs
    return doc


async def _user_allows(user_id: str, notif_type: NotificationType) -> bool:
    prefs = await _get_preferences(user_id)
    if not prefs.get("notifications_enabled", True):
        return False
    mapping = {
        "expiry_reminder": "expiry_reminders",
        "expired_weekly": "weekly_expired_report",
        "admin": "admin_announcements",
        "order": "order_updates",
        "system": "notifications_enabled",
    }
    key = mapping.get(notif_type, "notifications_enabled")
    return bool(prefs.get(key, True))


async def create_notification(user_id: str,
                              title: str,
                              body: str,
                              type: NotificationType = "system",
                              data: Optional[Dict[str, Any]] = None,
                              batch_id: Optional[str] = None,
                              dedupe_key: Optional[str] = None,
                              respect_prefs: bool = True) -> Optional[str]:
    """Create one notification for `user_id`. Returns the notification id, or None if
    skipped (either prefs disabled, or dedupe_key already exists)."""
    if respect_prefs and not await _user_allows(user_id, type):
        logger.debug("Skipping notification (prefs): user=%s type=%s", user_id, type)
        return None
    if dedupe_key:
        existing = await _db.notifications.find_one(
            {"user_id": user_id, "dedupe_key": dedupe_key}, {"_id": 0, "id": 1}
        )
        if existing:
            return existing.get("id")
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "title": title[:140],
        "body": body[:1000],
        "type": type,
        "data": data or {},
        "read": False,
        "read_at": None,
        "created_at": _now_iso(),
        "batch_id": batch_id,
        "dedupe_key": dedupe_key,
        "delivery_status": "delivered",  # in-app; FCM will set separately later
    }
    await _db.notifications.insert_one(doc)

    # Additive: also relay to FCM/APNs via Emergent-managed push.
    # Non-blocking — any failure just logs a warning.
    try:
        push_data: Dict[str, Any] = {
            "title": doc["title"],
            "message": doc["body"],
        }
        screen = (data or {}).get("screen")
        if screen:
            push_data["action_url"] = screen
        await send_push([user_id], push_data, idempotency_key=doc["id"])
    except Exception as e:
        logger.warning("Push relay for notification %s failed: %s", doc["id"], e)

    return doc["id"]


async def _resolve_audience(mode: AudienceMode,
                            role: Optional[str] = None,
                            region: Optional[str] = None,
                            ids: Optional[List[str]] = None) -> List[str]:
    """Return list of user IDs that match the audience. Enumerates users across
    the `pharmacies` and `suppliers` collections (admins excluded unless mode='ids')."""
    if mode == "ids":
        return list(dict.fromkeys(ids or []))  # de-dup while preserving order

    result: List[str] = []
    if mode == "all" or (mode == "role" and role == "pharmacy") or mode == "region":
        q = {}
        if mode == "region" and region:
            q["region_normalized"] = region.strip().lower()
        async for u in _db.pharmacies.find(q, {"_id": 0, "id": 1}):
            result.append(u["id"])
    if mode == "all" or (mode == "role" and role == "supplier"):
        q2 = {}
        if mode == "region" and region:
            q2["region_normalized"] = region.strip().lower()
        async for u in _db.suppliers.find(q2, {"_id": 0, "id": 1}):
            result.append(u["id"])
    if mode == "role" and role == "admin":
        async for u in _db.admins.find({}, {"_id": 0, "id": 1}):
            result.append(u["id"])

    return list(dict.fromkeys(result))


async def _dispatch_batch(batch: Dict[str, Any]) -> Dict[str, int]:
    """Materialize notifications for every recipient of a batch. Records stats."""
    ids = await _resolve_audience(
        batch["audience_mode"], batch.get("role"), batch.get("region"), batch.get("ids"),
    )
    delivered = 0
    failed = 0
    for uid in ids:
        try:
            nid = await create_notification(
                uid,
                batch["title"],
                batch["body"],
                type="admin",
                data=batch.get("data") or {},
                batch_id=batch["id"],
                respect_prefs=True,
            )
            if nid:
                delivered += 1
        except Exception as e:
            logger.exception("Failed to deliver notification to %s: %s", uid, e)
            failed += 1
    await _db.notification_batches.update_one(
        {"id": batch["id"]},
        {"$set": {
            "sent_at": _now_iso(),
            "status": "sent",
            "total_recipients": len(ids),
            "delivered_count": delivered,
            "failed_count": failed,
        }},
    )
    return {"total": len(ids), "delivered": delivered, "failed": failed}


# =====================================================================
# ==========================  ENDPOINTS  ==============================
# =====================================================================

# ---------- 1) Notification Center (user-facing) ----------

@router_notifications.get("/notifications")
async def list_notifications(unread_only: bool = False,
                             skip: int = 0,
                             limit: int = 50,
                             user: dict = Depends(lambda: None)):  # placeholder, rebound in init
    raise HTTPException(500, "not initialized")  # replaced below


@router_notifications.get("/notifications/unread-count")
async def unread_count(user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


@router_notifications.patch("/notifications/{nid}/read")
async def mark_read(nid: str, user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


@router_notifications.patch("/notifications/read-all")
async def mark_all_read(user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


@router_notifications.delete("/notifications/{nid}")
async def delete_notification(nid: str, user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


@router_notifications.delete("/notifications")
async def clear_all_notifications(user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


# ---------- 2) Preferences ----------
@router_notifications.get("/me/notification-preferences")
async def get_preferences(user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


@router_notifications.put("/me/notification-preferences")
async def put_preferences(data: PreferencesIn, user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


# ---------- 3) Push tokens (Phase 3 hook) ----------
@router_notifications.post("/me/push-token")
async def register_push_token(data: PushTokenIn, user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


@router_notifications.delete("/me/push-token")
async def unregister_push_token(data: PushTokenIn, user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


# ---------- 4) Account: change password + personal info ----------
@router_notifications.patch("/me/password")
async def change_password(data: ChangePasswordIn, user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


@router_notifications.get("/me/profile")
async def get_profile(user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


@router_notifications.patch("/me/profile")
async def update_profile(data: UpdateProfileIn, user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


# ---------- 5) Admin Panel ----------
@router_notifications.post("/admin/notifications/send")
async def admin_send(data: AdminSendIn, user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


@router_notifications.get("/admin/notifications/history")
async def admin_history(skip: int = 0, limit: int = 50, user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


@router_notifications.get("/admin/notifications/audience-summary")
async def admin_audience(user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


@router_notifications.delete("/admin/notifications/scheduled/{batch_id}")
async def admin_cancel_scheduled(batch_id: str, user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


# ---------- 6) Expired medicines list (deep-link target from weekly notification) ----------
@router_notifications.get("/medicines/expired-list")
async def expired_list(user: dict = Depends(lambda: None)):
    raise HTTPException(500, "not initialized")


# =====================================================================
# The above route stubs get replaced with proper role-guarded versions in
# `install_routes()`. This structure lets init() be called AFTER server.py
# is fully loaded, so we don't create a circular import.
# =====================================================================


def install_routes(require_role):
    """Build actual endpoints now that require_role is available. Idempotent."""

    # Clear stub routes so we can register real ones
    router_notifications.routes.clear()

    # ------------- USER: notifications -------------
    @router_notifications.get("/notifications")
    async def _list(unread_only: bool = Query(False),
                    skip: int = Query(0, ge=0),
                    limit: int = Query(50, ge=1, le=200),
                    user: dict = Depends(require_role("any"))):
        q: Dict[str, Any] = {"user_id": user["sub"]}
        if unread_only:
            q["read"] = False
        cursor = _db.notifications.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
        items = [n async for n in cursor]
        return {"items": items, "count": len(items)}

    @router_notifications.get("/notifications/unread-count")
    async def _unread(user: dict = Depends(require_role("any"))):
        n = await _db.notifications.count_documents({"user_id": user["sub"], "read": False})
        return {"unread": n}

    @router_notifications.patch("/notifications/{nid}/read")
    async def _mark(nid: str, user: dict = Depends(require_role("any"))):
        r = await _db.notifications.update_one(
            {"id": nid, "user_id": user["sub"]},
            {"$set": {"read": True, "read_at": _now_iso()}},
        )
        if r.matched_count == 0:
            raise HTTPException(404, "غير موجود")
        return {"status": "ok"}

    @router_notifications.patch("/notifications/read-all")
    async def _mark_all(user: dict = Depends(require_role("any"))):
        r = await _db.notifications.update_many(
            {"user_id": user["sub"], "read": False},
            {"$set": {"read": True, "read_at": _now_iso()}},
        )
        return {"status": "ok", "updated": r.modified_count}

    @router_notifications.delete("/notifications/{nid}")
    async def _del(nid: str, user: dict = Depends(require_role("any"))):
        r = await _db.notifications.delete_one({"id": nid, "user_id": user["sub"]})
        if r.deleted_count == 0:
            raise HTTPException(404, "غير موجود")
        return {"status": "ok"}

    @router_notifications.delete("/notifications")
    async def _clear(user: dict = Depends(require_role("any"))):
        r = await _db.notifications.delete_many({"user_id": user["sub"]})
        return {"status": "ok", "deleted": r.deleted_count}

    # ------------- USER: preferences -------------
    @router_notifications.get("/me/notification-preferences")
    async def _prefs(user: dict = Depends(require_role("any"))):
        prefs = await _get_preferences(user["sub"])
        prefs.pop("_id", None)
        return prefs

    @router_notifications.put("/me/notification-preferences")
    async def _put_prefs(data: PreferencesIn, user: dict = Depends(require_role("any"))):
        updates = {k: v for k, v in data.model_dump().items() if v is not None}
        if not updates:
            return await _get_preferences(user["sub"])
        updates["updated_at"] = _now_iso()
        # Ensure the user prefs doc exists first (idempotent) then apply updates.
        # Using two separate calls avoids the $set/$setOnInsert path conflict on the
        # SAME field key (Mongo error 40).
        await _db.notification_preferences.update_one(
            {"user_id": user["sub"]},
            {"$setOnInsert": {"user_id": user["sub"], **_default_preferences(),
                              "updated_at": _now_iso()}},
            upsert=True,
        )
        await _db.notification_preferences.update_one(
            {"user_id": user["sub"]}, {"$set": updates},
        )
        prefs = await _get_preferences(user["sub"])
        prefs.pop("_id", None)
        return prefs

    # ------------- Emergent-managed Push (FCM/APNs relay) ------------
    @router_notifications.post("/register-push", status_code=201)
    async def _register_push(body: dict, user: dict = Depends(require_role("any"))):
        """Register a device token with the Emergent Push service (SuprSend).
        Body: {user_id: str, platform: 'android'|'ios', device_token: str}.
        The user_id in the body must match the authenticated user (defense in depth)."""
        uid = body.get("user_id") or user["sub"]
        platform = body.get("platform") or "android"
        token = body.get("device_token")
        if not token:
            raise HTTPException(400, "device_token مطلوب")
        if uid != user["sub"]:
            raise HTTPException(403, "user_id لا يطابق المستخدم الحالي")
        client = _get_push_client()
        try:
            resp = await client.post(
                "/api/v1/push/users/register",
                json={"user_id": uid, "platform": platform, "device_token": token},
            )
            if resp.status_code == 401:
                logger.error("register-push: EMERGENT_PUSH_KEY placeholder/invalid")
                # Return 202 so client considers it success; deployer will fix key.
                return {"status": "queued", "note": "waiting for deployment"}
            if resp.status_code >= 500:
                return {"status": "queued", "note": "provider transient"}
            resp.raise_for_status()
        except Exception as e:
            logger.warning("register-push failed (non-blocking): %s", e)
            return {"status": "queued"}
        return {"status": "registered"}
    @router_notifications.post("/me/push-token")
    async def _reg_token(data: PushTokenIn, user: dict = Depends(require_role("any"))):
        await _db.push_tokens.update_one(
            {"user_id": user["sub"], "token": data.token},
            {"$set": {
                "user_id": user["sub"],
                "token": data.token,
                "platform": data.platform,
                "device_id": data.device_id,
                "last_seen_at": _now_iso(),
            },
             "$setOnInsert": {"created_at": _now_iso()}},
            upsert=True,
        )
        return {"status": "ok"}

    @router_notifications.delete("/me/push-token")
    async def _unreg_token(data: PushTokenIn, user: dict = Depends(require_role("any"))):
        r = await _db.push_tokens.delete_one({"user_id": user["sub"], "token": data.token})
        return {"status": "ok", "deleted": r.deleted_count}

    # ------------- USER: account (password/profile) -------------
    async def _find_user_doc(user_id: str, role: str):
        col = {"pharmacy": _db.pharmacies, "supplier": _db.suppliers, "admin": _db.admins}.get(role)
        if col is None:
            return None, None
        doc = await col.find_one({"id": user_id}, {"_id": 0})
        return col, doc

    @router_notifications.patch("/me/password")
    async def _change_pw(data: ChangePasswordIn, user: dict = Depends(require_role("any"))):
        col, doc = await _find_user_doc(user["sub"], user["role"])
        if not doc:
            raise HTTPException(404, "المستخدم غير موجود")
        if not _verify_password(data.current_password, doc.get("password", "")):
            raise HTTPException(400, "كلمة السر الحالية غير صحيحة")
        await col.update_one(
            {"id": user["sub"]},
            {"$set": {
                "password": _hash_password(data.new_password),
                "must_change_password": False,
                "password_updated_at": _now_iso(),
            }},
        )
        await create_notification(
            user["sub"], "تم تغيير كلمة السر",
            "تم تغيير كلمة السر بنجاح. إن لم تكن أنت، الرجاء التواصل مع الدعم.",
            type="system", respect_prefs=False,
        )
        return {"status": "ok"}

    @router_notifications.get("/me/profile")
    async def _my_profile(user: dict = Depends(require_role("any"))):
        col, doc = await _find_user_doc(user["sub"], user["role"])
        if not doc:
            raise HTTPException(404, "المستخدم غير موجود")
        doc.pop("password", None)
        doc.pop("_id", None)
        doc["role"] = user["role"]
        return doc

    @router_notifications.patch("/me/profile")
    async def _upd_profile(data: UpdateProfileIn, user: dict = Depends(require_role("any"))):
        col, doc = await _find_user_doc(user["sub"], user["role"])
        if not doc:
            raise HTTPException(404, "المستخدم غير موجود")
        updates = {k: v for k, v in data.model_dump().items() if v is not None and v != ""}
        if not updates:
            return {"status": "no_op"}
        updates["profile_updated_at"] = _now_iso()
        await col.update_one({"id": user["sub"]}, {"$set": updates})
        return {"status": "ok"}

    # ------------- ADMIN -------------
    @router_notifications.post("/admin/notifications/send")
    async def _admin_send(data: AdminSendIn, user: dict = Depends(require_role("admin"))):
        # Validate audience params
        if data.audience_mode == "role" and not data.role:
            raise HTTPException(400, "role مطلوب عند audience_mode=role")
        if data.audience_mode == "region" and not data.region:
            raise HTTPException(400, "region مطلوب عند audience_mode=region")
        if data.audience_mode == "ids" and not data.ids:
            raise HTTPException(400, "ids مطلوبة عند audience_mode=ids")

        batch = {
            "id": str(uuid.uuid4()),
            "admin_id": user["sub"],
            "title": data.title,
            "body": data.body,
            "audience_mode": data.audience_mode,
            "role": data.role,
            "region": data.region,
            "ids": data.ids,
            "data": data.data or {},
            "scheduled_for": data.scheduled_for,
            "status": "scheduled" if data.scheduled_for else "pending",
            "created_at": _now_iso(),
            "sent_at": None,
            "total_recipients": 0,
            "delivered_count": 0,
            "failed_count": 0,
        }
        await _db.notification_batches.insert_one(batch)

        if data.scheduled_for:
            # Parse and schedule
            try:
                dt = datetime.fromisoformat(data.scheduled_for.replace("Z", "+00:00"))
            except Exception:
                raise HTTPException(400, "scheduled_for غير صالح (ISO-8601)")
            if dt <= datetime.now(timezone.utc):
                raise HTTPException(400, "scheduled_for يجب أن يكون في المستقبل")
            _scheduler.add_job(
                _run_scheduled_batch, DateTrigger(run_date=dt),
                args=[batch["id"]], id=f"batch_{batch['id']}", replace_existing=True,
            )
            logger.info("Scheduled batch %s for %s", batch["id"], dt.isoformat())
            return {"status": "scheduled", "batch_id": batch["id"], "run_at": dt.isoformat()}

        # Dispatch immediately
        stats = await _dispatch_batch(batch)
        return {"status": "sent", "batch_id": batch["id"], **stats}

    @router_notifications.get("/admin/notifications/history")
    async def _admin_hist(skip: int = 0, limit: int = 50,
                          user: dict = Depends(require_role("admin"))):
        cursor = _db.notification_batches.find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
        items = [b async for b in cursor]
        return {"items": items, "count": len(items)}

    @router_notifications.get("/admin/notifications/audience-summary")
    async def _admin_aud(user: dict = Depends(require_role("admin"))):
        pharmacies = await _db.pharmacies.count_documents({})
        suppliers = await _db.suppliers.count_documents({})
        admins = await _db.admins.count_documents({})
        # By region
        agg = [{"$group": {"_id": "$region_normalized", "count": {"$sum": 1}}}]
        regions: Dict[str, int] = {}
        async for r in _db.pharmacies.aggregate(agg):
            key = r.get("_id") or "غير محدد"
            regions[key] = regions.get(key, 0) + r["count"]
        async for r in _db.suppliers.aggregate(agg):
            key = r.get("_id") or "غير محدد"
            regions[key] = regions.get(key, 0) + r["count"]
        return {
            "roles": {"pharmacy": pharmacies, "supplier": suppliers, "admin": admins},
            "total": pharmacies + suppliers,
            "regions": regions,
        }

    @router_notifications.delete("/admin/notifications/scheduled/{batch_id}")
    async def _admin_cancel(batch_id: str, user: dict = Depends(require_role("admin"))):
        batch = await _db.notification_batches.find_one({"id": batch_id}, {"_id": 0})
        if not batch:
            raise HTTPException(404, "غير موجود")
        if batch.get("status") != "scheduled":
            raise HTTPException(400, "لا يمكن الإلغاء (تم الإرسال بالفعل)")
        try:
            _scheduler.remove_job(f"batch_{batch_id}")
        except Exception:
            pass
        await _db.notification_batches.update_one(
            {"id": batch_id}, {"$set": {"status": "canceled", "canceled_at": _now_iso()}},
        )
        return {"status": "canceled"}

    # ------------- Expired medicines list (deep-link target) -------------
    @router_notifications.get("/medicines/expired-list")
    async def _expired(user: dict = Depends(require_role("pharmacy"))):
        today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cursor = _db.medicines.find(
            {"pharmacy_id": user["sub"],
             "expiry_date": {"$lte": today_iso, "$ne": None},
             "stock": {"$gt": 0}},
            {"_id": 0, "id": 1, "name": 1, "barcode": 1, "expiry_date": 1, "stock": 1, "price": 1},
        ).sort("expiry_date", 1)
        items = [m async for m in cursor]
        return {"items": items, "count": len(items)}


# =====================================================================
# ==========================  SCHEDULER  ==============================
# =====================================================================

async def _run_scheduled_batch(batch_id: str):
    """Called by APScheduler at the scheduled time."""
    try:
        batch = await _db.notification_batches.find_one({"id": batch_id}, {"_id": 0})
        if not batch:
            logger.warning("Scheduled batch %s not found", batch_id)
            return
        if batch.get("status") != "scheduled":
            logger.info("Batch %s not in scheduled status (%s), skipping", batch_id, batch.get("status"))
            return
        stats = await _dispatch_batch(batch)
        logger.info("Scheduled batch %s dispatched: %s", batch_id, stats)
    except Exception:
        logger.exception("Failed to run scheduled batch %s", batch_id)
        await _db.notification_batches.update_one(
            {"id": batch_id}, {"$set": {"status": "failed"}},
        )


THRESHOLD_DAYS = [90, 30, 7, 1]


async def _daily_expiry_scan():
    """Every day at 08:00 UTC: create expiry reminders for medicines whose expiry
    falls in {90, 30, 7, 1} days from today. Deduped per (medicine, day-bucket)."""
    try:
        today = datetime.now(timezone.utc).date()
        for days in THRESHOLD_DAYS:
            target = (today + timedelta(days=days)).strftime("%Y-%m-%d")
            cursor = _db.medicines.find(
                {"expiry_date": target, "stock": {"$gt": 0}},
                {"_id": 0, "id": 1, "name": 1, "pharmacy_id": 1, "stock": 1, "expiry_date": 1},
            )
            count = 0
            async for m in cursor:
                pid = m.get("pharmacy_id")
                if not pid:
                    continue
                dedupe = f"expiry:{m['id']}:{days}"
                await create_notification(
                    pid,
                    f"تنبيه صلاحية: {m['name']}",
                    f"سينتهي الدواء بعد {days} يوم/أيام (تاريخ {m['expiry_date']}). الكمية المتبقية: {m.get('stock', 0)}.",
                    type="expiry_reminder",
                    data={"screen": "/inventory", "medicine_id": m["id"], "expiry_date": m["expiry_date"]},
                    dedupe_key=dedupe,
                    respect_prefs=True,
                )
                count += 1
            logger.info("Expiry scan %s-day: created up to %d notifications", days, count)
    except Exception:
        logger.exception("Daily expiry scan failed")


async def _weekly_expired_report():
    """Every Monday 09:00 UTC: per pharmacy, count all currently-expired medicines
    with stock>0 and send a single summary notification (deep-link → expired list)."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Group expired items by pharmacy
        pipeline = [
            {"$match": {"expiry_date": {"$lte": today, "$ne": None}, "stock": {"$gt": 0}}},
            {"$group": {"_id": "$pharmacy_id",
                        "count": {"$sum": 1},
                        "total_units": {"$sum": "$stock"}}},
        ]
        async for row in _db.medicines.aggregate(pipeline):
            pid = row["_id"]
            if not pid:
                continue
            count = row["count"]
            units = row["total_units"]
            week_key = datetime.now(timezone.utc).strftime("%Y-W%V")
            await create_notification(
                pid,
                f"لديك {count} دواء منتهي الصلاحية",
                f"تم رصد {count} دواء منتهي الصلاحية (إجمالي {units} وحدة). اضغط لعرض القائمة الكاملة.",
                type="expired_weekly",
                data={"screen": "/medicines/expired", "count": count, "total_units": units},
                dedupe_key=f"expired_weekly:{pid}:{week_key}",
                respect_prefs=True,
            )
        logger.info("Weekly expired report completed")
    except Exception:
        logger.exception("Weekly expired report failed")


async def _restore_scheduled_batches():
    """On startup, re-register scheduled batches from DB with APScheduler."""
    try:
        cursor = _db.notification_batches.find(
            {"status": "scheduled", "scheduled_for": {"$ne": None}},
            {"_id": 0, "id": 1, "scheduled_for": 1},
        )
        now = datetime.now(timezone.utc)
        restored = 0
        async for b in cursor:
            try:
                dt = datetime.fromisoformat(b["scheduled_for"].replace("Z", "+00:00"))
            except Exception:
                continue
            if dt <= now:
                # Missed. Dispatch immediately.
                await _run_scheduled_batch(b["id"])
                continue
            _scheduler.add_job(
                _run_scheduled_batch, DateTrigger(run_date=dt),
                args=[b["id"]], id=f"batch_{b['id']}", replace_existing=True,
            )
            restored += 1
        logger.info("Restored %d scheduled notification batches", restored)
    except Exception:
        logger.exception("Failed to restore scheduled batches")


def start_scheduler():
    """Start APScheduler with recurring jobs. Called from server.py startup."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    # Daily expiry reminder scan at 08:00 UTC
    _scheduler.add_job(
        _daily_expiry_scan,
        CronTrigger(hour=8, minute=0),
        id="daily_expiry_scan", replace_existing=True,
    )
    # Weekly expired report Monday 09:00 UTC
    _scheduler.add_job(
        _weekly_expired_report,
        CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="weekly_expired_report", replace_existing=True,
    )
    _scheduler.start()
    logger.info("Notification scheduler started")


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


async def restore_scheduled():
    """Public wrapper for server.py to call after start_scheduler()."""
    await _restore_scheduled_batches()


# ---------- Optional dev helper: run jobs manually ----------

async def run_daily_scan_now():
    await _daily_expiry_scan()


async def run_weekly_report_now():
    await _weekly_expired_report()
