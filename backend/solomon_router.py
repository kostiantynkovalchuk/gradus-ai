from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from solomon_search import parse_query, search_decisions, summarize_decision
from solomon_ui import get_solomon_html
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

        if request.summarize:
            for j in judgments:
                j["summary"] = summarize_decision(j.get("link", ""))

        return {
            "count": len(judgments),
            "params": params,
            "results": judgments
        }
    except Exception as e:
        logger.error(f"Solomon API error: {e}")
        raise HTTPException(status_code=500, detail="Search processing error")


@router.post("/telegram/webhook")
async def solomon_webhook(request: Request):
    from solomon_bot import process_solomon_update
    update_data = await request.json()
    await process_solomon_update(update_data)
    return {"ok": True}
