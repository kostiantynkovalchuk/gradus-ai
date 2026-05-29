# Solomon — Full Project Handover

**Date:** 2026-05-29  
**Stack:** FastAPI (Python 3.11) · PostgreSQL · Pinecone · Anthropic Claude · React/Vite  
**Repo root:** `/home/runner/workspace`  
**Deployment:** Render (Docker) — `https://gradus-ai.onrender.com`

---

## Part A — Solomon Court Search Bot

### What it is
Telegram bot (`@solomon_court_ua_bot`) for AVTD's law department.  
Users search Ukrainian Supreme Court cassation decisions in natural language.  
Claude Haiku parses the query → court-search-agent proxy returns candidates → Claude Haiku scores relevance → bot returns top results with inline like/dislike buttons.

### Auth
Phone-based whitelist. Table `solomon_whitelist (phone, name, added_by, created_at)`.  
Sessions tracked in `solomon_sessions`. Only phones in the whitelist can use the bot.

### DB tables (migrations 017, 019, 020, 048)
| Table | Purpose |
|---|---|
| `solomon_whitelist` | Authorised phones |
| `solomon_sessions` | Active user sessions |
| `solomon_search_log` | Every search query + parameters |
| `solomon_feedback` | Per-result like/dislike (unique per session+doc) |
| `solomon_scorer_log` | Audit log for Layer 2 post-fetch scorer exclusions |

### Pipeline (two layers)

**Layer 1 — Query parsing (Claude Haiku prompt)**  
Prompt was tuned to eliminate the "рішення" colloquial trap (users say "рішення" but mean "ухвала"), excludes ухвали by default, and includes 4 worked examples.

**Layer 2 — Post-fetch Haiku scorer**  
Fetches 15 candidates from court-search-agent, scores relevance 0–10 + classifies substantive/procedural. Returns top N with score ≥ 6 that are substantive. Graceful degradation: if scorer fails, falls back to unscored results. Exclusions are logged to `solomon_scorer_log` for future classifier tuning.

### Analytics endpoint
`GET /law/analytics/data` — feedback analytics (likes/dislikes per query, per document).

### Webhook
Handled inside `backend/routes/telegram_webhook.py` — search is triggered from the existing HR-bot webhook infrastructure. The Solomon search does NOT use its own bot token; it shares the webhook routing.

### Frontend
`/law` page (React) — two tabs:
- Tab 1: **Пошук рішень** (Court search)
- Tab 2: **Договори поставки** (Solomon Contracts — see Part B)

Tab state via `?tab=contracts` query param.

---

## Part B — Solomon Contracts

### What it is
AI-powered supply contract risk analysis tool for AVTD's law department.  
Upload a contract bundle → Claude Sonnet scans for supplier-asymmetric risks → Pinecone RAG grounds alternative wordings in Ukrainian law → DOCX outputs (risk note, protocol of disagreements, legal opinion).

### URL / Auth
- Frontend tab: `/law?tab=contracts`  
- API prefix: `/api/contracts/*`  
- Auth: cookie `solcon_auth=<base64(solomon:gradus2026)>` OR `Authorization: Basic ...`  
- Env bypass for dev: `SOLCON_AUTH_BYPASS=true`

---

## Module Structure

```
backend/solomon_contracts/
├── __init__.py
├── analyzer.py      # §7.2 scan + §7.3 alternatives + §9.2 legal opinion (Claude Sonnet)
├── artifacts.py     # DOCX builders: risk note, protocol, legal opinion
├── citation_filter.py  # Phase 5: validates citations against approved KB registry
├── corpus.py        # Pinecone ingest + retrieval (chunking, embedding, namespaces)
├── db.py            # Thin psycopg2 wrapper (fetchone/fetchall/execute/log_*)
├── eval.py          # Eval harness (precision/recall against lawyer judgments)
├── ingestion.py     # File parsing: DOCX/DOC/PDF/ZIP → raw_text + clause list
├── kb_ingest.py     # Law ingestion helpers (fetch from zakon.rada.gov.ua)
├── kb_sources.py    # get_active_kb_sources() — 5-min cached registry helper
└── router.py        # All FastAPI endpoints
```

---

## Database Schema (migration 041 + amendments)

All tables prefixed `solcon_`. All use BigInt PKs, `created_at`/`updated_at` timestamps.

