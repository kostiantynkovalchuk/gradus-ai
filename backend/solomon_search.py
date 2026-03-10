import json
import logging
import requests
from anthropic import Anthropic
import os

logger = logging.getLogger(__name__)
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

PARSE_SYSTEM_PROMPT = """Ти парсер юридичних запитів. З запиту користувача витягни параметри пошуку та поверни ТІЛЬКИ JSON без пояснень:

{
  "search_text": "ключові слова для пошуку, макс 5 слів",
  "vr_type": "Вирок|Постанова|Рішення|Ухвала|" (порожньо = всі),
  "date_from": "DD.MM.YYYY або порожньо",
  "date_to": "DD.MM.YYYY або порожньо",
  "date_range": "1|2|3|0" (років назад, використовувати тільки якщо конкретні дати не вказані, 0=весь час)
}

Правила:
- Якщо вказано конкретні дати — заповни date_from/date_to, date_range залиш порожнім
- Якщо вказано "за N рік(ів)" або без дат — заповни date_range, date_from/date_to залиш порожніми
- вирок → vr_type: "Вирок", постанова → "Постанова", рішення → "Рішення", ухвала → "Ухвала"
- search_text: тільки змістовні ключові слова (без дат, типів документів, назв суду)"""


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
    limit = int(params.get("limit", 5))
    search_text = " ".join(params.get("search_text", "").split()[:5])

    date_from = params.get("date_from", "")
    date_to = params.get("date_to", "")

    if not date_from:
        date_range = params.get("date_range", "2")
        if date_range and date_range != "0":
            from datetime import datetime, timedelta
            years_back = int(date_range)
            past = datetime.now() - timedelta(days=365 * years_back)
            date_from = past.strftime("%d.%m.%Y")

    payload = {"search_text": search_text, "limit": limit}
    if date_from:
        payload["date_from"] = date_from
    if date_to:
        payload["date_to"] = date_to
    if params.get("vr_type"):
        payload["vr_type"] = params["vr_type"]

    resp = requests.post(
        "https://court-search-agent.replit.app/proxy/reyestr",
        json=payload,
        headers={"Authorization": "Bearer gradus-court-2026"},
        timeout=30,
    )
    logger.info(f"Reyestr status: {resp.status_code}")

    if resp.status_code != 200:
        logger.warning(f"Reyestr error: {resp.text[:200]}")
        return []

    data = resp.json()
    judgments = data.get("results", [])
    logger.info(f"Solomon: found {len(judgments)} judgments")

    results = []
    for j in judgments:
        doc_id = j.get("doc_id", "")

        decision_text = ""
        if doc_id:
            try:
                text_resp = requests.get(
                    f"https://court-search-agent.replit.app/proxy/reyestr/text/{doc_id}",
                    headers={"Authorization": "Bearer gradus-court-2026"},
                    timeout=20,
                )
                if text_resp.status_code == 200:
                    decision_text = text_resp.json().get("text", "")
            except Exception as e:
                logger.warning(f"Failed to fetch text for {doc_id}: {e}")

        summary = ""
        if decision_text and len(decision_text) > 100:
            summary = summarize_decision(decision_text)

        results.append({
            "cause_number": j.get("cause_number", "—"),
            "adjudication_date": j.get("reg_date", ""),
            "judge": j.get("judge", "—"),
            "court_name": j.get("court_name", ""),
            "justice_name": j.get("vr_type", ""),
            "link": j.get("link", ""),
            "doc_id": doc_id,
            "summary": summary,
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


def summarize_decision(decision_text: str) -> str:
    try:
        text = decision_text[:1000]

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=90,
            system='Ти юридичний помічник. Коротко (1 речення, до 150 символів) вкажи результат рішення суду за шаблоном: "Суд [задовольнив/відмовив/скасував] [що саме], бо [причина]." Без вступів, заголовків, лапок.',
            messages=[{"role": "user", "content": text}]
        )
        summary = response.content[0].text.strip()
        return cap_summary(summary)

    except Exception as e:
        logger.error(f"Solomon summarize error: {e}")
        return ""
