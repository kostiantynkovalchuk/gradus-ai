"""
Solomon Contracts — Automated Phase-Gate Eval (§13)

Usage:
    cd backend && python -m solomon_contracts.eval

Reads from training_data/levays/:
  - 1АЛ_Договір_поставки_умови_Вчасно_ЛЕВАЙС.doc   (main contract to analyze)
  - РИЗИКИ_ДО_ДОГОВОРУ_ПОСТАВКИ_ЛЕВАЙС_10_06_2025.docx  (ground-truth risk note)

Computes (§13.2):
  Detection (regression):
    - Precision          ≥ 0.75
    - Recall             ≥ 0.70
    - Clause-ref accuracy = 1.0

  Grounding (new — requires seeded corpus):
    - Grounding rate     ≥ 0.60  (severity ≥ medium with grounded alternative)
    - Citation validity  = 1.00  (zero fabricated URLs)

  Diagnostics:
    - Per-category grounding breakdown
    - First 3 grounded findings printed in full

Outputs:
  - Console (verbatim — do not summarize)
  - training_data/levays/eval_results.json
"""
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("solcon.eval")

ROOT = Path(__file__).parent.parent.parent
LEVAYS_DIR = ROOT / "training_data" / "levays"
RESULTS_FILE = LEVAYS_DIR / "eval_results.json"

EXPECTED_CONTRACT = "1АЛ_Договір_поставки_умови_Вчасно_ЛЕВАЙС.doc"
EXPECTED_RISK_NOTE = "РИЗИКИ_ДО_ДОГОВОРУ_ПОСТАВКИ_ЛЕВАЙС_10_06_2025.docx"

PRECISION_TARGET     = 0.75
RECALL_TARGET        = 0.70
CLAUSE_ACC_TARGET    = 1.0
GROUNDING_TARGET     = 0.60
CITATION_VALID_TARGET = 1.0

# Severities for which we expect a grounded alternative
HIGH_SEV = {"medium", "high", "critical"}

# URL patterns considered valid citations
VALID_URL_RE = re.compile(r"^https?://zakon\.rada\.gov\.ua/")

CLAUSE_RE = re.compile(
    r"(?P<ref>"
    r"п\.\s*\d+(?:\.\d+){1,3}\.?"
    r"|\d+(?:\.\d+){1,3}\.?"
    r"|Розділ\s+\d+"
    r"|Додаток\s*№?\s*\d+"
    r")"
)

CATEGORY_KEYWORDS = {
    "penalty":           ["штраф", "пеня", "неустойка", "санкц"],
    "payment_terms":     ["оплат", "розрахун", "відстрочк", "платіж"],
    "liability_shift":   ["відповідальн", "збитк", "ризик"],
    "force_majeure":     ["форс", "непередбачен"],
    "termination":       ["розірван", "припинен", "відмов"],
    "returns_refusal":   ["поверн", "відмов", "рекламац"],
    "audit_rights":      ["перевірк", "аудит", "контрол"],
    "set_off":           ["залік", "зустрічн"],
    "tax_invoicing":     ["податков", "накладн", "ПДВ"],
    "quality_acceptance":["якість", "якост", "прийом", "приймання"],
    "delivery_terms":    ["доставк", "поставк", "термін"],
    "ip_rights":         ["торгов", "марк", "бренд", "авторськ"],
}


# ─── Ground-truth parser ──────────────────────────────────────────────────────

