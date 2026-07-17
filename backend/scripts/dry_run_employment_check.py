"""
Dry-run: check current employment status via SED API for all pulse recipients
         whose verification_method = 'sed_api'.

READ-ONLY. Zero DB writes (no UPDATE, INSERT, or new columns).
Pulse population: exactly the WHERE clause from pulse_service.send_monthly_survey()
                  (verified: lines 1070–1075) plus verification_method filter.

Usage:
  cd /home/runner/workspace && python backend/scripts/dry_run_employment_check.py

Output:
  Summary (EMPLOYED / GONE / ERROR counts), then full GONE list, then full ERROR list.
"""
import os
import sys
import time
from datetime import datetime

import httpx
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models as _models
_models.init_db()

SED_API_URL = os.getenv("SED_API_URL", "https://api-sed.tdav.net.ua")
SED_API_KEY = os.getenv("SED_API_KEY", "")

PAUSE_S   = float(os.getenv("DRY_RUN_PAUSE", "0.200"))
TIMEOUT_S = float(os.getenv("DRY_RUN_TIMEOUT", "10.0"))


def check_one(phone: str) -> tuple[str, str]:
    """
    POST /api/employees with the phone exactly as stored in hr_users.phone.
    Returns (status, reason) where status ∈ {'EMPLOYED', 'GONE', 'ERROR'}.
    """
    if not phone:
        return "ERROR", "phone IS NULL in hr_users"

    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {SED_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        resp = httpx.post(
            f"{SED_API_URL}/api/employees",
            headers=headers,
            json={"phone": phone},
            timeout=TIMEOUT_S,
        )
    except httpx.TimeoutException:
        return "ERROR", "timeout"
    except Exception as exc:
        return "ERROR", f"request_error: {exc}"

    if resp.status_code != 200:
        return "ERROR", f"HTTP {resp.status_code}"

    try:
        data = resp.json()
    except Exception:
        return "ERROR", f"invalid JSON: {resp.text[:120]}"

    if data.get("status") is True:
        return "EMPLOYED", ""

    errors = data.get("errors") or []
    if isinstance(errors, list):
        errors_text = " | ".join(str(e) for e in errors)
    else:
        errors_text = str(errors)

    if "Employee not found." in errors_text:
        return "GONE", ""

    return "ERROR", f"status=false, errors: {errors_text or repr(data)}"


def main():
    if not SED_API_KEY:
        print("ERROR: SED_API_KEY not set in environment — aborting.")
        sys.exit(1)

    db = _models.SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT telegram_id, full_name, phone, last_sed_sync "
                "FROM hr_users "
                "WHERE is_active = TRUE AND telegram_id IS NOT NULL "
                "  AND verification_method = 'sed_api'"
            )
        ).fetchall()
    finally:
        db.close()

    total = len(rows)
    print(f"\n{'='*60}")
    print(f"DRY-RUN: employment check via SED API")
    print(f"Population (sed_api users, is_active, has telegram_id): {total}")
    print(f"{'='*60}\n")

    employed = []
    gone     = []
    errors   = []

    for i, row in enumerate(rows, 1):
        tg_id, full_name, phone, last_sync = row
        label = full_name or f"telegram_id={tg_id}"
        status, reason = check_one(phone)

        icon = {"EMPLOYED": "✅", "GONE": "🔴", "ERROR": "⚠️ "}.get(status, "?")
        sync_str = last_sync.strftime("%Y-%m-%d") if last_sync else "ніколи"
        print(f"[{i:3}/{total}] {icon} {status:<8}  {label}  ({phone})  last_sync={sync_str}"
              + (f"  ← {reason}" if reason else ""))

        if status == "EMPLOYED":
            employed.append((full_name, phone, last_sync))
        elif status == "GONE":
            gone.append((full_name, phone, last_sync))
        else:
            errors.append((full_name, phone, last_sync, reason))

        if i < total:
            time.sleep(PAUSE_S)

    print(f"\n{'='*60}")
    print(f"ПІДСУМОК")
    print(f"{'='*60}")
    print(f"  EMPLOYED : {len(employed)}")
    print(f"  GONE     : {len(gone)}")
    print(f"  ERROR    : {len(errors)}")
    print(f"  TOTAL    : {total}")

    if gone:
        print(f"\n{'─'*60}")
        print(f"GONE ({len(gone)}) — не знайдені в SED:")
        print(f"{'─'*60}")
        for full_name, phone, last_sync in gone:
            sync_str = last_sync.strftime("%Y-%m-%d") if last_sync else "ніколи"
            print(f"  • {full_name}  |  {phone}  |  last_sync={sync_str}")

    if errors:
        print(f"\n{'─'*60}")
        print(f"ERROR ({len(errors)}) — не вдалось перевірити:")
        print(f"{'─'*60}")
        for full_name, phone, last_sync, reason in errors:
            sync_str = last_sync.strftime("%Y-%m-%d") if last_sync else "ніколи"
            print(f"  • {full_name}  |  {phone}  |  last_sync={sync_str}  |  {reason}")

    print()


if __name__ == "__main__":
    main()
