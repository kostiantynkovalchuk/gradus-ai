import json
import logging
from database import get_db_connection

logger = logging.getLogger(__name__)


def get_or_create_agent(telegram_id: int, full_name: str) -> dict:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, telegram_id, full_name, region, role FROM photo_agents WHERE telegram_id = %s", (telegram_id,))
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO photo_agents (telegram_id, full_name, role) VALUES (%s, %s, 'agent') RETURNING id, telegram_id, full_name, region, role",
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


def save_report(agent_id: int, point_name: str, report: dict,
                photo_file_ids: list, comment: str) -> int:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO photo_reports
                (agent_id, trade_point_name, trade_point_type, score, passed,
                 errors, shelf_share, brands_found, raw_ai_response,
                 photo_count, has_gps, agent_comment)
                VALUES (%s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s::jsonb,
                        %s::jsonb, %s, %s, %s)
                RETURNING id""",
            (
                agent_id,
                point_name,
                report.get("trade_point_type", "unknown"),
                report.get("score", 0),
                report.get("passed", False),
                json.dumps(report.get("errors", []), ensure_ascii=False),
                json.dumps(report.get("shelf_share", {}), ensure_ascii=False),
                json.dumps(report.get("brands_found", {}), ensure_ascii=False),
                json.dumps(report, ensure_ascii=False),
                len(photo_file_ids),
                report.get("photo_quality", {}).get("has_gps", False),
                comment,
            )
        )
        report_id = cur.fetchone()[0]

        for i, file_id in enumerate(photo_file_ids):
            cur.execute(
                "INSERT INTO photo_report_images (report_id, file_id, sequence_number) VALUES (%s, %s, %s)",
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


def get_agent_stats(telegram_id: int) -> dict:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN passed THEN 1 ELSE 0 END) as passed_count,
                ROUND(AVG(score)::numeric, 1) as avg_score
                FROM photo_reports WHERE agent_id = %s
                AND created_at > NOW() - INTERVAL '30 days'""",
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