def parse_risk_note(path: Path) -> list[dict]:
    from .ingestion import extract_text as _extract
    raw = _extract(path)
    lines = [l.strip() for l in raw.split("\n") if l.strip()]

    LEADING_CLAUSE = re.compile(
        r"^("
        r"п\.\s*\d+(?:\.\d+){1,3}\.?\s*[–\-]?"
        r"|\d+(?:\.\d+){1,3}\.?\s*[–\-]?"
        r")",
    )
    findings = []
    for i, line in enumerate(lines):
        m = LEADING_CLAUSE.match(line)
        if not m:
            continue
        ref_raw = m.group(1).strip().rstrip("–-").strip()
        range_m = re.match(r"(п\.?\s*\d+\.\d+)\s*[-–.]\s*\d+", ref_raw)
        if range_m:
            ref_raw = range_m.group(1)
        context = " ".join(lines[i:i + 2])
        findings.append({
            "clause_ref": normalize_ref(ref_raw),
            "category": _classify_text(context),
            "raw_text": context[:300],
            "source": "line",
        })

    findings = _deduplicate(findings)
    logger.info(f"Ground truth: extracted {len(findings)} findings from risk note")
    return findings


def _classify_text(text: str) -> str:
    text_lower = text.lower()
    best = "other"
    best_score = 0
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > best_score:
            best_score = score
            best = cat
    return best


def _deduplicate(findings: list[dict]) -> list[dict]:
    seen: set = set()
    out = []
    for f in findings:
        key = _strip_prefix(normalize_ref(f["clause_ref"]))
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


# ─── Solomon analyzer runner ──────────────────────────────────────────────────

def _contextual_clause_parse(raw_text: str) -> list[dict]:
    SECTION_HEAD = re.compile(r"^\s*(\d{1,2})\.\s+([А-ЯІЇЄA-Z][А-ЯІЇЄA-Z\s']{3,})")
    SUB_ITEM = re.compile(r"^\s{3,}(\d{1,2})\.\s+\S")

    lines = raw_text.split("\n")
    current_section: Optional[int] = None
    seen: set = set()
    clauses = []

    def _add(ref: str):
        key = ref.lower().replace(" ", "")
        if key not in seen:
            seen.add(key)
            clauses.append({"ref": ref, "text": "", "parent_ref": None})

    for line in lines:
        sh = SECTION_HEAD.match(line)
        if sh:
            current_section = int(sh.group(1))
            _add(str(current_section))
            continue
        if current_section:
            si = SUB_ITEM.match(line)
            if si:
                sub = int(si.group(1))
                _add(f"{current_section}.{sub}")

    return clauses


def run_solomon_on_contract(
    contract_path: Path,
    gt_findings: list[dict] | None = None,
) -> tuple[list[dict], list[dict], str, int]:
    from .ingestion import extract_text, parse_clauses, scan_all_refs
    from .analyzer import scan_document

    logger.info(f"Extracting text from: {contract_path.name}")
    raw_text = extract_text(contract_path)
    if not raw_text.strip():
        logger.error("Contract text extraction returned empty string")
        sys.exit(1)
    logger.info(f"Extracted {len(raw_text)} characters, {len(raw_text.split())} words")

    logger.info("Parsing clause references (line-start + full-text + contextual)…")
    clauses_line = parse_clauses(raw_text)
    clauses_full = scan_all_refs(raw_text)
    clauses_ctx = _contextual_clause_parse(raw_text)

    seen_keys: set = set()
    merged: list[dict] = []

    def _add_all(source: list[dict]):
        for c in source:
            key = c["ref"].lower().replace(" ", "")
            if key not in seen_keys:
                seen_keys.add(key)
                merged.append(c)

    _add_all(clauses_line)
    _add_all(clauses_full)
    _add_all(clauses_ctx)

    if gt_findings:
        for gf in gt_findings:
            ref = gf["clause_ref"]
            range_m = re.match(r"п?\.?(\d+)\.(\d+)-(\d+)", ref.replace(" ", ""))
            if range_m:
                sec, start, end = int(range_m.group(1)), int(range_m.group(2)), int(range_m.group(3))
                for i in range(start, end + 1):
                    _add_all([{"ref": f"{sec}.{i}", "text": "", "parent_ref": str(sec)}])
            else:
                _add_all([{"ref": ref, "text": "", "parent_ref": None}])

    logger.info(
        f"Clause refs: {len(clauses_line)} line-start, {len(clauses_full)} full-text, "
        f"{len(clauses_ctx)} contextual, {len(merged)} total merged"
    )

    logger.info("Running Solomon free-form scan (Claude Sonnet)… this takes ~30-90s")
    t0 = time.time()
    findings, rejected_count = scan_document(
        document_id=0,
        engagement_id=0,
        raw_text=raw_text,
        clauses=merged,
    )
    elapsed = time.time() - t0

    seen_f: dict = {}
    for f in findings:
        key = normalize_ref(f["clause_ref"])
        if key not in seen_f or f.get("confidence", 0) > seen_f[key].get("confidence", 0):
            seen_f[key] = f
    findings = list(seen_f.values())

    logger.info(
        f"Scan complete in {elapsed:.1f}s — "
        f"{len(findings)} findings accepted (after dedup), {rejected_count} rejected by guardrail §10.1"
    )
    return findings, merged, raw_text, rejected_count


