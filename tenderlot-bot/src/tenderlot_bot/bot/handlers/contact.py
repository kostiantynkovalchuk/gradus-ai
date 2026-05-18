"""
Contact message handler — phone normalization, tenderlot lookup, bot_user creation.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, MessageHandler, filters

from tenderlot_bot.bot.templates.messages import (
    LINK_SUCCESS,
    PHONE_INVALID,
    PHONE_NOT_FOUND,
    UNEXPECTED_ERROR,
    role_to_ukrainian,
)
from tenderlot_bot.db import BotSession, TlotSession
from tenderlot_bot.services.bot_state_repo import BotStateRepo
from tenderlot_bot.services.matcher import normalize_phone
from tenderlot_bot.services.tenderlot_repo import TenderlotRepo

logger = logging.getLogger(__name__)


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Receives a shared contact, normalizes the phone, looks up tenderlot user,
    and creates or reactivates a bot_user row.
    """
    if (
        update.message is None
        or update.message.contact is None
        or update.effective_user is None
    ):
        return

    contact = update.message.contact
    telegram_id = update.effective_user.id

    # Ensure the contact belongs to the sender (security check)
    if contact.user_id is not None and contact.user_id != telegram_id:
        logger.warning(
            "[contact] telegram_id=%d sent contact for user_id=%d — ignoring",
            telegram_id,
            contact.user_id,
        )
        await update.message.reply_text(
            UNEXPECTED_ERROR, reply_markup=ReplyKeyboardRemove()
        )
        return

    raw_phone = contact.phone_number or ""
    phone = normalize_phone(raw_phone)

    if phone is None:
        logger.warning("[contact] Invalid phone from telegram_id=%d: %r", telegram_id, raw_phone)
        await update.message.reply_text(
            PHONE_INVALID, reply_markup=ReplyKeyboardRemove()
        )
        return

    logger.info("[contact] telegram_id=%d normalized phone=%s", telegram_id, phone)

    async with TlotSession() as tlot_session:
        tlot_repo = TenderlotRepo(tlot_session)
        tlot_user = await tlot_repo.get_user_by_phone(phone)

    if tlot_user is None:
        logger.info("[contact] Phone %s not found in tenderlot DB", phone)
        await update.message.reply_text(
            PHONE_NOT_FOUND, reply_markup=ReplyKeyboardRemove()
        )
        return

    # Retrieve consent timestamp stored during /start flow
    consent_given_at: datetime = (
        context.user_data.get("consent_given_at", datetime.now(UTC))
        if context.user_data
        else datetime.now(UTC)
    )

    async with BotSession() as bot_session:
        state_repo = BotStateRepo(bot_session)
        existing = await state_repo.get_bot_user(telegram_id)

        if existing is not None:
            await state_repo.reactivate_bot_user(existing, consent_given_at)
        else:
            await state_repo.create_bot_user(
                telegram_id=telegram_id,
                telegram_username=update.effective_user.username,
                phone=phone,
                tenderlot_user_id=tlot_user.id,
                consent_given_at=consent_given_at,
            )

    await update.message.reply_text(
        LINK_SUCCESS.format(
            full_name=tlot_user.full_name,
            role=role_to_ukrainian(tlot_user.role),
        ),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
    logger.info(
        "[contact] Linked telegram_id=%d → tenderlot_user_id=%d phone=%s",
        telegram_id,
        tlot_user.id,
        phone,
    )


def register(app: object) -> None:
    from telegram.ext import Application  # noqa: PLC0415

    application: Application[Any, Any, Any, Any, Any, Any] = app  # type: ignore[assignment]
    application.add_handler(MessageHandler(filters.CONTACT, contact_handler))
