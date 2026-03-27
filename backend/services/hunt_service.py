import os
import asyncio
import json
import logging
import httpx
from datetime import datetime as dt

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
                if data.get("error_code") == 400 or resp.status_code == 400:
                    logger.warning(
                        f"TG parse_mode error, retrying without parse_mode: "
                        f"{data.get('description', '')}"
                    )
                    payload_plain = {k: v for k, v in payload.items() if k != "parse_mode"}
                    resp2 = await client.post(url, json=payload_plain, timeout=15.0)
                    data = resp2.json()
                    if not data.get("ok"):
                        logger.error(f"TG send error (plain fallback): {data}")
                else:
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


def _candidate_key(c: dict) -> str:
    """Deduplication key: prefer profile_url, fall back to phone."""
    return c.get("profile_url") or c.get("phone") or c.get("username") or ""


async def _scrape_round(
    parsed: dict,
    channels: list,
    depth_days: int,
    seen_keys: set,
    round_num: int = 1,
) -> list:
    """
    Run one round of TG + Work.ua + Robota.ua scraping with the given depth_days.
    Returns only candidates NOT already in seen_keys.
    Adds new keys to seen_keys in-place.
    """
    from services.hunt_tg_scraper import scrape_telegram_channels as search_tg_channels
    from services.hunt_workua_scraper import search_workua
    from services.hunt_robotaua_scraper import search_robotaua
    from services.hunt_robotaua_applies import search_robotaua_applies

    keywords = parsed.get("keywords", [])
    if not keywords and parsed.get("position"):
        keywords = parsed["position"].split()[:5]

    logger.info(f"[Hunt] Round {round_num} — launching 4 scrapers (TG, WorkUA, RobotaUA, Applies) depth={depth_days}d")
    results = await asyncio.gather(
        search_tg_channels(keywords, channels, depth_days=depth_days),
        search_workua(parsed, depth_days=depth_days),
        search_robotaua(parsed, depth_days=depth_days),
        search_robotaua_applies(parsed, round_num=round_num),
        return_exceptions=True,
    )

    tg_r, workua_r, robotaua_r, applies_r = results
    tg_count = len(tg_r) if isinstance(tg_r, list) else f"ERR({tg_r})"
    workua_count = len(workua_r) if isinstance(workua_r, list) else f"ERR({workua_r})"
    robotaua_count = len(robotaua_r) if isinstance(robotaua_r, list) else f"ERR({robotaua_r})"
    applies_count = len(applies_r) if isinstance(applies_r, list) else f"ERR({applies_r})"
    logger.info(
        f"[Hunt] Round {round_num} results: "
        f"TG={tg_count}, WorkUA={workua_count}, RobotaUA={robotaua_count}, Applies={applies_count}"
    )

    raw = []
    for r in (applies_r, robotaua_r, workua_r, tg_r):
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
                raw.append(c)

    source_counts: dict = {}
    for c in raw:
        s = c.get("source", "?")
        source_counts[s] = source_counts.get(s, 0) + 1
    logger.info(f"[Hunt] Round {round_num} candidates by source: {source_counts}")

    # Dedup against already-seen candidates
    new_candidates = []
    for c in raw:
        key = _candidate_key(c)
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        new_candidates.append(c)

    return new_candidates


async def _score_candidates(candidates: list, parsed: dict, vacancy_city: str) -> list:
    """Score a list of candidates and apply city-mismatch cap."""
    from services.hunt_scorer import score_candidate
    from config.hunt_config import HUNT_CONFIG

    to_score = candidates[:HUNT_CONFIG["max_candidates_to_score"]]
    scored_raw = await asyncio.gather(
        *[score_candidate(c, parsed) for c in to_score],
        return_exceptions=True,
    )

    scored = []
    for i, s in enumerate(scored_raw):
        if isinstance(s, Exception):
            logger.error(f"Scoring error: {s}")
            continue
        s["raw_text"] = to_score[i].get("raw_text", "")
        # Carry forward date/fallback metadata from the raw candidate
        for field in ("message_date", "last_active_parsed", "candidate_date"):
            if field in to_score[i]:
                s.setdefault(field, to_score[i][field])
        scored.append(s)

    for sc in scored:
        if not _cities_match(vacancy_city, sc.get("city", "")):
            cap = HUNT_CONFIG["city_mismatch_cap"]
            old_score = sc.get("score", 0)
            sc["score"] = min(old_score, cap)
            logger.info(
                f"City mismatch: capped score to {cap} "
                f"({sc.get('city')} vs {vacancy_city})"
            )

    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    before = len(scored)
    scored = [sc for sc in scored if sc.get("score", 0) > 0]
    if len(scored) < before:
        logger.info(f"[Score filter] Removed {before - len(scored)} vacancy/zero-score entries")
    return scored


