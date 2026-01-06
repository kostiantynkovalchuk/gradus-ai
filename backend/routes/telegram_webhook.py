"""
Unified Telegram Webhook Handler
Handles BOTH:
1. Approval callbacks (approve/reject buttons)
2. Maya bot chat messages
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
import os
import httpx
import logging
from models import get_db
from services.telegram_webhook import telegram_webhook_handler

logger = logging.getLogger(__name__)
router = APIRouter()

TELEGRAM_MAYA_BOT_TOKEN = os.getenv("TELEGRAM_MAYA_BOT_TOKEN")


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
                    "Я завжди рада допомогти!"
                )
            elif text == "/help":
                await send_telegram_message(
                    chat_id,
                    "Я Maya - ваш AI-консультант з алкогольної індустрії! 🥂\n\n"
                    "Можу розповісти про:\n"
                    "• Бренди Best Brands (GREENDAY, HELSINKI, UKRAINKA)\n"
                    "• DOVBUSH коньяк\n"
                    "• Коктейлі та їх приготування\n"
                    "• Маркетингові тренди\n\n"
                    "Просто напишіть питання!"
                )
            return
        
        from services.bestbrands_video import detect_bestbrands_trigger, handle_bestbrands_request
        
        if detect_bestbrands_trigger(text):
            logger.info(f"🎬 Best Brands trigger detected from {chat_id}")
            await send_typing_action(chat_id)
            success = await handle_bestbrands_request(chat_id)
            if success:
                logger.info(f"✅ Best Brands video/text sent to {chat_id}")
                return
            logger.warning(f"Best Brands handler failed, falling back to AI")
        
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
