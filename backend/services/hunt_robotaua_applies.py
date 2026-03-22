"""
Robota.ua Applications Scraper for Maya Hunt
=============================================
Fetches candidates who applied to AVTD's own vacancies on Robota.ua.
These are the highest-quality leads — they came to us.

Requires employer-level credentials (ROBOTAUA_EMAIL + ROBOTAUA_PASSWORD).
Returns [] gracefully on 401 (candidate-only token) or any error.
"""

import re
import asyncio
import logging
from typing import Optional

import httpx

from services.robotaua_auth import login_robotaua, invalidate_token

logger = logging.getLogger(__name__)

_EMPLOYER_API = "https://employer-api.robota.ua"


# ──────────────────────────────────────────────────────────────────
# Helpers (minimal — reuse logic from scraper)
# ──────────────────────────────────────────────────────────────────

def _parse_age_str(val) -> Optional[int]:
    s = str(val or "")
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def _parse_salary_str(s: str) -> Optional[int]:
    if not s:
        return None
    digits = re.sub(r"[^\d]", "", str(s))
    return int(digits) if digits else None


def _salary_to_uah_usd(uah: Optional[int]) -> tuple:
    if not uah:
        return None, None
    try:
        from services.salary_normalizer import get_usd_uah_rate
        rate = get_usd_uah_rate()
    except Exception:
        rate = 40.0
    return uah, int(uah / rate) if rate else None


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").strip()


def _build_raw_text(detail: dict, summary: str) -> str:
    parts = []
    role = (detail.get("speciality") or "").strip()
    city = (detail.get("cityName") or "").strip()
    age = str(detail.get("age") or "")
    salary = (detail.get("salaryFull") or detail.get("salary") or "").strip()

    if role:
        parts.append(f"Посада: {role}")
    if city:
        parts.append(f"Місто: {city}")
    if age:
        parts.append(f"Вік: {age}")
    if salary:
        parts.append(f"Зарплата: {salary}")
    if summary:
        parts.append(f"Резюме:\n{summary[:1000]}")

    skills_list = detail.get("skills") or []
    if skills_list:
        skills_text = _strip_html(" ".join(s.get("description", "") for s in skills_list))
        if skills_text:
            parts.append(f"Навички: {skills_text[:400]}")

    return "\n".join(parts)[:3000]


# ──────────────────────────────────────────────────────────────────
# Main public function
# ──────────────────────────────────────────────────────────────────