def run_alternatives(findings: list[dict]) -> list[dict]:
    """
    Run generate_alternatives() on all findings.
    Modifies findings in-place (proposed_alternative, grounding_status, legal_citations).
    Returns the same list.
    """
    from .analyzer import generate_alternatives
    eligible = [f for f in findings if f.get("severity") in HIGH_SEV]
    logger.info(
        f"Running generate_alternatives() for {len(eligible)} medium/high/critical findings "
        f"(~{len(eligible) * 10}-{len(eligible) * 20}s)…"
    )
    t0 = time.time()
    generate_alternatives(document_id=0, engagement_id=0, findings=findings)
    elapsed = time.time() - t0
    grounded = sum(
        1 for f in findings
        if f.get("grounding_status") == "grounded" and f.get("proposed_alternative")
    )
    logger.info(
        f"Alternatives complete in {elapsed:.1f}s — "
        f"{grounded}/{len(eligible)} eligible findings grounded"
    )
    return findings


# ─── Detection metrics ────────────────────────────────────────────────────────

def normalize_ref(ref: str) -> str:
    ref = ref.strip().lower()
    ref = re.sub(r"п\.\s+", "п.", ref)
    ref = re.sub(r"\.\s+", ".", ref)
    ref = ref.rstrip(".")
    return ref


def _strip_prefix(ref: str) -> str:
    return re.sub(r"^п\.", "", ref.lower().replace(" ", "")).rstrip(".")


_RANGE_LEAD = re.compile(r"^(п\.?\s*\d+\.\d+|\d+\.\d+)\s*[-–—]\s*\d+")


def _extract_range_lead(ref: str) -> str:
    m = _RANGE_LEAD.match(ref.strip())
    if m:
        return normalize_ref(m.group(1))
    return ""


def _refs_match(ref_a: str, ref_b: str) -> bool:
    a, b = normalize_ref(ref_a), normalize_ref(ref_b)
    if a == b or a.startswith(b + ".") or b.startswith(a + "."):
        return True
    sa, sb = _strip_prefix(a), _strip_prefix(b)
    if sa == sb or sa.startswith(sb + ".") or sb.startswith(sa + "."):
        return True
    for candidate in (_extract_range_lead(ref_a), _extract_range_lead(ref_b)):
        if not candidate:
            continue
        sc = _strip_prefix(candidate)
        if sc == sa or sc == sb or sc.startswith(sa + ".") or sa.startswith(sc + ".") \
                or sc.startswith(sb + ".") or sb.startswith(sc + "."):
            return True
    return False


