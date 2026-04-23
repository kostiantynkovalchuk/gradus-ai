# Levays Gold Set — Solomon Contracts Phase-Gate Eval

Place the five Levays bundle files exactly as named below.
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

| Metric | Target |
|--------|--------|
| Precision | ≥ 0.75 |
| Recall | ≥ 0.70 |
| Clause-ref accuracy | = 1.0 |
| Grounding rate | Measured separately after corpus seed (task #7) |

Do not widen access to the law department until all targets are met.
If targets are unmet after 2–3 prompt iterations, stop and escalate.