async def search_robotaua_applies(vacancy: dict, round_num: int = 1) -> list:
    """
    Fetch candidates who applied to AVTD vacancies on Robota.ua.
    Only runs on round_num == 1 to avoid duplicate processing.
    Returns [] gracefully on auth failure or any error.
    """
    if round_num != 1:
        return []

    token = await login_robotaua()
    if not token:
        return []

    position = vacancy.get("position", "").lower()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:

            # Step 1: Get AVTD's published vacancies
            vac_resp = await client.post(
                f"{_EMPLOYER_API}/vacancy/list",
                headers=headers,
                json={"vacancyStateId": "4", "page": 0},
            )
            if vac_resp.status_code == 401:
                logger.info("[RobotaUA-Applies] 401 on vacancy/list — employer auth required")
                invalidate_token()
                return []
            if vac_resp.status_code != 200:
                logger.warning(f"[RobotaUA-Applies] vacancy/list {vac_resp.status_code}")
                return []

            vac_data = vac_resp.json()
            # Response may be list directly or wrapped in a key
            if isinstance(vac_data, list):
                all_vacancies = vac_data
            else:
                all_vacancies = vac_data.get("vacancies") or vac_data.get("items") or []

            logger.info(f"[RobotaUA-Applies] {len(all_vacancies)} published AVTD vacancies")

            # Step 2: Match vacancies to our search position
            matching_ids = []
            for vac in all_vacancies:
                vac_name = (vac.get("name") or vac.get("title") or "").lower()
                if position and any(word in vac_name for word in position.split() if len(word) > 3):
                    vac_id = vac.get("id") or vac.get("vacancyId")
                    if vac_id:
                        matching_ids.append(vac_id)

            if not matching_ids:
                logger.info(f"[RobotaUA-Applies] No matching AVTD vacancies for '{position}'")
                return []

            logger.info(f"[RobotaUA-Applies] {len(matching_ids)} matching vacancy IDs: {matching_ids[:5]}")

            # Step 3: Get applications for each vacancy
            candidates = []
            for vac_id in matching_ids[:5]:
                apply_resp = await client.post(
                    f"{_EMPLOYER_API}/apply/list",
                    headers=headers,
                    json={
                        "vacancyId": vac_id,
                        "folderId": 0,
                        "page": 0,
                        "candidateTypes": ["ApplicationWithResume", "ApplicationWithFile"],
                    },
                )
                if apply_resp.status_code == 401:
                    invalidate_token()
                    break
                if apply_resp.status_code != 200:
                    logger.warning(f"[RobotaUA-Applies] apply/list {apply_resp.status_code} for vac {vac_id}")
                    continue

                apply_data = apply_resp.json()
                applications = apply_data if isinstance(apply_data, list) else (
                    apply_data.get("applies") or apply_data.get("items") or []
                )
                logger.info(f"[RobotaUA-Applies] {len(applications)} applicants for vac {vac_id}")

                for app in applications[:30]:
                    app_id = app.get("id") or app.get("applyId")
                    resume_type = app.get("resumeType") or "Notepad"

                    await asyncio.sleep(0.5)

                    # Get full application detail
                    detail_resp = await client.post(
                        f"{_EMPLOYER_API}/apply/view/{app_id}",
                        headers=headers,
                        params={"resumeType": resume_type},
                    )
                    if detail_resp.status_code == 401:
                        invalidate_token()
                        break
                    if detail_resp.status_code != 200:
                        continue

                    detail = detail_resp.json()

                    # Extract contact info
                    email = detail.get("email") or ""
                    phone = detail.get("phone") or ""
                    contact_parts = [p for p in [phone, email] if p]
                    contact = ", ".join(contact_parts) if contact_parts else "Деталі на Robota.ua"

                    # Name
                    name = (detail.get("name") or "").strip()
                    surname = (detail.get("surname") or "").strip()
                    full_name = f"{name} {surname}".strip() or (
                        app.get("fullName") or app.get("displayName") or ""
                    ).strip()

                    # Salary
                    salary_str = detail.get("salaryFull") or detail.get("salary") or ""
                    salary_uah = _parse_salary_str(salary_str)
                    salary_uah, salary_usd = _salary_to_uah_usd(salary_uah)

                    # Resume summary
                    summary = ""
                    resume_file = detail.get("resumeFile") or {}
                    if resume_file.get("summary"):
                        summary = _strip_html(resume_file["summary"])

                    resume_id = detail.get("resumeId") or app_id
                    profile_url = detail.get("url") or f"https://robota.ua/ua/cv/{resume_id}"

                    candidates.append({
                        "source": "robota.ua-applies",
                        "profile_url": profile_url,
                        "full_name": full_name,
                        "current_role": (detail.get("speciality") or "").strip(),
                        "age": _parse_age_str(detail.get("age")),
                        "city": (detail.get("cityName") or "").strip(),
                        "salary_expectation": salary_usd,
                        "salary_expectation_uah": salary_uah,
                        "salary_expectation_usd": salary_usd,
                        "contact": contact,
                        "email": email,
                        "experience_years": None,
                        "skills": "",
                        "education": "",
                        "raw_text": _build_raw_text(detail, summary),
                        "message_date": None,
                        "last_active": (detail.get("lastActivityDate") or "")[:10],
                    })

            logger.info(f"[RobotaUA-Applies] Total: {len(candidates)} applicants")
            return candidates

    except Exception as e:
        logger.error(f"[RobotaUA-Applies] Error: {e}")
        return []
