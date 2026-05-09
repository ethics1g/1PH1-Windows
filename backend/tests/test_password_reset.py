"""
Backend tests for the Forgot Password / OTP Reset feature.
Endpoints under test:
  POST /api/auth/forgot-password
  POST /api/auth/verify-otp
  POST /api/auth/reset-password
Plus:
  - Audit trail in db.password_reset_audit
  - Pre-existing /api/pharmacy/login regression
"""
import os
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://pharma-checkout-8.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

# Mongo for inspection / cleanup
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "pharmacy_db")
mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]

# Pre-seeded credentials we must restore
SEED_PHARM_PHONE = "07700000001"
SEED_PHARM_PASS = "pass123"
SEED_SUPP_PHONE = "07811111111"
SEED_SUPP_PASS = "sup1"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="module")
def fresh_pharmacy(s):
    """Register a fresh pharmacy specifically for this test module."""
    phone = f"0779{uuid.uuid4().int % 10**7:07d}"
    payload = {"name": "TEST_RESET_PHARM", "phone": phone, "password": "init123", "address": "TEST"}
    r = s.post(f"{API}/pharmacy/register", json=payload)
    assert r.status_code == 200, r.text
    yield {"phone": phone, "password": "init123", "id": r.json()["pharmacy"]["id"]}
    # Cleanup
    db.pharmacies.delete_one({"phone": phone})
    db.password_reset_otps.delete_many({"phone": phone})
    db.password_reset_audit.delete_many({"phone": phone})


@pytest.fixture(scope="module")
def fresh_supplier(s):
    phone = f"0788{uuid.uuid4().int % 10**7:07d}"
    payload = {"name": "TEST_RESET_SUPP", "phone": phone, "password": "init123", "address": "TEST"}
    r = s.post(f"{API}/supplier/register", json=payload)
    assert r.status_code == 200, r.text
    yield {"phone": phone, "password": "init123", "id": r.json()["supplier"]["id"]}
    db.suppliers.delete_one({"phone": phone})
    db.password_reset_otps.delete_many({"phone": phone})
    db.password_reset_audit.delete_many({"phone": phone})


# ---------- forgot-password ----------
class TestForgotPassword:
    def test_invalid_role_400(self, s):
        r = s.post(f"{API}/auth/forgot-password", json={"phone": "0770", "role": "admin"})
        assert r.status_code == 400

    def test_unknown_phone_returns_ok_no_leak(self, s):
        unique = f"0770{uuid.uuid4().int % 10**7:07d}"
        r = s.post(f"{API}/auth/forgot-password", json={"phone": unique, "role": "pharmacy"})
        assert r.status_code == 200
        body = r.json()
        # No dev_otp field for non-existent phone
        assert "dev_otp" not in body
        assert body.get("status") == "ok"

    def test_dev_mode_returns_dev_otp_for_pharmacy(self, s, fresh_pharmacy):
        r = s.post(f"{API}/auth/forgot-password",
                   json={"phone": fresh_pharmacy["phone"], "role": "pharmacy"})
        assert r.status_code == 200
        body = r.json()
        assert "dev_otp" in body
        assert len(body["dev_otp"]) == 6 and body["dev_otp"].isdigit()
        # Audit logged
        audit = db.password_reset_audit.find_one(
            {"phone": fresh_pharmacy["phone"], "action": "otp_requested"})
        assert audit is not None

    def test_rate_limit_4th_returns_429(self, s, fresh_supplier):
        # 1st, 2nd, 3rd should succeed
        for i in range(3):
            r = s.post(f"{API}/auth/forgot-password",
                       json={"phone": fresh_supplier["phone"], "role": "supplier"})
            assert r.status_code == 200, f"req {i+1}: {r.status_code} {r.text}"
            assert "dev_otp" in r.json()
        # 4th must hit rate limit
        r4 = s.post(f"{API}/auth/forgot-password",
                    json={"phone": fresh_supplier["phone"], "role": "supplier"})
        assert r4.status_code == 429, f"expected 429, got {r4.status_code} {r4.text}"


