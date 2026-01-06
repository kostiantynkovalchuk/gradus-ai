"""
Best Brands Video Feature for Maya Telegram Bot

Sends a vertical (9:16) video presentation when users ask about Best Brands company.
Supports Ukrainian, Russian, and English with code-switching (e.g., "розкажи про best brands").
"""

import os
import re
import logging
import httpx
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

TELEGRAM_MAYA_BOT_TOKEN = os.getenv("TELEGRAM_MAYA_BOT_TOKEN")
BEST_BRANDS_VIDEO_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "bestbrands-presentation.mp4")
MEDIA_KEY = "bestbrands_presentation"

BESTBRANDS_TEXT_FALLBACK = """🏢 Best Brands — найбільший дистриб'ютор алкогольних брендів в Україні

📊 Ключові факти:
- Покриваємо понад 40 000 торгових точок по всій країні
- Працюємо з провідними українськими та міжнародними брендами
- Спеціалізуємось на HoReCa сегменті

🎯 Наші бренди включають:
- GreenDay (горілка преміум-класу)
- Dovbush (традиційні українські напої)
- Funju (інноваційні коктейльні рішення)
- Villa.ua (винна лінійка)

💼 Ми надаємо повний спектр послуг для ресторанів, готелей та кафе — від постачання до маркетингової підтримки.

📚 Джерела: avtd.com, офіційні сайти брендів компанії

Які питання маєш про наші продукти чи послуги? 😊"""


def detect_bestbrands_trigger(message_text: str) -> bool:
    """
    Detects if user is asking about Best Brands company.
    Supports code-switching (e.g., "розкажи про best brands").
    
    Returns True if message contains:
    - Any question phrase (UA/RU/EN) + company name variation
    - OR identity questions ("хто ви", "who are you")
    
    Case-insensitive matching.
    """
    if not message_text:
        return False
    
    message_lower = message_text.lower().strip()
    
    question_patterns_ua = [
        r'розкажи\s+про',
        r'що\s+таке',
        r'хто\s+такі',
        r'про\s+компанію',
        r'про\s+вас',
        r'хто\s+ви',
        r'ким\s+ви\s+є',
    ]
    
    question_patterns_ru = [
        r'расскажи\s+о',
        r'расскажи\s+про',
        r'что\s+такое',
        r'кто\s+такие',
        r'о\s+компании',
        r'про\s+компанию',
        r'кто\s+вы',
    ]
    
    question_patterns_en = [
        r'tell\s+me\s+about',
        r'tell\s+about',
        r'who\s+is',
        r'who\s+are',
        r'what\s+is',
        r'about\s+the\s+company',
        r'about\s+your\s+company',
        r'who\s+are\s+you',
    ]
    
    company_names = [
        r'best\s*brands?',
        r'бест\s*брендс?',
        r'bestbrands?',
        r'avtd',
        r'автд',
    ]
    
    company_only_patterns = [
        r'^про\s+компанію\??$',
        r'^о\s+компании\??$',
        r'^about\s+the\s+company\??$',
        r'^about\s+your\s+company\??$',
    ]
    
    for pattern in company_only_patterns:
        if re.search(pattern, message_lower):
            return True
    
    all_question_patterns = question_patterns_ua + question_patterns_ru + question_patterns_en
    
    has_question = any(re.search(p, message_lower) for p in all_question_patterns)
    has_company_name = any(re.search(p, message_lower) for p in company_names)
    
    if has_question and has_company_name:
        return True
    
    simple_about_patterns = [
        r'^про\s+best\s*brands?',
        r'^про\s+бест\s*брендс?',
        r'^about\s+best\s*brands?',
        r'^best\s*brands?\s*\?',
        r'^бест\s*брендс?\s*\?',
    ]
    
    for pattern in simple_about_patterns:
        if re.search(pattern, message_lower):
            return True
    
    return False


def get_stored_file_id() -> Optional[str]:
    """Get stored Telegram file_id from database"""
    try:
        import models
        from models.content import MediaFile
        
        if models.SessionLocal is None:
            models.init_db()
        
        db = models.SessionLocal()
        try:
            media = db.query(MediaFile).filter(MediaFile.media_key == MEDIA_KEY).first()
            if media:
                return media.file_id
            return None
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error getting stored file_id: {e}")
        return None


