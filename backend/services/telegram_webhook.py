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
            
            self._answer_callback_query(callback_id, "❌ Unknown action")
            return {"status": "error", "message": "Unknown callback data"}
            
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing callback data '{callback_data}': {e}")
            self._answer_callback_query(callback_id, "❌ Invalid request")
            return {"status": "error", "message": "Invalid callback format"}
    
    def _approve_content(self, content_id: int, callback_id: str, message: Dict, db: Session) -> Dict:
        """Approve content and post to Facebook with proper transaction handling"""
        
        try:
            article = db.query(ContentQueue).filter(ContentQueue.id == content_id).first()
            
            if not article:
                self._answer_callback_query(callback_id, "❌ Article not found")
                return {"status": "error", "message": "Article not found"}
            
            if article.status != 'pending_approval':
                self._answer_callback_query(callback_id, f"⚠️ Already {article.status}")
                return {"status": "error", "message": f"Article already {article.status}"}
            
            post_data = {
                'translated_title': article.translated_title or (article.extra_metadata.get('title', '') if article.extra_metadata else ''),
                'translated_content': article.translated_text or '',
                'url': article.source_url or '',
                'source': article.source or 'The Spirits Business',
                'author': (article.extra_metadata.get('author', '') if article.extra_metadata else ''),
                'image_url': article.image_url,
                'local_image_path': article.local_image_path
            }
            
            fb_result = facebook_poster.post_with_image(post_data)
            
            if not fb_result:
                self._answer_callback_query(callback_id, "❌ Facebook posting failed")
                return {"status": "error", "message": "Facebook posting failed, approval cancelled", "content_id": content_id}
            
            try:
                article.status = 'posted'
                article.reviewed_at = datetime.utcnow()
                article.reviewed_by = 'telegram_bot'
                
                if not article.extra_metadata:
                    article.extra_metadata = {}
                article.extra_metadata['fb_post_id'] = fb_result['post_id']
                article.extra_metadata['fb_post_url'] = fb_result['post_url']
                
                log_entry = ApprovalLog(
                    content_id=content_id,
                    action="approved_and_posted",
                    moderator="telegram_bot",
                    details={
                        "method": "telegram_inline_button",
                        "fb_post_url": fb_result['post_url']
                    }
                )
                db.add(log_entry)
                db.commit()
                db.refresh(article)
                
                logger.info(f"Content {content_id} approved via Telegram and posted to Facebook: {fb_result['post_url']}")
                
            except Exception as db_error:
                logger.error(f"Database error after Facebook posting for content {content_id}: {db_error}")
                db.rollback()
                self._answer_callback_query(callback_id, "⚠️ Posted to Facebook but DB update failed")
                return {
                    "status": "partial_success", 
                    "message": f"Posted to Facebook but database update failed: {str(db_error)}", 
                    "fb_post_url": fb_result['post_url'],
                    "content_id": content_id
                }
            
            new_caption = f"""✅ <b>Затверджено і опубліковано!</b>

📰 <b>{post_data['translated_title']}</b>

📱 Facebook: {fb_result['post_url']}
⏰ {datetime.utcnow().strftime('%H:%M, %d %b %Y')}"""
            
            caption_updated = self._update_message_caption(message, new_caption)
            if caption_updated:
                self._answer_callback_query(callback_id, "✅ Posted to Facebook!")
            else:
                self._answer_callback_query(callback_id, "✅ Posted! (Notification update failed)")
                logger.warning(f"Content {content_id}: Posted successfully but Telegram caption update failed")
            
            return {"status": "success", "fb_post_url": fb_result['post_url'], "content_id": content_id}
                
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
                self._answer_callback_query(callback_id, f"⚠️ Already {article.status}")
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
    
    def _update_message_caption(self, message: Dict, new_caption: str) -> bool:
        """
        Update Telegram message caption or text
        
        Automatically uses editMessageCaption for photo messages (with caption)
        or editMessageText for text-only messages
        
        Returns:
            True if message updated successfully, False otherwise
        """
        try:
            chat_id = message['chat']['id']
            message_id = message['message_id']
            
            has_photo = 'photo' in message
            
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
