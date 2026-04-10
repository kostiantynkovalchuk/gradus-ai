"""
Alex Gradus Telegram Bot — @alexgradus_bot
==========================================
Webhook route + full bot logic for the client-facing Alex Gradus AI.

Architecture:
  - Separate bot token (ALEX_GRADUS_BOT_TOKEN), isolated from all other bots
  - Identity bridge: telegram_user_id → email → subscription_tier (from maya_users)
  - Subscription enforced server-side from DB, not by caller
  - Reuses chat_with_avatars() from chat_endpoints.py for Claude responses
  - Memory (alex_conversations / alex_user_profiles) shared with web chat, keyed by email

Access rules for free tier:
  1. Trial expires 14 days after linking (trial_started_at)
  2. Daily limit: 5 questions/day (resets at midnight)
  Paid tiers (standard / premium): unlimited, full memory
"""

import logging
import os
import re
from datetime import date, datetime, timezone

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Markdown → plain text for Telegram
# Telegram does not render web-flavoured markdown consistently.
# Strip all markdown so the message renders as clean plain text.
# ─────────────────────────────────────────────────────────────────────────────

def _tg_format(text: str) -> str:
    """Strip Claude markdown for clean Telegram plain-text rendering."""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        # Strip markdown headers (# Header → Header)
        line = re.sub(r'^#{1,4}\s+', '', line)
        # Replace ─── / --- / === dividers with a blank line
        if re.match(r'^[-─═*]{3,}\s*$', line.strip()):
            cleaned.append('')
            continue
        # Strip **bold** markers, keep the inner text
        line = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
        # Strip remaining *italic* markers that are NOT bullet hyphens
        # Only matches *word* patterns, not standalone * at line start
        line = re.sub(r'(?<![*\n])\*([^*\n]+?)\*(?!\*)', r'\1', line)
        cleaned.append(line)

    result = '\n'.join(cleaned)
    # Collapse 3+ consecutive newlines to 2
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()

_alex_app: Application | None = None
_initialized: bool = False

FREE_DAILY_LIMIT = 5
TRIAL_DAYS = 14
DB_URL = os.environ.get("DATABASE_URL", "")


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _conn():
    return psycopg2.connect(DB_URL)


def _get_tg_user(telegram_user_id: int) -> dict | None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT email, subscription_tier, trial_started_at,
                   daily_question_count, daily_reset_date, is_active
            FROM telegram_alex_users
            WHERE telegram_user_id = %s
            """,
            (telegram_user_id,)
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "email": row[0],
        "tier": row[1],
        "trial_started_at": row[2],
        "daily_question_count": row[3],
        "daily_reset_date": row[4],
        "is_active": row[5],
    }


def _lookup_maya_user(email: str) -> dict | None:
    """Look up subscription info from maya_users by email."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT subscription_tier, subscription_started_at, registered_at,
                   subscription_status
            FROM maya_users
            WHERE email = %s
            """,
            (email,)
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "tier": row[0] or "free",
        "subscription_started_at": row[1],
        "registered_at": row[2],
        "status": row[3],
    }


def _link_tg_user(telegram_user_id: int, email: str, maya: dict) -> dict:
    """Insert or update telegram_alex_users record after email verification."""
    tier = maya["tier"] if maya else "free"
    trial_started = datetime.now(timezone.utc)

    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO telegram_alex_users
                (telegram_user_id, email, subscription_tier, trial_started_at, last_active)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (telegram_user_id) DO UPDATE
                SET email = EXCLUDED.email,
                    subscription_tier = EXCLUDED.subscription_tier,
                    trial_started_at = EXCLUDED.trial_started_at,
                    last_active = NOW()
            """,
            (telegram_user_id, email, tier, trial_started)
        )
        conn.commit()

    return {"email": email, "tier": tier, "trial_started_at": trial_started}


