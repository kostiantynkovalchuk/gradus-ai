"""
Bot's own state tables.

Dev:  SQLite   (bot_database_url = sqlite+aiosqlite:///./tenderlot_bot.db)
Prod: Neon PostgreSQL (swap connection string only)
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class BotBase(DeclarativeBase):
    pass


class NotificationType(StrEnum):
    TENDER_START = "tender_start"
    TENDER_END_REMINDER = "tender_end_reminder"  # future
    BID_OUTBID = "bid_outbid"  # future
    TENDER_CLOSED = "tender_closed"  # future


class BotUser(BotBase):
    """Links a Telegram identity to a tenderlot.net user account."""

    __tablename__ = "bot_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)  # E.164
    tenderlot_user_id: Mapped[int] = mapped_column(Integer, index=True)
    consent_given_at: Mapped[datetime] = mapped_column()
    linked_at: Mapped[datetime] = mapped_column()
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    unlinked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class NotificationLog(BotBase):
    """Immutable record of every Telegram message we attempted to send."""

    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_user_id: Mapped[int] = mapped_column(Integer, index=True)
    tender_id: Mapped[int] = mapped_column(Integer, index=True)
    notification_type: Mapped[str] = mapped_column(String(50))  # NotificationType value
    sent_at: Mapped[datetime] = mapped_column()
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(20))  # "sent"|"failed"|"blocked"
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "bot_user_id",
            "tender_id",
            "notification_type",
            name="uq_no_duplicate_notifications",
        ),
    )
