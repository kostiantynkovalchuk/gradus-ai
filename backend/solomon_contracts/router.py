"""
FastAPI router for Solomon Contracts.
All endpoints under /api/contracts/*
Auth: reuses existing Solomon session (solomon / gradus2026)
"""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from . import db as solcon_db
from .analyzer import generate_alternatives, generate_legal_opinion, scan_document
from .artifacts import build_opinion_docx, build_protocol_docx, build_risk_note_docx
from .corpus import ingest_incoterms_pdf, ingest_incoterms_summary, ingest_law_text, rebuild_corpus_namespace, run_sanity_queries
from .kb_sources import get_active_kb_sources, invalidate_cache as _invalidate_kb_cache
from .citation_filter import filter_citations
import threading
from pathlib import Path as _Path
from .ingestion import ingest_file, process_zip, run_background_ocr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contracts", tags=["solomon-contracts"])

SOLOMON_USER = "solomon"
SOLOMON_PASS = "gradus2026"

# Approved KB source list is now managed via solomon_kb_sources DB table.
# Use get_active_kb_sources() from kb_sources.py — 5-minute cached helper.


# ─── Auth ─────────────────────────────────────────────────────────────────────
import base64

def _auth_check(request: Request) -> str:
    """
    Reuses the existing Solomon credential pair (solomon / gradus2026).
    Accepted via:
      1. Cookie:  solcon_auth=<base64(user:pass)>
      2. Header:  Authorization: Basic <base64(user:pass)>
      3. Dev bypass: SOLCON_AUTH_BYPASS env var set to 'true'
    """
    if os.getenv("SOLCON_AUTH_BYPASS") == "true":
        return SOLOMON_USER

    _VALID = base64.b64encode(f"{SOLOMON_USER}:{SOLOMON_PASS}".encode()).decode()

    cookie_val = request.cookies.get("solcon_auth", "")
    if cookie_val == _VALID:
        return SOLOMON_USER

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        if auth_header[6:] == _VALID:
            return SOLOMON_USER

    raise HTTPException(status_code=401, detail="Unauthorized")


# ─── Engagement CRUD ──────────────────────────────────────────────────────────

class EngagementCreate(BaseModel):
    name: str
    counterparty_name: Optional[str] = None
    our_entity: Optional[str] = "AVTD"
    buyer_profile_id: Optional[int] = None
    engagement_date: Optional[str] = None


class EngagementPatch(BaseModel):
    avtd_role: Optional[str] = None  # 'supplier' | 'buyer'


@router.get("/engagements")
async def list_engagements(request: Request):
    _auth_check(request)
    rows = solcon_db.fetchall(
        """SELECT e.id, e.name, e.counterparty_name, e.our_entity, e.status,
                  e.created_at, e.engagement_date,
                  COUNT(DISTINCT d.id) as doc_count,
                  COUNT(DISTINCT f.id) as finding_count
           FROM solcon_engagements e
           LEFT JOIN solcon_documents d ON d.engagement_id = e.id
           LEFT JOIN solcon_findings f ON f.engagement_id = e.id
           GROUP BY e.id
           ORDER BY e.created_at DESC"""
    )
    return [dict(r) for r in (rows or [])]


