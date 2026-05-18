"""
Build and configure the PTB Application with all handlers registered.
"""

import logging

from telegram.ext import Application

from tenderlot_bot.bot.handlers import contact, help, start, status, unlink
from tenderlot_bot.config import settings

logger = logging.getLogger(__name__)


def build_application() -> Application:  # type: ignore[type-arg]
    """Create the PTB Application, register all handlers, and return it."""
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # Register handlers in order of specificity
    start.register(app)
    contact.register(app)
    help.register(app)
    unlink.register(app)
    status.register(app)

    logger.info("[Application] All handlers registered")
    return app
