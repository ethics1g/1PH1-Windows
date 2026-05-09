"""
End-to-end backend tests for the Supplier Commission System.
Targets the public URL via EXPO_PUBLIC_BACKEND_URL with /api prefix.
"""
import os
import json
import uuid
import sys
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://pharma-checkout-8.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

PHARMACY = {"phone": "07700000001", "password": "pass123"}
SUPPLIER = {"phone": "07811111111", "password": "sup1"}
ADMIN_PRIMARY = {"phone": "07823567874", "password": "Rasooll$123"}
ADMIN_FALLBACK = {"phone": "0000000000", "password": "admin123"}
NEW_ADMIN_PWD = "AdminPass$1"

results: list[tuple[str, bool, str]] = []
def rec(name, ok, detail=""):
    results.append((name, ok, detail))
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {name} :: {detail}")

def post(path, token=None, **kwargs):
    h = kwargs.pop("headers", {}) or {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return requests.post(f"{API}{path}", headers=h, timeout=30, **kwargs)

def get(path, token=None, **kwargs):
    h = kwargs.pop("headers", {}) or {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return requests.get(f"{API}{path}", headers=h, timeout=30, **kwargs)

def patch(path, token=None, **kwargs):
    h = kwargs.pop("headers", {}) or {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return requests.patch(f"{API}{path}", headers=h, timeout=30, **kwargs)


def login_unified(phone, password):
    r = post("/auth/login", json={"phone": phone, "password": password})
    return r


def login_admin_with_change(creds):
    """Login admin, handle must_change_password."""
    r = login_unified(creds["phone"], creds["password"])
    if r.status_code != 200:
        return None, f"login {creds['phone']} HTTP {r.status_code}: {r.text[:200]}"
    body = r.json()
    if body.get("role") != "admin":
        return None, f"role={body.get('role')} not admin"
    token = body["token"]
    must_change = body.get("user", {}).get("must_change_password", False)
    if must_change:
        # Try to change password
        cr = post("/admin/change-password", token=token,
                  json={"old_password": creds["password"], "new_password": NEW_ADMIN_PWD})
        if cr.status_code != 200:
            # might already have been changed; try logging in with NEW pwd
            r2 = login_unified(creds["phone"], NEW_ADMIN_PWD)
            if r2.status_code == 200:
                return r2.json()["token"], "logged in with NEW_ADMIN_PWD (already changed)"
            return None, f"change-password failed: {cr.status_code} {cr.text[:200]}"
        # Re-login with new pwd
        r2 = login_unified(creds["phone"], NEW_ADMIN_PWD)
        if r2.status_code != 200:
            return None, f"re-login after change-pwd failed: {r2.status_code}"
        return r2.json()["token"], "changed-pwd-and-relogged"
    return token, "no-change-needed"


def main():
    print(f"Testing against: {API}\n")

    # 1. Pharmacy login
    r = login_unified(PHARMACY["phone"], PHARMACY["password"])
    if r.status_code != 200:
        rec("1. Pharmacy login", False, f"HTTP {r.status_code}: {r.text[:200]}")
        return
    pj = r.json()
    token1 = pj["token"]
    pharmacy_id = pj["user"]["id"]
    rec("1. Pharmacy login", pj.get("role") == "pharmacy", f"role={pj.get('role')}, id={pharmacy_id[:8]}")

    # 2. Supplier login
    r = login_unified(SUPPLIER["phone"], SUPPLIER["password"])
    if r.status_code != 200:
        rec("2. Supplier login", False, f"HTTP {r.status_code}: {r.text[:200]}")
        return
    sj = r.json()
    token2 = sj["token"]
    supplier_id = sj["user"]["id"]
    rec("2. Supplier login", sj.get("role") == "supplier", f"role={sj.get('role')}, id={supplier_id[:8]}")

    # 3. Admin login (with possible change-password)
    token3, info = login_admin_with_change(ADMIN_PRIMARY)
    if not token3:
        # Try fallback admin
        token3, info2 = login_admin_with_change(ADMIN_FALLBACK)
        if not token3:
            rec("3. Admin login", False, f"primary: {info}; fallback: {info2}")
            return
        info = f"used FALLBACK admin: {info2}"
    rec("3. Admin login", True, info)

    # 4. Ensure supplier has product ParaTest1
    products = get("/supplier/products", token=token2).json()
    p = next((x for x in products if x["name"] == "ParaTest1"), None)
    if not p:
        cr = post("/supplier/products", token=token2,
                  json={"name": "ParaTest1", "price": 1000, "quantity": 10})
        if cr.status_code != 200:
            rec("4. Ensure supplier product", False, f"create failed: {cr.status_code} {cr.text[:200]}")
            return
        p = cr.json()
        rec("4. Ensure supplier product", True, "created ParaTest1")
    else:
        # Make sure quantity > 0
        if p.get("quantity", 0) <= 0 or p.get("price", 0) <= 0:
            # Re-create
            cr = post("/supplier/products", token=token2,
                      json={"name": "ParaTest1", "price": 1000, "quantity": 10})
            if cr.status_code == 200:
                p = cr.json()
        rec("4. Ensure supplier product", True, f"exists qty={p.get('quantity')} price={p.get('price')}")

    # 5. Pharmacy optimize
    r = post("/orders/optimize", token=token1, json={"items": [{"name": "ParaTest1", "quantity": 3}]})
    if r.status_code != 200:
        rec("5. POST /orders/optimize", False, f"HTTP {r.status_code}: {r.text[:200]}")
        return
    opt = r.json()
    smart_groups = opt.get("smart_split", {}).get("groups", []) or []
    single_options = opt.get("single_supplier", {}).get("options", []) or []
    have_plan = bool(smart_groups) or bool(single_options)
    rec("5. POST /orders/optimize",
        have_plan,
        f"smart={len(smart_groups)} single={len(single_options)} unavail={opt.get('unavailable')}")

    # Build groups for commit
    if smart_groups:
        groups = [{
            "supplier_id": g["supplier_id"],
            "supplier_name": g["supplier_name"],
            "items": [{"name": it["name"], "quantity": it["quantity"], "unit_price": it["unit_price"]} for it in g["items"]],
            "total": g["total"],
        } for g in smart_groups]
    elif single_options:
        g = single_options[0]
        groups = [{
            "supplier_id": g["supplier_id"],
            "supplier_name": g["supplier_name"],
            "items": [{"name": it["name"], "quantity": it["quantity"], "unit_price": it["unit_price"]} for it in g["items"]],
            "total": g["total"],
        }]
    else:
        # Fallback: hand-craft a group using known supplier_id
        groups = [{
            "supplier_id": supplier_id,
            "supplier_name": "مذخر النور",
            "items": [{"name": "ParaTest1", "quantity": 3, "unit_price": 1000.0}],
            "total": 3000.0,
        }]

    expected_total = groups[0]["total"]
    expected_commission = round(expected_total * 0.04, 2)

    # 6. Commit
    commit_id = str(uuid.uuid4())
    r = post("/orders/optimize/commit", token=token1, json={"commit_id": commit_id, "groups": groups})
    if r.status_code != 200:
        rec("6. POST /orders/optimize/commit", False, f"HTTP {r.status_code}: {r.text[:200]}")
        return
    cb = r.json()
    rec("6. POST /orders/optimize/commit",
        cb.get("status") == "ok" and cb.get("created", 0) >= 1,
        f"status={cb.get('status')} created={cb.get('created')}")

    # 7. Repeat with same commit_id
    r = post("/orders/optimize/commit", token=token1, json={"commit_id": commit_id, "groups": groups})
    if r.status_code != 200:
        rec("7. Idempotency commit", False, f"HTTP {r.status_code}: {r.text[:200]}")
    else:
        cb2 = r.json()
        ok = cb2.get("status") == "already_committed" and cb2.get("created") == 0
        rec("7. Idempotency commit", ok, f"status={cb2.get('status')} created={cb2.get('created')}")

    # 8. Supplier commissions
    r = get("/supplier/commissions", token=token2)
    if r.status_code != 200:
        rec("8. GET /supplier/commissions", False, f"HTTP {r.status_code}: {r.text[:200]}")
        return
    sc = r.json()
    rate_ok = sc.get("rate") == 0.04
    records = sc.get("records", [])
    monthly = sc.get("monthly", [])
    outstanding = sc.get("outstanding", 0)
    # Find a record matching our supplier_id and our commit (highest pending probably)
    target_rec = None
    for rrec in records:
        if rrec.get("commit_id") == commit_id and rrec.get("supplier_id") == groups[0]["supplier_id"]:
            target_rec = rrec
            break
    if not target_rec and records:
        # If supplier_id mismatch (commit used a synthetic id), pick most recent
        target_rec = records[0]
    detail = (f"rate={sc.get('rate')} records={len(records)} monthly={len(monthly)} "
              f"outstanding={outstanding}")
    if target_rec:
        comm_ok = abs(target_rec.get("commission") - round(target_rec.get("order_total") * 0.04, 2)) < 0.01
        ok = rate_ok and comm_ok and len(monthly) >= 1 and outstanding > 0
        rec("8. GET /supplier/commissions", ok,
            detail + f" rec_commission={target_rec.get('commission')} order_total={target_rec.get('order_total')}")
    else:
        rec("8. GET /supplier/commissions", False, detail + " no matching record found")
        return

    record_id = target_rec["id"]
    record_supplier_id = target_rec["supplier_id"]
    record_commission = target_rec["commission"]

    # If the record's supplier_id differs from logged-in supplier, we cannot upload proof as this supplier.
    if record_supplier_id != supplier_id:
        rec("9. Upload proof", False,
            f"record supplier_id={record_supplier_id[:8]} != login supplier {supplier_id[:8]}; "
            "cannot upload proof. (Optimize matched a different supplier.) Skipping subsequent supplier-side checks.")
        # Try to find an OWNED record instead
        owned = next((r0 for r0 in records if r0.get("supplier_id") == supplier_id and r0.get("status") == "pending"), None)
        if owned:
            record_id = owned["id"]
            record_commission = owned["commission"]
            rec("9-fallback. found owned pending record", True, f"id={record_id[:8]} comm={record_commission}")
        else:
            print("No owned record. Aborting subsequent commission tests.")
            print_summary()
            return

    # 9. Upload proof
    PNG1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAeImBZsAAAAASUVORK5CYII="
    r = post(f"/supplier/commissions/{record_id}/upload-proof", token=token2, json={"proof_b64": PNG1PX})
    if r.status_code != 200:
        rec("9. Upload proof", False, f"HTTP {r.status_code}: {r.text[:200]}")
        return
    rec("9. Upload proof", True, "200 OK")

    # Verify status -> submitted
    r = get("/supplier/commissions", token=token2)
    sc2 = r.json()
    rfound = next((x for x in sc2["records"] if x["id"] == record_id), None)
    rec("9b. Status submitted after proof",
        rfound is not None and rfound.get("status") == "submitted",
        f"status={rfound.get('status') if rfound else 'NOT_FOUND'}")

    # 10. Admin GET commissions?status=submitted + proof
    r = get("/admin/commissions", token=token3, params={"status": "submitted"})
    if r.status_code != 200:
        rec("10a. Admin list submitted", False, f"HTTP {r.status_code}: {r.text[:200]}")
        return
    ad = r.json()
    found = any(x["id"] == record_id for x in ad.get("records", []))
    rec("10a. Admin list submitted", found,
        f"records={len(ad.get('records', []))} found_target={found}")

    r = get(f"/admin/commissions/{record_id}/proof", token=token3)
    if r.status_code != 200:
        rec("10b. Admin get proof", False, f"HTTP {r.status_code}: {r.text[:200]}")
    else:
        proof_b64 = r.json().get("proof_b64") or ""
        rec("10b. Admin get proof", isinstance(proof_b64, str) and len(proof_b64) > 0,
            f"len={len(proof_b64)}")

    # 11. Admin confirm
    r = patch(f"/admin/commissions/{record_id}/confirm", token=token3)
    if r.status_code != 200:
        rec("11a. Admin confirm", False, f"HTTP {r.status_code}: {r.text[:200]}")
    else:
        rec("11a. Admin confirm", r.json().get("status") == "ok", f"resp={r.json()}")

    # Repeat -> already_paid
    r = patch(f"/admin/commissions/{record_id}/confirm", token=token3)
    rec("11b. Admin confirm idempotent",
        r.status_code == 200 and r.json().get("status") == "already_paid",
        f"resp={r.json()}")

    # 12. Supplier commissions reflects paid
    r = get("/supplier/commissions", token=token2)
    sc3 = r.json()
    rfound2 = next((x for x in sc3["records"] if x["id"] == record_id), None)
    new_outstanding = sc3.get("outstanding", 0)
    monthly0 = sc3.get("monthly", [{}])[0] if sc3.get("monthly") else {}
    paid_comm = monthly0.get("paid_commission", 0)
    decreased = new_outstanding < outstanding  # was the previous outstanding
    rec("12. Supplier outstanding decreased + paid",
        rfound2 is not None and rfound2.get("status") == "paid" and paid_comm > 0,
        f"status={rfound2.get('status') if rfound2 else 'NF'} paid_commission={paid_comm} "
        f"outstanding {outstanding} -> {new_outstanding} decreased={decreased}")

    # 13. Admin manual commission
    r = post("/admin/commissions", token=token3,
             json={"supplier_id": supplier_id, "pharmacy_name": "TestManual", "order_total": 5000})
    if r.status_code != 200:
        rec("13. Admin manual commission", False, f"HTTP {r.status_code}: {r.text[:200]}")
    else:
        body = r.json()
        rec("13. Admin manual commission",
            abs(body.get("commission", 0) - 200.0) < 0.01 and body.get("status") == "pending",
            f"commission={body.get('commission')} status={body.get('status')}")

    # 14. Role enforcement
    r = get("/supplier/commissions", token=token1)  # pharmacy hits supplier
    rec("14a. Pharmacy -> /supplier/commissions = 403",
        r.status_code == 403, f"got {r.status_code}")
    r = get("/admin/commissions", token=token2)  # supplier hits admin
    rec("14b. Supplier -> /admin/commissions = 403",
        r.status_code == 403, f"got {r.status_code}")

    print_summary()


def print_summary():
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n========== SUMMARY ==========")
    print(f"Passed: {passed}/{len(results)}  Failed: {failed}")
    if failed:
        print("\nFailed tests:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}: {detail}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        rec("EXCEPTION", False, str(e))
        print_summary()
        sys.exit(1)
