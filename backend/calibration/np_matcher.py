"""
Match our photo_reports with Olena's Excel data by NP-code.

Usage:
    cd backend
    python -m calibration.np_matcher

Reads:
    - photo_reports table (our AI results)
    - Перевірка_ФЗ.xlsm (Olena's ground truth)

Outputs:
    - Matched pairs: our report + Olena's check for same trade point
    - Match rate statistics
"""
import os
import re
import psycopg2
import pandas as pd
from datetime import timedelta

EXCEL_PATH = os.path.join(os.path.dirname(__file__), 'Перевірка_ФЗ.xlsm')


def extract_np_code(trade_point_name: str) -> str | None:
    """Extract NP-code from our trade_point_name field.

    Examples:
        "194409 Вовк НВ" → "194409"
        "7647маг.Вулик" → "7647"
        "182164 Власюк" → "182164"
        "Бар-магазин ФОП КраснобрижаЛВ" → None (no NP-code)
        "Без назви" → None
    """
    if not trade_point_name or trade_point_name == 'Без назви':
        return None

    match = re.match(r'^(\d{4,7})', trade_point_name.strip())
    if match:
        return match.group(1)

    match = re.search(r'(\d{4,7})\s', trade_point_name.strip())
    if match:
        return match.group(1)

    return None


def normalize_excel_np_code(kod_tt: str) -> str | None:
    """Normalize Excel NP-code.

    Examples:
        "1*100015" → "1100015"
        "17*98089" → "1798089"
        "194409"   → "194409"
    """
    if not kod_tt or pd.isna(kod_tt):
        return None
    kod = str(kod_tt).strip().replace('*', '')
    return kod if kod else None


def load_excel_data() -> pd.DataFrame:
    """Load and clean Olena's Excel data."""
    df = pd.read_excel(EXCEL_PATH, engine='openpyxl', header=2)

    df['np_code'] = df['Код ТТ'].apply(normalize_excel_np_code)

    df['np_code'] = df['np_code'].ffill()
    df['Назва ТТ'] = df['Назва ТТ'].ffill()

    df['doc_date'] = pd.to_datetime(df['Дата документу'], errors='coerce')
    df['check_date'] = pd.to_datetime(df['Дата перевірки'], errors='coerce')

    df['passed'] = df['Результат'] == 'ИСТИНА'

    print(f"Excel data loaded: {len(df)} rows, {df['np_code'].nunique()} unique NP-codes")
    return df


def load_our_reports() -> list[dict]:
    """Load our photo_reports with extracted NP-codes."""
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()
    cur.execute("""
        SELECT id, agent_id, trade_point_name, score, passed,
               shelf_share, created_at, errors
        FROM photo_reports
        WHERE trade_point_name IS NOT NULL
          AND trade_point_name != 'Без назви'
        ORDER BY created_at
    """)

    reports = []
    for r in cur.fetchall():
        np = extract_np_code(r[2])
        if np:
            reports.append({
                'id': r[0],
                'agent_id': r[1],
                'trade_point_name': r[2],
                'np_code': np,
                'score': r[3],
                'passed': r[4],
                'shelf_share': r[5] or {},
                'created_at': r[6],
                'errors': r[7] or [],
            })

    conn.close()
    print(f"Our reports loaded: {len(reports)} with NP-codes")
    return reports


def match_reports(our_reports: list[dict], excel_df: pd.DataFrame, date_window_days: int = 7) -> list[dict]:
    """Match our reports with Excel data by NP-code + date proximity.

    A match = same NP-code + document date within date_window_days of our report.
    """
    matches = []

    excel_by_np = {}
    for _, row in excel_df.iterrows():
        np = row['np_code']
        if np:
            if np not in excel_by_np:
                excel_by_np[np] = []
            excel_by_np[np].append(row)

    for report in our_reports:
        np = report['np_code']
        if np not in excel_by_np:
            continue

        report_date = report['created_at']
        if report_date is None:
            continue

        best_match = None
        best_delta = timedelta(days=999)

        for excel_row in excel_by_np[np]:
            doc_date = excel_row['doc_date']
            if pd.isna(doc_date):
                continue

            delta = abs(report_date - doc_date.to_pydatetime().replace(tzinfo=report_date.tzinfo))
            if delta < best_delta and delta <= timedelta(days=date_window_days):
                best_delta = delta
                best_match = excel_row

        if best_match is not None:
            matches.append({
                'report_id': report['id'],
                'np_code': np,
                'our_score': report['score'],
                'our_passed': report['passed'],
                'our_shelf_share': report['shelf_share'],
                'our_date': report['created_at'],
                'excel_pokaznik': best_match['Показник'],
                'excel_passed': best_match['passed'],
                'excel_comment': best_match.get('Коментар', ''),
                'excel_date': best_match['doc_date'],
                'date_delta_hours': best_delta.total_seconds() / 3600,
            })

    print(f"\nMatches found: {len(matches)} (from {len(our_reports)} reports)")
    return matches


def print_results(matches: list[dict]):
    """Print match analysis."""
    if not matches:
        print("No matches found!")
        return

    print(f"\n{'='*70}")
    print(f"CALIBRATION RESULTS — {len(matches)} matched pairs")
    print(f"{'='*70}")

    tp = sum(1 for m in matches if m['our_passed'] and m['excel_passed'])
    fp = sum(1 for m in matches if m['our_passed'] and not m['excel_passed'])
    fn = sum(1 for m in matches if not m['our_passed'] and m['excel_passed'])
    tn = sum(1 for m in matches if not m['our_passed'] and not m['excel_passed'])

    print(f"\nConfusion Matrix (AI vs Olena):")
    print(f"                    Olena: PASS    Olena: FAIL")
    print(f"  AI: PASS          {tp:5d}          {fp:5d}   ← False Positives (AI passes, Olena fails)")
    print(f"  AI: FAIL          {fn:5d}          {tn:5d}   ← True Negatives")

    total = tp + fp + fn + tn
    agreement = (tp + tn) / total * 100 if total > 0 else 0
    print(f"\n  Agreement: {agreement:.1f}%")
    if fp + tp > 0:
        print(f"  False Positive rate: {fp}/{fp+tp} ({fp*100/(fp+tp):.1f}%)")
    if fn + tn > 0:
        print(f"  False Negative rate: {fn}/{fn+tn} ({fn*100/(fn+tn):.1f}%)")

    for pok in ['МЧР', 'Д25Р', 'Д25Х']:
        pok_matches = [m for m in matches if m['excel_pokaznik'] == pok]
        if not pok_matches:
            continue
        agree = sum(1 for m in pok_matches if m['our_passed'] == m['excel_passed'])
        print(f"\n  {pok}: {agree}/{len(pok_matches)} agree ({agree*100//len(pok_matches)}%)")

    false_pos = [m for m in matches if m['our_passed'] and not m['excel_passed']]
    if false_pos:
        print(f"\n{'='*70}")
        print(f"FALSE POSITIVES — AI passed but Olena failed ({len(false_pos)}):")
        print(f"{'='*70}")
        for m in false_pos:
            comment = m['excel_comment'] or 'no comment'
            print(f"  Report #{m['report_id']} | NP:{m['np_code']} | {m['excel_pokaznik']} | AI:{m['our_score']}/100 | Olena: FAIL | {comment}")


if __name__ == '__main__':
    excel_df = load_excel_data()
    our_reports = load_our_reports()
    matches = match_reports(our_reports, excel_df)
    print_results(matches)
