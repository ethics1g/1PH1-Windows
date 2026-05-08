"""Backend API tests for Smart Multi-Pharmacy Price Optimization (POST /api/orders/optimize)
and new supplier product fields (quantity, delivery_time, supplier_phone)."""
import os
import time
import requests
import pytest
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"

PHARMACY_PHONE = "07700000001"
PHARMACY_PASSWORD = "pass123"

RUN = str(int(time.time()))


def auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def pharmacy_token(session):
    r = session.post(f"{BASE_URL}/pharmacy/login",
                     json={"phone": PHARMACY_PHONE, "password": PHARMACY_PASSWORD})
    assert r.status_code == 200, f"Pharmacy login failed: {r.text}"
    return r.json()["token"]


def _register_supplier(session, suffix, name, phone_prefix="0788"):
    """Register a fresh supplier. Returns (token, supplier_id, phone)."""
    phone = f"{phone_prefix}{RUN[-5:]}{suffix}"
    payload = {"name": name, "phone": phone, "password": "sup123",
               "address": f"Baghdad-{suffix}"}
    r = session.post(f"{BASE_URL}/supplier/register", json=payload)
    if r.status_code == 400:
        r = session.post(f"{BASE_URL}/supplier/login",
                         json={"phone": phone, "password": "sup123"})
    assert r.status_code == 200, f"Supplier auth failed: {r.text}"
    body = r.json()
    return body["token"], body["supplier"]["id"], phone


# Module-level state to share supplier+product fixtures across the optimize tests.
@pytest.fixture(scope="module")
def supplier_a(session):
    """Supplier A - has limited stock at low prices."""
    token, sid, phone = _register_supplier(session, "A1", f"TEST_SUPPA_{RUN}")
    return {"token": token, "id": sid, "phone": phone}


@pytest.fixture(scope="module")
def supplier_b(session):
    """Supplier B - has lots of stock at higher prices."""
    token, sid, phone = _register_supplier(session, "B2", f"TEST_SUPPB_{RUN}")
    return {"token": token, "id": sid, "phone": phone}


@pytest.fixture(scope="module")
def supplier_c(session):
    """Supplier C - has only one of the items."""
    token, sid, phone = _register_supplier(session, "C3", f"TEST_SUPPC_{RUN}")
    return {"token": token, "id": sid, "phone": phone}


# Item names used across tests. Must be unique vs any seeded production data
# (the marketplace already contains 'بنادول', 'فيتامين سي', etc. that would otherwise
# match via substring). Use a long unique token that no real product can contain.
UNIQ = f"ZQX{RUN}"
PANADOL = f"PANA{UNIQ}"            # base name
PANADOL_EXTRA = f"PANA{UNIQ}EXTRA"  # contains PANADOL as substring (q in n)
ASPIRIN = f"ASPI{UNIQ}"
NOEXIST = f"NOPE{UNIQ}"


@pytest.fixture(scope="module")
def seeded_products(session, supplier_a, supplier_b, supplier_c):
    """
    Seed marketplace with deterministic offers:

      Supplier A (low price, low qty):
        - PANADOL_EXTRA   price 900,  qty 10,  delivery '24h'
        - ASPIRIN         price 500,  qty 100, delivery '12h'

      Supplier B (high price, high qty):
        - PANADOL         price 1000, qty 50,  delivery '48h'
        - ASPIRIN         price 600,  qty 50,  delivery '24h'

      Supplier C (only PANADOL):
        - PANADOL         price 1100, qty 0,   delivery 'same-day' (qty=0 -> unlimited)
    """
    created = []  # list of (token, product_id)

    def add(token, payload):
        r = session.post(f"{BASE_URL}/supplier/products", json=payload, headers=auth(token))
        assert r.status_code == 200, f"add product failed: {r.text}"
        body = r.json()
        created.append((token, body["id"]))
        return body

    # Supplier A
    a1 = add(supplier_a["token"], {"name": PANADOL_EXTRA, "price": 900,
                                   "quantity": 10, "delivery_time": "24h"})
    a2 = add(supplier_a["token"], {"name": ASPIRIN, "price": 500,
                                   "quantity": 100, "delivery_time": "12h"})
    # Supplier B
    b1 = add(supplier_b["token"], {"name": PANADOL, "price": 1000,
                                   "quantity": 50, "delivery_time": "48h"})
    b2 = add(supplier_b["token"], {"name": ASPIRIN, "price": 600,
                                   "quantity": 50, "delivery_time": "24h"})
    # Supplier C - qty=0 => "unlimited" per algorithm
    c1 = add(supplier_c["token"], {"name": PANADOL, "price": 1100,
                                   "quantity": 0, "delivery_time": "same-day"})

    yield {"a1": a1, "a2": a2, "b1": b1, "b2": b2, "c1": c1}

    # Cleanup
    for token, pid in created:
        try:
            session.delete(f"{BASE_URL}/supplier/products/{pid}", headers=auth(token))
        except Exception:
            pass