# ---------- verify-otp ----------
class TestVerifyOtp:
    def test_non_numeric_otp_400(self, s, fresh_pharmacy):
        r = s.post(f"{API}/auth/verify-otp",
                   json={"phone": fresh_pharmacy["phone"], "role": "pharmacy", "otp": "abcdef"})
        assert r.status_code == 400

    def test_short_otp_400(self, s, fresh_pharmacy):
        r = s.post(f"{API}/auth/verify-otp",
                   json={"phone": fresh_pharmacy["phone"], "role": "pharmacy", "otp": "123"})
        assert r.status_code == 400

    def test_invalid_role_400(self, s, fresh_pharmacy):
        r = s.post(f"{API}/auth/verify-otp",
                   json={"phone": fresh_pharmacy["phone"], "role": "x", "otp": "123456"})
        assert r.status_code == 400

    def test_wrong_otp_then_correct_uses_attempts_then_invalidates(self, s):
        # Use a brand-new pharmacy so we have a clean OTP
        phone = f"0779{uuid.uuid4().int % 10**7:07d}"
        s.post(f"{API}/pharmacy/register",
               json={"name": "TEST_ATT", "phone": phone, "password": "init123", "address": "T"})
        try:
            req = s.post(f"{API}/auth/forgot-password",
                         json={"phone": phone, "role": "pharmacy"})
            assert req.status_code == 200
            real = req.json()["dev_otp"]
            wrong = "000000" if real != "000000" else "111111"

            # 3 wrong attempts
            for i in range(3):
                rr = s.post(f"{API}/auth/verify-otp",
                            json={"phone": phone, "role": "pharmacy", "otp": wrong})
                assert rr.status_code in (400, 429), f"attempt {i+1}: {rr.status_code} {rr.text}"

            # After 3 wrong attempts, OTP record should be marked used (invalidated).
            rec = db.password_reset_otps.find_one(
                {"phone": phone}, sort=[("created_at", -1)])
            assert rec is not None
            assert rec.get("used") is True or rec.get("attempts", 0) >= 3, \
                f"OTP not invalidated after 3 wrong attempts: used={rec.get('used')} attempts={rec.get('attempts')}"

            # Now even the correct OTP should fail (record is used or attempt-limit hit)
            rr = s.post(f"{API}/auth/verify-otp",
                        json={"phone": phone, "role": "pharmacy", "otp": real})
            assert rr.status_code in (400, 429)
        finally:
            db.pharmacies.delete_one({"phone": phone})
            db.password_reset_otps.delete_many({"phone": phone})
            db.password_reset_audit.delete_many({"phone": phone})

    def test_correct_otp_returns_reset_token_and_audit(self, s):
        phone = f"0779{uuid.uuid4().int % 10**7:07d}"
        s.post(f"{API}/pharmacy/register",
               json={"name": "TEST_OK", "phone": phone, "password": "init123", "address": "T"})
        try:
            req = s.post(f"{API}/auth/forgot-password",
                         json={"phone": phone, "role": "pharmacy"})
            real = req.json()["dev_otp"]
            v = s.post(f"{API}/auth/verify-otp",
                       json={"phone": phone, "role": "pharmacy", "otp": real})
            assert v.status_code == 200, v.text
            body = v.json()
            assert "reset_token" in body and len(body["reset_token"]) > 20
            assert body.get("expires_in") == 900
            # JWT sanity (3 parts)
            assert body["reset_token"].count(".") == 2
            # OTP record marked used
            rec = db.password_reset_otps.find_one({"phone": phone}, sort=[("created_at", -1)])
            assert rec.get("used") is True
            # Audit entry
            audit = db.password_reset_audit.find_one(
                {"phone": phone, "action": "otp_verified"})
            assert audit is not None
        finally:
            db.pharmacies.delete_one({"phone": phone})
            db.password_reset_otps.delete_many({"phone": phone})
            db.password_reset_audit.delete_many({"phone": phone})


