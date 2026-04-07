"""
Telegram channel auto-posting service.
Posts approved articles to @gradus_media_ua on a scheduled queue.
Slots (Kyiv time = UTC+2): 08:00, 13:00, 19:00
"""

import logging
import os
import requests as http_requests
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

KYIV_OFFSET = timedelta(hours=2)
KYIV_TZ = timezone(KYIV_OFFSET)
POSTING_SLOTS = [8, 13, 19]          # hour in Kyiv local time
MAX_CAPTION = 1024
ARTICLE_BASE_URL = "https://gradusmedia.org/article"
HASHTAGS = "\n\n#GradusAI #HoReCa #Бар #Маркетинг"


def _kyiv_now() -> datetime:
    return datetime.now(tz=KYIV_TZ)


def _slot_datetime_utc(date: datetime, hour: int) -> datetime:
    """Return UTC datetime for a Kyiv-time slot on the given date."""
    local = datetime(date.year, date.month, date.day, hour, 0, 0, tzinfo=KYIV_TZ)
    return local.astimezone(timezone.utc)


def get_next_available_slot_utc(db) -> datetime:
    """
    Find the next posting slot that is not already taken.
    Slots: 08:00, 13:00, 19:00 Kyiv time.
    Tries today's remaining slots first, then advances day-by-day.
    """
    from models.content import ContentQueue

    now_kyiv = _kyiv_now()

    for days_ahead in range(0, 30):
        candidate_date = now_kyiv + timedelta(days=days_ahead)
        for hour in POSTING_SLOTS:
            slot_utc = _slot_datetime_utc(candidate_date, hour)
            # Slot must be in the future
            if slot_utc <= datetime.now(tz=timezone.utc):
                continue
            # Slot must be unclaimed
            taken = db.query(ContentQueue).filter(
                ContentQueue.channel_status == "queued",
                ContentQueue.channel_scheduled_at == slot_utc.replace(tzinfo=None),
            ).first()
            if not taken:
                return slot_utc

    # Fallback (should never happen): tomorrow 08:00
    tomorrow = now_kyiv + timedelta(days=1)
    return _slot_datetime_utc(tomorrow, 8)


def queue_article_for_channel(article, db) -> datetime:
    """
    Set channel_status='queued' and channel_scheduled_at on article.
    Returns the scheduled UTC datetime.
    Does NOT commit — caller is responsible.
    """
    slot_utc = get_next_available_slot_utc(db)
    article.channel_status = "queued"
    article.channel_scheduled_at = slot_utc.replace(tzinfo=None)  # store naive UTC
    return slot_utc


def _build_caption(article) -> str:
    """Build Telegram caption under 1024 chars."""
    title = article.translated_title or article.extra_metadata.get("title", "") if article.extra_metadata else ""
    content = article.translated_text or ""
    link = f"{ARTICLE_BASE_URL}/{article.id}"

    fixed = f"📌 <b>{title}</b>\n\n"
    suffix = f"\n\n👉 Читати повністю: {link}{HASHTAGS}"
    available = MAX_CAPTION - len(fixed) - len(suffix)

    if len(content) > available:
        content = content[:available - 3] + "..."

    return fixed + content + suffix


def _download_image(url: str) -> Optional[bytes]:
    try:
        resp = http_requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning(f"Failed to download image {url}: {e}")
        return None


def post_article_to_channel(article, db) -> bool:
    """
    Download image and post article to the Telegram channel.
    Updates channel_status and channel_posted_at on success/failure.
    Does NOT commit — caller is responsible.
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("GRADUS_CHANNEL_ID", "-1003885641833")

    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set — cannot post to channel")
        article.channel_status = "failed"
        return False

    base_url = f"https://api.telegram.org/bot{bot_token}"
    caption = _build_caption(article)

    try:
        image_bytes = _download_image(article.image_url) if article.image_url else None

        if image_bytes:
            resp = http_requests.post(
                f"{base_url}/sendPhoto",
                data={"chat_id": channel_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": ("image.jpg", image_bytes, "image/jpeg")},
                timeout=30,
            )
        else:
            logger.warning(f"Article {article.id} has no image — sending text message")
            resp = http_requests.post(
                f"{base_url}/sendMessage",
                json={"chat_id": channel_id, "text": caption, "parse_mode": "HTML"},
                timeout=15,
            )

        result = resp.json()
        if result.get("ok"):
            article.channel_status = "posted"
            article.channel_posted_at = datetime.utcnow()
            logger.info(f"✅ Article {article.id} posted to channel")
            return True
        else:
            error = result.get("description", "Unknown error")
            logger.error(f"Telegram API error for article {article.id}: {error}")
            article.channel_status = "failed"
            _notify_approval_group(base_url, article, error)
            return False

    except Exception as e:
        logger.error(f"Error posting article {article.id} to channel: {e}")
        article.channel_status = "failed"
        _notify_approval_group(base_url, article, str(e))
        return False


def _notify_approval_group(base_url: str, article, error: str):
    """Send failure notification to the approval group."""
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        return
    title = (article.translated_title or "")[:60]
    try:
        http_requests.post(
            f"{base_url}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"❌ Помилка публікації в канал: <b>{title}</b> — {error[:200]}",
                "parse_mode": "HTML",
            },
            timeout=10,
        )
    except Exception as ex:
        logger.warning(f"Could not send failure notification: {ex}")


def process_channel_queue(db_session_factory):
    """
    Scheduler job: post any queued articles whose slot time has passed.
    Called every 5 minutes by APScheduler.
    """
    from models.content import ContentQueue

    db = db_session_factory()
    try:
        now_utc = datetime.utcnow()
        due = (
            db.query(ContentQueue)
            .filter(
                ContentQueue.channel_status == "queued",
                ContentQueue.channel_scheduled_at <= now_utc,
            )
            .all()
        )
        if not due:
            return

        logger.info(f"Channel queue: {len(due)} article(s) due for posting")
        for article in due:
            post_article_to_channel(article, db)
            db.commit()

    except Exception as e:
        logger.error(f"Error in process_channel_queue: {e}")
        db.rollback()
    finally:
        db.close()


def run_startup_recovery(db_session_factory):
    """
    On startup: immediately post any overdue queued articles
    (missed due to cold start or downtime).
    """
    from models.content import ContentQueue

    db = db_session_factory()
    try:
        now_utc = datetime.utcnow()
        overdue = (
            db.query(ContentQueue)
            .filter(
                ContentQueue.channel_status == "queued",
                ContentQueue.channel_scheduled_at <= now_utc,
            )
            .all()
        )
        if not overdue:
            logger.info("Channel startup recovery: no overdue articles")
            return

        logger.info(f"Channel startup recovery: posting {len(overdue)} overdue article(s)")
        for article in overdue:
            post_article_to_channel(article, db)
            db.commit()

    except Exception as e:
        logger.error(f"Error in run_startup_recovery: {e}")
        db.rollback()
    finally:
        db.close()


def send_queue_confirmation(article, slot_utc: datetime):
    """
    Send a confirmation message to the approval group:
    '📅 Стаття додана в чергу публікації: [дата] о [час] за Києвом'
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        return

    slot_kyiv = slot_utc.astimezone(KYIV_TZ)
    date_str = slot_kyiv.strftime("%d.%m.%Y")
    time_str = slot_kyiv.strftime("%H:%M")

    title = (article.translated_title or "")[:80]
    text = (
        f"📅 <b>Стаття додана в чергу публікації</b>\n"
        f"📰 {title}\n"
        f"🕐 {date_str} о {time_str} за Києвом"
    )

    try:
        http_requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Could not send queue confirmation: {e}")
