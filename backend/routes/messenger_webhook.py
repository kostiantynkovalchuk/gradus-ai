from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response
import os
import httpx
import logging
from services.facebook_poster import facebook_poster

logger = logging.getLogger(__name__)
router = APIRouter()

VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN", "gradus_maya_webhook_2025")
APP_SECRET = os.getenv("FACEBOOK_APP_SECRET")
PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
MAYA_PERSONA_ID = os.getenv("MAYA_PERSONA_ID")


@router.get("/webhook")
async def verify_messenger_webhook(request: Request):
    """
    Facebook Messenger webhook verification.
    Called when setting up webhook in Facebook App.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    logger.info(f"📞 Webhook verification request - mode: {mode}, token matches: {token == VERIFY_TOKEN}")
    
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("✅ Messenger webhook verified successfully!")
        return Response(content=challenge, media_type="text/plain")
    else:
        logger.warning(f"❌ Webhook verification failed - expected token: {VERIFY_TOKEN[:10]}...")
        raise HTTPException(status_code=403, detail="Verification token mismatch")


@router.post("/webhook")
async def handle_messenger_webhook(request: Request):
    """
    Handle incoming Facebook Messenger messages.
    Connects users to Maya avatar.
    """
    data = await request.json()
    
    if data.get("object") == "page":
        for entry in data.get("entry", []):
            for event in entry.get("messaging", []):
                await process_messenger_event(event)
    
    return {"status": "received"}


async def process_messenger_event(event: dict):
    """Process individual Messenger event"""
    sender_id = None
    try:
        sender_id = event.get("sender", {}).get("id")
        message = event.get("message", {})
        
        if message.get("is_echo"):
            return
        
        message_text = message.get("text", "")
        
        if not message_text or not sender_id:
            return
        
        logger.info(f"📨 Messenger message from {sender_id}: {message_text[:50]}...")
        
        user_info = await get_facebook_user_info(sender_id)
        user_name = user_info.get("first_name", "Friend")
        
        await send_typing_indicator(sender_id, True)
        
        try:
            from routes.chat_endpoints import chat_with_avatars, ChatRequest
            
            chat_request = ChatRequest(
                message=message_text,
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
        
        await send_messenger_reply(sender_id, response_text)
        
        logger.info(f"✅ Maya responded to {user_name} ({sender_id})")
        
    except Exception as e:
        logger.error(f"❌ Error processing Messenger event: {e}")
        if sender_id:
            try:
                await send_messenger_reply(
                    sender_id, 
                    "Вибачте, виникла помилка. Наша команда вже працює над цим! 🔧"
                )
            except:
                pass


async def get_facebook_user_info(user_id: str) -> dict:
    """Get user profile info from Facebook Graph API"""
    if not facebook_poster.page_access_token:
        return {}
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://graph.facebook.com/v18.0/{user_id}",
                params={
                    "fields": "first_name,last_name",
                    "access_token": facebook_poster.page_access_token
                }
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        logger.warning(f"⚠️ Error getting Facebook user info: {e}")
    
    return {}


async def send_typing_indicator(recipient_id: str, typing: bool):
    """Show/hide typing indicator as Maya"""
    if not facebook_poster.page_access_token:
        return
    
    try:
        payload = {
            "recipient": {"id": recipient_id},
            "sender_action": "typing_on" if typing else "typing_off"
        }
        
        if MAYA_PERSONA_ID:
            payload["persona_id"] = MAYA_PERSONA_ID
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"https://graph.facebook.com/v18.0/{PAGE_ID}/messages",
                params={"access_token": facebook_poster.page_access_token},
                json=payload
            )
    except Exception as e:
        logger.warning(f"⚠️ Error sending typing indicator: {e}")


async def send_messenger_reply(recipient_id: str, text: str):
    """Send message as Maya persona"""
    if not facebook_poster.page_access_token:
        logger.error("❌ No Facebook access token available")
        return
    
    try:
        max_length = 2000
        
        if len(text) > max_length:
            messages = [text[i:i+max_length] for i in range(0, len(text), max_length)]
        else:
            messages = [text]
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            for msg in messages:
                payload = {
                    "recipient": {"id": recipient_id},
                    "message": {"text": msg},
                    "messaging_type": "RESPONSE"
                }
                
                if MAYA_PERSONA_ID:
                    payload["persona_id"] = MAYA_PERSONA_ID
                    logger.info(f"📸 Sending as Maya persona")
                
                response = await client.post(
                    f"https://graph.facebook.com/v18.0/{PAGE_ID}/messages",
                    params={"access_token": facebook_poster.page_access_token},
                    json=payload
                )
                
                if response.status_code != 200:
                    logger.error(f"❌ Facebook send error: {response.text}")
                    raise Exception(f"Facebook API error: {response.status_code}")
                
                logger.info(f"✅ Message sent as Maya to {recipient_id}")
    
    except Exception as e:
        logger.error(f"❌ Error sending Messenger reply: {e}")
        raise


@router.post("/persona/create")
async def create_maya_persona(request: Request):
    """
    Create or update Maya's Messenger persona with profile photo.
    Returns the new persona_id to save in environment variables.
    """
    if not facebook_poster.page_access_token:
        raise HTTPException(status_code=500, detail="Facebook access token not configured")
    
    if not PAGE_ID:
        raise HTTPException(status_code=500, detail="Facebook Page ID not configured")
    
    # Get the app URL for photo
    app_url = os.getenv("APP_URL", "https://gradus-ai.onrender.com")
    photo_url = f"{app_url}/attached_assets/Maya_Gradus.png"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Create new persona
            response = await client.post(
                f"https://graph.facebook.com/v18.0/{PAGE_ID}/personas",
                params={"access_token": facebook_poster.page_access_token},
                data={
                    "name": "Maya",
                    "profile_picture_url": photo_url
                }
            )
            
            if response.status_code != 200:
                error_data = response.json()
                logger.error(f"❌ Persona creation failed: {error_data}")
                raise HTTPException(
                    status_code=response.status_code, 
                    detail=f"Facebook API error: {error_data.get('error', {}).get('message', 'Unknown error')}"
                )
            
            result = response.json()
            new_persona_id = result.get("id")
            
            logger.info(f"✅ Maya persona created with ID: {new_persona_id}")
            
            return {
                "success": True,
                "persona_id": new_persona_id,
                "photo_url": photo_url,
                "message": f"Maya persona created! Add MAYA_PERSONA_ID={new_persona_id} to your environment variables."
            }
            
    except httpx.RequestError as e:
        logger.error(f"❌ Network error creating persona: {e}")
        raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")


@router.get("/persona/list")
async def list_personas():
    """List all personas for the Facebook page"""
    if not facebook_poster.page_access_token or not PAGE_ID:
        raise HTTPException(status_code=500, detail="Facebook credentials not configured")
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://graph.facebook.com/v18.0/{PAGE_ID}/personas",
                params={"access_token": facebook_poster.page_access_token}
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="Failed to fetch personas")
            
            data = response.json()
            return {
                "personas": data.get("data", []),
                "current_maya_id": MAYA_PERSONA_ID
            }
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Network error: {str(e)}")
