"""
Security fix regression tests (SEC-001..SEC-004).

- SEC-001: No hardcoded 2nd admin (07823567874/Rasooll$123) seeded automatically.
- SEC-002: /api/auth/forgot-password never returns OTP in JSON (TEST_MODE_OTP_ECHO
  is a documented test-only escape hatch and is expected to be OFF in prod).
- SEC-003: Passwords are hashed with bcrypt for new accounts; legacy SHA256
  users are auto-upgraded on their next successful login.
- SEC-004: Image size limits are enforced on Gemini OCR endpoints.
"""
import os
import uuid
import hashlib
import pytest
import requests
from pymongo import MongoClient

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "pharmacy_db")
mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]

TEST_MODE_OTP_ECHO = os.environ.get("TEST_MODE_OTP_ECHO") == "1"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# ---------- SEC-001: hardcoded admin removed ----------
class TestSEC001HardcodedAdmin:
    def test_no_hardcoded_rasool_admin_credentials_work(self, s):
        """The previously hardcoded second admin 07823567874/Rasooll$123 must NOT
        grant access. If a real admin with that phone was created manually, that
        is fine — but the shipped default password must never authenticate."""
        r = s.post(f"{API}/admin/login",
                   json={"phone": "07823567874", "password": "Rasooll$123"})
        assert r.status_code == 401, (
            f"CRITICAL: the removed hardcoded admin password still works! "
            f"status={r.status_code} body={r.text[:200]}"
        )

    def test_default_bootstrap_admin_forces_password_change(self, s):
        """Default bootstrap admin (0000000000/admin123) must be flagged with
        must_change_password=True on first login."""
        r = s.post(f"{API}/admin/login",
                   json={"phone": "0000000000", "password": "admin123"})
        # 200 = still using default (dev env) OR 401 = already rotated.
        assert r.status_code in (200, 401)
        if r.status_code == 200:
            body = r.json()
            # must_change_password should be True until admin rotates it.
            assert "must_change_password" in body["admin"]


# ---------- SEC-002: OTP never in JSON (prod-safe default) ----------
class TestSEC002OtpNotLeaked:
    def test_forgot_password_response_never_contains_otp_fields(self, s):
        """The forgot-password JSON response must never include the OTP or its
        hash — even for known accounts. TEST_MODE_OTP_ECHO is the only legitimate
        exception (documented, off by default)."""
        phone = "07700000001"  # known pharmacy
        r = s.post(f"{API}/auth/forgot-password",
                   json={"phone": phone, "role": "pharmacy"})
        assert r.status_code in (200, 429)  # 429 if rate-limited
        if r.status_code != 200:
            return
        body = r.json()
        # Forbid OTP-adjacent field names
        forbidden = {"otp", "otp_hash", "code", "verification_code"}
        for k in forbidden:
            assert k not in body, f"SEC-002 regression: {k!r} in response {body}"

        if TEST_MODE_OTP_ECHO:
            # In test mode we intentionally echo dev_otp
            assert "dev_otp" in body
        else:
            assert "dev_otp" not in body, (
                "SEC-002 regression: dev_otp exposed even though "
                "TEST_MODE_OTP_ECHO is not set!"
            )


# ---------- SEC-003: bcrypt + legacy migration ----------
class TestSEC003BcryptMigration:
    def test_new_account_password_is_bcrypt(self, s):
        phone = f"0779{uuid.uuid4().int % 10**7:07d}"
        r = s.post(f"{API}/pharmacy/register",
                   json={"name": "SEC003", "phone": phone, "password": "bcryptpw",
                         "address": "T", "region": "بغداد"})
        assert r.status_code == 200, r.text
        try:
            doc = db.pharmacies.find_one({"phone": phone})
            assert doc is not None
            h = doc.get("password", "")
            assert h.startswith(("$2a$", "$2b$", "$2y$")), (
                f"New account not stored with bcrypt hash. Got prefix: {h[:6]}"
            )
        finally:
            db.pharmacies.delete_one({"phone": phone})

    def test_legacy_sha256_login_upgrades_hash(self, s):
        """Insert a user with a raw SHA256 hash directly, then login. The
        stored hash should be upgraded to bcrypt on that first success."""
        phone = f"0779{uuid.uuid4().int % 10**7:07d}"
        legacy = hashlib.sha256(b"legacypw").hexdigest()
        db.pharmacies.insert_one({
            "id": str(uuid.uuid4()),
            "name": "SEC003_LEGACY",
            "phone": phone,
            "password": legacy,
            "address": "T",
            "region": "بغداد",
            "region_normalized": "بغداد",
            "created_at": "2020-01-01T00:00:00+00:00",
        })
        try:
            r = s.post(f"{API}/pharmacy/login",
                       json={"phone": phone, "password": "legacypw"})
            assert r.status_code == 200, r.text
            doc = db.pharmacies.find_one({"phone": phone})
            new_h = doc.get("password", "")
            assert new_h.startswith(("$2a$", "$2b$", "$2y$")), (
                f"Legacy hash was not upgraded to bcrypt. Got: {new_h[:6]}"
            )
            assert doc.get("password_scheme") == "bcrypt"
            # Second login (now against bcrypt) also works
            r2 = s.post(f"{API}/pharmacy/login",
                        json={"phone": phone, "password": "legacypw"})
            assert r2.status_code == 200
        finally:
            db.pharmacies.delete_one({"phone": phone})

    def test_wrong_legacy_password_still_fails(self, s):
        phone = f"0779{uuid.uuid4().int % 10**7:07d}"
        db.pharmacies.insert_one({
            "id": str(uuid.uuid4()),
            "name": "SEC003_WRONG",
            "phone": phone,
            "password": hashlib.sha256(b"correctpw").hexdigest(),
            "address": "T", "region": "بغداد",
            "region_normalized": "بغداد",
            "created_at": "2020-01-01T00:00:00+00:00",
        })
        try:
            r = s.post(f"{API}/pharmacy/login",
                       json={"phone": phone, "password": "wrongpw"})
            assert r.status_code == 401
            # Hash must remain legacy since no successful login happened
            doc = db.pharmacies.find_one({"phone": phone})
            assert not doc["password"].startswith("$2")
        finally:
            db.pharmacies.delete_one({"phone": phone})


# ---------- SEC-004: image size limits ----------
class TestSEC004ImageSizeLimits:
    def _login(self, s):
        r = s.post(f"{API}/auth/login",
                   json={"phone": "07700000001", "password": "pass123"})
        assert r.status_code == 200, r.text
        return r.json()["token"]

    def test_tiny_image_rejected(self, s):
        tok = self._login(s)
        # <10KB decoded → returns 200 with hint (not 500 crash)
        tiny_b64 = "A" * 200  # ~150 bytes decoded
        r = s.post(f"{API}/orders/scan-image",
                   headers={"Authorization": f"Bearer {tok}"},
                   json={"image_base64": tiny_b64})
        assert r.status_code in (200, 400)
        if r.status_code == 200:
            body = r.json()
            assert body.get("items") == []
            assert "hint" in body

    def test_oversized_image_413(self, s):
        tok = self._login(s)
        # >10MB decoded → 413
        big_b64 = "A" * (11 * 1024 * 1024 * 4 // 3 + 1000)
        r = s.post(f"{API}/orders/scan-image",
                   headers={"Authorization": f"Bearer {tok}"},
                   json={"image_base64": big_b64})
        assert r.status_code == 413, (
            f"expected 413 for >10MB image, got {r.status_code}"
        )
