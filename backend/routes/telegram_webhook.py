from fastapi import APIRouter, Request
from fastapi.responses import Response
import os
import httpx
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

TELEGRAM_MAYA_BOT_TOKEN = os.getenv("TELEGRAM_MAYA_BOT_TOKEN")


@router.post("/webhook")
async def handle_telegram_webhook(request: Request):
    """Handle incoming Telegram messages"""
    
    data = await request.json()
    
    if "message" in data:
        await process_telegram_message(data["message"])
    
    return {"ok": True}


async def process_telegram_message(message: dict):
    """Process individual Telegram message"""
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
                    "• Бренди BestBrands (GREENDAY, HELSINKI, UKRAINKA, MARLIN)\n"
                    "• DOVBUSH коньяк\n"
                    "• Коктейлі та їх приготування\n"
                    "• Маркетингові тренди\n\n"
                    "Просто напишіть питання!"
                )
            return
        
        logger.info(f"📨 Telegram message from {chat_id}: {text[:50]}...")
        
        await send_typing_action(chat_id)
        
        try:
            from routes.chat_endpoints import chat_with_avatars, ChatRequest
            
            chat_request = ChatRequest(
                message=text,
                avatar="maya"
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
    """Send message to Telegram user"""
    if not TELEGRAM_MAYA_BOT_TOKEN:
        logger.error("❌ No Telegram bot token available")
        return
    
    try:
        max_length = 4096
        
        if len(text) > max_length:
            messages = [text[i:i+max_length] for i in range(0, len(text), max_length)]
        else:
            messages = [text]
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            for msg in messages:
                response = await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": msg,
                        "parse_mode": "Markdown"
                    },
                    timeout=10.0
                )
                
                if response.status_code != 200:
                    logger.error(f"❌ Telegram send error: {response.text}")
                    raise Exception(f"Telegram API error: {response.status_code}")
                
                logger.info(f"✅ Message sent to Telegram chat {chat_id}")
    
    except Exception as e:
        logger.error(f"❌ Error sending Telegram message: {e}")
        raise
