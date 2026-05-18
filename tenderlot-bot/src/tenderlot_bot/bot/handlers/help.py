"""
/help command handler.
"""

import logging
from typing import Any

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from tenderlot_bot.bot.templates.messages import HELP_TEXT

logger = logging.getLogger(__name__)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


def register(app: object) -> None:
    from telegram.ext import Application  # noqa: PLC0415

    application: Application[Any, Any, Any, Any, Any, Any] = app  # type: ignore[assignment]
    application.add_handler(CommandHandler("help", help_command))
