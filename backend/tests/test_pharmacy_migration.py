"""
Backend regression tests for the pharmacy data migration endpoints:
  - POST /api/admin/login
  - GET  /api/admin/pharmacy-summary/{phone}
  - GET  /api/admin/pharmacy-export/{phone}
  - POST /api/admin/pharmacy-import

Covers auth guards, export/import round-trip, idempotency, mode variants
and cleanup of test data.
"""
import os
import pytest
import requests
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# EXPO_PUBLIC_BACKEND_URL is the production-facing URL; we use the internal
# 8001 port for tests so we're validating exactly the running container.
BASE_URL = (
    os.environ.get("BACKEND_TEST_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")

ADMIN_PHONE = "0000000000"
ADMIN_PASSWORD = "admin123"

SOURCE_PHARMACY_PHONE = "07700000001"
SOURCE_PHARMACY_PASSWORD = "pass123"

TARGET_PHARMACY_PHONE = "07999999900"
TARGET_PHARMACY_PASSWORD = "migtest"

UNKNOWN_PHONE = "00000000000000"

PHARMACY_DATA_COLLECTIONS = [
    "medicines",
    "medicine_batches",
    "orders",
    "sales",
    "customers",
    "customer_payments",
    "paper_orders",
    "returns",
    "return_credits",
    "supplier_accounts",
    "supplier_ledger",
    "supplier_sales",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def api_client() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(api_client: requests.Session) -> str:
    r = api_client.post(
        f"{BASE_URL}/api/admin/login",
        json={"phone": ADMIN_PHONE, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    assert "token" in body and body["token"]
    assert body["admin"]["phone"] == ADMIN_PHONE
    # After first rotation the field should be false
    assert body["admin"].get("must_change_password") is False
    return body["token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def source_pharmacy_token(api_client: requests.Session) -> str:
    r = api_client.post(
        f"{BASE_URL}/api/pharmacy/login",
        json={"phone": SOURCE_PHARMACY_PHONE, "password": SOURCE_PHARMACY_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"Pharmacy login failed: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def target_pharmacy(api_client: requests.Session, admin_headers: Dict[str, str]):
    """Register (or reuse) the migration target pharmacy 07999999900.
    After the whole test session, wipe its 12 collections and delete the
    pharmacy record itself so the seed database is untouched.
    """
    payload = {
        "phone": TARGET_PHARMACY_PHONE,
        "password": TARGET_PHARMACY_PASSWORD,
        "name": "MIG_TARGET",
        "address": "Baghdad",
        "region": "بغداد",
    }
    r = requests.post(f"{BASE_URL}/api/pharmacy/register", json=payload, timeout=20)
    if r.status_code == 400:
        # Already exists from a prior run — that's fine. Fetch its id via login.
        login = requests.post(
            f"{BASE_URL}/api/pharmacy/login",
            json={"phone": TARGET_PHARMACY_PHONE, "password": TARGET_PHARMACY_PASSWORD},
            timeout=20,
        )
        assert login.status_code == 200, (
            f"Target already exists but login failed: {login.status_code} {login.text[:200]}"
        )
        info = login.json()["pharmacy"]
    else:
        assert r.status_code == 200, f"register failed: {r.status_code} {r.text[:200]}"
        info = r.json()["pharmacy"]

    yield info  # tests run

    # ---- Session teardown ----
    # Wipe the 12 collections for this target via pharmacy-import with an
    # empty bundle (mode=replace) — that hits delete_many on every collection.
    try:
        empty_bundle = {"schema_version": 1, "collections": {c: [] for c in PHARMACY_DATA_COLLECTIONS}}
        requests.post(
            f"{BASE_URL}/api/admin/pharmacy-import",
            headers=admin_headers,
            json={"target_phone": TARGET_PHARMACY_PHONE, "bundle": empty_bundle, "mode": "replace"},
            timeout=60,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[teardown] wipe failed: {e}")

    # Delete pharmacy record + related auth artefacts directly via Mongo so
    # we don't leave orphaned rows. Uses same MONGO_URL/DB_NAME as backend.
    try:
        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "pharmacy_db")
        cli = MongoClient(mongo_url)
        db = cli[db_name]
        db.pharmacies.delete_one({"phone": TARGET_PHARMACY_PHONE})
        for col in PHARMACY_DATA_COLLECTIONS:
            db[col].delete_many({"pharmacy_id": info["id"]})
        cli.close()
    except Exception as e:  # noqa: BLE001
        print(f"[teardown] mongo cleanup failed: {e}")


# ---------------------------------------------------------------------------
# 1. Admin login
# ---------------------------------------------------------------------------
class TestAdminLogin:
    def test_admin_login_success(self, admin_token: str):
        assert admin_token and len(admin_token) > 20


# ---------------------------------------------------------------------------
# 2/3/4/5. pharmacy-summary
# ---------------------------------------------------------------------------
class TestPharmacySummary:
    def test_summary_returns_expected_shape_and_counts(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-summary/{SOURCE_PHARMACY_PHONE}",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert set(body.keys()) >= {"pharmacy", "counts", "total"}
        assert body["pharmacy"]["phone"] == SOURCE_PHARMACY_PHONE
        assert "id" in body["pharmacy"] and "name" in body["pharmacy"]
        # Exactly the 12 documented collections must appear.
        assert set(body["counts"].keys()) == set(PHARMACY_DATA_COLLECTIONS), (
            f"Unexpected keys: {set(body['counts'].keys()) ^ set(PHARMACY_DATA_COLLECTIONS)}"
        )
        for col, cnt in body["counts"].items():
            assert isinstance(cnt, int), f"{col} count is not int: {cnt}"
        assert body["total"] >= 4900, f"Expected ≥4900 seed docs, got {body['total']}"
        assert body["counts"]["medicines"] > 2000
        assert body["counts"]["medicine_batches"] > 2000

    def test_summary_requires_auth(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-summary/{SOURCE_PHARMACY_PHONE}",
            timeout=20,
        )
        assert r.status_code == 401, r.text[:200]

    def test_summary_rejects_non_admin_token(self, source_pharmacy_token: str):
        r = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-summary/{SOURCE_PHARMACY_PHONE}",
            headers={"Authorization": f"Bearer {source_pharmacy_token}"},
            timeout=20,
        )
        assert r.status_code in (401, 403), r.text[:200]

    def test_summary_unknown_phone_returns_404(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-summary/{UNKNOWN_PHONE}",
            headers=admin_headers, timeout=20,
        )
        assert r.status_code == 404
        assert "لا توجد صيدلية" in r.json().get("detail", "")


# ---------------------------------------------------------------------------
# 6/7/8. pharmacy-export
# ---------------------------------------------------------------------------
class TestPharmacyExport:
    def test_export_full_bundle(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-export/{SOURCE_PHARMACY_PHONE}",
            headers=admin_headers, timeout=120,
        )
        assert r.status_code == 200
        bundle = r.json()
        assert bundle.get("schema_version") == 1
        assert "exported_at" in bundle
        src = bundle["source"]
        assert src["phone"] == SOURCE_PHARMACY_PHONE
        assert "pharmacy_id" in src and "name" in src
        assert "pharmacy_doc" in src
        # Password must never leak in the export
        assert "password" not in src["pharmacy_doc"], "password field leaked in pharmacy_doc!"

        collections = bundle["collections"]
        assert set(collections.keys()) == set(PHARMACY_DATA_COLLECTIONS)
        assert len(collections["medicines"]) > 2000
        # No _id in any doc across all collections
        for col, docs in collections.items():
            for d in docs[:50]:  # spot-check first 50 of each
                assert "_id" not in d, f"_id leaked in {col}: {d}"

    def test_export_requires_admin(self, source_pharmacy_token: str):
        r_no = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-export/{SOURCE_PHARMACY_PHONE}",
            timeout=20,
        )
        assert r_no.status_code == 401

        r_pharm = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-export/{SOURCE_PHARMACY_PHONE}",
            headers={"Authorization": f"Bearer {source_pharmacy_token}"},
            timeout=20,
        )
        assert r_pharm.status_code in (401, 403)

    def test_export_unknown_phone_returns_404(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-export/{UNKNOWN_PHONE}",
            headers=admin_headers, timeout=20,
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 9/10/11/12/13/14. pharmacy-import (E2E round-trip)
# ---------------------------------------------------------------------------
class TestPharmacyImport:
    @pytest.fixture(scope="class")
    def source_bundle(self, admin_headers) -> Dict[str, Any]:
        r = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-export/{SOURCE_PHARMACY_PHONE}",
            headers=admin_headers, timeout=120,
        )
        assert r.status_code == 200
        return r.json()

    @pytest.fixture(scope="class")
    def source_total(self, admin_headers) -> int:
        r = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-summary/{SOURCE_PHARMACY_PHONE}",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200
        return r.json()["total"]

    def test_import_merge_e2e(self, admin_headers, target_pharmacy,
                              source_bundle, source_total, api_client):
        r = requests.post(
            f"{BASE_URL}/api/admin/pharmacy-import",
            headers=admin_headers,
            json={"target_phone": TARGET_PHARMACY_PHONE,
                  "bundle": source_bundle, "mode": "merge"},
            timeout=300,
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body["ok"] is True
        assert body["mode"] == "merge"
        assert body["target"]["phone"] == TARGET_PHARMACY_PHONE
        assert body["target"]["pharmacy_id"] == target_pharmacy["id"]
        assert body["totals"]["inserted"] >= 4900, (
            f"inserted={body['totals']['inserted']} < 4900"
        )
        # per-collection stats present
        assert set(body["collections"].keys()) == set(PHARMACY_DATA_COLLECTIONS)

        # Verify with summary
        s = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-summary/{TARGET_PHARMACY_PHONE}",
            headers=admin_headers, timeout=30,
        )
        assert s.status_code == 200
        assert s.json()["total"] == source_total, (
            f"target total={s.json()['total']} != source total={source_total}"
        )

        # Verify a medicine appears when logging in as the target pharmacy
        login = requests.post(
            f"{BASE_URL}/api/pharmacy/login",
            json={"phone": TARGET_PHARMACY_PHONE, "password": TARGET_PHARMACY_PASSWORD},
            timeout=20,
        )
        assert login.status_code == 200
        tok = login.json()["token"]
        meds = requests.get(
            f"{BASE_URL}/api/medicines?limit=5",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=20,
        )
        assert meds.status_code == 200, meds.text[:200]
        data = meds.json()
        # /api/medicines might return a list or dict — accept both
        items = data if isinstance(data, list) else data.get("items") or data.get("medicines") or []
        assert len(items) >= 1, f"No medicines visible to target pharmacy: {data}"

    def test_import_idempotent(self, admin_headers, target_pharmacy,
                               source_bundle, source_total):
        # Re-run the same import; second call must succeed without doubling.
        r2 = requests.post(
            f"{BASE_URL}/api/admin/pharmacy-import",
            headers=admin_headers,
            json={"target_phone": TARGET_PHARMACY_PHONE,
                  "bundle": source_bundle, "mode": "merge"},
            timeout=300,
        )
        assert r2.status_code == 200, r2.text[:400]
        s = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-summary/{TARGET_PHARMACY_PHONE}",
            headers=admin_headers, timeout=30,
        )
        assert s.status_code == 200
        assert s.json()["total"] == source_total, (
            f"Idempotency broken: target total={s.json()['total']} != source={source_total}"
        )

    def test_import_replace_mode(self, admin_headers, target_pharmacy,
                                 source_bundle, source_total):
        r = requests.post(
            f"{BASE_URL}/api/admin/pharmacy-import",
            headers=admin_headers,
            json={"target_phone": TARGET_PHARMACY_PHONE,
                  "bundle": source_bundle, "mode": "replace"},
            timeout=300,
        )
        assert r.status_code == 200, r.text[:400]
        assert r.json()["mode"] == "replace"
        s = requests.get(
            f"{BASE_URL}/api/admin/pharmacy-summary/{TARGET_PHARMACY_PHONE}",
            headers=admin_headers, timeout=30,
        )
        assert s.status_code == 200
        assert s.json()["total"] == source_total

    def test_import_rejects_invalid_mode(self, admin_headers, target_pharmacy):
        r = requests.post(
            f"{BASE_URL}/api/admin/pharmacy-import",
            headers=admin_headers,
            json={"target_phone": TARGET_PHARMACY_PHONE,
                  "bundle": {"collections": {}}, "mode": "delete"},
            timeout=20,
        )
        assert r.status_code in (400, 422), r.text[:200]

    def test_import_rejects_invalid_bundle(self, admin_headers, target_pharmacy):
        r = requests.post(
            f"{BASE_URL}/api/admin/pharmacy-import",
            headers=admin_headers,
            json={"target_phone": TARGET_PHARMACY_PHONE, "bundle": {}, "mode": "merge"},
            timeout=20,
        )
        assert r.status_code == 400, r.text[:200]

    def test_import_rejects_unknown_target_phone(self, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/admin/pharmacy-import",
            headers=admin_headers,
            json={"target_phone": UNKNOWN_PHONE,
                  "bundle": {"collections": {}}, "mode": "merge"},
            timeout=20,
        )
        assert r.status_code == 404, r.text[:200]


# ---------------------------------------------------------------------------
# 16/17. Regression – existing endpoints still work
# ---------------------------------------------------------------------------
class TestRegression:
    def test_source_pharmacy_login_still_works(self):
        r = requests.post(
            f"{BASE_URL}/api/pharmacy/login",
            json={"phone": SOURCE_PHARMACY_PHONE, "password": SOURCE_PHARMACY_PASSWORD},
            timeout=20,
        )
        assert r.status_code == 200
        assert r.json()["pharmacy"]["phone"] == SOURCE_PHARMACY_PHONE

    def test_source_pharmacy_medicines_list_not_broken(self, source_pharmacy_token: str):
        r = requests.get(
            f"{BASE_URL}/api/medicines?limit=5",
            headers={"Authorization": f"Bearer {source_pharmacy_token}"},
            timeout=20,
        )
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        items = data if isinstance(data, list) else data.get("items") or data.get("medicines") or []
        assert len(items) >= 1, f"Existing endpoint returned no data: {data}"
