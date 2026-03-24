"""
Team Pulse — Employee Mood Intelligence Service

Handles:
1. Monthly mood survey dispatch (15th of month, weekday)
2. Behavioral trigger keyword detection
3. Psychological support video/message delivery
4. HR alert notifications
5. DB writes for pulse_surveys, pulse_triggers, pulse_risk_scores, pulse_video_views
"""

import hashlib
import logging
import os
from datetime import datetime

import httpx
from sqlalchemy import text

import models as _models

logger = logging.getLogger(__name__)

TELEGRAM_MAYA_BOT_TOKEN = os.getenv("TELEGRAM_MAYA_BOT_TOKEN")
HR_ALERT_CHAT_ID = os.getenv("HR_ALERT_CHAT_ID")

# ── NEW V2 CONSTANTS ──────────────────────────────────────────────────────────

PULSE_SCALE: dict[int, dict] = {
    3: {"emoji": "💚", "label": "тримаюсь впевнено 💪"},
    2: {"emoji": "💛", "label": "нормально, буває різне"},
    1: {"emoji": "💔", "label": "стоп, перевантаження"},
}

PROBLEM_CATEGORIES: dict[str, str] = {
    "colleagues": "Комунікація з колегами",
    "manager": "Комунікація з керівником",
    "tasks": "Складність задач",
    "other": "Інше",
}

# In-process state: {telegram_id: month_key} for "Інше" free-text capture
PULSE_AWAITING_TEXT: dict[int, str] = {}

# Deduplication: which survey months have already been dispatched (in-process)
_PULSE_SURVEY_DISPATCHED: set[str] = set()

# ── TRIGGER KEYWORDS ──────────────────────────────────────────────────────────

TRIGGER_KEYWORDS: dict[str, list[str]] = {
    "вигорання": [
        "вигоранн", "вигорів", "вигоріла", "вигоріли",
        "більше не можу", "вимотав", "вимотала", "виснажений", "виснажена", "виснаження",
        "набридло", "набридла", "апатія", "не хочу йти на роботу",
        "немає сил", "все набридло", "втомилась", "втомився від роботи",
        "хочу все кинути", "не можу більше", "втом", "перенавантаженн", "перевтом",
        "burnout", "burned out", "burnt out",
    ],
    "конфлікт": [
        "конфлікт", "конфліктую", "посварились", "посварилась", "посварився", "сварк",
        "кричали", "кричав на мене", "кричала на мене", "образили", "образив",
        "моббінг", "тиснуть", "погрожують", "погрожує", "зацькували", "цькуванн", "булінг",
        "знущаються", "знущається", "неповага", "упереджене ставлення",
        "не можу працювати з", "проблема з колегою", "проблема з начальник",
        "conflict",
    ],
    "стрес": [
        "стрес", "паніка", "тривога", "не можу заснути", "нервую",
        "депресія", "депресивний", "тривожність", "панікую", "погано сплю",
        "постійно нервую", "серце болить", "тиск", "мігрень від роботи",
        "психологічний тиск",
        "stress",
    ],
    "плачу": [
        "плачу", "ридаю", "плакала", "плакав", "плаче", "сльози",
        "хочеться плакати", "зривають на мені", "незаслужено",
        "cry", "crying",
    ],
    "звільнення": [
        "звільн", "заяв", "розрахунок", "розрахуватися", "звільнюсь",
        "хочу звільнитись", "думаю звільнитись", "піти з роботи",
        "шукаю нову роботу", "піду звідси", "не витримую більше",
        "підшукую роботу", "готую резюме щоб піти", "хочу піти",
        "як звільнитися", "як звільнитись", "звільнитися", "звільнитись",
        "процедура звільнення", "заява на звільнення", "хочу звільнитися",
        "dismiss", "quit", "resign",
    ],
    "права": [
        "мої права", "порушенн", "незаконн", "трудовий кодекс", "кзпп", "інспекція праці",
    ],
}

TRIGGER_VIDEO_MAP: dict[str, str] = {
    "вигорання": "video_values.mp4",
    "конфлікт": "video_values.mp4",
    "стрес": "video_values.mp4",
    "плачу": "video_values.mp4",
    "звільнення": "video_offboarding.mp4",
    "права": "video_values.mp4",
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
    "права": (
        "💛 *Твої права важливі.*\n\n"
        "Якщо ти вважаєш, що щось порушено — HR-команда допоможе розібратись.\n\n"
        "📞 Зверніться до HR-відділу — всі звернення конфіденційні."
    ),
}

