"""
ElevenLabs WebSocket clients for Sara real-time voice service.

Audio format choice: mp3_44100_128
  - Widely supported by Web Audio API's decodeAudioData()
  - Good compression for streaming (≈128kbps)
  - No gap between chunks when queued correctly

STT: Scribe v2 Realtime — binary PCM16 input, JSON transcript output
TTS: Flash v2.5 streaming — JSON text input, base64-encoded MP3 output
     NOTE: eleven_v3 is NOT supported on the TTS WebSocket. Do not change
     the default model here even if ELEVENLABS_TTS_MODEL is set to eleven_v3
     in the environment (that var belongs to the sync REST path in sara_webhook.py).
"""
import os
import json
import base64
import asyncio
import logging
from typing import AsyncIterator, Callable, Awaitable

import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

logger = logging.getLogger(__name__)

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

EL_WSS_BASE = "wss://api.elevenlabs.io/v1"
STT_URL_TMPL = EL_WSS_BASE + "/speech-to-text/stream?xi_api_key={key}&model_id={model}"
TTS_URL_TMPL = (
    EL_WSS_BASE
    + "/text-to-speech/{voice_id}/stream-input"
    + "?model_id={model}&output_format=mp3_44100_128&xi_api_key={key}"
)


class ScribeRealtimeSTT:
    """
    Wraps ElevenLabs Scribe v2 Realtime WebSocket (STT).

    Usage pattern (one instance per turn):
        async with ScribeRealtimeSTT(model) as stt:
            async for event in stt.events():
                if event["type"] == "partial":
                    ...
                elif event["type"] == "final":
                    transcript = event["text"]
                    break
            # feed audio via stt.send_audio(pcm16_bytes)
    """

    def __init__(self, model: str):
        self._model = model
        self._ws = None

    async def __aenter__(self):
        url = STT_URL_TMPL.format(key=ELEVENLABS_API_KEY, model=self._model)
        self._ws = await websockets.connect(
            url,
            additional_headers={"xi-api-key": ELEVENLABS_API_KEY},
            open_timeout=10,
            ping_interval=20,
        )
        logger.debug("[Scribe] STT WebSocket opened, model=%s", self._model)
        return self

    async def __aexit__(self, *_):
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def send_audio(self, pcm16_bytes: bytes):
        """Forward a binary PCM16 chunk to ElevenLabs."""
        if self._ws:
            try:
                await self._ws.send(pcm16_bytes)
            except (ConnectionClosedError, ConnectionClosedOK):
                pass

    async def signal_end_of_stream(self):
        """Tell ElevenLabs no more audio is coming (flush remaining buffer)."""
        if self._ws:
            try:
                await self._ws.send(json.dumps({"type": "end_of_stream"}))
            except (ConnectionClosedError, ConnectionClosedOK):
                pass

    async def receive_events(self) -> AsyncIterator[dict]:
        """
        Async iterator over transcript events from ElevenLabs.

        Yields dicts:
            {"type": "partial", "text": "..."}   — uncommitted interim
            {"type": "final",   "text": "..."}   — VAD-committed utterance
        """
        if not self._ws:
            return
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("[Scribe] Non-JSON message: %s", raw[:200])
                    continue

                event_type = msg.get("type", "") or msg.get("speech_event_type", "")

                # ElevenLabs Scribe v2 Realtime event shapes (July 2026):
                #   {"type": "interim_transcript", "text": "..."}
                #   {"type": "final_transcript",   "text": "..."}
                # Also emitted as:
                #   {"speech_event_type": "utterance_end", "text": "..."}
                # We normalise to "partial" / "final" for the pipeline.
                if "final" in event_type or event_type == "utterance_end":
                    text = msg.get("text", "").strip()
                    if text:
                        yield {"type": "final", "text": text}
                    return
                elif "interim" in event_type or "partial" in event_type:
                    text = msg.get("text", "").strip()
                    if text:
                        yield {"type": "partial", "text": text}
                else:
                    logger.debug("[Scribe] Unknown event: %s", event_type)
        except (ConnectionClosedError, ConnectionClosedOK):
            logger.info("[Scribe] STT WebSocket closed by server")


class FlashStreamingTTS:
    """
    Wraps ElevenLabs Flash v2.5 streaming TTS WebSocket.

    Open once per turn, send text sentence-chunks, receive binary MP3 chunks.

    Usage:
        async with FlashStreamingTTS(voice_id, model) as tts:
            await tts.send_text("Hello there.")
            await tts.send_text("How are you?")
            await tts.flush()
            async for audio_bytes in tts.audio_chunks():
                # relay to client
    """

    def __init__(self, voice_id: str, model: str):
        self._voice_id = voice_id
        self._model = model
        self._ws = None

    async def __aenter__(self):
        url = TTS_URL_TMPL.format(
            voice_id=self._voice_id, model=self._model, key=ELEVENLABS_API_KEY
        )
        self._ws = await websockets.connect(
            url,
            additional_headers={"xi-api-key": ELEVENLABS_API_KEY},
            open_timeout=10,
            ping_interval=20,
        )
        # BOS — required initialisation message; sends a space to warm up the voice
        await self._ws.send(
            json.dumps(
                {
                    "text": " ",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                }
            )
        )
        logger.debug("[Flash TTS] WebSocket opened, voice=%s model=%s", self._voice_id, self._model)
        return self

    async def __aexit__(self, *_):
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def send_text(self, text: str):
        """Queue a text chunk for synthesis."""
        if self._ws and text:
            await self._ws.send(json.dumps({"text": text}))

    async def flush(self):
        """Signal end of text input; ElevenLabs will synthesize and return all remaining audio."""
        if self._ws:
            await self._ws.send(json.dumps({"text": "", "flush": True}))

    async def audio_chunks(self) -> AsyncIterator[bytes]:
        """
        Async iterator yielding raw MP3 bytes as they arrive.
        Terminates when ElevenLabs closes the connection or sends isFinal=true.
        """
        if not self._ws:
            return
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    # Some ElevenLabs TTS WS versions send raw binary directly
                    if raw:
                        yield raw
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                audio_b64 = msg.get("audio", "")
                if audio_b64:
                    try:
                        yield base64.b64decode(audio_b64)
                    except Exception:
                        logger.warning("[Flash TTS] Base64 decode error")

                if msg.get("isFinal", False):
                    return
        except (ConnectionClosedError, ConnectionClosedOK):
            logger.info("[Flash TTS] TTS WebSocket closed by server")


async def tts_synthesize_chunked(
    voice_id: str,
    model: str,
    text_queue: asyncio.Queue,
    on_audio: Callable[[bytes], Awaitable[None]],
):
    """
    Consume text chunks from text_queue, stream them to Flash TTS,
    relay each audio chunk via on_audio callback.

    Sentinel: None in text_queue signals end of turn.
    Fail-open: any WS error is logged; on_audio is not called for failed chunks.
    """
    try:
        async with FlashStreamingTTS(voice_id, model) as tts:
            while True:
                chunk = await text_queue.get()
                if chunk is None:
                    break
                await tts.send_text(chunk)
            await tts.flush()
            async for audio in tts.audio_chunks():
                await on_audio(audio)
    except Exception as e:
        logger.exception("[Flash TTS] Synthesis error: %s", e)
