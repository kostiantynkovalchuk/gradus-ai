from fastapi import APIRouter, HTTPException
import httpx
import os
import logging
from datetime import datetime, timedelta

router = APIRouter()
logger = logging.getLogger(__name__)

FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
GRAPH_API_VERSION = "v21.0"

@router.get("/page-info")
async def get_page_info():
    """Get detailed Facebook page information"""
    if not FACEBOOK_PAGE_ID or not FACEBOOK_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="Facebook credentials not configured")
    
    try:
        url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{FACEBOOK_PAGE_ID}"
        params = {
            "fields": "id,name,username,fan_count,followers_count,is_published,verification_status,category,about,link,website,phone,emails",
            "access_token": FACEBOOK_ACCESS_TOKEN
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        
        return {
            "status": "success",
            "page": data
        }
    except Exception as e:
        logger.error(f"Facebook API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/posts")
async def get_recent_posts(limit: int = 20):
    """Get recent posts - NO insights, just post data"""
    if not FACEBOOK_PAGE_ID or not FACEBOOK_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="Facebook credentials not configured")
    
    try:
        url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{FACEBOOK_PAGE_ID}/posts"
        params = {
            "fields": "id,message,created_time,full_picture,permalink_url",
            "limit": limit,
            "access_token": FACEBOOK_ACCESS_TOKEN
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        
        return {
            "status": "success",
            "posts": data.get("data", []),
            "count": len(data.get("data", [])),
            "note": "Metrics unavailable - page too new (insights need 24-48 hours)"
        }
        
    except Exception as e:
        logger.error(f"Facebook API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/insights")
async def get_page_insights(days: int = 7):
    """Get page insights - returns graceful error if data not available yet"""
    if not FACEBOOK_PAGE_ID or not FACEBOOK_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="Facebook credentials not configured")
    
    try:
        since = int((datetime.now() - timedelta(days=days)).timestamp())
        until = int(datetime.now().timestamp())
        
        url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{FACEBOOK_PAGE_ID}/insights"
        params = {
            "metric": "page_impressions,page_impressions_unique,page_post_engagements,page_fans",
            "period": "day",
            "since": since,
            "until": until,
            "access_token": FACEBOOK_ACCESS_TOKEN
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            
            if response.status_code == 400:
                return {
                    "status": "not_available_yet",
                    "message": "Insights data not available yet. Reasons: page too new, not enough followers, or posts too recent.",
                    "recommendation": "Try again in 24-48 hours after posting and getting some followers",
                    "insights": []
                }
            
            response.raise_for_status()
            data = response.json()
        
        return {
            "status": "success",
            "insights": data.get("data", []),
            "period": f"last_{days}_days"
        }
        
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            return {
                "status": "not_available_yet",
                "message": "Insights data not ready. Page needs activity and time.",
                "insights": []
            }
        logger.error(f"Facebook API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def check_page_health():
    """Quick health check of Facebook page"""
    if not FACEBOOK_PAGE_ID or not FACEBOOK_ACCESS_TOKEN:
        return {"status": "not_configured"}
    
    try:
        url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{FACEBOOK_PAGE_ID}"
        params = {
            "fields": "id,is_published,followers_count",
            "access_token": FACEBOOK_ACCESS_TOKEN
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        
        return {
            "status": "healthy",
            "is_published": data.get("is_published", False),
            "followers": data.get("followers_count", 0)
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
