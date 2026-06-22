"""Backend tests for the Mandatory Receipt Confirmation feature.

Covers:
- PATCH /api/pharmacy/orders/{id}/reject-receipt (new endpoint)
    * 404 when missing
    * 403 when not owner
    * 400 when wrong status
    * 200 delivered -> not_received, no commission, no savings credit
- POST /api/orders/optimize/commit pending-receipt enforcement
    * 0 delivered -> 200
    * 1 delivered -> 200 (still allowed)
    * 2 delivered -> 409 with Arabic message containing keywords
- Re-allowed once one of the 2 delivered orders is processed (confirm OR reject)
- not_received is TERMINAL: supplier lifecycle endpoints return 400
- Auto-complete (_maybe_auto_complete_delivered) does NOT touch not_received
- Backward compatibility: confirm-receipt still credits commission + savings once
"""
import os
import time
import uuid
import requests
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

PHARMACY_PHONE = "07700000001"
PHARMACY_PASSWORD = "pass123"
SUPPLIER_PHONE = "07811111111"
SUPPLIER_PASSWORD = "sup1"

RUN = uuid.uuid4().hex[:8]


def auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ------------------------- fixtures -------------------------

@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL)
    db = client[DB_NAME]
    db.suppliers.update_one({"phone": SUPPLIER_PHONE}, {"$set": {"disabled": False}})
    yield db
    client.close()


@pytest.fixture(scope="module")
def pharmacy_token(session, mongo):
    r = session.post(f"{BASE_URL}/pharmacy/login",
                     json={"phone": PHARMACY_PHONE, "password": PHARMACY_PASSWORD})
    assert r.status_code == 200, f"Pharmacy login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def supplier_token(session, mongo):
    r = session.post(f"{BASE_URL}/supplier/login",
                     json={"phone": SUPPLIER_PHONE, "password": SUPPLIER_PASSWORD})
    assert r.status_code == 200, f"Supplier login failed: {r.text}"
    body = r.json()
    return body["token"], body["supplier"]["id"]


@pytest.fixture(scope="module")
def pharmacy_id(mongo):
    p = mongo.pharmacies.find_one({"phone": PHARMACY_PHONE}, {"id": 1})
    assert p, "Seed pharmacy not found"
    return p["id"]


@pytest.fixture(autouse=True)
def _isolate_pharmacy_state(mongo, pharmacy_id):
    """Before/after each test, force-resolve any pre-existing 'delivered' orders
    for the seeded pharmacy so the pending-receipt counter starts clean."""
    mongo.orders.update_many(
        {"pharmacy_id": pharmacy_id, "status": "delivered"},
        {"$set": {"status": "completed",
                  "completed_at": datetime.now(timezone.utc).isoformat(),
                  "auto_completed": False}},
    )
    yield
    # Cleanup: remove any TEST_ orders this run touched
    mongo.orders.delete_many({"pharmacy_id": pharmacy_id,
                              "commit_id": {"$regex": f"^TEST_{RUN}_"}})


# ------------------------- helpers -------------------------

def _commit_payload(supplier_id, supplier_name, total=500.0, savings_total=0.0):
    return {
        "commit_id": f"TEST_{RUN}_{uuid.uuid4().hex}",
        "groups": [{
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "items": [{"name": f"TEST_RX_{RUN}_{uuid.uuid4().hex[:6]}",
                       "quantity": 1, "unit_price": total}],
            "total": total,
        }],
        "savings_estimate_total": savings_total,
        "savings_per_group": [savings_total],
    }


def _create_delivered_order(session, pharmacy_token, supplier_tok, supplier_id,
                             supplier_name, total=500.0, savings=0.0):
    payload = _commit_payload(supplier_id, supplier_name, total=total, savings_total=savings)
    r = session.post(f"{BASE_URL}/orders/optimize/commit",
                     json=payload, headers=auth(pharmacy_token))
    assert r.status_code == 200, f"commit failed: {r.status_code} {r.text}"
    order_id = r.json()["orders"][0]["id"]
    h = auth(supplier_tok)
    for action in ("accept", "processing", "delivered"):
        rr = session.patch(f"{BASE_URL}/supplier/orders/{order_id}/{action}", headers=h)
        assert rr.status_code == 200, f"{action} failed: {rr.text}"
    return order_id


# ------------------------- TESTS: reject-receipt endpoint -------------------------

