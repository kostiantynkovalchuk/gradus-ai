"""
Shared pilot gate for Maya English (sara_tutor_bot).

Used by both sara_webhook.py and telegram_webhook.py so the whitelist
check lives in one place. Returns True when tg_user_id is allowed to
see the "Розмовна англійська" deep-link button / enter the tutor bot.
"""
import os
import logging

logger = logging.getLogger(__name__)

# Read once at import; a deploy restart picks up env changes.
_MAYA_ENGLISH_TEST_IDS: set[int] = set()
_raw = os.getenv("MAYA_ENGLISH_TEST_IDS", "")
for _part in _raw.split(","):
    _part = _part.strip()
    if _part.isdigit():
        _MAYA_ENGLISH_TEST_IDS.add(int(_part))


def is_english_pilot(tg_user_id: int) -> bool:
    """Return True if tg_user_id is in the env allowlist OR in maya_english_whitelist."""
    if tg_user_id in _MAYA_ENGLISH_TEST_IDS:
        return True
    db_url = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        return False
    try:
        import psycopg2
        with psycopg2.connect(db_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM maya_english_whitelist WHERE tg_user_id=%s LIMIT 1",
                (tg_user_id,),
            )
            return cur.fetchone() is not None
    except Exception as e:
        logger.error(f"is_english_pilot DB check failed: {e}")
        return False