### `solcon_engagements`
Master record per counterparty deal.
```
id, name, counterparty_name, our_entity (default 'AVTD'),
buyer_profile_id → solcon_buyer_profiles,
engagement_date, created_by, created_at, updated_at,
status CHECK IN (triage, under_review, protocol_drafted, protocol_sent,
                 counterparty_responded, agreed, declined, archived,
                 analysis_failed),
avtd_role CHECK IN (supplier, buyer)   ← required before exporting protocol
```

### `solcon_documents`
One row per uploaded file within an engagement.
```
id, engagement_id → solcon_engagements,
document_type CHECK IN (main_contract, additional_agreement, commercial_code,
                        specification, price_list, schedule, risks_note,
                        legal_opinion, protocol_draft, protocol_returned,
                        protocol_agreed, other),
original_filename, mime_type, storage_path,
raw_text TEXT,           ← extracted plain text
clauses JSONB,           ← [{ref, text}, …] parsed clause refs
extraction_method,       ← 'docx' | 'pdfplumber' | 'ocr' | 'antiword' | etc.
ocr_status,              ← null | 'pending' | 'running' | 'done' | 'failed'
ocr_current_page, ocr_total_pages,
analyzed_at, created_at, updated_at,
parent_document_id → solcon_documents   ← for appendix relationships
```

### `solcon_findings`
One row per detected risk clause.
```
id, document_id, engagement_id,
clause_ref TEXT,             ← e.g. "п.9.3–9.12"
clause_text TEXT,            ← verbatim excerpt ≤500 chars
category CHECK IN (penalty, payment_terms, liability_shift, ip_rights,
                   force_majeure, termination, returns_refusal, audit_rights,
                   set_off, tax_invoicing, quality_acceptance, delivery_terms, other),
severity CHECK IN (low, medium, high, critical),
monetary_exposure_uah NUMERIC,
short_note TEXT,             ← 1-2 sentence Ukrainian summary
proposed_alternative TEXT,   ← Sonnet + RAG output (medium/high/critical only)
grounding_status CHECK IN (grounded, ungrounded, not_applicable,
                            awaiting_incoterms_primary_source, out_of_approved_kb),
legal_citations JSONB,       ← [{article_ref, official_url, source_title}, …]
workflow_state CHECK IN (triage, included_in_protocol, excluded,
                          sent_to_counterparty, counterparty_accepted,
                          counterparty_rejected, counterparty_modified, agreed),
detected_by TEXT,            ← 'llm_scan'
confidence FLOAT,
lawyer_notes TEXT,
lawyer_judgment CHECK IN (accepted, rejected, modified_minor, modified_major, not_reviewed),
citation_filter_failed BOOL  ← true if Phase 5 filter raised exception
```

### `solcon_protocols`
Generated protocol DOCX record per document.
```
id, document_id, engagement_id, version INT,
finding_ids JSONB,           ← [id, …] of included findings
docx_storage_path TEXT,
generated_by, generated_at
UNIQUE (document_id, version)
```

### `solcon_legal_opinions`
Generated legal opinion per engagement.
```
id, engagement_id, version INT,
content_md TEXT,             ← Sonnet markdown output
docx_storage_path TEXT,
generated_by, generated_at
UNIQUE (engagement_id, version)
```

### `solcon_corpus_sources` (superseded by `solomon_kb_sources`)
Legacy table — still exists in schema but the live registry is now `solomon_kb_sources`.

### `solomon_kb_sources` (migration 051)
Single source of truth for all approved laws in the Pinecone corpus.
```
id, law_code TEXT UNIQUE,    ← e.g. 'TsKU', 'GKU', 'ZUPro_ZnSp'
law_name TEXT,
canonical_url TEXT,          ← zakon.rada.gov.ua base URL (no /print1 suffix)
article_ranges JSONB,        ← [[from, to], …] filter applied at ingest time
sub_article_filter JSONB,    ← {art_num: [sub_ids]} e.g. {14: ["14.1.54", …]}
current_edition_date DATE,   ← last known Ukrainian amendment date
current_edition_basis TEXT,  ← law that amended it
last_verified_at TIMESTAMP,
status CHECK IN (active, awaiting_source, deprecated),
pinecone_prefix TEXT,        ← vector ID prefix used at ingest (corpus_{id}_*)
notes TEXT,
created_at, updated_at
```
**20 seed rows** in migration 051 covering: ЦКУ (Civil Code), ГКУ (Commercial Code), 
ЗУ "Про захист прав споживачів", ЗУ "Про ЗЕД", ЗУ "Про захист від недобросовісної конкуренції", 
INCOTERMS 2020 (PDF), INCOTERMS 2020 summary (HDI card), ЗУ "Про електронну комерцію", 
ЗУ "Про платіжні послуги", ЗУ "Про товари з підробленими марками", ПКУ Art 14 (sub-article filter),
and others. Total approved corpus: **1028 chunks** in `solomon-contracts-corpus` Pinecone namespace.

