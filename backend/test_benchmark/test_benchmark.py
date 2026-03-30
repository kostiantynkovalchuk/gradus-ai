"""
Offline accuracy benchmark for Alex Photo Report Bot.

Fetches reports that have expert corrections from the DB and computes
AI vs expert delta per category. Run directly:

    cd backend && python -m test_benchmark.test_benchmark [--days 90] [--csv]

Output: per-category mean absolute error (MAE) in shelf-share %, overall accuracy.
"""

import argparse
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_db_connection


CAT_UA = {
    "vodka": "Горілка",
    "wine": "Вино",
    "cognac": "Коньяк",
    "sparkling": "Ігристе",
}

ACCURACY_THRESHOLD_PCT = 10


def fetch_corrected_reports(days: int = 90) -> list[dict]:
    """
    Fetch all photo_reports that have at least one expert correction
    within the given period. Returns a list of dicts:
      - report_id, shelf_share (AI), corrections (list of expert rows)
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                pr.id,
                pr.shelf_share,
                pr.score,
                pr.passed,
                pr.created_at,
                pr.trade_point_name
            FROM photo_reports pr
            WHERE pr.created_at > NOW() - INTERVAL '%s days'
              AND EXISTS (
                  SELECT 1 FROM expert_corrections ec WHERE ec.report_id = pr.id
              )
            ORDER BY pr.created_at DESC
            """,
            (days,),
        )
        report_rows = cur.fetchall()

        results = []
        for row in report_rows:
            report_id = row[0]
            shelf_share_raw = row[1]
            shelf_share = shelf_share_raw if isinstance(shelf_share_raw, dict) else {}

            cur.execute(
                """
                SELECT category, true_share, our_facings, total_facings,
                       expert_name, raw_text, created_at
                FROM expert_corrections
                WHERE report_id = %s AND true_share IS NOT NULL
                ORDER BY created_at
                """,
                (report_id,),
            )
            corrections = [
                {
                    "category": r[0],
                    "true_share": r[1],
                    "our_facings": r[2],
                    "total_facings": r[3],
                    "expert_name": r[4],
                    "raw_text": r[5],
                    "created_at": r[6].isoformat() if r[6] else None,
                }
                for r in cur.fetchall()
            ]

            if corrections:
                results.append(
                    {
                        "report_id": report_id,
                        "ai_shelf_share": shelf_share,
                        "ai_score": row[2],
                        "ai_passed": row[3],
                        "created_at": row[4].isoformat() if row[4] else None,
                        "trade_point_name": row[5],
                        "corrections": corrections,
                    }
                )

        cur.close()
        return results
    finally:
        conn.close()


def compute_metrics(reports: list[dict]) -> dict:
    """
    Compute per-category MAE and overall accuracy score.
    Returns dict with per-cat stats and summary.
    """
    per_category: dict[str, dict] = {}

    for report in reports:
        ai_ss = report["ai_shelf_share"]
        for correction in report["corrections"]:
            cat = correction.get("category")
            if not cat:
                continue
            expert_share = correction.get("true_share")
            if expert_share is None:
                continue

            ai_cat = ai_ss.get(cat, {}) if isinstance(ai_ss, dict) else {}
            ai_share = ai_cat.get("percent")

            if cat not in per_category:
                per_category[cat] = {"errors": [], "within_threshold": 0, "total": 0}

            per_category[cat]["total"] += 1

            if ai_share is not None:
                error = abs(float(ai_share) - float(expert_share))
                per_category[cat]["errors"].append(error)
                if error <= ACCURACY_THRESHOLD_PCT:
                    per_category[cat]["within_threshold"] += 1
            else:
                per_category[cat]["errors"].append(None)

    summary: dict[str, dict] = {}
    all_errors: list[float] = []
    all_within = 0
    all_total = 0

    for cat, data in per_category.items():
        valid_errors = [e for e in data["errors"] if e is not None]
        mae = round(sum(valid_errors) / len(valid_errors), 1) if valid_errors else None
        accuracy_pct = (
            round(data["within_threshold"] / data["total"] * 100, 1) if data["total"] > 0 else None
        )
        summary[cat] = {
            "ua_name": CAT_UA.get(cat, cat),
            "total_corrections": data["total"],
            "valid_comparisons": len(valid_errors),
            "mae_share_pct": mae,
            "within_10pct": data["within_threshold"],
            "accuracy_pct": accuracy_pct,
        }
        all_errors.extend(valid_errors)
        all_within += data["within_threshold"]
        all_total += data["total"]

    overall_mae = round(sum(all_errors) / len(all_errors), 1) if all_errors else None
    overall_accuracy = round(all_within / all_total * 100, 1) if all_total > 0 else None

    return {
        "by_category": summary,
        "overall": {
            "total_corrections": all_total,
            "valid_comparisons": len(all_errors),
            "mae_share_pct": overall_mae,
            "within_10pct": all_within,
            "accuracy_pct": overall_accuracy,
        },
    }


