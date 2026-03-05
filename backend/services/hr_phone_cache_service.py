"""
Phone cache service.
Phase 1: seeded from Blitz xlsx export.
Phase 2: will be replaced by nightly SED API sync when IT adds list endpoint.
"""
import re
import logging
import os
from io import BytesIO

logger = logging.getLogger(__name__)

R_MARKER = '(р)'
L_MARKER = '(л)'
EMPTY_PAT = re.compile(r'\(\s+\)\s+-\s+-')


def normalize_phone_cache(raw: str) -> str | None:
    if not raw:
        return None
    digits = re.sub(r'\D', '', str(raw))
    if len(digits) == 10 and digits.startswith('0'):
        return '380' + digits[1:]
    elif len(digits) == 12 and digits.startswith('380'):
        return digits
    elif len(digits) == 11 and digits.startswith('80'):
        return '3' + digits
    return None


def _has_digits(s: str) -> bool:
    return bool(re.search(r'\d', s))


def parse_blitz_phone_field(raw) -> tuple[str | None, str | None]:
    if not raw:
        return None, None
    raw = str(raw).strip()
    has_r = R_MARKER in raw
    has_l = L_MARKER in raw
    work_raw = mobile_raw = None

    if has_r and has_l:
        idx_l = raw.index(L_MARKER)
        work_part = raw[:idx_l].replace(R_MARKER, '').strip().rstrip(';').strip()
        mobile_part = raw[idx_l:].replace(L_MARKER, '').strip().rstrip(';').strip()
        if not EMPTY_PAT.search(work_part) and _has_digits(work_part):
            work_raw = work_part
        if not EMPTY_PAT.search(mobile_part) and _has_digits(mobile_part):
            mobile_raw = mobile_part
    elif has_r:
        p = raw.replace(R_MARKER, '').strip().rstrip(';').strip()
        if not EMPTY_PAT.search(p) and _has_digits(p):
            work_raw = p
    elif has_l:
        p = raw.replace(L_MARKER, '').strip().rstrip(';').strip()
        if _has_digits(p):
            mobile_raw = p
    elif _has_digits(raw):
        mobile_raw = raw

    return normalize_phone_cache(work_raw), normalize_phone_cache(mobile_raw)


def seed_from_xlsx_sync(xlsx_bytes: bytes, db) -> dict:
    import openpyxl
    from sqlalchemy import text

    wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), data_only=True)
    ws = wb.active

    imported = no_phone = errors = 0
    total = 0

    db.execute(text("DELETE FROM hr_employee_phone_cache"))

    for row in ws.iter_rows(min_row=2, values_only=True):
        name_raw, phone_raw = row[0], row[1]
        if not name_raw or str(name_raw).strip() in ('', 'ФИО'):
            continue
        total += 1
        full_name = str(name_raw).strip()

        work_norm, mobile_norm = parse_blitz_phone_field(phone_raw)

        if not work_norm and not mobile_norm:
            no_phone += 1
            logger.debug(f"No phone: {full_name} | raw: {phone_raw}")
            continue

        try:
            db.execute(
                text("""
                    INSERT INTO hr_employee_phone_cache
                        (full_name, phone_work_raw, phone_mobile_raw,
                         phone_work_norm, phone_mobile_norm, source)
                    VALUES (:name, :wr, :mr, :wn, :mn, 'blitz_xlsx')
                """),
                {
                    "name": full_name,
                    "wr": str(phone_raw) if phone_raw else None,
                    "mr": str(phone_raw) if phone_raw else None,
                    "wn": work_norm,
                    "mn": mobile_norm,
                }
            )
            imported += 1
        except Exception as e:
            logger.error(f"Insert error for {full_name}: {e}")
            errors += 1

    db.execute(
        text("""
            INSERT INTO hr_phone_import_log
                (source, total_rows, imported, no_phone)
            VALUES ('blitz_xlsx', :total, :imported, :no_phone)
        """),
        {"total": total, "imported": imported, "no_phone": no_phone}
    )
    db.commit()

    logger.info(
        f"Seed complete: {imported} imported, "
        f"{no_phone} no-phone, {errors} errors from {total} rows"
    )
    return {
        "total": total, "imported": imported,
        "no_phone": no_phone, "errors": errors
    }


def find_employee_by_phone_sync(phone: str, db) -> dict | None:
    from utils.phone_normalizer import normalize_phone
    from sqlalchemy import text

    normalized = normalize_phone(phone)
    if not normalized:
        logger.warning(f"Cannot normalize phone for cache lookup: {phone}")
        return None

    row = db.execute(
        text("""
            SELECT full_name, phone_work_norm, phone_mobile_norm, source
            FROM hr_employee_phone_cache
            WHERE phone_work_norm = :phone OR phone_mobile_norm = :phone
            LIMIT 1
        """),
        {"phone": normalized}
    ).fetchone()

    if not row:
        return None

    matched_via = "work" if row[1] == normalized else "mobile"
    logger.info(
        f"✅ Cache match: {normalized} → "
        f"{row[0]} via {matched_via}"
    )
    return {
        "full_name": row[0],
        "phone_work": row[1],
        "phone_mobile": row[2],
        "matched_via": matched_via,
        "source": row[3],
        "verified": True,
    }


def get_cache_stats_sync(db) -> dict:
    from sqlalchemy import text

    stats = db.execute(text("""
        SELECT
            COUNT(*) as total,
            COUNT(phone_work_norm) as with_work,
            COUNT(phone_mobile_norm) as with_mobile,
            MAX(imported_at) as last_import
        FROM hr_employee_phone_cache
    """)).fetchone()

    last_log = db.execute(text("""
        SELECT source, total_rows, imported, no_phone, imported_at
        FROM hr_phone_import_log
        ORDER BY imported_at DESC LIMIT 1
    """)).fetchone()

    result = {
        "total": stats[0] if stats else 0,
        "with_work": stats[1] if stats else 0,
        "with_mobile": stats[2] if stats else 0,
        "last_import": stats[3].isoformat() if stats and stats[3] else None,
    }
    if last_log:
        result["last_import_log"] = {
            "source": last_log[0],
            "total_rows": last_log[1],
            "imported": last_log[2],
            "no_phone": last_log[3],
            "imported_at": last_log[4].isoformat() if last_log[4] else None,
        }
    else:
        result["last_import_log"] = None

    return result
