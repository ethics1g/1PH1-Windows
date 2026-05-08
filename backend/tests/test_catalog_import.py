"""Backend tests for AI Supplier Catalog Import feature."""
import os
import io
import time
import base64
import asyncio
import uuid
import requests
import pytest
from pathlib import Path
from dotenv import load_dotenv
from PIL import Image, ImageDraw

# Load frontend env to get public backend URL
load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
# Load backend env for MONGO_URL / DB_NAME (direct DB seeding)
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") + "/api"

# Pre-existing supplier (from problem statement)
SUPPLIER_PHONE = "07811111111"
SUPPLIER_PASSWORD = "sup1"

# Pre-existing pharmacy
PHARMACY_PHONE = "07700000001"
PHARMACY_PASSWORD = "pass123"

RUN = str(int(time.time()))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def supplier_token(session):
    """Login pre-existing supplier; if it fails, register a fresh one."""
    r = session.post(f"{BASE_URL}/supplier/login",
                     json={"phone": SUPPLIER_PHONE, "password": SUPPLIER_PASSWORD})
    if r.status_code == 200:
        return r.json()["token"], r.json()["supplier"]["id"]
    # fallback: register new supplier
    new_phone = f"0790000{RUN[-4:]}"
    r2 = session.post(f"{BASE_URL}/supplier/register",
                      json={"name": f"TEST_SUP_{RUN}", "phone": new_phone,
                            "password": "sup123", "address": "بغداد"})
    assert r2.status_code == 200, r2.text
    return r2.json()["token"], r2.json()["supplier"]["id"]


