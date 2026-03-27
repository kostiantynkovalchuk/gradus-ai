"""
Robota.ua Applications Scraper for Maya Hunt
=============================================
Fetches candidates who applied to AVTD's own vacancies on Robota.ua.
These are the highest-quality leads — they came to us.

Requires employer-level credentials (ROBOTAUA_EMAIL + ROBOTAUA_PASSWORD).
Returns [] gracefully on 401 (candidate-only token) or any error.

No detail calls — contacts are extracted directly from /apply/list response.
  contacts.phones[].value  →  phone
  contacts.emails[].value  →  email  (skip phone-registration.rabota.ua addresses)
"""

import re
import logging
from typing import Optional

from services.robotaua_auth import login_robotaua, invalidate_token
from services.robotaua_client import cf_client

logger = logging.getLogger(__name__)

_EMPLOYER_API = "https://employer-api.robota.ua"


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

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


def _build_raw_text(full_name: str, speciality: str, skills: str, phone: str, email: str) -> str:
    parts = []
    if full_name:
        parts.append(f"Ім'я: {full_name}")
    if speciality:
        parts.append(f"Посада: {speciality}")
    if skills:
        parts.append(f"Навички: {skills[:400]}")
    if phone:
        parts.append(f"Телефон: {phone}")
    if email:
        parts.append(f"Email: {email}")
    return "\n".join(parts)[:3000]


# ──────────────────────────────────────────────────────────────────
# Main public function
# ──────────────────────────────────────────────────────────────────

async def search_robotaua_applies(vacancy: dict, round_num: int = 1) -> list:
    """
    Fetch candidates who applied to AVTD vacancies on Robota.ua.
    Only runs on round_num == 1 to avoid duplicate processing.

    Two-step process (zero detail calls):
      1. POST /vacancy/list  → find vacancies matching the search position
      2. POST /apply/list    → get all applicants; extract contacts from list response

    Returns [] gracefully on auth failure or any error.
    """
    logger.info(
        f"[RobotaUA-Applies] Search started: position='{vacancy.get('position')}', "
        f"round={round_num}"
    )

    if round_num != 1:
        logger.info("[RobotaUA-Applies] Skipping — only runs on round 1")
        return []

    token = await login_robotaua()
    if not token:
        logger.info("[RobotaUA-Applies] Complete: 0 candidates (no token)")
        return []

    position = vacancy.get("position", "").lower()
    # Significant words (> 3 chars) for fuzzy vacancy matching
    position_words = [w for w in position.split() if len(w) > 3]

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        async with cf_client(timeout=30) as client:

            # ── Step 1: Get AVTD's published vacancies ─────────────────────
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
            if isinstance(vac_data, list):
                all_vacancies = vac_data
            else:
                all_vacancies = (
                    vac_data.get("vacancies")
                    or vac_data.get("items")
                    or []
                )

            logger.info(f"[RobotaUA-Applies] {len(all_vacancies)} published AVTD vacancies")

            # ── Step 2: Fuzzy-match vacancies to search position ───────────
            # Field names confirmed from production: "vacancyName", "vacancyId"
            matching_ids = []
            for vac in all_vacancies:
                vac_name = (
                    vac.get("vacancyName")        # confirmed field name
                    or vac.get("name")
                    or vac.get("title")
                    or ""
                ).lower()
                vac_id = vac.get("vacancyId") or vac.get("id")  # confirmed field name
                if not vac_id:
                    continue
                # Match if at least one significant word from position appears in vacancy name
                if not position_words or any(word in vac_name for word in position_words):
                    matching_ids.append(vac_id)
                    logger.info(
                        f"[RobotaUA-Applies] Matched vacancy: '{vac_name}' (id={vac_id})"
                    )

            if not matching_ids:
                logger.info(
                    f"[RobotaUA-Applies] No matching AVTD vacancies for '{position}'"
                )
                return []

            logger.info(
                f"[RobotaUA-Applies] {len(matching_ids)} matching vacancy IDs: "
                f"{matching_ids[:5]}"
            )

            # ── Step 3: Fetch applicants from list (no detail calls) ───────
            candidates = []
            for vac_id in matching_ids[:5]:
                apply_resp = await client.post(
                    f"{_EMPLOYER_API}/apply/list",
                    headers=headers,
                    json={
                        "vacancyId": vac_id,
                        "folderId": 0,
                        "page": 0,
                        # Include all real application types; exclude Interaction (views)
                        "candidateTypes": [
                            "ApplicationWithResume",
                            "ApplicationWithFile",
                            "Application",
                        ],
                    },
                )
                if apply_resp.status_code == 401:
                    invalidate_token()
                    break
                if apply_resp.status_code != 200:
                    logger.warning(
                        f"[RobotaUA-Applies] apply/list {apply_resp.status_code} "
                        f"for vac {vac_id}"
                    )
                    continue

                apply_data = apply_resp.json()
                # Confirmed response key: "applies"
                applications = apply_data if isinstance(apply_data, list) else (
                    apply_data.get("applies")
                    or apply_data.get("items")
                    or []
                )
                logger.info(
                    f"[RobotaUA-Applies] {len(applications)} applicants for vac {vac_id}"
                )

                for apply in applications[:30]:

                    # ── Extract phone from contacts ────────────────────────
                    phone = ""
                    phones = (apply.get("contacts") or {}).get("phones") or []
                    if phones:
                        phone = phones[0].get("value", "").strip()

                    # ── Extract email from contacts ────────────────────────
                    email = ""
                    emails = (apply.get("contacts") or {}).get("emails") or []
                    if emails:
                        email = emails[0].get("value", "").strip()
                        # Skip auto-generated phone-registration addresses
                        if "phone-registration.rabota.ua" in email:
                            email = ""

                    full_name = (apply.get("name") or "").strip()
                    speciality = (apply.get("speciality") or "").strip()
                    skills = (apply.get("skillsSummary") or "").strip()

                    # ── Salary ─────────────────────────────────────────────
                    salary_raw = apply.get("salary")
                    salary_uah = None
                    salary_usd = None
                    if salary_raw:
                        currency_id = apply.get("currencyId", "")
                        if currency_id == "Ua":
                            salary_uah = int(salary_raw)
                            salary_uah, salary_usd = _salary_to_uah_usd(salary_uah)
                        elif currency_id == "Usd":
                            salary_usd = int(salary_raw)
                        else:
                            salary_uah = _parse_salary_str(str(salary_raw))
                            salary_uah, salary_usd = _salary_to_uah_usd(salary_uah)

                    resume_id = apply.get("resumeId") or apply.get("id")
                    profile_url = f"https://robota.ua/ua/cv/{resume_id}"
                    contact = phone or email or "Деталі на Robota.ua"

                    candidates.append({
                        "source": "robota.ua-applies",
                        "profile_url": profile_url,
                        "full_name": full_name,
                        "current_role": speciality,
                        "age": None,
                        "city": "",
                        "salary_expectation": salary_usd,
                        "salary_expectation_uah": salary_uah,
                        "salary_expectation_usd": salary_usd,
                        "contact": contact,
                        "phone": phone,
                        "email": email,
                        "experience_years": None,
                        "skills": skills[:300] if skills else "",
                        "education": "",
                        "raw_text": _build_raw_text(full_name, speciality, skills, phone, email),
                        "message_date": apply.get("addDate"),
                        "last_active": None,
                    })

            logger.info(f"[RobotaUA-Applies] Total: {len(candidates)} applicants")
            return candidates

    except Exception as e:
        logger.error(f"[RobotaUA-Applies] Error: {e}", exc_info=True)
        return []
