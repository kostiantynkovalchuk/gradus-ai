import io
import re
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
from .db import (
    get_or_create_agent, save_report, save_report_photos,
    get_agent_stats, save_expert_correction,
)
from .keyboards import MAIN_MENU, PHOTO_ACTIONS

logger = logging.getLogger(__name__)

WAITING_POINT_NAME = 1
WAITING_PHOTOS = 2
WAITING_CONFIRM = 3

EXPERT_TG_IDS: set[int] = {441389791, 424503938}

pending_reports = {}


def parse_correction(text: str) -> dict:
    """
    Parse a free-form expert correction message.

    Accepted formats (case-insensitive):
      "горілка 35% 7/20"
      "vodka GD=4 UA=3 total=20"
      "коньяк: наша=5 всього=15 → 33%"
      "вино villa 3 конкуренти 9 → 25%"
      "sparkling: villa 0, всього 8"
      "ігристе — не бачу villa ua зовсім"
    """
    text_l = text.lower()

    category_map = {
        "горілк": "vodka",
        "горілц": "vodka",
        "vodka": "vodka",
        "коньяк": "cognac",
        "cognac": "cognac",
        "бренді": "cognac",
        "brandy": "cognac",
        "вин": "wine",
        "wine": "wine",
        "ігрист": "sparkling",
        "sparkling": "sparkling",
        "шампан": "sparkling",
    }
    category = None
    for key, cat in category_map.items():
        if key in text_l:
            category = cat
            break

    share_match = re.search(r"(\d{1,3})\s*%", text)
    true_share = int(share_match.group(1)) if share_match else None

    fraction_match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    our_facings = int(fraction_match.group(1)) if fraction_match else None
    total_facings = int(fraction_match.group(2)) if fraction_match else None

    if our_facings is None:
        for pat in [
            r"(?:gd|наш|наші|our|ours?)\s*[=:]\s*(\d+)",
            r"(?:villa|adjari|greenday)\s+(\d+)",
            r"наш\w*\s+(\d+)",
        ]:
            m = re.search(pat, text_l)
            if m:
                our_facings = int(m.group(1))
                break

    if total_facings is None:
        for pat in [
            r"(?:total|всього|загал\w*|tot)\s*[=:]\s*(\d+)",
            r"(?:конкурент\w*|comp)\s+(\d+)",
        ]:
            m = re.search(pat, text_l)
            if m:
                if "конкурент" in pat and our_facings is not None:
                    comp = int(m.group(1))
                    total_facings = our_facings + comp
                else:
                    total_facings = int(m.group(1))
                break

    if our_facings is not None and total_facings is not None and true_share is None and total_facings > 0:
        true_share = round(our_facings / total_facings * 100)

    return {
        "category": category,
        "true_share": true_share,
        "our_facings": our_facings,
        "total_facings": total_facings,
        "raw_text": text,
    }


async def handle_expert_correction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Experts (by Telegram ID) can reply to a report to provide corrections."""
    user = update.effective_user
    if user is None or user.id not in EXPERT_TG_IDS:
        return

    msg = update.message
    if not msg or not msg.reply_to_message:
        return

    replied_text = msg.reply_to_message.text or ""
    report_id_match = re.search(r"ID звіту: #(\d+)", replied_text)
    if not report_id_match:
        await msg.reply_text(
            "⚠️ Не знайшов ID звіту в повідомленні. "
            "Будь ласка, відповідай саме на повідомлення зі звітом.",
            parse_mode="Markdown",
        )
        return

    report_id = int(report_id_match.group(1))
    correction_text = msg.text or ""

    parsed = parse_correction(correction_text)

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            save_expert_correction,
            report_id,
            user.id,
            user.full_name,
            parsed,
        )

        cat_ua = {"vodka": "горілка", "wine": "вино", "cognac": "коньяк", "sparkling": "ігристе"}
        cat_display = cat_ua.get(parsed.get("category"), parsed.get("category") or "невідомо")

        lines = [f"✅ *Корекцію до звіту #{report_id} збережено.*", ""]
        lines.append(f"📋 Категорія: {cat_display}")
        if parsed.get("true_share") is not None:
            lines.append(f"📊 Фактична частка: {parsed['true_share']}%")
        if parsed.get("our_facings") is not None and parsed.get("total_facings") is not None:
            lines.append(f"🔢 Фейсинги: {parsed['our_facings']} / {parsed['total_facings']}")
        lines.append("")
        lines.append("_Дякуємо! Дані використовуються для покращення точності AI._")

        await msg.reply_text("\n".join(lines), parse_mode="Markdown")

    except Exception as e:
        logger.error(f"[PhotoReport] Failed to save expert correction: {e}", exc_info=True)
        await msg.reply_text(
            "❌ Помилка при збереженні корекції. Спробуй ще раз.",
            parse_mode="Markdown",
        )


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
        "💡 *Порада:* Надсилай 2–3 фото для точнішого аналізу:\n"
        "  • Загальний огляд всіх полиць\n"
        "  • Крупні плани окремих секцій\n\n"
        "⚠️ *Обов'язково:* загальний огляд всіх полиць!\n\n"
        "Коли завантажиш всі фото — натисни *Готово* або напиши коментар "
        "(напр: 'без ліцензії', 'дефіцит центрального складу').",
        parse_mode="Markdown",
        reply_markup=PHOTO_ACTIONS
    )
    return WAITING_PHOTOS


async def photo_before_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Photo arrives while bot was still waiting for the store name — use placeholder."""
    user_id = update.effective_user.id

    pending_reports[user_id] = {
        "point_name": "Без назви",
        "photos_b64": [],
        "photos_bytes": [],
        "photo_file_ids": [],
        "comment": ""
    }

    return await _accept_photo(update, context, pending_reports[user_id])


