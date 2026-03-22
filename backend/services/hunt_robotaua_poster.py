"""
Robota.ua Vacancy Poster for Maya Hunt
=======================================
Publishes parsed Maya Hunt vacancies to Robota.ua via the official employer REST API.

Publication flow:
  1. POST /vacancy/add (id=0) → returns int vacancy_id
  2. POST /vacancy/state/{id}?state=Publicated → makes it live

Requires employer credentials: ROBOTAUA_EMAIL + ROBOTAUA_PASSWORD.
Returns {"success": False, "error": "..."} gracefully on auth failure.
"""

import os
import logging

import httpx

from services.robotaua_auth import login_robotaua, invalidate_token
from services.robotaua_client import cf_client
from services.robotaua_reference import get_city_id

logger = logging.getLogger(__name__)

_EMPLOYER_API = "https://employer-api.robota.ua"
_VACANCY_URL_TEMPLATE = "https://robota.ua/ua/company/vacancy/{vacancy_id}"
_MIN_DESC_LEN = 150


# ──────────────────────────────────────────────────────────────────
# Description builder
# ──────────────────────────────────────────────────────────────────

def _build_description(vacancy: dict) -> str:
    """
    Build an HTML vacancy description >= 150 chars from parsed vacancy fields.
    Robota.ua supports basic HTML in descriptions.
    """
    position = vacancy.get("position") or "Вакансія"
    city = vacancy.get("city") or ""
    requirements = vacancy.get("requirements") or []
    salary_max = vacancy.get("salary_max")
    salary_currency = vacancy.get("salary_currency") or "USD"
    raw_text = vacancy.get("raw_text") or ""

    parts = []

    # Company branding
    parts.append(
        "<p><strong>Торговий Дім АВ</strong> — провідний дистриб'ютор "
        "алкогольних та слабоалкогольних напоїв в Україні. "
        "Шукаємо відповідального та цілеспрямованого фахівця.</p>"
    )

    if city:
        parts.append(f"<p>📍 Місто: {city}</p>")

    if salary_max:
        currency_sign = "$" if salary_currency == "USD" else "грн"
        parts.append(f"<p>💰 Заробітна плата: до {salary_max} {currency_sign}</p>")

    if requirements:
        parts.append("<p><strong>Вимоги:</strong></p><ul>")
        for req in requirements[:10]:
            req_str = str(req).strip()
            if req_str:
                parts.append(f"<li>{req_str}</li>")
        parts.append("</ul>")
    else:
        parts.append(
            "<p><strong>Вимоги:</strong></p>"
            "<ul><li>Досвід роботи у продажах</li>"
            "<li>Відповідальність та комунікабельність</li>"
            "<li>Бажання розвиватися у сфері дистрибуції</li></ul>"
        )

    parts.append(
        "<p><strong>Ми пропонуємо:</strong></p>"
        "<ul><li>Офіційне працевлаштування</li>"
        "<li>Конкурентну заробітну плату та бонуси</li>"
        "<li>Корпоративний автомобіль / телефон</li>"
        "<li>Можливості для кар'єрного зростання</li></ul>"
    )

    parts.append(
        "<p>Надсилайте резюме — ми розглянемо вашу кандидатуру найближчим часом!</p>"
    )

    description = "".join(parts)

    # Ensure minimum length
    if len(description) < _MIN_DESC_LEN:
        description += (
            "<p>Торговий Дім АВ — це команда профіóсіоналів, "
            "яка цінує кожного співробітника та інвестує у його розвиток.</p>"
        )

    return description


def _similar_position(name_a: str, name_b: str) -> bool:
    """Return True if two position names share significant words."""
    if not name_a or not name_b:
        return False
    words_a = set(w.lower() for w in name_a.split() if len(w) > 3)
    words_b = set(w.lower() for w in name_b.split() if len(w) > 3)
    return bool(words_a & words_b)


# ──────────────────────────────────────────────────────────────────
# Main public functions
# ──────────────────────────────────────────────────────────────────

