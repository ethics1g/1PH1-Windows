"""
Order Lifecycle Workflow backend tests.

Tests pending -> accepted -> processing -> delivered -> completed workflow,
commission generation ONLY on completion, anti-circumvention redaction,
72h auto-complete, role enforcement, region enforcement, and idempotency.
"""
import os
import sys
import uuid
import json
import time
import requests
from pymongo import MongoClient
from datetime import datetime, timezone, timedelta

BACKEND_URL = "https://pharma-checkout-8.preview.emergentagent.com/api"
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "pharmacy_db"

mongo = MongoClient(MONGO_URL)
db = mongo[DB_NAME]

results = []  # list of (name, ok, detail)


def log(name, ok, detail=""):
    icon = "PASS" if ok else "FAIL"
    print(f"[{icon}] {name} :: {detail}")
    results.append((name, ok, detail))


def req(method, path, token=None, json_body=None, expect_status=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    url = f"{BACKEND_URL}{path}"
    r = requests.request(method, url, headers=h, json=json_body, timeout=30)
    if expect_status is not None and r.status_code != expect_status:
        print(f"  WARN {method} {path} -> {r.status_code} (expected {expect_status}) body={r.text[:300]}")
    return r


# ---- 0. Setup actors ----
print("\n=== 0. Setup actors ===")

RUN = uuid.uuid4().hex[:6]

PHARM = {"name": "صيدلية اختبار LC", "phone": f"077{int(time.time())%100000000:08d}",
         "password": "Ph1234!", "address": "بغداد - الكرادة", "region": "بغداد"}
SUP1 = {"name": "مذخر بغداد LC", "phone": f"078{(int(time.time())+1)%100000000:08d}",
        "password": "Su1234!", "address": "بغداد - الكاظمية", "region": "بغداد"}
SUP2 = {"name": "مذخر بغداد LC2", "phone": f"079{(int(time.time())+2)%100000000:08d}",
        "password": "Sw1234!", "address": "بغداد - المنصور", "region": "بغداد"}
SUPBASRA = {"name": "مذخر البصرة LC", "phone": f"076{(int(time.time())+3)%100000000:08d}",
            "password": "Sb1234!", "address": "البصرة", "region": "البصرة"}


def register(role, data):
    r = req("POST", f"/{role}/register", json_body=data)
    if r.status_code == 400 and "مسجل" in r.text:
        rl = req("POST", f"/{role}/login", json_body={"phone": data["phone"], "password": data["password"]})
        if rl.status_code != 200:
            raise RuntimeError(f"register&login failed for {role} {data['phone']}: {rl.text}")
        return rl.json()
    if r.status_code != 200:
        raise RuntimeError(f"register {role} failed: {r.status_code} {r.text}")
    return r.json()


pharm_obj = register("pharmacy", PHARM)
sup1_obj = register("supplier", SUP1)
sup2_obj = register("supplier", SUP2)
supbasra_obj = register("supplier", SUPBASRA)

tok_pharm = pharm_obj["token"]
tok_sup1 = sup1_obj["token"]
tok_sup2 = sup2_obj["token"]
tok_supbasra = supbasra_obj["token"]
sid1 = sup1_obj["supplier"]["id"]
sid2 = sup2_obj["supplier"]["id"]
sidbasra = supbasra_obj["supplier"]["id"]
pid = pharm_obj["pharmacy"]["id"]

log("setup actors registered", True, f"pid={pid} sid1={sid1} sid2={sid2} sidbasra={sidbasra}")

# Admin login
admin_resp = req("POST", "/admin/login", json_body={"phone": "0000000000", "password": "admin123"})
if admin_resp.status_code != 200:
    raise RuntimeError(f"admin login failed: {admin_resp.text}")
tok_admin = admin_resp.json()["token"]
log("admin login", True)


def add_prod(token, name, price, qty=100):
    r = req("POST", "/supplier/products", token=token,
            json_body={"name": name, "price": price, "quantity": qty})
    if r.status_code != 200:
        raise RuntimeError(f"add product failed: {r.text}")
    return r.json()


# Use truly distinct names — no shared tokens of length >=3 — to avoid
# Arabic-aware matcher fan-out between unrelated products.
NAME_A = f"PanadolA{RUN[:3]}"
NAME_B = f"AmoxilB{RUN[3:6]}"
NAME_BASRA = f"BasrolBA{RUN[:2]}{RUN[4:6]}"

add_prod(tok_sup1, NAME_A, 1000, 100)
add_prod(tok_sup2, NAME_B, 2000, 100)
add_prod(tok_supbasra, NAME_BASRA, 500, 100)
log("setup products added", True)


def commission_count(supplier_id):
    return db.supplier_sales.count_documents({"supplier_id": supplier_id})


# =============================================================
# TEST 1: Commit creates orders, NOT commissions
# =============================================================
print("\n=== TEST 1: Commit creates orders, NOT commissions ===")

before_sid1 = commission_count(sid1)
before_sid2 = commission_count(sid2)

opt = req("POST", "/orders/optimize", token=tok_pharm,
          json_body={"items": [{"name": NAME_A, "quantity": 5},
                                {"name": NAME_B, "quantity": 3}]})
if opt.status_code != 200:
    log("TEST 1 optimize", False, opt.text)
    sys.exit(1)
optdata = opt.json()
groups = optdata.get("smart_split", {}).get("groups", [])
log("TEST 1 optimize yields 2 supplier groups", len(groups) >= 2, f"groups={len(groups)}")

commit_id = str(uuid.uuid4())
commit_payload = {
    "commit_id": commit_id,
    "groups": [
        {"supplier_id": g["supplier_id"], "supplier_name": g["supplier_name"],
         "items": [{"name": it["name"], "quantity": it["quantity"], "unit_price": it["unit_price"]}
                   for it in g["items"]],
         "total": g["total"]} for g in groups
    ],
}
commit_resp = req("POST", "/orders/optimize/commit", token=tok_pharm, json_body=commit_payload)
log("TEST 1 commit status==200", commit_resp.status_code == 200, commit_resp.text[:200])
body = commit_resp.json()
log("TEST 1 commit status=ok", body.get("status") == "ok", str(body)[:200])
log("TEST 1 commit created==2", body.get("created") == 2, f"created={body.get('created')}")
log("TEST 1 commit returns orders array",
    isinstance(body.get("orders"), list) and len(body["orders"]) == 2,
    f"orders={body.get('orders')}")

after_sid1 = commission_count(sid1)
after_sid2 = commission_count(sid2)
log("TEST 1 NO commission created for sup1 on commit", after_sid1 == before_sid1,
    f"before={before_sid1} after={after_sid1}")
log("TEST 1 NO commission created for sup2 on commit", after_sid2 == before_sid2,
    f"before={before_sid2} after={after_sid2}")

ord_sid1_id = None
ord_sid2_id = None
for o in body.get("orders", []):
    od = db.orders.find_one({"id": o["id"]}, {"_id": 0, "supplier_id": 1})
    if od and od["supplier_id"] == sid1:
        ord_sid1_id = o["id"]
    elif od and od["supplier_id"] == sid2:
        ord_sid2_id = o["id"]
log("TEST 1 mapping orders to suppliers", ord_sid1_id is not None and ord_sid2_id is not None,
    f"sid1_order={ord_sid1_id} sid2_order={ord_sid2_id}")


# =============================================================
# TEST 2: Idempotency
# =============================================================
print("\n=== TEST 2: Idempotency ===")
re_commit = req("POST", "/orders/optimize/commit", token=tok_pharm, json_body=commit_payload)
log("TEST 2 idempotency status==200", re_commit.status_code == 200)
rb = re_commit.json()
log("TEST 2 idempotency status=already_committed", rb.get("status") == "already_committed", str(rb))
log("TEST 2 idempotency created==0", rb.get("created") == 0, str(rb))
total_orders_for_commit = db.orders.count_documents({"commit_id": commit_id})
log("TEST 2 only 2 orders for commit_id", total_orders_for_commit == 2,
    f"count={total_orders_for_commit}")


# =============================================================
# TEST 3: Anti-circumvention
# =============================================================
print("\n=== TEST 3: Anti-circumvention ===")
r = req("GET", "/supplier/orders?status=pending", token=tok_sup1)
log("TEST 3 sup1 GET pending status==200", r.status_code == 200, r.text[:300])
docs = r.json()
target = next((d for d in docs if d["id"] == ord_sid1_id), None)
log("TEST 3 sup1 sees own pending order", target is not None, str([d["id"] for d in docs])[:200])
if target:
    log("TEST 3 pharmacy_name is None (pending)", target.get("pharmacy_name") is None,
        f"value={target.get('pharmacy_name')!r}")
    log("TEST 3 pharmacy_phone is None (pending)", target.get("pharmacy_phone") is None,
        f"value={target.get('pharmacy_phone')!r}")
    log("TEST 3 pharmacy_address is None (pending)", target.get("pharmacy_address") is None,
        f"value={target.get('pharmacy_address')!r}")
    log("TEST 3 pharmacy_region visible (pending)", bool(target.get("pharmacy_region")),
        f"value={target.get('pharmacy_region')!r}")

r = req("PATCH", f"/supplier/orders/{ord_sid1_id}/accept", token=tok_sup1)
log("TEST 3 sup1 accept status==200", r.status_code == 200, r.text[:200])

r = req("GET", "/supplier/orders?status=accepted", token=tok_sup1)
docs = r.json()
target = next((d for d in docs if d["id"] == ord_sid1_id), None)
log("TEST 3 sup1 sees accepted order", target is not None)
if target:
    log("TEST 3 pharmacy_name visible after accept", target.get("pharmacy_name") == PHARM["name"],
        f"value={target.get('pharmacy_name')!r}")
    log("TEST 3 pharmacy_phone visible after accept", target.get("pharmacy_phone") == PHARM["phone"],
        f"value={target.get('pharmacy_phone')!r}")
    log("TEST 3 pharmacy_address visible after accept", target.get("pharmacy_address") == PHARM["address"],
        f"value={target.get('pharmacy_address')!r}")


# =============================================================
# TEST 4: Happy path state transitions
# =============================================================
print("\n=== TEST 4: Happy path state transitions ===")
r = req("PATCH", f"/supplier/orders/{ord_sid1_id}/processing", token=tok_sup1)
log("TEST 4 accepted->processing", r.status_code == 200, r.text[:200])

r = req("PATCH", f"/supplier/orders/{ord_sid1_id}/delivered", token=tok_sup1)
log("TEST 4 processing->delivered", r.status_code == 200, r.text[:200])

before_commission = commission_count(sid1)
r = req("PATCH", f"/pharmacy/orders/{ord_sid1_id}/confirm-receipt", token=tok_pharm)
log("TEST 4 delivered->completed (pharmacy confirm)", r.status_code == 200, r.text[:300])
rj = r.json()
log("TEST 4 response order_status==completed", rj.get("order_status") == "completed", str(rj))
log("TEST 4 response has commission_amount", rj.get("commission_amount") is not None, str(rj))
log("TEST 4 response has commission_id", rj.get("commission_id") is not None, str(rj))

od = db.orders.find_one({"id": ord_sid1_id}, {"_id": 0})
expected_commission = round(od["total"] * 0.04, 2)
log("TEST 4 db.orders.status==completed", od["status"] == "completed")
log("TEST 4 commission_amount == total*0.04",
    abs((od.get("commission_amount") or 0) - expected_commission) < 0.01,
    f"got={od.get('commission_amount')} expected={expected_commission} total={od['total']}")
log("TEST 4 commission_id present", bool(od.get("commission_id")))

after_commission = commission_count(sid1)
log("TEST 4 +1 supplier_sales record for sup1",
    after_commission == before_commission + 1,
    f"before={before_commission} after={after_commission}")

r = req("GET", "/supplier/commissions", token=tok_sup1)
records = r.json().get("records", [])
new_rec = next((x for x in records if x.get("order_id") == ord_sid1_id), None)
log("TEST 4 /supplier/commissions shows new record", new_rec is not None)
if new_rec:
    log("TEST 4 commission rate=0.04 in record", abs((new_rec.get("rate") or 0) - 0.04) < 0.001,
        f"rate={new_rec.get('rate')}")
    log("TEST 4 commission status=pending (unpaid)", new_rec.get("status") == "pending",
        f"status={new_rec.get('status')}")


# =============================================================
# TEST 5: Bad transitions return 400
# =============================================================
print("\n=== TEST 5: Bad transitions ===")
r = req("PATCH", f"/supplier/orders/{ord_sid2_id}/delivered", token=tok_sup2)
log("TEST 5 pending->delivered returns 400", r.status_code == 400, f"got {r.status_code} {r.text[:200]}")

r = req("PATCH", f"/supplier/orders/{ord_sid2_id}/accept", token=tok_sup2)
log("TEST 5 setup accept sid2", r.status_code == 200, r.text[:200])
r = req("PATCH", f"/pharmacy/orders/{ord_sid2_id}/confirm-receipt", token=tok_pharm)
log("TEST 5 accepted->confirm-receipt returns 400", r.status_code == 400, f"got {r.status_code} {r.text[:200]}")

r = req("PATCH", f"/supplier/orders/{ord_sid1_id}/accept", token=tok_sup1)
log("TEST 5 completed->accept returns 400", r.status_code == 400, f"got {r.status_code}")
r = req("PATCH", f"/supplier/orders/{ord_sid1_id}/delivered", token=tok_sup1)
log("TEST 5 completed->delivered returns 400", r.status_code == 400, f"got {r.status_code}")
r = req("PATCH", f"/pharmacy/orders/{ord_sid1_id}/confirm-receipt", token=tok_pharm)
log("TEST 5 completed->confirm-receipt returns 400", r.status_code == 400, f"got {r.status_code}")


# =============================================================
# TEST 6: Role enforcement
# =============================================================
print("\n=== TEST 6: Role enforcement ===")
r = req("PATCH", f"/supplier/orders/{ord_sid2_id}/accept", token=tok_pharm)
log("TEST 6 pharmacy on /supplier/accept returns 403",
    r.status_code == 403, f"got {r.status_code} {r.text[:200]}")

r = req("PATCH", f"/supplier/orders/{ord_sid2_id}/accept", token=tok_sup1)
log("TEST 6 other supplier on someone else's order returns 403",
    r.status_code == 403, f"got {r.status_code} {r.text[:200]}")

r = req("PATCH", f"/pharmacy/orders/{ord_sid2_id}/confirm-receipt", token=tok_sup1)
log("TEST 6 supplier on /pharmacy/confirm-receipt returns 403",
    r.status_code == 403, f"got {r.status_code} {r.text[:200]}")


# =============================================================
# TEST 7: Reject
# =============================================================
print("\n=== TEST 7: Reject ===")
new_commit = str(uuid.uuid4())
single_group = {
    "commit_id": new_commit,
    "groups": [{
        "supplier_id": sid2,
        "supplier_name": SUP2["name"],
        "items": [{"name": NAME_B, "quantity": 2, "unit_price": 2000}],
        "total": 4000,
    }],
}
r = req("POST", "/orders/optimize/commit", token=tok_pharm, json_body=single_group)
log("TEST 7 setup commit for reject", r.status_code == 200, r.text[:200])
created = r.json().get("orders") or []
if created:
    fresh_order_id = created[0]["id"]
    before_comm_sid2 = commission_count(sid2)
    rr = req("PATCH", f"/supplier/orders/{fresh_order_id}/reject", token=tok_sup2,
             json_body={"reason": "نفاد المخزون"})
    log("TEST 7 reject status==200", rr.status_code == 200, rr.text[:200])
    od = db.orders.find_one({"id": fresh_order_id}, {"_id": 0})
    log("TEST 7 db.orders.status==rejected", od["status"] == "rejected", f"status={od['status']}")
    log("TEST 7 rejection_reason saved", od.get("rejection_reason") == "نفاد المخزون",
        f"reason={od.get('rejection_reason')!r}")
    log("TEST 7 NO commission created on reject",
        commission_count(sid2) == before_comm_sid2,
        f"before={before_comm_sid2} after={commission_count(sid2)}")
else:
    log("TEST 7 setup got new order", False, str(r.json()))


# =============================================================
# TEST 8: Stats endpoint
# =============================================================
print("\n=== TEST 8: Stats endpoint ===")
r = req("GET", "/supplier/orders/stats", token=tok_sup1)
log("TEST 8 stats status==200", r.status_code == 200, r.text[:300])
stats = r.json()
log("TEST 8 by_status present", "by_status" in stats, str(stats)[:300])
log("TEST 8 completed_total present", "completed_total" in stats)
log("TEST 8 commission_due_total present", "commission_due_total" in stats)
log("TEST 8 rate==0.04", abs(stats.get("rate", 0) - 0.04) < 0.001, f"rate={stats.get('rate')}")
ct = float(stats.get("completed_total") or 0)
cd = float(stats.get("commission_due_total") or 0)
log("TEST 8 commission_due_total == completed_total*0.04",
    abs(cd - round(ct * 0.04, 2)) < 0.01,
    f"completed_total={ct} commission_due_total={cd}")


# =============================================================
# TEST 9: Auto-complete after 72h (simulated)
# =============================================================
print("\n=== TEST 9: Auto-complete after 72h ===")
auto_commit = str(uuid.uuid4())
ac_group = {
    "commit_id": auto_commit,
    "groups": [{
        "supplier_id": sid2,
        "supplier_name": SUP2["name"],
        "items": [{"name": NAME_B, "quantity": 1, "unit_price": 2000}],
        "total": 2000,
    }],
}
r = req("POST", "/orders/optimize/commit", token=tok_pharm, json_body=ac_group)
log("TEST 9 setup commit", r.status_code == 200, r.text[:200])
ac_order_id = r.json()["orders"][0]["id"]

r = req("PATCH", f"/supplier/orders/{ac_order_id}/accept", token=tok_sup2)
log("TEST 9 accept", r.status_code == 200)
r = req("PATCH", f"/supplier/orders/{ac_order_id}/processing", token=tok_sup2)
log("TEST 9 processing", r.status_code == 200)
r = req("PATCH", f"/supplier/orders/{ac_order_id}/delivered", token=tok_sup2)
log("TEST 9 delivered", r.status_code == 200)

backdated = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
db.orders.update_one({"id": ac_order_id}, {"$set": {"delivered_at": backdated}})
log("TEST 9 backdated delivered_at to >72h", True, backdated)

before_comm = commission_count(sid2)

r = req("GET", "/supplier/orders", token=tok_sup2)
log("TEST 9 GET /supplier/orders to trigger auto-complete", r.status_code == 200)

od = db.orders.find_one({"id": ac_order_id}, {"_id": 0})
log("TEST 9 auto-bumped to completed", od["status"] == "completed", f"status={od['status']}")
log("TEST 9 auto_completed==True", od.get("auto_completed") is True, f"auto_completed={od.get('auto_completed')}")
log("TEST 9 commission_amount set",
    bool(od.get("commission_amount")) and abs(od["commission_amount"] - round(2000 * 0.04, 2)) < 0.01,
    f"commission_amount={od.get('commission_amount')}")
log("TEST 9 commission record created in supplier_sales",
    commission_count(sid2) == before_comm + 1,
    f"before={before_comm} after={commission_count(sid2)}")


# =============================================================
# TEST 10: Commission upload-proof + admin pay continues to work
# =============================================================
print("\n=== TEST 10: Commission upload-proof + admin pay still work ===")
auto_comm = db.supplier_sales.find_one({"order_id": ac_order_id}, {"_id": 0})
if not auto_comm:
    log("TEST 10 commission record exists for auto-completed order", False, "")
else:
    rid = auto_comm["id"]
    r = req("POST", f"/supplier/commissions/{rid}/upload-proof", token=tok_sup2,
            json_body={"proof_b64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="})
    log("TEST 10 upload-proof status==200", r.status_code == 200, r.text[:200])
    after = db.supplier_sales.find_one({"id": rid}, {"_id": 0})
    log("TEST 10 status==submitted after upload-proof", after.get("status") == "submitted",
        f"status={after.get('status')}")
    r = req("PATCH", f"/admin/commissions/{rid}/confirm", token=tok_admin)
    log("TEST 10 admin confirm-payment status==200", r.status_code == 200, r.text[:200])
    after = db.supplier_sales.find_one({"id": rid}, {"_id": 0})
    log("TEST 10 status==paid after admin confirm", after.get("status") == "paid",
        f"status={after.get('status')}")


# =============================================================
# TEST 11: Region enforcement on commit still works
# =============================================================
print("\n=== TEST 11: Region enforcement on commit ===")
r = req("PATCH", "/admin/payment-settings", token=tok_admin,
        json_body={"marketplace_mode": "local"})
log("TEST 11 ensure local mode", r.status_code == 200)

bad_commit = {
    "commit_id": str(uuid.uuid4()),
    "groups": [{
        "supplier_id": sidbasra,
        "supplier_name": SUPBASRA["name"],
        "items": [{"name": NAME_BASRA, "quantity": 1, "unit_price": 500}],
        "total": 500,
    }],
}
r = req("POST", "/orders/optimize/commit", token=tok_pharm, json_body=bad_commit)
log("TEST 11 out-of-region commit returns 403",
    r.status_code == 403, f"got {r.status_code} {r.text[:200]}")


# ---- Summary ----
print("\n========== SUMMARY ==========")
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
print(f"PASS: {passed}    FAIL: {failed}    TOTAL: {len(results)}")
if failed > 0:
    print("\nFailed assertions:")
    for n, ok, d in results:
        if not ok:
            print(f"  - {n} :: {d}")
sys.exit(0 if failed == 0 else 1)
