"""
Solomon Contracts analyzer.
§7.2 — Free-form scan (Claude Sonnet)
§7.3 — Alternative wording generation (Pinecone RAG + Sonnet)
§10  — Correctness guardrails (clause-ref + legal grounding)
"""
import json
import logging
import re
import time
from typing import Optional

import anthropic

from . import db as solcon_db
from .corpus import retrieve_similar

logger = logging.getLogger(__name__)

ANTHROPIC_SCAN_MODEL = "claude-sonnet-4-5"
ANTHROPIC_ALT_MODEL = "claude-sonnet-4-5"
ANTHROPIC_OPINION_MODEL = "claude-sonnet-4-5"

VALID_CATEGORIES = {
    "penalty", "payment_terms", "liability_shift", "ip_rights",
    "force_majeure", "termination", "returns_refusal", "audit_rights",
    "set_off", "tax_invoicing", "quality_acceptance", "delivery_terms", "other",
}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}
VALID_GROUNDING = {"grounded", "ungrounded", "not_applicable"}

GROUNDED_URL_RE = re.compile(
    r"https?://(zakon\.rada\.gov\.ua|iccwbo\.org|incoterms|solcon_static)"
)

DISCLAIMER = (
    "\n\nАвтоматичний аналіз Solomon. "
    "Підлягає перевірці юристом. Не є юридичною консультацією."
)


# ─── §7.2 Free-form scan ─────────────────────────────────────────────────────

SCAN_SYSTEM = """You are a senior legal analyst reviewing a Ukrainian supply contract from the
supplier's perspective (the supplier is AVTD). Identify clauses that create
MATERIALLY ASYMMETRIC risk, financial exposure, or operational burden for the
supplier — burdens the buyer does NOT face under the same contract.

════ HARD RULES (violation = finding is invalid) ════
1. Cite a specific clause number exactly as it appears (e.g. 'п.4.8', '12.2').
   If you cannot locate a specific clause, DO NOT produce the finding.
2. Proposed alternatives MUST cite a Ukrainian legal source or INCOTERMS article.
   If none is available, set grounding_status='ungrounded', proposed_alternative=null.
3. Never quote more than 25 words verbatim. Paraphrase.
4. Report each clause number AT MOST ONCE. If the same clause covers multiple
   risk categories, use the single highest-severity category.

════ ASYMMETRY THRESHOLD (must pass to report) ════
Ask yourself: "Does this clause impose a burden, penalty, or restriction on the
SUPPLIER that an equivalent clause does NOT impose on the BUYER?"
- YES → report it.
- The same obligation applies to both parties → DO NOT report it.
- This is standard practice in Ukrainian FMCG supply contracts → DO NOT report it.
  Examples of routine clauses you must NOT flag:
  • Standard quality acceptance procedure (inspection at delivery)
  • Normal buyer audit rights for quality or invoicing
  • Sub-items of a mutual obligation list (e.g. п.2.1 підп.3, підп.6)
  • Standard delivery deadlines and INCOTERMS references
  • Reasonable product liability (hidden defect warranty up to ~2 years)

════ SPECIAL PATTERNS TO FLAG (high recall) ════
A. ONE-SIDED PENALTY BLOCK: If section 9 (відповідальність) contains multiple
   sub-clauses where ALL penalties/sanctions apply exclusively to the supplier
   with NO matching buyer penalty in the same section:
   (i)  Set clause_ref to the RANGE format, e.g. '9.3–9.12', covering the entire
        supplier-only block. category='penalty', severity='high'.
   (ii) If there is a SECOND distinct supplier-only block later in the section
        (e.g. clauses 9.13–9.19), produce ONE additional finding with
        clause_ref='9.13–9.19'.
   MANDATORY: Cite the full range as ONE finding. NEVER produce separate
   individual findings for '9.4', '9.6', '9.7', '9.8', etc.
   The ONLY valid clause_ref formats for section 9 penalty blocks are range
   notation like '9.3–9.12' or '9.13–9.19'. Single-clause citations within
   the penalty block (9.4, 9.5, 9.6, 9.7, 9.8) are forbidden.

B. UNLIMITED RETURNS: Any clause giving the buyer an unconditional or time-unlimited
   right to return unsold goods to the supplier → category='returns_refusal', severity='critical'.
   ALSO FLAG: Any clause making the supplier AUTOMATICALLY responsible (liable for replacement/refund)
   when consumers return goods to the buyer under consumer-protection law, without requiring proof
   that the supplier caused the defect (this shifts unlimited consumer return risk to the supplier)
   → category='returns_refusal', severity='high'.

C. UNILATERAL SET-OFF: Any clause allowing the buyer to automatically deduct from
   payment owed without prior written notice or dispute resolution → category='set_off'.

D. TERMINATION LOCK: Any clause in section 12 (or similar "розірвання договору" section)
   that LIMITS early termination of the contract to ONLY cases provided by law
   (phrases like "у випадках, передбачених чинним законодавством України" or
   "лише за взаємною згодою Сторін"), thereby preventing the supplier from exiting
   the contract unilaterally when commercially necessary → category='termination', severity='high'.
   Check clause 12.2 specifically (дострокове розірвання / early termination).

════ CATEGORIES ════
penalty, payment_terms, liability_shift, ip_rights, force_majeure,
termination, returns_refusal, audit_rights, set_off, tax_invoicing,
quality_acceptance, delivery_terms, other.

════ SEVERITY ════
- critical: unbounded liability, >100K UAH exposure, or automatic termination trigger
- high: 25-100% batch cost penalty, one-sided termination, rights-stripping clause
- medium: <25% batch cost penalty, meaningful operational burden
- low: minor administrative asymmetry

════ OUTPUT ════
JSON array of findings. Each finding:
  clause_ref (string), clause_text (≤25 word paraphrase), category (string),
  severity (string), monetary_exposure_uah (number or null),
  short_note (Ukrainian, 1-2 sentences), confidence (0.0-1.0).

Aim for PRECISION over completeness. 6-10 findings is optimal. More than 12 findings
almost certainly means you are over-flagging routine commercial terms.
Respond ONLY with valid JSON — no markdown fences, no explanation."""


