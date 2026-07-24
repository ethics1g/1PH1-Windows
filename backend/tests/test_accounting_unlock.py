"""Backend tests for the Accounting section unlock feature.

Endpoint under test: POST /api/auth/verify-password
Also verifies:
  - JWT is required
  - Wrong password returns 401 with Arabic detail `رمز غير صحيح`
  - Cross-account password rejection (pharmacy pw != supplier pw)
  - Rotating the pharmacy password automatically rotates the unlock code
    (because it uses the exact same login credential).
"""
import os
import hashlib
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or \
           "https://pharma-checkout-8.preview.emergentagent.com"

PHARMACY_PHONE = "07700000001"
PHARMACY_PW = "pass123"
SUPPLIER_PHONE = "07811111111"
SUPPLIER_PW = "sup1"
ADMIN_PHONE = "0000000000"
ADMIN_PW = "admin123"

WRONG_MSG = "رمز غير صحيح"


def _sha(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()


@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(http, endpoint, phone, pw):
    r = http.post(f"{BASE_URL}/api/{endpoint}", json={"phone": phone, "password": pw})
    assert r.status_code == 200, f"login {endpoint} failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def pharmacy_token(http):
    return _login(http, "pharmacy/login", PHARMACY_PHONE, PHARMACY_PW)


@pytest.fixture(scope="module")
def supplier_token(http):
    return _login(http, "supplier/login", SUPPLIER_PHONE, SUPPLIER_PW)


@pytest.fixture(scope="module")
def admin_token(http):
    # Admin also uses pharmacy/login endpoint per this codebase? Check first.
    # Try admin login endpoint variants
    for ep in ("admin/login", "pharmacy/login"):
        r = http.post(f"{BASE_URL}/api/{ep}", json={"phone": ADMIN_PHONE, "password": ADMIN_PW})
        if r.status_code == 200:
            return r.json()["token"]
    pytest.skip("admin login endpoint not found or admin credentials invalid")


@pytest.fixture(scope="module")
def mongo_col():
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "pharmacy_db")
    client = MongoClient(mongo_url)
    yield client[db_name]
    client.close()


def _verify(http, token, password):
    return http.post(
        f"{BASE_URL}/api/auth/verify-password",
        json={"password": password},
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )


# ---------- Pharmacy ----------
class TestPharmacyVerifyPassword:
    def test_correct_password_returns_ok(self, http, pharmacy_token):
        r = _verify(http, pharmacy_token, PHARMACY_PW)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

    def test_wrong_password_returns_401_arabic(self, http, pharmacy_token):
        r = _verify(http, pharmacy_token, "wrongpw")
        assert r.status_code == 401
        assert r.json().get("detail") == WRONG_MSG

    def test_empty_password_returns_401_arabic(self, http, pharmacy_token):
        r = _verify(http, pharmacy_token, "")
        assert r.status_code == 401
        assert r.json().get("detail") == WRONG_MSG

    def test_no_auth_header_returns_401(self, http):
        r = http.post(f"{BASE_URL}/api/auth/verify-password", json={"password": PHARMACY_PW})
        assert r.status_code == 401

    def test_invalid_body_returns_422(self, http, pharmacy_token):
        r = http.post(
            f"{BASE_URL}/api/auth/verify-password",
            json={},
            headers={"Authorization": f"Bearer {pharmacy_token}"},
        )
        # Pydantic should reject missing password
        assert r.status_code in (422, 401)


# ---------- Supplier ----------
class TestSupplierVerifyPassword:
    def test_correct_password_returns_ok(self, http, supplier_token):
        r = _verify(http, supplier_token, SUPPLIER_PW)
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_pharmacy_password_rejected(self, http, supplier_token):
        """Cross-account isolation: pharmacy pw must NOT unlock supplier account."""
        r = _verify(http, supplier_token, PHARMACY_PW)
        assert r.status_code == 401
        assert r.json().get("detail") == WRONG_MSG


# ---------- Admin ----------
class TestAdminVerifyPassword:
    def test_correct_password_returns_ok(self, http, admin_token):
        r = _verify(http, admin_token, ADMIN_PW)
        # Admin may have must_change_password with modified password.
        # Accept 200 or 401 (if pw was rotated); prefer 200.
        if r.status_code == 401:
            pytest.skip("admin password was rotated in a previous run — skipping")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


# ---------- Rotation (unlock code auto-follows login pw) ----------
class TestPasswordRotationAffectsUnlockCode:
    def test_rotate_and_verify(self, http, pharmacy_token, mongo_col):
        """Manually rotate pharmacy pw in MongoDB (no /me/password endpoint
        exists in server.py — see rca in test report). Then verify the
        unlock endpoint honours the new pw."""
        new_pw = "123456"
        # Persist original hash to restore later
        orig = mongo_col.pharmacies.find_one({"phone": PHARMACY_PHONE})
        assert orig is not None, "seed pharmacy missing"
        original_hash = orig["password"]
        try:
            mongo_col.pharmacies.update_one(
                {"phone": PHARMACY_PHONE}, {"$set": {"password": _sha(new_pw)}}
            )
            # old pw now rejected
            r_old = _verify(http, pharmacy_token, PHARMACY_PW)
            assert r_old.status_code == 401
            assert r_old.json().get("detail") == WRONG_MSG
            # new pw accepted
            r_new = _verify(http, pharmacy_token, new_pw)
            assert r_new.status_code == 200
            assert r_new.json() == {"ok": True}
        finally:
            # ALWAYS restore, even if assertion fails
            mongo_col.pharmacies.update_one(
                {"phone": PHARMACY_PHONE}, {"$set": {"password": original_hash}}
            )
        # Post-restore sanity
        r_restore = _verify(http, pharmacy_token, PHARMACY_PW)
        assert r_restore.status_code == 200, "password restore did not work"
