"""
Shared pytest fixtures.

Both databases use in-memory SQLite so tests are fast and isolated.
"""

import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tenderlot_bot.models.bot_state import BotBase, BotUser, NotificationType
from tenderlot_bot.models.tenderlot import TenderlotBase, TenderlotTender, TenderlotUser
from tenderlot_bot.services.bot_state_repo import BotStateRepo
from tenderlot_bot.services.tenderlot_repo import TenderlotRepo

# ── In-memory engines ──────────────────────────────────────────────────────────

_BOT_URL = "sqlite+aiosqlite:///:memory:"
_TLOT_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def bot_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(_BOT_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(BotBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def tlot_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(_TLOT_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(TenderlotBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def state_repo(bot_session: AsyncSession) -> BotStateRepo:
    return BotStateRepo(bot_session)


@pytest_asyncio.fixture
async def tlot_repo(tlot_session: AsyncSession) -> TenderlotRepo:
    return TenderlotRepo(tlot_session)


# ── Sample data helpers ────────────────────────────────────────────────────────

def make_tlot_user(
    phone: str = "+380671234567",
    role: str = "supplier",
    is_active: bool = True,
) -> TenderlotUser:
    return TenderlotUser(
        phone=phone,
        full_name="Тест Тестович",
        email="test@test.ua",
        role=role,
        is_active=is_active,
    )


def make_tender(
    start_mail_status: int = 1,
    target_role: str = "supplier",
) -> TenderlotTender:
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    return TenderlotTender(
        number="TL-TEST-001",
        title="Тестовий тендер",
        tender_type="auction",
        start_price=100_000.0,
        currency="UAH",
        starts_at=now,
        ends_at=now + timedelta(days=5),
        start_mail_status=start_mail_status,
        end_mail_status=0,
        target_role=target_role,
    )


def make_bot_user(
    telegram_id: int = 123456789,
    tenderlot_user_id: int = 1,
    is_active: bool = True,
) -> BotUser:
    now = datetime.now(timezone.utc)
    return BotUser(
        telegram_id=telegram_id,
        telegram_username="testuser",
        phone="+380671234567",
        tenderlot_user_id=tenderlot_user_id,
        consent_given_at=now,
        linked_at=now,
        is_active=is_active,
    )


@pytest.fixture
def mock_bot() -> MagicMock:
    """A mock PTB Bot instance that tracks send_message calls."""
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return bot
