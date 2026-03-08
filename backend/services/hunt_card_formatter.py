import logging

logger = logging.getLogger(__name__)

SOURCE_EMOJI = {
    "telegram": "📱",
    "work.ua": "💼",
    "robota.ua": "🔍",
}


def _format_salary(candidate: dict) -> str:
    usd = candidate.get("salary_expectation_usd")
    uah = candidate.get("salary_expectation_uah")

    if usd and uah:
        return f"${usd:,} (~{uah:,} грн)"
    if usd:
        from services.salary_normalizer import get_usd_uah_rate
        return f"${usd:,} (~{int(usd * get_usd_uah_rate()):,} грн)"
    if uah:
        from services.salary_normalizer import get_usd_uah_rate
        usd_calc = int(uah / get_usd_uah_rate())
        return f"{uah:,} грн (~${usd_calc:,})"

    amount = candidate.get("salary_expectation")
    if not amount or not isinstance(amount, (int, float)):
        return "За домовленістю"

    amount = int(amount)
    from services.salary_normalizer import get_usd_uah_rate
    rate = get_usd_uah_rate()
    if amount > 5000:
        usd_calc = int(amount / rate)
        return f"{amount:,} грн (~${usd_calc:,})"
    else:
        uah_calc = int(amount * rate)
        return f"${amount:,} (~{uah_calc:,} грн)"


def format_candidate_card(candidate: dict, index: int) -> str:
    try:
        score = candidate.get("score", 0)
        source = candidate.get("source", "unknown")
        source_em = SOURCE_EMOJI.get(source, "📋")
        full_name = candidate.get("full_name", "Невідомо")
        age = candidate.get("age")
        city = candidate.get("city")
        exp = candidate.get("experience_years")
        current_role = candidate.get("current_role")
        strengths = candidate.get("strengths", [])
        concerns = candidate.get("concerns", [])
        contact = candidate.get("contact")
        profile_url = candidate.get("profile_url")
        summary = candidate.get("summary", "")

        name_line = full_name
        if age:
            name_line += f", {age} р."

        lines = [
            f"#{index} | ⭐ {score}/100 | {source_em} {source}",
            "",
            f"👤 {name_line}",
            f"📍 {city or 'Місто не вказано'}",
            f"💼 {exp or '?'} р. — {current_role or 'Не вказано'}",
        ]

        if strengths:
            lines.append(f"🎯 {' · '.join(strengths)}")
        if concerns:
            lines.append(f"⚠️ {' · '.join(concerns)}")

        lines.append(f"💰 {_format_salary(candidate)}")
        lines.append(f"📞 {contact or 'Контакт не вказано'}")

        if profile_url:
            lines.append(f"🔗 {profile_url}")

        if summary:
            lines.append("")
            lines.append(summary)

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Card format error: {e}")
        return f"⚠️ Помилка форматування картки: {e}"
