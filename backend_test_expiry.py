"""
Focused backend test for "Expiry Date in Buy + Expiry Alerts" feature.
Re-tests sections A–F from the previous failing run.
"""
import os
import sys
import time
import json
import uuid
import requests
from datetime import datetime, timezone, timedelta

BASE = "https://pharma-checkout-8.preview.emergentagent.com/api"

PASS = 0
FAIL = 0
FAILS: list[str] = []


def _log(ok: bool, msg: str):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✅ {msg}")
    else:
        FAIL += 1
        FAILS.append(msg)
        print(f"  ❌ {msg}")


def login(phone: str, password: str) -> tuple[str, dict]:
    r = requests.post(f"{BASE}/auth/login", json={"phone": phone, "password": password}, timeout=30)
    r.raise_for_status()
    j = r.json()
    return j["token"], j


def auth_headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def today_plus(days: int) -> str:
    d = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def find_medicine(token: str, name: str) -> dict | None:
    r = requests.get(f"{BASE}/medicines?limit=500", headers=auth_headers(token), timeout=30)
    if r.status_code != 200:
        return None
    for m in r.json():
        if m.get("name") == name:
            return m
    return None


def delete_medicine(token: str, mid: str):
    requests.delete(f"{BASE}/medicines/{mid}", headers=auth_headers(token), timeout=30)


