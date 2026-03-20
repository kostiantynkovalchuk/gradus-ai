"""
Team Pulse — Employee Mood Intelligence Service

Handles:
1. Monthly anonymous mood survey dispatch
2. Behavioral trigger keyword detection
3. Psychological support video/message delivery
4. HR alert notifications
5. DB writes for pulse_surveys and pulse_triggers
"""

import hashlib
import logging
import os
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_MAYA_BOT_TOKEN = os.getenv("TELEGRAM_MAYA_BOT_TOKEN")
HR_ALERT_CHAT_ID = os.getenv("HR_ALERT_CHAT_ID")

TRIGGER_KEYWORDS: dict[str, list[str]] = {
    "вигорання": [
        "вигорів", "вигоріла", "вигоріли", "вигорання", "більше не можу",
        "вимотав", "вимотала", "виснажений", "виснажена", "виснаження",
        "набридло", "набридла", "апатія", "апатія", "не хочу йти на роботу",
        "немає сил", "все набридло", "втомилась", "втомився від роботи",
        "хочу все кинути",
    ],
    "конфлікт": [
        "конфлікт", "конфліктую", "посварились", "посварилась", "посварився",
        "кричали", "кричав на мене", "кричала на мене", "образили", "образив",
        "моббінг", "тиснуть", "погрожують", "погрожує", "зацькували",
        "знущаються", "знущається", "неповага", "упереджене ставлення",
    ],
    "стрес": [
        "стрес", "паніка", "тривога", "не можу заснути", "нервую",
        "депресія", "депресивний", "тривожність", "панікую", "погано сплю",
        "постійно нервую", "серце болить", "тиск", "мігрень від роботи",
        "психологічний тиск",
    ],
    "плачу": [
        "плачу", "ридаю", "плакала", "плакав", "плаче", "сльози",
        "хочеться плакати", "зривають на мені", "незаслужено",
    ],
    "звільнення": [
        "хочу звільнитись", "думаю звільнитись", "піти з роботи",
        "шукаю нову роботу", "піду звідси", "не витримую більше",
        "підшукую роботу", "готую резюме щоб піти", "хочу піти",
    ],
}

TRIGGER_VIDEO_MAP: dict[str, str] = {
    "вигорання": "pulse_burnout.mp4",
    "конфлікт": "pulse_conflict.mp4",
    "стрес": "pulse_stress.mp4",
    "плачу": "pulse_stress.mp4",
    "звільнення": "pulse_support.mp4",
}

TRIGGER_SUPPORT_TEXT: dict[str, str] = {
    "вигорання": (
        "💛 *Я чую тебе.*\n\n"
        "Вигорання — це реальна проблема, і важливо про неї говорити.\n\n"
        "Ти не один(а). HR-команда готова підтримати:\n"
        "📞 Зверніться до свого HR-партнера або напишіть у корпоративний чат."
    ),
    "конфлікт": (
        "💛 *Конфліктні ситуації на роботі — це важко.*\n\n"
        "Твоя безпека та комфорт — пріоритет для ТД АВ.\n\n"
        "Якщо ситуація потребує втручання:\n"
        "📞 Зверніться до HR-відділу — всі звернення конфіденційні."
    ),
    "стрес": (
        "💛 *Стрес на роботі буває у кожного.*\n\n"
        "Не тримай все в собі — HR-команда поруч і готова допомогти.\n\n"
        "📞 Поговори з HR-партнером або скористайся корпоративними ресурсами підтримки."
    ),
    "плачу": (
        "💛 *Все буде добре. Ти не один(а).*\n\n"
        "Якщо щось трапилось на роботі — HR-команда завжди готова вислухати.\n\n"
        "📞 Звертайся до HR — всі розмови конфіденційні."
    ),
    "звільнення": (
        "💛 *Перш ніж приймати рішення — поговори з нами.*\n\n"
        "HR-команда може допомогти знайти рішення, яке підійде всім.\n\n"
        "📞 Зверніться до HR-партнера — можливо, є варіанти, про які ви не знали."
    ),
}


