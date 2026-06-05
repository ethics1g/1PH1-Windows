"""
Backend tests for the new EXPIRY DATE feature on the pharmacy module.

Spec: /app/test_result.md  task "Expiry Date in Buy + Expiry Alerts".

Targets:
  - POST /api/medicines/buy now accepts expiry_date and validates it.
  - On duplicate medicine, earlier expiry_date wins (existing vs incoming).
  - GET /api/medicines/expiry-alerts (pharmacy only) groups items
    into expired / critical_7 / warning_30 / soon_90 buckets.
  - Backward compat: /api/medicines listing still works.
  - Role enforcement: supplier 403, unauth 401.
  - No regression: /api/orders/optimize, /api/auth/login.

Public URL is read from /app/frontend/.env (EXPO_PUBLIC_BACKEND_URL).
"""
import json
import sys
from datetime import datetime, timezone, timedelta

import requests


def _read_env(path: str, key: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln.startswith(f"{key}="):
                    return ln.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


BASE_URL = (_read_env("/app/frontend/.env", "EXPO_PUBLIC_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    print("Missing EXPO_PUBLIC_BACKEND_URL in /app/frontend/.env")
    sys.exit(1)
API = BASE_URL + "/api"

PHARMACY_PHONE = "07700000001"
PHARMACY_PASS = "pass123"
SUPPLIER_PHONE = "07811111111"
SUPPLIER_PASS = "sup1"

PASS_COUNT = 0
FAIL_COUNT = 0
FAILS = []


def _log(ok, label, info=""):
    global PASS_COUNT, FAIL_COUNT
    if ok:
        PASS_COUNT += 1
        print(f"  ✅ {label}")
    else:
        FAIL_COUNT += 1
        FAILS.append(f"{label} | {info}")
        print(f"  ❌ {label}  → {info}")


def assert_eq(actual, expected, label):
    _log(actual == expected, label, f"expected {expected!r}, got {actual!r}")


def assert_true(cond, label, info=""):
    _log(bool(cond), label, info)


def hdr(t):
    return {"Authorization": f"Bearer {t}"} if t else {}


def post(path, token=None, body=None):
    return requests.post(API + path,
                         headers={**hdr(token), "Content-Type": "application/json"},
                         data=json.dumps(body or {}), timeout=30)


def get(path, token=None):
    return requests.get(API + path, headers=hdr(token), timeout=30)


def login_pharmacy():
    r = post("/auth/login", body={"phone": PHARMACY_PHONE, "password": PHARMACY_PASS})
    assert_eq(r.status_code, 200, "Pharmacy login status=200")
    j = r.json()
    assert_eq(j.get("role"), "pharmacy", "Pharmacy login role")
    return j["token"]


def login_supplier():
    r = post("/auth/login", body={"phone": SUPPLIER_PHONE, "password": SUPPLIER_PASS})
    if r.status_code == 403:
        ar = post("/auth/login", body={"phone": "0000000000", "password": "admin123"})
        if ar.status_code == 200:
            atok = ar.json()["token"]
            for u in get("/admin/users?role=supplier", atok).json():
                if u.get("phone") == SUPPLIER_PHONE:
                    requests.patch(
                        f"{API}/admin/users/supplier/{u['id']}",
                        headers={**hdr(atok), "Content-Type": "application/json"},
                        data=json.dumps({"disabled": False}),
                        timeout=30,
                    )
        r = post("/auth/login", body={"phone": SUPPLIER_PHONE, "password": SUPPLIER_PASS})
    assert_eq(r.status_code, 200, "Supplier login status=200")
    j = r.json()
    assert_eq(j.get("role"), "supplier", "Supplier login role")
    return j["token"]


def today_utc():
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def fmt(d):
    return d.strftime("%Y-%m-%d")


def find_med(token, name):
    r = get("/medicines?limit=500", token)
    if r.status_code != 200:
        return None
    for m in r.json():
        if m.get("name") == name:
            return m
    return None


def cleanup(token):
    names = {"ExpTest_FAR", "ExpTest_30D", "ExpTest_7D", "ExpTest_EXPIRED",
             "ExpTest_90D", "ExpTest_OK", "ExpTest_NOEXP", "ExpTest_YM"}
    r = get("/medicines?limit=500", token)
    if r.status_code != 200:
        return
    for m in r.json():
        if m.get("name") in names:
            requests.delete(f"{API}/medicines/{m['id']}", headers=hdr(token), timeout=30)


def main():
    print(f"Base URL: {API}")

    print("\n=== Login ===")
    pharm_tok = login_pharmacy()
    sup_tok = login_supplier()

    cleanup(pharm_tok)

    today = today_utc()
    in_5 = fmt(today + timedelta(days=5))
    in_15 = fmt(today + timedelta(days=15))
    in_60 = fmt(today + timedelta(days=60))
    in_120 = fmt(today + timedelta(days=120))
    past_10 = fmt(today - timedelta(days=10))

    # ============ A. Buy creates medicine with expiry ============
    print("\n=== A. Buy creates medicines with expiry_date ===")
    cases_a = [
        ("ExpTest_FAR", "2029-12-31"),
        ("ExpTest_30D", in_15),
        ("ExpTest_7D", in_5),
        ("ExpTest_EXPIRED", past_10),
        ("ExpTest_90D", in_60),
        ("ExpTest_OK", in_120),
    ]
    for name, exp in cases_a:
        r = post("/medicines/buy", pharm_tok,
                 {"name": name, "quantity": 5, "price": 1000, "expiry_date": exp})
        assert_eq(r.status_code, 200, f"A.buy {name} status=200")
        m = find_med(pharm_tok, name)
        assert_true(m is not None, f"A.buy {name} exists in list")
        if m:
            assert_eq(m.get("expiry_date"), exp, f"A.buy {name} expiry_date stored")
            assert_eq(m.get("quantity"), 5, f"A.buy {name} quantity=5")

    # ============ B. Validation ============
    print("\n=== B. Validation ===")
    r = post("/medicines/buy", pharm_tok,
             {"name": "ExpTest_Bad", "quantity": 1, "price": 100, "expiry_date": "garbage"})
    assert_eq(r.status_code, 400, "B1 garbage expiry_date → 400")
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = r.text
    assert_true("غير صالح" in str(detail), "B1 detail mentions 'غير صالح'", info=str(detail))

    r = post("/medicines/buy", pharm_tok,
             {"name": "ExpTest_YM", "quantity": 2, "price": 200, "expiry_date": "2027-12"})
    assert_eq(r.status_code, 200, "B2 YYYY-MM accepted (200)")
    m = find_med(pharm_tok, "ExpTest_YM")
    assert_true(m is not None, "B2 ExpTest_YM exists")
    if m:
        assert_eq(m.get("expiry_date"), "2027-12-01", "B2 expiry_date stored as YYYY-MM-01")

    r = post("/medicines/buy", pharm_tok,
             {"name": "ExpTest_NOEXP", "quantity": 3, "price": 300})
    assert_eq(r.status_code, 200, "B3 no expiry_date → 200")
    m = find_med(pharm_tok, "ExpTest_NOEXP")
    assert_true(m is not None, "B3 ExpTest_NOEXP exists")
    if m:
        ev = m.get("expiry_date")
        assert_true(ev in (None, ""), "B3 expiry_date is null/empty", info=f"got {ev!r}")

    # ============ C. Merge logic ============
    print("\n=== C. Merge on duplicate ===")
    r = post("/medicines/buy", pharm_tok,
             {"name": "ExpTest_FAR", "quantity": 3, "price": 1100, "expiry_date": "2028-06-30"})
    assert_eq(r.status_code, 200, "C1 duplicate buy → 200")
    m = find_med(pharm_tok, "ExpTest_FAR")
    if m:
        assert_eq(m.get("quantity"), 8, "C1 quantity summed (5+3=8)")
        assert_eq(m.get("price"), 1100, "C1 price overwritten to 1100")
        assert_eq(m.get("expiry_date"), "2028-06-30", "C1 earlier expiry kept (2028-06-30)")

    r = post("/medicines/buy", pharm_tok,
             {"name": "ExpTest_FAR", "quantity": 2, "price": 1100, "expiry_date": "2030-01-01"})
    assert_eq(r.status_code, 200, "C2 duplicate buy → 200")
    m = find_med(pharm_tok, "ExpTest_FAR")
    if m:
        assert_eq(m.get("quantity"), 10, "C2 quantity summed (8+2=10)")
        assert_eq(m.get("expiry_date"), "2028-06-30", "C2 earlier expiry kept (2028-06-30 not 2030-01-01)")

    # ============ D. Expiry alerts ============
    print("\n=== D. /medicines/expiry-alerts ===")
    r = get("/medicines/expiry-alerts", pharm_tok)
    assert_eq(r.status_code, 200, "D GET /medicines/expiry-alerts status=200")
    if r.status_code == 200:
        body = r.json()
        for k in ("today", "groups", "counts", "total_alerts"):
            assert_true(k in body, f"D response has '{k}'", info=str(list(body.keys())))
        groups = body.get("groups", {}) or {}
        for g in ("expired", "critical_7", "warning_30", "soon_90"):
            assert_true(g in groups, f"D groups has '{g}'", info=str(list(groups.keys())))

        names_by_group = {g: [it.get("name") for it in groups.get(g, [])] for g in groups}

        assert_true("ExpTest_EXPIRED" in names_by_group.get("expired", []),
                    "D ExpTest_EXPIRED in groups.expired", info=str(names_by_group))
        assert_true("ExpTest_7D" in names_by_group.get("critical_7", []),
                    "D ExpTest_7D in groups.critical_7", info=str(names_by_group))
        assert_true("ExpTest_30D" in names_by_group.get("warning_30", []),
                    "D ExpTest_30D in groups.warning_30", info=str(names_by_group))
        assert_true("ExpTest_90D" in names_by_group.get("soon_90", []),
                    "D ExpTest_90D in groups.soon_90", info=str(names_by_group))

        all_names = []
        for g in groups.values():
            all_names.extend(it.get("name") for it in g)
        assert_true("ExpTest_OK" not in all_names, "D ExpTest_OK NOT in any group")
        assert_true("ExpTest_FAR" not in all_names, "D ExpTest_FAR NOT in any group")
        assert_true("ExpTest_NOEXP" not in all_names, "D ExpTest_NOEXP NOT in any group")

        for item in groups.get("expired", []):
            if item.get("name") == "ExpTest_EXPIRED":
                assert_eq(item.get("status"), "expired", "D ExpTest_EXPIRED status=expired")
                dl = item.get("days_left")
                assert_true(isinstance(dl, int) and dl < 0,
                            "D ExpTest_EXPIRED days_left < 0", info=f"got {dl!r}")
        for item in groups.get("critical_7", []):
            if item.get("name") == "ExpTest_7D":
                assert_eq(item.get("status"), "critical_7", "D ExpTest_7D status=critical_7")
                dl = item.get("days_left")
                assert_true(isinstance(dl, int) and 0 <= dl <= 7,
                            "D ExpTest_7D 0<=days_left<=7", info=f"got {dl!r}")
        for item in groups.get("warning_30", []):
            if item.get("name") == "ExpTest_30D":
                assert_eq(item.get("status"), "warning_30", "D ExpTest_30D status=warning_30")
                dl = item.get("days_left")
                assert_true(isinstance(dl, int) and 8 <= dl <= 30,
                            "D ExpTest_30D 8<=days_left<=30", info=f"got {dl!r}")
        for item in groups.get("soon_90", []):
            if item.get("name") == "ExpTest_90D":
                assert_eq(item.get("status"), "soon_90", "D ExpTest_90D status=soon_90")
                dl = item.get("days_left")
                assert_true(isinstance(dl, int) and 31 <= dl <= 90,
                            "D ExpTest_90D 31<=days_left<=90", info=f"got {dl!r}")

        counts = body.get("counts", {}) or {}
        if counts:
            assert_eq(body.get("total_alerts"), sum(counts.values()),
                      "D total_alerts == sum(counts)")

    r = get("/medicines?limit=500", pharm_tok)
    assert_eq(r.status_code, 200, "D2 GET /medicines status=200")
    if r.status_code == 200:
        meds = r.json()
        with_exp = [m for m in meds if m.get("expiry_date")]
        assert_true(len(with_exp) > 0, "D2 some medicines carry expiry_date field")
        noexp = [m for m in meds if m.get("name") == "ExpTest_NOEXP"]
        assert_true(len(noexp) == 1, "D2 ExpTest_NOEXP present without expiry_date")

    # ============ E. Role enforcement ============
    print("\n=== E. Role enforcement ===")
    r = post("/medicines/buy", sup_tok,
             {"name": "X", "quantity": 1, "price": 1, "expiry_date": "2030-01-01"})
    assert_eq(r.status_code, 403, "E1 supplier /medicines/buy → 403")
    r = get("/medicines/expiry-alerts", sup_tok)
    assert_eq(r.status_code, 403, "E2 supplier /medicines/expiry-alerts → 403")
    r = post("/medicines/buy", None, {"name": "X", "quantity": 1, "price": 1})
    assert_eq(r.status_code, 401, "E3 unauth /medicines/buy → 401")
    r = get("/medicines/expiry-alerts", None)
    assert_eq(r.status_code, 401, "E4 unauth /medicines/expiry-alerts → 401")

    # ============ F. No regression ============
    print("\n=== F. No regression ===")
    r = post("/orders/optimize", pharm_tok, {"items": [{"name": "Paracetamol", "quantity": 1}]})
    assert_eq(r.status_code, 200, "F1 /orders/optimize status=200")
    if r.status_code == 200:
        j = r.json()
        for k in ("unavailable", "per_item", "single_supplier", "smart_split", "summary"):
            assert_true(k in j, f"F1 optimize has '{k}'")

    r = get("/medicines?limit=10", pharm_tok)
    assert_eq(r.status_code, 200, "F2 /medicines list status=200")

    r = post("/auth/login", body={"phone": PHARMACY_PHONE, "password": PHARMACY_PASS})
    assert_eq(r.status_code, 200, "F3 /auth/login status=200")
    if r.status_code == 200:
        j = r.json()
        for k in ("token", "role", "user"):
            assert_true(k in j, f"F3 login has '{k}'", info=str(list(j.keys())))
        assert_eq(j.get("role"), "pharmacy", "F3 login role=pharmacy")

    cleanup(pharm_tok)

    print(f"\n=== SUMMARY: {PASS_COUNT} passed / {FAIL_COUNT} failed ===")
    if FAIL_COUNT:
        print("\nFailures:")
        for f in FAILS:
            print(" -", f)
    sys.exit(0 if FAIL_COUNT == 0 else 1)


if __name__ == "__main__":
    main()