@router.post("/engagements", status_code=201)
async def create_engagement(request: Request, body: EngagementCreate):
    _auth_check(request)
    result = solcon_db.fetchone(
        """INSERT INTO solcon_engagements
             (name, counterparty_name, our_entity, buyer_profile_id, engagement_date, created_by)
           VALUES (%s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (body.name, body.counterparty_name, body.our_entity,
         body.buyer_profile_id, body.engagement_date, SOLOMON_USER),
    )
    return {"id": result["id"], "name": body.name}


@router.get("/engagements/{eid}")
async def get_engagement(request: Request, eid: int):
    _auth_check(request)
    eng = solcon_db.fetchone(
        "SELECT * FROM solcon_engagements WHERE id = %s", (eid,)
    )
    if not eng:
        raise HTTPException(status_code=404, detail="Engagement not found")
    docs = solcon_db.fetchall(
        "SELECT id, original_filename, document_type, analyzed_at, created_at, "
        "COALESCE(LENGTH(raw_text), 0) AS raw_chars, extraction_method, "
        "ocr_status, COALESCE(ocr_current_page,0) AS ocr_current_page, "
        "COALESCE(ocr_total_pages,0) AS ocr_total_pages "
        "FROM solcon_documents WHERE engagement_id = %s ORDER BY created_at",
        (eid,),
    )
    findings = solcon_db.fetchall(
        """SELECT f.*, d.original_filename as doc_name
           FROM solcon_findings f
           JOIN solcon_documents d ON d.id = f.document_id
           WHERE f.engagement_id = %s
           ORDER BY f.severity DESC, f.clause_ref""",
        (eid,),
    )
    sev_summary = {}
    for f in (findings or []):
        sev_summary[f["severity"]] = sev_summary.get(f["severity"], 0) + 1

    latest_op = solcon_db.fetchone(
        "SELECT version, content_md, generated_at FROM solcon_legal_opinions "
        "WHERE engagement_id=%s ORDER BY version DESC LIMIT 1",
        (eid,),
    )
    return {
        "engagement": dict(eng),
        "documents": [dict(d) for d in (docs or [])],
        "findings": [dict(f) for f in (findings or [])],
        "severity_summary": sev_summary,
        "latest_opinion": dict(latest_op) if latest_op else None,
    }


@router.patch("/engagements/{eid}/status")
async def update_engagement_status(request: Request, eid: int):
    _auth_check(request)
    body = await request.json()
    status = body.get("status")
    valid = {
        "triage", "under_review", "protocol_drafted", "protocol_sent",
        "counterparty_responded", "agreed", "declined", "archived",
    }
    if status not in valid:
        raise HTTPException(status_code=400, detail="Invalid status")
    solcon_db.execute(
        "UPDATE solcon_engagements SET status=%s, updated_at=NOW() WHERE id=%s",
        (status, eid),
    )
    return {"ok": True}


@router.patch("/engagements/{eid}")
async def patch_engagement(request: Request, eid: int, body: EngagementPatch):
    """Update engagement fields. Currently supports: avtd_role ('supplier' | 'buyer')."""
    _auth_check(request)
    eng = solcon_db.fetchone("SELECT id FROM solcon_engagements WHERE id=%s", (eid,))
    if not eng:
        raise HTTPException(status_code=404, detail="Engagement not found")

    updates = []
    params = []

    if body.avtd_role is not None:
        if body.avtd_role not in ("supplier", "buyer"):
            raise HTTPException(
                status_code=400,
                detail="avtd_role must be 'supplier' or 'buyer'",
            )
        updates.append("avtd_role=%s")
        params.append(body.avtd_role)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at=NOW()")
    params.append(eid)
    solcon_db.execute(
        f"UPDATE solcon_engagements SET {', '.join(updates)} WHERE id=%s",
        tuple(params),
    )
    return {"ok": True}


# ─── Document upload & ingestion ──────────────────────────────────────────────

@router.post("/engagements/{eid}/upload", status_code=201)
async def upload_document(
    request: Request,
    eid: int,
    file: UploadFile = File(...),
    appendix_prefix: str = Form(""),
):
    _auth_check(request)
    eng = solcon_db.fetchone("SELECT id FROM solcon_engagements WHERE id=%s", (eid,))
    if not eng:
        raise HTTPException(status_code=404, detail="Engagement not found")

    data = await file.read()
    filename = file.filename or "upload"
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    created_ids = []

    if suffix == "zip":
        files = process_zip(data, eid)
        for f in files:
            f_data = f["path"].read_bytes()
            doc_dict = ingest_file(f["filename"], f_data, eid, appendix_prefix)
            doc_id = _save_document(eid, doc_dict)
            created_ids.append(doc_id)
            if doc_dict.get("_ocr_pending"):
                run_background_ocr(doc_id, _Path(doc_dict["storage_path"]))
    else:
        doc_dict = ingest_file(filename, data, eid, appendix_prefix)
        doc_id = _save_document(eid, doc_dict)
        created_ids.append(doc_id)
        if doc_dict.get("_ocr_pending"):
            run_background_ocr(doc_id, _Path(doc_dict["storage_path"]))

    return {"created": created_ids}


def _save_document(eid: int, doc_dict: dict) -> int:
    result = solcon_db.fetchone(
        """INSERT INTO solcon_documents
             (engagement_id, document_type, original_filename, mime_type,
              storage_path, raw_text, clauses, extraction_method, ocr_status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (
            eid,
            doc_dict["document_type"],
            doc_dict["original_filename"],
            doc_dict["mime_type"],
            doc_dict["storage_path"],
            doc_dict["raw_text"],
            doc_dict["clauses"],
            doc_dict.get("extraction_method"),
            doc_dict.get("ocr_status"),
        ),
    )
    return result["id"]


# ─── Analysis ────────────────────────────────────────────────────────────────

@router.post("/engagements/{eid}/analyze")
async def analyze_engagement(request: Request, eid: int):
    """
    Trigger full analysis of all unanalyzed documents in the engagement.
    Long-running — returns immediately with a task ID.
    Actual work runs in background via asyncio.
    """
    _auth_check(request)
    eng = solcon_db.fetchone("SELECT * FROM solcon_engagements WHERE id=%s", (eid,))
    if not eng:
        raise HTTPException(status_code=404, detail="Engagement not found")

    docs = solcon_db.fetchall(
        """SELECT * FROM solcon_documents
           WHERE engagement_id = %s AND analyzed_at IS NULL
             AND document_type IN ('main_contract','additional_agreement')
           ORDER BY created_at""",
        (eid,),
    )
    if not docs:
        return {"message": "No documents to analyze", "analyzed": 0}

    solcon_db.execute(
        "UPDATE solcon_engagements SET status='under_review', updated_at=NOW() WHERE id=%s",
        (eid,),
    )

    asyncio.create_task(_run_analysis(eid, [dict(d) for d in docs]))
    return {"message": "Analysis started", "document_count": len(docs)}


async def _run_analysis(eid: int, docs: list[dict]):
    loop = asyncio.get_event_loop()
    total_findings = 0
    any_success = False
    for doc in docs:
        try:
            findings, rejected = await loop.run_in_executor(
                None, _analyze_one_document, doc, eid
            )
            total_findings += len(findings)
            any_success = True
        except Exception as e:
            logger.exception(f"[SolCon] Analysis failed for doc {doc['id']}: {e}")
    if not any_success:
        try:
            solcon_db.execute(
                "UPDATE solcon_engagements SET status='analysis_failed', updated_at=NOW() WHERE id=%s",
                (eid,),
            )
        except Exception:
            pass
    logger.info(f"[SolCon] Analysis complete for eng={eid}, total findings={total_findings}")


def _analyze_one_document(doc: dict, eid: int):
    raw_clauses = doc.get("clauses") or "[]"
    clauses = raw_clauses if isinstance(raw_clauses, list) else json.loads(raw_clauses)
    raw_text = doc.get("raw_text", "")
    doc_id = doc["id"]

    findings_dicts, rejected = scan_document(doc_id, eid, raw_text, clauses)
    findings_with_alts = generate_alternatives(doc_id, eid, findings_dicts)

    inserted_ids = []
    for f in findings_with_alts:
        # Phase 5: apply citation filter before persisting
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
                  citation_filter_failed)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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

    solcon_db.execute(
        "UPDATE solcon_documents SET analyzed_at=NOW(), updated_at=NOW() WHERE id=%s",
        (doc_id,),
    )
    return findings_with_alts, rejected


