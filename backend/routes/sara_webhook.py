"""
Sara — Telegram webhook + brain (Step 4).

Voice in -> ElevenLabs STT -> Claude (reply + hidden JSON assessment) ->
ElevenLabs TTS of the REPLY in Sara's voice -> sendVoice. Each turn is
persisted to sara_turns; the last few turns are fed back as conversation
history so Sara has short-term memory within a session.

Minimal-first: no per-CEFR prompts / Russian ladder / level adaptation /
beats / 25-30 session lifecycle yet. A dumb get-or-create-session exists
only because sara_turns.session_id is NOT NULL.

Blocking work (ElevenLabs SDK, Claude SDK, psycopg2, ffmpeg) runs via
asyncio.to_thread so the shared event loop (other bots) stays responsive.
"""
import os
import re
import json
import asyncio
import logging
import subprocess
import tempfile

import httpx
import psycopg2
from fastapi import APIRouter, Request

try:
    from elevenlabs import ElevenLabs
except ImportError:
    from elevenlabs.client import ElevenLabs

from anthropic import Anthropic

try:
    from services.ai_models import SONNET, HAIKU
except ImportError:
    from ai_models import SONNET, HAIKU

logger = logging.getLogger(__name__)

sara_router = APIRouter()

SARA_BOT_TOKEN = os.getenv("SARA_BOT_TOKEN", "")
DB_URL = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")
ELEVEN_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")

TELEGRAM_API = f"https://api.telegram.org/bot{SARA_BOT_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{SARA_BOT_TOKEN}"

_eleven = ElevenLabs()  # auto-reads ELEVENLABS_API_KEY

_anthropic = None
def _get_anthropic():
    global _anthropic
    if _anthropic is None:
        _anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _anthropic


SARA_SYSTEM_PROMPT_BASE = """\
OUTPUT CONTRACT (highest priority, overrides everything below):
You MUST return exactly ONE raw JSON object and nothing else — no markdown, no
code fences, no text before or after. This is true for EVERY message without
exception: even if the learner asks you a personal question, asks about you,
asks whether you speak Russian, writes to you in Russian, or says something
off-topic — your ENTIRE response is still one JSON object, and your spoken
words go INSIDE the "reply" field. Never reply in plain text. Never break the
JSON wrapper for any reason.

The JSON shape is exactly:
{
  "reply": "<your short spoken reply to the learner>",
  "assessment": {
    "cefr_estimate": "A1|A2|B1|B2|C1|C2",
    "communicative_success": true,
    "errors": [
      {"type": "short label", "original": "what they said", "correction": "corrected form"}
    ]
  }
}

WHO YOU ARE:
You are Sara, a warm, friendly personal English tutor having a spoken
conversation with one adult learner. Keep "reply" SHORT — 1 to 3 sentences —
because it is read aloud as a voice message. Be warm and encouraging, never
clinical or wordy.

LANGUAGE RULE:
Always speak English in "reply". The learner is a Russian speaker. How much
Russian scaffolding to use is governed by the LEARNER LEVEL block at the very
end of this prompt — follow it. If they speak Russian to you or ask whether you
speak Russian, answer briefly in English and gently steer them back to
practising English; never hold the conversation in Russian.

TEACHING:
When the learner makes an English mistake, gently RECAST: naturally use the
correct form in your own reply instead of lecturing or listing errors.
Acknowledge what they said first, then keep the conversation going with a
light follow-up question. Log every correction in assessment.errors (empty
list if none). "assessment" is internal and never shown to the learner.

EXAMPLE (note: Russian question still returns JSON, reply is English):
Learner: "А по-русски ты хорошо говоришь?"
You:
{"reply": "I understand a little Russian, but let's keep practising English together! Tell me — what did you do this weekend?", "assessment": {"cefr_estimate": "A2", "communicative_success": true, "errors": []}}

EXAMPLE (English with an error, recast):
Learner: "Yesterday I go to work at six."
You:
{"reply": "Wow, you went to work at six? That's early! Do you always start so early?", "assessment": {"cefr_estimate": "A2", "communicative_success": true, "errors": [{"type": "past tense", "original": "I go to work", "correction": "I went to work"}]}}"""


