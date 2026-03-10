from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from solomon_search import parse_query, search_decisions
from solomon_ui import get_solomon_html
from database import get_db_connection
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/law", tags=["solomon"])


class SearchRequest(BaseModel):
    query: str
    summarize: bool = False


@router.get("/", response_class=HTMLResponse)
async def solomon_page():
    return get_solomon_html()


@router.get("/health")
async def health():
    return {"status": "ok", "service": "solomon"}


@router.post("/search")
async def search(request: SearchRequest):
    try:
        params = parse_query(request.query)
        judgments = search_decisions(params)

        return {
            "count": len(judgments),
            "params": params,
            "results": judgments
        }
    except Exception as e:
        logger.error(f"Solomon API error: {e}")
        raise HTTPException(status_code=500, detail="Search processing error")


@router.get("/analytics", response_class=HTMLResponse)
async def solomon_analytics():
    import os
    analytics_path = os.path.join(os.path.dirname(__file__), "solomon_analytics.html")
    with open(analytics_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@router.get("/analytics/data")
async def solomon_analytics_data():
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE feedback='like') as likes,
                COUNT(*) FILTER (WHERE feedback='dislike') as dislikes,
                COUNT(DISTINCT session_id) as users,
                COUNT(*) as total
            FROM solomon_feedback
            WHERE created_at > NOW() - INTERVAL '30 days'
        """)
        stats = cur.fetchone()

        cur.execute("""
            SELECT cause_number, COUNT(*) as likes
            FROM solomon_feedback
            WHERE feedback = 'like'
            GROUP BY cause_number
            ORDER BY likes DESC
            LIMIT 5
        """)
        top_liked = cur.fetchall()

        cur.execute("""
            SELECT cause_number, COUNT(*) as dislikes
            FROM solomon_feedback
            WHERE feedback = 'dislike'
            GROUP BY cause_number
            ORDER BY dislikes DESC
            LIMIT 5
        """)
        top_disliked = cur.fetchall()

        cur.close()
    finally:
        conn.close()

    return {
        "last_30_days": {
            "likes": stats[0], "dislikes": stats[1],
            "users": stats[2], "total": stats[3],
            "satisfaction": round(stats[0] / stats[3] * 100) if stats[3] > 0 else 0
        },
        "top_liked": [{"cause_number": r[0], "likes": r[1]} for r in top_liked],
        "top_disliked": [{"cause_number": r[0], "dislikes": r[1]} for r in top_disliked],
    }


@router.post("/telegram/webhook")
async def solomon_webhook(request: Request):
    from solomon_bot import process_solomon_update
    update_data = await request.json()
    await process_solomon_update(update_data)
    return {"ok": True}
