import os
import re
import logging
import requests
from datetime import date

logger = logging.getLogger(__name__)

_rate_cache = {"date": None, "rate": 41.0}


def get_usd_uah_rate() -> float:
    today = date.today().isoformat()

    if _rate_cache["date"] == today:
        return _rate_cache["rate"]

    try:
        resp = requests.get(
            "https://bank.gov.ua/NBUStatService/v1/statdirectory/"
            "exchange?valcode=USD&json",
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        rate = float(data[0]["rate"])

        _rate_cache["date"] = today
        _rate_cache["rate"] = rate

        logger.info(f"NBU USD/UAH rate updated: {rate}")
        return rate

    except Exception as e:
        logger.warning(f"NBU rate fetch failed: {e}, using fallback")
        fallback = float(os.getenv("USD_TO_UAH_RATE", "41.0"))
        _rate_cache["date"] = today
        _rate_cache["rate"] = fallback
        return fallback


def _get_rate():
    return get_usd_uah_rate()


def _parse_number(text: str) -> int:
    text = text.replace(" ", "").replace(",", "").replace("\u00a0", "")
    if text.lower().endswith("к") or text.lower().endswith("k"):
        return int(float(text[:-1]) * 1000)
    try:
        return int(float(text))
    except ValueError:
        return 0


def extract_salary(text: str) -> dict:
    result = {
        "salary_min_uah": None,
        "salary_max_uah": None,
        "salary_min_usd": None,
        "salary_max_usd": None,
        "salary_median_uah": None,
        "salary_median_usd": None,
        "original_text": text,
        "currency_detected": "unknown",
        "confidence": "low",
    }

    if not text:
        return result

    text_lower = text.lower().strip()

    vague = ["за домовленістю", "конкурентна", "обговорюється", "договірна", "гідна"]
    for v in vague:
        if v in text_lower:
            result["confidence"] = "low"
            return result

    usd_patterns = [
        r'\$\s*([\d\s,\.]+[кk]?)',
        r'([\d\s,\.]+[кk]?)\s*\$',
        r'([\d\s,\.]+[кk]?)\s*(?:usd|доларів|дол\.?)',
    ]

    uah_patterns = [
        r'([\d\s,\.]+[кk]?)\s*(?:грн|uah|гривень|гривен)',
        r'([\d\s,\.]+)\s*тис\.?\s*грн',
    ]

    range_pattern = r'від\s+([\d\s,\.]+[кk]?)\s*(?:до|[-–—])\s*([\d\s,\.]+[кk]?)'
    dash_range = r'([\d\s,\.]+[кk]?)\s*[-–—]\s*([\d\s,\.]+[кk]?)'

    currency = None
    min_val = None
    max_val = None

    range_match = re.search(range_pattern, text_lower)
    if not range_match:
        for pat in usd_patterns + uah_patterns:
            ctx = re.search(r'(?:від\s+)?' + pat + r'\s*(?:до|[-–—])\s*' + pat.replace(r'([\d\s,\.]+[кk]?)', r'([\d\s,\.]+[кk]?)'), text_lower)
            if ctx:
                range_match = ctx
                break

    if range_match:
        min_val = _parse_number(range_match.group(1))
        max_val = _parse_number(range_match.group(2))
        if min_val > max_val:
            min_val, max_val = max_val, min_val
    else:
        dash_match = re.search(dash_range, text_lower)
        if dash_match:
            min_val = _parse_number(dash_match.group(1))
            max_val = _parse_number(dash_match.group(2))
            if min_val > max_val:
                min_val, max_val = max_val, min_val

    for pat in usd_patterns:
        if re.search(pat, text_lower):
            currency = "USD"
            if min_val is None:
                m = re.search(pat, text_lower)
                if m:
                    min_val = _parse_number(m.group(1))
                    max_val = min_val
            break

    if currency is None:
        for pat in uah_patterns:
            if re.search(pat, text_lower):
                currency = "UAH"
                if "тис" in text_lower and min_val is not None and min_val < 100:
                    min_val *= 1000
                    if max_val and max_val < 100:
                        max_val *= 1000
                if min_val is None:
                    m = re.search(pat, text_lower)
                    if m:
                        min_val = _parse_number(m.group(1))
                        max_val = min_val
                break

    if currency is None and min_val is None:
        nums = re.findall(r'(\d[\d\s,]*\d|\d)', text)
        if nums:
            val = _parse_number(nums[0])
            if val > 0:
                min_val = val
                max_val = val
                currency = "USD" if val < 5000 else "UAH"
                result["confidence"] = "medium"

    if min_val is None or min_val == 0:
        return result

    if currency is None:
        currency = "USD" if min_val < 5000 else "UAH"
        result["confidence"] = "medium"
    else:
        result["confidence"] = "high"

    result["currency_detected"] = currency

    if max_val is None:
        max_val = min_val

    median = (min_val + max_val) // 2
    rate = _get_rate()

    if currency == "USD":
        result["salary_min_usd"] = min_val
        result["salary_max_usd"] = max_val
        result["salary_median_usd"] = median
        result["salary_min_uah"] = int(min_val * rate)
        result["salary_max_uah"] = int(max_val * rate)
        result["salary_median_uah"] = int(median * rate)
    else:
        result["salary_min_uah"] = min_val
        result["salary_max_uah"] = max_val
        result["salary_median_uah"] = median
        result["salary_min_usd"] = int(min_val / rate)
        result["salary_max_usd"] = int(max_val / rate)
        result["salary_median_usd"] = int(median / rate)

    return result


def normalize_to_usd(amount: float, currency: str) -> float:
    if currency == "USD":
        return amount
    if currency == "UAH":
        return amount / _get_rate()
    return amount


def normalize_to_uah(amount: float, currency: str) -> float:
    if currency == "UAH":
        return amount
    if currency == "USD":
        return amount * _get_rate()
    return amount


def format_salary_display(usd: int = None, uah: int = None) -> str:
    rate = _get_rate()
    if usd and uah:
        return f"${usd:,} / {uah:,} грн"
    if usd:
        return f"${usd:,} (~{int(usd * rate):,} грн)"
    if uah:
        return f"{uah:,} грн (~${int(uah / rate):,})"
    return "За домовленістю"