_LEVEL_BLOCK_A = (
    "LEARNER LEVEL: Beginner (A1-A2).\n"
    "Use very simple, short English sentences and common everyday words — one "
    "idea per sentence. When you introduce or correct a harder word, you may add "
    "a brief Russian gloss in parentheses so they understand. Be extra warm and "
    "encouraging; celebrate small wins."
)
_LEVEL_BLOCK_B = (
    "LEARNER LEVEL: Intermediate (B1-B2).\n"
    "Speak natural, clear English. Use Russian only rarely — at most a single "
    "word in parentheses for a genuinely hard term. Gently stretch them with "
    "slightly richer vocabulary and open follow-up questions."
)
_LEVEL_BLOCK_C = (
    "LEARNER LEVEL: Advanced (C1-C2).\n"
    "Speak fluent, natural English with full richness — idioms, nuance, varied "
    "structure. Do NOT use Russian at all. Treat them as a near-native "
    "conversation partner and invite precision and subtlety."
)
_LEVEL_BLOCK_DEFAULT = (
    "LEARNER LEVEL: Not yet known.\n"
    "Keep your English simple and clear for now. Offer a brief Russian word only "
    "if they seem confused. You will learn their level as you talk — adapt "
    "naturally."
)

_LEVEL_BLOCKS = {
    "A1": _LEVEL_BLOCK_A, "A2": _LEVEL_BLOCK_A,
    "B1": _LEVEL_BLOCK_B, "B2": _LEVEL_BLOCK_B,
    "C1": _LEVEL_BLOCK_C, "C2": _LEVEL_BLOCK_C,
}


def _build_system_prompt(cefr_band) -> str:
    block = _LEVEL_BLOCKS.get(cefr_band, _LEVEL_BLOCK_DEFAULT)
    return SARA_SYSTEM_PROMPT_BASE + "\n\n" + block


# ---------- copied from hunt_scorer.py (keystone JSON repair) ----------
def safe_parse_json(text: str) -> dict:
    text = re.sub(r'```json|```', '', text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')
        if text.count('"') % 2 != 0:
            text += '"'
        text += ']' * open_brackets
        text += '}' * open_braces
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Sara JSON repair failed: {e}")
            return {}


# ---------- CEFR level calibration ----------
_CEFR_TO_NUM = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}
_NUM_TO_CEFR = {v: k for k, v in _CEFR_TO_NUM.items()}
EWA_ALPHA = 0.2          # weight on the newest estimate (slow-moving level)
BAND_HYSTERESIS = 0.3    # dead-zone around band boundaries to prevent flicker


def _snap_band(rolling: float, current_band):
    """Snap a rolling float to a CEFR band, with hysteresis so the committed
    band only changes when rolling clearly crosses a boundary."""
    target_num = max(1, min(6, round(rolling)))
    if current_band is None:
        return _NUM_TO_CEFR[target_num]          # first calibration: accept directly
    current_num = _CEFR_TO_NUM.get(current_band, target_num)
    if target_num == current_num:
        return current_band
    boundary = (current_num + target_num) / 2.0
    if target_num > current_num and rolling >= boundary + BAND_HYSTERESIS:
        return _NUM_TO_CEFR[target_num]
    if target_num < current_num and rolling <= boundary - BAND_HYSTERESIS:
        return _NUM_TO_CEFR[target_num]
    return current_band                          # inside dead zone — hold steady


# ---------- blocking helpers (run via asyncio.to_thread) ----------

def _get_config_int(cur, key: str, default: int) -> int:
    cur.execute("SELECT value FROM sara_config WHERE key=%s", (key,))
    r = cur.fetchone()
    if r and r[0] is not None:
        try:
            return int(r[0])
        except (ValueError, TypeError):
            return default
    return default