# ── RISK SCORE ENGINE ─────────────────────────────────────────────────────────

RISK_POINTS: dict[str, int] = {
    "звільнення": 3,
    "конфлікт": 1,
    "вигорання": 1,
    "стрес": 1,
    "плачу": 1,
    "права": 1,
}

RISK_THRESHOLD_ALERT = 4
RISK_THRESHOLD_URGENT = 7

# ── PULSE VIDEO MAPPING ───────────────────────────────────────────────────────

PULSE_VIDEOS: dict[str, str] = {
    "breathing": "pulse_breathing.mp4",
    "conflict": "pulse_conflict.mp4",
    "burnout": "pulse_burnout.mp4",
    "decision": "pulse_decision.mp4",
    "resignation": "pulse_decision.mp4",
    "rights": "pulse_conflict.mp4",
    "stress": "pulse_burnout.mp4",
}

PULSE_VIDEO_FALLBACK_TEXT: dict[str, str] = {
    "breathing": (
        "🫁 Пауза для дихання\n\n"
        "Вдихни на 4 рахунки… затримай на 4… видихни на 4… пауза на 4.\n"
        "Повтори 3 рази. Твоє тіло вже трохи розслабилось.\n\n"
        "Якщо потрібна підтримка — напиши HR."
    ),
    "conflict": (
        "🤝 Конфлікт — це не кінець\n\n"
        "Спробуй замінити «Ти завжди…» на «Я відчуваю… коли…».\n"
        "Це не слабкість — це навичка.\n"
        "HR може допомогти як нейтральна сторона."
    ),
    "burnout": (
        "🌿 Зупинись і подивись\n\n"
        "Назви 5 речей, які бачиш… 4 звуки… 3 дотики… 2 запахи… 1 смак.\n"
        "Що забирає твою енергію сьогодні? Що її дає?\n"
        "Іноді достатньо змінити одну маленьку річ."
    ),
    "decision": (
        "📋 Перед рішенням\n\n"
        "Візьми аркуш паперу. Зліва: що тримає мене тут. Справа: що штовхає звідси.\n"
        "Подивись через день, коли емоції вляжуться.\n"
        "Поговори з HR — не щоб звільнитися, а щоб подивитися варіанти."
    ),
}


def detect_pulse_trigger(text: str) -> str | None:
    """
    Scan message text for emotional trigger keywords.
    Returns trigger_type string (e.g. 'вигорання') or None.
    """
    text_lower = text.lower()
    logger.info(f"PULSE_DETECT: checking '{text[:50]}' against {len(TRIGGER_KEYWORDS)} keywords")
    for trigger_type, keywords in TRIGGER_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                logger.info(f"[PULSE] Trigger detected: {trigger_type} (keyword: '{kw}')")
                return trigger_type
    return None


def log_trigger(
    department: str | None,
    position: str | None,
    trigger_type: str,
    employee_id: int | None = None,
    employee_name: str | None = None,
    trigger_text: str | None = None,
) -> int | None:
    """
    Insert a trigger event into pulse_triggers.
    Returns the new trigger id, or None on failure.
    """
    severity = "red" if trigger_type == "звільнення" else "yellow"
    points = RISK_POINTS.get(trigger_type, 1)
    try:
        db = _models.SessionLocal()
        try:
            result = db.execute(
                text(
                    "INSERT INTO pulse_triggers "
                    "(department, position, trigger_type, fired_at, "
                    " employee_id, employee_name, trigger_text, severity, risk_points) "
                    "VALUES (:dept, :pos, :ttype, NOW(), "
                    " :eid, :ename, :ttext, :sev, :pts) "
                    "RETURNING id"
                ),
                {
                    "dept": department,
                    "pos": position,
                    "ttype": trigger_type,
                    "eid": employee_id,
                    "ename": employee_name,
                    "ttext": trigger_text[:500] if trigger_text else None,
                    "sev": severity,
                    "pts": points,
                },
            )
            trigger_id = result.fetchone()[0]
            db.commit()
            logger.info(
                f"[PULSE] Trigger logged: {trigger_type} | dept={department} | "
                f"employee={employee_name} | id={trigger_id}"
            )
            return trigger_id
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[PULSE] log_trigger failed: {e}")
        return None


