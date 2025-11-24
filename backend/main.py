from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from contextlib import asynccontextmanager
import logging
import threading
import os

from models import get_db, init_db
from models.content import ContentQueue, ApprovalLog
from services.claude_service import claude_service
from services.image_generator import image_generator
from services.social_poster import social_poster
from services.notification_service import notification_service
from services.news_scraper import news_scraper
from services.translation_service import translation_service
from services.facebook_poster import facebook_poster
from services.scheduler import content_scheduler
from services.telegram_webhook import telegram_webhook_handler
from services.api_token_monitor import api_token_monitor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - start/stop scheduler"""
    logger.info("🚀 Starting Gradus Media AI Agent...")
    init_db()
    content_scheduler.start()
    logger.info("✅ Scheduler started - automation enabled!")
    
    yield
    
    logger.info("Shutting down scheduler...")
    content_scheduler.stop()

app = FastAPI(
    title="Gradus Media AI Agent",
    description="Automated content creation and distribution",
    version="1.0.0",
    lifespan=lifespan
)

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

class CreateContentRequest(BaseModel):
    title: str
    content: str
    source: str = "Manual"
    source_url: Optional[str] = None
    language: str = "uk"
    needs_translation: bool = False
    platforms: List[str] = ["facebook", "linkedin"]

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

@app.get("/api/content")
async def get_content(
    status: Optional[str] = None,
    platform: Optional[str] = None,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Get content with optional filters for status and platform"""
    try:
        query = db.query(ContentQueue)
        
        if status:
            query = query.filter(ContentQueue.status == status)
        
        if platform:
            from sqlalchemy import cast, String
            query = query.filter(cast(ContentQueue.platforms, String).like(f'%{platform}%'))
        
        articles = query.order_by(ContentQueue.created_at.desc()).limit(limit).all()
        
        return [
            {
                "id": article.id,
                "title": article.extra_metadata.get("title") if article.extra_metadata else None,
                "translated_title": article.translated_title,
                "status": article.status,
                "platforms": article.platforms,
                "language": article.language,
                "needs_translation": article.needs_translation,
                "created_at": article.created_at.isoformat() if article.created_at else None,
                "source": article.source,
                "image_url": article.image_url,
                "local_image_path": article.local_image_path,
            }
            for article in articles
        ]
    except Exception as e:
        logger.error(f"Error fetching content: {str(e)}")
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
        
        notification_service.notify_content_approved({
            'id': content_id,
            'title': content.translated_title or (content.extra_metadata.get('title', '') if content.extra_metadata else ''),
            'scheduled_time': str(request.scheduled_time) if request.scheduled_time else 'Відразу'
        })
        
        logger.info(f"Content {content_id} approved by {request.moderator}")
        
        fb_result = None
        if "facebook" in [p.lower() for p in request.platforms]:
            post_data = {
                'translated_title': content.translated_title or (content.extra_metadata.get('title', '') if content.extra_metadata else ''),
                'translated_content': content.translated_text or '',
                'url': content.source_url or '',
                'source': content.source or 'The Spirits Business',
                'author': (content.extra_metadata.get('author', '') if content.extra_metadata else ''),
                'image_url': content.image_url,
                'local_image_path': content.local_image_path
            }
            
            fb_result = facebook_poster.post_with_image(post_data)
            
            if fb_result:
                content.status = "posted"
                
                if not content.extra_metadata:
                    content.extra_metadata = {}
                content.extra_metadata['fb_post_id'] = fb_result['post_id']
                content.extra_metadata['fb_post_url'] = fb_result['post_url']
                
                db.commit()
                
                notification_service.notify_content_posted({
                    'id': content_id,
                    'title': post_data['translated_title'],
                    'platforms': ['Facebook'],
                    'fb_post_url': fb_result['post_url'],
                    'posted_at': fb_result['posted_at']
                })
                
                logger.info(f"Content {content_id} posted to Facebook: {fb_result['post_url']}")
        
        if fb_result:
            return {
                "status": "success",
                "message": "Content approved and posted to Facebook",
                "content": content,
                "fb_post_url": fb_result['post_url']
            }
        else:
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

