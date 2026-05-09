"""Admin Dashboard / RBAC backend tests.

Covers:
  - admin login & must_change_password flag
  - RBAC enforcement (401 / 403)
  - admin/change-password (validation + restore)
  - admin/stats schema
  - admin/users (listing, role filter, toggle disabled, login blocked, delete cascade)
  - admin/orders (listing, status filter, status update)
  - admin/products (combined kind, delete by kind)
  - admin/notifications (CRUD + audience routing via /api/notifications/active)
  - admin/audit-logs (action filter, login_failed entry)
  - existing pharmacy_login & supplier_login still work
"""
import os
import uuid
import time
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
assert BASE, "EXPO_PUBLIC_BACKEND_URL must be set"
API = f"{BASE}/api"

ADMIN_PHONE = "0000000000"
ADMIN_PASS = "admin123"
PH_PHONE = "07700000001"
PH_PASS = "pass123"
SUP_PHONE = "07811111111"
SUP_PASS = "sup1"


# ---------- helpers ----------
def _login(role: str, phone: str, password: str):
    r = requests.post(f"{API}/{role}/login", json={"phone": phone, "password": password}, timeout=15)
    return r


def _admin_token() -> str:
    r = _login("admin", ADMIN_PHONE, ADMIN_PASS)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _ph_token() -> str:
    r = _login("pharmacy", PH_PHONE, PH_PASS)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _sup_token() -> str:
    r = _login("supplier", SUP_PHONE, SUP_PASS)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- Admin login & must_change_password ----------
class TestAdminLogin:
    def test_admin_login_success(self):
        r = _login("admin", ADMIN_PHONE, ADMIN_PASS)
        assert r.status_code == 200
        body = r.json()
        assert "token" in body and isinstance(body["token"], str)
        admin = body["admin"]
        assert admin["phone"] == ADMIN_PHONE
        assert admin["email"] == "admin@system.local"
        assert "must_change_password" in admin
        assert isinstance(admin["must_change_password"], bool)

    def test_admin_login_wrong_password_writes_audit(self):
        r = _login("admin", ADMIN_PHONE, "wrongpw")
        assert r.status_code == 401
        # verify login_failed audit entry exists for admin role
        tok = _admin_token()
        a = requests.get(f"{API}/admin/audit-logs", params={"action": "login_failed"}, headers=_h(tok), timeout=15)
        assert a.status_code == 200
        logs = a.json()
        assert any(l.get("actor", {}).get("phone") == ADMIN_PHONE for l in logs)

    def test_admin_login_unknown_phone(self):
        r = _login("admin", "9999999999", "whatever")
        assert r.status_code == 401


# ---------- RBAC ----------
class TestRBAC:
    def test_no_token_401(self):
        r = requests.get(f"{API}/admin/stats", timeout=15)
        assert r.status_code == 401

    def test_pharmacy_token_403(self):
        tok = _ph_token()
        r = requests.get(f"{API}/admin/stats", headers=_h(tok), timeout=15)
        assert r.status_code == 403

    def test_supplier_token_403(self):
        tok = _sup_token()
        r = requests.get(f"{API}/admin/stats", headers=_h(tok), timeout=15)
        assert r.status_code == 403

    def test_admin_token_200(self):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/stats", headers=_h(tok), timeout=15)
        assert r.status_code == 200