def update_risk_score(
    employee_id: int,
    employee_name: str,
    department: str | None,
    points: int,
) -> bool:
    """
    Update rolling risk score for an employee via UPSERT.
    Returns True ONLY if this update crosses the RISK_THRESHOLD_ALERT.
    """
    try:
        db = _models.SessionLocal()
        try:
            prev_row = db.execute(
                text("SELECT current_score FROM pulse_risk_scores WHERE employee_id = :eid"),
                {"eid": employee_id},
            ).fetchone()
            prev_score = prev_row[0] if prev_row else 0

            db.execute(
                text("""
                    INSERT INTO pulse_risk_scores
                        (employee_id, employee_name, department, current_score,
                         last_trigger_at, last_calculated_at, alert_status)
                    VALUES (:eid, :ename, :dept, :pts, NOW(), NOW(), 'none')
                    ON CONFLICT (employee_id) DO UPDATE SET
                        current_score = pulse_risk_scores.current_score + :pts,
                        employee_name = :ename,
                        department = :dept,
                        last_trigger_at = NOW(),
                        last_calculated_at = NOW(),
                        alert_status = CASE
                            WHEN pulse_risk_scores.current_score + :pts >= :urgent THEN 'urgent'
                            WHEN pulse_risk_scores.current_score + :pts >= :alert  THEN 'red'
                            ELSE pulse_risk_scores.alert_status
                        END
                """),
                {
                    "eid": employee_id,
                    "ename": employee_name,
                    "dept": department,
                    "pts": points,
                    "urgent": RISK_THRESHOLD_URGENT,
                    "alert": RISK_THRESHOLD_ALERT,
                },
            )
            db.commit()

            new_score = prev_score + points
            crossed = prev_score < RISK_THRESHOLD_ALERT and new_score >= RISK_THRESHOLD_ALERT
            logger.info(
                f"[PULSE] Risk score updated: emp={employee_id}, "
                f"prev={prev_score} → new={new_score}, threshold_crossed={crossed}"
            )
            return crossed
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[PULSE] update_risk_score failed: {e}")
        return False


def log_hr_action(trigger_id: int, action: str, hr_user: str) -> None:
    """Log HR response to an alert; reduce risk score by 2 on resolve/false_positive."""
    try:
        db = _models.SessionLocal()
        try:
            row = db.execute(
                text("SELECT employee_id FROM pulse_triggers WHERE id = :tid"),
                {"tid": trigger_id},
            ).fetchone()

            risk_score_id = None
            if row and row[0]:
                r = db.execute(
                    text("SELECT id FROM pulse_risk_scores WHERE employee_id = :eid"),
                    {"eid": row[0]},
                ).fetchone()
                risk_score_id = r[0] if r else None

            db.execute(
                text("""
                    INSERT INTO pulse_hr_actions (trigger_id, risk_score_id, action, hr_user)
                    VALUES (:tid, :rsid, :action, :hr)
                """),
                {"tid": trigger_id, "rsid": risk_score_id, "action": action, "hr": hr_user},
            )

            if action in ("resolved", "false_positive") and row and row[0]:
                db.execute(
                    text("""
                        UPDATE pulse_risk_scores
                        SET current_score = GREATEST(0, current_score - 2),
                            alert_status = CASE
                                WHEN current_score - 2 <= 0 THEN 'none'
                                ELSE alert_status
                            END,
                            last_calculated_at = NOW()
                        WHERE employee_id = :eid
                    """),
                    {"eid": row[0]},
                )

            db.commit()
            logger.info(f"[PULSE] HR action logged: {action} | trigger_id={trigger_id} | by={hr_user}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[PULSE] log_hr_action failed: {e}")


def record_mood(
    telegram_id: int,
    score: int,
    db,
    month_key: str | None = None,
) -> tuple[bool, str | None]:
    """
    Store mood score for the current month (identified — stores telegram_id + name).
    Returns (already_voted: bool, department: str | None).
    """
    from models.hr_auth_models import HRUser

    user = db.query(HRUser).filter(HRUser.telegram_id == telegram_id).first()
    department = user.department if user else None
    employee_name = user.full_name if user else None

    survey_month = month_key or datetime.utcnow().strftime("%Y-%m")

    existing = db.execute(
        text("SELECT id FROM pulse_surveys WHERE telegram_id = :tid AND survey_month = :sm"),
        {"tid": telegram_id, "sm": survey_month},
    ).fetchone()

    if existing:
        return True, department

    db.execute(
        text(
            "INSERT INTO pulse_surveys "
            "(telegram_id, employee_name, department, score, survey_month, responded_at) "
            "VALUES (:tid, :ename, :dept, :score, :sm, NOW())"
        ),
        {
            "tid": telegram_id,
            "ename": employee_name,
            "dept": department,
            "score": score,
            "sm": survey_month,
        },
    )
    db.commit()

    if score == 1:
        try:
            db.execute(
                text("""
                    INSERT INTO pulse_risk_scores
                        (employee_id, employee_name, department, current_score,
                         last_trigger_at, last_calculated_at, alert_status)
                    VALUES (:eid, :ename, :dept, 2, NOW(), NOW(), 'red')
                    ON CONFLICT (employee_id) DO UPDATE SET
                        current_score = pulse_risk_scores.current_score + 2,
                        employee_name = :ename,
                        department = :dept,
                        last_trigger_at = NOW(),
                        last_calculated_at = NOW(),
                        alert_status = CASE
                            WHEN pulse_risk_scores.current_score + 2 >= :urgent THEN 'urgent'
                            ELSE 'red'
                        END
                """),
                {
                    "eid": telegram_id,
                    "ename": employee_name or "Unknown",
                    "dept": department,
                    "urgent": RISK_THRESHOLD_URGENT,
                },
            )
            db.commit()
        except Exception as e:
            logger.warning(f"[PULSE] Risk score update from survey failed: {e}")

    logger.info(f"[PULSE] Mood recorded: score={score}, dept={department}, month={survey_month}, tid={telegram_id}")
    return False, department


