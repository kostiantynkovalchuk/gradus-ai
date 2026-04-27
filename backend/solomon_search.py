import json
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from anthropic import Anthropic
import os
from services.ai_models import HAIKU

logger = logging.getLogger(__name__)
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── Layer 1: Query Parser ─────────────────────────────────────────────────────

PARSE_SYSTEM_PROMPT = """Ти парсер юридичних запитів. З запиту користувача витягни параметри та поверни ТІЛЬКИ JSON без пояснень:

{
  "search_text": "ключові слова, макс 5 слів",
  "vr_type": "2|3|" (2=Постанова, 3=Рішення, порожньо=всі типи крім ухвал),
  "cs_type": "1|2|3|4|" (1=Цивільне, 2=Кримінальне, 3=Господарське, 4=Адміністративне, порожньо=всі),
  "ins_type": "3",
  "date_from": "DD.MM.YYYY або порожньо",
  "date_to": "DD.MM.YYYY або порожньо",
  "date_range": "1|2|3|0|" (1=1рік, 2=2роки, 3=3роки, 0=весь час, порожньо якщо вказані конкретні дати),
  "judge": "Прізвище або Прізвище І.О. або порожньо",
  "case_number": "номер справи або порожньо",
  "limit": 5
}

═══ ПРАВИЛА vr_type (ТИП ДОКУМЕНТА) ═══

КРИТИЧНО: "рішень", "рішення" в значенні "судові рішення взагалі" — НЕ встановлювати vr_type.
Це найчастіша помилка. Правило: vr_type встановлюється ТІЛЬКИ якщо користувач явно називає
конкретний вид документа як обмеження, а не загальне слово для "рішень суду".

Встановлювати vr_type тільки коли:
- "саме постанова" / "тільки постанови" / "постанову суду" → "2"
- "вирок" → "2" (на касації вироків немає, вирок = постанова)
- "конкретно рішення" / "рішення першої інстанції" → "3"
- "ухвала" → vr_type "5" (але ухвали зазвичай процесуальні, уточни у користувача)

НЕ встановлювати vr_type (залишати порожньо) коли:
- "рішень про банкрутство" → порожньо (рішень = взагалі практики)
- "10 рішень щодо ПДВ" → порожньо
- "покажи рішення" / "знайди рішення" → порожньо
- "практика суду з питань..." → порожньо
- будь-яка фраза де "рішення" = "судова практика" в цілому → порожньо

ВАЖЛИВО: vr_type=5 (Ухвала) НІКОЛИ не встановлюється як тип пошуку за замовчуванням.
Ухвали є процесуальними документами і фільтруються автоматично на наступному кроці.

═══ ПРАВИЛА cs_type (ФОРМА СУДОЧИНСТВА) ═══

- податков*/ДПС/перевірка/ППР/нереальність/маркетинг витрати/КАС/КАСУ/АМКУ/антимонопольн* → "4"
- вирок/обвинувачення/злочин/КК України → "2"
- договір/стягнення/банкрутство/борг/ГК/господарськ* → "3"
- авторськ* права → "1" або "3" (залежить від сторін; якщо незрозуміло → порожньо)
- аліменти/спадщина/нерухомість/ЦК/розлучення/шлюб/майно подружжя → "1"
- якщо незрозуміло або стосується кількох юрисдикцій → порожньо

═══ ПРАВИЛА ДАТ ═══

- Конкретні дати → date_from/date_to, date_range порожньо
- Лише рік "2025" → date_from: "01.01.2025", date_to: "31.12.2025"
- "2024-2025" → date_from: "01.01.2024", date_to: "31.12.2025"
- "за 2025 рік" → date_from: "01.01.2025", date_to: "31.12.2025"
- "з 2023" → date_from: "01.01.2023", date_to порожньо
- "за N рік(ів)" → date_range N, дати порожньо
- Без дат → date_range: "2" (за замовчуванням 2 роки)
- "за весь час" / "всі роки" → date_range: "0"

═══ ПРАВИЛА СУДДІ ═══

- "практика Блажівської" → judge: "Блажівська"
- "суддя Тітов" → judge: "Тітов"
- "рішення судді Малашенкової" → judge: "Малашенкова"

═══ ПРАВИЛА НОМЕРА СПРАВИ ═══

- Номер СТРОГО у форматі XXX/XXXXX/XX (два слеші): наприклад 910/12568/24
- Тільки якщо є повний номер → case_number: "номер", search_text порожньо
- Окремі числа (324, 185) — це статті законів, НЕ номери справ
- "справа 910/12568/24" → case_number: "910/12568/24"

═══ ПРАВИЛА СТАТЕЙ ЗАКОНІВ ═══

- "стаття 324 КАС" → search_text: "стаття 324", cs_type: "4"
- "ст. 185 КК України" → search_text: "стаття 185", cs_type: "2"
- "частина 2 статті 42 ГК" → search_text: "стаття 42", cs_type: "3"
- "стаття 1212 ЦК" → search_text: "стаття 1212", cs_type: "1"
- ПК (податковий кодекс) → cs_type: "4"
- Стаття + ключові слова → search_text: "стаття N ключове_слово" (макс 5 слів)

═══ КІЛЬКІСТЬ РЕЗУЛЬТАТІВ ═══

- "покажи 10", "дай 3 приклади", "топ 7" → limit: N
- "більше результатів" або "більше" без числа → limit: 10
- За замовчуванням → limit: 5 (максимум: 20)

═══ ЗАГАЛЬНІ ПРАВИЛА search_text ═══

- Якщо є номер справи → search_text порожньо
- Номери статей (234, 185) БЕЗ слова "стаття" — НЕ включати
- ins_type завжди "3" якщо явно не вказано "апеляція" або "перша інстанція"
- Зазначений тип документу НЕ включати в search_text

═══ ПРИКЛАДИ ═══

Запит: "покажи 10 рішень про банкрутство"
JSON: {"search_text":"банкрутство","vr_type":"","cs_type":"3","ins_type":"3","date_range":"2","judge":"","case_number":"","limit":10}
Пояснення: "рішень" = колоквіальне, vr_type порожньо; банкрутство = господарське cs_type=3

Запит: "постанова про відшкодування збитків договір поставки 2024"
JSON: {"search_text":"відшкодування збитків договір","vr_type":"2","cs_type":"3","ins_type":"3","date_from":"01.01.2024","date_to":"31.12.2024","judge":"","case_number":"","limit":5}
Пояснення: "постанова" = явний тип документа → vr_type=2; договір поставки = господарське

Запит: "скасування ППР нереальність операцій"
JSON: {"search_text":"скасування ППР нереальність операцій","vr_type":"","cs_type":"4","ins_type":"3","date_range":"2","judge":"","case_number":"","limit":5}
Пояснення: ППР = адміністративне; vr_type порожньо (пошук по суті)

Запит: "розподіл майна подружжя корпоративні права 2024-2025"
JSON: {"search_text":"розподіл майна корпоративні права","vr_type":"","cs_type":"1","ins_type":"3","date_from":"01.01.2024","date_to":"31.12.2025","judge":"","case_number":"","limit":5}
Пояснення: майно подружжя = цивільне; vr_type порожньо (рішення = загальне слово)"""