def main():
    print("\n=== Setup: login as pharmacy & supplier ===")
    try:
        ph_tok, ph_payload = login("07700000001", "pass123")
        print(f"  pharmacy login OK role={ph_payload.get('role')}")
    except Exception as e:
        print(f"  ❌ Pharmacy login failed: {e}")
        sys.exit(1)
    try:
        sp_tok, sp_payload = login("07811111111", "sup1")
        print(f"  supplier login OK role={sp_payload.get('role')}")
    except Exception as e:
        print(f"  ⚠️ Supplier login failed (may be disabled): {e}")
        sp_tok = None

    run = uuid.uuid4().hex[:6].upper()  # unique suffix for product names
    names = {
        "FAR":     f"Expir_FAR_{run}",       # >90 days
        "D30":     f"Expir_D30_{run}",       # 30 days
        "D7":      f"Expir_D7_{run}",        # 7 days
        "EXPIRED": f"Expir_EXPIRED_{run}",   # past
        "YYYYMM":  f"Expir_MO_{run}",        # YYYY-MM input
        "GARBAGE": f"Expir_BAD_{run}",       # invalid
        "NOEXP":   f"Expir_NO_{run}",        # back compat
        "DUP":     f"Expir_DUP_{run}",       # for merge logic
        "QTY0":    f"Expir_QTY0_{run}",      # qty=0 (excluded from alerts)
        "BEYOND":  f"Expir_BEYOND_{run}",    # >90 days (excluded from alerts)
    }

    # Cleanup any pre-existing items with same names
    for n in names.values():
        m = find_medicine(ph_tok, n)
        if m:
            delete_medicine(ph_tok, m["id"])

    print("\n=== TEST 1: Buy with valid expiry_date (YYYY-MM-DD) stores the value ===")
    cases = [
        (names["FAR"],     today_plus(180), 10),
        (names["D30"],     today_plus(30),  10),
        (names["D7"],      today_plus(5),   10),
        (names["EXPIRED"], today_plus(-3),  10),
        (names["BEYOND"],  today_plus(200), 10),
        (names["QTY0"],    today_plus(20),  0),  # qty=0 → excluded from alerts
    ]
    created_meds = {}
    for nm, exp, qty in cases:
        r = requests.post(
            f"{BASE}/medicines/buy",
            headers=auth_headers(ph_tok),
            json={"name": nm, "quantity": qty, "price": 1000.0, "expiry_date": exp},
            timeout=30,
        )
        ok = r.status_code == 200 and (r.json().get("expiry_date") == exp)
        _log(ok, f"Buy {nm} exp={exp} qty={qty} → status={r.status_code} expiry_in_response={r.json().get('expiry_date') if r.status_code==200 else None}")
        if r.status_code == 200:
            created_meds[nm] = r.json()
            # Verify via /medicines list
            m = find_medicine(ph_tok, nm)
            _log(bool(m and m.get("expiry_date") == exp), f"  Verify via /medicines list: {nm} expiry_date={m.get('expiry_date') if m else None}")

    print("\n=== TEST 2: Buy with YYYY-MM normalized to YYYY-MM-01 ===")
    yyyymm = "2028-03"
    r = requests.post(
        f"{BASE}/medicines/buy",
        headers=auth_headers(ph_tok),
        json={"name": names["YYYYMM"], "quantity": 5, "price": 500.0, "expiry_date": yyyymm},
        timeout=30,
    )
    body = r.json() if r.status_code == 200 else {}
    _log(r.status_code == 200 and body.get("expiry_date") == "2028-03-01",
         f"Buy {names['YYYYMM']} expiry_date='2028-03' → status={r.status_code} stored={body.get('expiry_date')}")

    print("\n=== TEST 3: Buy with garbage expiry_date → 400 with 'تاريخ انتهاء غير صالح' ===")
    r = requests.post(
        f"{BASE}/medicines/buy",
        headers=auth_headers(ph_tok),
        json={"name": names["GARBAGE"], "quantity": 3, "price": 200.0, "expiry_date": "garbage"},
        timeout=30,
    )
    detail = ""
    try:
        detail = r.json().get("detail", "")
    except Exception:
        pass
    _log(r.status_code == 400 and ("تاريخ انتهاء غير صالح" in detail),
         f"garbage → status={r.status_code} detail={detail!r}")

    # Ensure garbage med wasn't created
    m = find_medicine(ph_tok, names["GARBAGE"])
    _log(m is None, f"Garbage entry NOT stored (find_medicine returned {m})")

    print("\n=== TEST 4: Buy without expiry_date → 200 (back compat) ===")
    r = requests.post(
        f"{BASE}/medicines/buy",
        headers=auth_headers(ph_tok),
        json={"name": names["NOEXP"], "quantity": 4, "price": 300.0},
        timeout=30,
    )
    body = r.json() if r.status_code == 200 else {}
    _log(r.status_code == 200 and body.get("expiry_date") in (None, ""),
         f"No expiry_date → status={r.status_code} expiry_date={body.get('expiry_date')}")

    print("\n=== TEST 5: Duplicate buy with earlier expiry → earlier wins; later → keep earlier ===")
    # Initial buy with FAR expiry
    far = today_plus(100)
    closer = today_plus(20)
    later = today_plus(300)
    r = requests.post(
        f"{BASE}/medicines/buy",
        headers=auth_headers(ph_tok),
        json={"name": names["DUP"], "quantity": 5, "price": 1000.0, "expiry_date": far},
        timeout=30,
    )
    _log(r.status_code == 200 and r.json().get("expiry_date") == far,
         f"DUP initial buy exp={far} → status={r.status_code} stored={r.json().get('expiry_date') if r.status_code==200 else None}")

    # Buy again with EARLIER expiry → should replace
    r = requests.post(
        f"{BASE}/medicines/buy",
        headers=auth_headers(ph_tok),
        json={"name": names["DUP"], "quantity": 3, "price": 1100.0, "expiry_date": closer},
        timeout=30,
    )
    body = r.json() if r.status_code == 200 else {}
    _log(r.status_code == 200 and body.get("expiry_date") == closer,
         f"DUP buy with EARLIER exp={closer} → status={r.status_code} stored={body.get('expiry_date')} (earlier wins)")
    _log(body.get("quantity") == 8, f"  quantity summed correctly: {body.get('quantity')} (expected 8)")

    # Buy again with LATER expiry → should keep `closer`
    r = requests.post(
        f"{BASE}/medicines/buy",
        headers=auth_headers(ph_tok),
        json={"name": names["DUP"], "quantity": 2, "price": 1200.0, "expiry_date": later},
        timeout=30,
    )
    body = r.json() if r.status_code == 200 else {}
    _log(r.status_code == 200 and body.get("expiry_date") == closer,
         f"DUP buy with LATER exp={later} → status={r.status_code} stored={body.get('expiry_date')} (kept earlier {closer})")
    _log(body.get("quantity") == 10, f"  quantity summed correctly: {body.get('quantity')} (expected 10)")

    print("\n=== TEST 6: GET /medicines/expiry-alerts → groups + counts + total_alerts ===")
    r = requests.get(f"{BASE}/medicines/expiry-alerts", headers=auth_headers(ph_tok), timeout=30)
    _log(r.status_code == 200, f"GET /medicines/expiry-alerts → status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        _log("today" in body and "groups" in body and "counts" in body and "total_alerts" in body,
             f"Response has today/groups/counts/total_alerts. keys={list(body.keys())}")
        grp = body.get("groups", {})
        _log(all(k in grp for k in ("expired", "critical_7", "warning_30", "soon_90")),
             f"groups keys present: {list(grp.keys())}")
        counts = body.get("counts", {})
        # Each item should have status + days_left
        any_item = None
        for k, lst in grp.items():
            if lst:
                any_item = lst[0]
                break
        _log(any_item is not None and "status" in any_item and "days_left" in any_item,
             f"Sample item has status+days_left: {any_item.get('status') if any_item else 'NONE'} days_left={any_item.get('days_left') if any_item else 'NONE'}")
        # Verify our items are in correct buckets
        all_items = []
        for v in grp.values():
            all_items.extend(v)
        names_in_alerts = {it.get("name") for it in all_items}

        # EXPIRED should be in 'expired'
        ok_expired = names["EXPIRED"] in {it["name"] for it in grp.get("expired", [])}
        _log(ok_expired, f"{names['EXPIRED']} in 'expired' group: {ok_expired}")
        # D7 (5 days) should be in 'critical_7'
        ok_c7 = names["D7"] in {it["name"] for it in grp.get("critical_7", [])}
        _log(ok_c7, f"{names['D7']} in 'critical_7' group: {ok_c7}")
        # D30 (30 days) should be in 'warning_30'
        ok_w30 = names["D30"] in {it["name"] for it in grp.get("warning_30", [])}
        _log(ok_w30, f"{names['D30']} in 'warning_30' group: {ok_w30}")
        # FAR (180 days) → NOT in alerts at all (only 90-day horizon)
        ok_far_excluded = names["FAR"] not in names_in_alerts
        _log(ok_far_excluded, f"{names['FAR']} (180d, >90d) NOT in alerts: {ok_far_excluded}")
        # BEYOND (200d) → NOT in alerts
        ok_beyond_excluded = names["BEYOND"] not in names_in_alerts
        _log(ok_beyond_excluded, f"{names['BEYOND']} (200d, >90d) NOT in alerts: {ok_beyond_excluded}")
        # QTY0 → NOT in alerts (qty=0)
        ok_qty0_excluded = names["QTY0"] not in names_in_alerts
        _log(ok_qty0_excluded, f"{names['QTY0']} (qty=0) NOT in alerts: {ok_qty0_excluded}")

        # counts add up to total_alerts
        sum_counts = sum(counts.values())
        _log(sum_counts == body.get("total_alerts"),
             f"sum(counts)={sum_counts} == total_alerts={body.get('total_alerts')}")

    print("\n=== TEST 7: Supplier hits /medicines/expiry-alerts → 403 (NOT 405) ===")
    if sp_tok:
        r = requests.get(f"{BASE}/medicines/expiry-alerts", headers=auth_headers(sp_tok), timeout=30)
        _log(r.status_code == 403, f"supplier GET /medicines/expiry-alerts → status={r.status_code} (expected 403)")
    else:
        print("  ⚠️ skipped (supplier login failed)")

    print("\n=== TEST 8: Unauthenticated /medicines/expiry-alerts → 401 ===")
    r = requests.get(f"{BASE}/medicines/expiry-alerts", timeout=30)
    _log(r.status_code == 401, f"unauth GET /medicines/expiry-alerts → status={r.status_code} (expected 401)")

    print("\n=== CLEANUP: delete test medicines ===")
    for n in list(names.values()):
        m = find_medicine(ph_tok, n)
        if m:
            delete_medicine(ph_tok, m["id"])

    print("\n" + "=" * 60)
    print(f"TOTAL: {PASS} PASS / {FAIL} FAIL")
    if FAILS:
        print("\nFAILED ASSERTIONS:")
        for f in FAILS:
            print(f"  - {f}")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
