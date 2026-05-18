"""
/unlink command handler — deactivates the bot_user row (does NOT delete it).
"""

import logging
from typing import Any

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from tenderlot_bot.bot.templates.messages import UNLINK_NOT_LINKED, UNLINK_SUCCESS
from tenderlot_bot.db import BotSession
from tenderlot_bot.services.bot_state_repo import BotStateRepo

logger = logging.getLogger(__name__)


async def unlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    telegram_id = update.effective_user.id

    async with BotSession() as bot_session:
        state_repo = BotStateRepo(bot_session)
        bot_user = await state_repo.get_bot_user(telegram_id)

        if bot_user is None or not bot_user.is_active:
            await update.message.reply_text(UNLINK_NOT_LINKED)
            return

        await state_repo.deactivate_bot_user(bot_user)

    logger.info("[unlink] telegram_id=%d unlinked", telegram_id)
    await update.message.reply_text(UNLINK_SUCCESS)


def register(app: object) -> None:
    from telegram.ext import Application  # noqa: PLC0415

    application: Application[Any, Any, Any, Any, Any, Any] = app  # type: ignore[assignment]
    application.add_handler(CommandHandler("unlink", unlink_command))
