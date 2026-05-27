"""
Maya Broadcast Service
======================
Handles broadcasting messages from the HR Broadcast private group to all active employees.
Supports: text, photo, video, document, audio, sticker, poll.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
import psycopg2
from psycopg2.extras import execute_values

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
    original_message: Optional[dict] = None,
) -> int:
    payload_json = json.dumps(original_message) if original_message else None
    with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO hr_broadcast_log
               (initiated_by, initiated_name, content_type, content_preview, file_id, status, payload)
               VALUES (%s, %s, %s, %s, %s, 'pending', %s)
               RETURNING id""",
            (initiated_by, initiated_name, content_type, content_preview, file_id, payload_json)
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


async def claim_pending_broadcast(broadcast_id: int) -> Optional[dict]:
    """
    Atomically transitions a broadcast from 'pending' to 'sending'.
    Returns the stored payload dict if the transition succeeded,
    None if the broadcast is already claimed, cancelled, or missing.
    This is the idempotency guard — only one caller wins the row.
    """
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE hr_broadcast_log
                      SET status = 'sending'
                    WHERE id = %s
                      AND status = 'pending'
                   RETURNING payload""",
                (broadcast_id,)
            )
            row = cur.fetchone()
            conn.commit()
        if row is None:
            return None
        payload = row[0]
        if payload is None:
            return None
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload
    except Exception as e:
        logger.error(f"[Broadcast] claim_pending_broadcast error: {e}")
        return None


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
    recipient_rows: list = []  # (broadcast_id, tg_id, message_id)

    async with httpx.AsyncClient(timeout=15.0) as client:
        for tg_id in recipients:
            try:
                msg_id = await _send_to_user(client, tg_id, original_message)
                if msg_id is not None:
                    sent += 1
                    recipient_rows.append((broadcast_id, tg_id, msg_id))
                else:
                    failed += 1
            except Exception as e:
                logger.debug(f"[Broadcast] Failed for {tg_id}: {e}")
                failed += 1
            await asyncio.sleep(0.05)

            if len(recipient_rows) >= 50:
                _insert_recipient_batch(recipient_rows)
                recipient_rows.clear()

    if recipient_rows:
        _insert_recipient_batch(recipient_rows)

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

    try:
        from services.avpost_service import maybe_archive_from_broadcast
        maybe_archive_from_broadcast(
            text_content=original_message.get('text'),
            caption=original_message.get('caption'),
            broadcast_id=broadcast_id,
        )
    except Exception as _avp_err:
        logger.warning(f"[Broadcast] AV Post archive hook failed: {_avp_err}")

    return {"sent": sent, "failed": failed}


def _insert_recipient_batch(rows: list) -> None:
    """Bulk-insert a batch of (broadcast_id, recipient_tg_id, message_id) rows."""
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            execute_values(
                cur,
                """INSERT INTO hr_broadcast_recipients
                   (broadcast_id, recipient_tg_id, message_id, status)
                   VALUES %s""",
                [(bid, tg_id, msg_id, 'sent') for bid, tg_id, msg_id in rows],
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[Broadcast] Recipient batch insert failed: {e}")


async def _send_to_user(client: httpx.AsyncClient, tg_id: int, msg: dict) -> Optional[int]:
    """Dispatch one message to one recipient. Returns message_id on success, None on failure."""
    if msg.get("text"):
        resp = await client.post(f"{_TG_API}/sendMessage", json={
            "chat_id": tg_id,
            "text": msg["text"],
            "parse_mode": "HTML",
        })
        data = resp.json()
        if data.get("ok"):
            return data["result"]["message_id"]
        return None

    if msg.get("photo"):
        payload = {"chat_id": tg_id, "photo": msg["photo"][-1]["file_id"]}
        if msg.get("caption"):
            payload["caption"] = msg["caption"]
            if msg.get("caption_entities"):
                payload["caption_entities"] = msg["caption_entities"]
        resp = await client.post(f"{_TG_API}/sendPhoto", json=payload)
        data = resp.json()
        if data.get("ok"):
            return data["result"]["message_id"]
        return None

    if msg.get("video"):
        payload = {"chat_id": tg_id, "video": msg["video"]["file_id"]}
        if msg.get("caption"):
            payload["caption"] = msg["caption"]
            if msg.get("caption_entities"):
                payload["caption_entities"] = msg["caption_entities"]
        resp = await client.post(f"{_TG_API}/sendVideo", json=payload)
        data = resp.json()
        if data.get("ok"):
            return data["result"]["message_id"]
        return None

    if msg.get("document"):
        payload = {"chat_id": tg_id, "document": msg["document"]["file_id"]}
        if msg.get("caption"):
            payload["caption"] = msg["caption"]
            if msg.get("caption_entities"):
                payload["caption_entities"] = msg["caption_entities"]
        resp = await client.post(f"{_TG_API}/sendDocument", json=payload)
        data = resp.json()
        if data.get("ok"):
            return data["result"]["message_id"]
        return None

    if msg.get("audio"):
        resp = await client.post(f"{_TG_API}/sendAudio", json={
            "chat_id": tg_id, "audio": msg["audio"]["file_id"]
        })
        data = resp.json()
        if data.get("ok"):
            return data["result"]["message_id"]
        return None

    if msg.get("sticker"):
        resp = await client.post(f"{_TG_API}/sendSticker", json={
            "chat_id": tg_id, "sticker": msg["sticker"]["file_id"]
        })
        data = resp.json()
        if data.get("ok"):
            return data["result"]["message_id"]
        return None

    if msg.get("poll"):
        poll = msg["poll"]
        resp = await client.post(f"{_TG_API}/sendPoll", json={
            "chat_id": tg_id,
            "question": poll["question"],
            "options": [o["text"] for o in poll["options"]],
            "is_anonymous": poll.get("is_anonymous", True),
        })
        data = resp.json()
        if data.get("ok"):
            return data["result"]["message_id"]
        return None

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Recall broadcast
# ─────────────────────────────────────────────────────────────────────────────

async def execute_recall(broadcast_id: int, initiated_by: int) -> dict:
    """
    Deletes all sent messages for a broadcast.
    Returns {"recalled": N, "failed": M, "expired": 0}
    or {"error": "...", ...} on guard failures.
    """
    # 1. Atomic guard: claim the broadcast for recalling
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE hr_broadcast_log
                      SET status = 'recalling'
                    WHERE id = %s
                      AND status IN ('completed', 'sent')
                   RETURNING created_at, completed_at""",
                (broadcast_id,)
            )
            row = cur.fetchone()
            conn.commit()
    except Exception as e:
        logger.error(f"[Recall] claim error: {e}")
        return {"error": "db_error"}

    if row is None:
        return {"error": "already recalled or not eligible"}

    created_at, completed_at = row
    ref_time = completed_at or created_at
    now_utc = datetime.now(timezone.utc)
    if ref_time.tzinfo is None:
        ref_time = ref_time.replace(tzinfo=timezone.utc)
    age_hours = (now_utc - ref_time).total_seconds() / 3600

    if age_hours > 47:
        try:
            with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE hr_broadcast_log SET status = 'completed' WHERE id = %s",
                    (broadcast_id,)
                )
                conn.commit()
        except Exception:
            pass
        return {"error": "too old", "age_hours": round(age_hours, 1)}

    # 2. Fetch recipients with stored message_ids
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id, recipient_tg_id, message_id
                     FROM hr_broadcast_recipients
                    WHERE broadcast_id = %s
                      AND status = 'sent'
                      AND message_id IS NOT NULL""",
                (broadcast_id,)
            )
            recipient_rows = cur.fetchall()
    except Exception as e:
        logger.error(f"[Recall] fetch recipients error: {e}")
        return {"error": "db_error"}

    recalled = failed = 0

    async with httpx.AsyncClient(timeout=10.0) as client:
        for row_id, tg_id, msg_id in recipient_rows:
            try:
                resp = await client.post(f"{_TG_API}/deleteMessage", json={
                    "chat_id": tg_id,
                    "message_id": msg_id,
                })
                if resp.json().get("ok"):
                    recalled += 1
                    new_status = 'recalled'
                else:
                    failed += 1
                    new_status = 'recall_failed'
                    logger.debug(f"[Recall] deleteMessage failed for {tg_id}: {resp.text[:80]}")
            except Exception as e:
                failed += 1
                new_status = 'recall_failed'
                logger.debug(f"[Recall] deleteMessage exception for {tg_id}: {e}")

            try:
                with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
                    cur.execute(
                        "UPDATE hr_broadcast_recipients SET status = %s WHERE id = %s",
                        (new_status, row_id)
                    )
                    conn.commit()
            except Exception:
                pass

            await asyncio.sleep(0.04)

    # 3. Finalize
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE hr_broadcast_log SET status = 'recalled', completed_at = NOW() WHERE id = %s",
                (broadcast_id,)
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[Recall] finalize error: {e}")

    logger.info(f"[Recall] id={broadcast_id} by={initiated_by}: recalled={recalled} failed={failed}")
    return {"recalled": recalled, "failed": failed, "expired": 0}


async def get_broadcast_summary(broadcast_id: int) -> Optional[dict]:
    """Returns key fields for the recall confirmation card."""
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT id, status, sent_count, failed_count, content_type, created_at, completed_at
                     FROM hr_broadcast_log
                    WHERE id = %s""",
                (broadcast_id,)
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "id":           row[0],
            "status":       row[1],
            "sent_count":   row[2],
            "failed_count": row[3],
            "content_type": row[4],
            "created_at":   row[5],
            "completed_at": row[6],
        }
    except Exception as e:
        logger.warning(f"[Broadcast] get_broadcast_summary error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# User activity helpers (called from my_chat_member updates)
# ─────────────────────────────────────────────────────────────────────────────

async def mark_user_inactive(telegram_id: int) -> None:
    """Mark a user inactive when they block the bot."""
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE hr_users SET is_active = FALSE WHERE telegram_id = %s",
                (telegram_id,)
            )
            conn.commit()
        logger.info(f"[Broadcast] Marked user {telegram_id} inactive (bot blocked)")
    except Exception as e:
        logger.warning(f"[Broadcast] mark_user_inactive error: {e}")


async def mark_user_active(telegram_id: int) -> None:
    """Mark a user active when they unblock the bot."""
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE hr_users SET is_active = TRUE WHERE telegram_id = %s",
                (telegram_id,)
            )
            conn.commit()
        logger.info(f"[Broadcast] Marked user {telegram_id} active (bot unblocked)")
    except Exception as e:
        logger.warning(f"[Broadcast] mark_user_active error: {e}")
