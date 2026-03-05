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


async def scrape_telegram_channels(keywords: list[str], channels: list[str]) -> list[dict]:
    if not TELETHON_API_ID or not TELETHON_API_HASH or not TELETHON_SESSION:
        logger.warning("Telethon credentials not set (TELETHON_API_ID/TELETHON_API_HASH/TELETHON_SESSION). Skipping TG scraping.")
        return []

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        logger.warning("telethon not installed. Skipping TG scraping.")
        return []

    candidates = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

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

        for channel in channels:
            try:
                entity = await client.get_entity(channel)
                async for message in client.iter_messages(entity, limit=200):
                    if not message.text or not message.date:
                        continue
                    if message.date.replace(tzinfo=timezone.utc) < cutoff:
                        break

                    text_lower = message.text.lower()
                    if not any(kw.lower() in text_lower for kw in keywords):
                        continue

                    phones = PHONE_PATTERN.findall(message.text)
                    usernames = USERNAME_PATTERN.findall(message.text)

                    if not phones and not usernames:
                        continue

                    candidates.append({
                        "source": f"telegram:{channel}",
                        "name": "",
                        "raw_text": message.text[:2000],
                        "phone": phones[0].strip() if phones else "",
                        "username": usernames[0] if usernames else "",
                        "message_date": message.date.isoformat(),
                        "message_link": f"https://t.me/{channel.lstrip('@')}/{message.id}" if channel.startswith("@") else "",
                    })
            except Exception as e:
                logger.error(f"Error scraping channel {channel}: {e}")
                continue

        await client.disconnect()
    except Exception as e:
        logger.error(f"Telethon connection error: {e}")
        return []

    logger.info(f"TG scraper found {len(candidates)} candidates from {len(channels)} channels")
    return candidates
