"""
Robota.ua GraphQL CV Scraper for Maya Hunt
==========================================
Searches Robota.ua's CV database via the confirmed dracula.robota.ua GraphQL API.

Requires: ROBOTAUA_JWT environment variable (Bearer token from employer.robota.ua).
If JWT is missing or expired, all functions return [] gracefully.

Key API facts (confirmed from live introspection):
  - Endpoint: https://dracula.robota.ua/
  - recommendedProfResumes → AI-matched CVs by vacancy title/city/description
  - employerResume(id) → full CV with contacts (may be hidden without CVDB sub)
  - cvdbRegions → { cvdbRegions { cities { id name } } }
  - employerResume returns a union type; check __typename == "EmployerResume"
"""

import os
import re
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://dracula.robota.ua/"
PROFILE_URL_TEMPLATE = "https://robota.ua/candidates/{resume_id}"

# Module-level city cache: city_name_lower → str(city_id)
# Populated lazily on first call to search_robotaua.
_city_cache: dict = {}
_city_cache_loaded: bool = False

# City name alias table: variant → canonical key present in _city_cache
CITY_ALIASES = {
    "kyiv":             "київ",
    "kiev":             "київ",
    "киев":             "київ",
    "dnipro":           "дніпро",
    "dnipropetrovsk":   "дніпро",
    "дніпропетровськ":  "дніпро",
    "dnepropetrovsk":   "дніпро",
    "днепр":            "дніпро",
    "kharkiv":          "харків",
    "kharkov":          "харків",
    "харьков":          "харків",
    "odesa":            "одеса",
    "odessa":           "одеса",
    "одесса":           "одеса",
    "lviv":             "львів",
    "lvov":             "львів",
    "львов":            "львів",
    "zaporizhzhia":     "запоріжжя",
    "zaporizhja":       "запоріжжя",
    "запорожье":        "запоріжжя",
    "vinnytsia":        "вінниця",
    "vinnitsa":         "вінниця",
    "вінниця":          "вінниця",
    "вінниці":          "вінниця",
    "poltava":          "полтава",
    "mykolaiv":         "миколаїв",
    "nikolaev":         "миколаїв",
    "mykolaiv":         "миколаїв",
    "kherson":          "херсон",
    "cherkasy":         "черкаси",
    "sumy":             "суми",
    "zhytomyr":         "житомир",
    "rivne":            "рівне",
    "рівне":            "рівне",
    "ternopil":         "тернопіль",
    "тернопіль":        "тернопіль",
    "khmelnytskyi":     "хмельницький",
    "хмельницький":     "хмельницький",
    "ivano-frankivsk":  "івано-франківськ",
    "івано-франківськ": "івано-франківськ",
    "kropyvnytskyi":    "кропивницький",
    "кропивницький":    "кропивницький",
    "uzhhorod":         "ужгород",
    "ужгород":          "ужгород",
    "lutsk":            "луцьк",
    "луцьк":            "луцьк",
    "chernihiv":        "чернігів",
    "чернігів":         "чернігів",
    "chernivtsi":       "чернівці",
    "чернівці":         "чернівці",
}

# ──────────────────────────────────────────────────────────────────
# Headers / auth
# ──────────────────────────────────────────────────────────────────

def _get_jwt() -> str:
    return os.getenv("ROBOTAUA_JWT", "")


def _check_jwt_expiry(token: str) -> bool:
    """Return True if token is valid (not expired), False otherwise. Logs warning."""
    if not token:
        return False
    try:
        import base64, json as _json
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        decoded = _json.loads(base64.b64decode(payload_b64))
        exp = decoded.get("exp", 0)
        if exp and exp < time.time():
            logger.warning(
                f"Robota.ua JWT is EXPIRED (exp={exp}). "
                "Update ROBOTAUA_JWT env secret to re-enable this source."
            )
            return False
    except Exception:
        pass
    return True