async def run_hunt(vacancy_id: int, vacancy_text: str, thread_id: int, chat_id: int):
    from config.hunt_config import HUNT_CONFIG

    import models
    if models.SessionLocal is None:
        models.init_db()
    db = models.SessionLocal()

    try:
        from models.hunt_models import HuntVacancy, HuntCandidate, HuntSource
        from services.hunt_vacancy_parser import parse_vacancy
        from services.hunt_scorer import extract_salary_data
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
            "🔍 Шукаю кандидатів...\n📋 Work.ua + Telegram + Robota.ua\n⏳ Це займе 1-3 хвилини",
            thread_id=thread_id,
        )
        status_msg_id = status_resp.get("result", {}).get("message_id")

        # Load active TG channels from DB
        import psycopg2
        try:
            conn = psycopg2.connect(os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL"))
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

        vacancy_city = parsed.get("city", "")
        seen_keys: set = set()

        # ── ROUND 1: 60 days ──────────────────────────────────────
        depth1 = HUNT_CONFIG["search_depth_days"]
        logger.info(f"Hunt #{vacancy_id} Round 1: depth={depth1}d")
        round1_raw = await _scrape_round(parsed, channels, depth1, seen_keys, round_num=1)

        if not round1_raw:
            if status_msg_id:
                await _edit_message(
                    chat_id, status_msg_id,
                    "⚠️ Кандидатів не знайдено.\n💡 Спробуйте переформулювати вакансію або розширити вимоги.",
                )
            if vacancy:
                vacancy.status = 'no_results'
                db.commit()
            return

        scored1 = await _score_candidates(round1_raw, parsed, vacancy_city)
        quality1 = [sc for sc in scored1 if sc.get("score", 0) >= HUNT_CONFIG["quality_threshold"]]
        logger.info(f"Hunt #{vacancy_id} Round 1: {len(scored1)} scored, {len(quality1)} quality")

        all_scored = list(scored1)

        # ── ROUND 2: 180 days (fallback) ──────────────────────────
        if not quality1:
            depth2 = HUNT_CONFIG["fallback_depth_days"]
            logger.info(f"Hunt #{vacancy_id} Round 2: depth={depth2}d (no quality from R1)")
            if status_msg_id:
                await _edit_message(
                    chat_id, status_msg_id,
                    "🔄 Розширюю пошук до 6 місяців...",
                )
            else:
                await _send_message(chat_id, "🔄 Розширюю пошук до 6 місяців...", thread_id=thread_id)

            round2_raw = await _scrape_round(parsed, channels, depth2, seen_keys, round_num=2)
            if round2_raw:
                scored2 = await _score_candidates(round2_raw, parsed, vacancy_city)
                for sc in scored2:
                    sc["is_fallback"] = True
                    sc["fallback_round"] = 180
                quality1 = [sc for sc in scored2 if sc.get("score", 0) >= HUNT_CONFIG["quality_threshold"]]
                all_scored.extend(scored2)
                logger.info(f"Hunt #{vacancy_id} Round 2: {len(scored2)} scored, {len(quality1)} quality")

        # ── ROUND 3: 365 days (deep fallback) ─────────────────────
        if not quality1:
            depth3 = HUNT_CONFIG["fallback_deep_depth_days"]
            logger.info(f"Hunt #{vacancy_id} Round 3: depth={depth3}d (no quality from R1+R2)")
            if status_msg_id:
                await _edit_message(
                    chat_id, status_msg_id,
                    "🔄 Розширюю пошук до 1 року...",
                )
            else:
                await _send_message(chat_id, "🔄 Розширюю пошук до 1 року...", thread_id=thread_id)

            round3_raw = await _scrape_round(parsed, channels, depth3, seen_keys, round_num=3)
            if round3_raw:
                scored3 = await _score_candidates(round3_raw, parsed, vacancy_city)
                for sc in scored3:
                    sc["is_fallback"] = True
                    sc["fallback_round"] = 365
                quality1 = [sc for sc in scored3 if sc.get("score", 0) >= HUNT_CONFIG["quality_threshold"]]
                all_scored.extend(scored3)
                logger.info(f"Hunt #{vacancy_id} Round 3: {len(scored3)} scored, {len(quality1)} quality")

        # ── Save ALL scored candidates to DB ───────────────────────
        for sc in all_scored:
            # Resolve candidate_date from available date fields
            candidate_date = None
            for field in ("candidate_date", "message_date", "last_active_parsed"):
                val = sc.get(field)
                if not val:
                    continue
                if isinstance(val, str):
                    try:
                        from datetime import datetime as _dt
                        candidate_date = _dt.fromisoformat(val.replace("Z", "+00:00")).replace(tzinfo=None)
                    except Exception:
                        pass
                elif hasattr(val, "year"):
                    candidate_date = val
                if candidate_date:
                    break

            try:
                await extract_salary_data(sc, parsed, vacancy_id)
            except Exception as sal_err:
                logger.warning(f"Salary extraction skipped: {sal_err}")

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
                candidate_date=candidate_date,
                is_fallback=sc.get("is_fallback", False),
                fallback_round=sc.get("fallback_round"),
            )
            db.add(candidate)
            db.flush()
            sc["db_id"] = candidate.id
        db.commit()

        quality = quality1
        total = len(all_scored)

        if not quality:
            msg = "😔 Якісних кандидатів не знайдено.\nСпробуйте переформулювати вакансію або розширити вимоги."
            if status_msg_id:
                await _edit_message(chat_id, status_msg_id, msg)
            else:
                await _send_message(chat_id, msg, thread_id=thread_id)
            if vacancy:
                vacancy.status = 'no_results'
                db.commit()
            return

        top = quality[:HUNT_CONFIG["max_cards_shown"]]

        # Determine which round produced the results for the status message
        round_label = ""
        if top and top[0].get("is_fallback"):
            fr = top[0].get("fallback_round")
            if fr == 365:
                round_label = "\n📋 Знайдено в архіві за 1 рік"
            elif fr == 180:
                round_label = "\n📋 Знайдено в архіві за 6 місяців"

        status_text = (
            f"✅ Знайдено {len(quality)} якісних кандидатів з {total}. "
            f"Показую топ {len(top)}:{round_label}"
        )
        if status_msg_id:
            await _edit_message(chat_id, status_msg_id, status_text)

        for idx, sc in enumerate(top, 1):
            card_text = format_candidate_card(sc, idx)
            cand_id = sc.get("db_id")
            keyboard_rows = [
                [
                    {"text": "✅ В роботу", "callback_data": f"hunt_approve_{cand_id}"},
                    {"text": "❌ Пропустити", "callback_data": f"hunt_reject_{cand_id}"},
                ],
                [
                    {"text": "💾 Зберегти", "callback_data": f"hunt_save_{cand_id}"},
                    {"text": "🎯 Найняти", "callback_data": f"hunt_hire_{cand_id}"},
                ],
            ]
            if sc.get("source") == "robota.ua":
                keyboard_rows.append([
                    {"text": "📞 Контакт", "callback_data": f"hunt_contact_{cand_id}"},
                ])
            keyboard = {"inline_keyboard": keyboard_rows}
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