# ─── Findings management ──────────────────────────────────────────────────────

@router.patch("/findings/{fid}/state")
async def update_finding_state(request: Request, fid: int):
    _auth_check(request)
    body = await request.json()
    state = body.get("workflow_state")
    valid = {
        "triage", "included_in_protocol", "excluded", "sent_to_counterparty",
        "counterparty_accepted", "counterparty_rejected", "counterparty_modified", "agreed",
    }
    if state not in valid:
        raise HTTPException(status_code=400, detail="Invalid workflow_state")
    lawyer_notes = body.get("lawyer_notes")
    solcon_db.execute(
        """UPDATE solcon_findings
           SET workflow_state=%s, lawyer_notes=COALESCE(%s, lawyer_notes), updated_at=NOW()
           WHERE id=%s""",
        (state, lawyer_notes, fid),
    )
    return {"ok": True}


@router.patch("/findings/{fid}/judgment")
async def update_finding_judgment(request: Request, fid: int):
    """Quality tracking: lawyer verdict on a detected finding."""
    _auth_check(request)
    body = await request.json()
    judgment = body.get("lawyer_judgment")
    valid = {"accepted", "rejected", "modified_minor", "modified_major", "not_reviewed"}
    if judgment not in valid:
        raise HTTPException(status_code=400, detail="Invalid lawyer_judgment")
    solcon_db.execute(
        "UPDATE solcon_findings SET lawyer_judgment=%s, updated_at=NOW() WHERE id=%s",
        (judgment, fid),
    )
    return {"ok": True}


@router.post("/findings/{fid}/judge")
async def judge_finding(request: Request, fid: int):
    """Eval harness: record lawyer judgment on a finding."""
    _auth_check(request)
    body = await request.json()
    judgment = body.get("judgment")
    valid = {"true_positive", "false_positive", "wrong_category", "wrong_severity"}
    if judgment not in valid:
        raise HTTPException(status_code=400, detail="Invalid judgment")
    solcon_db.execute(
        """INSERT INTO solcon_eval_judgments (finding_id, judgment, judged_by, notes)
           VALUES (%s,%s,%s,%s)
           ON CONFLICT DO NOTHING""",
        (fid, judgment, SOLOMON_USER, body.get("notes")),
    )
    return {"ok": True}


# ─── Artifact generation ──────────────────────────────────────────────────────

@router.get("/engagements/{eid}/risk-note.docx")
async def download_risk_note(request: Request, eid: int):
    _auth_check(request)
    eng = solcon_db.fetchone("SELECT * FROM solcon_engagements WHERE id=%s", (eid,))
    if not eng:
        raise HTTPException(status_code=404, detail="Not found")
    docs = solcon_db.fetchall(
        "SELECT * FROM solcon_documents WHERE engagement_id=%s", (eid,)
    )
    findings = solcon_db.fetchall(
        "SELECT * FROM solcon_findings WHERE engagement_id=%s ORDER BY severity DESC",
        (eid,),
    )
    docx_bytes = build_risk_note_docx(
        eng["name"],
        eng["counterparty_name"] or "—",
        [dict(d) for d in (docs or [])],
        [dict(f) for f in (findings or [])],
    )
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="risks_{eid}.docx"'},
    )