async def alert_hr_team(trigger_type: str, department: str | None) -> None:
    """Send an anonymous HR alert to HR_ALERT_CHAT_ID (if configured)."""
    if not HR_ALERT_CHAT_ID or not TELEGRAM_MAYA_BOT_TOKEN:
        return
    try:
        ts = datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")
        dept_str = department or "Невідомий відділ"
        text_msg = (
            f"🔴 *Пульс команди — Попередження*\n"
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


async def send_pulse_video(chat_id: int, trigger_or_video_id: str) -> None:
    """
    Send a support video for the given trigger type or video_id.
    Falls back to a text message if the video file is not present.
    """
    if not TELEGRAM_MAYA_BOT_TOKEN:
        return

    fallback_key = trigger_or_video_id
    if fallback_key == "звільнення":
        fallback_key = "decision"
    elif fallback_key in ("конфлікт", "права"):
        fallback_key = "conflict"
    elif fallback_key in ("вигорання", "стрес", "плачу"):
        fallback_key = "burnout"

    video_file = PULSE_VIDEOS.get(trigger_or_video_id) or PULSE_VIDEOS.get(fallback_key)
    video_sent = False

    if video_file:
        import pathlib
        video_path = pathlib.Path(__file__).parent.parent / "static" / "pulse_videos" / video_file
        if video_path.exists():
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    with open(video_path, "rb") as f:
                        resp = await client.post(
                            f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendVideo",
                            data={"chat_id": str(chat_id), "supports_streaming": "true"},
                            files={"video": (video_file, f, "video/mp4")},
                        )
                if resp.status_code == 200:
                    video_sent = True
                    logger.info(f"[PULSE] Pulse video sent: {video_file} → {chat_id}")
            except Exception as e:
                logger.warning(f"[PULSE] Pulse video send failed ({video_file}): {e}")

    if not video_sent:
        msg = PULSE_VIDEO_FALLBACK_TEXT.get(
            fallback_key,
            PULSE_VIDEO_FALLBACK_TEXT["breathing"],
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                )
            logger.info(f"[PULSE] Pulse video fallback text sent: {fallback_key} → {chat_id}")
        except Exception as e:
            logger.warning(f"[PULSE] Pulse video fallback failed: {e}")


def log_video_view(telegram_id: int, video_id: str) -> None:
    """Log video view to pulse_video_views (privacy-hashed)."""
    _salt = "teamPulse2026avtd"
    emp_hash = hashlib.sha256(f"{telegram_id}:{_salt}".encode()).hexdigest()
    try:
        db = _models.SessionLocal()
        try:
            db.execute(
                text("INSERT INTO pulse_video_views (employee_hash, video_id) VALUES (:h, :vid)"),
                {"h": emp_hash, "vid": video_id},
            )
            db.commit()
            logger.info(f"[PULSE] Video view logged: {video_id}")
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[PULSE] log_video_view failed: {e}")


def get_risk_history(employee_id: int, limit: int = 5) -> list[dict]:
    """
    Return the last 5 pulse_triggers within the past 30 days for an employee,
    ordered newest-first.
    """
    try:
        db = _models.SessionLocal()
        try:
            rows = db.execute(
                text("""
                    SELECT id, trigger_type, severity, risk_points, trigger_text, fired_at
                    FROM pulse_triggers
                    WHERE employee_id = :eid
                      AND fired_at >= NOW() - INTERVAL '30 days'
                    ORDER BY fired_at DESC
                    LIMIT :lim
                """),
                {"eid": employee_id, "lim": limit},
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "trigger_type": r[1],
                    "severity": r[2],
                    "risk_points": r[3],
                    "trigger_text": r[4],
                    "fired_at": r[5].isoformat() if r[5] else None,
                }
                for r in rows
            ]
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[PULSE] get_risk_history failed: {e}")
        return []


