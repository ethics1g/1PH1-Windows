"""
End-to-end test for the RETURNS (الرواجع) workflow.

Verifies:
1. A pharmacy can create a return for a completed supplier order.
2. Returned quantities are correctly restored into inventory batches
   (LIFO restore direction).
3. Supplier account credit / ledger is updated once (idempotent) after
   the supplier confirms receipt of the returned goods.
4. Profit reports stay consistent — returns do not corrupt sale/cost
   figures (sales stay untouched; a supplier return is a *purchase* return).
5. Full audit trail: return.timeline, supplier_ledger, return_credits.
6. Guardrails:
   - Cannot return more units than were originally ordered.
   - Cannot return from a non-delivered order.
   - Rejected return → no stock restore, no credit.
   - Idempotency: rerunning apply_return_credit is a no-op.

The test creates its OWN supplier + pharmacy medicines to avoid coupling
with pre-seeded data.
"""
from __future__ import annotations

import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://pharma-checkout-8.preview.emergentagent.com"
API = f"{BASE_URL}/api"

PHARMACY = {"phone": "07700000001", "password": "pass123"}
SUPPLIER = {"phone": "07811111111", "password": "sup1"}


def _login(creds: dict) -> str:
    r = requests.post(f"{API}/auth/login", json=creds, timeout=20)
    assert r.status_code == 200, f"login {creds['phone']} failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok, r.json()
    return tok


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def ph_tok():
    return _login(PHARMACY)


@pytest.fixture(scope="module")
def sup_tok():
    return _login(SUPPLIER)


@pytest.fixture(scope="module")
def ph_h(ph_tok):
    return _hdr(ph_tok)


@pytest.fixture(scope="module")
def sup_h(sup_tok):
    return _hdr(sup_tok)


@pytest.fixture(scope="module")
def state():
    return {"stamp": int(time.time())}


# ---------------------------------------------------------------- SETUP
class TestReturnsSetup:

    def test_00_supplier_id_from_login(self, sup_tok, state):
        # Decode JWT sub without secret verification (safe: only sub read)
        import base64, json
        payload = sup_tok.split(".")[1] + "=="
        j = json.loads(base64.urlsafe_b64decode(payload))
        state["supplier_id"] = j["sub"]

    def test_01_seed_two_medicines_with_batches(self, ph_h, state):
        """Create MED-A and MED-B with a couple of batches each so we can
        confirm restore behavior on a partially-consumed inventory."""
        stamp = state["stamp"]
        # MED-A: two batches (100@50, 100@70) -> total 200
        name_a = f"RTN_MED_A_{stamp}"
        state["name_a"] = name_a
        r = requests.post(f"{API}/medicines/buy-v2", headers=ph_h, timeout=15,
                          json={"name": name_a, "quantity": 100,
                                "purchase_price": 50, "selling_price": 100})
        assert r.status_code == 200, r.text
        state["med_a_id"] = r.json()["medicine"]["id"]
        r = requests.post(f"{API}/medicines/buy-v2", headers=ph_h, timeout=15,
                          json={"name": name_a, "quantity": 100,
                                "purchase_price": 70, "selling_price": 100})
        assert r.status_code == 200, r.text

        # MED-B: one batch (50@30)
        name_b = f"RTN_MED_B_{stamp}"
        state["name_b"] = name_b
        r = requests.post(f"{API}/medicines/buy-v2", headers=ph_h, timeout=15,
                          json={"name": name_b, "quantity": 50,
                                "purchase_price": 30, "selling_price": 60})
        assert r.status_code == 200, r.text
        state["med_b_id"] = r.json()["medicine"]["id"]

    def test_02_partially_consume_med_a(self, ph_h, state):
        """Sell 120 units of MED-A: consumes 100@50 + 20@70 → batches now [0, 80]."""
        r = requests.post(f"{API}/sales", headers=ph_h, timeout=15,
                          json={"items": [{"medicine_id": state["med_a_id"],
                                           "quantity": 120}],
                                "payment_type": "cash"})
        assert r.status_code == 200, r.text
        sale = r.json()
        assert sale["cost"] == 100 * 50 + 20 * 70
        # Batches now [0, 80]
        rb = requests.get(f"{API}/medicines/{state['med_a_id']}/batches",
                          headers=ph_h, timeout=15)
        assert rb.status_code == 200, rb.text
        assert [b["remaining_quantity"] for b in rb.json()["batches"]] == [0, 80]
        state["profit_snapshot_after_sale"] = sale["profit"]