@router.post("/engagements/{eid}/documents/{did}/re-extract")
async def re_extract_document(request: Request, eid: int, did: int):
    """Re-run text extraction + clause parsing on the stored file.
    Clears analyzed_at so the document can be re-analyzed afterwards.
    Returns 409 if the file is no longer on disk (re-upload required).
    """
    _auth_check(request)
    doc = solcon_db.fetchone(
        "SELECT * FROM solcon_documents WHERE id=%s AND engagement_id=%s", (did, eid)
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    from pathlib import Path as _Path
    from .ingestion import extract_text, parse_clauses, scan_all_refs
    import json as _json

    path = _Path(doc["storage_path"])
    if not path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"File not on disk: {path.name}. Please re-upload the document.",
        )

    raw_text, extraction_method = extract_text(path, doc["mime_type"] or "")

    if extraction_method == "ocr:pending":
        # Scanned PDF — reset to pending state and launch background OCR
        solcon_db.execute(
            """UPDATE solcon_documents
               SET raw_text='', clauses='[]'::jsonb, extraction_method=NULL,
                   ocr_status='pending', ocr_current_page=0, ocr_total_pages=0,
                   analyzed_at=NULL, updated_at=NOW()
               WHERE id=%s""",
            (did,),
        )
        run_background_ocr(did, path)
        return {"ok": True, "async": True, "method": "ocr:pending"}

    clauses = parse_clauses(raw_text)
    if not clauses:
        clauses = scan_all_refs(raw_text)

    solcon_db.execute(
        """UPDATE solcon_documents
           SET raw_text=%s, clauses=%s::jsonb, extraction_method=%s,
               ocr_status=NULL, ocr_current_page=0, analyzed_at=NULL, updated_at=NOW()
           WHERE id=%s""",
        (raw_text, _json.dumps(clauses), extraction_method, did),
    )
    return {"ok": True, "chars": len(raw_text), "clauses": len(clauses), "method": extraction_method}


@router.get("/engagements/{eid}/documents/{did}/ocr-status")
async def get_ocr_status(request: Request, eid: int, did: int):
    """Poll endpoint for background OCR progress. Called every 3 s by the frontend."""
    _auth_check(request)
    doc = solcon_db.fetchone(
        """SELECT ocr_status,
                  COALESCE(ocr_current_page, 0) AS ocr_current_page,
                  COALESCE(ocr_total_pages,  0) AS ocr_total_pages,
                  COALESCE(LENGTH(raw_text),  0) AS chars
           FROM solcon_documents WHERE id=%s AND engagement_id=%s""",
        (did, eid),
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return dict(doc)


@router.delete("/engagements/{eid}/documents/{did}")
async def delete_document(request: Request, eid: int, did: int):
    """Delete a document record (and its file + findings) from an engagement."""
    _auth_check(request)
    doc = solcon_db.fetchone(
        "SELECT * FROM solcon_documents WHERE id=%s AND engagement_id=%s", (did, eid)
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove file from disk if it exists
    from pathlib import Path as _Path
    path = _Path(doc["storage_path"])
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass

    # Cascade: delete findings and then the document
    solcon_db.execute("DELETE FROM solcon_findings WHERE document_id=%s", (did,))
    solcon_db.execute("DELETE FROM solcon_documents WHERE id=%s", (did,))
    return {"ok": True}


@router.patch("/engagements/{eid}/documents/{did}/type")
async def patch_document_type(request: Request, eid: int, did: int):
    _auth_check(request)
    from .ingestion import VALID_DOC_TYPES
    body = await request.json()
    new_type = (body.get("document_type") or "").strip()
    if new_type not in VALID_DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid document_type: {new_type}")
    solcon_db.execute(
        "UPDATE solcon_documents SET document_type=%s WHERE id=%s AND engagement_id=%s",
        (new_type, did, eid),
    )
    return {"ok": True, "document_type": new_type}


@router.post("/engagements/{eid}/documents/{did}/protocol")
async def generate_protocol(request: Request, eid: int, did: int):
    _auth_check(request)
    eng = solcon_db.fetchone("SELECT * FROM solcon_engagements WHERE id=%s", (eid,))
    findings = solcon_db.fetchall(
        """SELECT * FROM solcon_findings
           WHERE document_id=%s AND workflow_state='included_in_protocol'
           ORDER BY clause_ref""",
        (did,),
    )
    if not findings:
        raise HTTPException(status_code=400, detail="No findings included in protocol")

    doc_record = solcon_db.fetchone(
        "SELECT original_filename FROM solcon_documents WHERE id=%s", (did,)
    )
    original_filename = (doc_record["original_filename"] if doc_record else None) or f"doc{did}"

    avtd_role = eng.get("avtd_role")
    if not avtd_role:
        raise HTTPException(
            status_code=400,
            detail=(
                "Set AVTD role on engagement before exporting protocol. "
                "Use PATCH /api/contracts/engagements/{eid} with "
                "{\"avtd_role\": \"supplier\" or \"buyer\"}."
            ),
        )

    finding_ids = [f["id"] for f in findings]
    docx_bytes = build_protocol_docx(
        eng["name"],
        eng["counterparty_name"] or "—",
        [dict(f) for f in findings],
        document_filename=original_filename,
        avtd_role=avtd_role,
    )

    from pathlib import Path
    from urllib.parse import quote
    from .ingestion import UPLOAD_DIR
    proto_dir = UPLOAD_DIR / str(eid) / "protocols"
    proto_dir.mkdir(parents=True, exist_ok=True)

    existing = solcon_db.fetchone(
        "SELECT COALESCE(MAX(version),0) as mv FROM solcon_protocols WHERE document_id=%s", (did,)
    )
    version = (existing["mv"] or 0) + 1
    proto_path = proto_dir / f"protocol_doc{did}_v{version}.docx"
    proto_path.write_bytes(docx_bytes)

    solcon_db.execute(
        """INSERT INTO solcon_protocols
             (document_id, engagement_id, version, finding_ids, docx_storage_path, generated_by)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (document_id, version) DO UPDATE
             SET docx_storage_path=EXCLUDED.docx_storage_path""",
        (did, eid, version, json.dumps(finding_ids), str(proto_path), SOLOMON_USER),
    )
    solcon_db.execute(
        "UPDATE solcon_findings SET workflow_state='sent_to_counterparty' WHERE id=ANY(%s)",
        (finding_ids,),
    )
    solcon_db.execute(
        "UPDATE solcon_engagements SET status='protocol_drafted', updated_at=NOW() WHERE id=%s",
        (eid,),
    )

    # RFC 5987 filename: «Протокол розбіжностей — {source_filename}.docx»
    doc_stem = Path(original_filename).stem[:60]
    dl_name = f"Протокол розбіжностей — {doc_stem}.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(dl_name)}"},
    )


