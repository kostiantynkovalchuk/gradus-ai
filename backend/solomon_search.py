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
    JUSTICE_CODES_LOCAL = {
        "цивільні": 1, "кримінальні": 5,
        "господарські": 3, "адміністративні": 4, "всі": None,
    }
    JUDGMENT_CODES_LOCAL = {
        "постанови": 2, "рішення": 4, "всі": None,
    }

    justice_code = JUSTICE_CODES_LOCAL.get(params.get("justice_type", "всі"))
    judgment_code = JUDGMENT_CODES_LOCAL.get(params.get("judgment_type", "постанови"), 2)
    date_range = params.get("date_range", "2")
    limit = int(params.get("limit", 5))
    search_text = " ".join(params.get("search_text", "").split()[:5])

    query_params = {
        "text": search_text,
        "stage": "cassation",
    }
    if judgment_code:
        query_params["justice_code"] = str(judgment_code)
    if justice_code:
        query_params["judgment_code"] = str(justice_code)
    if date_range and date_range != "0":
        query_params["adjudication_date_year"] = str(date_range)

    resp = requests.get(
        "https://court-search-agent.replit.app/proxy/court",
        params=query_params,
        headers={"Authorization": "Bearer gradus-court-2026"},
        timeout=30,
    )
    logger.info(f"Court status: {resp.status_code}")
    logger.info(f"Court URL: {resp.url}")

    if resp.status_code != 200:
        logger.warning(f"Court error: {resp.text[:200]}")
        return []

    html = resp.text
    marker = "window.__INITIAL_STATE__='"
    idx = html.find(marker)
    if idx == -1:
        logger.warning("Solomon: __INITIAL_STATE__ not found in response")
        logger.info(f"Court preview: {html[:300]}")
        return []

    start = idx + len(marker)
    end = html.find("';</script>", start)
    if end == -1:
        end = html.find("'</script>", start)
    if end == -1:
        logger.warning("Solomon: could not find end of __INITIAL_STATE__")
        return []

    raw_json = html[start:end]
    raw_json = raw_json.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.error(f"Solomon: JSON parse error: {e}")
        logger.info(f"Raw JSON preview: {raw_json[:300]}")
        return []

    judgments = data.get("pageData", {}).get("judgments", [])
    logger.info(f"Solomon: found {len(judgments)} judgments")

    results = []
    for j in judgments[:limit]:
        link = j.get("link", "")
        if link and not link.startswith("http"):
            link = f"https://court.opendatabot.ua{link}"
        results.append({
            "cause_number": j.get("cause_number", "—"),
            "adjudication_date": j.get("adjudication_date", "")[:10],
            "judge": j.get("judge", "—"),
            "court_name": j.get("court_name", ""),
            "justice_name": j.get("justice_name", ""),
            "link": link,
            "doc_id": str(j.get("doc_id", "")),
        })

    return results


def cap_summary(text: str) -> str:
    text = text.strip()
    if len(text) <= 250 and text[-1] in '.!?»"':
        return text
    for i in range(len(text) - 1, 79, -1):
        if text[i] == '.':
            return text[:i + 1]
    for i in range(len(text) - 1, 79, -1):
        if text[i] == ',':
            return text[:i] + '.'
    for i in range(len(text) - 1, 79, -1):
        if text[i] == ' ':
            return text[:i] + '.'
    return text


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
            max_tokens=90,
            system='Ти юридичний помічник. Коротко (1 речення, до 150 символів) вкажи результат рішення суду за шаблоном: "Суд [задовольнив/відмовив/скасував] [що саме], бо [причина]." Без вступів, заголовків, лапок.',
            messages=[{"role": "user", "content": text[:1000]}]
        )
        summary = response.content[0].text.strip()
        return cap_summary(summary)

    except Exception as e:
        logger.error(f"Solomon summarize error: {e}")
        return "Текст рішення недоступний."
