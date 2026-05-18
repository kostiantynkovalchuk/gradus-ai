"""
KB Sources registry helper.
Single source of truth for approved laws in solomon-contracts-corpus.
Replaces the old LAW_SOURCES constant in router.py.
"""
from datetime import datetime, timedelta
from typing import Optional
from . import db as solcon_db

_cache_until: Optional[datetime] = None
_cached_sources: Optional[list] = None


def get_active_kb_sources(force: bool = False) -> list[dict]:
    """
    Return all solomon_kb_sources rows with status='active'.
    Results are cached for 5 minutes to avoid repeated DB hits.
    Each row is a dict with keys: id, law_code, law_name, canonical_url,
    current_edition_date, current_edition_basis, last_verified_at, status, etc.
    """
    global _cache_until, _cached_sources
    if not force and _cache_until and datetime.now() < _cache_until:
        return _cached_sources or []
    rows = solcon_db.fetchall(
        "SELECT * FROM solomon_kb_sources WHERE status = 'active' ORDER BY id"
    )
    _cached_sources = [dict(r) for r in (rows or [])]
    _cache_until = datetime.now() + timedelta(minutes=5)
    return _cached_sources


def get_all_kb_sources() -> list[dict]:
    """Return all rows (active + awaiting_source + deprecated) — no cache."""
    rows = solcon_db.fetchall(
        "SELECT * FROM solomon_kb_sources ORDER BY id"
    )
    return [dict(r) for r in (rows or [])]


def invalidate_cache():
    """Call after insert/update to solomon_kb_sources."""
    global _cache_until, _cached_sources
    _cache_until = None
    _cached_sources = None