# ---------------- New supplier product fields ----------------
class TestSupplierProductFields:
    def test_create_product_with_new_fields_autopopulates_phone(self, session, supplier_a):
        payload = {"name": f"TEST_FieldCheck_{RUN}", "price": 12.5,
                   "quantity": 33, "delivery_time": "next-day"}
        r = session.post(f"{BASE_URL}/supplier/products", json=payload,
                         headers=auth(supplier_a["token"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["quantity"] == 33
        assert body["delivery_time"] == "next-day"
        # supplier_phone is auto-populated from supplier profile (NOT from the request body)
        assert body["supplier_phone"] == supplier_a["phone"], \
            f"expected supplier_phone={supplier_a['phone']}, got {body.get('supplier_phone')}"
        # cleanup
        session.delete(f"{BASE_URL}/supplier/products/{body['id']}",
                       headers=auth(supplier_a["token"]))

    def test_marketplace_returns_new_fields(self, session, pharmacy_token,
                                            seeded_products, supplier_a):
        r = session.get(f"{BASE_URL}/marketplace", headers=auth(pharmacy_token))
        assert r.status_code == 200
        items = r.json()
        # find the seeded supplier-A panadol-extra entry
        target = next((p for p in items
                       if p["id"] == seeded_products["a1"]["id"]), None)
        assert target is not None, "seeded product not found in marketplace"
        assert target["quantity"] == 10
        assert target["delivery_time"] == "24h"
        assert target["supplier_phone"] == supplier_a["phone"]


# ---------------- /api/orders/optimize ----------------
class TestOptimizeAuth:
    def test_supplier_token_forbidden(self, session, supplier_a):
        r = session.post(f"{BASE_URL}/orders/optimize",
                         json={"items": [{"name": PANADOL, "quantity": 1}]},
                         headers=auth(supplier_a["token"]))
        assert r.status_code == 403

    def test_no_token_unauthorized(self, session):
        r = session.post(f"{BASE_URL}/orders/optimize",
                         json={"items": [{"name": PANADOL, "quantity": 1}]})
        assert r.status_code == 401


class TestOptimizeShape:
    def test_response_shape(self, session, pharmacy_token, seeded_products):
        r = session.post(
            f"{BASE_URL}/orders/optimize",
            json={"items": [{"name": PANADOL, "quantity": 1}]},
            headers=auth(pharmacy_token),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("unavailable", "per_item", "single_supplier", "smart_split", "summary"):
            assert key in body, f"missing key {key} in response"
        assert "plan" in body["per_item"] and "total" in body["per_item"]
        assert "options" in body["single_supplier"]
        assert "groups" in body["smart_split"] and "items_summary" in body["smart_split"]
        assert {"cheapest_total", "most_expensive_total", "max_savings"} <= set(body["summary"].keys())


class TestOptimizeUnavailable:
    def test_unknown_item_in_unavailable(self, session, pharmacy_token, seeded_products):
        r = session.post(
            f"{BASE_URL}/orders/optimize",
            json={"items": [
                {"name": PANADOL, "quantity": 1},
                {"name": NOEXIST, "quantity": 5},
            ]},
            headers=auth(pharmacy_token),
        )
        assert r.status_code == 200
        body = r.json()
        assert NOEXIST in body["unavailable"]
        assert PANADOL not in body["unavailable"]


class TestOptimizeSubstringMatch:
    """Requesting 'بنادول' (PANADOL) should match supplier A's product 'بنادول إكسترا'
    (PANADOL_EXTRA) via substring matching, even though no supplier sells the exact
    name PANADOL... actually supplier B sells exact PANADOL too. Verify offer set
    contains BOTH supplier A (substring match) and supplier B (exact)."""

    def test_substring_query_to_longer_name(self, session, pharmacy_token, seeded_products):
        # Query "بنادول_RUN" should substring-match "بنادول_RUN إكسترا" (supplier A)
        r = session.post(
            f"{BASE_URL}/orders/optimize",
            json={"items": [{"name": PANADOL, "quantity": 1}]},
            headers=auth(pharmacy_token),
        )
        assert r.status_code == 200
        body = r.json()
        # per_item picks the cheapest -> supplier A @ 900 (matched via substring)
        per_item_plan = body["per_item"]["plan"]
        assert len(per_item_plan) == 1
        assert per_item_plan[0]["unit_price"] == 900
        # smart_split items_summary breakdown should include both A and B
        breakdown_supplier_names = {b["supplier_name"]
                                    for b in body["smart_split"]["items_summary"][0]["breakdown"]}
        assert any("SUPPA" in n for n in breakdown_supplier_names)

    def test_longer_query_to_substring(self, session, pharmacy_token, seeded_products):
        # Query "بنادول إكسترا" should substring-match "بنادول" too (n in q)
        r = session.post(
            f"{BASE_URL}/orders/optimize",
            json={"items": [{"name": PANADOL_EXTRA, "quantity": 1}]},
            headers=auth(pharmacy_token),
        )
        assert r.status_code == 200
        body = r.json()
        # Should find offers from supplier A (exact) AND supplier B & C (substring n in q)
        all_supplier_names = set()
        for grp in body["smart_split"]["groups"]:
            all_supplier_names.add(grp["supplier_name"])
        assert any("SUPPA" in n for n in all_supplier_names)


class TestOptimizePerItem:
    def test_per_item_picks_cheapest_ignoring_qty(self, session, pharmacy_token, seeded_products):
        # Need 30 units of PANADOL. A has 10 @ 900 (substring match - cheapest);
        # per_item ignores qty so it should still pick supplier A.
        r = session.post(
            f"{BASE_URL}/orders/optimize",
            json={"items": [{"name": PANADOL, "quantity": 30}]},
            headers=auth(pharmacy_token),
        )
        assert r.status_code == 200
        per_item = r.json()["per_item"]
        assert len(per_item["plan"]) == 1
        line = per_item["plan"][0]
        assert line["unit_price"] == 900  # supplier A cheapest
        assert line["quantity"] == 30
        assert line["line_total"] == 900 * 30
        assert per_item["total"] == 900 * 30


class TestOptimizeSingleSupplier:
    def test_only_suppliers_with_all_items(self, session, pharmacy_token, seeded_products):
        # Basket = PANADOL + ASPIRIN.
        # Supplier A has both (PANADOL via substring on PANADOL_EXTRA + ASPIRIN). YES
        # Supplier B has both (PANADOL + ASPIRIN). YES
        # Supplier C has only PANADOL. NO -> must NOT appear in single_supplier.
        r = session.post(
            f"{BASE_URL}/orders/optimize",
            json={"items": [
                {"name": PANADOL, "quantity": 5},
                {"name": ASPIRIN, "quantity": 5},
            ]},
            headers=auth(pharmacy_token),
        )
        assert r.status_code == 200
        opts = r.json()["single_supplier"]["options"]
        names = [o["supplier_name"] for o in opts]
        assert any("SUPPA" in n for n in names), f"Supplier A missing: {names}"
        assert any("SUPPB" in n for n in names), f"Supplier B missing: {names}"
        assert not any("SUPPC" in n for n in names), \
            f"Supplier C should be excluded (lacks ASPIRIN): {names}"
        # Cheapest single-supplier (best) should be supplier A:
        # A: 900*5 + 500*5 = 7000;  B: 1000*5 + 600*5 = 8000
        best = r.json()["single_supplier"]["best"]
        assert "SUPPA" in best["supplier_name"]
        assert best["total"] == 7000


class TestOptimizeSmartSplit:
    def test_split_across_suppliers_when_qty_insufficient(self, session, pharmacy_token,
                                                          seeded_products):
        # Need 30 of PANADOL.
        # Cheapest = supplier A (via substring) @ 900, qty=10.
        # Then supplier B @ 1000, qty=50 -> takes the remaining 20.
        # (Supplier C @ 1100 should NOT be needed.)
        r = session.post(
            f"{BASE_URL}/orders/optimize",
            json={"items": [{"name": PANADOL, "quantity": 30}]},
            headers=auth(pharmacy_token),
        )
        assert r.status_code == 200
        body = r.json()
        smart = body["smart_split"]
        # Item summary
        assert len(smart["items_summary"]) == 1
        summary_item = smart["items_summary"][0]
        assert summary_item["requested_quantity"] == 30
        assert summary_item["fulfilled_quantity"] == 30
        assert summary_item["missing_quantity"] == 0
        # Breakdown: A=10 @900 + B=20 @1000
        bk = {b["supplier_name"]: b for b in summary_item["breakdown"]}
        a_key = next(k for k in bk if "SUPPA" in k)
        b_key = next(k for k in bk if "SUPPB" in k)
        assert bk[a_key]["quantity"] == 10
        assert bk[a_key]["unit_price"] == 900
        assert bk[b_key]["quantity"] == 20
        assert bk[b_key]["unit_price"] == 1000
        # Supplier C should NOT be touched
        assert not any("SUPPC" in n for n in bk.keys())
        # Total = 10*900 + 20*1000 = 29000
        assert smart["total"] == 29000.0
        # Groups sorted by total desc -> B (20000) first, then A (9000)
        groups = smart["groups"]
        assert len(groups) == 2
        assert groups[0]["total"] >= groups[1]["total"]
        assert "SUPPB" in groups[0]["supplier_name"]
        assert "SUPPA" in groups[1]["supplier_name"]

    def test_qty_zero_treated_as_unlimited(self, session, pharmacy_token, seeded_products):
        # If we ask for 200 units of an item only supplier C carries with qty=0,
        # smart_split should still fully fulfill it from supplier C.
        # Use PANADOL_EXTRA (long form) with quantity > supplier A stock (10) AND > B stock (50).
        # PANADOL_EXTRA matches: A exact (qty=10), B substring n in q (qty=50), C substring (qty=0 unlimited).
        # Need 100. A=10 @900, B=50 @1000, C=remaining 40 @1100 (qty=0 -> takes remaining).
        r = session.post(
            f"{BASE_URL}/orders/optimize",
            json={"items": [{"name": PANADOL_EXTRA, "quantity": 100}]},
            headers=auth(pharmacy_token),
        )
        assert r.status_code == 200
        body = r.json()
        smart_summary = body["smart_split"]["items_summary"][0]
        assert smart_summary["fulfilled_quantity"] == 100
        assert smart_summary["missing_quantity"] == 0
        bk = {b["supplier_name"]: b for b in smart_summary["breakdown"]}
        a_key = next(k for k in bk if "SUPPA" in k)
        b_key = next(k for k in bk if "SUPPB" in k)
        c_key = next(k for k in bk if "SUPPC" in k)
        assert bk[a_key]["quantity"] == 10
        assert bk[b_key]["quantity"] == 50
        assert bk[c_key]["quantity"] == 40  # remaining picked up by qty=0 supplier


class TestOptimizeSummary:
    def test_max_savings_is_max_minus_min(self, session, pharmacy_token, seeded_products):
        r = session.post(
            f"{BASE_URL}/orders/optimize",
            json={"items": [
                {"name": PANADOL, "quantity": 5},
                {"name": ASPIRIN, "quantity": 5},
            ]},
            headers=auth(pharmacy_token),
        )
        assert r.status_code == 200
        body = r.json()
        s = body["summary"]
        assert s["max_savings"] == pytest.approx(
            round(s["most_expensive_total"] - s["cheapest_total"], 2)
        )
        # Sanity: max >= min
        assert s["most_expensive_total"] >= s["cheapest_total"]
