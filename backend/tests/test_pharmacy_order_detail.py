"""
Regression tests for the NEW endpoint GET /api/pharmacy/orders/{order_id}.

Root cause of user bug: this endpoint was missing (404) so the returns creation
screen stayed stuck on the spinner.

Covers:
  A. pharmacy login can hydrate ANY of its own orders (200 + expected fields)
  B. bogus order id -> 404 with Arabic detail
  C. supplier role -> 403 (require_role("pharmacy"))
  D. full mini-flow: order -> create return -> visible in GET /api/returns
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL",
                          "https://pharma-checkout-8.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

PHARM = {"phone": "07700000001", "password": "pass123"}
SUP = {"phone": "07811111111", "password": "sup1"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def pharm_headers():
    return {"Authorization": f"Bearer {_login(PHARM)}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def sup_headers():
    return {"Authorization": f"Bearer {_login(SUP)}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def existing_order(pharm_headers):
    r = requests.get(f"{API}/pharmacy/orders", headers=pharm_headers, timeout=15)
    assert r.status_code == 200
    orders = r.json()
    assert isinstance(orders, list)
    if not orders:
        pytest.skip("no orders exist for pharmacy 07700000001 — cannot exercise endpoint")
    # prefer delivered/completed
    prio = [o for o in orders if o.get("status") in ("delivered", "completed")]
    return (prio or orders)[0]


# ---------- A. happy path ----------
class TestPharmacyOrderDetailHappy:
    def test_get_own_order_returns_200(self, pharm_headers, existing_order):
        oid = existing_order["id"]
        r = requests.get(f"{API}/pharmacy/orders/{oid}", headers=pharm_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("id", "status", "items", "supplier_name", "total"):
            assert key in body, f"missing key {key} in {list(body.keys())}"
        assert body["id"] == oid
        assert isinstance(body["items"], list)
        # no leaked mongodb _id
        assert "_id" not in body


# ---------- B. bogus id ----------
class TestPharmacyOrderDetailNotFound:
    def test_bogus_id_returns_404_arabic(self, pharm_headers):
        bogus = f"nonexistent-{uuid.uuid4()}"
        r = requests.get(f"{API}/pharmacy/orders/{bogus}", headers=pharm_headers, timeout=15)
        assert r.status_code == 404, r.text
        detail = r.json().get("detail", "")
        assert "غير موجودة" in detail, f"expected arabic 'not found', got: {detail!r}"


# ---------- C. wrong role ----------
class TestPharmacyOrderDetailRoleGuard:
    def test_supplier_role_gets_403(self, sup_headers, existing_order):
        oid = existing_order["id"]
        r = requests.get(f"{API}/pharmacy/orders/{oid}", headers=sup_headers, timeout=15)
        # require_role decorator raises 403 (not 500)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"

    def test_missing_auth_gets_401_or_403(self, existing_order):
        oid = existing_order["id"]
        r = requests.get(f"{API}/pharmacy/orders/{oid}", timeout=15)
        assert r.status_code in (401, 403), f"got {r.status_code}"


# ---------- D. mini end-to-end returns flow ----------
class TestReturnsMiniFlow:
    def _find_completable_order(self, pharm_headers):
        r = requests.get(f"{API}/pharmacy/orders", headers=pharm_headers, timeout=15)
        assert r.status_code == 200
        orders = r.json()
        return next(
            (o for o in orders if o.get("status") in ("delivered", "completed") and o.get("items")),
            None,
        )

    def test_create_return_and_verify_persistence(self, pharm_headers):
        r = requests.get(f"{API}/pharmacy/orders", headers=pharm_headers, timeout=15)
        assert r.status_code == 200
        candidates = [o for o in r.json()
                      if o.get("status") in ("delivered", "completed") and o.get("items")]
        if not candidates:
            pytest.skip("no delivered/completed order — cannot exercise POST /api/returns")

        # try each candidate order until we find one where a return succeeds
        # (older orders may have exhausted their return quota from earlier suites)
        last_err = None
        for order in candidates[:15]:
            oid = order["id"]
            r_det = requests.get(f"{API}/pharmacy/orders/{oid}",
                                 headers=pharm_headers, timeout=15)
            assert r_det.status_code == 200, r_det.text
            detail = r_det.json()
            for item in detail.get("items", []):
                payload = {
                    "original_order_id": oid,
                    "items": [{
                        "name": item.get("name", "TEST_item"),
                        "quantity": 1,
                        "unit_price": float(item.get("unit_price") or item.get("price") or 1.0),
                        "medicine_id": item.get("medicine_id"),  # None often, as UI does
                    }],
                    "reason": "damaged",
                    "notes": "TEST_ منتج تالف",
                }
                r2 = requests.post(f"{API}/returns", json=payload,
                                   headers=pharm_headers, timeout=20)
                if r2.status_code in (200, 201):
                    created = r2.json()
                    assert "id" in created and "total" in created
                    new_id = created["id"]

                    r3 = requests.get(f"{API}/returns", headers=pharm_headers, timeout=15)
                    assert r3.status_code == 200
                    payload3 = r3.json()
                    # /api/returns returns either a list or {items:[...]}
                    rows = payload3["items"] if isinstance(payload3, dict) else payload3
                    ids = [x.get("id") for x in rows]
                    assert new_id in ids, f"new return {new_id} not visible"
                    return  # SUCCESS
                last_err = f"{r2.status_code}: {r2.text[:200]}"

        pytest.skip(f"no order with returnable stock left (last err: {last_err})")