async def _accept_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, report_data: dict) -> int:
    """Shared logic: download a photo and append to report_data. Returns next state."""
    if len(report_data["photos_b64"]) >= 5:
        await update.message.reply_text(
            "⚠️ Максимум 5 фото. Натисни *Готово* для аналізу.",
            parse_mode="Markdown",
            reply_markup=PHOTO_ACTIONS
        )
        return WAITING_PHOTOS

    msg = update.message
    if msg.photo:
        tg_file = await context.bot.get_file(msg.photo[-1].file_id)
        file_id = msg.photo[-1].file_id
    elif msg.document:
        tg_file = await context.bot.get_file(msg.document.file_id)
        file_id = msg.document.file_id
    else:
        return WAITING_PHOTOS

    buf = io.BytesIO()
    await tg_file.download_to_memory(buf)
    raw_bytes = buf.getvalue()

    report_data["photos_b64"].append(base64.b64encode(raw_bytes).decode("utf-8"))
    report_data["photos_bytes"].append(raw_bytes)
    report_data["photo_file_ids"].append(file_id)

    count = len(report_data["photos_b64"])
    if count == 1:
        more_msg = (
            "📸 Фото 1/5 отримано.\n\n"
            "💡 _Для точнішого аналізу надсилай 2–3 фото з різних кутів. "
            "Або натисни Готово якщо фото достатньо._"
        )
    else:
        more_msg = (
            f"📸 Фото {count}/5 отримано. "
            + ("Надішли ще або натисни Готово." if count < 5 else "Натисни Готово для аналізу.")
        )

    try:
        await update.message.reply_text(more_msg, reply_markup=PHOTO_ACTIONS, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(
            f"Фото {count}/5 отримано.", reply_markup=PHOTO_ACTIONS
        )
    return WAITING_PHOTOS


async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in pending_reports:
        await update.message.reply_text("Спочатку почни новий звіт: /start")
        return WAITING_PHOTOS

    return await _accept_photo(update, context, pending_reports[user_id])


async def receive_document_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photos sent as file attachments (not compressed)."""
    user_id = update.effective_user.id

    if user_id not in pending_reports:
        await update.message.reply_text("Спочатку почни новий звіт: /start")
        return WAITING_PHOTOS

    return await _accept_photo(update, context, pending_reports[user_id])


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
        f"⏳ Аналізую {photo_count} фото...\n_Це займе ~20–40 секунд_",
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

        if photo_count == 1:
            tg_message += (
                "\n\n💡 _Порада: Наступного разу надішли 2–3 фото (загальний огляд + "
                "крупні плани) — це підвищить точність аналізу._"
            )

        retried = scored_report.get("retried_categories", [])
        if retried:
            cat_ua = {"vodka": "горілка", "wine": "вино", "cognac": "коньяк", "sparkling": "ігристе"}
            retried_str = ", ".join(cat_ua.get(c, c) for c in retried)
            tg_message += f"\n🔄 _Виконано повторний аналіз: {retried_str}_"

        try:
            await update.message.reply_text(
                tg_message,
                parse_mode="Markdown",
                reply_markup=MAIN_MENU
            )
        except Exception as fmt_err:
            logger.warning(f"[PhotoReport] Markdown parse failed, retrying plain: {fmt_err}")
            plain = tg_message.replace("*", "").replace("_", "").replace("`", "")
            await update.message.reply_text(plain, reply_markup=MAIN_MENU)

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
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_point_name),
                MessageHandler(filters.PHOTO, photo_before_name),
                MessageHandler(filters.Document.IMAGE, photo_before_name),
            ],
            WAITING_PHOTOS: [
                MessageHandler(filters.PHOTO, receive_photo),
                MessageHandler(filters.Document.IMAGE, receive_document_photo),
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

    expert_filter = filters.TEXT & filters.REPLY & filters.User(list(EXPERT_TG_IDS))
    app.add_handler(MessageHandler(expert_filter, handle_expert_correction))

    return app
