from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, CheckConstraint, ARRAY, JSON
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
    scheduled_post_time = Column(TIMESTAMP)
    platforms = Column(ARRAY(String))
    created_at = Column(TIMESTAMP, server_default=func.now())
    reviewed_at = Column(TIMESTAMP)
    reviewed_by = Column(String(100))
    rejection_reason = Column(Text)
    edit_history = Column(JSON)
    extra_metadata = Column(JSON)
    analytics = Column(JSON)
    
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'pending_approval', 'approved', 'rejected', 'posted')",
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