class TestRejectReceiptEndpoint:
    """PATCH /api/pharmacy/orders/{id}/reject-receipt"""

    def test_404_when_order_missing(self, session, pharmacy_token):
        r = session.patch(f"{BASE_URL}/pharmacy/orders/nonexistent-{uuid.uuid4().hex}/reject-receipt",
                          headers=auth(pharmacy_token), json={})
        assert r.status_code == 404
        assert "غير موجودة" in r.text

    def test_403_when_not_owner(self, session, supplier_token, mongo, pharmacy_id):
        # Insert order owned by a DIFFERENT pharmacy
        other_id = f"other-pharm-{RUN}"
        fake_order_id = f"TEST_OTHER_{RUN}_{uuid.uuid4().hex}"
        sup_tok, sup_id = supplier_token
        mongo.orders.insert_one({
            "id": fake_order_id,
            "pharmacy_id": other_id,
            "supplier_id": sup_id,
            "status": "delivered",
            "total": 1.0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "delivered_at": datetime.now(timezone.utc).isoformat(),
        })
        # Login as seeded pharmacy and attempt to reject
        r = session.post(f"{BASE_URL}/pharmacy/login",
                         json={"phone": PHARMACY_PHONE, "password": PHARMACY_PASSWORD})
        tok = r.json()["token"]
        r2 = session.patch(f"{BASE_URL}/pharmacy/orders/{fake_order_id}/reject-receipt",
                           headers=auth(tok), json={})
        assert r2.status_code == 403, r2.text
        mongo.orders.delete_one({"id": fake_order_id})

    def test_400_wrong_status(self, session, pharmacy_token, supplier_token):
        sup_tok, sup_id = supplier_token
        payload = _commit_payload(sup_id, "مذخر النور", total=100.0)
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=payload, headers=auth(pharmacy_token))
        assert r.status_code == 200
        order_id = r.json()["orders"][0]["id"]
        # Order is 'pending' - rejecting should 400
        r2 = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/reject-receipt",
                           headers=auth(pharmacy_token), json={})
        assert r2.status_code == 400, r2.text
        assert "الحالة" in r2.text
        # cleanup
        session.patch(f"{BASE_URL}/supplier/orders/{order_id}/reject",
                      headers=auth(sup_tok), json={"reason": "cleanup"})

    def test_role_required(self, session, supplier_token):
        sup_tok, _ = supplier_token
        r = session.patch(f"{BASE_URL}/pharmacy/orders/anything/reject-receipt",
                          headers=auth(sup_tok), json={})
        assert r.status_code in (401, 403)

    def test_reject_success_delivered_to_not_received(self, session, pharmacy_token,
                                                       supplier_token, mongo, pharmacy_id):
        sup_tok, sup_id = supplier_token
        order_id = _create_delivered_order(session, pharmacy_token, sup_tok, sup_id,
                                            "مذخر النور", total=300.0, savings=10.0)
        # Record pharmacy cumulative_savings & commission count BEFORE
        cum_before = mongo.pharmacies.find_one({"id": pharmacy_id}, {"_id": 0,
                                                "cumulative_savings": 1}) or {}
        com_before = mongo.supplier_sales.count_documents({"order_id": order_id})

        r = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/reject-receipt",
                          headers=auth(pharmacy_token),
                          json={"reason": "السائق لم يصل"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["order_status"] == "not_received"

        # Verify db state via GET
        r2 = session.get(f"{BASE_URL}/pharmacy/orders?status=not_received",
                         headers=auth(pharmacy_token))
        assert r2.status_code == 200
        rows = [o for o in r2.json() if o["id"] == order_id]
        assert rows, "not_received order not in list"
        o = rows[0]
        assert o["status"] == "not_received"
        assert o.get("not_received_at")
        assert o.get("not_received_reason") == "السائق لم يصل"

        # No commission created, no savings credit
        com_after = mongo.supplier_sales.count_documents({"order_id": order_id})
        assert com_after == com_before, "commission should NOT be created on reject"
        cum_after = mongo.pharmacies.find_one({"id": pharmacy_id}, {"_id": 0,
                                               "cumulative_savings": 1}) or {}
        assert float(cum_after.get("cumulative_savings") or 0) == \
               float(cum_before.get("cumulative_savings") or 0), \
               "cumulative_savings must NOT be credited on reject"

    def test_reject_without_body(self, session, pharmacy_token, supplier_token):
        """Body is optional (RejectReceiptIn is Optional)."""
        sup_tok, sup_id = supplier_token
        order_id = _create_delivered_order(session, pharmacy_token, sup_tok, sup_id,
                                            "مذخر النور", total=100.0)
        r = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/reject-receipt",
                          headers=auth(pharmacy_token))
        assert r.status_code == 200, r.text


# ------------------------- TESTS: commit_order pending-receipt enforcement ----

