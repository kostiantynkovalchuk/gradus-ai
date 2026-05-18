"""
Read/write repository for the bot's own state database.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tenderlot_bot.models.bot_state import BotUser, NotificationLog, NotificationType

logger = logging.getLogger(__name__)


class BotStateRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── BotUser ────────────────────────────────────────────────────────────────

    async def get_bot_user(self, telegram_id: int) -> BotUser | None:
        result = await self._session.execute(
            select(BotUser).where(BotUser.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_active_bot_users_for_tlot_users(
        self, tenderlot_user_ids: list[int]
    ) -> Sequence[BotUser]:
        """Return active BotUser rows whose tenderlot_user_id is in the given list."""
        result = await self._session.execute(
            select(BotUser).where(
                BotUser.tenderlot_user_id.in_(tenderlot_user_ids),
                BotUser.is_active.is_(True),
            )
        )
        return result.scalars().all()

    async def create_bot_user(
        self,
        telegram_id: int,
        telegram_username: str | None,
        phone: str,
        tenderlot_user_id: int,
        consent_given_at: datetime,
    ) -> BotUser:
        now = datetime.now(UTC)
        bot_user = BotUser(
            telegram_id=telegram_id,
            telegram_username=telegram_username,
            phone=phone,
            tenderlot_user_id=tenderlot_user_id,
            consent_given_at=consent_given_at,
            linked_at=now,
            is_active=True,
        )
        self._session.add(bot_user)
        await self._session.commit()
        await self._session.refresh(bot_user)
        logger.info("[BotStateRepo] Created bot_user for telegram_id=%d", telegram_id)
        return bot_user

    async def reactivate_bot_user(self, bot_user: BotUser, consent_given_at: datetime) -> None:
        now = datetime.now(UTC)
        bot_user.is_active = True
        bot_user.unlinked_at = None
        bot_user.linked_at = now
        bot_user.consent_given_at = consent_given_at
        await self._session.commit()
        logger.info("[BotStateRepo] Reactivated bot_user id=%d", bot_user.id)

    async def deactivate_bot_user(self, bot_user: BotUser) -> None:
        bot_user.is_active = False
        bot_user.unlinked_at = datetime.now(UTC)
        await self._session.commit()
        logger.info("[BotStateRepo] Deactivated bot_user id=%d", bot_user.id)

    # ── NotificationLog ────────────────────────────────────────────────────────

    async def get_already_notified_user_ids(
        self,
        tender_id: int,
        notification_type: NotificationType,
        bot_user_ids: list[int],
    ) -> set[int]:
        """
        Return the subset of bot_user_ids that already have a notification_log
        row for this (tender_id, notification_type) pair.
        """
        result = await self._session.execute(
            select(NotificationLog.bot_user_id).where(
                NotificationLog.tender_id == tender_id,
                NotificationLog.notification_type == notification_type.value,
                NotificationLog.bot_user_id.in_(bot_user_ids),
            )
        )
        return {row[0] for row in result}

    async def log_notification(
        self,
        bot_user_id: int,
        tender_id: int,
        notification_type: NotificationType,
        delivery_status: str,
        telegram_message_id: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """
        Insert a notification_log row.
        Silently ignores duplicate-send races (unique constraint).
        """
        log = NotificationLog(
            bot_user_id=bot_user_id,
            tender_id=tender_id,
            notification_type=notification_type.value,
            sent_at=datetime.now(UTC),
            telegram_message_id=telegram_message_id,
            delivery_status=delivery_status,
            error_message=error_message,
        )
        self._session.add(log)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            logger.debug(
                "[BotStateRepo] Duplicate notification suppressed: "
                "bot_user_id=%d tender_id=%d type=%s",
                bot_user_id,
                tender_id,
                notification_type.value,
            )

    async def count_notifications_this_week(self, bot_user_id: int) -> int:
        """Count successfully sent notifications for a user in the last 7 days."""
        from datetime import timedelta

        from sqlalchemy import func

        since = datetime.now(UTC) - timedelta(days=7)
        result = await self._session.scalar(
            select(func.count())
            .select_from(NotificationLog)
            .where(
                NotificationLog.bot_user_id == bot_user_id,
                NotificationLog.delivery_status == "sent",
                NotificationLog.sent_at >= since,
            )
        )
        return result or 0
