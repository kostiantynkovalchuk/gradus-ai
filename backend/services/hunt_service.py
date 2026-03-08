import os
import asyncio
import json
import logging
import httpx

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_MAYA_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

CITY_ALIASES = {
    "дніпро": ["дніпро", "dnipro", "дніпропетровськ"],
    "київ": ["київ", "kyiv", "киев"],
    "харків": ["харків", "kharkiv", "харьков"],
    "одеса": ["одеса", "odesa", "одесса"],
    "львів": ["львів", "lviv"],
}


def _cities_match(vacancy_city: str, candidate_city: str) -> bool:
    if not vacancy_city or not candidate_city:
        return True
    v = vacancy_city.lower().strip()
    c = candidate_city.lower().strip()
    for aliases in CITY_ALIASES.values():
        if any(v in a or a in v for a in aliases):
            if any(c in a or a in c for a in aliases):
                return True
    return v in c or c in v


async def _send_message(chat_id: int, text: str, thread_id: int = None, reply_markup: dict = None) -> dict:
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return {}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if thread_id:
        payload["message_thread_id"] = thread_id
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=15.0)
            data = resp.json()
            if not data.get("ok"):
                logger.error(f"TG send error: {data}")
            return data
    except Exception as e:
        logger.error(f"TG send exception: {e}")
        return {}


async def _edit_message(chat_id: int, message_id: int, text: str, reply_markup: dict = None) -> dict:
    if not BOT_TOKEN:
        return {}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10.0)
            return resp.json()
    except Exception as e:
        logger.error(f"TG edit exception: {e}")
        return {}


async def _edit_reply_markup(chat_id: int, message_id: int, reply_markup: dict = None) -> dict:
    if not BOT_TOKEN:
        return {}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageReplyMarkup"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10.0)
            return resp.json()
    except Exception as e:
        logger.error(f"TG edit markup exception: {e}")
        return {}


async def _answer_callback(callback_query_id: str, text: str) -> dict:
    if not BOT_TOKEN:
        return {}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={
                "callback_query_id": callback_query_id,
                "text": text,
            }, timeout=10.0)
            return resp.json()
    except Exception as e:
        logger.error(f"TG answer callback exception: {e}")
        return {}


async def _fetch_and_save_salary_analytics(position: str, vacancy_id: int) -> None:
    try:
        if not position:
            return

        from services.robotaua_salary import fetch_salary_analytics, save_salary_data

        loop = asyncio.get_event_loop()
        salary_result = await loop.run_in_executor(
            None, lambda: fetch_salary_analytics(position)
        )

        if salary_result:
            import models
            if models.SessionLocal is None:
                models.init_db()
            sal_db = models.SessionLocal()
            try:
                save_salary_data(salary_result, vacancy_id, sal_db)
                logger.info(f"Salary analytics saved for vacancy #{vacancy_id}")
            finally:
                sal_db.close()
    except Exception as e:
        logger.error(f"Salary analytics background task failed: {e}")


