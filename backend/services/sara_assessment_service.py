"""
Sara — split-brain assessment service (Architecture C, Phase 2).

Lives entirely in the MAIN backend. sara-english (backend/sara_realtime/)
never imports this module and never touches the DB directly — see CLAUDE.md
§11. This module owns:
  - upserting a `sara_sessions` row for a web (realtime) session
  - inserting the per-turn `sara_turns` row (idempotent on retry)
  - running the background Haiku assessment call
  - persisting the assessment JSON + flattened `sara_errors` rows

Mirrors backend/services/survey_service.py's shape exactly (audit B5):
psycopg2, `_get_conn()`, explicit `with conn.cursor()` blocks, explicit
commit, rollback on exception, connection always closed in `finally`.
"""
import json
import logging
import os

import psycopg2
from anthropic import Anthropic

from services.ai_models import HAIKU
from services.sara_prompts import safe_parse_json

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


# ─────────────────────────────────────────────────────────────────────────────
# ASSESSMENT PROMPT — background ANALYST. JSON output is correct here; this is
# the whole point of the Phase 1 two-prompt split (spoken prompt vs. hidden
# assessment prompt never mix).
# ─────────────────────────────────────────────────────────────────────────────

ASSESSMENT_SYSTEM_PROMPT = """\
You are an English-tutoring assessment engine. Given one exchange (learner \
utterance + tutor reply) and the learner's CEFR band, return ONLY valid JSON, \
no prose, exactly:
{"cefr_estimate": "A1|A2|B1|B2|C1|C2",
 "communicative_success": true|false,
 "errors": [{"type": "<short category>",
             "original": "<learner's exact words>",
             "correction": "<corrected form>",
             "explanation_ru": "<одна короткая строка по-русски>"}]}

Rules: max 3 errors, the most learning-valuable ones for the given band (at \
A2 ignore minor article slips if bigger issues exist; do not invent errors — \
empty list is a valid answer). original must quote the learner verbatim. \
explanation_ru is one short Russian sentence a beginner understands. Filler \
words (uh, um, mm) are NEVER errors."""


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 1: upsert_web_session
# ─────────────────────────────────────────────────────────────────────────────

def upsert_web_session(web_session_id: str) -> int:
    """
    Ensure a sara_sessions row exists for this web_session_id (source='web'),
    bump last_activity_at / message_count, and return the numeric session id.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sara_sessions (source, web_session_id)
                VALUES ('web', %s)
                ON CONFLICT (web_session_id) WHERE web_session_id IS NOT NULL DO NOTHING
                """,
                (web_session_id,),
            )
            cur.execute(
                """
                UPDATE sara_sessions
                SET last_activity_at = now(),
                    message_count = message_count + 1
                WHERE web_session_id = %s
                RETURNING id
                """,
                (web_session_id,),
            )
            row = cur.fetchone()
        conn.commit()
        return row[0]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 2: insert_turn
# ─────────────────────────────────────────────────────────────────────────────

def insert_turn(session_id: int, turn_index: int, user_text: str, sara_text: str):
    """
    Insert one sara_turns row. Returns the new turn_id, or None if this
    (session_id, turn_index) pair already exists — a retried/duplicate POST.
    None means: skip assessment entirely (idempotent, no double Haiku spend).
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sara_turns (session_id, turn_index, user_text, sara_text)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (session_id, turn_index) WHERE turn_index IS NOT NULL DO NOTHING
                RETURNING id
                """,
                (session_id, turn_index, user_text, sara_text),
            )
            row = cur.fetchone()
        conn.commit()
        return row[0] if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 3: run_assessment
# ─────────────────────────────────────────────────────────────────────────────

def run_assessment(user_text: str, sara_text: str, cefr_band: str) -> dict:
    """
    Sync Anthropic() client (main-backend convention, audit B6). Model = HAIKU.
    Never raises — unparseable output is reported, not crashed on.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("[SaraAssessment] ANTHROPIC_API_KEY not set — skipping assessment")
        return {"assessment_failed": True, "raw": ""}

    client = Anthropic(api_key=api_key)
    user_prompt = (
        f"Learner CEFR band: {cefr_band}\n\n"
        f"Learner utterance: {user_text}\n\n"
        f"Tutor reply: {sara_text}"
    )

    try:
        response = client.messages.create(
            model=HAIKU,
            max_tokens=1000,
            system=ASSESSMENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text_block = next((b for b in response.content if hasattr(b, "text")), None)
        raw = text_block.text if text_block else ""
    except Exception as e:
        logger.warning("[SaraAssessment] Haiku call failed: %s", e)
        return {"assessment_failed": True, "raw": ""}

    parsed = safe_parse_json(raw)
    if not parsed:
        logger.warning("[SaraAssessment] Unparseable assessment output: %r", raw[:500])
        return {"assessment_failed": True, "raw": raw[:500]}

    return parsed


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 4: save_assessment
# ─────────────────────────────────────────────────────────────────────────────

def save_assessment(turn_id: int, session_id: int, assessment_dict: dict):
    """
    Persist the assessment JSON on sara_turns and flatten up to 5 errors into
    sara_errors so the "repeated error" support trigger stays a cheap COUNT.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sara_turns SET assessment = %s::jsonb WHERE id = %s",
                (json.dumps(assessment_dict), turn_id),
            )
            for error in (assessment_dict.get("errors") or [])[:5]:
                error_type = error.get("type") if isinstance(error, dict) else None
                if not error_type:
                    continue
                cur.execute(
                    """
                    INSERT INTO sara_errors (turn_id, session_id, error_type)
                    VALUES (%s, %s, %s)
                    """,
                    (turn_id, session_id, error_type),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 5: get_session_corrections (Phase 3 UI read path — audit D9)
# ─────────────────────────────────────────────────────────────────────────────

def get_session_corrections(web_session_id: str) -> list:
    """
    Return ordered [{turn_index, errors:[{type,original,correction,explanation_ru}]}]
    for a web session, pulled from sara_turns.assessment jsonb.
    Empty list for an unknown session — never 404, Phase 3 UI polls this.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.turn_index, t.assessment
                FROM sara_turns t
                JOIN sara_sessions s ON s.id = t.session_id
                WHERE s.web_session_id = %s
                  AND t.turn_index IS NOT NULL
                  AND t.assessment IS NOT NULL
                ORDER BY t.turn_index ASC
                """,
                (web_session_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    result = []
    for turn_index, assessment in rows:
        errors = (assessment or {}).get("errors") or []
        result.append({
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
    return result