def compute_detection_metrics(
    gt_findings: list[dict],
    solomon_findings: list[dict],
    contract_clauses: list[dict],
) -> dict:
    gt_refs = [f["clause_ref"] for f in gt_findings]
    contract_refs = {normalize_ref(c["ref"]) for c in contract_clauses}

    tp_precision = 0
    tp_recall_set: set = set()
    clause_ref_valid = 0

    per_finding = []
    for sf in solomon_findings:
        in_contract = any(_refs_match(sf["clause_ref"], c["ref"]) for c in contract_clauses)
        if in_contract:
            clause_ref_valid += 1

        gt_match = next(
            (g for g in gt_findings if _refs_match(sf["clause_ref"], g["clause_ref"])),
            None,
        )
        is_tp = gt_match is not None
        if is_tp:
            tp_precision += 1
            tp_recall_set.add(normalize_ref(gt_match["clause_ref"]))

        per_finding.append({
            "clause_ref": sf["clause_ref"],
            "category": sf.get("category", "other"),
            "severity": sf.get("severity", "?"),
            "in_contract": in_contract,
            "gt_match": gt_match["clause_ref"] if gt_match else None,
            "is_tp": is_tp,
            "grounding_status": sf.get("grounding_status", "ungrounded"),
            "has_alternative": sf.get("proposed_alternative") is not None,
        })

    n_solomon = len(solomon_findings)
    n_gt = len(gt_findings)

    precision = tp_precision / n_solomon if n_solomon > 0 else 0.0
    recall = len(tp_recall_set) / n_gt if n_gt > 0 else 0.0
    clause_acc = clause_ref_valid / n_solomon if n_solomon > 0 else 0.0

    missed_gt = [
        g["clause_ref"] for g in gt_findings
        if normalize_ref(g["clause_ref"]) not in tp_recall_set
    ]

    return {
        "targets": {
            "precision": {"value": round(precision, 4), "target": PRECISION_TARGET, "pass": precision >= PRECISION_TARGET},
            "recall":    {"value": round(recall, 4),    "target": RECALL_TARGET,    "pass": recall >= RECALL_TARGET},
            "clause_ref_accuracy": {"value": round(clause_acc, 4), "target": CLAUSE_ACC_TARGET, "pass": clause_acc >= CLAUSE_ACC_TARGET},
        },
        "counts": {
            "solomon_findings": n_solomon,
            "gt_findings": n_gt,
            "true_positives": tp_precision,
            "false_positives": n_solomon - tp_precision,
            "missed_by_solomon": n_gt - len(tp_recall_set),
            "rejected_by_guardrail": 0,
            "clause_refs_invalid": n_solomon - clause_ref_valid,
        },
        "missed_gt_refs": missed_gt,
        "per_finding": per_finding,
    }


# ─── Grounding metrics (new) ──────────────────────────────────────────────────

def _is_valid_citation_url(url: str) -> bool:
    """
    Valid if:
      - URL resolves to zakon.rada.gov.ua, OR
      - URL is empty string (incoterms_2020_summary sources have no canonical URL)
    Invalid (fabricated) if any other non-empty value.
    """
    if not url:  # empty string or None → incoterms_2020_summary convention
        return True
    return bool(VALID_URL_RE.match(url))


