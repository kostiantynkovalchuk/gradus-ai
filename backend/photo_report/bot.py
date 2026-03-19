import io
import base64
import asyncio
import logging
import os
from telegram import Update, Bot
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, filters, ContextTypes
)
from .vision import analyze_photos
from .scoring import calculate_score
from .formatter import format_report_for_telegram
from .db import get_or_create_agent, save_report, save_report_photos, get_agent_stats
from .keyboards import MAIN_MENU, PHOTO_ACTIONS

logger = logging.getLogger(__name__)

WAITING_POINT_NAME = 1
WAITING_PHOTOS = 2
WAITING_CONFIRM = 3

pending_reports = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, get_or_create_agent, user.id, user.full_name)

    await update.message.reply_text(
        f"Привіт, {user.first_name}! 👋\n\n"
        "Я — Alex Photo Report. Перевіряю виставлення товарів AVTD.\n\n"
        "Натисни *📸 Новий звіт* щоб почати.",
        reply_markup=MAIN_MENU,
        parse_mode="Markdown"
    )


async def new_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, get_or_create_agent, user.id, user.full_name)

    await update.message.reply_text(
        "📍 *Новий звіт*\n\n"
        "Напиши назву торгової точки:\n"
        "_(наприклад: АТБ Хрещатик або Кафе Ромашка)_",
        parse_mode="Markdown"
    )
    return WAITING_POINT_NAME


async def receive_point_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    point_name = update.message.text.strip()

    pending_reports[user_id] = {
        "point_name": point_name,
        "photos_b64": [],
        "photos_bytes": [],
        "photo_file_ids": [],
        "comment": ""
    }

    await update.message.reply_text(
        f"✅ Точка: *{point_name}*\n\n"
        "📸 Надішли фотографії (до 5 штук).\n\n"
        "⚠️ *Обов'язково:* загальний огляд всіх полиць!\n\n"
        "Коли завантажиш всі фото — натисни *Готово* або напиши коментар "
        "(напр: 'без ліцензії', 'дефіцит центрального складу').",
        parse_mode="Markdown",
        reply_markup=PHOTO_ACTIONS
    )
    return WAITING_PHOTOS


async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in pending_reports:
        await update.message.reply_text("Спочатку почни новий звіт: /start")
        return WAITING_PHOTOS

    report_data = pending_reports[user_id]

    if len(report_data["photos_b64"]) >= 5:
        await update.message.reply_text("⚠️ Максимум 5 фото. Натисни *Готово*.", parse_mode="Markdown")
        return WAITING_PHOTOS

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    buf = io.BytesIO()
    await file.download_to_memory(buf)
    raw_bytes = buf.getvalue()

    b64 = base64.b64encode(raw_bytes).decode("utf-8")

    report_data["photos_b64"].append(b64)
    report_data["photos_bytes"].append(raw_bytes)
    report_data["photo_file_ids"].append(photo.file_id)

    count = len(report_data["photos_b64"])
    await update.message.reply_text(
        f"📸 Фото {count}/5 отримано. "
        f"{'Надішли ще або натисни Готово.' if count < 5 else 'Натисни Готово.'}"
    )
    return WAITING_PHOTOS


async def process_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    if user_id not in pending_reports:
        await update.message.reply_text("Спочатку почни новий звіт.")
        return ConversationHandler.END

    report_data = pending_reports[user_id]

    if not report_data["photos_b64"]:
        await update.message.reply_text("⚠️ Додай хоча б одне фото!")
        return WAITING_PHOTOS

    text = update.message.text
    if text and text not in ["✅ Готово", "Готово"]:
        report_data["comment"] = text

    photo_count = len(report_data["photos_b64"])
    await update.message.reply_text(
        f"⏳ Аналізую {photo_count} фото...\n_Це займе ~20 секунд_",
        parse_mode="Markdown"
    )

    try:
        loop = asyncio.get_event_loop()

        vision_raw = await loop.run_in_executor(
            None,
            analyze_photos,
            report_data["photos_b64"],
            report_data["comment"]
        )

        scored_report = calculate_score(vision_raw)

        report_id = await loop.run_in_executor(
            None,
            save_report,
            user_id,
            report_data["point_name"],
            scored_report,
            vision_raw,
            report_data["photo_file_ids"],
            report_data["comment"]
        )

        await loop.run_in_executor(
            None,
            save_report_photos,
            report_id,
            report_data["photos_bytes"]
        )

        tg_message = format_report_for_telegram(
            scored_report,
            user.full_name,
            report_data["point_name"]
        )
        tg_message += f"\n\n_ID звіту: #{report_id}_"

        await update.message.reply_text(
            tg_message,
            parse_mode="Markdown",
            reply_markup=MAIN_MENU
        )

    except Exception as e:
        logger.error(f"Photo report error: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Помилка аналізу. Спробуй ще раз або звернись до супервайзера.",
            reply_markup=MAIN_MENU
        )
    finally:
        pending_reports.pop(user_id, None)

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending_reports.pop(update.effective_user.id, None)
    await update.message.reply_text(
        "❌ Звіт скасовано.",
        reply_markup=MAIN_MENU
    )
    return ConversationHandler.END


async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    loop = asyncio.get_event_loop()
    stats = await loop.run_in_executor(None, get_agent_stats, user_id)

    total = stats.get("total", 0)
    passed = stats.get("passed_count", 0)
    avg = stats.get("avg_score", 0)
    rate = round(passed / total * 100) if total > 0 else 0

    await update.message.reply_text(
        f"📊 *Твоя статистика (30 днів)*\n\n"
        f"📋 Звітів: {total}\n"
        f"✅ Пройдено: {passed} ({rate}%)\n"
        f"⭐ Середній бал: {avg}/100",
        parse_mode="Markdown"
    )


def create_photo_report_app() -> Application:
    token = os.environ.get("PHOTO_REPORT_BOT_TOKEN")
    if not token:
        raise ValueError("PHOTO_REPORT_BOT_TOKEN not set")

    app = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("report", new_report),
            MessageHandler(filters.Regex("^📸 Новий звіт$"), new_report)
        ],
        states={
            WAITING_POINT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_point_name)
            ],
            WAITING_PHOTOS: [
                MessageHandler(filters.PHOTO, receive_photo),
                MessageHandler(filters.Regex("^(✅ Готово|Готово)$"), process_report),
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_report),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^❌ Скасувати$"), cancel)
        ]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.Regex("^📊 Моя статистика$"), my_stats))

    return app
