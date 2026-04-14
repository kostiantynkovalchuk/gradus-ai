"""
Alex Photo Report Admin Dashboard
GET /alex        → alex_dashboard.html (HTTP Basic Auth)
GET /alex/api/accuracy  → AI accuracy metrics JSON
"""

import os
import secrets
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

router = APIRouter(prefix="/alex", tags=["Alex Photo Admin"])
security = HTTPBasic()
logger = logging.getLogger(__name__)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Maya_2026"


def _verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    ok_pass = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("", response_class=HTMLResponse)
async def alex_dashboard(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(_verify_admin),
):
    """Render Alex Photo Report admin dashboard."""
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "templates", "alex_dashboard.html"
    )
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="alex_dashboard.html not found")


@router.get("/api/accuracy")
async def alex_accuracy(
    days: int = Query(default=30, ge=1, le=365),
    credentials: HTTPBasicCredentials = Depends(_verify_admin),
):
    """AI accuracy metrics — compares AI shelf-share predictions vs expert corrections."""
    try:
        from photo_report.db import get_accuracy_metrics
        return get_accuracy_metrics(days=days)
    except Exception as e:
        logger.error(f"[Alex] accuracy metrics error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/recent-queries")
async def alex_recent_queries(
    limit: int = Query(default=50, ge=1, le=200),
    credentials: HTTPBasicCredentials = Depends(_verify_admin),
):
    """Recent queries from Alex AVTD field agents bot."""
    try:
        from models import get_db
        from sqlalchemy import text as _sa_text

        db = next(get_db())
        try:
            rows = db.execute(
                _sa_text("""
                    SELECT
                        id,
                        user_name,
                        query,
                        preset_matched,
                        rag_used,
                        response_time_ms,
                        satisfied,
                        created_at
                    FROM hr_query_log
                    WHERE bot_source = 'alex_avtd'
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            ).fetchall()
        finally:
            db.close()

        return {
            "queries": [
                {
                    "id": r[0],
                    "user": r[1] or "Unknown",
                    "query": r[2],
                    "preset_hit": r[3],
                    "rag_used": r[4],
                    "response_ms": r[5] or 0,
                    "satisfied": r[6],
                    "created_at": r[7].isoformat() if r[7] else None,
                }
                for r in rows
            ],
            "total": len(rows),
        }
    except Exception as e:
        logger.error(f"[Alex] recent-queries error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/patterns")
async def alex_patterns(
    days: int = Query(default=30, ge=1, le=365),
    credentials: HTTPBasicCredentials = Depends(_verify_admin),
):
    """Systematic error patterns detected from accumulated expert corrections."""
    try:
        from photo_report.learning import analyze_correction_patterns
        return analyze_correction_patterns(days=days)
    except Exception as e:
        logger.error(f"[Alex] patterns error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
