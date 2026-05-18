"""
The polling worker — heart of the bot.

Reads tenderlot_tender every N seconds.
For each tender where start_mail_status=1 AND no notification_log row exists
for (bot_user, tender, 'tender_start') — dispatches via Notifier.

Idempotent by design: the unique constraint on notification_log
prevents duplicates even across restarts.
"""

import asyncio
import logging

from tenderlot_bot.config import settings
from tenderlot_bot.db import BotSession, TlotSession
from tenderlot_bot.models.bot_state import NotificationType
from tenderlot_bot.services.bot_state_repo import BotStateRepo
from tenderlot_bot.services.notifier import NotificationResult, Notifier
from tenderlot_bot.services.tenderlot_repo import TenderlotRepo

logger = logging.getLogger(__name__)


class PollingWorker:
    """
    Background worker that polls for new tenders and dispatches notifications.

    Usage:
        worker = PollingWorker(bot=application.bot)
        asyncio.create_task(worker.run_forever())
    """

    def __init__(self, bot: object) -> None:
        # `bot` is telegram.Bot — typed as object to avoid circular import at module level
        self._bot = bot
        self._running = False

    async def run_forever(self) -> None:
        """Poll indefinitely. Catches all exceptions per cycle to avoid crashing."""
        self._running = True
        logger.info(
            "[PollingWorker] Started. Polling for tenders every %ds.",
            settings.poll_interval_seconds,
        )
        while self._running:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("[PollingWorker] Cycle failed; will retry next interval")
            await asyncio.sleep(settings.poll_interval_seconds)

    def stop(self) -> None:
        """Signal the worker to stop after the current sleep."""
        self._running = False
        logger.info("[PollingWorker] Stop requested")

    async def _poll_once(self) -> None:
        """
        One poll cycle:
          1. Fetch up to poll_batch_size tenders with start_mail_status=1
          2. For each tender: find target tenderlot users → find linked bot users →
             filter already-notified → dispatch via Notifier
          3. Log each send (success/failure) to notification_log
        """
        async with TlotSession() as tlot_session, BotSession() as bot_session:
            tlot_repo = TenderlotRepo(tlot_session)
            state_repo = BotStateRepo(bot_session)

            notifier = Notifier(bot=self._bot, state_repo=state_repo)  # type: ignore[arg-type]

            tenders = await tlot_repo.get_pending_tenders(
                batch_size=settings.poll_batch_size
            )

            if not tenders:
                logger.debug("[PollingWorker] No pending tenders this cycle")
                return

            logger.info("[PollingWorker] Found %d pending tender(s)", len(tenders))

            for tender in tenders:
                try:
                    await self._dispatch_tender(
                        tender=tender,
                        tlot_repo=tlot_repo,
                        state_repo=state_repo,
                        notifier=notifier,
                    )
                except Exception:
                    # One failed tender must NOT block others
                    logger.exception(
                        "[PollingWorker] Failed to dispatch tender_id=%d — skipping",
                        tender.id,
                    )

    async def _dispatch_tender(
        self,
        tender: object,
        tlot_repo: TenderlotRepo,
        state_repo: BotStateRepo,
        notifier: Notifier,
    ) -> None:
        from tenderlot_bot.models.tenderlot import TenderlotTender  # noqa: PLC0415

        tender_obj: TenderlotTender = tender  # type: ignore[assignment]

        # 1. Find all tenderlot users eligible for this tender's role
        tlot_users = await tlot_repo.get_active_users_for_role(tender_obj.target_role)
        if not tlot_users:
            logger.debug("[PollingWorker] No eligible tenderlot users for tender_id=%d", tender_obj.id)
            return

        tlot_user_ids = [u.id for u in tlot_users]

        # 2. Find linked bot users
        bot_users = await state_repo.get_active_bot_users_for_tlot_users(tlot_user_ids)
        if not bot_users:
            logger.debug(
                "[PollingWorker] No linked Telegram users for tender_id=%d", tender_obj.id
            )
            return

        # 3. Filter out already-notified
        already_notified = await state_repo.get_already_notified_user_ids(
            tender_id=tender_obj.id,
            notification_type=NotificationType.TENDER_START,
            bot_user_ids=[u.id for u in bot_users],
        )

        to_notify = [u for u in bot_users if u.id not in already_notified]
        logger.info(
            "[PollingWorker] tender_id=%d: %d eligible, %d already notified, %d to send",
            tender_obj.id,
            len(bot_users),
            len(already_notified),
            len(to_notify),
        )

        # 4. Dispatch — one try/except per user
        sent = failed = blocked = 0
        for bot_user in to_notify:
            try:
                result = await notifier.send_tender_start(bot_user, tender_obj)
                if result == NotificationResult.SENT:
                    sent += 1
                elif result == NotificationResult.BLOCKED:
                    blocked += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
                logger.exception(
                    "[PollingWorker] send failed for bot_user_id=%d tender_id=%d",
                    bot_user.id,
                    tender_obj.id,
                )

        logger.info(
            "[PollingWorker] tender_id=%d dispatch done: sent=%d failed=%d blocked=%d",
            tender_obj.id,
            sent,
            failed,
            blocked,
        )
