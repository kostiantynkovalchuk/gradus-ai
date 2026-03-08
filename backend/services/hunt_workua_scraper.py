import logging
import time
import random
import re
from typing import List, Dict, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

_last_request_time = 0.0

def _rate_limit():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < 3.0:
        time.sleep(3.0 - elapsed)
    _last_request_time = time.time()

WORKUA_BASE = "https://www.work.ua"
WORKUA_RESUMES = "https://www.work.ua/resumes"

CITY_SLUGS = {
    "київ": "kyiv",
    "kyiv": "kyiv",
    "дніпро": "dnipro",
    "dnipro": "dnipro",
    "дніпропетровськ": "dnipro",
    "харків": "kharkiv",
    "kharkiv": "kharkiv",
    "одеса": "odesa",
    "odesa": "odesa",
    "львів": "lviv",
    "lviv": "lviv",
    "запоріжжя": "zaporizhzhia",
    "вінниця": "vinnytsia",
    "полтава": "poltava",
    "миколаїв": "mykolaiv",
    "херсон": "kherson",
    "черкаси": "cherkasy",
    "суми": "sumy",
    "житомир": "zhytomyr",
}


def build_search_url(position: str, city: str, page: int = 1) -> str:
    city_lower = city.lower().strip() if city else ""
    city_slug = CITY_SLUGS.get(city_lower, city_lower)

    keywords = quote(position.strip()).replace("%20", "+")

    if city_slug:
        url = f"{WORKUA_RESUMES}-{city_slug}-{keywords}/"
    else:
        url = f"{WORKUA_RESUMES}-{keywords}/"

    if page > 1:
        url += f"?page={page}"

    return url


def parse_resume_card(card, session) -> Optional[Dict]:
    try:
        candidate = {}

        link = card.find("a", href=re.compile(r"/resumes/\d+"))
        if not link:
            return None

        profile_path = link.get("href", "")
        candidate["profile_url"] = f"{WORKUA_BASE}{profile_path}"
        candidate["source"] = "work.ua"

        title_el = card.find(["h2", "h3", "strong"])
        if title_el:
            candidate["current_role"] = title_el.get_text(strip=True)

        meta_text = card.get_text(separator=" ", strip=True)

        age_match = re.search(r'(\d{2})\s*рок', meta_text)
        if age_match:
            candidate["age"] = int(age_match.group(1))

        city_match = re.search(
            r'(Київ|Дніпро|Харків|Одеса|Львів|Запоріжжя|'
            r'Вінниця|Полтава|Миколаїв|Херсон)',
            meta_text,
        )
        if city_match:
            candidate["city"] = city_match.group(1)

        time_el = card.find(class_=re.compile(r'(date|time|ago)'))
        if time_el:
            candidate["last_active"] = time_el.get_text(strip=True)

        salary_match = re.search(
            r'(\d[\d\s,]+)\s*(грн|₴|\$|USD|usd)',
            meta_text,
        )
        if salary_match:
            candidate["salary_raw"] = salary_match.group(0)

        return candidate if candidate.get("profile_url") else None

    except Exception as e:
        logger.error(f"Card parse error: {e}")
        return None