@router.post("/engagements/{eid}/legal-opinion")
async def generate_opinion(request: Request, eid: int):
    _auth_check(request)
    eng = solcon_db.fetchone("SELECT * FROM solcon_engagements WHERE id=%s", (eid,))
    if not eng:
        raise HTTPException(status_code=404, detail="Not found")
    docs = solcon_db.fetchall(
        "SELECT * FROM solcon_documents WHERE engagement_id=%s", (eid,)
    )
    findings = solcon_db.fetchall(
        """SELECT f.*, d.original_filename as doc_name
           FROM solcon_findings f
           JOIN solcon_documents d ON d.id = f.document_id
           WHERE f.engagement_id=%s ORDER BY f.severity DESC""",
        (eid,),
    )
    findings_list = [dict(f) for f in (findings or [])]
    loop = asyncio.get_event_loop()
    md_text = await loop.run_in_executor(
        None,
        generate_legal_opinion,
        eid,
        eng["counterparty_name"] or "—",
        [dict(d) for d in (docs or [])],
        findings_list,
    )

    existing = solcon_db.fetchone(
        "SELECT COALESCE(MAX(version),0) as mv FROM solcon_legal_opinions WHERE engagement_id=%s",
        (eid,),
    )
    version = (existing["mv"] or 0) + 1

    from .ingestion import UPLOAD_DIR
    op_dir = UPLOAD_DIR / str(eid) / "opinions"
    op_dir.mkdir(parents=True, exist_ok=True)
    docx_bytes = build_opinion_docx(md_text, eng["name"], findings=findings_list)
    op_path = op_dir / f"opinion_v{version}.docx"
    op_path.write_bytes(docx_bytes)

    solcon_db.execute(
        """INSERT INTO solcon_legal_opinions
             (engagement_id, version, content_md, docx_storage_path, generated_by)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (engagement_id, version) DO UPDATE
             SET content_md=EXCLUDED.content_md""",
        (eid, version, md_text, str(op_path), SOLOMON_USER),
    )
    return {"markdown": md_text, "version": version}


@router.get("/engagements/{eid}/legal-opinion/{version}.docx")
async def download_opinion(request: Request, eid: int, version: int):
    _auth_check(request)
    rec = solcon_db.fetchone(
        "SELECT docx_storage_path FROM solcon_legal_opinions WHERE engagement_id=%s AND version=%s",
        (eid, version),
    )
    if not rec or not rec["docx_storage_path"]:
        raise HTTPException(status_code=404, detail="Opinion not found")
    data = open(rec["docx_storage_path"], "rb").read()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="opinion_{eid}_v{version}.docx"'},
    )


# ─── Buyer profiles ───────────────────────────────────────────────────────────

@router.get("/buyers")
async def list_buyers(request: Request):
    _auth_check(request)
    rows = solcon_db.fetchall(
        "SELECT id, buyer_name, legal_entity, edrpou, notes, created_at "
        "FROM solcon_buyer_profiles ORDER BY buyer_name"
    )
    return [dict(r) for r in (rows or [])]