async def run_hunt(vacancy_id: int, vacancy_text: str, thread_id: int, chat_id: int):
    import models
    if models.SessionLocal is None:
        models.init_db()
    db = models.SessionLocal()

    try:
        from models.hunt_models import HuntVacancy, HuntCandidate, HuntSource
        from services.hunt_vacancy_parser import parse_vacancy
        from services.hunt_tg_scraper import scrape_telegram_channels as search_tg_channels
        from services.hunt_workua_scraper import search_workua
        from services.hunt_scorer import score_candidate, extract_salary_data
        from services.hunt_card_formatter import format_candidate_card

        logger.info(f"🔍 Hunt started for vacancy #{vacancy_id}")

        parsed = await parse_vacancy(vacancy_text)

        vacancy = db.query(HuntVacancy).filter(HuntVacancy.id == vacancy_id).first()
        if vacancy:
            vacancy.position = parsed.get("position", "")[:200]
            vacancy.city = parsed.get("city")
            vacancy.requirements = json.dumps(parsed.get("requirements", []), ensure_ascii=False)
            vacancy.salary_max = parsed.get("salary_max")
            vacancy.status = 'searching'
            db.commit()

        asyncio.create_task(
            _fetch_and_save_salary_analytics(
                parsed.get("position", ""),
                vacancy_id,
            )
        )

        status_resp = await _send_message(
            chat_id,
            "🔍 Шукаю кандидатів...\n📋 Work.ua + Telegram канали\n⏳ Це займе 1-2 хвилини",
            thread_id=thread_id,
        )
        status_msg_id = status_resp.get("result", {}).get("message_id")

        import psycopg2
        try:
            conn = psycopg2.connect(os.getenv("DATABASE_URL"))
            cur = conn.cursor()
            cur.execute(
                "SELECT tg_channel FROM hunt_sources "
                "WHERE is_active = TRUE AND channel_type = 'scan'"
            )
            rows = cur.fetchall()
            channels = [row[0] for row in rows]
            conn.close()
        except Exception as e:
            logger.warning(f"DB channel load failed: {e}, using defaults")
            channels = []

        if not channels:
            channels = [
                "kiev_rabota2", "rabota_kieve_ua",
                "rabota_dnipro_vacancy", "kharkiv_robota1",
                "odesa_odessa_rabota", "robota_rabota_lviv",
                "jobforukrainians",
            ]
            logger.info(f"Using default channels: {channels}")
        else:
            logger.info(f"Channels from DB (scan): {channels}")

        keywords = parsed.get("keywords", [])
        if not keywords and parsed.get("position"):
            keywords = parsed["position"].split()[:5]

        results = await asyncio.gather(
            search_tg_channels(keywords, channels),
            search_workua(parsed),
            return_exceptions=True,
        )

        all_candidates = []
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Scraper error: {r}")
                continue
            if isinstance(r, list):
                for c in r:
                    if "phone" in c or "username" in c:
                        contact_parts = []
                        if c.get("phone"):
                            contact_parts.append(c["phone"])
                        if c.get("username"):
                            contact_parts.append(c["username"])
                        c.setdefault("contact", " / ".join(contact_parts))
                    if c.get("message_link") and not c.get("profile_url"):
                        c["profile_url"] = c["message_link"]
                    src = c.get("source", "")
                    if src.startswith("telegram:"):
                        c["source"] = "telegram"
                    all_candidates.append(c)

        if not all_candidates:
            msg = "⚠️ Кандидатів не знайдено.\n💡 Спробуйте переформулювати вакансію або розширити вимоги."
            if status_msg_id:
                await _edit_message(chat_id, status_msg_id, msg)
            else:
                await _send_message(chat_id, msg, thread_id=thread_id)
            if vacancy:
                vacancy.status = 'no_results'
                db.commit()
            logger.info(f"Hunt #{vacancy_id}: no candidates found")
            return

        to_score = all_candidates[:10]
        scored = await asyncio.gather(
            *[score_candidate(c, parsed) for c in to_score],
            return_exceptions=True,
        )

        scored_candidates = []
        for i, s in enumerate(scored):
            if isinstance(s, Exception):
                logger.error(f"Scoring error: {s}")
                continue
            s["raw_text"] = to_score[i].get("raw_text", "")
            scored_candidates.append(s)

        vacancy_city = parsed.get("city", "")
        for sc in scored_candidates:
            if not _cities_match(vacancy_city, sc.get("city", "")):
                old_score = sc.get("score", 0)
                sc["score"] = min(old_score, 20)
                logger.info(
                    f"City mismatch: capped score to 20 "
                    f"({sc.get('city')} vs {vacancy_city})"
                )

        scored_candidates.sort(key=lambda x: x.get("score", 0), reverse=True)

        for sc in scored_candidates:
            try:
                await extract_salary_data(sc, parsed, vacancy_id)
            except Exception as sal_err:
                logger.warning(f"Salary extraction skipped: {sal_err}")

        for sc in scored_candidates:
            candidate = HuntCandidate(
                vacancy_id=vacancy_id,
                source=sc.get("source", "unknown"),
                full_name=sc.get("full_name", "Невідомо"),
                age=sc.get("age"),
                city=sc.get("city"),
                experience_years=sc.get("experience_years"),
                current_role=sc.get("current_role"),
                skills=sc.get("skills", ""),
                salary_expectation=sc.get("salary_expectation"),
                contact=sc.get("contact", ""),
                profile_url=sc.get("profile_url", ""),
                raw_text=sc.get("raw_text", "")[:2000],
                ai_score=sc.get("score", 0),
                ai_summary=sc.get("summary", ""),
                hr_decision='pending',
            )
            db.add(candidate)
            db.flush()
            sc["db_id"] = candidate.id
        db.commit()

        quality = [sc for sc in scored_candidates if sc.get("score", 0) >= 35]
        total = len(scored_candidates)

        if not quality:
            if status_msg_id:
                await _edit_message(
                    chat_id, status_msg_id,
                    f"😔 Якісних кандидатів не знайдено.\nСпробуйте переформулювати вакансію або розширити вимоги.",
                )
            return

        top = quality[:5]

        if status_msg_id:
            await _edit_message(
                chat_id, status_msg_id,
                f"✅ Знайдено {len(quality)} якісних кандидатів з {total}. Показую топ {min(5, len(quality))}:",
            )

        for idx, sc in enumerate(top, 1):
            card_text = format_candidate_card(sc, idx)
            cand_id = sc.get("db_id")
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "✅ В роботу", "callback_data": f"hunt_approve_{cand_id}"},
                        {"text": "❌ Пропустити", "callback_data": f"hunt_reject_{cand_id}"},
                    ],
                    [
                        {"text": "💾 Зберегти", "callback_data": f"hunt_save_{cand_id}"},
                        {"text": "🎯 Найняти", "callback_data": f"hunt_hire_{cand_id}"},
                    ],
                ]
            }
            resp = await _send_message(chat_id, card_text, thread_id=thread_id, reply_markup=keyboard)
            msg_id = resp.get("result", {}).get("message_id")
            if msg_id and cand_id:
                cand_obj = db.query(HuntCandidate).filter(HuntCandidate.id == cand_id).first()
                if cand_obj:
                    cand_obj.telegram_message_id = msg_id
                    db.commit()
            await asyncio.sleep(0.5)

        await _send_message(
            chat_id,
            "──────────────────\n🔄 Потрібно більше кандидатів?\nВідправте вакансію ще раз або уточніть вимоги.",
            thread_id=thread_id,
        )

        if vacancy:
            vacancy.status = 'completed'
            db.commit()

        logger.info(f"✅ Hunt #{vacancy_id} completed: {total} scored, {len(top)} shown")

    except Exception as e:
        logger.error(f"❌ Hunt #{vacancy_id} failed: {e}", exc_info=True)
        try:
            await _send_message(
                chat_id,
                f"❌ Помилка пошуку: {str(e)[:200]}",
                thread_id=thread_id,
            )
        except Exception:
            pass
    finally:
        db.close()


