# Solomon Contracts — Law Director Feedback v2 — Pre-flight Audit

**Date:** 2026-05-18  
**Prepared by:** Solomon automated audit  
**Branch:** `feat/law-director-v2`  
**Status:** Awaiting law director sign-off before Workstream B proceeds.

---

## 0.1 — Laws in the Corpus

**Pinecone index:** `gradus-media`  
**Namespace:** `solomon-contracts-corpus`  
**Total vectors in namespace:** 1 042  
**Metadata URL field:** `official_url` (NOT `source_url` — the chunk schema uses `official_url`; update any tooling that references `source_url`)

The 15 approved sources are defined in `backend/solomon_contracts/router.py → LAW_SOURCES[]`. Chunk IDs follow the pattern `corpus_{source_id}_{chunk_index}`. Source IDs are DB-assigned at ingest time; chunk counts below are derived from the LAW_SOURCES whitelist and the total vector count (1 042 = all 15 laws + INCOTERMS summary scaffold).

| # | law_name | official_url | article_filter | notes |
|---|---|---|---|---|
| 1 | Цивільний кодекс України | zakon.rada.gov.ua/laws/show/435-15 | Arts 3-21, 202-241, 509-558, 610-654, 655-726, 901-966 | **BIG CODE** — whitelisted ranges |
| 2 | Господарський кодекс України | zakon.rada.gov.ua/laws/show/436-15 | Arts 173-199, 200-212, 230-241, 264-291 | **BIG CODE** — whitelisted ranges; ⚠ SEE §0.2 |
| 3 | Податковий кодекс України | zakon.rada.gov.ua/laws/show/2755-17 | Art 14 (12 sub-articles), Arts 134-141, 185-201 | **BIG CODE** — whitelist + sub-article filter |
| 4 | ЗУ «Про захист прав споживачів» | zakon.rada.gov.ua/laws/show/1023-12 | None — whole doc | — |
| 5 | ЗУ «Про основні принципи...харчових продуктів» | zakon.rada.gov.ua/laws/show/771/97-вр | None — whole doc | — |
| 6 | ЗУ «Про інформацію для споживачів...харчових продуктів» | zakon.rada.gov.ua/laws/show/2639-19 | None — whole doc | **[UNVERIFIED URL]** |
| 7 | ЗУ «Про держ. регулювання...алкогольних напоїв» | zakon.rada.gov.ua/laws/show/481/95-вр | None — whole doc | — |
| 8 | ЗУ «Про товариства з обмеженою...відповідальністю» | zakon.rada.gov.ua/laws/show/2275-19 | None — whole doc | — |
| 9 | ЗУ «Про електронні документи та документообіг» | zakon.rada.gov.ua/laws/show/851-15 | None — whole doc | — |
| 10 | ЗУ «Про авторське право і суміжні права» | zakon.rada.gov.ua/laws/show/3792-12 | None — whole doc | **[UNVERIFIED URL]** |
| 11 | ЗУ «Про рекламу» | zakon.rada.gov.ua/laws/show/270/96-вр | None — whole doc | — |
| 12 | ЗУ «Про захист від недобросовісної конкуренції» | zakon.rada.gov.ua/laws/show/236/96-вр | None — whole doc | — |
| 13 | ЗУ «Про захист економічної конкуренції» | zakon.rada.gov.ua/laws/show/2210-14 | None — whole doc | — |
| 14 | ЗУ «Про бухгалтерський облік та фін. звітність» | zakon.rada.gov.ua/laws/show/996-14 | None — whole doc | — |
| 15 | Постанова КМУ №187 «Про захист нац. безпеки...» | zakon.rada.gov.ua/laws/show/187-2022-п | None — whole doc | — |

**Additional chunks:** INCOTERMS 2020 summary (HDI Global SE) — `source_type=incoterms_2020_summary` — no canonical zakon.rada.gov.ua URL.

**Metadata gap:** Chunks do NOT carry `first_ingested_at` or `edition_date` metadata fields. These fields are required by Workstream B (`solomon_kb_sources`) and Workstream D (edition actualization). They will be populated via Workstream B's backfill script.

