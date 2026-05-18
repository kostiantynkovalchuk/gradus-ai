"""
Seed mock tenderlot database with realistic Ukrainian test data.

Run via:  python scripts/seed_mock_db.py
Or:       python scripts/seed_mock_db.py --add-tender
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tenderlot_bot.models.tenderlot import TenderlotTender, TenderlotUser

logger = logging.getLogger(__name__)

# ── Mock users ─────────────────────────────────────────────────────────────────
MOCK_USERS = [
    # index 0: canonical test phone for self-testing
    {
        "phone": "+380000000001",
        "full_name": "Тестовий Користувач",
        "email": "test@example.com",
        "role": "supplier",
        "is_active": True,
    },
    # index 1: developer test phone for live self-testing
    {
        "phone": "+34692480784",
        "full_name": "Dev Test User",
        "email": "dev@test.local",
        "role": "supplier",
        "is_active": True,
    },
    {
        "phone": "+380671234567",
        "full_name": "Коваленко Олена Василівна",
        "email": "o.kovalenko@supplier.ua",
        "role": "supplier",
        "is_active": True,
    },
    {
        "phone": "+380502345678",
        "full_name": "Іванченко Микола Петрович",
        "email": "m.ivanchenko@carry.ua",
        "role": "carrier",
        "is_active": True,
    },
    {
        "phone": "+380633456789",
        "full_name": "Бондаренко Світлана Іванівна",
        "email": "s.bondarenko@supplier.ua",
        "role": "supplier",
        "is_active": True,
    },
    {
        "phone": "+380674567890",
        "full_name": "Мельник Андрій Олексійович",
        "email": "a.melnyk@carrier.ua",
        "role": "carrier",
        "is_active": True,
    },
    {
        "phone": "+380505678901",
        "full_name": "Ткаченко Юлія Миколаївна",
        "email": "y.tkachenko@supplier.ua",
        "role": "supplier",
        "is_active": True,
    },
    {
        "phone": "+380676789012",
        "full_name": "Сидоренко Василь Григорович",
        "email": "v.sydorenko@carry.ua",
        "role": "carrier",
        "is_active": True,
    },
    {
        "phone": "+380507890123",
        "full_name": "Поліщук Наталія Олегівна",
        "email": "n.polishchuk@supplier.ua",
        "role": "supplier",
        "is_active": True,
    },
    {
        "phone": "+380678901234",
        "full_name": "Лисенко Ігор Степанович",
        "email": "i.lysenko@carry.ua",
        "role": "carrier",
        "is_active": True,
    },
]


def _make_tenders(now: datetime) -> list[dict[str, object]]:
    """Return 5 mock tenders covering both types and roles."""
    return [
        # ── Ready to send immediately ──────────────────────────────────────────
        {
            "number": "TL-2026-001",
            "title": "Постачання алкогольних напоїв преміум-класу",
            "tender_type": "auction",
            "start_price": 500_000.0,
            "currency": "UAH",
            "starts_at": now + timedelta(hours=2),
            "ends_at": now + timedelta(days=5),
            "start_mail_status": 1,
            "end_mail_status": 0,
            "target_role": "supplier",
        },
        {
            "number": "TL-2026-002",
            "title": "Логістика доставки вантажів по Україні",
            "tender_type": "proposal_collection",
            "start_price": 150_000.0,
            "currency": "UAH",
            "starts_at": now + timedelta(hours=1),
            "ends_at": now + timedelta(days=3),
            "start_mail_status": 1,
            "end_mail_status": 0,
            "target_role": "carrier",
        },
        # ── Pending (not yet ready to notify) ─────────────────────────────────
        {
            "number": "TL-2026-003",
            "title": "Закупівля пива та слабоалкогольних напоїв",
            "tender_type": "auction",
            "start_price": 300_000.0,
            "currency": "UAH",
            "starts_at": now + timedelta(days=2),
            "ends_at": now + timedelta(days=7),
            "start_mail_status": 0,
            "end_mail_status": 0,
            "target_role": "both",
        },
        {
            "number": "TL-2026-004",
            "title": "Транспортування міцних напоїв (міжрегіональна логістика)",
            "tender_type": "proposal_collection",
            "start_price": 75_000.0,
            "currency": "USD",
            "starts_at": now + timedelta(days=1),
            "ends_at": now + timedelta(days=4),
            "start_mail_status": 0,
            "end_mail_status": 0,
            "target_role": "carrier",
        },
        {
            "number": "TL-2026-005",
            "title": "Постачання вина та ігристих напоїв для мережі супермаркетів",
            "tender_type": "auction",
            "start_price": None,
            "currency": "UAH",
            "starts_at": now + timedelta(days=3),
            "ends_at": now + timedelta(days=10),
            "start_mail_status": 0,
            "end_mail_status": 0,
            "target_role": "supplier",
        },
    ]


async def populate(session: AsyncSession, force: bool = False) -> None:
    """
    Seed mock data into the tenderlot database.

    Args:
        session: async SQLAlchemy session bound to the tenderlot DB
        force: if True, skip the emptiness check and always seed
    """
    existing = await session.scalar(select(TenderlotUser).limit(1))
    if existing is not None and not force:
        logger.info("[seed] tenderlot_user already has rows — skipping seed")
        return

    now = datetime.now(UTC)

    for user_data in MOCK_USERS:
        session.add(TenderlotUser(**user_data))

    for tender_data in _make_tenders(now):
        session.add(TenderlotTender(**tender_data))

    await session.commit()
    logger.info("[seed] Seeded %d users and %d tenders", len(MOCK_USERS), 5)


async def add_one_tender(session: AsyncSession) -> TenderlotTender:
    """
    Add a single new tender with start_mail_status=1 for live testing.
    Called by: python scripts/seed_mock_db.py --add-tender
    """
    now = datetime.now(UTC)

    # Count existing tenders to generate a unique number
    from sqlalchemy import func
    count_result = await session.scalar(select(func.count()).select_from(TenderlotTender))
    count = (count_result or 0) + 1

    tender = TenderlotTender(
        number=f"TL-2026-{count:03d}",
        title=f"Новий тендер #{count} — постачання товарів AVTD",
        tender_type="auction",
        start_price=float(count * 50_000),
        currency="UAH",
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(days=5),
        start_mail_status=1,
        end_mail_status=0,
        target_role="both",
    )
    session.add(tender)
    await session.commit()
    await session.refresh(tender)
    logger.info("[seed] Added tender #%d: %s", tender.id, tender.title)
    return tender
