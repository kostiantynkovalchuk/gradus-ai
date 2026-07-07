"""
Sara Real-Time Voice Service — FastAPI app.

Serves:
  GET  /           → test page (auth: ?token=)
  GET  /health     → liveness probe
  WS   /ws/session → real-time voice session (auth: ?token=)

Auth: single env var SARA_RT_ACCESS_TOKEN (pilot gate, not a full auth system).
Page: 403 on bad token. WebSocket: close code 4403 on bad token.

Start command (from backend/ as CWD, matching monorepo import root):
  uvicorn sara_realtime.app:app --host 0.0.0.0 --port $PORT

Does NOT call run_migrations() — migrations are owned by the main service.
Does NOT register any Telegram webhook.
Does NOT import backend/main.py or any route module.
"""
import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from sara_realtime.pipeline import SessionPipeline
from sara_realtime.eleven_ws import ScribeRealtimeSTT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ACCESS_TOKEN = os.getenv("SARA_RT_ACCESS_TOKEN", "")
VOICE_ID = os.getenv("SARA_RT_VOICE_ID") or os.getenv("ELEVENLABS_VOICE_ID", "")
STT_MODEL = os.getenv("SARA_RT_STT_MODEL", "scribe_v2_realtime")
TTS_MODEL = os.getenv("SARA_RT_TTS_MODEL", "eleven_flash_v2_5")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Sara Real-Time Voice", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _check_token(token: str) -> bool:
    """Reject if ACCESS_TOKEN is set and the provided token doesn't match."""
    if not ACCESS_TOKEN:
        return True
    return token == ACCESS_TOKEN


@app.get("/")
async def index(token: str = ""):
    if not _check_token(token):
        return HTMLResponse("<h1>403 Forbidden</h1>", status_code=403)
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "service": "sara-realtime"})


@app.websocket("/ws/session")
async def ws_session(websocket: WebSocket, token: str = ""):
    if not _check_token(token):
        await websocket.close(code=4403)
        return

    await websocket.accept()
    logger.info("[WS] New session accepted")

    pipeline = SessionPipeline(
        voice_id=VOICE_ID,
        stt_model=STT_MODEL,
        tts_model=TTS_MODEL,
    )

    # audio_queue: binary PCM16 frames from the browser → STT leg
    audio_queue: asyncio.Queue = asyncio.Queue(maxsize=500)

    # One persistent STT connection per session (EL keeps context across turns)
    stt_client = None
    session_started = False

    try:
        async with ScribeRealtimeSTT(STT_MODEL) as stt:
            stt_client = stt

            while True:
                try:
                    message = await websocket.receive()
                except WebSocketDisconnect:
                    logger.info("[WS] Client disconnected")
                    break

                # Binary frame → PCM16 audio → audio_queue for STT
                if "bytes" in message and message["bytes"]:
                    if session_started:
                        try:
                            audio_queue.put_nowait(message["bytes"])
                        except asyncio.QueueFull:
                            logger.warning("[WS] Audio queue full — dropping frame")
                    continue

                # JSON control message
                if "text" not in message or not message["text"]:
                    continue

                import json as _json
                try:
                    cmd = _json.loads(message["text"])
                except _json.JSONDecodeError:
                    logger.warning("[WS] Bad JSON from client: %s", message["text"][:100])
                    continue

                msg_type = cmd.get("type", "")

                if msg_type == "start":
                    session_started = True
                    logger.info("[WS] Session started, sample_rate=%s", cmd.get("sample_rate"))
                    # Kick off the first turn — pipeline blocks until VAD commit + response done
                    asyncio.create_task(
                        _run_turn_loop(websocket, pipeline, audio_queue, stt_client),
                        name="turn_loop",
                    )

                elif msg_type == "end_session":
                    logger.info("[WS] Client requested end_session")
                    break

                else:
                    logger.debug("[WS] Unknown command type: %s", msg_type)

    except WebSocketDisconnect:
        logger.info("[WS] WebSocket disconnected during session")
    except Exception as e:
        logger.exception("[WS] Unexpected session error: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        # Unblock any waiting drain task
        try:
            audio_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        logger.info("[WS] Session closed")


async def _run_turn_loop(websocket, pipeline: SessionPipeline, audio_queue: asyncio.Queue, stt_client):
    """
    Runs the turn loop: each VAD commit triggers one full pipeline turn.
    After a turn completes, loops back to wait for the next VAD commit.
    Errors within a turn are surfaced as {"type": "error"} events; the loop continues.
    This task runs for the lifetime of the session.
    """
    while True:
        try:
            result = await pipeline.run_turn(websocket, audio_queue, stt_client)
            if result is None:
                logger.warning("[TurnLoop] Turn returned None — continuing to next turn")
        except WebSocketDisconnect:
            logger.info("[TurnLoop] WebSocket disconnected — exiting loop")
            break
        except Exception as e:
            logger.exception("[TurnLoop] Unhandled turn error: %s", e)
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except Exception:
                break
