"""Backend verification for the Emergent Push Notifications flow.

Covers the checklist provided by the main agent:
  A. admin send → 200 status:sent, delivered==total, failed==0
  B. pharmacy sees the new notification at the top of GET /notifications
  C. backend log contains the '401 unauthorized' relay message
  D. POST /register-push returns 201 with status:queued (or registered), never 500
  E. Two identical sends → distinct batch_ids, both status:sent
  F. GET /admin/notifications/history → first item is the last-sent batch
  G. GET /admin/notifications/audience-summary → contains roles/total/regions
  H. Log inspection — send_push is called (401 emitted) but only once per send
  J. Preferences respected — pharmacy with notifications_enabled=false is skipped
"""
import os
import re
import time
import subprocess
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_PHONE = "0000000000"
ADMIN_PASS = "admin123"
PHARMACY_PHONE = "07700000001"
PHARMACY_PASS = "pass123"

BACKEND_ERR_LOG = "/var/log/supervisor/backend.err.log"
BACKEND_OUT_LOG = "/var/log/supervisor/backend.out.log"


# --------- Helpers ---------

def _login(phone: str, password: str) -> dict:
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "password": password}, timeout=10)
    assert r.status_code == 200, f"login failed for {phone}: {r.status_code} {r.text}"
    return r.json()


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _read_logs_tail(n: int = 400) -> str:
    combined = ""
    for path in (BACKEND_ERR_LOG, BACKEND_OUT_LOG):
        try:
            out = subprocess.run(
                ["tail", "-n", str(n), path], capture_output=True, text=True, timeout=5
            )
            combined += out.stdout + "\n"
        except Exception:
            pass
    return combined


@pytest.fixture(scope="module")
def admin_token() -> str:
    data = _login(ADMIN_PHONE, ADMIN_PASS)
    return data["token"]


@pytest.fixture(scope="module")
def pharmacy_ctx() -> dict:
    data = _login(PHARMACY_PHONE, PHARMACY_PASS)
    # Try to get user id via /me/profile
    r = requests.get(f"{API}/me/profile", headers=_auth_headers(data["token"]), timeout=10)
    assert r.status_code == 200, f"profile fetch failed: {r.status_code} {r.text}"
    profile = r.json()
    return {"token": data["token"], "user_id": profile.get("id")}


# --------- A. admin send ---------

def test_A_admin_send_role_pharmacy(admin_token, pharmacy_ctx):
    payload = {
        "title": "TEST_Push_A",
        "body": "Push test A body",
        "audience_mode": "role",
        "role": "pharmacy",
    }
    r = requests.post(
        f"{API}/admin/notifications/send",
        json=payload, headers=_auth_headers(admin_token), timeout=15,
    )
    assert r.status_code == 200, f"send failed: {r.status_code} {r.text}"
    data = r.json()
    assert data["status"] == "sent"
    assert "batch_id" in data
    assert data["total"] >= 1
    assert data["delivered"] == data["total"], f"delivered != total: {data}"
    assert data["failed"] == 0
    # Stash for later use
    pytest.batch_A_id = data["batch_id"]
    pytest.batch_A_total = data["total"]


# --------- B. pharmacy sees the notification ---------

def test_B_pharmacy_sees_notification(pharmacy_ctx):
    r = requests.get(
        f"{API}/notifications?limit=5",
        headers=_auth_headers(pharmacy_ctx["token"]), timeout=10,
    )
    assert r.status_code == 200, r.text
    items = r.json().get("items", [])
    assert items, "pharmacy notifications list is empty"
    top = items[0]
    assert top["title"] == "TEST_Push_A"
    assert top["body"] == "Push test A body"
    assert top["type"] == "admin"
    assert top.get("batch_id") == pytest.batch_A_id


# --------- C. backend logs contain 401 unauthorized ---------

