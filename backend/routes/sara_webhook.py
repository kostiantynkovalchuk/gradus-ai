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
import html
import json
import time
import asyncio
import logging
import subprocess
import tempfile
from datetime import datetime

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
ELEVEN_TTS_MODEL = os.getenv("ELEVENLABS_TTS_MODEL", "eleven_v3")
ELEVEN_STT_MODEL = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v1")

TELEGRAM_API = f"https://api.telegram.org/bot{SARA_BOT_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{SARA_BOT_TOKEN}"

_eleven = ElevenLabs()  # auto-reads ELEVENLABS_API_KEY

_anthropic = None
def _get_anthropic():
    global _anthropic
    if _anthropic is None:
        _anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _anthropic


from services.sara_prompts import (
    SARA_SYSTEM_PROMPT_BASE, SARA_SYSTEM_PROMPT_BASE_EN, SARA_LANGUAGE_MODE,
    _LEVEL_BLOCK_A, _LEVEL_BLOCK_B, _LEVEL_BLOCK_C, _LEVEL_BLOCK_DEFAULT,
    _LEVEL_BLOCKS, _LEVEL_BLOCK_A_EN, _LEVEL_BLOCK_B_EN, _LEVEL_BLOCK_C_EN,
    _LEVEL_BLOCK_DEFAULT_EN, _LEVEL_BLOCKS_EN,
    _build_system_prompt, safe_parse_json,
    _CEFR_TO_NUM, _NUM_TO_CEFR, EWA_ALPHA, BAND_HYSTERESIS, _snap_band,
)


# ---------- pilot gate ----------
from services.maya_english_pilot import is_english_pilot


# ---------- caps & usage config (read at import; all optional with safe defaults) ----------

_LESSON_TIME_CAP_S       = int(os.getenv("MAYA_LESSON_TIME_CAP_S",       "900"))
_LESSON_CREDIT_CAP       = int(os.getenv("MAYA_LESSON_CREDIT_CAP",       "2500"))
_WEEKLY_LESSON_CAP       = int(os.getenv("MAYA_WEEKLY_LESSON_CAP",       "3"))
_MONTHLY_CREDIT_SOFT_CAP = int(os.getenv("MAYA_MONTHLY_CREDIT_SOFT_CAP", "450000"))
_ACCOUNT_HARD_CAP        = int(os.getenv("MAYA_ACCOUNT_HARD_CAP",        "550000"))
_CREDITS_PER_TTS_CHAR    = float(os.getenv("MAYA_CREDITS_PER_TTS_CHAR",  "0.5"))

# ElevenLabs subscription usage cache — refreshed at most every _SUB_CACHE_TTL seconds
_sub_cache: dict = {"ts": 0.0, "count": 0}
_SUB_CACHE_TTL = 60.0

# Goodbye lines (TTS voice for all reasons except hard_breaker which is text-only)
_GOODBYE_VOICE = {
    "time_cap":     "That's all for today's lesson — great work! See you next time.",
    "credit_cap":   "That's all for today's lesson — great work! See you next time.",
    "weekly_cap":   "You've done all your practice sessions this week — see you next week!",
    "soft_breaker": "English practice is done for this month — see you next month!",
}
_GOODBYE_TEXT_ONLY = {
    "hard_breaker": "English practice is paused for now — please try again later.",
}


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
        model_id=ELEVEN_STT_MODEL,
        file=ogg_bytes,
        tag_audio_events=False,
    )
    return (result.text or "").strip()


def _synthesize_to_ogg(text: str) -> bytes:
    audio_gen = _eleven.text_to_speech.convert(
        ELEVEN_VOICE_ID,
        text=text,
        model_id=ELEVEN_TTS_MODEL,
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
            "SELECT id, (last_activity_at < now() - (%s * interval '1 minute')) AS is_idle, "
            "started_at "
            "FROM sara_sessions WHERE tg_user_id=%s AND status='active' "
            "ORDER BY id DESC LIMIT 1",
            (idle_min, tg_user_id),
        )
        row = cur.fetchone()

        if row and not row[1]:
            session_id = row[0]                       # active and fresh → continue
            started_at = row[2]
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
            started_at = datetime.utcnow()

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
                f"BEAT (open with this, warmly, then continue naturally): Welcome the learner back "
                f"and briefly reference last time before your normal reply. Last session summary: "
                f"\"{last_summary}\". Keep it to one short welcoming clause — do not recap in detail."
            )
            cur.execute(
                "UPDATE sara_state SET last_session_summary=NULL, updated_at=now() WHERE tg_user_id=%s",
                (tg_user_id,),
            )
        elif streak_days in _streak_milestones(cur):
            beat_instruction = (
                f"BEAT (work this into your reply, warmly): Congratulate the learner — this is day "
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
    return session_id, history, cefr_band, beat_instruction, opened_new, started_at


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


def _close_session(session_id: int) -> None:
    """Mark a session closed (cap hit or user end). Blocking."""
    if not DB_URL:
        return
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE sara_sessions SET status='closed', ended_at=now() "
                "WHERE id=%s AND status='active'",
                (session_id,),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"[MAYA CAPS] _close_session failed for session={session_id}: {e}")


