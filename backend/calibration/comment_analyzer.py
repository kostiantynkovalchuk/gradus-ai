"""
Analyze Olena's fail comments to find patterns our AI should detect.

Maps Olena's comments to our error codes and finds gaps.

Usage:
    cd backend
    python -m calibration.comment_analyzer
"""
import os
import re
import pandas as pd
from collections import Counter
from calibration.np_matcher import load_excel_data


COMMENT_TO_AI_ERROR = {
    r'Нет POS': 'POS_MISSING',
    r'нет ШВ[КЮ]': 'SHELF_STRIP_MISSING',
    r'Нет ШВ[КЮ]': 'SHELF_STRIP_MISSING',

    r'Нет обзора': 'NO_OVERVIEW',
    r'Нет общего плана': 'NO_OVERVIEW',
    r'Темное фото': 'DARK_PHOTO',
    r'Фото монитора': 'MONITOR_PHOTO',
    r'Нечитабельное': 'UNREADABLE',
    r'не можливо порахувати': 'UNREADABLE',

    r'доля полки водки': 'VODKA_SHARE_FAIL',
    r'доля полки коньяк': 'COGNAC_SHARE_FAIL',
    r'доля полки вина': 'WINE_SHARE_FAIL',
    r'доля по коньяку': 'COGNAC_SHARE_FAIL',

    r'[Рр]азорван': 'BLOCK_BREAK',
    r'Неправильный порядок': 'WRONG_ORDER',
    r'Неправильый порядок': 'WRONG_ORDER',

    r'на нижней полке': 'FORBIDDEN_SHELF',
    r'не в элитке': 'NOT_IN_ELITE',
    r'премиальный не в элитке': 'PREMIUM_NOT_ELITE',

    r'этикетка закрыта': 'LABEL_HIDDEN',
    r'закрыта конкурентами': 'BLOCKED_BY_COMPETITOR',

    r'дублювання': 'DUPLICATE',
    r'дублирование': 'DUPLICATE',
    r'дублір': 'DUPLICATE',

    r'нет фото меню': 'NO_MENU_PHOTO',
    r'не полное меню': 'INCOMPLETE_MENU',
    r'не повне меню': 'INCOMPLETE_MENU',
    r'Нечитабельное меню': 'UNREADABLE_MENU',
    r'відсутн.*меню': 'MISSING_FROM_MENU',
}

AI_DETECTS = {
    'POS_MISSING': True,
    'SHELF_STRIP_MISSING': True,
    'NO_OVERVIEW': True,
    'DARK_PHOTO': True,
    'MONITOR_PHOTO': True,
    'VODKA_SHARE_FAIL': True,
    'COGNAC_SHARE_FAIL': True,
    'WINE_SHARE_FAIL': True,
    'BLOCK_BREAK': True,
    'WRONG_ORDER': True,
    'FORBIDDEN_SHELF': True,
    'LABEL_HIDDEN': True,
    'BLOCKED_BY_COMPETITOR': False,
    'NOT_IN_ELITE': True,
    'PREMIUM_NOT_ELITE': True,
    'DUPLICATE': False,
    'NO_MENU_PHOTO': False,
    'INCOMPLETE_MENU': False,
    'UNREADABLE_MENU': False,
    'UNREADABLE': True,
    'MISSING_FROM_MENU': False,
}


def classify_comment(comment: str) -> list[str]:
    """Classify a comment into error categories."""
    if not comment or pd.isna(comment):
        return []

    categories = []
    for pattern, category in COMMENT_TO_AI_ERROR.items():
        if re.search(pattern, str(comment), re.IGNORECASE):
            categories.append(category)

    return categories if categories else ['UNKNOWN']


def analyze_comments():
    """Full analysis of Olena's fail comments."""
    df = load_excel_data()
    fails = df[df['Результат'] == 'ЛОЖЬ'].copy()

    print(f"\n{'='*70}")
    print(f"COMMENT PATTERN ANALYSIS — {len(fails)} fails")
    print(f"{'='*70}")

    all_categories = Counter()
    brand_mentions = Counter()

    for _, row in fails.iterrows():
        comment = row.get('Коментар', '')
        cats = classify_comment(comment)
        for cat in cats:
            all_categories[cat] += 1

        if comment and not pd.isna(comment):
            comment_lower = str(comment).lower()
            for brand in ['вилла юа', 'villa', 'аджари', 'adjari', 'довбуш',
                         'greenday', 'гд', 'хельсинки', 'helsinki', 'українка',
                         'диди лари', 'didi lari', 'кристи', 'kristi', 'жж',
                         'луиджи', 'виаджо', 'фризанте', 'frizzante', 'шву', 'швк']:
                if brand in comment_lower:
                    brand_mentions[brand] += 1

    print(f"\nError categories (from {len(fails)} fails):")
    print(f"{'Category':<25} {'Count':>6} {'AI Detects':>12} {'Action':<30}")
    print("-" * 75)

    for cat, count in all_categories.most_common():
        detects = AI_DETECTS.get(cat)
        if detects is True:
            status = "YES"
            action = "Calibrate threshold"
        elif detects is False:
            status = "NO"
            action = "IMPLEMENT"
        else:
            status = "Unknown"
            action = "Investigate"
        print(f"  {cat:<23} {count:>6}   {status:<12} {action}")

    print(f"\nBrand mentions in fail comments:")
    for brand, count in brand_mentions.most_common():
        print(f"  {brand}: {count}")

    print(f"\n{'='*70}")
    print(f"GAP ANALYSIS — What AI should improve")
    print(f"{'='*70}")

    not_detected = {cat: count for cat, count in all_categories.items()
                    if AI_DETECTS.get(cat) is False and cat != 'DUPLICATE'}

    if not_detected:
        print(f"\nErrors Olena catches but AI does NOT:")
        for cat, count in sorted(not_detected.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count} instances")

    calibrate = {cat: count for cat, count in all_categories.items()
                 if AI_DETECTS.get(cat) is True and count > 5}

    if calibrate:
        print(f"\nErrors AI detects but may need calibration (>5 fails):")
        for cat, count in sorted(calibrate.items(), key=lambda x: -x[1]):
            print(f"  {cat}: {count} instances — verify AI catches these correctly")


if __name__ == '__main__':
    analyze_comments()