### `solomon_kb_source_history` (migration 051)
Audit log for edition changes to `solomon_kb_sources`.

### `solcon_citation_filter_log` (migration 051)
Per-finding log of citations dropped by Phase 5 filter.
```
id, finding_id → solcon_findings, original_citations JSONB,
filtered_citations JSONB, dropped_citations JSONB, created_at
```

### `solcon_llm_audit`
Every LLM API call with token counts and duration.
```
id, engagement_id, document_id, mode (scan/alternative/opinion),
model, input_tokens, output_tokens, duration_ms, result_status, created_at
```

### `solcon_retrieval_audit`
RAG retrieval audit per finding.
```
id, finding_id, query_hash, top_k_results JSONB, used_citations JSONB, created_at
```

### `solcon_eval_judgments`
Lawyer verdicts for eval harness.
```
id, finding_id, judgment CHECK IN (true_positive, false_positive,
                                    wrong_category, wrong_severity),
judged_by, notes, created_at
UNIQUE (finding_id)
```

### `solcon_buyer_profiles`
Reusable counterparty CRM.
```
id, buyer_name, legal_entity, edrpou, notes, created_at
```

### `solcon_templates` (stub)
Document templates — schema created, not yet populated.

---

## API Reference (`/api/contracts/*`)

### Engagements
| Method | Path | Description |
|---|---|---|
| GET | `/engagements` | List all with doc/finding counts |
| POST | `/engagements` | Create (name, counterparty_name, our_entity, buyer_profile_id) |
| GET | `/engagements/{eid}` | Full detail: docs + findings + severity_summary + latest_opinion |
| PATCH | `/engagements/{eid}/status` | Update status (triage→agreed etc.) |
| PATCH | `/engagements/{eid}` | Update fields — currently only `avtd_role` |

### Documents
| Method | Path | Description |
|---|---|---|
| POST | `/engagements/{eid}/upload` | Upload file (DOCX/DOC/PDF/ZIP/XLSX). ZIP auto-extracted. |
| PATCH | `/engagements/{eid}/documents/{did}/type` | Change document_type |
| POST | `/engagements/{eid}/documents/{did}/re-extract` | Re-run text extraction + clause parse |
| GET | `/engagements/{eid}/documents/{did}/ocr-status` | Poll OCR progress (3s interval) |
| DELETE | `/engagements/{eid}/documents/{did}` | Delete doc + file + findings |

### Analysis
| Method | Path | Description |
|---|---|---|
| POST | `/engagements/{eid}/analyze` | Start background analysis (202 pattern) |

### Findings
| Method | Path | Description |
|---|---|---|
| PATCH | `/findings/{fid}/state` | Update workflow_state |
| PATCH | `/findings/{fid}/judgment` | Lawyer judgment (accepted/rejected/modified_*) |
| POST | `/findings/{fid}/judge` | Eval harness verdict (true_positive/false_positive/…) |

### Artifacts (DOCX downloads)
| Method | Path | Description |
|---|---|---|
| GET | `/engagements/{eid}/risk-note.docx` | Risk note — all findings, bullet list |
| GET | `/engagements/{eid}/documents/{did}/protocol.docx` | 4-col protocol (requires avtd_role set) |
| POST | `/engagements/{eid}/legal-opinion` | Generate legal opinion → returns markdown + version |
| GET | `/engagements/{eid}/legal-opinion/{version}.docx` | Download generated opinion |

### Corpus Admin (background jobs, 202 + polling)
| Method | Path | Description |
|---|---|---|
| GET | `/admin/corpus/sources` | All KB sources (active + deprecated) |
| POST | `/admin/corpus/sources/{id}/verify` | Mark source last_verified_at = now |
| POST | `/admin/corpus/ingest-law` | Ingest law text → Pinecone (async job) |
| POST | `/admin/corpus/ingest-incoterms` | Ingest INCOTERMS PDF (async job) |
| POST | `/admin/corpus/ingest-incoterms-summary` | Ingest HDI summary card |
| POST | `/admin/corpus/rebuild` | Rebuild entire namespace (async job) |
| POST | `/admin/corpus/seed-sources` | Insert all 20 seed rows |
| GET | `/admin/corpus/jobs/{id}` | Poll job status |
| GET | `/admin/corpus/sanity` | Run 5 sanity queries against Pinecone |
| GET | `/admin/eval/metrics` | Precision/recall/grounding rate |

