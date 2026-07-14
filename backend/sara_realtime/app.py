"""
Sara Real-Time Voice Service — FastAPI app.

Serves:
  GET  /           → production lesson UI (open access)
  GET  /health     → liveness probe
  WS   /ws/session → real-time voice session (open access)

Auth: none. SARA_RT_ACCESS_TOKEN env var is read but ignored.

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

from sara_realtime.pipeline import (
    SessionPipeline,
    end_session as _forward_end_session,
    fetch_learner_context,
    report_session_streak,
    DEFAULT_LEARNER_ID,
)
from sara_realtime.eleven_ws import ScribeRealtimeSTT, should_accept_transcript, TRANSCRIPT_B1_ACTION

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ACCESS_TOKEN = os.getenv("SARA_RT_ACCESS_TOKEN", "")  # read but not used — auth disabled
# Configured pilot learner id (Part B2). A second pilot user is just a
# different env value + a seeded sara_web_state row — never hardcoded logic.
LEARNER_ID = os.getenv("SARA_RT_LEARNER_ID", DEFAULT_LEARNER_ID)
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


def _task_done_cb(label: str):
    """Return an asyncio Task done-callback that logs unexpected exceptions."""
    def _cb(task: asyncio.Task):
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.exception("[%s] task raised unexpectedly: %s", label, exc)
    return _cb


@app.get("/manifest.json")
async def manifest():
    """Serve the PWA manifest from site root so Chrome finds it at the
    standard location. The manifest itself lives in static/ alongside
    the app, but must be served without a /static/ prefix so the
    start_url ("/") and scope resolve correctly."""
    return HTMLResponse(
        content=(STATIC_DIR / "manifest.json").read_text(encoding="utf-8"),
        media_type="application/manifest+json",
    )


@app.get("/sw.js")
async def service_worker():
    """Service worker must be served from "/" scope (not /static/sw.js)
    so its scope covers the whole app, not just /static/. Chrome's PWA
    install prompt requires a registered SW — this one is network-only
    pass-through, no caching, just satisfying the installability check."""
    return HTMLResponse(
        content=(STATIC_DIR / "sw.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/")
async def index():
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/debug")
async def debug_page():
    """
    Engineering lab-bench test page (the original throwaway Phase-1 UI).
    Kept alongside the production UI at "/" for raw event/metrics debugging.
    """
    html_path = STATIC_DIR / "debug.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "service": "sara-english"})


@app.websocket("/ws/session")
async def ws_session(websocket: WebSocket):
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
    welcome_sent = [False]  # mutable so the "start" handler can flip it once

    # Part 4 audit (welcome-back beat): fetched once, right after accept(),
    # so the client can choose greeting-vs-welcome-back BEFORE it plays any
    # beat. Cached here and reused by the "start" handler below so the
    # welcome turn itself doesn't trigger a second, redundant HTTP round
    # trip to the main backend for the same learner_id.
    try:
        early_context = await fetch_learner_context(LEARNER_ID)
    except Exception as e:
        logger.exception("[WS] Early learner-context fetch failed (non-fatal): %s", e)
        early_context = None
    try:
        await websocket.send_json({
            "type": "session_context",
            "should_welcome_back": bool(early_context and early_context.get("should_welcome_back")),
        })
    except Exception:
        pass

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

                # Identity + welcome turn (Part B2/B3) — fires once per
                # session, only after this successful "start". Gated on
                # welcome_sent so a duplicate "start" (e.g. reconnect retry)
                # never speaks twice. A context-fetch or welcome-turn failure
                # must never block the lesson (rule 3) — turn_active guards
                # the mic gate around it exactly like a normal turn, and any
                # exception is caught and logged, never re-raised.
                if not welcome_sent[0]:
                    welcome_sent[0] = True
                    turn_active.set()
                    try:
                        # Reuse the context fetched right after accept() (see
                        # above) instead of fetching it again — avoids a
                        # second identical HTTP round trip per session.
                        context = early_context if early_context is not None else await fetch_learner_context(LEARNER_ID)
                        await pipeline.run_welcome_turn(
                            websocket,
                            context["display_name"],
                            context["last_session_summary"],
                            context["last_theme"],
                        )
                    except Exception as e:
                        logger.exception("[WS] Welcome turn failed (non-fatal): %s", e)
                    finally:
                        turn_active.clear()

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
                # Part 3 audit: fast, DB-only streak check — awaited here
                # (bounded, best-effort) so the result can reach the client
                # over the still-open WS before it closes. Deliberately NOT
                # the Haiku-backed recap path (that stays fire-and-forget in
                # the finally block below, unchanged). Any failure/timeout
                # degrades to a deterministic "no streak" ack — never hangs,
                # never blocks teardown.
                streak_result = None
                try:
                    streak_result = await asyncio.wait_for(
                        report_session_streak(web_session_id, LEARNER_ID),
                        timeout=3.0,
                    )
                except Exception as e:
                    logger.warning("[WS] Session streak check failed/timed out (non-fatal): %s", e)
                try:
                    await websocket.send_json({
                        "type": "session_ended",
                        "streak_milestone": bool(streak_result and streak_result.get("streak_milestone")),
                        "streak_count": streak_result.get("streak_count") if streak_result else None,
                    })
                except Exception:
                    pass
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
            _forward_end_session(web_session_id, session_elapsed_s, learner_id=LEARNER_ID),
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
            raw_text = event.get("text", "").strip()
            detected_lang = event.get("language_code")
            if not raw_text:
                logger.debug("[Scribe] Empty committed transcript — dropped")
                continue

            # Commit-boundary filter (Prompt #3 — Part B).
            # B2: noise/empty (no alphanumeric content) → silent drop.
            # B1: wrong language/script → drop + optional reask cue.
            # CJK punctuation in otherwise-valid turns is normalized, not dropped.
            accept, clean_text, reject_reason = should_accept_transcript(raw_text, detected_lang)
            if not accept:
                if reject_reason == "noise_empty":
                    logger.debug(
                        "[Scribe] Commit dropped (B2 noise/empty): %r", raw_text[:80]
                    )
                else:
                    logger.warning(
                        "[Scribe] Commit dropped (%s lang_detected=%r): %r",
                        reject_reason, detected_lang, raw_text[:80],
                    )
                    if TRANSCRIPT_B1_ACTION == "reask":
                        try:
                            await websocket.send_json({
                                "type": "transcript_rejected",
                                "action": "reask",
                            })
                        except Exception:
                            pass
                # Clear any partial bubble the client is showing for this commit
                try:
                    await websocket.send_json({"type": "partial_transcript", "text": ""})
                except Exception:
                    pass
                continue

            if turn_active.is_set():
                logger.debug(
                    "[Scribe] Committed transcript dropped (turn active): %r", clean_text[:80]
                )
                continue
            logger.info("[Scribe] Committed transcript → turn_loop: %r", clean_text[:80])
            await transcript_queue.put(clean_text)

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