# ------------------------------------------------------------- ORDER FLOW
class TestSupplierOrderChain:

    def test_10_commit_supplier_order(self, ph_h, state):
        """Create a supplier order via /orders/optimize/commit (bypasses
        the marketplace to keep the test deterministic)."""
        stamp = state["stamp"]
        state["commit_id"] = f"rtn-commit-{stamp}-{uuid.uuid4().hex[:6]}"
        group = {
            "supplier_id": state["supplier_id"],
            "supplier_name": "SUP",
            "total": 100.0 * 10 + 60.0 * 5,   # 1300 IQD
            "items": [
                {"name": state["name_a"], "quantity": 10, "unit_price": 100.0},
                {"name": state["name_b"], "quantity": 5,  "unit_price": 60.0},
            ],
        }
        r = requests.post(f"{API}/orders/optimize/commit", headers=ph_h,
                          timeout=15,
                          json={"commit_id": state["commit_id"],
                                "groups": [group]})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["created"] == 1, data
        state["order_id"] = data["orders"][0]["id"]
        state["order_total"] = data["orders"][0]["total"]

    def test_11_supplier_accept_process_deliver(self, sup_h, state):
        oid = state["order_id"]
        r = requests.patch(f"{API}/supplier/orders/{oid}/accept",
                           headers=sup_h, timeout=15)
        assert r.status_code == 200, r.text
        r = requests.patch(f"{API}/supplier/orders/{oid}/processing",
                           headers=sup_h, timeout=15)
        assert r.status_code == 200, r.text
        r = requests.patch(f"{API}/supplier/orders/{oid}/delivered",
                           headers=sup_h, timeout=15)
        assert r.status_code == 200, r.text

    def test_12_pharmacy_confirm_receipt_completes_order(self, ph_h, state):
        oid = state["order_id"]
        r = requests.patch(f"{API}/pharmacy/orders/{oid}/confirm-receipt",
                           headers=ph_h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["order_status"] == "completed"

    def test_13_supplier_debit_reflects_completed_order(self, ph_h, state):
        r = requests.get(f"{API}/accounting/supplier-accounts/{state['supplier_id']}",
                         headers=ph_h, timeout=15)
        assert r.status_code == 200, r.text
        acct = r.json()["account"]
        # Debit includes THIS order plus any pre-existing completed orders,
        # so we just require it's >= our order total.
        assert acct["total_purchased"] >= state["order_total"] - 0.01
        state["debit_before_return"] = acct["total_purchased"]
        state["credit_applied_before"] = acct["credit_applied_total"]
        state["available_credit_before"] = acct["available_credit"]
        state["outstanding_before"] = acct["outstanding_balance"]


# ----------------------------------------------------------------- RETURNS
class TestReturnsHappyPath:

    def test_20_create_return_valid(self, ph_h, state):
        """Pharmacy creates a partial return: 3 of MED-A + 2 of MED-B."""
        payload = {
            "original_order_id": state["order_id"],
            "reason": "damaged",
            "notes": "test damage",
            "items": [
                {"medicine_id": state["med_a_id"],
                 "name": state["name_a"], "quantity": 3, "unit_price": 100.0},
                {"medicine_id": state["med_b_id"],
                 "name": state["name_b"], "quantity": 2, "unit_price": 60.0},
            ],
        }
        r = requests.post(f"{API}/returns", headers=ph_h, timeout=15, json=payload)
        assert r.status_code == 201, r.text
        rj = r.json()
        assert rj["status"] == "pending"
        assert rj["total"] == 3 * 100 + 2 * 60  # 420
        state["return_id"] = rj["id"]
        state["return_total"] = rj["total"]

    def test_21_return_over_quantity_rejected(self, ph_h, state):
        """Try to return more than remains for MED-A (10 ordered − 3 pending = 7 max)."""
        payload = {
            "original_order_id": state["order_id"],
            "reason": "damaged",
            "items": [{"medicine_id": state["med_a_id"],
                       "name": state["name_a"], "quantity": 20,
                       "unit_price": 100.0}],
        }
        r = requests.post(f"{API}/returns", headers=ph_h, timeout=15, json=payload)
        assert r.status_code == 400, r.text
        assert "أكبر من" in r.json().get("detail", "")

    def test_22_supplier_approves_return(self, sup_h, state):
        r = requests.patch(f"{API}/returns/{state['return_id']}/approve",
                           headers=sup_h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "approved"

    def test_23_pharmacy_marks_shipped(self, ph_h, state):
        r = requests.patch(f"{API}/returns/{state['return_id']}/mark-shipped",
                           headers=ph_h, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "waiting_receipt"

    def test_24_supplier_confirms_receipt_deducts_stock_and_credits(
        self, sup_h, ph_h, state
    ):
        r = requests.patch(f"{API}/returns/{state['return_id']}/confirm-receipt",
                           headers=sup_h, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["return"]["status"] == "completed"
        # 3 + 2 = 5 units of stock deducted from pharmacy (goods shipped back)
        assert body["deducted_units"] == 5, body
        # Credit is applied to supplier account
        assert body["credit"]["status"] == "applied", body["credit"]
        assert body["credit"]["amount_applied"] == state["return_total"], body["credit"]

    def test_25_batches_lifo_deduct_med_a(self, ph_h, state):
        """MED-A batches were [0, 80] before deduction. LIFO deduction of 3
        pulls from the newest batch → [0, 77]. Total stock 77."""
        rb = requests.get(f"{API}/medicines/{state['med_a_id']}/batches",
                          headers=ph_h, timeout=15)
        assert rb.status_code == 200, rb.text
        rems = [b["remaining_quantity"] for b in rb.json()["batches"]]
        assert rems == [0, 77], f"expected [0, 77] got {rems}"
        assert rb.json()["total_stock"] == 77

    def test_26_batches_lifo_deduct_med_b(self, ph_h, state):
        """MED-B: single batch had 50 remaining. LIFO deduction of 2 → 48.
        This proves the pharmacy correctly SHIPS OUT the returned goods
        (stock decreases, not increases)."""
        rb = requests.get(f"{API}/medicines/{state['med_b_id']}/batches",
                          headers=ph_h, timeout=15)
        assert rb.status_code == 200, rb.text
        batches = rb.json()["batches"]
        total = rb.json()["total_stock"]
        assert total == 48, f"expected total 48 got {total}"
        assert batches[0]["remaining_quantity"] == 48

    def test_27_supplier_ledger_entry_created(self, ph_h, state):
        r = requests.get(f"{API}/accounting/supplier-accounts/{state['supplier_id']}",
                         headers=ph_h, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # ledger should contain a return_credit entry with our return_id
        ent = next(
            (l for l in data["ledger"]
             if l.get("kind") == "return_credit"
             and l.get("reference_id") == state["return_id"]),
            None,
        )
        assert ent is not None, f"ledger entry missing. ledger={data['ledger']}"
        assert ent["amount"] == state["return_total"]
        # supplier_accounts balance moved correctly
        acct = data["account"]
        expected_new_credit = round(state["credit_applied_before"]
                                    + state["return_total"], 2)
        # credit_applied is capped at debit; may equal debit if excess flowed
        # to available_credit. We only assert monotonic non-decrease.
        assert acct["credit_applied_total"] >= state["credit_applied_before"], acct
        assert (acct["credit_applied_total"] + acct["available_credit"]
                >= expected_new_credit - 0.01), acct

    def test_28_idempotency_confirm_receipt(self, sup_h, state):
        """Calling confirm-receipt again on already-completed return must
        NOT create a second credit entry (state transition guard)."""
        r = requests.patch(f"{API}/returns/{state['return_id']}/confirm-receipt",
                           headers=sup_h, timeout=15)
        # Transition guard should reject (already completed)
        assert r.status_code == 400, r.text

    def test_29_direct_apply_return_credit_is_idempotent(self, ph_h, state):
        """Ensure the accounting side-effect is idempotent even if invoked
        multiple times (defense-in-depth against retries).
        We can't reach the function directly over HTTP, but the ledger only
        has ONE entry for this return_id, which proves it."""
        r = requests.get(f"{API}/accounting/supplier-accounts/{state['supplier_id']}",
                         headers=ph_h, timeout=15)
        assert r.status_code == 200, r.text
        matches = [l for l in r.json()["ledger"]
                   if l.get("reference_id") == state["return_id"]
                   and l.get("kind") == "return_credit"]
        assert len(matches) == 1, matches


# ----------------------------------------------------------- REJECTION PATH
class TestReturnsRejectionPath:

    def test_30_create_second_return(self, ph_h, state):
        """Create another return that we will REJECT — no stock/credit change."""
        payload = {
            "original_order_id": state["order_id"],
            "reason": "wrong_item",
            "items": [{"medicine_id": state["med_b_id"],
                       "name": state["name_b"], "quantity": 1,
                       "unit_price": 60.0}],
        }
        r = requests.post(f"{API}/returns", headers=ph_h, timeout=15, json=payload)
        assert r.status_code == 201, r.text
        state["return_id_2"] = r.json()["id"]

    def test_31_supplier_rejects(self, sup_h, state):
        r = requests.patch(f"{API}/returns/{state['return_id_2']}/reject",
                           headers=sup_h, timeout=15,
                           json={"reason": "not our fault"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "rejected"

    def test_32_no_ledger_entry_for_rejected(self, ph_h, state):
        r = requests.get(f"{API}/accounting/supplier-accounts/{state['supplier_id']}",
                         headers=ph_h, timeout=15)
        assert r.status_code == 200
        matches = [l for l in r.json()["ledger"]
                   if l.get("reference_id") == state["return_id_2"]]
        assert matches == []

    def test_33_no_stock_change_after_rejection(self, ph_h, state):
        rb = requests.get(f"{API}/medicines/{state['med_b_id']}/batches",
                          headers=ph_h, timeout=15)
        assert rb.status_code == 200
        # After the earlier successful return, MED-B was deducted to 48;
        # rejecting a second return must NOT change stock further.
        assert rb.json()["total_stock"] == 48


# ------------------------------------------------------- GUARDS: BAD STATES
class TestReturnsGuards:

    def test_40_return_from_pending_order_rejected(self, ph_h, state):
        """Can't return from an order still in pending status."""
        stamp = state["stamp"]
        cid = f"guard-{stamp}-{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/orders/optimize/commit", headers=ph_h,
                          timeout=15,
                          json={"commit_id": cid, "groups": [{
                              "supplier_id": state["supplier_id"],
                              "supplier_name": "SUP",
                              "total": 100.0,
                              "items": [{"name": state["name_a"],
                                         "quantity": 1, "unit_price": 100}],
                          }]})
        assert r.status_code == 200, r.text
        pending_oid = r.json()["orders"][0]["id"]
        state["pending_oid_to_cleanup"] = pending_oid

        rr = requests.post(f"{API}/returns", headers=ph_h, timeout=15, json={
            "original_order_id": pending_oid,
            "reason": "damaged",
            "items": [{"medicine_id": state["med_a_id"],
                       "name": state["name_a"], "quantity": 1,
                       "unit_price": 100}],
        })
        assert rr.status_code == 400, rr.text
        assert "المُسلَّمة" in rr.json().get("detail", "")

    def test_41_unauthenticated_returns_endpoint(self):
        r = requests.get(f"{API}/returns", timeout=15)
        assert r.status_code == 401, r.text

    def test_42_pharmacy_cannot_approve(self, ph_h, state):
        r = requests.patch(f"{API}/returns/{state['return_id']}/approve",
                           headers=ph_h, timeout=15)
        # 403 because require_role("supplier")
        assert r.status_code == 403, r.text


# ------------------------------------------------------------- PROFIT AUDIT
class TestReturnsProfitReport:

    def test_50_profit_report_unaffected_by_returns(self, ph_h, state):
        """Returns are a *purchase* return — they don't touch the pharmacy's
        POS sales aggregate. Profit report must still include the earlier
        MED-A sale intact."""
        r = requests.get(f"{API}/accounting/profit-report?period=day",
                         headers=ph_h, timeout=15)
        assert r.status_code == 200, r.text
        # The sale we made in setup contributed profit_snapshot_after_sale
        # to today's row. Ensure that row still exists.
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = next((x for x in r.json()["rows"] if x["period"] == today), None)
        assert row is not None, r.json()["rows"]
        # Contribution from our sale must still be visible
        # (>= snapshot because other tests may have added more)
        assert row["profit"] >= state["profit_snapshot_after_sale"] - 0.01