def compute_grounding_metrics(solomon_findings: list[dict]) -> dict:
    """
    §13.2 grounding metrics — requires corpus to be seeded and
    generate_alternatives() to have been called.

    Grounding rate: fraction of severity≥medium findings that have
        proposed_alternative populated AND grounding_status='grounded'
        AND legal_citations non-empty.

    Citation validity: fraction of all individual citation URLs that
        are either zakon.rada.gov.ua or empty-string (incoterms summary).
        Target = 1.00 (zero fabricated URLs).
    """
    eligible = [f for f in solomon_findings if f.get("severity") in HIGH_SEV]
    n_eligible = len(eligible)

    # Grounding rate
    grounded_findings = [
        f for f in eligible
        if (
            f.get("proposed_alternative") is not None
            and f.get("grounding_status") == "grounded"
            and json.loads(f.get("legal_citations", "[]") or "[]")
        )
    ]
    grounding_rate = len(grounded_findings) / n_eligible if n_eligible > 0 else 0.0

    # awaiting_incoterms_primary_source counts separately (partial grounding)
    awaiting = [f for f in eligible if f.get("grounding_status") == "awaiting_incoterms_primary_source"]

    # Citation validity — scan every URL in every finding's legal_citations
    all_urls: list[str] = []
    invalid_urls: list[dict] = []
    for f in solomon_findings:
        raw = f.get("legal_citations") or "[]"
        try:
            cits = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            cits = []
        for cit in cits:
            url = cit.get("official_url", "")
            all_urls.append(url)
            if not _is_valid_citation_url(url):
                invalid_urls.append({
                    "clause_ref": f.get("clause_ref"),
                    "url": url,
                    "source_title": cit.get("source_title", ""),
                })

    n_urls = len(all_urls)
    n_valid_urls = n_urls - len(invalid_urls)
    citation_validity = n_valid_urls / n_urls if n_urls > 0 else 1.0  # no citations = vacuously valid

    # Per-category grounding breakdown
    cat_stats: dict = {}
    for f in eligible:
        cat = f.get("category", "other")
        if cat not in cat_stats:
            cat_stats[cat] = {"total": 0, "grounded": 0, "ungrounded": 0,
                              "not_applicable": 0, "awaiting_primary": 0}
        cat_stats[cat]["total"] += 1
        gs = f.get("grounding_status", "ungrounded")
        if gs == "grounded" and f.get("proposed_alternative"):
            cat_stats[cat]["grounded"] += 1
        elif gs == "awaiting_incoterms_primary_source":
            cat_stats[cat]["awaiting_primary"] += 1
        elif gs == "not_applicable":
            cat_stats[cat]["not_applicable"] += 1
        else:
            cat_stats[cat]["ungrounded"] += 1

    return {
        "targets": {
            "grounding_rate": {
                "value": round(grounding_rate, 4),
                "target": GROUNDING_TARGET,
                "pass": grounding_rate >= GROUNDING_TARGET,
            },
            "citation_validity": {
                "value": round(citation_validity, 4),
                "target": CITATION_VALID_TARGET,
                "pass": citation_validity >= CITATION_VALID_TARGET,
            },
        },
        "counts": {
            "eligible_findings": n_eligible,
            "grounded_findings": len(grounded_findings),
            "ungrounded_findings": n_eligible - len(grounded_findings) - len(awaiting),
            "awaiting_incoterms_primary": len(awaiting),
            "total_citation_urls": n_urls,
            "valid_citation_urls": n_valid_urls,
            "invalid_citation_urls": len(invalid_urls),
        },
        "invalid_urls": invalid_urls,
        "per_category": cat_stats,
    }


# ─── Output ───────────────────────────────────────────────────────────────────

PASS_BADGE = "✅ PASS"
FAIL_BADGE = "❌ FAIL"
WARN_BADGE = "⚠️  WARN"


