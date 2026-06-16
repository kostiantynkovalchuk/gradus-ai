"""
Sara — Telegram webhook (Step 2: plumbing only, no brain).

Pattern note: structured like alex_avtd_webhook.py (bare router, full-path
decorator, request.json + immediate ack) BUT uses the ack-first +
asyncio.create_task background split from telegram_webhook.py's hunt handler —
because Sara's real processing (STT -> Claude -> TTS) will be too slow to run
inside the webhook response.

For now process_update only:
  1. dedups the Telegram update_id (idempotency guard, per Rules.rtf)
  2. logs what arrived
No STT, no Claude, no TTS yet.
"""
import os
import asyncio
import logging
import psycopg2
from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

sara_router = APIRouter()

SARA_BOT_TOKEN = os.getenv("SARA_BOT_TOKEN", "")
DB_URL = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")


async def process_update(update: dict):
    """Background worker. Runs AFTER Telegram has already been acked."""
    update_id = update.get("update_id")

    # --- Idempotency guard: insert update_id first; skip if already seen ---
    if update_id is not None and DB_URL:
        try:
            with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sara_inbound_updates (update_id) "
                    "VALUES (%s) ON CONFLICT (update_id) DO NOTHING",
                    (update_id,),
                )
                conn.commit()
                if cur.rowcount == 0:
                    # row already existed -> Telegram retry or double-tap
                    logger.info(f"🔁 Sara: duplicate update {update_id} ignored")
                    return
        except Exception as e:
            # On DB error, proceed rather than drop the user's message.
            # (A rare double-process is better than silent message loss.)
            logger.error(f"Sara dedup check failed for update {update_id}: {e}")

    # --- For now: just log what arrived. No processing yet. ---
    msg = update.get("message") or update.get("edited_message") or {}
    chat_id = msg.get("chat", {}).get("id")
    has_text = bool(msg.get("text"))
    has_voice = bool(msg.get("voice"))
    logger.info(
        f"📩 Sara update {update_id}: chat={chat_id} "
        f"text={has_text} voice={has_voice}"
    )


@sara_router.post("/webhook/sara")
async def sara_webhook(request: Request):
    # Guard: if token not set, silently ack (don't error Telegram)
    if not SARA_BOT_TOKEN:
        return {"ok": True}
    try:
        update = await request.json()
    except Exception:
        return {"ok": True}            # ack even on a malformed body

    # Fire-and-forget: hand off to background, ack Telegram immediately
    asyncio.create_task(process_update(update))
    return {"ok": True}