@pytest.fixture(scope="module")
def pharmacy_token(session):
    r = session.post(f"{BASE_URL}/pharmacy/login",
                     json={"phone": PHARMACY_PHONE, "password": PHARMACY_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def supplier_headers(supplier_token):
    token, _sid = supplier_token
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def pharmacy_headers(pharmacy_token):
    return {"Authorization": f"Bearer {pharmacy_token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_pricelist_jpeg_b64() -> str:
    """Create a small synthetic JPEG with simulated price-list text."""
    img = Image.new("RGB", (800, 600), color="white")
    d = ImageDraw.Draw(img)
    lines = [
        "Price List - TEST_PHARMA",
        "",
        "Paracetamol 500mg tab    1500 IQD   Qty:200",
        "Amoxicillin 250mg cap    2200 IQD   Qty:150",
        "Ibuprofen 400mg tab      1800 IQD   Qty:120",
        "Vitamin C 1000mg tab      900 IQD   Qty:300",
    ]
    y = 30
    for ln in lines:
        d.text((30, y), ln, fill="black")
        y += 40
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def make_oversize_b64(size_bytes: int = 13 * 1024 * 1024) -> str:
    """Generate a base64 string that decodes to ~size_bytes bytes."""
    raw = b"A" * size_bytes
    return base64.b64encode(raw).decode("ascii")


def poll_job(session, headers, job_id: str, timeout: int = 60) -> dict:
    """Poll job until status != 'pending' and != 'processing'."""
    start = time.time()
    last = None
    while time.time() - start < timeout:
        r = session.get(f"{BASE_URL}/supplier/catalog/jobs/{job_id}", headers=headers)
        assert r.status_code == 200, r.text
        last = r.json()
        st = last["job"]["status"]
        if st not in ("pending", "processing"):
            return last
        time.sleep(2)
    return last


# ---------------------------------------------------------------------------
# 1. Auth & role-guard tests
# ---------------------------------------------------------------------------
class TestAuthGuards:
    def test_pharmacy_forbidden_on_upload(self, session, pharmacy_headers):
        r = session.post(f"{BASE_URL}/supplier/catalog/upload",
                         json={"file_b64": "abc", "file_type": "image/jpeg"},
                         headers=pharmacy_headers)
        assert r.status_code == 403, r.text

    def test_pharmacy_forbidden_on_jobs_list(self, session, pharmacy_headers):
        r = session.get(f"{BASE_URL}/supplier/catalog/jobs", headers=pharmacy_headers)
        assert r.status_code == 403

    def test_pharmacy_forbidden_on_publish(self, session, pharmacy_headers):
        r = session.post(f"{BASE_URL}/supplier/catalog/jobs/anything/publish",
                         headers=pharmacy_headers)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 2. Validation tests
# ---------------------------------------------------------------------------
class TestUploadValidation:
    def test_empty_file_b64_returns_400(self, session, supplier_headers):
        r = session.post(f"{BASE_URL}/supplier/catalog/upload",
                         json={"file_b64": "", "file_type": "image/jpeg"},
                         headers=supplier_headers)
        assert r.status_code == 400, r.text

    def test_oversize_returns_413(self, session, supplier_headers):
        # 13 MB raw -> base64 ~17.3 MB string. > 12 MB threshold.
        big = make_oversize_b64(13 * 1024 * 1024)
        r = session.post(f"{BASE_URL}/supplier/catalog/upload",
                         json={"file_b64": big, "file_type": "image/jpeg"},
                         headers=supplier_headers)
        assert r.status_code == 413, f"Expected 413 got {r.status_code}: {r.text[:200]}"


# ---------------------------------------------------------------------------
# 3. Full upload -> background processing -> review -> publish flow
# ---------------------------------------------------------------------------
class TestCatalogPipeline:
    def test_full_pipeline(self, session, supplier_headers, supplier_token):
        # 3a. Upload
        b64 = make_pricelist_jpeg_b64()
        r = session.post(f"{BASE_URL}/supplier/catalog/upload",
                         json={"file_b64": b64, "file_type": "image/jpeg",
                               "filename": f"TEST_pricelist_{RUN}.jpg"},
                         headers=supplier_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "job_id" in body
        assert body["status"] == "pending"
        job_id = body["job_id"]

        # 3b. List jobs - should include this job and NOT include file_b64
        r2 = session.get(f"{BASE_URL}/supplier/catalog/jobs", headers=supplier_headers)
        assert r2.status_code == 200
        jobs = r2.json()
        assert any(j["id"] == job_id for j in jobs), "uploaded job missing in list"
        for j in jobs:
            assert "file_b64" not in j, "file_b64 leaked in jobs list"

        # 3c. Poll until processing finishes
        result = poll_job(session, supplier_headers, job_id, timeout=90)
        assert result is not None
        final_status = result["job"]["status"]
        assert final_status in ("review", "failed", "published"), \
            f"unexpected final status {final_status}"

        # We accept review (success) or failed (when extraction returns nothing)
        # but pipeline MUST exit pending/processing
        assert final_status != "processing"
        assert final_status != "pending"

        # 3d. Verify response shape
        assert "items" in result and "grouped" in result
        for k in ("auto", "needs_review", "approved", "rejected"):
            assert k in result["grouped"], f"grouped missing {k}"

        # Stash the job for next tests via class attr
        TestCatalogPipeline.job_id = job_id
        TestCatalogPipeline.final_status = final_status

    def test_job_detail_excludes_file_b64(self, session, supplier_headers):
        job_id = getattr(TestCatalogPipeline, "job_id", None)
        if not job_id:
            pytest.skip("no job from upload test")
        r = session.get(f"{BASE_URL}/supplier/catalog/jobs/{job_id}", headers=supplier_headers)
        assert r.status_code == 200
        assert "file_b64" not in r.json()["job"] or r.json()["job"].get("file_b64") in (None,)


# ---------------------------------------------------------------------------
# 4. Direct DB insert -> patch (correction) -> publish flow
#    (does not rely on Gemini extracting anything)
# ---------------------------------------------------------------------------
class TestPatchAndPublishDirect:
    """Insert known import_item directly via motor, then test PATCH/publish."""

    @classmethod
    def setup_class(cls):
        from motor.motor_asyncio import AsyncIOMotorClient
        cls.client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        cls.db = cls.client[os.environ["DB_NAME"]]

    @classmethod
    def teardown_class(cls):
        cls.client.close()

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    @pytest.fixture(scope="class")
    def seeded(self, supplier_token):
        token, sid = supplier_token
        # Manually create an import_job in 'review' state
        job_id = f"TEST_job_{RUN}_{uuid.uuid4().hex[:6]}"
        item_id = f"TEST_item_{RUN}_{uuid.uuid4().hex[:6]}"

        async def _seed():
            await self.db.import_jobs.insert_one({
                "id": job_id,
                "supplier_id": sid,
                "status": "review",
                "progress": 100,
                "file_type": "image/jpeg",
                "filename": "TEST_seed.jpg",
                "file_size": 1234,
                "file_b64": None,
                "total_items": 1,
                "items_to_review": 1,
                "page_count": 1,
                "error": None,
                "created_at": "2026-01-01T00:00:00+00:00",
                "completed_at": "2026-01-01T00:00:01+00:00",
            })
            await self.db.import_items.insert_one({
                "id": item_id,
                "job_id": job_id,
                "supplier_id": sid,
                "raw_text": f"TEST_DRUG_{RUN}",
                "extracted": {
                    "name": f"TEST_DRUG_{RUN}",
                    "strength": "500mg",
                    "dosage_form": "tab",
                    "manufacturer": "ACME",
                    "price": 1500.0,
                    "quantity": 100,
                },
                "canonical_key": f"test_drug_{RUN} 500mg tab",
                "suggested_canonical_name": "different suggestion",
                "match_confidence": 0.6,
                "match_status": "needs_review",
                "approved_name": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            })

        self._run(_seed())
        yield {"sid": sid, "job_id": job_id, "item_id": item_id, "token": token}

        async def _cleanup():
            await self.db.import_items.delete_many({"job_id": job_id})
            await self.db.import_jobs.delete_one({"id": job_id})
            await self.db.catalog_corrections.delete_many({"supplier_id": sid,
                                                           "original_key": f"test_drug_{RUN} 500mg tab"})
            await self.db.supplier_products.delete_many({"supplier_id": sid,
                                                         "name": {"$regex": f"^TEST_APPROVED_{RUN}"}})
        self._run(_cleanup())

    def test_patch_creates_correction_and_approves(self, session, supplier_headers, seeded):
        item_id = seeded["item_id"]
        approved_name = f"TEST_APPROVED_{RUN}"
        r = session.patch(
            f"{BASE_URL}/supplier/catalog/items/{item_id}",
            json={"approved_name": approved_name, "match_status": "approved"},
            headers=supplier_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["match_status"] == "approved"
        assert body["approved_name"] == approved_name

        # Verify catalog_corrections record was created
        async def _check():
            return await self.db.catalog_corrections.find_one({
                "supplier_id": seeded["sid"],
                "original_key": f"test_drug_{RUN} 500mg tab",
            })
        doc = self._run(_check())
        assert doc is not None, "catalog_corrections not created"
        assert doc["corrected_name"] == approved_name

    def test_invalid_match_status_rejected(self, session, supplier_headers, seeded):
        r = session.patch(
            f"{BASE_URL}/supplier/catalog/items/{seeded['item_id']}",
            json={"match_status": "garbage"}, headers=supplier_headers,
        )
        assert r.status_code == 400

    def test_patch_other_supplier_item_404(self, session, supplier_headers):
        r = session.patch(f"{BASE_URL}/supplier/catalog/items/nonexistent_xyz",
                          json={"match_status": "approved"}, headers=supplier_headers)
        assert r.status_code == 404

    def test_publish_only_approved_items(self, session, supplier_headers, seeded):
        # Add a second item that is 'rejected' to confirm it is skipped
        rejected_item_id = f"TEST_rej_{RUN}_{uuid.uuid4().hex[:6]}"

        async def _seed_reject():
            await self.db.import_items.insert_one({
                "id": rejected_item_id,
                "job_id": seeded["job_id"],
                "supplier_id": seeded["sid"],
                "raw_text": "rejected drug",
                "extracted": {"name": f"TEST_REJECTED_{RUN}", "price": 500, "quantity": 50},
                "canonical_key": "rejected",
                "suggested_canonical_name": None,
                "match_confidence": 0.1,
                "match_status": "rejected",
                "approved_name": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            })
        self._run(_seed_reject())

        # Publish
        r = session.post(f"{BASE_URL}/supplier/catalog/jobs/{seeded['job_id']}/publish",
                         headers=supplier_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] >= 1
        # Only approved (not rejected) should be present
        async def _check_products():
            cur = self.db.supplier_products.find({"supplier_id": seeded["sid"]})
            return [p async for p in cur]
        prods = self._run(_check_products())
        names = [p["name"] for p in prods]
        assert any(n == f"TEST_APPROVED_{RUN}" for n in names), \
            f"approved product missing in supplier_products: {names}"
        assert all(f"TEST_REJECTED_{RUN}" != n for n in names), \
            "rejected item must NOT be published"

        # Job status must move to 'published'
        async def _check_job():
            return await self.db.import_jobs.find_one({"id": seeded["job_id"]}, {"_id": 0})
        j = self._run(_check_job())
        assert j["status"] == "published"
        assert j.get("published_count", 0) >= 1

    def test_published_item_visible_in_marketplace(self, session, pharmacy_headers, seeded):
        r = session.get(f"{BASE_URL}/marketplace", headers=pharmacy_headers)
        assert r.status_code == 200
        names = [p["name"] for p in r.json()]
        assert any(n == f"TEST_APPROVED_{RUN}" for n in names), \
            f"published item missing in marketplace (found {len(names)} products)"

    def test_published_item_visible_in_supplier_products(self, session, supplier_headers):
        r = session.get(f"{BASE_URL}/supplier/products", headers=supplier_headers)
        assert r.status_code == 200
        names = [p["name"] for p in r.json()]
        assert any(n == f"TEST_APPROVED_{RUN}" for n in names)

    def test_publish_idempotent_updates_existing(self, session, supplier_headers, seeded):
        """Publishing same job again should update (not duplicate) the product."""
        r = session.post(f"{BASE_URL}/supplier/catalog/jobs/{seeded['job_id']}/publish",
                         headers=supplier_headers)
        assert r.status_code == 200, r.text

        async def _count():
            return await self.db.supplier_products.count_documents({
                "supplier_id": seeded["sid"], "name": f"TEST_APPROVED_{RUN}"
            })
        cnt = self._run(_count())
        assert cnt == 1, f"expected exactly 1 product, found {cnt}"