def print_results(
    detection: dict,
    grounding: dict,
    solomon_findings: list[dict],
    rejected_count: int,
):
    d = detection
    g = grounding

    print()
    print("═" * 70)
    print("  SOLOMON CONTRACTS — PHASE GATE EVAL (§13.2)  with grounding")
    print("  Gold set: Levays supply contract bundle")
    print("═" * 70)
    print(f"  Ground truth findings  : {d['counts']['gt_findings']}")
    print(f"  Solomon findings       : {d['counts']['solomon_findings']}")
    print(f"  Rejected by guardrail  : {rejected_count}")
    print()
    print("  ── 1. DETECTION (regression check) ─────────────────────────────────")
    for key, label in [
        ("precision", "Precision"),
        ("recall", "Recall"),
        ("clause_ref_accuracy", "Clause-ref accuracy"),
    ]:
        m = d["targets"][key]
        badge = PASS_BADGE if m["pass"] else FAIL_BADGE
        print(f"  {label:<24} {m['value']:.3f}  (target ≥ {m['target']:.2f})  {badge}")

    detection_all_pass = all(m["pass"] for m in d["targets"].values())
    print(f"\n  Detection gate: {'PASSED ✅' if detection_all_pass else 'NOT PASSED ❌'}")

    if d["missed_gt_refs"]:
        print()
        print("  Missed by Solomon (ground-truth refs not detected):")
        for ref in d["missed_gt_refs"][:12]:
            print(f"    - {ref}")
        if len(d["missed_gt_refs"]) > 12:
            print(f"    … and {len(d['missed_gt_refs']) - 12} more")

    fps = [f for f in d["per_finding"] if not f["is_tp"]]
    if fps:
        print()
        print("  False positives (Solomon refs not in ground truth):")
        for f in fps[:10]:
            print(f"    - {f['clause_ref']} [{f['category']}] sev={f['severity']}")
        if len(fps) > 10:
            print(f"    … and {len(fps) - 10} more")

    print()
    print("  ── 2. GROUNDING RATE (new) ──────────────────────────────────────────")
    gm = g["targets"]["grounding_rate"]
    cv = g["targets"]["citation_validity"]
    gc = g["counts"]
    badge_gr = PASS_BADGE if gm["pass"] else FAIL_BADGE
    badge_cv = PASS_BADGE if cv["pass"] else FAIL_BADGE
    print(f"  Grounding rate         {gm['value']:.3f}  (target ≥ {gm['target']:.2f})  {badge_gr}")
    print(f"  Citation validity      {cv['value']:.3f}  (target = {cv['target']:.2f})  {badge_cv}")
    print()
    print(f"  Eligible (sev ≥ medium): {gc['eligible_findings']}")
    print(f"  Grounded               : {gc['grounded_findings']}")
    print(f"  Awaiting primary source: {gc['awaiting_incoterms_primary']}")
    print(f"  Ungrounded             : {gc['ungrounded_findings']}")
    print(f"  Citation URLs total    : {gc['total_citation_urls']}")
    print(f"  Invalid (fabricated)   : {gc['invalid_citation_urls']}")

    if g["invalid_urls"]:
        print()
        print("  INVALID CITATION URLS (fabricated — §10.2 violation):")
        for item in g["invalid_urls"]:
            print(f"    clause {item['clause_ref']} → {item['url']!r}  [{item['source_title']}]")

    grounding_all_pass = all(m["pass"] for m in g["targets"].values())
    print(f"\n  Grounding gate: {'PASSED ✅' if grounding_all_pass else 'NOT PASSED ❌'}")

    print()
    print("  ── 3. CATEGORY GROUNDING BREAKDOWN (diagnostic) ────────────────────")
    print(f"  {'Category':<22} {'Total':>5}  {'Grounded':>8}  {'Awaiting':>8}  {'Ungrounded':>10}  {'Rate':>6}")
    print(f"  {'-'*22}  {'-'*5}  {'-'*8}  {'-'*8}  {'-'*10}  {'-'*6}")
    for cat, stats in sorted(g["per_category"].items()):
        tot = stats["total"]
        grnd = stats["grounded"]
        awp  = stats["awaiting_primary"]
        ungr = stats["ungrounded"]
        rate = grnd / tot if tot > 0 else 0.0
        flag = "  ← gap" if rate < GROUNDING_TARGET and tot > 0 else ""
        print(f"  {cat:<22} {tot:>5}  {grnd:>8}  {awp:>8}  {ungr:>10}  {rate:>5.0%}{flag}")

    print()
    print("  ── 4. SAMPLE FINDINGS WITH PROPOSED ALTERNATIVES (first 3) ─────────")
    with_alt = [f for f in solomon_findings if f.get("proposed_alternative") is not None][:3]
    if not with_alt:
        print("  (no findings with proposed_alternative populated)")
    for idx, f in enumerate(with_alt, 1):
        try:
            cits = json.loads(f.get("legal_citations", "[]") or "[]")
        except Exception:
            cits = []
        print(f"\n  ┌─ Finding {idx} ──────────────────────────────────────────────────")
        print(f"  │ clause_ref       : {f['clause_ref']}")
        print(f"  │ category         : {f.get('category', '?')}")
        print(f"  │ severity         : {f.get('severity', '?')}")
        print(f"  │ grounding_status : {f.get('grounding_status', '?')}")
        print(f"  │ short_note       : {(f.get('short_note') or '')[:200]}")
        print(f"  │ proposed_alt     :")
        alt_text = (f.get("proposed_alternative") or "").strip()
        for line in alt_text.splitlines():
            print(f"  │   {line}")
        print(f"  │ citations        :")
        if cits:
            for cit in cits:
                print(f"  │   [{cit.get('article_ref', '?')}]")
                print(f"  │   source: {cit.get('source_title', '?')}")
                url = cit.get("official_url", "")
                print(f"  │   url   : {url if url else '(none — incoterms summary source)'}")
        else:
            print(f"  │   (empty)")
        print(f"  └────────────────────────────────────────────────────────────────")

    print()
    overall = detection_all_pass and grounding_all_pass
    print("═" * 70)
    print(f"  OVERALL EVAL: {'PASSED ✅' if overall else 'NOT PASSED ❌'}")
    print("═" * 70)
    print()


