from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, CheckConstraint, ARRAY, JSON, Boolean, LargeBinary
from sqlalchemy.sql import func
from .import Base

class ContentQueue(Base):
    __tablename__ = "content_queue"
    
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String(20), nullable=False)
    source = Column(String(255))
    source_url = Column(String(500))
    source_title = Column(Text)
    original_text = Column(Text)
    translated_title = Column(Text)
    translated_text = Column(Text)
    image_url = Column(Text)
    image_prompt = Column(Text)
    local_image_path = Column(Text)
    image_data = Column(LargeBinary)  # Persistent image storage (binary data)
    scheduled_post_time = Column(TIMESTAMP)
    platforms = Column(ARRAY(String))
    created_at = Column(TIMESTAMP, server_default=func.now())
    reviewed_at = Column(TIMESTAMP)
    reviewed_by = Column(String(100))
    rejection_reason = Column(Text)
    edit_history = Column(JSON)
    extra_metadata = Column(JSON)
    analytics = Column(JSON)
    posted_at = Column(TIMESTAMP)
    
    # Language support fields
    language = Column(String(10), default='en')
    needs_translation = Column(Boolean, default=True)
    
    # Notification tracking to prevent duplicate Telegram notifications
    notification_sent = Column(Boolean, default=False)
    
    # Article category for filtering
    category = Column(String(20), nullable=True, default=None)
    
    # Unsplash image attribution (API compliance)
    image_credit = Column(String(255), nullable=True)
    image_credit_url = Column(String(500), nullable=True)
    image_photographer = Column(String(255), nullable=True)
    unsplash_image_id = Column(String(100), nullable=True)
    
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'pending_approval', 'approved', 'rejected', 'posted', 'posting_facebook', 'posting_linkedin')",
            name='valid_status'
        ),
    )

class ApprovalLog(Base):
    __tablename__ = "approval_log"
    
    id = Column(Integer, primary_key=True, index=True)
    content_id = Column(Integer, nullable=False)
    action = Column(String(50))
    moderator = Column(String(100))
    timestamp = Column(TIMESTAMP, server_default=func.now())
    details = Column(JSON)


class MediaFile(Base):
    """Store Telegram file_ids for reusable media (videos, images, etc.)"""
    __tablename__ = "media_files"
    
    id = Column(Integer, primary_key=True, index=True)
    media_type = Column(String(50), nullable=False)  # 'video', 'image', 'document'
    media_key = Column(String(100), nullable=False, unique=True)  # e.g., 'bestbrands_presentation'
    file_id = Column(String(255), nullable=False)  # Telegram file_id
    description = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
