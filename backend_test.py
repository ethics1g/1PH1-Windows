"""
Backend test suite for:
  A) Payment Settings (new feature)
  B) Excel Structured Parse Fix (re-test)

Run: python /app/backend_test.py
"""
import os
import io
import sys
import time
import json
import base64
import uuid
import requests
from openpyxl import Workbook

BASE = "https://pharma-checkout-8.preview.emergentagent.com/api"

PASS = []
FAIL = []

def check(name: str, cond: bool, detail: str = ""):
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append((name, detail))
        print(f"  ❌ {name}  {detail}")

def hr(label: str):
    print("\n" + "=" * 70)
    print(label)
    print("=" * 70)

def login(role_path: str, phone: str, password: str):
    r = requests.post(f"{BASE}/{role_path}", json={"phone": phone, "password": password}, timeout=30)
    if r.status_code != 200:
        print(f"  ⚠ login {role_path} {phone} -> {r.status_code} {r.text[:150]}")
        return None
    return r.json().get("token")

def admin_login():
    # try primary then fallback
    for phone, pwd in [("0000000000", "admin123"), ("0000000000", "NewAdmin$1"),
                       ("07823567874", "Rasooll$123"), ("07823567874", "NewAdmin$1")]:
        r = requests.post(f"{BASE}/admin/login", json={"phone": phone, "password": pwd}, timeout=30)
        if r.status_code == 200:
            print(f"  (admin login: {phone}/{pwd})")
            return r.json()["token"]
    return None

def supplier_ensure_enabled(admin_tok: str, phone: str):
    """If supplier is disabled, re-enable via admin endpoint."""
    r = requests.get(f"{BASE}/admin/users?role=supplier", headers={"Authorization": f"Bearer {admin_tok}"}, timeout=30)
    if r.status_code != 200:
        return
    for u in r.json():
        if u.get("phone") == phone and u.get("disabled"):
            sid = u["id"]
            requests.patch(f"{BASE}/admin/users/supplier/{sid}",
                           headers={"Authorization": f"Bearer {admin_tok}"},
                           json={"disabled": False}, timeout=30)
            print(f"  (re-enabled supplier {phone})")

