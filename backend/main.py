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
from services.news_scraper import news_scraper
from services.translation_service import translation_service

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

@app.post("/api/test/telegram")
async def test_telegram():
    """Test Telegram notification"""
    result = notification_service.send_test_notification()
    return result

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

@app.post("/api/scraper/test")
async def test_scraper():
    """Test the news scraper with 1 article"""
    try:
        logger.info("Testing news scraper with 1 article...")
        articles = news_scraper.scrape_spirits_business(limit=1)
        
        return {
            "success": True,
            "message": f"Successfully scraped {len(articles)} article(s)",
            "articles": articles
        }
    except Exception as e:
        logger.error(f"Scraper test error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/scraper/run")
async def run_scraper(limit: int = 5, db: Session = Depends(get_db)):
    """
    Manually trigger the news scraper.
    Scrapes articles and adds them to the content queue for approval.
    """
    try:
        logger.info(f"Running news scraper (limit: {limit})...")
        
        articles = news_scraper.scrape_spirits_business(limit=limit)
        
        created_count = 0
        for article in articles:
            try:
                existing = db.query(ContentQueue).filter(
                    ContentQueue.source_url == article['url']
                ).first()
                
                if existing:
                    logger.info(f"Article already exists: {article['title'][:50]}...")
                    continue
                
                content_entry = ContentQueue(
                    status="draft",
                    source="The Spirits Business",
                    source_url=article['url'],
                    original_text=article['excerpt'],
                    translated_text=None,
                    image_url=None,
                    platforms=["facebook", "linkedin"],
                    extra_metadata={
                        "title": article['title'],
                        "date": article['date'],
                        "author": article['author'],
                        "scraped_at": article['scraped_at']
                    }
                )
                
                db.add(content_entry)
                created_count += 1
                
            except Exception as e:
                logger.error(f"Error saving article: {str(e)}")
                continue
        
        db.commit()
        
        logger.info(f"Scraper completed: {len(articles)} scraped, {created_count} new articles added")
        
        return {
            "success": True,
            "message": f"Scraper completed successfully",
            "scraped": len(articles),
            "new_articles": created_count,
            "articles": articles
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Scraper error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/translate/article/{article_id}")
async def translate_article_endpoint(article_id: int, db: Session = Depends(get_db)):
    """
    Translate a single article by ID and send Telegram notification
    Updates the article's translated_text and status
    """
    try:
        article = db.query(ContentQueue).filter(ContentQueue.id == article_id).first()
        
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        
        original_text = article.original_text or ''
        
        article_data = {
            'id': article_id,
            'title': article.extra_metadata.get('title', '') if article.extra_metadata else '',
            'content': original_text,
            'summary': original_text[:1000] if original_text else ''
        }
        
        logger.info(f"Translating article {article_id}: {article_data['title'][:50]}...")
        
        translation, notification_sent = translation_service.translate_article_with_notification(
            article_data,
            article_id
        )
        
        if translation and translation.get('title') and translation.get('content'):
            article.translated_title = translation['title']
            article.translated_text = translation['content']
            article.status = 'pending_approval'
            db.commit()
            
            logger.info(f"Article {article_id} translated successfully")
            
            return {
                "status": "success",
                "article_id": article_id,
                "notification_sent": notification_sent,
                "translated_title": translation['title'],
                "translated_content_length": len(translation['content']),
                "preview": translation['content'][:200] + "..."
            }
        else:
            raise HTTPException(status_code=500, detail="Translation failed")
            
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Translation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/translate/pending")
async def translate_pending_articles(limit: int = 5, db: Session = Depends(get_db)):
    """
    Translate all articles with status='draft' and send Telegram notifications
    """
    try:
        draft_articles = db.query(ContentQueue).filter(
            ContentQueue.status == 'draft',
            ContentQueue.translated_text == None
        ).limit(limit).all()
        
        if not draft_articles:
            return {
                "status": "success",
                "message": "No articles to translate",
                "translated_count": 0,
                "total_draft": 0,
                "notifications_sent": 0
            }
        
        logger.info(f"Translating {len(draft_articles)} draft articles...")
        
        translated_count = 0
        notifications_sent = 0
        
        for article in draft_articles:
            original_text = article.original_text or ''
            
            article_data = {
                'id': article.id,
                'title': article.extra_metadata.get('title', '') if article.extra_metadata else '',
                'content': original_text,
                'summary': original_text[:1000] if original_text else ''
            }
            
            translation, notification_sent = translation_service.translate_article_with_notification(
                article_data,
                article.id
            )
            
            if translation and translation.get('title') and translation.get('content'):
                article.translated_title = translation['title']
                article.translated_text = translation['content']
                article.status = 'pending_approval'
                translated_count += 1
                if notification_sent:
                    notifications_sent += 1
                logger.info(f"Translated article {article.id}: {article_data['title'][:50]}...")
        
        db.commit()
        
        logger.info(f"Translation completed: {translated_count}/{len(draft_articles)} articles translated")
        
        return {
            "status": "success",
            "translated_count": translated_count,
            "total_draft": len(draft_articles),
            "notifications_sent": notifications_sent
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Batch translation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
