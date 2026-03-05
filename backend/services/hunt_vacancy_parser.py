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


async def parse_vacancy(text: str) -> dict:
    try:
        c = _ensure_client()
        response = c.messages.create(
            model=CLAUDE_MODEL_TELEGRAM,
            max_tokens=1024,
            system=(
                "You are an HR assistant. Parse this job vacancy text and return JSON only.\n"
                "No preamble, no markdown, just raw JSON.\n\n"
                "Return:\n"
                '{\n'
                '  "position": "job title in Ukrainian",\n'
                '  "city": "city name or null",\n'
                '  "requirements": ["requirement 1", "requirement 2"],\n'
                '  "salary_max": integer or null,\n'
                '  "keywords": ["keyword1", "keyword2", "keyword3"]\n'
                '}'
            ),
            messages=[{"role": "user", "content": f"Parse this vacancy:\n\n{text[:3000]}"}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        parsed = json.loads(raw)
        parsed.setdefault("position", text[:100])
        parsed.setdefault("city", None)
        parsed.setdefault("requirements", [])
        parsed.setdefault("salary_max", None)
        parsed.setdefault("keywords", [])
        logger.info(f"Parsed vacancy: {parsed.get('position')}")
        return parsed

    except json.JSONDecodeError as e:
        logger.error(f"Vacancy parse JSON error: {e}")
        return {"position": text[:100], "city": None, "requirements": [], "salary_max": None, "keywords": []}
    except Exception as e:
        logger.error(f"Vacancy parse error: {e}")
        return {"position": text[:100], "city": None, "requirements": [], "salary_max": None, "keywords": []}
