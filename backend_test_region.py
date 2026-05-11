"""
Backend tests for strict region-based marketplace filtering.

Tests A..I from the review request.
"""
import os
import sys
import json
import time
import uuid
import requests
from typing import Optional

BASE = os.environ.get("BACKEND_URL", "https://pharma-checkout-8.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

PASS = []
FAIL = []


def _log(ok: bool, label: str, detail: str = ""):
    tag = "PASS" if ok else "FAIL"
    line = f"[{tag}] {label}" + (f" :: {detail}" if detail else "")
    print(line)
    (PASS if ok else FAIL).append(line)


def post(path, body=None, token=None, expect_status=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.post(f"{API}{path}", json=body, headers=h, timeout=30)
    return r


def patch(path, body=None, token=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.patch(f"{API}{path}", json=body, headers=h, timeout=30)


def get(path, token=None, params=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.get(f"{API}{path}", headers=h, params=params, timeout=30)


# -----------------------------------------------------------------
# Setup: log in admin so we can toggle marketplace_mode at the end
# -----------------------------------------------------------------
admin_token = None
r = post("/admin/login", {"phone": "0000000000", "password": "admin123"})
if r.status_code != 200:
    print("FATAL: admin login failed", r.status_code, r.text)
    sys.exit(1)
admin_token = r.json()["token"]

# Ensure mode=local at start
patch("/admin/payment-settings", {"marketplace_mode": "local"}, token=admin_token)


# -----------------------------------------------------------------
# Helpers to register/login pharmacy or supplier with unique phones
# -----------------------------------------------------------------
def reset_user(phone: str, role: str):
    """Delete any existing user via admin to make tests deterministic."""
    # Find via /admin/users
    r = get(f"/admin/users", token=admin_token, params={"role": role, "limit": 500})
    if r.status_code != 200:
        return
    for u in r.json():
        if u.get("phone") == phone:
            requests.delete(f"{API}/admin/users/{role}/{u['id']}",
                            headers={"Authorization": f"Bearer {admin_token}"})


def register_pharmacy(name, phone, password, address, region, country=None):
    body = {"name": name, "phone": phone, "password": password, "address": address}
    if region is not None:
        body["region"] = region
    if country is not None:
        body["country"] = country
    return post("/pharmacy/register", body)


def register_supplier(name, phone, password, address, region, country=None):
    body = {"name": name, "phone": phone, "password": password, "address": address}
    if region is not None:
        body["region"] = region
    if country is not None:
        body["country"] = country
    return post("/supplier/register", body)


def login_pharmacy(phone, password):
    return post("/pharmacy/login", {"phone": phone, "password": password})


def login_supplier(phone, password):
    return post("/supplier/login", {"phone": phone, "password": password})


# -----------------------------------------------------------------
# A. Backward compatibility (legacy users without region)
# -----------------------------------------------------------------
print("\n=== A. Backward compatibility ===")
# Clear region on legacy users to simulate "no region" state
import pymongo
from pymongo import MongoClient
mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
# Try connecting locally to clear region; if not possible, skip
try:
    mc = MongoClient(mongo_url, serverSelectionTimeoutMS=2000)
    dbn = os.environ.get("DB_NAME", "test_database")
    mdb = mc[dbn]
    mdb.pharmacies.update_one({"phone": "07700000001"},
                              {"$unset": {"region": "", "region_normalized": "", "country": ""}})
    mdb.suppliers.update_one({"phone": "07811111111"},
                             {"$unset": {"region": "", "region_normalized": "", "country": ""}})
    # ensure not disabled
    mdb.suppliers.update_one({"phone": "07811111111"}, {"$set": {"disabled": False}})
    mdb.pharmacies.update_one({"phone": "07700000001"}, {"$set": {"disabled": False}})
    print("[setup] Cleared region on legacy users + ensured enabled")
except Exception as e:
    print(f"[setup] WARN cannot clear region directly via mongo ({e}); will proceed assuming legacy state")

# A.1 login pharmacy A
r = login_pharmacy("07700000001", "pass123")
_log(r.status_code == 200, "A.1 pharmacy A login", f"status={r.status_code}")
phA_data = r.json() if r.status_code == 200 else {}
phA_token = phA_data.get("token")
_log(phA_data.get("must_set_region") is True,
     "A.1 pharmacy A must_set_region=true",
     f"got {phA_data.get('must_set_region')}")

# A.2 login supplier A
r = login_supplier("07811111111", "sup1")
_log(r.status_code == 200, "A.2 supplier A login", f"status={r.status_code} {r.text[:100]}")
spA_data = r.json() if r.status_code == 200 else {}
spA_token = spA_data.get("token")
_log(spA_data.get("must_set_region") is True,
     "A.2 supplier A must_set_region=true",
     f"got {spA_data.get('must_set_region')}")

# A.3 POST /api/orders/optimize as pharmacy A (no region) — should still work
r = post("/orders/optimize", {"items": [{"name": "ParaTest1", "quantity": 1}]}, token=phA_token)
_log(r.status_code == 200, "A.3 pharmacy A optimize works without region (degraded open)",
     f"status={r.status_code} body={r.text[:120]}")


# -----------------------------------------------------------------
# B. Registration validation
# -----------------------------------------------------------------
print("\n=== B. Registration validation ===")

# B.1 pharmacy register without region
r = post("/pharmacy/register",
         {"name": "PhTest", "phone": f"0779{uuid.uuid4().int % 10**7:07d}",
          "password": "x", "address": "a"})
ok = (r.status_code in (400, 422))
if r.status_code == 422:
    detail = r.text.lower()
    ok = "region" in detail
elif r.status_code == 400:
    ok = "region" in r.text.lower() or "منطق" in r.text
_log(ok, "B.1 pharmacy register without region -> 400/422",
     f"status={r.status_code} body={r.text[:150]}")

# B.2 supplier register without region
r = post("/supplier/register",
         {"name": "SpTest", "phone": f"0789{uuid.uuid4().int % 10**7:07d}",
          "password": "x", "address": "a"})
ok = (r.status_code in (400, 422))
if r.status_code == 422:
    ok = "region" in r.text.lower()
elif r.status_code == 400:
    ok = "region" in r.text.lower() or "منطق" in r.text
_log(ok, "B.2 supplier register without region -> 400/422",
     f"status={r.status_code} body={r.text[:150]}")

# B.3 pharmacy register with region="Baghdad", country="Iraq"
B3_PHONE = f"077{uuid.uuid4().int % 10**8:08d}"
r = register_pharmacy("PhBaghdad", B3_PHONE, "pwd123", "addr", "Baghdad", "Iraq")
_log(r.status_code == 200, "B.3 pharmacy register with region+country -> 200",
     f"status={r.status_code} body={r.text[:200]}")
if r.status_code == 200:
    body = r.json()
    _log(body.get("pharmacy", {}).get("region") == "Baghdad",
         "B.3 pharmacy.region == 'Baghdad'",
         f"got {body.get('pharmacy', {}).get('region')}")

# B.4 same phone same supplier register again -> 400 (duplicate)
DUP_PHONE = f"078{uuid.uuid4().int % 10**8:08d}"
r1 = register_supplier("DupS", DUP_PHONE, "p", "a", "Baghdad", "Iraq")
_log(r1.status_code == 200, "B.4 first supplier register -> 200", f"status={r1.status_code}")
r2 = register_supplier("DupS", DUP_PHONE, "p", "a", "Baghdad", "Iraq")
_log(r2.status_code == 400, "B.4 duplicate supplier register -> 400",
     f"status={r2.status_code} body={r2.text[:120]}")


# -----------------------------------------------------------------
# C. Set-region flow (use pharmacy A and supplier A, then re-login)
# -----------------------------------------------------------------
print("\n=== C. Set-region flow ===")

# C.1 PATCH set-region as pharmacy A with diacritic بَغداد
r = patch("/auth/set-region",
          {"region": "بَغداد", "country": "العراق"}, token=phA_token)
_log(r.status_code == 200, "C.1 pharmacy A set-region بَغداد -> 200",
     f"status={r.status_code} body={r.text[:200]}")
if r.status_code == 200:
    body = r.json()
    _log(body.get("region") == "بَغداد" and body.get("country") == "العراق",
         "C.1 response region+country round-trip",
         f"got region={body.get('region')!r} country={body.get('country')!r}")

# C.2 PATCH set-region as supplier A with بغداد (no diacritic)
r = patch("/auth/set-region", {"region": "بغداد"}, token=spA_token)
_log(r.status_code == 200, "C.2 supplier A set-region بغداد -> 200",
     f"status={r.status_code} body={r.text[:200]}")

# C.3 empty region -> 400
r = patch("/auth/set-region", {"region": ""}, token=phA_token)
_log(r.status_code == 400, "C.3 empty region -> 400",
     f"status={r.status_code} body={r.text[:120]}")

# C.4 pharmacy A re-login -> must_set_region == false
r = login_pharmacy("07700000001", "pass123")
phA2 = r.json() if r.status_code == 200 else {}
phA_token = phA2.get("token") or phA_token
_log(phA2.get("must_set_region") is False,
     "C.4 pharmacy A re-login must_set_region=false",
     f"got {phA2.get('must_set_region')}")


# -----------------------------------------------------------------
# D. Diacritic/case-insensitive matching
# -----------------------------------------------------------------
print("\n=== D. Diacritic/case-insensitive matching ===")

# Cleanup any prior runs (test phones may persist between runs)
SUPB_PHONE = "07712340001"
SUPC_PHONE = "07712340002"
reset_user(SUPB_PHONE, "supplier")
reset_user(SUPC_PHONE, "supplier")

rB = register_supplier("Test SupB", SUPB_PHONE, "pwdB", "addrB", "BAGHDAD", "Iraq")
_log(rB.status_code == 200, "D.2a register SupB region=BAGHDAD",
     f"status={rB.status_code} body={rB.text[:200]}")
spB_token = rB.json().get("token") if rB.status_code == 200 else None
spB_id = rB.json().get("supplier", {}).get("id") if rB.status_code == 200 else None

rC = register_supplier("Test SupC", SUPC_PHONE, "pwdC", "addrC", "basra", "Iraq")
_log(rC.status_code == 200, "D.2b register SupC region=basra",
     f"status={rC.status_code} body={rC.text[:200]}")
spC_token = rC.json().get("token") if rC.status_code == 200 else None
spC_id = rC.json().get("supplier", {}).get("id") if rC.status_code == 200 else None

# D.3: SupB adds product MedB1
if spB_token:
    rp = post("/supplier/products", {"name": "MedB1", "price": 1000, "quantity": 5}, token=spB_token)
    _log(rp.status_code == 200, "D.3 SupB add MedB1",
         f"status={rp.status_code} body={rp.text[:200]}")
    if rp.status_code == 200:
        rn = rp.json().get("region_normalized")
        _log(rn == "baghdad", "D.3 MedB1 region_normalized=baghdad",
             f"got {rn!r}")

# D.4: SupC adds product MedC1
if spC_token:
    rp = post("/supplier/products", {"name": "MedC1", "price": 2000, "quantity": 5}, token=spC_token)
    _log(rp.status_code == 200, "D.4 SupC add MedC1",
         f"status={rp.status_code} body={rp.text[:200]}")

# D.5: pharmacy A region "بَغداد" -> normalized "بغداد" (Arabic). Should NOT match SupB ("baghdad" latin).
r = get("/marketplace", token=phA_token)
_log(r.status_code == 200, "D.5 pharmacy A GET /marketplace -> 200",
     f"status={r.status_code}")
if r.status_code == 200:
    items = r.json()
    names = [p["name"] for p in items]
    _log("MedC1" not in names, "D.5 pharmacy A marketplace excludes MedC1 (basra)",
         f"names={names[:10]}")
    _log("MedB1" not in names, "D.5 pharmacy A (Arabic بغداد) excludes MedB1 (Latin baghdad) — expected per spec",
         f"names={names[:10]}")


# -----------------------------------------------------------------
# E. Marketplace filtering — same Arabic region
# -----------------------------------------------------------------
print("\n=== E. Same-region Arabic filtering ===")

P_BG_PHONE = "07712340101"
S_BG_PHONE = "07712340201"
S_BA_PHONE = "07712340202"
reset_user(P_BG_PHONE, "pharmacy")
reset_user(S_BG_PHONE, "supplier")
reset_user(S_BA_PHONE, "supplier")

# E.1 Create Pharmacy P_BG (بغداد)
rPbg = register_pharmacy("P_BG", P_BG_PHONE, "pbg1", "addr", "بغداد", "العراق")
_log(rPbg.status_code == 200, "E.1 register P_BG (بغداد)", f"status={rPbg.status_code} body={rPbg.text[:200]}")
pbg_token = rPbg.json().get("token") if rPbg.status_code == 200 else None

# E.2 Create Supplier S_BG (بغداد) + S_BA (البصرة)
rSbg = register_supplier("S_BG", S_BG_PHONE, "sbg1", "addr", "بغداد", "العراق")
_log(rSbg.status_code == 200, "E.2a register S_BG (بغداد)", f"status={rSbg.status_code}")
sbg_token = rSbg.json().get("token") if rSbg.status_code == 200 else None
sbg_id = rSbg.json().get("supplier", {}).get("id") if rSbg.status_code == 200 else None

rSba = register_supplier("S_BA", S_BA_PHONE, "sba1", "addr", "البصرة", "العراق")
_log(rSba.status_code == 200, "E.2b register S_BA (البصرة)", f"status={rSba.status_code}")
sba_token = rSba.json().get("token") if rSba.status_code == 200 else None
sba_id = rSba.json().get("supplier", {}).get("id") if rSba.status_code == 200 else None

# E.3 add products
if sbg_token:
    r = post("/supplier/products", {"name": "BG_MED", "price": 500, "quantity": 10}, token=sbg_token)
    _log(r.status_code == 200, "E.3a S_BG add BG_MED", f"status={r.status_code}")
if sba_token:
    r = post("/supplier/products", {"name": "BA_MED", "price": 600, "quantity": 10}, token=sba_token)
    _log(r.status_code == 200, "E.3b S_BA add BA_MED", f"status={r.status_code}")

# E.4 P_BG marketplace -> includes BG_MED, excludes BA_MED
r = get("/marketplace", token=pbg_token)
if r.status_code == 200:
    items = r.json()
    names = [p["name"] for p in items]
    _log("BG_MED" in names, "E.4 P_BG marketplace includes BG_MED",
         f"names={names[:15]}")
    _log("BA_MED" not in names, "E.4 P_BG marketplace EXCLUDES BA_MED",
         f"names={names[:15]}")
else:
    _log(False, "E.4 GET /marketplace", f"status={r.status_code}")

# E.5 P_BG /suppliers -> includes S_BG, excludes S_BA
r = get("/suppliers", token=pbg_token)
if r.status_code == 200:
    s_list = r.json()
    ids = [s["id"] for s in s_list]
    _log(sbg_id in ids, "E.5 P_BG /suppliers includes S_BG", f"#items={len(ids)}")
    _log(sba_id not in ids, "E.5 P_BG /suppliers EXCLUDES S_BA", f"sba in ids? {sba_id in ids}")
else:
    _log(False, "E.5 GET /suppliers", f"status={r.status_code}")

# E.6 optimize for BA_MED -> shouldn't include S_BA
r = post("/orders/optimize", {"items": [{"name": "BA_MED", "quantity": 1}]}, token=pbg_token)
if r.status_code == 200:
    body = r.json()
    unavail = body.get("unavailable", [])
    sg = body.get("smart_split", {}).get("groups", [])
    ss_opts = body.get("single_supplier", {}).get("options", [])
    cond = ("BA_MED" in unavail) or (not sg and not ss_opts)
    _log(cond, "E.6 BA_MED optimize excludes S_BA",
         f"unavailable={unavail} groups={[g.get('supplier_name') for g in sg]} ss={len(ss_opts)}")
else:
    _log(False, "E.6 optimize BA_MED", f"status={r.status_code}")

# E.7 optimize for BG_MED -> S_BG should appear
r = post("/orders/optimize", {"items": [{"name": "BG_MED", "quantity": 1}]}, token=pbg_token)
if r.status_code == 200:
    body = r.json()
    sg = body.get("smart_split", {}).get("groups", [])
    sids = {g.get("supplier_id") for g in sg}
    _log(sbg_id in sids, "E.7 BG_MED optimize includes S_BG", f"groups suppliers={sids}")
else:
    _log(False, "E.7 optimize BG_MED", f"status={r.status_code}")


# -----------------------------------------------------------------
# F. Commit enforcement
# -----------------------------------------------------------------
print("\n=== F. Commit enforcement ===")

# F.1 commit with S_BA group -> 403
commit_id_bad = str(uuid.uuid4())
body = {
    "commit_id": commit_id_bad,
    "groups": [{
        "supplier_id": sba_id, "supplier_name": "S_BA", "total": 600,
        "items": [{"name": "BA_MED", "quantity": 1, "unit_price": 600}],
    }],
}
r = post("/orders/optimize/commit", body, token=pbg_token)
ok = (r.status_code == 403) and (("منطقتك" in r.text) or ("region" in r.text.lower()) or ("خارج" in r.text))
_log(ok, "F.1 commit with out-of-region supplier -> 403",
     f"status={r.status_code} body={r.text[:200]}")

# F.2 commit with S_BG group -> 200, created>=1
commit_id_ok = str(uuid.uuid4())
body = {
    "commit_id": commit_id_ok,
    "groups": [{
        "supplier_id": sbg_id, "supplier_name": "S_BG", "total": 500,
        "items": [{"name": "BG_MED", "quantity": 1, "unit_price": 500}],
    }],
}
r = post("/orders/optimize/commit", body, token=pbg_token)
ok = (r.status_code == 200) and r.json().get("created", 0) >= 1
_log(ok, "F.2 commit with same-region supplier -> 200 created>=1",
     f"status={r.status_code} body={r.text[:200]}")


# -----------------------------------------------------------------
# G. National mode toggle
# -----------------------------------------------------------------
print("\n=== G. National mode toggle ===")

# G.1 set national
r = patch("/admin/payment-settings", {"marketplace_mode": "national"}, token=admin_token)
ok = r.status_code == 200 and r.json().get("marketplace_mode") == "national"
_log(ok, "G.1 PATCH marketplace_mode=national -> 200",
     f"status={r.status_code} got={r.json().get('marketplace_mode') if r.status_code==200 else r.text[:200]}")

# G.2 P_BG /suppliers includes both
r = get("/suppliers", token=pbg_token)
if r.status_code == 200:
    ids = [s["id"] for s in r.json()]
    _log((sbg_id in ids) and (sba_id in ids),
         "G.2 national mode: /suppliers includes BOTH S_BG and S_BA",
         f"sbg_in={sbg_id in ids} sba_in={sba_id in ids}")
else:
    _log(False, "G.2 /suppliers", f"status={r.status_code}")

# G.3 P_BG /marketplace includes both BG_MED & BA_MED
r = get("/marketplace", token=pbg_token)
if r.status_code == 200:
    names = [p["name"] for p in r.json()]
    _log(("BG_MED" in names) and ("BA_MED" in names),
         "G.3 national mode: /marketplace includes both BG_MED & BA_MED",
         f"BG_MED={'BG_MED' in names} BA_MED={'BA_MED' in names}")
else:
    _log(False, "G.3 /marketplace", f"status={r.status_code}")

# G.4 commit with S_BA -> now succeeds
commit_id_ba = str(uuid.uuid4())
body = {
    "commit_id": commit_id_ba,
    "groups": [{
        "supplier_id": sba_id, "supplier_name": "S_BA", "total": 600,
        "items": [{"name": "BA_MED", "quantity": 1, "unit_price": 600}],
    }],
}
r = post("/orders/optimize/commit", body, token=pbg_token)
ok = (r.status_code == 200) and r.json().get("created", 0) >= 1
_log(ok, "G.4 national mode: commit S_BA -> 200 created>=1",
     f"status={r.status_code} body={r.text[:200]}")

# G.5 restore local
r = patch("/admin/payment-settings", {"marketplace_mode": "local"}, token=admin_token)
ok = r.status_code == 200 and r.json().get("marketplace_mode") == "local"
_log(ok, "G.5 PATCH marketplace_mode=local (restore) -> 200",
     f"status={r.status_code}")

# G.6 invalid mode -> 400
r = patch("/admin/payment-settings", {"marketplace_mode": "foo"}, token=admin_token)
_log(r.status_code == 400, "G.6 invalid marketplace_mode=foo -> 400",
     f"status={r.status_code} body={r.text[:150]}")


# -----------------------------------------------------------------
# H. Suggestions
# -----------------------------------------------------------------
print("\n=== H. Suggestions ===")
r = get("/regions/suggest", token=pbg_token)
if r.status_code == 200:
    arr = r.json()
    _log(isinstance(arr, list) and len(arr) > 0,
         "H.1 /regions/suggest returns non-empty list",
         f"#items={len(arr) if isinstance(arr, list) else 'n/a'}")
    if isinstance(arr, list) and arr:
        sample = arr[0]
        keys_ok = all(k in sample for k in ("region", "region_normalized", "country", "count"))
        _log(keys_ok, "H.1 entry has region/region_normalized/country/count",
             f"sample={sample}")
        labels = [a.get("region") for a in arr]
        _log(any("بغداد" in (l or "") for l in labels),
             "H.1 includes بغداد", f"labels={labels[:10]}")
        _log(any("البصرة" in (l or "") for l in labels) or any("بصره" in (l or "") for l in labels),
             "H.1 includes البصرة", f"labels={labels[:10]}")
else:
    _log(False, "H.1 /regions/suggest", f"status={r.status_code} body={r.text[:200]}")

r = get("/regions/suggest", token=pbg_token, params={"q": "بغ"})
if r.status_code == 200:
    arr = r.json()
    labels = [a.get("region") for a in arr]
    _log(any("بغداد" in (l or "") for l in labels),
         "H.2 /regions/suggest?q=بغ includes بغداد",
         f"labels={labels}")
else:
    _log(False, "H.2 /regions/suggest?q=بغ", f"status={r.status_code}")


# -----------------------------------------------------------------
# I. Role enforcement / auth
# -----------------------------------------------------------------
print("\n=== I. Role enforcement ===")
# I.1 pharmacy already used set-region OK at C.1 (working). Just verify again.
r = patch("/auth/set-region", {"region": "بغداد"}, token=pbg_token)
_log(r.status_code == 200, "I.1 pharmacy set-region -> 200",
     f"status={r.status_code} body={r.text[:120]}")

# I.2 unauth GET /regions/suggest -> 401
r = get("/regions/suggest")
_log(r.status_code == 401, "I.2 unauth /regions/suggest -> 401",
     f"status={r.status_code}")

# I.3 unauth PATCH /auth/set-region -> 401
r = requests.patch(f"{API}/auth/set-region", json={"region": "x"}, timeout=10)
_log(r.status_code == 401, "I.3 unauth PATCH /auth/set-region -> 401",
     f"status={r.status_code}")


# -----------------------------------------------------------------
# Spec extra: GET /api/payment-info should include marketplace_mode
# -----------------------------------------------------------------
print("\n=== Extra: /payment-info marketplace_mode ===")
r = get("/payment-info", token=pbg_token)
if r.status_code == 200:
    has_field = "marketplace_mode" in r.json()
    _log(has_field, "X.1 /payment-info includes marketplace_mode",
         f"keys={list(r.json().keys())}")
else:
    _log(False, "X.1 /payment-info", f"status={r.status_code}")


# -----------------------------------------------------------------
# Cleanup: ensure marketplace_mode back to local
# -----------------------------------------------------------------
patch("/admin/payment-settings", {"marketplace_mode": "local"}, token=admin_token)

print("\n\n=== SUMMARY ===")
print(f"PASS: {len(PASS)} / FAIL: {len(FAIL)}")
print()
if FAIL:
    print("FAILED:")
    for f in FAIL:
        print(" ", f)
print()
print("DONE")
sys.exit(0 if not FAIL else 1)