def fetch_cv_details(profile_url: str, session) -> Dict:
    details = {}

    try:
        _rate_limit()

        resp = session.get(profile_url, timeout=15)
        resp.raise_for_status()

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        name_el = soup.find("h1") or soup.find(class_=re.compile(r'name'))
        if name_el:
            details["full_name"] = name_el.get_text(strip=True)

        phone_el = soup.find(string=re.compile(r'\+?3?8?0\d{9}'))
        if phone_el:
            details["contact"] = phone_el.strip()

        email_el = soup.find("a", href=re.compile(r'^mailto:'))
        if email_el:
            details["email"] = email_el.get_text(strip=True)

        exp_section = soup.find(class_=re.compile(r'experience|work-history'))
        if exp_section:
            exp_text = exp_section.get_text(separator=" ", strip=True)
            years_match = re.search(r'(\d+)\s*рок', exp_text)
            months_match = re.search(r'(\d+)\s*міс', exp_text)
            years = int(years_match.group(1)) if years_match else 0
            months = int(months_match.group(1)) if months_match else 0
            details["experience_years"] = round(years + months / 12, 1)

        skills_section = soup.find(class_=re.compile(r'(skill|keyword|tag)'))
        if skills_section:
            skills = [
                s.get_text(strip=True)
                for s in skills_section.find_all(["span", "li", "a"])
                if s.get_text(strip=True)
            ]
            details["skills"] = ", ".join(skills[:10])

        salary_el = soup.find(
            string=re.compile(r'(грн|₴|\$)\s*\d|\d+\s*(грн|₴|\$|USD)')
        )
        if salary_el:
            details["salary_raw"] = salary_el.strip()

        edu_section = soup.find(class_=re.compile(r'education'))
        if edu_section:
            details["education"] = edu_section.get_text(separator=" ", strip=True)[:200]

        main_content = soup.find("main") or soup.find(
            class_=re.compile(r'(resume|cv|profile)-content')
        )
        if main_content:
            details["raw_text"] = main_content.get_text(separator="\n", strip=True)[:3000]
        else:
            details["raw_text"] = soup.get_text(separator="\n", strip=True)[:3000]

        logger.info(f"Fetched CV details: {details.get('full_name', 'Unknown')}")

    except Exception as e:
        logger.error(f"CV detail fetch error for {profile_url}: {e}")

    return details


def scrape_workua_candidates(
    position: str,
    city: str,
    keywords: List[str],
    max_candidates: int = 20,
) -> List[Dict]:
    from services.workua_auth import get_workua_session
    from services.salary_normalizer import extract_salary

    max_candidates = min(max_candidates, 30)

    session = get_workua_session()
    if not session:
        logger.warning("Work.ua session unavailable - returning empty")
        return []

    candidates = []

    try:
        from bs4 import BeautifulSoup

        search_url = build_search_url(position, city)
        logger.info(f"Work.ua search: {search_url}")

        _rate_limit()
        resp = session.get(search_url, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        count_el = soup.find(string=re.compile(r'\d+\s+кандидат'))
        if count_el:
            logger.info(f"Work.ua found: {count_el.strip()}")

        cards = (
            soup.find_all("div", class_=re.compile(r'resume-link'))
            or soup.find_all("article", class_=re.compile(r'resume'))
            or soup.find_all("div", attrs={"data-id": True})
            or [a.parent for a in soup.find_all("a", href=re.compile(r'/resumes/\d+'))]
        )

        logger.info(f"Found {len(cards)} CV cards on page")

        for card in cards[:max_candidates]:
            candidate = parse_resume_card(card, session)
            if not candidate:
                continue

            if candidate.get("profile_url"):
                details = fetch_cv_details(candidate["profile_url"], session)
                candidate.update(details)

            salary_raw = candidate.pop("salary_raw", None)
            if salary_raw:
                salary_data = extract_salary(salary_raw)
                candidate["salary_expectation_usd"] = salary_data.get("salary_median_usd")
                candidate["salary_expectation_uah"] = salary_data.get("salary_median_uah")
                candidate["salary_expectation"] = salary_data.get("salary_median_usd")

            candidate.setdefault("source", "work.ua")
            candidate.setdefault("full_name", "Кандидат Work.ua")
            candidate.setdefault("city", city)
            candidate.setdefault("current_role", position)
            candidate.setdefault("experience_years", 0)
            candidate.setdefault("skills", "")
            candidate.setdefault("contact", "")
            candidate.setdefault("raw_text", "")

            candidates.append(candidate)
            logger.info(f"Parsed: {candidate['full_name']} ({candidate.get('city', '?')})")

            if len(candidates) >= max_candidates:
                break

        logger.info(f"Work.ua scrape complete: {len(candidates)} candidates")

    except Exception as e:
        logger.error(f"Work.ua scrape error: {e}")
    finally:
        session.close()

    return candidates


async def search_workua(vacancy: dict) -> list:
    import asyncio
    position = vacancy.get("position", "")
    city = vacancy.get("city", "")
    keywords = vacancy.get("keywords", [])

    if not position:
        logger.info("Work.ua: no position specified, skipping")
        return []

    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, scrape_workua_candidates, position, city, keywords, 15
        )
    except Exception as e:
        logger.error(f"Work.ua search_workua wrapper error: {e}")
        return []
