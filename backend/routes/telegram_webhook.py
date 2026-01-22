"""
Unified Telegram Webhook Handler
Handles:
1. Approval callbacks (approve/reject buttons)
2. Maya bot chat messages
3. HR Bot RAG queries and menu navigation
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
import os
import httpx
import logging
import json
from models import get_db
from services.telegram_webhook import telegram_webhook_handler
from services.hr_keyboards import (
    create_main_menu_keyboard, create_category_keyboard,
    create_feedback_keyboard, create_back_keyboard,
    create_content_navigation_keyboard,
    MENU_TITLES, split_long_message, LEGAL_CONTRACTS, CATEGORY_NAMES
)

logger = logging.getLogger(__name__)
router = APIRouter()

TELEGRAM_MAYA_BOT_TOKEN = os.getenv("TELEGRAM_MAYA_BOT_TOKEN")
API_BASE_URL = os.getenv("APP_URL", "http://localhost:8000")

HR_KEYWORDS = [
    'зарплата', 'зп', 'виплата', 'аванс', 'нарахування',
    'відпустка', 'лікарняний', 'хворіє', 'захворів',
    'віддалена', 'удаленка', 'remote', 'з дому',
    'бліц', 'сед', 'урс', 'доступ',
    'канцтовари', 'меблі', 'обладнання',
    'командировка', 'відрядження',
    'конфлікт', 'звільнення', 'звільнитись',
    'контакти hr', 'кадри', 'документи для прийому',
    'працевлаштування', 'новачок', 'перший день',
    'кпк', 'планшет', 'мобільна торгівля',
    'графік роботи', 'робочий день',
    'технічна підтримка', '3636'
]

CONTENT_CATEGORY_MAP = {
    'video_overview': 'about',
    'video_values': 'about',
    'video_history': 'about',
    'section_structure': 'about',
    'section_4_structure': 'about',
    'section_appendix_22.': 'contacts',
    'q1': 'onboarding',
    'q2': 'onboarding',
    'q3': 'onboarding',
    'q4': 'salary',
    'q5': 'salary',
    'q6': 'work',
    'q8': 'tech',
    'q10': 'work',
    'q11': 'work',
    'q12': 'work',
    'q15': 'tech',
    'q17': 'tech',
    'q18': 'tech',
    'q19': 'tech',
    'q20': 'work',
    'q26': 'work',
}

def is_hr_question(text: str) -> bool:
    """Check if text is HR-related question"""
    text_lower = text.lower()
    return any(kw in text_lower for kw in HR_KEYWORDS)


@router.post("/webhook")
async def handle_telegram_webhook(request: Request, db: Session = Depends(get_db)):
    """
    UNIFIED webhook handler for all Telegram updates
    
    Priority order:
    1. Callback queries (approval buttons) - Critical business logic
    2. Regular messages (Maya bot chat) - User interaction
    """
    
    try:
        data = await request.json()
        
        logger.info(f"📞 Telegram webhook: {list(data.keys())}")
        
        if "callback_query" in data:
            callback_data = data['callback_query'].get('data', '')
            logger.info(f"🔘 Callback query: {callback_data}")
            
            if callback_data.startswith('hr_'):
                result = await handle_hr_callback(data['callback_query'])
                logger.info(f"✓ HR callback processed")
                return result
            else:
                result = telegram_webhook_handler.handle_callback_query(
                    data['callback_query'],
                    db
                )
                logger.info(f"✓ Callback processed: {result.get('status')}")
                return result
        
        elif "message" in data:
            message = data["message"]
            text = message.get("text", "")
            logger.info(f"💬 Message from user: {text[:50]}")
            
            await process_telegram_message(message)
            return {"ok": True}
        
        else:
            logger.warning(f"⚠️  Unknown update: {list(data.keys())}")
            return {"ok": True}
            
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


async def process_telegram_message(message: dict):
    """Process Maya bot chat messages"""
    try:
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")
        user_name = message.get("from", {}).get("first_name", "Friend")
        
        if not text or not chat_id:
            return
        
        if text.startswith("/"):
            if text == "/start":
                await send_telegram_message(
                    chat_id,
                    "Привіт! Я Maya 👋\n\n"
                    "AI-експертка з маркетингу та трендів алкогольної індустрії від Gradus Media.\n\n"
                    "Запитай мене про:\n"
                    "🍸 Бренди горілки, коньяку, вина\n"
                    "🍹 Коктейлі та рецепти\n"
                    "📊 Тренди та маркетинг\n\n"
                    "👥 /hr - HR-довідник для співробітників\n\n"
                    "Я завжди рада допомогти!"
                )
            elif text == "/help":
                await send_telegram_message(
                    chat_id,
                    "Я Maya - ваш AI-консультант з алкогольної індустрії! 🥂\n\n"
                    "Можу розповісти про:\n"
                    "• Бренди Торгового Дому АВ (GREENDAY, HELSINKI, UKRAINKA)\n"
                    "• DOVBUSH коньяк\n"
                    "• Коктейлі та їх приготування\n"
                    "• Маркетингові тренди\n\n"
                    "*Команди:*\n"
                    "/hr - HR-довідник для співробітників\n"
                    "/contacts - Контакти спеціалістів\n\n"
                    "Просто напишіть питання!"
                )
            elif text == "/hr":
                user_name = message.get("from", {}).get("first_name", "")
                await send_telegram_message_with_keyboard(
                    chat_id,
                    f"👋 *Вітаю, {user_name}!*\n\n"
                    "Я Maya — HR асистент ТД АВ. Допоможу вам з:\n\n"
                    "• Питаннями про зарплату та відпустки\n"
                    "• Технічною підтримкою\n"
                    "• Інформацією для новачків\n"
                    "• Контактами спеціалістів\n\n"
                    "Оберіть розділ або напишіть своє питання 👇",
                    create_main_menu_keyboard()
                )
            elif text == "/contacts":
                await fetch_and_send_hr_content(chat_id, None, 'section_appendix_22.')
            return
        
        from services.bestbrands_video import detect_bestbrands_trigger, handle_bestbrands_request
        
        if detect_bestbrands_trigger(text):
            logger.info(f"🎬 ТДАВ trigger detected from {chat_id}")
            await send_typing_action(chat_id)
            success = await handle_bestbrands_request(chat_id)
            if success:
                logger.info(f"✅ ТДАВ video/text sent to {chat_id}")
                return
            logger.warning(f"ТДАВ handler failed, falling back to AI")
        
        if is_hr_question(text):
            logger.info(f"📋 HR question detected from {chat_id}: {text[:50]}...")
            user_id = message.get("from", {}).get("id", 0)
            await handle_hr_question(chat_id, user_id, text)
            return
        
        logger.info(f"📨 Telegram message from {chat_id}: {text[:50]}...")
        
        await send_typing_action(chat_id)
        
        try:
            from routes.chat_endpoints import chat_with_avatars, ChatRequest
            
            chat_request = ChatRequest(
                message=text,
                avatar="maya",
                source="telegram"
            )
            response_data = await chat_with_avatars(chat_request)
            
            if hasattr(response_data, 'response'):
                response_text = response_data.response
            elif isinstance(response_data, dict):
                response_text = response_data.get("response", "Вибачте, виникла помилка.")
            else:
                response_text = str(response_data)
        except Exception as e:
            logger.error(f"Error getting Maya response: {e}")
            response_text = "Привіт! Я Майя з Gradus Media. Зараз у мене технічні складнощі, але я скоро повернусь! 💫"
        
        await send_telegram_message(chat_id, response_text)
        
        logger.info(f"✅ Maya responded to {user_name} on Telegram")
        
    except Exception as e:
        logger.error(f"❌ Error processing Telegram message: {e}")
        try:
            await send_telegram_message(
                chat_id,
                "Вибачте, виникла помилка. Спробуйте ще раз! 🙏"
            )
        except:
            pass


async def send_typing_action(chat_id: int):
    """Show typing indicator"""
    if not TELEGRAM_MAYA_BOT_TOKEN:
        return
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendChatAction",
                json={
                    "chat_id": chat_id,
                    "action": "typing"
                }
            )
    except Exception as e:
        logger.warning(f"⚠️ Error sending typing action: {e}")


async def delete_telegram_message(chat_id: int, message_id: int):
    """Delete a Telegram message"""
    if not TELEGRAM_MAYA_BOT_TOKEN or not message_id:
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/deleteMessage"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json={"chat_id": chat_id, "message_id": message_id})
        return True
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")
        return False


async def send_telegram_video(chat_id: int, video_source: str, caption: str = None, reply_markup: dict = None):
    """Send a video to a Telegram chat - handles both file_id and local paths"""
    import pathlib
    
    if not TELEGRAM_MAYA_BOT_TOKEN:
        logger.warning("TELEGRAM_MAYA_BOT_TOKEN not set")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendVideo"
    
    # Check if source is a URL - extract filename to find local file
    if video_source.startswith('http'):
        # Extract video filename from URL (e.g., video_overview.mp4)
        video_filename = video_source.split('/')[-1]
        base_name = video_filename.rsplit('.', 1)[0]  # Remove extension
        
        # Check for cached file_id in database
        from models import get_db
        from models.content import MediaFile
        try:
            with next(get_db()) as db:
                # Try to find cached file by media_key
                cached = db.query(MediaFile).filter(
                    MediaFile.media_type == 'video',
                    MediaFile.media_key == base_name
                ).first()
                if cached and cached.file_id:
                    video_source = cached.file_id
                    logger.info(f"Using cached file_id for {cached.media_key}")
        except Exception as e:
            logger.warning(f"Could not check cache: {e}")
        
        # If still URL, try to upload local file directly
        if video_source.startswith('http'):
            base_dir = pathlib.Path(__file__).parent.parent / "static" / "videos"
            
            # Use mp4 (Telegram doesn't support webm playback)
            local_path = None
            for ext in ['mp4']:
                candidate = base_dir / f"{base_name}.{ext}"
                if candidate.exists():
                    local_path = candidate
                    video_filename = f"{base_name}.{ext}"
                    logger.info(f"Found video file: {video_filename}")
                    break
            
            if local_path and local_path.exists():
                try:
                    with open(local_path, 'rb') as f:
                        file_content = f.read()
                    
                    data = {
                        'chat_id': str(chat_id),
                        'supports_streaming': 'true'
                    }
                    if caption:
                        data['caption'] = caption[:1024]
                        data['parse_mode'] = 'Markdown'
                    if reply_markup:
                        data['reply_markup'] = json.dumps(reply_markup)
                    
                    async with httpx.AsyncClient(timeout=120.0) as client:
                        content_type = 'video/webm' if video_filename.endswith('.webm') else 'video/mp4'
                        files = {'video': (video_filename, file_content, content_type)}
                        response = await client.post(url, files=files, data=data)
                        
                        if response.status_code == 200:
                            result = response.json()
                            # Cache the file_id for future use
                            if result.get('ok') and result.get('result', {}).get('video', {}).get('file_id'):
                                new_file_id = result['result']['video']['file_id']
                                try:
                                    with next(get_db()) as db:
                                        media = MediaFile(
                                            media_type='video',
                                            media_key=base_name,
                                            file_id=new_file_id,
                                            description=video_filename
                                        )
                                        db.add(media)
                                        db.commit()
                                        logger.info(f"Cached file_id for {base_name}")
                                except Exception as e:
                                    logger.warning(f"Could not cache file_id: {e}")
                            logger.info(f"Video uploaded and sent to {chat_id}")
                            return True
                        else:
                            logger.error(f"Failed to upload video: {response.text}")
                            return False
                except Exception as e:
                    logger.error(f"Error uploading video: {e}")
                    return False
            else:
                logger.error(f"Local video file not found: {local_path}")
                return False
    
    # Send using file_id (cached or provided)
    payload = {
        "chat_id": chat_id,
        "video": video_source,
        "supports_streaming": True
    }
    
    if caption:
        payload["caption"] = caption[:1024]
        payload["parse_mode"] = "Markdown"
    
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                logger.info(f"Video sent to {chat_id}")
                return True
            else:
                logger.error(f"Failed to send video: {response.text}")
                return False
    except Exception as e:
        logger.error(f"Error sending video: {e}")
        return False


async def send_telegram_message(chat_id: int, text: str):
    """Send message via Maya bot"""
    if not TELEGRAM_MAYA_BOT_TOKEN:
        logger.error("TELEGRAM_MAYA_BOT_TOKEN not set")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendMessage"
    
    max_length = 4096
    if len(text) > max_length:
        messages = [text[i:i+max_length] for i in range(0, len(text), max_length)]
    else:
        messages = [text]
    
    async with httpx.AsyncClient() as client:
        try:
            for msg in messages:
                response = await client.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": msg,
                        "parse_mode": "Markdown"
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    logger.info(f"✓ Message sent to chat {chat_id}")
                else:
                    logger.error(f"Telegram API error: {response.text}")
                
        except Exception as e:
            logger.error(f"Error sending message: {e}")


async def send_telegram_message_with_keyboard(chat_id: int, text: str, keyboard: dict = None):
    """Send message with inline keyboard"""
    if not TELEGRAM_MAYA_BOT_TOKEN:
        logger.error("TELEGRAM_MAYA_BOT_TOKEN not set")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    
    if keyboard:
        payload["reply_markup"] = keyboard
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            if response.status_code == 200:
                return True
            logger.error(f"Telegram API error: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return False


async def send_legal_document(chat_id: int, doc_id: str):
    """Send legal document file to user by uploading directly"""
    import pathlib
    import unicodedata
    
    if not TELEGRAM_MAYA_BOT_TOKEN:
        logger.error("TELEGRAM_MAYA_BOT_TOKEN not set")
        return False
    
    contract = LEGAL_CONTRACTS.get(doc_id)
    if not contract:
        await send_telegram_message(chat_id, "❌ Документ не знайдено")
        return False
    
    file_rel_path = contract['file']
    doc_name = contract['name']
    
    # Build absolute path to the file
    base_dir = pathlib.Path(__file__).parent.parent / "static" / "legal_contracts"
    full_path = base_dir / file_rel_path
    
    # Handle Unicode normalization differences (NFD vs NFC)
    if not full_path.exists():
        # Try to find file with different Unicode normalization
        parent_dir = full_path.parent
        target_filename = full_path.name
        target_nfc = unicodedata.normalize('NFC', target_filename)
        target_nfd = unicodedata.normalize('NFD', target_filename)
        
        if parent_dir.exists():
            for existing_file in parent_dir.iterdir():
                existing_nfc = unicodedata.normalize('NFC', existing_file.name)
                existing_nfd = unicodedata.normalize('NFD', existing_file.name)
                if existing_nfc == target_nfc or existing_nfd == target_nfd:
                    full_path = existing_file
                    logger.info(f"Found file with Unicode normalization match: {full_path.name}")
                    break
    
    if not full_path.exists():
        logger.error(f"Legal document file not found: {full_path}")
        await send_telegram_message(chat_id, "❌ Файл документа не знайдено")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendDocument"
    
    try:
        # Read file and upload directly to Telegram
        with open(full_path, 'rb') as f:
            file_content = f.read()
        
        # Get filename from path
        filename = full_path.name
        
        async with httpx.AsyncClient() as client:
            files = {'document': (filename, file_content)}
            data = {'chat_id': str(chat_id), 'caption': f"📄 {doc_name}"}
            response = await client.post(url, files=files, data=data, timeout=60.0)
            
            if response.status_code == 200:
                logger.info(f"Sent legal document {doc_id} to chat {chat_id}")
                return True
            else:
                logger.error(f"Telegram API error sending document: {response.text}")
                await send_telegram_message(chat_id, f"❌ Помилка відправки документа. Спробуйте пізніше.")
                return False
    except Exception as e:
        logger.error(f"Error sending document: {e}")
        await send_telegram_message(chat_id, f"❌ Помилка відправки документа. Спробуйте пізніше.")
        return False


async def edit_telegram_message(chat_id: int, message_id: int, text: str, keyboard: dict = None):
    """Edit existing message"""
    if not TELEGRAM_MAYA_BOT_TOKEN:
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/editMessageText"
    
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    
    if keyboard:
        payload["reply_markup"] = keyboard
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10.0)
            return response.status_code == 200
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        return False


async def answer_callback(callback_id: str, text: str = ""):
    """Answer callback query"""
    if not TELEGRAM_MAYA_BOT_TOKEN:
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/answerCallbackQuery"
    
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json={
                "callback_query_id": callback_id,
                "text": text
            }, timeout=5.0)
    except Exception as e:
        logger.warning(f"Error answering callback: {e}")


async def handle_hr_callback(callback_query: dict):
    """Handle HR bot callbacks"""
    callback_id = callback_query.get('id')
    callback_data = callback_query.get('data', '')
    message = callback_query.get('message', {})
    chat_id = message.get('chat', {}).get('id')
    message_id = message.get('message_id')
    
    await answer_callback(callback_id)
    
    try:
        if callback_data.startswith('hr_menu:'):
            menu_id = callback_data.split(':')[1]
            
            if menu_id == 'main':
                await edit_telegram_message(
                    chat_id, message_id,
                    "🏢 *Maya HR Assistant*\n\nОберіть розділ або напишіть своє питання:",
                    create_main_menu_keyboard()
                )
            elif menu_id in MENU_TITLES:
                await edit_telegram_message(
                    chat_id, message_id,
                    f"{MENU_TITLES[menu_id]}\n\nОберіть підрозділ:",
                    create_category_keyboard(menu_id)
                )
        
        elif callback_data.startswith('hr_doc:'):
            doc_id = callback_data.split(':')[1]
            await send_legal_document(chat_id, doc_id)
        
        elif callback_data.startswith('hr_content:'):
            content_id = callback_data.split(':')[1]
            parent_category = CONTENT_CATEGORY_MAP.get(content_id)
            await fetch_and_send_hr_content(chat_id, message_id, content_id, parent_category=parent_category)
        
        elif callback_data.startswith('hr_text:'):
            content_id = callback_data.split(':')[1]
            parent_category = CONTENT_CATEGORY_MAP.get(content_id)
            await fetch_and_send_hr_content(chat_id, None, content_id, text_only=True, parent_category=parent_category)
        
        elif callback_data.startswith('hr_feedback:'):
            parts = callback_data.split(':')
            feedback_info = parts[1] if len(parts) > 1 else ''
            
            if ':' in feedback_info or len(parts) > 2:
                if len(parts) > 2:
                    feedback_type = parts[1]
                    log_id = int(parts[2]) if parts[2].isdigit() else None
                else:
                    feedback_type = feedback_info
                    log_id = None
            else:
                feedback_type = feedback_info
                log_id = None
            
            user_id = callback_query.get('from', {}).get('id', 0)
            
            if log_id:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"{API_BASE_URL}/api/hr/log-feedback",
                            json={
                                "log_id": log_id,
                                "user_id": user_id,
                                "feedback_type": feedback_type
                            },
                            timeout=5.0
                        )
                except:
                    pass
            
            if feedback_type == 'helpful':
                await answer_callback(callback_id, "Дякуємо за відгук! 🙏")
            elif feedback_type == 'not_helpful':
                await send_telegram_message_with_keyboard(
                    chat_id,
                    "Вибачте, що не змогла допомогти.\n\n"
                    "Ви можете:\n"
                    "• Переформулювати питання\n"
                    "• Звернутися до HR департаменту\n"
                    "• Подивитися контакти спеціалістів",
                    create_main_menu_keyboard()
                )
        
        elif callback_data == 'hr_ask':
            await send_telegram_message(chat_id, "Напишіть своє питання, і я постараюся допомогти! 💬")
        
        return {"ok": True}
    
    except Exception as e:
        logger.error(f"HR callback error: {e}")
        return {"ok": False, "error": str(e)}


async def fetch_and_send_hr_content(chat_id: int, message_id: int, content_id: str, text_only: bool = False, parent_category: str = None):
    """Fetch content from HR API and send to user with proper back navigation"""
    nav_keyboard = create_content_navigation_keyboard(parent_category)
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{API_BASE_URL}/api/hr/content/{content_id}",
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                title = data.get('title', 'Інформація')
                content = data.get('content', 'Контент недоступний')
                content_type = data.get('content_type', 'text')
                video_url = data.get('video_url')
                
                if content_type == 'video' and video_url and not text_only:
                    if message_id:
                        await delete_telegram_message(chat_id, message_id)
                    
                    video_nav = nav_keyboard.copy()
                    text_button = [{"text": "📄 Текстова версія", "callback_data": f"hr_text:{content_id}"}]
                    video_nav["inline_keyboard"] = [text_button] + video_nav["inline_keyboard"]
                    
                    success = await send_telegram_video(
                        chat_id,
                        video_url,
                        f"🎬 *{title}*",
                        video_nav
                    )
                    
                    if not success:
                        await send_telegram_message_with_keyboard(
                            chat_id,
                            f"⚠️ Відео тимчасово недоступне.\n\n*{title}*\n\n{content}",
                            nav_keyboard
                        )
                    return
                
                chunks = split_long_message(f"*{title}*\n\n{content}")
                
                for idx, chunk in enumerate(chunks):
                    if idx == 0 and message_id:
                        await edit_telegram_message(
                            chat_id, message_id, chunk,
                            nav_keyboard if len(chunks) == 1 else None
                        )
                    else:
                        await send_telegram_message_with_keyboard(
                            chat_id, chunk,
                            nav_keyboard if idx == len(chunks) - 1 else None
                        )
            else:
                if message_id:
                    await edit_telegram_message(
                        chat_id, message_id,
                        "❌ Контент не знайдено. Спробуйте інший розділ.",
                        create_main_menu_keyboard()
                    )
                else:
                    await send_telegram_message_with_keyboard(
                        chat_id,
                        "❌ Контент не знайдено. Спробуйте інший розділ.",
                        create_main_menu_keyboard()
                    )
    
    except Exception as e:
        logger.error(f"Error fetching HR content: {e}")
        if message_id:
            await edit_telegram_message(
                chat_id, message_id,
                "❌ Помилка завантаження. Спробуйте пізніше.",
                create_main_menu_keyboard()
            )
        else:
            await send_telegram_message_with_keyboard(
                chat_id,
                "❌ Помилка завантаження. Спробуйте пізніше.",
                create_main_menu_keyboard()
            )


import time

async def handle_hr_question(chat_id: int, user_id: int, query: str):
    """Process HR question via RAG system with logging"""
    await send_typing_action(chat_id)
    start_time = time.time()
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_BASE_URL}/api/hr/answer",
                json={"query": query, "user_id": user_id},
                timeout=15.0
            )
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            if response.status_code != 200:
                await send_telegram_message_with_keyboard(
                    chat_id,
                    "❌ Вибачте, виникла помилка. Спробуйте ще раз або зверніться до HR.",
                    create_main_menu_keyboard()
                )
                return
            
            data = response.json()
            answer_text = data.get('text', data.get('answer', ''))
            sources = data.get('sources', [])
            is_preset = data.get('from_preset', False)
            confidence = data.get('confidence', 0.0)
            
            log_id = None
            rag_used = not is_preset and len(sources) > 0
            
            try:
                log_response = await client.post(
                    f"{API_BASE_URL}/api/hr/log-query",
                    json={
                        "user_id": user_id,
                        "query": query,
                        "preset_matched": is_preset,
                        "rag_used": rag_used,
                        "content_ids": [s.get('content_id') for s in sources] if sources else [],
                        "response_time_ms": response_time_ms
                    },
                    timeout=5.0
                )
                if log_response.status_code == 200:
                    log_data = log_response.json()
                    log_id = log_data.get('log_id')
                
                if response_time_ms > 3000:
                    logger.warning(f"Slow HR query ({response_time_ms}ms): {query[:50]}")
            except:
                pass
            
            feedback_keyboard = create_feedback_keyboard(sources, log_id=log_id)
            
            if is_preset:
                await send_telegram_message_with_keyboard(
                    chat_id, answer_text, feedback_keyboard
                )
            else:
                full_response = answer_text
                if sources:
                    full_response += "\n\n📚 *Джерела:*\n"
                    for idx, source in enumerate(sources[:3], 1):
                        full_response += f"{idx}. {source.get('title', 'Документ')}\n"
                
                await send_telegram_message_with_keyboard(
                    chat_id, full_response, feedback_keyboard
                )
                
    except httpx.TimeoutException:
        await send_telegram_message_with_keyboard(
            chat_id,
            "⏱️ Запит обробляється довго. Спробуйте переформулювати або зверніться до HR.",
            create_main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"HR question error: {e}")
        await send_telegram_message_with_keyboard(
            chat_id,
            "❌ Не вдалося обробити запит. Зверніться до HR департаменту.",
            create_main_menu_keyboard()
        )
