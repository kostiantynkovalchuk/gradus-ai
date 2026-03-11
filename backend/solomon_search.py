import json
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from anthropic import Anthropic
import os

logger = logging.getLogger(__name__)
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

PARSE_SYSTEM_PROMPT = """Ти парсер юридичних запитів. З запиту користувача витягни параметри та поверни ТІЛЬКИ JSON:

{
  "search_text": "ключові слова, макс 5 слів, без дат і типів документів",
  "vr_type": "1|2|3|5|" (1=Вирок, 2=Постанова, 3=Рішення, 5=Ухвала, порожньо=всі),
  "cs_type": "1|2|3|4|" (1=Цивільне, 2=Кримінальне, 3=Господарське, 4=Адміністративне, порожньо=всі),
  "ins_type": "3" (завжди 3=Касаційна, якщо не вказано інше),
  "date_from": "DD.MM.YYYY або порожньо",
  "date_to": "DD.MM.YYYY або порожньо",
  "date_range": "1|2|3|0" (тільки якщо конкретні дати не вказані: 1=1рік, 2=2роки, 3=3роки, 0=весь час),
  "judge": "ПІБ судді або порожньо",
  "case_number": "номер справи або порожньо"
}

Правила:
- ins_type завжди "3" (касація) якщо явно не вказано "апеляція" або "перша інстанція"
- вирок → vr_type "1", постанова → "2", рішення → "3", ухвала → "5"
- податков*/ДПС/перевірка/ППР/нереальність/маркетинг витрати → cs_type "4"
- вирок/обвинувачення/злочин/КК України → cs_type "2"
- договір/стягнення/банкрутство/борг → cs_type "3"
- аліменти/спадщина/нерухомість → cs_type "1"
- якщо незрозуміло → cs_type порожньо
- Якщо є конкретні дати (формат DD.MM.YYYY або назва дати) → date_from/date_to, date_range порожньо
- Якщо вказано лише рік (наприклад "2025", "за 2025 рік") → date_from: "01.01.2025", date_to: "31.12.2025", date_range порожньо
- Якщо діапазон років ("2024-2025") → date_from: "01.01.2024", date_to: "31.12.2025", date_range порожньо
- Якщо "з 2023" (без кінця) → date_from: "01.01.2023", date_to порожньо, date_range порожньо
- Якщо є "за N рік(ів)" без конкретного року або без дат → date_range, date_from/date_to порожньо
- date_range default "2" якщо дати не вказані і рік не вказаний; "0" тільки якщо явно "весь час"
- search_text: тільки змістовні ключові слова справи
- Якщо запит містить конкретні фільтри (тип документу + форма судочинства + дати), search_text може бути порожнім або містити лише 1-2 найважливіших змістовних слова справи (не назви статей, не слова "кодекс", "стаття")
- Номери статей (234, 185, тощо) — НЕ включати в search_text, вони не індексуються в повнотекстовому пошуку"""


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


def fetch_decision_text(doc_id: str) -> str:
    try:
        resp = requests.get(
            f"https://court-search-agent.replit.app/proxy/reyestr/text/{doc_id}",
            headers={"Authorization": "Bearer gradus-court-2026"},
            timeout=20,
        )
        if resp.status_code == 200:
            return resp.json().get("text", "")
    except Exception as e:
        logger.warning(f"Failed to fetch text for {doc_id}: {e}")
    return ""


def search_with_fallback(base_payload: dict) -> list:
    attempts = [
        base_payload.copy(),
        {**base_payload, "vr_type": None},
        {**base_payload, "vr_type": None, "cs_type": None},
        {**base_payload, "vr_type": None, "cs_type": None, "date_from": None, "date_to": None},
    ]
    for i, payload in enumerate(attempts):
        clean = {k: v for k, v in payload.items() if v is not None and v != ""}
        resp = requests.post(
            "https://court-search-agent.replit.app/proxy/reyestr",
            json=clean,
            headers={"Authorization": "Bearer gradus-court-2026"},
            timeout=30,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            if results:
                logger.info(f"Solomon: found {len(results)} judgments on attempt {i+1}")
                return results
        logger.info(f"Solomon: attempt {i+1} returned 0, relaxing filters")
    return []


def search_decisions(params: dict) -> list:
    logger.info(f"Solomon parsed params: {params}")
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

    payload = {
        "limit": limit,
        "ins_type": params.get("ins_type", "3"),
        "sort": "1",
    }
    if search_text:
        payload["search_text"] = search_text
    if params.get("vr_type"):
        payload["vr_type"] = params["vr_type"]
    if params.get("cs_type"):
        payload["cs_type"] = params["cs_type"]
    if params.get("judge"):
        payload["judge"] = params["judge"]
    if params.get("case_number"):
        payload["case_number"] = params["case_number"]
    if date_from:
        payload["date_from"] = date_from
    if date_to:
        payload["date_to"] = date_to

    logger.info(f"Solomon proxy payload: {payload}")

    judgments = search_with_fallback(payload)
    logger.info(f"Solomon: total {len(judgments)} judgments after fallback")

    doc_ids = [j.get("doc_id", "") for j in judgments]
    texts = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_id = {executor.submit(fetch_decision_text, doc_id): doc_id for doc_id in doc_ids if doc_id}
        for future in as_completed(future_to_id):
            doc_id = future_to_id[future]
            texts[doc_id] = future.result()

    results = []
    for j in judgments:
        doc_id = j.get("doc_id", "")
        decision_text = texts.get(doc_id, "")
        bad_signals = ["<", "метадан", "резолютивна частина не наведена"]
        is_bad = (
            not decision_text
            or len(decision_text) < 300
            or any(s in decision_text[:200] for s in bad_signals)
        )
        summary = "" if is_bad else summarize_decision(decision_text)

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
            system='Ти юридичний помічник. Коротко (1 речення, до 150 символів) вкажи результат рішення суду за шаблоном: "Суд [задовольнив/відмовив/скасував] [що саме], бо [причина]." Без вступів, заголовків, лапок.\n\nКРИТИЧНО: Якщо текст не містить чіткої резолютивної частини ("задовольнити", "відмовити", "скасувати", "залишити", "закрити") — поверни ТІЛЬКИ порожній рядок "". Жодних пояснень чому текст неповний. Жодних слів про відсутність резолютивної частини. Або результат, або порожньо.',
            messages=[{"role": "user", "content": text}]
        )
        summary = response.content[0].text.strip()
        return cap_summary(summary)

    except Exception as e:
        logger.error(f"Solomon summarize error: {e}")
        return ""