async def handle_hunt_action(callback_query: dict):
    callback_data = callback_query.get("data", "")
    callback_id = callback_query.get("id")
    message = callback_query.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    thread_id = message.get("message_thread_id")

    parts = callback_data.split("_")
    if len(parts) < 4:
        await _answer_callback(callback_id, "Невірна команда")
        return

    action = parts[2]
    try:
        vacancy_id = int(parts[3])
    except (ValueError, IndexError):
        await _answer_callback(callback_id, "Невірний ID")
        return

    await _answer_callback(callback_id, "Прийнято!")

    import models
    if models.SessionLocal is None:
        models.init_db()
    db = models.SessionLocal()

    try:
        from models.hunt_models import HuntVacancy
        vacancy = db.query(HuntVacancy).filter(HuntVacancy.id == vacancy_id).first()

        if not vacancy:
            await _edit_message(chat_id, message_id, f"❌ Вакансію #{vacancy_id} не знайдено")
            return

        vacancy_text = vacancy.raw_text or ""

        if action == "search":
            vacancy.status = 'searching'
            db.commit()
            await _edit_message(chat_id, message_id, f"🔍 Шукаю кандидатів для вакансії #{vacancy_id}...")
            import asyncio
            asyncio.create_task(run_hunt(vacancy_id, vacancy_text, thread_id, chat_id))

        elif action == "post":
            vacancy.status = 'posting'
            db.commit()
            await _edit_message(chat_id, message_id, f"📢 Розміщую вакансію #{vacancy_id} в каналах...")
            import asyncio
            from services.hunt_poster import run_vacancy_posting
            asyncio.create_task(run_vacancy_posting(vacancy_id, chat_id, thread_id))

        elif action == "both":
            vacancy.status = 'searching'
            db.commit()
            await _edit_message(chat_id, message_id, f"🔍+📢 Шукаю кандидатів і розміщую вакансію #{vacancy_id}...")
            import asyncio
            from services.hunt_poster import run_vacancy_posting
            asyncio.create_task(run_hunt(vacancy_id, vacancy_text, thread_id, chat_id))
            asyncio.create_task(run_vacancy_posting(vacancy_id, chat_id, thread_id))

        elif action == "skip":
            vacancy.status = 'pending'
            db.commit()
            await _edit_message(chat_id, message_id, f"⏸ Збережено. Вакансія #{vacancy_id} чекає на обробку.")

        else:
            await _edit_message(chat_id, message_id, "❓ Невідома дія")

    except Exception as e:
        logger.error(f"Hunt action error: {e}", exc_info=True)
    finally:
        db.close()


