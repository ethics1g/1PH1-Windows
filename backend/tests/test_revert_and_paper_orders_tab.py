"""
Iteration 22 verification tests.

Covers:
1. Customer FIFO payment kept — GET /api/customers/{cid} returns payments
   sorted ASC (oldest → newest).
2. Supplier debts FULLY REVERTED:
   - GET /api/accounting/supplier-accounts/{sid} does NOT contain
     paper_orders / invoices_paid_total / paper_purchased / marketplace_purchased.
   - orders items should NOT have paid_amount, outstanding, payment_status,
     order_number enrichments.
   - POST /api/accounting/supplier-accounts/{sid}/pay → 404/405.
   - GET /api/accounting/supplier-accounts/{sid}/unpaid-invoices → 404/405.
   - outstanding_balance formula = total_purchased − credit_applied_total.
3. Paper orders list endpoint (used by /pharmacy-orders new tab) still works.
"""
import os
import time
import pytest
import requests

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
    assert tok, f"no token: {r.json()}"
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def state():
    return {}


def _buy(h, name, qty=100, cost=10, sell=20):
    r = requests.post(f"{API}/medicines/buy-v2",
                      json={"name": name, "quantity": qty,
                            "purchase_price": cost, "selling_price": sell},
                      headers=h, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["medicine"]["id"]


def _credit_sale(h, med_id, qty, cname, cphone, paid=0.0):
    r = requests.post(f"{API}/sales",
                      json={"items": [{"medicine_id": med_id, "quantity": qty}],
                            "payment_type": "credit",
                            "customer_name": cname, "customer_phone": cphone,
                            "amount_paid": paid},
                      headers=h, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# =====================================================================
# 1. Customer FIFO payment kept + payments sorted ASC
# =====================================================================
class TestCustomerFIFOKept:

    def test_01_create_customer_and_two_payments(self, h, state):
        med_id = _buy(h, f"TEST_REVERT_{int(time.time()*1000)}", qty=100, cost=10, sell=20)
        phone = f"TEST_R_{int(time.time())}"
        cname = "TEST_زبون رجوع"
        # Two credit sales with a time gap so FIFO is meaningful
        s1 = _credit_sale(h, med_id, 3, cname, phone)  # 60
        time.sleep(1.2)
        s2 = _credit_sale(h, med_id, 2, cname, phone)  # 40
        cid = s1["customer_id"]
        state["cid"] = cid
        # Payment 1
        r1 = requests.post(f"{API}/customers/{cid}/payment",
                           json={"amount": 20.0, "notes": "TEST_pay1"},
                           headers=h, timeout=15)
        assert r1.status_code == 200, r1.text
        assert "allocations" in r1.json(), "FIFO allocations missing"
        time.sleep(1.2)
        # Payment 2
        r2 = requests.post(f"{API}/customers/{cid}/payment",
                           json={"amount": 15.0, "notes": "TEST_pay2"},
                           headers=h, timeout=15)
        assert r2.status_code == 200, r2.text

    def test_02_payments_sorted_asc_oldest_first(self, h, state):
        cid = state["cid"]
        r = requests.get(f"{API}/customers/{cid}", headers=h, timeout=15)
        assert r.status_code == 200
        payments = r.json()["payments"]
        # Filter our TEST_ notes for deterministic assertion
        ours = [p for p in payments if (p.get("notes") or "").startswith("TEST_pay")]
        assert len(ours) >= 2, f"expected 2 test payments, found: {[p.get('notes') for p in payments]}"
        # ASC sort: TEST_pay1 must come before TEST_pay2
        # Verify by created_at
        dates = [p["created_at"] for p in payments]
        assert dates == sorted(dates), f"payments NOT ASC sorted: {dates}"
        # And also that our two markers appear in the right order
        marker_order = [p["notes"] for p in ours]
        assert marker_order == ["TEST_pay1", "TEST_pay2"], f"wrong order: {marker_order}"

    def test_03_fifo_allocations_still_present(self, h, state):
        cid = state["cid"]
        r = requests.get(f"{API}/customers/{cid}", headers=h, timeout=15)
        payments = r.json()["payments"]
        receive_pays = [p for p in payments if p.get("kind") == "receive"]
        assert receive_pays, "no receive payments recorded"
        # At least one must have allocations
        assert any("allocations" in p and p["allocations"] for p in receive_pays), \
            "no allocations found in any receive payment"


# =====================================================================
# 2. Supplier debts fully reverted
# =====================================================================
class TestSupplierReverted:

    def test_01_find_supplier_with_orders(self, h, state):
        r = requests.get(f"{API}/accounting/supplier-accounts", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        items = r.json().get("items", [])
        if not items:
            pytest.skip("No supplier accounts to test against")
        # Prefer one with outstanding > 0
        chosen = next((s for s in items if s.get("outstanding_balance", 0) > 0), items[0])
        state["sid"] = chosen["supplier_id"]
        state["initial_out"] = chosen.get("outstanding_balance", 0)
        state["total_purchased"] = chosen.get("total_purchased", 0)
        state["credit_applied"] = chosen.get("credit_applied_total", 0)

    def test_02_account_response_has_no_new_fields(self, h, state):
        sid = state["sid"]
        r = requests.get(f"{API}/accounting/supplier-accounts/{sid}",
                         headers=h, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        # Top-level keys: account, ledger, orders, returns (NO paper_orders)
        assert "paper_orders" not in j, f"paper_orders leaked at top level: keys={list(j.keys())}"
        acct = j["account"]
        # These enrichment fields should be GONE
        for forbidden in ("invoices_paid_total", "paper_purchased", "marketplace_purchased"):
            assert forbidden not in acct, f"forbidden field '{forbidden}' present in account: {acct}"
        # Required legacy fields still present
        for req in ("total_purchased", "credit_applied_total", "outstanding_balance",
                    "available_credit", "supplier_id", "pharmacy_id"):
            assert req in acct, f"missing legacy field '{req}': {acct}"

    def test_03_orders_have_no_enrichment_fields(self, h, state):
        sid = state["sid"]
        r = requests.get(f"{API}/accounting/supplier-accounts/{sid}",
                         headers=h, timeout=15)
        orders = r.json().get("orders", [])
        # If pharmacy has no orders with this supplier, skip — but we picked
        # a supplier with orders.
        if not orders:
            pytest.skip("no orders returned")
        allowed_keys = {"id", "total", "total_cost", "created_at", "completed_at",
                        "items", "commit_id"}
        for o in orders:
            # Enrichment fields must NOT be there
            for forbidden in ("paid_amount", "outstanding", "payment_status", "order_number"):
                assert forbidden not in o, \
                    f"forbidden field '{forbidden}' present in order {o.get('id')}: {list(o.keys())}"
            # Only allowed keys (subset check)
            extra = set(o.keys()) - allowed_keys
            assert not extra, f"unexpected extra keys in order: {extra}"

    def test_04_pay_endpoint_removed(self, h, state):
        sid = state["sid"]
        r = requests.post(f"{API}/accounting/supplier-accounts/{sid}/pay",
                          json={"amount": 1.0}, headers=h, timeout=15)
        assert r.status_code in (404, 405), \
            f"POST supplier-accounts/{sid}/pay should be removed, got {r.status_code}: {r.text}"

    def test_05_unpaid_invoices_endpoint_removed(self, h, state):
        sid = state["sid"]
        r = requests.get(f"{API}/accounting/supplier-accounts/{sid}/unpaid-invoices",
                         headers=h, timeout=15)
        assert r.status_code in (404, 405), \
            f"GET unpaid-invoices should be removed, got {r.status_code}: {r.text}"

    def test_06_outstanding_formula_matches_purchased_minus_credit(self, h, state):
        sid = state["sid"]
        r = requests.get(f"{API}/accounting/supplier-accounts/{sid}",
                         headers=h, timeout=15)
        acct = r.json()["account"]
        expected = max(0.0, round(acct["total_purchased"] - acct["credit_applied_total"], 2))
        assert abs(acct["outstanding_balance"] - expected) < 0.02, \
            f"formula mismatch: outstanding={acct['outstanding_balance']} vs expected={expected}"


# =====================================================================
# 3. Paper orders endpoint still works (feeds the new pharmacy-orders tab)
# =====================================================================
class TestPaperOrdersTabAPI:

    def test_01_list_paper_orders(self, h):
        r = requests.get(f"{API}/orders/paper", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "items" in j and "count" in j
        # Each item must NOT include full image (list projection excludes it)
        for it in j["items"]:
            assert "image_base64" not in it, \
                f"paper order list leaks image_base64: id={it.get('id')}"

    def test_02_paper_order_detail_returns_image(self, h):
        r = requests.get(f"{API}/orders/paper", headers=h, timeout=15)
        items = r.json().get("items", [])
        if not items:
            pytest.skip("no paper orders exist — cannot test detail")
        pid = items[0]["id"]
        r2 = requests.get(f"{API}/orders/paper/{pid}", headers=h, timeout=15)
        assert r2.status_code == 200, r2.text
        detail = r2.json()
        # image_base64 must exist (this is what UI shows)
        assert detail.get("image_base64"), "paper order detail missing archived image"


# =====================================================================
# 4. No regressions on sell/buy/returns/payment paper-order
# =====================================================================
class TestNoRegressions:

    def test_summary(self, h):
        r = requests.get(f"{API}/accounting/summary", headers=h, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "today" in j and "month" in j and "outstanding_debts" in j

    def test_customers_list(self, h):
        r = requests.get(f"{API}/customers", headers=h, timeout=15)
        assert r.status_code == 200

    def test_supplier_accounts_list(self, h):
        r = requests.get(f"{API}/accounting/supplier-accounts", headers=h, timeout=15)
        assert r.status_code == 200
        j = r.json()
        for it in j.get("items", []):
            # Also ensure no new fields leaked into the list projection
            for forbidden in ("invoices_paid_total", "paper_purchased", "marketplace_purchased"):
                assert forbidden not in it, f"forbidden field '{forbidden}' in list item: {it}"

    def test_pharmacy_orders_list(self, h):
        r = requests.get(f"{API}/pharmacy/orders", headers=h, timeout=15)
        assert r.status_code == 200

    def test_returns_list(self, h):
        r = requests.get(f"{API}/returns", headers=h, timeout=15)
        assert r.status_code == 200

    def test_paper_order_pay_endpoint_still_works(self, h):
        """POST /api/orders/paper/{id}/pay endpoint must still exist (kept)."""
        r = requests.get(f"{API}/orders/paper", headers=h, timeout=15)
        items = [i for i in r.json().get("items", []) if (i.get("remaining", 0) or 0) > 0]
        if not items:
            pytest.skip("no unpaid paper orders to test payment on")
        pid = items[0]["id"]
        r2 = requests.post(f"{API}/orders/paper/{pid}/pay",
                           json={"amount": 1.0, "notes": "TEST_paper_pay"},
                           headers=h, timeout=15)
        assert r2.status_code == 200, r2.text
        j = r2.json()
        assert j.get("status") == "ok"
        assert "remaining" in j and "payment_status" in j
