import os
from anthropic import Anthropic
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class TranslationService:
    def __init__(self):
        self.claude_api_key = os.getenv('ANTHROPIC_API_KEY')
        self.client = Anthropic(api_key=self.claude_api_key) if self.claude_api_key else None
    
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
