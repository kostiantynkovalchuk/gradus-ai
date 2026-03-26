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

Two-pass strategy (API rate-limit friendly):
  Pass 1 — list data only:  build raw_text from list fields → score with Claude
  Pass 2 — detail calls:    only for candidates scoring >= 35 (contacts needed)
  Hard cap: _DAILY_DETAIL_LIMIT calls per calendar day across all runs.
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

# ── Daily detail-call counter ────────────────────────────────────────────────
_DAILY_DETAIL_LIMIT = 100
_daily_detail_calls: int = 0
_daily_detail_date: str = ""          # "YYYY-MM-DD" of last reset

LIST_FETCH_LIMIT   = 10               # candidates to take from list
DETAIL_SCORE_FLOOR = 35               # min Claude score to trigger detail call
DETAIL_SLEEP_SEC   = 2.0              # seconds between detail calls


def _check_daily_limit() -> bool:
    """Return True if we can make another detail call today, False if capped."""
    global _daily_detail_calls, _daily_detail_date
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if today != _daily_detail_date:
        _daily_detail_calls = 0
        _daily_detail_date = today
    if _daily_detail_calls >= _DAILY_DETAIL_LIMIT:
        logger.warning(
            f"[RobotaUA] Daily detail-call limit reached ({_DAILY_DETAIL_LIMIT}/day). "
            "Skipping remaining detail fetches for today."
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
# Main public function
# ──────────────────────────────────────────────────────────────────

async def search_robotaua(vacancy: dict, depth_days: int = None) -> list:
    """
    Search Robota.ua CV database via REST API.

    Two-pass strategy:
      Pass 1: Build candidates from list data (no detail calls) → score with Claude
      Pass 2: Fetch /resume/{id} only for candidates scoring >= DETAIL_SCORE_FLOOR

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

            # ── List call ──────────────────────────────────────────────────
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

            # ── PASS 1: Build lightweight candidates from list data only ───
            pass1_candidates: list[dict] = []
            for doc in documents[:LIST_FETCH_LIMIT]:
                resume_id = doc.get("resumeId")
                if not resume_id:
                    continue

                last_activity_str = doc.get("lastActivityDate") or doc.get("addDate") or ""
                if last_activity_str:
                    last_dt = _parse_iso_date(last_activity_str)
                    if last_dt and last_dt < cutoff:
                        logger.debug(f"[RobotaUA] Skipping {resume_id} (inactive > {depth_days}d)")
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

                # Build raw_text from list fields — enough for Claude scoring
                raw_text = _build_raw_text(
                    full_name=display_name,
                    role=speciality,
                    city=city,
                    age_str=age_raw,
                    salary_str=salary_str_list,
                    experiences=experiences_list,
                    skills_html="",         # not available in list
                    keywords=keywords_list,
                )

                pass1_candidates.append({
                    "_resume_id": resume_id,            # internal, stripped before return
                    "_headers": headers,                # carry auth for pass 2
                    "source": "robota.ua",
                    "profile_url": profile_url,
                    "full_name": display_name,
                    "current_role": speciality,
                    "age": age,
                    "city": city,
                    "salary_expectation": salary_usd,
                    "salary_expectation_uah": salary_uah,
                    "salary_expectation_usd": salary_usd,
                    "contact": "Деталі на Robota.ua",   # populated in pass 2
                    "email": "",
                    "experience_years": exp_years,
                    "skills": "",
                    "education": "",
                    "raw_text": raw_text,
                    "message_date": None,
                    "last_active": last_active,
                })

            logger.info(
                f"[RobotaUA] Pass 1 complete: {len(pass1_candidates)} candidates built "
                f"from list data (no detail calls)"
            )

            if not pass1_candidates:
                return []

            # ── Score pass-1 candidates with Claude ───────────────────────
            from services.hunt_scorer import score_candidate as _score_candidate
            scored = await asyncio.gather(
                *[_score_candidate(c, vacancy) for c in pass1_candidates],
                return_exceptions=True,
            )

            # Pair candidates with their scores
            pass1_scored: list[tuple[dict, int]] = []
            for cand, result in zip(pass1_candidates, scored):
                if isinstance(result, Exception):
                    logger.warning(f"[RobotaUA] Scoring error for {cand['_resume_id']}: {result}")
                    score = 0
                else:
                    score = result.get("score", 0) if isinstance(result, dict) else 0
                pass1_scored.append((cand, score))
                logger.debug(
                    f"[RobotaUA] Pass-1 score {cand['_resume_id']}: {score}"
                )

            # Sort by score descending for logging clarity
            pass1_scored.sort(key=lambda x: x[1], reverse=True)
            qualify = [(c, s) for c, s in pass1_scored if s >= DETAIL_SCORE_FLOOR]
            logger.info(
                f"[RobotaUA] Pass-1 scoring: {len(qualify)}/{len(pass1_scored)} "
                f"candidates qualify (score >= {DETAIL_SCORE_FLOOR})"
            )

            # ── PASS 2: Fetch full details only for qualifying candidates ──
            final_candidates: list[dict] = []
            for cand, score in pass1_scored:
                resume_id = cand["_resume_id"]
                cand_headers = cand.pop("_headers")
                cand.pop("_resume_id", None)

                if score >= DETAIL_SCORE_FLOOR:
                    if not _check_daily_limit():
                        # Over daily limit — keep list-data version, no contacts
                        final_candidates.append(cand)
                        continue

                    await asyncio.sleep(DETAIL_SLEEP_SEC)
                    try:
                        detail_resp = await client.get(
                            f"{_EMPLOYER_API}/resume/{resume_id}",
                            headers=cand_headers,
                        )
                        _increment_daily_counter()

                        if detail_resp.status_code == 200:
                            detail = detail_resp.json()
                            name = (detail.get("name") or "").strip()
                            surname = (detail.get("surname") or "").strip()
                            if name or surname:
                                cand["full_name"] = f"{name} {surname}".strip()
                            age_detail = _parse_age_str(detail.get("age"))
                            if age_detail:
                                cand["age"] = age_detail
                            email = detail.get("email") or ""
                            phone = detail.get("phone") or ""
                            skills_list = detail.get("skills") or []
                            skills_html = " ".join(
                                s.get("description", "") for s in skills_list
                            )
                            if skills_html:
                                cand["skills"] = _strip_html(skills_html)[:300]
                            detail_salary_str = (
                                detail.get("salaryFull") or detail.get("salary") or ""
                            )
                            if detail_salary_str and not cand["salary_expectation_uah"]:
                                sal_uah = _parse_salary_str(detail_salary_str)
                                sal_uah, sal_usd = _salary_to_uah_usd(sal_uah)
                                cand["salary_expectation"] = sal_usd
                                cand["salary_expectation_uah"] = sal_uah
                                cand["salary_expectation_usd"] = sal_usd
                            # Update raw_text with skills from detail
                            if skills_html:
                                cand["raw_text"] = _build_raw_text(
                                    full_name=cand["full_name"],
                                    role=cand["current_role"],
                                    city=cand["city"],
                                    age_str=str(cand.get("age") or ""),
                                    salary_str=detail_salary_str or cand.get("salary_expectation_uah") or "",
                                    experiences=[],     # already in raw_text from pass 1
                                    skills_html=skills_html,
                                    keywords=[],
                                )
                            contact_parts = []
                            if phone:
                                contact_parts.append(phone)
                            if email:
                                contact_parts.append(email)
                            cand["contact"] = (
                                ", ".join(contact_parts) if contact_parts else "Деталі на Robota.ua"
                            )
                            cand["email"] = email
                            logger.info(
                                f"[RobotaUA] Detail fetched for {resume_id} "
                                f"(score={score}, contact={'yes' if contact_parts else 'no'})"
                            )
                        elif detail_resp.status_code == 401:
                            invalidate_token()
                            logger.warning("[RobotaUA] 401 on detail call — stopping pass 2")
                            final_candidates.append(cand)
                            break
                        else:
                            logger.warning(
                                f"[RobotaUA] Detail call failed for {resume_id}: "
                                f"{detail_resp.status_code}"
                            )
                    except Exception as detail_err:
                        logger.warning(
                            f"[RobotaUA] Detail call error for {resume_id}: {detail_err}"
                        )
                else:
                    # Below threshold — strip internal keys, keep list data only
                    cand.pop("_resume_id", None)
                    cand.pop("_headers", None)

                final_candidates.append(cand)

            # Clean up any remaining internal keys (safety)
            for c in final_candidates:
                c.pop("_resume_id", None)
                c.pop("_headers", None)

            logger.info(
                f"[RobotaUA] CV search complete: {len(final_candidates)} candidates "
                f"(detail calls today: {_daily_detail_calls}/{_DAILY_DETAIL_LIMIT})"
            )
            return final_candidates

    except Exception as e:
        logger.error(f"[RobotaUA] CV search error: {e}")
        return []
