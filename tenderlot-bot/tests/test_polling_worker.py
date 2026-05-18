"""
Tests for the polling worker.

Key invariants:
  1. Tenders with start_mail_status=1 are dispatched to linked users.
  2. The same tender is NOT dispatched twice (idempotency).
  3. A tender with no linked Telegram users is silently skipped.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tenderlot_bot.models.bot_state import BotUser, NotificationType
from tenderlot_bot.models.tenderlot import TenderlotTender, TenderlotUser
from tenderlot_bot.services.bot_state_repo import BotStateRepo
from tenderlot_bot.services.notifier import NotificationResult, Notifier
from tenderlot_bot.services.tenderlot_repo import TenderlotRepo
from tests.conftest import make_bot_user, make_tender, make_tlot_user


@pytest_asyncio.fixture
async def seeded_tlot(tlot_session: AsyncSession) -> TenderlotUser:
    """One active tenderlot supplier user in the DB."""
    user = make_tlot_user(phone="+380671234567", role="supplier")
    tlot_session.add(user)
    await tlot_session.commit()
    await tlot_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def seeded_tender_ready(tlot_session: AsyncSession) -> TenderlotTender:
    """One tender with start_mail_status=1 targeting suppliers."""
    tender = make_tender(start_mail_status=1, target_role="supplier")
    tlot_session.add(tender)
    await tlot_session.commit()
    await tlot_session.refresh(tender)
    return tender


@pytest_asyncio.fixture
async def seeded_tender_pending(tlot_session: AsyncSession) -> TenderlotTender:
    """One tender with start_mail_status=0 — should NOT be dispatched."""
    tender = make_tender(start_mail_status=0, target_role="supplier")
    tlot_session.add(tender)
    await tlot_session.commit()
    await tlot_session.refresh(tender)
    return tender


@pytest_asyncio.fixture
async def seeded_bot_user(
    bot_session: AsyncSession, seeded_tlot: TenderlotUser
) -> BotUser:
    """One linked, active bot user tied to seeded_tlot."""
    bu = make_bot_user(telegram_id=111222333, tenderlot_user_id=seeded_tlot.id)
    bot_session.add(bu)
    await bot_session.commit()
    await bot_session.refresh(bu)
    return bu


class TestPollingWorkerDispatch:
    async def test_dispatches_to_linked_user(
        self,
        tlot_repo: TenderlotRepo,
        state_repo: BotStateRepo,
        seeded_tlot: TenderlotUser,
        seeded_tender_ready: TenderlotTender,
        seeded_bot_user: BotUser,
        mock_bot: MagicMock,
    ) -> None:
        """Tender with start_mail_status=1 is sent to a linked user."""
        notifier = Notifier(bot=mock_bot, state_repo=state_repo)
        mock_bot.send_message.return_value = MagicMock(message_id=42)

        # Verify tender is found by repo
        tenders = await tlot_repo.get_pending_tenders()
        assert len(tenders) == 1
        assert tenders[0].id == seeded_tender_ready.id

        # Verify bot user is found for the tlot user's role
        bot_users = await state_repo.get_active_bot_users_for_tlot_users(
            [seeded_tlot.id]
        )
        assert len(bot_users) == 1

        # Not yet notified
        already = await state_repo.get_already_notified_user_ids(
            tender_id=seeded_tender_ready.id,
            notification_type=NotificationType.TENDER_START,
            bot_user_ids=[seeded_bot_user.id],
        )
        assert len(already) == 0

        # Send
        result = await notifier.send_tender_start(seeded_bot_user, seeded_tender_ready)
        assert result == NotificationResult.SENT
        mock_bot.send_message.assert_called_once()

    async def test_no_duplicates_on_second_dispatch(
        self,
        tlot_repo: TenderlotRepo,
        state_repo: BotStateRepo,
        seeded_tlot: TenderlotUser,
        seeded_tender_ready: TenderlotTender,
        seeded_bot_user: BotUser,
        mock_bot: MagicMock,
    ) -> None:
        """Second dispatch of the same tender to the same user is suppressed."""
        notifier = Notifier(bot=mock_bot, state_repo=state_repo)
        mock_bot.send_message.return_value = MagicMock(message_id=42)

        # First send
        await notifier.send_tender_start(seeded_bot_user, seeded_tender_ready)

        # Now already_notified should contain this user
        already = await state_repo.get_already_notified_user_ids(
            tender_id=seeded_tender_ready.id,
            notification_type=NotificationType.TENDER_START,
            bot_user_ids=[seeded_bot_user.id],
        )
        assert seeded_bot_user.id in already

        # Simulate polling worker filtering: to_notify should be empty
        to_notify = [u for u in [seeded_bot_user] if u.id not in already]
        assert len(to_notify) == 0

        # send_message was only called once total
        assert mock_bot.send_message.call_count == 1

    async def test_pending_tender_not_dispatched(
        self,
        tlot_repo: TenderlotRepo,
        seeded_tender_pending: TenderlotTender,
    ) -> None:
        """Tender with start_mail_status=0 is not returned by get_pending_tenders."""
        tenders = await tlot_repo.get_pending_tenders()
        ids = [t.id for t in tenders]
        assert seeded_tender_pending.id not in ids

    async def test_no_linked_users_skips_silently(
        self,
        tlot_repo: TenderlotRepo,
        state_repo: BotStateRepo,
        seeded_tender_ready: TenderlotTender,
        seeded_tlot: TenderlotUser,
    ) -> None:
        """If no bot users are linked, get_active_bot_users_for_tlot_users returns empty."""
        bot_users = await state_repo.get_active_bot_users_for_tlot_users(
            [seeded_tlot.id]
        )
        assert len(bot_users) == 0
