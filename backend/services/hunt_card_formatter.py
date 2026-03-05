import logging

logger = logging.getLogger(__name__)

SOURCE_EMOJI = {
    "telegram": "📱",
    "work.ua": "💼",
    "robota.ua": "🔍",
}


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
        salary = candidate.get("salary_expectation")
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

        lines.append(f"💰 {salary or '?'} $/міс")
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
