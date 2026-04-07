"""
Onboarding Email Sequence — Alex Gradus
========================================
4 emails triggered by APScheduler (checked every 5 minutes).
All emails use maya_users as the user registry.

Sequence:
  Email 1 — Welcome       : step 0 → 1  (immediately on registration)
  Email 2 — Day 3         : step 1 → 2  (onboarding_scheduled_at + 3 days)
  Email 3 — Day 6 urgency : step 2 → 3  (onboarding_scheduled_at + 6 days)
  Email 4 — Day 8 win-back: step 3 → 4  (onboarding_scheduled_at + 8 days)

Rules:
  - Never send to paid users (standard / premium)
  - Day 3/6/8 emails require onboarding_scheduled_at to be non-NULL;
    they never fall back to registered_at (prevents mass-fire on old users)
  - onboarding_scheduled_at is always set to NOW() when Email 1 fires
  - Log every email attempt to Render logs

BUG HISTORY:
  v1 — _set_step used COALESCE(sched_at, registered_at, NOW()), which caused
       day-3/6/8 to fire immediately for existing users with old registered_at.
  v2 — fixed: sched_at is always NOW() on Email 1; day-3/6/8 skip if sched_at NULL.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import psycopg2

from services.email_service import base_template, send_email, _cta_button

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "")

CHAT_URL    = "https://gradusmedia.org/чат"
BOT_URL     = "https://t.me/alexgradus_bot"
PRICING_URL = "https://gradusmedia.org/тарифи"

HORECA_FALLBACK_HEADLINE = "Коктейльні тренди літа 2026 вже на gradusmedia.org"


def _conn():
    return psycopg2.connect(DB_URL)


def _set_step(cur, email: str, step: int, anchor_now: bool = False) -> None:
    """
    Advance a user to the given onboarding step.
    anchor_now=True → also set onboarding_scheduled_at = NOW() (used only for
    step 1 transition so day calculations are always relative to Email 1 send time).
    """
    if anchor_now:
        cur.execute(
            """UPDATE maya_users
               SET onboarding_step = %s,
                   onboarding_scheduled_at = NOW()
               WHERE email = %s""",
            (step, email),
        )
    else:
        cur.execute(
            "UPDATE maya_users SET onboarding_step = %s WHERE email = %s",
            (step, email),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Email 1 — Welcome (step 0 → 1)
# ─────────────────────────────────────────────────────────────────────────────

def _build_welcome(name: str) -> str:
    first = name.split()[0] if name else "друже"
    content = f"""
<h2 style="color:#c9a84c;margin:0 0 20px;font-size:22px;">
  Привіт, {first}! Я Alex Gradus 🥃
</h2>
<p style="margin:0 0 16px;">
  Ваш 7-денний безкоштовний доступ активовано.<br>
  Я ваш AI-експерт з прибутковості бару — допомагаю власникам HoReCa-закладів
  заробляти більше на кожному склянці.
</p>

<p style="margin:0 0 12px;font-weight:bold;color:#c9a84c;">Ось з чим я допомагаю:</p>
<ul style="margin:0 0 24px;padding-left:20px;color:#e8e8e8;">
  <li style="margin-bottom:8px;">🍹 Коктейльні тренди та побудова меню</li>
  <li style="margin-bottom:8px;">💰 Знизити витрати бару на 15–20%</li>
  <li style="margin-bottom:8px;">📋 Ліцензії, постачальники, ціноутворення</li>
</ul>

{_cta_button("Задати перше питання →", CHAT_URL)}

<p style="text-align:center;margin:0 0 24px;color:#aaa;font-size:14px;">
  або в Telegram →
  <a href="{BOT_URL}" style="color:#c9a84c;text-decoration:none;">@alexgradus_bot</a>
</p>

<p style="margin:0;color:#888;font-size:13px;text-align:center;">
  У вас 5 питань на день протягом 7 днів.
</p>
"""
    return base_template(content)


def _send_welcome(email: str, name: str) -> bool:
    return send_email(
        to=email,
        subject="Привіт від Alex 👋 Ваш trial активовано",
        html=_build_welcome(name),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Email 2 — Day 3 engagement (step 1 → 2)
# ─────────────────────────────────────────────────────────────────────────────

def _build_day3(name: str) -> str:
    first = name.split()[0] if name else "друже"
    content = f"""