# ---------- change-password (validates + restores) ----------
class TestAdminChangePassword:
    def test_validates_old_password(self):
        tok = _admin_token()
        r = requests.post(f"{API}/admin/change-password", headers=_h(tok),
                          json={"old_password": "wrong", "new_password": "abcdef"}, timeout=15)
        assert r.status_code == 401

    def test_validates_new_password_length(self):
        tok = _admin_token()
        r = requests.post(f"{API}/admin/change-password", headers=_h(tok),
                          json={"old_password": ADMIN_PASS, "new_password": "12345"}, timeout=15)
        assert r.status_code == 400

    def test_change_password_flow_and_restore(self):
        tok = _admin_token()
        new_pw = "newpw_" + uuid.uuid4().hex[:6]
        # change
        r = requests.post(f"{API}/admin/change-password", headers=_h(tok),
                          json={"old_password": ADMIN_PASS, "new_password": new_pw}, timeout=15)
        assert r.status_code == 200
        # old password no longer works
        assert _login("admin", ADMIN_PHONE, ADMIN_PASS).status_code == 401
        # new pw works + must_change_password=False
        r2 = _login("admin", ADMIN_PHONE, new_pw)
        assert r2.status_code == 200
        assert r2.json()["admin"]["must_change_password"] is False
        # RESTORE original
        tok2 = r2.json()["token"]
        r3 = requests.post(f"{API}/admin/change-password", headers=_h(tok2),
                           json={"old_password": new_pw, "new_password": ADMIN_PASS}, timeout=15)
        assert r3.status_code == 200
        assert _login("admin", ADMIN_PHONE, ADMIN_PASS).status_code == 200


# ---------- Stats ----------
class TestAdminStats:
    def test_stats_schema(self):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/stats", headers=_h(tok), timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("pharmacies", "suppliers", "medicines", "products", "orders",
                  "sales", "revenue", "catalog_jobs", "audit_logs"):
            assert k in d, f"missing key: {k}"
        assert isinstance(d["revenue"], (int, float))
        assert all(isinstance(d[k], int) for k in ("pharmacies", "suppliers", "medicines",
                                                    "products", "orders", "sales",
                                                    "catalog_jobs", "audit_logs"))