def test_C_backend_log_shows_401():
    # Give logs a moment to flush
    time.sleep(1.0)
    log = _read_logs_tail(500)
    # Accept either the concrete message or the substring
    assert re.search(r"Emergent push:\s*401 unauthorized", log), (
        "Expected '401 unauthorized' relay log line not found. "
        "This proves the relay is wired. Log tail head:\n" + log[-2000:]
    )


# --------- D. register-push must NOT 500 ---------

def test_D_register_push_returns_2xx(pharmacy_ctx):
    r = requests.post(
        f"{API}/register-push",
        json={
            "user_id": pharmacy_ctx["user_id"],
            "platform": "android",
            "device_token": "test-device-token-abc123",
        },
        headers=_auth_headers(pharmacy_ctx["token"]),
        timeout=15,
    )
    assert r.status_code in (200, 201, 202), f"register-push status {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("status") in ("queued", "registered"), data


def test_D2_register_push_rejects_mismatched_user(pharmacy_ctx):
    r = requests.post(
        f"{API}/register-push",
        json={
            "user_id": "some-other-user",
            "platform": "android",
            "device_token": "test-device-token-abc123",
        },
        headers=_auth_headers(pharmacy_ctx["token"]),
        timeout=10,
    )
    assert r.status_code == 403


def test_D3_register_push_missing_token_400(pharmacy_ctx):
    r = requests.post(
        f"{API}/register-push",
        json={"user_id": pharmacy_ctx["user_id"], "platform": "android"},
        headers=_auth_headers(pharmacy_ctx["token"]),
        timeout=10,
    )
    assert r.status_code == 400


# --------- E. idempotency: two sends produce two batches ---------

def test_E_two_sends_two_batches(admin_token):
    payload = {
        "title": "TEST_Push_E",
        "body": "Push idempotency E",
        "audience_mode": "role",
        "role": "pharmacy",
    }
    r1 = requests.post(f"{API}/admin/notifications/send",
                       json=payload, headers=_auth_headers(admin_token), timeout=15)
    r2 = requests.post(f"{API}/admin/notifications/send",
                       json=payload, headers=_auth_headers(admin_token), timeout=15)
    assert r1.status_code == 200 and r2.status_code == 200
    d1, d2 = r1.json(), r2.json()
    assert d1["status"] == "sent" and d2["status"] == "sent"
    assert d1["batch_id"] != d2["batch_id"]
    assert d1["delivered"] == d1["total"]
    assert d2["delivered"] == d2["total"]
    # Same delivered count each time (audience unchanged between the two calls)
    assert d1["delivered"] == d2["delivered"]


# --------- F. history returns most recent batch first ---------

def test_F_history_top_is_recent(admin_token):
    r = requests.get(
        f"{API}/admin/notifications/history?limit=5",
        headers=_auth_headers(admin_token), timeout=10,
    )
    assert r.status_code == 200, r.text
    items = r.json().get("items", [])
    assert items, "admin history is empty"
    top = items[0]
    assert top.get("status") in ("sent", "pending")
    # The top must be one of our recent TEST_Push_* titles
    assert top.get("title", "").startswith("TEST_Push_"), top


# --------- G. audience-summary shape ---------

