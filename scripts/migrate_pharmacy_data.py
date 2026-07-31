#!/usr/bin/env python3
"""
Pharmacy Data Migration — Preview → Production
==============================================
Migrates all operational data (medicines, batches, orders, sales, customers,
payments, paper orders, returns, supplier accounts, etc.) for a single
pharmacy account from the *preview* Emergent deployment to the *production*
deployment, so both the Android APK and the Windows Electron app see the
same data.

USAGE (from a shell with Python 3.9+ and `requests` installed):

    python3 migrate_pharmacy_data.py \\
        --pharmacy-phone   07700000001 \\
        --admin-phone      0000000000 \\
        --admin-password   'REDACTED' \\
        --source-url       https://pharma-checkout-8.preview.emergentagent.com \\
        --target-url       https://pharma-checkout-8.emergent.host \\
        --mode             merge

Options:
  --mode merge (default): upserts each document by id. Safe to run
                          repeatedly — existing docs get replaced,
                          new docs inserted.
  --mode replace        : first wipes the target pharmacy's data on the
                          production side, then inserts everything. Use
                          when you want a bit-for-bit copy.

Prerequisites:
  1. The updated backend (with /api/admin/pharmacy-export|import|summary)
     is deployed to BOTH the preview URL AND the production URL.
  2. The same admin account exists on both deployments with the same
     password (the bootstrap admin `0000000000` / `admin123` works by
     default until you rotate it).
  3. The destination pharmacy record (matching `--pharmacy-phone`)
     already exists on production. If not, register it first from the
     Windows/Android app.
"""

import argparse
import sys
import json
import time
from typing import Any, Dict

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("This script needs `requests`. Install with: pip install requests")


# ---------------------------------------------------------------------------
def _die(msg: str, extra: Any = None) -> None:
    print(f"\n❌  {msg}")
    if extra is not None:
        print(f"    {extra}")
    sys.exit(1)


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m"


def admin_login(base_url: str, phone: str, password: str) -> str:
    r = requests.post(
        f"{base_url.rstrip('/')}/api/admin/login",
        json={"phone": phone, "password": password},
        timeout=20,
    )
    if r.status_code != 200:
        _die(f"Admin login failed at {base_url}", f"HTTP {r.status_code} — {r.text[:200]}")
    return r.json()["token"]


