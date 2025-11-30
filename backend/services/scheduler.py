from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from datetime import datetime, timedelta
import logging
import os
from services.news_scraper import news_scraper
from services.translation_service import translation_service
from models.content import ContentQueue

logger = logging.getLogger(__name__)

class ContentScheduler:
    def __init__(self):
        # Use PostgreSQL for persistent job storage
        database_url = os.environ.get('DATABASE_URL', '')
        
        jobstores = {}
        if database_url:
            try:
                jobstores['default'] = SQLAlchemyJobStore(url=database_url)
                logger.info("Using PostgreSQL job store for scheduler persistence")
            except Exception as e:
                logger.warning(f"Failed to create SQLAlchemy job store: {e}, using memory store")
        
        executors = {
            'default': ThreadPoolExecutor(5)
        }
        
        job_defaults = {
            'coalesce': True,  # Combine multiple missed runs into one
            'max_instances': 1,
            'misfire_grace_time': 3600 * 6  # 6 hours grace period for missed jobs
        }
        
        self.scheduler = BackgroundScheduler(
            jobstores=jobstores if jobstores else None,
            executors=executors,
            job_defaults=job_defaults
        )
    
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
    
    def scrape_linkedin_sources_task(self):
        """
        Scrape LinkedIn sources: The Spirits Business, Drinks International
        Runs: Mon/Wed/Fri at 1:00 AM
        
        Professional, business-oriented sources for B2B audience
        """
        logger.info("🤖 [SCHEDULER] Scraping LinkedIn sources...")
        
        try:
            from services.scrapers.manager import scraper_manager
            
            # LinkedIn sources - professional content
            linkedin_sources = ['spirits_business', 'drinks_international']
            
            db = self._get_db_session()
            try:
                # Get existing URLs for deduplication
                existing_urls = set(
                    url[0] for url in db.query(ContentQueue.source_url).filter(
                        ContentQueue.source_url.isnot(None)
                    ).all()
                )
                
                existing_hashes = set(
                    meta.get('content_hash', '') 
                    for meta in db.query(ContentQueue.extra_metadata).filter(
                        ContentQueue.extra_metadata.isnot(None)
                    ).all()
                    if meta and meta.get('content_hash')
                )
                
                total_new = 0
                
                for source_name in linkedin_sources:
                    try:
                        articles = scraper_manager.scrape_source(source_name, limit=3)
                        logger.info(f"  📊 {source_name}: {len(articles)} articles scraped")
                        
                        for article in articles:
                            if scraper_manager.check_duplicate(article, existing_urls, existing_hashes):
                                logger.info(f"    ⏭️  Duplicate skipped: {article.title[:50]}...")
                                continue
                            
                            content_hash = article.get_content_hash()
                            new_article = ContentQueue(
                                status='draft',
                                source=article.source_name,
                                source_url=article.url,
                                original_text=article.content,
                                language=article.language,
                                needs_translation=article.needs_translation,
                                platforms=['linkedin'],
                                extra_metadata={
                                    'title': article.title,
                                    'published_date': article.published_at,
                                    'author': article.author,
                                    'content_hash': content_hash,
                                    'scraped_at': datetime.utcnow().isoformat()
                                }
                            )
                            db.add(new_article)
                            total_new += 1
                            
                            existing_urls.add(article.url)
                            existing_hashes.add(content_hash)
                            
                            lang_emoji = "🇺🇦" if article.language == 'uk' else "🇬🇧"
                            logger.info(f"    ✅ {lang_emoji} {article.title[:50]}...")
                    
                    except Exception as e:
                        logger.error(f"  ❌ {source_name} failed: {e}")
                        continue
                
                db.commit()
                logger.info(f"✅ [SCHEDULER] LinkedIn: Scraped {total_new} new articles")
                
            finally:
                db.close()
        
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] LinkedIn scraping failed: {e}")
    
    def scrape_facebook_sources_task(self):
        """
        Scrape Facebook sources: Delo.ua, HoReCa-Ukraine, Just Drinks
        Runs: Every day at 2:00 AM
        
        Mix of Ukrainian and English sources for general audience
        """
        logger.info("🤖 [SCHEDULER] Scraping Facebook sources...")
        
        try:
            from services.scrapers.manager import scraper_manager
            
            # Facebook sources - 2 Ukrainian + 1 English
            facebook_sources = ['delo_ua', 'restorator_ua', 'just_drinks']
            
            db = self._get_db_session()
            try:
                # Get existing URLs for deduplication
                existing_urls = set(
                    url[0] for url in db.query(ContentQueue.source_url).filter(
                        ContentQueue.source_url.isnot(None)
                    ).all()
                )
                
                existing_hashes = set(
                    meta.get('content_hash', '') 
                    for meta in db.query(ContentQueue.extra_metadata).filter(
                        ContentQueue.extra_metadata.isnot(None)
                    ).all()
                    if meta and meta.get('content_hash')
                )
                
                total_new = 0
                
                for source_name in facebook_sources:
                    try:
                        articles = scraper_manager.scrape_source(source_name, limit=3)
                        logger.info(f"  📊 {source_name}: {len(articles)} articles scraped")
                        
                        for article in articles:
                            if scraper_manager.check_duplicate(article, existing_urls, existing_hashes):
                                logger.info(f"    ⏭️  Duplicate skipped: {article.title[:50]}...")
                                continue
                            
                            content_hash = article.get_content_hash()
                            new_article = ContentQueue(
                                status='draft',
                                source=article.source_name,
                                source_url=article.url,
                                original_text=article.content,
                                language=article.language,
                                needs_translation=article.needs_translation,
                                platforms=['facebook'],
                                extra_metadata={
                                    'title': article.title,
                                    'published_date': article.published_at,
                                    'author': article.author,
                                    'content_hash': content_hash,
                                    'scraped_at': datetime.utcnow().isoformat()
                                }
                            )
                            db.add(new_article)
                            total_new += 1
                            
                            existing_urls.add(article.url)
                            existing_hashes.add(content_hash)
                            
                            lang_emoji = "🇺🇦" if article.language == 'uk' else "🇬🇧"
                            logger.info(f"    ✅ {lang_emoji} {article.title[:50]}...")
                    
                    except Exception as e:
                        logger.error(f"  ❌ {source_name} failed: {e}")
                        continue
                
                db.commit()
                logger.info(f"✅ [SCHEDULER] Facebook: Scraped {total_new} new articles")
                
            finally:
                db.close()
        
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Facebook scraping failed: {e}")
    
    def translate_pending_task(self):
        """
        Task: Translate draft articles every hour (notifications sent later with images)
        Runs at: Every hour at :15 (00:15, 01:15, etc.)
        
        ONLY translates articles that need translation (needs_translation=True)
        Ukrainian sources (needs_translation=False) skip translation entirely
        """
        logger.info("🤖 [SCHEDULER] Starting translation task...")
        
        try:
            db = self._get_db_session()
            try:
                # Get articles that NEED translation
                draft_articles = db.query(ContentQueue).filter(
                    ContentQueue.status == 'draft',
                    ContentQueue.needs_translation == True,
                    ContentQueue.translated_text == None
                ).limit(10).all()
                
                if not draft_articles:
                    logger.info("[SCHEDULER] No articles need translation")
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
        
        Handles BOTH:
        - Translated articles (status='pending_approval', has translated_text)
        - Ukrainian articles (needs_translation=False, status='draft')
        """
        logger.info("🤖 [SCHEDULER] Starting image generation task...")
        
        try:
            # Import services inside function to avoid circular imports
            from services.image_generator import image_generator
            from services.notification_service import notification_service
            from sqlalchemy import or_
            
            db = self._get_db_session()
            try:
                # Get articles ready for images:
                # 1. Already translated (status='pending_approval')
                # 2. Ukrainian articles that don't need translation (needs_translation=False)
                articles_without_images = db.query(ContentQueue).filter(
                    or_(
                        # Translated articles ready for images
                        (ContentQueue.status == 'pending_approval'),
                        # Ukrainian articles ready for images (skip translation)
                        (ContentQueue.status == 'draft') & (ContentQueue.needs_translation == False)
                    ),
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
                            
                            # Mark Ukrainian articles as pending_approval after image generation
                            if not article.needs_translation and article.status == 'draft':
                                article.status = 'pending_approval'
                                # Use original text as "translated" text for Ukrainian sources
                                if not article.translated_title:
                                    article.translated_title = article.extra_metadata.get('title', '') if article.extra_metadata else ''
                                if not article.translated_text:
                                    article.translated_text = article.original_text
                            
                            generated_count += 1
                            
                            logger.info(f"[SCHEDULER] Generated image for article {article.id}")
                            
                            notification_data = {
                                'id': article.id,
                                'translated_title': article.translated_title,
                                'translated_text': article.translated_text or article.original_text or '',
                                'image_url': article.image_url,
                                'local_image_path': article.local_image_path,
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
                    'image_url': article.image_url,
                    'local_image_path': article.local_image_path
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
    
    def check_and_run_missed_scraping(self):
        """
        Check if scraping was missed and run immediately if needed.
        Called on startup to catch up on missed jobs.
        """
        logger.info("🔍 [SCHEDULER] Checking for missed scraping tasks...")
        
        try:
            db = self._get_db_session()
            try:
                # Find the most recent scraped article
                from sqlalchemy import func
                latest_article = db.query(func.max(ContentQueue.created_at)).scalar()
                
                if latest_article:
                    hours_since_last = (datetime.utcnow() - latest_article).total_seconds() / 3600
                    logger.info(f"📊 Last article scraped {hours_since_last:.1f} hours ago")
                    
                    # If more than 24 hours since last scrape, run both scraping tasks
                    if hours_since_last > 24:
                        logger.info("⚠️ More than 24 hours since last scrape - running catch-up scraping...")
                        
                        # Run Facebook sources (daily)
                        try:
                            logger.info("🔄 Running catch-up: Facebook sources...")
                            self.scrape_facebook_sources_task()
                        except Exception as e:
                            logger.error(f"❌ Catch-up Facebook scraping failed: {e}")
                        
                        # Check if today is Mon/Wed/Fri for LinkedIn
                        today = datetime.utcnow().weekday()
                        if today in [0, 2, 4]:  # Monday=0, Wednesday=2, Friday=4
                            try:
                                logger.info("🔄 Running catch-up: LinkedIn sources...")
                                self.scrape_linkedin_sources_task()
                            except Exception as e:
                                logger.error(f"❌ Catch-up LinkedIn scraping failed: {e}")
                        
                        logger.info("✅ Catch-up scraping completed")
                    else:
                        logger.info("✅ Scraping is up-to-date, no catch-up needed")
                else:
                    logger.info("📭 No articles in database, running initial scrape...")
                    self.scrape_facebook_sources_task()
                    self.scrape_linkedin_sources_task()
                    
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"❌ Error checking missed scraping: {e}")
    
    def start(self):
        """Start scheduler with platform-specific scraping and posting"""
        if self.scheduler.running:
            logger.info("Scheduler already running, skipping start")
            return
        
        try:
            # LinkedIn sources: Mon/Wed/Fri at 1:00 AM
            self.scheduler.add_job(
                self.scrape_linkedin_sources_task,
                CronTrigger(day_of_week='mon,wed,fri', hour=1, minute=0),
                id='scrape_linkedin',
                name='Scrape LinkedIn sources (TSB, Drinks Int)',
                replace_existing=True
            )
        except Exception as e:
            logger.info(f"Scheduler issue, recreating... ({e})")
            # Recreate scheduler with same config
            database_url = os.environ.get('DATABASE_URL', '')
            jobstores = {}
            if database_url:
                try:
                    jobstores['default'] = SQLAlchemyJobStore(url=database_url)
                except:
                    pass
            
            self.scheduler = BackgroundScheduler(
                jobstores=jobstores if jobstores else None,
                executors={'default': ThreadPoolExecutor(5)},
                job_defaults={
                    'coalesce': True,
                    'max_instances': 1,
                    'misfire_grace_time': 3600 * 6
                }
            )
            self.scheduler.add_job(
                self.scrape_linkedin_sources_task,
                CronTrigger(day_of_week='mon,wed,fri', hour=1, minute=0),
                id='scrape_linkedin',
                name='Scrape LinkedIn sources (TSB, Drinks Int)',
                replace_existing=True
            )
        
        # Facebook sources: Daily at 2:00 AM
        self.scheduler.add_job(
            self.scrape_facebook_sources_task,
            CronTrigger(hour=2, minute=0),
            id='scrape_facebook',
            name='Scrape Facebook sources (Delo, HoReCa, Just Drinks)',
            replace_existing=True
        )
        
        # Translation: 3x per day (morning, afternoon, evening)
        self.scheduler.add_job(
            self.translate_pending_task,
            CronTrigger(hour='6,14,20', minute=0),
            id='translate_articles',
            name='Translate pending articles (3x/day)',
            replace_existing=True
        )
        
        # Images: 3x per day (15 minutes after translation)
        self.scheduler.add_job(
            self.generate_images_task,
            CronTrigger(hour='6,14,20', minute=15),
            id='generate_images',
            name='Generate images & send Telegram notifications (3x/day)',
            replace_existing=True
        )
        
        # LinkedIn posting: Mon/Wed/Fri at 9:00 AM
        self.scheduler.add_job(
            self.post_to_linkedin_task,
            CronTrigger(day_of_week='mon,wed,fri', hour=9, minute=0),
            id='post_linkedin',
            name='Post to LinkedIn',
            replace_existing=True
        )
        
        # Facebook posting: Daily at 6:00 PM
        self.scheduler.add_job(
            self.post_to_facebook_task,
            CronTrigger(hour=18, minute=0),
            id='post_facebook',
            name='Post to Facebook',
            replace_existing=True
        )
        
        # Cleanup: Daily at 3:00 AM
        self.scheduler.add_job(
            self.cleanup_old_content_task,
            CronTrigger(hour=3, minute=0),
            id='cleanup_old_content',
            name='Cleanup old rejected content',
            replace_existing=True
        )
        
        # API monitoring: Daily at 8:00 AM
        self.scheduler.add_job(
            self.check_api_services_task,
            CronTrigger(hour=8, minute=0),
            id='check_api_services',
            name='Check all API services',
            replace_existing=True
        )
        
        self.scheduler.start()
        
        logger.info("=" * 60)
        logger.info("✅ GRADUS MEDIA AI AGENT - FULLY OPERATIONAL")
        logger.info("=" * 60)
        logger.info("")
        logger.info("📰 CONTENT SOURCES:")
        logger.info("   LinkedIn (Mon/Wed/Fri):")
        logger.info("      • The Spirits Business 🇬🇧")
        logger.info("      • Drinks International 🇬🇧")
        logger.info("")
        logger.info("   Facebook (Daily):")
        logger.info("      • Delo.ua 🇺🇦")
        logger.info("      • HoReCa-Україна 🇺🇦")
        logger.info("      • Just Drinks 🇬🇧")
        logger.info("")
        logger.info("📅 SCRAPING SCHEDULE:")
        logger.info("   • LinkedIn: Mon/Wed/Fri 1:00 AM")
        logger.info("   • Facebook: Daily 2:00 AM")
        logger.info("")
        logger.info("🔄 PROCESSING:")
        logger.info("   • Translation: 3x/day at 6am, 2pm, 8pm")
        logger.info("   • Images: 3x/day at 6:15am, 2:15pm, 8:15pm")
        logger.info("")
        logger.info("📢 POSTING SCHEDULE:")
        logger.info("   • LinkedIn: Mon/Wed/Fri 9:00 AM")
        logger.info("   • Facebook: Daily 6:00 PM")
        logger.info("")
        logger.info("🔧 MAINTENANCE:")
        logger.info("   • API monitoring: Daily 8:00 AM")
        logger.info("   • Cleanup: Daily 3:00 AM")
        logger.info("")
        logger.info("=" * 60)
        logger.info("🚀 System ready! Waiting for next scheduled task...")
        logger.info("=" * 60)
    
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
