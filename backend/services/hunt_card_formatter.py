import logging
from datetime import datetime

logger = logging.getLogger(__name__)

SOURCE_EMOJI = {
    "telegram": "📱",
    "work.ua": "💼",
    "robota.ua": "🔍",
    "robota.ua-applies": "📩",
}

SOURCE_LABEL = {
    "robota.ua-applies": "robota.ua (відгук)",
}

FALLBACK_ROUND_LABELS = {
    180: "📋 Знайдено в архіві за 6 місяців",
    365: "📋 Знайдено в архіві за 1 рік",
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


def _format_candidate_date(candidate: dict) -> str:
    """
    Return a formatted date string for the candidate's CV/post date.
    Tries candidate_date first (DB field), then message_date (TG), then last_active_parsed.
    """
    for field in ("candidate_date", "message_date", "last_active_parsed"):
        val = candidate.get(field)
        if not val:
            continue
        if isinstance(val, str):
            try:
                val = datetime.fromisoformat(val.replace("Z", "+00:00"))
            except Exception:
                continue
        if isinstance(val, datetime):
            return val.strftime("%d.%m.%Y")
    return ""


def format_candidate_card(candidate: dict, index: int) -> str:
    try:
        score = candidate.get("score", 0)
        source = candidate.get("source", "unknown")
        source_em = SOURCE_EMOJI.get(source, "📋")
        source_label = SOURCE_LABEL.get(source, source)   # human-readable label
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

        is_fallback = candidate.get("is_fallback", False)
        fallback_round = candidate.get("fallback_round")  # 180 or 365

        name_line = full_name
        if age:
            name_line += f", {age} р."

        lines = [
            f"#{index} | ⭐ {score}/100 | {source_em} {source_label}",
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

        if source == "robota.ua-applies":
            # Contacts are known — show phone and email directly
            phone = candidate.get("phone") or ""
            email = candidate.get("email") or ""
            if phone:
                lines.append(f"📞 {phone}")
            if email:
                lines.append(f"📧 {email}")
            if not phone and not email:
                lines.append(f"📞 {contact or 'Контакт не вказано'}")
            if profile_url:
                lines.append(f"🔗 {profile_url}")
        elif source == "work.ua" and profile_url:
            # Merge contact + URL into a single clean clickable line
            lines.append(f"📞 [Контакт на Work.ua ↗]({profile_url})")
        else:
            lines.append(f"📞 {contact or 'Контакт не вказано'}")
            if profile_url:
                lines.append(f"🔗 {profile_url}")

        if summary:
            lines.append("")
            lines.append(summary)

        # Fallback archive label
        if is_fallback:
            cv_date = _format_candidate_date(candidate)
            date_suffix = f" від {cv_date}" if cv_date else ""
            if fallback_round == 365:
                lines.append(f"\n⏳ CV{date_suffix} (архів)")
            else:
                lines.append(f"\n⏳ CV{date_suffix}")

            round_label = FALLBACK_ROUND_LABELS.get(fallback_round)
            if round_label:
                lines.append(round_label)

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Card format error: {e}")
        return f"⚠️ Помилка форматування картки: {e}"
