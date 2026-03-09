import os
import re
import json
import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, Contact,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import CommandStart, Command
from database import get_db_connection
from solomon_search import parse_query, search_decisions, summarize_decision

logger = logging.getLogger(__name__)

SOLOMON_BOT_TOKEN = os.getenv("SOLOMON_BOT_TOKEN")
bot = Bot(token=SOLOMON_BOT_TOKEN) if SOLOMON_BOT_TOKEN else None
dp = Dispatcher()


def normalize_phone(phone: str) -> str:
    import re
    digits = re.sub(r'\D', '', str(phone))
    if digits.startswith('380'):
        return '+' + digits
    if digits.startswith('0'):
        return '+38' + digits
    return '+' + digits


def is_authorized(phone: str) -> bool:
    normalized = normalize_phone(phone)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM solomon_whitelist WHERE phone=%s AND is_active=true",
        (normalized,)
    )
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result is not None


def get_session(telegram_user_id: int) -> dict | None:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT phone, username FROM solomon_sessions WHERE telegram_user_id=%s",
        (telegram_user_id,)
    )
    result = cur.fetchone()
    cur.close()
    conn.close()
    return {"phone": result[0], "username": result[1]} if result else None


def save_session(telegram_user_id: int, phone: str, username: str):
    normalized = normalize_phone(phone)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO solomon_sessions (telegram_user_id, phone, username)
        VALUES (%s, %s, %s)
        ON CONFLICT (telegram_user_id) DO UPDATE
        SET phone=%s, username=%s, last_active=NOW()
    """, (telegram_user_id, normalized, username, normalized, username))
    conn.commit()
    cur.close()
    conn.close()


def log_search(telegram_user_id: int, phone: str,
               query: str, params: dict, count: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO solomon_search_log
        (telegram_user_id, phone, query_text, search_params, results_count)
        VALUES (%s, %s, %s, %s, %s)
    """, (telegram_user_id, phone, query, json.dumps(params), count))
    conn.commit()
    cur.close()
    conn.close()


@dp.message(CommandStart())
async def start(message: Message):
    session = get_session(message.from_user.id)
    if session:
        await message.answer(
            "👋 З поверненням!\n\n"
            "Напишіть запит — знайду практику Верховного Суду.\n"
            "/help — приклади запитів",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(
            text="📱 Поділитись номером",
            request_contact=True
        )]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "👋 Вітаю в *СОЛОМОН*\n"
        "Асистент пошуку практики Верховного Суду України\n\n"
        "🔐 Підтвердіть номер телефону для доступу:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


@dp.message(F.contact)
async def handle_contact(message: Message):
    contact: Contact = message.contact

    if contact.user_id != message.from_user.id:
        await message.answer(
            "❌ Будь ласка, поділіться власним номером телефону.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    phone = contact.phone_number
    phone_normalized = re.sub(r'\s+', '', phone)
    if not phone_normalized.startswith('+'):
        phone_normalized = '+' + phone_normalized

    if is_authorized(phone_normalized):
        username = message.from_user.username or message.from_user.full_name
        save_session(message.from_user.id, phone_normalized, username)
        await message.answer(
            "✅ *Доступ підтверджено!*\n\n"
            "Напишіть запит, наприклад:\n"
            "_«скасування ППР нереальність операцій 2024-2025»_\n\n"
            "/help — приклади запитів\n"
            "/history — ваші останні пошуки",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await message.answer(
            "❌ Ваш номер не в списку авторизованих користувачів.\n\n"
            "Зверніться до адміністратора для отримання доступу.",
            reply_markup=ReplyKeyboardRemove()
        )


@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "📖 *Приклади запитів:*\n\n"
        "• _скасування ППР нереальність операцій 2024-2025_\n"
        "• _оскарження рішення АМКУ антиконкурентні дії_\n"
        "• _стягнення збитків ДТП таксі_\n"
        "• _визнання недійсним договору купівлі нерухомості_\n"
        "• _документальна перевірка маркетингові послуги_\n\n"
        "💡 Чим детальніший запит — тим точніші результати.",
        parse_mode="Markdown"
    )


@dp.message(Command("history"))
async def history_cmd(message: Message):
    session = get_session(message.from_user.id)
    if not session:
        await message.answer("🔐 Спочатку авторизуйтесь через /start")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT query_text, results_count, created_at
        FROM solomon_search_log
        WHERE telegram_user_id=%s
        ORDER BY created_at DESC LIMIT 5
    """, (message.from_user.id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await message.answer("📋 Історія пошуків порожня.")
        return

    text = "🕐 *Останні пошуки:*\n\n"
    for i, row in enumerate(rows, 1):
        date = row[2].strftime("%d.%m %H:%M")
        text += f"{i}. _{row[0][:60]}_\n   📊 {row[1]} рішень | {date}\n\n"
    await message.answer(text, parse_mode="Markdown")


@dp.message()
async def handle_search(message: Message):
    session = get_session(message.from_user.id)
    if not session:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(
                text="📱 Поділитись номером",
                request_contact=True
            )]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await message.answer(
            "🔐 Підтвердіть номер телефону для доступу:",
            reply_markup=keyboard
        )
        return

    processing_msg = await message.answer("⏳ Шукаю та аналізую рішення...")
    await bot.send_chat_action(message.chat.id, "typing")

    try:
        params = parse_query(message.text)
        judgments = search_decisions(params)

        if not judgments:
            await processing_msg.edit_text(
                "🔍 За вашим запитом нічого не знайдено.\n\n"
                "Спробуйте змінити формулювання або розширити "
                "часовий діапазон.\n/help — приклади запитів"
            )
            return

        numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        header = (
            f"📋 Знайдено *{len(judgments)}* рішень\n"
            "🏛 Верховний Суд | Касація\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        blocks = []
        for i, j in enumerate(judgments):
            date = j.get("adjudication_date", "")[:10]
            cause = j.get("cause_number", "")
            judge = j.get("judge", "")
            link = j.get("link", "")
            summary = summarize_decision(link) if link else "Недоступно."

            block = (
                f"{numbers[i]} *Справа № {cause}* — {date}\n"
                f"👨‍⚖️ {judge}\n\n"
                f"💡 {summary}\n\n"
                f"🔗 [Читати повністю]({link})\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
            )
            blocks.append(block)

        footer = f"🔍 _{message.text[:80]}_"

        chunks = []
        current = header
        for block in blocks:
            if len(current) + len(block) > 3800:
                chunks.append(current)
                current = "📋 *Продовження...*\n━━━━━━━━━━━━━━━━━━\n" + block
            else:
                current += block
        current += footer
        chunks.append(current)

        await processing_msg.edit_text(
            chunks[0],
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        for chunk in chunks[1:]:
            await message.answer(
                chunk,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )

        log_search(
            message.from_user.id,
            session["phone"],
            message.text,
            params,
            len(judgments)
        )

    except Exception as e:
        logger.error(f"Solomon search error: {e}")
        await processing_msg.edit_text(
            "⚠️ Виникла помилка при обробці запиту. Спробуйте ще раз."
        )


async def setup_solomon_webhook(base_url: str):
    if not SOLOMON_BOT_TOKEN:
        logger.warning("SOLOMON_BOT_TOKEN not set — Solomon webhook skipped")
        return
    webhook_url = f"{base_url}/law/telegram/webhook"
    await bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True
    )
    logger.info(f"Solomon webhook set: {webhook_url}")


async def process_solomon_update(update_data: dict):
    from aiogram.types import Update
    update = Update(**update_data)
    await dp.feed_update(bot, update)
