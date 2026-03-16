import logging
import os
from typing import Dict
from sqlalchemy.orm import Session
from models.content import ContentQueue, ApprovalLog
from datetime import datetime
from services.facebook_poster import facebook_poster
from services.notification_service import notification_service
import requests

logger = logging.getLogger(__name__)

class TelegramWebhookHandler:
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
    
    def handle_callback_query(self, callback_query: Dict, db: Session) -> Dict:
        """
        Handle Telegram inline button callbacks
        
        Args:
            callback_query: Telegram callback query data
            db: Database session
            
        Returns:
            Dict with status and message
        """
        callback_id = callback_query.get('id')
        callback_data = callback_query.get('data')
        message = callback_query.get('message')
        
        if not callback_data:
            return {"status": "error", "message": "No callback data"}
        
        try:
            if callback_data.startswith('approve_'):
                content_id_str = callback_data.split('_')[1]
                if not content_id_str.isdigit():
                    logger.error(f"Invalid content_id in approve callback: {content_id_str}")
                    self._answer_callback_query(callback_id, "❌ Invalid content ID")
                    return {"status": "error", "message": "Invalid content ID"}
                
                content_id = int(content_id_str)
                return self._approve_content(content_id, callback_id, message, db)
                
            elif callback_data.startswith('reject_'):
                content_id_str = callback_data.split('_')[1]
                if not content_id_str.isdigit():
                    logger.error(f"Invalid content_id in reject callback: {content_id_str}")
                    self._answer_callback_query(callback_id, "❌ Invalid content ID")
                    return {"status": "error", "message": "Invalid content ID"}
                
                content_id = int(content_id_str)
                return self._reject_content(content_id, callback_id, message, db)
            
            elif callback_data.startswith('regenerate_'):
                content_id_str = callback_data.split('_')[1]
                if not content_id_str.isdigit():
                    logger.error(f"Invalid content_id in regenerate callback: {content_id_str}")
                    self._answer_callback_query(callback_id, "❌ Invalid content ID")
                    return {"status": "error", "message": "Invalid content ID"}
                
                content_id = int(content_id_str)
                return self._regenerate_image(content_id, callback_id, message, db)
            
            self._answer_callback_query(callback_id, "❌ Unknown action")
            return {"status": "error", "message": "Unknown callback data"}
            
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing callback data '{callback_data}': {e}")
            self._answer_callback_query(callback_id, "❌ Invalid request")
            return {"status": "error", "message": "Invalid callback format"}
    
    def _approve_content(self, content_id: int, callback_id: str, message: Dict, db: Session) -> Dict:
        """
        Approve content for scheduled posting (NO IMMEDIATE POST)
        Marks as 'approved' - scheduler will post at optimal times
        """
        try:
            article = db.query(ContentQueue).filter(ContentQueue.id == content_id).first()
            
            if not article:
                self._answer_callback_query(callback_id, "❌ Article not found")
                return {"status": "error", "message": "Article not found"}
            
            if article.status != 'pending_approval':
                logger.warning(f"Stale approve button clicked for article {content_id} (status: {article.status})")
                self._answer_callback_query(callback_id, f"⚠️ Already {article.status}")
                if message:
                    self._update_message_caption(message, f"⚠️ Article #{content_id} already <b>{article.status}</b>", remove_keyboard=True)
                return {"status": "error", "message": f"Article already {article.status}"}
            
            article.status = 'approved'
            article.reviewed_at = datetime.utcnow()
            article.reviewed_by = 'telegram_bot'
            
            if not article.category:
                try:
                    from services.categorization import categorize_article
                    article.category = categorize_article(
                        article.translated_title or article.source_title,
                        (article.translated_text or article.original_text or "")[:2000],
                        source=article.source
                    )
                    logger.info(f"Auto-categorized article {content_id} as '{article.category}'")
                except Exception as e:
                    logger.warning(f"Auto-categorization failed for {content_id}: {e}")
            
            if not article.extra_metadata:
                article.extra_metadata = {}
            article.extra_metadata['approved_at'] = datetime.utcnow().isoformat()
            article.extra_metadata['approved_by'] = 'telegram'
            
            log_entry = ApprovalLog(
                content_id=content_id,
                action="approved",
                moderator="telegram_bot",
                details={
                    "method": "telegram_inline_button",
                    "note": "Approved for scheduled posting"
                }
            )
            db.add(log_entry)

            # Queue article for Telegram channel posting
            channel_slot_utc = None
            try:
                from services.channel_poster import queue_article_for_channel
                channel_slot_utc = queue_article_for_channel(article, db)
                logger.info(f"Article {content_id} queued for channel at {channel_slot_utc}")
            except Exception as e:
                logger.warning(f"Could not queue article {content_id} for channel: {e}")

            db.commit()
            db.refresh(article)

            # Send channel queue confirmation
            if channel_slot_utc:
                try:
                    from services.channel_poster import send_queue_confirmation
                    send_queue_confirmation(article, channel_slot_utc)
                except Exception as e:
                    logger.warning(f"Could not send channel queue confirmation: {e}")
            
            logger.info(f"Content {content_id} approved via Telegram - scheduled for posting")
            
            title = article.translated_title or (article.extra_metadata.get('title', '') if article.extra_metadata else 'No title')

            from datetime import timezone, timedelta
            KYIV_TZ = timezone(timedelta(hours=2))
            channel_time_str = ""
            if channel_slot_utc:
                slot_kyiv = channel_slot_utc.astimezone(KYIV_TZ)
                channel_time_str = f"\n📢 Канал: {slot_kyiv.strftime('%d.%m.%Y о %H:%M')} за Києвом"

            posting_schedule = f"""📅 <b>Розклад публікації:</b>
• Facebook: Щодня о 18:00
• LinkedIn: Пн/Ср/Пт о 9:00{channel_time_str}

💡 Система автоматично опублікує контент в оптимальний час для максимальної взаємодії."""
            
            new_caption = f"""✅ <b>Контент схвалено!</b>

📰 <b>{title}</b>

✅ Статус: Готово до публікації
🆔 ID: {content_id}

{posting_schedule}"""
            
            caption_updated = self._update_message_caption(message, new_caption)
            if caption_updated:
                self._answer_callback_query(callback_id, "✅ Схвалено! Буде опубліковано за розкладом")
            else:
                self._answer_callback_query(callback_id, "✅ Схвалено для публікації")
                logger.warning(f"Content {content_id}: Approved but Telegram caption update failed")
            
            return {"status": "success", "message": "Content approved for scheduled posting", "content_id": content_id}
                
        except Exception as e:
            logger.error(f"Error approving content {content_id}: {e}")
            db.rollback()
            self._answer_callback_query(callback_id, f"❌ Error: {str(e)[:100]}")
            return {"status": "error", "message": str(e)}
    
    def _reject_content(self, content_id: int, callback_id: str, message: Dict, db: Session) -> Dict:
        """Reject content with proper transaction handling"""
        
        try:
            article = db.query(ContentQueue).filter(ContentQueue.id == content_id).first()
            
            if not article:
                self._answer_callback_query(callback_id, "❌ Article not found")
                return {"status": "error", "message": "Article not found"}
            
            if article.status != 'pending_approval':
                logger.warning(f"Stale reject button clicked for article {content_id} (status: {article.status})")
                self._answer_callback_query(callback_id, f"⚠️ Already {article.status}")
                if message:
                    self._update_message_caption(message, f"⚠️ Article #{content_id} already <b>{article.status}</b>", remove_keyboard=True)
                return {"status": "error", "message": f"Article already {article.status}"}
            
            article.status = 'rejected'
            article.reviewed_at = datetime.utcnow()
            article.reviewed_by = 'telegram_bot'
            article.rejection_reason = 'Rejected via Telegram'
            
            log_entry = ApprovalLog(
                content_id=content_id,
                action="rejected",
                moderator="telegram_bot",
                details={"reason": "Rejected via Telegram inline button"}
            )
            db.add(log_entry)
            db.commit()
            db.refresh(article)
            
            logger.info(f"Content {content_id} rejected via Telegram")
            
            title = article.translated_title or (article.extra_metadata.get('title', 'No title') if article.extra_metadata else 'No title')
            new_caption = f"""❌ <b>Відхилено</b>

📰 <b>{title}</b>

🗑️ Контент відхилено через Telegram
⏰ {datetime.utcnow().strftime('%H:%M, %d %b %Y')}"""
            
            caption_updated = self._update_message_caption(message, new_caption)
            if caption_updated:
                self._answer_callback_query(callback_id, "❌ Rejected")
            else:
                self._answer_callback_query(callback_id, "❌ Rejected (Notification update failed)")
                logger.warning(f"Content {content_id}: Rejected successfully but Telegram caption update failed")
            
            return {"status": "success", "message": "Content rejected", "content_id": content_id}
            
        except Exception as e:
            logger.error(f"Error rejecting content {content_id}: {e}")
            db.rollback()
            self._answer_callback_query(callback_id, f"❌ Error: {str(e)[:100]}")
            return {"status": "error", "message": str(e)}
    
    def _regenerate_image(self, content_id: int, callback_id: str, message: Dict, db: Session) -> Dict:
        """Fetch new image for article from Unsplash"""
        
        try:
            article = db.query(ContentQueue).filter(ContentQueue.id == content_id).first()
            
            if not article:
                self._answer_callback_query(callback_id, "❌ Article not found")
                return {"status": "error", "message": "Article not found"}
            
            if article.status not in ['pending_approval', 'approved', 'draft']:
                self._answer_callback_query(callback_id, f"⚠️ Cannot regenerate - status: {article.status}")
                return {"status": "error", "message": f"Cannot regenerate for status: {article.status}"}
            
            from services.unsplash_service import unsplash_service
            
            last_tier = article.last_tier_used
            tier_attempts = list(article.tier_attempts) if article.tier_attempts else []
            
            if last_tier is not None:
                next_tier = (last_tier + 1) % 4
            else:
                next_tier = (content_id % 4 + 1) % 4
            
            tier_name = unsplash_service.TIER_NAMES[next_tier]
            self._answer_callback_query(callback_id, f"🔄 Fetching new image (Tier {next_tier}: {tier_name})...")
            logger.info(f"🔄 New Image: Article #{content_id}, Last Tier {last_tier} → Next Tier {next_tier}")
            
            title = article.translated_title or article.source_title or ""
            content = article.translated_text or article.original_text or ""
            
            result = unsplash_service.select_image_for_article(title, content, article_id=content_id, start_tier=next_tier)
            
            if not result or not result.get('image_url'):
                self._send_text_message(message['chat']['id'], f"❌ No suitable images found for article #{content_id}")
                return {"status": "error", "message": "No images found"}
            
            article.image_url = result['image_url']
            article.image_photographer = result['image_photographer']
            article.image_credit = result['image_credit']
            article.image_credit_url = result['image_credit_url']
            article.unsplash_image_id = result['unsplash_image_id']
            article.last_tier_used = result.get('last_tier_used')
            new_attempts = result.get('attempted_tiers', [])
            for t in new_attempts:
                if t not in tier_attempts:
                    tier_attempts.append(t)
            article.tier_attempts = tier_attempts
            article.local_image_path = None
            article.image_data = None
            
            db.commit()
            db.refresh(article)
            
            logger.info(f"New image fetched for article {content_id}: {result['image_photographer']} (Tier {result.get('last_tier_used')})")
            
            chat_id = message['chat']['id']
            title = article.translated_title or 'Без заголовка'
            preview_text = (article.translated_text or '')[:150]
            if len(article.translated_text or '') > 150:
                preview_text += "..."
            
            new_caption = f"""🆕 <b>Новий контент для перевірки</b>

📰 <b>{title}</b>

{preview_text}

📰 {article.source or 'GradusMedia'}
🔗 ID: {content_id}
📸 {article.image_photographer or 'Unsplash'} (Tier {result.get('last_tier_used', '?')})"""
            
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Approve & Post", "callback_data": f"approve_{content_id}"},
                        {"text": "❌ Reject", "callback_data": f"reject_{content_id}"}
                    ],
                    [
                        {"text": "🔄 New Image", "callback_data": f"regenerate_{content_id}"}
                    ]
                ]
            }
            
            image_url = result.get('image_url')
            self._send_photo_or_update(chat_id, image_url, new_caption, keyboard, message)
            
            return {"status": "success", "message": "New image fetched", "content_id": content_id}
            
        except Exception as e:
            logger.error(f"Error fetching new image for content {content_id}: {e}")
            db.rollback()
            self._send_text_message(message['chat']['id'], f"❌ Error fetching new image: {str(e)[:100]}")
            return {"status": "error", "message": str(e)}
    
    def _send_photo_or_update(self, chat_id: int, image_url: str, caption: str, keyboard: Dict, old_message: Dict) -> bool:
        """
        Send new photo message and delete the old one to avoid duplicates.
        Telegram doesn't support changing the photo in editMessageCaption,
        so we delete + resend for image changes.
        """
        import json
        try:
            old_message_id = old_message.get('message_id')
            if old_message_id:
                delete_url = f"{self.base_url}/deleteMessage"
                requests.post(delete_url, json={
                    "chat_id": chat_id,
                    "message_id": old_message_id
                }, timeout=5)
            
            url = f"{self.base_url}/sendPhoto"
            payload = {
                "chat_id": chat_id,
                "photo": image_url,
                "caption": caption,
                "parse_mode": "HTML",
                "reply_markup": keyboard
            }
            response = requests.post(url, json=payload, timeout=15)
            result = response.json()
            
            if result.get('ok'):
                logger.info(f"Sent updated photo message to chat {chat_id}")
                return True
            else:
                logger.warning(f"Photo send failed, trying text-only: {result.get('description')}")
                text_url = f"{self.base_url}/sendMessage"
                text_payload = {
                    "chat_id": chat_id,
                    "text": caption,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard
                }
                requests.post(text_url, json=text_payload, timeout=10)
                return True
        except Exception as e:
            logger.error(f"Error in _send_photo_or_update: {e}")
            return False
    
    def _send_text_message(self, chat_id: int, text: str) -> bool:
        """Send a simple text message"""
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            response = requests.post(url, json=payload, timeout=10)
            return response.json().get('ok', False)
        except Exception as e:
            logger.error(f"Error sending text message: {e}")
            return False
    
    def _update_message_caption(self, message: Dict, new_caption: str, remove_keyboard: bool = True) -> bool:
        """
        Update Telegram message caption or text.
        
        When remove_keyboard=True (default), removes inline buttons to prevent
        duplicate actions on already-processed articles.
        """
        try:
            chat_id = message['chat']['id']
            message_id = message['message_id']
            
            has_photo = 'photo' in message
            
            empty_keyboard = {"inline_keyboard": []} if remove_keyboard else None
            
            if has_photo:
                url = f"{self.base_url}/editMessageCaption"
                payload = {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "caption": new_caption,
                    "parse_mode": "HTML"
                }
            else:
                url = f"{self.base_url}/editMessageText"
                payload = {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": new_caption,
                    "parse_mode": "HTML"
                }
            
            if empty_keyboard:
                payload["reply_markup"] = empty_keyboard
            
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            
            if result.get('ok'):
                return True
            else:
                logger.error(f"Failed to update message: {result.get('description', 'Unknown error')}")
                return False
                
        except Exception as e:
            logger.error(f"Exception updating message: {e}")
            return False
    
    def _answer_callback_query(self, callback_id: str, text: str):
        """Answer callback query to remove loading state"""
        url = f"{self.base_url}/answerCallbackQuery"
        payload = {
            "callback_query_id": callback_id,
            "text": text,
            "show_alert": False
        }
        
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to answer callback query: {e}")

telegram_webhook_handler = TelegramWebhookHandler()