def _streak_milestones(cur) -> set:
    cur.execute("SELECT value FROM sara_config WHERE key='streak_milestones'")
    r = cur.fetchone()
    if r and r[0]:
        out = set()
        for part in str(r[0]).split(","):
            part = part.strip()
            if part.isdigit():
                out.add(int(part))
        return out
    return {3, 7}


def _recap(turns: list) -> str:
    """One-sentence recap of a closed session, for next-time continuity. Haiku. Blocking."""
    convo = "\n".join(f"Learner: {u}\nSara: {s}" for (u, s) in turns if (u or s))
    if not convo.strip():
        return ""
    try:
        c = _get_anthropic()
        response = c.messages.create(
            model=HAIKU,
            max_tokens=120,
            system=(
                "Summarize this English tutoring conversation in ONE short sentence "
                "(max ~18 words), as a note to the tutor for next time — what the learner "
                "talked about and practised. Example: 'Talked about his work trip and "
                "practised past tense.' Return ONLY the sentence, no preamble."
            ),
            messages=[{"role": "user", "content": convo[:4000]}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Sara recap failed: {e}")
        return ""   # recap is best-effort; never block the session on it


def _transcribe(ogg_bytes: bytes) -> str:
    result = _eleven.speech_to_text.convert(
        model_id="scribe_v1",
        file=ogg_bytes,
        tag_audio_events=False,
    )
    return (result.text or "").strip()


def _synthesize_to_ogg(text: str) -> bytes:
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


def _prepare(tg_user_id: int):
    """Resolve the current session (expiring + recapping a stale one if needed),
    load recent history, and read the level. Blocking."""
    recap_turns = None
    opened_new = False
    with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
        idle_min = _get_config_int(cur, "session_idle_minutes", 30)

        cur.execute(
            "SELECT id, (last_activity_at < now() - (%s * interval '1 minute')) AS is_idle "
            "FROM sara_sessions WHERE tg_user_id=%s AND status='active' "
            "ORDER BY id DESC LIMIT 1",
            (idle_min, tg_user_id),
        )
        row = cur.fetchone()

        if row and not row[1]:
            session_id = row[0]                       # active and fresh → continue
        else:
            if row and row[1]:                        # active but idle → close + recap
                stale_id = row[0]
                cur.execute(
                    "UPDATE sara_sessions SET status='closed', ended_at=now() WHERE id=%s",
                    (stale_id,),
                )
                cur.execute(
                    "SELECT user_text, sara_text FROM sara_turns WHERE session_id=%s ORDER BY id",
                    (stale_id,),
                )
                recap_turns = cur.fetchall()
            cur.execute(
                "INSERT INTO sara_sessions (tg_user_id, status) VALUES (%s,'active') RETURNING id",
                (tg_user_id,),
            )
            session_id = cur.fetchone()[0]
            opened_new = True

        cur.execute(
            "SELECT user_text, sara_text FROM sara_turns WHERE session_id=%s "
            "ORDER BY id DESC LIMIT 6",
            (session_id,),
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT cefr_band, streak_days, last_session_summary "
            "FROM sara_state WHERE tg_user_id=%s",
            (tg_user_id,),
        )
        state_row = cur.fetchone()
        cefr_band = state_row[0] if state_row else None
        streak_days = (state_row[1] if state_row else 0) or 0
        last_summary = state_row[2] if state_row else None

        beat_instruction = ""
        if opened_new and last_summary:
            beat_instruction = (
                f"BEAT (open with this, warmly, then continue naturally): Welcome Felix back by name "
                f"and briefly reference last time before your normal reply. Last session summary: "
                f"\"{last_summary}\". Keep it to one short welcoming clause — do not recap in detail."
            )
            cur.execute(
                "UPDATE sara_state SET last_session_summary=NULL, updated_at=now() WHERE tg_user_id=%s",
                (tg_user_id,),
            )
        elif streak_days in _streak_milestones(cur):
            beat_instruction = (
                f"BEAT (work this into your reply, warmly): Congratulate Felix by name — this is day "
                f"{streak_days} in a row practising. One short celebratory clause, then continue normally."
            )

        conn.commit()

    history = []
    for user_text, sara_text in reversed(rows):
        if user_text:
            history.append({"role": "user", "content": user_text})
        if sara_text:
            history.append({"role": "assistant", "content": sara_text})

    # Recap the just-closed session (Haiku) and store it. Best-effort, outside the
    # first connection so we don't hold a DB conn across the LLM call.
    if recap_turns:
        summary = _recap(recap_turns)
        if summary:
            with psycopg2.connect(DB_URL) as conn2, conn2.cursor() as cur2:
                cur2.execute(
                    "INSERT INTO sara_state (tg_user_id, last_session_summary, updated_at) "
                    "VALUES (%s, %s, now()) "
                    "ON CONFLICT (tg_user_id) DO UPDATE "
                    "SET last_session_summary=EXCLUDED.last_session_summary, updated_at=now()",
                    (tg_user_id, summary),
                )
                conn2.commit()
            logger.info(f"📒 Sara session recap stored for {tg_user_id}: {summary!r}")

    logger.info(f"🗂️ Sara session {session_id} (history turns: {len(rows)})")
    return session_id, history, cefr_band, beat_instruction


def _think(transcript: str, history: list, cefr_band, beat_instruction: str = ""):
    """Claude dual-output: returns (reply_text, assessment_dict, ok). Blocking."""
    c = _get_anthropic()
    messages = list(history) + [{"role": "user", "content": transcript}]
    system = _build_system_prompt(cefr_band)
    if beat_instruction:
        system = system + "\n\n" + beat_instruction
    response = c.messages.create(
        model=SONNET,
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    raw = response.content[0].text.strip()
    data = safe_parse_json(raw)
    reply = (data.get("reply") or "").strip()
    assessment = data.get("assessment") or {}
    if not reply:
        logger.error(f"Sara _think: no reply parsed from: {raw[:200]!r}")
        return "Hmm, one moment — could you say that again?", {}, False
    return reply, assessment, True


def _persist(session_id: int, tg_user_id: int, transcript: str, reply: str, assessment: dict):
    """Log the turn, bump session activity, and recalibrate the rolling level.
    Blocking — runs via asyncio.to_thread."""
    with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sara_turns (session_id, user_text, sara_text, assessment, reply_word_count) "
            "VALUES (%s, %s, %s, %s, %s)",
            (session_id, transcript, reply, json.dumps(assessment), len(reply.split())),
        )
        cur.execute(
            "UPDATE sara_sessions SET last_activity_at=now(), message_count=message_count+1 "
            "WHERE id=%s",
            (session_id,),
        )

        # --- streak maintenance ---
        cur.execute(
            "SELECT last_practice_date, streak_days FROM sara_state WHERE tg_user_id=%s",
            (tg_user_id,),
        )
        srow = cur.fetchone()
        if srow and srow[0] is not None:
            last_date, streak = srow[0], (srow[1] or 0)
            cur.execute("SELECT (current_date - %s)", (last_date,))
            gap_days = cur.fetchone()[0]
            if gap_days == 0:
                new_streak = streak                  # already practised today
            elif gap_days == 1:
                new_streak = streak + 1              # consecutive day
            else:
                new_streak = 1                       # gap broke the streak
        else:
            new_streak = 1                           # first ever practice
        cur.execute(
            "INSERT INTO sara_state (tg_user_id, streak_days, last_practice_date, updated_at) "
            "VALUES (%s, %s, current_date, now()) "
            "ON CONFLICT (tg_user_id) DO UPDATE "
            "SET streak_days=EXCLUDED.streak_days, last_practice_date=current_date, updated_at=now()",
            (tg_user_id, new_streak),
        )

        # --- level calibration (incremental EWA + hysteresis) ---
        estimate = (assessment or {}).get("cefr_estimate")
        if estimate in _CEFR_TO_NUM:                       # skip turns with no/invalid estimate
            cur.execute(
                "SELECT cefr_rolling, cefr_band FROM sara_state WHERE tg_user_id=%s",
                (tg_user_id,),
            )
            row = cur.fetchone()
            new_num = _CEFR_TO_NUM[estimate]
            if row and row[0] is not None:
                old_rolling, old_band = row[0], row[1]
                new_rolling = EWA_ALPHA * new_num + (1 - EWA_ALPHA) * old_rolling
            else:
                old_band = row[1] if row else None
                new_rolling = float(new_num)               # seed on first estimate
            new_band = _snap_band(new_rolling, old_band)
            cur.execute(
                "INSERT INTO sara_state (tg_user_id, cefr_band, cefr_rolling, updated_at) "
                "VALUES (%s, %s, %s, now()) "
                "ON CONFLICT (tg_user_id) DO UPDATE "
                "SET cefr_band=EXCLUDED.cefr_band, cefr_rolling=EXCLUDED.cefr_rolling, updated_at=now()",
                (tg_user_id, new_band, round(new_rolling, 3)),
            )
            logger.info(
                f"📊 Sara level: user={tg_user_id} rolling={new_rolling:.2f} "
                f"band={new_band} (turn estimate {estimate})"
            )
        conn.commit()


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
        await hc.post(f"{TELEGRAM_API}/sendVoice", data={"chat_id": chat_id}, files=files)


async def _send_text(chat_id: int, text: str):
    async with httpx.AsyncClient(timeout=30) as hc:
        await hc.post(f"{TELEGRAM_API}/sendMessage", data={"chat_id": chat_id, "text": text})


async def _chat_action(chat_id: int, action: str):
    try:
        async with httpx.AsyncClient(timeout=15) as hc:
            await hc.post(f"{TELEGRAM_API}/sendChatAction", data={"chat_id": chat_id, "action": action})
    except Exception:
        pass


async def handle_voice(chat_id: int, file_id: str):
    try:
        await _chat_action(chat_id, "record_voice")
        ogg_in = await _download_voice(file_id)

        transcript = await asyncio.to_thread(_transcribe, ogg_in)
        logger.info(f"🗣️ Sara heard: {transcript!r}")
        if not transcript:
            await _send_text(chat_id, "Sorry, I couldn't hear that — try again?")
            return

        session_id, history, cefr_band, beat_instruction = await asyncio.to_thread(_prepare, chat_id)
        reply, assessment, ok = await asyncio.to_thread(
            _think, transcript, history, cefr_band, beat_instruction
        )
        logger.info(f"💭 Sara reply: {reply!r} | level={cefr_band} | beat={bool(beat_instruction)} | ok={ok}")

        ogg_out = await asyncio.to_thread(_synthesize_to_ogg, reply)
        await _send_voice(chat_id, ogg_out)

        if ok:
            await asyncio.to_thread(_persist, session_id, chat_id, transcript, reply, assessment)
            logger.info(f"📝 Sara turn persisted (session {session_id})")
        else:
            logger.info("Sara: fallback turn NOT persisted (avoids history poisoning)")
    except Exception as e:
        logger.error(f"Sara handle_voice failed for chat {chat_id}: {e}")
        try:
            await _send_text(chat_id, "Something went wrong on my side — try again in a moment.")
        except Exception:
            pass


async def process_update(update: dict):
    update_id = update.get("update_id")
    if update_id is not None and DB_URL:
        try:
            with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sara_inbound_updates (update_id) VALUES (%s) "
                    "ON CONFLICT (update_id) DO NOTHING",
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
        await _send_text(chat_id, "Send me a voice message and we'll talk 🎤")


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