def _user_hash(telegram_id: int) -> str:
    """SHA-256 hash of telegram_id for anonymous storage."""
    return hashlib.sha256(str(telegram_id).encode()).hexdigest()


def detect_pulse_trigger(text: str) -> str | None:
    """
    Scan message text for emotional trigger keywords.
    Returns trigger_type string (e.g. 'вигорання') or None.
    Checks longest/most specific triggers first within each group.
    """
    text_lower = text.lower()
    for trigger_type, keywords in TRIGGER_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                logger.info(f"[PULSE] Trigger detected: {trigger_type} (keyword: '{kw}')")
                return trigger_type
    return None


def log_trigger(department: str | None, position: str | None, trigger_type: str) -> None:
    """Synchronously insert a trigger event into pulse_triggers."""
    try:
        import models
        if models.SessionLocal is None:
            models.init_db()
        db = models.SessionLocal()
        try:
            from sqlalchemy import text
            db.execute(
                text(
                    "INSERT INTO pulse_triggers (department, position, trigger_type, fired_at) "
                    "VALUES (:dept, :pos, :ttype, NOW())"
                ),
                {"dept": department, "pos": position, "ttype": trigger_type},
            )
            db.commit()
            logger.info(f"[PULSE] Trigger logged: {trigger_type} | dept={department}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[PULSE] log_trigger failed: {e}")


def record_mood(telegram_id: int, score: int, db) -> tuple[bool, str | None]:
    """
    Store anonymous mood score for the current month.
    Returns (already_voted: bool, department: str | None).
    """
    from sqlalchemy import text
    from models.hr_auth_models import HRUser

    user = db.query(HRUser).filter(HRUser.telegram_id == telegram_id).first()
    department = user.department if user else None

    user_h = _user_hash(telegram_id)
    survey_month = datetime.utcnow().strftime("%Y-%m")

    existing = db.execute(
        text(
            "SELECT id FROM pulse_surveys WHERE user_hash = :uh AND survey_month = :sm"
        ),
        {"uh": user_h, "sm": survey_month},
    ).fetchone()

    if existing:
        return True, department

    db.execute(
        text(
            "INSERT INTO pulse_surveys (user_hash, department, score, survey_month, responded_at) "
            "VALUES (:uh, :dept, :score, :sm, NOW())"
        ),
        {"uh": user_h, "dept": department, "score": score, "sm": survey_month},
    )
    db.commit()
    logger.info(f"[PULSE] Mood recorded: score={score}, dept={department}, month={survey_month}")
    return False, department


async def alert_hr_team(trigger_type: str, department: str | None) -> None:
    """Send an HR alert to HR_ALERT_CHAT_ID (if configured)."""
    if not HR_ALERT_CHAT_ID or not TELEGRAM_MAYA_BOT_TOKEN:
        return
    try:
        ts = datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")
        dept_str = department or "Невідомий відділ"
        text_msg = (
            f"🔴 *Пульс-тригер*\n"
            f"Тип: `{trigger_type}`\n"
            f"Відділ: {dept_str}\n"
            f"Час: {ts}\n\n"
            f"_Перевірте стан співробітника (конфіденційно)_"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": HR_ALERT_CHAT_ID,
                    "text": text_msg,
                    "parse_mode": "Markdown",
                },
            )
        logger.info(f"[PULSE] HR alert sent: {trigger_type} | dept={department}")
    except Exception as e:
        logger.warning(f"[PULSE] alert_hr_team failed: {e}")


