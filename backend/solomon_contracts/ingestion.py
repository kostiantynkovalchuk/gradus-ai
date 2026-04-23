"""
Bundle ingestion pipeline for Solomon Contracts.
Handles: file saving, text extraction, document classification, clause parsing.
"""
import io
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(os.getenv("SOLCON_UPLOAD_DIR", "/tmp/solomon_uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CLAUSE_RE = re.compile(
    r"(?m)^(?P<ref>"
    r"п\.\s*\d+(?:\.\d+){1,3}\.?"
    r"|\d+(?:\.\d+){1,3}\.?"
    r"|Розділ\s+\d+"
    r"|Додаток\s*№?\s*\d+"
    r")\s*"
)

DOC_TYPE_HINTS = [
    (re.compile(r"риз(ики|ики)", re.I), "risks_note"),
    (re.compile(r"висновок", re.I), "legal_opinion"),
    (re.compile(r"протокол", re.I), "protocol_draft"),
    (re.compile(r"кодекс|ethics|code", re.I), "commercial_code"),
    (re.compile(r"специфікац", re.I), "specification"),
    (re.compile(r"прайс|price.?list", re.I), "price_list"),
    (re.compile(r"додаткова.угода|ду\b|допка|edi", re.I), "additional_agreement"),
]

VALID_DOC_TYPES = {
    "main_contract", "additional_agreement", "commercial_code",
    "specification", "price_list", "risks_note", "legal_opinion",
    "protocol_draft", "protocol_returned", "protocol_agreed", "other",
}


# ─── Text extraction ─────────────────────────────────────────────────────────

def extract_text_from_docx(path: Path) -> str:
    from docx import Document as DocxDocument
    doc = DocxDocument(str(path))
    paras = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                paras.append(row_text)
    return "\n".join(paras)


def extract_text_from_doc(path: Path) -> str:
    """Try antiword → LibreOffice → python-docx fallback chain."""
    # 1. antiword (fastest, no headless overhead)
    try:
        result = subprocess.run(
            ["antiword", str(path)],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # 2. LibreOffice headless conversion
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["soffice", "--headless", "--convert-to", "docx", "--outdir", tmp, str(path)],
                capture_output=True, timeout=30,
            )
            converted = list(Path(tmp).glob("*.docx"))
            if result.returncode == 0 and converted:
                return extract_text_from_docx(converted[0])
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # 3. python-docx last-ditch (works on some .doc that are actually .docx-zipped)
    try:
        return extract_text_from_docx(path)
    except Exception:
        return ""


def extract_text_from_pdf(path: Path) -> str:
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if text:
                    pages.append(f"[Стор. {i + 1}]\n{text}")
        return "\n\n".join(pages)
    except Exception as e:
        logger.warning(f"[SolCon] PDF extraction failed for {path}: {e}")
        return ""


def extract_text_from_xlsx(path: Path) -> str:
    from openpyxl import load_workbook
    rows = []
    try:
        wb = load_workbook(str(path), read_only=True, data_only=True)
        for ws in wb.worksheets:
            rows.append(f"[Аркуш: {ws.title}]")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    rows.append(" | ".join(cells))
        wb.close()
    except Exception as e:
        logger.warning(f"[SolCon] XLSX extraction failed: {e}")
    return "\n".join(rows)


def extract_text(path: Path, mime_type: str = "") -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx" or mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return extract_text_from_docx(path)
    if suffix == ".doc" or mime_type == "application/msword":
        return extract_text_from_doc(path)
    if suffix == ".pdf" or mime_type == "application/pdf":
        return extract_text_from_pdf(path)
    if suffix in (".xlsx", ".xls") or "spreadsheet" in mime_type:
        return extract_text_from_xlsx(path)
    logger.warning(f"[SolCon] Unknown file type {suffix} — skipping extraction")
    return ""


# ─── Document classification ─────────────────────────────────────────────────

def _classify_by_filename(filename: str) -> Optional[str]:
    name_lower = filename.lower()
    for pattern, doc_type in DOC_TYPE_HINTS:
        if pattern.search(name_lower):
            return doc_type
    if re.search(r"договір.поставки|договор.поставки", name_lower, re.I):
        return "main_contract"
    return None


def _classify_via_llm(filename: str, text_snippet: str) -> str:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    t0 = time.time()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=64,
        system=(
            "You classify Ukrainian legal documents. "
            "Reply with exactly ONE of: main_contract, additional_agreement, "
            "commercial_code, specification, price_list, risks_note, legal_opinion, "
            "protocol_draft, protocol_returned, protocol_agreed, other. "
            "No explanation."
        ),
        messages=[{
            "role": "user",
            "content": f"Filename: {filename}\n\nFirst 500 chars:\n{text_snippet[:500]}",
        }],
    )
    duration_ms = int((time.time() - t0) * 1000)
    result = msg.content[0].text.strip().lower()
    from . import db as solcon_db
    solcon_db.log_llm_call(
        None, None, "classify", "claude-haiku-4-5-20251001",
        msg.usage.input_tokens, msg.usage.output_tokens, duration_ms,
    )
    return result if result in VALID_DOC_TYPES else "other"