async def post_vacancy_to_robotaua(vacancy: dict) -> dict:
    """
    Post a Maya Hunt vacancy to Robota.ua.

    Args:
        vacancy: dict with keys from HuntVacancy: position, city, salary_max,
                 salary_currency, requirements (list), raw_text

    Returns:
        {
          "success": bool,
          "vacancy_id": int | None,
          "url": str | None,
          "error": str | None,
        }
    """
    token = await login_robotaua()
    if not token:
        return {"success": False, "vacancy_id": None, "url": None,
                "error": "Немає токена авторизації Robota.ua"}

    # Resolve city
    city_name = vacancy.get("city") or ""
    city_id = await get_city_id(city_name) or 1  # default Kyiv

    # Build description
    description = _build_description(vacancy)

    # Build vacancy body
    body: dict = {
        "id": 0,
        "cityId": city_id,
        "name": vacancy.get("position") or "Вакансія",
        "description": description,
        "publishType": "Base",
        "sendResumeType": "3",
        "contactPerson": os.getenv("HR_CONTACT_NAME", "HR AVTD"),
        "contactPhone": os.getenv("HR_CONTACT_PHONE", ""),
        "contactEMail": os.getenv("HR_CONTACT_EMAIL", os.getenv("ROBOTAUA_EMAIL", "michailova@vinkom.net")),
        "employmentTypes": ["FullTime"],
        "workTypes": ["Office"],
        "endingType": "CloseAndNotify",
        "isForStudent": False,
    }

    salary_max = vacancy.get("salary_max")
    salary_currency = (vacancy.get("salary_currency") or "UAH").upper()
    if salary_max:
        # Convert USD → UAH if needed (Robota.ua expects UAH)
        if salary_currency == "USD":
            try:
                from services.salary_normalizer import get_usd_uah_rate
                rate = get_usd_uah_rate() or 40.0
                body["salary"] = int(salary_max * rate)
            except Exception:
                body["salary"] = int(salary_max * 40)
        else:
            body["salary"] = int(salary_max)

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        async with cf_client(timeout=20) as client:
            # Step 1: Create vacancy
            logger.info(f"[RobotaUA-Poster] Creating vacancy: {body['name']} / city_id={city_id}")
            add_resp = await client.post(f"{_EMPLOYER_API}/vacancy/add", headers=headers, json=body)

            if add_resp.status_code == 401:
                invalidate_token()
                return {
                    "success": False, "vacancy_id": None, "url": None,
                    "error": "Потрібен акаунт роботодавця (ROBOTAUA_EMAIL + ROBOTAUA_PASSWORD)"
                }

            if add_resp.status_code not in (200, 201):
                logger.error(f"[RobotaUA-Poster] /vacancy/add {add_resp.status_code}: {add_resp.text[:300]}")
                return {
                    "success": False, "vacancy_id": None, "url": None,
                    "error": f"API помилка {add_resp.status_code}: {add_resp.text[:150]}"
                }

            result = add_resp.json()
            # Response is either int or {"id": int, ...}
            if isinstance(result, int):
                new_vacancy_id = result
            elif isinstance(result, dict):
                new_vacancy_id = result.get("id") or result.get("vacancyId")
            else:
                new_vacancy_id = None

            if not new_vacancy_id:
                return {
                    "success": False, "vacancy_id": None, "url": None,
                    "error": f"API не повернув vacancy ID: {str(result)[:200]}"
                }

            logger.info(f"[RobotaUA-Poster] Vacancy created: id={new_vacancy_id}")

            # Step 2: Publish
            pub_resp = await client.post(
                f"{_EMPLOYER_API}/vacancy/state/{new_vacancy_id}?state=Publicated",
                headers=headers,
            )

            if pub_resp.status_code not in (200, 204):
                logger.warning(f"[RobotaUA-Poster] Publish {pub_resp.status_code}: {pub_resp.text[:200]}")
                vacancy_url = _VACANCY_URL_TEMPLATE.format(vacancy_id=new_vacancy_id)
                return {
                    "success": True,
                    "vacancy_id": new_vacancy_id,
                    "url": vacancy_url,
                    "error": f"Вакансію створено (draft), але публікація не вдалась: {pub_resp.status_code}",
                }

            vacancy_url = _VACANCY_URL_TEMPLATE.format(vacancy_id=new_vacancy_id)
            logger.info(f"[RobotaUA-Poster] Published: {vacancy_url}")
            return {"success": True, "vacancy_id": new_vacancy_id, "url": vacancy_url, "error": None}

    except Exception as e:
        logger.error(f"[RobotaUA-Poster] Error: {e}")
        return {"success": False, "vacancy_id": None, "url": None, "error": str(e)[:200]}