def _log_usage(session_id, tg_user_id: int, event_type: str,
               stt_seconds=0, tts_chars=0, credits_est=0) -> None:
    """Insert a row into maya_english_usage. Blocking.
    Never raises — logs ERROR loudly on failure (silent under-counting defeats the breaker)."""
    if not DB_URL:
        return
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO maya_english_usage "
                "(session_id, tg_user_id, event_type, stt_seconds, tts_chars, credits_est) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (session_id, tg_user_id, event_type, stt_seconds, tts_chars, credits_est),
            )
            conn.commit()
    except Exception as e:
        logger.error(
            f"[MAYA USAGE] FAILED to log event={event_type} user={tg_user_id} "
            f"session={session_id}: {e}"
        )


def _query_caps(session_id: int, tg_user_id: int, is_new_session: bool) -> dict:
    """Single DB round-trip for per-session and (if new session) per-user cap values.
    Blocking. Returns safe zeroes on error so caps are still evaluated."""
    result = {"session_credits": 0.0, "monthly_credits": 0.0, "weekly_sessions": 0}
    if not DB_URL:
        return result
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(credits_est), 0) FROM maya_english_usage "
                "WHERE session_id=%s",
                (session_id,),
            )
            result["session_credits"] = float(cur.fetchone()[0] or 0)

            if is_new_session:
                cur.execute(
                    "SELECT COALESCE(SUM(credits_est), 0) FROM maya_english_usage "
                    "WHERE created_at >= date_trunc('month', now())",
                )
                result["monthly_credits"] = float(cur.fetchone()[0] or 0)

                # Count sessions with ≥1 persisted sara_turn, not raw session rows.
                # TG sessions never write active_seconds (always 0) and never reach
                # status='completed' — that machinery is web-only (sara_assessment_service
                # is never called from sara_webhook.py). Counting bare sessions would block
                # users whose only prior sessions were empty/abandoned/cap-blocked (0 turns).
                cur.execute(
                    "SELECT COUNT(DISTINCT s.id) "
                    "FROM sara_sessions s "
                    "JOIN sara_turns t ON t.session_id = s.id "
                    "WHERE s.tg_user_id=%s "
                    "AND s.started_at >= now() - interval '7 days'",
                    (tg_user_id,),
                )
                result["weekly_sessions"] = int(cur.fetchone()[0] or 0)
    except Exception as e:
        logger.error(f"[MAYA CAPS] _query_caps failed session={session_id}: {e}")
    return result


def _local_account_credits_this_month() -> float:
    """Sum of all maya_english_usage credits since start of calendar month.
    Blocking fallback when ElevenLabs subscription API is unavailable."""
    if not DB_URL:
        return 0.0
    try:
        with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(credits_est), 0) FROM maya_english_usage "
                "WHERE created_at >= date_trunc('month', now())",
            )
            return float(cur.fetchone()[0] or 0)
    except Exception as e:
        logger.error(f"[MAYA CAPS] _local_account_credits_this_month failed: {e}")
        return 0.0


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


async def _send_text(chat_id: int, text: str, parse_mode: str = None):
    async with httpx.AsyncClient(timeout=30) as hc:
        payload = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        await hc.post(f"{TELEGRAM_API}/sendMessage", data=payload)


