"""
Maya Broadcast Service
======================
Handles broadcasting messages from the HR Broadcast private group to all active employees.
Supports: text, photo, video, document, audio, sticker, poll.
"""
import asyncio
import logging
import os
from typing import Optional

import httpx
import psycopg2

logger = logging.getLogger(__name__)

TOKEN    = os.environ.get("TELEGRAM_MAYA_BOT_TOKEN", "")
GROUP_ID = int(os.environ.get("MAYA_BROADCAST_GROUP_ID", "0"))
DB_URL   = os.environ.get("DATABASE_URL", "")

_TG_API = f"https://api.telegram.org/bot{TOKEN}"

CONTENT_TYPE_LABELS = {
    "text":     "📝 Текст",
    "photo":    "🖼 Фото",
    "video":    "🎥 Відео",
    "document": "📎 Документ",
    "audio":    "🎵 Аудіо",
    "sticker":  "😊 Стікер",
    "poll":     "📊 Опитування",
}


# ─────────────────────────────────────────────────────────────────────────────
# Guard helpers
# ─────────────────────────────────────────────────────────────────────────────

def is_broadcast_group(chat_id: int) -> bool:
    return GROUP_ID != 0 and chat_id == GROUP_ID


async def is_authorized_broadcaster(telegram_id: int) -> bool:
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM hr_users
                   WHERE telegram_id = %s
                     AND access_level IN ('hr_admin', 'developer')
                     AND is_active = TRUE
                   LIMIT 1""",
                (telegram_id,)
            )
            return cur.fetchone() is not None
    except Exception as e:
        logger.warning(f"[Broadcast] is_authorized_broadcaster error: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

async def create_broadcast_log(
    initiated_by: int,
    initiated_name: str,
    content_type: str,
    content_preview: str,
    file_id: Optional[str] = None,
) -> int:
    with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO hr_broadcast_log
               (initiated_by, initiated_name, content_type, content_preview, file_id, status)
               VALUES (%s, %s, %s, %s, %s, 'pending')
               RETURNING id""",
            (initiated_by, initiated_name, content_type, content_preview, file_id)
        )
        broadcast_id = cur.fetchone()[0]
        conn.commit()
    logger.info(f"[Broadcast] Created log id={broadcast_id}, type={content_type}, by={initiated_name}")
    return broadcast_id


async def cancel_broadcast(broadcast_id: int) -> None:
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE hr_broadcast_log SET status = 'cancelled' WHERE id = %s",
                (broadcast_id,)
            )
            conn.commit()
        logger.info(f"[Broadcast] Cancelled id={broadcast_id}")
    except Exception as e:
        logger.warning(f"[Broadcast] cancel_broadcast error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Confirmation card
# ─────────────────────────────────────────────────────────────────────────────

async def send_confirmation_card(
    broadcast_id: int,
    content_type: str,
    content_preview: str,
    sender_name: str,
) -> int:
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM hr_users WHERE telegram_id IS NOT NULL AND is_active = TRUE"
            )
            recipient_count = cur.fetchone()[0]
    except Exception as e:
        logger.warning(f"[Broadcast] Could not count recipients: {e}")
        recipient_count = 0

    type_label   = CONTENT_TYPE_LABELS.get(content_type, content_type)
    preview_text = (content_preview or "—")[:100]

    card_text = (
        f"📤 *Готово до розсилки*\n\n"
        f"👤 Ініціатор: {sender_name}\n"
        f"📋 Тип: {type_label}\n"
        f"📝 Зміст: {preview_text}\n"
        f"👥 Отримувачів: {recipient_count}\n\n"
        f"Розіслати всім співробітникам?"
    )

    payload = {
        "chat_id": GROUP_ID,
        "text": card_text,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ Розіслати",  "callback_data": f"broadcast_confirm_{broadcast_id}"},
                {"text": "❌ Скасувати", "callback_data": f"broadcast_cancel_{broadcast_id}"},
            ]]
        },
    }

    msg_id = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{_TG_API}/sendMessage", json=payload)
        data = resp.json()
        msg_id = data.get("result", {}).get("message_id", 0)

    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE hr_broadcast_log SET confirmation_msg_id = %s WHERE id = %s",
                (msg_id, broadcast_id)
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[Broadcast] Could not store confirmation_msg_id: {e}")

    return msg_id