def _build_headers(token: str) -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "uk",
        "apollographql-client-name": "web-alliance-desktop",
        "apollographql-client-version": "071f324",
        "Content-Type": "application/json",
        "Origin": "https://employer.robota.ua",
        "Referer": "https://employer.robota.ua/",
        "Authorization": f"Bearer {token}",
        "x-alliance-locale": "uk_UA",
    }


# ──────────────────────────────────────────────────────────────────
# GraphQL queries (confirmed from live API introspection)
# ──────────────────────────────────────────────────────────────────

_REGIONS_QUERY = """
query cvdbRegions {
  cvdbRegions {
    cities { id name }
  }
}
"""

_RECOMMENDED_QUERY = """
query recommendedProfResumesQuery(
    $input: RecommendedProfResumesInput!
    $first: Int
) {
  recommendedProfResumes(input: $input, first: $first) {
    total
    recommendedProfResumeList {
      id
      displayName
      speciality
      age
      gender
      lastActivityDate
      updateDate
      city { id name }
      resumeSalary { amount currency }
      experience {
        company
        position
        startDate
        endDate
        isCurrent
      }
    }
  }
}
"""

_EMPLOYER_RESUME_QUERY = """
query employerResumeQuery($id: ID!) {
  employerResume(id: $id) {
    __typename
    ... on EmployerResume {
      id
      title
      isAnonymous
      skills
      addedAt
      updatedAt
      isActivelySearchingForNewJob
      city { id name }
      salary { amount currency }
      personal {
        firstName
        lastName
        birthDate
      }
      contacts {
        phones { phone }
        email { email }
        socialNetworks { type url }
      }
      experiences {
        company
        position
        startDate
        endDate
        isCurrent
        description
      }
      educations {
        name
        type
        yearStart
        yearEnd
      }
      languageSkills {
        language { name }
        level { name }
      }
    }
    ... on NotFoundEmployerResumeError {
      message
    }
    ... on ServerError {
      message
    }
  }
}
"""


# ──────────────────────────────────────────────────────────────────
# HTTP helper
# ──────────────────────────────────────────────────────────────────

async def _gql(
    query: str,
    variables: dict,
    operation: str,
    token: str,
    timeout: float = 15.0,
) -> dict:
    payload = {
        "query": query,
        "variables": variables,
        "operationName": operation,
    }
    url = f"{GRAPHQL_URL}?q={operation}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=_build_headers(token))
            resp.raise_for_status()
            data = resp.json()

        errors = data.get("errors", [])
        if errors:
            first_err = errors[0].get("message", "")
            if any(w in first_err for w in ("Unauthorized", "401", "Forbidden", "jwt", "token")):
                logger.warning(f"Robota.ua auth error: {first_err}")
            else:
                logger.warning(f"Robota.ua GQL error ({operation}): {first_err[:150]}")

        return data
    except httpx.TimeoutException:
        logger.warning(f"Robota.ua request timed out ({operation})")
        return {}
    except Exception as e:
        logger.error(f"Robota.ua request failed ({operation}): {e}")
        return {}


# ──────────────────────────────────────────────────────────────────
# City cache
# ──────────────────────────────────────────────────────────────────

async def _ensure_city_cache(token: str) -> None:
    global _city_cache, _city_cache_loaded
    if _city_cache_loaded:
        return

    result = await _gql(_REGIONS_QUERY, {}, "cvdbRegions", token)
    cities = (
        result
        .get("data", {})
        .get("cvdbRegions", {})
        .get("cities", [])
    )
    for city in cities:
        name_lower = city["name"].lower()
        _city_cache[name_lower] = str(city["id"])
    _city_cache_loaded = True
    logger.info(f"Robota.ua city cache loaded: {len(_city_cache)} cities")


