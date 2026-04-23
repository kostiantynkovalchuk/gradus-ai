"""
FastAPI router for Solomon Contracts.
All endpoints under /api/contracts/*
Auth: reuses existing Solomon session (solomon / gradus2026)
"""
import asyncio
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from . import db as solcon_db
from .analyzer import generate_alternatives, generate_legal_opinion, scan_document
from .artifacts import build_opinion_docx, build_protocol_docx, build_risk_note_docx
from .corpus import ingest_incoterms_pdf, ingest_law_text, rebuild_corpus_namespace
from .ingestion import ingest_file, process_zip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contracts", tags=["solomon-contracts"])

SOLOMON_USER = "solomon"
SOLOMON_PASS = "gradus2026"

LAW_SOURCES = [
    {"title": "Цивільний кодекс України", "url": "https://zakon.rada.gov.ua/laws/show/435-15"},
    {"title": "Господарський кодекс України", "url": "https://zakon.rada.gov.ua/laws/show/436-15"},
    {"title": "Закон України «Про захист прав споживачів»", "url": "https://zakon.rada.gov.ua/laws/show/1023-12"},
    {"title": "Закон України «Про безпечність та якість харчових продуктів»", "url": "https://zakon.rada.gov.ua/laws/show/771/97-%D0%B2%D1%80"},
    {"title": "Закон України «Про товариства з обмеженою та додатковою відповідальністю»", "url": "https://zakon.rada.gov.ua/laws/show/2275-19"},
    {"title": "Закон України «Про електронні документи та електронний документообіг»", "url": "https://zakon.rada.gov.ua/laws/show/851-15"},
    {"title": "Закон України «Про авторське право і суміжні права»", "url": "https://zakon.rada.gov.ua/laws/show/3792-12"},
    {"title": "Закон України «Про рекламу»", "url": "https://zakon.rada.gov.ua/laws/show/270/96-%D0%B2%D1%80"},
    {"title": "Закон України «Про захист від недобросовісної конкуренції»", "url": "https://zakon.rada.gov.ua/laws/show/236/96-%D0%B2%D1%80"},
    {"title": "Закон України «Про бухгалтерський облік та фінансову звітність в Україні»", "url": "https://zakon.rada.gov.ua/laws/show/996-14"},
]


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
        "SELECT id, original_filename, document_type, analyzed_at, created_at "
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

    return {
        "engagement": dict(eng),
        "documents": [dict(d) for d in (docs or [])],
        "findings": [dict(f) for f in (findings or [])],
        "severity_summary": sev_summary,
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
    else:
        doc_dict = ingest_file(filename, data, eid, appendix_prefix)
        doc_id = _save_document(eid, doc_dict)
        created_ids.append(doc_id)

    return {"created": created_ids}


def _save_document(eid: int, doc_dict: dict) -> int:
    result = solcon_db.fetchone(
        """INSERT INTO solcon_documents
             (engagement_id, document_type, original_filename, mime_type,
              storage_path, raw_text, clauses)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (
            eid,
            doc_dict["document_type"],
            doc_dict["original_filename"],
            doc_dict["mime_type"],
            doc_dict["storage_path"],
            doc_dict["raw_text"],
            doc_dict["clauses"],
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
    for doc in docs:
        try:
            findings, rejected = await loop.run_in_executor(
                None, _analyze_one_document, doc, eid
            )
            total_findings += len(findings)
        except Exception as e:
            logger.error(f"[SolCon] Analysis failed for doc {doc['id']}: {e}")
    logger.info(f"[SolCon] Analysis complete for eng={eid}, total findings={total_findings}")


def _analyze_one_document(doc: dict, eid: int):
    clauses = json.loads(doc.get("clauses", "[]"))
    raw_text = doc.get("raw_text", "")
    doc_id = doc["id"]

    findings_dicts, rejected = scan_document(doc_id, eid, raw_text, clauses)
    findings_with_alts = generate_alternatives(doc_id, eid, findings_dicts)

    inserted_ids = []
    for f in findings_with_alts:
        result = solcon_db.fetchone(
            """INSERT INTO solcon_findings
                 (document_id, engagement_id, clause_ref, clause_text, category,
                  severity, monetary_exposure_uah, short_note, proposed_alternative,
                  grounding_status, legal_citations, workflow_state, detected_by, confidence)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (
                f["document_id"], f["engagement_id"], f["clause_ref"], f["clause_text"],
                f["category"], f["severity"], f.get("monetary_exposure_uah"),
                f["short_note"], f.get("proposed_alternative"),
                f.get("grounding_status", "ungrounded"),
                f.get("legal_citations", "[]"),
                f.get("workflow_state", "triage"), f["detected_by"],
                f.get("confidence"),
            ),
        )
        inserted_ids.append(result["id"])

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

    finding_ids = [f["id"] for f in findings]
    docx_bytes = build_protocol_docx(
        eng["name"],
        eng["counterparty_name"] or "—",
        [dict(f) for f in findings],
    )

    from pathlib import Path
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

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="protocol_{eid}_v{version}.docx"'},
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
    loop = asyncio.get_event_loop()
    md_text = await loop.run_in_executor(
        None,
        generate_legal_opinion,
        eid,
        eng["counterparty_name"] or "—",
        [dict(d) for d in (docs or [])],
        [dict(f) for f in (findings or [])],
    )

    existing = solcon_db.fetchone(
        "SELECT COALESCE(MAX(version),0) as mv FROM solcon_legal_opinions WHERE engagement_id=%s",
        (eid,),
    )
    version = (existing["mv"] or 0) + 1

    from .ingestion import UPLOAD_DIR
    op_dir = UPLOAD_DIR / str(eid) / "opinions"
    op_dir.mkdir(parents=True, exist_ok=True)
    docx_bytes = build_opinion_docx(md_text, eng["name"])
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


# ─── Corpus admin ─────────────────────────────────────────────────────────────

@router.post("/admin/corpus/seed-sources")
async def seed_corpus_sources(request: Request):
    """Seed the known law sources into solcon_corpus_sources (idempotent)."""
    _auth_check(request)
    inserted = 0
    for src in LAW_SOURCES:
        existing = solcon_db.fetchone(
            "SELECT id FROM solcon_corpus_sources WHERE official_url=%s", (src["url"],)
        )
        if not existing:
            solcon_db.execute(
                """INSERT INTO solcon_corpus_sources (source_type, title, official_url)
                   VALUES ('ukr_law', %s, %s)""",
                (src["title"], src["url"]),
            )
            inserted += 1
    return {"seeded": inserted, "total": len(LAW_SOURCES)}


@router.post("/admin/corpus/rebuild")
async def rebuild_corpus(request: Request):
    _auth_check(request)
    loop = asyncio.get_event_loop()
    asyncio.create_task(loop.run_in_executor(None, rebuild_corpus_namespace))
    return {"message": "Corpus rebuild started in background"}


@router.post("/admin/corpus/incoterms")
async def upload_incoterms(request: Request, file: UploadFile = File(...)):
    _auth_check(request)
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF required")
    data = await file.read()

    existing = solcon_db.fetchone(
        "SELECT id FROM solcon_corpus_sources WHERE source_type='incoterms_2020'"
    )
    if existing:
        source_id = existing["id"]
    else:
        result = solcon_db.fetchone(
            """INSERT INTO solcon_corpus_sources
               (source_type, title, official_url)
               VALUES ('incoterms_2020', 'INCOTERMS 2020', '')
               RETURNING id"""
        )
        source_id = result["id"]

    loop = asyncio.get_event_loop()
    count = await loop.run_in_executor(None, ingest_incoterms_pdf, source_id, data)
    solcon_db.execute(
        "UPDATE solcon_corpus_sources SET chunk_count=%s, last_ingested_at=NOW() WHERE id=%s",
        (count, source_id),
    )
    return {"chunks_ingested": count}


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
