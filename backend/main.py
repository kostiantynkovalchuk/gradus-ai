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
                'image_url': content.image_url
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
                article.id,
                article.image_url
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
async def generate_images_for_pending(limit: int = 5, db: Session = Depends(get_db)):
    """
    Generate images for all articles that don't have one yet
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
                "generated_count": 0
            }
        
        logger.info(f"Generating images for {len(articles_without_images)} articles...")
        
        generated_count = 0
        
        for article in articles_without_images:
            article_data = {
                'title': article.extra_metadata.get('title', '') if article.extra_metadata else '',
                'content': article.original_text or article.translated_text or ''
            }
            
            result = image_generator.generate_article_image(article_data)
            
            if result.get('image_url'):
                article.image_url = result['image_url']
                article.image_prompt = result['prompt']
                generated_count += 1
                logger.info(f"Generated image for article {article.id}")
        
        db.commit()
        
        logger.info(f"Image generation completed: {generated_count}/{len(articles_without_images)}")
        
        return {
            "status": "success",
            "generated_count": generated_count,
            "total_without_images": len(articles_without_images)
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Batch image generation error: {str(e)}")
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
