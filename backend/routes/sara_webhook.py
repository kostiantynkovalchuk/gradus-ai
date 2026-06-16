"""
Sara — Telegram webhook + echo loop (Step 3).

Voice message -> download OGG from Telegram -> ElevenLabs STT (Scribe) ->
ElevenLabs TTS in Sara's voice (Clarice) -> ffmpeg wrap to OGG/Opus ->
sendVoice back. Still NO brain — Sara just repeats what you said, in her voice.

The blocking ElevenLabs SDK + ffmpeg calls run via asyncio.to_thread so they
do NOT block the shared event loop — other bots (Maya HR, Solomon) stay
responsive during the multi-second STT/TTS. DB dedup uses psycopg2 (codebase
convention). Webhook acks immediately, all work happens in the background task.
"""
import os
import asyncio
import logging
import subprocess
import tempfile

import httpx
import psycopg2
from fastapi import APIRouter, Request

try:
    from elevenlabs import ElevenLabs            # canonical public import
except ImportError:
    from elevenlabs.client import ElevenLabs     # fallback per SDK source layout

logger = logging.getLogger(__name__)

sara_router = APIRouter()

SARA_BOT_TOKEN = os.getenv("SARA_BOT_TOKEN", "")
DB_URL = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")
ELEVEN_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")

TELEGRAM_API = f"https://api.telegram.org/bot{SARA_BOT_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{SARA_BOT_TOKEN}"

# SDK auto-reads ELEVENLABS_API_KEY from env.
_eleven = ElevenLabs()


# ---------- blocking helpers (run off the event loop via asyncio.to_thread) ----------

def _transcribe(ogg_bytes: bytes) -> str:
    """ElevenLabs STT. Accepts OGG/Opus directly; language auto-detected."""
    result = _eleven.speech_to_text.convert(
        model_id="scribe_v1",
        file=ogg_bytes,
        tag_audio_events=False,
    )
    return (result.text or "").strip()


def _synthesize_to_ogg(text: str) -> bytes:
    """ElevenLabs TTS (Clarice, multilingual) -> Opus, then ffmpeg-wrap to a
    clean OGG/Opus container that Telegram sendVoice reliably accepts."""
    audio_gen = _eleven.text_to_speech.convert(
        ELEVEN_VOICE_ID,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="opus_48000_128",
    )
    raw = b"".join(audio_gen)

    with tempfile.NamedTemporaryFile(suffix=".bin") as fin, \
         tempfile.NamedTemporaryFile(suffix=".ogg") as fout:
        fin.write(raw)
        fin.flush()
        subprocess.run(
            ["ffmpeg", "-y", "-i", fin.name,
             "-c:a", "libopus", "-b:a", "128k", "-f", "ogg", fout.name],
            check=True, capture_output=True,
        )
        fout.seek(0)
        return fout.read()


# ---------- async pipeline ----------

async def _download_voice(file_id: str) -> bytes:
    async with httpx.AsyncClient(timeout=60) as hc:
        meta = await hc.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id})
        file_path = meta.json()["result"]["file_path"]
        audio = await hc.get(f"{TELEGRAM_FILE_API}/{file_path}")
        return audio.content


async def _send_voice(chat_id: int, ogg_bytes: bytes):
    async with httpx.AsyncClient(timeout=60) as hc:
        files = {"voice": ("sara.ogg", ogg_bytes, "audio/ogg")}
        await hc.post(f"{TELEGRAM_API}/sendVoice",
                      data={"chat_id": chat_id}, files=files)


async def _send_text(chat_id: int, text: str):
    async with httpx.AsyncClient(timeout=30) as hc:
        await hc.post(f"{TELEGRAM_API}/sendMessage",
                      data={"chat_id": chat_id, "text": text})


async def _chat_action(chat_id: int, action: str):
    try:
        async with httpx.AsyncClient(timeout=15) as hc:
            await hc.post(f"{TELEGRAM_API}/sendChatAction",
                          data={"chat_id": chat_id, "action": action})
    except Exception:
        pass  # cosmetic only — never let this break the flow


async def handle_voice(chat_id: int, file_id: str):
    """Echo loop: STT -> TTS in Sara's voice -> sendVoice. No brain yet."""
    try:
        await _chat_action(chat_id, "record_voice")
        ogg_in = await _download_voice(file_id)

        transcript = await asyncio.to_thread(_transcribe, ogg_in)
        logger.info(f"🗣️ Sara STT: {transcript!r}")
        if not transcript:
            await _send_text(chat_id, "Sorry, I couldn't hear that — try again?")
            return

        ogg_out = await asyncio.to_thread(_synthesize_to_ogg, transcript)
        await _send_voice(chat_id, ogg_out)
        logger.info(f"🔊 Sara echoed {len(ogg_out)} bytes to chat {chat_id}")
    except Exception as e:
        logger.error(f"Sara voice echo failed for chat {chat_id}: {e}")
        try:
            await _send_text(chat_id, "Something went wrong on my side — try again in a moment.")
        except Exception:
            pass


async def process_update(update: dict):
    """Background worker. Runs AFTER Telegram has been acked."""
    update_id = update.get("update_id")

    # --- idempotency guard ---
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
                    logger.info(f"🔁 Sara: duplicate update {update_id} ignored")
                    return
        except Exception as e:
            logger.error(f"Sara dedup check failed for update {update_id}: {e}")

    msg = update.get("message") or update.get("edited_message") or {}
    chat_id = msg.get("chat", {}).get("id")
    if chat_id is None:
        return

    voice = msg.get("voice")
    if voice and voice.get("file_id"):
        await handle_voice(chat_id, voice["file_id"])
        return

    if msg.get("text"):
        await _send_text(chat_id, "Send me a voice message and I'll echo it back 🎤")


@sara_router.post("/webhook/sara")
async def sara_webhook(request: Request):
    if not SARA_BOT_TOKEN:
        return {"ok": True}
    try:
        update = await request.json()
    except Exception:
        return {"ok": True}
    asyncio.create_task(process_update(update))
    return {"ok": True}
