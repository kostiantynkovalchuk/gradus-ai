"""
Phase 6 — Daily KB edition actualization cron.

Checks each active solomon_kb_sources row for edition changes.
If the edition date/basis has changed since last ingest, triggers full re-ingest.
Writes history rows to solomon_kb_source_history for auditing.

Dev-channel Telegram alert on parser/HTTP failures only — no notification to legal team.
Auto-reingest on edition flip is SILENT.

Scheduled: daily at 03:00 Kyiv time (01:00 UTC, since Kyiv is UTC+2).
"""
import logging
import os
import re
from datetime import date, datetime
from typing import Optional

import requests

from solomon_contracts import db as solcon_db
from solomon_contracts.kb_ingest import (
    _fetch_current_edition,
    _parse_edition_header,
    ingest_law,
)

logger = logging.getLogger(__name__)

# ─── Entry point ──────────────────────────────────────────────────────────────

def run_daily_edition_check():
    """
    Check all active KB sources for edition changes.
    Called by the scheduler daily at 03:00 Kyiv time (01:00 UTC).
    """
    logger.info("[KBEditionCheck] Daily edition check starting")
    sources = solcon_db.fetchall(
        "SELECT * FROM solomon_kb_sources WHERE status = 'active' ORDER BY id"
    )
    if not sources:
        logger.warning("[KBEditionCheck] No active sources found")
        return

    ok, changed, failed_list = 0, 0, []
    for source in sources:
        try:
            result = _check_one_source(dict(source))
            if result == "no_change":
                ok += 1
            elif result == "updated":
                changed += 1
        except Exception as e:
            failed_list.append(source["law_code"])
            logger.exception(f"[KBEditionCheck] Failed for {source['law_code']}: {e}")
            _notify_dev(f"[KB Edition Check] Failed for {source['law_code']}: {e}")

    logger.info(
        f"[KBEditionCheck] Done: {ok} no_change, {changed} updated, {len(failed_list)} failed"
    )
    if failed_list:
        logger.error(f"[KBEditionCheck] Failed sources: {failed_list}")


# ─── Per-source check ─────────────────────────────────────────────────────────

def _check_one_source(source: dict) -> str:
    """
    Check one source for edition changes.
    Returns: 'no_change' | 'updated' | raises on failure.
    """
    canonical_url = source.get("canonical_url", "")
    if not canonical_url:
        logger.warning(f"[KBEditionCheck] {source['law_code']}: no canonical_url, skipping")
        return "no_change"

    history_id = solcon_db.fetchone(
        """INSERT INTO solomon_kb_source_history
             (kb_source_id, edition_date_from, edition_basis_from,
              status, reingest_started_at)
           VALUES (%s, %s, %s, 'in_progress', NOW())
           RETURNING id""",
        (source["id"], source.get("current_edition_date"), source.get("current_edition_basis")),
    )["id"]

    try:
        html, _ = _fetch_current_edition(canonical_url, max_hops=3)
        new_date, new_basis, next_basis, _ = _parse_edition_header(html)

        cur_date = source.get("current_edition_date")
        cur_basis = source.get("current_edition_basis")

        if _dates_equal(new_date, cur_date) and new_basis == cur_basis:
            solcon_db.execute(
                """UPDATE solomon_kb_source_history
                   SET status = 'no_change'
                   WHERE id = %s""",
                (history_id,),
            )
            solcon_db.execute(
                "UPDATE solomon_kb_sources SET last_verified_at = NOW() WHERE id = %s",
                (source["id"],),
            )
            logger.debug(f"[KBEditionCheck] {source['law_code']}: no change")
            return "no_change"

        logger.info(
            f"[KBEditionCheck] {source['law_code']}: edition flipped "
            f"({cur_date}/{cur_basis} → {new_date}/{new_basis}) — re-ingesting"
        )

        result = ingest_law(source["law_code"])

        solcon_db.execute(
            """UPDATE solomon_kb_source_history
               SET status = 'completed',
                   edition_date_to       = %s,
                   edition_basis_to      = %s,
                   chunks_added          = %s,
                   reingest_completed_at = NOW()
               WHERE id = %s""",
            (result["edition_date"], result["edition_basis"], result["chunks_added"], history_id),
        )
        return "updated"

    except Exception as exc:
        solcon_db.execute(
            """UPDATE solomon_kb_source_history
               SET status = 'failed',
                   error_message         = %s,
                   reingest_completed_at = NOW()
               WHERE id = %s""",
            (str(exc)[:2000], history_id),
        )
        raise


def _dates_equal(a: Optional[date], b) -> bool:
    """Compare dates robustly (handles date/datetime/None/string from DB)."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    a_str = a.isoformat() if hasattr(a, "isoformat") else str(a)[:10]
    b_str = b.isoformat() if hasattr(b, "isoformat") else str(b)[:10]
    return a_str == b_str


# ─── Dev channel notification ─────────────────────────────────────────────────

def _notify_dev(message: str):
    """
    Send a Telegram message to the dev ops channel on failure.
    Uses TELEGRAM_BOT_TOKEN + SOLOMON_OPS_CHAT_ID env vars.
    Silent if env vars not set (development mode).
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("SOLOMON_OPS_CHAT_ID")
    if not token or not chat_id:
        logger.warning(f"[KBEditionCheck] Dev notify skipped (no token/chat_id): {message}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": f"⚠️ {message}", "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"[KBEditionCheck] Dev notify failed: {e}")
