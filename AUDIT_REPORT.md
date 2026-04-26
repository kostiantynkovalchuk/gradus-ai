# Claude Model Audit Report
**Date:** 2026-04-26  
**Scope:** Live code only (`backend/`, `frontend/`) — `attached_assets/` excluded (historical prompt files, not executed)

---

## Summary

| Category | Count |
|---|---|
| Deprecated model strings (need migration) | **4** |
| Hardcoded current models (need centralization) | **5** |
| Deprecated beta headers (`context-1m`) | **0** ✅ |
| Claude refs in config/env/docs files | **0** ✅ |
| Frontend Claude refs | **0** ✅ |

**No `context-1m-2025-08-07` or `anthropic-beta` headers found anywhere in the live codebase.** Nothing to remove on that front.

---

## Section A — Deprecated Model Strings (MUST FIX before April 30)

### A1 — `backend/config/models.py` · Line 16
```
CLAUDE_MODEL_WEBSITE = "claude-sonnet-4-5-20250929"
```
**Replacement:** `"claude-sonnet-4-6"`  
**Risk:** MED — Used in website/client-facing chat (non-Alex path). Consumers:
- `backend/routes/chat_endpoints.py:377` — website channel chat responses

---

### A2 — `backend/solomon_contracts/analyzer.py` · Line 20
```
ANTHROPIC_SCAN_MODEL = "claude-sonnet-4-5"
```
**Replacement:** `"claude-sonnet-4-6"` (import `SONNET` from `ai_models.py`)  
**Risk:** HIGH — Contract document scanning. Called at lines 145, 153, 166, 175 in same file.

---

### A3 — `backend/solomon_contracts/analyzer.py` · Line 21
```
ANTHROPIC_ALT_MODEL = "claude-sonnet-4-5"
```
**Replacement:** `"claude-sonnet-4-6"` (import `SONNET` from `ai_models.py`)  
**Risk:** HIGH — Generates alternative contract wording with RAG grounding. Called at lines 327, 335, 342.

---

### A4 — `backend/solomon_contracts/analyzer.py` · Line 22
```
ANTHROPIC_OPINION_MODEL = "claude-sonnet-4-5"
```
**Replacement:** `"claude-sonnet-4-6"` (import `SONNET` from `ai_models.py`)  
**Risk:** HIGH — Generates legal opinion DOCX artifact. Called at lines 445, 456.

---

## Section B — Deprecated Beta Headers

**None found.** The `context-1m-2025-08-07` beta header is not present anywhere in the live codebase.  
No other `anthropic-beta` headers were found either.

---

## Section C — Hardcoded Current Models (LOW risk — centralize per Step 2)

These are already using the correct model strings but are hardcoded instead of imported from a central module. Should be refactored as part of the centralization step.

| File | Line | Current Value | Proposed Import |
|---|---|---|---|
| `backend/photo_report/vision.py` | 488 | `"claude-sonnet-4-6"` | `SONNET` from `ai_models` |
| `backend/solomon_search.py` | 85 | `"claude-haiku-4-5-20251001"` | `HAIKU` from `ai_models` |
| `backend/solomon_search.py` | 247 | `"claude-haiku-4-5-20251001"` | `HAIKU` from `ai_models` |
| `backend/solomon_contracts/ingestion.py` | 157 | `"claude-haiku-4-5-20251001"` | `HAIKU` from `ai_models` |
| `backend/services/api_token_monitor.py` | 108 | `"claude-haiku-4-5-20251001"` | `HAIKU` from `ai_models` |

> **Note:** `backend/solomon_contracts/ingestion.py:175` passes the model string as a log argument — this is not an API call, just a string for audit trail. Still worth updating for consistency.

---

## Section D — Config/Env/Docs

No Claude model references found in `.env`, `.env.example`, `render.yaml`, `*.toml`, `*.md`, or `Dockerfile`.

**One stale comment** in `backend/config/models.py` lines 6-7:
```
# - Website (potential clients): Sonnet 4.5 (best Ukrainian quality)
# - Content generation: Sonnet 4.5 (translation, images, categorization)
```
These describe the old `4.5` models. Should be updated to reflect `4.6` after migration.

---

## Migration Plan (Step 2 — after approval)

### Files to touch

1. **Create** `backend/services/ai_models.py` — single source of truth as specified
2. **Edit** `backend/config/models.py:16` — `CLAUDE_MODEL_WEBSITE → "claude-sonnet-4-6"` + update header comments
3. **Edit** `backend/solomon_contracts/analyzer.py:20–22` — replace three constants with `from backend.services.ai_models import SONNET` (or relative `from ..services.ai_models`)
4. **Edit** `backend/photo_report/vision.py:488` — import and use `SONNET`
5. **Edit** `backend/solomon_search.py:85,247` — import and use `HAIKU`
6. **Edit** `backend/solomon_contracts/ingestion.py:157,175` — import and use `HAIKU`
7. **Edit** `backend/services/api_token_monitor.py:108` — import and use `HAIKU`

### No changes needed to

- `backend/routes/chat_endpoints.py` — already imports from `config.models`
- `backend/services/hr_rag_service.py` — already imports `CLAUDE_MODEL_TELEGRAM`
- `backend/services/translation_service.py` — already imports `CLAUDE_MODEL_CONTENT`
- `backend/services/image_generator.py` — already imports `CLAUDE_MODEL_CONTENT`
- All other files that import from `config.models` — they'll inherit the fix automatically once `config/models.py` is updated

---

## Risk Assessment

| Item | Risk | Reason |
|---|---|---|
| A1 — `CLAUDE_MODEL_WEBSITE` | MED | Client-facing chat — model change is non-breaking, just quality/cost shift |
| A2 — `ANTHROPIC_SCAN_MODEL` | HIGH | Solomon contract scan — core feature for head-of-law handoff |
| A3 — `ANTHROPIC_ALT_MODEL` | HIGH | Alternative generation — affects RAG grounding quality |
| A4 — `ANTHROPIC_OPINION_MODEL` | HIGH | Legal opinion generation — lawyer-facing output |
| C items | LOW | Already correct model, just a code hygiene change |

**Recommendation:** All A-items must be fixed before April 30. The `claude-sonnet-4-5` alias (A2–A4) has no date suffix and may already be routing to an older model.
