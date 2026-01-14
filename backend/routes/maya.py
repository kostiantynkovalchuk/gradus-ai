from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
import os
import logging

from routes.chat_endpoints import chat_with_avatars, ChatRequest as ChatEndpointRequest
from services.preset_service import preset_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/maya", tags=["alex"])

rate_limit_storage = {}

class ChatRequest(BaseModel):
    message: str
    session_id: str

class ChatResponse(BaseModel):
    reply: str
    remaining_questions: int

def check_rate_limit(session_id: str) -> int:
    """Check remaining questions for session"""
    today = datetime.now().date()
    key = f"{session_id}:{today}"
    
    if key not in rate_limit_storage:
        rate_limit_storage[key] = {"count": 0, "date": today}
    
    if rate_limit_storage[key]["date"] != today:
        rate_limit_storage[key] = {"count": 0, "date": today}
    
    used = rate_limit_storage[key]["count"]
    return max(0, 5 - used)

def increment_usage(session_id: str):
    """Increment usage count"""
    today = datetime.now().date()
    key = f"{session_id}:{today}"
    
    if key not in rate_limit_storage:
        rate_limit_storage[key] = {"count": 0, "date": today}
    
    rate_limit_storage[key]["count"] += 1

@router.post("/chat", response_model=ChatResponse)
async def chat_with_alex(request: ChatRequest):
    """
    Alex AI chat endpoint with RAG - Website chat uses Alex persona
    Alex is the Premium Bar Operations Consultant - more trusted in HoReCa business
    
    Flow:
    1. Check preset answers first (instant, free)
    2. If no preset, use Claude API (costs money)
    """
    try:
        remaining = check_rate_limit(request.session_id)
        
        if remaining <= 0:
            raise HTTPException(
                status_code=429, 
                detail="Ви досягли ліміту безкоштовних питань на сьогодні"
            )
        
        preset_answer = preset_service.get_preset_answer(request.message)
        
        if preset_answer:
            logger.info(f"[PRESET] Served instant answer for: {request.message[:50]}...")
            increment_usage(request.session_id)
            remaining_after = check_rate_limit(request.session_id)
            
            return ChatResponse(
                reply=preset_answer,
                remaining_questions=remaining_after
            )
        
        logger.info(f"[API] Calling Claude for: {request.message[:50]}...")
        
        chat_request = ChatEndpointRequest(
            message=request.message,
            avatar="alex",
            conversation_history=[]
        )
        
        response = await chat_with_avatars(chat_request)
        
        increment_usage(request.session_id)
        
        remaining_after = check_rate_limit(request.session_id)
        
        return ChatResponse(
            reply=response.response,
            remaining_questions=remaining_after
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Alex chat error: {e}")
        raise HTTPException(status_code=500, detail="Вибачте, сталася помилка. Спробуйте ще раз.")


@router.get("/preset-stats")
async def get_preset_stats():
    """Get preset usage statistics"""
    return preset_service.get_stats()


@router.post("/reload-presets")
async def reload_presets():
    """Reload preset answers from file"""
    return preset_service.reload_presets()