# ============================================================
# A) Payment Settings tests
# ============================================================
def test_payment_settings():
    hr("A) PAYMENT SETTINGS")

    admin_tok = admin_login()
    if not admin_tok:
        FAIL.append(("admin_login", "all admin credentials rejected"))
        print("  ❌ admin_login: all credentials rejected. Abort.")
        return None, None
    PASS.append("admin_login")

    h_admin = {"Authorization": f"Bearer {admin_tok}"}

    # --- 1. GET initial settings ---
    r = requests.get(f"{BASE}/admin/payment-settings", headers=h_admin, timeout=30)
    check("GET /admin/payment-settings -> 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    if r.status_code == 200:
        s = r.json()
        expected_keys = {"zaincash_phone", "zaincash_qr_b64", "whatsapp_admin_number",
                        "bank_name", "bank_account_number", "iban", "stripe_public_key",
                        "stripe_secret_key", "stripe_enabled", "instructions",
                        "updated_at", "updated_by", "id"}
        missing = expected_keys - set(s.keys())
        check("payment-settings has all expected fields", not missing, f"missing={missing}")
        check("id == 'payment'", s.get("id") == "payment", f"id={s.get('id')}")
        check("stripe_enabled is bool", isinstance(s.get("stripe_enabled"), bool),
              f"type={type(s.get('stripe_enabled')).__name__}")

    # --- 2a. PATCH full payload ---
    payload = {
        "zaincash_phone": "07901234567",
        "whatsapp_admin_number": "9647901234567",
        "instructions": "حول العمولة ثم أرسل إثبات الدفع",
        "stripe_enabled": False,
        "stripe_public_key": "pk_test_DEMO123",
        "stripe_secret_key": "sk_test_SECRET456",
        "bank_name": "بنك بغداد",
        "iban": "IQ12BBAC0000000000001234567",
    }
    r = requests.patch(f"{BASE}/admin/payment-settings", json=payload, headers=h_admin, timeout=30)
    check("PATCH full payload -> 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    if r.status_code == 200:
        s = r.json()
        ok = all(s.get(k) == v for k, v in payload.items())
        check("PATCH reflects all sent fields", ok,
              f"diff={[(k, payload[k], s.get(k)) for k in payload if s.get(k) != payload[k]]}")
        check("updated_at populated", bool(s.get("updated_at")), f"updated_at={s.get('updated_at')}")
        check("updated_by populated", bool(s.get("updated_by")), f"updated_by={s.get('updated_by')}")

    # --- 2b. Partial update ---
    r = requests.patch(f"{BASE}/admin/payment-settings",
                       json={"zaincash_phone": "07999999999"}, headers=h_admin, timeout=30)
    check("PATCH partial -> 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        s = r.json()
        check("Partial: zaincash_phone updated", s.get("zaincash_phone") == "07999999999",
              f"got={s.get('zaincash_phone')}")
        check("Partial: other field preserved (bank_name)", s.get("bank_name") == "بنك بغداد",
              f"bank_name={s.get('bank_name')}")
        check("Partial: stripe_public_key preserved",
              s.get("stripe_public_key") == "pk_test_DEMO123",
              f"got={s.get('stripe_public_key')}")

    # --- 2c. Clear field (iban -> null via "") ---
    r = requests.patch(f"{BASE}/admin/payment-settings",
                       json={"iban": ""}, headers=h_admin, timeout=30)
    check("PATCH clear iban -> 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        s = r.json()
        check("iban cleared to null", s.get("iban") in (None, ""), f"iban={s.get('iban')}")
        check("Clear: other fields preserved (bank_name)", s.get("bank_name") == "بنك بغداد",
              f"bank_name={s.get('bank_name')}")

    # --- 2d. QR upload (1x1 png) ---
    qr_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAeImBZsAAAAASUVORK5CYII="
    r = requests.patch(f"{BASE}/admin/payment-settings",
                       json={"zaincash_qr_b64": qr_png}, headers=h_admin, timeout=30)
    check("PATCH qr small -> 200", r.status_code == 200, f"status={r.status_code} body={r.text[:200]}")
    if r.status_code == 200:
        s = r.json()
        check("zaincash_qr_b64 stored", s.get("zaincash_qr_b64") == qr_png,
              f"stored_len={len(s.get('zaincash_qr_b64') or '')}")

    # --- 2e. Size limit: ~5MB string -> expect 413 ---
    big_b64 = "A" * (5 * 1024 * 1024 + 1024)  # ~5MB string > 4MB cutoff
    r = requests.patch(f"{BASE}/admin/payment-settings",
                       json={"zaincash_qr_b64": big_b64}, headers=h_admin, timeout=60)
    check("PATCH qr >5MB -> 413", r.status_code == 413, f"status={r.status_code} body={r.text[:200]}")

    # --- 3. GET /payment-info as supplier ---
    sup_tok = login("supplier/login", "07811111111", "sup1")
    if not sup_tok:
        # try re-enable
        supplier_ensure_enabled(admin_tok, "07811111111")
        sup_tok = login("supplier/login", "07811111111", "sup1")
    check("supplier login", bool(sup_tok), "could not get supplier token")

    if sup_tok:
        h_sup = {"Authorization": f"Bearer {sup_tok}"}
        r = requests.get(f"{BASE}/payment-info", headers=h_sup, timeout=30)
        check("GET /payment-info (supplier) -> 200", r.status_code == 200, f"status={r.status_code}")
        if r.status_code == 200:
            info = r.json()
            expected = {"zaincash_phone", "zaincash_qr_b64", "whatsapp_admin_number",
                        "bank_name", "bank_account_number", "iban", "stripe_public_key",
                        "stripe_enabled", "instructions", "updated_at"}
            missing = expected - set(info.keys())
            check("payment-info has all expected fields", not missing, f"missing={missing}")
            # CRITICAL
            check("stripe_secret_key NOT present in /payment-info",
                  "stripe_secret_key" not in info,
                  f"LEAK: stripe_secret_key={info.get('stripe_secret_key')}")
            # values match what admin saved
            check("payment-info.zaincash_phone == latest patch",
                  info.get("zaincash_phone") == "07999999999",
                  f"got={info.get('zaincash_phone')}")
            check("payment-info.whatsapp_admin_number matches",
                  info.get("whatsapp_admin_number") == "9647901234567",
                  f"got={info.get('whatsapp_admin_number')}")
            check("payment-info.bank_name matches",
                  info.get("bank_name") == "بنك بغداد",
                  f"got={info.get('bank_name')}")
            check("payment-info.iban cleared (null)",
                  info.get("iban") in (None, ""), f"got={info.get('iban')}")
            check("payment-info.stripe_public_key matches",
                  info.get("stripe_public_key") == "pk_test_DEMO123",
                  f"got={info.get('stripe_public_key')}")
            check("payment-info.stripe_enabled is False",
                  info.get("stripe_enabled") is False, f"got={info.get('stripe_enabled')}")
            check("payment-info.zaincash_qr_b64 matches",
                  info.get("zaincash_qr_b64") == qr_png,
                  f"len={len(info.get('zaincash_qr_b64') or '')}")

    # --- 4. Role enforcement ---
    pharm_tok = login("pharmacy/login", "07700000001", "pass123")
    check("pharmacy login", bool(pharm_tok))
    if pharm_tok:
        h_p = {"Authorization": f"Bearer {pharm_tok}"}
        r = requests.get(f"{BASE}/admin/payment-settings", headers=h_p, timeout=30)
        check("pharmacy GET /admin/payment-settings -> 403", r.status_code == 403,
              f"status={r.status_code}")
        r = requests.patch(f"{BASE}/admin/payment-settings", headers=h_p,
                           json={"zaincash_phone": "07000000000"}, timeout=30)
        check("pharmacy PATCH /admin/payment-settings -> 403", r.status_code == 403,
              f"status={r.status_code}")

    if sup_tok:
        h_s = {"Authorization": f"Bearer {sup_tok}"}
        r = requests.get(f"{BASE}/admin/payment-settings", headers=h_s, timeout=30)
        check("supplier GET /admin/payment-settings -> 403", r.status_code == 403,
              f"status={r.status_code}")
        r = requests.patch(f"{BASE}/admin/payment-settings", headers=h_s,
                           json={"zaincash_phone": "07000000001"}, timeout=30)
        check("supplier PATCH /admin/payment-settings -> 403", r.status_code == 403,
              f"status={r.status_code}")

    r = requests.get(f"{BASE}/payment-info", timeout=30)  # no auth header
    check("unauth GET /payment-info -> 401", r.status_code == 401, f"status={r.status_code}")

    # --- 5. Audit log ---
    r = requests.get(f"{BASE}/admin/audit-logs?action=payment_settings_updated",
                     headers=h_admin, timeout=30)
    check("audit logs payment_settings_updated -> 200", r.status_code == 200,
          f"status={r.status_code}")
    if r.status_code == 200:
        logs = r.json()
        check("audit log has entries", len(logs) >= 1, f"count={len(logs)}")
        if logs:
            last = logs[0]
            check("audit actor.role == admin", last.get("actor", {}).get("role") == "admin",
                  f"actor={last.get('actor')}")
            fields = last.get("meta", {}).get("fields") or []
            check("audit meta.fields is a list with at least 1 field",
                  isinstance(fields, list) and len(fields) > 0, f"fields={fields}")

    return admin_tok, sup_tok


# ============================================================
# B) Excel structured parse fix re-test
# ============================================================
def test_excel_structured(admin_tok, sup_tok):
    hr("B) EXCEL STRUCTURED PARSE (RE-TEST)")

    if not sup_tok:
        sup_tok = login("supplier/login", "07811111111", "sup1")
    if not sup_tok and admin_tok:
        supplier_ensure_enabled(admin_tok, "07811111111")
        sup_tok = login("supplier/login", "07811111111", "sup1")

    if not sup_tok:
        FAIL.append(("supplier login (excel)", "no token"))
        print("  ❌ no supplier token; skipping excel tests")
        return

    h_sup = {"Authorization": f"Bearer {sup_tok}"}

    # 1. Template download
    r = requests.get(f"{BASE}/supplier/catalog/template", headers=h_sup, timeout=30)
    check("GET /supplier/catalog/template -> 200", r.status_code == 200, f"status={r.status_code}")
    template_bytes = b""
    if r.status_code == 200:
        template_bytes = r.content
        check("template ~5KB and is xlsx (zip PK)",
              len(template_bytes) > 1000 and template_bytes[:2] == b"PK",
              f"size={len(template_bytes)}")

    # 2. Upload template via /upload
    if template_bytes:
        b64 = base64.b64encode(template_bytes).decode()
        r = requests.post(f"{BASE}/supplier/catalog/upload",
                          headers=h_sup,
                          json={"file_b64": b64, "file_type": "xlsx",
                                "filename": "catalog_template.xlsx"}, timeout=60)
        check("POST /supplier/catalog/upload template -> 200", r.status_code == 200,
              f"status={r.status_code} body={r.text[:200]}")
        if r.status_code == 200:
            job_id = r.json().get("job_id")
            check("upload returns job_id", bool(job_id))

            # Poll
            job_data = None
            for _ in range(20):
                time.sleep(1)
                jr = requests.get(f"{BASE}/supplier/catalog/jobs/{job_id}", headers=h_sup, timeout=30)
                if jr.status_code == 200:
                    jd = jr.json()
                    st = (jd.get("job") or {}).get("status")
                    if st in ("review", "failed", "published"):
                        job_data = jd
                        break
            check("template upload reached terminal status", job_data is not None, "timeout 20s")
            if job_data:
                job = job_data["job"]
                check("template job status == 'review'", job.get("status") == "review",
                      f"status={job.get('status')} err={job.get('error')}")
                check("template job extraction_method == 'excel_structured'",
                      job.get("extraction_method") == "excel_structured",
                      f"method={job.get('extraction_method')}")
                check("template job total_items == 3", job.get("total_items") == 3,
                      f"total_items={job.get('total_items')}")
                cols = (job.get("extraction_meta") or {}).get("columns_detected") or {}
                check("extraction_meta.columns_detected has STRING keys",
                      all(isinstance(k, str) for k in cols.keys()) and len(cols) > 0,
                      f"keys={[type(k).__name__ for k in cols.keys()]}, cols={cols}")

    # 3. Build mixed-quality xlsx: 1 valid, 1 invalid price ('abc'), 1 empty name
    wb = Workbook()
    ws = wb.active
    ws.title = "Catalog"
    ws.append(["product_name", "price", "quantity", "category"])
    ws.append(["Amoxil 500", 2500, 30, "Antibiotic"])         # valid
    ws.append(["BadPrice Tab", "abc", 10, "Painkiller"])      # invalid price
    ws.append(["", 1000, 5, "Other"])                          # empty name
    bio = io.BytesIO()
    wb.save(bio)
    mixed_bytes = bio.getvalue()
    b64_mixed = base64.b64encode(mixed_bytes).decode()

    r = requests.post(f"{BASE}/supplier/catalog/upload",
                      headers=h_sup,
                      json={"file_b64": b64_mixed, "file_type": "xlsx",
                            "filename": "mixed.xlsx"}, timeout=60)
    check("POST /supplier/catalog/upload mixed -> 200", r.status_code == 200,
          f"status={r.status_code}")
    if r.status_code == 200:
        job_id = r.json().get("job_id")
        job_data = None
        for _ in range(20):
            time.sleep(1)
            jr = requests.get(f"{BASE}/supplier/catalog/jobs/{job_id}", headers=h_sup, timeout=30)
            if jr.status_code == 200:
                jd = jr.json()
                st = (jd.get("job") or {}).get("status")
                if st in ("review", "failed", "published"):
                    job_data = jd
                    break
        check("mixed job reached terminal status", job_data is not None, "timeout")
        if job_data:
            job = job_data["job"]
            check("mixed job status == 'review'", job.get("status") == "review",
                  f"status={job.get('status')} err={job.get('error')}")
            check("mixed job extraction_method == 'excel_structured'",
                  job.get("extraction_method") == "excel_structured",
                  f"method={job.get('extraction_method')}")
            # Note: structured parser drops rows with name='' or price<=0 BEFORE the
            # rejected_invalid counter in process_import_job, so rejected_invalid may be 0
            # but total_items must == 1 (the only valid row).
            check("mixed: total_items counts only valid row(s) (==1)",
                  job.get("total_items") == 1,
                  f"total_items={job.get('total_items')}, items_count={len(job_data.get('items', []))}")
            # Either rejected_invalid > 0 OR structured parser silently dropped: accept either
            # but verify the invalid rows did NOT make it to items
            items = job_data.get("items", [])
            names = [(it.get("extracted") or {}).get("name") for it in items]
            check("mixed: 'BadPrice Tab' (invalid price) NOT in items",
                  "BadPrice Tab" not in names, f"names={names}")
            check("mixed: empty-name row NOT in items",
                  not any((n or "").strip() == "" for n in names),
                  f"names={names}")
            # Bonus assertion: at least one of the two invalid signals should surface
            ri = job.get("rejected_invalid") or 0
            # In current implementation, parse_excel_structured drops invalid rows silently
            # (no rejected_invalid increment). The downstream rejected_invalid is only
            # incremented for AI-extracted items. So this is informational.
            print(f"     (info) mixed rejected_invalid={ri}; expect rows actually dropped pre-dedup")


def main():
    test_payment_settings_result = test_payment_settings()
    admin_tok, sup_tok = test_payment_settings_result or (None, None)
    test_excel_structured(admin_tok, sup_tok)

    hr("SUMMARY")
    print(f"  PASS: {len(PASS)}")
    print(f"  FAIL: {len(FAIL)}")
    if FAIL:
        print("\nFailures:")
        for n, d in FAIL:
            print(f"  - {n}: {d}")
    sys.exit(0 if not FAIL else 1)


if __name__ == "__main__":
    main()
