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

from anthropic import AsyncAnthropic

from services.sara_prompts import _LEVEL_BLOCKS, _LEVEL_BLOCK_DEFAULT

from sara_realtime.eleven_ws import tts_synthesize_chunked

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_HISTORY_TURNS = 20
PHASE1_CEFR_BAND = "A2"

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

REPLY LENGTH:
Keep every reply short: one to three spoken sentences. Long replies are tiring
to listen to. When in doubt, say less and ask a question.

LANGUAGE RULE:
Always speak English. The learner is a Russian speaker. You may give the
Russian translation of a difficult English word in parentheses to help them
understand — for example: to practise (тренироваться). Follow the learner
level instructions at the end of this prompt. If the learner writes to you in
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

EXAMPLE — learner writes in Russian, you redirect warmly:
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
    ) -> Optional[str]:
        """
        Run one turn: Claude streaming → TTS.

        The STT leg (Scribe socket, audio forwarding, VAD commit detection) is
        owned by _stt_reader / _stt_recv in app.py. This method receives a
        committed transcript string and handles only the Brain + TTS pipeline.

        t0 is set at function entry, which is the moment the committed transcript
        was pulled from transcript_queue — i.e. the VAD commit baseline. All
        SARA_RT_TURN metrics are deltas from this point (t_stt_commit_ms = 0).

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
