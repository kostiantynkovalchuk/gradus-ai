"""
Alex AVTD Bot — Telegram webhook handler
Field agent assistant for AVTD sales reps
"""
import os
import time
import logging
import httpx
from typing import List, Optional
from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from sqlalchemy import text as _sa_text
from models import get_db
from services.avtd_tree import (
    main_menu_keyboard,
    back_keyboard,
    client_keyboard,
    kpi_keyboard,
    tech_keyboard,
    orders_keyboard,
    get_preset,
)

logger = logging.getLogger(__name__)
alex_avtd_router = APIRouter()

ALEX_AVTD_BOT_TOKEN = os.getenv("TELEGRAM_ALEX_AVTD_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{ALEX_AVTD_BOT_TOKEN}"

PHOTO_REPORT_BOT_LINK = "https://t.me/avtd_photo_report_bot"
# Alex-specific extra row prepended to the shared root menu.
_PHOTO_ROW = [{"text": "📷 Фотозвіт / Мерчандайзинг", "url": PHOTO_REPORT_BOT_LINK}]

ALEX_AVTD_SYSTEM_PROMPT = """Ти — Alex, асистент торгового агента АВТД.
Відповідай коротко і практично — агент читає з телефону між візитами.

Твоя зона відповідальності:
- Blitz Trade (КПК): робота, синхронізація, помилки
- KPI: СЦ, АКБ, ОА, МЧ, ДП, ДПХ, фотозвіт
- Замовлення: статуси R*, ND*, CRE*, А*, АЕ*
- Маршрути та торгові точки
- Акції та спеццілі
- Портфель брендів АВТД: GreenDay, Helsinki, Ukrainka,
  Adjari, Довбуш, Klinkov, Jean Jack, Villa UA,
  Kristi Valley, Didi Lari, Kosher, Funju
- Інформація по клієнту в mobiletrade

Якщо запит розмитий або незрозумілий — НЕ відмовляй.
Визнач найближчу тему за ключовими словами і дай відповідь:

план / плани / таргет / ціль / виконання → відповідай ОДРАЗУ без вступу. Формат відповіді:

Виконання плану дивись тут:

📊 Загальне виконання:
Blitz Trade → Головна → Інфо
https://mobiletrade.tdav.net.ua/home

📍 По конкретній точці:
Blitz Trade → Маршрут → Торгова точка → Показники

📋 Детальні звіти:
Звіт Аналітика — всі показники
Звіт ПП — по точках і агентах
Звіт Виконання СЦ — по агент/ТРТ/товар

Якщо потрібна конкретна причина чому не зараховується — уточни який показник: СЦ, АКБ, ОА, МЧ, ДП або ДПХ.

клієнт / точка / ТРТ / контрагент / дебіторка / ДЗ / борг
→ розкажи про інформацію по клієнту в mobiletrade

акція / акції / знижка / промо
→ розкажи про акції в Blitz Trade

замовлення / заказ / синхронізація / товар
→ розкажи про замовлення і типові помилки

фото / фотозвіт / ФЗ / мерч / мерчендайзинг
→ розкажи про фотозвіти в mobiletrade

маршрут / точка / перемаршрут
→ розкажи про маршрути і до кого звертатись

залишки / остатки / склад
→ розкажи про залишки в КПК і mobiletrade

Якщо зовсім не можеш визначити тему — запитай уточнення ОДНИМ
коротким питанням, не відмовляй повністю.

Посилання на портал: https://tdav.atlassian.net/
Відповідай мовою запиту (українська або російська)."""


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


def _get_user_name(telegram_id: int, db: Session, tg_from: dict = None) -> str:
    """Resolve display name: hr_users DB first, then Telegram identity, then Unknown."""
    try:
        row = db.execute(
            _sa_text("SELECT full_name FROM hr_users WHERE telegram_id = :tid"),
            {"tid": telegram_id},
        ).fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    if tg_from:
        parts = [tg_from.get("first_name", ""), tg_from.get("last_name", "")]
        name = " ".join(p for p in parts if p).strip()
        if name:
            return name
        if tg_from.get("username"):
            return "@" + tg_from["username"]
    return "Unknown"


async def _log_query(telegram_id: int, query: str, preset_matched: bool,
                     response_time_ms: int, db: Session, user_name: str = "Unknown",
                     rag_used: bool = False, content_ids: Optional[List[str]] = None,
                     search_method: Optional[str] = None, top_score: Optional[float] = None):
    try:
        db.execute(
            _sa_text("""
                INSERT INTO hr_query_log
                    (user_id, user_name, query, preset_matched, response_time_ms, bot_source,
                     rag_used, content_ids, search_method, top_score, created_at)
                VALUES
                    (:uid, :name, :q, :pm, :rt, 'alex_avtd',
                     :rag_used, :content_ids, :search_method, :top_score, NOW())
            """),
            {
                "uid": telegram_id,
                "name": user_name,
                "q": query[:500],
                "pm": preset_matched,
                "rt": response_time_ms,
                "rag_used": rag_used,
                "content_ids": content_ids or [],
                "search_method": search_method,
                "top_score": top_score,
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

    update_id = update.get("update_id")
    if update_id is not None:
        # Fail-open by design: a dedup-table failure must never block
        # real user traffic (mirrors sara_webhook.py's process_update).
        # Uses its own short-lived session so the dedup check does not
        # couple to the request session's lifecycle.
        dedup_db: Session = next(get_db())
        try:
            result = dedup_db.execute(
                _sa_text(
                    "INSERT INTO telegram_inbound_updates (bot_source, update_id) "
                    "VALUES ('alex_avtd', :update_id) ON CONFLICT DO NOTHING"
                ),
                {"update_id": update_id},
            )
            dedup_db.commit()
            if result.rowcount == 0:
                logger.info(f"🔁 Alex AVTD: duplicate update {update_id} ignored")
                return {"ok": True}
        except Exception as e:
            logger.error(f"Alex AVTD dedup check failed for update {update_id}: {e}")
            dedup_db.rollback()
        finally:
            dedup_db.close()

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

            if data == "ax_menu":
                await tg_edit(chat_id, message_id, "👋 Оберіть розділ:",
                              main_menu_keyboard("ax_", extra_rows=[_PHOTO_ROW]))
                return {"ok": True}

            if data == "ax_client":
                await tg_edit(chat_id, message_id,
                              "👤 *Інформація по клієнту*\n\nОберіть тему:", client_keyboard("ax_"))
                return {"ok": True}

            if data == "ax_kpi":
                await tg_edit(chat_id, message_id,
                              "📊 *KPI та показники*\n\nОберіть тему:", kpi_keyboard("ax_"))
                return {"ok": True}

            if data == "ax_tech":
                await tg_edit(chat_id, message_id,
                              "🔧 *Технічні питання*\n\nОберіть тему:", tech_keyboard("ax_"))
                return {"ok": True}

            if data == "ax_orders":
                await tg_edit(chat_id, message_id,
                              "📦 *Замовлення та залишки*\n\nОберіть тему:", orders_keyboard("ax_"))
                return {"ok": True}

            if data.startswith("ax_"):
                preset = get_preset(data[len("ax_"):])
                if preset:
                    await tg_edit(chat_id, message_id, preset, back_keyboard("ax_"))
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

        user_name = _get_user_name(telegram_id, db, msg["from"])

        if msg_text in ("/start", "/menu"):
            await tg_send(
                chat_id,
                "👋 Привіт! Я *Alex* — твій асистент у полі.\n\n"
                "Обери розділ або напиши питання напряму 👇",
                main_menu_keyboard("ax_", extra_rows=[_PHOTO_ROW]),
            )
            return {"ok": True}

        if msg_text.startswith("/"):
            return {"ok": True}

        t0 = time.time()
        answer = None
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
        await tg_send(chat_id, response_text, back_keyboard("ax_"))
        await _log_query(
            telegram_id, msg_text, preset_matched, elapsed_ms, db, user_name,
            rag_used=not preset_matched and bool(answer.sources) if answer else False,
            content_ids=[s.content_id for s in answer.sources] if answer else [],
            search_method=answer.search_method if answer else None,
            top_score=answer.top_score if answer else None,
        )

    except Exception as e:
        logger.error(f"[ALEX_AVTD] Webhook error: {e}")
    finally:
        db.close()

    return {"ok": True}