async def send_pulse_meme(chat_id: int) -> bool:
    """
    Send a random meme from pulse_memes table.
    Returns True if a meme was sent, False if fallback text was used.
    """
    if not TELEGRAM_MAYA_BOT_TOKEN:
        return False

    try:
        db = _models.SessionLocal()
        try:
            row = db.execute(
                text("SELECT id, file_id, file_url, caption FROM pulse_memes WHERE is_active = TRUE ORDER BY RANDOM() LIMIT 1")
            ).fetchone()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[PULSE] send_pulse_meme DB error: {e}")
        row = None

    meme_keyboard = {
        "inline_keyboard": [
            [{"text": "😄 Ще один мем", "callback_data": "hr_pulse:meme"}],
        ]
    }

    if row:
        meme_id, file_id, file_url, caption = row
        photo_src = file_id or file_url
        caption_text = caption or "😄"
        if photo_src:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendPhoto",
                        json={
                            "chat_id": chat_id,
                            "photo": photo_src,
                            "caption": caption_text,
                            "reply_markup": meme_keyboard,
                        },
                    )
                if resp.status_code == 200:
                    logger.info(f"[PULSE] Meme sent (id={meme_id}) to {chat_id}")
                    return True
                logger.warning(f"[PULSE] sendPhoto failed: {resp.status_code} {resp.text[:100]}")
            except Exception as e:
                logger.warning(f"[PULSE] Meme send error: {e}")

    fallback = "😄 Мем-терапія поки що готується! А поки що — зроби перерву на каву ☕"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_MAYA_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": fallback,
                    "reply_markup": meme_keyboard,
                },
            )
    except Exception as e:
        logger.warning(f"[PULSE] Meme fallback failed: {e}")
    return False


def send_monthly_survey() -> int:
    """
    Scheduled task: send mood survey to all active hr_users.
    Dispatches on the 15th of the month (or nearest weekday 13–17).
    Called daily by APScheduler — function handles date/weekday validation.
    Returns count of successfully sent messages.
    """
    today = datetime.utcnow()

    if not (13 <= today.day <= 17):
        logger.debug(f"[PULSE] Survey day check: day={today.day} not in 13-17 window, skipping")
        return 0

    if today.weekday() > 4:
        logger.info(f"[PULSE] Survey day check: day={today.day} is weekend, skipping")
        return 0

    month_key = today.strftime("%Y-%m")
    if month_key in _PULSE_SURVEY_DISPATCHED:
        logger.info(f"[PULSE] Survey already dispatched for {month_key}, skipping")
        return 0

    if not TELEGRAM_MAYA_BOT_TOKEN:
        logger.warning("[PULSE] TELEGRAM_MAYA_BOT_TOKEN not set — survey skipped")
        return 0

    _PULSE_SURVEY_DISPATCHED.add(month_key)

    db = _models.SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT telegram_id, first_name FROM hr_users "
                "WHERE is_active = TRUE AND telegram_id IS NOT NULL"
            )
        ).fetchall()
        logger.info(f"[PULSE] Sending monthly survey ({month_key}) to {len(rows)} users")

        survey_keyboard = {
            "inline_keyboard": [
                [{"text": "💚 Тримаюсь впевнено 💪", "callback_data": f"hr_pulse:mood:3:{month_key}"}],
                [{"text": "💛 Нормально, буває різне", "callback_data": f"hr_pulse:mood:2:{month_key}"}],
                [{"text": "💔 Стоп, перевантаження", "callback_data": f"hr_pulse:mood:1:{month_key}"}],
            ]
        }
        survey_text = (
            "❤️ *Пульс команди*\n\n"
            "Як би ти описав/описала своє робоче самопочуття?"
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
            return sent

        sent_count = 0
        try:
            sent_count = asyncio.run(_send_all(rows))
        except Exception as e:
            logger.error(f"[PULSE] Async survey send failed: {e}")
        return sent_count

    except Exception as e:
        logger.error(f"[PULSE] send_monthly_survey failed: {e}")
        _PULSE_SURVEY_DISPATCHED.discard(month_key)
        return 0
    finally:
        db.close()
