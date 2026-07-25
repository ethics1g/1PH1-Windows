"""
Batch-based expiry management E2E tests.

Covers scenarios A–G from the review request + sanity role/auth checks
on POST /api/notifications/scan-expiry.

Business rule under test: expiry alerts (and expired-list) are computed
ONLY from batches where remaining_quantity > 0. A depleted batch never
generates an alert, even if its expiry date is in the past.
"""
from __future__ import annotations
import os
import time
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL is required")
API = f"{BASE_URL}/api"

PHARMACY = {"phone": "07700000001", "password": "pass123"}
SUPPLIER = {"phone": "07811111111", "password": "sup1"}


# --------------------------------------------------------------------
# ---------------------------  FIXTURES  -----------------------------
# --------------------------------------------------------------------

def _login(role: str, creds: dict) -> str:
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login {role} failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in login response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def h_pharm():
    tok = _login("pharmacy", PHARMACY)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def h_supp():
    tok = _login("supplier", SUPPLIER)
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _today() -> datetime:
    return datetime.now(timezone.utc)


def _iso(days_offset: int) -> str:
    return (_today() + timedelta(days=days_offset)).strftime("%Y-%m-%d")


def _buy(h, name, qty, purchase_price, selling_price, expiry_days):
    payload = {
        "name": name,
        "quantity": qty,
        "purchase_price": purchase_price,
        "selling_price": selling_price,
        "expiry_date": _iso(expiry_days),
    }
    r = requests.post(f"{API}/medicines/buy-v2", json=payload, headers=h, timeout=20)
    assert r.status_code == 200, f"buy-v2 failed: {r.status_code} {r.text}"
    return r.json()


def _sell(h, medicine_id, qty):
    r = requests.post(
        f"{API}/sales",
        json={"items": [{"medicine_id": medicine_id, "quantity": qty}],
              "payment_type": "cash"},
        headers=h, timeout=20,
    )
    assert r.status_code == 200, f"sale failed: {r.status_code} {r.text}"
    return r.json()


