"""
Per-turn orchestration for Sara real-time voice service.

Turn flow:
  STT leg  : stream PCM16 audio to ElevenLabs Scribe, collect VAD-committed text
  Brain leg : AsyncAnthropic streaming (claude-sonnet-4-6), sentence-chunk output
  TTS leg   : stream chunks to ElevenLabs Flash v2.5 as they arrive (overlap)
  Metrics   : log one SARA_RT_TURN line + embed in turn_complete payload

Phase 1 constraints (per spec):
  - No DB reads or writes.
  - cefr_band hardcoded "A2"; calibration wiring comes in Phase 2.
  - History: in-memory list, last 20 turns.
  - Sync Anthropic client forbidden here — only AsyncAnthropic.
"""
import asyncio
import logging
import os
import time
from typing import Optional

import httpx
from anthropic import AsyncAnthropic

from services.sara_prompts import _LEVEL_BLOCKS, _LEVEL_BLOCK_DEFAULT

from sara_realtime.eleven_ws import tts_synthesize_chunked

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_HISTORY_TURNS = 20
PHASE1_CEFR_BAND = "A2"

# ── Turn forwarding (Architecture C — audit C7/C8) ────────────────────────────
# First-ever outbound HTTP call from sara_realtime/. This is a POST to the
# MAIN backend, never a DB write and never a migration call — §11 stays
# intact. Graceful degradation: if either env var is unset, forwarding is
# disabled entirely and sara-english keeps working standalone.
MAIN_BACKEND_URL = os.getenv("MAIN_BACKEND_URL", "").rstrip("/")
SARA_INTERNAL_TOKEN = os.getenv("SARA_INTERNAL_TOKEN", "")
_FORWARD_ENABLED = bool(MAIN_BACKEND_URL and SARA_INTERNAL_TOKEN)

if not _FORWARD_ENABLED:
    logger.warning(
        "[Pipeline] Turn forwarding disabled — MAIN_BACKEND_URL and/or "
        "SARA_INTERNAL_TOKEN not set. sara-english runs fully standalone."
    )

# Lazy module-level httpx.AsyncClient — created once, reused across turns
# and sessions. Never instantiated if forwarding is disabled.
_forward_client: Optional[httpx.AsyncClient] = None


def _get_forward_client() -> httpx.AsyncClient:
    global _forward_client
    if _forward_client is None:
        _forward_client = httpx.AsyncClient(timeout=15.0)
    return _forward_client


async def _forward_turn(
    websocket,
    web_session_id: str,
    turn_index: int,
    user_transcript: str,
    sara_reply: str,
    cefr_band: str,
    session_elapsed_s: Optional[float],
):
    """
    Fire-and-forget POST to the main backend. Runs inside its own
    asyncio.create_task (see run_turn) — never awaited on the voice path.
    Failures are logged and NEVER propagate; the voice path is provably
    unaffected by this call's success or failure.

    On a successful response, relays any assessment corrections and the
    lesson-completion flag back to the browser over the same WS — still
    entirely inside this fire-and-forget task, so a slow/failed WS send here
    can never delay or break the voice path (R11).
    """
    try:
        client = _get_forward_client()
        resp = await client.post(
            f"{MAIN_BACKEND_URL}/internal/sara/turn",
            headers={"Authorization": f"Bearer {SARA_INTERNAL_TOKEN}"},
            json={
                "web_session_id": web_session_id,
                "turn_index": turn_index,
                "user_transcript": user_transcript,
                "sara_reply": sara_reply,
                "cefr_band": cefr_band,
                "session_elapsed_s": session_elapsed_s,
            },
        )
        if resp.status_code // 100 != 2:
            logger.warning(
                "[Pipeline] Turn forward non-2xx: status=%d body=%r",
                resp.status_code, resp.text[:300],
            )
            return

        try:
            data = resp.json()
        except Exception:
            logger.warning("[Pipeline] Turn forward: response body was not JSON")
            return

        assessment = data.get("assessment")
        errors = (assessment.get("errors") or []) if isinstance(assessment, dict) else []
        if errors:
            try:
                await websocket.send_json({
                    "type": "corrections",
                    "turn_index": turn_index,
                    "errors": [
                        {
                            "type": e.get("type"),
                            "original": e.get("original"),
                            "correction": e.get("correction"),
                            "explanation_ru": e.get("explanation_ru"),
                        }
                        for e in errors if isinstance(e, dict)
                    ],
                })
            except Exception as ws_e:
                logger.warning("[Pipeline] Failed to relay corrections over WS: %s", ws_e)

        if data.get("lesson_completed"):
            try:
                await websocket.send_json({"type": "lesson_completed"})
            except Exception as ws_e:
                logger.warning("[Pipeline] Failed to relay lesson_completed over WS: %s", ws_e)

    except httpx.TimeoutException as e:
        logger.warning("[Pipeline] Turn forward timed out: %s", e)
    except Exception as e:
        logger.warning("[Pipeline] Turn forward failed: %s", e)


