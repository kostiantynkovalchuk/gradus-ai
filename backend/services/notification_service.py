import logging
from typing import Optional

logger = logging.getLogger(__name__)

class NotificationService:
    """
    Service for sending notifications to moderators.
    Supports email and Telegram notifications.
    """
    
    def __init__(self):
        self.email_enabled = False
        self.telegram_enabled = False
        logger.info("NotificationService initialized")
    
    async def notify_new_content(self, content_id: int, title: str) -> bool:
        """
        Notify moderators when new content needs approval.
        """
        try:
            message = f"New content needs approval:\nID: {content_id}\nTitle: {title}"
            
            logger.info(f"Notification: {message}")
            
            return True
            
        except Exception as e:
            logger.error(f"Notification error: {str(e)}")
            return False
    
    async def notify_content_approved(self, content_id: int, moderator: str) -> bool:
        """
        Notify when content is approved.
        """
        try:
            message = f"Content #{content_id} approved by {moderator}"
            logger.info(f"Notification: {message}")
            return True
        except Exception as e:
            logger.error(f"Notification error: {str(e)}")
            return False

notification_service = NotificationService()
