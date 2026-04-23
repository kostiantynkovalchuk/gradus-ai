"""
DOCX artifact generation for Solomon Contracts.
§9.1 Risk note (auto, bullet list by document)
§9.3 Protocol (4-column table)
§9.2 Legal opinion (Sonnet markdown → DOCX)
"""
import io
import json
import logging
from pathlib import Path
from typing import Optional

from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "Автоматичний аналіз Solomon. "
    "Підлягає перевірці юристом. Не є юридичною консультацією."
)

SEV_COLORS = {
    "critical": RGBColor(0xC0, 0x39, 0x2B),
    "high": RGBColor(0xE0, 0x6C, 0x00),
    "medium": RGBColor(0xB8, 0x89, 0x2A),
    "low": RGBColor(0x3A, 0x4D, 0x6E),
}


# ─── §9.1 Risk note DOCX ─────────────────────────────────────────────────────

def build_risk_note_docx(
    engagement_name: str,
    counterparty: str,
    documents: list[dict],
    findings: list[dict],
) -> bytes:
    """
    Produce risk note DOCX: informal bullet list grouped by document.
    Grouped by document → category within document.
    """
    doc = Document()
    _set_margins(doc)

    h = doc.add_heading(f"Ризики — {counterparty}", level=1)
    h.runs[0].font.color.rgb = RGBColor(0x0D, 0x15, 0x28)
    doc.add_paragraph(f"Справа: {engagement_name}")
    doc.add_paragraph()

    # Group findings by document then category
    by_doc: dict[int, list] = {}
    for f in findings:
        by_doc.setdefault(f["document_id"], []).append(f)

    doc_map = {d["id"]: d for d in documents}

    for doc_id, doc_findings in by_doc.items():
        doc_info = doc_map.get(doc_id, {})
        doc.add_heading(doc_info.get("original_filename", f"Документ #{doc_id}"), level=2)

        by_cat: dict[str, list] = {}
        for f in doc_findings:
            by_cat.setdefault(f["category"], []).append(f)

        for cat, cat_findings in by_cat.items():
            doc.add_heading(_cat_label(cat), level=3)
            for f in cat_findings:
                p = doc.add_paragraph(style="List Bullet")
                r = p.add_run(f"[{f['clause_ref']}] ")
                r.bold = True
                sev_color = SEV_COLORS.get(f["severity"], RGBColor(0x3A, 0x4D, 0x6E))
                r2 = p.add_run(f"[{f['severity'].upper()}] ")
                r2.font.color.rgb = sev_color
                r2.bold = True
                r3 = p.add_run(f"[{_cat_label(cat)}] ")
                r3.font.color.rgb = RGBColor(0x7A, 0x8F, 0xA8)
                p.add_run(f.get("short_note", ""))
                if f.get("monetary_exposure_uah"):
                    p.add_run(f" (≈{f['monetary_exposure_uah']:,.0f} грн)")
                if f.get("proposed_alternative"):
                    alt_p = doc.add_paragraph(style="List Bullet 2")
                    r_ai = alt_p.add_run("💡 AI suggestion — requires lawyer review: ")
                    r_ai.italic = True
                    r_ai.font.color.rgb = RGBColor(0x2E, 0x42, 0x70)
                    alt_p.add_run(f["proposed_alternative"])
                    cits = json.loads(f.get("legal_citations", "[]"))
                    if cits:
                        cit_text = "; ".join(
                            c.get("article_ref", "") or c.get("source_title", "")
                            for c in cits
                        )
                        alt_p.add_run(f" [{cit_text}]").italic = True

    doc.add_paragraph()
    footer_p = doc.add_paragraph()
    footer_r = footer_p.add_run(DISCLAIMER)
    footer_r.italic = True
    footer_r.font.color.rgb = RGBColor(0x7A, 0x8F, 0xA8)
    footer_r.font.size = Pt(9)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ─── §9.3 Protocol DOCX ──────────────────────────────────────────────────────

