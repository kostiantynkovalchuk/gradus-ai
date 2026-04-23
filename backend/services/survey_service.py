"""
HR Survey Service — Easter Holiday 2026
Handles broadcasting, voting, scoreboards, and manual close.
"""
import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import psycopg2

logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_MAYA_BOT_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 1: get_survey_observers
# ─────────────────────────────────────────────────────────────────────────────

async def get_survey_observers() -> list[int]:
    """
    Returns telegram_ids of developer + admin_hr users.
    Fetched live from hr_users — no hardcoded IDs.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT telegram_id FROM hr_users
                WHERE access_level IN ('developer', 'admin_hr')
                  AND telegram_id IS NOT NULL
                  AND is_active = true
                """
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 2: broadcast_survey
# ─────────────────────────────────────────────────────────────────────────────

async def broadcast_survey(survey_id: str) -> dict:
    """Sends survey to all active hr_users with inline keyboard."""
    import asyncio

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT question FROM hr_surveys WHERE survey_id = %s",
                (survey_id,)
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        logger.error(f"[SurveyService] survey not found: {survey_id}")
        return {"sent": 0, "failed": 0}

    question = row[0]

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT telegram_id FROM hr_users WHERE telegram_id IS NOT NULL AND is_active = true"
            )
            recipients = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    sent = 0
    failed = 0
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    async with httpx.AsyncClient(timeout=10) as client:
        for tg_id in recipients:
            try:
                await client.post(url, json={
                    "chat_id": tg_id,
                    "text": question,
                    "parse_mode": "Markdown",
                    "reply_markup": {
                        "inline_keyboard": [[
                            {"text": "✅ Так", "callback_data": f"survey_{survey_id}_yes"},
                            {"text": "❌ Ні",  "callback_data": f"survey_{survey_id}_no"},
                        ]]
                    }
                })
                sent += 1
            except Exception as e:
                failed += 1
                logger.warning(f"[SurveyService] broadcast failed for {tg_id}: {e}")
            await asyncio.sleep(0.05)

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE hr_surveys SET sent_count = %s WHERE survey_id = %s",
                (sent, survey_id)
            )
            conn.commit()
    finally:
        conn.close()

    logger.info(f"[SurveyService] broadcast {survey_id}: sent={sent} failed={failed}")
    return {"sent": sent, "failed": failed}


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 3: get_results
# ─────────────────────────────────────────────────────────────────────────────

async def get_results(survey_id: str) -> dict:
    """Returns current vote counts and percentages."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT answer, COUNT(*) FROM hr_survey_votes WHERE survey_id = %s GROUP BY answer",
                (survey_id,)
            )
            rows = cur.fetchall()
            cur.execute(
                "SELECT sent_count FROM hr_surveys WHERE survey_id = %s",
                (survey_id,)
            )
            survey_row = cur.fetchone()
    finally:
        conn.close()

    counts = {r[0]: int(r[1]) for r in rows}
    yes_count = counts.get("yes", 0)
    no_count  = counts.get("no",  0)
    total     = yes_count + no_count
    sent      = survey_row[0] if survey_row else 0

    yes_pct = round(yes_count / total * 100, 1) if total > 0 else 0.0
    no_pct  = round(no_count  / total * 100, 1) if total > 0 else 0.0

    return {
        "yes":   {"count": yes_count, "pct": yes_pct},
        "no":    {"count": no_count,  "pct": no_pct},
        "total": total,
        "sent":  sent,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 4: _build_scoreboard_text
# ─────────────────────────────────────────────────────────────────────────────

async def _build_scoreboard_text(survey_id: str) -> str:
    r = await get_results(survey_id)
    kyiv_time = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%H:%M")

    def bar(pct: float) -> str:
        filled = int(pct / 10)
        return "█" * filled + "░" * (10 - filled)

    return (
        f"📊 *Опитування: Вихідний 13/04 — LIVE*\n\n"
        f"✅ Так {bar(r['yes']['pct'])} "
        f"{r['yes']['pct']}% ({r['yes']['count']})\n"
        f"❌ Ні  {bar(r['no']['pct'])}  "
        f"{r['no']['pct']}% ({r['no']['count']})\n\n"
        f"👥 Проголосувало: {r['total']} з {r['sent']}\n"
        f"🕐 Оновлено: {kyiv_time}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 5: post_scoreboard
# ─────────────────────────────────────────────────────────────────────────────

async def post_scoreboard(survey_id: str) -> None:
    """Posts initial scoreboard to observers. Stores message_ids for future edits."""
    text = await _build_scoreboard_text(survey_id)
    observers = await get_survey_observers()
    targets = []

    async with httpx.AsyncClient(timeout=10) as client:
        for tg_id in observers:
            try:
                resp = await client.post(
                    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                    json={"chat_id": tg_id, "text": text, "parse_mode": "Markdown"}
                )
                data = resp.json()
                msg_id = data["result"]["message_id"]
                targets.append({"chat_id": tg_id, "msg_id": msg_id})
            except Exception as e:
                logger.error(f"[SurveyService] post_scoreboard failed for {tg_id}: {e}")

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hr_survey_meta (survey_id, scoreboard_targets)
                VALUES (%s, %s)
                ON CONFLICT (survey_id) DO UPDATE
                SET scoreboard_targets = EXCLUDED.scoreboard_targets
                """,
                (survey_id, json.dumps(targets))
            )
            conn.commit()
    finally:
        conn.close()

    logger.info(f"[SurveyService] scoreboard posted to {len(targets)} observers")


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 6: update_scoreboard
# ─────────────────────────────────────────────────────────────────────────────