def parse_query(user_text: str) -> dict:
    response = client.messages.create(
        model=HAIKU,
        max_tokens=350,
        system=PARSE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}]
    )
    raw = response.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ── Reyestr proxy helpers ─────────────────────────────────────────────────────

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


# ── Layer 2: Post-fetch relevance + substantive scorer ───────────────────────

_SCORER_SYSTEM = """Ти класифікатор касаційних рішень Верховного Суду України.
Завдання: оцінити кожне рішення за релевантністю до запиту юриста та визначити,
чи є воно рішенням по суті (substantive) чи процесуальним (procedural).

SUBSTANTIVE = true (рішення по суті):
- Суд залишив/скасував/змінив рішення нижчої інстанції по суті справи
- Суд задовольнив/відмовив у задоволенні позову (касаційної скарги) по суті
- Є чітка резолютивна частина щодо прав та обов'язків сторін

SUBSTANTIVE = false (процесуальне):
- Повернення касаційної скарги (залишити без розгляду / повернути скаргу)
- Відмова у відкритті касаційного провадження
- Направлення справи на новий розгляд БЕЗ вирішення по суті
- Закриття провадження у справі
- Процедурні питання (строки, підсудність, забезпечення позову)
- Ухвала про будь-які процесуальні дії

RELEVANCE 0-10:
10 = точно по темі запиту, та сама правова проблема
7-9 = суміжна тема, корисний прецедент
5-6 = може бути корисним, непряме відношення
0-4 = не стосується запиту

Поверни ТІЛЬКИ JSON масив, без коментарів."""