### Buyers
| Method | Path | Description |
|---|---|---|
| GET | `/buyers` | All buyer profiles |
| POST | `/buyers` | Create buyer profile |

---

## Analysis Pipeline (step by step)

```
POST /engagements/{eid}/analyze
  └── _run_analysis()  [asyncio background task]
        └── _analyze_one_document() [run_in_executor → thread]
              ├── 1. scan_document()           [analyzer.py §7.2]
              │     ├── Claude Sonnet: SCAN_SYSTEM prompt
              │     ├── Guardrail §10.1: clause_ref must exist in parsed clauses
              │     └── _remove_subsumed_findings(): collapse range-covered sub-clauses
              ├── 2. generate_alternatives()   [analyzer.py §7.3]
              │     ├── For severity ∈ {medium, high, critical}:
              │     │     ├── retrieve_similar() → Pinecone top_k=5
              │     │     └── Claude Sonnet: ALT_SYSTEM + retrieved sources
              │     └── Guardrail §10.2: citation URL must match GROUNDED_URL_RE
              ├── 3. filter_citations()        [citation_filter.py Phase 5]
              │     └── Drop citations not in solomon_kb_sources (active)
              └── 4. INSERT into solcon_findings with final grounding_status
```

---

## Key Business Rules in Analyzer Prompt

### §7.2 Scan system prompt hard rules
1. Must cite a specific clause number — if not found in contract, finding is invalid
2. Proposed alternatives must cite a Ukrainian legal source or INCOTERMS article
3. Never quote > 25 words verbatim (paraphrase)
4. Each clause cited at most once (highest severity category wins)

### Asymmetry threshold
Only report clauses that impose a burden on the SUPPLIER that does NOT apply to the BUYER.  
Standard FMCG commercial terms are explicitly excluded from flagging.

### Special patterns (high recall targets)
- **A. One-sided penalty block:** report as range `9.3–9.12` (never individual sub-clauses)
- **B. Unlimited returns:** `returns_refusal/critical`
- **C. Unilateral set-off:** automatic buyer deduction without notice → `set_off`
- **D. Termination lock:** clause 12.2 limiting supplier's exit rights → `termination/high`

### Severity definitions
- `critical`: unbounded liability, >100K UAH, or automatic termination trigger
- `high`: 25–100% batch cost penalty, one-sided termination, rights-stripping
- `medium`: <25% batch cost penalty, meaningful operational burden
- `low`: minor administrative asymmetry

### Precision target
6–10 findings is optimal. >12 findings means over-flagging.

---

## Artifact Formats

### Risk note DOCX (`§9.1`)
Informal internal document. Grouped by document → category → bullet list.  
Each bullet: `[clause_ref] [SEVERITY] [Category] short_note (≈UAH)`  
AI proposal indented as sub-bullet.  
Footer: disclaimer.

### Protocol DOCX (`§9.3`)
Counterparty-facing negotiation table, 4 columns:  
`№ | Редакція {Buyer/Supplier} | Редакція {AVTD} | Узгоджена редакція`  
Column widths: 454 + 3200 + 3200 + 2506 DXA (fits A4).  
**Requires `avtd_role` set on engagement** — raises 400 otherwise.  
AI tag stripped from both columns. Clause ref bolded in col 1.  
No AI disclaimer in this document (internal-only disclaimer kept in risk note and opinion).

### Legal Opinion DOCX (`§9.2`)
Formal Ukrainian legal counsel structure.  
Claude Sonnet generates markdown → `build_opinion_docx()` converts to DOCX.  
Includes "Правова база" appendix table: 3 columns (law name | edition | last verified).  
Edition and verification dates pulled from `solomon_kb_sources` via 5-min cached helper.  
Footer: `"Автоматичний аналіз Solomon. Підлягає перевірці юристом. Не є юридичною консультацією."`

---

## Pinecone Configuration