# ---------- Users (with cleanup) ----------
@pytest.fixture
def temp_pharmacy():
    phone = "0779" + uuid.uuid4().hex[:7]
    r = requests.post(f"{API}/pharmacy/register", json={
        "name": "TEST_pharm_admin", "phone": phone, "password": "pw123456", "address": "TEST"
    }, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    yield {"id": body["pharmacy"]["id"], "phone": phone, "password": "pw123456", "token": body["token"]}
    # cleanup via admin delete (idempotent)
    try:
        atok = _admin_token()
        requests.delete(f"{API}/admin/users/pharmacy/{body['pharmacy']['id']}", headers=_h(atok), timeout=15)
    except Exception:
        pass


@pytest.fixture
def temp_supplier():
    phone = "0788" + uuid.uuid4().hex[:7]
    r = requests.post(f"{API}/supplier/register", json={
        "name": "TEST_sup_admin", "phone": phone, "password": "pw123456", "address": "TEST"
    }, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    yield {"id": body["supplier"]["id"], "phone": phone, "password": "pw123456", "token": body["token"]}
    try:
        atok = _admin_token()
        requests.delete(f"{API}/admin/users/supplier/{body['supplier']['id']}", headers=_h(atok), timeout=15)
    except Exception:
        pass


class TestAdminUsers:
    def test_users_list_combined_with_role(self, temp_pharmacy, temp_supplier):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/users", headers=_h(tok), timeout=15)
        assert r.status_code == 200
        users = r.json()
        roles = {u.get("role") for u in users}
        assert "pharmacy" in roles and "supplier" in roles
        ids = {u["id"] for u in users}
        assert temp_pharmacy["id"] in ids and temp_supplier["id"] in ids

    def test_users_role_filter(self, temp_pharmacy, temp_supplier):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/users", params={"role": "pharmacy"}, headers=_h(tok), timeout=15)
        assert r.status_code == 200
        assert all(u["role"] == "pharmacy" for u in r.json())
        r2 = requests.get(f"{API}/admin/users", params={"role": "supplier"}, headers=_h(tok), timeout=15)
        assert r2.status_code == 200
        assert all(u["role"] == "supplier" for u in r2.json())

    def test_disable_pharmacy_blocks_login_then_enable(self, temp_pharmacy):
        tok = _admin_token()
        r = requests.patch(f"{API}/admin/users/pharmacy/{temp_pharmacy['id']}",
                           headers=_h(tok), json={"disabled": True}, timeout=15)
        assert r.status_code == 200
        # login blocked 403
        r2 = _login("pharmacy", temp_pharmacy["phone"], temp_pharmacy["password"])
        assert r2.status_code == 403
        assert "معطل" in r2.text
        # audit entry user_disabled
        a = requests.get(f"{API}/admin/audit-logs", params={"action": "user_disabled"},
                         headers=_h(tok), timeout=15)
        assert a.status_code == 200
        assert any(l.get("target", {}).get("id") == temp_pharmacy["id"] for l in a.json())
        # enable
        r3 = requests.patch(f"{API}/admin/users/pharmacy/{temp_pharmacy['id']}",
                            headers=_h(tok), json={"disabled": False}, timeout=15)
        assert r3.status_code == 200
        r4 = _login("pharmacy", temp_pharmacy["phone"], temp_pharmacy["password"])
        assert r4.status_code == 200
        a2 = requests.get(f"{API}/admin/audit-logs", params={"action": "user_enabled"},
                          headers=_h(tok), timeout=15)
        assert any(l.get("target", {}).get("id") == temp_pharmacy["id"] for l in a2.json())

    def test_disable_supplier_blocks_login(self, temp_supplier):
        tok = _admin_token()
        requests.patch(f"{API}/admin/users/supplier/{temp_supplier['id']}",
                       headers=_h(tok), json={"disabled": True}, timeout=15)
        r = _login("supplier", temp_supplier["phone"], temp_supplier["password"])
        assert r.status_code == 403

    def test_patch_invalid_role(self):
        tok = _admin_token()
        r = requests.patch(f"{API}/admin/users/admin/some-id",
                           headers=_h(tok), json={"disabled": True}, timeout=15)
        assert r.status_code == 400

    def test_patch_missing_disabled(self, temp_pharmacy):
        tok = _admin_token()
        r = requests.patch(f"{API}/admin/users/pharmacy/{temp_pharmacy['id']}",
                           headers=_h(tok), json={}, timeout=15)
        assert r.status_code == 400

    def test_delete_pharmacy_cascades_medicines(self, temp_pharmacy):
        # add medicine as the temp pharmacy
        h = {"Authorization": f"Bearer {temp_pharmacy['token']}", "Content-Type": "application/json"}
        med = requests.post(f"{API}/medicines", headers=h,
                            json={"name": "TEST_med_cascade", "quantity": 5, "price": 1.0}, timeout=15)
        assert med.status_code == 200, med.text
        # delete pharmacy via admin
        tok = _admin_token()
        r = requests.delete(f"{API}/admin/users/pharmacy/{temp_pharmacy['id']}",
                            headers=_h(tok), timeout=15)
        assert r.status_code == 200
        # re-login fails
        r2 = _login("pharmacy", temp_pharmacy["phone"], temp_pharmacy["password"])
        assert r2.status_code == 401
        # admin/products no longer contains this medicine
        p = requests.get(f"{API}/admin/products", params={"kind": "medicine"},
                         headers=_h(tok), timeout=15)
        assert p.status_code == 200
        assert all(m.get("pharmacy_id") != temp_pharmacy["id"] for m in p.json())
        # audit log user_deleted
        a = requests.get(f"{API}/admin/audit-logs", params={"action": "user_deleted"},
                         headers=_h(tok), timeout=15)
        assert any(l.get("target", {}).get("id") == temp_pharmacy["id"] for l in a.json())

    def test_delete_supplier_cascades_products(self, temp_supplier):
        h = {"Authorization": f"Bearer {temp_supplier['token']}", "Content-Type": "application/json"}
        p = requests.post(f"{API}/supplier/products", headers=h,
                          json={"name": "TEST_sp_cascade", "price": 2.0, "quantity": 10}, timeout=15)
        assert p.status_code == 200
        tok = _admin_token()
        r = requests.delete(f"{API}/admin/users/supplier/{temp_supplier['id']}",
                            headers=_h(tok), timeout=15)
        assert r.status_code == 200
        all_products = requests.get(f"{API}/admin/products", params={"kind": "supplier_product"},
                                    headers=_h(tok), timeout=15).json()
        assert all(sp.get("supplier_id") != temp_supplier["id"] for sp in all_products)


# ---------- Orders ----------
class TestAdminOrders:
    def test_orders_listing_enriched_and_status_update(self, temp_pharmacy):
        # create an order from pharmacy
        h = {"Authorization": f"Bearer {temp_pharmacy['token']}", "Content-Type": "application/json"}
        o = requests.post(f"{API}/orders", headers=h,
                          json={"items": [{"name": "TEST_item", "quantity": 1}]}, timeout=15)
        assert o.status_code == 200, o.text
        oid = o.json()["id"]

        tok = _admin_token()
        # list returns pharmacy_name + default status pending
        r = requests.get(f"{API}/admin/orders", headers=_h(tok), timeout=15)
        assert r.status_code == 200
        match = next((d for d in r.json() if d["id"] == oid), None)
        assert match is not None
        assert "pharmacy_name" in match
        assert match.get("status", "pending") == "pending"

        # update to confirmed
        u = requests.patch(f"{API}/admin/orders/{oid}", headers=_h(tok),
                           json={"status": "confirmed"}, timeout=15)
        assert u.status_code == 200

        # status filter
        r2 = requests.get(f"{API}/admin/orders", params={"status": "confirmed"},
                          headers=_h(tok), timeout=15)
        assert r2.status_code == 200
        assert any(d["id"] == oid for d in r2.json())
        assert all(d["status"] == "confirmed" for d in r2.json())

    def test_order_invalid_status(self):
        tok = _admin_token()
        r = requests.patch(f"{API}/admin/orders/non-existent", headers=_h(tok),
                           json={"status": "bogus"}, timeout=15)
        assert r.status_code == 400

    def test_order_not_found(self):
        tok = _admin_token()
        r = requests.patch(f"{API}/admin/orders/{uuid.uuid4()}", headers=_h(tok),
                           json={"status": "confirmed"}, timeout=15)
        assert r.status_code == 404


# ---------- Products ----------
class TestAdminProducts:
    def test_combined_with_kind_and_delete(self, temp_pharmacy, temp_supplier):
        ph_h = {"Authorization": f"Bearer {temp_pharmacy['token']}", "Content-Type": "application/json"}
        m = requests.post(f"{API}/medicines", headers=ph_h,
                          json={"name": "TEST_med_kind", "quantity": 1, "price": 1.0}, timeout=15).json()
        sp_h = {"Authorization": f"Bearer {temp_supplier['token']}", "Content-Type": "application/json"}
        sp = requests.post(f"{API}/supplier/products", headers=sp_h,
                           json={"name": "TEST_sp_kind", "price": 2.0, "quantity": 5}, timeout=15).json()

        tok = _admin_token()
        r = requests.get(f"{API}/admin/products", headers=_h(tok), timeout=15)
        assert r.status_code == 200
        items = r.json()
        kinds = {it["kind"] for it in items}
        assert "medicine" in kinds and "supplier_product" in kinds

        # delete medicine
        d1 = requests.delete(f"{API}/admin/products/medicine/{m['id']}", headers=_h(tok), timeout=15)
        assert d1.status_code == 200
        # delete supplier_product
        d2 = requests.delete(f"{API}/admin/products/supplier_product/{sp['id']}", headers=_h(tok), timeout=15)
        assert d2.status_code == 200
        # invalid kind
        d3 = requests.delete(f"{API}/admin/products/foo/whatever", headers=_h(tok), timeout=15)
        assert d3.status_code == 400
        # not found
        d4 = requests.delete(f"{API}/admin/products/medicine/{uuid.uuid4()}", headers=_h(tok), timeout=15)
        assert d4.status_code == 404


# ---------- Notifications ----------
class TestAdminNotifications:
    def test_create_list_delete_and_audience_routing(self, temp_pharmacy, temp_supplier):
        tok = _admin_token()
        # create 3 notifs: all, pharmacy, supplier
        n_all = requests.post(f"{API}/admin/notifications", headers=_h(tok),
                              json={"title": "TEST_all", "body": "b", "audience": "all"}, timeout=15).json()
        n_ph = requests.post(f"{API}/admin/notifications", headers=_h(tok),
                             json={"title": "TEST_ph", "body": "b", "audience": "pharmacy"}, timeout=15).json()
        n_sp = requests.post(f"{API}/admin/notifications", headers=_h(tok),
                             json={"title": "TEST_sp", "body": "b", "audience": "supplier"}, timeout=15).json()

        # invalid audience
        bad = requests.post(f"{API}/admin/notifications", headers=_h(tok),
                            json={"title": "x", "body": "y", "audience": "everyone"}, timeout=15)
        assert bad.status_code == 400
        # empty title/body
        empty = requests.post(f"{API}/admin/notifications", headers=_h(tok),
                              json={"title": "  ", "body": "", "audience": "all"}, timeout=15)
        assert empty.status_code == 400

        # admin lists
        lst = requests.get(f"{API}/admin/notifications", headers=_h(tok), timeout=15).json()
        ids = {n["id"] for n in lst}
        assert {n_all["id"], n_ph["id"], n_sp["id"]} <= ids

        # pharmacy sees all + pharmacy
        ph_h = {"Authorization": f"Bearer {temp_pharmacy['token']}"}
        ph_active = requests.get(f"{API}/notifications/active", headers=ph_h, timeout=15).json()
        ph_titles = {n["title"] for n in ph_active}
        assert "TEST_all" in ph_titles and "TEST_ph" in ph_titles and "TEST_sp" not in ph_titles

        # supplier sees all + supplier
        sp_h = {"Authorization": f"Bearer {temp_supplier['token']}"}
        sp_active = requests.get(f"{API}/notifications/active", headers=sp_h, timeout=15).json()
        sp_titles = {n["title"] for n in sp_active}
        assert "TEST_all" in sp_titles and "TEST_sp" in sp_titles and "TEST_ph" not in sp_titles

        # admin can also fetch active
        adm_active = requests.get(f"{API}/notifications/active", headers=_h(tok), timeout=15)
        assert adm_active.status_code == 200

        # cleanup
        for nid in (n_all["id"], n_ph["id"], n_sp["id"]):
            d = requests.delete(f"{API}/admin/notifications/{nid}", headers=_h(tok), timeout=15)
            assert d.status_code == 200
        # verify gone from admin list
        lst2 = requests.get(f"{API}/admin/notifications", headers=_h(tok), timeout=15).json()
        ids2 = {n["id"] for n in lst2}
        assert not ({n_all["id"], n_ph["id"], n_sp["id"]} & ids2)

    def test_active_requires_auth(self):
        r = requests.get(f"{API}/notifications/active", timeout=15)
        assert r.status_code == 401


# ---------- Audit logs ----------
class TestAuditLogs:
    def test_action_filter(self):
        tok = _admin_token()
        # trigger a login event
        _login("admin", ADMIN_PHONE, ADMIN_PASS)
        r = requests.get(f"{API}/admin/audit-logs", params={"action": "login"},
                         headers=_h(tok), timeout=15)
        assert r.status_code == 200
        logs = r.json()
        assert all(l["action"] == "login" for l in logs)

    def test_no_filter(self):
        tok = _admin_token()
        r = requests.get(f"{API}/admin/audit-logs", headers=_h(tok), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------- Regression: existing logins still work ----------
class TestRegression:
    def test_pharmacy_login(self):
        r = _login("pharmacy", PH_PHONE, PH_PASS)
        assert r.status_code == 200
        assert "token" in r.json()

    def test_supplier_login(self):
        r = _login("supplier", SUP_PHONE, SUP_PASS)
        assert r.status_code == 200
        assert "token" in r.json()
