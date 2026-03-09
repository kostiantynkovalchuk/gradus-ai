import re
import json
import logging
import requests
from bs4 import BeautifulSoup
from anthropic import Anthropic
import os

logger = logging.getLogger(__name__)
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

PARSE_SYSTEM_PROMPT = """Ти помічник юриста України.
Перетвори запит на JSON параметри пошуку.
Поверни ТІЛЬКИ JSON без markdown або пояснень.

ОБОВ'ЯЗКОВІ ПРАВИЛА:

1. justice_type (тип справи):
   - ДПС, ППР, податок, перевірка, НДС, митниця → "адміністративні"
   - Банкрутство, корпоративні спори, АМКУ → "господарські"
   - Трудові, сімейні, спадщина → "цивільні"
   - Кримінальне переслідування → "кримінальні"
   - Незрозуміло → "адміністративні"

2. search_text:
   - Прості ключові слова через пробіл, максимум 5 слів
   - НЕ використовуй оператори & або |
   - Приклад: "податкове повідомлення нереальність маркетинг"

3. date_range:
   - "2024-2025" або "2 роки" → "2"
   - "останній рік" або "2025" → "1"
   - "3 роки" → "3"
   - не вказано → "2"

4. judgment_type:
   - За замовчуванням → "постанови"
   - Тільки якщо явно вказано "рішення" як тип документу → "рішення"
   - "рішення АМКУ/ДПС/суду" (предмет оскарження) → "постанови"

Формат відповіді:
{
  "search_text": "ключові слова",
  "justice_type": "адміністративні|господарські|цивільні|кримінальні",
  "judgment_type": "постанови|рішення|всі",
  "date_range": "1|2|3|0",
  "limit": 5
}"""

JUSTICE_CODES = {
    "цивільні": "1",
    "кримінальні": "2",
    "господарські": "3",
    "адміністративні": "4",
    "всі": "0",
}

JUDGMENT_CODES = {
    "постанови": "2",
    "рішення": "4",
    "всі": "0",
}


def parse_query(user_text: str) -> dict:
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=PARSE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}]
    )
    raw = response.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def search_decisions(params: dict) -> list:
    justice_code = JUSTICE_CODES.get(params.get("justice_type", "всі"), "0")
    judgment_code = JUDGMENT_CODES.get(params.get("judgment_type", "постанови"), "2")
    date_range = params.get("date_range", "2")
    limit = int(params.get("limit", 5))

    query_params = {
        "text": params.get("search_text", ""),
    }
    if justice_code != "0":
        query_params["justice_code"] = justice_code
    if judgment_code != "0":
        query_params["judgment_code"] = judgment_code
    if date_range != "0":
        query_params["adjudication_date_year"] = date_range

    logger.info(f"Solomon search params: {query_params}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "Referer": "https://court.opendatabot.ua/",
    })

    try:
        session.get("https://court.opendatabot.ua", timeout=10)
    except Exception:
        pass

    resp = session.get(
        "https://court.opendatabot.ua/search",
        params=query_params,
        timeout=15
    )
    logger.info(f"Court status: {resp.status_code}")
    logger.info(f"Court URL: {resp.url}")
    logger.info(f"Court preview: {repr(resp.text[:500])}")
    html = resp.text

    markers = [
        ("window.__INITIAL_STATE__='", "'"),
        ('window.__INITIAL_STATE__="', '"'),
        ("__INITIAL_STATE__='", "'"),
        ('__INITIAL_STATE__="', '"'),
    ]

    start = -1
    quote_char = "'"
    used_marker = ""
    for marker, qc in markers:
        start = html.find(marker)
        if start != -1:
            used_marker = marker
            quote_char = qc
            break

    if start == -1:
        logger.warning("Solomon: __INITIAL_STATE__ not found in response")
        return []

    logger.info(f"Solomon: found marker '{used_marker}' at position {start}")
    json_start = start + len(used_marker)
    end = html.find(f"{quote_char};</script>", json_start)
    if end == -1:
        end = html.find(f"{quote_char}</script>", json_start)
    if end == -1:
        return []

    raw_json = html[json_start:end]
    raw_json = raw_json.replace('\\"', '"').replace("\\'", "'")

    try:
        data = json.loads(raw_json)
        judgments = data.get("pageData", {}).get("judgments", [])
        logger.info(f"Solomon: found {len(judgments)} judgments")
        return judgments[:limit]
    except json.JSONDecodeError as e:
        logger.error(f"Solomon JSON parse error: {e}")
        return []


def cap_summary(text: str, limit: int = 250) -> str:
    if len(text) <= limit:
        return text
    truncated = text[:limit]
    last_period = max(
        truncated.rfind(". "),
        truncated.rfind(".\n"),
        truncated.rfind(".")
    )
    if last_period > 100:
        return truncated[:last_period + 1]
    return truncated[:247] + "..."


def summarize_decision(link: str) -> str:
    try:
        resp = requests.get(
            link,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10
        )
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        full_text = soup.get_text(separator=" ", strip=True)

        for marker in ["Додайте Опендатабот", "Опендатабот — сервіс"]:
            idx = full_text.find(marker)
            if idx > 0:
                full_text = full_text[:idx]

        js_markers = ["localStorage", "matchMedia", "addEventListener"]
        if any(m in full_text[:500] for m in js_markers):
            return "Текст рішення недоступний."

        if len(full_text) > 8000:
            text = full_text[:1000] + " ...[середина]... " + full_text[-4000:]
        else:
            text = full_text

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="""Ти помічник юриста. Напиши резюме рішення ОДНИМ реченням
(максимум 200 символів): що вирішив суд і чому.
Без вступів, тільки факти.""",
            messages=[{"role": "user", "content": text[:5000]}]
        )
        summary = response.content[0].text.strip()
        return cap_summary(summary, 250)

    except Exception as e:
        logger.error(f"Solomon summarize error: {e}")
        return "Текст рішення недоступний."
