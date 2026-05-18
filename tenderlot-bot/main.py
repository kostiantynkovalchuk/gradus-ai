"""
Tenderlot Bot — entry point.

Startup sequence:
  1. Configure logging
  2. Build PTB Application with post_init + post_shutdown hooks
  3. post_init: create DB tables → seed mock data → launch polling worker
  4. PTB manages its own event loop via run_polling()

Production note (Render):
  - Set TENDERLOT_BOT_BOT_MODE=webhook
  - Replace run_polling() with run_webhook(url=..., webhook_url=...)
  - Switch TENDERLOT_BOT_TENDERLOT_DATABASE_URL to MariaDB connection string
  - Switch TENDERLOT_BOT_BOT_DATABASE_URL to Neon PostgreSQL connection string
"""

import asyncio
import logging
import sys
from typing import Any

# Ensure src/ is on the path when running as `python main.py` from project root
sys.path.insert(0, "src")

from telegram.ext import Application

from tenderlot_bot.bot.application import build_application
from tenderlot_bot.config import settings
from tenderlot_bot.db import TlotSession, init_db
from tenderlot_bot.logging_config import setup_logging
from tenderlot_bot.mocks.seed_data import populate
from tenderlot_bot.services.polling_worker import PollingWorker

logger = logging.getLogger(__name__)

_worker: PollingWorker | None = None


async def _post_init(application: Application[Any, Any, Any, Any, Any, Any]) -> None:
    """
    Called by PTB after the Application is initialised but before polling starts.
    The correct place to run async startup work in PTB v21+.
    """
    logger.info("[main] Initializing databases...")
    await init_db()
    logger.info("[main] Databases ready")

    async with TlotSession() as session:
        await populate(session)

    global _worker
    _worker = PollingWorker(bot=application.bot)
    asyncio.create_task(_worker.run_forever())

    logger.info(
        "[main] Bot started. Polling for tenders every %ds.",
        settings.poll_interval_seconds,
    )


async def _post_shutdown(application: Application[Any, Any, Any, Any, Any, Any]) -> None:
    """Graceful shutdown — stop the polling worker."""
    if _worker is not None:
        _worker.stop()
    logger.info("[main] Bot shut down cleanly")


def main() -> None:
    setup_logging(level=settings.log_level, fmt=settings.log_format)

    app = build_application(post_init=_post_init, post_shutdown=_post_shutdown)

    # run_polling() manages its own event loop — do NOT wrap in asyncio.run()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