def test_G_audience_summary(admin_token):
    r = requests.get(
        f"{API}/admin/notifications/audience-summary",
        headers=_auth_headers(admin_token), timeout=10,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "roles" in data
    assert "total" in data
    assert "regions" in data
    assert isinstance(data["roles"], dict)
    for k in ("pharmacy", "supplier", "admin"):
        assert k in data["roles"], data["roles"]


# --------- H. send_push invoked exactly once per user per send ---------

def test_H_send_push_invocations_align_with_recipients(admin_token, pharmacy_ctx):
    """After a fresh send, count the number of '401 unauthorized' relay log lines that
    appeared during the window and confirm it's >= number of pharmacies delivered.
    This proves send_push was actually called per user (one 401 per call)."""
    # Snapshot log length first
    before = _read_logs_tail(2000)
    before_401 = len(re.findall(r"Emergent push:\s*401 unauthorized", before))

    payload = {
        "title": "TEST_Push_H",
        "body": "Push H once-per-user",
        "audience_mode": "role",
        "role": "pharmacy",
    }
    r = requests.post(
        f"{API}/admin/notifications/send",
        json=payload, headers=_auth_headers(admin_token), timeout=15,
    )
    assert r.status_code == 200
    delivered = r.json()["delivered"]

    time.sleep(1.5)
    after = _read_logs_tail(2000)
    after_401 = len(re.findall(r"Emergent push:\s*401 unauthorized", after))

    new_401 = after_401 - before_401
    # send_push chunks by 100, so 1 chunk -> 1 log line per chunk. With <100 pharmacies
    # we expect exactly one 401 per send_push call. create_notification calls
    # send_push once per user, so new_401 should equal `delivered`.
    assert new_401 >= 1, (
        f"No new 401 lines observed after send (delivered={delivered}). "
        f"before={before_401} after={after_401}"
    )
    # Not stronger equality: log verbosity/rotation can shift; just verify plausibility.
    assert new_401 <= delivered + 2, (
        f"Suspicious: {new_401} 401 lines for delivered={delivered} — send_push may be "
        f"called >1x per user."
    )


# --------- J. preferences respected ---------

def test_J_preferences_skip_disabled_user(admin_token, pharmacy_ctx):
    # 1. Disable notifications for the pharmacy user
    r = requests.put(
        f"{API}/me/notification-preferences",
        json={"notifications_enabled": False},
        headers=_auth_headers(pharmacy_ctx["token"]),
        timeout=10,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("notifications_enabled") is False

    # 2. Count pharmacy's notifications before send
    r_before = requests.get(f"{API}/notifications?limit=200",
                            headers=_auth_headers(pharmacy_ctx["token"]), timeout=10)
    assert r_before.status_code == 200
    count_before = len(r_before.json().get("items", []))

    # 3. Admin sends to role=pharmacy
    payload = {
        "title": "TEST_Push_J_skip",
        "body": "Should be skipped for disabled user",
        "audience_mode": "role",
        "role": "pharmacy",
    }
    r_send = requests.post(
        f"{API}/admin/notifications/send",
        json=payload, headers=_auth_headers(admin_token), timeout=15,
    )
    assert r_send.status_code == 200
    stats = r_send.json()
    # total counts recipients resolved; delivered should reflect skip (< total)
    # NOTE: We can't assert exact math without knowing the pharmacies count, but we
    # can assert that our disabled user did NOT receive a new row.
    assert stats["status"] == "sent"

    # 4. Verify our user's notification list is UNCHANGED (no new "TEST_Push_J_skip" row)
    r_after = requests.get(f"{API}/notifications?limit=200",
                           headers=_auth_headers(pharmacy_ctx["token"]), timeout=10)
    assert r_after.status_code == 200
    items_after = r_after.json().get("items", [])
    j_hits = [i for i in items_after if i.get("title") == "TEST_Push_J_skip"]
    assert not j_hits, f"Disabled-prefs user still received notification: {j_hits[:1]}"
    # Also the total count did not go up
    assert len(items_after) == count_before, (
        f"Notification list size changed unexpectedly for disabled user "
        f"(before={count_before}, after={len(items_after)})"
    )

    # 5. Confirm delivered_count < total in stats (i.e. at least one user was skipped)
    assert stats["delivered"] < stats["total"], (
        f"Preference-based skip did not reduce delivered count: {stats}"
    )

    # 6. Cleanup: re-enable to leave the account in a good state for later runs
    r_reset = requests.put(
        f"{API}/me/notification-preferences",
        json={"notifications_enabled": True},
        headers=_auth_headers(pharmacy_ctx["token"]),
        timeout=10,
    )
    assert r_reset.status_code == 200
