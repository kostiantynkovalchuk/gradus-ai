import os
import logging

logger = logging.getLogger(__name__)


async def search_workua(vacancy: dict) -> list:
    email = os.getenv("WORKUA_EMAIL")
    password = os.getenv("WORKUA_PASSWORD")

    if not email or not password:
        logger.info("Work.ua credentials not configured (WORKUA_EMAIL/WORKUA_PASSWORD), skipping")
        return []

    logger.info(f"Work.ua scraper placeholder called for vacancy: {vacancy.get('title', 'N/A')}")
    return []
