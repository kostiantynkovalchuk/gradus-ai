"""
Build and configure the PTB Application with all handlers registered.
"""

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from telegram.ext import Application

from tenderlot_bot.bot.handlers import contact, help, start, status, unlink
from tenderlot_bot.config import settings

logger = logging.getLogger(__name__)

_AppCallback = Callable[
    [Application[Any, Any, Any, Any, Any, Any]], Coroutine[Any, Any, None]
]


def build_application(
    post_init: _AppCallback | None = None,
    post_shutdown: _AppCallback | None = None,
) -> Application[Any, Any, Any, Any, Any, Any]:
    """Create the PTB Application, register all handlers, and return it."""
    builder = Application.builder().token(settings.telegram_bot_token)

    if post_init is not None:
        builder = builder.post_init(post_init)
    if post_shutdown is not None:
        builder = builder.post_shutdown(post_shutdown)

    app = builder.build()

    start.register(app)
    contact.register(app)
    help.register(app)
    unlink.register(app)
    status.register(app)

    logger.info("[Application] All handlers registered")
    return app