class BuyerCreate(BaseModel):
    buyer_name: str
    legal_entity: Optional[str] = None
    edrpou: Optional[str] = None
    notes: Optional[str] = None


@router.post("/buyers", status_code=201)
async def create_buyer(request: Request, body: BuyerCreate):
    _auth_check(request)
    result = solcon_db.fetchone(
        """INSERT INTO solcon_buyer_profiles (buyer_name, legal_entity, edrpou, notes)
           VALUES (%s,%s,%s,%s) RETURNING id""",
        (body.buyer_name, body.legal_entity, body.edrpou, body.notes),
    )
    return {"id": result["id"]}


# ─── Corpus admin: background job registry ────────────────────────────────────
# Per §4.1: all corpus operations run as background jobs → 202 + job_id.
# In-memory dict is sufficient — these are ephemeral admin ops on a
# single-server Render deployment.
_corpus_jobs: dict[str, dict] = {}


def _new_job(op: str) -> str:
    job_id = uuid.uuid4().hex[:10]
    _corpus_jobs[job_id] = {
        "job_id": job_id,
        "op": op,
        "status": "queued",
        "progress": [],
        "result": None,
        "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    return job_id


def _job_progress(job_id: str, msg: str):
    if job_id in _corpus_jobs:
        _corpus_jobs[job_id]["progress"].append(msg)
        logger.info(f"[CorpusJob {job_id}] {msg}")


def _job_done(job_id: str, result: dict):
    if job_id in _corpus_jobs:
        _corpus_jobs[job_id]["status"] = "done"
        _corpus_jobs[job_id]["result"] = result
        _corpus_jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


def _job_error(job_id: str, error: str):
    if job_id in _corpus_jobs:
        _corpus_jobs[job_id]["status"] = "error"
        _corpus_jobs[job_id]["error"] = error
        _corpus_jobs[job_id]["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.get("/admin/corpus/jobs/{job_id}")
async def get_corpus_job(request: Request, job_id: str):
    """Poll the status of a background corpus job."""
    _auth_check(request)
    job = _corpus_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ─── Corpus admin: endpoints (202 + job_id) ───────────────────────────────────

@router.post("/admin/corpus/seed-sources", status_code=202)
async def seed_corpus_sources(request: Request):
    """
    Seed all 15 Ukrainian law sources (§8.1) into solcon_corpus_sources.
    Idempotent. Returns 202 + job_id; poll GET …/jobs/{id}.
    """
    _auth_check(request)
    job_id = _new_job("seed-sources")

    async def _run():
        _corpus_jobs[job_id]["status"] = "running"
        try:
            inserted = 0
            skipped = 0
            active_sources = get_active_kb_sources()
            for src in active_sources:
                existing = solcon_db.fetchone(
                    "SELECT id FROM solcon_corpus_sources WHERE official_url=%s",
                    (src["canonical_url"],),
                )
                if not existing:
                    solcon_db.execute(
                        """INSERT INTO solcon_corpus_sources (source_type, title, official_url)
                           VALUES ('ukr_law', %s, %s)""",
                        (src["law_name"], src["canonical_url"]),
                    )
                    inserted += 1
                    _job_progress(job_id, f"Inserted: {src['law_name']}")
                else:
                    skipped += 1
            _job_done(job_id, {"inserted": inserted, "skipped": skipped, "total": len(active_sources)})
        except Exception as exc:
            _job_error(job_id, str(exc))

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "queued"}


@router.post("/admin/corpus/rebuild", status_code=202)
async def rebuild_corpus(request: Request):
    """
    Re-fetch all 15 laws from zakon.rada.gov.ua, re-chunk, re-embed, upsert to
    Pinecone. Clears the namespace first (idempotent). Runs sanity queries after.
    Returns 202 + job_id; poll GET …/jobs/{id}.
    """
    _auth_check(request)
    job_id = _new_job("rebuild")

    def _progress(msg: str):
        _job_progress(job_id, msg)

    def _do_rebuild():
        _corpus_jobs[job_id]["status"] = "running"
        try:
            # Build filter lookup keyed by both URL and name.
            # New registry has no article_filter — Phase 4 ingests all articles.
            law_filters: dict = {}
            for src in get_active_kb_sources():
                entry = {"article_filter": None, "sub_article_filter": None}
                law_filters[src["canonical_url"]] = entry
                law_filters[src["law_name"]] = entry
            total = rebuild_corpus_namespace(on_progress=_progress, law_filters=law_filters)
            _job_progress(job_id, f"Rebuild complete — {total} chunks ingested. Running sanity queries…")
            sanity = run_sanity_queries()
            _job_done(job_id, {
                "chunks_ingested": total,
                "sanity": sanity,
                "sanity_ok": sanity.get("_summary", {}).get("ok", False),
            })
        except Exception as exc:
            _job_error(job_id, str(exc))

    async def _async_rebuild():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_rebuild)

    asyncio.create_task(_async_rebuild())
    return {"job_id": job_id, "status": "queued"}


