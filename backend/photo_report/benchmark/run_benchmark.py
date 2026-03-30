"""
Alex Photo Report — Benchmark Runner

Picks N random Gotz photos from a directory, runs each through the full
analysis pipeline, and prints the results for manual review.

Usage:
    cd backend
    python -m photo_report.benchmark.run_benchmark --dir photo_report/benchmark --count 5
    python -m photo_report.benchmark.run_benchmark --dir photo_report/benchmark --count 5 --all

Args:
    --dir   Path to benchmark image directory (default: photo_report/benchmark)
    --count Number of photos to analyze (default: 5, 0 = all)
    --all   Analyze all photos in the directory
    --file  Analyze a specific file instead of random selection
"""

import argparse
import base64
import json
import random
import sys
from pathlib import Path


def load_image_b64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def run_benchmark(image_dir: Path, count: int, specific_file: str | None = None) -> None:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from photo_report.vision import analyze_photos, BRAND_REFERENCES
    from photo_report.scoring import calculate_score

    ref_count = len(BRAND_REFERENCES)
    print(f"\n{'='*60}")
    print(f"Alex Photo Report — Benchmark")
    print(f"Reference images loaded: {ref_count}")
    print(f"{'='*60}\n")

    if specific_file:
        files = [Path(specific_file)]
    else:
        jpg_files = sorted(image_dir.glob("*.jpg")) + sorted(image_dir.glob("*.jpeg"))
        if not jpg_files:
            print(f"ERROR: No .jpg/.jpeg files found in {image_dir}")
            sys.exit(1)

        if count == 0 or count >= len(jpg_files):
            files = jpg_files
        else:
            files = random.sample(jpg_files, min(count, len(jpg_files)))

    print(f"Analyzing {len(files)} photo(s):\n")

    for i, img_path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {img_path.name}")
        print("-" * 50)

        try:
            b64 = load_image_b64(img_path)
            vision_result = analyze_photos([b64])
            score_result = calculate_score(vision_result)

            print(f"Score:   {score_result['score']}/100  [{score_result['status']}]")
            print(f"Photos:  {img_path.name}")

            shares = score_result.get("shelf_shares", {})
            print("\nShelf shares:")
            for cat, val in shares.items():
                if val is not None:
                    print(f"  {cat.title()}: {val}%")
                else:
                    print(f"  {cat.title()}: (not assessed — low confidence)")

            vodka_detail = score_result.get("vodka_detail")
            if vodka_detail:
                print("\nVodka detail:")
                for brand, facings in vodka_detail.items():
                    if facings is not None:
                        print(f"  {brand.title()}: {facings} facings")

            retried = score_result.get("retried_categories", [])
            if retried:
                print(f"\nRetried categories (was low confidence): {', '.join(retried)}")

            errors = score_result.get("errors", [])
            if errors:
                print(f"\nErrors ({len(errors)}):")
                for e in errors:
                    sev = e.get("severity", "?")
                    print(f"  [{sev.upper()}] {e['text']}")

            warnings = score_result.get("warnings", [])
            if warnings:
                print(f"\nWarnings:")
                for w in warnings:
                    print(f"  {w}")

            shelf_scan = vision_result.get("shelf_scan", [])
            if shelf_scan:
                print(f"\nShelf scan ({len(shelf_scan)} rows):")
                for row in shelf_scan:
                    brands = ", ".join(row.get("brands", []))
                    print(f"  Row {row['row']} [{row['category']}]: {brands}")

        except Exception as e:
            print(f"  ERROR: {e}")

        print()

    print(f"{'='*60}")
    print(f"Benchmark complete. {len(files)} photo(s) analyzed.")
    if ref_count == 0:
        print(
            "\n⚠️  No reference images were loaded. Upload .jpg files to "
            "backend/photo_report/references/ to enable visual anchors for Claude."
        )
    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Alex Photo Report benchmark on Gotz ideal-shelf photos"
    )
    parser.add_argument(
        "--dir",
        default="photo_report/benchmark",
        help="Directory with .jpg benchmark photos (default: photo_report/benchmark)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Number of random photos to analyze (default: 5). Use 0 for all.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Analyze all photos in the directory (overrides --count)",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="Analyze a specific file instead of random selection",
    )
    args = parser.parse_args()

    image_dir = Path(args.dir)
    if not args.file and not image_dir.exists():
        print(f"ERROR: Directory {image_dir} does not exist")
        sys.exit(1)

    count = 0 if args.all else args.count
    run_benchmark(image_dir, count, args.file)


if __name__ == "__main__":
    main()
