"""
ElevenLabs WebSocket clients for Sara real-time voice service.

Audio format choice: mp3_44100_128
  - Widely supported by Web Audio API's decodeAudioData()
  - Good compression for streaming (≈128kbps)
  - No gap between chunks when queued correctly

STT: Scribe v2 Realtime
  Endpoint : wss://api.elevenlabs.io/v1/speech-to-text/realtime
  Auth     : xi-api-key HEADER only (never in URL)
  Input    : JSON {"message_type":"input_audio_chunk","audio_base_64":"<b64>","sample_rate":16000}
  Commit   : VAD-based (commit_strategy=vad query param) — no manual EOS message
  Events   : session_started | partial_transcript | committed_transcript | scribeError
  Ref      : https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime

TTS: Flash v2.5 streaming
  Auth     : xi-api-key HEADER only (never in URL)
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

# STT: key in HEADER only — not in URL (403 if key appears in URL on v1/realtime)
STT_URL_TMPL = (
    EL_WSS_BASE
    + "/speech-to-text/realtime"
    + "?model_id={model}&audio_format=pcm_16000&commit_strategy=vad"
)

# TTS: key in HEADER only — xi_api_key removed from query string
TTS_URL_TMPL = (
    EL_WSS_BASE
    + "/text-to-speech/{voice_id}/stream-input"
    + "?model_id={model}&output_format=mp3_44100_128"
)


class ScribeRealtimeSTT:
    """
    Wraps ElevenLabs Scribe v2 Realtime WebSocket (STT).

    Protocol (doc-confirmed 2026-07-07):
      • Client sends: JSON {"message_type":"input_audio_chunk",
                            "audio_base_64":"<base64 PCM16>",
                            "sample_rate":16000}
      • VAD commits automatically (commit_strategy=vad) — no EOS message needed.
      • Server emits: session_started → partial_transcript → committed_transcript

    Usage pattern (one instance per session — EL keeps VAD context across turns):
        async with ScribeRealtimeSTT(model) as stt:
            async for event in stt.receive_events():
                if event["type"] == "partial":
                    ...
                elif event["type"] == "final":
                    transcript = event["text"]
                    break
            # feed audio concurrently via stt.send_audio(pcm16_bytes)
    """

    def __init__(self, model: str):
        self._model = model
        self._ws = None

    async def __aenter__(self):
        url = STT_URL_TMPL.format(model=self._model)
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
        """
        Wrap PCM16 bytes as a doc-confirmed input_audio_chunk JSON frame and send.

        Shape (doc-confirmed):
          {"message_type": "input_audio_chunk",
           "audio_base_64": "<base64>",
           "sample_rate": 16000}

        commit_strategy=vad (set at connect time) means VAD commits automatically;
        no per-chunk "commit" field or end-of-stream message is needed.
        """
        if self._ws and pcm16_bytes:
            try:
                await self._ws.send(json.dumps({
                    "message_type": "input_audio_chunk",
                    "audio_base_64": base64.b64encode(pcm16_bytes).decode("utf-8"),
                    "sample_rate": 16000,
                }))
            except (ConnectionClosedError, ConnectionClosedOK):
                pass

    async def receive_events(self) -> AsyncIterator[dict]:
        """
        Async iterator over transcript events from ElevenLabs Scribe v2 Realtime.

        Doc-confirmed server→client message_type values:
          session_started             → logged, not yielded
          partial_transcript          → yields {"type": "partial", "text": "..."}
          committed_transcript        → yields {"type": "final", "text": "..."}, loops
          committed_transcript_with_timestamps → treated same as committed_transcript
          scribeError                 → yields {"type": "error", "message": "..."}, returns

        The generator loops indefinitely across VAD commits so one Scribe socket
        serves the entire session lifetime.

        RAISES ConnectionClosedError / ConnectionClosedOK on socket death — never
        swallows them. The caller (_stt_recv → _stt_reader) handles reconnect logic.
        R9 compliance: silent deafness via except-and-return is forbidden.
        """
        if not self._ws:
            return
        # ConnectionClosedError / ConnectionClosedOK are NOT caught here.
        # They propagate to _stt_recv → _stt_reader which handles reconnect. R9.
        async for raw in self._ws:
            if isinstance(raw, bytes):
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("[Scribe] Non-JSON frame: %s", raw[:200])
                continue

            mt = msg.get("message_type", "")

            if mt == "session_started":
                logger.info(
                    "[Scribe] Session started: id=%s config=%s",
                    msg.get("session_id"), msg.get("config"),
                )

            elif mt == "partial_transcript":
                text = msg.get("text", "").strip()
                if text:
                    yield {"type": "partial", "text": text}

            elif mt in ("committed_transcript", "committed_transcript_with_timestamps"):
                text = msg.get("text", "").strip()
                yield {"type": "final", "text": text}  # caller filters empty/gated
                # No return — loop continues across multiple VAD commits. R10.

            else:
                # Defensive catch-all: any message_type outside the known-good set
                # is treated as an error regardless of exact casing or naming.
                err = msg.get("message") or msg.get("error") or msg.get("text") or str(msg)
                logger.error("[Scribe] Unknown/error message_type=%r raw=%s", mt, str(msg)[:400])
                yield {"type": "error", "message": err}
                return  # scribeError is terminal; EL will not recover


class FlashStreamingTTS:
    """
    Wraps ElevenLabs Flash v2.5 streaming TTS WebSocket.

    Open once per turn, send text sentence-chunks, receive binary MP3 chunks.
    Auth: xi-api-key HEADER only (not in URL).

    Usage:
        async with FlashStreamingTTS(voice_id, model) as tts:
            await tts.send_text("Hello there.")
            await tts.send_text("How are you?")
            await tts.close_stream()
            async for audio_bytes in tts.audio_chunks():
                # relay to client
    """

    def __init__(self, voice_id: str, model: str):
        self._voice_id = voice_id
        self._model = model
        self._ws = None

    async def __aenter__(self):
        url = TTS_URL_TMPL.format(voice_id=self._voice_id, model=self._model)
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

    async def close_stream(self):
        """Send EOS (end-of-stream) to ElevenLabs: empty text string closes the text input.
        Docs-confirmed: {"text": ""} (no flush key) is the canonical close signal.
        After EOS the server finishes synthesis, emits isFinal=true in the last audio
        frame, and closes the connection — allowing audio_chunks() to exit cleanly."""
        if self._ws:
            await self._ws.send(json.dumps({"text": ""}))

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
            await tts.close_stream()
            async for audio in tts.audio_chunks():
                await on_audio(audio)
    except Exception as e:
        logger.exception("[Flash TTS] Synthesis error: %s", e)
