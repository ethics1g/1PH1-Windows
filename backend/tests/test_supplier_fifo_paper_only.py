"""
End-to-end tests for iteration 23 (RESTORE + extend FIFO supplier debt).

Focus: paper-order-only suppliers (with auto-assigned local:* supplier_id)
must appear in supplier-accounts and be payable via the same FIFO endpoints
as marketplace suppliers.

Covers all six items in the review request for the paper-only flow.
"""
import os
import time
import pytest
import requests

# 1x1 PNG base64 padded to > 100 chars (endpoint requires min length)
IMG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
           + "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL is required")
API = f"{BASE_URL}/api"
PHARMACY = {"phone": "07700000001", "password": "pass123"}


@pytest.fixture(scope="module")
def h():
    r = requests.post(f"{API}/auth/login", json=PHARMACY, timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def state():
    return {}


# =====================================================================
# CORE FLOW: paper-order-only supplier appears + can be paid via FIFO
# =====================================================================

class TestPaperOnlySupplierFIFO:

    def test_01_create_paper_order_without_supplier_id_gets_local_sid(self, h, state):
        """Create a paper order WITHOUT supplier_id -> local:* auto-assigned."""
        ts = int(time.time() * 1000)
        supplier_name = f"TEST_مذخر تجريبي paper-only {ts}"
        state["supplier_name"] = supplier_name
        payload = {
            "image_base64": IMG_B64,
            "supplier_name": supplier_name,
            "invoice_number": f"TEST-INV-{ts}",
            "invoice_date": "2026-01-15",
            "items": [{"name": f"TEST_دواء {ts}", "quantity": 5,
                       "purchase_price": 20.0, "selling_price": 25.0}],
            "total": 100.0,
            "amount_paid": 30.0,
            "notes": "TEST paper-only supplier",
        }
        r = requests.post(f"{API}/orders/paper", json=payload, headers=h, timeout=20)
        assert r.status_code in (200, 201), f"paper-order create failed: {r.status_code} {r.text}"
        j = r.json()
        # supplier_id auto-assigned; must be local:*
        assert j.get("supplier_id", "").startswith("local:"), f"expected local:* supplier_id, got {j.get('supplier_id')}"
        assert j["supplier_name"] == supplier_name
        assert j["total"] == 100.0
        assert j["amount_paid"] == 30.0
        assert j["remaining"] == 70.0
        assert j["payment_status"] == "partial"
        state["paper_order_id"] = j["id"]
        state["local_sid"] = j["supplier_id"]

    def test_02_supplier_accounts_list_includes_paper_only(self, h, state):
        """GET /accounting/supplier-accounts must list the new local:* supplier."""
        r = requests.get(f"{API}/accounting/supplier-accounts", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "items" in j and "total_outstanding" in j
        sid = state["local_sid"]
        match = next((it for it in j["items"] if it.get("supplier_id") == sid), None)
        assert match is not None, f"local:* supplier {sid} not found in {[it.get('supplier_id') for it in j['items']]}"
        assert match["outstanding_balance"] == 70.0, f"outstanding wrong: {match}"
        assert match["supplier_name"] == state["supplier_name"]
        # paper_purchased tag / source tag
        assert match.get("source") in ("paper", "combined"), f"source: {match.get('source')}"
        assert match.get("order_count", 0) >= 1

    def test_03_supplier_detail_returns_synthetic_supplier(self, h, state):
        """GET /accounting/supplier-accounts/{local_sid} returns 200 with
        supplier.name from paper_orders.supplier_name (no marketplace doc exists)."""
        sid = state["local_sid"]
        r = requests.get(f"{API}/accounting/supplier-accounts/{sid}", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "account" in j and "paper_orders" in j and "orders" in j and "ledger" in j
        # supplier info from synthesized fallback
        assert j["account"]["supplier"]["name"] == state["supplier_name"]
        assert j["account"]["supplier"].get("is_local") is True
        # paper_orders array contains our order, orders array empty
        assert any(p["id"] == state["paper_order_id"] for p in j["paper_orders"]), \
            f"paper order not in detail: {[p.get('id') for p in j['paper_orders']]}"
        assert j["orders"] == [], f"expected empty marketplace orders, got {j['orders']}"
        # ledger has paper_order_debit entry
        assert any(l.get("kind") == "paper_order_debit" and l.get("reference_id") == state["paper_order_id"]
                   for l in j["ledger"]), \
            f"paper_order_debit ledger entry missing: {[l.get('kind') for l in j['ledger']]}"
        # outstanding balance sane
        assert j["account"]["outstanding_balance"] == 70.0

    def test_04_unpaid_invoices_lists_paper_order_fifo(self, h, state):
        sid = state["local_sid"]
        r = requests.get(f"{API}/accounting/supplier-accounts/{sid}/unpaid-invoices", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "invoices" in j and "count" in j and "total_outstanding" in j
        assert j["count"] >= 1
        assert j["total_outstanding"] == 70.0
        inv = next((i for i in j["invoices"] if i["id"] == state["paper_order_id"]), None)
        assert inv is not None
        assert inv["type"] == "paper"
        assert inv["outstanding"] == 70.0
        assert inv["paid_amount"] == 30.0

    def test_05_partial_fifo_payment_updates_paper_order(self, h, state):
        """POST /pay with 25 -> paper order remaining 70->45, amount_paid 30->55."""
        sid = state["local_sid"]
        r = requests.post(f"{API}/accounting/supplier-accounts/{sid}/pay",
                          json={"amount": 25.0, "notes": "TEST_partial FIFO"},
                          headers=h, timeout=15)
        assert r.status_code == 200, f"pay failed: {r.status_code} {r.text}"
        j = r.json()
        assert j["status"] == "ok"
        assert j["amount_applied"] == 25.0
        assert j["remaining_balance"] == 45.0
        assert j["supplier_status"] == "active"
        assert len(j["allocations"]) == 1
        a = j["allocations"][0]
        assert a["invoice_type"] == "paper"
        assert a["invoice_id"] == state["paper_order_id"]
        assert a["previous_outstanding"] == 70.0
        assert a["amount_applied"] == 25.0
        assert a["new_outstanding"] == 45.0
        assert a["fully_paid"] is False
        # Verify persistence: GET detail
        r2 = requests.get(f"{API}/accounting/supplier-accounts/{sid}", headers=h, timeout=15)
        j2 = r2.json()
        po = next(p for p in j2["paper_orders"] if p["id"] == state["paper_order_id"])
        assert po["remaining"] == 45.0
        assert po["amount_paid"] == 55.0
        assert po["payment_status"] == "partial"
        # Verify supplier_ledger has pharmacy_payment entry with allocations
        pmt = next((l for l in j2["ledger"] if l.get("kind") == "pharmacy_payment"), None)
        assert pmt is not None
        assert "allocations" in pmt and len(pmt["allocations"]) == 1
        assert pmt["amount"] == 25.0

    def test_06_full_remaining_payment_settles_paper_order(self, h, state):
        """Pay remaining 45 -> paper order paid, supplier outstanding=0."""
        sid = state["local_sid"]
        r = requests.post(f"{API}/accounting/supplier-accounts/{sid}/pay",
                          json={"amount": 45.0, "notes": "TEST_final settle"},
                          headers=h, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["amount_applied"] == 45.0
        assert j["remaining_balance"] == 0.0
        assert j["supplier_status"] == "paid"
        a = j["allocations"][0]
        assert a["fully_paid"] is True
        assert a["new_outstanding"] == 0.0
        # Verify paper order is fully paid
        r2 = requests.get(f"{API}/accounting/supplier-accounts/{sid}", headers=h, timeout=15)
        j2 = r2.json()
        assert j2["account"]["outstanding_balance"] == 0.0
        po = next(p for p in j2["paper_orders"] if p["id"] == state["paper_order_id"])
        assert po["remaining"] == 0.0
        assert po["payment_status"] == "paid"

    def test_07_overpay_rejected(self, h, state):
        """After settling, attempting to pay again -> 400 (no unpaid invoices)."""
        sid = state["local_sid"]
        r = requests.post(f"{API}/accounting/supplier-accounts/{sid}/pay",
                          json={"amount": 10.0}, headers=h, timeout=15)
        assert r.status_code == 400, r.text


# =====================================================================
# REGRESSION: marketplace supplier list still works + other flows intact
# =====================================================================

class TestRegression:

    def test_supplier_accounts_list_shape(self, h):
        r = requests.get(f"{API}/accounting/supplier-accounts", headers=h, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "items" in j and "count" in j and "total_outstanding" in j and "total_available_credit" in j
        # No mongo _id leakage
        for it in j["items"]:
            assert "_id" not in it

    def test_customers_still_works(self, h):
        r = requests.get(f"{API}/customers", headers=h, timeout=15)
        assert r.status_code == 200

    def test_accounting_summary_still_works(self, h):
        r = requests.get(f"{API}/accounting/summary", headers=h, timeout=15)
        assert r.status_code == 200
        assert "today" in r.json() and "month" in r.json()

    def test_paper_order_individual_pay_still_works(self, h):
        """Regression: /orders/paper/{id}/pay direct payment endpoint still works."""
        ts = int(time.time() * 1000)
        payload = {
            "image_base64": IMG_B64,
            "supplier_name": f"TEST_regression_paper {ts}",
            "invoice_date": "2026-01-15",
            "items": [{"name": f"TEST_item {ts}", "quantity": 1,
                       "purchase_price": 50.0, "selling_price": 65.0}],
            "total": 50.0,
            "amount_paid": 0.0,
        }
        r = requests.post(f"{API}/orders/paper", json=payload, headers=h, timeout=20)
        assert r.status_code in (200, 201), r.text
        po_id = r.json()["id"]
        # Pay directly on paper order (legacy endpoint)
        r2 = requests.post(f"{API}/orders/paper/{po_id}/pay",
                           json={"amount": 20.0}, headers=h, timeout=15)
        assert r2.status_code == 200, r2.text
        j2 = r2.json()
        assert j2.get("payment_status") == "partial"
        assert j2.get("remaining") == 30.0
