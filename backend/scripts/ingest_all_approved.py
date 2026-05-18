"""
Phase 4 driver — ingest all missing approved law sources into solomon-contracts-corpus.

Run from project root: cd backend && python scripts/ingest_all_approved.py

Notes:
- ПК (2755-17) is already in corpus as source_id=3 — skip it here.
- INCOTERMS 2020 is 'awaiting_source' — skip until Andrey delivers the file.
- Re-run individual laws: python scripts/ingest_all_approved.py --only 3817-20
"""
import os
import sys
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solomon_contracts.kb_ingest import ingest_law

TO_INGEST = [
    # All 19 active laws in solomon_kb_sources (id=1..20, skip id=5 awaiting_source INCOTERMS).
    # Run with --only <codes> to re-ingest individual laws.
    # NOTE: IDs in solomon_kb_sources do NOT match solcon_corpus_sources IDs — always
    # ingest ALL active laws to avoid ID-collision overwrites.
    "435-15",    # id=1  ЦК (already in corpus from solcon run; use to upgrade metadata)
    "2755-17",   # id=2  ПК
    "3817-20",   # id=3  Держ. регулювання алкоголю (2024)
    "995_003",   # id=4  CISG
    # id=5 incoterms_2020 → awaiting_source, skip
    "z0128-98",  # id=6  Перевезення вантажів автотранспортом
    "996-14",    # id=7  Бухоблік
    "z0168-95",  # id=8  Положення №88
    "2800-20",   # id=9  Географічні зазначення спиртних напоїв
    "3689-12",   # id=10 Знаки для товарів і послуг
    "3688-12",   # id=11 Промислові зразки
    "2811-20",   # id=12 Авторське право (2022)
    "270/96-вр", # id=13 Реклама
    "1023-12",   # id=14 Захист прав споживачів
    "2297-17",   # id=15 Захист персональних даних
    "2639-19",   # id=16 Інформація споживачів щодо харчових продуктів
    "z0601-21",  # id=17 Маркування харчових продуктів
    "3928-20",   # id=18 Виноград, вино
    "851-15",    # id=19 Електронні документи
    "2155-19",   # id=20 Електронна ідентифікація
]


def main():
    parser = argparse.ArgumentParser(description="Ingest approved law sources")
    parser.add_argument("--only", nargs="*", help="Law codes to ingest (subset)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be ingested, then exit")
    args = parser.parse_args()

    targets = args.only if args.only else TO_INGEST
    unknown = [c for c in targets if c not in TO_INGEST and c]
    if unknown:
        print(f"Warning: unknown codes: {unknown}")

    if args.dry_run:
        print("DRY RUN — would ingest:")
        for code in targets:
            print(f"  {code}")
        return

    success, failed = 0, 0
    for idx, code in enumerate(targets):
        if idx > 0:
            time.sleep(3)  # polite pause between requests to avoid rate-limiting
        print(f"\nIngesting {code}...")
        try:
            result = ingest_law(code)
            print(f"  ✓ {result['chunks_added']} chunks, edition {result['edition_date']}, basis {result['edition_basis']}")
            success += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Done: {success} succeeded, {failed} failed")
    if failed > 0:
        print("Re-run failed laws with: python scripts/ingest_all_approved.py --only <codes...>")
        sys.exit(1)


if __name__ == "__main__":
    main()