| Key | Value |
|---|---|
| Index | `gradus-media` (shared with other system features) |
| Corpus namespace | `solomon-contracts-corpus` |
| Findings namespace | `solomon-contracts-findings` |
| Embed model | `text-embedding-3-small` (1536-dim) |
| Chunk size | ≤ 800 words |
| Current corpus size | 1028 chunks |

### Chunking strategy
- **Ukrainian laws:** split by `Стаття N` boundaries → article-range filter → sub-article filter for dense articles (e.g. ПКУ Art 14 with 200+ sub-articles)
- **INCOTERMS PDF:** split by rule code (EXW, FCA, CPT, …)
- **INCOTERMS summary:** one chunk per rule code (12 chunks), `source_type='incoterms_2020_summary'`
- **Oversized articles:** numbered sub-paragraphs → blank-line split → word-count split (in that order)

### Citation grounding levels
| `grounding_status` | Meaning |
|---|---|
| `grounded` | Citations found and URL-validated |
| `ungrounded` | No valid citations found |
| `not_applicable` | Severity is `low` — alternatives not generated |
| `awaiting_incoterms_primary_source` | Only summary card available; A-article detail needed |
| `out_of_approved_kb` | All citations dropped by Phase 5 filter |

---

## Ingestion Pipeline

**File types supported:**  
- `.docx` → python-docx  
- `.doc` → antiword → LibreOffice headless → python-docx (fallback chain)  
- `.pdf` (text-based) → pdfplumber  
- `.pdf` (scanned) → OCR via `ocr:pending` flow (background thread, polls via `ocr-status`)  
- `.xlsx` → openpyxl  
- `.zip` → extracted, each file processed individually  

**Clause parsing:**  
Regex `CLAUSE_RE` matches `п.N.N.N`, `N.N.N`, `Розділ N`, `Додаток N`.  
Fallback `scan_all_refs()` for non-standard documents.

**Document classification (Claude Haiku):**  
Filename regex hints first; falls back to `HAIKU` classification for ambiguous files.

**Storage:** `backend/solomon_uploads/{eid}/` (configurable via `SOLCON_UPLOAD_DIR`).

---

## Eval Harness

Access at `?tab=contracts&view=admin/eval`.  
API endpoint: `GET /api/contracts/admin/eval/metrics`  

Metrics:
- **Precision** = true_positive / (true_positive + false_positive) → target ≥ 0.75
- **Recall** = true_positive / (true_positive + wrong_category + wrong_severity) → target ≥ 0.70
- **Grounding rate** = grounded findings / total findings → target ≥ 0.60

Lawyer judgment recorded via `PATCH /findings/{fid}/judgment` or `POST /findings/{fid}/judge`.

---

## INCOTERMS 2020 Summary Handling

The system has a special source type `incoterms_2020_summary` (HDI Global SE summary card).  
This is **not** the official ICC primary source.

**What it covers:** rule codes, risk-transfer points, mode-of-transport selection.  
**What it does NOT cover:** A1-A10 / B1-B10 obligation text.

When the alt generator uses this source:
- General rule recommendation → `grounded` is valid
- A-article / B-article obligation detail needed → `awaiting_incoterms_primary_source`
- Every citation must include: `"per INCOTERMS 2020 summary (HDI Global SE). Full rule text should be consulted before adoption."`

---

## Environment Variables

| Variable | Used by | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | analyzer.py | Sonnet for scan + alt + opinion, Haiku for classification |
| `OPENAI_API_KEY` | corpus.py | text-embedding-3-small |
| `PINECONE_API_KEY` | corpus.py | Pinecone index access |
| `PINECONE_INDEX_NAME` | corpus.py | Default: `gradus-media` |
| `DATABASE_URL` | db.py | Falls back to `NEON_DATABASE_URL` |
| `SOLCON_UPLOAD_DIR` | ingestion.py | Default: `backend/solomon_uploads/` |
| `SOLCON_AUTH_BYPASS` | router.py | Set `true` for dev |

---

## Migration Index (Solomon-related only)

| Migration | Tables / Changes |
|---|---|
| 017 | `solomon_whitelist`, `solomon_sessions`, `solomon_search_log` |
| 019 | `solomon_feedback` |
| 020 | Adds `search_log_id`, `query_text`, `search_params` to `solomon_feedback` |
| 041 | All 11 `solcon_*` tables (core schema) |
| 048 | `solomon_scorer_log` |
| 051 | `solomon_kb_sources`, `solomon_kb_source_history`, `solcon_citation_filter_log`; adds `citation_filter_failed` to `solcon_findings`; 20 seed rows |