async def end_session(web_session_id: str, session_elapsed_s: float):
    """
    Fire-and-forget POST to /internal/sara/session/end, called once from
    app.py's ws_session teardown (finally block). Same graceful-degradation
    contract as _forward_turn: no-ops entirely if forwarding is disabled,
    never raises.
    """
    if not _FORWARD_ENABLED:
        return
    try:
        client = _get_forward_client()
        resp = await client.post(
            f"{MAIN_BACKEND_URL}/internal/sara/session/end",
            headers={"Authorization": f"Bearer {SARA_INTERNAL_TOKEN}"},
            json={"web_session_id": web_session_id, "session_elapsed_s": session_elapsed_s},
        )
        if resp.status_code // 100 != 2:
            logger.warning(
                "[Pipeline] Session end forward non-2xx: status=%d body=%r",
                resp.status_code, resp.text[:300],
            )
    except httpx.TimeoutException as e:
        logger.warning("[Pipeline] Session end forward timed out: %s", e)
    except Exception as e:
        logger.warning("[Pipeline] Session end forward failed: %s", e)


# Sentence-chunking thresholds
SENTENCE_END_CHARS = frozenset(".!?…")
CHUNK_CHAR_LIMIT = 60

# ── Realtime system prompt ────────────────────────────────────────────────────
# Entirely separate from services/sara_prompts.py (which uses JSON few-shot
# examples for the Telegram bot). This prompt contains ZERO JSON and ZERO braces
# — any JSON example, even contradicted by a suffix, can be imitated by the model.
# Pedagogy preserved: warm tutor, recast errors, Russian glosses at low levels,
# always end with a question, short sentences for beginners.
# Regression check: grep -c '{' on the composed prompt must be 0.
SARA_REALTIME_PROMPT_BASE = """\
WHO YOU ARE:
You are Sara, a warm, friendly personal English tutor having a live spoken
conversation with one adult learner. You speak naturally, like a trusted friend
who is also a skilled English teacher.

HOW YOUR WORDS ARE USED:
Everything you say is read aloud word-for-word by a text-to-speech voice.
Write only what Sara actually says out loud. No JSON, no code, no markdown,
no asterisks, no bullet points, no emoji, no formatting symbols of any kind.
No labels or headings. Everything outside a spoken sentence is wrong here.
Write all numbers, times, dates, and prices as words (say 'twenty-six degrees',
'ten o'clock' — never '26' or '10:00') — your words are spoken aloud and
digits are read unnaturally.

REPLY LENGTH:
Keep every reply short: one to three spoken sentences. Long replies are tiring
to listen to. When in doubt, say less and ask a question.

LANGUAGE RULE:
Always speak English. The learner is a Russian speaker. You may give the
Russian translation of a difficult English word in parentheses to help them
understand — for example: to practise (тренироваться). Follow the learner
level instructions at the end of this prompt. If the learner speaks to you in
Russian, answer briefly in English and gently guide them back to practising
English. Never hold the full conversation in Russian.

TEACHING METHOD:
When the learner makes an English mistake, gently RECAST it: naturally use the
correct form in your own reply, without pointing it out or explaining. First
acknowledge what they said, then keep the conversation going warmly with a
follow-up question. Do not lecture or list errors out loud.

Always end your reply with a short follow-up question to keep the conversation
moving.

EXAMPLE — grammar error, recast naturally:
Learner: Yesterday I go to the market and buy many things.
Sara: Oh, you went to the market! What did you buy? I love hearing about
shopping trips.

EXAMPLE — learner speaks in Russian, you redirect warmly:
Learner: A ty govorysh po-russki?
Sara: I understand a little Russian, but let us keep practising English
together — you are doing so well! Tell me, what did you do this weekend?

EXAMPLE — vocabulary error, recast and continue:
Learner: I am very boring today. Nothing interesting.
Sara: Oh, you are bored (скучаешь)! I know that feeling. What do you usually
do when you have free time?\
"""


def _make_done_callback(label: str):
    """Return an asyncio Task done-callback that logs any exception."""
    def _cb(task: asyncio.Task):
        exc = task.exception() if not task.cancelled() else None
        if exc:
            logger.exception("[%s] background task raised: %s", label, exc)
    return _cb


