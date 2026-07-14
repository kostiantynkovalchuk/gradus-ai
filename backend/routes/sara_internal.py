"""
Sara — internal service-to-service routes (Architecture C, Phase 2).

Called only by sara-english (backend/sara_realtime/), never by the browser
directly. Registered in main.py exactly like sara_webhook (audit B4).

Auth: bearer check against env SARA_INTERNAL_TOKEN. This is a new
module-local copy of the SARA_RT_ACCESS_TOKEN `_check_token` pattern from
backend/sara_realtime/app.py — no shared internal-auth framework exists in
this codebase (audit B4), so one is not invented here.
"""
import logging

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services import sara_assessment_service as assessment_service

logger = logging.getLogger(__name__)

sara_internal_router = APIRouter(prefix="/internal/sara", tags=["sara-internal"])

import os
INTERNAL_TOKEN = os.getenv("SARA_INTERNAL_TOKEN", "")


def _check_token(authorization: str | None) -> bool:
    """Reject if INTERNAL_TOKEN is set and the bearer token doesn't match."""
    if not INTERNAL_TOKEN:
        return True
    if not authorization or not authorization.startswith("Bearer "):
        return False
    return authorization[len("Bearer "):] == INTERNAL_TOKEN


class SaraTurnRequest(BaseModel):
    web_session_id: str
    turn_index: int
    user_transcript: str
    sara_reply: str
    cefr_band: str = "A2"
    # Total active-session seconds as tracked by sara-english (Phase 3 lesson
    # completion). Optional so an older/mismatched caller degrades gracefully
    # to "never completes" rather than erroring.
    session_elapsed_s: float | None = None


@sara_internal_router.post("/turn")
async def post_turn(payload: SaraTurnRequest, authorization: str | None = Header(default=None)):
    if not _check_token(authorization):
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    try:
        result = assessment_service.write_turn_guarded(
            payload.web_session_id,
            payload.session_elapsed_s,
            payload.turn_index,
            payload.user_transcript,
            payload.sara_reply,
        )

        if result["rejected"]:
            logger.warning(
                "[SaraInternal] Turn rejected — session=%s is %s (turn_index=%s)",
                payload.web_session_id, result["session_status"], payload.turn_index,
            )
            # HTTP 200 — caller is fire-and-forget from sara-english; a non-200
            # would crash or retry-storm the voice service.  "closed" means
            # "received and safely discarded," not "written."
            return JSONResponse({"status": "closed"})

        session_id = result["session_id"]
        turn_id = result["turn_id"]
        lesson_completed_now = result["lesson_completed_now"]

        if turn_id is None:
            logger.info(
                "[SaraInternal] Duplicate turn (session=%s, turn_index=%s) — skipped assessment",
                payload.web_session_id, payload.turn_index,
            )
            return JSONResponse({"status": "duplicate"})

        assessment = assessment_service.run_assessment(
            payload.user_transcript, payload.sara_reply, payload.cefr_band
        )
        assessment_service.save_assessment(turn_id, session_id, assessment)

        if lesson_completed_now:
            logger.info(
                "[SaraInternal] Lesson completed (session=%s, turn_index=%s)",
                payload.web_session_id, payload.turn_index,
            )

        return JSONResponse({
            "status": "ok",
            "turn_id": turn_id,
            "assessment": assessment,
            "lesson_completed": lesson_completed_now,
        })

    except Exception as e:
        logger.exception("[SaraInternal] /internal/sara/turn failed: %s", e)
        return JSONResponse({"status": "error"}, status_code=500)


class SaraSessionEndRequest(BaseModel):
    web_session_id: str
    session_elapsed_s: float | None = None
    # Which learner this web session belongs to, so the best-effort recap
    # (below) knows which sara_web_state row to update. Optional so an
    # older/mismatched caller degrades gracefully to "no recap" rather than
    # erroring — the end-of-session close itself never depends on this.
    learner_id: str | None = None


@sara_internal_router.post("/session/end")
async def post_session_end(payload: SaraSessionEndRequest, authorization: str | None = Header(default=None)):
    if not _check_token(authorization):
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    try:
        closed = assessment_service.end_session(payload.web_session_id, payload.session_elapsed_s)
    except Exception as e:
        logger.exception(
            "[SaraInternal] /internal/sara/session/end failed (session=%s): %s",
            payload.web_session_id, e,
        )
        return JSONResponse({"status": "error"}, status_code=500)

    # Best-effort recap — the session is already validly closed above; a
    # recap failure here must never turn a successful end into an error
    # (rule 3 / spec Part C1).
    if payload.learner_id:
        try:
            assessment_service.generate_and_store_recap(payload.learner_id, payload.web_session_id)
        except Exception as e:
            logger.warning(
                "[SaraInternal] recap generation failed (learner=%s, session=%s): %s",
                payload.learner_id, payload.web_session_id, e,
            )

    return JSONResponse({"status": "ok", "closed": closed})


