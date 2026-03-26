"""
Robota.ua REST API CV Scraper for Maya Hunt
============================================
Uses the official employer REST API (employer-api.robota.ua).

Confirmed field names from live API exploration (2026-03-22):
  POST /cvdb/resumes response document:
    resumeId, speciality, fullName, displayName, salary (str "20 000 грн."),
    age (str "51 рік"), cityName, experience[]{beginWork, finishWork, position, company},
    url, lastActivityDate, keywords, cityId

  GET /resume/{id} response:
    resumeId, name, surname, birthDate, age (str "51"), email, phone, skype,
    speciality, salary (str "20000"), currencyId, currencySign, salaryFull,
    skills[]{description (HTML)}, lastActivityDate, updateDate

Search strategy (Pass 1 only — no automatic detail calls):
  - Fetch list via POST /cvdb/resumes, take top LIST_FETCH_LIMIT candidates.
  - Build raw_text from list fields (name, speciality, city, salary, experience, keywords).
  - Return candidates without contact info; contact is fetched on-demand via
    fetch_robotaua_contact() when HR clicks the "📞 Контакт" button.

Contact fetch (on-demand via button):
  - Daily cap: _DAILY_DETAIL_LIMIT calls per UTC calendar day.
  - Sleep DETAIL_SLEEP_SEC between successive calls in the same request.
"""

import re
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from services.robotaua_auth import login_robotaua, invalidate_token
from services.robotaua_client import cf_client
from services.robotaua_reference import get_city_id

logger = logging.getLogger(__name__)

_EMPLOYER_API = "https://employer-api.robota.ua"

LIST_FETCH_LIMIT  = 20       # candidates taken from list response
DETAIL_SLEEP_SEC  = 2.0      # seconds to sleep before a detail call

# ── Daily detail-call counter ────────────────────────────────────────────────
_DAILY_DETAIL_LIMIT = 100
_daily_detail_calls: int = 0
_daily_detail_date:  str = ""    # "YYYY-MM-DD" of last reset


def _check_daily_limit() -> bool:
    """Return True if a detail call is allowed today, False if capped."""
    global _daily_detail_calls, _daily_detail_date
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if today != _daily_detail_date:
        _daily_detail_calls = 0
        _daily_detail_date = today
    if _daily_detail_calls >= _DAILY_DETAIL_LIMIT:
        logger.warning(
            f"[RobotaUA] Daily detail-call limit reached ({_DAILY_DETAIL_LIMIT}/day)."
        )
        return False
    return True


def _increment_daily_counter():
    global _daily_detail_calls
    _daily_detail_calls += 1
    remaining = _DAILY_DETAIL_LIMIT - _daily_detail_calls
    if remaining <= 20:
        logger.warning(
            f"[RobotaUA] Approaching daily limit: {_daily_detail_calls}/{_DAILY_DETAIL_LIMIT} "
            f"detail calls used ({remaining} remaining)."
        )


# ──────────────────────────────────────────────────────────────────
# Parsing helpers
# ──────────────────────────────────────────────────────────────────

def _parse_age_str(age_val) -> Optional[int]:
    """Parse age from either "51 рік" (list) or "51" (detail)."""
    if age_val is None:
        return None
    s = str(age_val)
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def _parse_iso_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=None)
    except ValueError:
        pass
    try:
        return datetime.strptime(s[:7], "%Y-%m")
    except ValueError:
        pass
    return None


def _parse_experience_years(experiences: list) -> Optional[float]:
    """Sum total months from beginWork/finishWork fields."""
    if not experiences:
        return None
    total_months = 0
    for exp in experiences:
        try:
            start_str = exp.get("beginWork") or exp.get("startDate") or ""
            end_str = exp.get("finishWork") or exp.get("endDate") or ""
            is_current = not end_str or "0001-01-01" in end_str

            start_dt = _parse_iso_date(start_str)
            end_dt = _parse_iso_date(end_str) if not is_current else datetime.utcnow()

            if start_dt and end_dt and end_dt >= start_dt:
                diff = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
                total_months += max(0, diff)
        except Exception:
            pass
    if total_months == 0:
        return None
    return round(total_months / 12, 1)


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").strip()


def _parse_salary_str(salary_str: str) -> Optional[int]:
    """Parse salary string like '20 000 грн.' → 20000."""
    if not salary_str:
        return None
    digits = re.sub(r"[^\d]", "", salary_str)
    return int(digits) if digits else None


