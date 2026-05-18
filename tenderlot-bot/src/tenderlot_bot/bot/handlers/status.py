"""
/status command handler — profile info and weekly notification count.
"""

import logging
from typing import Any

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from tenderlot_bot.bot.templates.messages import (
    STATUS_NOT_LINKED,
    STATUS_TEXT,
    role_to_ukrainian,
    status_label,
)
from tenderlot_bot.db import BotSession, TlotSession
from tenderlot_bot.services.bot_state_repo import BotStateRepo
from tenderlot_bot.services.tenderlot_repo import TenderlotRepo

logger = logging.getLogger(__name__)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    telegram_id = update.effective_user.id

    async with BotSession() as bot_session:
        state_repo = BotStateRepo(bot_session)
        bot_user = await state_repo.get_bot_user(telegram_id)

        if bot_user is None:
            await update.message.reply_text(STATUS_NOT_LINKED)
            return

        week_count = await state_repo.count_notifications_this_week(bot_user.id)

    async with TlotSession() as tlot_session:
        tlot_repo = TenderlotRepo(tlot_session)
        tlot_user = await tlot_repo.get_user_by_phone(bot_user.phone)

    full_name = tlot_user.full_name if tlot_user else bot_user.phone
    role = role_to_ukrainian(tlot_user.role) if tlot_user else "—"

    await update.message.reply_text(
        STATUS_TEXT.format(
            full_name=full_name,
            role=role,
            phone=bot_user.phone,
            status=status_label(bot_user.is_active),
            linked_at=bot_user.linked_at.strftime("%d.%m.%Y %H:%M"),
            week_count=week_count,
        ),
        parse_mode="HTML",
    )


def register(app: object) -> None:
    from telegram.ext import Application  # noqa: PLC0415

    application: Application[Any, Any, Any, Any, Any, Any] = app  # type: ignore[assignment]
    application.add_handler(CommandHandler("status", status_command))