class TestCommitPendingEnforcement:
    """POST /api/orders/optimize/commit must 409 when >=2 delivered orders pending."""

    def test_zero_pending_allowed(self, session, pharmacy_token, supplier_token):
        sup_tok, sup_id = supplier_token
        payload = _commit_payload(sup_id, "مذخر النور", total=50.0)
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=payload, headers=auth(pharmacy_token))
        assert r.status_code == 200, r.text
        # cleanup
        oid = r.json()["orders"][0]["id"]
        session.patch(f"{BASE_URL}/supplier/orders/{oid}/reject",
                      headers=auth(sup_tok), json={"reason": "cleanup"})

    def test_one_pending_still_allowed(self, session, pharmacy_token, supplier_token):
        sup_tok, sup_id = supplier_token
        # Create 1 delivered order
        d1 = _create_delivered_order(session, pharmacy_token, sup_tok, sup_id, "مذخر النور",
                                      total=120.0)
        # Now commit a new one — should still succeed (1 < 2)
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=_commit_payload(sup_id, "مذخر النور", total=70.0),
                         headers=auth(pharmacy_token))
        assert r.status_code == 200, f"1 pending should be allowed: {r.status_code} {r.text}"

    def test_two_pending_blocks_with_409(self, session, pharmacy_token, supplier_token):
        sup_tok, sup_id = supplier_token
        # Create 2 delivered orders
        _create_delivered_order(session, pharmacy_token, sup_tok, sup_id, "مذخر النور",
                                 total=80.0)
        _create_delivered_order(session, pharmacy_token, sup_tok, sup_id, "مذخر النور",
                                 total=90.0)
        # Attempt to commit -> 409
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=_commit_payload(sup_id, "مذخر النور", total=100.0),
                         headers=auth(pharmacy_token))
        assert r.status_code == 409, f"expected 409, got {r.status_code} {r.text}"
        detail = r.json().get("detail") or ""
        # Educational Arabic message contains key phrases
        assert "طلباتي" in detail, f"missing 'طلباتي' in detail: {detail}"
        assert "تأكيد الاستلام" in detail, f"missing 'تأكيد الاستلام' in detail: {detail}"
        assert "لم أستلم الطلبية" in detail, f"missing 'لم أستلم الطلبية': {detail}"

    def test_recovers_after_confirm_receipt(self, session, pharmacy_token, supplier_token):
        sup_tok, sup_id = supplier_token
        d1 = _create_delivered_order(session, pharmacy_token, sup_tok, sup_id, "مذخر النور",
                                      total=200.0, savings=15.0)
        d2 = _create_delivered_order(session, pharmacy_token, sup_tok, sup_id, "مذخر النور",
                                      total=210.0)
        # Confirm receipt on first -> pending count drops to 1
        r0 = session.patch(f"{BASE_URL}/pharmacy/orders/{d1}/confirm-receipt",
                           headers=auth(pharmacy_token))
        assert r0.status_code == 200, r0.text
        # Now commit should be allowed
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=_commit_payload(sup_id, "مذخر النور", total=50.0),
                         headers=auth(pharmacy_token))
        assert r.status_code == 200, f"after confirm-receipt, commit should pass: {r.status_code} {r.text}"

    def test_recovers_after_reject_receipt(self, session, pharmacy_token, supplier_token):
        sup_tok, sup_id = supplier_token
        d1 = _create_delivered_order(session, pharmacy_token, sup_tok, sup_id, "مذخر النور",
                                      total=160.0)
        d2 = _create_delivered_order(session, pharmacy_token, sup_tok, sup_id, "مذخر النور",
                                      total=170.0)
        # Reject the first one -> drops to 1
        r0 = session.patch(f"{BASE_URL}/pharmacy/orders/{d1}/reject-receipt",
                           headers=auth(pharmacy_token), json={"reason": "test"})
        assert r0.status_code == 200, r0.text
        # commit allowed
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=_commit_payload(sup_id, "مذخر النور", total=55.0),
                         headers=auth(pharmacy_token))
        assert r.status_code == 200, f"after reject-receipt, commit should pass: {r.text}"


# ------------------------- TESTS: not_received is terminal ----------------------

