"""Comprehensive tests for the Notification & Account Management system.

Covers:
- Notification Center CRUD (list, unread count, mark read/all, delete/clear)
- Notification Preferences (default, partial PUT, no 500)
- /me/password (wrong current, correct current, system notification)
- /me/profile GET/PATCH
- Admin panel (send all/role/scheduled/cancel/history/audience-summary)
- RBAC (pharmacy cannot send admin; supplier register-push different uid)
- /api/register-push placeholder → queued
- /api/medicines/expired-list (pharmacy only)
- Manual invocation of _daily_expiry_scan and _weekly_expired_report via HTTP-inserted medicines
- Cross-user isolation (user A cannot access user B's notifications)
"""
import os
import time
import uuid
import asyncio
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://pharma-checkout-8.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

PHARMACY_PHONE = "07700000001"
PHARMACY_PASS = "pass123"
SUPPLIER_PHONE = "07811111111"
SUPPLIER_PASS = "sup1"
ADMIN_PHONE = "0000000000"
ADMIN_PASS = "admin123"


# ---------------------- fixtures ----------------------

def _login(phone, password):
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": password}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"login failed for {phone}: {r.status_code} {r.text[:200]}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def pharmacy_token():
    return _login(PHARMACY_PHONE, PHARMACY_PASS)


@pytest.fixture(scope="module")
def supplier_token():
    return _login(SUPPLIER_PHONE, SUPPLIER_PASS)


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_PHONE, ADMIN_PASS)


