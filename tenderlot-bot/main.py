"""
Tenderlot Bot — entry point.

Startup sequence:
  1. Configure logging
  2. Create DB tables (idempotent)
  3. Seed mock data if tenderlot_user table is empty
  4. Build PTB Application
  5. Start polling worker as background asyncio task
  6. Run PTB with run_polling() [dev mode]

Production note (Render):
  - Switch to run_webhook() with the Render-assigned URL
  - Set TENDERLOT_BOT_BOT_MODE=webhook
  - Configure HTTPS endpoint in Render dashboard
"""

import asyncio
import logging
import signal
import sys

# Ensure src/ is on the path when running as `python main.py` from project root
sys.path.insert(0, "src")

from tenderlot_bot.config import settings
from tenderlot_bot.db import BotSession, TlotSession, init_db
from tenderlot_bot.logging_config import setup_logging
from tenderlot_bot.mocks.seed_data import populate
from tenderlot_bot.bot.application import build_application
from tenderlot_bot.services.polling_worker import PollingWorker

logger = logging.getLogger(__name__)


async def _seed_if_empty() -> None:
    """Seed mock tenderlot data only if the table is empty."""
    async with TlotSession() as session:
        await populate(session)


async def _async_main() -> None:
    setup_logging(level=settings.log_level, fmt=settings.log_format)

    logger.info("[main] Initializing databases...")
    await init_db()
    logger.info("[main] Databases ready")

    await _seed_if_empty()

    app = build_application()
    worker = PollingWorker(bot=app.bot)

    # Graceful shutdown on SIGTERM (Render + Replit both send this)
    loop = asyncio.get_running_loop()

    def _handle_sigterm() -> None:
        logger.info("[main] SIGTERM received — stopping")
        worker.stop()
        loop.stop()

    loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)

    # Start polling worker as background task
    polling_task = asyncio.create_task(worker.run_forever())

    logger.info(
        "[main] Bot started. Polling for tenders every %ds.",
        settings.poll_interval_seconds,
    )

    try:
        # PTB's run_polling() takes control of the event loop
        await app.run_polling(drop_pending_updates=True)
    finally:
        worker.stop()
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
        logger.info("[main] Bot shut down cleanly")


if __name__ == "__main__":
    asyncio.run(_async_main())