def _format_reply_with_corrections(reply: str, errors: list) -> str:
    """Bold the corrected words in Sara's reply.

    Strategy: for each error, find words present in `correction` but absent
    from `original` (the actual fix). Bold those individual words wherever
    they appear in the reply. Never raises — any problem just falls back to
    the plain (HTML-escaped) reply text."""
    if not reply:
        return reply
    if not errors:
        return html.escape(reply)
    try:
        # Collect the changed words across all errors
        bold_words = set()
        for err in errors:
            if not isinstance(err, dict):
                continue
            orig = (err.get("original") or "").lower().split()
            corr = (err.get("correction") or "").lower().split()
            orig_set = set(orig)
            # Words in correction that aren't in original = the actual fixes
            for w in corr:
                if w not in orig_set and len(w) > 1:
                    bold_words.add(w)
        if not bold_words:
            return html.escape(reply)
        # Build the result: bold matching words (case-insensitive)
        escaped = html.escape(reply)
        for word in sorted(bold_words, key=len, reverse=True):
            pattern = re.compile(
                r'(?<![&\w])(' + re.escape(html.escape(word)) + r')(?!\w)',
                re.IGNORECASE
            )
            escaped = pattern.sub(r'<b>\1</b>', escaped)
        return escaped
    except Exception:
        return html.escape(reply)


async def _chat_action(chat_id: int, action: str):
    try:
        async with httpx.AsyncClient(timeout=15) as hc:
            await hc.post(f"{TELEGRAM_API}/sendChatAction", data={"chat_id": chat_id, "action": action})
    except Exception:
        pass


async def _fetch_account_credits_used() -> int:
    """Fetch character_count from ElevenLabs /v1/user/subscription. Cached 60 s.
    Returns -1 on any error; caller falls back to local DB sum."""
    now = time.monotonic()
    if now - _sub_cache["ts"] < _SUB_CACHE_TTL:
        return _sub_cache["count"]
    try:
        api_key = os.getenv("ELEVENLABS_API_KEY", "")
        async with httpx.AsyncClient(timeout=10.0) as hc:
            r = await hc.get(
                "https://api.elevenlabs.io/v1/user/subscription",
                headers={"xi-api-key": api_key},
            )
            r.raise_for_status()
            data = r.json()
            count = int(data.get("character_count", 0))
            _sub_cache["ts"] = now
            _sub_cache["count"] = count
            return count
    except Exception as e:
        logger.error(f"[MAYA CAPS] ElevenLabs subscription check failed: {e}")
        return -1


async def check_lesson_allowed(
    tg_user_id: int, session_id: int, session_started_at, is_new_session: bool
) -> str:
    """
    Returns 'ok' or a reason string. Called AFTER _prepare, BEFORE _transcribe so a
    blocked turn costs zero STT/TTS credits. Checks in spec order:
      1. hard_breaker  — account character_count vs MAYA_ACCOUNT_HARD_CAP (every turn)
      2. time_cap      — wall-clock elapsed vs MAYA_LESSON_TIME_CAP_S (every turn)
      3. credit_cap    — session credits vs MAYA_LESSON_CREDIT_CAP (every turn)
      4. soft_breaker  — monthly credits vs MAYA_MONTHLY_CREDIT_SOFT_CAP (new session only)
      5. weekly_cap    — user sessions in last 7 d vs MAYA_WEEKLY_LESSON_CAP (new session only)
    """
    # 1. Hard breaker — always check, even mid-lesson
    credits_used = await _fetch_account_credits_used()
    if credits_used == -1:
        # API unavailable — fall back to local monthly sum as conservative proxy
        credits_used = await asyncio.to_thread(_local_account_credits_this_month)
    if credits_used >= _ACCOUNT_HARD_CAP:
        return "hard_breaker"

    # 2. Per-lesson time cap
    try:
        if session_started_at.tzinfo is None:
            elapsed = (datetime.utcnow() - session_started_at).total_seconds()
        else:
            from datetime import timezone as _tz
            elapsed = (datetime.now(_tz.utc) - session_started_at).total_seconds()
        if elapsed >= _LESSON_TIME_CAP_S:
            return "time_cap"
    except Exception as e:
        logger.warning(f"[MAYA CAPS] time-cap check error: {e}")

    # 3, 4, 5 — single DB round-trip
    caps = await asyncio.to_thread(_query_caps, session_id, tg_user_id, is_new_session)

    # 3. Per-lesson credit cap
    if caps["session_credits"] >= _LESSON_CREDIT_CAP:
        return "credit_cap"

    # 4 & 5 — new session only (in-progress lessons are never blocked by these)
    if is_new_session:
        if caps["monthly_credits"] >= _MONTHLY_CREDIT_SOFT_CAP:
            return "soft_breaker"
        if caps["weekly_sessions"] >= _WEEKLY_LESSON_CAP:
            return "weekly_cap"

    return "ok"