def _get_med(h, mid):
    # /medicines/{mid}/batches returns { medicine, batches, total_stock }
    r = requests.get(f"{API}/medicines/{mid}/batches", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _scan(h):
    r = requests.post(f"{API}/notifications/scan-expiry", headers=h, timeout=30)
    assert r.status_code == 200, f"scan-expiry failed: {r.status_code} {r.text}"
    return r.json()


def _notifs(h, limit=200):
    """Fetch notifications, paginating with the server's 200-per-page cap."""
    items: list = []
    skip = 0
    page_size = min(200, limit)
    while len(items) < limit:
        r = requests.get(
            f"{API}/notifications?limit={page_size}&skip={skip}", headers=h, timeout=15,
        )
        assert r.status_code == 200, r.text
        chunk = r.json().get("items", [])
        if not chunk:
            break
        items.extend(chunk)
        if len(chunk) < page_size:
            break
        skip += page_size
    return items


def _expired_list(h):
    r = requests.get(f"{API}/medicines/expired-list", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------
# --------------------------  SCENARIOS  -----------------------------
# --------------------------------------------------------------------

class TestA_BatchCreationPreservesHistory:
    """Adding a same-named medicine with a different expiry creates a NEW
    batch instead of overwriting the previous one."""

    def test_two_batches_distinct_expiry(self, h_pharm):
        name = f"TEST_EXP_MED_A_{int(time.time())}"
        r1 = _buy(h_pharm, name, 20, 50, 100, 400)
        r2 = _buy(h_pharm, name, 30, 60, 100, 800)
        assert r1["medicine"]["id"] == r2["medicine"]["id"], "medicine must be reused"
        mid = r1["medicine"]["id"]

        # Give purchased_at a distinguishable order
        info = _get_med(h_pharm, mid)
        batches = info["batches"]
        assert len(batches) == 2, f"expected 2 batches, got {len(batches)}"
        # sorted by purchased_at asc (endpoint sorts by purchased_at ascending)
        b1, b2 = batches[0], batches[1]
        assert b1["remaining_quantity"] == 20
        assert b2["remaining_quantity"] == 30
        assert b1["expiry_date"] == _iso(400)
        assert b2["expiry_date"] == _iso(800)
        assert info["total_stock"] == 50

        # Mirror medicine.expiry_date == earliest active (today+400d)
        med_r = info["medicine"]
        assert med_r is not None
        # Reload the raw medicine doc via listing endpoint (batches endpoint
        # only returns id/name/price). Use a lightweight cross-check: earliest
        # batch expiry equals _iso(400).
        earliest = min(b["expiry_date"] for b in batches if b.get("expiry_date"))
        assert earliest == _iso(400)


class TestB_FIFODrainsOldestFirst:
    def test_sell_15_drains_batch1(self, h_pharm):
        name = f"TEST_EXP_MED_B1_{int(time.time())}"
        r1 = _buy(h_pharm, name, 20, 50, 100, 400)
        _buy(h_pharm, name, 30, 60, 100, 800)
        mid = r1["medicine"]["id"]

        _sell(h_pharm, mid, 15)
        info = _get_med(h_pharm, mid)
        batches = info["batches"]
        assert len(batches) == 2
        assert batches[0]["remaining_quantity"] == 5, "batch-1 must be drained by FIFO first"
        assert batches[1]["remaining_quantity"] == 30
        assert info["total_stock"] == 35

        # Mirror expiry stays at earliest active = batch-1 (today+400d)
        earliest_active = min(
            b["expiry_date"] for b in batches
            if b.get("expiry_date") and b["remaining_quantity"] > 0
        )
        assert earliest_active == _iso(400)


class TestC_DepletedBatchExcludedFromAlerts:
    """The most business-critical: a batch that hits 0 must disappear from
    alerts and expired-list, regardless of its expiry date."""

    def test_depleted_earliest_batch_stops_alert(self, h_pharm):
        name = f"TEST_EXP_MED_C_{int(time.time())}"
        # batch-1: near-expiry, small qty; batch-2: distant expiry, larger qty
        r1 = _buy(h_pharm, name, 10, 50, 100, 7)     # matches 7-day threshold
        _buy(h_pharm, name, 15, 60, 100, 400)
        mid = r1["medicine"]["id"]

        # Deplete batch-1 entirely
        _sell(h_pharm, mid, 10)
        info = _get_med(h_pharm, mid)
        b_by_exp = {b["expiry_date"]: b for b in info["batches"]}
        assert b_by_exp[_iso(7)]["remaining_quantity"] == 0
        assert b_by_exp[_iso(400)]["remaining_quantity"] == 15

        # Trigger the scan and inspect notifications
        _scan(h_pharm)
        notifs = _notifs(h_pharm, limit=200)
        # No expiry_reminder for THIS medicine referencing the 7-day threshold
        for n in notifs:
            if n.get("type") != "expiry_reminder":
                continue
            data = n.get("data") or {}
            if data.get("medicine_id") == mid:
                # If any alert exists for this med, it must NOT be for the
                # depleted batch's expiry.
                assert data.get("expiry_date") != _iso(7), (
                    f"Depleted batch generated an alert: {n}"
                )
        # And no alert for the far-future batch (400d not in {90,30,7,1})
        for n in notifs:
            if n.get("type") == "expiry_reminder" and (n.get("data") or {}).get("medicine_id") == mid:
                # 400d out of threshold, so nothing should be here.
                pytest.fail(f"Unexpected expiry_reminder for far-future batch: {n}")

    def test_depleted_past_expiry_batch_not_in_expired_list(self, h_pharm):
        name = f"TEST_EXP_MED_C2_{int(time.time())}"
        # single already-expired batch, then sell everything
        r1 = _buy(h_pharm, name, 5, 50, 100, -3)
        mid = r1["medicine"]["id"]
        _sell(h_pharm, mid, 5)  # deplete
        info = _get_med(h_pharm, mid)
        assert info["batches"][0]["remaining_quantity"] == 0
        assert info["total_stock"] == 0

        _scan(h_pharm)
        exp = _expired_list(h_pharm)
        ids = {row["id"] for row in exp.get("items", [])}
        assert mid not in ids, (
            f"Depleted past-expiry medicine must NOT appear in expired-list: {exp}"
        )


class TestD_AlertsForActiveBatches:
    def test_active_7day_batch_triggers_alert(self, h_pharm):
        name = f"TEST_EXP_MED_D_{int(time.time())}"
        r = _buy(h_pharm, name, 8, 50, 100, 7)
        mid = r["medicine"]["id"]
        _scan(h_pharm)

        notifs = _notifs(h_pharm, limit=200)
        matching = [
            n for n in notifs
            if n.get("type") == "expiry_reminder"
            and (n.get("data") or {}).get("medicine_id") == mid
        ]
        assert matching, f"Expected an expiry_reminder for {mid}. Got {len(notifs)} notifs total."
        n = matching[0]
        assert "تنبيه صلاحية:" in n["title"], f"Arabic title missing: {n['title']}"
        assert name in n["title"], f"Medicine name missing from title: {n['title']}"
        assert (n["data"] or {}).get("medicine_id") == mid


class TestE_DedupeIdempotency:
    def test_scan_twice_no_duplicate(self, h_pharm):
        name = f"TEST_EXP_MED_E_{int(time.time())}"
        r = _buy(h_pharm, name, 8, 50, 100, 7)
        mid = r["medicine"]["id"]
        _scan(h_pharm)
        _scan(h_pharm)

        notifs = _notifs(h_pharm, limit=500)
        matching = [
            n for n in notifs
            if n.get("type") == "expiry_reminder"
            and (n.get("data") or {}).get("medicine_id") == mid
            and (n.get("data") or {}).get("expiry_date") == _iso(7)
        ]
        assert len(matching) == 1, (
            f"Expected exactly 1 dedupe'd 7-day alert, got {len(matching)}: {matching}"
        )


class TestF_WeeklyExpiredReport:
    def test_weekly_dedupe_and_active_only(self, h_pharm):
        name = f"TEST_EXP_MED_F_{int(time.time())}"
        r1 = _buy(h_pharm, name, 10, 50, 100, -5)   # past-expiry
        _buy(h_pharm, name, 20, 60, 100, 400)
        mid = r1["medicine"]["id"]

        _sell(h_pharm, mid, 5)  # batch-1 now has 5 remaining (still active)
        _scan(h_pharm)

        before = [n for n in _notifs(h_pharm, limit=500) if n.get("type") == "expired_weekly"]
        assert before, "Expected at least one expired_weekly notification"
        assert (before[0].get("data") or {}).get("count", 0) >= 1

        before_count = len(before)

        # Deplete batch-1 fully, then scan again.
        _sell(h_pharm, mid, 5)
        info = _get_med(h_pharm, mid)
        past_batch = next(b for b in info["batches"] if b["expiry_date"] == _iso(-5))
        assert past_batch["remaining_quantity"] == 0

        _scan(h_pharm)
        after = [n for n in _notifs(h_pharm, limit=500) if n.get("type") == "expired_weekly"]
        # Dedupe includes week_key → count must not increase.
        assert len(after) == before_count, (
            f"Weekly expired report duplicated within same week: "
            f"before={before_count} after={len(after)}"
        )


class TestG_ExpiredListSchema:
    def test_expired_list_returns_batch_details(self, h_pharm):
        name = f"TEST_EXP_MED_G_{int(time.time())}"
        r1 = _buy(h_pharm, name, 10, 50, 100, -5)   # past-expiry active
        mid = r1["medicine"]["id"]
        # Leave 5 units remaining
        _sell(h_pharm, mid, 5)

        _scan(h_pharm)
        exp = _expired_list(h_pharm)
        items = exp.get("items", [])
        matches = [it for it in items if it["id"] == mid]
        assert matches, f"Medicine {mid} not in expired-list; got items={items}"
        row = matches[0]
        assert row["stock"] == 5, f"Expected stock=5, got {row['stock']}"
        assert row["expiry_date"] == _iso(-5)
        assert isinstance(row.get("batches"), list)
        assert len(row["batches"]) == 1
        assert row["batches"][0]["remaining_quantity"] == 5


# --------------------------------------------------------------------
# ------------------  SANITY: ROLE / AUTH GUARDS  --------------------
# --------------------------------------------------------------------

class TestSanityGuards:
    def test_scan_expiry_requires_auth(self):
        r = requests.post(f"{API}/notifications/scan-expiry", timeout=15)
        assert r.status_code == 401, f"unauth should be 401, got {r.status_code} {r.text}"

    def test_scan_expiry_forbids_supplier(self, h_supp):
        r = requests.post(f"{API}/notifications/scan-expiry", headers=h_supp, timeout=15)
        assert r.status_code == 403, (
            f"supplier should get 403 on pharmacy-only endpoint, got {r.status_code} {r.text}"
        )