def _sentence_chunks(token_buffer: str) -> tuple[list[str], str]:
    """
    Extract all flushable sentence chunks from buffer.
    Returns (chunks_to_send, remaining_buffer).

    Flushes on sentence-ending punctuation followed by a space (or end of buffer),
    or at a word boundary when buffer exceeds CHUNK_CHAR_LIMIT chars.
    """
    chunks = []
    buf = token_buffer

    while True:
        flushed = False
        # Sentence-end punctuation scan
        for i, ch in enumerate(buf):
            if ch in SENTENCE_END_CHARS:
                after = i + 1
                if after >= len(buf) or buf[after] in " \n":
                    chunk = buf[:after + 1].strip()
                    if chunk:
                        chunks.append(chunk)
                    buf = buf[after + 1:].lstrip()
                    flushed = True
                    break
        if flushed:
            continue

        # Overflow flush at word boundary
        if len(buf) >= CHUNK_CHAR_LIMIT:
            last_space = buf.rfind(" ", 0, CHUNK_CHAR_LIMIT + 10)
            if last_space > 0:
                # Guard: never cut inside or immediately before a parenthetical
                # gloss — that severs the Cyrillic gloss from the English word
                # it annotates. Two failure modes:
                #  A) last_space is immediately before "("   → "word | (gloss)"
                #  B) last_space is inside "(...)"           → gloss split mid-word
                # rfind("(", 0, last_space+2) catches both: it finds the
                # rightmost "(" at or before last_space+1 (case A) or earlier
                # (case B). Then if that paren is unclosed, we back up past the
                # glossed word so "word (gloss)" travels in the same TTS chunk.
                open_paren = buf.rfind("(", 0, last_space + 2)
                if open_paren > 0:
                    close_paren = buf.find(")", open_paren)
                    if close_paren < 0 or close_paren >= last_space:
                        # Cut touches an unclosed paren. Back up to before the
                        # glossed word (one extra space before the "(" itself).
                        space_before_paren = buf.rfind(" ", 0, open_paren)
                        if space_before_paren > 0:
                            safe_cut = buf.rfind(" ", 0, space_before_paren)
                            last_space = safe_cut if safe_cut > 0 else space_before_paren
                        else:
                            # No space before the paren — flush whole buffer as
                            # one chunk rather than severing the gloss.
                            chunk = buf.strip()
                            if chunk:
                                chunks.append(chunk)
                            buf = ""
                            continue
                chunk = buf[:last_space].strip()
                if chunk:
                    chunks.append(chunk)
                buf = buf[last_space + 1:]
                continue

        break

    return chunks, buf