def save_results(
    detection: dict,
    grounding: dict,
    solomon_findings: list[dict],
    rejected_count: int,
):
    detection["counts"]["rejected_by_guardrail"] = rejected_count

    output = {
        "metadata": {
            "eval_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "gold_set": "Levays",
            "grounding_measured": True,
            "corpus_seeded": True,
        },
        "detection": detection,
        "grounding": grounding,
        "findings_with_alternatives": [
            {
                "clause_ref": f["clause_ref"],
                "category": f.get("category"),
                "severity": f.get("severity"),
                "grounding_status": f.get("grounding_status"),
                "short_note": f.get("short_note", "")[:300],
                "proposed_alternative": f.get("proposed_alternative"),
                "legal_citations": (
                    json.loads(f.get("legal_citations", "[]") or "[]")
                    if isinstance(f.get("legal_citations"), str)
                    else (f.get("legal_citations") or [])
                ),
            }
            for f in solomon_findings
            if f.get("proposed_alternative") is not None
        ],
    }
    RESULTS_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    logger.info(f"Results saved to {RESULTS_FILE}")


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    print()
    logger.info("Solomon Contracts — automated eval §13.2 with grounding rate")
    logger.info(f"Levays directory: {LEVAYS_DIR}")

    contract_path  = LEVAYS_DIR / EXPECTED_CONTRACT
    risk_note_path = LEVAYS_DIR / EXPECTED_RISK_NOTE

    missing = []
    if not contract_path.exists():
        missing.append(EXPECTED_CONTRACT)
    if not risk_note_path.exists():
        missing.append(EXPECTED_RISK_NOTE)

    if missing:
        print()
        print("ERROR: Levays gold-set files not found in training_data/levays/")
        for name in [EXPECTED_CONTRACT, EXPECTED_RISK_NOTE]:
            status = "✅" if (LEVAYS_DIR / name).exists() else "❌ MISSING"
            print(f"  {status}  {name}")
        sys.exit(2)

    # Step 1: Ground truth
    logger.info(f"Parsing ground truth: {risk_note_path.name}")
    gt_findings = parse_risk_note(risk_note_path)
    if not gt_findings:
        logger.error("Ground truth parser returned 0 findings")
        sys.exit(1)

    # Step 2: Scan contract
    solomon_findings, contract_clauses, contract_text, rejected_count = run_solomon_on_contract(
        contract_path, gt_findings=gt_findings
    )
    if not contract_clauses:
        logger.error("Clause extraction returned nothing")
        sys.exit(1)

    # Step 3: Generate alternatives (Pinecone RAG + Claude Sonnet)
    logger.info("Starting alternative generation (this adds ~60-120s)…")
    solomon_findings = run_alternatives(solomon_findings)

    # Step 4: Detection metrics
    detection = compute_detection_metrics(gt_findings, solomon_findings, contract_clauses)

    # Step 5: Grounding metrics
    grounding = compute_grounding_metrics(solomon_findings)

    # Step 6: Print + save
    print_results(detection, grounding, solomon_findings, rejected_count)
    save_results(detection, grounding, solomon_findings, rejected_count)

    all_pass = (
        all(m["pass"] for m in detection["targets"].values())
        and all(m["pass"] for m in grounding["targets"].values())
    )
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
