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

from services.sara_prompts import _build_system_prompt, safe_parse_json

from sara_realtime.eleven_ws import ScribeRealtimeSTT, tts_synthesize_chunked

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_HISTORY_TURNS = 20
PHASE1_CEFR_BAND = "A2"

# Sentence-chunking thresholds
SENTENCE_END_CHARS = frozenset(".!?…")
CHUNK_CHAR_LIMIT = 60


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
        audio_queue: asyncio.Queue,
        stt_client: ScribeRealtimeSTT,
    ) -> Optional[str]:
        """
        Run one complete turn: STT → Claude → TTS.

        Returns the Sara reply text (for history update), or None on failure.
        Never raises — all errors surface as {"type": "error"} WS events.

        websocket: FastAPI WebSocket (already accepted)
        audio_queue: asyncio.Queue fed by the main receive loop with PCM16 bytes
        stt_client: open ScribeRealtimeSTT (shared across turns for session)
        """
        t0 = time.monotonic()
        ms = lambda: int((time.monotonic() - t0) * 1000)

        # ── STT leg ──────────────────────────────────────────────────────────
        transcript = None
        try:
            # Drain audio_queue → STT WebSocket until VAD commit
            stt_task = asyncio.create_task(
                self._drain_audio_to_stt(audio_queue, stt_client),
                name="stt_drain",
            )
            stt_task.add_done_callback(_make_done_callback("stt_drain"))

            async for event in stt_client.receive_events():
                if event["type"] == "partial":
                    await websocket.send_json({
                        "type": "partial_transcript",
                        "text": event["text"],
                    })
                elif event["type"] == "final":
                    transcript = event["text"]
                    break

            stt_task.cancel()
            try:
                await stt_task
            except asyncio.CancelledError:
                pass

        except Exception as e:
            logger.exception("[Pipeline] STT leg error: %s", e)
            await self._send_error(websocket, f"STT error: {e}")
            return None

        if not transcript:
            logger.warning("[Pipeline] STT committed empty transcript — skipping turn")
            return None

        t_stt_commit = ms()
        await websocket.send_json({"type": "user_transcript", "text": transcript})
        logger.info("[Pipeline] VAD commit at +%dms: %r", t_stt_commit, transcript[:80])

        # ── Brain + TTS overlap ───────────────────────────────────────────────
        t_claude_first_token: Optional[int] = None
        t_first_audio: Optional[int] = None
        full_reply_text = ""
        full_reply_json = {}

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
            system_prompt = _build_system_prompt(PHASE1_CEFR_BAND)
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

            # Parse the JSON reply from Claude's raw response
            full_reply_json = safe_parse_json(raw_response)
            full_reply_text = full_reply_json.get("reply", raw_response)

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
            logger.error("[Pipeline] TTS task timed out")
            tts_task.cancel()
        except Exception as e:
            logger.exception("[Pipeline] TTS task error: %s", e)

        t_turn_end = ms()

        # ── Metrics ──────────────────────────────────────────────────────────
        metrics = {
            "t_stt_commit_ms": t_stt_commit,
            "t_claude_first_token_ms": t_claude_first_token,
            "t_first_audio_to_client_ms": t_first_audio,
            "t_turn_end_ms": t_turn_end,
        }
        logger.info(
            "SARA_RT_TURN t_stt_commit=%d t_claude_first_token=%s "
            "t_first_audio_to_client=%s t_turn_end=%d",
            t_stt_commit,
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

    async def _drain_audio_to_stt(self, audio_queue: asyncio.Queue, stt: ScribeRealtimeSTT):
        """Continuously drain audio chunks from queue and forward to STT WS."""
        while True:
            chunk = await audio_queue.get()
            if chunk is None:
                break
            await stt.send_audio(chunk)

    @staticmethod
    async def _send_error(websocket, message: str):
        try:
            await websocket.send_json({"type": "error", "message": message})
        except Exception:
            pass
