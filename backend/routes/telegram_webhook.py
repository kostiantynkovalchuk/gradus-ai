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
from services.maya_hr_content import get_direct_content, has_direct_content
from services.hr_auth import (
    handle_start_command, handle_phone_verification,
    is_awaiting_phone, is_valid_phone, set_awaiting_phone,
    set_pending_phone, get_pending_phone, clear_pending_state,
    get_user_by_telegram_id, get_access_level,
    handle_admin_command, handle_adduser_command, handle_logs_command,
    handle_stats_command, handle_listusers_command
)
from utils.phone_normalizer import normalize_phone, format_for_display

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
    'технічна підтримка', '3636',
    'стіл', 'крісло', 'замовити', 'закупити', 'основні фонди',
    'техніка', 'комп\'ютер', 'ноутбук', 'монітор',
    'контакти цо', 'центральний офіс', 'контакти офісу'
]

CONTENT_CATEGORY_MAP = {
    'video_overview': 'about',
    'video_values': 'about',
    'video_history': 'about',
    'section_structure': 'about',
    'section_4_structure': 'about',
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
    'q19': 'work',
    'q20': 'work',
    'q21': 'tech',
    'q26': 'work',
    'appendix_12_ranks': 'work',
    'appendix_12_1_norms': 'work',
    'appendix_21_furniture': 'work',
    'appendix_21_1_equipment': 'work',
    'appendix_22_contacts': 'contacts',
}

VIDEO_CONTENT_TRIGGERS = {
    'video_values': ['цінност', 'values', 'наші цінності', 'корпоративні цінності'],
    'video_history': ['історі', 'history', 'історія компанії', 'як все почалось'],
    'video_overview': ['про компан', 'about company', 'що таке avtd', 'що таке автд', 
                       'загальна інформація', 'хто ми', 'про нас'],
    'q26': ['звільнен', 'звільнити', 'звільняюсь', 'хочу звільнитись', 'процес звільнення',
            'як звільнитись', 'offboarding', 'resignation', 'хочу піти', 'хочу йти'],
}

VIDEO_CAPTIONS = {
    'video_values': '🎥 Цінності компанії AVTD',
    'video_history': '🎥 Історія компанії AVTD (25+ років)',
    'video_overview': '🎥 Про компанію AVTD',
    'q26': '📤 Звільнення',
}


