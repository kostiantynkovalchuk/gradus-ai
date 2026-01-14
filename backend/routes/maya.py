from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
import os

from routes.chat_endpoints import chat_with_avatars, ChatRequest as ChatEndpointRequest

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
    """
    try:
        remaining = check_rate_limit(request.session_id)
        
        if remaining <= 0:
            raise HTTPException(
                status_code=429, 
                detail="Ви досягли ліміту безкоштовних питань на сьогодні"
            )
        
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
        print(f"Alex chat error: {e}")
        raise HTTPException(status_code=500, detail="Вибачте, сталася помилка. Спробуйте ще раз.")