async def send_pulse_support(chat_id: int, trigger_type: str) -> None:
    """
    Send a support video (if available) and a supportive text message
    for the detected trigger type.
    """
    if not TELEGRAM_MAYA_BOT_TOKEN:
        return

    support_text = TRIGGER_SUPPORT_TEXT.get(
        trigger_type,
        "💛 *Я тут і готова підтримати.*\n\nЗверніться до HR-команди — всі звернення конфіденційні.",
    )

    video_filename = TRIGGER_VIDEO_MAP.get(trigger_type)
    video_sent = False

    if video_filename:
        import pathlib
        video_path = pathlib.Path(__file__).parent.parent / "static" / "videos" / video_filename
        if video_path.exists():
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    with open(video_path, "rb") as f:
                        resp = await client.post(
                            f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendVideo",
                            data={"chat_id": str(chat_id), "supports_streaming": "true"},
                            files={"video": (video_filename, f, "video/mp4")},
                        )
                    if resp.status_code == 200:
                        video_sent = True
                        logger.info(f"[PULSE] Support video sent: {video_filename} → {chat_id}")
            except Exception as e:
                logger.warning(f"[PULSE] Video send failed ({video_filename}): {e}")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": support_text,
                    "parse_mode": "Markdown",
                },
            )
        logger.info(f"[PULSE] Support message sent: {trigger_type} → {chat_id}")
    except Exception as e:
        logger.warning(f"[PULSE] Support message failed: {e}")


def send_monthly_survey() -> None:
    """
    Scheduled task: send mood survey to all active hr_users.
    Called by APScheduler on the 1st of each month at 09:00 Kyiv time.
    """
    if not TELEGRAM_MAYA_BOT_TOKEN:
        logger.warning("[PULSE] TELEGRAM_MAYA_BOT_TOKEN not set — survey skipped")
        return

    import models
    if models.SessionLocal is None:
        models.init_db()

    db = models.SessionLocal()
    try:
        from sqlalchemy import text

        rows = db.execute(
            text(
                "SELECT telegram_id, first_name FROM hr_users "
                "WHERE is_active = TRUE AND telegram_id IS NOT NULL"
            )
        ).fetchall()
        logger.info(f"[PULSE] Sending monthly survey to {len(rows)} users")

        survey_keyboard = {
            "inline_keyboard": [
                [
                    {"text": "💔", "callback_data": "hr_pulse:mood:1"},
                    {"text": "🧡", "callback_data": "hr_pulse:mood:2"},
                    {"text": "💛", "callback_data": "hr_pulse:mood:3"},
                    {"text": "💚", "callback_data": "hr_pulse:mood:4"},
                    {"text": "💙", "callback_data": "hr_pulse:mood:5"},
                ]
            ]
        }
        survey_text = (
            "💛 *Пульс команди — щомісячне опитування*\n\n"
            "Як ти почуваєшся на роботі цього місяця?\n"
            "Оціни своє самопочуття від 💔 до 💙\n\n"
            "_Відповідь анонімна — тільки загальна статистика по відділах_"
        )

        import httpx as _httpx
        import asyncio

        async def _send_all(rows):
            sent = skipped = errors = 0
            async with _httpx.AsyncClient(timeout=10.0) as client:
                for row in rows:
                    tg_id = row[0]
                    try:
                        resp = await client.post(
                            f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendMessage",
                            json={
                                "chat_id": tg_id,
                                "text": survey_text,
                                "parse_mode": "Markdown",
                                "reply_markup": survey_keyboard,
                            },
                        )
                        if resp.status_code == 200:
                            sent += 1
                        else:
                            data = resp.json()
                            if "bot was blocked" in str(data) or "chat not found" in str(data):
                                skipped += 1
                            else:
                                logger.warning(f"[PULSE] Survey to {tg_id}: {resp.status_code}")
                                errors += 1
                    except Exception as e:
                        logger.warning(f"[PULSE] Survey send error (uid={tg_id}): {e}")
                        errors += 1
            logger.info(
                f"[PULSE] Survey complete: sent={sent}, skipped={skipped}, errors={errors}"
            )

        try:
            asyncio.run(_send_all(rows))
        except Exception as e:
            logger.error(f"[PULSE] Async survey send failed: {e}")

    except Exception as e:
        logger.error(f"[PULSE] send_monthly_survey failed: {e}")
    finally:
        db.close()
