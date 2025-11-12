from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import logging

from models import get_db, init_db
from models.content import ContentQueue, ApprovalLog
from services.claude_service import claude_service
from services.image_generator import image_generator
from services.social_poster import social_poster
from services.notification_service import notification_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Gradus Media AI Agent")

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.warning(f"Database initialization deferred: {str(e)}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    system_prompt: Optional[str] = None

class TranslateRequest(BaseModel):
    text: str

class ApproveRequest(BaseModel):
    moderator: str
    scheduled_time: Optional[datetime] = None
    platforms: List[str] = ["facebook", "linkedin"]

class RejectRequest(BaseModel):
    moderator: str
    reason: str

class EditRequest(BaseModel):
    translated_text: Optional[str] = None
    image_prompt: Optional[str] = None
    platforms: Optional[List[str]] = None

@app.get("/")
async def root():
    return {
        "message": "Gradus Media AI Agent API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "chat": "/chat",
            "translate": "/translate",
            "content": "/api/content/*"
        }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "services": {
            "claude": "configured",
            "database": "connected",
            "image_generator": "ready",
            "social_poster": "awaiting credentials"
        }
    }

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        response = await claude_service.chat(request.message, request.system_prompt)
        return {"response": response}
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/translate")
async def translate(request: TranslateRequest):
    try:
        translation = await claude_service.translate_to_ukrainian(request.text)
        return {"translation": translation}
    except Exception as e:
        logger.error(f"Translation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/content/pending")
async def get_pending_content(db: Session = Depends(get_db)):
    try:
        content = db.query(ContentQueue).filter(
            ContentQueue.status == "pending_approval"
        ).order_by(ContentQueue.created_at.desc()).all()
        return content
    except Exception as e:
        logger.error(f"Error fetching pending content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/content/history")
async def get_content_history(
    limit: int = 50,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        query = db.query(ContentQueue)
        
        if status:
            query = query.filter(ContentQueue.status == status)
        
        content = query.order_by(ContentQueue.created_at.desc()).limit(limit).all()
        return content
    except Exception as e:
        logger.error(f"Error fetching content history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/content/{content_id}/approve")
async def approve_content(
    content_id: int,
    request: ApproveRequest,
    db: Session = Depends(get_db)
):
    try:
        content = db.query(ContentQueue).filter(ContentQueue.id == content_id).first()
        
        if not content:
            raise HTTPException(status_code=404, detail="Content not found")
        
        if content.status != "pending_approval":
            raise HTTPException(status_code=400, detail="Content is not pending approval")
        
        content.status = "approved"
        content.reviewed_at = datetime.utcnow()
        content.reviewed_by = request.moderator
        content.scheduled_post_time = request.scheduled_time or datetime.utcnow()
        content.platforms = request.platforms
        
        log_entry = ApprovalLog(
            content_id=content_id,
            action="approved",
            moderator=request.moderator,
            details={"platforms": request.platforms, "scheduled_time": str(request.scheduled_time)}
        )
        
        db.add(log_entry)
        db.commit()
        db.refresh(content)
        
        await notification_service.notify_content_approved(content_id, request.moderator)
        
        logger.info(f"Content {content_id} approved by {request.moderator}")
        
        return {"message": "Content approved successfully", "content": content}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error approving content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/content/{content_id}/reject")
async def reject_content(
    content_id: int,
    request: RejectRequest,
    db: Session = Depends(get_db)
):
    try:
        content = db.query(ContentQueue).filter(ContentQueue.id == content_id).first()
        
        if not content:
            raise HTTPException(status_code=404, detail="Content not found")
        
        content.status = "rejected"
        content.reviewed_at = datetime.utcnow()
        content.reviewed_by = request.moderator
        content.rejection_reason = request.reason
        
        log_entry = ApprovalLog(
            content_id=content_id,
            action="rejected",
            moderator=request.moderator,
            details={"reason": request.reason}
        )
        
        db.add(log_entry)
        db.commit()
        db.refresh(content)
        
        logger.info(f"Content {content_id} rejected by {request.moderator}")
        
        return {"message": "Content rejected successfully", "content": content}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error rejecting content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/content/{content_id}/edit")
async def edit_content(
    content_id: int,
    request: EditRequest,
    db: Session = Depends(get_db)
):
    try:
        content = db.query(ContentQueue).filter(ContentQueue.id == content_id).first()
        
        if not content:
            raise HTTPException(status_code=404, detail="Content not found")
        
        changes = {}
        
        if request.translated_text:
            old_translation = content.translated_text
            content.translated_text = request.translated_text
            changes["translated_text"] = {"old": old_translation, "new": request.translated_text}
        
        if request.image_prompt:
            new_image_url = await image_generator.generate_image(request.image_prompt)
            old_image = content.image_url
            content.image_url = new_image_url
            content.image_prompt = request.image_prompt
            changes["image"] = {"old": old_image, "new": new_image_url}
        
        if request.platforms:
            old_platforms = content.platforms
            content.platforms = request.platforms
            changes["platforms"] = {"old": old_platforms, "new": request.platforms}
        
        if content.edit_history:
            content.edit_history.append({
                "timestamp": datetime.utcnow().isoformat(),
                "changes": changes
            })
        else:
            content.edit_history = [{
                "timestamp": datetime.utcnow().isoformat(),
                "changes": changes
            }]
        
        log_entry = ApprovalLog(
            content_id=content_id,
            action="edited",
            moderator="system",
            details=changes
        )
        
        db.add(log_entry)
        db.commit()
        db.refresh(content)
        
        logger.info(f"Content {content_id} edited")
        
        return {"message": "Content updated successfully", "content": content}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error editing content: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/content/stats")
async def get_stats(db: Session = Depends(get_db)):
    try:
        pending = db.query(ContentQueue).filter(ContentQueue.status == "pending_approval").count()
        approved = db.query(ContentQueue).filter(ContentQueue.status == "approved").count()
        posted = db.query(ContentQueue).filter(ContentQueue.status == "posted").count()
        rejected = db.query(ContentQueue).filter(ContentQueue.status == "rejected").count()
        
        return {
            "pending": pending,
            "approved": approved,
            "posted": posted,
            "rejected": rejected
        }
    except Exception as e:
        logger.error(f"Error fetching stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
