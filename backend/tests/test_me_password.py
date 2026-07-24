"""
Regression tests for PATCH /api/me/password.

The endpoint changes the login password AND is the same secret used by the
accounting-unlock keypad (POST /api/auth/verify-password), so one change
must automatically update both places.

Covers:
  * wrong current password  -> 401 Arabic detail
  * new password < 6 chars  -> 400 Arabic detail
  * new == current          -> 400 Arabic detail
  * happy rotate            -> 200, old pw dead, new pw works for
                                verify-password AND full /auth/login
  * rapid 3x rotations
  * cross-role supplier
  * unauthenticated call     -> 401
  * final cleanup: restore original password for other suites
"""
import hashlib
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or \
           os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")

PHARM_PHONE = "07700000001"
PHARM_PW = "pass123"

SUP_PHONE = "07811111111"
SUP_PW = "sup1"  # seed password (only 4 chars, below endpoint's >=6)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _restore_supplier_seed_password():
    """The /me/password endpoint enforces new_password >= 6 chars, so we
    cannot rotate back to `sup1` (4 chars) via the API.  Reset directly in
    Mongo so downstream test suites still see the seed state."""
    try:
        from pymongo import MongoClient
        mongo_url = os.environ["MONGO_URL"]
        db_name = os.environ["DB_NAME"]
        with MongoClient(mongo_url) as c:
            c[db_name].suppliers.update_one(
                {"phone": SUP_PHONE},
                {"$set": {"password": _sha256(SUP_PW)}},
            )
    except Exception as e:  # noqa
        print(f"[warn] could not restore supplier seed pw: {e}")


# ---------- helpers ----------
def _login(phone: str, password: str):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"phone": phone, "password": password}, timeout=30)
    return r


def _auth_headers(token: str):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def pharm_token():
    r = _login(PHARM_PHONE, PHARM_PW)
    assert r.status_code == 200, f"seed pharmacy login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module", autouse=True)
def _reset_after_all():
    """Guarantee pharmacy pw is back to `pass123` at end of module."""
    yield
    # Try current known good states in order: could be pass123 (all passed) or
    # 123456 (test crashed mid-flight). Restore to pass123.
    for candidate in ("pass123", "123456"):
        r = _login(PHARM_PHONE, candidate)
        if r.status_code == 200:
            tok = r.json()["token"]
            if candidate != "pass123":
                requests.patch(
                    f"{BASE_URL}/api/me/password",
                    json={"current_password": candidate, "new_password": PHARM_PW},
                    headers=_auth_headers(tok), timeout=30)
            break


# ---------- validation / error cases ----------
class TestMePasswordErrors:
    def test_unauthenticated_is_401(self):
        r = requests.patch(f"{BASE_URL}/api/me/password",
                           json={"current_password": "x", "new_password": "abcdef"},
                           timeout=30)
        assert r.status_code in (401, 403), r.text

    def test_wrong_current_password_is_401_arabic(self, pharm_token):
        r = requests.patch(f"{BASE_URL}/api/me/password",
                           json={"current_password": "WRONG_PW",
                                 "new_password": "abcdef"},
                           headers=_auth_headers(pharm_token), timeout=30)
        assert r.status_code == 401, r.text
        assert "كلمة السر الحالية غير صحيحة" in r.json().get("detail", "")

    def test_short_new_password_is_400_arabic(self, pharm_token):
        r = requests.patch(f"{BASE_URL}/api/me/password",
                           json={"current_password": PHARM_PW, "new_password": "abc"},
                           headers=_auth_headers(pharm_token), timeout=30)
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", "")
        assert "6" in detail and "كلمة" in detail

    def test_new_equals_current_is_400_arabic(self, pharm_token):
        r = requests.patch(f"{BASE_URL}/api/me/password",
                           json={"current_password": PHARM_PW,
                                 "new_password": PHARM_PW},
                           headers=_auth_headers(pharm_token), timeout=30)
        assert r.status_code == 400, r.text
        assert "كلمة السر" in r.json().get("detail", "")


