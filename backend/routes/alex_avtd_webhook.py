"""
Alex AVTD Bot — Telegram webhook handler
Field agent assistant for AVTD sales reps
"""
import os
import time
import logging
import httpx
from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from sqlalchemy import text as _sa_text
from models import get_db

logger = logging.getLogger(__name__)
alex_avtd_router = APIRouter()

ALEX_AVTD_BOT_TOKEN = os.getenv("TELEGRAM_ALEX_AVTD_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{ALEX_AVTD_BOT_TOKEN}"

PHOTO_REPORT_BOT_LINK = "https://t.me/avtd_photo_report_bot"

ALEX_AVTD_SYSTEM_PROMPT = """Ти — Alex, корпоративний асистент для торгових агентів АВТД.
Ти відповідаєш ВИКЛЮЧНО на питання пов'язані з роботою торгового агента:
- Робота з мобільним застосунком Blitz Trade (КПК)
- KPI та показники: СЦ, АКБ, ОА, МЧ, ДП, ДПХ, фотозвіт
- Замовлення, залишки, статуси (R*, ND*, CRE*, А*, АЕ*)
- Маршрути та торгові точки
- Акції та спеццілі
- Портфель брендів АВТД: GreenDay, Helsinki, Ukrainka, Adjari, Довбуш, Klinkov, Jean Jack, Villa UA, Kristi Valley, Didi Lari, Kosher, Funju
- Інформація по клієнту в mobiletrade

Відповідай коротко, практично, українською або мовою запиту.
Якщо питання не стосується роботи агента — ввічливо відмов і запропонуй звернутися до відповідного відділу.
Посилання на Atlassian портал: https://tdav.atlassian.net/"""


def main_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📷 Фотозвіт / Мерчандайзинг", "url": PHOTO_REPORT_BOT_LINK}],
            [
                {"text": "👤 Клієнт", "callback_data": "ax_client"},
                {"text": "📊 KPI", "callback_data": "ax_kpi"},
            ],
            [
                {"text": "🔧 Технічні питання", "callback_data": "ax_tech"},
                {"text": "📦 Замовлення", "callback_data": "ax_orders"},
            ],
        ]
    }


def back_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "◀ Головне меню", "callback_data": "ax_menu"}]
        ]
    }


def client_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📋 Умови співпраці", "callback_data": "ax_client_terms"}],
            [{"text": "💰 Дебіторська заборгованість", "callback_data": "ax_client_debt"}],
            [{"text": "🏪 Інформація по точці", "callback_data": "ax_client_info"}],
            [{"text": "◀ Назад", "callback_data": "ax_menu"}],
        ]
    }


def kpi_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "❓ Чому не зарахувався фотозвіт?", "callback_data": "ax_kpi_photo"}],
            [{"text": "💵 Розрахунок бонусу / штраф за ДЗ", "callback_data": "ax_kpi_bonus"}],
            [{"text": "🎯 Як рахується спецціль?", "callback_data": "ax_kpi_sc"}],
            [{"text": "📈 Де дивитися мої показники?", "callback_data": "ax_kpi_where"}],
            [{"text": "◀ Назад", "callback_data": "ax_menu"}],
        ]
    }


def tech_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📱 Blitz Trade — інструкція", "callback_data": "ax_tech_blitz"}],
            [{"text": "🎁 Акція не спрацювала", "callback_data": "ax_tech_promo"}],
            [{"text": "🗺 Маршрути та точки", "callback_data": "ax_tech_routes"}],
            [{"text": "🔄 Помилка синхронізації", "callback_data": "ax_tech_sync"}],
            [{"text": "◀ Назад", "callback_data": "ax_menu"}],
        ]
    }


def orders_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🔤 Статуси замовлень (R*, ND*, CRE*...)", "callback_data": "ax_orders_status"}],
            [{"text": "📦 Залишки товарів", "callback_data": "ax_orders_stock"}],
            [{"text": "🚫 Товар не відображається", "callback_data": "ax_orders_missing"}],
            [{"text": "◀ Назад", "callback_data": "ax_menu"}],
        ]
    }