**Two unverified URLs** flagged in code comments (laws #6 and #10). Konstantin must confirm with the law director.

---

## 0.2 — Is ГК (Господарський кодекс) in the Corpus?

**Answer: YES — confirmed smoking gun.**

A real-embedding query (`text-embedding-3-small`, query: "господарський кодекс поставка договір") returned ГК chunks from the namespace. Confirmed chunk examples:

| vector_id | official_url | article_ref |
|---|---|---|
| corpus_2_9 | https://zakon.rada.gov.ua/laws/show/436-15/print1 | Ст. 181 |
| corpus_2_11 | https://zakon.rada.gov.ua/laws/show/436-15/print1 | Ст. 183 |
| corpus_2_53 | https://zakon.rada.gov.ua/laws/show/436-15/print1 | Ст. 265 |

ГК chunks are identifiable by `official_url` containing `436-15`. The ingested article ranges are **Arts 173–199, 200–212, 230–241, 264–291** (see `LAW_SOURCES` entry #2 in router.py).

**Action required (Workstream B):** After the law director confirms ГК is not in the approved list, all `corpus_2_*` vectors must be removed from the namespace. Script `backend/scripts/delete_orphan_chunks.py` will execute this after review of `backend/audits/orphan_chunks_{date}.csv`.

---

## 0.3 — Where Do ГК Citations Originate?

**Query:** `solcon_findings` WHERE `legal_citations::text ILIKE '%436-15%' OR ILIKE '%господарськ%'`

**Result: 11 findings** cite Господарський кодекс. All have `grounding_status = 'grounded'`.

| finding_id | clause_ref | ГК articles cited | grounding_status |
|---|---|---|---|
| 2 | 9.3 | Ст. 231 | grounded |
| 7 | 9.8 | Ст. 265 | grounded |
| 11 | 7.2 | Ст. 231 | grounded |
| 12 | 7.14 | Ст. 232, 233 | grounded |
| 13 | 11.3 | Ст. 188, 206 | grounded |
| 15 | 5.7 | Ст. 268, 269 | grounded |
| 21 | 4.15 | Ст. 268 | grounded |
| 35 | 3.3 | Ст. 216, 268 | grounded |
| 42 | п.9.3–п.9.12 | Ст. 231, 232, 233 | grounded |
| 47 | п.3.4 | Ст. 268 | grounded |
| 51 | 9.3–9.12 | Ст. 231, 232, 233 | grounded |

**Retrieval trace status:** `solcon_retrieval_audit` table has **0 rows**. The `log_retrieval()` function is defined in `backend/solomon_contracts/db.py` but is NOT called anywhere in the current analyzer path. Per-finding retrieval chains are not persisted.

**Root cause assessment:**

Since ГК chunks ARE present in the corpus (confirmed §0.2) and all 11 findings are `grounded`, the primary cause is **corpus inclusion**: the model retrieved ГК chunks and correctly cited them. This is not primarily prompt leakage — it is a data problem.

However, because retrieval audit is empty, we cannot rule out a secondary prompt-leakage component. The grounding labelling in the current system is `grounded`/`ungrounded` (set by the analyzer) — not a verified retrieval hit. The labelling is self-reported by the LLM, not cross-validated against Pinecone retrieval results.

**Recommendation for Workstream C:** Before the citation filter ships, also wire up `log_retrieval()` into the analyzer call path so future audits can distinguish retrieval-grounded vs prior-grounded citations.

**Note on `grounding_status` values:** The current DB CHECK constraint allows: `grounded`, `ungrounded`, `not_applicable`, `awaiting_incoterms_primary_source`. The spec (Workstream C §C.5) references values `retrieved`, `no_basis_found` — these do NOT exist in the current schema. Migration 052 must enumerate and preserve ALL existing values before adding `out_of_approved_kb`.

---

## 0.4 — Protocol DOCX: Current Column Structure

**Builder location:** `backend/solomon_contracts/artifacts.py` → `build_protocol_docx()` (line 176)  
**Called from:** `backend/solomon_contracts/router.py` → `POST /api/contracts/engagements/{eid}/documents/{did}/protocol` (line 641)

**Current column structure (5 columns):**

| col | header | data source | width |
|---|---|---|---|
| 0 | Пункт договору | `finding["clause_ref"]` | auto (not set) |
| 1 | Редакція Покупця | `finding["clause_text"]` | auto |
| 2 | Редакція Постачальника | `finding["proposed_alternative"]` or `short_note` — AI-cleaned via `_protocol_clean()` | auto |
| 3 | Правова підстава | `finding["legal_citations"]` JSONB → formatted via `_format_citations_docx()` | auto |
| 4 | Узгоджена редакція | `""` (empty) | auto |

**Column order matches spec's description:** ✓ (`Пункт договору / Редакція Покупця / Редакція Постачальника / Правова підстава / Узгоджена редакція`)

**Issues confirmed:**
1. No explicit column widths — all auto-sized by Word engine. Column 4 (Узгоджена редакція) frequently truncates.
2. `"AVTD виступає Постачальником."` is **hardcoded** (line 197). No `avtd_role` on the engagement record.
3. `Правова підстава` (col 3) exposes internal legal citations to the counterparty — must be dropped from the protocol per law director instruction.
4. AI marker `[AI пропозиція — потребує перевірки юриста]` stripped from col 2 (supplier) via `_protocol_clean()` but col 1 (buyer's verbatim `clause_text`) passes through without cleaning.
5. No DOCX column width control — python-docx table created without `set_col_width`.

**Legal opinion DOCX regression check:** `build_opinion_docx()` in the same file does NOT use `build_protocol_docx()` — it is a separate builder. Workstream A changes to the protocol builder will NOT affect the legal opinion output.

---

## Summary — Actions Required Before Workstream B

| Item | Action | Workstream |
|---|---|---|
| ГК chunks in corpus | Remove after law director approves final list | B |
| 2 unverified URLs (laws #6, #10) | Confirm canonical URLs with law director | B |
| No `edition_date` metadata on chunks | Add via Workstream D ingestion + B backfill | B/D |
| `retrieval_audit` not populated | Wire `log_retrieval()` into analyzer path | C |
| `grounding_status` values mismatch spec | Capture exact current values before migration 052 (done: `grounded`, `ungrounded`, `not_applicable`, `awaiting_incoterms_primary_source`) | C |
| 5-column protocol DOCX | Restructure 5 → 4 columns | **A — shipped** |
| Hardcoded `avtd_role='supplier'` | `avtd_role` column + dynamic headers | **A — shipped** |

**Workstream A is shipped in this PR.** Workstreams B, C, D await law director sign-off on the approved law list.