def store_file_id(file_id: str) -> bool:
    """Store Telegram file_id in database"""
    try:
        import models
        from models.content import MediaFile
        
        if models.SessionLocal is None:
            models.init_db()
        
        db = models.SessionLocal()
        try:
            existing = db.query(MediaFile).filter(MediaFile.media_key == MEDIA_KEY).first()
            
            if existing:
                existing.file_id = file_id
            else:
                new_media = MediaFile(
                    media_type='video',
                    media_key=MEDIA_KEY,
                    file_id=file_id,
                    description='Best Brands presentation video for Maya bot'
                )
                db.add(new_media)
            
            db.commit()
            logger.info(f"✅ Stored file_id for {MEDIA_KEY}")
            return True
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error storing file_id: {e}")
        return False


async def upload_video_to_telegram(chat_id: int) -> Tuple[bool, Optional[str]]:
    """
    Upload video file to Telegram and get file_id.
    Returns (success, file_id or None)
    """
    if not TELEGRAM_MAYA_BOT_TOKEN:
        logger.error("TELEGRAM_MAYA_BOT_TOKEN not set")
        return False, None
    
    if not os.path.exists(BEST_BRANDS_VIDEO_PATH):
        logger.error(f"Video file not found: {BEST_BRANDS_VIDEO_PATH}")
        return False, None
    
    url = f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendVideo"
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(BEST_BRANDS_VIDEO_PATH, 'rb') as video_file:
                files = {'video': ('bestbrands.mp4', video_file, 'video/mp4')}
                data = {
                    'chat_id': chat_id,
                    'caption': '📚 Джерела: avtd.com, офіційні сайти брендів компанії',
                    'supports_streaming': 'true',
                    'width': '1080',
                    'height': '1920'
                }
                
                response = await client.post(url, files=files, data=data)
                result = response.json()
                
                if result.get('ok'):
                    video_info = result.get('result', {}).get('video', {})
                    file_id = video_info.get('file_id')
                    
                    if file_id:
                        store_file_id(file_id)
                        logger.info(f"✅ Video uploaded successfully, file_id stored")
                        return True, file_id
                    else:
                        logger.error("Video sent but no file_id in response")
                        return True, None
                else:
                    logger.error(f"Telegram API error: {result.get('description')}")
                    return False, None
                    
    except Exception as e:
        logger.error(f"Error uploading video: {e}")
        return False, None


async def send_video_by_file_id(chat_id: int, file_id: str) -> bool:
    """Send video using stored file_id (instant)"""
    if not TELEGRAM_MAYA_BOT_TOKEN:
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendVideo"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json={
                'chat_id': chat_id,
                'video': file_id,
                'caption': '📚 Джерела: avtd.com, офіційні сайти брендів компанії',
                'supports_streaming': True,
                'width': 1080,
                'height': 1920
            })
            
            result = response.json()
            
            if result.get('ok'):
                logger.info(f"✅ Video sent via file_id to chat {chat_id}")
                return True
            else:
                error_desc = result.get('description', 'Unknown error')
                logger.error(f"Failed to send video: {error_desc}")
                if 'file' in error_desc.lower() and 'not found' in error_desc.lower():
                    logger.warning("file_id may be invalid, will need re-upload")
                return False
                
    except Exception as e:
        logger.error(f"Error sending video: {e}")
        return False


async def send_text_fallback(chat_id: int) -> bool:
    """Send text-only version if video fails"""
    if not TELEGRAM_MAYA_BOT_TOKEN:
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendMessage"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={
                'chat_id': chat_id,
                'text': BESTBRANDS_TEXT_FALLBACK,
                'parse_mode': 'Markdown'
            })
            
            result = response.json()
            return result.get('ok', False)
            
    except Exception as e:
        logger.error(f"Error sending text fallback: {e}")
        return False


async def handle_bestbrands_request(chat_id: int) -> bool:
    """
    Main handler that tries video first, falls back to text.
    Returns True if handled successfully.
    """
    logger.info(f"🎬 Best Brands request from chat {chat_id}")
    
    stored_file_id = get_stored_file_id()
    
    if stored_file_id:
        logger.info("📦 Using stored file_id")
        success = await send_video_by_file_id(chat_id, stored_file_id)
        
        if success:
            return True
        
        logger.warning("Stored file_id failed, trying fresh upload")
    
    if os.path.exists(BEST_BRANDS_VIDEO_PATH):
        logger.info("📤 Uploading video file...")
        success, _ = await upload_video_to_telegram(chat_id)
        
        if success:
            return True
    else:
        logger.warning(f"Video file not found at {BEST_BRANDS_VIDEO_PATH}")
    
    logger.info("📝 Falling back to text response")
    return await send_text_fallback(chat_id)