class TestNotReceivedTerminal:
    """Supplier lifecycle endpoints must 400 on not_received; auto-complete skips it."""

    def test_supplier_endpoints_400_on_not_received(self, session, pharmacy_token,
                                                     supplier_token):
        sup_tok, sup_id = supplier_token
        order_id = _create_delivered_order(session, pharmacy_token, sup_tok, sup_id,
                                            "مذخر النور", total=300.0)
        r = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/reject-receipt",
                          headers=auth(pharmacy_token), json={"reason": "x"})
        assert r.status_code == 200
        h = auth(sup_tok)
        # delivered/processing/accept/reject all should 400 because status is not_received
        for action in ("accept", "processing", "delivered"):
            rr = session.patch(f"{BASE_URL}/supplier/orders/{order_id}/{action}", headers=h)
            assert rr.status_code == 400, f"{action} on not_received should 400, got {rr.status_code} {rr.text}"
        rr = session.patch(f"{BASE_URL}/supplier/orders/{order_id}/reject",
                            headers=h, json={"reason": "x"})
        assert rr.status_code == 400, f"reject on not_received should 400, got {rr.status_code}"

    def test_confirm_receipt_400_on_not_received(self, session, pharmacy_token,
                                                  supplier_token):
        sup_tok, sup_id = supplier_token
        order_id = _create_delivered_order(session, pharmacy_token, sup_tok, sup_id,
                                            "مذخر النور", total=100.0)
        # reject first
        r = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/reject-receipt",
                          headers=auth(pharmacy_token), json={})
        assert r.status_code == 200
        # confirm-receipt should now 400
        r2 = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/confirm-receipt",
                           headers=auth(pharmacy_token))
        assert r2.status_code == 400

    def test_auto_complete_does_not_touch_not_received(self, session, pharmacy_token,
                                                       supplier_token, mongo, pharmacy_id):
        sup_tok, sup_id = supplier_token
        order_id = _create_delivered_order(session, pharmacy_token, sup_tok, sup_id,
                                            "مذخر النور", total=400.0, savings=20.0)
        # mark as not_received via reject-receipt
        r = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/reject-receipt",
                          headers=auth(pharmacy_token), json={})
        assert r.status_code == 200
        # Backdate not_received_at AND delivered_at to >80h ago
        past = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
        mongo.orders.update_one({"id": order_id},
                                 {"$set": {"delivered_at": past,
                                            "not_received_at": past}})
        # Triggering the GET runs _maybe_auto_complete_delivered
        r2 = session.get(f"{BASE_URL}/pharmacy/orders?status=not_received",
                         headers=auth(pharmacy_token))
        assert r2.status_code == 200
        order = next((o for o in r2.json() if o["id"] == order_id), None)
        assert order, "order should still exist"
        assert order["status"] == "not_received", \
            f"auto-complete must NOT touch not_received, status={order['status']}"


# ------------------------- TESTS: confirm-receipt backward compat ----------------

class TestConfirmReceiptRegression:
    """Ensure confirm-receipt commission + savings credit still works once."""

    def test_confirm_credits_commission_and_savings_once(self, session, pharmacy_token,
                                                          supplier_token, mongo,
                                                          pharmacy_id):
        sup_tok, sup_id = supplier_token
        savings_amt = 17.0
        order_id = _create_delivered_order(session, pharmacy_token, sup_tok, sup_id,
                                            "مذخر النور", total=500.0,
                                            savings=savings_amt)
        cum_before = float((mongo.pharmacies.find_one({"id": pharmacy_id},
                            {"_id": 0, "cumulative_savings": 1})
                            or {}).get("cumulative_savings") or 0)
        r = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/confirm-receipt",
                          headers=auth(pharmacy_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["order_status"] == "completed"
        assert body.get("commission_amount") and body["commission_amount"] > 0
        # savings credited
        cum_after = float((mongo.pharmacies.find_one({"id": pharmacy_id},
                            {"_id": 0, "cumulative_savings": 1})
                            or {}).get("cumulative_savings") or 0)
        assert abs(cum_after - (cum_before + savings_amt)) < 0.01, \
            f"cum_before={cum_before}, cum_after={cum_after}, expected delta={savings_amt}"
        # Re-confirm should 400 (not completed double-credit)
        r2 = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/confirm-receipt",
                           headers=auth(pharmacy_token))
        assert r2.status_code == 400, f"double confirm should 400, got {r2.status_code}"
        cum_after2 = float((mongo.pharmacies.find_one({"id": pharmacy_id},
                            {"_id": 0, "cumulative_savings": 1})
                            or {}).get("cumulative_savings") or 0)
        assert abs(cum_after2 - cum_after) < 0.01, "double credit happened"


# ------------------------- TESTS: cleanup safety ----------------------

class TestRegressionRoles:
    def test_pharmacy_role_required_on_reject(self, session, supplier_token):
        sup_tok, _ = supplier_token
        r = session.patch(f"{BASE_URL}/pharmacy/orders/anything/reject-receipt",
                          headers=auth(sup_tok), json={})
        assert r.status_code in (401, 403)