def H(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def pharmacy_id(pharmacy_token):
    r = requests.get(f"{API}/me/profile", headers=H(pharmacy_token), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def supplier_id(supplier_token):
    r = requests.get(f"{API}/me/profile", headers=H(supplier_token), timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------------------- Notification Center ----------------------

class TestNotificationCenter:
    def test_list_notifications_paginated(self, pharmacy_token):
        r = requests.get(f"{API}/notifications?limit=10&skip=0", headers=H(pharmacy_token), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "items" in j and "count" in j
        assert isinstance(j["items"], list)

    def test_unread_count(self, pharmacy_token):
        r = requests.get(f"{API}/notifications/unread-count", headers=H(pharmacy_token), timeout=15)
        assert r.status_code == 200
        assert "unread" in r.json()
        assert isinstance(r.json()["unread"], int)

    def test_mark_read_nonexistent_404(self, pharmacy_token):
        r = requests.patch(f"{API}/notifications/{uuid.uuid4()}/read", headers=H(pharmacy_token), timeout=15)
        assert r.status_code == 404

    def test_delete_nonexistent_404(self, pharmacy_token):
        r = requests.delete(f"{API}/notifications/{uuid.uuid4()}", headers=H(pharmacy_token), timeout=15)
        assert r.status_code == 404

    def test_mark_all_read(self, pharmacy_token):
        r = requests.patch(f"{API}/notifications/read-all", headers=H(pharmacy_token), timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # unread should be 0 now
        c = requests.get(f"{API}/notifications/unread-count", headers=H(pharmacy_token), timeout=15).json()
        assert c["unread"] == 0


# ---------------------- Preferences ----------------------

class TestPreferences:
    def test_get_default(self, supplier_token):
        r = requests.get(f"{API}/me/notification-preferences", headers=H(supplier_token), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        for k in ("notifications_enabled", "expiry_reminders", "weekly_expired_report",
                  "admin_announcements", "order_updates"):
            assert k in j, f"missing default key {k}"

    def test_put_partial_no_500(self, pharmacy_token):
        """CRITICAL regression: PUT with partial payload used to return 500 due to $set/$setOnInsert conflict."""
        r = requests.put(f"{API}/me/notification-preferences",
                         headers=H(pharmacy_token),
                         json={"expiry_reminders": False}, timeout=15)
        assert r.status_code == 200, f"partial PUT returned {r.status_code}: {r.text}"
        assert r.json()["expiry_reminders"] is False
        # revert
        rr = requests.put(f"{API}/me/notification-preferences",
                          headers=H(pharmacy_token),
                          json={"expiry_reminders": True}, timeout=15)
        assert rr.status_code == 200
        assert rr.json()["expiry_reminders"] is True


# ---------------------- Password change ----------------------

class TestPassword:
    def test_wrong_current_400_arabic(self, pharmacy_token):
        r = requests.patch(f"{API}/me/password", headers=H(pharmacy_token),
                           json={"current_password": "WRONG_PWD", "new_password": "abc123"}, timeout=15)
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        # arabic word for "current" or "incorrect"
        assert any(ch >= "\u0600" and ch <= "\u06FF" for ch in detail), f"expected arabic detail, got: {detail}"

    def test_change_and_reset(self):
        # Login fresh (to avoid using stale token if pw already changed)
        tok = _login(PHARMACY_PHONE, PHARMACY_PASS)
        new_pw = "temp_pw_9x!"
        r = requests.patch(f"{API}/me/password", headers=H(tok),
                           json={"current_password": PHARMACY_PASS, "new_password": new_pw}, timeout=15)
        assert r.status_code == 200, r.text
        # verify login with new works
        tok2 = _login(PHARMACY_PHONE, new_pw)
        assert tok2
        # verify a system notification was created
        notifs = requests.get(f"{API}/notifications?limit=5", headers=H(tok2), timeout=15).json()
        titles = [n["title"] for n in notifs.get("items", [])]
        assert any("كلمة السر" in t for t in titles), f"no password change notification found: {titles}"
        # reset back
        rr = requests.patch(f"{API}/me/password", headers=H(tok2),
                            json={"current_password": new_pw, "new_password": PHARMACY_PASS}, timeout=15)
        assert rr.status_code == 200
        # confirm original works
        assert _login(PHARMACY_PHONE, PHARMACY_PASS)


# ---------------------- Profile ----------------------

class TestProfile:
    def test_get_profile_no_password(self, pharmacy_token):
        r = requests.get(f"{API}/me/profile", headers=H(pharmacy_token), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "password" not in j
        assert "id" in j and "role" in j

    def test_patch_profile(self, pharmacy_token):
        # capture original
        original = requests.get(f"{API}/me/profile", headers=H(pharmacy_token), timeout=15).json()
        r = requests.patch(f"{API}/me/profile", headers=H(pharmacy_token),
                           json={"name": original.get("name", "صيدلية الشفاء")}, timeout=15)
        assert r.status_code == 200


# ---------------------- Admin panel ----------------------

class TestAdminPanel:
    def test_pharmacy_cannot_send(self, pharmacy_token):
        r = requests.post(f"{API}/admin/notifications/send", headers=H(pharmacy_token),
                          json={"title": "x", "body": "y", "audience_mode": "all"}, timeout=15)
        assert r.status_code == 403

    def test_audience_summary(self, admin_token):
        r = requests.get(f"{API}/admin/notifications/audience-summary", headers=H(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "roles" in j and "total" in j
        assert j["roles"]["pharmacy"] >= 0

    def test_send_to_all(self, admin_token):
        r = requests.post(f"{API}/admin/notifications/send", headers=H(admin_token),
                          json={"title": "TEST_ALL", "body": "test all audience",
                                "audience_mode": "all"}, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "sent"
        assert j["failed"] == 0
        assert j["total"] == j["delivered"]
        assert j["total"] >= 1

    def test_send_to_role_pharmacy(self, admin_token):
        summary = requests.get(f"{API}/admin/notifications/audience-summary", headers=H(admin_token)).json()
        n_pharm = summary["roles"]["pharmacy"]
        r = requests.post(f"{API}/admin/notifications/send", headers=H(admin_token),
                          json={"title": "TEST_ROLE_PH", "body": "role pharm",
                                "audience_mode": "role", "role": "pharmacy"}, timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert j["total"] == n_pharm

    def test_schedule_and_run(self, admin_token):
        future = (datetime.now(timezone.utc) + timedelta(seconds=4)).isoformat()
        r = requests.post(f"{API}/admin/notifications/send", headers=H(admin_token),
                          json={"title": "TEST_SCH", "body": "sched",
                                "audience_mode": "role", "role": "pharmacy",
                                "scheduled_for": future}, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "scheduled"
        bid = j["batch_id"]
        time.sleep(7)
        hist = requests.get(f"{API}/admin/notifications/history?limit=100",
                            headers=H(admin_token), timeout=15).json()
        batch = next((b for b in hist["items"] if b["id"] == bid), None)
        assert batch is not None
        assert batch["status"] == "sent", f"expected sent, got {batch['status']}"

    def test_schedule_and_cancel(self, admin_token):
        future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
        r = requests.post(f"{API}/admin/notifications/send", headers=H(admin_token),
                          json={"title": "TEST_CANCEL", "body": "will be cancelled",
                                "audience_mode": "role", "role": "supplier",
                                "scheduled_for": future}, timeout=15)
        assert r.status_code == 200
        bid = r.json()["batch_id"]
        c = requests.delete(f"{API}/admin/notifications/scheduled/{bid}",
                            headers=H(admin_token), timeout=15)
        assert c.status_code == 200
        # cancel again → 400 (status now 'canceled', not 'scheduled')
        c2 = requests.delete(f"{API}/admin/notifications/scheduled/{bid}",
                             headers=H(admin_token), timeout=15)
        assert c2.status_code == 400

    def test_cancel_sent_batch_400(self, admin_token):
        # send now
        r = requests.post(f"{API}/admin/notifications/send", headers=H(admin_token),
                          json={"title": "TEST_NOW", "body": "already sent",
                                "audience_mode": "ids", "ids": [str(uuid.uuid4())]}, timeout=15)
        # audience_mode=ids with a random id → still creates batch, delivers 0
        assert r.status_code == 200
        bid = r.json()["batch_id"]
        c = requests.delete(f"{API}/admin/notifications/scheduled/{bid}",
                            headers=H(admin_token), timeout=15)
        assert c.status_code == 400

    def test_history_sorted(self, admin_token):
        r = requests.get(f"{API}/admin/notifications/history?limit=10",
                         headers=H(admin_token), timeout=15)
        assert r.status_code == 200
        items = r.json()["items"]
        for a, b in zip(items, items[1:]):
            assert a["created_at"] >= b["created_at"]


# ---------------------- Register push ----------------------

class TestRegisterPush:
    def test_placeholder_returns_queued(self, pharmacy_token, pharmacy_id):
        r = requests.post(f"{API}/register-push", headers=H(pharmacy_token),
                          json={"user_id": pharmacy_id, "platform": "android",
                                "device_token": "fake-token-for-test-12345"}, timeout=15)
        assert r.status_code in (200, 201), r.text
        assert r.json().get("status") == "queued"

    def test_wrong_user_id_403(self, supplier_token, pharmacy_id):
        r = requests.post(f"{API}/register-push", headers=H(supplier_token),
                          json={"user_id": pharmacy_id, "platform": "android",
                                "device_token": "fake-supplier-token"}, timeout=15)
        assert r.status_code == 403


# ---------------------- Cross-user isolation ----------------------

class TestIsolation:
    def test_supplier_cannot_read_pharmacy_notification(self, admin_token, pharmacy_token, supplier_token, pharmacy_id):
        # admin sends to pharmacy only
        rr = requests.post(f"{API}/admin/notifications/send", headers=H(admin_token),
                           json={"title": "PH_ONLY", "body": "for pharmacy",
                                 "audience_mode": "ids", "ids": [pharmacy_id]}, timeout=15)
        assert rr.status_code == 200
        # get pharmacy's latest notification id
        n = requests.get(f"{API}/notifications?limit=1", headers=H(pharmacy_token), timeout=15).json()
        assert n["count"] >= 1
        nid = n["items"][0]["id"]
        # supplier tries to mark it read → 404
        s = requests.patch(f"{API}/notifications/{nid}/read", headers=H(supplier_token), timeout=15)
        assert s.status_code == 404
        # supplier tries to delete → 404
        d = requests.delete(f"{API}/notifications/{nid}", headers=H(supplier_token), timeout=15)
        assert d.status_code == 404


# ---------------------- Expired list (pharmacy only) ----------------------

class TestExpiredList:
    def test_pharmacy_ok(self, pharmacy_token):
        r = requests.get(f"{API}/medicines/expired-list", headers=H(pharmacy_token), timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "items" in j and "count" in j

    def test_supplier_403(self, supplier_token):
        r = requests.get(f"{API}/medicines/expired-list", headers=H(supplier_token), timeout=15)
        assert r.status_code == 403


# ---------------------- Scheduler manual runs (via mongo + module) ----------------------

class TestSchedulerManual:
    """These insert medicine docs directly in Mongo then invoke module funcs."""

    @pytest.fixture(scope="class")
    def notif_module(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        import notifications as notif_mod
        return notif_mod

    def _with_fresh_db(self, notif_mod, coro_factory):
        """Create a fresh motor client bound to a new event loop, then run coro."""
        from motor.motor_asyncio import AsyncIOMotorClient
        loop = asyncio.new_event_loop()
        try:
            client = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=loop)
            db = client[os.environ["DB_NAME"]]
            # temporarily rebind module's _db
            prev = notif_mod._db
            notif_mod._db = db
            try:
                return loop.run_until_complete(coro_factory(db))
            finally:
                notif_mod._db = prev
                client.close()
        finally:
            loop.close()

    def test_daily_expiry_scan_and_dedupe(self, notif_module, pharmacy_id, pharmacy_token):
        notif_mod = notif_module

        async def _run(db):
            # insert medicine expiring in 7 days
            expiry = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
            med_id = f"TEST_MED_{uuid.uuid4()}"
            await db.medicines.insert_one({
                "id": med_id,
                "pharmacy_id": pharmacy_id,
                "name": "TEST_ExpiryMed",
                "barcode": f"TEST_{uuid.uuid4().hex[:8]}",
                "expiry_date": expiry,
                "stock": 5,
                "price": 1000,
            })
            # ensure prefs allow it
            await db.notification_preferences.update_one(
                {"user_id": pharmacy_id},
                {"$set": {"user_id": pharmacy_id, "notifications_enabled": True,
                          "expiry_reminders": True}},
                upsert=True,
            )
            # clean prior notif with same dedupe key
            await db.notifications.delete_many({"dedupe_key": f"expiry:{med_id}:7"})

            await notif_mod._daily_expiry_scan()
            count1 = await db.notifications.count_documents({"dedupe_key": f"expiry:{med_id}:7"})
            # run again → still 1 (dedupe)
            await notif_mod._daily_expiry_scan()
            count2 = await db.notifications.count_documents({"dedupe_key": f"expiry:{med_id}:7"})

            # cleanup
            await db.medicines.delete_one({"id": med_id})
            await db.notifications.delete_many({"dedupe_key": f"expiry:{med_id}:7"})
            return count1, count2, med_id

        c1, c2, med_id = self._with_fresh_db(notif_mod, _run)
        assert c1 == 1, f"expected 1 notification after first scan, got {c1}"
        assert c2 == 1, f"expected still 1 (dedupe) after second scan, got {c2}"

    def test_weekly_expired_report(self, notif_module, pharmacy_id):
        notif_mod = notif_module

        async def _run(db):
            expiry = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            med_id = f"TEST_MED_{uuid.uuid4()}"
            await db.medicines.insert_one({
                "id": med_id,
                "pharmacy_id": pharmacy_id,
                "name": "TEST_ExpiredMed",
                "barcode": f"TEST_{uuid.uuid4().hex[:8]}",
                "expiry_date": expiry,
                "stock": 3,
                "price": 500,
            })
            await db.notification_preferences.update_one(
                {"user_id": pharmacy_id},
                {"$set": {"weekly_expired_report": True, "notifications_enabled": True}},
                upsert=True,
            )
            week_key = datetime.now(timezone.utc).strftime("%Y-W%V")
            dedupe = f"expired_weekly:{pharmacy_id}:{week_key}"
            await db.notifications.delete_many({"dedupe_key": dedupe})

            await notif_mod._weekly_expired_report()
            doc = await db.notifications.find_one({"dedupe_key": dedupe}, {"_id": 0})
            # cleanup
            await db.medicines.delete_one({"id": med_id})
            await db.notifications.delete_many({"dedupe_key": dedupe})
            return doc

        doc = self._with_fresh_db(notif_mod, _run)
        assert doc is not None, "weekly expired notification not created"
        assert doc["type"] == "expired_weekly"
        assert doc["data"]["screen"] == "/medicines/expired"
