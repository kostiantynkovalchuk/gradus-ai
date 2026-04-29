"""
AV Post archive service.

Responsibilities:
1. Detect AV Post URLs in broadcast content (text + captions)
2. Auto-archive new editions after successful broadcast
3. Provide list/count APIs for the Maya HR menu
"""
import os
import re
import logging
import psycopg2
from typing import Optional

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "")

# Matches avpost-bestbrands.vercel.app AND avpost-bestbrands-N.vercel.app (N = edition number)
AVPOST_URL_REGEX = re.compile(
    r'https?://(?:www\.)?avpost-bestbrands(?:-\d+)?\.vercel\.app(?:/[^\s\)\]]*)?',
    re.IGNORECASE,
)


def extract_avpost_url(text: Optional[str]) -> Optional[str]:
    """Return the first AV Post URL found in text, or None."""
    if not text:
        return None
    match = AVPOST_URL_REGEX.search(text)
    if not match:
        return None
    return match.group(0).rstrip('.,;:!?)')


def _next_edition_number(cur) -> int:
    cur.execute("SELECT COALESCE(MAX(edition_number), 0) + 1 FROM hr_avpost_editions")
    return cur.fetchone()[0]


def archive_edition(
    url: str,
    broadcast_id: Optional[int] = None,
    source: str = 'broadcast',
    title: Optional[str] = None,
) -> Optional[int]:
    """
    Insert a new edition. Returns the edition id.
    Idempotent — duplicate URLs return the existing id without updating.
    """
    with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM hr_avpost_editions WHERE url = %s", (url,))
        row = cur.fetchone()
        if row:
            logger.info(f"[AVPOST] Edition already archived: {url} (id={row[0]})")
            return row[0]

        edition_num = _next_edition_number(cur)
        final_title = title or f"Випуск №{edition_num}"

        cur.execute(
            """INSERT INTO hr_avpost_editions
                 (url, title, edition_number, source, broadcast_id, published_at)
               VALUES (%s, %s, %s, %s, %s, NOW())
               RETURNING id""",
            (url, final_title, edition_num, source, broadcast_id),
        )
        edition_id = cur.fetchone()[0]
        conn.commit()
        logger.info(f"[AVPOST] 📰 Archived edition #{edition_num}: {url} (id={edition_id})")
        return edition_id


def list_editions(limit: int = 50, offset: int = 0) -> list[dict]:
    """Return active editions ordered newest-first."""
    with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, url, title, edition_number, published_at
               FROM hr_avpost_editions
               WHERE is_active = TRUE
               ORDER BY published_at DESC, id DESC
               LIMIT %s OFFSET %s""",
            (limit, offset),
        )
        return [
            {
                "id": r[0],
                "url": r[1],
                "title": r[2],
                "edition_number": r[3],
                "published_at": r[4],
            }
            for r in cur.fetchall()
        ]


def count_editions() -> int:
    """Count active editions."""
    with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM hr_avpost_editions WHERE is_active = TRUE")
        return cur.fetchone()[0]


def maybe_archive_from_broadcast(
    text_content: Optional[str],
    caption: Optional[str],
    broadcast_id: Optional[int],
) -> Optional[int]:
    """
    Called from broadcast_service.execute_broadcast() after a successful send.
    Scans text + caption for an AV Post URL. Archives if found.
    Safe to call on every broadcast — non-AV-Post broadcasts are a no-op.
    """
    url = extract_avpost_url(text_content) or extract_avpost_url(caption)
    if not url:
        return None
    try:
        return archive_edition(url=url, broadcast_id=broadcast_id, source='broadcast')
    except Exception as e:
        logger.exception(f"[AVPOST] Failed to archive from broadcast {broadcast_id}: {e}")
        return None
