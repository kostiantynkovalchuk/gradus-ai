import os
import re
import json
import logging
from anthropic import Anthropic
from config.models import CLAUDE_MODEL_TELEGRAM

logger = logging.getLogger(__name__)

client = None

def _ensure_client():
    global client
    if client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        client = Anthropic(api_key=api_key)
    return client


def safe_parse_json(text: str) -> dict:
    text = re.sub(r'```json|```', '', text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')

        if text.count('"') % 2 != 0:
            text += '"'

        text += ']' * open_brackets
        text += '}' * open_braces

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON repair failed: {e}")
            return {}


async def score_candidate(candidate: dict, vacancy: dict) -> dict:
    try:
        c = _ensure_client()
        vacancy_with_budget = dict(vacancy)
        sal_max = vacancy_with_budget.get("salary_max")
        sal_cur = vacancy_with_budget.get("salary_currency", "")
        if sal_max and sal_cur:
            vacancy_with_budget["budget_display"] = f"{sal_max} {sal_cur}"
        vacancy_json = json.dumps(vacancy_with_budget, ensure_ascii=False, default=str)
        candidate_text = candidate.get("raw_text", "")

        response = c.messages.create(
            model=CLAUDE_MODEL_TELEGRAM,
            max_tokens=2000,
            system=(
                "You are an HR assistant scoring a candidate for a vacancy.\n"
                "Return JSON only. No preamble, no markdown.\n\n"
                "IMPORTANT: If the text is a job vacancy/posting by an employer (not a "
                "candidate's resume/CV), score it 0 and set full_name to "
                "'ВАКАНСІЯ (не кандидат)'. Signs of a vacancy: company hiring, job "
                "description with requirements, 'шукаємо'/'запрошуємо'/'потрібен' "
                "language, store/company name, or contact instructions like "
                "'надіслати резюме'/'звертайтесь'.\n\n"
                "Return:\n"
                '{\n'
                '  "score": 0-100,\n'
                '  "full_name": "extracted name or Невідомо",\n'
                '  "age": integer or null,\n'
                '  "city": "extracted city or null",\n'
                '  "experience_years": float or null,\n'
                '  "current_role": "extracted role or null",\n'
                '  "skills": "comma separated skills",\n'
                '  "salary_expectation": integer or null,\n'
                '  "salary_expectation_raw": "original text like 25000 грн or $600",\n'
                '  "salary_expectation_usd": integer or null,\n'
                '  "salary_expectation_uah": integer or null,\n'
                '  "currency_detected": "UAH" or "USD" or "unknown",\n'
                '  "contact": "phone or @username",\n'
                '  "summary": "2 sentence summary in Ukrainian",\n'
                '  "strengths": ["strength 1", "strength 2"],\n'
                '  "concerns": ["concern 1"]\n'
                '}'
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Vacancy: {vacancy_json[:2000]}\n\n"
                    f"Candidate name (from structured data): {candidate.get('full_name') or 'unknown'}\n"
                    f"Candidate source: {candidate.get('source', 'unknown')}\n"
                    f"Candidate city: {candidate.get('city') or 'unknown'}\n"
                    f"Candidate age: {candidate.get('age') or 'unknown'}\n\n"
                    f"Candidate text:\n{candidate_text[:2000]}"
                ),
            }],
        )

        raw = response.content[0].text.strip()
        scored = safe_parse_json(raw)

        if not scored:
            return _fallback(candidate, "Empty JSON after parse")

        scored.setdefault("score", 0)
        scored.setdefault("full_name", "Невідомо")
        scored.setdefault("age", None)
        scored.setdefault("city", None)
        scored.setdefault("experience_years", None)
        scored.setdefault("current_role", None)
        scored.setdefault("skills", "")
        scored.setdefault("salary_expectation", None)
        scored.setdefault("salary_expectation_raw", "")
        scored.setdefault("salary_expectation_usd", None)
        scored.setdefault("salary_expectation_uah", None)
        scored.setdefault("currency_detected", "unknown")

        if scored.get("salary_expectation_raw") and (not scored.get("salary_expectation_usd") or not scored.get("salary_expectation_uah")):
            from services.salary_normalizer import extract_salary
            parsed = extract_salary(scored["salary_expectation_raw"])
            if parsed["salary_median_usd"]:
                scored["salary_expectation_usd"] = scored.get("salary_expectation_usd") or parsed["salary_median_usd"]
                scored["salary_expectation_uah"] = scored.get("salary_expectation_uah") or parsed["salary_median_uah"]
                scored["currency_detected"] = parsed["currency_detected"]

        scored.setdefault("contact", candidate.get("contact", ""))
        scored.setdefault("summary", "")
        scored.setdefault("strengths", [])
        scored.setdefault("concerns", [])

        scored["source"] = candidate.get("source", "unknown")
        scored["profile_url"] = candidate.get("profile_url", "")

        logger.info(f"Scored candidate '{scored['full_name']}': {scored['score']}/100")
        return scored

    except json.JSONDecodeError as e:
        logger.error(f"Scorer JSON error: {e}")
        return _fallback(candidate, str(e))
    except Exception as e:
        logger.error(f"Scorer error: {e}")
        return _fallback(candidate, str(e))


async def extract_salary_data(candidate: dict, vacancy: dict, vacancy_id: int):
    from services.salary_normalizer import extract_salary, get_usd_uah_rate
    USD_TO_UAH_RATE = get_usd_uah_rate()

    salary_raw = candidate.get("salary_expectation_raw", "")
    salary_usd = candidate.get("salary_expectation_usd")
    salary_uah = candidate.get("salary_expectation_uah")
    currency_detected = candidate.get("currency_detected", "unknown")

    if not salary_usd and not salary_uah:
        salary = candidate.get("salary_expectation")
        if not salary or not isinstance(salary, (int, float)):
            return
        salary = int(salary)
        salary_usd = salary
        salary_uah = int(salary * USD_TO_UAH_RATE)
        currency_detected = "USD"

    if not salary_usd and not salary_uah:
        return

    try:
        import models
        if models.SessionLocal is None:
            models.init_db()
        db = models.SessionLocal()
        try:
            from models.hunt_models import HuntSalaryData
            entry = HuntSalaryData(
                vacancy_id=vacancy_id,
                source=candidate.get("source", "unknown"),
                data_type="candidate",
                position=vacancy.get("position", ""),
                city=candidate.get("city") or vacancy.get("city"),
                salary_median=salary_usd or (int(salary_uah / USD_TO_UAH_RATE) if salary_uah else None),
                salary_min_usd=salary_usd,
                salary_max_usd=salary_usd,
                salary_median_usd=salary_usd,
                salary_min_uah=salary_uah,
                salary_max_uah=salary_uah,
                salary_median_uah=salary_uah,
                currency="USD",
                currency_detected=currency_detected,
                usd_rate_at_collection=USD_TO_UAH_RATE,
                skills=candidate.get("skills", ""),
                source_url=candidate.get("profile_url", ""),
            )
            db.add(entry)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Salary data extraction error: {e}")


def _fallback(candidate: dict, error: str) -> dict:
    return {
        "score": 0,
        "full_name": "Невідомо",
        "age": None,
        "city": None,
        "experience_years": None,
        "current_role": None,
        "skills": "",
        "salary_expectation": None,
        "contact": candidate.get("contact", ""),
        "summary": f"Помилка аналізу: {error}",
        "strengths": [],
        "concerns": [],
        "source": candidate.get("source", "unknown"),
        "profile_url": candidate.get("profile_url", ""),
    }