def _salary_to_uah_usd(amount_uah: Optional[int]) -> tuple:
    """Convert UAH salary to (uah, usd)."""
    if not amount_uah:
        return None, None
    try:
        from services.salary_normalizer import get_usd_uah_rate
        rate = get_usd_uah_rate()
    except Exception:
        rate = 40.0
    usd = int(amount_uah / rate) if rate else None
    return amount_uah, usd


def _build_raw_text(
    full_name: str,
    role: str,
    city: str,
    age_str: str,
    salary_str: str,
    experiences: list,
    skills_html: str,
    keywords: list,
) -> str:
    parts = []
    if full_name:
        parts.append(f"Ім'я: {full_name}")
    if role:
        parts.append(f"Посада: {role}")
    if city:
        parts.append(f"Місто: {city}")
    if age_str:
        parts.append(f"Вік: {age_str}")
    if salary_str:
        parts.append(f"Зарплата: {salary_str}")
    if experiences:
        parts.append("Досвід:")
        for exp in experiences[:6]:
            pos = exp.get("position") or ""
            company = exp.get("company") or ""
            start = (exp.get("beginWork") or exp.get("startDate") or "")[:7]
            end_raw = exp.get("finishWork") or exp.get("endDate") or ""
            is_current = not end_raw or "0001-01-01" in end_raw
            end = "по сьогодні" if is_current else end_raw[:7]
            parts.append(f"  - {pos} @ {company} ({start} – {end})")
    if skills_html:
        skills_plain = _strip_html(skills_html)[:500]
        if skills_plain:
            parts.append(f"Навички: {skills_plain}")
    if keywords:
        parts.append(f"Ключові слова: {', '.join(keywords[:20])}")
    return "\n".join(parts)[:3000]


# ──────────────────────────────────────────────────────────────────
# On-demand contact fetch (triggered by HR button click)
# ──────────────────────────────────────────────────────────────────

async def fetch_robotaua_contact(resume_id: str) -> dict:
    """
    Fetch contact details for a single Robota.ua resume.
    Called only when HR explicitly clicks "📞 Контакт" — never during search.

    Returns dict with keys: phone, email, full_name, skills_text, error (if any).
    """
    if not _check_daily_limit():
        return {"error": f"Досягнуто денний ліміт запитів ({_DAILY_DETAIL_LIMIT}/день). Спробуйте завтра."}

    token = await login_robotaua()
    if not token:
        return {"error": "Не вдалося авторизуватися на Robota.ua"}

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        await asyncio.sleep(DETAIL_SLEEP_SEC)
        async with cf_client(timeout=20) as client:
            resp = await client.get(f"{_EMPLOYER_API}/resume/{resume_id}", headers=headers)
            _increment_daily_counter()

            if resp.status_code == 401:
                invalidate_token()
                return {"error": "Авторизація Robota.ua вичерпалась. Спробуйте ще раз."}
            if resp.status_code == 403:
                return {"error": "Доступ заборонено (403). Перевищено ліміт Robota.ua."}
            if resp.status_code == 404:
                return {"error": "Резюме не знайдено (можливо видалено кандидатом)."}
            if resp.status_code != 200:
                return {"error": f"Помилка Robota.ua API: HTTP {resp.status_code}"}

            detail = resp.json()
            name = (detail.get("name") or "").strip()
            surname = (detail.get("surname") or "").strip()
            full_name = f"{name} {surname}".strip() if (name or surname) else ""
            phone = detail.get("phone") or ""
            email = detail.get("email") or ""
            skills_list = detail.get("skills") or []
            skills_html = " ".join(s.get("description", "") for s in skills_list)
            skills_text = _strip_html(skills_html)[:400] if skills_html else ""

            logger.info(
                f"[RobotaUA] Contact fetched for resume {resume_id} "
                f"(phone={'yes' if phone else 'no'}, email={'yes' if email else 'no'}, "
                f"calls today: {_daily_detail_calls}/{_DAILY_DETAIL_LIMIT})"
            )
            return {
                "phone": phone,
                "email": email,
                "full_name": full_name,
                "skills_text": skills_text,
                "error": None,
            }

    except Exception as e:
        logger.error(f"[RobotaUA] fetch_robotaua_contact({resume_id}) error: {e}")
        return {"error": f"Технічна помилка: {str(e)[:120]}"}


# ──────────────────────────────────────────────────────────────────
# Main public function
# ──────────────────────────────────────────────────────────────────

