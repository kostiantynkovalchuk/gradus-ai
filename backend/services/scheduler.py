from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import logging
from services.news_scraper import news_scraper
from services.translation_service import translation_service
from models.content import ContentQueue

logger = logging.getLogger(__name__)

class ContentScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
    
    def _get_db_session(self):
        """
        Get a properly initialized database session for scheduler tasks.
        This ensures SessionLocal is initialized even in background threads.
        """
        import models
        
        # Ensure database is initialized (handles background thread case)
        if models.SessionLocal is None:
            models.init_db()
        
        return models.SessionLocal()
    
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
            
            db = self._get_db_session()
            try:
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
            finally:
                db.close()
            
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Scraping failed: {e}")
    
    def translate_pending_task(self):
        """
        Task: Translate draft articles every hour (notifications sent later with images)
        Runs at: Every hour at :15 (00:15, 01:15, etc.)
        """
        logger.info("🤖 [SCHEDULER] Starting translation task...")
        
        try:
            db = self._get_db_session()
            try:
                draft_articles = db.query(ContentQueue).filter(
                    ContentQueue.status == 'draft',
                    ContentQueue.translated_text == None
                ).limit(10).all()
                
                if not draft_articles:
                    logger.info("[SCHEDULER] No articles to translate")
                    return
                
                translated_count = 0
                
                for article in draft_articles:
                    try:
                        article_data = {
                            'title': article.extra_metadata.get('title', '') if article.extra_metadata else '',
                            'content': article.original_text
                        }
                        
                        translation = translation_service.translate_article(article_data)
                        
                        if translation and translation.get('title') and translation.get('content'):
                            article.translated_title = translation['title']
                            article.translated_text = translation['content']
                            article.status = 'pending_approval'
                            translated_count += 1
                            logger.info(f"[SCHEDULER] Translated article {article.id}: {article_data['title'][:50]}...")
                    except Exception as e:
                        logger.error(f"[SCHEDULER] Error translating article {article.id}: {e}")
                        db.rollback()
                        continue
                
                db.commit()
                logger.info(f"✅ [SCHEDULER] Translated {translated_count} articles (notifications will be sent with images)")
            finally:
                db.close()
            
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Translation failed: {e}")
    
    def generate_images_task(self):
        """
        Task: Generate images AND send Telegram notifications with image previews
        Runs at: Every hour at :30 (00:30, 01:30, etc.)
        """
        logger.info("🤖 [SCHEDULER] Starting image generation task...")
        
        try:
            # Import services inside function to avoid circular imports
            from services.image_generator import image_generator
            from services.notification_service import notification_service
            
            db = self._get_db_session()
            try:
                articles_without_images = db.query(ContentQueue).filter(
                    ContentQueue.status == 'pending_approval',
                    ContentQueue.image_url == None
                ).limit(10).all()
                
                if not articles_without_images:
                    logger.info("[SCHEDULER] No articles need images")
                    return
                
                generated_count = 0
                notifications_sent = 0
                
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
                            article.local_image_path = result.get('local_path', '')
                            generated_count += 1
                            
                            logger.info(f"[SCHEDULER] Generated image for article {article.id}")
                            
                            notification_data = {
                                'id': article.id,
                                'translated_title': article.translated_title,
                                'translated_text': article.translated_text or article.original_text or '',
                                'image_url': article.image_url,
                                'source': article.source or 'The Spirits Business',
                                'created_at': article.created_at.strftime('%Y-%m-%d %H:%M') if article.created_at else ''
                            }
                            
                            try:
                                notification_service.send_approval_notification(notification_data)
                                notifications_sent += 1
                                logger.info(f"✅ [SCHEDULER] Notification with image sent for article {article.id}")
                            except Exception as notif_error:
                                logger.error(f"[SCHEDULER] Failed to send notification for article {article.id}: {notif_error}")
                            
                    except Exception as e:
                        logger.error(f"[SCHEDULER] Error generating image for article {article.id}: {e}")
                        db.rollback()
                        continue
                
                db.commit()
                logger.info(f"✅ [SCHEDULER] Generated {generated_count} images, sent {notifications_sent} notifications")
            finally:
                db.close()
            
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Image generation failed: {e}")
    
    def cleanup_old_content_task(self):
        """
        Task: Clean up old rejected content
        Runs at: 03:00 AM daily
        """
        logger.info("🤖 [SCHEDULER] Starting cleanup task...")
        
        try:
            db = self._get_db_session()
            try:
                cutoff_date = datetime.utcnow() - timedelta(days=30)
                
                deleted = db.query(ContentQueue).filter(
                    ContentQueue.status == 'rejected',
                    ContentQueue.created_at < cutoff_date
                ).delete()
                
                db.commit()
                logger.info(f"✅ [SCHEDULER] Cleaned up {deleted} old articles")
            finally:
                db.close()
            
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Cleanup failed: {e}")
    
    def check_api_services_task(self):
        """
        Task: Comprehensive API monitoring - Check all services
        Runs at: 09:00 daily
        """
        logger.info("🤖 [SCHEDULER] Checking all API services...")
        
        try:
            from services.api_token_monitor import api_token_monitor
            
            results = api_token_monitor.check_all_services()
            
            services = results.get('services', {})
            warnings = results.get('warnings', [])
            errors = results.get('errors', [])
            
            healthy_count = sum(1 for s in services.values() if s.get('status') == 'healthy')
            total_count = len(services)
            
            logger.info(f"✅ [SCHEDULER] API Monitor: {healthy_count}/{total_count} services healthy")
            
            if errors:
                logger.error(f"❌ {len(errors)} service(s) with errors:")
                for error in errors:
                    logger.error(f"  • {error['service']}: {error['message']}")
            
            if warnings:
                logger.warning(f"⚠️ {len(warnings)} service(s) with warnings:")
                for warning in warnings:
                    logger.warning(f"  • {warning['service']}: {warning['message']}")
            
            if not warnings and not errors:
                logger.info("✅ All API services operational")
                
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] API monitoring failed: {e}")
    
    def post_to_facebook_task(self):
        """
        Post approved content to Facebook at scheduled time
        Runs: Every day at 6:00 PM
        Posts oldest approved content (FIFO queue)
        """
        logger.info("🤖 [SCHEDULER] Facebook scheduled posting...")
        
        try:
            from services.facebook_poster import facebook_poster
            from services.notification_service import notification_service
            
            db = self._get_db_session()
            try:
                article = db.query(ContentQueue).filter(
                    ContentQueue.status == 'approved'
                ).order_by(ContentQueue.created_at.asc()).first()
                
                if not article:
                    logger.info("[SCHEDULER] No approved content to post to Facebook")
                    return
                
                post_data = {
                    'translated_title': article.translated_title or '',
                    'translated_content': article.translated_text or '',
                    'url': article.source_url or '',
                    'source': article.source or 'The Spirits Business',
                    'author': article.extra_metadata.get('author', '') if article.extra_metadata else '',
                    'image_url': article.image_url,
                    'local_image_path': article.local_image_path
                }
                
                result = facebook_poster.post_with_image(post_data)
                
                if result:
                    article.status = 'posted'
                    article.posted_at = datetime.utcnow()
                    
                    if not article.extra_metadata:
                        article.extra_metadata = {}
                    article.extra_metadata['fb_post_id'] = result['post_id']
                    article.extra_metadata['fb_post_url'] = result['post_url']
                    article.extra_metadata['posted_platform'] = 'facebook'
                    
                    db.commit()
                    
                    logger.info(f"✅ [SCHEDULER] Posted to Facebook: Article {article.id}")
                    
                    title = article.translated_title or 'No title'
                    message = f"""📢 <b>Опубліковано!</b>

📱 <b>Платформа:</b> Facebook

📰 <b>{title}</b>

🔗 <a href="{result['post_url']}">Переглянути пост</a>

✅ Автоматична публікація за розкладом
🆔 ID: {article.id}
🕐 {datetime.utcnow().strftime('%H:%M, %d %b %Y')}"""
                    
                    notification_service.send_custom_notification(message)
                    
                else:
                    logger.error(f"❌ [SCHEDULER] Facebook posting failed for article {article.id}")
                    
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Facebook posting task failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def post_to_linkedin_task(self):
        """
        Post approved content to LinkedIn at scheduled time
        Runs: Mon/Wed/Fri at 9:00 AM
        Posts oldest approved content (FIFO queue)
        """
        logger.info("🤖 [SCHEDULER] LinkedIn scheduled posting...")
        
        try:
            from services.linkedin_poster import linkedin_poster
            from services.notification_service import notification_service
            
            db = self._get_db_session()
            try:
                article = db.query(ContentQueue).filter(
                    ContentQueue.status == 'approved'
                ).order_by(ContentQueue.created_at.asc()).first()
                
                if not article:
                    logger.info("[SCHEDULER] No approved content to post to LinkedIn")
                    return
                
                post_data = {
                    'title': article.translated_title or '',
                    'text': article.translated_text or '',
                    'source': article.source or 'The Spirits Business',
                    'source_url': article.source_url or '',
                    'image_url': article.image_url
                }
                
                result = linkedin_poster.post_to_linkedin(post_data)
                
                if result.get('status') == 'success':
                    article.status = 'posted'
                    article.posted_at = datetime.utcnow()
                    
                    if not article.extra_metadata:
                        article.extra_metadata = {}
                    article.extra_metadata['linkedin_post_id'] = result.get('post_id', '')
                    article.extra_metadata['linkedin_post_url'] = result.get('post_url', '')
                    article.extra_metadata['posted_platform'] = 'linkedin'
                    
                    db.commit()
                    
                    logger.info(f"✅ [SCHEDULER] Posted to LinkedIn: Article {article.id}")
                    
                    title = article.translated_title or 'No title'
                    post_url = result.get('post_url', '')
                    
                    message = f"""📢 <b>Опубліковано!</b>

💼 <b>Платформа:</b> LinkedIn

📰 <b>{title}</b>

🔗 <a href="{post_url}">Переглянути пост</a>

✅ Автоматична публікація за розкладом
🆔 ID: {article.id}
🕐 {datetime.utcnow().strftime('%H:%M, %d %b %Y')}"""
                    
                    notification_service.send_custom_notification(message)
                    
                else:
                    logger.error(f"❌ [SCHEDULER] LinkedIn posting failed: {result.get('message', 'Unknown error')}")
                    
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] LinkedIn posting task failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
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
        
        self.scheduler.add_job(
            self.check_api_services_task,
            CronTrigger(hour=9, minute=0),
            id='check_api_services',
            name='Check all API services',
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self.post_to_facebook_task,
            CronTrigger(hour=18, minute=0),
            id='post_facebook',
            name='Post to Facebook (scheduled)',
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self.post_to_linkedin_task,
            CronTrigger(day_of_week='mon,wed,fri', hour=9, minute=0),
            id='post_linkedin',
            name='Post to LinkedIn (scheduled)',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info("✅ Scheduler started with 7 automated tasks")
        logger.info("📅 Next scrape: 00:00, 06:00, 12:00, 18:00")
        logger.info("🔄 Translation: Every hour at :15")
        logger.info("🎨 Images: Every hour at :30")
        logger.info("🗑️  Cleanup: Daily at 03:00")
        logger.info("🔐 API Monitor: Daily at 09:00")
        logger.info("📱 Facebook posting: Daily at 18:00 (6 PM)")
        logger.info("💼 LinkedIn posting: Mon/Wed/Fri at 09:00")
    
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