def detect_video_content(query: str) -> tuple:
    """Check if query matches video content triggers.
    Returns (content_id, caption) if match found, else (None, None)"""
    query_lower = query.lower().strip()
    
    for content_id, triggers in VIDEO_CONTENT_TRIGGERS.items():
        for trigger in triggers:
            if trigger in query_lower:
                caption = VIDEO_CAPTIONS.get(content_id, '🎥 Відео від Maya HR')
                return content_id, caption
    
    return None, None


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
            
            if callback_data.startswith('admin_cmd:'):
                result = await handle_admin_button_callback(data['callback_query'], db)
                logger.info(f"✓ Admin button callback processed")
                return result
            elif callback_data.startswith('hr_'):
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

            if message.get("document") and not text:
                logger.info(f"📎 Document received: {message['document'].get('file_name', 'unknown')}")
                await handle_document_upload(message, db)
                return {"ok": True}

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
    """Process Maya bot chat messages with auth"""
    try:
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")
        user_name = message.get("from", {}).get("first_name", "Friend")
        telegram_id = message.get("from", {}).get("id", chat_id)
        
        if not text or not chat_id:
            return
        
        from models import get_db
        db_gen = get_db()
        db = next(db_gen)
        
        try:
            if is_awaiting_phone(telegram_id) and not text.startswith("/"):
                phone_raw = text.strip()
                if is_valid_phone(phone_raw):
                    try:
                        phone_normalized = normalize_phone(phone_raw)
                    except ValueError:
                        phone_normalized = phone_raw
                    phone_display = format_for_display(phone_normalized)
                    
                    set_pending_phone(telegram_id, phone_normalized)
                    
                    confirm_keyboard = {
                        "inline_keyboard": [
                            [{"text": "✅ Підтвердити і верифікуватись", "callback_data": "hr_verify_phone:confirm"}],
                            [{"text": "✏️ Ввести інший номер", "callback_data": "hr_verify_phone:retry"}]
                        ]
                    }
                    await send_telegram_message_with_keyboard(
                        chat_id,
                        f"📱 Номер отримано: `{phone_display}`\n\n"
                        f"Натисніть кнопку для верифікації:",
                        confirm_keyboard
                    )
                else:
                    await send_telegram_message(
                        chat_id,
                        "❌ Невірний формат номера.\n\n"
                        "📱 Введіть український номер у будь-якому форматі:\n"
                        "✅ +380671234567\n"
                        "✅ 0671234567\n"
                        "✅ 380671234567\n\n"
                        "Спробуйте ще раз:"
                    )
                return

            if text.startswith("/"):
                if text == "/start":
                    await handle_start_command(chat_id, telegram_id, user_name, db)
                elif text == "/help":
                    await send_telegram_message(
                        chat_id,
                        "Я Maya — HR-асистент Торгового Дому АВ! 💃\n\n"
                        "Можу допомогти з:\n"
                        "• HR-питаннями та процедурами\n"
                        "• Інформацією про компанію та бренди\n"
                        "• Відпустки, зарплата, техпідтримка\n\n"
                        "*Команди:*\n"
                        "/start - Реєстрація / головне меню\n"
                        "/hr - HR-довідник для співробітників\n"
                        "/contacts - Контакти спеціалістів\n"
                        "/admin - Адмін-панель (для адмінів)\n\n"
                        "Просто напишіть питання!"
                    )
                elif text == "/hr":
                    user = get_user_by_telegram_id(db, telegram_id)
                    if not user:
                        await send_telegram_message(
                            chat_id,
                            "Для доступу до HR-довідника потрібно пройти верифікацію.\n\n"
                            "Натисни /start щоб розпочати."
                        )
                    else:
                        await send_telegram_message_with_keyboard(
                            chat_id,
                            f"👋 *Вітаю, {user.first_name or user_name}!*\n\n"
                            "Я Maya — HR асистент ТД АВ. Допоможу вам з:\n\n"
                            "• Питаннями про зарплату та відпустки\n"
                            "• Технічною підтримкою\n"
                            "• Інформацією для новачків\n"
                            "• Контактами спеціалістів\n\n"
                            "Оберіть розділ або напишіть своє питання 👇",
                            create_main_menu_keyboard()
                        )
                elif text == "/contacts":
                    await fetch_and_send_hr_content(chat_id, None, 'appendix_22_contacts')
                elif text == "/admin":
                    await handle_admin_command(chat_id, telegram_id, db)
                elif text.startswith("/adduser"):
                    args = text[len("/adduser"):].strip()
                    await handle_adduser_command(chat_id, telegram_id, args, db)
                elif text == "/logs":
                    await handle_logs_command(chat_id, telegram_id, db)
                elif text == "/stats":
                    await handle_stats_command(chat_id, telegram_id, db)
                elif text == "/listusers":
                    await handle_listusers_command(chat_id, telegram_id, db)
                return
        finally:
            try:
                db.close()
            except:
                pass
        
        from services.bestbrands_video import detect_bestbrands_trigger, handle_bestbrands_request
        
        if detect_bestbrands_trigger(text):
            logger.info(f"🎬 ТДАВ trigger detected from {chat_id}")
            await send_typing_action(chat_id)
            success = await handle_bestbrands_request(chat_id)
            if success:
                logger.info(f"✅ ТДАВ video/text sent to {chat_id}")
                return
            logger.warning(f"ТДАВ handler failed, falling back to AI")
        
        auth_db_gen = get_db()
        auth_db = next(auth_db_gen)
        try:
            user = get_user_by_telegram_id(auth_db, telegram_id)
            if not user:
                await send_telegram_message(
                    chat_id,
                    "Для доступу до бота потрібно пройти верифікацію.\n\n"
                    "Натисни /start щоб розпочати."
                )
                return
        finally:
            auth_db.close()

        logger.info(
            f"MSG_ROUTED: telegram_id={telegram_id}, "
            f"user={user.full_name}, text='{text[:50]}...'"
        )
        user_id = message.get("from", {}).get("id", 0)
        await handle_hr_question(chat_id, user_id, text)
        
    except Exception as e:
        logger.error(
            f"MSG_ERROR: telegram_id={telegram_id}, "
            f"error={type(e).__name__}: {str(e)[:200]}",
            exc_info=True
        )
        try:
            await send_telegram_message(
                chat_id,
                "Вибачте, виникла технічна помилка.\n\n"
                "Спробуйте ще раз через хвилину або зверніться до HR-відділу."
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
            # Version suffix to invalidate old cache entries - increment when video changes
            cache_key = f"{base_name}_v5"
            with next(get_db()) as db:
                # Try to find cached file by media_key
                cached = db.query(MediaFile).filter(
                    MediaFile.media_type == 'video',
                    MediaFile.media_key == cache_key
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
                        'supports_streaming': 'true',
                        'width': '1080',
                        'height': '1920'
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
                                            media_key=cache_key,
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
        payload["reply_markup"] = reply_markup  # Don't stringify - httpx does it when using json=
    
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


async def handle_admin_button_callback(callback_query: dict, db):
    """Handle admin button callbacks from inline keyboard"""
    callback_id = callback_query.get('id')
    callback_data = callback_query.get('data', '')
    chat_id = callback_query.get('message', {}).get('chat', {}).get('id')
    telegram_id = callback_query.get('from', {}).get('id')
    cmd = callback_data.replace('admin_cmd:', '')

    await answer_callback(callback_id, f"Виконую {cmd}...")

    from services.hr_auth import (
        handle_admin_command, handle_adduser_command,
        handle_logs_command, handle_stats_command,
        handle_listusers_command
    )

    if cmd == "admin":
        await handle_admin_command(chat_id, telegram_id, db)
    elif cmd == "stats":
        await handle_stats_command(chat_id, telegram_id, db)
    elif cmd == "logs":
        await handle_logs_command(chat_id, telegram_id, db)
    elif cmd == "adduser":
        await handle_adduser_command(chat_id, telegram_id, [], db)
    elif cmd == "listusers":
        await handle_listusers_command(chat_id, telegram_id, db)

    return {"ok": True}


async def handle_hr_callback(callback_query: dict):
    """Handle HR bot callbacks"""
    callback_id = callback_query.get('id')
    callback_data = callback_query.get('data', '')
    message = callback_query.get('message', {})
    chat_id = message.get('chat', {}).get('id')
    message_id = message.get('message_id')
    is_video_message = 'video' in message
    
    await answer_callback(callback_id)
    
    try:
        if callback_data.startswith('hr_menu:'):
            menu_id = callback_data.split(':')[1]
            
            if menu_id == 'main':
                if is_video_message:
                    await delete_telegram_message(chat_id, message_id)
                    await send_telegram_message_with_keyboard(
                        chat_id,
                        "🏢 *Maya HR Assistant*\n\nОберіть розділ або напишіть своє питання:",
                        create_main_menu_keyboard()
                    )
                else:
                    await edit_telegram_message(
                        chat_id, message_id,
                        "🏢 *Maya HR Assistant*\n\nОберіть розділ або напишіть своє питання:",
                        create_main_menu_keyboard()
                    )
            elif menu_id == 'training':
                training_url = "https://docs.google.com/document/d/1Xm8wPB4Rwcj_4G50jXDLq_fANV_vvpLiyK_usrKIMs4/edit"
                training_keyboard = {
                    "inline_keyboard": [
                        [{"text": "📖 Відкрити документ", "url": training_url}],
                        [{"text": "🏠 Головне меню", "callback_data": "hr_menu:main"}]
                    ]
                }
                training_msg = (
                    "📚 *Навчальні матеріали*\n\n"
                    "HR-процеси та робота в системі «Бліц»\n\n"
                    "Покрокова інструкція щодо підбору, оформлення та звільнення співробітників."
                )
                if is_video_message:
                    await delete_telegram_message(chat_id, message_id)
                    await send_telegram_message_with_keyboard(chat_id, training_msg, training_keyboard)
                else:
                    await edit_telegram_message(chat_id, message_id, training_msg, training_keyboard)
            elif menu_id in MENU_TITLES:
                if is_video_message:
                    await delete_telegram_message(chat_id, message_id)
                    await send_telegram_message_with_keyboard(
                        chat_id,
                        f"{MENU_TITLES[menu_id]}\n\nОберіть підрозділ:",
                        create_category_keyboard(menu_id)
                    )
                else:
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
            logger.info(f"🔍 HR_CONTENT callback - Raw: {callback_data}, Extracted ID: {content_id}")
            
            direct = get_direct_content(content_id)
            if direct:
                logger.info(f"✅ Found in CONTENT_MAP: {content_id} → {direct.get('title', 'NO TITLE')}")
                if direct.get('type') == 'link':
                    logger.info(f"📎 Link type, URL: {direct.get('url', 'NO URL')[:60]}...")
            else:
                logger.error(f"❌ NOT FOUND in CONTENT_MAP: {content_id}")
            
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
                        
                        if feedback_type == 'not_helpful':
                            from routes.hr_routes import hr_pinecone_index
                            from services.hr_rag_service import get_hr_rag_service
                            from models import get_db
                            
                            fb_db = next(get_db())
                            try:
                                rag_service = get_hr_rag_service(
                                    pinecone_index=hr_pinecone_index,
                                    db_session=fb_db
                                )
                                await rag_service.create_preset_candidate(log_id)
                            finally:
                                fb_db.close()
                except Exception as fb_err:
                    logger.warning(f"Feedback processing error: {fb_err}")
            
            if feedback_type == 'helpful':
                await answer_callback(callback_id, "Дякую! 😊")
            elif feedback_type == 'not_helpful':
                await answer_callback(callback_id, "Зрозуміло, передам HR-команді!")
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
        
        elif callback_data.startswith('hr_verify_phone:'):
            action = callback_data.replace('hr_verify_phone:', '', 1)
            telegram_id = callback_query.get('from', {}).get('id')
            
            if action == 'retry':
                clear_pending_state(telegram_id)
                set_awaiting_phone(telegram_id, True)
                await edit_telegram_message(
                    chat_id, message_id,
                    "📱 Введіть свій робочий номер телефону:\n\n"
                    "Формат: `+380501234567` або `0501234567`"
                )
            elif action == 'confirm':
                phone_normalized = get_pending_phone(telegram_id)
                if not phone_normalized:
                    await edit_telegram_message(
                        chat_id, message_id,
                        "⚠️ Сесія верифікації закінчилась.\n\n"
                        "Натисніть /start щоб почати знову."
                    )
                    return {"ok": True}
                
                clear_pending_state(telegram_id)
                phone_display = format_for_display(phone_normalized)
                
                await edit_telegram_message(
                    chat_id, message_id,
                    f"🔍 Перевіряю номер `{phone_display}`...\n"
                    f"Зачекайте кілька секунд."
                )
                
                from models import get_db as _get_db
                db_gen = _get_db()
                db = next(db_gen)
                try:
                    user_info = {
                        "first_name": callback_query.get('from', {}).get('first_name', ''),
                        "last_name": callback_query.get('from', {}).get('last_name', ''),
                        "username": callback_query.get('from', {}).get('username'),
                    }
                    await handle_phone_verification(chat_id, telegram_id, phone_normalized, user_info, db)
                finally:
                    db.close()
        
        return {"ok": True}
    
    except Exception as e:
        logger.error(f"HR callback error: {e}")
        return {"ok": False, "error": str(e)}


async def fetch_and_send_hr_content(chat_id: int, message_id: int, content_id: str, text_only: bool = False, parent_category: str = None):
    """Fetch content - uses direct memory lookup first, then falls back to API"""
    nav_keyboard = create_content_navigation_keyboard(parent_category)
    
    direct_content = get_direct_content(content_id)
    if direct_content:
        title = direct_content.get('title', 'Інформація')
        content = direct_content.get('content', 'Контент недоступний')
        content_type = direct_content.get('type', 'text')
        video_url = direct_content.get('video_url')
        logger.info(f"📦 Direct content lookup for {content_id} - instant response")
    else:
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
                    logger.info(f"🌐 API lookup for {content_id} - database response")
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
                    return
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
            return
    
    if content_type == 'video' and video_url and not text_only:
        if message_id:
            await delete_telegram_message(chat_id, message_id)
        
        success = await send_telegram_video(
            chat_id,
            video_url,
            f"🎬 *{title}*",
            nav_keyboard
        )
        
        if not success:
            await send_telegram_message_with_keyboard(
                chat_id,
                f"⚠️ Відео тимчасово недоступне.\n\n*{title}*\n\n{content}",
                nav_keyboard
            )
        return
    
    # Handle link type - send URL with description
    if content_type == 'link':
        url = direct_content.get('url', '') if direct_content else ''
        description = direct_content.get('description', '') if direct_content else ''
        emoji = direct_content.get('emoji', '📄') if direct_content else '📄'
        
        message = f"{emoji} *{title}*\n\n{description}\n\n🔗 [Відкрити документ]({url})"
        
        if message_id:
            await edit_telegram_message(chat_id, message_id, message, nav_keyboard)
        else:
            await send_telegram_message_with_keyboard(chat_id, message, nav_keyboard)
        return
    
    # Get attachments if present
    attachments = direct_content.get('attachments', []) if direct_content else []
    
    chunks = split_long_message(f"*{title}*\n\n{content}")
    
    for idx, chunk in enumerate(chunks):
        # For last chunk, attach keyboard (either attachments or nav)
        is_last = idx == len(chunks) - 1
        keyboard_to_use = nav_keyboard if is_last and not attachments else None
        
        if idx == 0 and message_id:
            await edit_telegram_message(chat_id, message_id, chunk, keyboard_to_use)
        else:
            await send_telegram_message_with_keyboard(chat_id, chunk, keyboard_to_use)
    
    # Send attachments as buttons if present
    if attachments:
        attachment_buttons = []
        for attachment_id in attachments:
            attachment = get_direct_content(attachment_id)
            if attachment:
                att_title = attachment.get('title', 'Додаток')
                att_emoji = attachment.get('emoji', '📄')
                # Truncate button text to 60 chars max (Telegram limit is 64)
                button_text = f"{att_emoji} {att_title}"
                if len(button_text) > 60:
                    button_text = button_text[:57] + "..."
                attachment_buttons.append([{
                    "text": button_text,
                    "callback_data": f"hr_content:{attachment_id}"
                }])
        
        if attachment_buttons:
            # Add back button
            attachment_buttons.extend(nav_keyboard.get("inline_keyboard", []))
            attachment_keyboard = {"inline_keyboard": attachment_buttons}
            await send_telegram_message_with_keyboard(
                chat_id,
                "📎 *Додаткові матеріали:*",
                attachment_keyboard
            )


import time

async def send_video_only_response(chat_id: int, content_id: str, caption: str) -> bool:
    """Send video-only response for video content. Returns True if successful."""
    try:
        video_url = None
        
        from services.maya_hr_content import HR_CONTENT
        direct_content = HR_CONTENT.get(content_id)
        if direct_content and direct_content.get('type') == 'video' and direct_content.get('video_url'):
            video_url = direct_content['video_url']
        
        if not video_url:
            from models import get_db
            from models.hr_models import HRContent
            with next(get_db()) as db:
                content = db.query(HRContent).filter(HRContent.content_id == content_id).first()
                if content and content.video_url:
                    video_url = content.video_url
        
        if not video_url:
            logger.warning(f"Video content not found or no video_url: {content_id}")
            return False
            
        nav_keyboard = create_main_menu_keyboard()
        
        success = await send_telegram_video(
            chat_id,
            video_url,
            caption,
            nav_keyboard
        )
        
        if success:
            logger.info(f"Sent video-only response for {content_id}")
            return True
        else:
            logger.warning(f"Failed to send video for {content_id}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending video-only response: {e}")
        return False


async def handle_hr_question(chat_id: int, user_id: int, query: str):
    """Process HR question via RAG system with logging"""
    await send_typing_action(chat_id)
    start_time = time.time()
    
    video_content_id, video_caption = detect_video_content(query)
    if video_content_id:
        logger.info(f"Video content detected for query: {query[:50]} -> {video_content_id}")
        success = await send_video_only_response(chat_id, video_content_id, video_caption)
        if success:
            return
        logger.info(f"Video send failed, falling back to text response")
    
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


def _extract_text_from_bytes(content: bytes, filename: str) -> str:
    filename_lower = filename.lower()
    if filename_lower.endswith('.txt'):
        return content.decode('utf-8', errors='replace')
    elif filename_lower.endswith('.pdf'):
        import io
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(content))
        return '\n'.join(page.extract_text() or '' for page in reader.pages)
    elif filename_lower.endswith('.docx'):
        import io
        from docx import Document as DocxDocument
        doc = DocxDocument(io.BytesIO(content))
        return '\n'.join(p.text for p in doc.paragraphs)
    else:
        return content.decode('utf-8', errors='replace')


ALLOWED_DOC_EXTENSIONS = {'.txt', '.pdf', '.docx', '.md'}
MAX_DOC_SIZE = 5 * 1024 * 1024


async def handle_document_upload(message: dict, db: Session):
    chat_id = message.get("chat", {}).get("id")
    telegram_id = message.get("from", {}).get("id")
    doc_info = message.get("document", {})
    file_name = doc_info.get("file_name", "unknown")
    file_size = doc_info.get("file_size", 0)
    file_id = doc_info.get("file_id")
    caption = message.get("caption", "")

    access = get_access_level(db, telegram_id)
    if not access or access not in ("developer", "admin_hr", "admin_it"):
        await send_telegram_message(
            chat_id,
            "⚠️ Завантаження документів доступне лише для HR-адміністраторів."
        )
        return

    ext = '.' + file_name.rsplit('.', 1)[-1].lower() if '.' in file_name else ''
    if ext not in ALLOWED_DOC_EXTENSIONS:
        await send_telegram_message(
            chat_id,
            f"⚠️ Непідтримуваний формат: *{ext}*\n"
            f"Підтримуються: {', '.join(ALLOWED_DOC_EXTENSIONS)}"
        )
        return

    if file_size > MAX_DOC_SIZE:
        await send_telegram_message(chat_id, "⚠️ Файл завеликий (макс. 5 МБ).")
        return

    await send_typing_action(chat_id)

    try:
        bot_token = TELEGRAM_MAYA_BOT_TOKEN
        async with httpx.AsyncClient() as client:
            file_resp = await client.get(
                f"https://api.telegram.org/bot{bot_token}/getFile",
                params={"file_id": file_id},
                timeout=10.0
            )
            if file_resp.status_code != 200:
                logger.error(f"Telegram getFile failed: {file_resp.status_code} {file_resp.text[:200]}")
                await send_telegram_message(chat_id, "❌ Не вдалося отримати файл від Telegram.")
                return
            file_data = file_resp.json()
            if not file_data.get("ok"):
                logger.error(f"Telegram getFile error: {file_data}")
                await send_telegram_message(chat_id, "❌ Не вдалося отримати файл.")
                return
            file_path = file_data.get("result", {}).get("file_path")
            if not file_path:
                await send_telegram_message(chat_id, "❌ Не вдалося отримати файл.")
                return

            dl_resp = await client.get(
                f"https://api.telegram.org/file/bot{bot_token}/{file_path}",
                timeout=30.0
            )
            if dl_resp.status_code != 200:
                logger.error(f"Telegram file download failed: {dl_resp.status_code}")
                await send_telegram_message(chat_id, "❌ Не вдалося завантажити файл.")
                return
            content_bytes = dl_resp.content

        text_content = _extract_text_from_bytes(content_bytes, file_name)

        if len(text_content.strip()) < 50:
            await send_telegram_message(
                chat_id,
                "⚠️ Не вдалося витягти текст з документа або текст занадто короткий."
            )
            return

        title = caption.strip() if caption.strip() else file_name.rsplit('.', 1)[0]

        from routes.hr_routes import hr_pinecone_index
        from services.hr_rag_service import get_hr_rag_service

        rag_service = get_hr_rag_service(
            pinecone_index=hr_pinecone_index,
            db_session=db
        )

        result = await rag_service.ingest_document(
            title=title,
            content=text_content,
            category="uploaded",
            subcategory="telegram_upload"
        )

        if result.get('status') == 'success':
            await send_telegram_message(
                chat_id,
                f"✅ *Документ завантажено до бази знань!*\n\n"
                f"📄 *Назва:* {title}\n"
                f"🆔 *ID:* `{result['content_id']}`\n"
                f"📏 *Розмір:* {result['content_length']} символів\n\n"
                f"Документ тепер доступний через пошук Maya."
            )
            logger.info(f"Document ingested via Telegram: {result['content_id']} by user {telegram_id}")
        elif result.get('status') == 'partial':
            await send_telegram_message(
                chat_id,
                f"⚠️ *Документ збережено частково*\n\n"
                f"📄 *Назва:* {title}\n"
                f"🆔 *ID:* `{result['content_id']}`\n\n"
                f"Помилка: {result.get('error', 'unknown')}\n"
                f"Текст збережено в БД, але семантичний пошук може не працювати."
            )
        else:
            await send_telegram_message(chat_id, "❌ Не вдалося завантажити документ.")

    except Exception as e:
        logger.error(f"Document upload error: {e}", exc_info=True)
        await send_telegram_message(
            chat_id,
            "❌ Помилка при обробці документа. Спробуйте ще раз."
        )
