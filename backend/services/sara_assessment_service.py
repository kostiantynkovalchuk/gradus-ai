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
from datetime import datetime, timedelta, timezone

import psycopg2
from anthropic import Anthropic

from services.ai_models import HAIKU
from services.sara_prompts import safe_parse_json

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Elapsed *active* seconds (learner speaking/turn time, tracked by sara-english
# and sent on every turn POST) at which a web session auto-flips to
# status='completed'. Default 600s = 10 minutes.
SARA_LESSON_COMPLETE_S = int(os.environ.get("SARA_LESSON_COMPLETE_S", "600"))


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

def upsert_web_session(web_session_id: str, session_elapsed_s: float | None = None):
    """
    Ensure a sara_sessions row exists for this web_session_id (source='web'),
    bump last_activity_at / message_count, ratchet active_seconds up to the
    caller-reported elapsed time, and flip status 'active' -> 'completed'
    (setting completed_at) the first time active_seconds crosses
    SARA_LESSON_COMPLETE_S.

    SELECT ... FOR UPDATE row-locks the session for the duration of this
    transaction so concurrent/retried turn POSTs cannot race the completion
    flip (same row-locking pattern used elsewhere in this codebase for
    idempotency, e.g. duplicate post prevention).

    Returns (session_id, lesson_completed_now) where lesson_completed_now is
    True only on the single call that performs the active->completed flip.
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
                "SELECT id, status, active_seconds FROM sara_sessions "
                "WHERE web_session_id = %s FOR UPDATE",
                (web_session_id,),
            )
            row = cur.fetchone()
            session_id, prev_status, prev_active = row

            elapsed = int(session_elapsed_s) if session_elapsed_s is not None else 0
            new_active = max(prev_active, elapsed)

            lesson_completed_now = (
                prev_status == "active" and new_active >= SARA_LESSON_COMPLETE_S
            )
            new_status = "completed" if lesson_completed_now else prev_status

            cur.execute(
                """
                UPDATE sara_sessions
                SET last_activity_at = now(),
                    message_count = message_count + 1,
                    active_seconds = %s,
                    status = %s,
                    completed_at = CASE WHEN %s THEN now() ELSE completed_at END
                WHERE id = %s
                """,
                (new_active, new_status, lesson_completed_now, session_id),
            )
        conn.commit()
        return session_id, lesson_completed_now
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 1b: end_session — explicit end-of-session signal (Phase 3)
# ─────────────────────────────────────────────────────────────────────────────

def end_session(web_session_id: str, session_elapsed_s: float | None = None) -> bool:
    """
    Idempotent atomic close: always stamps ended_at/active_seconds for the
    session (so a retried or late end-of-session POST against an already-
    'completed' session still records the end), but the CASE guards the
    *status transition* only — a session already past 'active' (e.g.
    'completed') is never demoted to 'closed'. Returns True iff the row's
    status is 'closed' after this call.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sara_sessions
                SET ended_at = now(),
                    active_seconds = GREATEST(active_seconds, %s),
                    status = CASE WHEN status = 'active' THEN 'closed'
                                  ELSE status END
                WHERE web_session_id = %s
                RETURNING status
                """,
                (int(session_elapsed_s or 0), web_session_id),
            )
            row = cur.fetchone()
        conn.commit()
        return row is not None and row[0] == "closed"
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


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 6: get_learner_context — web-safe identity + continuity read
#
# Reads ONLY sara_web_state (our own table, migration 069). NEVER reads
# sara_state / sara_sessions.theme — those are the Telegram bot's
# single-writer columns (audit C12). A fresh/unknown learner_id degrades to
# a name-only context with null summary/theme rather than raising, so a
# context-fetch problem never blocks the lesson (rule 3).
# ─────────────────────────────────────────────────────────────────────────────

# Threshold for the welcome-back beat (Part 4 audit): configurable, default
# 3 days. A null last_session_at (never had a session, or pre-migration-070
# row) means "first-ever session" — that is a normal greeting, NOT
# welcome-back, per spec Part 4.
SARA_WELCOME_BACK_DAYS = int(os.environ.get("SARA_WELCOME_BACK_DAYS", "3"))


def get_learner_context(learner_id: str) -> dict:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT display_name, last_session_summary, last_theme, last_session_at "
                "FROM sara_web_state WHERE learner_id = %s",
                (learner_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return {
            "display_name": learner_id.capitalize(),
            "last_session_summary": None,
            "last_theme": None,
            "should_welcome_back": False,
        }

    display_name, last_session_summary, last_theme, last_session_at = row

    should_welcome_back = False
    if last_session_at is not None:
        gap = datetime.now(timezone.utc) - last_session_at
        should_welcome_back = gap >= timedelta(days=SARA_WELCOME_BACK_DAYS)

    return {
        "display_name": display_name,
        "last_session_summary": last_session_summary,
        "last_theme": last_theme,
        "should_welcome_back": should_welcome_back,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 7: generate_and_store_recap — session-end continuity write
#
# ENGLISH ONLY output (summary_en/theme are fed straight back into a future
# English welcome turn, audit language law). Writes to sara_web_state ONLY —
# never to sara_state.last_session_summary or sara_sessions.theme (audit
# C12: those are the Telegram bot's single-writer columns).
#
# Best-effort by design: called as the LAST step of /internal/sara/session/end,
# wrapped so any failure here never fails the (already-succeeded) end call.
# Idempotency choice: a re-run simply regenerates the recap from the same
# turns and overwrites the row (acceptable — recap is a derived summary, not
# an append-only log; no "already written" guard is kept).
# ─────────────────────────────────────────────────────────────────────────────

RECAP_SYSTEM_PROMPT = """\
You are summarizing one English-tutoring session for the NEXT session's \
opening greeting. Given the conversation turns, return ONLY valid JSON, no \
prose, exactly:
{"summary_en": "<=2 sentences, ENGLISH ONLY, what the learner actually said \
or practised>" or null,
 "theme": "<3-6 word topic label, ENGLISH ONLY>" or null}

HONESTY RULE (critical — this summary is read back to the learner next time):
Summarize ONLY what the learner actually said this session. Do not invent
places, events, names, or details that were not in the transcript. Do not
embellish or guess at specifics the learner never mentioned.

If the session was too short, empty, or had no real learner content to
summarize (e.g. only a greeting, a single word, silence, or test text),
return both fields as JSON null — do NOT invent a plausible-sounding
summary just to fill the field.

Rules: English only, no Russian or any other language anywhere in the
output. Be specific and concrete ONLY when the transcript actually supports
it."""


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 6b: record_session_completion — streak + last-session-at bookkeeping
#
# Two DIFFERENT conditions, per audit — do not conflate:
#   - last_session_at = now() UNCONDITIONALLY on every session end (welcome-
#     back cares about any absence, not credit).
#   - completed_lesson_count += 1 ONLY IF this session's status='completed',
#     and only ONCE per session — guarded by sara_sessions.streak_counted so
#     a double call to session/end (it's idempotent elsewhere) can't
#     double-count. The guard is read-and-flip inside one transaction: the
#     increment + the streak_counted=TRUE write commit together, so a second
#     call for the same web_session_id sees streak_counted already TRUE and
#     skips the increment entirely.
#
# Called from TWO places, both safe because of the guard above:
#   1. The fast /internal/sara/session/streak endpoint (awaited synchronously
#      by app.py's WS end_session handler, before it acks the client) — this
#      is the path that actually reaches the browser in time to pick a beat.
#   2. generate_and_store_recap() below (fire-and-forget, may run after #1
#      already did the bookkeeping — becomes a no-op re-read in that case).
#
# Best-effort by design (rule 3): never raises; a failure here must never
# block session end or recap generation.
# ─────────────────────────────────────────────────────────────────────────────

def record_session_completion(web_session_id: str, learner_id: str) -> dict:
    """Returns {"streak_milestone": bool, "streak_count": int|None}."""
    try:
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, streak_counted FROM sara_sessions WHERE web_session_id = %s",
                    (web_session_id,),
                )
                row = cur.fetchone()
                status, streak_counted = (row[0], row[1]) if row else (None, False)

                should_increment = (status == "completed") and not streak_counted

                if should_increment:
                    cur.execute(
                        """
                        INSERT INTO sara_web_state
                            (learner_id, display_name, completed_lesson_count, last_session_at, updated_at)
                        VALUES (%s, %s, 1, now(), now())
                        ON CONFLICT (learner_id) DO UPDATE
                        SET completed_lesson_count = sara_web_state.completed_lesson_count + 1,
                            last_session_at = now(),
                            updated_at = now()
                        RETURNING completed_lesson_count
                        """,
                        (learner_id, learner_id.capitalize()),
                    )
                    new_count = cur.fetchone()[0]
                    cur.execute(
                        "UPDATE sara_sessions SET streak_counted = TRUE WHERE web_session_id = %s",
                        (web_session_id,),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO sara_web_state (learner_id, display_name, last_session_at, updated_at)
                        VALUES (%s, %s, now(), now())
                        ON CONFLICT (learner_id) DO UPDATE
                        SET last_session_at = now(),
                            updated_at = now()
                        RETURNING completed_lesson_count
                        """,
                        (learner_id, learner_id.capitalize()),
                    )
                    new_count = cur.fetchone()[0] if status == "completed" else None
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "[SaraAssessment] record_session_completion failed (learner=%s, session=%s): %s",
            learner_id, web_session_id, e,
        )
        return {"streak_milestone": False, "streak_count": None}

    streak_milestone = bool(new_count is not None and new_count % 5 == 0 and should_increment)
    return {"streak_milestone": streak_milestone, "streak_count": new_count}