def print_report(metrics: dict, reports: list[dict], csv_mode: bool = False) -> None:
    overall = metrics["overall"]
    by_cat = metrics["by_category"]

    if csv_mode:
        print("category,ua_name,total,valid,mae_pct,within_10pct,accuracy_pct")
        for cat, data in by_cat.items():
            print(
                f"{cat},{data['ua_name']},{data['total_corrections']},"
                f"{data['valid_comparisons']},{data['mae_share_pct']},"
                f"{data['within_10pct']},{data['accuracy_pct']}"
            )
        print(
            f"OVERALL,Overall,{overall['total_corrections']},"
            f"{overall['valid_comparisons']},{overall['mae_share_pct']},"
            f"{overall['within_10pct']},{overall['accuracy_pct']}"
        )
        return

    print("\n" + "=" * 60)
    print("  ALEX PHOTO REPORT — ACCURACY BENCHMARK")
    print("=" * 60)
    print(f"\n  Звітів з корекціями: {len(reports)}")
    print(f"  Всього корекцій:     {overall['total_corrections']}")
    print(f"  Валідних порівнянь:  {overall['valid_comparisons']}")
    print()

    header = f"{'Категорія':<14} {'Корекцій':>10} {'MAE %':>8} {'В межах ±10%':>14} {'Точність':>10}"
    print(header)
    print("-" * len(header))

    for cat, data in by_cat.items():
        acc = f"{data['accuracy_pct']}%" if data["accuracy_pct"] is not None else "—"
        mae = f"{data['mae_share_pct']}%" if data["mae_share_pct"] is not None else "—"
        w10 = data["within_10pct"]
        tot = data["total_corrections"]
        print(f"  {data['ua_name']:<12} {tot:>10} {mae:>8} {w10:>8}/{tot:<4}  {acc:>8}")

    print("-" * len(header))
    o_acc = f"{overall['accuracy_pct']}%" if overall["accuracy_pct"] is not None else "—"
    o_mae = f"{overall['mae_share_pct']}%" if overall["mae_share_pct"] is not None else "—"
    print(
        f"  {'ЗАГАЛОМ':<12} {overall['total_corrections']:>10} "
        f"{o_mae:>8} {overall['within_10pct']:>8}/{overall['total_corrections']:<4}  "
        f"{o_acc:>8}"
    )
    print("=" * 60)

    if overall["accuracy_pct"] is not None:
        if overall["accuracy_pct"] >= 80:
            verdict = "✅ ВІДМІННО — AI точно розпізнає фейсинги"
        elif overall["accuracy_pct"] >= 60:
            verdict = "⚠️  ПРИЙНЯТНО — є поле для покращення"
        else:
            verdict = "❌ ПОТРІБНЕ ВДОСКОНАЛЕННЯ — висока похибка"
        print(f"\n  {verdict}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Photo Report accuracy benchmark")
    parser.add_argument("--days", type=int, default=90, help="Look-back window in days (default 90)")
    parser.add_argument("--csv", action="store_true", help="Output in CSV format")
    args = parser.parse_args()

    print(f"Fetching corrected reports for the last {args.days} days...")
    reports = fetch_corrected_reports(days=args.days)

    if not reports:
        print("No corrected reports found. Ask experts to reply to bot reports with corrections.")
        sys.exit(0)

    metrics = compute_metrics(reports)
    print_report(metrics, reports, csv_mode=args.csv)


if __name__ == "__main__":
    main()