def _resolve_city_id(city_name: str) -> Optional[str]:
    """Return str city ID or None if the city isn't found."""
    if not city_name:
        return None
    name = city_name.lower().strip()

    # Direct match
    if name in _city_cache:
        return _city_cache[name]

    # Alias lookup
    canonical = CITY_ALIASES.get(name)
    if canonical and canonical in _city_cache:
        return _city_cache[canonical]

    # Partial match (e.g. "дніпро" inside "дніпро (дніпропетровськ)")
    for cached_name, cached_id in _city_cache.items():
        if name in cached_name or cached_name in name:
            return cached_id

    return None


# ──────────────────────────────────────────────────────────────────
# Helpers: parsing fields into scorer-ready format
# ──────────────────────────────────────────────────────────────────

def _parse_experience_years(experiences: list) -> Optional[float]:
    """Sum total months across all non-current+past positions, return years."""
    if not experiences:
        return None
    total_months = 0
    for exp in experiences:
        try:
            start_str = exp.get("startDate") or ""
            end_str = exp.get("endDate") or ""
            is_current = exp.get("isCurrent", False)

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


def _parse_iso_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(s[:len(fmt)], fmt)
        except Exception:
            pass
    return None


def _parse_age(birth_date: str) -> Optional[int]:
    dt = _parse_iso_date(birth_date)
    if not dt:
        return None
    today = datetime.utcnow()
    return today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))


def _salary_to_usd_uah(amount: Optional[int], currency: str) -> tuple:
    """Return (salary_uah, salary_usd) as ints or None."""
    if not amount:
        return None, None
    try:
        from services.salary_normalizer import get_usd_uah_rate
        rate = get_usd_uah_rate()
    except Exception:
        rate = 40.0

    currency_upper = (currency or "").upper()
    if currency_upper in ("UAH", "ГРН", ""):
        uah = int(amount)
        usd = int(amount / rate) if rate else None
    elif currency_upper in ("USD", "US", "$"):
        usd = int(amount)
        uah = int(amount * rate) if rate else None
    else:
        uah, usd = int(amount), None
    return uah, usd


def _build_raw_text(
    role: str,
    city: str,
    experiences: list,
    skills: str,
    education_lines: list,
    salary_str: str,
    languages: list,
) -> str:
    parts = []
    if role:
        parts.append(f"Посада: {role}")
    if city:
        parts.append(f"Місто: {city}")
    if salary_str:
        parts.append(f"Зарплата: {salary_str}")
    if experiences:
        parts.append("Досвід:")
        for exp in experiences[:8]:
            pos = exp.get("position") or ""
            company = exp.get("company") or ""
            start = (exp.get("startDate") or "")[:7]
            end = "по сьогодні" if exp.get("isCurrent") else (exp.get("endDate") or "")[:7]
            desc = exp.get("description") or ""
            line = f"  - {pos} @ {company} ({start} – {end})"
            if desc:
                line += f": {desc[:100]}"
            parts.append(line)
    if skills:
        parts.append(f"Навички: {skills}")
    if education_lines:
        parts.append("Освіта:")
        for e in education_lines[:3]:
            parts.append(f"  - {e}")
    if languages:
        parts.append(f"Мови: {', '.join(languages)}")
    return "\n".join(parts)[:3000]


# ──────────────────────────────────────────────────────────────────
# Main public function
# ──────────────────────────────────────────────────────────────────

