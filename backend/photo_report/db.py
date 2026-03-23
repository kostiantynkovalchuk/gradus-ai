import json
import logging
from database import get_db_connection

logger = logging.getLogger(__name__)


def get_or_create_agent(telegram_id: int, full_name: str) -> dict:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, telegram_id, full_name, region, role FROM photo_agents WHERE telegram_id = %s",
            (telegram_id,)
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO photo_agents (telegram_id, full_name, role) "
                "VALUES (%s, %s, 'agent') "
                "RETURNING id, telegram_id, full_name, region, role",
                (telegram_id, full_name)
            )
            row = cur.fetchone()
            conn.commit()
        cur.close()
        return {
            "id": row[0],
            "telegram_id": row[1],
            "full_name": row[2],
            "region": row[3],
            "role": row[4],
        }
    finally:
        conn.close()


def save_report(
    agent_id: int,
    point_name: str,
    scored_report: dict,
    vision_raw: dict,
    photo_file_ids: list,
    comment: str
) -> int:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO photo_reports
                (agent_id, trade_point_name, trade_point_type, score, passed,
                 errors, shelf_share, brands_found, raw_ai_response,
                 vision_raw_json, photo_count, has_gps, agent_comment)
                VALUES (%s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s::jsonb,
                        %s::jsonb, %s::jsonb, %s, %s, %s)
                RETURNING id""",
            (
                agent_id,
                point_name,
                scored_report.get("trade_point_type", "retail"),
                scored_report.get("score", 0),
                scored_report.get("passed", False),
                json.dumps(scored_report.get("errors", []), ensure_ascii=False),
                json.dumps(scored_report.get("shelf_share", {}), ensure_ascii=False),
                json.dumps(scored_report.get("brands_found", {}), ensure_ascii=False),
                json.dumps(scored_report, ensure_ascii=False),
                json.dumps(vision_raw, ensure_ascii=False),
                len(photo_file_ids),
                scored_report.get("photo_quality", {}).get("has_overview", False),
                comment,
            )
        )
        report_id = cur.fetchone()[0]

        for i, file_id in enumerate(photo_file_ids):
            cur.execute(
                "INSERT INTO photo_report_images (report_id, file_id, sequence_number) "
                "VALUES (%s, %s, %s)",
                (report_id, file_id, i + 1)
            )
        conn.commit()
        cur.close()
        return report_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_report_photos(report_id: int, photos_bytes: list[bytes]) -> int:
    if not photos_bytes:
        return 0
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        stored = 0
        for i, photo_bytes in enumerate(photos_bytes):
            cur.execute(
                "INSERT INTO report_photos (report_id, photo_order, photo_data, size_bytes) "
                "VALUES (%s, %s, %s, %s)",
                (report_id, i + 1, photo_bytes, len(photo_bytes))
            )
            stored += 1
        conn.commit()
        cur.close()
        logger.info(f"Stored {stored} photos for report #{report_id}")
        return stored
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to store photos for report #{report_id}: {e}")
        return 0
    finally:
        conn.close()


def get_agent_stats(telegram_id: int) -> dict:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN passed THEN 1 ELSE 0 END) as passed_count,
                ROUND(AVG(score)::numeric, 1) as avg_score
                FROM photo_reports pr
                JOIN photo_agents pa ON pa.id = pr.agent_id
                WHERE pa.telegram_id = %s
                AND pr.created_at > NOW() - INTERVAL '30 days'""",
            (telegram_id,)
        )
        row = cur.fetchone()
        cur.close()
        return {
            "total": row[0] or 0,
            "passed_count": row[1] or 0,
            "avg_score": float(row[2]) if row[2] else 0,
        }
    finally:
        conn.close()


def save_expert_correction(
    report_id: int,
    expert_telegram_id: int,
    expert_name: str,
    parsed: dict,
) -> int:
    """Save an expert's manual correction for a report. Returns correction id."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO expert_corrections
                (report_id, expert_telegram_id, expert_name,
                 category, true_share, our_facings, total_facings, raw_text)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                report_id,
                expert_telegram_id,
                expert_name,
                parsed.get("category"),
                parsed.get("true_share"),
                parsed.get("our_facings"),
                parsed.get("total_facings"),
                parsed.get("raw_text", ""),
            ),
        )
        correction_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        logger.info(
            f"[PhotoReport] Expert correction #{correction_id} saved for report #{report_id} "
            f"by {expert_name} ({expert_telegram_id})"
        )
        return correction_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_accuracy_metrics(days: int = 30) -> dict:
    """
    Return accuracy metrics comparing AI predictions vs expert corrections.
    Used by the /hr/api/accuracy endpoint.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                COUNT(DISTINCT ec.report_id)             AS corrected_reports,
                COUNT(ec.id)                              AS total_corrections,
                COUNT(DISTINCT ec.category)               AS categories_corrected,
                AVG(ABS(
                    COALESCE(
                        (pr.shelf_share->ec.category->>'percent')::float,
                        0
                    ) - ec.true_share
                ))                                        AS avg_share_error_pct,
                ec.category                               AS most_corrected_category,
                COUNT(ec.id)                              AS cat_count
            FROM expert_corrections ec
            JOIN photo_reports pr ON pr.id = ec.report_id
            WHERE ec.created_at > NOW() - INTERVAL '%s days'
              AND ec.true_share IS NOT NULL
            GROUP BY ec.category
            ORDER BY cat_count DESC
            """,
            (days,),
        )
        rows = cur.fetchall()

        total_corrections = 0
        corrected_reports = 0
        avg_errors: list[float] = []
        by_category: dict = {}

        for row in rows:
            corrected_reports = max(corrected_reports, row[0] or 0)
            total_corrections += row[1] or 0
            if row[3] is not None:
                avg_errors.append(float(row[3]))
            cat = row[4]
            if cat:
                by_category[cat] = {
                    "corrections": row[1] or 0,
                    "avg_share_error_pct": round(float(row[3]), 1) if row[3] else None,
                }

        cur.execute(
            """
            SELECT COUNT(*) FROM photo_reports
            WHERE created_at > NOW() - INTERVAL '%s days'
            """,
            (days,),
        )
        total_reports = cur.fetchone()[0] or 0

        cur.execute(
            """
            SELECT ec.id, ec.report_id, ec.expert_name, ec.category,
                   ec.true_share, ec.our_facings, ec.total_facings,
                   ec.raw_text, ec.created_at
            FROM expert_corrections ec
            ORDER BY ec.created_at DESC
            LIMIT 10
            """,
        )
        recent_rows = cur.fetchall()
        recent = [
            {
                "id": r[0],
                "report_id": r[1],
                "expert_name": r[2],
                "category": r[3],
                "true_share": r[4],
                "our_facings": r[5],
                "total_facings": r[6],
                "raw_text": r[7],
                "created_at": r[8].isoformat() if r[8] else None,
            }
            for r in recent_rows
        ]

        cur.close()
        return {
            "period_days": days,
            "total_reports": total_reports,
            "corrected_reports": corrected_reports,
            "correction_rate_pct": (
                round(corrected_reports / total_reports * 100, 1) if total_reports > 0 else 0
            ),
            "total_corrections": total_corrections,
            "avg_share_error_pct": round(sum(avg_errors) / len(avg_errors), 1) if avg_errors else None,
            "by_category": by_category,
            "recent_corrections": recent,
        }
    finally:
        conn.close()
