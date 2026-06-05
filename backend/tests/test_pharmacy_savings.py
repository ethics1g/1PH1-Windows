"""Backend tests for the Pharmacy Cumulative Savings feature.

Covers:
- GET /api/pharmacy/savings auth & role enforcement, response shape
- POST /api/orders/optimize/commit accepts savings_estimate_total + savings_per_group
- Order lifecycle (accept -> processing -> delivered -> confirm-receipt) credits
  pharmacies.cumulative_savings ONCE via savings_credited flag
- Auto-complete path (delivered + 72h) credits exactly once
- Backward compatibility: commit without savings -> orders with savings_estimate=0,
  completion does NOT change cumulative_savings
- Idempotency, role enforcement, anti-circumvention regression
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

RUN = str(int(time.time()))


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
    # If supplier flagged disabled by previous test run, re-enable
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
    if r.status_code != 200 and "disabled" in r.text.lower():
        mongo.suppliers.update_one({"phone": SUPPLIER_PHONE}, {"$set": {"disabled": False}})
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


# ------------------------- helpers -------------------------

def _login_supplier_token(session, token):
    """Just unpack tuple supplier_token fixture"""
    return token[0], token[1]


def _make_commit_payload(supplier_id, supplier_name, total=1000.0,
                        savings_total=None, savings_per_group=None):
    items = [{"name": f"TEST_SAVITEM_{RUN}_{uuid.uuid4().hex[:6]}",
              "quantity": 1, "unit_price": total}]
    payload = {
        "commit_id": f"TEST_COMMIT_{uuid.uuid4().hex}",
        "groups": [{
            "supplier_id": supplier_id,
            "supplier_name": supplier_name,
            "items": items,
            "total": total,
        }],
    }
    if savings_total is not None:
        payload["savings_estimate_total"] = savings_total
    if savings_per_group is not None:
        payload["savings_per_group"] = savings_per_group
    return payload


def _walk_to_delivered(session, supplier_token, order_id):
    """Take an order from pending -> accepted -> processing -> delivered."""
    h = auth(supplier_token)
    for path in ("accept", "processing", "delivered"):
        r = session.patch(f"{BASE_URL}/supplier/orders/{order_id}/{path}", headers=h)
        assert r.status_code == 200, f"{path} failed: {r.text}"


def _get_pharmacy_cum(session, pharmacy_token):
    r = session.get(f"{BASE_URL}/pharmacy/savings", headers=auth(pharmacy_token))
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------- tests -------------------------

class TestSavingsEndpointAuth:
    """GET /api/pharmacy/savings auth & role enforcement"""

    def test_unauthenticated_returns_401_or_403(self, session):
        r = session.get(f"{BASE_URL}/pharmacy/savings")
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text}"

    def test_supplier_role_forbidden(self, session, supplier_token):
        tok, _ = supplier_token
        r = session.get(f"{BASE_URL}/pharmacy/savings", headers=auth(tok))
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"

    def test_pharmacy_response_shape(self, session, pharmacy_token):
        r = session.get(f"{BASE_URL}/pharmacy/savings", headers=auth(pharmacy_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "cumulative_savings" in body
        assert "updated_at" in body
        assert "completed_orders" in body
        assert isinstance(body["cumulative_savings"], (int, float))
        assert isinstance(body["completed_orders"], int)


class TestCommitWithSavings:
    """POST /api/orders/optimize/commit accepts savings_* fields"""

    def test_commit_stores_savings_per_order(self, session, pharmacy_token,
                                              supplier_token, mongo):
        sup_tok, sup_id = supplier_token
        payload = _make_commit_payload(sup_id, "مذخر النور",
                                       total=1000.0,
                                       savings_total=200.0,
                                       savings_per_group=[200.0])
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=payload, headers=auth(pharmacy_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["created"] == 1
        order_id = body["orders"][0]["id"]
        # Verify DB
        doc = mongo.orders.find_one({"id": order_id})
        assert doc is not None
        assert doc["savings_estimate"] == pytest.approx(200.0)
        assert doc["savings_credited"] is False
        # Cleanup
        mongo.orders.delete_one({"id": order_id})

    def test_commit_distributes_savings_proportional_when_per_group_missing(
            self, session, pharmacy_token, supplier_token, mongo):
        sup_tok, sup_id = supplier_token
        payload = {
            "commit_id": f"TEST_COMMIT_{uuid.uuid4().hex}",
            "groups": [
                {"supplier_id": sup_id, "supplier_name": "X",
                 "items": [{"name": f"TS_{uuid.uuid4().hex[:6]}",
                            "quantity": 1, "unit_price": 600}], "total": 600.0},
                {"supplier_id": sup_id, "supplier_name": "X",
                 "items": [{"name": f"TS_{uuid.uuid4().hex[:6]}",
                            "quantity": 1, "unit_price": 400}], "total": 400.0},
            ],
            "savings_estimate_total": 100.0,
        }
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=payload, headers=auth(pharmacy_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created"] == 2
        # 60/40 distribution of 100 = 60 / 40
        ids = [o["id"] for o in body["orders"]]
        docs = list(mongo.orders.find({"id": {"$in": ids}}))
        savings_by_total = {d["total"]: d["savings_estimate"] for d in docs}
        assert savings_by_total[600.0] == pytest.approx(60.0, abs=0.01)
        assert savings_by_total[400.0] == pytest.approx(40.0, abs=0.01)
        mongo.orders.delete_many({"id": {"$in": ids}})

    def test_commit_without_savings_backward_compat(self, session, pharmacy_token,
                                                     supplier_token, mongo):
        sup_tok, sup_id = supplier_token
        payload = _make_commit_payload(sup_id, "مذخر النور", total=500.0)
        # NOTE: no savings_* fields
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=payload, headers=auth(pharmacy_token))
        assert r.status_code == 200, r.text
        order_id = r.json()["orders"][0]["id"]
        doc = mongo.orders.find_one({"id": order_id})
        assert doc["savings_estimate"] == 0.0
        assert doc["savings_credited"] is False
        mongo.orders.delete_one({"id": order_id})

    def test_commit_idempotency_same_commit_id(self, session, pharmacy_token,
                                                supplier_token, mongo):
        sup_tok, sup_id = supplier_token
        cid = f"TEST_IDEM_{uuid.uuid4().hex}"
        payload = _make_commit_payload(sup_id, "مذخر النور", total=300.0,
                                       savings_total=30.0, savings_per_group=[30.0])
        payload["commit_id"] = cid
        r1 = session.post(f"{BASE_URL}/orders/optimize/commit",
                          json=payload, headers=auth(pharmacy_token))
        assert r1.status_code == 200
        # Second call must be idempotent (no new order)
        r2 = session.post(f"{BASE_URL}/orders/optimize/commit",
                          json=payload, headers=auth(pharmacy_token))
        assert r2.status_code == 200
        assert r2.json().get("status") == "already_committed"
        count = mongo.orders.count_documents({"commit_id": cid})
        assert count == 1
        mongo.orders.delete_many({"commit_id": cid})


class TestManualCompletionCreditsSavings:
    """Full lifecycle: confirm-receipt credits pharmacies.cumulative_savings exactly once."""

    def test_manual_completion_credits_once(self, session, pharmacy_token,
                                             supplier_token, mongo, pharmacy_id):
        sup_tok, sup_id = supplier_token
        before = _get_pharmacy_cum(session, pharmacy_token)
        before_cum = before["cumulative_savings"]
        before_completed = before["completed_orders"]

        # Commit order with savings=123.45
        payload = _make_commit_payload(sup_id, "مذخر النور", total=2000.0,
                                       savings_total=123.45,
                                       savings_per_group=[123.45])
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=payload, headers=auth(pharmacy_token))
        assert r.status_code == 200, r.text
        order_id = r.json()["orders"][0]["id"]

        # Supplier walks order to delivered
        _walk_to_delivered(session, sup_tok, order_id)

        # Pharmacy confirms receipt
        r2 = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/confirm-receipt",
                           headers=auth(pharmacy_token))
        assert r2.status_code == 200, r2.text

        # Verify pharmacy cumulative_savings increased by exactly 123.45
        after = _get_pharmacy_cum(session, pharmacy_token)
        delta = round(after["cumulative_savings"] - before_cum, 2)
        assert delta == pytest.approx(123.45, abs=0.01), \
            f"expected +123.45, got {delta} (before={before_cum}, after={after['cumulative_savings']})"
        assert after["completed_orders"] == before_completed + 1
        assert after["updated_at"] is not None

        # Verify savings_credited flag set on the order
        doc = mongo.orders.find_one({"id": order_id})
        assert doc["savings_credited"] is True
        assert doc["status"] == "completed"

        # Second confirm-receipt MUST be 400 (lifecycle) and must NOT double-credit
        r3 = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/confirm-receipt",
                           headers=auth(pharmacy_token))
        assert r3.status_code == 400, f"expected 400 on second confirm, got {r3.status_code}: {r3.text}"
        after2 = _get_pharmacy_cum(session, pharmacy_token)
        assert after2["cumulative_savings"] == after["cumulative_savings"], \
            "savings double-credited on second confirm-receipt!"

        # Cleanup
        mongo.orders.delete_one({"id": order_id})
        mongo.supplier_sales.delete_many({"order_id": order_id})

    def test_completion_without_savings_no_increment(self, session, pharmacy_token,
                                                      supplier_token, mongo):
        """Backward compat: order with savings_estimate=0 must NOT change cumulative."""
        sup_tok, sup_id = supplier_token
        before = _get_pharmacy_cum(session, pharmacy_token)["cumulative_savings"]

        payload = _make_commit_payload(sup_id, "مذخر النور", total=500.0)
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=payload, headers=auth(pharmacy_token))
        order_id = r.json()["orders"][0]["id"]
        _walk_to_delivered(session, sup_tok, order_id)
        r2 = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/confirm-receipt",
                           headers=auth(pharmacy_token))
        assert r2.status_code == 200

        after = _get_pharmacy_cum(session, pharmacy_token)["cumulative_savings"]
        assert after == before, f"cumulative changed for zero-savings order ({before} -> {after})"

        mongo.orders.delete_one({"id": order_id})
        mongo.supplier_sales.delete_many({"order_id": order_id})


class TestAutoCompletionCreditsSavings:
    """Auto-complete path: delivered + >72h triggers completion on next supplier list."""

    def test_auto_complete_credits_once(self, session, pharmacy_token,
                                         supplier_token, mongo):
        sup_tok, sup_id = supplier_token
        before = _get_pharmacy_cum(session, pharmacy_token)["cumulative_savings"]

        payload = _make_commit_payload(sup_id, "مذخر النور", total=1500.0,
                                       savings_total=77.0, savings_per_group=[77.0])
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=payload, headers=auth(pharmacy_token))
        assert r.status_code == 200, r.text
        order_id = r.json()["orders"][0]["id"]
        _walk_to_delivered(session, sup_tok, order_id)

        # Backdate delivered_at to 80h ago
        backdate = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
        mongo.orders.update_one({"id": order_id}, {"$set": {"delivered_at": backdate}})

        # Hit GET /api/supplier/orders to trigger auto-complete
        r2 = session.get(f"{BASE_URL}/supplier/orders", headers=auth(sup_tok))
        assert r2.status_code == 200

        # Verify auto-completion
        doc = mongo.orders.find_one({"id": order_id})
        assert doc["status"] == "completed", f"auto-complete failed, status={doc['status']}"
        assert doc.get("auto_completed") is True
        assert doc["savings_credited"] is True

        # Verify cumulative incremented by exactly 77
        after = _get_pharmacy_cum(session, pharmacy_token)["cumulative_savings"]
        delta = round(after - before, 2)
        assert delta == pytest.approx(77.0, abs=0.01), \
            f"expected +77, got {delta}"

        # Trigger auto-complete a second time (re-run query) — must not re-credit
        session.get(f"{BASE_URL}/supplier/orders", headers=auth(sup_tok))
        after2 = _get_pharmacy_cum(session, pharmacy_token)["cumulative_savings"]
        assert after2 == after, "auto-complete double-credited!"

        mongo.orders.delete_one({"id": order_id})
        mongo.supplier_sales.delete_many({"order_id": order_id})


class TestLifecycleRoleAndRegression:
    """Regression: lifecycle endpoints role + state enforcement still work."""

    def test_pharmacy_cannot_accept_order(self, session, pharmacy_token, supplier_token):
        sup_tok, sup_id = supplier_token
        payload = _make_commit_payload(sup_id, "مذخر النور", total=100.0,
                                       savings_total=5.0, savings_per_group=[5.0])
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=payload, headers=auth(pharmacy_token))
        order_id = r.json()["orders"][0]["id"]
        # Pharmacy attempts supplier accept -> 403
        r2 = session.patch(f"{BASE_URL}/supplier/orders/{order_id}/accept",
                           headers=auth(pharmacy_token))
        assert r2.status_code == 403, f"expected 403, got {r2.status_code}: {r2.text}"
        # Cleanup: have supplier reject + delete
        session.patch(f"{BASE_URL}/supplier/orders/{order_id}/reject",
                      headers=auth(sup_tok), json={"reason": "test cleanup"})

    def test_supplier_cannot_confirm_receipt(self, session, pharmacy_token, supplier_token):
        sup_tok, sup_id = supplier_token
        payload = _make_commit_payload(sup_id, "مذخر النور", total=100.0)
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=payload, headers=auth(pharmacy_token))
        order_id = r.json()["orders"][0]["id"]
        _walk_to_delivered(session, sup_tok, order_id)
        r2 = session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/confirm-receipt",
                           headers=auth(sup_tok))
        assert r2.status_code == 403
        # Cleanup via pharmacy
        session.patch(f"{BASE_URL}/pharmacy/orders/{order_id}/confirm-receipt",
                      headers=auth(pharmacy_token))

    def test_pending_order_redacts_pharmacy_info(self, session, pharmacy_token, supplier_token):
        sup_tok, sup_id = supplier_token
        payload = _make_commit_payload(sup_id, "مذخر النور", total=100.0)
        r = session.post(f"{BASE_URL}/orders/optimize/commit",
                         json=payload, headers=auth(pharmacy_token))
        order_id = r.json()["orders"][0]["id"]
        r2 = session.get(f"{BASE_URL}/supplier/orders?status=pending", headers=auth(sup_tok))
        assert r2.status_code == 200
        rows = [o for o in r2.json() if o["id"] == order_id]
        assert rows, "freshly committed order not visible to supplier"
        o = rows[0]
        assert o["pharmacy_name"] is None
        assert o["pharmacy_phone"] is None
        assert o["pharmacy_address"] is None
        # Cleanup
        session.patch(f"{BASE_URL}/supplier/orders/{order_id}/reject",
                      headers=auth(sup_tok), json={"reason": "cleanup"})