<h2 style="color:#c9a84c;margin:0 0 20px;font-size:22px;">
  {first}, ось що ще вміє Alex 🥃
</h2>
<p style="margin:0 0 20px;">
  Більшість власників барів використовують Alex для зниження витрат
  і побудови прибуткового меню.
</p>

<div style="background:#0f0f1a;border-left:3px solid #c9a84c;padding:16px 20px;
            border-radius:4px;margin:0 0 24px;">
  <p style="margin:0 0 8px;color:#c9a84c;font-size:14px;font-weight:bold;">
    Питання клієнта:
  </p>
  <p style="margin:0 0 12px;font-style:italic;color:#ddd;">
    "Як знизити витрати на бар на 20%?"
  </p>
  <p style="margin:0 0 6px;color:#c9a84c;font-size:14px;font-weight:bold;">
    Alex відповів:
  </p>
  <p style="margin:0;color:#e8e8e8;">
    Аналіз собівартості коктейлів — перший крок. Найчастіше 20–30% списань
    йде на неправильний розлив. Alex допоможе знайти де саме — і дасть план
    виправлення за тиждень.
  </p>
</div>

{_cta_button("Запитати Alex зараз →", CHAT_URL)}

<p style="text-align:center;margin:24px 0 0;color:#888;font-size:13px;">
  Залишилось 4 дні trial.
</p>
"""
    return base_template(content)


def _send_day3(email: str, name: str) -> bool:
    first = name.split()[0] if name else "друже"
    return send_email(
        to=email,
        subject=f"{first}, ось що ще вміє Alex 🥃",
        html=_build_day3(name),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Email 3 — Day 6 urgency (step 2 → 3)
# ─────────────────────────────────────────────────────────────────────────────

def _build_day6(name: str) -> str:
    content = f"""
<h2 style="color:#c9a84c;margin:0 0 20px;font-size:22px;">
  Завтра закінчується ваш доступ до Alex ⏰
</h2>
<p style="margin:0 0 20px;">
  Ваш безкоштовний період закінчується завтра.
</p>

<p style="margin:0 0 10px;font-weight:bold;color:#e8e8e8;">
  Що ви втрачаєте:
</p>
<ul style="margin:0 0 20px;padding-left:20px;color:#e8e8e8;">
  <li style="margin-bottom:8px;">❌ Необмежені питання до Alex</li>
  <li style="margin-bottom:8px;">❌ Щотижневі тренд-звіти на email</li>
  <li style="margin-bottom:8px;">❌ База постачальників AVTD</li>
</ul>

<p style="margin:0 0 10px;font-weight:bold;color:#c9a84c;">
  Що дає Standard:
</p>
<ul style="margin:0 0 28px;padding-left:20px;color:#e8e8e8;">
  <li style="margin-bottom:8px;">✅ Безлімітні питання 24/7</li>
  <li style="margin-bottom:8px;">✅ Щотижневий дайджест трендів</li>
  <li style="margin-bottom:8px;">✅ Перевірені постачальники зі знижками</li>
</ul>

{_cta_button("Продовжити за $7/міс →", PRICING_URL)}

<p style="text-align:center;margin:20px 0 0;color:#888;font-size:13px;">
  Менше ніж одна пляшка вина на місяць 🍷
</p>
"""
    return base_template(content)


def _send_day6(email: str, name: str) -> bool:
    return send_email(
        to=email,
        subject="Завтра закінчується ваш доступ до Alex ⏰",
        html=_build_day6(name),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Email 4 — Day 8 win-back (step 3 → 4)
# ─────────────────────────────────────────────────────────────────────────────

def _get_latest_horeca_headline() -> str:
    """
    Fetches the most recent posted article that is tagged as HoReCa / bar /
    restaurant content. Falls back to a hardcoded string if none found.
    The category filter prevents non-HoReCa articles (e.g. pharmacy news)
    from appearing in the win-back email.
    """
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT COALESCE(translated_title, source_title)
                   FROM content_queue
                   WHERE status = 'posted'
                     AND COALESCE(translated_title, source_title) IS NOT NULL
                     AND (
                       category ILIKE '%horeca%'
                       OR category ILIKE '%%бар%%'
                       OR category ILIKE '%%ресторан%%'
                       OR category ILIKE '%%spirits%%'
                       OR category ILIKE '%%drinks%%'
                     )
                   ORDER BY posted_at DESC NULLS LAST, created_at DESC
                   LIMIT 1"""
            )
            row = cur.fetchone()
            if row and row[0]:
                return row[0]
            # No HoReCa-categorised article — use hardcoded fallback
            logger.warning("[Onboarding] No HoReCa article found for win-back email — using fallback")
            return HORECA_FALLBACK_HEADLINE
    except Exception as e:
        logger.warning(f"[Onboarding] Could not fetch HoReCa headline: {e}")
        return HORECA_FALLBACK_HEADLINE


