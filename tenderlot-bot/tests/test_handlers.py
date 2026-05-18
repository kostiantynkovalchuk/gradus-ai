"""
Tests for bot command handlers.

Uses AsyncMock to simulate PTB Update/CallbackQuery objects.
No real Telegram API calls are made.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tenderlot_bot.bot.handlers.start import consent_callback, relink_callback
from tenderlot_bot.bot.templates.messages import CONSENT_CONFIRMED, SHARE_CONTACT_PROMPT


def _make_consent_update(callback_data: str = "consent:yes") -> MagicMock:
    """Build a minimal fake Update with a CallbackQuery."""
    query = MagicMock()
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()

    chat = MagicMock()
    chat.send_message = AsyncMock()

    user = MagicMock()
    user.id = 123456789

    update = MagicMock()
    update.callback_query = query
    update.effective_user = user
    update.effective_chat = chat
    return update


def _make_context(user_data: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    return ctx


class TestConsentCallback:
    async def test_consent_yes_sends_exactly_one_new_message(self) -> None:
        """
        Tapping ✅ Згоден must result in exactly ONE new message (the keyboard prompt).
        The edit_message_text call updates the existing consent message — it does NOT
        send a new message. The net new message count must be 1.
        """
        update = _make_consent_update("consent:yes")
        ctx = _make_context()

        await consent_callback(update, ctx)

        # Inline button message is edited — not a new send
        update.callback_query.edit_message_text.assert_called_once_with(CONSENT_CONFIRMED)

        # Exactly one new message sent (the contact-prompt with keyboard)
        update.effective_chat.send_message.assert_called_once()
        call_args = update.effective_chat.send_message.call_args
        assert call_args[0][0] == SHARE_CONTACT_PROMPT or call_args[1].get("text") == SHARE_CONTACT_PROMPT or SHARE_CONTACT_PROMPT in str(call_args)

    async def test_consent_yes_stores_consent_timestamp(self) -> None:
        """Tapping ✅ Згоден stores consent_given_at in user_data."""
        update = _make_consent_update("consent:yes")
        ctx = _make_context()

        await consent_callback(update, ctx)

        assert "consent_given_at" in ctx.user_data
        assert isinstance(ctx.user_data["consent_given_at"], datetime)

    async def test_consent_no_sends_no_keyboard_message(self) -> None:
        """Tapping ❌ Не згоден edits the message but sends no new message."""
        update = _make_consent_update("consent:no")
        ctx = _make_context()

        await consent_callback(update, ctx)

        # The decline message goes into the edit
        update.callback_query.edit_message_text.assert_called_once()
        # No new message sent
        update.effective_chat.send_message.assert_not_called()

    async def test_relink_yes_sends_exactly_one_new_message(self) -> None:
        """Tapping 🔄 Підключити знову also results in exactly ONE new message."""
        update = _make_consent_update("relink:yes")
        ctx = _make_context()

        await relink_callback(update, ctx)

        update.callback_query.edit_message_text.assert_called_once_with(CONSENT_CONFIRMED)
        update.effective_chat.send_message.assert_called_once()

    async def test_relink_no_sends_no_keyboard_message(self) -> None:
        """Tapping ❌ Ні, дякую edits the message but sends no new message."""
        update = _make_consent_update("relink:no")
        ctx = _make_context()

        await relink_callback(update, ctx)

        update.callback_query.edit_message_text.assert_called_once()
        update.effective_chat.send_message.assert_not_called()