def summary(base_url: str, token: str, phone: str) -> Dict[str, Any]:
    r = requests.get(
        f"{base_url.rstrip('/')}/api/admin/pharmacy-summary/{phone}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if r.status_code != 200:
        _die(f"pharmacy-summary failed at {base_url}", f"HTTP {r.status_code} — {r.text[:200]}")
    return r.json()


def export_bundle(base_url: str, token: str, phone: str) -> Dict[str, Any]:
    r = requests.get(
        f"{base_url.rstrip('/')}/api/admin/pharmacy-export/{phone}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    if r.status_code != 200:
        _die(f"pharmacy-export failed at {base_url}", f"HTTP {r.status_code} — {r.text[:200]}")
    return r.json()


def import_bundle(base_url: str, token: str, phone: str, bundle: Dict[str, Any], mode: str) -> Dict[str, Any]:
    r = requests.post(
        f"{base_url.rstrip('/')}/api/admin/pharmacy-import",
        headers={"Authorization": f"Bearer {token}"},
        json={"target_phone": phone, "bundle": bundle, "mode": mode},
        timeout=300,
    )
    if r.status_code != 200:
        _die(f"pharmacy-import failed at {base_url}", f"HTTP {r.status_code} — {r.text[:400]}")
    return r.json()


def _print_counts(title: str, counts: Dict[str, int], total: int) -> None:
    print(f"\n{_bold(title)}   (total: {total})")
    for col, cnt in sorted(counts.items(), key=lambda kv: -kv[1]):
        marker = "  " if cnt == 0 else "▸ "
        print(f"    {marker}{col:<24} {cnt:>7}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Migrate pharmacy data preview → production")
    ap.add_argument("--pharmacy-phone", required=True, help="Phone number of the pharmacy to migrate")
    ap.add_argument("--admin-phone",    required=True, help="Admin login phone on BOTH deployments")
    ap.add_argument("--admin-password", required=True, help="Admin password on BOTH deployments")
    ap.add_argument("--source-url",     required=True, help="URL of the SOURCE (preview) deployment")
    ap.add_argument("--target-url",     required=True, help="URL of the TARGET (production) deployment")
    ap.add_argument("--mode", choices=("merge", "replace"), default="merge",
                    help="'merge' (upsert, safe re-run) or 'replace' (wipe target first)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Only fetch counts, don't actually import.")
    ap.add_argument("--dump-file", default=None,
                    help="Optional path to save the exported bundle as JSON.")
    args = ap.parse_args()

    print(_bold("== Pharmacy Data Migration =="))
    print(f"  Pharmacy phone : {args.pharmacy_phone}")
    print(f"  Source (preview): {args.source_url}")
    print(f"  Target (prod)   : {args.target_url}")
    print(f"  Mode            : {args.mode}{'  (DRY-RUN)' if args.dry_run else ''}")

    # 1. Login on both sides
    print("\n[1/6] Logging into source (preview)…", end=" ", flush=True)
    src_token = admin_login(args.source_url, args.admin_phone, args.admin_password)
    print("✅")

    print("[2/6] Logging into target (production)…", end=" ", flush=True)
    dst_token = admin_login(args.target_url, args.admin_phone, args.admin_password)
    print("✅")

    # 2. Pre-migration summaries
    print("[3/6] Fetching pre-migration summaries…")
    src_before = summary(args.source_url, src_token, args.pharmacy_phone)
    dst_before = summary(args.target_url, dst_token, args.pharmacy_phone)
    _print_counts("SOURCE (preview) — before", src_before["counts"], src_before["total"])
    _print_counts("TARGET (production) — before", dst_before["counts"], dst_before["total"])

    if src_before["total"] == 0:
        print("\n⚠️  Source has zero documents — nothing to migrate. Aborting.")
        return

    # 3. Export
    print(f"\n[4/6] Exporting from {args.source_url} …", end=" ", flush=True)
    t0 = time.time()
    bundle = export_bundle(args.source_url, src_token, args.pharmacy_phone)
    print(f"✅  ({time.time() - t0:.1f}s, {len(json.dumps(bundle)) // 1024} KiB)")

    if args.dump_file:
        with open(args.dump_file, "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False, indent=2)
        print(f"    Saved bundle to {args.dump_file}")

    if args.dry_run:
        print("\n🛈  dry-run — skipping import.")
        return

    # 4. Confirm
    if args.mode == "replace" and dst_before["total"] > 0:
        print(f"\n⚠️  mode=replace will WIPE {dst_before['total']} existing documents on production!")
        if input("    Type YES to continue: ").strip() != "YES":
            print("Aborted.")
            return

    # 5. Import
    print(f"\n[5/6] Importing into {args.target_url} …", end=" ", flush=True)
    t0 = time.time()
    result = import_bundle(args.target_url, dst_token, args.pharmacy_phone, bundle, args.mode)
    print(f"✅  ({time.time() - t0:.1f}s)")
    print(f"    inserted={result['totals']['inserted']}  replaced={result['totals']['replaced']}")

    # 6. Post-migration summary
    print("\n[6/6] Verifying…")
    dst_after = summary(args.target_url, dst_token, args.pharmacy_phone)
    _print_counts("TARGET (production) — after", dst_after["counts"], dst_after["total"])

    src_total = src_before["total"]
    dst_total = dst_after["total"]
    if dst_total >= src_total:
        print(f"\n✅  {_bold('SUCCESS')} — target now has {dst_total} docs (source had {src_total}).")
    else:
        print(f"\n⚠️  Post-migration count ({dst_total}) is below source ({src_total}). Check the audit logs.")


if __name__ == "__main__":
    main()