async def search_robotaua(vacancy: dict, depth_days: int = None) -> list:
    """
    Search Robota.ua for candidates matching a vacancy dict.

    Returns a list of candidate dicts compatible with the Hunt scorer.
    Returns [] on any auth/network error — never raises.

    vacancy dict keys used: position, city, keywords, requirements
    depth_days: only return candidates active within this many days
    """
    from config.hunt_config import HUNT_CONFIG

    if depth_days is None:
        depth_days = HUNT_CONFIG["search_depth_days"]

    token = _get_jwt()
    if not token:
        logger.info("Robota.ua: ROBOTAUA_JWT not set — skipping source")
        return []

    if not _check_jwt_expiry(token):
        return []

    position = vacancy.get("position", "")
    if not position:
        logger.info("Robota.ua: no position in vacancy, skipping")
        return []

    try:
        await _ensure_city_cache(token)
    except Exception as e:
        logger.warning(f"Robota.ua city cache load failed: {e}")

    city_name = vacancy.get("city", "")
    city_id = _resolve_city_id(city_name)
    if city_id:
        logger.info(f"Robota.ua city resolved: '{city_name}' → id={city_id}")
    else:
        logger.info(f"Robota.ua city '{city_name}' not found in cache — searching Ukraine-wide (cityId=0)")
        city_id = "0"

    requirements = vacancy.get("requirements", "")
    keywords = vacancy.get("keywords", [])
    description_parts = []
    if requirements:
        if isinstance(requirements, list):
            description_parts.append(" ".join(requirements))
        else:
            description_parts.append(str(requirements))
    if keywords:
        description_parts.append(" ".join(keywords))
    vacancy_description = " ".join(description_parts).strip()

    gql_input = {
        "vacancyTitle": position,
        "vacancyDescription": vacancy_description,
        "cityId": city_id,
        "resumeType": "ALL",
    }

    logger.info(
        f"Robota.ua search: position='{position}' city_id={city_id} "
        f"depth_days={depth_days}"
    )

    search_result = await _gql(
        _RECOMMENDED_QUERY,
        {"input": gql_input, "first": 20},
        "recommendedProfResumesQuery",
        token,
    )

    resume_list = (
        search_result
        .get("data", {})
        .get("recommendedProfResumes", {})
        .get("recommendedProfResumeList", [])
    )
    total_available = (
        search_result
        .get("data", {})
        .get("recommendedProfResumes", {})
        .get("total", 0)
    )

    if not resume_list:
        logger.info(f"Robota.ua: 0 results for '{position}'")
        return []

    logger.info(
        f"Robota.ua: {len(resume_list)}/{total_available} resumes returned for '{position}'"
    )

    cutoff = datetime.utcnow() - timedelta(days=depth_days)

    candidates = []
    contacts_found = 0

    for item in resume_list:
        resume_id = str(item.get("id", ""))
        if not resume_id:
            continue

        # Date filter from list response
        last_activity_str = item.get("lastActivityDate") or item.get("updateDate") or ""
        if last_activity_str:
            last_dt = _parse_iso_date(last_activity_str)
            if last_dt and last_dt < cutoff:
                logger.debug(
                    f"Robota.ua: skipping resume {resume_id} "
                    f"(lastActivity={last_activity_str[:10]}, cutoff={depth_days}d)"
                )
                continue

        profile_url = PROFILE_URL_TEMPLATE.format(resume_id=resume_id)

        # Basic fields from list response
        display_name = item.get("displayName") or ""
        speciality = item.get("speciality") or ""
        age_from_list = item.get("age")
        city_obj = item.get("city") or {}
        city_from_list = city_obj.get("name", "")
        salary_obj = item.get("resumeSalary")
        salary_uah_l, salary_usd_l = _salary_to_usd_uah(
            salary_obj.get("amount") if salary_obj else None,
            salary_obj.get("currency", "UAH") if salary_obj else "UAH",
        )
        exp_from_list = _parse_experience_years(item.get("experience") or [])

        # Attempt to fetch full CV for richer data + contacts
        await asyncio.sleep(1.0)  # 1 second rate limit between employerResume calls
        detail_result = await _gql(
            _EMPLOYER_RESUME_QUERY,
            {"id": resume_id},
            "employerResumeQuery",
            token,
        )
        detail = (
            detail_result
            .get("data", {})
            .get("employerResume", {})
        )
        typename = detail.get("__typename", "")

        full_name = display_name
        current_role = speciality
        city = city_from_list
        age = age_from_list
        salary_uah = salary_uah_l
        salary_usd = salary_usd_l
        salary_expectation = salary_usd_l
        contact = "Деталі на Robota.ua"
        email = ""
        skills = ""
        education_lines = []
        experiences = item.get("experience") or []
        languages = []
        exp_years = exp_from_list
        last_active = last_activity_str[:10] if last_activity_str else ""

        if typename == "EmployerResume":
            personal = detail.get("personal") or {}
            first_name = personal.get("firstName") or ""
            last_name = personal.get("lastName") or ""
            if first_name or last_name:
                full_name = f"{first_name} {last_name}".strip()
            birth_date = personal.get("birthDate") or ""
            if birth_date:
                age = _parse_age(birth_date)

            title = detail.get("title") or speciality
            if title:
                current_role = title

            city_d = detail.get("city") or {}
            if city_d.get("name"):
                city = city_d["name"]

            sal_d = detail.get("salary") or {}
            if sal_d.get("amount"):
                salary_uah, salary_usd = _salary_to_usd_uah(
                    sal_d["amount"], sal_d.get("currency", "UAH")
                )
                salary_expectation = salary_usd

            # Contacts — may be hidden without CVDB subscription
            contacts_d = detail.get("contacts") or {}
            phones = contacts_d.get("phones") or []
            email_d = contacts_d.get("email") or {}
            email = (email_d.get("email") or "") if isinstance(email_d, dict) else ""

            if phones:
                first_phone = phones[0].get("phone", "") if isinstance(phones[0], dict) else str(phones[0])
                contact = first_phone or email or "Деталі на Robota.ua"
                contacts_found += 1
            elif email:
                contact = email
                contacts_found += 1

            # Experiences from detail (more fields than list)
            detail_exps = detail.get("experiences") or []
            if detail_exps:
                experiences = detail_exps
            exp_years = _parse_experience_years(experiences)

            skills_raw = detail.get("skills") or ""
            skills = skills_raw[:500] if isinstance(skills_raw, str) else ""

            edus = detail.get("educations") or []
            for edu in edus[:3]:
                edu_name = edu.get("name") or ""
                year_end = edu.get("yearEnd") or ""
                if edu_name:
                    education_lines.append(f"{edu_name} ({year_end})" if year_end else edu_name)

            lang_skills = detail.get("languageSkills") or []
            for ls in lang_skills:
                lang_name = (ls.get("language") or {}).get("name", "")
                level_name = (ls.get("level") or {}).get("name", "")
                if lang_name:
                    languages.append(f"{lang_name} ({level_name})" if level_name else lang_name)

        # Build salary string for raw_text
        if salary_uah and salary_usd:
            salary_str = f"{salary_uah:,} грн / ${salary_usd:,}"
        elif salary_uah:
            salary_str = f"{salary_uah:,} грн"
        elif salary_usd:
            salary_str = f"${salary_usd:,}"
        else:
            salary_str = ""

        raw_text = _build_raw_text(
            role=current_role,
            city=city,
            experiences=experiences,
            skills=skills,
            education_lines=education_lines,
            salary_str=salary_str,
            languages=languages,
        )

        candidate = {
            "source":                 "robota.ua",
            "profile_url":            profile_url,
            "full_name":              full_name or "Кандидат Robota.ua",
            "current_role":           current_role or position,
            "age":                    age,
            "city":                   city,
            "salary_expectation":     salary_expectation,
            "salary_expectation_usd": salary_usd,
            "salary_expectation_uah": salary_uah,
            "contact":                contact,
            "email":                  email,
            "experience_years":       exp_years,
            "skills":                 skills,
            "raw_text":               raw_text,
            "message_date":           last_activity_str or "",
            "last_active":            last_active,
        }
        candidates.append(candidate)

    logger.info(
        f"Robota.ua: returned {len(candidates)} candidates "
        f"({contacts_found} with visible contacts) "
        f"for '{position}' (depth={depth_days}d)"
    )
    return candidates