# ─────────────────────────────────────────────────────────────────────────────
# Execute broadcast
# ─────────────────────────────────────────────────────────────────────────────

async def execute_broadcast(broadcast_id: int, original_message: dict) -> dict:
    """Send content to all active hr_users. Returns {"sent": n, "failed": n}."""
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT telegram_id FROM hr_users WHERE telegram_id IS NOT NULL AND is_active = TRUE"
            )
            recipients = [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"[Broadcast] Could not fetch recipients: {e}")
        return {"sent": 0, "failed": 0}

    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE hr_broadcast_log SET status = 'sending', recipient_count = %s WHERE id = %s",
                (len(recipients), broadcast_id)
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[Broadcast] Could not update status to sending: {e}")

    logger.info(f"[Broadcast] Starting id={broadcast_id} → {len(recipients)} recipients")

    sent = failed = 0
    async with httpx.AsyncClient(timeout=15.0) as client:
        for tg_id in recipients:
            try:
                ok = await _send_to_user(client, tg_id, original_message)
                if ok:
                    sent += 1
                else:
                    failed += 1
            except Exception as e:
                logger.debug(f"[Broadcast] Failed for {tg_id}: {e}")
                failed += 1
            await asyncio.sleep(0.05)

    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE hr_broadcast_log
                   SET status = 'completed', sent_count = %s, failed_count = %s, completed_at = NOW()
                   WHERE id = %s""",
                (sent, failed, broadcast_id)
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[Broadcast] Could not update completed status: {e}")

    logger.info(f"[Broadcast] id={broadcast_id} done: sent={sent} failed={failed}")
    return {"sent": sent, "failed": failed}


async def _send_to_user(client: httpx.AsyncClient, tg_id: int, msg: dict) -> bool:
    """Dispatch one message to one recipient. Returns True on success."""
    if msg.get("text"):
        resp = await client.post(f"{_TG_API}/sendMessage", json={
            "chat_id": tg_id,
            "text": msg["text"],
            "parse_mode": "HTML",
        })
        return resp.json().get("ok", False)

    if msg.get("photo"):
        payload = {"chat_id": tg_id, "photo": msg["photo"][-1]["file_id"]}
        if msg.get("caption"):
            payload["caption"] = msg["caption"]
            if msg.get("caption_entities"):
                payload["caption_entities"] = msg["caption_entities"]
        resp = await client.post(f"{_TG_API}/sendPhoto", json=payload)
        return resp.json().get("ok", False)

    if msg.get("video"):
        payload = {"chat_id": tg_id, "video": msg["video"]["file_id"]}
        if msg.get("caption"):
            payload["caption"] = msg["caption"]
            if msg.get("caption_entities"):
                payload["caption_entities"] = msg["caption_entities"]
        resp = await client.post(f"{_TG_API}/sendVideo", json=payload)
        return resp.json().get("ok", False)

    if msg.get("document"):
        payload = {"chat_id": tg_id, "document": msg["document"]["file_id"]}
        if msg.get("caption"):
            payload["caption"] = msg["caption"]
            if msg.get("caption_entities"):
                payload["caption_entities"] = msg["caption_entities"]
        resp = await client.post(f"{_TG_API}/sendDocument", json=payload)
        return resp.json().get("ok", False)

    if msg.get("audio"):
        resp = await client.post(f"{_TG_API}/sendAudio", json={
            "chat_id": tg_id, "audio": msg["audio"]["file_id"]
        })
        return resp.json().get("ok", False)

    if msg.get("sticker"):
        resp = await client.post(f"{_TG_API}/sendSticker", json={
            "chat_id": tg_id, "sticker": msg["sticker"]["file_id"]
        })
        return resp.json().get("ok", False)

    if msg.get("poll"):
        poll = msg["poll"]
        resp = await client.post(f"{_TG_API}/sendPoll", json={
            "chat_id": tg_id,
            "question": poll["question"],
            "options": [o["text"] for o in poll["options"]],
            "is_anonymous": poll.get("is_anonymous", True),
        })
        return resp.json().get("ok", False)

    return False
