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


@sara_internal_router.post("/turn")
async def post_turn(payload: SaraTurnRequest, authorization: str | None = Header(default=None)):
    if not _check_token(authorization):
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    try:
        session_id = assessment_service.upsert_web_session(payload.web_session_id)

        turn_id = assessment_service.insert_turn(
            session_id, payload.turn_index, payload.user_transcript, payload.sara_reply
        )
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

        return JSONResponse({"status": "ok", "turn_id": turn_id})

    except Exception as e:
        logger.exception("[SaraInternal] /internal/sara/turn failed: %s", e)
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
