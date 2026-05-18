"""
One-shot backfill: populate current_edition_date / current_edition_basis /
next_edition_basis on existing solomon_kb_sources rows.

Does NOT touch Pinecone — only updates the DB registry.
Skips INCOTERMS (awaiting_source) automatically.

Run from project root:
    cd backend && python scripts/backfill_edition_dates.py

Options:
    --only <law_codes...>   Backfill only the specified law codes
    --dry-run               Print what would be fetched without writing to DB
"""
import os
import sys
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solomon_contracts import db as solcon_db
from solomon_contracts.kb_ingest import _fetch_current_edition, _parse_edition_header


def backfill(targets: list[str] | None = None, dry_run: bool = False):
    rows = solcon_db.fetchall(
        "SELECT id, law_code, law_name, canonical_url, status FROM solomon_kb_sources ORDER BY id"
    )
    active = [r for r in rows if r["status"] == "active"]
    if targets:
        active = [r for r in active if r["law_code"] in targets]

    print(f"{'DRY-RUN — ' if dry_run else ''}Backfilling editions for {len(active)} active source(s)\n")

    succeeded, failed_null, failed_err = [], [], []

    for i, source in enumerate(active):
        if i > 0:
            time.sleep(2)  # polite pause between requests

        code = source["law_code"]
        url  = source["canonical_url"]
        if not url:
            print(f"  ✗ {code:15s}  SKIP — no canonical_url")
            failed_err.append((code, "no canonical_url"))
            continue

        try:
            html, final_url = _fetch_current_edition(url, max_hops=3)
            edition_date, edition_basis, next_basis, _ = _parse_edition_header(html)

            if dry_run:
                print(f"  ~ {code:15s}  ред={edition_date}  підстава={edition_basis}  next={next_basis}")
                if edition_date is None:
                    failed_null.append(code)
                else:
                    succeeded.append(code)
                continue

            solcon_db.execute(
                """UPDATE solomon_kb_sources
                   SET current_edition_date        = %s,
                       current_edition_basis       = %s,
                       next_edition_basis          = %s,
                       last_verified_at            = NOW(),
                       updated_at                  = NOW()
                   WHERE id = %s""",
                (edition_date, edition_basis, next_basis, source["id"]),
            )

            if edition_date is not None:
                print(f"  ✓ {code:15s}  ред={edition_date}  підстава={edition_basis}  next={next_basis}")
                succeeded.append(code)
            else:
                # Never-amended law — NULL edition date is expected and valid
                print(f"  ○ {code:15s}  ред=None (never amended)  next={next_basis}")
                failed_null.append(code)

        except Exception as e:
            print(f"  ✗ {code:15s}  FAILED: {e}")
            failed_err.append((code, str(e)))

    print(f"\n{'='*55}")
    print(f"Succeeded (with edition date): {len(succeeded)}")
    print(f"NULL edition (never amended):  {len(failed_null)}")
    if failed_null:
        print(f"  {failed_null}")
    print(f"Errors:                        {len(failed_err)}")
    if failed_err:
        for code, err in failed_err:
            print(f"  {code}: {err}")

    if not dry_run:
        # Final DB check
        nulls = solcon_db.fetchone(
            "SELECT COUNT(*) as c FROM solomon_kb_sources WHERE status='active' AND current_edition_date IS NULL"
        )
        print(f"\nDB check — active rows with NULL current_edition_date: {nulls['c']}")
        if nulls["c"] == len(failed_null):
            print("✓ All NULLs are accounted-for never-amended laws")
        else:
            print("⚠ Unexpected NULLs remain — inspect manually")


def main():
    parser = argparse.ArgumentParser(description="Backfill edition dates for solomon_kb_sources")
    parser.add_argument("--only", nargs="*", help="Law codes to process (subset)")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing to DB")
    args = parser.parse_args()
    backfill(targets=args.only, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