PRESETS = {
    "ax_client_terms": (
        "📋 *Умови співпраці з клієнтом*\n\n"
        "Доступні в двох місцях:\n"
        "• Сайт mobiletrade → Довідник → Контрагенти → Угоди\n"
        "• Blitz Trade → Маршрут → Торгова точка → Картка клієнта"
    ),
    "ax_client_debt": (
        "💰 *Дебіторська заборгованість*\n\n"
        "• Blitz Trade → Маршрут → Торгова точка (загальна ДЗ)\n"
        "• Сайт mobiletrade → Довідник → Контрагенти → Деталізація до накладної\n\n"
        "Штраф за ДЗ: `[ПДЗ – 10%×ДЗ] × 3%`"
    ),
    "ax_client_info": (
        "🏪 *Інформація по клієнту*\n\n"
        "Сайт mobiletrade → Довідник → Контрагенти:\n"
        "Основні, Торгові точки, Угоди, Маркетингові виплати,\n"
        "Замовлення, Відвантаження, Оплати, Мерчендайзинг, Фотозвіти\n\n"
        "Документи: mobiletrade → Документи → (Журнал, Замовлення, Накладні, Фотозвіт...)"
    ),
    "ax_kpi_photo": (
        "❓ *Чому не зарахувався фотозвіт?*\n\n"
        "Причини для МЧ, ДП, ДПХ:\n"
        "• ФЗ не синхронізовано в базу\n"
        "• Невірно вибрано результат візиту\n"
        "• Результат візиту не відповідає типу трт (МЧ на HoReCa — не зараховується)\n"
        "• МЧ2 — між візитами пройшло менше 5 днів\n\n"
        "Причини для СЦ, АКБ, ОА:\n"
        "• Випадіння товару при проведенні замовлення\n"
        "• Повернення/вичерки за попередні накладні\n"
        "• Самовивіз не враховується для СЦ\n\n"
        "Виправити результат візиту можна на сайті mobiletrade → Документи → Фотозвіти (протягом 3 робочих днів)"
    ),
    "ax_kpi_bonus": (
        "💵 *Бонус / штраф за ДЗ*\n\n"
        "Формула штрафу: `[ПДЗ – 10%×ДЗ] × 3%`\n\n"
        "Де дивитися виконання KPI:\n"
        "• Blitz Trade → Головна → Інфо\n"
        "• Blitz Trade → Маршрут → Торгова точка → Показники\n"
        "• Сайт mobiletrade → Головна → Дашборд\n"
        "• Звіти: Аналітика, ПП, Виконання СЦ"
    ),
    "ax_kpi_sc": (
        "🎯 *Спецціль — чому не зарахована?*\n\n"
        "5 типових причин:\n"
        "• Випадіння товару при проведенні замовлення\n"
        "• Повернення/вичерки за попередні накладні\n"
        "• ФЗ не синхронізовано\n"
        "• Невірний результат візиту\n"
        "• Самовивіз (для СЦ не враховується)\n\n"
        "Перевірити: mobiletrade → Звіти → Виконання СЦ"
    ),
    "ax_kpi_where": (
        "📈 *Де дивитися показники?*\n\n"
        "• Blitz Trade → Головна → Інфо — загальне виконання\n"
        "• Blitz Trade → Маршрут → Торгова точка → Показники — по точці\n"
        "• Сайт mobiletrade → Головна → Дашборд\n"
        "• Звіт Аналітика — всі показники\n"
        "• Звіт ПП — по агентах і маршрутах\n"
        "• Звіт Виконання СЦ — по агент/ТРТ/товар"
    ),
    "ax_tech_blitz": (
        "📱 *Blitz Trade — інструкція*\n\n"
        "Повна інструкція на порталі:\n"
        "tdav.atlassian.net → Центр підтримки → IT AV Helpdesk → Мобільна торгівля → Інструкція з роботи з Blitz Trade\n\n"
        "Там же: перелік можливих помилок при синхронізації"
    ),
    "ax_tech_promo": (
        "🎁 *Акція не спрацювала*\n\n"
        "Де дивитися:\n"
        "• КПК: Журнал → Замовлення → статус «Помилка експорту»\n"
        "• Сайт МТ: Документи → Замовлення → Примітки\n\n"
        "Причини:\n"
        "• Випадіння товару при замовленні\n"
        "• Повернення/вичерки за попередні накладні\n"
        "• Акція закінчилась на філіалі\n"
        "• Перевищено ліміт акцій по ТРТ\n"
        "• Основне замовлення в СТОПАХ — акційне опрацюється після проведення\n\n"
        "Залишки по акціям — уточніть у старшого оператора"
    ),
    "ax_tech_routes": (
        "🗺 *Маршрути та торгові точки*\n\n"
        "• Додати нову ТРТ в маршрут → подання інформації старшому оператору\n"
        "• Перемістити ТРТ в інший маршрут → старший оператор\n"
        "• Перемаршрутизація → шаблон Регіональному аналітику\n"
        "• Пропала ТРТ з маршруту → уточнити у старшого оператора стан точки"
    ),
    "ax_tech_sync": (
        "🔄 *Помилка синхронізації замовлення*\n\n"
        "Перевірте:\n"
        "• Всі поля заповнені (н/д або ціна 0 → помилка)\n"
        "  → Видаліть замовлення, повна синхронізація, набийте заново\n"
        "• Немає пустих замовлень → видалити і синхронізувати\n"
        "• Статус замовлення: mobiletrade → Документи → Замовлення\n"
        "• Розшифровка статусів: tdav.atlassian.net → IT AV Helpdesk → Мобільна торгівля"
    ),
    "ax_orders_status": (
        "🔤 *Статуси замовлень*\n\n"
        "• `R*` — Резерв (замовлення прийнято)\n"
        "• `ND*` — Немає даних / не оброблено\n"
        "• `CRE*` — Кредитне замовлення\n"
        "• `А*` — Архів\n"
        "• `АЕ*` — Архів з помилкою\n\n"
        "Повна розшифровка: tdav.atlassian.net → Мобільна торгівля → Документ замовлення"
    ),
    "ax_orders_stock": (
        "📦 *Залишки товарів*\n\n"
        "• При створенні замовлення — залишки відображаються автоматично\n"
        "• Blitz Trade → Головна → Звіти → Залишки\n"
        "• Сайт МТ → Звіти → Залишки товарів на складі\n\n"
        "Товар відображається згідно вибраної фірми в замовленні"
    ),
    "ax_orders_missing": (
        "🚫 *Товар не відображається*\n\n"
        "• Якщо товар не відображається в КПК → його немає на залишках\n"
        "• Товар доступний згідно вибраної фірми в замовленні\n"
        "• Немає потрібної фірми → відсутній або закінчився договір\n"
        "  → Зверніться до старшого оператора"
    ),
}