async def close_vacancy_on_robotaua(robotaua_vacancy_id: int) -> bool:
    """Close a vacancy on Robota.ua (call when HR clicks 'Найняти')."""
    if not robotaua_vacancy_id:
        return False
    token = await login_robotaua()
    if not token:
        return False
    try:
        async with cf_client(timeout=15) as client:
            resp = await client.post(
                f"{_EMPLOYER_API}/vacancy/state/{robotaua_vacancy_id}?state=Closed",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 401:
                invalidate_token()
            success = resp.status_code in (200, 204)
            logger.info(f"[RobotaUA-Poster] Close vacancy {robotaua_vacancy_id}: {'OK' if success else resp.status_code}")
            return success
    except Exception as e:
        logger.error(f"[RobotaUA-Poster] Close vacancy error: {e}")
        return False


async def get_avtd_vacancies() -> list:
    """List all AVTD vacancies on Robota.ua (for dashboard and duplicate check)."""
    token = await login_robotaua()
    if not token:
        return []
    try:
        async with cf_client(timeout=15) as client:
            resp = await client.post(
                f"{_EMPLOYER_API}/vacancy/list",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"page": 0},
            )
            if resp.status_code == 401:
                invalidate_token()
                return []
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else (data.get("vacancies") or data.get("items") or [])
            return []
    except Exception as e:
        logger.error(f"[RobotaUA-Poster] get_avtd_vacancies error: {e}")
        return []


async def run_vacancy_posting_robotaua(vacancy_id: int, chat_id: int, thread_id: int):
    """
    Top-level task: post a DB vacancy to Robota.ua and notify HR via Telegram.
    Designed to run as asyncio.create_task() — never raises.
    """
    import json as _json
    import models as _models

    if _models.SessionLocal is None:
        _models.init_db()
    db = _models.SessionLocal()

    try:
        from models.hunt_models import HuntVacancy, HuntPosting

        vacancy = db.query(HuntVacancy).filter(HuntVacancy.id == vacancy_id).first()
        if not vacancy:
            logger.error(f"[RobotaUA-Poster] Vacancy #{vacancy_id} not found")
            await _tg(chat_id, thread_id, f"❌ Вакансію #{vacancy_id} не знайдено")
            return

        # Duplicate check — already posted
        if vacancy.robotaua_vacancy_id:
            existing_url = vacancy.robotaua_vacancy_url or _VACANCY_URL_TEMPLATE.format(
                vacancy_id=vacancy.robotaua_vacancy_id
            )
            await _tg(
                chat_id, thread_id,
                f"ℹ️ Вакансію вже опубліковано на Robota.ua (ID #{vacancy.robotaua_vacancy_id})\n"
                f"🔗 {existing_url}"
            )
            return

        # Build vacancy dict for poster
        requirements = []
        if vacancy.requirements:
            try:
                requirements = _json.loads(vacancy.requirements)
            except Exception:
                pass

        parsed = {
            "position": vacancy.position or "",
            "city": vacancy.city or "",
            "salary_max": vacancy.salary_max,
            "salary_currency": "UAH",
            "requirements": requirements,
            "raw_text": vacancy.raw_text or "",
        }

        result = await post_vacancy_to_robotaua(parsed)

        if result["success"]:
            # Save robotaua_vacancy_id to DB
            vacancy.robotaua_vacancy_id = result["vacancy_id"]
            vacancy.robotaua_vacancy_url = result.get("url")
            vacancy.status = "posted"
            db.add(HuntPosting(
                vacancy_id=vacancy_id,
                channel="robota.ua",
                status="posted",
            ))
            db.commit()

            msg = f"✅ Вакансію опубліковано на Robota.ua!\n🔗 {result['url']}"
            if result.get("error"):
                msg += f"\n⚠️ {result['error']}"
            await _tg(chat_id, thread_id, msg)
            logger.info(f"[RobotaUA-Poster] Vacancy #{vacancy_id} posted as robota.ua ID {result['vacancy_id']}")
        else:
            db.add(HuntPosting(
                vacancy_id=vacancy_id,
                channel="robota.ua",
                status="failed",
                error_message=(result.get("error") or "")[:500],
            ))
            db.commit()
            await _tg(chat_id, thread_id, f"❌ Помилка публікації на Robota.ua:\n{result.get('error', 'Невідома помилка')}")

    except Exception as e:
        logger.error(f"[RobotaUA-Poster] run_vacancy_posting_robotaua error: {e}", exc_info=True)
        try:
            await _tg(chat_id, thread_id, f"❌ Помилка: {str(e)[:200]}")
        except Exception:
            pass
    finally:
        db.close()


async def _tg(chat_id: int, thread_id: int, text: str):
    """Send a Telegram message (fire-and-forget helper)."""
    bot_token = os.getenv("TELEGRAM_MAYA_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        return
    payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if thread_id:
        payload["message_thread_id"] = thread_id
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json=payload,
            )
    except Exception as e:
        logger.error(f"[RobotaUA-Poster] TG send error: {e}")
