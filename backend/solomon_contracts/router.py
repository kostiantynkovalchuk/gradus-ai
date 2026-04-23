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
from .ingestion import ingest_file, process_zip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/contracts", tags=["solomon-contracts"])

SOLOMON_USER = "solomon"
SOLOMON_PASS = "gradus2026"

# §8.1 — full list confirmed by head of law department 2026-04-23 (15 sources).
#
# article_filter:     list of (from_art, to_art) int ranges.  None = whole doc.
# sub_article_filter: dict art_num → list of sub-article ID strings.
#                     Used for Art 14 of the Tax Code (definition filtering).
# URLs marked [UNVERIFIED] were assigned by pattern — redirect tracking in
# rebuild will correct them and update official_url in solcon_corpus_sources.
LAW_SOURCES = [
    # ── Three codes: article-range whitelisted ─────────────────────────────────
    {
        "title": "Цивільний кодекс України",
        "url": "https://zakon.rada.gov.ua/laws/show/435-15",
        # Supply-contract-relevant articles only.
        # Excluded: Books I-II (persons/family/objects), Book VI (inheritance).
        "article_filter": [
            (3,   21),    # General principles: good faith, pacta sunt servanda
            (202, 241),   # Transactions — validity and invalidity
            (509, 558),   # Obligations: general + security (penalty, surety)
            (610, 654),   # Breach & liability; general contract provisions
            (655, 726),   # Purchase-sale + supply (постачання) contracts
            (901, 966),   # Service contracts (послуги)
        ],
        "sub_article_filter": None,
    },
    {
        "title": "Господарський кодекс України",
        "url": "https://zakon.rada.gov.ua/laws/show/436-15",
        # Commercial supply + economic sanctions only.
        "article_filter": [
            (173, 199),   # Commercial obligations: general
            (200, 212),   # Security of commercial obligations
            (230, 241),   # Economic sanctions and liability
            (264, 291),   # Commercial purchase-sale and supply
        ],
        "sub_article_filter": None,
    },
    {
        "title": "Податковий кодекс України",
        "url": "https://zakon.rada.gov.ua/laws/show/2755-17",
        # Art 14 (definitions) → sub_article_filter keeps only the ~12 definitions
        # that appear in actual supply-contract risk notes.
        # Arts 134-141 (profit tax) and 185-201 (VAT) → chunked whole.
        "article_filter": [
            (14,  14),    # Definitions — sub_article_filter applied below
            (134, 141),   # Profit tax: deductible costs, supply-related
            (185, 201),   # VAT: taxable supply, base, rate, tax credit, tax invoice
        ],
        "sub_article_filter": {
            14: [
                "14.1.54",   # господарська діяльність
                "14.1.71",   # дата виникнення права
                "14.1.122",  # місце постачання товарів
                "14.1.136",  # нерезидент
                "14.1.139",  # особа (платник ПДВ)
                "14.1.156",  # податкове зобов'язання
                "14.1.159",  # податковий кредит
                "14.1.162",  # поставка (для ПДВ)
                "14.1.180",  # резидент
                "14.1.185",  # розумна економічна причина
                "14.1.191",  # постачання товарів
                "14.1.202",  # товари
            ],
        },
    },

    # ── Twelve remaining laws: whole-document, preamble-stripped ──────────────
    {
        "title": "Закон України «Про захист прав споживачів»",
        "url": "https://zakon.rada.gov.ua/laws/show/1023-12",
        "article_filter": None, "sub_article_filter": None,
    },
    {
        "title": "Закон України «Про основні принципи та вимоги до безпечності та якості харчових продуктів»",
        "url": "https://zakon.rada.gov.ua/laws/show/771/97-%D0%B2%D1%80",
        "article_filter": None, "sub_article_filter": None,
    },
    {
        "title": "Закон України «Про інформацію для споживачів щодо харчових продуктів»",  # [UNVERIFIED URL]
        "url": "https://zakon.rada.gov.ua/laws/show/2639-19",
        "article_filter": None, "sub_article_filter": None,
    },
    {
        "title": "Закон України «Про державне регулювання виробництва і обігу спирту етилового, коньячного і плодового, алкогольних напоїв та тютюнових виробів»",
        "url": "https://zakon.rada.gov.ua/laws/show/481/95-%D0%B2%D1%80",
        "article_filter": None, "sub_article_filter": None,
    },
    {
        "title": "Закон України «Про товариства з обмеженою та додатковою відповідальністю»",
        "url": "https://zakon.rada.gov.ua/laws/show/2275-19",
        "article_filter": None, "sub_article_filter": None,
    },
    {
        "title": "Закон України «Про електронні документи та електронний документообіг»",
        "url": "https://zakon.rada.gov.ua/laws/show/851-15",
        "article_filter": None, "sub_article_filter": None,
    },
    {
        "title": "Закон України «Про авторське право і суміжні права»",  # [UNVERIFIED URL]
        "url": "https://zakon.rada.gov.ua/laws/show/3792-12",
        "article_filter": None, "sub_article_filter": None,
    },
    {
        "title": "Закон України «Про рекламу»",
        "url": "https://zakon.rada.gov.ua/laws/show/270/96-%D0%B2%D1%80",
        "article_filter": None, "sub_article_filter": None,
    },
    {
        "title": "Закон України «Про захист від недобросовісної конкуренції»",
        "url": "https://zakon.rada.gov.ua/laws/show/236/96-%D0%B2%D1%80",
        "article_filter": None, "sub_article_filter": None,
    },
    {
        "title": "Закон України «Про захист економічної конкуренції»",
        "url": "https://zakon.rada.gov.ua/laws/show/2210-14",
        "article_filter": None, "sub_article_filter": None,
    },
    {
        "title": "Закон України «Про бухгалтерський облік та фінансову звітність в Україні»",
        "url": "https://zakon.rada.gov.ua/laws/show/996-14",
        "article_filter": None, "sub_article_filter": None,
    },
    {
        "title": "Постанова КМУ №187 «Про забезпечення захисту національної безпеки в сфері економіки»",
        "url": "https://zakon.rada.gov.ua/laws/show/187-2022-%D0%BF",
        "article_filter": None, "sub_article_filter": None,
    },
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
            for src in LAW_SOURCES:
                existing = solcon_db.fetchone(
                    "SELECT id FROM solcon_corpus_sources WHERE official_url=%s",
                    (src["url"],),
                )
                if not existing:
                    solcon_db.execute(
                        """INSERT INTO solcon_corpus_sources (source_type, title, official_url)
                           VALUES ('ukr_law', %s, %s)""",
                        (src["title"], src["url"]),
                    )
                    inserted += 1
                    _job_progress(job_id, f"Inserted: {src['title']}")
                else:
                    skipped += 1
            _job_done(job_id, {"inserted": inserted, "skipped": skipped, "total": len(LAW_SOURCES)})
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
            # Build filter lookup keyed by both URL and title so rebuild can
            # match even after canonical-URL redirect tracking updates the DB.
            law_filters: dict = {}
            for src in LAW_SOURCES:
                entry = {
                    "article_filter": src.get("article_filter"),
                    "sub_article_filter": src.get("sub_article_filter"),
                }
                law_filters[src["url"]] = entry
                law_filters[src["title"]] = entry
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
