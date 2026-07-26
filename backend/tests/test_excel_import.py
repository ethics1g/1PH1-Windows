"""Backend tests for Excel / CSV supplier catalog import feature.

Covers cases A–K from the review request:
  A. Smart column mapping (Arabic + English mixed)
  B. Commit creates medicines + batches via existing pipeline
  C. Update path (same barcode second time → new batch, FIFO preserved)
  D. Unknown headers → 400 Arabic detail
  E. XLSX support
  F. Alternative header wording
  G. Different date formats parsed → ISO YYYY-MM-DD
  H. Per-row error reporting
  I. Large file (500 rows) safety
  J. Auth guards (401 unauth, 403 supplier)
  K. Empty file / bad base64 → 400
"""
from __future__ import annotations

import base64
import io
import os
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"

PHARMACY_PHONE = "07700000001"
PHARMACY_PASSWORD = "pass123"
SUPPLIER_PHONE = "07811111111"
SUPPLIER_PASSWORD = "sup1"

RUN = f"{int(time.time())}_{uuid.uuid4().hex[:4]}"


# ----------------------------- fixtures -------------------------------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def pharmacy_headers(session):
    r = session.post(f"{BASE_URL}/pharmacy/login",
                     json={"phone": PHARMACY_PHONE, "password": PHARMACY_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def supplier_headers(session):
    r = session.post(f"{BASE_URL}/supplier/login",
                     json={"phone": SUPPLIER_PHONE, "password": SUPPLIER_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}",
            "Content-Type": "application/json"}


# ----------------------------- helpers --------------------------------
def _b64_csv(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _preview(session, headers, filename: str, b64: str):
    return session.post(f"{BASE_URL}/orders/excel/preview",
                        json={"filename": filename, "file_base64": b64},
                        headers=headers)


def _commit(session, headers, items, supplier_id=None, supplier_name=None):
    payload = {"items": items}
    if supplier_id:
        payload["supplier_id"] = supplier_id
    if supplier_name:
        payload["supplier_name"] = supplier_name
    return session.post(f"{BASE_URL}/orders/excel/commit",
                        json=payload, headers=headers)


# ============================ CASE A ==================================
class TestA_SmartColumnMapping:
    def test_arabic_english_mixed_headers(self, session, pharmacy_headers):
        csv_text = (
            "barcode,اسم الدواء,quantity,السعر,expiry,batch,manufacturer\n"
            f"T_XLSA_{RUN}_1,باراسيتامول 500,50,250,2028-06,B100,شركة أ\n"
            f"T_XLSA_{RUN}_2,ايبوبروفين 200,30,180,2027-12-01,B200,شركة ب\n"
        )
        r = _preview(session, pharmacy_headers, "cat.csv", _b64_csv(csv_text))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 2
        cd = body["columns_detected"]
        assert cd["barcode"] == 0
        assert cd["name"] == 1
        assert cd["quantity"] == 2
        assert cd["purchase_price"] == 3
        assert cd["expiry_date"] == 4
        assert cd["batch_number"] == 5
        assert cd["manufacturer"] == 6

        it = body["items"][0]
        assert it["name"] == "باراسيتامول 500"
        assert it["barcode"] == f"T_XLSA_{RUN}_1"
        assert it["quantity"] == 50
        assert it["purchase_price"] == 250
        assert it["expiry_date"] == "2028-06-01"
        assert it["batch_number"] == "B100"
        assert it["manufacturer"] == "شركة أ"


# ============================ CASE B & C =============================
class TestBC_CommitAndUpdate:
    """Committed rows create medicines + batches via existing pipeline,
    and second commit with same barcode adds a NEW batch (FIFO)."""

    barcode1 = f"T_XLSBC_{RUN}_1"
    barcode2 = f"T_XLSBC_{RUN}_2"

    def _items_v1(self):
        return [
            {"name": f"TEST_XLS_MED_A_{RUN}", "barcode": self.barcode1,
             "quantity": 50, "purchase_price": 250.0,
             "expiry_date": "2028-06-01", "batch_number": "B100",
             "manufacturer": "شركة أ"},
            {"name": f"TEST_XLS_MED_B_{RUN}", "barcode": self.barcode2,
             "quantity": 30, "purchase_price": 180.0,
             "expiry_date": "2027-12-01", "batch_number": "B200",
             "manufacturer": "شركة ب"},
        ]

    def test_b_commit_creates_new_meds_and_batches(self, session, pharmacy_headers):
        r = _commit(session, pharmacy_headers, self._items_v1())
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["imported"] == 2
        assert body["new"] == 2
        assert body["updated"] == 0
        assert body["failed"] == 0
        assert len(body["succeeded"]) == 2

        med_id = body["succeeded"][0]["medicine_id"]
        TestBC_CommitAndUpdate.med_id_a = med_id

        # GET batches — must show 1 batch with correct expiry & remaining
        rb = session.get(f"{BASE_URL}/medicines/{med_id}/batches",
                         headers=pharmacy_headers)
        assert rb.status_code == 200, rb.text
        bd = rb.json()
        assert len(bd["batches"]) == 1
        b = bd["batches"][0]
        assert b["remaining_quantity"] == 50
        assert (b.get("expiry_date") or "").startswith("2028-06-01")
        assert bd["total_stock"] == 50

    def test_c_second_commit_updates_and_adds_new_batch(self, session, pharmacy_headers):
        items_v2 = [
            {**self._items_v1()[0], "quantity": 60, "batch_number": "B100-2"},
            {**self._items_v1()[1], "quantity": 40, "batch_number": "B200-2"},
        ]
        r = _commit(session, pharmacy_headers, items_v2)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["updated"] == 2, body
        assert body["new"] == 0
        assert body["failed"] == 0

        # Medicine still 1 record, but 2 batches now
        med_id = TestBC_CommitAndUpdate.med_id_a
        rb = session.get(f"{BASE_URL}/medicines/{med_id}/batches",
                         headers=pharmacy_headers)
        assert rb.status_code == 200
        bd = rb.json()
        assert len(bd["batches"]) == 2, bd
        # Total stock 50 + 60 = 110
        assert bd["total_stock"] == 110
        # FIFO: earliest first (created_at ASC)
        # oldest is 50, newest is 60
        remainings = [b["remaining_quantity"] for b in bd["batches"]]
        assert remainings == [50, 60], remainings


# ============================ CASE D ==================================
class TestD_UnknownHeaders:
    def test_bad_headers_400(self, session, pharmacy_headers):
        csv_text = "foo,bar,baz\n1,2,3\n"
        r = _preview(session, pharmacy_headers, "junk.csv", _b64_csv(csv_text))
        assert r.status_code == 400
        assert "اسم الدواء" in r.json()["detail"]


# ============================ CASE E ==================================
class TestE_XLSX:
    def test_xlsx_preview_and_commit(self, session, pharmacy_headers):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Barcode", "Medicine Name", "Quantity", "Price", "Expiry"])
        rows = [
            (f"T_XLSE_{RUN}_1", f"TEST_XLS_E1_{RUN}", 10, 100, "2028-01-01"),
            (f"T_XLSE_{RUN}_2", f"TEST_XLS_E2_{RUN}", 20, 150, "2028-02-01"),
            (f"T_XLSE_{RUN}_3", f"TEST_XLS_E3_{RUN}", 30, 200, "2028-03-01"),
        ]
        for row in rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        r = _preview(session, pharmacy_headers, "cat.xlsx", b64)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 3
        cd = body["columns_detected"]
        for k in ("barcode", "name", "quantity", "purchase_price", "expiry_date"):
            assert k in cd, f"missing detected column {k}"

        # Commit → new=3
        r2 = _commit(session, pharmacy_headers, body["items"])
        assert r2.status_code == 201, r2.text
        b2 = r2.json()
        assert b2["new"] == 3, b2


# ============================ CASE F ==================================
class TestF_AlternativeHeaders:
    def test_alt_arabic_headers(self, session, pharmacy_headers):
        csv_text = (
            "الباركود,اسم المنتج,الكمية,سعر الشراء,تاريخ الانتهاء,الدفعة,الشركة المصنعة\n"
            f"T_XLSF_{RUN}_1,TEST_XLS_F1_{RUN},5,120,2028-05-01,BF1,شركة\n"
        )
        r = _preview(session, pharmacy_headers, "alt.csv", _b64_csv(csv_text))
        assert r.status_code == 200, r.text
        cd = r.json()["columns_detected"]
        for k in ("barcode", "name", "quantity", "purchase_price",
                  "expiry_date", "batch_number", "manufacturer"):
            assert k in cd, f"missing {k}: {cd}"


# ============================ CASE G ==================================
class TestG_DateFormats:
    def test_multiple_date_formats(self, session, pharmacy_headers):
        csv_text = (
            "name,quantity,price,expiry\n"
            f"TEST_XLS_G1_{RUN},1,10,01/06/2027\n"
            f"TEST_XLS_G2_{RUN},1,10,2026-08\n"
            f"TEST_XLS_G3_{RUN},1,10,12-2028\n"
        )
        r = _preview(session, pharmacy_headers, "d.csv", _b64_csv(csv_text))
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert items[0]["expiry_date"] == "2027-06-01"
        assert items[1]["expiry_date"] == "2026-08-01"
        assert items[2]["expiry_date"] == "2028-12-01"


# ============================ CASE H ==================================
class TestH_PerRowErrors:
    def test_missing_name_and_zero_quantity_reported(self, session, pharmacy_headers):
        # Send items directly to commit
        items = [
            {"name": f"TEST_XLS_H_OK_{RUN}", "quantity": 5,
             "purchase_price": 100, "expiry_date": "2028-01-01"},
            {"name": "", "quantity": 10, "purchase_price": 100,
             "expiry_date": "2028-01-01"},
            {"name": f"TEST_XLS_H_ZERO_{RUN}", "quantity": 0,
             "purchase_price": 100, "expiry_date": "2028-01-01"},
        ]
        r = _commit(session, pharmacy_headers, items)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["failed"] >= 2, body
        # Find reasons
        errs = {e["row"]: e["error"] for e in body["errors"]}
        # rows are 1-based; expect rows 2 and 3 to fail
        assert any("الاسم" in e for e in errs.values()), errs
        assert any("الكمية" in e for e in errs.values()), errs


# ============================ CASE I ==================================
class TestI_LargeFile:
    def test_500_rows_preview_and_commit(self, session, pharmacy_headers):
        lines = ["barcode,name,quantity,price,expiry"]
        for i in range(500):
            lines.append(
                f"T_XLSI_{RUN}_{i},TEST_XLS_I_{RUN}_{i},1,10,2028-01-01"
            )
        csv_text = "\n".join(lines) + "\n"
        r = _preview(session, pharmacy_headers, "big.csv", _b64_csv(csv_text))
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 500
        r2 = _commit(session, pharmacy_headers, r.json()["items"])
        assert r2.status_code == 201
        b2 = r2.json()
        assert b2["imported"] == 500, b2


# ============================ CASE J ==================================
class TestJ_AuthGuards:
    def _payload(self):
        return {"filename": "x.csv",
                "file_base64": _b64_csv("name,qty,price\nA,1,1\n")}

    def test_preview_unauth_401(self, session):
        r = session.post(f"{BASE_URL}/orders/excel/preview",
                         json=self._payload(),
                         headers={"Content-Type": "application/json"})
        assert r.status_code == 401, r.status_code

    def test_preview_supplier_403(self, session, supplier_headers):
        r = session.post(f"{BASE_URL}/orders/excel/preview",
                         json=self._payload(), headers=supplier_headers)
        assert r.status_code == 403, r.status_code

    def test_commit_unauth_401(self, session):
        r = session.post(f"{BASE_URL}/orders/excel/commit",
                         json={"items": [{"name": "A", "quantity": 1,
                                          "purchase_price": 1}]},
                         headers={"Content-Type": "application/json"})
        assert r.status_code == 401

    def test_commit_supplier_403(self, session, supplier_headers):
        r = session.post(f"{BASE_URL}/orders/excel/commit",
                         json={"items": [{"name": "A", "quantity": 1,
                                          "purchase_price": 1}]},
                         headers=supplier_headers)
        assert r.status_code == 403


# ============================ CASE K ==================================
class TestK_BadInput:
    def test_empty_b64_400(self, session, pharmacy_headers):
        r = session.post(f"{BASE_URL}/orders/excel/preview",
                         json={"filename": "x.csv", "file_base64": ""},
                         headers=pharmacy_headers)
        assert r.status_code == 400

    def test_short_b64_400(self, session, pharmacy_headers):
        r = session.post(f"{BASE_URL}/orders/excel/preview",
                         json={"filename": "x.csv", "file_base64": "abc"},
                         headers=pharmacy_headers)
        assert r.status_code == 400

    def test_bad_base64_400(self, session, pharmacy_headers):
        # Long-enough garbage that is not decodable text and header parses to empty
        # (invalid base64 chars). Should still yield 400 via decode or empty-headers path.
        r = session.post(f"{BASE_URL}/orders/excel/preview",
                         json={"filename": "x.csv",
                               "file_base64": "!!!!!!!!!!!!!!!!!!!!!!"},
                         headers=pharmacy_headers)
        assert r.status_code == 400
