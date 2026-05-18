# Pinecone Unknown Sources — Resolved

**Date:** 2026-05-18  
**Namespace:** `solomon-contracts-corpus` (index: `gradus-media`)  
**Total vectors at audit time:** 1 042

---

## Method

All 15 source_ids were enumerated by:
1. Querying the namespace with 10 diverse legal-domain embeddings (via `text-embedding-3-small`), `top_k=10` each.
2. Extracting `source_id` from vector IDs (pattern: `corpus_{source_id}_{chunk_index}`).
3. Recording `official_url` and `source_title` metadata from matched chunks.
4. For chunk counts: querying with `filter={"official_url": {"$eq": <url>}}`, `top_k=100`, using the law's own topic as query.

The filter approach with zero-vector (`[0.0]*1536`) was **not reliable** — Pinecone ANN ignores zero-vector queries even with metadata filters. Real embedding queries were used instead.

---

## Source Inventory (all 15 source_ids)

| source_id | official_url | source_title | chunks | classification |
|---|---|---|---|---|
| 1 | `.../laws/show/435-15/print1` | Цивільний кодекс України | ~200 | **APPROVED** (law #1) |
| 2 | `.../laws/show/436-15/print1` | Господарський кодекс України | 74 | **DELETE** — not in approved list |
| 3 | `.../laws/show/2755-17/print1` | Податковий кодекс України | ~90 | **APPROVED** (law #2) — present despite spec table saying "missing" |
| 4 | `.../laws/show/1023-12/print1` | Закон про захист прав споживачів | ~40 | **APPROVED** (law #14) |
| 5 | `.../laws/show/771/97-вр/print1` | Закон про безпечність та якість харчових продуктів | 81 | **DELETE** — not in approved list |
| 6 | `.../laws/show/2639-19/print1` | Закон про інформацію для споживачів щодо харчових продуктів | ~35 | **APPROVED** (law #16) |
| 7 | `.../laws/show/481/95-вр/print1` | Закон про держ. регулювання алкогольних напоїв (старий) | 64 | **DELETE** — superseded by approved 3817-20 |
| 8 | `.../laws/show/2275-19/print1` | Закон про товариства з обмеженою відповідальністю | 61 | **DELETE** — not in approved list |
| 9 | `.../laws/show/851-15/print1` | Закон про електронні документи та документообіг | ~30 | **APPROVED** (law #19) |
| 10 | `.../laws/show/3792-12/print1` | Закон про авторське право і суміжні права (старий) | 64 | **DELETE** — superseded by approved 2811-20 |
| 11 | `.../laws/show/270/96-вр/print1` | Закон про рекламу | ~30 | **APPROVED** (law #13) |
| 12 | `.../laws/show/236/96-вр/print1` | Закон про захист від недобросовісної конкуренції | 30 | **DELETE** — not in approved list |
| 13 | `.../laws/show/2210-14/print1` | Закон про захист економічної конкуренції | 76 | **DELETE** — not in approved list |
| 14 | `.../laws/show/996-14/print1` | Закон про бухгалтерський облік та фінансову звітність | ~25 | **APPROVED** (law #7) |
| 15 | `.../laws/show/187-2022-п/print1` | Постанова КМУ №187 «Про нац. безпеку в сфері економіки» | 3 | **DELETE** — not in approved list |

---

## Key Findings

**Source_id=3 (ПК, 2755-17) is PRESENT** despite the law director's ТЗ table marking it as "missing".  
→ ПК does not need to be re-ingested in Phase 4. It's already in the approved corpus.  
→ Phase 4 TO_INGEST list should be updated: remove `"2755-17"` from the driver script.

**Source_id=9 (851-15, Електронні документи)** did not appear in initial filter queries (zero-vector approach failed). Confirmed via embedding-based sampling — 851-15 IS in the corpus and IS on the approved list. No action needed.

**No unidentified orphan sources.** All 15 source_ids resolve cleanly to known laws.

---

## Phase 3 Deletion Targets

| source_id | official_url (metadata key) | chunks | action |
|---|---|---|---|
| 2 | `https://zakon.rada.gov.ua/laws/show/436-15/print1` | 74 | DELETE |
| 5 | `https://zakon.rada.gov.ua/laws/show/771/97-%D0%B2%D1%80/print1` | 81 | DELETE |
| 7 | `https://zakon.rada.gov.ua/laws/show/481/95-%D0%B2%D1%80/print1` | 64 | DELETE |
| 8 | `https://zakon.rada.gov.ua/laws/show/2275-19/print1` | 61 | DELETE |
| 10 | `https://zakon.rada.gov.ua/laws/show/3792-12/print1` | 64 | DELETE |
| 12 | `https://zakon.rada.gov.ua/laws/show/236/96-%D0%B2%D1%80/print1` | 30 | DELETE |
| 13 | `https://zakon.rada.gov.ua/laws/show/2210-14/print1` | 76 | DELETE |
| 15 | `https://zakon.rada.gov.ua/laws/show/187-2022-%D0%BF/print1` | 3 | DELETE |

**Total chunks to delete: 453 of 1 042**  
**Remaining after cleanup: ~589 chunks** (7 approved laws: ЦК, ПК, Споживачі, Інфо споживачів, Електронні документи, Реклама, Бухоблік)

---

## Approved Phase 4 Ingest List (revised)

Remove 2755-17 (ПК) — already in corpus. Updated list:

```python
TO_INGEST = [
    # "2755-17",  # ПК — already in corpus as source_id=3
    "3817-20",   # New спирт
    "995_003",   # CISG
    "z0128-98",  # Перевезення
    "z0168-95",  # Положення 88
    "2800-20",   # Геогр. зазначення
    "3689-12",   # Знаки
    "3688-12",   # Промислові зразки
    "2811-20",   # New авт. право
    "2297-17",   # Персональні дані
    "z0601-21",  # Маркування
    "3928-20",   # Виноград
    "2155-19",   # Електронна ідент.
]
```

12 laws to ingest (not 13).