@sara_internal_router.get("/learner/{learner_id}")
async def get_learner(learner_id: str, authorization: str | None = Header(default=None)):
    """
    Identity + continuity read for the web (sara-english) welcome turn.
    Returns display_name + last_session_summary + last_theme + (Part 4 audit)
    should_welcome_back, with nulls/False (200, not 404) for a fresh/unknown
    learner_id — a context-fetch problem must never block the lesson (rule 3).
    """
    if not _check_token(authorization):
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    try:
        context = assessment_service.get_learner_context(learner_id)
        return JSONResponse({
            "display_name": context["display_name"],
            "last_session_summary": context["last_session_summary"],
            "last_theme": context["last_theme"],
            "should_welcome_back": context["should_welcome_back"],
        })
    except Exception as e:
        logger.exception("[SaraInternal] /internal/sara/learner/%s failed: %s", learner_id, e)
        return JSONResponse({"status": "error"}, status_code=500)


class SaraSessionStreakRequest(BaseModel):
    web_session_id: str
    learner_id: str


@sara_internal_router.post("/session/streak")
async def post_session_streak(payload: SaraSessionStreakRequest, authorization: str | None = Header(default=None)):
    """
    Fast, DB-only streak/continuity bookkeeping (Part 2/3 audit) — no Haiku
    call, so this is safe to await synchronously from app.py's WS
    end_session handler before it acks the client, unlike the slower
    recap generation in /session/end which stays fire-and-forget.

    Idempotency: record_session_completion() is guarded by
    sara_sessions.streak_counted, so calling this AND letting the normal
    /session/end -> generate_and_store_recap() flow run afterward for the
    same web_session_id is safe — the second call is a no-op re-read.
    """
    if not _check_token(authorization):
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    try:
        result = assessment_service.record_session_completion(payload.web_session_id, payload.learner_id)
        return JSONResponse({
            "status": "ok",
            "streak_milestone": result["streak_milestone"],
            "streak_count": result["streak_count"],
        })
    except Exception as e:
        logger.exception(
            "[SaraInternal] /internal/sara/session/streak failed (session=%s): %s",
            payload.web_session_id, e,
        )
        return JSONResponse({"status": "error"}, status_code=500)


@sara_internal_router.post("/learner/{learner_id}/reset")
async def reset_learner(learner_id: str, authorization: str | None = Header(default=None)):
    """
    Testing/ops utility: nulls last_session_summary + last_theme for a
    learner so the next welcome turn genuinely runs the fresh-learner path
    (spec Part D). Does NOT delete the sara_web_state row or display_name —
    only clears continuity. Bearer-gated exactly like the other internal
    routes.
    """
    if not _check_token(authorization):
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    try:
        found = assessment_service.reset_learner_continuity(learner_id)
        return JSONResponse({"status": "ok", "learner_id": learner_id, "found": found})
    except Exception as e:
        logger.exception("[SaraInternal] /internal/sara/learner/%s/reset failed: %s", learner_id, e)
        return JSONResponse({"status": "error"}, status_code=500)


@sara_internal_router.get("/learner/{learner_id}/streak-peek")
async def get_streak_peek(learner_id: str, authorization: str | None = Header(default=None)):
    """
    Read-only preview of whether the NEXT credited lesson for `learner_id`
    would be a streak milestone.  Does NOT consume streak_counted.

    Called by the realtime pipeline right after lesson_completed fires at
    turn-time, so the client can arm the correct beat before the user taps
    End Lesson — without racing against the authoritative streak increment
    that still runs at session-end via /session/streak.
    """
    if not _check_token(authorization):
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    try:
        result = assessment_service.peek_streak_milestone(learner_id)
        return JSONResponse({
            "status": "ok",
            "streak_milestone": result["streak_milestone"],
            "streak_count": result["streak_count"],
        })
    except Exception as e:
        logger.exception(
            "[SaraInternal] /internal/sara/learner/%s/streak-peek failed: %s",
            learner_id, e,
        )
        return JSONResponse({"status": "error"}, status_code=500)


@sara_internal_router.get("/session/{web_session_id}/corrections")
async def get_corrections(web_session_id: str, authorization: str | None = Header(default=None)):
    if not _check_token(authorization):
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    try:
        corrections = assessment_service.get_session_corrections(web_session_id)
        return JSONResponse(corrections)
    except Exception as e:
        logger.exception(
            "[SaraInternal] /internal/sara/session/%s/corrections failed: %s",
            web_session_id, e,
        )
        return JSONResponse({"status": "error"}, status_code=500)
