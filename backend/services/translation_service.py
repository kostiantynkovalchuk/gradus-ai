import os
from anthropic import Anthropic
from typing import Dict, Optional
from datetime import datetime
import logging
from config.models import CLAUDE_MODEL_CONTENT

logger = logging.getLogger(__name__)

class TranslationService:
    def __init__(self):
        self.claude_api_key = os.getenv('ANTHROPIC_API_KEY')
        self.client = Anthropic(api_key=self.claude_api_key) if self.claude_api_key else None
        
        from services.notification_service import notification_service
        self.notification_service = notification_service
    
    def translate_article(self, article_data: Dict) -> Dict[str, str]:
        """
        Translate article title and content separately
        
        Args:
            article_data: Dict with 'title' and 'content' or 'summary'
            
        Returns:
            Dict with 'title' and 'content' keys
        """
        if not self.client:
            logger.error("Claude API client not initialized")
            return {"title": "", "content": ""}
        
        title = article_data.get('title', '')
        content = article_data.get('content') or article_data.get('summary', '')
        
        title_prompt = f"""Переведи только заголовок статьи на украинский язык профессионально:

{title}

Верни только переведенный заголовок, без дополнительных слов."""

        content_prompt = f"""Переведи текст статьи на украинский язык профессионально:

{content}

Требования:
- Сохрани термины и бренды как есть
- Естественный украинский язык
- Информативный стиль

Верни только переведенный текст."""

        try:
            title_message = self.client.messages.create(
                model=CLAUDE_MODEL_CONTENT,
                max_tokens=200,
                messages=[{"role": "user", "content": title_prompt}]
            )
            translated_title = title_message.content[0].text.strip()
            
            content_message = self.client.messages.create(
                model=CLAUDE_MODEL_CONTENT,
                max_tokens=4000,
                messages=[{"role": "user", "content": content_prompt}]
            )
            translated_content = content_message.content[0].text.strip()
            
            logger.info(f"Translated article: {title[:50]}...")
            
            return {
                "title": translated_title,
                "content": translated_content
            }
            
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return {"title": "", "content": ""}
    
    def translate_article_with_notification(self, article_data: Dict, article_id: int, image_url: str = None) -> tuple[Dict[str, str], bool]:
        """
        Translate article and send Telegram notification with image
        
        Args:
            article_data: Dict with article info
            article_id: Database ID of the article
            image_url: Optional image URL to include in notification
            
        Returns:
            Tuple of (Dict with 'title' and 'content', notification_sent boolean)
        """
        translation = self.translate_article(article_data)
        notification_sent = False
        
        if translation and translation.get('title') and translation.get('content'):
            notification_data = {
                'id': article_id,
                'source': 'The Spirits Business',
                'title': translation['title'],
                'translated_text': translation['content'],
                'image_url': image_url,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M')
            }
            
            try:
                result = self.notification_service.send_approval_notification(notification_data)
                if result:
                    notification_sent = True
                    logger.info(f"Notification sent for article {article_id}")
                else:
                    logger.warning(f"Notification failed for article {article_id}")
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")
        
        return translation, notification_sent
    
    def translate_batch(self, articles: list) -> Dict[int, str]:
        """
        Translate multiple articles
        
        Returns:
            Dict mapping article IDs to translations
        """
        translations = {}
        
        for article in articles:
            article_id = article.get('id')
            translation = self.translate_article(article)
            
            if translation:
                translations[article_id] = translation
        
        return translations

translation_service = TranslationService()