def score_and_filter(
    original_query: str,
    parsed_params: dict,
    candidates: list,
    limit: int,
) -> list:
    """
    Batched Haiku call: score all candidates for relevance (0-10) and
    substantive/procedural classification. Returns up to `limit` results.

    Exclusions (relevance<6 OR substantive=false) are logged to
    solomon_scorer_log for future classifier tuning.
    """
    if not candidates:
        return []

    # Build compact per-result descriptors for Haiku
    items = []
    for i, r in enumerate(candidates):
        snippet = r.get("_text_snippet", "")[:450]
        items.append({
            "idx": i,
            "doc_id": r["doc_id"],
            "cause": r["cause_number"],
            "type": r.get("justice_name", ""),
            "court": r.get("court_name", ""),
            "snippet": snippet or "(текст відсутній)",
        })

    prompt = (
        f'Запит юриста: "{original_query}"\n\n'
        f"Нижче {len(items)} рішень. Оціни кожне.\n\n"
        + json.dumps(items, ensure_ascii=False, indent=2)
        + '\n\nПоверни JSON масив:\n'
          '[{"idx":0,"relevance":7,"substantive":true,"reason":""},...]\n'
          'reason — коротко чому excluded (якщо relevance<6 або substantive=false), інакше ""'
    )

    try:
        resp = client.messages.create(
            model=HAIKU,
            max_tokens=900,
            system=_SCORER_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        scores: list[dict] = json.loads(raw)
    except Exception as e:
        logger.error(f"Solomon scorer failed: {e} — returning candidates unfiltered")
        # Graceful degradation: if scorer crashes, fall back to original order
        for r in candidates:
            r.pop("_text_snippet", None)
        return candidates[:limit]

    # Build lookup by idx
    score_map = {s["idx"]: s for s in scores}

    kept = []
    excluded = []
    for s in sorted(scores, key=lambda x: -x.get("relevance", 0)):
        candidate = candidates[s["idx"]]
        rel = s.get("relevance", 0)
        subst = s.get("substantive", True)
        if rel >= 6 and subst:
            kept.append(candidate)
        else:
            excluded.append((candidate, s))

    # Log exclusions asynchronously (best-effort, non-blocking)
    if excluded:
        _log_exclusions(original_query, parsed_params, excluded)

    # Graceful degradation: if scorer was too aggressive and filtered everything,
    # include best-scored results regardless of threshold (avoids empty response)
    if not kept and candidates:
        logger.warning(
            "Solomon scorer: all %d candidates excluded — falling back to top by score",
            len(candidates),
        )
        all_scored = sorted(scores, key=lambda x: -x.get("relevance", 0))
        for s in all_scored[:limit]:
            kept.append(candidates[s["idx"]])

    # Strip internal field before returning
    for r in kept:
        r.pop("_text_snippet", None)

    return kept[:limit]


def _log_exclusions(query_text: str, parsed_params: dict, excluded: list) -> None:
    """
    Write excluded-decision rows to solomon_scorer_log.
    Called in the main thread but is fast (bulk INSERT).
    Best-effort: errors are logged but do not affect the search response.
    """
    try:
        from database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        for result, score in excluded:
            rel = score.get("relevance", 0)
            subst = score.get("substantive", True)
            parts = []
            if not subst:
                parts.append("procedural")
            if rel < 6:
                parts.append(f"low_relevance:{rel}")
            reason = "+".join(parts) if parts else (score.get("reason") or "unknown")

            cur.execute(
                """INSERT INTO solomon_scorer_log
                     (query_text, search_params, doc_id, cause_number,
                      action, relevance_score, is_substantive, exclusion_reason)
                   VALUES (%s, %s::jsonb, %s, %s, 'excluded', %s, %s, %s)""",
                (
                    query_text,
                    json.dumps(parsed_params),
                    result.get("doc_id", ""),
                    result.get("cause_number", ""),
                    rel,
                    subst,
                    reason,
                ),
            )
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Solomon scorer: logged %d exclusions", len(excluded))
    except Exception as e:
        logger.warning("Solomon scorer: could not log exclusions: %s", e)


# ── Main search flow ──────────────────────────────────────────────────────────

def search_decisions(params: dict, original_query: str = "") -> list:
    logger.info(f"Solomon parsed params: {params}")
    limit = min(int(params.get("limit", 5)), 20)
    # Fetch 3× the requested limit (min 15, max 20) so the scorer has enough
    # candidates to filter from without fetching an excessive number of documents.
    fetch_limit = min(max(limit * 3, 15), 20)
    search_text = " ".join(params.get("search_text", "").split()[:5])

    if params.get("case_number"):
        payload = {
            "case_number": params["case_number"],
            "limit": limit,
            "ins_type": params.get("ins_type", "3"),
            "sort": "1",
        }
        logger.info(f"Solomon direct lookup: {params['case_number']}")
        resp = requests.post(
            "https://court-search-agent.replit.app/proxy/reyestr",
            json=payload,
            headers={"Authorization": "Bearer gradus-court-2026"},
            timeout=30,
        )
        if resp.status_code == 200:
            judgments = resp.json().get("results", [])
            logger.info(f"Solomon direct lookup: found {len(judgments)}")
            # Direct lookup by case number: skip scoring, just return results
            return _build_results(judgments, limit, skip_scorer=True)
        return []

    base_payload = {
        "limit": fetch_limit,
        "ins_type": params.get("ins_type", "3"),
        "sort": "1",
    }
    if search_text:
        base_payload["search_text"] = search_text
    if params.get("vr_type"):
        base_payload["vr_type"] = params["vr_type"]
    if params.get("cs_type"):
        base_payload["cs_type"] = params["cs_type"]
    if params.get("judge"):
        base_payload["judge"] = params["judge"]

    date_from = params.get("date_from", "")
    date_to = params.get("date_to", "")
    if not date_from:
        date_range = params.get("date_range", "2")
        if date_range and date_range != "0":
            from datetime import datetime, timedelta
            past = datetime.now() - timedelta(days=365 * int(date_range))
            date_from = past.strftime("%d.%m.%Y")
    if date_from:
        base_payload["date_from"] = date_from
    if date_to:
        base_payload["date_to"] = date_to

    logger.info(f"Solomon proxy payload: {base_payload}")

    judgments = search_with_fallback(base_payload)
    logger.info(f"Solomon: {len(judgments)} candidates before scoring")

    # Build raw result dicts with text snippets (no summaries yet — saves Haiku
    # calls for candidates that will be excluded by the scorer)
    candidates = _build_raw_results(judgments, fetch_limit)

    # Score, filter, and log exclusions
    query_for_scorer = original_query or search_text or params.get("search_text", "")
    final = score_and_filter(query_for_scorer, params, candidates, limit)

    # Generate summaries only for the final kept results
    _add_summaries(final)

    logger.info(f"Solomon: {len(final)} results after scoring (from {len(candidates)} candidates)")
    return final


def _build_raw_results(judgments: list, limit: int) -> list:
    """
    Parallel-fetch decision texts. Return result dicts with '_text_snippet'
    populated (used by the scorer). Summaries are NOT generated here.
    """
    doc_ids = [j.get("doc_id", "") for j in judgments[:limit]]
    texts = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_id = {
            executor.submit(fetch_decision_text, did): did
            for did in doc_ids if did
        }
        for future in as_completed(future_to_id):
            texts[future_to_id[future]] = future.result()

    results = []
    for j in judgments[:limit]:
        doc_id = j.get("doc_id", "")
        text = texts.get(doc_id, "")
        results.append({
            "cause_number": j.get("cause_number", "—"),
            "adjudication_date": j.get("reg_date", ""),
            "judge": j.get("judge", "—"),
            "court_name": j.get("court_name", ""),
            "justice_name": j.get("vr_type", ""),
            "link": j.get("link", ""),
            "doc_id": doc_id,
            "summary": "",           # filled in by _add_summaries after scoring
            "_text_snippet": text,   # transient — stripped before returning to caller
        })
    return results


def _add_summaries(results: list) -> None:
    """Generate one-sentence summaries IN PLACE for the final kept results only."""
    bad_signals = ["<", "метадан", "резолютивна частина не наведена"]
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {}
        for r in results:
            text = r.get("_text_snippet", "")
            is_bad = (
                not text
                or len(text) < 300
                or any(s in text[:200] for s in bad_signals)
            )
            if not is_bad:
                futures[executor.submit(summarize_decision, text)] = r
        for future in as_completed(futures):
            futures[future]["summary"] = future.result()


def _build_results(judgments: list, limit: int, skip_scorer: bool = False) -> list:
    """
    Legacy helper used for direct case-number lookups (no scoring needed).
    Keeps the original one-pass build+summarize flow.
    """
    doc_ids = [j.get("doc_id", "") for j in judgments[:limit]]
    texts = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_id = {
            executor.submit(fetch_decision_text, did): did
            for did in doc_ids if did
        }
        for future in as_completed(future_to_id):
            texts[future_to_id[future]] = future.result()

    results = []
    bad_signals = ["<", "метадан", "резолютивна частина не наведена"]
    for j in judgments[:limit]:
        doc_id = j.get("doc_id", "")
        decision_text = texts.get(doc_id, "")
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


# ── Summarizer (unchanged) ────────────────────────────────────────────────────

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


def summarize_decision(text: str) -> str:
    try:
        response = client.messages.create(
            model=HAIKU,
            max_tokens=90,
            system="""Ти юридичний помічник. Коротко (1 речення, до 150 символів) вкажи результат рішення суду за шаблоном: "Суд [задовольнив/відмовив/скасував] [що саме], бо [причина]." Без вступів, заголовків, лапок.

КРИТИЧНО: Якщо текст не містить чіткої резолютивної частини — поверни порожній рядок.""",
            messages=[{"role": "user", "content": text[:1000]}],
        )
        if not response.content or len(response.content) == 0:
            return ""
        return cap_summary(response.content[0].text.strip())
    except Exception as e:
        logger.error(f"Solomon summarize error: {e}")
        return ""
