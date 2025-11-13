import os
from anthropic import Anthropic
from typing import Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class TranslationService:
    def __init__(self):
        self.claude_api_key = os.getenv('ANTHROPIC_API_KEY')
        self.client = Anthropic(api_key=self.claude_api_key) if self.claude_api_key else None
        
        from services.notification_service import notification_service
        self.notification_service = notification_service
    
    def translate_article(self, article_data: Dict) -> Optional[str]:
        """
        Translate article from English to Ukrainian using Claude
        
        Args:
            article_data: Dict with 'title' and 'content' or 'summary'
            
        Returns:
            Ukrainian translation or None if failed
        """
        if not self.client:
            logger.error("Claude API client not initialized")
            return None
        
        title = article_data.get('title', '')
        content = article_data.get('content') or article_data.get('summary', '')
        
        full_text = f"{title}\n\n{content}"
        
        prompt = f"""Переведи следующую статью о спиртных напитках на украинский язык.

Требования к переводу:
- Профессиональный стиль для алкогольной индустрии
- Сохрани все термины и названия брендов как есть (например: vodka → vodka, не горілка)
- Естественный украинский язык, не дословный перевод
- Сохрани структуру и форматирование
- Tone of voice: информативный, но не сухой

СТАТЬЯ:

{full_text}

Переведи только текст статьи, без комментариев."""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            translation = message.content[0].text.strip()
            logger.info(f"Translated article: {title[:50]}...")
            return translation
            
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return None
    
    def translate_article_with_notification(self, article_data: Dict, article_id: int) -> tuple[Optional[str], bool]:
        """
        Translate article and send Telegram notification
        
        Args:
            article_data: Dict with article info
            article_id: Database ID of the article
            
        Returns:
            Tuple of (Ukrainian translation or None, notification_sent boolean)
        """
        translation = self.translate_article(article_data)
        notification_sent = False
        
        if translation:
            notification_data = {
                'id': article_id,
                'source': 'The Spirits Business',
                'title': article_data.get('title', 'No title'),
                'translated_text': translation,
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