@app.post("/api/content/create")
async def create_content(
    request: CreateContentRequest,
    db: Session = Depends(get_db)
):
    """
    Create Ukrainian content manually (bypasses translation)
    Useful for adding Ukrainian news sources that don't need translation
    """
    try:
        new_content = ContentQueue(
            status='draft',
            source=request.source,
            source_url=request.source_url,
            original_text=request.content,
            language=request.language,
            needs_translation=request.needs_translation,
            platforms=request.platforms,
            extra_metadata={
                'title': request.title,
                'created_via': 'api',
                'created_at': datetime.utcnow().isoformat()
            }
        )
        
        db.add(new_content)
        db.commit()
        db.refresh(new_content)
        
        logger.info(f"Ukrainian content created: ID {new_content.id}, language={request.language}, needs_translation={request.needs_translation}")
        
        return {
            "status": "success",
            "message": "Ukrainian content created successfully",
            "content_id": new_content.id,
            "language": request.language,
            "needs_translation": request.needs_translation,
            "next_steps": "Content will be processed for images and sent for approval"
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating Ukrainian content: {str(e)}")
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
                    original_text=article.get('content', ''),
                    translated_text=None,
                    image_url=article.get('image_url'),
                    platforms=["facebook", "linkedin"],
                    extra_metadata={
                        "title": article.get('title'),
                        "published_date": article.get('published_date'),
                        "author": article.get('author'),
                        "scraped_at": article.get('scraped_at')
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
            article_id,
            article.image_url
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
async def translate_pending_articles(limit: int = 10, db: Session = Depends(get_db)):
    """
    Translate all articles with status='draft' (notifications sent later with images)
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
                "total_draft": 0
            }
        
        logger.info(f"Translating {len(draft_articles)} draft articles...")
        
        translated_count = 0
        
        for article in draft_articles:
            original_text = article.original_text or ''
            
            article_data = {
                'id': article.id,
                'title': article.extra_metadata.get('title', '') if article.extra_metadata else '',
                'content': original_text,
                'summary': original_text[:1000] if original_text else ''
            }
            
            try:
                translation = await claude_service.translate_to_ukrainian(original_text)
                
                if translation:
                    article.translated_title = article_data['title']
                    article.translated_text = translation
                    article.status = 'pending_approval'
                    translated_count += 1
                    logger.info(f"Translated article {article.id}: {article_data['title'][:50]}...")
            except Exception as e:
                logger.error(f"Failed to translate article {article.id}: {e}")
                continue
        
        db.commit()
        
        logger.info(f"Translation completed: {translated_count}/{len(draft_articles)} articles translated")
        
        return {
            "status": "success",
            "translated_count": translated_count,
            "total_draft": len(draft_articles),
            "message": f"Translated {translated_count} articles. Run image generation next to send notifications."
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Batch translation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/images/generate/{article_id}")
async def generate_image_for_article(article_id: int, db: Session = Depends(get_db)):
    """
    Generate image for a specific article
    Updates article with image_url and image_prompt
    """
    try:
        article = db.query(ContentQueue).filter(ContentQueue.id == article_id).first()
        
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        
        article_data = {
            'title': article.extra_metadata.get('title', '') if article.extra_metadata else '',
            'content': article.original_text or article.translated_text or ''
        }
        
        logger.info(f"Generating image for article {article_id}: {article_data['title'][:50]}...")
        
        result = image_generator.generate_article_image(article_data)
        
        if result.get('image_url'):
            article.image_url = result['image_url']
            article.image_prompt = result['prompt']
            article.local_image_path = result.get('local_path', '')
            db.commit()
            
            logger.info(f"Image generated successfully for article {article_id}")
            
            return {
                "status": "success",
                "article_id": article_id,
                "image_url": result['image_url'],
                "prompt": result['prompt']
            }
        else:
            raise HTTPException(status_code=500, detail="Image generation failed")
            
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error generating image: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/images/regenerate/{article_id}")
async def regenerate_image(
    article_id: int,
    db: Session = Depends(get_db)
):
    """
    Regenerate image for article (generates new prompt and new image)
    """
    try:
        article = db.query(ContentQueue).filter(ContentQueue.id == article_id).first()
        
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        
        article_data = {
            'title': article.extra_metadata.get('title', '') if article.extra_metadata else '',
            'content': article.original_text or article.translated_text or ''
        }
        
        logger.info(f"Regenerating image for article {article_id}")
        
        result = image_generator.generate_article_image(article_data)
        
        if result.get('image_url'):
            article.image_url = result['image_url']
            article.image_prompt = result['prompt']
            article.local_image_path = result.get('local_path', '')
            db.commit()
            
            logger.info(f"Image regenerated for article {article_id}")
            
            return {
                "status": "success",
                "article_id": article_id,
                "image_url": result['image_url'],
                "prompt": result['prompt']
            }
        else:
            raise HTTPException(status_code=500, detail="Image regeneration failed")
            
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error regenerating image: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/images/generate-pending")
async def generate_images_for_pending(limit: int = 10, db: Session = Depends(get_db)):
    """
    Generate images AND send Telegram notifications with image previews
    """
    try:
        articles_without_images = db.query(ContentQueue).filter(
            ContentQueue.status == 'pending_approval',
            ContentQueue.image_url == None
        ).limit(limit).all()
        
        if not articles_without_images:
            return {
                "status": "success",
                "message": "No articles need images",
                "generated_count": 0,
                "total_without_images": 0,
                "notifications_sent": 0
            }
        
        logger.info(f"Generating images for {len(articles_without_images)} articles...")
        
        generated_count = 0
        notifications_sent = 0
        
        for article in articles_without_images:
            article_data = {
                'title': article.extra_metadata.get('title', '') if article.extra_metadata else '',
                'content': article.original_text or article.translated_text or ''
            }
            
            try:
                result = image_generator.generate_article_image(article_data)
                
                if result.get('image_url'):
                    article.image_url = result['image_url']
                    article.image_prompt = result['prompt']
                    article.local_image_path = result.get('local_path', '')
                    generated_count += 1
                    
                    logger.info(f"Generated image for article {article.id}")
                    
                    notification_data = {
                        'id': article.id,
                        'title': article.extra_metadata.get('title', '') if article.extra_metadata else '',
                        'translated_text': article.translated_text or article.original_text or '',
                        'image_url': article.image_url,
                        'source': article.source or 'The Spirits Business',
                        'created_at': article.created_at.strftime('%Y-%m-%d %H:%M') if article.created_at else ''
                    }
                    
                    try:
                        notification_service.send_approval_notification(notification_data)
                        notifications_sent += 1
                        logger.info(f"✅ Notification with image sent for article {article.id}")
                    except Exception as notif_error:
                        logger.error(f"Failed to send notification for article {article.id}: {notif_error}")
                        
            except Exception as e:
                logger.error(f"Failed to generate image for article {article.id}: {e}")
                continue
        
        db.commit()
        
        logger.info(f"Image generation completed: {generated_count}/{len(articles_without_images)}, notifications sent: {notifications_sent}")
        
        return {
            "status": "success",
            "generated_count": generated_count,
            "total_without_images": len(articles_without_images),
            "notifications_sent": notifications_sent,
            "message": f"Generated {generated_count} images and sent {notifications_sent} Telegram notifications"
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Batch image generation error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/images/migrate-local-storage")
async def migrate_images_to_local_storage(db: Session = Depends(get_db)):
    """
    Retroactively download existing DALL-E images and save them locally.
    This fixes articles that have image_url but no local_image_path.
    """
    try:
        articles_need_migration = db.query(ContentQueue).filter(
            ContentQueue.image_url != None,
            ContentQueue.local_image_path == None
        ).all()
        
        if not articles_need_migration:
            return {
                "status": "success",
                "message": "No articles need migration",
                "migrated_count": 0
            }
        
        logger.info(f"Migrating {len(articles_need_migration)} images to local storage...")
        
        migrated_count = 0
        failed_count = 0
        
        for article in articles_need_migration:
            try:
                logger.info(f"Downloading image for article {article.id}...")
                local_path = image_generator.download_and_save_image(article.image_url)
                
                if local_path:
                    article.local_image_path = local_path
                    migrated_count += 1
                    logger.info(f"✅ Article {article.id}: Saved to {local_path}")
                else:
                    failed_count += 1
                    logger.warning(f"⚠️ Article {article.id}: Download failed (URL may be expired)")
                    
            except Exception as e:
                failed_count += 1
                logger.error(f"❌ Article {article.id}: Migration error: {e}")
                continue
        
        db.commit()
        
        logger.info(f"Migration completed: {migrated_count} succeeded, {failed_count} failed")
        
        return {
            "status": "success",
            "total_articles": len(articles_need_migration),
            "migrated_count": migrated_count,
            "failed_count": failed_count,
            "message": f"Migrated {migrated_count}/{len(articles_need_migration)} images to local storage"
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Migration error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/facebook/test")
async def test_facebook_connection():
    """Test Facebook API connection"""
    try:
        if facebook_poster.verify_token():
            return {
                "status": "success",
                "message": "Facebook token is valid",
                "page_id": facebook_poster.page_id
            }
        else:
            raise HTTPException(status_code=500, detail="Facebook token invalid")
    except Exception as e:
        logger.error(f"Facebook test error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/facebook/post-test")
async def test_facebook_post():
    """Post a test message to Facebook"""
    try:
        test_data = {
            'translated_title': '🧪 Тестовий пост від Gradus AI',
            'translated_content': 'Це тестовий пост для перевірки інтеграції з Facebook. Система автоматичного постингу працює коректно!',
            'url': 'https://www.thespiritsbusiness.com/',
            'source': 'Gradus AI Bot',
            'author': 'Test System',
            'image_url': None
        }
        
        result = facebook_poster.post_with_image(test_data)
        
        if result:
            return {
                "status": "success",
                "message": "Test post created!",
                "post_url": result['post_url'],
                "post_id": result['post_id']
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to create test post")
    except Exception as e:
        logger.error(f"Facebook post test error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/facebook/token-status")
async def check_facebook_token():
    """Check Facebook token expiration status"""
    from services.facebook_token_manager import facebook_token_manager
    
    status = facebook_token_manager.check_token_expiration()
    
    return status

@app.get("/api/monitor/all")
async def monitor_all_api_services():
    """
    Comprehensive monitoring of all API services
    Returns health status, quotas, and expiration info
    """
    try:
        results = api_token_monitor.check_all_services()
        return results
    except Exception as e:
        logger.error(f"API monitoring error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/monitor/anthropic")
async def monitor_anthropic():
    """Check Claude/Anthropic API status"""
    try:
        result = api_token_monitor.check_anthropic_api()
        return result
    except Exception as e:
        logger.error(f"Anthropic monitoring error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/monitor/openai")
async def monitor_openai():
    """Check OpenAI/DALL-E API status"""
    try:
        result = api_token_monitor.check_openai_api()
        return result
    except Exception as e:
        logger.error(f"OpenAI monitoring error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/monitor/test-alerts")
async def test_monitoring_alerts():
    """
    Manually trigger API monitoring check and send alerts if needed
    Useful for testing notification system
    """
    try:
        results = api_token_monitor.check_all_services()
        
        if not results.get('warnings') and not results.get('errors'):
            api_token_monitor.send_success_notification(results)
        
        return {
            "status": "success",
            "message": "Monitoring check completed",
            "results": results
        }
    except Exception as e:
        logger.error(f"Monitoring test error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/facebook/token-alert")
async def send_token_alert():
    """Manually trigger token expiration alert"""
    from services.facebook_token_manager import facebook_token_manager
    
    status = facebook_token_manager.check_token_expiration()
    
    if status.get('days_remaining'):
        facebook_token_manager.send_expiration_alert(status['days_remaining'])
        return {"status": "success", "message": "Alert sent", "days_remaining": status['days_remaining']}
    
    return {"status": "info", "message": "Token never expires or invalid", "token_status": status}

@app.get("/api/analytics/post/{content_id}")
async def get_post_analytics(content_id: int, db: Session = Depends(get_db)):
    """Get analytics for specific post by content ID"""
    from services.analytics_tracker import analytics_tracker
    
    article = db.query(ContentQueue).filter(ContentQueue.id == content_id).first()
    
    if not article or not article.extra_metadata or 'fb_post_id' not in article.extra_metadata:
        raise HTTPException(status_code=404, detail="Post not found or not posted to Facebook")
    
    post_id = article.extra_metadata['fb_post_id']
    metrics = analytics_tracker.get_post_insights(post_id)
    
    if 'error' not in metrics:
        if not article.extra_metadata:
            article.extra_metadata = {}
        article.extra_metadata['analytics'] = metrics
        db.commit()
    
    return {
        "content_id": content_id,
        "title": article.translated_title or 'Untitled',
        "post_url": article.extra_metadata.get('fb_post_url', ''),
        "metrics": metrics
    }

@app.get("/api/analytics/recent")
async def get_recent_posts_analytics(limit: int = 10):
    """Get performance metrics for recent posts"""
    from services.analytics_tracker import analytics_tracker
    
    results = analytics_tracker.get_recent_posts_performance(limit=limit)
    
    return {
        "posts": results,
        "count": len(results)
    }

@app.get("/api/analytics/insights")
async def get_posting_insights(days: int = 30):
    """Get best posting times and engagement insights"""
    from services.analytics_tracker import analytics_tracker
    
    insights = analytics_tracker.get_best_posting_times(days=days)
    
    return insights

@app.get("/api/scheduler/status")
async def get_scheduler_status():
    """Get scheduler status and upcoming jobs"""
    jobs = content_scheduler.get_jobs()
    
    return {
        "status": "running",
        "scheduler_active": content_scheduler.scheduler.running,
        "jobs": jobs,
        "total_jobs": len(jobs)
    }

@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Telegram webhook endpoint to handle inline button callbacks
    
    Receives updates from Telegram Bot API when users click inline buttons
    
    Security: Set TELEGRAM_WEBHOOK_SECRET environment variable and configure webhook:
    https://api.telegram.org/bot<TOKEN>/setWebhook?url=<URL>&secret_token=<SECRET>
    """
    try:
        telegram_secret = os.getenv('TELEGRAM_WEBHOOK_SECRET')
        if telegram_secret:
            provided_secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
            if provided_secret != telegram_secret:
                logger.warning("Telegram webhook: Invalid or missing secret token")
                raise HTTPException(status_code=403, detail="Forbidden")
        
        payload = await request.json()
        
        if 'callback_query' in payload:
            result = telegram_webhook_handler.handle_callback_query(
                payload['callback_query'],
                db
            )
            return result
        
        return {"status": "ok", "message": "No callback_query found"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Telegram webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/telegram/set-webhook")
async def set_telegram_webhook():
    """
    Set Telegram webhook URL
    Call this once to configure the webhook
    
    Optional: Set TELEGRAM_WEBHOOK_SECRET in Secrets for webhook authentication
    """
    import requests
    
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not bot_token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not configured")
    
    replit_domains = os.getenv('REPLIT_DOMAINS')
    if not replit_domains:
        replit_domains = os.getenv('REPLIT_DEV_DOMAIN')
    
    if not replit_domains:
        raise HTTPException(
            status_code=500, 
            detail="Could not determine app URL. Make sure app is running on Replit."
        )
    
    app_url = f"https://{replit_domains.split(',')[0]}"
    webhook_url = f"{app_url}/api/telegram/webhook"
    
    telegram_secret = os.getenv('TELEGRAM_WEBHOOK_SECRET')
    
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {"url": webhook_url}
    
    if telegram_secret:
        payload["secret_token"] = telegram_secret
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        result = response.json()
        
        if result.get('ok'):
            return {
                "status": "success",
                "message": "Webhook set successfully",
                "webhook_url": webhook_url,
                "secured": bool(telegram_secret),
                "telegram_response": result
            }
        else:
            return {
                "status": "error",
                "message": result.get('description', 'Unknown error'),
                "details": result
            }
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/telegram/webhook-info")
async def get_webhook_info():
    """Get current webhook information from Telegram"""
    import requests
    
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not bot_token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not configured")
    
    url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    
    try:
        response = requests.get(url, timeout=10)
        result = response.json()
        
        if result.get('ok'):
            webhook_info = result.get('result', {})
            return {
                "status": "success",
                "webhook_info": webhook_info,
                "is_configured": bool(webhook_info.get('url')),
                "pending_updates": webhook_info.get('pending_update_count', 0)
            }
        else:
            raise HTTPException(
                status_code=500, 
                detail=result.get('description', 'Failed to get webhook info')
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get webhook info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
