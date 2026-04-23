import os
import logging
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

_DB_URL = None


def _get_url() -> str:
    global _DB_URL
    if _DB_URL is None:
        _DB_URL = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    return _DB_URL


def conn():
    return psycopg2.connect(_get_url(), cursor_factory=psycopg2.extras.RealDictCursor)


def execute(sql: str, params=None):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)
            c.commit()


def fetchone(sql: str, params=None):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def fetchall(sql: str, params=None):
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def log_llm_call(
    engagement_id, document_id, mode: str, model: str,
    input_tokens: int, output_tokens: int, duration_ms: int,
    result_status: str = "ok",
):
    try:
        execute(
            """INSERT INTO solcon_llm_audit
               (engagement_id, document_id, mode, model, input_tokens,
                output_tokens, duration_ms, result_status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (engagement_id, document_id, mode, model, input_tokens,
             output_tokens, duration_ms, result_status),
        )
    except Exception as e:
        logger.warning(f"[SolCon] LLM audit log failed: {e}")


def log_retrieval(finding_id, query_hash: str, top_k_results: list, used_citations: list):
    import json
    try:
        execute(
            """INSERT INTO solcon_retrieval_audit
               (finding_id, query_hash, top_k_results, used_citations)
               VALUES (%s, %s, %s, %s)""",
            (finding_id, query_hash, json.dumps(top_k_results), json.dumps(used_citations)),
        )
    except Exception as e:
        logger.warning(f"[SolCon] Retrieval audit log failed: {e}")
