def format_report_for_telegram(report: dict, agent_name: str, point_name: str) -> str:
    score = report.get("score", 0)
    passed = report.get("passed", False)
    errors = report.get("errors", [])
    share = report.get("shelf_share", {})
    elite = report.get("elite_shelf_check", {})

    status_icon = "✅" if passed else "❌"
    status_text = "ПРОЙДЕНО" if passed else "НЕ ПРОЙДЕНО"

    lines = [
        f"📊 *Звіт: {point_name}*",
        f"👤 {agent_name}",
        f"{status_icon} *{status_text} — {score}/100*",
        ""
    ]

    if errors:
        lines.append(f"❌ *Помилки ({len(errors)}):*")
        for e in errors:
            prefix = "🚫" if e.get("severity") == "auto_fail" else "⚠️"
            brand = f" ({e['brand']})" if e.get("brand") else ""
            lines.append(f"{prefix} {e['description']}{brand} `[{e['code']}]`")
        lines.append("")

    cat_names = {"vodka": "Горілка", "wine": "Вино", "cognac": "Коньяк", "sparkling": "Ігристе"}
    share_lines = []
    for cat, data in share.items():
        if data.get("total_facings", 0) > 0:
            icon = "✅" if data.get("passed") else "❌"
            share_lines.append(
                f"{icon} {cat_names.get(cat, cat)}: {data.get('percent', 0)}% "
                f"(норма ≥{data.get('threshold', 0)}%)"
            )
    if share_lines:
        lines.append("📈 *Доля полки:*")
        lines.extend(share_lines)
        lines.append("")

    if elite.get("elite_section_exists"):
        ev_icon = "✅" if elite.get("gd_evolution_on_top") else "❌"
        lines.append(f"{ev_icon} Evolution/Planet/Discovery на елітній полиці")

    if report.get("notes"):
        lines.append(f"\n💬 _{report['notes']}_")

    return "\n".join(lines)
