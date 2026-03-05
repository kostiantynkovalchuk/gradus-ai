import os
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


async def score_candidate(candidate: dict, vacancy: dict) -> dict:
    try:
        c = _ensure_client()
        vacancy_json = json.dumps(vacancy, ensure_ascii=False, default=str)
        candidate_text = candidate.get("raw_text", "")

        response = c.messages.create(
            model=CLAUDE_MODEL_TELEGRAM,
            max_tokens=512,
            system=(
                "You are an HR assistant scoring a candidate for a vacancy.\n"
                "Return JSON only. No preamble, no markdown.\n\n"
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
                '  "contact": "phone or @username",\n'
                '  "summary": "2 sentence summary in Ukrainian",\n'
                '  "strengths": ["strength 1", "strength 2"],\n'
                '  "concerns": ["concern 1"]\n'
                '}'
            ),
            messages=[{
                "role": "user",
                "content": f"Vacancy: {vacancy_json[:2000]}\n\nCandidate text: {candidate_text[:2000]}",
            }],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        scored = json.loads(raw)
        scored.setdefault("score", 0)
        scored.setdefault("full_name", "Невідомо")
        scored.setdefault("age", None)
        scored.setdefault("city", None)
        scored.setdefault("experience_years", None)
        scored.setdefault("current_role", None)
        scored.setdefault("skills", "")
        scored.setdefault("salary_expectation", None)
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
    salary = candidate.get("salary_expectation")
    if not salary or not isinstance(salary, (int, float)):
        return
    salary = int(salary)
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
                salary_median=salary,
                currency="USD",
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
