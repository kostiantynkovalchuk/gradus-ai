import os
import asyncio
import logging

logger = logging.getLogger(__name__)


async def run_vacancy_posting(vacancy_id: int, chat_id: int, thread_id: int):
    import models
    if models.SessionLocal is None:
        models.init_db()
    db = models.SessionLocal()

    try:
        from models.hunt_models import HuntVacancy, HuntPosting
        import json

        vacancy = db.query(HuntVacancy).filter(HuntVacancy.id == vacancy_id).first()
        if not vacancy:
            logger.error(f"Vacancy #{vacancy_id} not found")
            await _send_tg_message(chat_id, thread_id, f"❌ Вакансію #{vacancy_id} не знайдено")
            return

        position = vacancy.position or "Вакансія"
        city = vacancy.city or ""
        requirements = []
        if vacancy.requirements:
            try:
                requirements = json.loads(vacancy.requirements)
            except (json.JSONDecodeError, TypeError):
                pass
        salary_max = vacancy.salary_max

        contact = os.getenv("HR_CONTACT", "@avtd_hr")
        position_tag = position.replace(" ", "_").lower()
        city_tag = city.lower() if city else "україна"

        requirements_formatted = "\n".join([f"— {r}" for r in requirements]) if requirements else "— За деталями звертайтесь"
        salary_text = f"До {salary_max}$/міс" if salary_max else "За домовленістю"

        formatted_post = (
            f"🔔 Вакансія | Торговий Дім АВ\n\n"
            f"💼 {position}\n"
            f"📍 {city}\n\n"
            f"📋 Вимоги:\n{requirements_formatted}\n\n"
            f"💰 {salary_text}\n\n"
            f"📩 Відгукнутись: {contact}\n"
            f"#вакансія #{position_tag} #{city_tag}"
        )

        import psycopg2
        try:
            conn = psycopg2.connect(os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL"))
            cur = conn.cursor()
            cur.execute(
                "SELECT tg_channel FROM hunt_sources "
                "WHERE is_active = TRUE AND channel_type = 'post'"
            )
            rows = cur.fetchall()
            channels = [row[0] for row in rows]
            conn.close()
            logger.info(f"Poster loaded {len(channels)} channels (post type)")
        except Exception as e:
            logger.warning(f"DB channel load failed: {e}")
            channels = []

        if not channels:
            await _send_tg_message(
                chat_id, thread_id,
                "📢 Немає активних каналів для розміщення.\n"
                "Додайте канали з type='post' до таблиці hunt_sources."
            )
            return

        session_string = os.getenv("HR_TELETHON_SESSION") or os.getenv("TELETHON_SESSION")
        api_id_str = os.getenv("TELETHON_API_ID", "0")
        api_hash = os.getenv("TELETHON_API_HASH", "")

        if not session_string or not api_hash or api_id_str == "0":
            logger.warning("Telethon credentials not configured for posting")
            await _send_tg_message(
                chat_id, thread_id,
                "⚠️ Telethon не налаштовано. Встановіть HR_TELETHON_SESSION в env vars."
            )
            return

        api_id = int(api_id_str)

        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
        except ImportError:
            logger.error("telethon not installed")
            await _send_tg_message(chat_id, thread_id, "❌ Telethon не встановлено.")
            return

        posted = []
        failed = []

        try:
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
            await client.connect()

            for channel in channels:
                try:
                    await client.send_message(channel, formatted_post)
                    posted.append(channel)
                    db.add(HuntPosting(vacancy_id=vacancy_id, channel=channel, status='posted'))
                except Exception as e:
                    logger.error(f"Failed to post to {channel}: {e}")
                    failed.append(channel)
                    db.add(HuntPosting(vacancy_id=vacancy_id, channel=channel, status='failed', error_message=str(e)[:500]))
                db.commit()
                await asyncio.sleep(3)

            await client.disconnect()
        except Exception as e:
            logger.error(f"Telethon connection error: {e}")
            db.commit()
            await _send_tg_message(chat_id, thread_id, f"❌ Помилка Telethon: {str(e)[:200]}")
            return

        vacancy.status = 'posted'
        db.commit()

        report = f"📢 Вакансію розміщено!\n\n"
        report += f"✅ Успішно: {len(posted)} каналів\n"
        if failed:
            report += f"❌ Помилка: {len(failed)} каналів\n"
        if posted:
            report += f"\nКанали: {', '.join(['@' + c for c in posted])}"

        await _send_tg_message(chat_id, thread_id, report)
        logger.info(f"Vacancy #{vacancy_id} posted to {len(posted)} channels, {len(failed)} failed")

    except Exception as e:
        logger.error(f"Vacancy posting error: {e}", exc_info=True)
        await _send_tg_message(chat_id, thread_id, f"❌ Помилка розміщення: {str(e)[:200]}")
    finally:
        db.close()


async def _send_tg_message(chat_id: int, thread_id: int, text: str):
    import httpx
    bot_token = os.getenv("TELEGRAM_MAYA_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if thread_id:
        payload["message_thread_id"] = thread_id
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=15.0)
    except Exception as e:
        logger.error(f"TG send error in poster: {e}")
