import os
import re
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

TELETHON_API_ID = os.getenv("TELETHON_API_ID", "")
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH", "")
TELETHON_SESSION = os.getenv("TELETHON_SESSION", "")

PHONE_PATTERN = re.compile(r'\+?\d[\d\s\-()]{8,}\d')
USERNAME_PATTERN = re.compile(r'@[A-Za-z0-9_]{5,}')

_VACANCY_SIGNALS = re.compile(
    r'шукаємо|запрошуємо|потрібен|потрібна|потрібні|вакансія|відкрита позиція|'
    r'ми пропонуємо|ми шукаємо|графік роботи|умови роботи|обов\'язки|компанія|'
    r'магазин|мережа|бренд|зп від|ставка[\s:]|оклад|надіслати резюме|'
    r'писати в дірект|звертайтесь|конкурентна зп|офіційне оформлення',
    re.IGNORECASE,
)
_CV_SIGNALS = re.compile(
    r'шукаю роботу|розглядаю пропозиції|маю досвід|мій досвід|'
    r'працював|працювала|резюме|cv\b|я шукаю|я маю|я працюю|'
    r'\d{2}\s*рок',
    re.IGNORECASE,
)


def is_cv_post(text: str) -> bool:
    """Return True if the message looks like a candidate CV, False if it looks like a vacancy."""
    vacancy_count = len(_VACANCY_SIGNALS.findall(text))
    cv_count = len(_CV_SIGNALS.findall(text))
    if vacancy_count > cv_count:
        return False
    if cv_count > 0:
        return True
    return False


async def scrape_telegram_channels(
    keywords: list[str],
    channels: list[str],
    depth_days: int = None,
) -> list[dict]:
    from config.hunt_config import HUNT_CONFIG
    if depth_days is None:
        depth_days = HUNT_CONFIG["search_depth_days"]

    logger.info(f"TG scraper received {len(channels)} channels: {channels}, depth_days={depth_days}")
    if channels:
        logger.info(f"First channel item type: {type(channels[0])}, value: {channels[0]}")

    if not TELETHON_API_ID or not TELETHON_API_HASH or not TELETHON_SESSION:
        logger.warning("Telethon credentials not set (TELETHON_API_ID/TELETHON_API_HASH/TELETHON_SESSION). Skipping TG scraping.")
        logger.info("TG scraper complete: 0 candidates (no credentials)")
        return []

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        logger.warning("telethon not installed. Skipping TG scraping.")
        return []

    candidates = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=depth_days)

    try:
        client = TelegramClient(
            StringSession(TELETHON_SESSION),
            int(TELETHON_API_ID),
            TELETHON_API_HASH
        )
        await client.connect()

        if not await client.is_user_authorized():
            logger.warning("Telethon session not authorized. Skipping TG scraping.")
            await client.disconnect()
            return []

        from config.hunt_config import HUNT_CONFIG
        msg_limit = HUNT_CONFIG["tg_messages_per_channel"]

        for channel in channels:
            ch_kept = 0
            ch_skipped_vacancy = 0
            ch_skipped_other = 0
            ch_total = 0
            try:
                entity = await client.get_entity(channel)
                async for message in client.iter_messages(entity, limit=msg_limit):
                    if not message.text or not message.date:
                        continue
                    if message.date.replace(tzinfo=timezone.utc) < cutoff:
                        break

                    ch_total += 1
                    text_lower = message.text.lower()
                    if not any(kw.lower() in text_lower for kw in keywords):
                        ch_skipped_other += 1
                        continue

                    if not is_cv_post(message.text):
                        ch_skipped_vacancy += 1
                        continue

                    phones = PHONE_PATTERN.findall(message.text)
                    usernames = USERNAME_PATTERN.findall(message.text)

                    if not phones and not usernames:
                        ch_skipped_other += 1
                        continue

                    ch_kept += 1
                    candidates.append({
                        "source": f"telegram:{channel}",
                        "name": "",
                        "raw_text": message.text[:2000],
                        "phone": phones[0].strip() if phones else "",
                        "username": usernames[0] if usernames else "",
                        "message_date": message.date.isoformat(),
                        "message_link": f"https://t.me/{channel.lstrip('@')}/{message.id}" if channel.startswith("@") else "",
                    })
                logger.info(
                    f"TG filter [{channel}]: {ch_kept} CVs kept, "
                    f"{ch_skipped_vacancy} vacancies skipped, "
                    f"{ch_skipped_other} other skipped out of {ch_total} messages"
                )
            except Exception as e:
                logger.error(f"Error scraping channel {channel}: {e}")
                continue

        await client.disconnect()
    except Exception as e:
        logger.error(f"Telethon connection error: {e}")
        return []

    logger.info(f"TG scraper found {len(candidates)} candidates from {len(channels)} channels (depth={depth_days}d)")
    return candidates