def generate_and_store_recap(learner_id: str, web_session_id: str) -> dict | None:
    # Streak/timestamp bookkeeping runs first and independently of recap
    # generation succeeding — recap can bail out below (no turns, no API
    # key, LLM/parse failure) but last_session_at + the credited-lesson
    # count must still be written (rule 3 / audit Part 2).
    try:
        streak_info = record_session_completion(web_session_id, learner_id)
    except Exception as e:
        logger.warning("[SaraAssessment] Streak bookkeeping raised unexpectedly: %s", e)
        streak_info = {"streak_milestone": False, "streak_count": None}

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.user_text, t.sara_text
                FROM sara_turns t
                JOIN sara_sessions s ON s.id = t.session_id
                WHERE s.web_session_id = %s
                ORDER BY t.turn_index ASC
                """,
                (web_session_id,),
            )
            turns = cur.fetchall()
    finally:
        conn.close()

    if not turns:
        logger.info("[SaraAssessment] No turns for session=%s — skipping recap", web_session_id)
        return {"summary_en": None, "theme": None, **streak_info}

    transcript = "\n".join(f"Learner: {u}\nTutor: {s}" for u, s in turns)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("[SaraAssessment] ANTHROPIC_API_KEY not set — skipping recap")
        return {"summary_en": None, "theme": None, **streak_info}

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=HAIKU,
            max_tokens=400,
            system=RECAP_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": transcript}],
        )
        text_block = next((b for b in response.content if hasattr(b, "text")), None)
        raw = text_block.text if text_block else ""
    except Exception as e:
        logger.warning("[SaraAssessment] Recap Haiku call failed (session=%s): %s", web_session_id, e)
        return {"summary_en": None, "theme": None, **streak_info}

    if not isinstance(parsed := safe_parse_json(raw), dict):
        logger.warning("[SaraAssessment] Unparseable recap output (session=%s): %r", web_session_id, raw[:500])
        return {"summary_en": None, "theme": None, **streak_info}

    summary_en = parsed.get("summary_en")
    theme = parsed.get("theme")

    # Honesty rule (spec Part D3a): the model may legitimately return both
    # fields as null when there was nothing real to summarize (too short/
    # empty session). That is a valid, honest outcome — write the nulls so
    # the next welcome turn correctly falls back to the fresh-learner path,
    # rather than treating this as a failure and leaving stale data behind.
    if summary_en is None and theme is None:
        logger.info(
            "[SaraAssessment] Recap: session too short/empty to summarize (session=%s) — writing nulls",
            web_session_id,
        )
    elif not summary_en or not theme:
        # Half-populated (one present, one missing) is a malformed response,
        # not an honest null — skip the write rather than store a partial
        # continuity record.
        logger.warning("[SaraAssessment] Malformed recap output (session=%s): %r", web_session_id, raw[:500])
        return {"summary_en": None, "theme": None, **streak_info}

    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sara_web_state (learner_id, display_name, last_session_summary, last_theme, updated_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (learner_id) DO UPDATE
                SET last_session_summary = EXCLUDED.last_session_summary,
                    last_theme = EXCLUDED.last_theme,
                    updated_at = now()
                """,
                (learner_id, learner_id.capitalize(), summary_en, theme),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info("[SaraAssessment] Recap stored (learner=%s, session=%s): theme=%r", learner_id, web_session_id, theme)
    return {"summary_en": summary_en, "theme": theme, **streak_info}


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 8: reset_learner_continuity — testing/ops utility
#
# Nulls last_session_summary + last_theme for a learner so the next welcome
# turn genuinely runs the fresh-learner path (spec Part D). Writes to
# sara_web_state ONLY, same isolation guarantee as generate_and_store_recap.
# Does not delete the row or touch display_name.
# ─────────────────────────────────────────────────────────────────────────────

def reset_learner_continuity(learner_id: str) -> bool:
    """Returns True if a sara_web_state row existed (and was reset), False if not found."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sara_web_state
                SET last_session_summary = NULL, last_theme = NULL, updated_at = now()
                WHERE learner_id = %s
                """,
                (learner_id,),
            )
            found = cur.rowcount > 0
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info("[SaraAssessment] Continuity reset (learner=%s, found=%s)", learner_id, found)
    return found