@router.post("/admin/corpus/incoterms", status_code=202)
async def upload_incoterms(request: Request, file: UploadFile = File(None)):
    """
    INCOTERMS 2020 ingestion — three-tier fallback per §3.4:
      Tier 1 (PDF):  upload a .pdf file → pdfplumber extraction + chunk + embed
      Tier 2 (text): upload a .txt file → plain-text chunk + embed
      Tier 3 (defer): no file → mark source as 'pending' in DB, skip embedding
    Returns 202 + job_id; poll GET …/jobs/{id}.
    """
    _auth_check(request)

    # Determine tier before reading the file
    if file and file.filename:
        fname = file.filename.lower()
        if fname.endswith(".pdf"):
            tier = "pdf"
        elif fname.endswith(".txt"):
            tier = "txt"
        else:
            raise HTTPException(status_code=400, detail="Upload a .pdf or .txt file, or omit file to defer.")
        data = await file.read()
    else:
        tier = "defer"
        data = b""

    job_id = _new_job(f"incoterms-{tier}")

    def _ensure_source() -> int:
        existing = solcon_db.fetchone(
            "SELECT id FROM solcon_corpus_sources WHERE source_type='incoterms_2020'"
        )
        if existing:
            return existing["id"]
        row = solcon_db.fetchone(
            """INSERT INTO solcon_corpus_sources (source_type, title, official_url)
               VALUES ('incoterms_2020', 'INCOTERMS 2020', '')
               RETURNING id"""
        )
        return row["id"]

    def _do_incoterms():
        _corpus_jobs[job_id]["status"] = "running"
        try:
            source_id = _ensure_source()
            if tier == "pdf":
                _job_progress(job_id, "Tier 1: parsing PDF with pdfplumber…")
                count = ingest_incoterms_pdf(source_id, data)
                solcon_db.execute(
                    "UPDATE solcon_corpus_sources SET chunk_count=%s, last_ingested_at=NOW() WHERE id=%s",
                    (count, source_id),
                )
                _job_done(job_id, {"tier": "pdf", "chunks_ingested": count, "source_id": source_id})

            elif tier == "txt":
                _job_progress(job_id, "Tier 2: ingesting plain text…")
                from .corpus import _chunk_incoterms, _embed, _pinecone_index, CORPUS_NS
                import re
                text = data.decode("utf-8", errors="replace")
                chunks = _chunk_incoterms(text)
                idx = _pinecone_index()
                rules = ["EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF"]
                vectors = []
                for i, chunk in enumerate(chunks):
                    rule_match = next((r for r in rules if re.search(rf"\b{r}\b", chunk[:50])), None)
                    article_ref = f"INCOTERMS {rule_match}" if rule_match else f"INCOTERMS chunk_{i}"
                    vec = _embed(chunk)
                    vectors.append({
                        "id": f"incoterms_{source_id}_{i}",
                        "values": vec,
                        "metadata": {
                            "source_id": source_id,
                            "source_type": "incoterms_2020",
                            "source_title": "INCOTERMS 2020",
                            "article_ref": article_ref,
                            "official_url": "",
                            "chunk_text": chunk[:1000],
                        },
                    })
                    if len(vectors) >= 50:
                        idx.upsert(vectors=vectors, namespace=CORPUS_NS)
                        vectors = []
                if vectors:
                    idx.upsert(vectors=vectors, namespace=CORPUS_NS)
                count = len(chunks)
                solcon_db.execute(
                    "UPDATE solcon_corpus_sources SET chunk_count=%s, last_ingested_at=NOW() WHERE id=%s",
                    (count, source_id),
                )
                _job_done(job_id, {"tier": "txt", "chunks_ingested": count, "source_id": source_id})

            else:
                # Tier 3: defer — mark source as present but not yet ingested
                _job_progress(job_id, "Tier 3: deferring INCOTERMS — marked pending in DB.")
                solcon_db.execute(
                    "UPDATE solcon_corpus_sources SET last_ingested_at=NULL WHERE id=%s",
                    (source_id,),
                )
                _job_done(job_id, {"tier": "defer", "chunks_ingested": 0, "source_id": source_id,
                                   "note": "INCOTERMS not yet ingested — upload PDF or TXT to complete."})

        except Exception as exc:
            _job_error(job_id, str(exc))

    async def _async_incoterms():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_incoterms)

    asyncio.create_task(_async_incoterms())
    return {"job_id": job_id, "status": "queued"}