def scan_document(
    document_id: int,
    engagement_id: int,
    raw_text: str,
    clauses: list[dict],
) -> tuple[list[dict], int]:
    """
    Run free-form scan (§7.2).
    Returns list of raw finding dicts (not yet in DB).
    Guardrail §10.1 applied here.
    """
    client = anthropic.Anthropic()

    clause_refs_set = {c["ref"].lower() for c in clauses}

    user_msg = f"<contract>\n{raw_text[:120000]}\n</contract>"

    t0 = time.time()
    try:
        msg = client.messages.create(
            model=ANTHROPIC_SCAN_MODEL,
            max_tokens=8192,
            system=SCAN_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        logger.error(f"[SolCon] Scan LLM call failed doc={document_id}: {e}")
        solcon_db.log_llm_call(
            engagement_id, document_id, "scan", ANTHROPIC_SCAN_MODEL,
            0, 0, int((time.time() - t0) * 1000), "error",
        )
        return [], 0

    duration_ms = int((time.time() - t0) * 1000)
    raw_out = msg.content[0].text.strip()
    # Strip markdown fences if model wraps response (```json ... ```)
    if raw_out.startswith("```"):
        raw_out = re.sub(r"^```(?:json)?\s*", "", raw_out)
        raw_out = re.sub(r"\s*```$", "", raw_out).strip()

    solcon_db.log_llm_call(
        engagement_id, document_id, "scan", ANTHROPIC_SCAN_MODEL,
        msg.usage.input_tokens, msg.usage.output_tokens, duration_ms,
    )

    try:
        findings_raw = json.loads(raw_out)
    except json.JSONDecodeError:
        logger.error(f"[SolCon] Scan JSON parse failed doc={document_id}: {raw_out[:200]}")
        solcon_db.log_llm_call(
            engagement_id, document_id, "scan", ANTHROPIC_SCAN_MODEL,
            0, 0, 0, "parse_error",
        )
        return [], 0

    accepted = []
    rejected_count = 0

    for f in findings_raw:
        clause_ref = str(f.get("clause_ref", "")).strip()
        # §10.1: verify clause_ref exists in parsed clauses
        # Normalize both sides: lowercase, no spaces, strip leading п. for comparison
        norm_ref = clause_ref.lower().replace(" ", "").lstrip("п.")
        found = any(
            c["ref"].lower().replace(" ", "").lstrip("п.") == norm_ref
            or norm_ref in c["ref"].lower().replace(" ", "").lstrip("п.")
            or c["ref"].lower().replace(" ", "").lstrip("п.") in norm_ref
            for c in clauses
        )
        if not found and clauses:
            logger.info(f"[SolCon] Rejected finding: ungrounded clause_ref={clause_ref!r}")
            rejected_count += 1
            continue

        category = f.get("category", "other")
        if category not in VALID_CATEGORIES:
            category = "other"
        severity = f.get("severity", "low")
        if severity not in VALID_SEVERITIES:
            severity = "low"

        accepted.append({
            "document_id": document_id,
            "engagement_id": engagement_id,
            "clause_ref": clause_ref,
            "clause_text": str(f.get("clause_text", ""))[:500],
            "category": category,
            "severity": severity,
            "monetary_exposure_uah": _safe_num(f.get("monetary_exposure_uah")),
            "short_note": str(f.get("short_note", ""))[:2000],
            "proposed_alternative": None,
            "grounding_status": "ungrounded",
            "legal_citations": "[]",
            "workflow_state": "triage",
            "detected_by": "llm_scan",
            "confidence": _safe_float(f.get("confidence", 0.7)),
        })

    if rejected_count:
        logger.info(f"[SolCon] Guardrail §10.1: rejected {rejected_count} finding(s) for doc={document_id}")

    return accepted, rejected_count


# ─── §7.3 Alternative wording generation ─────────────────────────────────────

ALT_SYSTEM = """You are a legal advisor helping an alcohol distributor (AVTD, supplier)
renegotiate unfavorable contract clauses under Ukrainian law.

Given a risk finding and retrieved legal sources, propose an alternative clause
wording that minimizes supplier risk.

HARD RULES:
1. You MUST cite at least one of the retrieved legal sources explicitly (article/section number).
   If none of the retrieved sources support a grounded alternative, output:
   {"grounding_status": "ungrounded", "alternative": null, "citations": []}
2. The alternative clause text MUST be in Ukrainian.
3. Tag every alternative with 'AI suggestion — requires lawyer review'.
4. Never fabricate URLs. Only cite URLs from the retrieved sources list.

OUTPUT: JSON object:
{
  "grounding_status": "grounded" | "ungrounded",
  "alternative": "<clause text in Ukrainian or null>",
  "citations": [{"article_ref": "...", "official_url": "...", "source_title": "..."}]
}
No markdown fences, no explanation."""


def generate_alternatives(
    document_id: int,
    engagement_id: int,
    findings: list[dict],
) -> list[dict]:
    """
    For each finding where severity ≥ medium, generate proposed_alternative via RAG + Sonnet.
    Modifies and returns the findings list with alternatives filled in.
    """
    HIGH_SEV = {"medium", "high", "critical"}
    client = anthropic.Anthropic()

    for finding in findings:
        if finding["severity"] not in HIGH_SEV:
            finding["grounding_status"] = "not_applicable"
            continue

        short_note = finding.get("short_note", "")
        try:
            top_sources = retrieve_similar(short_note, top_k=5)
        except Exception as e:
            logger.warning(f"[SolCon] RAG failed for finding: {e}")
            top_sources = []

        query_hash = _hash(short_note)

        sources_text = "\n\n".join(
            f"[{i+1}] {s['article_ref']} — {s['source_title']}\n"
            f"URL: {s['official_url']}\n"
            f"{s['chunk_text'][:600]}"
            for i, s in enumerate(top_sources)
        ) or "No relevant sources retrieved."

        user_msg = (
            f"Finding:\n"
            f"  clause_ref: {finding['clause_ref']}\n"
            f"  severity: {finding['severity']}\n"
            f"  short_note: {short_note}\n\n"
            f"Retrieved legal sources:\n{sources_text}"
        )

        t0 = time.time()
        try:
            msg = client.messages.create(
                model=ANTHROPIC_ALT_MODEL,
                max_tokens=1024,
                system=ALT_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
            )
        except Exception as e:
            logger.error(f"[SolCon] Alternative LLM failed: {e}")
            solcon_db.log_llm_call(
                engagement_id, document_id, "alternative", ANTHROPIC_ALT_MODEL,
                0, 0, int((time.time() - t0) * 1000), "error",
            )
            continue

        duration_ms = int((time.time() - t0) * 1000)
        solcon_db.log_llm_call(
            engagement_id, document_id, "alternative", ANTHROPIC_ALT_MODEL,
            msg.usage.input_tokens, msg.usage.output_tokens, duration_ms,
        )

        try:
            result = json.loads(msg.content[0].text.strip())
        except json.JSONDecodeError:
            logger.warning("[SolCon] Alternative JSON parse failed")
            continue

        grounding = result.get("grounding_status", "ungrounded")
        if grounding not in VALID_GROUNDING:
            grounding = "ungrounded"
        alternative = result.get("alternative")
        citations = result.get("citations", [])

        # §10.2 post-LLM validation: check every citation URL
        valid_citations = []
        all_valid = True
        for cit in citations:
            url = cit.get("official_url", "")
            if url and not GROUNDED_URL_RE.match(url):
                logger.warning(f"[SolCon] §10.2 Rejected citation URL: {url}")
                all_valid = False
            else:
                valid_citations.append(cit)

        if not all_valid or not valid_citations:
            grounding = "ungrounded"
            alternative = None
            valid_citations = []

        finding["grounding_status"] = grounding
        finding["proposed_alternative"] = alternative
        finding["legal_citations"] = json.dumps(valid_citations)

        # audit log retrieval
        if finding.get("_finding_id"):
            solcon_db.log_retrieval(
                finding["_finding_id"],
                query_hash,
                [{"id": s["id"], "score": s["score"]} for s in top_sources],
                [c["official_url"] for c in valid_citations],
            )

    return findings


# ─── §9.2 Legal opinion generation ───────────────────────────────────────────

OPINION_SYSTEM = """You are a senior Ukrainian legal counsel preparing a formal legal opinion
for AVTD (supplier) regarding a supply contract engagement.

Write a formal legal opinion in Ukrainian, structured as follows:
1. Heading: 'Правовий висновок — {counterparty}'
2. One section per document in the engagement (e.g. 'Ризики за Договором поставки').
3. Within each section, group findings by category.
4. Each finding rendered as a formal paragraph: clause reference, risk explanation.
5. If proposed_alternative exists, add a subsection tagged 'AI suggestion — requires lawyer review'.
6. Closing summary table (plain text): count by severity, total monetary exposure.

HARD RULES:
- Every AI suggestion paragraph must end with: 'AI suggestion — requires lawyer review'
- Footer: 'Автоматичний аналіз Solomon. Підлягає перевірці юристом. Не є юридичною консультацією.'
- Respond in Markdown only."""


def generate_legal_opinion(
    engagement_id: int,
    counterparty: str,
    documents: list[dict],
    findings: list[dict],
) -> str:
    """Generate legal opinion markdown for an engagement."""
    client = anthropic.Anthropic()

    findings_summary = json.dumps([
        {
            "doc": f.get("doc_name", ""),
            "clause_ref": f["clause_ref"],
            "category": f["category"],
            "severity": f["severity"],
            "short_note": f["short_note"],
            "proposed_alternative": f.get("proposed_alternative"),
            "legal_citations": json.loads(f.get("legal_citations", "[]")),
        }
        for f in findings
    ], ensure_ascii=False, indent=2)

    user_msg = (
        f"Counterparty: {counterparty}\n\n"
        f"Documents: {', '.join(d['original_filename'] for d in documents)}\n\n"
        f"Findings (JSON):\n{findings_summary}"
    )

    t0 = time.time()
    try:
        msg = client.messages.create(
            model=ANTHROPIC_OPINION_MODEL,
            max_tokens=4096,
            system=OPINION_SYSTEM.format(counterparty=counterparty),
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as e:
        logger.error(f"[SolCon] Legal opinion LLM failed eng={engagement_id}: {e}")
        return f"# Помилка генерації\n\n{e}\n{DISCLAIMER}"

    duration_ms = int((time.time() - t0) * 1000)
    solcon_db.log_llm_call(
        engagement_id, None, "opinion", ANTHROPIC_OPINION_MODEL,
        msg.usage.input_tokens, msg.usage.output_tokens, duration_ms,
    )
    content = msg.content[0].text.strip()
    if DISCLAIMER.strip() not in content:
        content += DISCLAIMER
    return content


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _safe_num(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_float(val, default=0.7) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _hash(text: str) -> str:
    import hashlib
    return hashlib.md5(text.encode()).hexdigest()