---

## Known Design Decisions & Gotchas

1. **`solcon_contracts` DB module uses its own `psycopg2.connect()` on every call** — not FastAPI dependency injection. This is intentional (isolated connection pool for long-running background jobs) but means no SQLAlchemy session sharing.

2. **`solcon_corpus_sources` vs `solomon_kb_sources`:** The original table (`solcon_corpus_sources`) is still in the schema but is not used for citation filtering or DOCX edition rendering. All live logic uses `solomon_kb_sources`. Do not confuse them.

3. **Protocol requires `avtd_role` on the engagement** — if not set, `build_protocol_docx()` raises `ValueError` and the endpoint returns 400. Must call `PATCH /engagements/{eid}` with `{"avtd_role": "supplier"|"buyer"}` first.

4. **`_set_table_fixed_layout()` in `artifacts.py`** uses `find(qn('w:tblPr')) + manual insert` instead of `get_or_add_tblPr()` — the latter does not exist on `CT_Tbl`. This was a bug fixed in a previous session.

5. **Subsumed findings filter** (`_remove_subsumed_findings`): if a range finding (e.g. `9.3–9.12`) exists, any individual sub-clause finding (e.g. `9.6`) inside that range is automatically removed post-scan. This enforces the "one finding per penalty block" rule.

6. **Citation filter fallback:** if `filter_citations()` raises, `citation_filter_failed=True` is stored and the raw (unfiltered) citations are persisted — never silently drops data on filter error.

7. **Async pattern for analysis:** `POST /analyze` returns immediately; actual work runs in `asyncio.create_task()`. There is no job-polling endpoint for analysis (unlike corpus jobs which use the 202 + `_corpus_jobs` dict pattern). The frontend polls `GET /engagements/{eid}` to detect completion via `analyzed_at` on documents.

8. **OCR status polling:** scanned PDFs set `ocr_status='pending'`, launch a background thread, and the frontend polls `GET /engagements/{eid}/documents/{did}/ocr-status` every 3 seconds.

9. **INCOTERMS official_url:** for `incoterms_2020_summary` source type, `official_url` is always `""` (empty string) — no canonical URL exists for the summary card. The citation URL validator (`GROUNDED_URL_RE`) does not reject empty URLs.

10. **Eval harness access:** `?tab=contracts&view=admin/eval` — no separate auth, uses same `solcon_auth` cookie.

---

## Phase Status

| Phase | Description | Status |
|---|---|---|
| 1 | Core schema + upload + scan + DOCX artifacts | ✅ Complete |
| 2 | UI built (engagement list, document upload, findings table, DOCX download) | ✅ Complete |
| 3 | Corpus seeded (1028 chunks, 15 laws + INCOTERMS) | ✅ Complete |
| 4 | RAG-grounded alternatives + legal opinion | ✅ Complete |
| 5 | Citation filter (Phase 5) | ✅ Complete |
| 6 (P1) | `solomon_kb_sources` registry + `get_active_kb_sources()` | ✅ Complete (migration 051) |
| 6 (P5) | Citation filter wired to registry | ✅ Complete |
| 6 (P7) | Legal opinion DOCX "Правова база" appendix with edition dates | ✅ Complete |
| P2 | Pinecone unknown source_id audit | Planned |
| P3 | Corpus cleanup (delete unauthorized chunks) | Planned |
| P4 | Ingest 13 missing approved laws | Planned |
| P6 | Edition actualization cron (`kb_edition_check.py`) | Planned |

---

## Files Quick Reference

| File | Lines | Role |
|---|---|---|
| `backend/solomon_contracts/analyzer.py` | 555 | Claude prompts + guardrails |
| `backend/solomon_contracts/router.py` | 1164 | All FastAPI endpoints |
| `backend/solomon_contracts/artifacts.py` | 597 | DOCX generation |
| `backend/solomon_contracts/corpus.py` | ~600 | Pinecone + chunking |
| `backend/solomon_contracts/ingestion.py` | 651 | File parsing + OCR |
| `backend/solomon_contracts/db.py` | 72 | DB wrapper |
| `backend/solomon_contracts/kb_sources.py` | 45 | Registry cache helper |
| `backend/solomon_contracts/citation_filter.py` | 95 | Phase 5 filter |
| `backend/solomon_contracts/eval.py` | — | Eval metrics |
| `backend/db_migrations.py` | — | Migrations 017/019/020/041/048/051 |
