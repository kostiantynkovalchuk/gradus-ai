"""
Solomon Contracts — background analysis worker entry point.

This module owns analyze_one_document(), the pure sync function that scans
one document, generates alternatives, persists findings, and stamps
analysis_status='done'.  It has zero web-request dependency (no FastAPI
Request, no Depends, no asyncio event loop) so it can be called directly
from an APScheduler BackgroundScheduler thread.

Imports from: analyzer, citation_filter, db (all psycopg2 / sync).
Imported by:  router.py (re-export),  services/scheduler.py (analysis job).
"""
import concurrent.futures
import json
import logging

from . import db as solcon_db
from .analyzer import (
    _dedup_cross_section_findings,
    _remove_subsumed_findings,
    generate_alternatives,
    scan_document,
    split_into_sections,
)
from .citation_filter import filter_citations

logger = logging.getLogger(__name__)

FINDINGS_CAP = 45  # single dial: max findings kept per document


def analyze_one_document(doc: dict, eid: int):
    """
    Scan one document, generate alternatives, persist findings, and mark done.

    Args:
        doc: Row from solcon_documents as a plain dict (keys: id, raw_text,
             clauses, document_type, engagement_id, …).
        eid: Engagement ID (used for scope queries and logging).

    Returns:
        (findings_with_alts, total_rejected) — same shape as before the
        extraction so router.py callers remain compatible.

    Side-effects:
        • Inserts rows into solcon_findings and solcon_citation_filter_log.
        • Updates solcon_documents.analysis_status → 'done', analyzed_at=NOW().

    Does NOT handle the 'failed' transition — the caller (scheduler worker)
    is responsible for catching exceptions and stamping 'failed'.
    """
    raw_clauses = doc.get("clauses") or "[]"
    clauses = raw_clauses if isinstance(raw_clauses, list) else json.loads(raw_clauses)
    raw_text = doc.get("raw_text", "")
    doc_id = doc["id"]

    # ── Section-aware scan (parallel) ────────────────────────────────────────
    # The 5 section scans are fully independent: each receives immutable text +
    # clauses slices, produces its own result tuple, and uses psycopg2 via
    # solcon_db.conn() which opens a fresh connection per call (thread-safe).
    # Results are merged in the main thread after all futures resolve, so there
    # is zero shared mutable state during the concurrent phase.
    sections = split_into_sections(raw_text, clauses)

    def _scan_section(section: dict) -> tuple[list, int]:
        sec_findings, sec_rejected = scan_document(
            doc_id, eid,
            section["text"],
            section["clauses"],
        )
        logger.info(
            "[SolCon] Section %r → %d finding(s), %d rejected (doc=%d)",
            section["name"], len(sec_findings), sec_rejected, doc_id,
        )
        return sec_findings, sec_rejected

    all_findings: list[dict] = []
    total_rejected = 0
    # max_workers=5 matches the section count; executor is released immediately
    # after collect so threads don't linger into the alternatives phase.
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        section_results = list(executor.map(_scan_section, sections))

    for sec_findings, sec_rejected in section_results:
        all_findings.extend(sec_findings)
        total_rejected += sec_rejected

    # Post-merge cross-section range dedup
    all_findings = _remove_subsumed_findings(all_findings)
    all_findings = _dedup_cross_section_findings(all_findings)

    # ── Global cap ────────────────────────────────────────────────────────────
    # Selection is explicitly severity-aware:
    #   1. Keep ALL critical + high findings (never drop these for a medium/low).
    #   2. Fill remaining slots up to FINDINGS_CAP with top medium/low, ranked
    #      by confidence desc, verified-first.
    #   3. Edge case — critical+high alone exceed FINDINGS_CAP (e.g. a very dense
    #      contract): trim lowest-ranked ones within that group; a critical is
    #      never dropped while a high is kept.
    #   4. Belt-and-suspenders hard ceiling: never silently exceed FINDINGS_CAP.
    _HIGH_TIERS = {"critical", "high"}
    _SEV_RANK   = {"critical": 4, "high": 3, "medium": 2, "low": 1}

    def _cap_key(f):
        return (
            -_SEV_RANK.get(f.get("severity", ""), 0),
            -(float(f.get("confidence") or 0)),
            1 if f.get("clause_ref_unverified") else 0,
        )

    critical_high = sorted(
        (f for f in all_findings if f.get("severity") in _HIGH_TIERS),
        key=_cap_key,
    )
    medium_low = sorted(
        (f for f in all_findings if f.get("severity") not in _HIGH_TIERS),
        key=_cap_key,
    )

    total_before_cap = len(all_findings)
    if len(critical_high) >= FINDINGS_CAP:
        all_findings = critical_high[:FINDINGS_CAP]
    else:
        slots = FINDINGS_CAP - len(critical_high)
        all_findings = critical_high + medium_low[:slots]
    all_findings = all_findings[:FINDINGS_CAP]  # hard ceiling

    if len(all_findings) < total_before_cap:
        logger.info(
            "[SolCon] Cap applied: kept %d / %d findings (%d low-ranked dropped) doc=%d",
            len(all_findings), total_before_cap,
            total_before_cap - len(all_findings), doc_id,
        )

    findings_with_alts = generate_alternatives(doc_id, eid, all_findings)

    inserted_ids = []
    for f in findings_with_alts:
        raw_cit = f.get("legal_citations", "[]")
        try:
            raw_cit_list = json.loads(raw_cit) if isinstance(raw_cit, str) else (raw_cit or [])
        except (json.JSONDecodeError, TypeError):
            raw_cit_list = []
        filter_failed = False
        dropped: list = []
        kept = raw_cit_list
        grounding = f.get("grounding_status", "ungrounded")
        try:
            kept, dropped = filter_citations(raw_cit_list)
            if not kept and raw_cit_list:
                grounding = "out_of_approved_kb"
        except Exception as _cfe:
            filter_failed = True
            logger.exception(f"[CitFilter] Failed for doc {doc_id}: {_cfe}")
            kept, grounding = raw_cit_list, f.get("grounding_status", "ungrounded")

        result = solcon_db.fetchone(
            """INSERT INTO solcon_findings
                 (document_id, engagement_id, clause_ref, clause_text, category,
                  severity, monetary_exposure_uah, short_note, proposed_alternative,
                  grounding_status, legal_citations, workflow_state, detected_by, confidence,
                  citation_filter_failed, clause_ref_unverified)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (
                f["document_id"], f["engagement_id"], f["clause_ref"], f["clause_text"],
                f["category"], f["severity"], f.get("monetary_exposure_uah"),
                f["short_note"], f.get("proposed_alternative"),
                grounding,
                json.dumps(kept),
                f.get("workflow_state", "triage"), f["detected_by"],
                f.get("confidence"),
                filter_failed,
                f.get("clause_ref_unverified", False),
            ),
        )
        finding_id = result["id"]
        inserted_ids.append(finding_id)

        if dropped and not filter_failed:
            try:
                solcon_db.execute(
                    """INSERT INTO solcon_citation_filter_log
                         (finding_id, original_citations, filtered_citations, dropped_citations)
                       VALUES (%s, %s, %s, %s)""",
                    (
                        finding_id,
                        json.dumps(raw_cit_list),
                        json.dumps(kept),
                        json.dumps(dropped),
                    ),
                )
            except Exception as _log_e:
                logger.warning(f"[CitFilter] Log write failed for finding {finding_id}: {_log_e}")

    # Stamp 'done' — the authoritative signal that findings are complete.
    solcon_db.execute(
        """UPDATE solcon_documents
           SET analyzed_at=NOW(), analysis_status='done', updated_at=NOW()
           WHERE id=%s""",
        (doc_id,),
    )
    return findings_with_alts, total_rejected
