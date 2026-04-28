"""Backend API tests for Arabic Pharmacy Cashier App."""
import os
import time
import base64
import requests
import pytest
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"

PHARMACY_PHONE = "07700000001"
PHARMACY_PASSWORD = "pass123"

# Unique suffix to avoid collisions across runs
RUN = str(int(time.time()))


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def pharmacy_token(session):
    r = session.post(f"{BASE_URL}/pharmacy/login",
                     json={"phone": PHARMACY_PHONE, "password": PHARMACY_PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.text}"
    data = r.json()
    assert "token" in data and "pharmacy" in data
    return data["token"]


@pytest.fixture(scope="session")
def supplier_token(session):
    # Register a fresh supplier
    phone = f"079{RUN[-7:]}"
    payload = {"name": f"TEST_supplier_{RUN}", "phone": phone,
               "password": "sup123", "address": "Baghdad"}
    r = session.post(f"{BASE_URL}/supplier/register", json=payload)
    if r.status_code == 400:  # already exists
        r = session.post(f"{BASE_URL}/supplier/login",
                         json={"phone": phone, "password": "sup123"})
    assert r.status_code == 200, f"Supplier auth failed: {r.text}"
    return r.json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- Auth tests ----------
class TestAuth:
    def test_pharmacy_login_seeded(self, session):
        r = session.post(f"{BASE_URL}/pharmacy/login",
                         json={"phone": PHARMACY_PHONE, "password": PHARMACY_PASSWORD})
        assert r.status_code == 200
        body = r.json()
        assert body["pharmacy"]["phone"] == PHARMACY_PHONE
        assert body["token"]

    def test_pharmacy_login_wrong_pw(self, session):
        r = session.post(f"{BASE_URL}/pharmacy/login",
                         json={"phone": PHARMACY_PHONE, "password": "wrong"})
        assert r.status_code == 401

    def test_pharmacy_register_duplicate(self, session):
        r = session.post(f"{BASE_URL}/pharmacy/register",
                         json={"name": "x", "phone": PHARMACY_PHONE,
                               "password": "p", "address": "a"})
        assert r.status_code == 400

    def test_pharmacy_register_new(self, session):
        phone = f"077{RUN[-7:]}"
        r = session.post(f"{BASE_URL}/pharmacy/register",
                         json={"name": f"TEST_pharm_{RUN}", "phone": phone,
                               "password": "p123", "address": "Baghdad"})
        assert r.status_code == 200
        assert r.json()["pharmacy"]["phone"] == phone

    def test_supplier_register_login(self, supplier_token):
        assert supplier_token

    def test_me_pharmacy(self, session, pharmacy_token):
        r = session.get(f"{BASE_URL}/me", headers=auth(pharmacy_token))
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "pharmacy"
        assert body["user"]["phone"] == PHARMACY_PHONE
        assert "password" not in body["user"]

    def test_me_supplier(self, session, supplier_token):
        r = session.get(f"{BASE_URL}/me", headers=auth(supplier_token))
        assert r.status_code == 200
        assert r.json()["role"] == "supplier"

    def test_me_no_token(self, session):
        r = session.get(f"{BASE_URL}/me")
        assert r.status_code == 401


# ---------- Medicines CRUD ----------
class TestMedicines:
    created_ids = []

    def test_create_medicine(self, session, pharmacy_token):
        payload = {"name": f"TEST_Panadol_{RUN}", "barcode": f"BC{RUN}",
                   "quantity": 10, "price": 2.5}
        r = session.post(f"{BASE_URL}/medicines", json=payload, headers=auth(pharmacy_token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["name"] == payload["name"]
        assert data["quantity"] == 10
        assert data["price"] == 2.5
        assert "id" in data and "_id" not in data
        TestMedicines.created_ids.append(data["id"])

    def test_list_medicines_includes_created(self, session, pharmacy_token):
        r = session.get(f"{BASE_URL}/medicines", headers=auth(pharmacy_token))
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()]
        assert TestMedicines.created_ids[0] in ids

    def test_barcode_lookup(self, session, pharmacy_token):
        r = session.get(f"{BASE_URL}/medicines/barcode/BC{RUN}", headers=auth(pharmacy_token))
        assert r.status_code == 200
        assert r.json()["barcode"] == f"BC{RUN}"

    def test_barcode_not_found(self, session, pharmacy_token):
        r = session.get(f"{BASE_URL}/medicines/barcode/NOTEXIST_{RUN}", headers=auth(pharmacy_token))
        assert r.status_code == 404

    def test_update_medicine(self, session, pharmacy_token):
        mid = TestMedicines.created_ids[0]
        r = session.patch(f"{BASE_URL}/medicines/{mid}",
                          json={"price": 3.75}, headers=auth(pharmacy_token))
        assert r.status_code == 200
        assert r.json()["price"] == 3.75

    def test_buy_existing_increments_qty(self, session, pharmacy_token):
        # buying same barcode should increment quantity
        payload = {"name": f"TEST_Panadol_{RUN}", "barcode": f"BC{RUN}",
                   "quantity": 5, "price": 4.0}
        r = session.post(f"{BASE_URL}/medicines/buy", json=payload, headers=auth(pharmacy_token))
        assert r.status_code == 200
        data = r.json()
        assert data["quantity"] == 15  # 10 + 5
        assert data["price"] == 4.0

    def test_buy_new_creates(self, session, pharmacy_token):
        payload = {"name": f"TEST_NewMed_{RUN}", "barcode": f"NEW{RUN}",
                   "quantity": 7, "price": 1.0}
        r = session.post(f"{BASE_URL}/medicines/buy", json=payload, headers=auth(pharmacy_token))
        assert r.status_code == 200
        data = r.json()
        assert data["quantity"] == 7
        TestMedicines.created_ids.append(data["id"])

    def test_sell_deducts_qty(self, session, pharmacy_token):
        mid = TestMedicines.created_ids[0]
        r = session.post(f"{BASE_URL}/medicines/sell",
                         json={"items": [{"medicine_id": mid, "quantity": 3}]},
                         headers=auth(pharmacy_token))
        assert r.status_code == 200
        body = r.json()
        # price was updated to 4.0 then sell 3 -> total 12.0
        assert body["total"] == pytest.approx(12.0)
        # verify deducted
        r2 = session.get(f"{BASE_URL}/medicines", headers=auth(pharmacy_token))
        med = next(m for m in r2.json() if m["id"] == mid)
        assert med["quantity"] == 12  # 15 - 3

    def test_sell_insufficient(self, session, pharmacy_token):
        mid = TestMedicines.created_ids[0]
        r = session.post(f"{BASE_URL}/medicines/sell",
                         json={"items": [{"medicine_id": mid, "quantity": 9999}]},
                         headers=auth(pharmacy_token))
        assert r.status_code == 400

    def test_delete_medicine(self, session, pharmacy_token):
        for mid in TestMedicines.created_ids:
            r = session.delete(f"{BASE_URL}/medicines/{mid}", headers=auth(pharmacy_token))
            assert r.status_code == 200
        # confirm gone
        r = session.delete(f"{BASE_URL}/medicines/{TestMedicines.created_ids[0]}",
                           headers=auth(pharmacy_token))
        assert r.status_code == 404


# ---------- Orders ----------
class TestOrders:
    def test_create_and_list_order(self, session, pharmacy_token):
        payload = {"items": [{"name": "TEST_med_a", "quantity": 5},
                             {"name": "TEST_med_b", "quantity": 2}]}
        r = session.post(f"{BASE_URL}/orders", json=payload, headers=auth(pharmacy_token))
        assert r.status_code == 200
        oid = r.json()["id"]
        r2 = session.get(f"{BASE_URL}/orders", headers=auth(pharmacy_token))
        assert r2.status_code == 200
        assert oid in [o["id"] for o in r2.json()]


# ---------- Supplier products ----------
class TestSupplierProducts:
    pid = None

    def test_supplier_create_product(self, session, supplier_token):
        payload = {"name": f"TEST_prod_{RUN}", "price": 9.99,
                   "description": "test product"}
        r = session.post(f"{BASE_URL}/supplier/products", json=payload,
                         headers=auth(supplier_token))
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == payload["name"]
        assert data["supplier_name"]
        TestSupplierProducts.pid = data["id"]

    def test_supplier_list_own(self, session, supplier_token):
        r = session.get(f"{BASE_URL}/supplier/products", headers=auth(supplier_token))
        assert r.status_code == 200
        assert TestSupplierProducts.pid in [p["id"] for p in r.json()]

    def test_marketplace_visible_to_pharmacy(self, session, pharmacy_token):
        r = session.get(f"{BASE_URL}/marketplace", headers=auth(pharmacy_token))
        assert r.status_code == 200
        assert TestSupplierProducts.pid in [p["id"] for p in r.json()]

    def test_marketplace_visible_to_supplier(self, session, supplier_token):
        r = session.get(f"{BASE_URL}/marketplace", headers=auth(supplier_token))
        assert r.status_code == 200

    def test_supplier_delete_product(self, session, supplier_token):
        r = session.delete(f"{BASE_URL}/supplier/products/{TestSupplierProducts.pid}",
                           headers=auth(supplier_token))
        assert r.status_code == 200


# ---------- Role enforcement ----------
class TestRoleEnforcement:
    def test_supplier_cannot_list_medicines(self, session, supplier_token):
        r = session.get(f"{BASE_URL}/medicines", headers=auth(supplier_token))
        assert r.status_code == 403

    def test_supplier_cannot_create_order(self, session, supplier_token):
        r = session.post(f"{BASE_URL}/orders", json={"items": []},
                         headers=auth(supplier_token))
        assert r.status_code == 403

    def test_pharmacy_cannot_add_supplier_product(self, session, pharmacy_token):
        r = session.post(f"{BASE_URL}/supplier/products",
                         json={"name": "x", "price": 1.0},
                         headers=auth(pharmacy_token))
        assert r.status_code == 403

    def test_pharmacy_cannot_list_supplier_products(self, session, pharmacy_token):
        r = session.get(f"{BASE_URL}/supplier/products", headers=auth(pharmacy_token))
        assert r.status_code == 403


# ---------- AI Identify (best effort) ----------
class TestIdentify:
    def test_identify_returns_response(self, session, pharmacy_token):
        # 1x1 PNG (red pixel) - smallest valid base64 image
        tiny_png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
                    "IQAAAABJRU5ErkJggg==")
        try:
            r = session.post(f"{BASE_URL}/medicines/identify",
                             json={"image_base64": tiny_png},
                             headers=auth(pharmacy_token), timeout=60)
        except requests.Timeout:
            pytest.skip("LLM call timed out")
        # Accept 200 (success) or 500 (LLM error) - just verify endpoint exists & reachable
        assert r.status_code in (200, 500), f"Unexpected status: {r.status_code} {r.text}"
        if r.status_code == 200:
            assert "name" in r.json()