# ---------- reset-password ----------
class TestResetPassword:
    def _full_flow_get_token(self, s, phone, role):
        req = s.post(f"{API}/auth/forgot-password", json={"phone": phone, "role": role})
        otp = req.json()["dev_otp"]
        v = s.post(f"{API}/auth/verify-otp",
                   json={"phone": phone, "role": role, "otp": otp})
        return v.json()["reset_token"]

    def test_short_password_400(self, s):
        phone = f"0779{uuid.uuid4().int % 10**7:07d}"
        s.post(f"{API}/pharmacy/register",
               json={"name": "TEST_SP", "phone": phone, "password": "init123", "address": "T"})
        try:
            tok = self._full_flow_get_token(s, phone, "pharmacy")
            r = s.post(f"{API}/auth/reset-password",
                       json={"reset_token": tok, "new_password": "12345"})
            assert r.status_code == 400
        finally:
            db.pharmacies.delete_one({"phone": phone})
            db.password_reset_otps.delete_many({"phone": phone})
            db.password_reset_audit.delete_many({"phone": phone})

    def test_invalid_token_401(self, s):
        r = s.post(f"{API}/auth/reset-password",
                   json={"reset_token": "not-a-jwt", "new_password": "abcdef"})
        assert r.status_code == 401

    def test_pharmacy_full_flow_password_changes(self, s):
        phone = f"0779{uuid.uuid4().int % 10**7:07d}"
        old_pw = "init123"
        new_pw = "newpw456"
        s.post(f"{API}/pharmacy/register",
               json={"name": "TEST_PHARM_FULL", "phone": phone, "password": old_pw, "address": "T"})
        try:
            tok = self._full_flow_get_token(s, phone, "pharmacy")
            r = s.post(f"{API}/auth/reset-password",
                       json={"reset_token": tok, "new_password": new_pw})
            assert r.status_code == 200, r.text
            # Old password fails
            old = s.post(f"{API}/pharmacy/login", json={"phone": phone, "password": old_pw})
            assert old.status_code == 401
            # New password works
            new = s.post(f"{API}/pharmacy/login", json={"phone": phone, "password": new_pw})
            assert new.status_code == 200
            assert "token" in new.json()
            # Audit entry
            audit = db.password_reset_audit.find_one(
                {"role": "pharmacy", "action": "password_reset_completed"},
                sort=[("timestamp", -1)])
            assert audit is not None
            # Single-use: second call same token -> 401
            r2 = s.post(f"{API}/auth/reset-password",
                        json={"reset_token": tok, "new_password": "anotherpw"})
            assert r2.status_code == 401, f"expected 401 single-use, got {r2.status_code}"
        finally:
            db.pharmacies.delete_one({"phone": phone})
            db.password_reset_otps.delete_many({"phone": phone})
            db.password_reset_audit.delete_many({"phone": phone})

    def test_supplier_full_flow_password_changes(self, s):
        phone = f"0788{uuid.uuid4().int % 10**7:07d}"
        old_pw = "init123"
        new_pw = "supnew99"
        s.post(f"{API}/supplier/register",
               json={"name": "TEST_SUPP_FULL", "phone": phone, "password": old_pw, "address": "T"})
        try:
            tok = self._full_flow_get_token(s, phone, "supplier")
            r = s.post(f"{API}/auth/reset-password",
                       json={"reset_token": tok, "new_password": new_pw})
            assert r.status_code == 200, r.text
            old = s.post(f"{API}/supplier/login", json={"phone": phone, "password": old_pw})
            assert old.status_code == 401
            new = s.post(f"{API}/supplier/login", json={"phone": phone, "password": new_pw})
            assert new.status_code == 200
        finally:
            db.suppliers.delete_one({"phone": phone})
            db.password_reset_otps.delete_many({"phone": phone})
            db.password_reset_audit.delete_many({"phone": phone})


# ---------- Regression for pre-seeded creds ----------
class TestRegression:
    def test_seeded_pharmacy_login_still_works(self, s):
        r = s.post(f"{API}/pharmacy/login",
                   json={"phone": SEED_PHARM_PHONE, "password": SEED_PHARM_PASS})
        assert r.status_code == 200, f"Seeded pharmacy creds broken: {r.text}"

    def test_seeded_supplier_login_still_works(self, s):
        r = s.post(f"{API}/supplier/login",
                   json={"phone": SEED_SUPP_PHONE, "password": SEED_SUPP_PASS})
        assert r.status_code == 200, f"Seeded supplier creds broken: {r.text}"
