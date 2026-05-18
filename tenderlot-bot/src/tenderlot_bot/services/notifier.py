"""
Telegram message dispatcher.

Wraps python-telegram-bot's send_message with:
  - Message rendering from templates
  - InlineKeyboardMarkup construction
  - Error categorization (Forbidden → BLOCKED, BadRequest → FAILED, NetworkError → raise)
  - notification_log writing
"""

import logging
from enum import StrEnum

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError

from tenderlot_bot.bot.templates.messages import (
    TENDER_START,
    TENDER_START_BUTTON_TEXT,
    TENDER_START_BUTTON_URL,
    format_price,
)
from tenderlot_bot.models.bot_state import BotUser, NotificationType
from tenderlot_bot.models.tenderlot import TenderlotTender
from tenderlot_bot.services.bot_state_repo import BotStateRepo

logger = logging.getLogger(__name__)


class NotificationResult(StrEnum):
    SENT = "sent"
    FAILED = "failed"
    BLOCKED = "blocked"


class Notifier:
    """Wraps PTB's bot.send_message with logging and error categorization."""

    def __init__(self, bot: Bot, state_repo: BotStateRepo) -> None:
        self._bot = bot
        self._state_repo = state_repo

    async def send_tender_start(
        self,
        bot_user: BotUser,
        tender: TenderlotTender,
    ) -> NotificationResult:
        """
        Send a tender-start notification to a single user.
        Writes a notification_log row regardless of outcome.
        """
        text = TENDER_START.format(
            title=tender.title,
            number=tender.number,
            price=format_price(tender.start_price, tender.currency),
            currency=tender.currency,
            ends_at=tender.ends_at.strftime("%d.%m.%Y %H:%M"),
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=TENDER_START_BUTTON_TEXT,
                        url=TENDER_START_BUTTON_URL.format(tender_id=tender.id),
                    )
                ]
            ]
        )

        telegram_message_id: int | None = None
        result = NotificationResult.SENT
        error_msg: str | None = None

        try:
            msg = await self._bot.send_message(
                chat_id=bot_user.telegram_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            telegram_message_id = msg.message_id
            logger.info(
                "[Notifier] Sent tender_start tender_id=%d → telegram_id=%d msg_id=%d",
                tender.id,
                bot_user.telegram_id,
                msg.message_id,
            )

        except Forbidden as exc:
            # User blocked the bot — deactivate them silently
            result = NotificationResult.BLOCKED
            error_msg = str(exc)
            logger.warning(
                "[Notifier] User blocked bot: telegram_id=%d — deactivating",
                bot_user.telegram_id,
            )
            await self._state_repo.deactivate_bot_user(bot_user)

        except BadRequest as exc:
            result = NotificationResult.FAILED
            error_msg = str(exc)
            logger.error(
                "[Notifier] BadRequest sending to telegram_id=%d: %s",
                bot_user.telegram_id,
                exc,
            )

        except NetworkError:
            # Transient — let caller retry on next poll cycle
            logger.error(
                "[Notifier] NetworkError sending to telegram_id=%d — will retry",
                bot_user.telegram_id,
            )
            raise

        except TelegramError as exc:
            result = NotificationResult.FAILED
            error_msg = str(exc)
            logger.error(
                "[Notifier] TelegramError for telegram_id=%d: %s",
                bot_user.telegram_id,
                exc,
            )

        await self._state_repo.log_notification(
            bot_user_id=bot_user.id,
            tender_id=tender.id,
            notification_type=NotificationType.TENDER_START,
            delivery_status=result.value,
            telegram_message_id=telegram_message_id,
            error_message=error_msg,
        )

        return result
