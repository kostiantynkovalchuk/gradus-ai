"""
Compare our pass/fail decisions with Olena's for Д25 (shelf share) checks.

Our threshold: vodka ≥25% = pass
Olena's Д25Р/Д25Х: pass/fail based on her visual assessment

This script finds the optimal threshold that maximizes agreement with Olena.

Usage:
    cd backend
    python -m calibration.pass_fail_calibrator
"""
import os
import psycopg2
import pandas as pd
from calibration.np_matcher import load_excel_data, load_our_reports, match_reports


def calibrate_vodka_threshold(matches: list[dict]):
    """Find optimal vodka threshold that matches Olena's Д25 decisions."""

    d25_matches = [m for m in matches if m['excel_pokaznik'] in ('Д25Р', 'Д25Х')]

    if not d25_matches:
        print("No Д25 matches found!")
        return

    print(f"\n{'='*70}")
    print(f"VODKA THRESHOLD CALIBRATION — {len(d25_matches)} Д25 matches")
    print(f"{'='*70}")

    for m in d25_matches:
        ss = m['our_shelf_share']
        vodka = ss.get('vodka', {})
        m['our_vodka_pct'] = vodka.get('percent') or 0
        m['our_vodka_conf'] = vodka.get('confidence', 'low')

    print(f"\nThreshold optimization:")
    print(f"{'Threshold':>10} {'Agreement':>10} {'FP':>5} {'FN':>5} {'Details':>30}")

    best_threshold = 25
    best_agreement = 0

    for threshold in range(15, 40):
        agree = 0
        fp = 0
        fn = 0

        for m in d25_matches:
            ai_pass = m['our_vodka_pct'] >= threshold
            olena_pass = m['excel_passed']

            if ai_pass == olena_pass:
                agree += 1
            elif ai_pass and not olena_pass:
                fp += 1
            else:
                fn += 1

        pct = agree * 100 / len(d25_matches)
        marker = " ← CURRENT" if threshold == 25 else (" ← BEST" if pct > best_agreement else "")
        print(f"{threshold:>8}%  {pct:>8.1f}%  {fp:>4}  {fn:>4}  {marker}")

        if pct > best_agreement:
            best_agreement = pct
            best_threshold = threshold

    print(f"\nOptimal threshold: {best_threshold}% (agreement: {best_agreement:.1f}%)")
    print(f"Current threshold: 25%")

    if best_threshold != 25:
        print(f"RECOMMENDATION: Change vodka threshold from 25% to {best_threshold}%")


def analyze_disagreements(matches: list[dict]):
    """Show cases where AI and Olena disagree."""
    d25_matches = [m for m in matches if m['excel_pokaznik'] in ('Д25Р', 'Д25Х')]

    print(f"\n{'='*70}")
    print(f"DISAGREEMENTS — AI vs Olena")
    print(f"{'='*70}")

    for m in d25_matches:
        ss = m['our_shelf_share']
        vodka = ss.get('vodka', {})
        our_pct = vodka.get('percent') or 0
        our_pass = our_pct >= 25

        if our_pass != m['excel_passed']:
            direction = "AI:PASS Olena:FAIL" if our_pass else "AI:FAIL Olena:PASS"
            comment = m['excel_comment'] or ''
            print(f"  #{m['report_id']} | NP:{m['np_code']} | vodka:{our_pct}% | {direction} | {comment}")


if __name__ == '__main__':
    excel_df = load_excel_data()
    our_reports = load_our_reports()
    matches = match_reports(our_reports, excel_df)
    calibrate_vodka_threshold(matches)
    analyze_disagreements(matches)
