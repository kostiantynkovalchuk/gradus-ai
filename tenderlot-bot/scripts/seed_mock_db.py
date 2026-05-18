"""
CLI script to populate the mock tenderlot database for manual testing.

Behaviour:
  - Default (no flags): seed users + 5 tenders if table is empty; SKIP if data exists.
  - --force: truncate and re-seed even when data already exists.
  - --add-tender: insert one new tender with start_mail_status=1 (for live polling test).

After seeding, the script queries the DB and prints the actual phones — never hardcoded.
"""

import asyncio
import logging
import sys

sys.path.insert(0, "src")

from sqlalchemy import select

from tenderlot_bot.db import TlotSession, init_db, tlot_engine
from tenderlot_bot.logging_config import setup_logging
from tenderlot_bot.mocks.seed_data import add_one_tender, populate
from tenderlot_bot.models.tenderlot import TenderlotUser

logger = logging.getLogger(__name__)


async def _print_users(limit: int = 5) -> None:
    """Query and print actual phones from the DB — never hardcoded."""
    async with TlotSession() as session:
        result = await session.execute(
            select(TenderlotUser.phone, TenderlotUser.full_name, TenderlotUser.role)
            .order_by(TenderlotUser.id)
            .limit(limit)
        )
        rows = result.all()

    print("\nTest phones available (live from DB):")
    for phone, name, role in rows:
        print(f"  {phone}  — {name} ({role})")


async def _main() -> None:
    setup_logging(level="INFO", fmt="text")
    await init_db()

    args = sys.argv[1:]
    force = "--force" in args
    add_tender = "--add-tender" in args

    async with TlotSession() as session:
        if add_tender:
            tender = await add_one_tender(session)
            print(f"Added tender: #{tender.id} — {tender.title}")
            print(f"  start_mail_status={tender.start_mail_status}")
            print(f"  target_role={tender.target_role}")
            print(f"  ends_at={tender.ends_at}")
        else:
            await populate(session, force=force)
            if force:
                print("Mock data re-seeded (--force).")
            else:
                print("Mock data seeded (skipped if already populated).")
            await _print_users()


async def _shutdown() -> None:
    """Dispose DB engines so asyncio.run() exits cleanly."""
    from tenderlot_bot.db import bot_engine  # noqa: PLC0415

    await tlot_engine.dispose()
    await bot_engine.dispose()


async def _run() -> None:
    await _main()
    await _shutdown()


if __name__ == "__main__":
    asyncio.run(_run())