async def handle_hunt_decision(callback_query: dict, db):
    callback_data = callback_query.get("data", "")
    callback_id = callback_query.get("id")
    message = callback_query.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")

    parts = callback_data.split("_")
    if len(parts) < 3:
        await _answer_callback(callback_id, "Невірна команда")
        return

    decision = parts[1]
    try:
        candidate_id = int(parts[2])
    except (ValueError, IndexError):
        await _answer_callback(callback_id, "Невірний ID")
        return

    from models.hunt_models import HuntCandidate

    decision_map = {
        "approve": ("approved", "✅ Взято в роботу"),
        "reject": ("rejected", "❌ Відхилено"),
        "save": ("saved", "💾 Збережено"),
        "hire": ("hired", "🎯 Найнято через Maya Hunt!"),
    }

    if decision not in decision_map:
        await _answer_callback(callback_id, "Невідома дія")
        return

    status, label = decision_map[decision]

    candidate = db.query(HuntCandidate).filter(HuntCandidate.id == candidate_id).first()
    if candidate:
        if decision == "hire" and candidate.hr_decision == "hired":
            await _answer_callback(callback_id, "🎯 Вже найнято раніше")
            return
        candidate.hr_decision = status
        if decision == "hire":
            from datetime import datetime as dt
            candidate.hired_at = dt.now()
            vacancy = db.query(HuntVacancy).filter(HuntVacancy.id == candidate.vacancy_id).first()
            if vacancy and vacancy.status != "filled":
                vacancy.status = "filled"
        db.commit()
        logger.info(f"Hunt candidate #{candidate_id} → {status}")
    else:
        logger.warning(f"Hunt candidate #{candidate_id} not found")

    if chat_id and message_id:
        keyboard = {"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]}
        await _edit_reply_markup(chat_id, message_id, reply_markup=keyboard)

    await _answer_callback(callback_id, label)
