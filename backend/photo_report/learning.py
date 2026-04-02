"""
Expert correction pattern analysis for Alex Photo Report.
Detects systematic AI errors from accumulated expert feedback.
"""
import logging
import os
from collections import defaultdict

from .db import get_db_connection

logger = logging.getLogger(__name__)

CAT_NAMES = {
    "vodka": "горілка",
    "wine": "вино",
    "cognac": "коньяк",
    "sparkling": "ігристе",
}

BRANDS = ["ukrainka", "helsinki", "greenday"]


def analyze_correction_patterns(days: int = 30) -> dict:
    """
    Analyze accumulated expert corrections and detect systematic AI errors.

    Returns:
        {
          "patterns": [{"category", "severity", "pattern", "recommendation"}, ...],
          "sample_size": int,
          "categories_analyzed": [...],
          "period_days": int,
        }
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                ec.category,
                ec.true_share,
                (pr.shelf_share -> ec.category ->> 'percent')::float AS ai_share,
                ec.our_facings,
                ec.total_facings,
                ec.report_id
            FROM expert_corrections ec
            JOIN photo_reports pr ON pr.id = ec.report_id
            WHERE ec.created_at >= NOW() - INTERVAL '%s days'
              AND ec.category IS NOT NULL
            ORDER BY ec.created_at DESC
            """,
            (days,),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    if not rows:
        return {"patterns": [], "sample_size": 0, "categories_analyzed": [], "period_days": days}

    # Group by category
    category_errors: dict[str, list[dict]] = defaultdict(list)
    report_ids: set[int] = set()

    for row in rows:
        cat, expert_val, ai_val, our_f, total_f, report_id = row
        report_ids.add(report_id)

        if expert_val is None:
            continue

        if ai_val is None:
            category_errors[cat].append({"type": "missed", "expert": expert_val, "ai": None})
        else:
            deviation = expert_val - ai_val
            category_errors[cat].append({
                "type": "deviation",
                "expert": expert_val,
                "ai": ai_val,
                "deviation": deviation,
            })

    total_reports = len(report_ids)
    patterns = []

    for cat, errors in category_errors.items():
        cat_name = CAT_NAMES.get(cat, cat)
        missed = [e for e in errors if e["type"] == "missed"]
        deviations = [e for e in errors if e["type"] == "deviation"]

        if missed:
            miss_rate = len(missed) / len(errors) * 100
            if miss_rate > 30:
                patterns.append({
                    "category": cat,
                    "severity": "high",
                    "pattern": (
                        f"{cat_name}: AI пропускає категорію в {miss_rate:.0f}% випадків "
                        f"({len(missed)}/{len(errors)})"
                    ),
                    "recommendation": (
                        f"Додати більше reference images для {cat_name} "
                        f"або покращити shelf scan prompt"
                    ),
                })

        if deviations:
            avg_dev = sum(abs(e["deviation"]) for e in deviations) / len(deviations)
            bias = sum(e["deviation"] for e in deviations) / len(deviations)

            if avg_dev > 15:
                direction = "занижує" if bias > 0 else "завищує"
                patterns.append({
                    "category": cat,
                    "severity": "high",
                    "pattern": (
                        f"{cat_name}: AI систематично {direction} на {avg_dev:.0f}% "
                        f"(bias: {bias:+.0f}%)"
                    ),
                    "recommendation": (
                        f"Перевірити counting logic для {cat_name}. "
                        f"{'Під-рахунок наших брендів' if bias > 0 else 'Пере-рахунок конкурентів'}"
                    ),
                })
            elif avg_dev > 8:
                patterns.append({
                    "category": cat,
                    "severity": "medium",
                    "pattern": f"{cat_name}: середнє відхилення {avg_dev:.0f}%",
                    "recommendation": "Прийнятно, але є простір для покращення",
                })

    return {
        "patterns": patterns,
        "sample_size": total_reports,
        "categories_analyzed": list(category_errors.keys()),
        "period_days": days,
    }


def send_weekly_accuracy_digest() -> None:
    """
    Sync job: send weekly accuracy digest to all expert Telegram IDs via Bot API.
    Registered in scheduler (BackgroundScheduler) — no async needed.
    """
    import httpx

    token = os.environ.get("PHOTO_REPORT_BOT_TOKEN", "")
    if not token:
        logger.warning("[Learning] PHOTO_REPORT_BOT_TOKEN not set — skipping weekly digest")
        return

    expert_ids: list[int] = [441389791, 424503938, 5253694737]

    try:
        patterns = analyze_correction_patterns(days=7)
    except Exception as e:
        logger.error(f"[Learning] analyze_correction_patterns failed: {e}", exc_info=True)
        return

    if patterns["sample_size"] == 0:
        logger.info("[Learning] No corrections this week — skipping digest")
        return

    lines = [
        "Тижневий звіт точності Alex Photo Report",
        f"Період: останні 7 днів",
        f"Корекцій проаналізовано: {patterns['sample_size']}",
        "",
    ]

    for p in patterns["patterns"]:
        icon = "🔴" if p["severity"] == "high" else "🟡"
        lines.append(f"{icon} {p['pattern']}")
        lines.append(f"   Рекомендація: {p['recommendation']}")
        lines.append("")

    if not patterns["patterns"]:
        lines.append("Систематичних помилок не виявлено!")

    text = "\n".join(lines)
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    with httpx.Client(timeout=10) as client:
        for tg_id in expert_ids:
            try:
                client.post(url, json={"chat_id": tg_id, "text": text})
            except Exception as e:
                logger.error(f"[Learning] Failed to send digest to {tg_id}: {e}")
