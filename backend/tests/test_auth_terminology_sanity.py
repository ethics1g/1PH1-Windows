# Sanity check: backend contract must remain unchanged after frontend terminology rename.
# Registers a pharmacy + supplier and confirms role field returned as-is.
import base64
import json
import os
import time
import requests
import pytest


def _jwt_role(token: str) -> str:
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64)).get("role")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://pharma-checkout-8.preview.emergentagent.com"

TS = str(int(time.time()))[-6:]


@pytest.fixture(scope="module")
def s():
    return requests.Session()


def _try_register(session, role, phone, name):
    payload = {
        "name": name,
        "phone": phone,
        "password": "testpw123",
        "region": "بغداد",
        "address": "شارع 1",
    }
    # First try /api/{role}/register (matches login.tsx code path)
    url1 = f"{BASE_URL}/api/{role}/register"
    r = session.post(url1, json=payload, timeout=20)
    if r.status_code in (200, 201):
        return r, url1
    # Fallback to /api/auth/register with role in body
    url2 = f"{BASE_URL}/api/auth/register"
    payload2 = {**payload, "role": role}
    r2 = session.post(url2, json=payload2, timeout=20)
    return r2, url2


def test_register_pharmacy_role_unchanged(s):
    phone = f"0779999{TS}"
    r, used_url = _try_register(s, "pharmacy", phone, "متجر اختبار")
    assert r.status_code in (200, 201), f"[{used_url}] {r.status_code}: {r.text[:300]}"
    data = r.json()
    assert "token" in data, f"missing token: {data}"
    # Role must remain 'pharmacy' internally (JWT payload) and the entity key must be 'pharmacy'
    assert "pharmacy" in data, f"expected 'pharmacy' key in response; got keys={list(data.keys())}"
    assert _jwt_role(data["token"]) == "pharmacy", f"JWT role mismatch; body={data}"
    # login with same creds
    lr = s.post(f"{BASE_URL}/api/auth/login", json={"phone": phone, "password": "testpw123"}, timeout=15)
    assert lr.status_code == 200, lr.text[:300]
    lbody = lr.json()
    assert lbody.get("role") == "pharmacy", f"login role mismatch: {lbody}"


def test_register_supplier_role_unchanged(s):
    phone = f"0778888{TS}"
    r, used_url = _try_register(s, "supplier", phone, "مورد اختبار")
    assert r.status_code in (200, 201), f"[{used_url}] {r.status_code}: {r.text[:300]}"
    data = r.json()
    assert "token" in data, f"missing token: {data}"
    assert "supplier" in data, f"expected 'supplier' key in response; got keys={list(data.keys())}"
    assert _jwt_role(data["token"]) == "supplier", f"JWT role mismatch; body={data}"
    lr = s.post(f"{BASE_URL}/api/auth/login", json={"phone": phone, "password": "testpw123"}, timeout=15)
    assert lr.status_code == 200, lr.text[:300]
    assert lr.json().get("role") == "supplier"
