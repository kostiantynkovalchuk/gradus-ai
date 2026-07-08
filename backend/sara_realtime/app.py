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

Session architecture: three long-lived coroutines per session.

  [ws_session receive loop]
    mic frame → gate at INGESTION:
        turn_active.is_set() → discard + count (rate-logged)
        else                 → audio_queue.put_nowait()
    JSON control             → start | end_session

  [stt_reader task] — owns the Scribe socket for the session lifetime
    LAZY START: created only after the "start" control message arrives so
    that an idle test page does not burn EL connections on every load.
    loop:
      connect Scribe (same URL/params as before)
      run two parallel sub-tasks:
        stt_pump: audio_queue → stt.send_audio()
        stt_recv: stt.receive_events() →
            partial_transcript  → relay to browser
            committed_transcript:
                turn_active.is_set()? drop + DEBUG
                empty/whitespace?     drop + DEBUG
                else                  → transcript_queue.put()
            error               → log ERROR
      ConnectionClosedOK/Error from stt_recv: log WARNING, reconnect
        backoff: 0.5 → 1 → 2 → 4 → 8s (max 5 consecutive attempts)
        success: resets consecutive counter
        attempt 5 failure: send {"type":"error"} to browser, end task
      CancelledError: return (session teardown — do NOT reconnect)

  [turn_loop task] — consumes transcripts, never touches the STT socket
    transcript = await transcript_queue.get()   ← blocks; cannot spin
    turn_active.set()
    await pipeline.run_turn(websocket, transcript)
    turn_active.clear()

There is NO post-turn queue drain anywhere in this session. Mic gating
happens at ingestion; committed-transcript gating happens in stt_recv. R10.
"""
import asyncio
import logging
import os
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from sara_realtime.pipeline import SessionPipeline, end_session as _forward_end_session
from sara_realtime.eleven_ws import ScribeRealtimeSTT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ACCESS_TOKEN = os.getenv("SARA_RT_ACCESS_TOKEN", "")
VOICE_ID = os.getenv("SARA_RT_VOICE_ID") or os.getenv("ELEVENLABS_VOICE_ID", "")
STT_MODEL = os.getenv("SARA_RT_STT_MODEL", "scribe_v2_realtime")
TTS_MODEL = os.getenv("SARA_RT_TTS_MODEL", "eleven_flash_v2_5")

# Maximum consecutive Scribe reconnect attempts before ending the session.
STT_MAX_ATTEMPTS = 5
# Exponential backoff schedule (seconds), one entry per attempt index.
STT_BACKOFF_S = [0.5, 1.0, 2.0, 4.0, 8.0]

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Sara Real-Time Voice", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _check_token(token: str) -> bool:
    """Reject if ACCESS_TOKEN is set and the provided token doesn't match."""
    if not ACCESS_TOKEN:
        return True
    return token == ACCESS_TOKEN


def _task_done_cb(label: str):
    """Return an asyncio Task done-callback that logs unexpected exceptions."""
    def _cb(task: asyncio.Task):
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.exception("[%s] task raised unexpectedly: %s", label, exc)
    return _cb


@app.get("/")
async def index(token: str = ""):
    if not _check_token(token):
        return HTMLResponse("<h1>403 Forbidden</h1>", status_code=403)
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/debug")
async def debug_page(token: str = ""):
    """
    Engineering lab-bench test page (the original throwaway Phase-1 UI).
    Kept alongside the production UI at "/" for raw event/metrics debugging —
    same token gate, same static dir, just a different file.
    """
    if not _check_token(token):
        return HTMLResponse("<h1>403 Forbidden</h1>", status_code=403)
    html_path = STATIC_DIR / "debug.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "service": "sara-english"})


