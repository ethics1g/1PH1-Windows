"""Tests for the two-pass OCR fallback + `hint` field in /orders/scan-image.

Feature under test: /app/backend/paper_orders.py (iteration 28 fix)
Scope:
  - <100 char base64 → 400
  - <10 KB image → 200 with count=0 + hint mentioning 'صغيرة جداً'
  - >10 MB image → 413
  - real synthetic invoice → response has either items>0 or a `hint` field
  - Backend logs show 'raw response preview' + two-pass retry line
  - Regression: existing paper-orders commit/list flow still works (tiny smoke)
"""
from __future__ import annotations

import base64
import io
import os
import re
import time
from pathlib import Path

import pytest
import requests

# Optional PIL for building a realistic-looking invoice image
try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL")
if not BASE_URL:
    _env_path = "/app/frontend/.env"
    if os.path.isfile(_env_path):
        with open(_env_path, "r", encoding="utf-8") as _f:
            for line in _f:
                if line.strip().startswith("EXPO_PUBLIC_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().strip('"')
                    break
BASE_URL = (BASE_URL or "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL missing"

PHARMACY = {"phone": "07700000001", "password": "pass123"}

# ---------------- fixtures ----------------

@pytest.fixture(scope="module")
def pharmacy_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=PHARMACY, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def h_pharm(pharmacy_token):
    return {"Authorization": f"Bearer {pharmacy_token}", "Content-Type": "application/json"}


def _tiny_valid_png_b64() -> str:
    """~1.5KB valid-ish base64 PNG-ish payload. Passes the >100 length guard
    but should hit the <10KB size guard and return a hint."""
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"01234567" * 128).decode()


def _mid_size_random_b64(kb: int) -> str:
    """Produces a base64 blob of approximately `kb` KB of random-ish bytes."""
    raw = os.urandom(kb * 1024)
    return base64.b64encode(raw).decode()


def _synthetic_invoice_b64() -> str:
    """Produces a printable-looking invoice PNG using PIL, base64-encoded."""
    if not _HAS_PIL:
        return ""
    W, H = 900, 700
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    lines = [
        "TAREEQ AL-SALAM  PHARMACY INVOICE",
        "Invoice No: INV-2026-001    Date: 2026-01-05",
        "-----------------------------------------------",
        "Item                    Qty   Price   Total",
        "-----------------------------------------------",
        "Paracetamol 500mg       30    250     7500",
        "Amoxicillin 250mg       10    1500    15000",
        "Ibuprofen 400mg         20    300     6000",
        "Cetirizine 10mg         15    400     6000",
        "-----------------------------------------------",
        "                        GRAND TOTAL:  34500",
    ]
    y = 30
    for line in lines:
        d.text((30, y), line, fill="black", font=font)
        y += 40
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ---------------- size / input guard tests ----------------

class TestInputGuards:

    def test_invalid_base64_too_short_returns_400(self, h_pharm):
        r = requests.post(f"{BASE_URL}/api/orders/scan-image",
                          json={"image_base64": "abc"}, headers=h_pharm, timeout=15)
        assert r.status_code == 400, r.text
        # error message should be Arabic 'الصورة غير صالحة'
        try:
            msg = r.json().get("detail", "")
        except Exception:
            msg = r.text
        assert "غير صالحة" in msg or "invalid" in msg.lower(), msg

    def test_tiny_image_returns_hint_not_error(self, h_pharm):
        b64 = _tiny_valid_png_b64()
        # sanity: base64 length passes the >100 chars gate…
        assert len(b64) > 100
        # …but decodes to <10 KB
        assert int(len(b64) * 0.75) < 10 * 1024
        r = requests.post(f"{BASE_URL}/api/orders/scan-image",
                          json={"image_base64": b64}, headers=h_pharm, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("count") == 0
        assert body.get("items") == []
        hint = body.get("hint", "")
        assert hint, "expected `hint` field on empty result"
        assert "صغيرة جداً" in hint, f"unexpected hint: {hint}"

    def test_oversized_image_returns_413(self, h_pharm):
        # generate ~11 MB of random bytes → base64 will be ~14.7MB
        b64 = _mid_size_random_b64(11 * 1024)  # 11 MB raw
        assert int(len(b64) * 0.75) > 10 * 1024 * 1024
        r = requests.post(f"{BASE_URL}/api/orders/scan-image",
                          json={"image_base64": b64}, headers=h_pharm, timeout=60)
        assert r.status_code == 413, f"got {r.status_code}: {r.text[:200]}"


# ---------------- OCR real-image flow ----------------

@pytest.mark.skipif(not _HAS_PIL, reason="Pillow not available")
class TestRealImageFlow:

    def test_synthetic_invoice_returns_items_or_hint(self, h_pharm):
        b64 = _synthetic_invoice_b64()
        # >10KB
        assert int(len(b64) * 0.75) > 10 * 1024
        r = requests.post(f"{BASE_URL}/api/orders/scan-image",
                          json={"image_base64": b64}, headers=h_pharm, timeout=120)
        # Should be 200 no matter what; count may be 0 if Gemini rejects the
        # synthetic image, but a `hint` must then be present.
        assert r.status_code == 200, r.text
        body = r.json()
        assert "count" in body and "items" in body and "metadata" in body
        if body["count"] == 0:
            assert body.get("hint"), "hint field required on empty count"
        else:
            assert isinstance(body["items"], list) and len(body["items"]) >= 1
            for it in body["items"]:
                assert "name" in it
                assert "quantity" in it
                assert "purchase_price" in it


# ---------------- backend log verification ----------------

class TestBackendLogging:
    """Verify the diagnostic logging & two-pass retry actually fires."""

    LOG_PATHS = [
        "/var/log/supervisor/backend.err.log",
        "/var/log/supervisor/backend.out.log",
    ]

    def _read_recent(self, lines: int = 400) -> str:
        chunks = []
        for p in self.LOG_PATHS:
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        chunks.append(f.read()[-200_000:])
                except Exception:
                    pass
        return "\n".join(chunks)

    def test_logs_show_ocr_activity(self, h_pharm):
        """After a scan-image call, backend logs should mention the OCR call
        preview or the two-pass retry marker."""
        if not _HAS_PIL:
            pytest.skip("PIL not available to trigger a real OCR call")
        b64 = _synthetic_invoice_b64()
        # Trigger a scan (real Gemini call may or may not return items)
        r = requests.post(f"{BASE_URL}/api/orders/scan-image",
                          json={"image_base64": b64}, headers=h_pharm, timeout=120)
        assert r.status_code == 200
        # Give logs a moment to flush
        time.sleep(1.0)
        logs = self._read_recent()
        # Either the "raw response preview" line or the "pass 1 returned 0" line
        # must appear. Both live only in this iteration's code.
        has_preview = "paper-order OCR" in logs and "raw response preview" in logs
        has_retry = "pass 1 returned 0 items" in logs
        assert has_preview or has_retry, \
            "expected either 'raw response preview' or 'pass 1 returned 0' in backend logs"


# ---------------- Regression smoke ----------------

class TestRegressionSmoke:
    """Confirm existing paper-orders flow still works after the fix."""

    def test_commit_and_list_still_work(self, h_pharm):
        ts = int(time.time())
        dummy = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0123456789abcdef" * 200).decode()
        payload = {
            "image_base64": dummy,
            "supplier_name": "REG_TEST_supplier",
            "total": 2500,
            "amount_paid": 0,
            "items": [{"name": f"TEST_OCR_REG_{ts}", "quantity": 5, "purchase_price": 500}],
        }
        r = requests.post(f"{BASE_URL}/api/orders/paper", json=payload,
                          headers=h_pharm, timeout=30)
        assert r.status_code == 201, r.text
        oid = r.json()["id"]

        r2 = requests.get(f"{BASE_URL}/api/orders/paper?limit=200",
                          headers=h_pharm, timeout=15)
        assert r2.status_code == 200
        assert any(it["id"] == oid for it in r2.json().get("items", []))
