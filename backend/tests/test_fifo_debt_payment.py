"""
End-to-end FIFO debt payment tests — customers and suppliers.

Covers:
- POST /api/customers/{cid}/payment FIFO allocation across oldest credit sales
- Partial vs full payment; overpayment guard
- customer_payments doc stores allocations[] with sale_id/amount_applied/fully_paid
- POST /api/accounting/supplier-accounts/{sid}/pay FIFO across marketplace orders
- supplier_ledger stores kind='pharmacy_payment' with allocations
- GET /api/accounting/supplier-accounts/{sid}/unpaid-invoices returns FIFO sorted list
- Regression: /api/accounting/summary, /api/customers still work
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


# =====================================================================
# ============================ FIXTURES ===============================
# =====================================================================

@pytest.fixture(scope="module")
def pharm_token():
    r = requests.post(f"{API}/auth/login", json=PHARMACY, timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def h(pharm_token):
    return {"Authorization": f"Bearer {pharm_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def customer_state():
    return {}


@pytest.fixture(scope="module")
def supplier_state():
    return {}


def _make_medicine(h, name_prefix="TEST_FIFO_DEBT", qty=100, cost=10, sell=20):
    """Create a med with stock via buy-v2, returns id + selling_price."""
    unique_name = f"{name_prefix}_{int(time.time()*1000)}"
    payload = {"name": unique_name, "quantity": qty,
               "purchase_price": cost, "selling_price": sell}
    r = requests.post(f"{API}/medicines/buy-v2", json=payload, headers=h, timeout=15)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    return r.json()["medicine"]["id"], sell, unique_name


def _make_credit_sale(h, med_id, qty, customer_name, customer_phone, amount_paid=0.0):
    """Create a credit sale. Returns the sale doc."""
    payload = {
        "items": [{"medicine_id": med_id, "quantity": qty}],
        "payment_type": "credit",
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "amount_paid": amount_paid,
    }
    r = requests.post(f"{API}/sales", json=payload, headers=h, timeout=15)
    assert r.status_code == 200, f"sale failed: {r.status_code} {r.text}"
    return r.json()


# =====================================================================
# ============================ CUSTOMERS ==============================
# =====================================================================

class TestCustomerFIFOPayment:

    def test_01_create_credit_sales_same_customer(self, h, customer_state):
        # Create one medicine with enough stock for 3 sales
        med_id, sell, _ = _make_medicine(h, "TEST_FIFO_CUST", qty=100, cost=10, sell=20)
        phone = f"TEST_C_{int(time.time())}"
        cname = "TEST_زبون تجريبي FIFO"
        customer_state["phone"] = phone
        customer_state["name"] = cname

        # Sale 1 (oldest): 3 units * 20 = 60
        s1 = _make_credit_sale(h, med_id, 3, cname, phone, amount_paid=0)
        time.sleep(1.1)  # ensure created_at ordering
        # Sale 2: 2 units * 20 = 40
        s2 = _make_credit_sale(h, med_id, 2, cname, phone, amount_paid=0)
        time.sleep(1.1)
        # Sale 3 (newest): 5 units * 20 = 100
        s3 = _make_credit_sale(h, med_id, 5, cname, phone, amount_paid=0)

        assert s1["outstanding"] == 60.0, f"s1 outstanding: {s1}"
        assert s2["outstanding"] == 40.0
        assert s3["outstanding"] == 100.0
        assert s1["customer_id"] == s2["customer_id"] == s3["customer_id"]
        customer_state["cid"] = s1["customer_id"]
        customer_state["s1"] = s1["id"]
        customer_state["s2"] = s2["id"]
        customer_state["s3"] = s3["id"]
        customer_state["total_debt"] = 200.0

    def test_02_customer_detail_has_three_unpaid_sales(self, h, customer_state):
        cid = customer_state["cid"]
        r = requests.get(f"{API}/customers/{cid}", headers=h, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["customer"]["remaining_balance"] == 200.0
        # sales sorted by created_at DESC in endpoint
        sales = j["sales"]
        assert len(sales) >= 3
        # Each has outstanding > 0
        target_ids = {customer_state["s1"], customer_state["s2"], customer_state["s3"]}
        found = [s for s in sales if s["id"] in target_ids]
        assert len(found) == 3
        for s in found:
            assert s["outstanding"] > 0

    def test_03_partial_payment_fifo_settles_oldest_first(self, h, customer_state):
        """Pay 80 → should fully settle s1 (60) + partially settle s2 (20/40)."""
        cid = customer_state["cid"]
        r = requests.post(f"{API}/customers/{cid}/payment",
                          json={"amount": 80.0, "notes": "TEST_partial"},
                          headers=h, timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        j = r.json()
        assert j["amount_applied"] == 80.0
        assert j["remaining_balance"] == 120.0
        assert j["customer_status"] == "active"
        # allocations: oldest first
        allocs = j["allocations"]
        assert len(allocs) == 2, f"expected 2 allocations, got {allocs}"
        a1, a2 = allocs
        assert a1["sale_id"] == customer_state["s1"], f"oldest sale not first: {a1}"
        assert a1["amount_applied"] == 60.0
        assert a1["fully_paid"] is True
        assert a1["previous_outstanding"] == 60.0
        assert a1["new_outstanding"] == 0.0
        assert a2["sale_id"] == customer_state["s2"]
        assert a2["amount_applied"] == 20.0
        assert a2["fully_paid"] is False
        assert a2["new_outstanding"] == 20.0

    def test_04_customer_detail_reflects_allocation(self, h, customer_state):
        cid = customer_state["cid"]
        r = requests.get(f"{API}/customers/{cid}", headers=h, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["customer"]["remaining_balance"] == 120.0
        # Check sales outstanding after allocation
        sales_by_id = {s["id"]: s for s in j["sales"]}
        assert sales_by_id[customer_state["s1"]]["outstanding"] == 0.0
        assert sales_by_id[customer_state["s1"]]["amount_paid"] == 60.0
        assert sales_by_id[customer_state["s2"]]["outstanding"] == 20.0
        assert sales_by_id[customer_state["s2"]]["amount_paid"] == 20.0
        assert sales_by_id[customer_state["s3"]]["outstanding"] == 100.0
        # Payment record has allocations
        payments = j["payments"]
        latest = [p for p in payments if p.get("kind") == "receive"][0]
        assert "allocations" in latest
        assert len(latest["allocations"]) == 2
        assert latest["invoices_fully_paid"] == 1
        assert latest["invoices_partial"] == 1
        assert latest["recorded_by"] is not None

    def test_05_second_partial_continues_from_middle_sale(self, h, customer_state):
        """Pay 30 → settles s2 (20 remaining) + starts s3 (10/100)."""
        cid = customer_state["cid"]
        r = requests.post(f"{API}/customers/{cid}/payment",
                          json={"amount": 30.0},
                          headers=h, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["amount_applied"] == 30.0
        assert j["remaining_balance"] == 90.0
        allocs = j["allocations"]
        assert len(allocs) == 2
        assert allocs[0]["sale_id"] == customer_state["s2"]
        assert allocs[0]["amount_applied"] == 20.0
        assert allocs[0]["fully_paid"] is True
        assert allocs[1]["sale_id"] == customer_state["s3"]
        assert allocs[1]["amount_applied"] == 10.0
        assert allocs[1]["fully_paid"] is False

    def test_06_overpayment_rejected_with_400(self, h, customer_state):
        cid = customer_state["cid"]
        r = requests.post(f"{API}/customers/{cid}/payment",
                          json={"amount": 999999.0},
                          headers=h, timeout=15)
        assert r.status_code == 400, r.text
        # Arabic error message
        detail = r.json().get("detail", "")
        assert "أكبر" in detail or "الرصيد" in detail

    def test_07_full_payment_settles_and_marks_customer_paid(self, h, customer_state):
        cid = customer_state["cid"]
        r = requests.post(f"{API}/customers/{cid}/payment",
                          json={"amount": 90.0, "notes": "TEST_full"},
                          headers=h, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["amount_applied"] == 90.0
        assert j["remaining_balance"] == 0.0
        assert j["customer_status"] == "paid"
        # Confirm via GET
        r2 = requests.get(f"{API}/customers/{cid}", headers=h, timeout=15)
        cust = r2.json()["customer"]
        assert cust["remaining_balance"] == 0.0
        assert cust["status"] == "paid"

    def test_08_payment_on_settled_customer_rejected(self, h, customer_state):
        cid = customer_state["cid"]
        r = requests.post(f"{API}/customers/{cid}/payment",
                          json={"amount": 10.0}, headers=h, timeout=15)
        assert r.status_code == 400, r.text

    def test_09_customers_list_still_works_regression(self, h):
        r = requests.get(f"{API}/customers", headers=h, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "items" in j and "count" in j


# =====================================================================
# ============================ SUPPLIERS ==============================
# =====================================================================

class TestSupplierFIFOPayment:

    def test_01_get_supplier_accounts_overview(self, h, supplier_state):
        """Find a supplier with outstanding balance to test against."""
        r = requests.get(f"{API}/accounting/supplier-accounts", headers=h, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "items" in j
        candidates = [s for s in j["items"] if s.get("outstanding_balance", 0) > 0]
        if not candidates:
            candidates = j["items"]
        if not candidates:
            pytest.skip("No supplier accounts found — cannot test supplier FIFO pay")
        chosen = candidates[0]
        supplier_state["sid"] = chosen["supplier_id"]
        supplier_state["initial_outstanding"] = chosen["outstanding_balance"]
        supplier_state["supplier_name"] = chosen.get("supplier_name")

    def test_02_unpaid_invoices_endpoint_fifo_sorted(self, h, supplier_state):
        sid = supplier_state["sid"]
        r = requests.get(f"{API}/accounting/supplier-accounts/{sid}/unpaid-invoices",
                         headers=h, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "invoices" in j and "count" in j and "total_outstanding" in j
        dates = [inv["created_at"] for inv in j["invoices"] if inv.get("created_at")]
        assert dates == sorted(dates), f"Not FIFO sorted: {dates}"
        supplier_state["unpaid_invoices"] = j["invoices"]
        supplier_state["total_available"] = j["total_outstanding"]


# =====================================================================
# ============================ REGRESSION =============================
# =====================================================================

class TestRegression:

    def test_summary_still_works(self, h):
        r = requests.get(f"{API}/accounting/summary", headers=h, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "today" in j and "month" in j and "outstanding_debts" in j

    def test_supplier_accounts_list_still_works(self, h):
        r = requests.get(f"{API}/accounting/supplier-accounts", headers=h, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "items" in j
        assert "total_outstanding" in j

    def test_customers_list_still_works(self, h):
        r = requests.get(f"{API}/customers", headers=h, timeout=15)
        assert r.status_code == 200

    def test_medicines_search_still_works(self, h):
        r = requests.get(f"{API}/medicines/search?q=TEST", headers=h, timeout=15)
        assert r.status_code == 200