@router.post("/admin/corpus/incoterms-summary", status_code=202)
async def ingest_incoterms_summary_endpoint(request: Request):
    """
    Ingest the HDI Global SE INCOTERMS 2020 summary card.

    source_type = 'incoterms_2020_summary'
    12 structured chunks (one per rule, FCA has two place-variants).
    Metadata includes rule_code and transport_mode (any_mode | sea_only).

    This source covers risk-transfer points and mode-of-transport selection ONLY.
    It does NOT include A1-A10/B1-B10 obligation text.
    Citations generated by Solomon from this source will read:
      "per INCOTERMS 2020 summary (HDI Global SE). Full rule text should be consulted
       before adoption."

    Returns 202 + job_id; poll GET …/jobs/{id}.
    """
    _auth_check(request)

    PROVENANCE = (
        "HDI Global SE summary card. Covers rule codes, risk transfer points, and "
        "mode-of-transport selection. Does NOT include A1-A10/B1-B10 obligation text. "
        "Upgrade to primary ICC source when available."
    )

    job_id = _new_job("incoterms-summary")

    def _ensure_source() -> int:
        existing = solcon_db.fetchone(
            "SELECT id FROM solcon_corpus_sources WHERE source_type='incoterms_2020_summary'"
        )
        if existing:
            # Refresh provenance_note in case it was updated
            solcon_db.execute(
                "UPDATE solcon_corpus_sources SET provenance_note=%s WHERE id=%s",
                (PROVENANCE, existing["id"]),
            )
            return existing["id"]
        row = solcon_db.fetchone(
            """INSERT INTO solcon_corpus_sources
               (source_type, title, official_url, provenance_note)
               VALUES ('incoterms_2020_summary',
                       'INCOTERMS 2020 — Summary (HDI Global SE)',
                       NULL, %s)
               RETURNING id""",
            (PROVENANCE,),
        )
        return row["id"]

    def _do_summary():
        _corpus_jobs[job_id]["status"] = "running"
        try:
            source_id = _ensure_source()
            _job_progress(job_id, "Ingesting INCOTERMS 2020 summary (12 rule chunks)…")
            count = ingest_incoterms_summary(source_id)
            solcon_db.execute(
                "UPDATE solcon_corpus_sources SET chunk_count=%s, last_ingested_at=NOW() WHERE id=%s",
                (count, source_id),
            )
            _job_done(job_id, {
                "chunks_ingested": count,
                "source_id": source_id,
                "source_type": "incoterms_2020_summary",
                "note": (
                    "12 rule chunks upserted. Covers EXW/FCA×2/FAS/FOB/CFR/CIF/CPT/CIP/DAP/DPU/DDP. "
                    "Does not include A1-A10/B1-B10 obligation text."
                ),
            })
        except Exception as exc:
            _job_error(job_id, str(exc))

    async def _async_summary():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_summary)

    asyncio.create_task(_async_summary())
    return {"job_id": job_id, "status": "queued"}


# ─── Audit & eval ─────────────────────────────────────────────────────────────

@router.get("/admin/audit")
async def get_audit(request: Request, limit: int = 100):
    _auth_check(request)
    rows = solcon_db.fetchall(
        """SELECT * FROM solcon_llm_audit
           ORDER BY created_at DESC LIMIT %s""",
        (limit,),
    )
    total = solcon_db.fetchone("SELECT COUNT(*) as n FROM solcon_llm_audit")
    rejected = solcon_db.fetchone(
        "SELECT COUNT(*) as n FROM solcon_llm_audit WHERE result_status != 'ok'"
    )
    return {
        "total_calls": total["n"] if total else 0,
        "rejected_count": rejected["n"] if rejected else 0,
        "recent": [dict(r) for r in (rows or [])],
    }


@router.get("/admin/eval")
async def get_eval(request: Request):
    _auth_check(request)
    judgments = solcon_db.fetchall(
        """SELECT ej.*, f.clause_ref, f.category, f.severity, f.short_note
           FROM solcon_eval_judgments ej
           JOIN solcon_findings f ON f.id = ej.finding_id
           ORDER BY ej.created_at DESC"""
    )
    counts = {}
    for j in (judgments or []):
        counts[j["judgment"]] = counts.get(j["judgment"], 0) + 1
    tp = counts.get("true_positive", 0)
    fp = counts.get("false_positive", 0)
    total = tp + fp
    precision = tp / total if total > 0 else None
    return {
        "counts": counts,
        "precision": precision,
        "judgments": [dict(j) for j in (judgments or [])],
    }


# ─── Corpus sources list ──────────────────────────────────────────────────────

@router.get("/admin/corpus/sources")
async def list_corpus_sources(request: Request):
    _auth_check(request)
    rows = solcon_db.fetchall(
        "SELECT * FROM solcon_corpus_sources ORDER BY source_type, title"
    )
    return [dict(r) for r in (rows or [])]


@router.get("/kb-sources")
async def list_kb_sources(request: Request):
    """
    Phase 1 registry: return all solomon_kb_sources rows (active + awaiting_source).
    Used by Phase 7 UI to display edition dates and verification timestamps on citations.
    Returns: [{id, law_code, law_name, canonical_url, current_edition_date,
               last_verified_at, status, ...}]
    """
    _auth_check(request)
    rows = solcon_db.fetchall(
        """SELECT id, law_code, law_name, canonical_url, status,
                  current_edition_date, current_edition_basis,
                  last_verified_at, approved_by, notes
           FROM solomon_kb_sources
           ORDER BY id"""
    )
    return [dict(r) for r in (rows or [])]