@app.websocket("/ws/session")
async def ws_session(websocket: WebSocket, token: str = ""):
    if not _check_token(token):
        await websocket.close(code=4403)
        return

    await websocket.accept()
    logger.info("[WS] New session accepted")

    # Web session identity for Architecture C turn forwarding. Generated here
    # (not by the browser) so it cannot be spoofed/reused across sessions.
    # turn_index increments per completed turn within this WS session and is
    # the idempotency key on the main-backend side (sara_turns unique index).
    web_session_id = str(uuid4())
    turn_index_counter = [0]
    # Monotonic wall-clock start of this WS session — used to compute
    # session_elapsed_s for both per-turn forwarding and the end-of-session
    # POST (Phase 3 lesson completion tracking).
    session_start_t = time.monotonic()

    pipeline = SessionPipeline(
        voice_id=VOICE_ID,
        stt_model=STT_MODEL,
        tts_model=TTS_MODEL,
    )

    # ── Shared state ──────────────────────────────────────────────────────────
    audio_queue: asyncio.Queue = asyncio.Queue(maxsize=500)      # mic → stt_reader
    transcript_queue: asyncio.Queue = asyncio.Queue(maxsize=10)  # stt_reader → turn_loop
    turn_active = asyncio.Event()  # set while pipeline.run_turn is executing

    # Ingestion-gate telemetry (rate-limited to once per 60s)
    discarded_mic = [0]
    last_gate_log = [time.monotonic()]  # R4 fix: real monotonic start, not 0.0

    # Monotonic timestamp of the last mic frame forwarded to Scribe.
    # Updated by _stt_pump on every send; read by _stt_reader to decide
    # whether a Scribe close is "idle" (INFO) or "mid-stream" (WARNING).
    last_audio_t: list = [0.0]

    # ── Long-lived background tasks ───────────────────────────────────────────
    # reader_task is started LAZILY — only after the "start" control message
    # arrives, so an idle browser tab does not open a Scribe connection.
    reader_task = None

    loop_task = asyncio.create_task(
        _turn_loop(
            websocket, pipeline, transcript_queue, turn_active,
            web_session_id, turn_index_counter, session_start_t,
        ),
        name="turn_loop",
    )
    loop_task.add_done_callback(_task_done_cb("turn_loop"))

    session_started = False

    try:
        while True:
            try:
                message = await websocket.receive()
            except WebSocketDisconnect:
                logger.info("[WS] Client disconnected")
                break

            # ASGI sends {"type":"websocket.disconnect"} before raising
            # WebSocketDisconnect; catch it here to avoid the
            # "Cannot call receive once a disconnect message has been received"
            # RuntimeError on page reload.
            if message.get("type") == "websocket.disconnect":
                code = message.get("code", "?")
                logger.info("[WS] Client disconnected (ASGI, code=%s)", code)
                break

            # ── Binary frame: PCM16 mic audio (ingestion gate) ────────────────
            if "bytes" in message and message["bytes"]:
                if session_started:
                    if turn_active.is_set():
                        # Half-duplex gate: discard while Sara is thinking/speaking.
                        # Gating here at ingestion — no post-turn drain exists. R10.
                        discarded_mic[0] += 1
                        now = time.monotonic()
                        if now - last_gate_log[0] >= 60.0:
                            logger.info(
                                "[WS] Gate: %d mic frames discarded in last 60s",
                                discarded_mic[0],
                            )
                            discarded_mic[0] = 0
                            last_gate_log[0] = now
                    else:
                        try:
                            audio_queue.put_nowait(message["bytes"])
                        except asyncio.QueueFull:
                            logger.warning("[WS] Audio queue full — dropping frame")
                continue

            # ── JSON control message ──────────────────────────────────────────
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
                # Lazy Scribe connect: open the EL STT socket only now that mic
                # is actually flowing, not at WS-accept time.
                if reader_task is None:
                    reader_task = asyncio.create_task(
                        _stt_reader(
                            audio_queue, transcript_queue, turn_active,
                            websocket, last_audio_t,
                        ),
                        name="stt_reader",
                    )
                    reader_task.add_done_callback(_task_done_cb("stt_reader"))

            elif msg_type == "ping":
                try:
                    await websocket.send_json({"type": "pong"})
                except Exception:
                    pass

            elif msg_type == "text_turn":
                # Typed-text turn (UI text input), bypassing STT entirely.
                # Same gating as a committed Scribe transcript: ignored before
                # "start" and dropped while a turn is already in flight — the
                # ingestion gate for mic frames has no equivalent for typed
                # text, so it is enforced explicitly here.
                if not session_started:
                    continue
                text = (cmd.get("text") or "").strip()
                if not text:
                    continue
                if turn_active.is_set():
                    logger.debug("[WS] text_turn dropped (turn active): %r", text[:80])
                    continue
                try:
                    transcript_queue.put_nowait(text)
                except asyncio.QueueFull:
                    logger.warning("[WS] transcript_queue full — dropping text_turn")

            elif msg_type == "end_session":
                logger.info("[WS] Client requested end_session")
                break

            else:
                logger.debug("[WS] Unknown command type: %s", msg_type)

    except WebSocketDisconnect:
        logger.info("[WS] WebSocket disconnected during session")
    except Exception as e:
        logger.exception("[WS] Session error: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        # reader_task is None if the "start" message never arrived.
        if reader_task is not None:
            reader_task.cancel()
        loop_task.cancel()
        tasks = [t for t in (reader_task, loop_task) if t is not None]
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("[WS] Session closed — all tasks cancelled")

        # Fire-and-forget end-of-session signal to the main backend (Phase 3
        # lesson completion). Created as its own task so a slow/failed POST
        # here can never delay WS teardown — this function call itself
        # returns immediately either way.
        session_elapsed_s = time.monotonic() - session_start_t
        end_task = asyncio.create_task(
            _forward_end_session(web_session_id, session_elapsed_s),
            name="forward_end_session",
        )
        end_task.add_done_callback(_task_done_cb("forward_end_session"))


# ── STT reader task ───────────────────────────────────────────────────────────

async def _stt_reader(
    audio_queue: asyncio.Queue,
    transcript_queue: asyncio.Queue,
    turn_active: asyncio.Event,
    websocket,
    last_audio_t: list,  # [float] shared with _stt_pump; 0.0 until first audio sent
):
    """
    Owns the Scribe STT WebSocket for the session lifetime.

    Connects Scribe, runs two parallel sub-tasks (pump + recv), and reconnects
    with exponential backoff when the connection closes unexpectedly.

    Log levels for Scribe closes:
      INFO    — EL closed an idle connection (no mic audio in the last 5s).
                Expected behavior; no operator action needed.
      WARNING — connection closed while audio was actively flowing (<5s ago).
                May indicate a dropped utterance; worth investigating.

    R9: ConnectionClosed is never swallowed — it propagates from receive_events()
    through _stt_recv, surfaces here as an exception, and triggers a reconnect
    or user-visible error. Deafness without a log line is forbidden.
    """
    consecutive = 0

    while True:
        pump_task = None
        recv_task = None
        try:
            async with ScribeRealtimeSTT(STT_MODEL) as stt:
                consecutive = 0
                logger.info("[Scribe] Connected — consecutive failure counter reset")

                pump_task = asyncio.create_task(
                    _stt_pump(audio_queue, stt, last_audio_t), name="stt_pump"
                )
                recv_task = asyncio.create_task(
                    _stt_recv(stt, transcript_queue, turn_active, websocket),
                    name="stt_recv",
                )
                pump_task.add_done_callback(_task_done_cb("stt_pump"))
                recv_task.add_done_callback(_task_done_cb("stt_recv"))

                try:
                    # Block until either sub-task finishes (pump never finishes
                    # normally; recv finishes when ConnectionClosed propagates).
                    done, _ = await asyncio.wait(
                        {pump_task, recv_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    # Always cancel both sub-tasks on any exit path.
                    pump_task.cancel()
                    recv_task.cancel()
                    try:
                        await asyncio.gather(pump_task, recv_task, return_exceptions=True)
                    except asyncio.CancelledError:
                        pass  # Outer cancellation during cleanup — acceptable

                # Re-raise the first exception from a finished task.
                # If recv_task raised ConnectionClosed*, it propagates here
                # and lands in the except below → triggers reconnect.
                for t in done:
                    if not t.cancelled() and t.exception() is not None:
                        raise t.exception()  # type: ignore[misc]

                # recv_task ended without exception — EL closed the socket cleanly
                # (e.g. idle timeout). Log at INFO if the connection was idle,
                # WARNING if audio was flowing recently (possible dropped utterance).
                audio_age = time.monotonic() - last_audio_t[0]
                if audio_age < 5.0:
                    logger.warning(
                        "[Scribe] EL closed STT connection while audio active "
                        "(last frame %.1fs ago) — reconnecting",
                        audio_age,
                    )
                else:
                    logger.info(
                        "[Scribe] EL closed idle STT connection "
                        "(no audio for %.0fs) — reconnecting",
                        audio_age,
                    )
                # Fall through to next while True iteration (no exception = reconnect)

        except asyncio.CancelledError:
            # Session teardown — do NOT reconnect.
            logger.info("[Scribe] Reader task cancelled — session teardown")
            return

        except Exception as e:
            consecutive += 1
            is_close = isinstance(e, (ConnectionClosedError, ConnectionClosedOK))
            code = getattr(getattr(e, "rcvd", None), "code", "?") if is_close else None

            if is_close:
                audio_age = time.monotonic() - last_audio_t[0]
                if audio_age < 5.0:
                    logger.warning(
                        "[Scribe] Connection closed while audio active "
                        "(last frame %.1fs ago, close_code=%s, consecutive=%d/%d)",
                        audio_age, code, consecutive, STT_MAX_ATTEMPTS,
                    )
                else:
                    logger.info(
                        "[Scribe] EL closed idle connection "
                        "(no audio for %.0fs, close_code=%s, consecutive=%d/%d)",
                        audio_age, code, consecutive, STT_MAX_ATTEMPTS,
                    )
            else:
                logger.exception(
                    "[Scribe] Unexpected error (consecutive=%d/%d): %s",
                    consecutive, STT_MAX_ATTEMPTS, e,
                )

            if consecutive > STT_MAX_ATTEMPTS:
                logger.error(
                    "[Scribe] %d consecutive failures — ending session", STT_MAX_ATTEMPTS
                )
                try:
                    await websocket.send_json({
                        "type": "error",
                        "message": "speech connection lost — please restart the session",
                    })
                except Exception:
                    pass
                return

            # User-visible reconnect notice (rule 3 of CLAUDE.md: no invisible failure).
            try:
                await websocket.send_json({"type": "status", "message": "reconnecting speech..."})
            except Exception:
                return  # Browser also disconnected — stop trying

            backoff = STT_BACKOFF_S[min(consecutive - 1, len(STT_BACKOFF_S) - 1)]
            logger.info("[Scribe] Reconnecting in %.1fs...", backoff)
            await asyncio.sleep(backoff)


async def _stt_pump(
    audio_queue: asyncio.Queue,
    stt: ScribeRealtimeSTT,
    last_audio_t: list,  # [float] — updated here so _stt_reader can gauge activity
):
    """
    Drain mic frames from audio_queue and forward to the Scribe STT socket.
    Runs until cancelled (Scribe reconnect or session teardown).
    Records the monotonic time of each forwarded frame in last_audio_t[0].
    """
    while True:
        chunk = await audio_queue.get()
        if chunk:  # None or empty bytes are no-ops; skip silently
            last_audio_t[0] = time.monotonic()
            await stt.send_audio(chunk)


async def _stt_recv(
    stt: ScribeRealtimeSTT,
    transcript_queue: asyncio.Queue,
    turn_active: asyncio.Event,
    websocket,
):
    """
    Receive Scribe events and route them.

    partial_transcript  → relay to browser as {"type":"partial_transcript"}
    committed_transcript:
        empty/whitespace → drop (DEBUG)
        turn_active set  → drop — trailing tail or echo (DEBUG)
        else             → transcript_queue.put() for turn_loop to consume
    error               → log ERROR (terminal; function returns after yield)

    ConnectionClosedError / ConnectionClosedOK propagate from receive_events()
    through this function to _stt_reader, which handles reconnect. R9.
    """
    async for event in stt.receive_events():
        if event["type"] == "partial":
            try:
                await websocket.send_json({
                    "type": "partial_transcript",
                    "text": event["text"],
                })
            except Exception:
                pass

        elif event["type"] == "final":
            text = event.get("text", "").strip()
            if not text:
                logger.debug("[Scribe] Empty committed transcript — dropped")
                continue
            if turn_active.is_set():
                logger.debug(
                    "[Scribe] Committed transcript dropped (turn active): %r", text[:80]
                )
                continue
            logger.info("[Scribe] Committed transcript → turn_loop: %r", text[:80])
            await transcript_queue.put(text)

        elif event["type"] == "error":
            logger.error("[Scribe] Error event from Scribe: %s", event.get("message"))


# ── Turn loop task ────────────────────────────────────────────────────────────

async def _turn_loop(
    websocket,
    pipeline: SessionPipeline,
    transcript_queue: asyncio.Queue,
    turn_active: asyncio.Event,
    web_session_id: str,
    turn_index_counter: list,  # [int], shared mutable counter — one WS session
    session_start_t: float,  # monotonic WS-accept time — for session_elapsed_s
):
    """
    Consumes committed transcripts from transcript_queue and runs the brain+TTS
    pipeline for each one.

    Blocks on transcript_queue.get() — cannot spin. A broken STT socket produces
    no transcripts, so this task is naturally idle until stt_reader reconnects and
    the learner speaks again.

    turn_active is set for the duration of each pipeline.run_turn call so that
    both the ingestion gate (ws_session) and the committed-transcript gate
    (stt_recv) discard stale audio and echo commits while Sara is responding.

    R10: there is no post-turn drain. Gating is at ingestion only.
    """
    while True:
        # Blocks here — CancelledError propagates on session teardown.
        try:
            transcript = await transcript_queue.get()
        except asyncio.CancelledError:
            logger.info("[TurnLoop] Cancelled while waiting for transcript — exiting")
            return

        turn_active.set()
        try:
            turn_index_counter[0] += 1
            await pipeline.run_turn(
                websocket, transcript,
                web_session_id=web_session_id,
                turn_index=turn_index_counter[0],
                session_elapsed_s=time.monotonic() - session_start_t,
            )
        except asyncio.CancelledError:
            logger.info("[TurnLoop] Cancelled during pipeline turn — exiting")
            return
        except Exception as e:
            # run_turn is documented as never raising, but belt-and-suspenders.
            logger.exception("[TurnLoop] Unexpected error in run_turn: %s", e)
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass
        finally:
            turn_active.clear()
