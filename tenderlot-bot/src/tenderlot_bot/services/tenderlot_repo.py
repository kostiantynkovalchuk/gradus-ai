"""
Read-only repository for the tenderlot database.

In production this reads from MariaDB; in dev it reads from the mock SQLite.
The interface is identical — only the connection string changes.
"""

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tenderlot_bot.models.tenderlot import TenderlotTender, TenderlotUser

logger = logging.getLogger(__name__)


class TenderlotRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_phone(self, phone: str) -> TenderlotUser | None:
        """Look up an active tenderlot user by E.164 phone number."""
        result = await self._session.execute(
            select(TenderlotUser).where(
                TenderlotUser.phone == phone,
                TenderlotUser.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_tenders(self, batch_size: int = 50) -> Sequence[TenderlotTender]:
        """
        Return tenders where start_mail_status=1 (ready to notify).
        The caller is responsible for filtering out already-notified users.
        """
        result = await self._session.execute(
            select(TenderlotTender)
            .where(TenderlotTender.start_mail_status == 1)
            .limit(batch_size)
        )
        return result.scalars().all()

    async def get_active_users_for_role(self, target_role: str) -> Sequence[TenderlotUser]:
        """
        Return all active tenderlot users whose role matches the tender's target_role.
        target_role == "both" means all active users.
        """
        if target_role == "both":
            result = await self._session.execute(
                select(TenderlotUser).where(TenderlotUser.is_active.is_(True))
            )
        else:
            result = await self._session.execute(
                select(TenderlotUser).where(
                    TenderlotUser.role == target_role,
                    TenderlotUser.is_active.is_(True),
                )
            )
        return result.scalars().all()
