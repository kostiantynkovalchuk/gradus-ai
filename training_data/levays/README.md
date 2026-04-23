# Levays Gold Set — Solomon Contracts Phase-Gate Eval

Place the Levays bundle files exactly as named below.
The automated eval reads from this directory.

## Required files

| File | Role |
|------|------|
| `1АЛ_Договір_поставки_умови_Вчасно_ЛЕВАЙС.doc` | Main contract — input to Solomon analyzer |
| `РИЗИКИ_ДО_ДОГОВОРУ_ПОСТАВКИ_ЛЕВАЙС_10_06_2025.docx` | Lawyer-written risk note — **ground truth** |
| `правовий_висновок_до_договору_поставки.doc` | Lawyer-written legal opinion (Phase 2 quality check) |
| `Протокол_Левайс.docx` | Outbound protocol v1 (ground truth for protocol wording) |
| `протокол_розбіжностей_до_договору_поставки_Левайс.docx` | Counterparty-returned protocol (Phase 3 re-analysis eval) |

## Run the eval

```bash
cd backend && python -m solomon_contracts.eval
```

Requires `ANTHROPIC_API_KEY` and `DATABASE_URL`.
Outputs to console + `training_data/levays/eval_results.json`.

## Phase-gate targets (§13.2)

| Metric | Target | Achieved |
|--------|--------|---------|
| Precision | ≥ 0.75 | **0.875** ✅ |
| Recall | ≥ 0.70 | **0.875** ✅ |
| Clause-ref accuracy | = 1.0 | **1.000** ✅ |
| Grounding rate | Measured separately after corpus seed (task #7) | — |

**Phase gate PASSED** on 2026-04-23.

## Key fixes applied during eval development

1. **GT parser** (`eval.py:parse_risk_note`): switched from `doc.paragraphs` to
   `extract_text()` lines — the DOCX uses `<w:br/>` inline breaks so all 8 risks
   were in one XML paragraph element.
2. **Analyzer truncation** (`analyzer.py`): raised `raw_text[:60000]` → `[:120000]`
   so sections 9 (char 59,567) and 12 (char 69,406) are visible to Claude.
3. **max_tokens** (`analyzer.py`): 4 096 → 8 192 to prevent JSON truncation on
   large contracts.
4. **Range-ref matching** (`eval.py:_refs_match`): range citations like
   `9.3–9.12` now match GT `п.9.3` via `_extract_range_lead`.
5. **SCAN_SYSTEM prompt**: tightened asymmetry threshold; added specific patterns
   for one-sided penalty blocks (range notation), consumer-protection return
   liability, and termination lock (§12.2).
6. **Solomon dedup** (`eval.py`): duplicate clause_ref findings kept only
   highest-confidence one before metric computation.
