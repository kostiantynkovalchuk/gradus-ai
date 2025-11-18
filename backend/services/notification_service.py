import os
import requests
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
    
    def send_approval_notification(self, content_data: Dict[str, Any]) -> bool:
        """Send notification when content needs approval"""
        
        message = f"""
🆕 <b>Новий контент для перевірки</b>

📰 <b>Джерело:</b> {content_data.get('source', 'Unknown')}
📝 <b>Заголовок:</b> {content_data.get('title', 'No title')}

🇺🇦 <b>Переклад (перші 150 символів):</b>
{content_data.get('translated_text', '')[:150]}...

🔗 <b>ID:</b> {content_data.get('id')}
⏰ <b>Час:</b> {content_data.get('created_at', '')}
        """
        
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            
            if result.get('ok'):
                logger.info(f"Notification sent for content {content_data.get('id')}")
                return True
            else:
                logger.error(f"Telegram API error: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False
    
    def notify_content_approved(self, content_data: Dict[str, Any]) -> bool:
        """
        Send notification when content is approved and ready to post
        
        Args:
            content_data: Dict with approved content info
            
        Returns:
            True if notification sent successfully
        """
        message = f"""
✅ <b>Контент затверджено!</b>

📰 <b>Заголовок:</b> {content_data.get('title', 'No title')}
📅 <b>Запланований постинг:</b> {content_data.get('scheduled_time', 'Відразу')}
🔗 <b>ID:</b> {content_data.get('id')}

Контент буде опубліковано відповідно до розкладу.
        """
        
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            
            if result.get('ok'):
                logger.info(f"Approval notification sent for content {content_data.get('id')}")
                return True
            else:
                logger.error(f"Telegram API error: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send approval notification: {e}")
            return False
    
    def notify_content_posted(self, content_data: Dict[str, Any]) -> bool:
        """
        Send notification when content is successfully posted to social media
        
        Args:
            content_data: Dict with posted content info
            
        Returns:
            True if notification sent successfully
        """
        message = f"""
🎉 <b>Контент опубліковано!</b>

📰 <b>Заголовок:</b> {content_data.get('title', 'No title')}
📱 <b>Платформи:</b> {', '.join(content_data.get('platforms', []))}
🔗 <b>Facebook:</b> {content_data.get('fb_post_url', 'N/A')}
⏰ <b>Час:</b> {content_data.get('posted_at', '')}

Контент успішно опубліковано на соціальних мережах!
        """
        
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            
            if result.get('ok'):
                logger.info(f"Posted notification sent for content {content_data.get('id')}")
                return True
            else:
                logger.error(f"Telegram API error: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send posted notification: {e}")
            return False
    
    def send_test_notification(self) -> Dict[str, Any]:
        """Send test notification"""
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": "🧪 Тестове повідомлення від Gradus AI\n\n✅ Сервіс працює коректно!",
            "parse_mode": "HTML"
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            return response.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

notification_service = NotificationService()