async def search_robotaua(vacancy: dict, depth_days: int = None) -> list:
    """
    Search Robota.ua CV database via REST API.

    Pass 1 only — list data, no detail calls:
      Build candidates from list fields (name, speciality, city, salary, experience,
      keywords). Contact is NOT fetched here; HR requests it via the Контакт button.

    Returns a list of candidate dicts compatible with the Hunt scorer.
    Returns [] on any auth/network error — never raises.
    """
    logger.info(
        f"[RobotaUA] CV search started: position='{vacancy.get('position')}', "
        f"city='{vacancy.get('city')}'"
    )

    from config.hunt_config import HUNT_CONFIG
    if depth_days is None:
        depth_days = HUNT_CONFIG["search_depth_days"]

    token = await login_robotaua()
    if not token:
        logger.info("[RobotaUA] CV search complete: 0 candidates (no token)")
        return []

    position = vacancy.get("position", "")
    if not position:
        logger.info("[RobotaUA] CV search complete: 0 candidates (no position)")
        return []

    city_name = vacancy.get("city", "")
    city_id = await get_city_id(city_name)
    if city_id:
        logger.info(f"[RobotaUA] City '{city_name}' → id={city_id}")
    else:
        logger.info(f"[RobotaUA] City '{city_name}' not found — searching Ukraine-wide")

    search_body: dict = {"keyWords": position, "page": 0}
    if city_id:
        search_body["cityId"] = city_id

    logger.info(
        f"[RobotaUA] Search: position='{position}' cityId={city_id} depth={depth_days}d"
    )
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        async with cf_client(timeout=30) as client:

            resp = await client.post(
                f"{_EMPLOYER_API}/cvdb/resumes", headers=headers, json=search_body
            )

            if resp.status_code == 401:
                logger.warning("[RobotaUA] 401 on CV search — invalidating token")
                invalidate_token()
                return []
            if resp.status_code != 200:
                logger.error(
                    f"[RobotaUA] CV search failed: {resp.status_code} {resp.text[:200]}"
                )
                return []

            data = resp.json()
            documents = data.get("documents", [])
            total = data.get("total", 0)
            logger.info(
                f"[RobotaUA] {len(documents)}/{total} CVs returned for '{position}'"
            )
            if not documents:
                return []

            cutoff = datetime.utcnow() - timedelta(days=depth_days)
            candidates = []

            # ── Pass 1: list data only — no detail calls ───────────────
            for doc in documents[:LIST_FETCH_LIMIT]:
                resume_id = doc.get("resumeId")
                if not resume_id:
                    continue

                last_activity_str = doc.get("lastActivityDate") or doc.get("addDate") or ""
                if last_activity_str:
                    last_dt = _parse_iso_date(last_activity_str)
                    if last_dt and last_dt < cutoff:
                        logger.debug(
                            f"[RobotaUA] Skipping {resume_id} (inactive > {depth_days}d)"
                        )
                        continue

                profile_url = doc.get("url") or f"https://robota.ua/ua/cv/{resume_id}"
                speciality = doc.get("speciality") or ""
                display_name = (doc.get("fullName") or doc.get("displayName") or "").strip()
                age_raw = doc.get("age") or ""
                city = doc.get("cityName") or city_name
                salary_str_list = doc.get("salary") or ""
                experiences_list = doc.get("experience") or []
                keywords_list = doc.get("keywords") or []
                last_active = last_activity_str[:10] if last_activity_str else ""

                salary_uah = _parse_salary_str(salary_str_list)
                salary_uah, salary_usd = _salary_to_uah_usd(salary_uah)
                exp_years = _parse_experience_years(experiences_list)
                age = _parse_age_str(age_raw)

                raw_text = _build_raw_text(
                    full_name=display_name,
                    role=speciality,
                    city=city,
                    age_str=age_raw,
                    salary_str=salary_str_list,
                    experiences=experiences_list,
                    skills_html="",
                    keywords=keywords_list,
                )

                candidates.append({
                    "source": "robota.ua",
                    "profile_url": profile_url,
                    "full_name": display_name,
                    "current_role": speciality,
                    "age": age,
                    "city": city,
                    "salary_expectation": salary_usd,
                    "salary_expectation_uah": salary_uah,
                    "salary_expectation_usd": salary_usd,
                    "contact": "Деталі на Robota.ua",
                    "email": "",
                    "experience_years": exp_years,
                    "skills": "",
                    "education": "",
                    "raw_text": raw_text,
                    "message_date": None,
                    "last_active": last_active,
                })

            logger.info(
                f"[RobotaUA] CV search complete: {len(candidates)} candidates "
                f"(list-only, 0 detail calls)"
            )
            return candidates

    except Exception as e:
        logger.error(f"[RobotaUA] CV search error: {e}")
        return []
