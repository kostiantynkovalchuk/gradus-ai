"""
CLI script to populate the mock tenderlot database for manual testing.

Usage:
    python scripts/seed_mock_db.py              # seed users + 5 tenders
    python scripts/seed_mock_db.py --add-tender # add one new tender with start_mail_status=1
    python scripts/seed_mock_db.py --force      # re-seed even if table is not empty
"""

import asyncio
import logging
import sys

sys.path.insert(0, "src")

from tenderlot_bot.db import TlotSession, init_db
from tenderlot_bot.logging_config import setup_logging
from tenderlot_bot.mocks.seed_data import add_one_tender, populate

logger = logging.getLogger(__name__)


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
            print("\nTest phones available:")
            print("  +380000000001  — Тестовий Користувач (supplier)")
            print("  +380675755800  — Апенко Дмитро Сергійович (supplier)")


if __name__ == "__main__":
    asyncio.run(_main())
