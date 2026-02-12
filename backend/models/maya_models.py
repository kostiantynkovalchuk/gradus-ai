from sqlalchemy import Column, Integer, String, Text, TIMESTAMP, DECIMAL, Date, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from . import Base


class MayaUser(Base):
    __tablename__ = "maya_users"
    
    email = Column(String(255), primary_key=True)
    name = Column(String(255), nullable=False)
    position = Column(String(100))
    
    questions_today = Column(Integer, default=0)
    questions_limit = Column(Integer, default=5)
    last_question_at = Column(TIMESTAMP)
    last_reset_date = Column(Date, server_default=func.current_date())
    
    subscription_tier = Column(String(50), default='free')
    subscription_status = Column(String(50), default='active')
    subscription_started_at = Column(TIMESTAMP)
    subscription_expires_at = Column(TIMESTAMP)
    
    liqpay_order_id = Column(String(255))
    
    registered_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        CheckConstraint("subscription_tier IN ('free', 'standard', 'premium')", name='valid_tier'),
        CheckConstraint("subscription_status IN ('active', 'cancelled', 'expired', 'trial')", name='valid_status'),
    )


class MayaSubscription(Base):
    __tablename__ = "maya_subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False)
    
    tier = Column(String(50), nullable=False)
    billing_cycle = Column(String(20), nullable=False)
    amount = Column(DECIMAL(10, 2), nullable=False)
    currency = Column(String(3), default='USD')
    
    liqpay_order_id = Column(String(255), unique=True)
    payment_status = Column(String(50), default='pending')
    payment_data = Column(JSONB)
    
    started_at = Column(TIMESTAMP)
    expires_at = Column(TIMESTAMP)
    
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        CheckConstraint("tier IN ('standard', 'premium')", name='valid_sub_tier'),
        CheckConstraint("billing_cycle IN ('monthly', 'annual')", name='valid_cycle'),
        CheckConstraint("payment_status IN ('pending', 'success', 'failed', 'refunded')", name='valid_payment_status'),
    )


class MayaQueryLog(Base):
    __tablename__ = "maya_query_log"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False)
    
    query_text = Column(Text, nullable=False)
    response_text = Column(Text)
    tokens_used = Column(Integer)
    response_time_ms = Column(Integer)
    
    session_id = Column(String(255))
    user_tier = Column(String(50))
    
    created_at = Column(TIMESTAMP, server_default=func.now())