# ---------- happy path + accounting-unlock coupling ----------
class TestMePasswordHappyFlow:

    def test_rotate_and_verify_couples_with_accounting_unlock(self, pharm_token):
        # 1. rotate pass123 -> 123456
        r = requests.patch(f"{BASE_URL}/api/me/password",
                           json={"current_password": PHARM_PW,
                                 "new_password": "123456"},
                           headers=_auth_headers(pharm_token), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

        # 2. old password must be rejected by verify-password
        r_old = requests.post(f"{BASE_URL}/api/auth/verify-password",
                              json={"password": PHARM_PW},
                              headers=_auth_headers(pharm_token), timeout=30)
        assert r_old.status_code == 401, r_old.text

        # 3. new password unlocks accounting via verify-password (same secret)
        r_new = requests.post(f"{BASE_URL}/api/auth/verify-password",
                              json={"password": "123456"},
                              headers=_auth_headers(pharm_token), timeout=30)
        assert r_new.status_code == 200, r_new.text
        assert r_new.json() == {"ok": True}

        # 4. LOGIN accepts new password
        r_login_new = _login(PHARM_PHONE, "123456")
        assert r_login_new.status_code == 200, r_login_new.text

        # 5. LOGIN rejects old password
        r_login_old = _login(PHARM_PHONE, PHARM_PW)
        assert r_login_old.status_code == 401, r_login_old.text

        # 6. Rotate back to pass123 for downstream tests
        new_tok = r_login_new.json()["token"]
        r_back = requests.patch(f"{BASE_URL}/api/me/password",
                                json={"current_password": "123456",
                                      "new_password": PHARM_PW},
                                headers=_auth_headers(new_tok), timeout=30)
        assert r_back.status_code == 200, r_back.text

        # 7. Confirm original login works again
        assert _login(PHARM_PHONE, PHARM_PW).status_code == 200

    def test_rapid_three_rotations(self):
        """Ensure hashing/idempotency handles many rotations back-to-back."""
        chain = [PHARM_PW, "abcdef", "qwerty", "zxcvbn", PHARM_PW]
        current = chain[0]
        for nxt in chain[1:]:
            tok = _login(PHARM_PHONE, current).json()["token"]
            r = requests.patch(f"{BASE_URL}/api/me/password",
                               json={"current_password": current,
                                     "new_password": nxt},
                               headers=_auth_headers(tok), timeout=30)
            assert r.status_code == 200, f"{current}->{nxt}: {r.status_code} {r.text}"
            # login with new works
            r_l = _login(PHARM_PHONE, nxt)
            assert r_l.status_code == 200, r_l.text
            current = nxt
        # final state must be original pass123
        assert _login(PHARM_PHONE, PHARM_PW).status_code == 200


# ---------- cross-role: supplier ----------
class TestMePasswordSupplier:
    def test_supplier_can_rotate_and_verify(self):
        r = _login(SUP_PHONE, SUP_PW)
        assert r.status_code == 200, f"seed supplier login failed: {r.text}"
        tok = r.json()["token"]
        new_pw = "sup12345"
        try:
            r_ch = requests.patch(f"{BASE_URL}/api/me/password",
                                  json={"current_password": SUP_PW,
                                        "new_password": new_pw},
                                  headers=_auth_headers(tok), timeout=30)
            assert r_ch.status_code == 200, r_ch.text

            # verify-password accepts new
            r_v = requests.post(f"{BASE_URL}/api/auth/verify-password",
                                json={"password": new_pw},
                                headers=_auth_headers(tok), timeout=30)
            assert r_v.status_code == 200, r_v.text

            # login accepts new, rejects old
            assert _login(SUP_PHONE, new_pw).status_code == 200
            assert _login(SUP_PHONE, SUP_PW).status_code == 401
        finally:
            # Rotate back regardless of outcome.  The endpoint enforces
            # min-6-chars on `new_password`, so we cannot go back to `sup1`
            # via the API — restore directly in Mongo instead.
            _restore_supplier_seed_password()
        assert _login(SUP_PHONE, SUP_PW).status_code == 200