async def _end_lesson_with_cap(chat_id: int, session_id: int, tg_user_id: int, reason: str) -> None:
    """Close session, log end_* event, send goodbye. Hard breaker = text only (never synthesize)."""
    await asyncio.to_thread(_close_session, session_id)

    event_type = f"end_{reason}"   # matches CHECK constraint values in maya_english_usage
    tts_chars = 0

    if reason in _GOODBYE_TEXT_ONLY:
        try:
            await _send_text(chat_id, _GOODBYE_TEXT_ONLY[reason])
        except Exception as e:
            logger.error(f"[MAYA CAPS] text goodbye failed reason={reason}: {e}")
    elif reason in _GOODBYE_VOICE:
        line = _GOODBYE_VOICE[reason]
        try:
            ogg = await asyncio.to_thread(_synthesize_to_ogg, line)
            tts_chars = len(line)
            await _send_voice(chat_id, ogg)
        except Exception:
            logger.error(f"[MAYA CAPS] TTS goodbye failed reason={reason}, sending text fallback")
            try:
                await _send_text(chat_id, line)
            except Exception:
                pass
    else:
        logger.warning(f"[MAYA CAPS] unknown cap reason={reason!r}, no goodbye sent")

    await asyncio.to_thread(
        _log_usage, session_id, tg_user_id, event_type,
        0, tts_chars, round(tts_chars * _CREDITS_PER_TTS_CHAR),
    )


async def handle_voice(chat_id: int, file_id: str, duration: int = 0):
    # sara_* tables (sara_sessions, sara_turns, sara_state) now store Maya English
    # employee data on this bot. Do NOT rename them — append-only discipline applies.
    try:
        await _chat_action(chat_id, "record_voice")
        ogg_in = await _download_voice(file_id)

        # _prepare runs BEFORE _transcribe: cap check fires before any ElevenLabs spend.
        session_id, history, cefr_band, beat_instruction, is_new_session, session_started_at = \
            await asyncio.to_thread(_prepare, chat_id)

        cap_reason = await check_lesson_allowed(
            chat_id, session_id, session_started_at, is_new_session
        )
        if cap_reason != "ok":
            logger.info(f"[MAYA CAPS] user={chat_id} session={session_id} blocked: {cap_reason}")
            await _end_lesson_with_cap(chat_id, session_id, chat_id, cap_reason)
            return

        transcript = await asyncio.to_thread(_transcribe, ogg_in)
        logger.info(f"🗣️ Sara heard: {transcript!r}")
        if not transcript:
            await _send_text(chat_id, "Sorry, I couldn't hear that — try again?")
            return

        reply, assessment, ok = await asyncio.to_thread(
            _think, transcript, history, cefr_band, beat_instruction
        )
        logger.info(f"💭 Sara reply: {reply!r} | level={cefr_band} | beat={bool(beat_instruction)} | ok={ok}")

        ogg_out = await asyncio.to_thread(_synthesize_to_ogg, reply)
        await _send_voice(chat_id, ogg_out)

        # --- parallel text with bolded corrections (best-effort; never blocks voice) ---
        try:
            errors = (assessment or {}).get("errors") or []
            display_text = _format_reply_with_corrections(reply, errors)
            if display_text:
                await _send_text(chat_id, display_text, parse_mode="HTML")
        except Exception:
            logger.warning("Sara text-alongside failed, continuing with voice", exc_info=True)

        if ok:
            await asyncio.to_thread(_persist, session_id, chat_id, transcript, reply, assessment)
            logger.info(f"📝 Sara turn persisted (session {session_id})")
        else:
            logger.info("Sara: fallback turn NOT persisted (avoids history poisoning)")

        # Usage meter — failure must log loudly but must NOT crash the lesson
        try:
            tts_chars = len(reply)
            credits = round(tts_chars * _CREDITS_PER_TTS_CHAR)
            await asyncio.to_thread(
                _log_usage, session_id, chat_id, "turn", duration, tts_chars, credits,
            )
        except Exception as e:
            logger.error(f"[MAYA USAGE] meter write failed user={chat_id} session={session_id}: {e}")

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

    # Pilot gate — deny-by-default. Covers the voice path, the text/command
    # path, AND the edited_message double-billing edge case — do not add a
    # separate fix for edited_message elsewhere.
    if not is_english_pilot(chat_id):
        await _send_text(chat_id, "English practice isn't enabled for your account yet.")
        return

    voice = msg.get("voice")
    if voice and voice.get("file_id"):
        await handle_voice(chat_id, voice["file_id"], voice.get("duration", 0))
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
