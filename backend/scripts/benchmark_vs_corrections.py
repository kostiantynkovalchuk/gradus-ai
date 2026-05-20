"""
Benchmark current vision pipeline against saved expert corrections.

Re-analyzes stored photos through analyze_photos() + calculate_score()
and compares shelf-share percentages to expert_corrections rows.

Usage:
    cd backend
    python scripts/benchmark_vs_corrections.py 2>&1 | tee benchmark_output.txt

Cost: ~29 reports × avg 1.2 photos × ~$0.21/call ≈ $7 total
Runtime: ~10-15 minutes
"""

import os
import sys
import json
import base64
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2

DATABASE_URL = os.environ["DATABASE_URL"]


def run_benchmark():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # ── 1. Load reports that have expert corrections ───────────────────────────
    cur.execute("""
        SELECT DISTINCT pr.id, pr.trade_point_name
        FROM photo_reports pr
        JOIN expert_corrections ec ON ec.report_id = pr.id
        WHERE pr.id >= 86
          AND pr.scoring_version = 'v2'
          AND ec.true_share IS NOT NULL
        ORDER BY pr.id
    """)
    reports = cur.fetchall()
    print(f"Found {len(reports)} reports with expert corrections\n")

    # ── 2. Load all expert corrections into memory ─────────────────────────────
    cur.execute("""
        SELECT report_id, category, true_share
        FROM expert_corrections
        WHERE report_id >= 86
          AND true_share IS NOT NULL
        ORDER BY report_id, category
    """)
    corrections: dict[int, dict[str, int]] = {}
    for report_id, category, true_share in cur.fetchall():
        corrections.setdefault(report_id, {})[category] = true_share

    # ── 3. Import vision + scoring (after sys.path is set) ────────────────────
    from photo_report.vision import analyze_photos
    from photo_report.scoring import calculate_score

    # ── 4. Per-report loop ────────────────────────────────────────────────────
    # category -> list of (new_share, expert_share)
    new_results: dict[str, list[tuple[float, float]]] = defaultdict(list)
    # category -> list of (old_share, expert_share)
    old_results: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for report_id, trade_point_name in reports:
        # Fetch stored photos (BYTEA)
        cur.execute("""
            SELECT photo_data FROM report_photos
            WHERE report_id = %s
            ORDER BY photo_order
        """, (report_id,))
        photo_rows = cur.fetchall()

        if not photo_rows:
            print(f"Report #{report_id} ({trade_point_name}): no photos stored — skip")
            continue

        # Fetch old shelf_share from DB (stored after original analysis)
        cur.execute("SELECT shelf_share FROM photo_reports WHERE id = %s", (report_id,))
        row = cur.fetchone()
        old_shelf_share: dict = row[0] if row and row[0] else {}

        # Convert BYTEA → base64 strings
        photos_b64: list[str] = []
        for (photo_data,) in photo_rows:
            if isinstance(photo_data, memoryview):
                photo_data = bytes(photo_data)
            photos_b64.append(base64.b64encode(photo_data).decode())

        print(f"Report #{report_id} ({trade_point_name}): {len(photos_b64)} photo(s)")

        try:
            # Re-run through current pipeline (synchronous)
            vision_raw = analyze_photos(photos_b64)
            scored = calculate_score(vision_raw)
            new_shelf_share: dict = scored.get("shelf_share") or {}
        except Exception as exc:
            print(f"  ERROR: {exc}")
            continue

        report_corrections = corrections.get(report_id, {})
        for category, expert_share in report_corrections.items():
            new_cat = new_shelf_share.get(category) or {}
            new_share = float(new_cat.get("percent") or 0)

            old_cat = old_shelf_share.get(category) or {}
            old_share = float(old_cat.get("percent") or 0)

            new_results[category].append((new_share, expert_share))
            old_results[category].append((old_share, expert_share))

            new_gap = abs(new_share - expert_share)
            old_gap = abs(old_share - expert_share)
            delta = old_gap - new_gap
            if delta > 0:
                symbol = "✅"
            elif delta < 0:
                symbol = "❌"
            else:
                symbol = "="
            sign = "+" if delta > 0 else ""
            print(
                f"  {category:<10} old={old_share:5.1f}%  new={new_share:5.1f}%  "
                f"expert={expert_share:5.1f}%  |  "
                f"old_gap={old_gap:5.1f}pp  new_gap={new_gap:5.1f}pp  "
                f"{symbol} {sign}{delta:.1f}pp"
            )

    # ── 5. Summary table ──────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS — OLD vs NEW PIPELINE")
    print("=" * 70)
    print(
        f"{'Category':<12} {'Old MAE':>8} {'New MAE':>8} "
        f"{'AI=0 old':>10} {'AI=0 new':>10} {'Delta MAE':>10}"
    )
    print("-" * 70)

    categories = ["vodka", "cognac", "wine", "sparkling"]
    for category in categories:
        if category not in new_results:
            print(f"{category:<12}  — no data —")
            continue

        nd = new_results[category]
        od = old_results[category]
        n = len(nd)

        new_mae = sum(abs(a - e) for a, e in nd) / n
        old_mae = sum(abs(a - e) for a, e in od) / n

        new_zeros = sum(1 for a, _ in nd if a == 0)
        old_zeros = sum(1 for a, _ in od if a == 0)

        delta = old_mae - new_mae
        sign = "+" if delta > 0 else ""
        print(
            f"{category:<12} {old_mae:>7.1f}%  {new_mae:>7.1f}%  "
            f"{old_zeros:>4}/{n:<4}  {new_zeros:>4}/{n:<4}  "
            f"{sign}{delta:>7.1f}pp"
        )

    conn.close()
    print("\nBenchmark complete.")


if __name__ == "__main__":
    run_benchmark()
