"""
Phase 5: Structured citation filter.
Validates legal_citations against the approved solomon_kb_sources registry.
Unauthorized citations are dropped before findings are persisted.
"""
import logging
import re
from typing import Optional

from . import db as solcon_db
from .kb_sources import get_active_kb_sources

logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """Strip /print1, /edYYYYMMDD suffixes and #fragment."""
    if not url:
        return ""
    url = re.sub(r"/print1.*$", "", url)
    url = re.sub(r"/ed\d{8}.*$", "", url)
    url = url.split("#")[0]
    return url.rstrip("/")


def filter_citations(citations: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Validate a list of citation dicts against the approved KB registry.

    Args:
        citations: list of {"article_ref": str, "official_url": str, "source_title": str}

    Returns:
        (kept, dropped) — both are lists of citation dicts.
        dropped items have an additional "reason" key.
    """
    approved_urls = {
        normalize_url(s["canonical_url"])
        for s in get_active_kb_sources()
        if s.get("canonical_url")
    }
    kept, dropped = [], []
    for cit in citations:
        raw_url = cit.get("official_url", "")
        if normalize_url(raw_url) in approved_urls:
            kept.append(cit)
        else:
            dropped.append({
                **cit,
                "reason": "Source not in approved KB registry",
            })
    return kept, dropped


def apply_citation_filter(
    finding_id: int,
    raw_citations: list[dict],
) -> tuple[list[dict], bool]:
    """
    Apply the citation filter to a finding's citations and log results.

    Returns:
        (final_citations, filter_failed)
        - final_citations: the citations to persist (may be empty)
        - filter_failed: True if an exception occurred (original citations preserved)

    Side effects:
        - Inserts a row into solcon_citation_filter_log if any citations were dropped.
    """
    import json
    try:
        kept, dropped = filter_citations(raw_citations)

        if dropped:
            try:
                solcon_db.execute(
                    """INSERT INTO solcon_citation_filter_log
                         (finding_id, original_citations, filtered_citations, dropped_citations)
                       VALUES (%s, %s, %s, %s)""",
                    (
                        finding_id,
                        json.dumps(raw_citations),
                        json.dumps(kept),
                        json.dumps(dropped),
                    ),
                )
            except Exception as log_err:
                logger.warning(f"[CitFilter] Failed to write filter log for finding {finding_id}: {log_err}")

        return kept, False

    except Exception as exc:
        logger.exception(f"[CitFilter] Citation filter raised for finding {finding_id}: {exc}")
        return raw_citations, True
