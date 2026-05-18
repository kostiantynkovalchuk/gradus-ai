"""
/start command handler — consent flow and re-link handling.

Flow:
  1. Already linked & active  → show profile
  2. Already linked & inactive → offer re-link
  3. New user → consent screen
  4. Consent ✅ → request contact
  5. Consent ❌ → polite goodbye
"""

import logging
from datetime import UTC, datetime
from typing import Any

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from tenderlot_bot.bot.templates.messages import (
    ALREADY_LINKED,
    ALREADY_LINKED_INACTIVE,
    CONSENT_AGREE_BUTTON,
    CONSENT_DECLINE_BUTTON,
    CONSENT_DECLINED,
    CONSENT_TEXT,
    RELINK_AGREE_BUTTON,
    RELINK_DECLINE_BUTTON,
    SHARE_CONTACT_BUTTON,
    SHARE_CONTACT_PROMPT,
    role_to_ukrainian,
)
from tenderlot_bot.db import BotSession, TlotSession
from tenderlot_bot.services.bot_state_repo import BotStateRepo
from tenderlot_bot.services.tenderlot_repo import TenderlotRepo

logger = logging.getLogger(__name__)

# Callback data constants
_CB_CONSENT_YES = "consent:yes"
_CB_CONSENT_NO = "consent:no"
_CB_RELINK_YES = "relink:yes"
_CB_RELINK_NO = "relink:no"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point for /start."""
    if update.effective_user is None or update.message is None:
        return

    telegram_id = update.effective_user.id

    async with BotSession() as bot_session:
        state_repo = BotStateRepo(bot_session)
        bot_user = await state_repo.get_bot_user(telegram_id)

    if bot_user is not None:
        if bot_user.is_active:
            async with TlotSession() as tlot_session:
                tlot_repo = TenderlotRepo(tlot_session)
                tlot_user = await tlot_repo.get_user_by_phone(bot_user.phone)

            full_name = tlot_user.full_name if tlot_user else bot_user.phone
            role = role_to_ukrainian(tlot_user.role) if tlot_user else "—"

            await update.message.reply_text(
                ALREADY_LINKED.format(full_name=full_name, role=role),
                parse_mode="HTML",
            )
            return

        # Inactive — offer re-link
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(RELINK_AGREE_BUTTON, callback_data=_CB_RELINK_YES),
                    InlineKeyboardButton(RELINK_DECLINE_BUTTON, callback_data=_CB_RELINK_NO),
                ]
            ]
        )
        await update.message.reply_text(
            ALREADY_LINKED_INACTIVE,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    # New user — consent screen
    await _show_consent(update)


async def _show_consent(update: Update) -> None:
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(CONSENT_AGREE_BUTTON, callback_data=_CB_CONSENT_YES),
                InlineKeyboardButton(CONSENT_DECLINE_BUTTON, callback_data=_CB_CONSENT_NO),
            ]
        ]
    )
    if update.message:
        await update.message.reply_text(
            CONSENT_TEXT, reply_markup=keyboard, parse_mode="HTML"
        )


async def consent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ✅ Згоден / ❌ Не згоден inline button presses."""
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    await query.answer()

    if query.data == _CB_CONSENT_NO:
        await query.edit_message_text(CONSENT_DECLINED)
        return

    # Consent given — store timestamp in context for the contact handler
    if context.user_data is not None:
        context.user_data["consent_given_at"] = datetime.now(UTC)

    # Show request_contact keyboard
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton(SHARE_CONTACT_BUTTON, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await query.edit_message_text(SHARE_CONTACT_PROMPT, parse_mode="HTML")
    if update.effective_chat:
        await update.effective_chat.send_message(
            SHARE_CONTACT_PROMPT,
            reply_markup=keyboard,
        )


async def relink_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle re-link inline button presses."""
    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    await query.answer()

    if query.data == _CB_RELINK_NO:
        await query.edit_message_text("Зрозуміло. Надішліть /start, якщо передумаєте.")
        return

    # Re-link flow — same as fresh consent
    if context.user_data is not None:
        context.user_data["consent_given_at"] = datetime.now(UTC)

    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton(SHARE_CONTACT_BUTTON, request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await query.edit_message_text(SHARE_CONTACT_PROMPT)
    if update.effective_chat:
        await update.effective_chat.send_message(
            SHARE_CONTACT_PROMPT,
            reply_markup=keyboard,
        )


def register(app: object) -> None:
    """Register all start-flow handlers on the PTB Application."""
    from telegram.ext import Application  # noqa: PLC0415

    application: Application[Any, Any, Any, Any, Any, Any] = app  # type: ignore[assignment]
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(
        CallbackQueryHandler(consent_callback, pattern=r"^consent:")
    )
    application.add_handler(
        CallbackQueryHandler(relink_callback, pattern=r"^relink:")
    )