def _build_day8(name: str) -> str:
    headline = _get_latest_horeca_headline()
    content = f"""
<h2 style="color:#c9a84c;margin:0 0 20px;font-size:22px;">
  Alex сумує 🥃 Повертайтесь
</h2>
<p style="margin:0 0 20px;">
  Ваш trial завершився, але Alex нікуди не пішов.
</p>

<div style="background:#0f0f1a;border-left:3px solid #c9a84c;padding:16px 20px;
            border-radius:4px;margin:0 0 24px;">
  <p style="margin:0 0 6px;color:#888;font-size:13px;">
    Поки вас не було, у HoReCa відбулось:
  </p>
  <p style="margin:0;color:#e8e8e8;font-style:italic;">
    {headline}
  </p>
</div>

{_cta_button("Повернутись за $7/міс →", PRICING_URL)}

<p style="margin:28px 0 0;color:#888;font-size:13px;">
  PS: Якщо є питання — просто відповідіть на цей лист.
</p>
"""
    return base_template(content)


def _send_day8(email: str, name: str) -> bool:
    return send_email(
        to=email,
        subject="Alex сумує 🥃 Повертайтесь",
        html=_build_day8(name),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main checker — called every 5 minutes by APScheduler
# ─────────────────────────────────────────────────────────────────────────────

def check_and_send_onboarding_emails() -> None:
    """
    Scans maya_users for users who need the next onboarding email and sends it.
    Skips paid users. Runs in the APScheduler background thread.
    """
    logger.info("[Onboarding] Checking for pending emails...")
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT email, name, subscription_tier, onboarding_step,
                              onboarding_scheduled_at, registered_at
                       FROM maya_users
                       WHERE subscription_tier NOT IN ('standard', 'premium')
                         AND onboarding_step < 4
                       ORDER BY registered_at ASC"""
                )
                users = cur.fetchall()

            for (email, name, tier, step, sched_at, registered_at) in users:
                try:
                    _process_user(conn, email, name or "", step, sched_at)
                except Exception as e:
                    logger.error(f"[Onboarding] Error processing {email}: {e}")

    except Exception as e:
        logger.error(f"[Onboarding] DB error in checker: {e}")


def _process_user(
    conn,
    email: str,
    name: str,
    step: int,
    sched_at,
) -> None:
    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        # ── Email 1 — Welcome (fires immediately for new registrations) ────────
        if step == 0:
            if _send_welcome(email, name):
                logger.info(f"[Onboarding] Welcome sent → {email}")
            # anchor_now=True → onboarding_scheduled_at = NOW()
            # This is the correct base for all subsequent day calculations.
            _set_step(cur, email, 1, anchor_now=True)
            conn.commit()
            return

        # ── Day-based emails — require sched_at to be set ─────────────────────
        # If sched_at is NULL the user somehow skipped Email 1 without anchoring
        # the schedule; skip rather than firing all remaining emails at once.
        if sched_at is None:
            logger.warning(
                f"[Onboarding] {email} at step {step} but onboarding_scheduled_at"
                " is NULL — skipping until Email 1 fires and sets the anchor"
            )
            return

        if sched_at.tzinfo is None:
            sched_at = sched_at.replace(tzinfo=timezone.utc)

        if step == 1 and now >= sched_at + timedelta(days=3):
            if _send_day3(email, name):
                logger.info(f"[Onboarding] Day-3 email sent → {email}")
            _set_step(cur, email, 2)
            conn.commit()

        elif step == 2 and now >= sched_at + timedelta(days=6):
            if _send_day6(email, name):
                logger.info(f"[Onboarding] Day-6 email sent → {email}")
            _set_step(cur, email, 3)
            conn.commit()

        elif step == 3 and now >= sched_at + timedelta(days=8):
            if _send_day8(email, name):
                logger.info(f"[Onboarding] Day-8 email sent → {email}")
            _set_step(cur, email, 4)
            conn.commit()