async def _close_robotaua_vacancy_bg(robotaua_vacancy_id: int):
    """Background task: close a published vacancy on Robota.ua after hire."""
    try:
        from services.hunt_robotaua_poster import close_vacancy_on_robotaua
        closed = await close_vacancy_on_robotaua(robotaua_vacancy_id)
        logger.info(f"[Hunt] Robota.ua vacancy {robotaua_vacancy_id} closed: {closed}")
    except Exception as e:
        logger.error(f"[Hunt] _close_robotaua_vacancy_bg error: {e}")


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
            asyncio.create_task(run_hunt(vacancy_id, vacancy_text, thread_id, chat_id))

        elif action == "post":
            vacancy.status = 'posting'
            db.commit()
            await _edit_message(chat_id, message_id, f"📢 Розміщую вакансію #{vacancy_id} на Robota.ua...")
            from services.hunt_robotaua_poster import run_vacancy_posting_robotaua
            asyncio.create_task(run_vacancy_posting_robotaua(vacancy_id, chat_id, thread_id))

        elif action == "both":
            vacancy.status = 'searching'
            db.commit()
            await _edit_message(chat_id, message_id, f"🔍+📢 Шукаю кандидатів і публікую вакансію #{vacancy_id} на Robota.ua...")
            from services.hunt_robotaua_poster import run_vacancy_posting_robotaua
            asyncio.create_task(run_hunt(vacancy_id, vacancy_text, thread_id, chat_id))
            asyncio.create_task(run_vacancy_posting_robotaua(vacancy_id, chat_id, thread_id))

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

    from models.hunt_models import HuntCandidate, HuntVacancy

    # ── Contact button: fetch phone/email on demand ────────────────────────
    if decision == "contact":
        candidate = db.query(HuntCandidate).filter(HuntCandidate.id == candidate_id).first()
        if not candidate:
            await _answer_callback(callback_id, "Кандидата не знайдено")
            return
        if candidate.source != "robota.ua":
            await _answer_callback(callback_id, "Контакт доступний тільки для Robota.ua")
            return

        # Extract resume_id from profile_url  e.g. https://robota.ua/ua/cv/12345678
        profile_url = candidate.profile_url or ""
        import re as _re
        m = _re.search(r"/cv/(\d+)", profile_url)
        if not m:
            await _answer_callback(callback_id, "Не вдалося визначити ID резюме")
            return

        resume_id_str = m.group(1)
        await _answer_callback(callback_id, "📞 Завантажуємо контакт...")

        from services.hunt_robotaua_scraper import fetch_robotaua_contact
        result = await fetch_robotaua_contact(resume_id_str)

        if result.get("error"):
            await _send_message(
                chat_id,
                f"⚠️ Не вдалося отримати контакт:\n{result['error']}",
                thread_id=message.get("message_thread_id"),
            )
            return

        phone = result.get("phone") or ""
        email = result.get("email") or ""
        full_name = result.get("full_name") or candidate.full_name or ""
        skills_text = result.get("skills_text") or ""

        # Contacts not available — this CV requires CVDB subscription to unlock
        if not phone and not email:
            await _send_message(
                chat_id,
                (
                    f"📞 Контакти доступні після входу на robota.ua:\n"
                    f"🔗 {profile_url}\n\n"
                    f"💡 Для автоматичного отримання контактів потрібна підписка CVDB"
                ),
                thread_id=message.get("message_thread_id"),
            )
            return

        contact_lines = [
            f"📞 *Контакт — {full_name}*",
            f"Телефон: {phone or '—'}",
            f"Email: {email or '—'}",
        ]
        if skills_text:
            contact_lines.append(f"\n🛠 Навички: {skills_text[:300]}")
        contact_lines.append(f"\n🔗 {profile_url}")

        await _send_message(
            chat_id,
            "\n".join(contact_lines),
            thread_id=message.get("message_thread_id"),
        )

        # Save contact to DB for future reference
        if phone != "—" or email != "—":
            contact_str = ", ".join(p for p in [phone, email] if p != "—")
            candidate.contact = contact_str
            db.commit()

        return

    # ── Standard decision buttons ──────────────────────────────────────────
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
            candidate.hired_at = dt.now()
            vacancy = db.query(HuntVacancy).filter(HuntVacancy.id == candidate.vacancy_id).first()
            if vacancy and vacancy.status != "filled":
                vacancy.status = "filled"
                if vacancy.robotaua_vacancy_id:
                    asyncio.create_task(_close_robotaua_vacancy_bg(vacancy.robotaua_vacancy_id))
        db.commit()
        logger.info(f"Hunt candidate #{candidate_id} → {status}")
    else:
        logger.warning(f"Hunt candidate #{candidate_id} not found")

    if chat_id and message_id:
        keyboard = {"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]}
        await _edit_reply_markup(chat_id, message_id, reply_markup=keyboard)

    await _answer_callback(callback_id, label)