def _increment_and_update(telegram_user_id: int) -> None:
    """Increment daily counter and reset if new day. Update last_active."""
    today = date.today()
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE telegram_alex_users
            SET daily_question_count = CASE
                    WHEN daily_reset_date IS NULL OR daily_reset_date < %s THEN 1
                    ELSE daily_question_count + 1
                END,
                daily_reset_date = %s,
                last_active = NOW()
            WHERE telegram_user_id = %s
            """,
            (today, today, telegram_user_id)
        )
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Paywall checks
# ─────────────────────────────────────────────────────────────────────────────

def _trial_expired(user: dict) -> bool:
    if user["tier"] not in ("free", None):
        return False
    ts = user.get("trial_started_at")
    if not ts:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    return delta.days >= TRIAL_DAYS


def _daily_limit_reached(user: dict) -> bool:
    if user["tier"] not in ("free", None):
        return False
    today = date.today()
    reset_date = user.get("daily_reset_date")
    if reset_date and reset_date < today:
        logger.info(f"[DailyReset] Counter reset for {user.get('email')} (last reset: {reset_date})")
        return False  # will be reset on next increment
    count = user.get("daily_question_count") or 0
    return count >= FREE_DAILY_LIMIT


# ─────────────────────────────────────────────────────────────────────────────
# In-memory state: users waiting to enter email after /start
# ─────────────────────────────────────────────────────────────────────────────
_pending_email: set[int] = set()


# ─────────────────────────────────────────────────────────────────────────────
# Telegram handlers
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context) -> None:
    user_id = update.effective_user.id
    _pending_email.add(user_id)
    await update.message.reply_text(
        "Привіт! Я Alex Gradus — ваш AI-експерт з прибутковості бару 🥃\n\n"
        "Щоб почати, введіть вашу email-адресу з gradusmedia.org"
    )


async def handle_message(update: Update, context) -> None:
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    # ── Email linking flow ───────────────────────────────────────────────────
    if user_id in _pending_email:
        email = text.lower().strip()
        if "@" not in email or "." not in email:
            await update.message.reply_text(
                "Будь ласка, введіть коректну email-адресу."
            )
            return

        maya = _lookup_maya_user(email)
        if not maya:
            await update.message.reply_text(
                "Email не знайдено. "
                "Зареєструйтесь безкоштовно на gradusmedia.org 👇"
            )
            return

        user = _link_tg_user(user_id, email, maya)
        _pending_email.discard(user_id)

        tier_labels = {"free": "Free", "standard": "Standard", "premium": "Premium"}
        tier_label = tier_labels.get(user["tier"], user["tier"].title())

        await update.message.reply_text(
            f"Чудово! Акаунт підключено ✅\n"
            f"Тариф: {tier_label}\n\n"
            "Задайте будь-яке питання про ваш бар 👇"
        )
        return

    # ── Normal chat flow ─────────────────────────────────────────────────────
    user = _get_tg_user(user_id)
    if not user:
        await update.message.reply_text(
            "Будь ласка, введіть /start щоб підключити акаунт."
        )
        return

    # Paywall check 1 — trial expiry
    if _trial_expired(user):
        await update.message.reply_text(
            "Ваш 14-денний безкоштовний період завершився 🕐\n\n"
            "Необмежений доступ до Alex від $7/міс\n"
            "→ gradusmedia.org/тарифи"
        )
        return

    # Paywall check 2 — daily limit
    if _daily_limit_reached(user):
        await update.message.reply_text(
            "Ви використали 5 безкоштовних питань сьогодні 💬\n\n"
            "Повертайтесь завтра або отримайте необмежений доступ "
            "від $7/міс → gradusmedia.org/тарифи"
        )
        return

    # ── Call Claude via existing chat_with_avatars ───────────────────────────
    await update.message.chat.send_action("typing")
    try:
        from routes.chat_endpoints import chat_with_avatars, ChatRequest

        req = ChatRequest(
            message=text,
            conversation_history=[],
            avatar="alex",
            source="telegram",
            user_email=user["email"],
            user_tier=user["tier"],
        )
        result = await chat_with_avatars(req)
        response_text = _tg_format(result.response)
    except Exception as e:
        logger.error(f"[AlexTG] chat_with_avatars error: {e}", exc_info=True)
        response_text = "Вибачте, сталася технічна помилка. Спробуйте ще раз."

    await update.message.reply_text(response_text)

    # ── Post-response bookkeeping ────────────────────────────────────────────
    _increment_and_update(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# App factory
# ─────────────────────────────────────────────────────────────────────────────

def create_alex_gradus_app() -> Application:
    token = os.environ.get("ALEX_GRADUS_BOT_TOKEN")
    if not token:
        raise RuntimeError("ALEX_GRADUS_BOT_TOKEN not set")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app


# ─────────────────────────────────────────────────────────────────────────────
# Lazy-init singleton (same pattern as photo_report_webhook.py)
# ─────────────────────────────────────────────────────────────────────────────

async def _get_alex_app() -> Application:
    global _alex_app, _initialized
    if _alex_app is None:
        _alex_app = create_alex_gradus_app()
    if not _initialized:
        await _alex_app.initialize()
        _initialized = True
    return _alex_app


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI route
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/webhook/alex-gradus")
async def alex_gradus_webhook(request: Request):
    try:
        app = await _get_alex_app()
        data = await request.json()
        update = Update.de_json(data, app.bot)
        await app.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"[AlexTG] Webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/webhook/alex-gradus/health")
async def alex_gradus_health():
    token_set = bool(os.environ.get("ALEX_GRADUS_BOT_TOKEN"))
    return {"status": "ok", "service": "alex-gradus", "token_configured": token_set}