class SessionPipeline:
    """
    Manages per-WebSocket-session state and runs each turn.

    Instantiated once per connected client.
    """

    def __init__(self, voice_id: str, stt_model: str, tts_model: str):
        self._voice_id = voice_id
        self._stt_model = stt_model
        self._tts_model = tts_model
        self._history: list[dict] = []
        self._anthropic = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def _build_messages(self, transcript: str) -> list[dict]:
        """Assemble Claude messages list from history + new user turn."""
        msgs = list(self._history[-MAX_HISTORY_TURNS * 2:])
        msgs.append({"role": "user", "content": transcript})
        return msgs

    async def run_turn(
        self,
        websocket,
        transcript: str,
        web_session_id: Optional[str] = None,
        turn_index: Optional[int] = None,
        session_elapsed_s: Optional[float] = None,
    ) -> Optional[str]:
        """
        Run one turn: Claude streaming → TTS.

        The STT leg (Scribe socket, audio forwarding, VAD commit detection) is
        owned by _stt_reader / _stt_recv in app.py. This method receives a
        committed transcript string and handles only the Brain + TTS pipeline.

        t0 is set at function entry, which is the moment the committed transcript
        was pulled from transcript_queue — i.e. the VAD commit baseline. All
        SARA_RT_TURN metrics are deltas from this point (t_stt_commit_ms = 0).

        web_session_id / turn_index (assigned per-session/per-turn in app.py)
        are used only to fire the fire-and-forget forward POST to the main
        backend after the turn completes — see the forward task below. Never
        awaited on the voice path (audit C7, R11).

        Returns the Sara reply text (for history), or None on brain/TTS error.
        Never raises — all errors surface as {"type": "error"} WS events.
        """
        t0 = time.monotonic()
        ms = lambda: int((time.monotonic() - t0) * 1000)

        await websocket.send_json({"type": "user_transcript", "text": transcript})
        logger.info("[Pipeline] Turn start — transcript: %r", transcript[:80])

        # ── Brain + TTS overlap ───────────────────────────────────────────────
        t_claude_first_token: Optional[int] = None
        t_first_audio: Optional[int] = None
        full_reply_text = ""

        # Queue: sentence chunks flow from Claude streamer → TTS synthesizer
        tts_text_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        async def _relay_audio(audio_bytes: bytes):
            nonlocal t_first_audio
            if t_first_audio is None:
                t_first_audio = ms()
            # Relay binary audio chunk to browser
            await websocket.send_bytes(audio_bytes)

        # Start TTS consumer task
        tts_task = asyncio.create_task(
            tts_synthesize_chunked(
                self._voice_id, self._tts_model, tts_text_queue, _relay_audio
            ),
            name="tts_synthesize",
        )
        tts_task.add_done_callback(_make_done_callback("tts_synthesize"))

        try:
            system_prompt = SARA_REALTIME_PROMPT_BASE + "\n\n" + _LEVEL_BLOCKS.get(PHASE1_CEFR_BAND, _LEVEL_BLOCK_DEFAULT)
            messages = self._build_messages(transcript)

            token_buffer = ""
            raw_response = ""

            async with self._anthropic.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=512,
                system=system_prompt,
                messages=messages,
            ) as stream:
                async for token in stream.text_stream:
                    if t_claude_first_token is None:
                        t_claude_first_token = ms()

                    raw_response += token
                    token_buffer += token

                    # Send delta to client (live preview)
                    await websocket.send_json({"type": "assistant_delta", "text": token})

                    # Sentence-chunk flush to TTS
                    chunks, token_buffer = _sentence_chunks(token_buffer)
                    for chunk in chunks:
                        await tts_text_queue.put(chunk)

            # Flush any remaining buffer
            if token_buffer.strip():
                await tts_text_queue.put(token_buffer.strip())

            # Signal TTS end-of-turn
            await tts_text_queue.put(None)

            # Realtime mode: raw_response IS the spoken reply — no JSON parsing.
            full_reply_text = raw_response

        except Exception as e:
            logger.exception("[Pipeline] Brain/TTS overlap error: %s", e)
            await tts_text_queue.put(None)  # unblock TTS consumer
            await self._send_error(websocket, f"Claude error: {e}")
            try:
                await asyncio.wait_for(tts_task, timeout=2.0)
            except Exception:
                pass
            return None

        # Wait for TTS to finish sending all audio
        try:
            await asyncio.wait_for(tts_task, timeout=30.0)
        except asyncio.TimeoutError:
            logger.error(
                "[Pipeline] TTS 30s safety timeout fired — close_stream() EOS may not have triggered "
                "isFinal from ElevenLabs; check TTS WebSocket behavior"
            )
            tts_task.cancel()
        except Exception as e:
            logger.exception("[Pipeline] TTS task error: %s", e)

        t_turn_end = ms()

        # ── Metrics ──────────────────────────────────────────────────────────
        # All values are ms elapsed since STT commit (t0 was reset at that moment).
        # t_stt_commit_ms is always 0 — it IS the baseline.
        metrics = {
            "t_stt_commit_ms": 0,
            "t_claude_first_token_ms": t_claude_first_token,
            "t_first_audio_to_client_ms": t_first_audio,
            "t_turn_end_ms": t_turn_end,
        }
        logger.info(
            "SARA_RT_TURN t_stt_commit=0 t_claude_first_token=%s "
            "t_first_audio_to_client=%s t_turn_end=%d",
            t_claude_first_token if t_claude_first_token is not None else "N/A",
            t_first_audio if t_first_audio is not None else "N/A",
            t_turn_end,
        )

        await websocket.send_json({"type": "turn_complete", "metrics": metrics})

        # ── Fire-and-forget forward to main backend (Architecture C) ──────────
        # Fired AFTER turn_complete has been sent to the browser — the voice
        # path has already finished from the user's perspective. This task is
        # never awaited here; its own errors are caught inside _forward_turn
        # and never propagate (audit C7/C8, R11).
        if _FORWARD_ENABLED and web_session_id is not None and turn_index is not None:
            forward_task = asyncio.create_task(
                _forward_turn(
                    websocket, web_session_id, turn_index, transcript,
                    full_reply_text or raw_response, PHASE1_CEFR_BAND,
                    session_elapsed_s,
                ),
                name="forward_turn",
            )
            forward_task.add_done_callback(_make_done_callback("forward_turn"))

        # Update history (keep last MAX_HISTORY_TURNS pairs)
        self._history.append({"role": "user", "content": transcript})
        self._history.append({"role": "assistant", "content": full_reply_text or raw_response})
        if len(self._history) > MAX_HISTORY_TURNS * 2:
            self._history = self._history[-(MAX_HISTORY_TURNS * 2):]

        return full_reply_text

    @staticmethod
    async def _send_error(websocket, message: str):
        try:
            await websocket.send_json({"type": "error", "message": message})
        except Exception:
            pass
