"""
Async SQLAlchemy engine + session factories.

Two separate databases:
  - bot_engine / BotSession   → bot's own state (SQLite dev / PostgreSQL prod)
  - tlot_engine / TlotSession → tenderlot read-only mock (SQLite dev / MariaDB prod)
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tenderlot_bot.config import settings
from tenderlot_bot.models.bot_state import BotBase
from tenderlot_bot.models.tenderlot import TenderlotBase

# ── Bot state DB ───────────────────────────────────────────────────────────────
bot_engine = create_async_engine(
    settings.bot_database_url,
    echo=False,
    connect_args={"check_same_thread": False}
    if "sqlite" in settings.bot_database_url
    else {},
)
BotSession: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bot_engine, expire_on_commit=False
)

# ── Tenderlot read-only DB ─────────────────────────────────────────────────────
tlot_engine = create_async_engine(
    settings.tenderlot_database_url,
    echo=False,
    connect_args={"check_same_thread": False}
    if "sqlite" in settings.tenderlot_database_url
    else {},
)
TlotSession: async_sessionmaker[AsyncSession] = async_sessionmaker(
    tlot_engine, expire_on_commit=False
)


async def init_db() -> None:
    """Create all tables (idempotent). Call once at startup."""
    async with bot_engine.begin() as conn:
        await conn.run_sync(BotBase.metadata.create_all)
    async with tlot_engine.begin() as conn:
        await conn.run_sync(TenderlotBase.metadata.create_all)
