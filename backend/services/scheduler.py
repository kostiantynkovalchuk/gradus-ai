from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import logging
from services.news_scraper import news_scraper
from services.translation_service import translation_service
from services.image_generator import image_generator
from services.notification_service import notification_service
from models import SessionLocal
from models.content import ContentQueue

logger = logging.getLogger(__name__)

class ContentScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
    
    def scrape_news_task(self):
        """
        Task: Scrape news every 6 hours
        Runs at: 00:00, 06:00, 12:00, 18:00
        """
        logger.info("🤖 [SCHEDULER] Starting news scraping task...")
        
        try:
            articles = news_scraper.scrape_spirits_business(limit=5)
            
            if not articles:
                logger.warning("[SCHEDULER] No new articles found")
                return
            
            with SessionLocal() as db:
                new_count = 0
                
                for article in articles:
                    try:
                        existing = db.query(ContentQueue).filter(
                            ContentQueue.source_url == article.get('url')
                        ).first()
                        
                        if not existing:
                            new_article = ContentQueue(
                                status='draft',
                                source='The Spirits Business',
                                source_url=article.get('url'),
                                original_text=article.get('content', ''),
                                platforms=['facebook', 'linkedin'],
                                extra_metadata={
                                    'title': article.get('title'),
                                    'published_date': article.get('published_date'),
                                    'author': article.get('author'),
                                    'scraped_at': article.get('scraped_at')
                                }
                            )
                            db.add(new_article)
                            new_count += 1
                    except Exception as e:
                        logger.error(f"[SCHEDULER] Error processing article: {e}")
                        db.rollback()
                        continue
                
                db.commit()
                logger.info(f"✅ [SCHEDULER] Scraped {new_count} new articles")
            
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Scraping failed: {e}")
    
    def translate_pending_task(self):
        """
        Task: Translate draft articles every hour
        Runs at: Every hour at :15 (00:15, 01:15, etc.)
        """
        logger.info("🤖 [SCHEDULER] Starting translation task...")
        
        try:
            with SessionLocal() as db:
                draft_articles = db.query(ContentQueue).filter(
                    ContentQueue.status == 'draft',
                    ContentQueue.translated_text == None
                ).limit(5).all()
                
                if not draft_articles:
                    logger.info("[SCHEDULER] No articles to translate")
                    return
                
                translated_count = 0
                
                for article in draft_articles:
                    try:
                        article_data = {
                            'id': article.id,
                            'title': article.extra_metadata.get('title', '') if article.extra_metadata else '',
                            'content': article.original_text,
                            'summary': article.original_text[:1000] if article.original_text else ''
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
                    except Exception as e:
                        logger.error(f"[SCHEDULER] Error translating article {article.id}: {e}")
                        db.rollback()
                        continue
                
                db.commit()
                logger.info(f"✅ [SCHEDULER] Translated {translated_count} articles")
            
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Translation failed: {e}")
    
    def generate_images_task(self):
        """
        Task: Generate images for articles without images
        Runs at: Every hour at :30 (00:30, 01:30, etc.)
        """
        logger.info("🤖 [SCHEDULER] Starting image generation task...")
        
        try:
            with SessionLocal() as db:
                articles_without_images = db.query(ContentQueue).filter(
                    ContentQueue.status == 'pending_approval',
                    ContentQueue.image_url == None
                ).limit(5).all()
                
                if not articles_without_images:
                    logger.info("[SCHEDULER] No articles need images")
                    return
                
                generated_count = 0
                
                for article in articles_without_images:
                    try:
                        article_data = {
                            'title': article.extra_metadata.get('title', '') if article.extra_metadata else '',
                            'content': article.original_text or article.translated_text or ''
                        }
                        
                        result = image_generator.generate_article_image(article_data)
                        
                        if result.get('image_url'):
                            article.image_url = result['image_url']
                            article.image_prompt = result['prompt']
                            generated_count += 1
                    except Exception as e:
                        logger.error(f"[SCHEDULER] Error generating image for article {article.id}: {e}")
                        db.rollback()
                        continue
                
                db.commit()
                logger.info(f"✅ [SCHEDULER] Generated {generated_count} images")
            
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Image generation failed: {e}")
    
    def cleanup_old_content_task(self):
        """
        Task: Clean up old rejected content
        Runs at: 03:00 AM daily
        """
        logger.info("🤖 [SCHEDULER] Starting cleanup task...")
        
        try:
            with SessionLocal() as db:
                cutoff_date = datetime.utcnow() - timedelta(days=30)
                
                deleted = db.query(ContentQueue).filter(
                    ContentQueue.status == 'rejected',
                    ContentQueue.created_at < cutoff_date
                ).delete()
                
                db.commit()
                logger.info(f"✅ [SCHEDULER] Cleaned up {deleted} old articles")
            
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Cleanup failed: {e}")
    
    def start(self):
        """Start the scheduler with all tasks (idempotent)"""
        if self.scheduler.running:
            logger.info("Scheduler already running, skipping start")
            return
        
        try:
            self.scheduler.add_job(
                self.scrape_news_task,
                CronTrigger(hour='0,6,12,18', minute=0),
                id='scrape_news',
                name='Scrape news articles',
                replace_existing=True
            )
        except:
            logger.info("Scheduler was shutdown, recreating...")
            self.scheduler = BackgroundScheduler()
            self.scheduler.add_job(
                self.scrape_news_task,
                CronTrigger(hour='0,6,12,18', minute=0),
                id='scrape_news',
                name='Scrape news articles',
                replace_existing=True
            )
        
        self.scheduler.add_job(
            self.translate_pending_task,
            CronTrigger(minute=15),
            id='translate_articles',
            name='Translate pending articles',
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self.generate_images_task,
            CronTrigger(minute=30),
            id='generate_images',
            name='Generate article images',
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self.cleanup_old_content_task,
            CronTrigger(hour=3, minute=0),
            id='cleanup_old_content',
            name='Cleanup old rejected content',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info("✅ Scheduler started with 4 automated tasks")
        logger.info("📅 Next scrape: 00:00, 06:00, 12:00, 18:00")
        logger.info("🔄 Translation: Every hour at :15")
        logger.info("🎨 Images: Every hour at :30")
        logger.info("🗑️  Cleanup: Daily at 03:00")
    
    def stop(self):
        """Stop the scheduler (idempotent)"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler stopped")
        else:
            logger.info("Scheduler already stopped")
    
    def get_jobs(self):
        """Get list of scheduled jobs"""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
                'trigger': str(job.trigger)
            })
        return jobs

content_scheduler = ContentScheduler()