async def tg_send(chat_id: int, msg_text: str, keyboard=None, parse_mode="Markdown"):
    if not ALEX_AVTD_BOT_TOKEN:
        return
    payload = {"chat_id": chat_id, "text": msg_text, "parse_mode": parse_mode}
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logger.warning(f"[ALEX_AVTD] tg_send error: {e}")


async def tg_answer_callback(callback_id: str):
    if not ALEX_AVTD_BOT_TOKEN:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{TELEGRAM_API}/answerCallbackQuery",
                json={"callback_query_id": callback_id},
                timeout=5,
            )
    except Exception as e:
        logger.warning(f"[ALEX_AVTD] answerCallback error: {e}")


async def tg_edit(chat_id: int, message_id: int, msg_text: str, keyboard=None):
    if not ALEX_AVTD_BOT_TOKEN:
        return
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": msg_text,
        "parse_mode": "Markdown",
    }
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        async with httpx.AsyncClient() as client:
            await client.post(f"{TELEGRAM_API}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        logger.warning(f"[ALEX_AVTD] tg_edit error: {e}")


def is_authorized(telegram_id: int, db: Session) -> bool:
    result = db.execute(
        _sa_text("SELECT 1 FROM hr_users WHERE telegram_id = :tid AND is_active = true"),
        {"tid": telegram_id},
    ).fetchone()
    return result is not None


def _get_user_name(telegram_id: int, db: Session) -> str:
    """Fetch full_name from hr_users for logging."""
    try:
        row = db.execute(
            _sa_text("SELECT full_name FROM hr_users WHERE telegram_id = :tid"),
            {"tid": telegram_id},
        ).fetchone()
        return row[0] if row and row[0] else "Unknown"
    except Exception:
        return "Unknown"


async def _log_query(telegram_id: int, query: str, preset_matched: bool,
                     response_time_ms: int, db: Session, user_name: str = "Unknown"):
    try:
        db.execute(
            _sa_text("""
                INSERT INTO hr_query_log
                    (user_id, user_name, query, preset_matched, response_time_ms, bot_source, created_at)
                VALUES
                    (:uid, :name, :q, :pm, :rt, 'alex_avtd', NOW())
            """),
            {
                "uid": telegram_id,
                "name": user_name,
                "q": query[:500],
                "pm": preset_matched,
                "rt": response_time_ms,
            },
        )
        db.commit()
    except Exception as e:
        logger.warning(f"[ALEX_AVTD] log_query failed: {e}")


@alex_avtd_router.post("/api/telegram/alex_avtd_webhook")
async def alex_avtd_webhook(request: Request):
    if not ALEX_AVTD_BOT_TOKEN:
        return {"ok": True}

    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

    db: Session = next(get_db())

    try:
        if "callback_query" in update:
            cq = update["callback_query"]
            callback_id = cq["id"]
            telegram_id = cq["from"]["id"]
            chat_id = cq["message"]["chat"]["id"]
            message_id = cq["message"]["message_id"]
            data = cq.get("data", "")

            await tg_answer_callback(callback_id)

            if not is_authorized(telegram_id, db):
                await tg_send(chat_id, "⛔ Доступ заборонено. Зверніться до HR.")
                return {"ok": True}

            user_name = _get_user_name(telegram_id, db)

            if data == "ax_menu":
                await tg_edit(chat_id, message_id, "👋 Оберіть розділ:", main_menu_keyboard())
                return {"ok": True}

            if data == "ax_client":
                await tg_edit(chat_id, message_id,
                              "👤 *Інформація по клієнту*\n\nОберіть тему:", client_keyboard())
                return {"ok": True}

            if data == "ax_kpi":
                await tg_edit(chat_id, message_id,
                              "📊 *KPI та показники*\n\nОберіть тему:", kpi_keyboard())
                return {"ok": True}

            if data == "ax_tech":
                await tg_edit(chat_id, message_id,
                              "🔧 *Технічні питання*\n\nОберіть тему:", tech_keyboard())
                return {"ok": True}

            if data == "ax_orders":
                await tg_edit(chat_id, message_id,
                              "📦 *Замовлення та залишки*\n\nОберіть тему:", orders_keyboard())
                return {"ok": True}

            if data in PRESETS:
                t0 = time.time()
                await tg_edit(chat_id, message_id, PRESETS[data], back_keyboard())
                elapsed = int((time.time() - t0) * 1000)
                await _log_query(telegram_id, data, True, elapsed, db, user_name)
                return {"ok": True}

            return {"ok": True}

        if "message" not in update:
            return {"ok": True}

        msg = update["message"]
        chat_id = msg["chat"]["id"]
        telegram_id = msg["from"]["id"]
        msg_text = msg.get("text", "").strip()

        if not msg_text:
            return {"ok": True}

        if not is_authorized(telegram_id, db):
            await tg_send(
                chat_id,
                "⛔ *Доступ заборонено*\n\nЦей бот доступний лише для співробітників АВТД.\n"
                "Зверніться до HR-відділу для отримання доступу.",
            )
            return {"ok": True}

        user_name = _get_user_name(telegram_id, db)

        if msg_text in ("/start", "/menu"):
            await tg_send(
                chat_id,
                "👋 Привіт! Я *Alex* — твій асистент у полі.\n\n"
                "Обери розділ або напиши питання напряму 👇",
                main_menu_keyboard(),
            )
            return {"ok": True}

        t0 = time.time()
        try:
            from routes.hr_routes import hr_pinecone_index
            from services.hr_rag_service import HRRagService

            service = HRRagService(
                pinecone_index=hr_pinecone_index,
                db_session=db,
                system_prompt_override=ALEX_AVTD_SYSTEM_PROMPT,
            )
            answer = await service.get_answer_with_context(
                query=msg_text,
                user_context={"user_id": telegram_id, "bot_source": "alex_avtd"},
            )
            response_text = answer.text
            preset_matched = answer.from_preset
        except Exception as e:
            logger.error(f"[ALEX_AVTD] RAG error: {e}")
            response_text = (
                "⚠️ Виникла помилка при обробці запиту.\n\n"
                "Спробуй ще раз або зверніться до:\n"
                "• Старшого оператора\n"
                "• Порталу: https://tdav.atlassian.net/"
            )
            preset_matched = False

        elapsed_ms = int((time.time() - t0) * 1000)
        await tg_send(chat_id, response_text, back_keyboard())
        await _log_query(telegram_id, msg_text, preset_matched, elapsed_ms, db, user_name)

    except Exception as e:
        logger.error(f"[ALEX_AVTD] Webhook error: {e}")
    finally:
        db.close()

    return {"ok": True}