async def update_scoreboard(survey_id: str) -> None:
    """Edits existing scoreboard messages. 3-second debounce."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT scoreboard_targets, last_edit_at FROM hr_survey_meta WHERE survey_id = %s",
                (survey_id,)
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row or not row[0]:
        return

    raw_targets, last_edit_at = row
    targets = raw_targets if isinstance(raw_targets, list) else json.loads(raw_targets)

    # Debounce: skip if edited less than 3 seconds ago
    if last_edit_at is not None:
        elapsed = (datetime.now(timezone.utc) - last_edit_at.replace(tzinfo=timezone.utc)).total_seconds()
        if elapsed < 3:
            return

    text = await _build_scoreboard_text(survey_id)

    async with httpx.AsyncClient(timeout=10) as client:
        for target in targets:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{TOKEN}/editMessageText",
                    json={
                        "chat_id": target["chat_id"],
                        "message_id": target["msg_id"],
                        "text": text,
                        "parse_mode": "Markdown",
                    }
                )
            except Exception as e:
                if "message is not modified" not in str(e).lower():
                    logger.error(f"[SurveyService] update_scoreboard failed: {e}")

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE hr_survey_meta SET last_edit_at = NOW() WHERE survey_id = %s",
                (survey_id,)
            )
            conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 7: register_vote
# ─────────────────────────────────────────────────────────────────────────────

async def register_vote(survey_id: str, telegram_id: int, answer: str) -> dict:
    """Records or updates a user's vote."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_open FROM hr_surveys WHERE survey_id = %s",
                (survey_id,)
            )
            survey_row = cur.fetchone()
            if not survey_row:
                return {"status": "not_found"}
            if not survey_row[0]:
                return {"status": "closed"}

            cur.execute(
                "SELECT id FROM hr_users WHERE telegram_id = %s AND is_active = true",
                (telegram_id,)
            )
            user_row = cur.fetchone()
            if not user_row:
                return {"status": "unauthorized"}

            user_id = user_row[0]
            cur.execute(
                """
                INSERT INTO hr_survey_votes (survey_id, user_id, answer)
                VALUES (%s, %s, %s)
                ON CONFLICT (survey_id, user_id)
                DO UPDATE SET answer = EXCLUDED.answer, voted_at = NOW()
                """,
                (survey_id, user_id, answer)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"[SurveyService] register_vote error: {e}", exc_info=True)
        return {"status": "error"}
    finally:
        conn.close()

    results = await get_results(survey_id)
    return {"status": "ok", "answer": answer, "results": results}


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 8: close_survey
# ─────────────────────────────────────────────────────────────────────────────

async def close_survey(survey_id: str) -> None:
    """Manually closes survey. Updates scoreboard with final result."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE hr_surveys SET is_open = FALSE WHERE survey_id = %s",
                (survey_id,)
            )
            conn.commit()
    finally:
        conn.close()

    r = await get_results(survey_id)
    yes_count = r["yes"]["count"]
    no_count  = r["no"]["count"]
    winner    = "yes" if yes_count >= no_count else "no"
    winner_label = "✅ Так" if winner == "yes" else "❌ Ні"

    def bar(pct: float) -> str:
        filled = int(pct / 10)
        return "█" * filled + "░" * (10 - filled)

    final_text = (
        f"📊 *Опитування завершено: Вихідний 13/04*\n\n"
        f"✅ Так {bar(r['yes']['pct'])} {r['yes']['pct']}% ({r['yes']['count']})\n"
        f"❌ Ні  {bar(r['no']['pct'])}  {r['no']['pct']}% ({r['no']['count']})\n\n"
        f"👥 Всього проголосувало: {r['total']} з {r['sent']}\n"
        f"🏆 Результат: *{winner_label}*"
    )

    # Fetch scoreboard targets
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT scoreboard_targets FROM hr_survey_meta WHERE survey_id = %s",
                (survey_id,)
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row and row[0]:
        raw_targets = row[0]
        targets = raw_targets if isinstance(raw_targets, list) else json.loads(raw_targets)
        async with httpx.AsyncClient(timeout=10) as client:
            for target in targets:
                try:
                    await client.post(
                        f"https://api.telegram.org/bot{TOKEN}/editMessageText",
                        json={
                            "chat_id": target["chat_id"],
                            "message_id": target["msg_id"],
                            "text": final_text,
                            "parse_mode": "Markdown",
                        }
                    )
                except Exception as e:
                    logger.error(f"[SurveyService] close_survey edit failed: {e}")

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE hr_survey_meta
                SET final_result = %s, closed_at = NOW()
                WHERE survey_id = %s
                """,
                (winner, survey_id)
            )
            conn.commit()
    finally:
        conn.close()

    logger.info(f"[SurveyService] survey {survey_id} closed. Winner: {winner_label}")
