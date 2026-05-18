"""
Tests for the Notifier service.

Key invariants:
  1. Successful send → notification_log row with delivery_status='sent'
  2. Forbidden error → bot_user.is_active=False + log row with 'blocked'
  3. BadRequest error → log row with 'failed', no exception raised
  4. NetworkError → exception is re-raised (caller retries next cycle)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.error import BadRequest, Forbidden, NetworkError

from tenderlot_bot.models.bot_state import BotUser, NotificationLog, NotificationType
from tenderlot_bot.services.bot_state_repo import BotStateRepo
from tenderlot_bot.services.notifier import NotificationResult, Notifier
from tests.conftest import make_bot_user, make_tender, make_tlot_user


@pytest_asyncio.fixture
async def active_bot_user(bot_session: AsyncSession) -> BotUser:
    bu = make_bot_user(telegram_id=999000111)
    bot_session.add(bu)
    await bot_session.commit()
    await bot_session.refresh(bu)
    return bu


class TestNotifierSend:
    async def test_successful_send_creates_log_row(
        self,
        state_repo: BotStateRepo,
        bot_session: AsyncSession,
        active_bot_user: BotUser,
        mock_bot: MagicMock,
    ) -> None:
        """Happy path: message sent → log row with status='sent'."""
        mock_bot.send_message.return_value = MagicMock(message_id=77)
        notifier = Notifier(bot=mock_bot, state_repo=state_repo)

        tender = make_tender()
        tender.id = 1  # type: ignore[assignment]

        result = await notifier.send_tender_start(active_bot_user, tender)

        assert result == NotificationResult.SENT
        mock_bot.send_message.assert_called_once()

        # Check notification_log row
        log = await bot_session.scalar(
            select(NotificationLog).where(
                NotificationLog.bot_user_id == active_bot_user.id,
                NotificationLog.tender_id == 1,
                NotificationLog.delivery_status == "sent",
            )
        )
        assert log is not None
        assert log.telegram_message_id == 77

    async def test_forbidden_marks_user_inactive(
        self,
        state_repo: BotStateRepo,
        bot_session: AsyncSession,
        active_bot_user: BotUser,
        mock_bot: MagicMock,
    ) -> None:
        """Forbidden (user blocked bot) → is_active=False + log row 'blocked'."""
        mock_bot.send_message.side_effect = Forbidden("bot was blocked by the user")
        notifier = Notifier(bot=mock_bot, state_repo=state_repo)

        tender = make_tender()
        tender.id = 2  # type: ignore[assignment]

        result = await notifier.send_tender_start(active_bot_user, tender)

        assert result == NotificationResult.BLOCKED

        # Refresh to get updated is_active
        await bot_session.refresh(active_bot_user)
        assert active_bot_user.is_active is False

        # Log row should exist with 'blocked'
        log = await bot_session.scalar(
            select(NotificationLog).where(
                NotificationLog.bot_user_id == active_bot_user.id,
                NotificationLog.delivery_status == "blocked",
            )
        )
        assert log is not None

    async def test_bad_request_returns_failed(
        self,
        state_repo: BotStateRepo,
        bot_session: AsyncSession,
        active_bot_user: BotUser,
        mock_bot: MagicMock,
    ) -> None:
        """BadRequest → NotificationResult.FAILED, no exception raised to caller."""
        mock_bot.send_message.side_effect = BadRequest("message text is empty")
        notifier = Notifier(bot=mock_bot, state_repo=state_repo)

        tender = make_tender()
        tender.id = 3  # type: ignore[assignment]

        result = await notifier.send_tender_start(active_bot_user, tender)

        assert result == NotificationResult.FAILED

        log = await bot_session.scalar(
            select(NotificationLog).where(
                NotificationLog.bot_user_id == active_bot_user.id,
                NotificationLog.delivery_status == "failed",
            )
        )
        assert log is not None
        assert log.error_message is not None

    async def test_network_error_is_reraised(
        self,
        state_repo: BotStateRepo,
        active_bot_user: BotUser,
        mock_bot: MagicMock,
    ) -> None:
        """NetworkError is re-raised so the polling worker can retry next cycle."""
        mock_bot.send_message.side_effect = NetworkError("connection timeout")
        notifier = Notifier(bot=mock_bot, state_repo=state_repo)

        tender = make_tender()
        tender.id = 4  # type: ignore[assignment]

        with pytest.raises(NetworkError):
            await notifier.send_tender_start(active_bot_user, tender)