def classify_document(filename: str, raw_text: str) -> str:
    hint = _classify_by_filename(filename)
    if hint:
        return hint
    if not raw_text.strip():
        return "other"
    return _classify_via_llm(filename, raw_text)


# ─── Clause parsing ──────────────────────────────────────────────────────────

CLAUSE_ANYWHERE_RE = re.compile(
    r"(?:п\.\s*)?(?<!\d)(\d{1,2}\.\d{1,2}(?:\.\d{1,2}){0,2})(?!\d)"
)

def scan_all_refs(raw_text: str, appendix_prefix: str = "") -> list[dict]:
    """
    Find all X.Y[.Z] clause refs mentioned ANYWHERE in the text (cross-refs, etc.)
    Used to supplement line-start parsing for table-formatted documents.
    Returns list of {ref, text, parent_ref} with empty text (ref-only entries).
    Filters out obvious dates (dd.mm.yyyy pattern).
    """
    DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}")
    date_spans = {m.span() for m in DATE_RE.finditer(raw_text)}

    seen = set()
    clauses = []
    for m in CLAUSE_ANYWHERE_RE.finditer(raw_text):
        if m.span() in date_spans:
            continue
        ref = m.group(0).strip()
        norm = re.sub(r"п\.\s*", "п.", ref).rstrip(".")
        if norm in seen:
            continue
        seen.add(norm)
        clauses.append({
            "ref": appendix_prefix + norm,
            "text": "",
            "parent_ref": _parent_ref(norm),
        })
    return clauses


def parse_clauses(raw_text: str, appendix_prefix: str = "") -> list[dict]:
    """
    Extract clause refs from text using Ukrainian contract numbering conventions.
    Returns list of {ref, text, parent_ref}.
    """
    clauses = []
    lines = raw_text.split("\n")
    current_ref = None
    current_lines: list[str] = []

    def _flush():
        if current_ref:
            clauses.append({
                "ref": (appendix_prefix + current_ref).strip(),
                "text": " ".join(current_lines).strip(),
                "parent_ref": _parent_ref(current_ref),
            })

    for line in lines:
        m = CLAUSE_RE.match(line)
        if m:
            _flush()
            current_ref = m.group("ref").strip()
            current_lines = [line[m.end():].strip()]
        else:
            if current_ref:
                current_lines.append(line.strip())

    _flush()
    return clauses


def _parent_ref(ref: str) -> Optional[str]:
    """п.5.5.1 → п.5.5, п.5.5 → п.5, п.5 → None"""
    m = re.match(r"(п\.\s*)?(\d+(?:\.\d+)*)", ref)
    if not m:
        return None
    parts = m.group(2).split(".")
    if len(parts) <= 1:
        return None
    prefix = "п." if ref.startswith("п") else ""
    return prefix + ".".join(parts[:-1])


def normalize_clause_ref(ref: str) -> str:
    """Normalize 'п. 5.5' → 'п.5.5'"""
    ref = re.sub(r"п\.\s+", "п.", ref)
    return ref.strip()


# ─── Bundle ingestion ────────────────────────────────────────────────────────

def save_upload(filename: str, data: bytes, engagement_id: int) -> Path:
    eng_dir = UPLOAD_DIR / str(engagement_id)
    eng_dir.mkdir(parents=True, exist_ok=True)
    dest = eng_dir / filename
    dest.write_bytes(data)
    return dest


def process_zip(data: bytes, engagement_id: int) -> list[dict]:
    """Extract zip, return list of {filename, path, size}."""
    files = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            name = Path(member.filename).name
            suffix = Path(name).suffix.lower()
            if suffix not in {".doc", ".docx", ".pdf", ".xls", ".xlsx"}:
                continue
            content = zf.read(member.filename)
            path = save_upload(name, content, engagement_id)
            files.append({"filename": name, "path": path, "size": len(content)})
    return files


def ingest_file(
    filename: str, data: bytes, engagement_id: int,
    appendix_prefix: str = "",
) -> dict:
    """
    Save file, extract text, classify, parse clauses.
    Returns dict ready for DB insert into solcon_documents.
    """
    path = save_upload(filename, data, engagement_id)
    suffix = Path(filename).suffix.lower()
    mime_map = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".pdf": "application/pdf",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
    }
    mime_type = mime_map.get(suffix, "application/octet-stream")
    raw_text = extract_text(path, mime_type)
    doc_type = classify_document(filename, raw_text)
    clauses = parse_clauses(raw_text, appendix_prefix)

    return {
        "engagement_id": engagement_id,
        "document_type": doc_type,
        "original_filename": filename,
        "mime_type": mime_type,
        "storage_path": str(path),
        "raw_text": raw_text,
        "clauses": json.dumps(clauses),
    }