def build_protocol_docx(
    engagement_name: str,
    counterparty: str,
    findings: list[dict],
) -> bytes:
    """
    4-column table: Clause № | Buyer version | Supplier version | Agreed version
    """
    doc = Document()
    _set_margins(doc)

    h = doc.add_heading(f"ПРОТОКОЛ РОЗБІЖНОСТЕЙ", level=1)
    h.runs[0].font.color.rgb = RGBColor(0x0D, 0x15, 0x28)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph(
        f"до Договору поставки з {counterparty}\n"
        f"Справа: {engagement_name}\n"
        f"AVTD виступає Постачальником."
    )
    doc.add_paragraph()

    tbl = doc.add_table(rows=1, cols=4)
    tbl.style = "Table Grid"
    hdr = tbl.rows[0].cells
    headers = ["Пункт договору", "Редакція Покупця", "Редакція Постачальника", "Узгоджена редакція"]
    for i, h_text in enumerate(headers):
        hdr[i].text = h_text
        for p in hdr[i].paragraphs:
            for run in p.runs:
                run.bold = True
                run.font.color.rgb = RGBColor(0x0D, 0x15, 0x28)

    for f in findings:
        row = tbl.add_row().cells
        row[0].text = f.get("clause_ref", "")
        row[1].text = f.get("clause_text", "")
        supplier_text = f.get("proposed_alternative") or f.get("short_note", "")
        row[2].text = supplier_text
        row[3].text = ""

    doc.add_paragraph()
    preamble = doc.add_paragraph(
        "Цей протокол складено у двох примірниках, по одному для кожної Сторони."
    )
    footer_p = doc.add_paragraph()
    footer_r = footer_p.add_run(DISCLAIMER)
    footer_r.italic = True
    footer_r.font.color.rgb = RGBColor(0x7A, 0x8F, 0xA8)
    footer_r.font.size = Pt(9)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ─── §9.2 Legal opinion DOCX (from markdown) ─────────────────────────────────

def build_opinion_docx(markdown_text: str, engagement_name: str) -> bytes:
    """Convert markdown legal opinion to DOCX."""
    doc = Document()
    _set_margins(doc)

    for line in markdown_text.split("\n"):
        if line.startswith("### "):
            h = doc.add_heading(line[4:], level=3)
        elif line.startswith("## "):
            h = doc.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            h = doc.add_heading(line[2:], level=1)
            h.runs[0].font.color.rgb = RGBColor(0x0D, 0x15, 0x28)
        elif line.startswith("- "):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif line.strip() == "":
            doc.add_paragraph()
        else:
            p = doc.add_paragraph()
            _add_md_run(p, line)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _add_md_run(p, text: str):
    """Minimal bold/italic markdown parsing for inline text."""
    import re
    segments = re.split(r"(\*\*.*?\*\*|\*.*?\*)", text)
    for seg in segments:
        if seg.startswith("**") and seg.endswith("**"):
            r = p.add_run(seg[2:-2])
            r.bold = True
        elif seg.startswith("*") and seg.endswith("*"):
            r = p.add_run(seg[1:-1])
            r.italic = True
        else:
            p.add_run(seg)


def _set_margins(doc: Document):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1.2)
        section.right_margin = Inches(1)


def _cat_label(cat: str) -> str:
    labels = {
        "penalty": "Штрафні санкції",
        "payment_terms": "Умови оплати",
        "liability_shift": "Перенесення відповідальності",
        "ip_rights": "Права інтелектуальної власності",
        "force_majeure": "Форс-мажор",
        "termination": "Розірвання договору",
        "returns_refusal": "Повернення / відмова товару",
        "audit_rights": "Право аудиту",
        "set_off": "Залік вимог",
        "tax_invoicing": "Податкові накладні",
        "quality_acceptance": "Приймання за якістю",
        "delivery_terms": "Умови поставки",
        "other": "Інше",
    }
    return labels.get(cat, cat)
