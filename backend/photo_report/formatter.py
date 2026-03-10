def format_report_for_telegram(report: dict, agent_name: str, point_name: str) -> str:
    score = report.get("score", 0)
    passed = report.get("passed", False)
    errors = report.get("errors", [])
    share = report.get("shelf_share", {})
    elite = report.get("elite_shelf_check", {})
    scored_cats = report.get("scored_categories", ["vodka"])
    info_cats = report.get("info_only_categories", ["wine", "cognac", "sparkling"])

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

    scored_lines = []
    for cat in scored_cats:
        data = share.get(cat, {})
        if data.get("total_facings", 0) > 0:
            icon = "✅" if data.get("passed") else "❌"
            scored_lines.append(
                f"{icon} {cat_names.get(cat, cat)}: {data.get('percent', 0)}% "
                f"(норма ≥{data.get('threshold', 0)}%)"
            )
    if scored_lines:
        lines.append("📈 *Доля полки (горілка):*")
        lines.extend(scored_lines)
        lines.append("")

    info_lines = []
    for cat in info_cats:
        data = share.get(cat, {})
        if data.get("total_facings", 0) > 0:
            info_lines.append(
                f"📊 {cat_names.get(cat, cat)}: {data.get('percent', 0)}% "
                f"(норма Phase 2 ≥{data.get('threshold', 0)}%)"
            )
    if info_lines:
        lines.append("📋 *Інфо (не впливає на оцінку):*")
        lines.extend(info_lines)
        lines.append("")

    if elite.get("elite_section_exists"):
        ev_icon = "✅" if elite.get("gd_evolution_on_top") else "❌"
        lines.append(f"{ev_icon} Evolution/Planet/Discovery на елітній полиці")

    if report.get("notes"):
        lines.append(f"\n💬 _{report['notes']}_")

    return "\n".join(lines)
